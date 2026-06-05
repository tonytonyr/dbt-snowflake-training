"""Entry point for the e-commerce simulator.

Modes:
  --bootstrap   Create schema and seed reference data from CSV files.
  --historical  Generate N months of compressed order history.
  --stream      Emit live orders at configurable real-time pace.
"""

import argparse
import logging
import random
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from simulator import load_config
from simulator.db import Database, get_database
from simulator.generator import (
    create_new_customer,
    generate_historical_orders,
    generate_order,
    pick_customer,
)
from simulator.state_machine import OrderState, PaymentState, StateMachine

logger = logging.getLogger(__name__)

MAX_NEW_CUSTOMER_RETRIES = 5

# Realistic per-transition delay windows (seconds).
# Order transitions drive the clock; payment events share the same timestamp.
_ORDER_DELAY: dict[tuple[str, str], tuple[float, float]] = {
    ("placed",    "confirmed"):   (0,       1_800),     # 0–30 min  (payment auth)
    ("placed",    "cancelled"):   (0,       3_600),     # 0–1 hr
    ("confirmed", "shipped"):     (3_600,   259_200),   # 1 hr–3 days (fulfillment)
    ("confirmed", "cancelled"):   (0,       86_400),    # 0–1 day
    ("shipped",   "delivered"):   (172_800, 604_800),   # 2–7 days (transit)
    ("shipped",   "returned"):    (172_800, 604_800),   # 2–7 days
    ("delivered", "returned"):    (86_400,  2_592_000), # 1–30 days (return window)
}


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


# ------------------------------------------------------------------
# Modes
# ------------------------------------------------------------------

def bootstrap_mode(db: Database) -> None:
    """Create schema and seed reference data from CSV files."""
    logger.info("Starting bootstrap mode")
    config = load_config()
    db.bootstrap_schema()
    db.seed_from_csv(config["bootstrap"]["csv_dir"])
    logger.info("Bootstrap completed successfully")


def historical_mode(db: Database, num_months: int) -> None:
    """Generate num_months of compressed order history.

    All lifecycle computation happens in memory first; a single bulk transaction
    writes everything to the database at the end.  This avoids the 400K
    per-order commits that made the previous approach slow.
    """
    logger.info("Starting historical mode: %d months", num_months)
    config = load_config()

    customers = db.load_customers()
    products = db.load_products()
    if not customers or not products:
        raise RuntimeError("No customers or products found — run --bootstrap first")

    end_date = datetime.now(UTC)
    start_date = end_date - timedelta(days=30 * num_months)

    orders, payments, items = generate_historical_orders(
        customers, products,
        config["simulation"]["num_orders"],
        start_date, end_date,
    )
    logger.info("Simulating lifecycles in memory for %d orders…", len(orders))

    lifecycle_results = [
        compute_order_lifecycle(order, payment, config)
        for order, payment in zip(orders, payments, strict=True)
    ]

    logger.info("Writing all data in a single bulk transaction…")
    db.bulk_insert_historical(
        orders,
        payments,
        items,
        lifecycle_results,
    )

    logger.info("Historical simulation completed: %d orders", len(orders))


def stream_mode(db: Database, duration_secs: float | None = None) -> None:
    """Emit live orders at real-time pace with new customer injection.

    Runs until interrupted or, when duration_secs is set, until that many
    wall-clock seconds have elapsed.
    """
    logger.info(
        "Starting stream mode%s",
        f" (duration={duration_secs}s)" if duration_secs is not None else "",
    )
    config = load_config()
    rate_max = config["simulation"]["new_customer_rate_max"]
    tick = config["simulation"]["tick_interval"]

    customers = db.load_customers()
    products = db.load_products()
    if not customers or not products:
        raise RuntimeError("No customers or products found — run --bootstrap first")

    deadline = time.monotonic() + duration_secs if duration_secs is not None else None

    while True:
        if deadline is not None and time.monotonic() >= deadline:
            logger.info("Stream duration elapsed — stopping")
            break
        customer, new_address = pick_customer(customers, rate_max)

        if new_address is not None:
            for _ in range(MAX_NEW_CUSTOMER_RETRIES):
                try:
                    db.insert_customer_with_address(customer, new_address)
                    customers.append(customer)
                    logger.debug("New customer injected: %s", customer["customer_id"])
                    break
                except Exception:  # noqa: BLE001
                    customer, new_address = create_new_customer()
            else:
                logger.warning(
                    "Skipping new customer after %d email collisions",
                    MAX_NEW_CUSTOMER_RETRIES,
                )
                customer = random.choice(customers)

        order, payment, order_items = generate_order(
            customer, products, datetime.now(UTC)
        )
        db.insert_order(order, payment, order_items)
        simulate_order_lifecycle(db, order, payment, config)

        time.sleep(tick)


# ------------------------------------------------------------------
# Lifecycle simulation
# ------------------------------------------------------------------

def compute_order_lifecycle(
    order: dict[str, Any],
    payment: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Pure function: drive an order through its state machine, return results.

    No database access — all output is returned as a dict so callers can
    accumulate results in memory and bulk-write later.
    """
    order_state = OrderState(order["order_state"])
    payment_state = PaymentState(payment["payment_state"])
    retry_count = 0
    max_retries = config["simulation"]["max_retries"]

    order_events: list[tuple[Any, ...]] = []
    payment_events: list[tuple[Any, ...]] = []

    order_date = datetime.fromisoformat(order["order_date"])
    current_time = order_date

    is_stuck = False
    stuck_reason: str | None = None

    while not StateMachine.is_terminal_order_state(order_state):
        next_order_state = StateMachine.attempt_order_transition(order_state)

        if next_order_state is None:
            if order_state == OrderState.SHIPPED:
                is_stuck = True
                stuck_reason = "system_error"
            break

        lo, hi = _ORDER_DELAY.get(
            (order_state.value, next_order_state.value), (0, 60)
        )
        current_time += timedelta(seconds=random.uniform(lo, hi))

        order_events.append((
            f"evt_{uuid.uuid4().hex[:12]}",
            order["order_id"],
            order_state.value,
            next_order_state.value,
            current_time,
            None,
            None,
        ))

        next_payment_state: PaymentState | None = None
        if next_order_state == OrderState.RETURNED:
            next_payment_state = PaymentState.REFUNDED
        elif not StateMachine.is_terminal_payment_state(payment_state, retry_count):
            next_payment_state = StateMachine.attempt_payment_transition(
                payment_state, retry_count
            )
            if next_payment_state == PaymentState.FAILED:
                retry_count = min(retry_count + 1, max_retries)

        if next_payment_state is not None:
            payment_events.append((
                f"evt_{uuid.uuid4().hex[:12]}",
                payment["payment_id"],
                payment_state.value,
                next_payment_state.value,
                current_time,
                "declined" if next_payment_state == PaymentState.FAILED else None,
                retry_count if next_payment_state == PaymentState.FAILED else None,
            ))
            payment_state = next_payment_state

        order_state = next_order_state

    return {
        "order_id":       order["order_id"],
        "order_state":    order_state.value,
        "is_stuck":       is_stuck,
        "stuck_reason":   stuck_reason,
        "payment_id":     payment["payment_id"],
        "payment_state":  payment_state.value,
        "retry_count":    retry_count,
        "order_events":   order_events,
        "payment_events": payment_events,
        "final_updated_at": current_time,
    }


def simulate_order_lifecycle(
    db: Database,
    order: dict[str, Any],
    payment: dict[str, Any],
    config: dict[str, Any],
) -> None:
    """Compute lifecycle and immediately persist — used by stream mode."""
    result = compute_order_lifecycle(order, payment, config)
    db.finalize_order(
        order_id=result["order_id"],
        order_state=result["order_state"],
        is_stuck=result["is_stuck"],
        stuck_reason=result["stuck_reason"],
        payment_id=result["payment_id"],
        payment_state=result["payment_state"],
        retry_count=result["retry_count"],
        order_events=result["order_events"],
        payment_events=result["payment_events"],
        final_updated_at=result["final_updated_at"],
    )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="E-commerce Simulator")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--bootstrap", action="store_true",
                       help="Create schema and seed reference data from CSV")
    group.add_argument("--historical", type=int, metavar="MONTHS",
                       help="Generate N months of order history")
    group.add_argument("--stream", action="store_true",
                       help="Emit live orders at real-time pace")
    parser.add_argument(
        "--duration", type=float, metavar="SECONDS",
        help="Stop stream mode after this many wall-clock seconds (default: infinite)",
    )
    args = parser.parse_args()

    try:
        with get_database() as db:
            if args.bootstrap:
                bootstrap_mode(db)
            elif args.historical:
                historical_mode(db, args.historical)
            elif args.stream:
                stream_mode(db, duration_secs=args.duration)
    except Exception as exc:
        logger.error("Simulation failed: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
