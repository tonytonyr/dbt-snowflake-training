"""Data generation for the e-commerce simulator.

Bootstrap data (customers, addresses, products) is loaded from CSV files.
This module handles runtime data: order generation and new customer injection.
"""

import bisect
import logging
import random
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from faker import Faker

from simulator.state_machine import OrderState, PaymentState

logger = logging.getLogger(__name__)
fake = Faker()

# ---------------------------------------------------------------------------
# Seasonal demand weights by month (1=Jan … 12=Dec).
# Early December (days 1–15) gets an extra holiday-shopping boost applied on
# top of the monthly base weight in _seasonal_weight().
# ---------------------------------------------------------------------------
_MONTHLY_WEIGHT: dict[int, float] = {
    1:  0.65,   # post-holiday slump
    2:  0.70,
    3:  0.90,
    4:  0.95,
    5:  1.00,
    6:  1.05,   # light summer lift
    7:  1.10,
    8:  1.05,
    9:  1.00,
    10: 1.10,   # pre-holiday ramp
    11: 1.80,   # Black Friday / Cyber Monday
    12: 2.50,   # Christmas shopping — early Dec gets extra multiplier below
}

# Zipf-like exponent for product popularity.
# alpha=0.8 → top ~20% of products take ~65% of order line volume.
_PRODUCT_POPULARITY_ALPHA = 0.8


def _seasonal_weight(dt: datetime) -> float:
    """Return a demand multiplier for a given datetime.

    December 1-15 (peak gift-buying window) gets a 1.5× bonus on top of the
    monthly base, tapering to 1.0× by Dec 31 (post-Christmas lull).
    """
    base = _MONTHLY_WEIGHT[dt.month]
    if dt.month == 12:
        if dt.day <= 15:
            base *= 1.5   # early Dec holiday rush
        elif dt.day <= 24:
            base *= 1.1   # last-minute shopping, slower
        else:
            base *= 0.6   # post-Christmas
    return base


def _sample_order_dates(
    start: datetime,
    end: datetime,
    n: int,
) -> list[datetime]:
    """Sample n order datetimes between start and end using seasonal weights.

    Builds a pool of candidate days, weights each by _seasonal_weight, then
    samples with replacement and adds a random intra-day offset.
    """
    days: list[datetime] = []
    weights: list[float] = []
    current = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while current < end:
        days.append(current)
        weights.append(_seasonal_weight(current))
        current += timedelta(days=1)

    if not days:
        return [start] * n

    chosen_days = random.choices(days, weights=weights, k=n)
    seconds_in_day = 86_400
    return [
        d + timedelta(seconds=random.randint(0, seconds_in_day - 1))
        for d in chosen_days
    ]


def _make_product_weights(products: list[dict[str, Any]]) -> list[float]:
    """Assign power-law popularity weights to products (shuffled ranking).

    Products are randomly ranked 1..N; weight = 1 / rank^alpha.
    This gives a long-tail distribution: a few bestsellers, many slow movers.
    """
    n = len(products)
    ranks = list(range(1, n + 1))
    random.shuffle(ranks)
    return [1.0 / (r ** _PRODUCT_POPULARITY_ALPHA) for r in ranks]


def generate_order(
    customer: dict[str, Any],
    products: list[dict[str, Any]],
    order_date: datetime,
    product_weights: list[float] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Generate a single order with items and payment for the given customer.

    Args:
        customer: Customer dict with customer_id and address_id.
        products: Full product catalogue.
        order_date: Exact timestamp for this order (caller controls date sampling).
        product_weights: Optional power-law weights for product selection.
            When None, falls back to uniform sampling (stream mode / tests).
    """
    num_items = random.randint(1, 5)

    if product_weights is not None:
        # Weighted sampling without replacement via repeated choices + dedup.
        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        attempts = 0
        while len(selected) < num_items and attempts < num_items * 10:
            pick = random.choices(products, weights=product_weights, k=1)[0]
            if pick["product_id"] not in seen:
                selected.append(pick)
                seen.add(pick["product_id"])
            attempts += 1
    else:
        selected = random.sample(products, k=min(num_items, len(products)))

    items = []
    subtotal = Decimal("0")
    for product in selected:
        quantity = random.randint(1, 3)
        unit_price = Decimal(str(product["price"]))
        total_price = round(unit_price * quantity, 2)
        subtotal += total_price
        items.append({
            "order_item_id": f"item_{uuid.uuid4().hex[:12]}",
            "order_id": None,
            "product_id": product["product_id"],
            "quantity": quantity,
            "unit_price": float(unit_price),
            "total_price": float(total_price),
        })

    tax = round(subtotal * Decimal("0.08"), 2)
    shipping_cost = round(Decimal(str(random.uniform(5.0, 20.0))), 2)
    total_amount = round(subtotal + tax + shipping_cost, 2)

    order_id = f"ord_{uuid.uuid4().hex[:12]}"
    order = {
        "order_id": order_id,
        "customer_id": customer["customer_id"],
        "order_state": OrderState.PLACED.value,
        "order_date": order_date.isoformat(),
        "first_event_at": order_date.isoformat(),
        "subtotal": float(subtotal),
        "tax": float(tax),
        "shipping_cost": float(shipping_cost),
        "total_amount": float(total_amount),
        "shipping_address_id": customer["address_id"],
        "is_stuck": False,
        "stuck_reason": None,
    }

    payment = {
        "payment_id": f"pay_{uuid.uuid4().hex[:12]}",
        "order_id": order_id,
        "payment_state": PaymentState.PENDING.value,
        "amount": float(total_amount),
        "payment_method": random.choice(["credit_card", "paypal", "debit_card"]),
        "payment_date": None,
        "authorization_date": None,
        "capture_date": None,
        "refund_date": None,
        "failure_reason": None,
        "retry_count": 0,
    }

    for item in items:
        item["order_id"] = order_id

    return order, payment, items


def generate_historical_orders(
    customers: list[dict[str, Any]],
    products: list[dict[str, Any]],
    num_orders: int,
    start_date: datetime,
    end_date: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Generate a batch of historical orders from existing customers and products.

    Order dates are sampled with seasonal weighting (December peaks, Jan/Feb
    slumps).  Product selection uses a power-law popularity distribution so a
    small number of products drive the majority of volume.

    Order dates are constrained to [max(start_date, customer.created_at), end_date]
    so no order is placed before the customer existed.  Customers whose created_at
    falls after end_date are excluded from selection.
    """
    if not customers:
        raise ValueError("customers list is empty — run bootstrap first")
    if not products:
        raise ValueError("products list is empty — run bootstrap first")

    # Pre-filter to customers who existed before end_date, sorted by created_at
    # so we can bisect to find those alive at any given order date.
    eligible = sorted(
        (c for c in customers if _as_utc(c["created_at"]) < end_date),
        key=lambda c: _as_utc(c["created_at"]),
    )
    if not eligible:
        raise ValueError(
            "No customers existed before end_date — check created_at values"
        )
    if len(eligible) < len(customers):
        logger.info(
            "Excluded %d customers whose created_at >= end_date",
            len(customers) - len(eligible),
        )

    # Sorted created_at list for O(log n) bisect lookups.
    eligible_created = [_as_utc(c["created_at"]) for c in eligible]

    # Pre-compute product popularity weights once for the whole batch.
    product_weights = _make_product_weights(products)

    # Pre-sample order dates with seasonal weighting.  For each date, pick a
    # customer who actually existed on that date (bisect on sorted eligible list).
    # This preserves the seasonal date distribution without date-shifting.
    order_dates = _sample_order_dates(start_date, end_date, num_orders)

    orders, payments, all_items = [], [], []
    skipped = 0
    for order_date in order_dates:
        order_date_utc = order_date.replace(tzinfo=UTC) if order_date.tzinfo is None else order_date
        # Find the slice of customers whose created_at <= order_date_utc.
        cutoff = bisect.bisect_right(eligible_created, order_date_utc)
        if cutoff == 0:
            skipped += 1
            continue
        customer = eligible[random.randrange(cutoff)]
        order, payment, items = generate_order(
            customer, products, order_date_utc, product_weights
        )
        orders.append(order)
        payments.append(payment)
        all_items.extend(items)

    if skipped:
        logger.info("Skipped %d order dates with no eligible customers yet", skipped)
    logger.info("Generated %d historical orders", len(orders))
    return orders, payments, all_items


def _as_utc(value: Any) -> datetime:  # noqa: ANN401
    """Coerce a date-like value to a timezone-aware UTC datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return datetime.fromisoformat(str(value)).replace(tzinfo=UTC)


def create_new_customer() -> tuple[dict[str, Any], dict[str, Any]]:
    """Generate a new customer and address for runtime injection (ADR-016).

    Returns (customer, address) — caller must INSERT both and handle
    IntegrityError on email uniqueness with a retry.
    """
    address_id = f"addr_{uuid.uuid4().hex[:12]}"
    address = {
        "address_id": address_id,
        "street_address": fake.street_address(),
        "city": fake.city(),
        "state": fake.state_abbr(),
        "postal_code": fake.zipcode(),
        "country": "US",
    }
    customer = {
        "customer_id": f"cust_{uuid.uuid4().hex[:12]}",
        "first_name": fake.first_name(),
        "last_name": fake.last_name(),
        "email": fake.email(),
        "address_id": address_id,
        "created_at": datetime.now(UTC).isoformat(),
    }
    return customer, address


def pick_customer(
    customers: list[dict[str, Any]],
    new_customer_rate_max: float,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Return (customer, address_or_None) for the next order.

    Draws a new-customer rate from Uniform(0, new_customer_rate_max) per
    order (ADR-016). Returns a fresh (customer, address) pair when a new
    customer is selected, otherwise picks from the existing pool.
    """
    if random.random() < random.uniform(0, new_customer_rate_max):
        customer, address = create_new_customer()
        return customer, address
    return random.choice(customers), None
