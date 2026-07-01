"""Database adapter for the e-commerce simulator.

Supports DuckDB (local/test) and Postgres (production) via a common interface.
DuckDB is the default — no server required, ideal for development and testing.
"""

import csv
import logging
import os
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any

logger = logging.getLogger(__name__)

_DDL = [
    # addresses first — customers FK references it
    """
    CREATE TABLE IF NOT EXISTS addresses (
        address_id   TEXT PRIMARY KEY,
        street_address TEXT NOT NULL,
        city         TEXT NOT NULL,
        state        TEXT NOT NULL,
        postal_code  TEXT NOT NULL,
        country      TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS customers (
        customer_id TEXT PRIMARY KEY,
        first_name  TEXT NOT NULL,
        last_name   TEXT NOT NULL,
        email       TEXT UNIQUE NOT NULL,
        address_id  TEXT NOT NULL,
        created_at  TIMESTAMP WITH TIME ZONE NOT NULL,
        FOREIGN KEY (address_id) REFERENCES addresses(address_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS products (
        product_id TEXT PRIMARY KEY,
        sku        TEXT UNIQUE NOT NULL,
        name       TEXT NOT NULL,
        price      NUMERIC(12, 2) NOT NULL,
        cost_price NUMERIC(12, 2) NOT NULL,
        category   TEXT NOT NULL
    )
    """,
"""
    CREATE TABLE IF NOT EXISTS orders (
        order_id           TEXT PRIMARY KEY,
        customer_id        TEXT NOT NULL,
        order_state        TEXT NOT NULL,
        order_date         TIMESTAMP WITH TIME ZONE NOT NULL,
        first_event_at    TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at         TIMESTAMP WITH TIME ZONE NOT NULL,
        subtotal           NUMERIC(12, 2) NOT NULL,
        tax                NUMERIC(12, 2) NOT NULL,
        shipping_cost      NUMERIC(12, 2) NOT NULL,
        total_amount       NUMERIC(12, 2) NOT NULL,
        shipping_address_id TEXT NOT NULL,
        is_stuck           BOOLEAN DEFAULT FALSE,
        stuck_reason       TEXT,
        FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
        FOREIGN KEY (shipping_address_id) REFERENCES addresses(address_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS payments (
        payment_id         TEXT PRIMARY KEY,
        order_id           TEXT NOT NULL,
        payment_state      TEXT NOT NULL,
        amount             NUMERIC(12, 2) NOT NULL,
        payment_method     TEXT NOT NULL,
        payment_date       TIMESTAMP WITH TIME ZONE,
        authorization_date TIMESTAMP WITH TIME ZONE,
        capture_date       TIMESTAMP WITH TIME ZONE,
        refund_date        TIMESTAMP WITH TIME ZONE,
        failure_reason     TEXT,
        retry_count        INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (order_id) REFERENCES orders(order_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS order_items (
        order_item_id TEXT PRIMARY KEY,
        order_id      TEXT NOT NULL,
        product_id    TEXT NOT NULL,
        quantity      INTEGER NOT NULL,
        unit_price    NUMERIC(12, 2) NOT NULL,
        total_price   NUMERIC(12, 2) NOT NULL,
        FOREIGN KEY (order_id) REFERENCES orders(order_id),
        FOREIGN KEY (product_id) REFERENCES products(product_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS order_events (
        event_id        TEXT PRIMARY KEY,
        order_id        TEXT NOT NULL,
        previous_state  TEXT,
        new_state       TEXT NOT NULL,
        event_timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
        reason          TEXT,
        retry_count     INTEGER,
        FOREIGN KEY (order_id) REFERENCES orders(order_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS payment_events (
        event_id        TEXT PRIMARY KEY,
        payment_id      TEXT NOT NULL,
        previous_state  TEXT,
        new_state       TEXT NOT NULL,
        event_timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
        failure_reason  TEXT,
        retry_attempt   INTEGER,
        FOREIGN KEY (payment_id) REFERENCES payments(payment_id)
    )
    """,
]


class Database:
    """Database adapter supporting DuckDB and Postgres."""

    def __init__(self, db_type: str, **kwargs: Any) -> None:  # noqa: ANN401
        self._db_type = db_type
        if db_type == "duckdb":
            import duckdb
            self._conn = duckdb.connect(kwargs.get("path", "simulator.duckdb"))
            self._pool = None
        elif db_type == "postgres":
            from psycopg2 import pool as pg_pool
            self._conn = None
            self._pool = pg_pool.ThreadedConnectionPool(
                minconn=1, maxconn=10, dsn=kwargs["dsn"]
            )
        else:
            raise ValueError(f"Unsupported db_type: {db_type!r}")

    @contextmanager
    def _get_conn(self) -> Generator:
        if self._db_type == "duckdb":
            yield self._conn
        else:
            conn = self._pool.getconn()
            try:
                yield conn
            except Exception:
                # Without this, a failed statement leaves the connection in an
                # aborted-transaction state, and it gets handed to the next
                # borrower still broken — every statement on it fails with
                # "current transaction is aborted" until something rolls it back.
                # Invisible against DuckDB (single connection, no pool).
                conn.rollback()
                raise
            finally:
                self._pool.putconn(conn)

    def _adapt(self, sql: str) -> str:
        if self._db_type == "duckdb":
            return sql.replace("%s", "?")
        return sql

    def _bulk_insert(
        self,
        cursor: Any,  # noqa: ANN401
        table: str,
        columns: list[str],
        rows: list[tuple[Any, ...]],
    ) -> None:
        if not rows:
            return
        if self._db_type == "duckdb":
            self._duckdb_fast_insert(cursor, table, columns, rows, on_conflict=True)
        else:
            from psycopg2.extras import execute_values
            cols = ", ".join(columns)
            sql = f"INSERT INTO {table} ({cols}) VALUES %s ON CONFLICT DO NOTHING"
            execute_values(cursor, sql, rows)

    def _insert_batch(
        self,
        cursor: Any,  # noqa: ANN401
        table: str,
        columns: list[str],
        rows: list[tuple[Any, ...]],
    ) -> None:
        if not rows:
            return
        if self._db_type == "duckdb":
            self._duckdb_fast_insert(cursor, table, columns, rows, on_conflict=False)
        else:
            from psycopg2.extras import execute_values
            cols = ", ".join(columns)
            sql = f"INSERT INTO {table} ({cols}) VALUES %s"
            execute_values(cursor, sql, rows)

    def _duckdb_fast_insert(
        self,
        conn: Any,  # noqa: ANN401
        table: str,
        columns: list[str],
        rows: list[tuple[Any, ...]],
        *,
        on_conflict: bool = False,
    ) -> None:
        """Fast DuckDB bulk insert via pandas DataFrame zero-copy path.

        DuckDB can reference a local DataFrame variable directly in SQL, which
        is orders of magnitude faster than executemany with row-by-row binding.
        """
        import pandas as pd
        df = pd.DataFrame(rows, columns=columns)
        cols = ", ".join(columns)
        conflict_clause = " ON CONFLICT DO NOTHING" if on_conflict else ""
        conn.execute(
            f"INSERT INTO {table} ({cols}) SELECT {cols} FROM df{conflict_clause}"
        )

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def bootstrap_schema(self) -> None:
        """Create all tables (idempotent)."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            try:
                for ddl in _DDL:
                    cursor.execute(ddl)
                conn.commit()
            finally:
                cursor.close()
        logger.info("Schema bootstrapped successfully")
        if self._db_type == "postgres":
            self._ensure_publication()

    def _ensure_publication(self, name: str = "dbz_publication") -> None:
        """Create the Debezium publication if it doesn't already exist.

        Postgres has no `CREATE PUBLICATION IF NOT EXISTS` — existence is checked
        against pg_publication first. Watches orders, order_items, payments: the
        three tables Phase 4b's Debezium connector subscribes to (SPEC.md Phase 4
        erratum — no `returns` table exists in this schema). REPLICA IDENTITY
        DEFAULT (the Postgres default) is sufficient here — this schema has no
        hard DELETEs anywhere in this module, so Debezium never needs a full
        before-image for a tombstone.
        """
        with self._get_conn() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT 1 FROM pg_publication WHERE pubname = %s", (name,)
                )
                if cursor.fetchone() is None:
                    cursor.execute(
                        f"CREATE PUBLICATION {name} FOR TABLE "
                        "orders, order_items, payments"
                    )
                    logger.info("Created publication %s", name)
                conn.commit()
            finally:
                cursor.close()

    # ------------------------------------------------------------------
    # Seeding
    # ------------------------------------------------------------------

    def seed_from_csv(self, csv_dir: str) -> None:
        """Load addresses, customers, and products from CSV files."""
        base = Path(csv_dir).resolve()
        with self._get_conn() as conn:
            if self._db_type == "duckdb":
                self._seed_from_csv_duckdb(conn, base)
            else:
                self._seed_from_csv_postgres(conn, base)

    def _seed_from_csv_duckdb(self, conn: Any, base: Path) -> None:  # noqa: ANN401
        """Use DuckDB native read_csv for fast bulk loading (seconds vs minutes)."""
        tables = [
            ("addresses", base / "addresses.csv",
             "address_id, street_address, city, state, postal_code, country"),
            ("customers", base / "customers.csv",
             "customer_id, first_name, last_name, email, address_id, created_at"),
            ("products",  base / "products.csv",
             "product_id, sku, name, category, price, cost_price"),
        ]
        cursor = conn.cursor()
        try:
            for table, path, cols in tables:
                cursor.execute(
                    f"INSERT OR IGNORE INTO {table} ({cols})"
                    f" SELECT {cols} FROM read_csv_auto('{path}', header=true)"
                )
                n = cursor.fetchone()
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                logger.info("Seeded %d rows into %s", count, table)
            conn.commit()
        finally:
            cursor.close()

    def _seed_from_csv_postgres(self, conn: Any, base: Path) -> None:  # noqa: ANN401
        """Row-by-row fallback for Postgres (no native read_csv_auto)."""
        cursor = conn.cursor()
        try:
            _ADDR_COLS = ["address_id", "street_address", "city", "state", "postal_code", "country"]
            addr_rows = _read_csv(base / "addresses.csv", _ADDR_COLS)
            self._bulk_insert(cursor, "addresses", _ADDR_COLS, addr_rows)
            logger.info("Seeded %d addresses", len(addr_rows))

            _CUST_COLS = ["customer_id", "first_name", "last_name", "email", "address_id", "created_at"]
            cust_rows = _read_csv(base / "customers.csv", _CUST_COLS)
            self._bulk_insert(cursor, "customers", _CUST_COLS, cust_rows)
            logger.info("Seeded %d customers", len(cust_rows))

            prod_rows = _read_csv(base / "products.csv",
                                  ["product_id", "sku", "name", "category", "price", "cost_price"])
            self._bulk_insert(cursor, "products",
                              ["product_id", "sku", "name", "category", "price", "cost_price"],
                              prod_rows)
            logger.info("Seeded %d products", len(prod_rows))
            conn.commit()
        finally:
            cursor.close()

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def load_customers(self) -> list[dict[str, Any]]:
        """Return all customers as lightweight dicts for order generation."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT customer_id, address_id, created_at FROM customers"
                )
                return [
                    {
                        "customer_id": r[0],
                        "address_id": r[1],
                        "created_at": r[2] if isinstance(r[2], datetime)
                                      else datetime.fromisoformat(str(r[2])),
                    }
                    for r in cursor.fetchall()
                ]
            finally:
                cursor.close()

    def load_products(self) -> list[dict[str, Any]]:
        """Return all products as lightweight dicts for order generation."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT product_id, price FROM products")
                return [
                    {"product_id": r[0], "price": float(r[1])}
                    for r in cursor.fetchall()
                ]
            finally:
                cursor.close()

    # ------------------------------------------------------------------
    # Order writes
    # ------------------------------------------------------------------

    def insert_order(
        self,
        order: dict[str, Any],
        payment: dict[str, Any],
        items: list[dict[str, Any]],
    ) -> None:
        """Insert an order, payment, and line items in one transaction."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    self._adapt(
                        "INSERT INTO orders ("
                         "order_id, customer_id, order_state, order_date, first_event_at, updated_at,"
                         " subtotal, tax, shipping_cost, total_amount,"
                         " shipping_address_id, is_stuck, stuck_reason"

                         ") VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                    ),
                    (
                        order["order_id"], order["customer_id"],
                        order["order_state"], order["order_date"],
                         order.get("first_event_at", order["order_date"]), order.get("updated_at", order["order_date"]), order["subtotal"],
                        order["tax"], order["shipping_cost"],
                        order["total_amount"], order["shipping_address_id"],
                        order["is_stuck"], order["stuck_reason"],
                    ),
                )
                cursor.execute(
                    self._adapt(
                        "INSERT INTO payments ("
                        "payment_id, order_id, payment_state, amount, payment_method,"
                        " payment_date, authorization_date, capture_date,"
                        " refund_date, failure_reason, retry_count"
                        ") VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                    ),
                    (
                        payment["payment_id"], payment["order_id"],
                        payment["payment_state"], payment["amount"],
                        payment["payment_method"],
                        payment.get("payment_date"),
                        payment.get("authorization_date"),
                        payment.get("capture_date"),
                        payment.get("refund_date"),
                        payment.get("failure_reason"),
                        payment["retry_count"],
                    ),
                )
                self._insert_batch(
                    cursor, "order_items",
                    ["order_item_id", "order_id", "product_id",
                     "quantity", "unit_price", "total_price"],
                    [
                        (i["order_item_id"], i["order_id"], i["product_id"],
                         i["quantity"], i["unit_price"], i["total_price"])
                        for i in items
                    ],
                )
                conn.commit()
            finally:
                cursor.close()

    def finalize_order(
        self,
        order_id: str,
        order_state: str,
        is_stuck: bool,
        stuck_reason: str | None,
        payment_id: str,
        payment_state: str,
        retry_count: int,
        order_events: list[tuple[Any, ...]],
        payment_events: list[tuple[Any, ...]],
        final_updated_at: datetime | None = None,
    ) -> None:
        """Write final states and all lifecycle events in one transaction."""
        updated_at = final_updated_at or datetime.now(UTC)
        with self._get_conn() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    self._adapt(
                        "UPDATE orders SET order_state = %s, is_stuck = %s,"
                        " stuck_reason = %s, updated_at = %s"
                        " WHERE order_id = %s"
                    ),
                    (order_state, is_stuck, stuck_reason, updated_at, order_id),
                )
                cursor.execute(
                    self._adapt(
                        "UPDATE payments SET payment_state = %s, retry_count = %s "
                        "WHERE payment_id = %s"
                    ),
                    (payment_state, retry_count, payment_id),
                )
                self._insert_batch(
                    cursor, "order_events",
                    ["event_id", "order_id", "previous_state", "new_state",
                     "event_timestamp", "reason", "retry_count"],
                    order_events,
                )
                self._insert_batch(
                    cursor, "payment_events",
                    ["event_id", "payment_id", "previous_state", "new_state",
                     "event_timestamp", "failure_reason", "retry_attempt"],
                    payment_events,
                )
                conn.commit()
            finally:
                cursor.close()

    def apply_order_transition(
        self,
        order_id: str,
        order_state: str,
        is_stuck: bool,
        stuck_reason: str | None,
        updated_at: datetime,
        order_event: tuple[Any, ...] | None,
        payment_id: str | None = None,
        payment_state: str | None = None,
        retry_count: int | None = None,
        payment_event: tuple[Any, ...] | None = None,
    ) -> None:
        """Apply one lifecycle step — an order state change and, usually, a paired
        payment state change — plus its event row(s), as a single small transaction.

        This is the ADR-019 "drip" write: stream_mode calls this once per queued
        transition, spaced out over real wall-clock time, in contrast to
        finalize_order's all-at-once write of an order's entire remaining lifecycle
        (still used by the historical/bulk path).
        """
        with self._get_conn() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    self._adapt(
                        "UPDATE orders SET order_state = %s, is_stuck = %s,"
                        " stuck_reason = %s, updated_at = %s WHERE order_id = %s"
                    ),
                    (order_state, is_stuck, stuck_reason, updated_at, order_id),
                )
                if order_event is not None:
                    self._insert_batch(
                        cursor, "order_events",
                        ["event_id", "order_id", "previous_state", "new_state",
                         "event_timestamp", "reason", "retry_count"],
                        [order_event],
                    )
                if payment_id is not None:
                    cursor.execute(
                        self._adapt(
                            "UPDATE payments SET payment_state = %s,"
                            " retry_count = %s WHERE payment_id = %s"
                        ),
                        (payment_state, retry_count, payment_id),
                    )
                if payment_event is not None:
                    self._insert_batch(
                        cursor, "payment_events",
                        ["event_id", "payment_id", "previous_state", "new_state",
                         "event_timestamp", "failure_reason", "retry_attempt"],
                        [payment_event],
                    )
                conn.commit()
            finally:
                cursor.close()

    def bulk_insert_historical(
        self,
        orders: list[dict[str, Any]],
        payments: list[dict[str, Any]],
        items: list[dict[str, Any]],
        lifecycle_results: list[dict[str, Any]],
        chunk_size: int = 10_000,
    ) -> None:
        """Write historical data in chunks, one transaction per chunk.

        Single-transaction writes of 1M+ rows cause DuckDB to buffer everything
        in memory and hold the WAL open for minutes. Chunking at 10K orders
        keeps peak memory low, gives visible progress, and is still ~40x faster
        than the old per-order commit approach.
        """
        # Build item lookup keyed by order_id for fast per-chunk slicing.
        items_by_order_id: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            items_by_order_id.setdefault(item["order_id"], []).append(item)

        total = len(orders)
        committed = 0

        for chunk_start in range(0, total, chunk_size):
            chunk_end = min(chunk_start + chunk_size, total)
            o_chunk = orders[chunk_start:chunk_end]
            p_chunk = payments[chunk_start:chunk_end]
            r_chunk = lifecycle_results[chunk_start:chunk_end]

            order_rows = [
                (
                    o["order_id"], o["customer_id"],
                    r["order_state"],
                    o["order_date"],
                    o["order_date"],
                    r["final_updated_at"].isoformat()
                    if hasattr(r["final_updated_at"], "isoformat")
                    else r["final_updated_at"],
                    o["subtotal"], o["tax"], o["shipping_cost"], o["total_amount"],
                    o["shipping_address_id"],
                    r["is_stuck"], r["stuck_reason"],
                )
                for o, r in zip(o_chunk, r_chunk, strict=True)
            ]

            payment_rows = [
                (
                    p["payment_id"], p["order_id"],
                    r["payment_state"],
                    p["amount"], p["payment_method"],
                    p.get("payment_date"), p.get("authorization_date"),
                    p.get("capture_date"), p.get("refund_date"),
                    p.get("failure_reason"),
                    r["retry_count"],
                )
                for p, r in zip(p_chunk, r_chunk, strict=True)
            ]

            item_rows = [
                (i["order_item_id"], i["order_id"], i["product_id"],
                 i["quantity"], i["unit_price"], i["total_price"])
                for o in o_chunk
                for i in items_by_order_id.get(o["order_id"], [])
            ]

            order_event_rows: list[tuple[Any, ...]] = [
                evt for r in r_chunk for evt in r["order_events"]
            ]
            payment_event_rows: list[tuple[Any, ...]] = [
                evt for r in r_chunk for evt in r["payment_events"]
            ]

            with self._get_conn() as conn:
                cursor = conn.cursor()
                try:
                    self._insert_batch(
                        cursor, "orders",
                         ["order_id", "customer_id", "order_state", "order_date",
                          "first_event_at", "updated_at", "subtotal", "tax", "shipping_cost",
                          "total_amount", "shipping_address_id", "is_stuck", "stuck_reason"],
                        order_rows,
                    )
                    self._insert_batch(
                        cursor, "payments",
                        ["payment_id", "order_id", "payment_state", "amount",
                         "payment_method", "payment_date", "authorization_date",
                         "capture_date", "refund_date", "failure_reason", "retry_count"],
                        payment_rows,
                    )
                    self._insert_batch(
                        cursor, "order_items",
                        ["order_item_id", "order_id", "product_id",
                         "quantity", "unit_price", "total_price"],
                        item_rows,
                    )
                    self._insert_batch(
                        cursor, "order_events",
                        ["event_id", "order_id", "previous_state", "new_state",
                         "event_timestamp", "reason", "retry_count"],
                        order_event_rows,
                    )
                    self._insert_batch(
                        cursor, "payment_events",
                        ["event_id", "payment_id", "previous_state", "new_state",
                         "event_timestamp", "failure_reason", "retry_attempt"],
                        payment_event_rows,
                    )
                    conn.commit()
                finally:
                    cursor.close()

            committed += len(o_chunk)
            logger.info(
                "Chunk committed: %d/%d orders (%.0f%%)",
                committed, total, committed / total * 100,
            )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        if self._db_type == "duckdb" and self._conn:
            self._conn.close()
        elif self._pool:
            self._pool.closeall()

    def __enter__(self) -> "Database":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _read_csv(path: Path, columns: list[str]) -> list[tuple[Any, ...]]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [tuple(row[col] for col in columns) for row in reader]


def get_database(config: dict[str, Any] | None = None) -> Database:
    from simulator import load_config
    if config is None:
        config = load_config()
    db_cfg = config.get("database", {})
    # SIMULATOR_DB_TYPE lets an operator point at Postgres for a Phase 4 CDC
    # session without editing the checked-in config.yaml default (which stays
    # duckdb — Phase 1-3 local dev is unaffected; see SPEC.md Phase 4a).
    db_type = os.environ.get("SIMULATOR_DB_TYPE", db_cfg.get("type", "duckdb"))
    if db_type == "duckdb":
        return Database("duckdb", path=db_cfg.get("path", "simulator.duckdb"))
    dsn = db_cfg.get("dsn") or os.environ.get("DATABASE_URL", "")
    if not dsn:
        raise ValueError("database.dsn or DATABASE_URL env var required for postgres")
    return Database("postgres", dsn=dsn)
