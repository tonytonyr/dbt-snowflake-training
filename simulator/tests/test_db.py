"""Tests for simulator/db.py using in-memory DuckDB."""

import pytest

from simulator.db import Database


@pytest.fixture
def db() -> Database:
    database = Database("duckdb", path=":memory:")
    database.bootstrap_schema()
    return database


@pytest.fixture
def seeded_db(db: Database, tmp_path: pytest.TempPathFactory) -> Database:
    """DuckDB with minimal CSV seed data."""
    addr = tmp_path / "addresses.csv"
    addr.write_text(
        "address_id,street_address,city,state,postal_code,country\n"
        "addr_001,123 Main St,Boston,MA,02108,US\n"
        "addr_002,456 Oak Ave,Austin,TX,78701,US\n"
    )
    cust = tmp_path / "customers.csv"
    cust.write_text(
        "customer_id,first_name,last_name,email,address_id,created_at\n"
        "cust_001,Jane,Doe,jane@example.com,addr_001,2024-01-01T00:00:00+00:00\n"
        "cust_002,John,Smith,john@example.com,addr_002,2024-02-01T00:00:00+00:00\n"
    )
    prod = tmp_path / "products.csv"
    prod.write_text(
        "product_id,sku,name,category,price,cost_price\n"
        "prod_001,SKU-001,Widget A,Electronics,29.99,15.00\n"
        "prod_002,SKU-002,Widget B,Electronics,49.99,25.00\n"
    )
    db.seed_from_csv(str(tmp_path))
    return db


class TestBootstrapSchema:
    def test_creates_all_tables(self, db: Database) -> None:
        cursor = db._conn.cursor()
        cursor.execute("SHOW TABLES")
        tables = {row[0] for row in cursor.fetchall()}
        expected = {
            "addresses", "customers", "products", "orders", "payments",
            "order_items", "order_events", "payment_events",
        }
        assert expected == tables

    def test_idempotent(self, db: Database) -> None:
        db.bootstrap_schema()
        db.bootstrap_schema()


class TestSeedFromCsv:
    def test_loads_all_tables(self, seeded_db: Database) -> None:
        customers = seeded_db.load_customers()
        products = seeded_db.load_products()
        assert len(customers) == 2
        assert len(products) == 2

    def test_customer_has_address_id(self, seeded_db: Database) -> None:
        customers = seeded_db.load_customers()
        assert all("address_id" in c for c in customers)

    def test_customer_has_created_at(self, seeded_db: Database) -> None:
        from datetime import datetime
        customers = seeded_db.load_customers()
        for c in customers:
            assert "created_at" in c
            assert isinstance(c["created_at"], datetime)
            assert c["created_at"].tzinfo is not None

    def test_idempotent(
        self, seeded_db: Database, tmp_path: pytest.TempPathFactory
    ) -> None:
        seeded_db.seed_from_csv(str(tmp_path))


class TestInsertOrder:
    def test_inserts_order_payment_items(self, seeded_db: Database) -> None:
        customers = seeded_db.load_customers()
        customer = customers[0]
        order = {
            "order_id": "ord_test001",
            "customer_id": customer["customer_id"],
            "order_state": "placed",
            "order_date": "2024-06-01T10:00:00+00:00",
            "updated_at": "2024-06-01T10:00:00+00:00",
            "subtotal": 29.99,
            "tax": 2.40,
            "shipping_cost": 5.00,
            "total_amount": 37.39,
            "shipping_address_id": customer["address_id"],
            "is_stuck": False,
            "stuck_reason": None,
        }
        payment = {
            "payment_id": "pay_test001",
            "order_id": "ord_test001",
            "payment_state": "pending",
            "amount": 37.39,
            "payment_method": "credit_card",
            "payment_date": None,
            "authorization_date": None,
            "capture_date": None,
            "refund_date": None,
            "failure_reason": None,
            "retry_count": 0,
        }
        items = [{
            "order_item_id": "item_test001",
            "order_id": "ord_test001",
            "product_id": "prod_001",
            "quantity": 1,
            "unit_price": 29.99,
            "total_price": 29.99,
        }]
        seeded_db.insert_order(order, payment, items)

        cursor = seeded_db._conn.cursor()
        cursor.execute("SELECT order_id FROM orders WHERE order_id = 'ord_test001'")
        assert cursor.fetchone() is not None


class TestFinalizeOrder:
    def test_updates_states_and_writes_events(self, seeded_db: Database) -> None:
        customers = seeded_db.load_customers()
        customer = customers[0]
        order = {
            "order_id": "ord_fin001",
            "customer_id": customer["customer_id"],
            "order_state": "placed",
            "order_date": "2024-06-01T10:00:00+00:00",
            "updated_at": "2024-06-01T10:00:00+00:00",
            "subtotal": 10.0, "tax": 0.8, "shipping_cost": 5.0, "total_amount": 15.8,
            "shipping_address_id": customer["address_id"],
            "is_stuck": False, "stuck_reason": None,
        }
        payment = {
            "payment_id": "pay_fin001", "order_id": "ord_fin001",
            "payment_state": "pending", "amount": 15.8, "payment_method": "credit_card",
            "payment_date": None, "authorization_date": None, "capture_date": None,
            "refund_date": None, "failure_reason": None, "retry_count": 0,
        }
        seeded_db.insert_order(order, payment, [])

        from datetime import UTC, datetime
        now = datetime.now(UTC)
        seeded_db.finalize_order(
            order_id="ord_fin001",
            order_state="delivered",
            is_stuck=False,
            stuck_reason=None,
            payment_id="pay_fin001",
            payment_state="captured",
            retry_count=0,
            order_events=[
                ("evt_001", "ord_fin001", "placed", "confirmed", now, None, None)
            ],
            payment_events=[
                ("evt_002", "pay_fin001", "pending", "authorized", now, None, None)
            ],
        )

        cursor = seeded_db._conn.cursor()
        cursor.execute(
            "SELECT order_state FROM orders WHERE order_id = 'ord_fin001'"
        )
        assert cursor.fetchone()[0] == "delivered"

        cursor.execute(
            "SELECT COUNT(*) FROM order_events WHERE order_id = 'ord_fin001'"
        )
        assert cursor.fetchone()[0] == 1

        cursor.execute(
            "SELECT COUNT(*) FROM payment_events WHERE payment_id = 'pay_fin001'"
        )
        assert cursor.fetchone()[0] == 1
