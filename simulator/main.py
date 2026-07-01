"""Entry point for the e-commerce simulator.

Modes:
  --bootstrap   Create schema and seed reference data from CSV files.
  --historical  Generate N months of compressed order history.
  --stream      Emit live orders at configurable real-time pace.
"""

import argparse
import bisect
import heapq
import itertools
import logging
import random
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from simulator import load_config
from simulator.db import Database, get_database
from simulator.generator import generate_historical_orders, generate_order
from simulator.state_machine import OrderState, PaymentState, StateMachine

logger = logging.getLogger(__name__)

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


@dataclass
class PendingTransition:
    """One scheduled lifecycle step, fired at a real wall-clock time (ADR-019).

    `to_order_state` is the state this transition lands on when it fires — rolled
    at schedule time, not at fire time, mirroring compute_order_lifecycle's
    one-roll-per-step behavior. `payment_state`/`retry_count` are the values as of
    scheduling; `_fire_transition` computes what they become when this fires.
    """

    order_id: str
    payment_id: str
    from_order_state: OrderState
    to_order_state: OrderState
    payment_state: PaymentState
    retry_count: int
    fire_at: float  # time.monotonic() seconds


class SimClock:
    """Wall-clock time advanced at `compression_ratio` (ADR-019).

    Used only to decide which pre-generated customers are eligible yet
    (`created_at <= sim_clock.now()`, per ADR-018) — event timestamps written to
    the database are real wall-clock time, since that's what a live CDC consumer
    actually observes.
    """

    def __init__(self, compression_ratio: float) -> None:
        self._ratio = compression_ratio
        self._start_real = time.monotonic()
        self._start_sim = datetime.now(UTC)

    def now(self) -> datetime:
        elapsed_real = time.monotonic() - self._start_real
        return self._start_sim + timedelta(seconds=elapsed_real * self._ratio)


def _schedule_next(
    order_id: str,
    payment_id: str,
    from_state: OrderState,
    payment_state: PaymentState,
    retry_count: int,
    compression_ratio: float,
) -> PendingTransition | None:
    """Roll the next transition out of `from_state` and schedule it.

    Returns None if `from_state` has no further transition — either a genuine
    stuck order (only possible from SHIPPED) or DELIVERED settling with no
    return (the common case, ~97% of the time). Callers distinguish the two by
    checking `from_state` themselves; this function only reports "nothing to
    schedule."
    """
    next_state = StateMachine.attempt_order_transition(from_state)
    if next_state is None:
        return None
    lo, hi = _ORDER_DELAY.get((from_state.value, next_state.value), (0, 60))
    delay = random.uniform(lo, hi)
    fire_at = time.monotonic() + delay / compression_ratio
    return PendingTransition(
        order_id=order_id,
        payment_id=payment_id,
        from_order_state=from_state,
        to_order_state=next_state,
        payment_state=payment_state,
        retry_count=retry_count,
        fire_at=fire_at,
    )


def _fire_transition(
    db: Database,
    transition: PendingTransition,
    max_retries: int,
    compression_ratio: float,
) -> PendingTransition | None:
    """Apply one queued lifecycle step and schedule what comes next, if anything."""
    now = datetime.now(UTC)
    to_state = transition.to_order_state
    payment_state = transition.payment_state
    retry_count = transition.retry_count

    order_event = (
        f"evt_{uuid.uuid4().hex[:12]}",
        transition.order_id,
        transition.from_order_state.value,
        to_state.value,
        now,
        None,
        None,
    )

    next_payment_state: PaymentState | None = None
    if to_state == OrderState.RETURNED:
        next_payment_state = PaymentState.REFUNDED
    elif not StateMachine.is_terminal_payment_state(payment_state, retry_count):
        next_payment_state = StateMachine.attempt_payment_transition(
            payment_state, retry_count
        )
        if next_payment_state == PaymentState.FAILED:
            retry_count = min(retry_count + 1, max_retries)

    payment_event = None
    if next_payment_state is not None:
        payment_event = (
            f"evt_{uuid.uuid4().hex[:12]}",
            transition.payment_id,
            payment_state.value,
            next_payment_state.value,
            now,
            "declined" if next_payment_state == PaymentState.FAILED else None,
            retry_count if next_payment_state == PaymentState.FAILED else None,
        )

    db.apply_order_transition(
        order_id=transition.order_id,
        order_state=to_state.value,
        is_stuck=False,
        stuck_reason=None,
        updated_at=now,
        order_event=order_event,
        payment_id=transition.payment_id if next_payment_state is not None else None,
        payment_state=(
            next_payment_state.value if next_payment_state is not None else None
        ),
        retry_count=retry_count if next_payment_state is not None else None,
        payment_event=payment_event,
    )

    if StateMachine.is_terminal_order_state(to_state):
        return None

    effective_payment_state = next_payment_state or payment_state
    next_pending = _schedule_next(
        transition.order_id, transition.payment_id, to_state,
        effective_payment_state, retry_count, compression_ratio,
    )

    if next_pending is None and to_state == OrderState.SHIPPED:
        # attempt_order_transition(SHIPPED) returned None — the rare (1%) stuck
        # case, as opposed to DELIVERED settling with no further transition.
        db.apply_order_transition(
            order_id=transition.order_id,
            order_state=to_state.value,
            is_stuck=True,
            stuck_reason="system_error",
            updated_at=datetime.now(UTC),
            order_event=None,
        )

    return next_pending


def stream_mode(db: Database, duration_secs: float | None = None) -> None:
    """Emit live orders at real-time pace with a pending-transitions queue (ADR-019).

    Each order's lifecycle drips out as discrete, spaced-out state UPDATEs over
    real wall-clock time (scaled by `stream.compression_ratio`) instead of landing
    all at once — this is what makes stream mode a realistic CDC source. New
    customers are never injected at runtime; the eligible pool grows as
    pre-generated `created_at` dates are crossed (ADR-018).

    Runs until interrupted or, when duration_secs is set, until that many
    wall-clock seconds have elapsed.
    """
    logger.info(
        "Starting stream mode%s",
        f" (duration={duration_secs}s)" if duration_secs is not None else "",
    )
    config = load_config()
    tick = config["simulation"]["tick_interval"]
    max_retries = config["simulation"]["max_retries"]
    compression_ratio = config["stream"]["compression_ratio"]

    customers = db.load_customers()
    products = db.load_products()
    if not customers or not products:
        raise RuntimeError("No customers or products found — run --bootstrap first")

    eligible = sorted(customers, key=lambda c: c["created_at"])
    eligible_created = [c["created_at"] for c in eligible]

    sim_clock = SimClock(compression_ratio)
    pending: list[tuple[float, int, PendingTransition]] = []
    counter = itertools.count()

    deadline = time.monotonic() + duration_secs if duration_secs is not None else None

    while True:
        if deadline is not None and time.monotonic() >= deadline:
            logger.info("Stream duration elapsed — stopping")
            break

        cutoff = bisect.bisect_right(eligible_created, sim_clock.now())
        if cutoff > 0:
            customer = eligible[random.randrange(cutoff)]
            order, payment, order_items = generate_order(
                customer, products, datetime.now(UTC)
            )
            db.insert_order(order, payment, order_items)

            first = _schedule_next(
                order["order_id"], payment["payment_id"],
                OrderState.PLACED, PaymentState.PENDING, 0, compression_ratio,
            )
            if first is not None:
                heapq.heappush(pending, (first.fire_at, next(counter), first))
        else:
            logger.debug("No eligible customers yet at sim time %s", sim_clock.now())

        now_real = time.monotonic()
        while pending and pending[0][0] <= now_real:
            _, _, due = heapq.heappop(pending)
            next_transition = _fire_transition(
                db, due, max_retries, compression_ratio
            )
            if next_transition is not None:
                heapq.heappush(
                    pending, (next_transition.fire_at, next(counter), next_transition)
                )

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
    """Compute an order's entire remaining lifecycle and persist it in one write.

    Historical/bulk-path helper. Stream mode no longer uses this (ADR-019) — it
    schedules and applies one transition at a time via `_schedule_next` /
    `_fire_transition` instead, so state changes drip out over real time.
    """
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
