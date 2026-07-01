"""Integration tests for simulator/db.py against a real Postgres server.

Postgres has been a code path in db.py since Phase 1 but was never actually
exercised until Phase 4a stood up a live instance (docker-compose.yml). This
module runs the same kinds of assertions as test_db.py, but against Postgres
instead of in-memory DuckDB, using a dedicated `retail_test` database so it
never touches the `retail` database seeded with the Phase 4 lesson's demo data.

Skips automatically if no Postgres is reachable — run locally with the Phase
4.0 stack up:
    docker compose up -d postgres
    pytest simulator/tests/test_db_postgres.py
"""

import os
import uuid
from datetime import UTC, datetime

import psycopg2
import pytest

from simulator.db import Database

_ADMIN_DSN = os.environ.get(
    "TEST_POSTGRES_ADMIN_DSN", "postgresql://retail:changeme@localhost:5432/retail"
)
_TEST_DB_NAME = "retail_test"


def _test_dsn() -> str:
    return _ADMIN_DSN.rsplit("/", 1)[0] + f"/{_TEST_DB_NAME}"


@pytest.fixture(scope="module", autouse=True)
def _ensure_test_database() -> None:
    """Create a dedicated retail_test database (idempotent — Postgres has no
    CREATE DATABASE IF NOT EXISTS) so these tests never touch the demo dataset
    seeded into `retail` for the Phase 4 lesson."""
    try:
        conn = psycopg2.connect(_ADMIN_DSN, connect_timeout=3)
    except psycopg2.OperationalError:
        pytest.skip(
            f"No Postgres reachable at {_ADMIN_DSN} — start the Phase 4.0 stack "
            "(docker compose up -d postgres) to run this module"
        )
    conn.autocommit = True
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (_TEST_DB_NAME,)
        )
        if cursor.fetchone() is None:
            cursor.execute(f"CREATE DATABASE {_TEST_DB_NAME}")
        cursor.close()
    finally:
        conn.close()


@pytest.fixture
def db() -> Database:
    database = Database("postgres", dsn=_test_dsn())
    database.bootstrap_schema()
    return database


class TestPostgresBootstrap:
    def test_creates_publication(self, db: Database) -> None:
        with db._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM pg_publication WHERE pubname = 'dbz_publication'"
            )
            assert cursor.fetchone() is not None

    def test_idempotent(self, db: Database) -> None:
        db.bootstrap_schema()  # must not raise on rerun


class TestPostgresConnRollback:
    def test_failed_statement_does_not_poison_pool(self, db: Database) -> None:
        """Regression test for the _get_conn rollback bug fixed in Phase 4a: a
        failed statement must not leave a pooled connection in an
        aborted-transaction state for the next borrower."""
        with (  # noqa: PT012
            pytest.raises(Exception, match="does_not_exist"),  # noqa: PT011
            db._get_conn() as conn,
        ):
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM this_table_does_not_exist")

        # A poisoned connection would fail this with "current transaction is
        # aborted, commands ignored until end of transaction block".
        with db._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            assert cursor.fetchone() == (1,)


class TestPostgresOrderWrites:
    def test_insert_order_and_apply_transition(self, db: Database) -> None:
        address = {
            "address_id": f"addr_{uuid.uuid4().hex[:12]}",
            "street_address": "1 Test St", "city": "Testville",
            "state": "CA", "postal_code": "00000", "country": "US",
        }
        customer = {
            "customer_id": f"cust_{uuid.uuid4().hex[:12]}",
            "first_name": "Test", "last_name": "User",
            "email": f"{uuid.uuid4().hex[:8]}@example.com",
            "address_id": address["address_id"], "created_at": datetime.now(UTC),
        }
        with db._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO addresses (address_id, street_address, city,"
                " state, postal_code, country) VALUES (%s,%s,%s,%s,%s,%s)",
                tuple(address.values()),
            )
            cursor.execute(
                "INSERT INTO customers (customer_id, first_name, last_name,"
                " email, address_id, created_at) VALUES (%s,%s,%s,%s,%s,%s)",
                tuple(customer.values()),
            )
            conn.commit()

        order_id = f"ord_{uuid.uuid4().hex[:12]}"
        payment_id = f"pay_{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC)
        order = {
            "order_id": order_id, "customer_id": customer["customer_id"],
            "order_state": "placed", "order_date": now.isoformat(),
            "first_event_at": now.isoformat(), "updated_at": now.isoformat(),
            "subtotal": 10.0, "tax": 0.8, "shipping_cost": 5.0,
            "total_amount": 15.8, "shipping_address_id": address["address_id"],
            "is_stuck": False, "stuck_reason": None,
        }
        payment = {
            "payment_id": payment_id, "order_id": order_id,
            "payment_state": "pending", "amount": 15.8,
            "payment_method": "credit_card", "payment_date": None,
            "authorization_date": None, "capture_date": None,
            "refund_date": None, "failure_reason": None, "retry_count": 0,
        }
        db.insert_order(order, payment, [])
        db.apply_order_transition(
            order_id=order_id, order_state="confirmed", is_stuck=False,
            stuck_reason=None, updated_at=datetime.now(UTC),
            order_event=(
                f"evt_{uuid.uuid4().hex[:12]}", order_id, "placed",
                "confirmed", datetime.now(UTC), None, None,
            ),
            payment_id=payment_id, payment_state="authorized", retry_count=0,
            payment_event=(
                f"evt_{uuid.uuid4().hex[:12]}", payment_id, "pending",
                "authorized", datetime.now(UTC), None, None,
            ),
        )

        with db._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT order_state FROM orders WHERE order_id = %s", (order_id,)
            )
            assert cursor.fetchone()[0] == "confirmed"
            cursor.execute(
                "SELECT payment_state FROM payments WHERE payment_id = %s",
                (payment_id,),
            )
            assert cursor.fetchone()[0] == "authorized"
            cursor.execute(
                "SELECT COUNT(*) FROM order_events WHERE order_id = %s", (order_id,)
            )
            assert cursor.fetchone()[0] == 1
            cursor.execute(
                "SELECT COUNT(*) FROM payment_events WHERE payment_id = %s",
                (payment_id,),
            )
            assert cursor.fetchone()[0] == 1
