"""Tests for simulator/generator.py."""

import math
from datetime import UTC, datetime
from typing import Any

import pytest

from simulator.generator import (
    create_new_customer,
    generate_historical_orders,
    generate_order,
    pick_customer,
)


@pytest.fixture
def customers() -> list[dict]:
    return [
        {
            "customer_id": "cust_001",
            "address_id": "addr_001",
            "created_at": datetime(2023, 1, 1, tzinfo=UTC),
        },
        {
            "customer_id": "cust_002",
            "address_id": "addr_002",
            "created_at": datetime(2023, 6, 1, tzinfo=UTC),
        },
    ]


@pytest.fixture
def products() -> list[dict]:
    return [
        {"product_id": "prod_001", "price": 19.99},
        {"product_id": "prod_002", "price": 49.99},
        {"product_id": "prod_003", "price": 9.99},
        {"product_id": "prod_004", "price": 99.99},
        {"product_id": "prod_005", "price": 29.99},
    ]


@pytest.fixture
def date_range() -> tuple[datetime, datetime]:
    return datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 6, 30, tzinfo=UTC)


class TestGenerateOrder:
    def test_returns_order_payment_items(
        self,
        customers: list[dict[str, Any]],
        products: list[dict[str, Any]],
        date_range: tuple[datetime, datetime],
    ) -> None:
        order, payment, items = generate_order(customers[0], products, date_range[0])
        assert order["customer_id"] == "cust_001"
        assert order["shipping_address_id"] == "addr_001"
        assert order["order_state"] == "placed"
        assert len(items) >= 1

    def test_totals_are_consistent(
        self,
        customers: list[dict[str, Any]],
        products: list[dict[str, Any]],
        date_range: tuple[datetime, datetime],
    ) -> None:
        order, payment, _ = generate_order(customers[0], products, date_range[0])
        expected = round(order["subtotal"] + order["tax"] + order["shipping_cost"], 2)
        assert math.isclose(order["total_amount"], expected, rel_tol=1e-4)
        assert math.isclose(payment["amount"], order["total_amount"], rel_tol=1e-4)

    def test_items_reference_order_id(
        self,
        customers: list[dict[str, Any]],
        products: list[dict[str, Any]],
        date_range: tuple[datetime, datetime],
    ) -> None:
        order, _, items = generate_order(customers[0], products, date_range[0])
        assert all(item["order_id"] == order["order_id"] for item in items)

    def test_payment_references_order(
        self,
        customers: list[dict[str, Any]],
        products: list[dict[str, Any]],
        date_range: tuple[datetime, datetime],
    ) -> None:
        order, payment, _ = generate_order(customers[0], products, date_range[0])
        assert payment["order_id"] == order["order_id"]
        assert payment["payment_state"] == "pending"
        assert payment["retry_count"] == 0


class TestGenerateHistoricalOrders:
    def test_returns_correct_count(
        self,
        customers: list[dict[str, Any]],
        products: list[dict[str, Any]],
        date_range: tuple[datetime, datetime],
    ) -> None:
        orders, payments, items = generate_historical_orders(
            customers, products, 10, *date_range
        )
        assert len(orders) == 10
        assert len(payments) == 10
        assert len(items) >= 10

    def test_raises_on_empty_customers(
        self,
        products: list[dict[str, Any]],
        date_range: tuple[datetime, datetime],
    ) -> None:
        with pytest.raises(ValueError, match="customers list is empty"):
            generate_historical_orders([], products, 5, *date_range)

    def test_raises_on_empty_products(
        self,
        customers: list[dict[str, Any]],
        products: list[dict[str, Any]],
        date_range: tuple[datetime, datetime],
    ) -> None:
        with pytest.raises(ValueError, match="products list is empty"):
            generate_historical_orders(customers, [], 5, *date_range)

    def test_order_date_not_before_customer_created_at(
        self,
        products: list[dict[str, Any]],
    ) -> None:
        # customer_b joined 3 months into the window — orders must not predate that
        window_start = datetime(2024, 1, 1, tzinfo=UTC)
        window_end = datetime(2024, 12, 31, tzinfo=UTC)
        customer_b_created = datetime(2024, 4, 1, tzinfo=UTC)
        customers = [
            {
                "customer_id": "cust_a",
                "address_id": "addr_a",
                "created_at": datetime(2023, 1, 1, tzinfo=UTC),
            },
            {
                "customer_id": "cust_b",
                "address_id": "addr_b",
                "created_at": customer_b_created,
            },
        ]
        orders, _, _ = generate_historical_orders(
            customers, products, 50, window_start, window_end
        )
        for order in orders:
            order_date = datetime.fromisoformat(order["order_date"])
            if order["customer_id"] == "cust_b":
                assert order_date >= customer_b_created, (
                    f"cust_b order at {order_date} predates customer creation "
                    f"{customer_b_created}"
                )

    def test_excludes_customers_created_after_end_date(
        self,
        products: list[dict[str, Any]],
    ) -> None:
        window_start = datetime(2024, 1, 1, tzinfo=UTC)
        window_end = datetime(2024, 6, 30, tzinfo=UTC)
        customers = [
            {
                "customer_id": "cust_early",
                "address_id": "addr_a",
                "created_at": datetime(2023, 1, 1, tzinfo=UTC),
            },
            {
                "customer_id": "cust_future",
                "address_id": "addr_b",
                "created_at": datetime(2025, 1, 1, tzinfo=UTC),  # after window
            },
        ]
        orders, _, _ = generate_historical_orders(
            customers, products, 20, window_start, window_end
        )
        for order in orders:
            assert order["customer_id"] != "cust_future", (
                "future customer should not appear in historical orders"
            )

    def test_raises_when_all_customers_are_future(
        self,
        products: list[dict[str, Any]],
    ) -> None:
        window_start = datetime(2023, 1, 1, tzinfo=UTC)
        window_end = datetime(2023, 6, 30, tzinfo=UTC)
        customers = [
            {
                "customer_id": "cust_future",
                "address_id": "addr_a",
                "created_at": datetime(2025, 1, 1, tzinfo=UTC),
            },
        ]
        with pytest.raises(ValueError, match="No customers existed before end_date"):
            generate_historical_orders(customers, products, 5, window_start, window_end)


class TestCreateNewCustomer:
    def test_returns_customer_and_address(self) -> None:
        customer, address = create_new_customer()
        assert customer["customer_id"].startswith("cust_")
        assert customer["address_id"] == address["address_id"]
        assert address["country"] == "US"
        assert "@" in customer["email"]

    def test_unique_ids(self) -> None:
        c1, a1 = create_new_customer()
        c2, a2 = create_new_customer()
        assert c1["customer_id"] != c2["customer_id"]
        assert a1["address_id"] != a2["address_id"]


class TestPickCustomer:
    def test_returns_existing_at_zero_rate(
        self, customers: list[dict[str, Any]]
    ) -> None:
        for _ in range(20):
            customer, address = pick_customer(customers, new_customer_rate_max=0.0)
            assert address is None
            assert customer in customers

    def test_returns_new_at_max_rate(
        self, customers: list[dict[str, Any]]
    ) -> None:
        new_count = sum(
            1 for _ in range(100)
            if pick_customer(customers, new_customer_rate_max=1.0)[1] is not None
        )
        assert new_count > 0
