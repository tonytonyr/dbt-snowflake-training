"""Integration tests for simulator/main.py using in-memory DuckDB."""

import logging
import time
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from simulator.db import Database
from simulator.main import (
    bootstrap_mode,
    historical_mode,
    simulate_order_lifecycle,
    stream_mode,
)


@pytest.fixture(autouse=True)
def disable_logging() -> None:
    logging.getLogger("simulator.main").setLevel(logging.WARNING)


@pytest.fixture
def db(tmp_path: pytest.TempPathFactory) -> Database:
    """In-memory DuckDB with minimal seed data loaded from temp CSVs."""
    (tmp_path / "addresses.csv").write_text(
        "address_id,street_address,city,state,postal_code,country\n"
        + "\n".join(
            f"addr_{i:03d},123 Main St,Boston,MA,02108,US" for i in range(5)
        )
    )
    (tmp_path / "customers.csv").write_text(
        "customer_id,first_name,last_name,email,address_id,created_at\n"
        + "\n".join(
            f"cust_{i:03d},First{i},Last{i},user{i}@example.com,addr_{i:03d},2024-01-01T00:00:00+00:00"
            for i in range(5)
        )
    )
    (tmp_path / "products.csv").write_text(
        "product_id,sku,name,category,price,cost_price\n"
        + "\n".join(
            f"prod_{i:03d},SKU-{i:03d},Product {i},Electronics,{10 + i}.99,{5 + i}.00"
            for i in range(5)
        )
    )

    database = Database("duckdb", path=":memory:")
    database.bootstrap_schema()

    with patch("simulator.main.load_config", return_value={
        "bootstrap": {"csv_dir": str(tmp_path)},
        "simulation": {"num_orders": 10, "max_retries": 3,
                       "tick_interval": 0, "new_customer_rate_max": 0.10},
    }):
        bootstrap_mode(database)

    return database


class TestBootstrapMode:
    def test_seeds_all_tables(self, db: Database) -> None:
        assert len(db.load_customers()) == 5
        assert len(db.load_products()) == 5

    def test_idempotent(self, db: Database, tmp_path: pytest.TempPathFactory) -> None:
        with patch("simulator.main.load_config", return_value={
            "bootstrap": {"csv_dir": str(tmp_path)},
            "simulation": {},
        }):
            bootstrap_mode(db)


class TestHistoricalMode:
    def test_generates_orders(self, db: Database) -> None:
        with patch("simulator.main.load_config", return_value={
            "simulation": {"num_orders": 5, "max_retries": 3,
                           "tick_interval": 0, "new_customer_rate_max": 0.10},
        }):
            historical_mode(db, num_months=1)

        cursor = db._conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM orders")
        assert cursor.fetchone()[0] == 5

    def test_creates_events(self, db: Database) -> None:
        with patch("simulator.main.load_config", return_value={
            "simulation": {"num_orders": 3, "max_retries": 3,
                           "tick_interval": 0, "new_customer_rate_max": 0.10},
        }):
            historical_mode(db, num_months=1)

        cursor = db._conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM order_events")
        assert cursor.fetchone()[0] > 0

    def test_raises_without_bootstrap(self) -> None:
        empty_db = Database("duckdb", path=":memory:")
        empty_db.bootstrap_schema()
        cfg = {"simulation": {
            "num_orders": 5, "max_retries": 3,
            "tick_interval": 0, "new_customer_rate_max": 0.10,
        }}
        with (
            patch("simulator.main.load_config", return_value=cfg),
            pytest.raises(RuntimeError, match="run --bootstrap first"),
        ):
            historical_mode(empty_db, num_months=1)


class TestSimulateOrderLifecycle:
    def test_finalizes_order(self, db: Database) -> None:
        customer = db.load_customers()[0]

        order = {
            "order_id": "ord_lifecycle001",
            "customer_id": customer["customer_id"],
            "order_state": "placed",
            "order_date": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "subtotal": 19.99,
            "tax": 1.60,
            "shipping_cost": 5.00,
            "total_amount": 26.59,
            "shipping_address_id": customer["address_id"],
            "is_stuck": False,
            "stuck_reason": None,
        }
        payment = {
            "payment_id": "pay_lifecycle001",
            "order_id": "ord_lifecycle001",
            "payment_state": "pending",
            "amount": 26.59,
            "payment_method": "credit_card",
            "payment_date": None,
            "authorization_date": None,
            "capture_date": None,
            "refund_date": None,
            "failure_reason": None,
            "retry_count": 0,
        }
        db.insert_order(order, payment, [])

        config = {"simulation": {"max_retries": 3}}
        simulate_order_lifecycle(db, order, payment, config)

        cursor = db._conn.cursor()
        cursor.execute(
            "SELECT order_state FROM orders WHERE order_id = 'ord_lifecycle001'"
        )
        final_state = cursor.fetchone()[0]
        valid = ("confirmed", "cancelled", "shipped", "delivered", "returned")
        assert final_state in valid


class TestEventTimestamps:
    def test_events_after_order_date(self, db: Database) -> None:
        customer = db.load_customers()[0]
        order_date = datetime(2024, 1, 1, tzinfo=UTC)
        order = {
            "order_id": "ord_ts001",
            "customer_id": customer["customer_id"],
            "order_state": "placed",
            "order_date": order_date.isoformat(),
            "updated_at": order_date.isoformat(),
            "subtotal": 19.99, "tax": 1.60, "shipping_cost": 5.00,
            "total_amount": 26.59,
            "shipping_address_id": customer["address_id"],
            "is_stuck": False, "stuck_reason": None,
        }
        payment = {
            "payment_id": "pay_ts001", "order_id": "ord_ts001",
            "payment_state": "pending", "amount": 26.59,
            "payment_method": "credit_card",
            "payment_date": None, "authorization_date": None,
            "capture_date": None, "refund_date": None,
            "failure_reason": None, "retry_count": 0,
        }
        db.insert_order(order, payment, [])
        config = {"simulation": {"max_retries": 3}}
        simulate_order_lifecycle(db, order, payment, config)

        cursor = db._conn.cursor()
        cursor.execute(
            "SELECT event_timestamp FROM order_events WHERE order_id = 'ord_ts001'"
            " ORDER BY event_timestamp"
        )
        rows = cursor.fetchall()
        assert len(rows) > 0
        for (ts,) in rows:
            assert ts >= order_date, (
                f"event timestamp {ts} is before order_date {order_date}"
            )

    def test_events_are_monotonically_increasing(self, db: Database) -> None:
        customer = db.load_customers()[0]
        order_date = datetime(2024, 1, 1, tzinfo=UTC)
        order = {
            "order_id": "ord_ts002",
            "customer_id": customer["customer_id"],
            "order_state": "placed",
            "order_date": order_date.isoformat(),
            "updated_at": order_date.isoformat(),
            "subtotal": 19.99, "tax": 1.60, "shipping_cost": 5.00,
            "total_amount": 26.59,
            "shipping_address_id": customer["address_id"],
            "is_stuck": False, "stuck_reason": None,
        }
        payment = {
            "payment_id": "pay_ts002", "order_id": "ord_ts002",
            "payment_state": "pending", "amount": 26.59,
            "payment_method": "credit_card",
            "payment_date": None, "authorization_date": None,
            "capture_date": None, "refund_date": None,
            "failure_reason": None, "retry_count": 0,
        }
        db.insert_order(order, payment, [])
        config = {"simulation": {"max_retries": 3}}
        simulate_order_lifecycle(db, order, payment, config)

        cursor = db._conn.cursor()
        cursor.execute(
            "SELECT event_timestamp FROM order_events WHERE order_id = 'ord_ts002'"
            " ORDER BY event_timestamp"
        )
        timestamps = [row[0] for row in cursor.fetchall()]
        for i in range(1, len(timestamps)):
            assert timestamps[i] >= timestamps[i - 1], (
                f"timestamps not monotonic: {timestamps[i - 1]} > {timestamps[i]}"
            )

    def test_orders_updated_at_reflects_final_event(self, db: Database) -> None:
        customer = db.load_customers()[0]
        order_date = datetime(2024, 1, 1, tzinfo=UTC)
        order = {
            "order_id": "ord_ts003",
            "customer_id": customer["customer_id"],
            "order_state": "placed",
            "order_date": order_date.isoformat(),
            "updated_at": order_date.isoformat(),
            "subtotal": 19.99, "tax": 1.60, "shipping_cost": 5.00,
            "total_amount": 26.59,
            "shipping_address_id": customer["address_id"],
            "is_stuck": False, "stuck_reason": None,
        }
        payment = {
            "payment_id": "pay_ts003", "order_id": "ord_ts003",
            "payment_state": "pending", "amount": 26.59,
            "payment_method": "credit_card",
            "payment_date": None, "authorization_date": None,
            "capture_date": None, "refund_date": None,
            "failure_reason": None, "retry_count": 0,
        }
        db.insert_order(order, payment, [])
        config = {"simulation": {"max_retries": 3}}
        simulate_order_lifecycle(db, order, payment, config)

        cursor = db._conn.cursor()
        cursor.execute(
            "SELECT updated_at FROM orders WHERE order_id = 'ord_ts003'"
        )
        updated_at = cursor.fetchone()[0]
        assert updated_at >= order_date, (
            f"orders.updated_at {updated_at} should be >= order_date {order_date}"
        )


class TestStreamDuration:
    def test_stream_exits_after_duration(self, db: Database) -> None:
        cfg = {
            "simulation": {
                "num_orders": 1000, "max_retries": 3,
                "tick_interval": 0, "new_customer_rate_max": 0.0,
            },
        }
        start = time.monotonic()
        with patch("simulator.main.load_config", return_value=cfg):
            stream_mode(db, duration_secs=0.5)
        elapsed = time.monotonic() - start
        assert elapsed >= 0.5
        assert elapsed < 5.0, f"stream took too long to stop: {elapsed:.1f}s"

    def test_stream_inserts_orders(self, db: Database) -> None:
        cfg = {
            "simulation": {
                "num_orders": 1000, "max_retries": 3,
                "tick_interval": 0, "new_customer_rate_max": 0.0,
            },
        }
        with patch("simulator.main.load_config", return_value=cfg):
            stream_mode(db, duration_secs=0.2)

        cursor = db._conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM orders")
        assert cursor.fetchone()[0] > 0


class TestCLI:
    @patch("simulator.main.bootstrap_mode")
    def test_cli_bootstrap_mode(self, mock_bootstrap: MagicMock) -> None:
        with (
            patch("sys.argv", ["main.py", "--bootstrap"]),
            patch("simulator.main.get_database") as mock_get_db,
        ):
            mock_db = mock_get_db.return_value.__enter__.return_value
            import simulator.main
            simulator.main.main()
            mock_bootstrap.assert_called_once_with(mock_db)

    @patch("simulator.main.historical_mode")
    def test_cli_historical_mode(self, mock_historical: MagicMock) -> None:
        with (
            patch("sys.argv", ["main.py", "--historical", "3"]),
            patch("simulator.main.get_database") as mock_get_db,
        ):
            mock_db = mock_get_db.return_value.__enter__.return_value
            import simulator.main
            simulator.main.main()
            mock_historical.assert_called_once_with(mock_db, 3)

    @patch("simulator.main.stream_mode")
    def test_cli_stream_mode(self, mock_stream: MagicMock) -> None:
        with (
            patch("sys.argv", ["main.py", "--stream"]),
            patch("simulator.main.get_database") as mock_get_db,
        ):
            mock_db = mock_get_db.return_value.__enter__.return_value
            import simulator.main
            simulator.main.main()
            mock_stream.assert_called_once_with(mock_db, duration_secs=None)

    @patch("simulator.main.stream_mode")
    def test_cli_stream_duration(self, mock_stream: MagicMock) -> None:
        with (
            patch("sys.argv", ["main.py", "--stream", "--duration", "30"]),
            patch("simulator.main.get_database") as mock_get_db,
        ):
            mock_db = mock_get_db.return_value.__enter__.return_value
            import simulator.main
            simulator.main.main()
            mock_stream.assert_called_once_with(mock_db, duration_secs=30.0)
