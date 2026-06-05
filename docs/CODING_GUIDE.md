# Coding Guide

Authoritative coding standards for this project. All agents read this file
before writing any Python or SQL. These rules are enforced by pre-commit hooks
— code that fails the hooks will not be merged.

**Scope:** Python (`simulator/`) and SQL (Postgres DDL + dbt models).
**Snowflake SQL** for dbt models uses the same SQL rules unless noted.

---

## Python

### Toolchain

| Tool | Purpose | Config |
|------|---------|--------|
| Ruff | Lint + format | `pyproject.toml` `[tool.ruff]` |
| pytest | Test runner | `pyproject.toml` `[tool.pytest]` |
| pre-commit | Hook runner | `.pre-commit-config.yaml` |

Run locally:
```bash
ruff check simulator/          # lint
ruff format --check simulator/ # format check
ruff format simulator/         # apply format
pytest simulator/tests/        # run tests
```

---

### Style

**Line length:** 88 characters (Ruff default).

**Imports:** stdlib → third-party → local, each group separated by a blank
line. Never use wildcard imports (`from x import *`).

```python
# CORRECT
import random
from datetime import datetime, timezone
from enum import Enum

import psycopg2

from simulator.state_machine import OrderState
```

**String quotes:** Double quotes. Ruff enforces this.

**Trailing commas:** Always on multi-line collections and function signatures.
Ruff enforces this.

```python
# CORRECT
TERMINAL_STATES = {
    OrderState.RETURNED,
    OrderState.CANCELLED,
    OrderState.CAPTURED,
}

# WRONG — missing trailing comma
TERMINAL_STATES = {
    OrderState.RETURNED,
    OrderState.CANCELLED,
    OrderState.CAPTURED
}
```

---

### Type Hints

**Required** on every public function and method signature. Use the `|` union
syntax (Python 3.10+). Never use `Optional[X]` — write `X | None`.

```python
# CORRECT
def apply_transition(
    order_id: str,
    current_state: OrderState,
    event: str,
) -> OrderState | None:
    ...

# WRONG — no type hints
def apply_transition(order_id, current_state, event):
    ...

# WRONG — old Optional syntax
from typing import Optional
def apply_transition(...) -> Optional[OrderState]:
    ...
```

Return type is always annotated. If a function never returns, annotate `-> None`.

Private/internal helpers (single leading underscore) may omit type hints if
the types are obvious from context, but annotating them is preferred.

---

### Naming

| Thing | Convention | Example |
|-------|-----------|---------|
| Module | `snake_case` | `state_machine.py` |
| Class | `PascalCase` | `OrderStateMachine` |
| Enum | `PascalCase`, members `UPPER_SNAKE` | `OrderState.PLACED` |
| Function / method | `snake_case` | `apply_transition()` |
| Variable | `snake_case` | `retry_count` |
| Constant (module-level) | `UPPER_SNAKE_CASE` | `MAX_RETRIES = 3` |
| Private attribute/method | `_single_leading_underscore` | `_validate_transition()` |

Never use single-letter variable names except for loop counters (`i`, `j`) or
coordinates. `order` not `o`, `payment` not `p`.

---

### Enums for State

All state values **must** be defined as `Enum` members. Never compare against
raw strings.

```python
# CORRECT
from enum import Enum

class OrderState(Enum):
    PLACED = "placed"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    RETURNED = "returned"

if state == OrderState.PLACED:
    ...

# WRONG — raw string comparison
if state == "placed":
    ...
```

---

### Error Handling

Only catch exceptions you can handle. Never silently swallow exceptions.
Never use bare `except:`.

```python
# CORRECT
try:
    conn = psycopg2.connect(dsn)
except psycopg2.OperationalError as exc:
    logger.error("DB connection failed: %s", exc)
    raise

# WRONG — bare except
try:
    conn = psycopg2.connect(dsn)
except:
    pass

# WRONG — catching too broadly
try:
    conn = psycopg2.connect(dsn)
except Exception:
    pass
```

Raise `ValueError` for invalid arguments. Raise custom exceptions (subclass
`Exception`) for domain errors (e.g., `InvalidTransitionError`).

---

### Logging

Use the standard `logging` module. Never use `print()` for runtime output.
Module-level logger only — do not pass loggers as arguments.

```python
# CORRECT
import logging

logger = logging.getLogger(__name__)

def apply_transition(...) -> OrderState | None:
    logger.debug("Attempting transition: %s -> %s", current_state, event)
    ...
    logger.info("Transition applied: order=%s state=%s", order_id, new_state)

# WRONG
print(f"Transitioning order {order_id}")
```

Log format: `%(asctime)s %(name)s %(levelname)s %(message)s`. Configured once
at the entry point (`simulator/main.py`), not in library modules.

---

### Comments and Docstrings

Default: **no comments**. Names should be self-documenting.

Add a comment only when the **why** is non-obvious: a hidden constraint, a
probability derived from the spec, a Postgres-specific workaround.

```python
# CORRECT — explains a non-obvious constraint from the spec
# After 3 retries, failed payments become terminal regardless of retry probability.
if payment.retry_count >= MAX_RETRIES:
    return PaymentState.FAILED

# WRONG — restates what the code already says
# Check if retry count is at max
if payment.retry_count >= MAX_RETRIES:
    return PaymentState.FAILED
```

Public classes get a one-line docstring describing **what** the class
represents, not how it works.

```python
class OrderStateMachine:
    """Models valid order lifecycle transitions and their probabilities."""
```

Public functions do **not** need docstrings if the name and type hints are
sufficient. Add a docstring only when the behavior has a non-obvious
constraint.

---

### Testing

One test file per source module: `simulator/state_machine.py` →
`simulator/tests/test_state_machine.py`.

Test function naming: `test_<thing_being_tested>_<condition>`.

```python
# CORRECT
def test_apply_transition_placed_to_confirmed() -> None: ...
def test_apply_transition_delivered_is_not_terminal() -> None: ...
def test_payment_failed_becomes_terminal_after_max_retries() -> None: ...

# WRONG
def test_transitions() -> None: ...
def test_1() -> None: ...
```

Every public function that contains branching logic needs at minimum:
- One test for the happy path
- One test per error/edge branch

Use `pytest.mark.parametrize` for probability/state matrix tests rather than
copy-pasting similar test functions.

Do not mock the database in integration tests — use a real Postgres connection
pointed at a test schema. Unit tests for pure logic (no I/O) need no
database.

---

### File and Module Structure

```
simulator/
  __init__.py
  main.py          # entry point — argument parsing, logging setup, mode dispatch
  state_machine.py # OrderStateMachine, PaymentStateMachine, all Enum definitions
  db.py            # Postgres connection management, DDL bootstrap
  generator.py     # data generation (customers, products, addresses)
  runner.py        # historical mode and streaming mode orchestration
  tests/
    __init__.py
    test_state_machine.py
    test_generator.py
    test_db.py
```

Modules are single-responsibility. Do not put database calls inside
`state_machine.py` — the state machine is pure logic, persistence is `db.py`'s
job.

---

## SQL — Postgres

These rules apply to all Postgres DDL (`simulator/schema.sql`) and any raw
SQL queries in the simulator. dbt models follow these rules except where dbt
Jinja templating requires deviation.

### Identifiers

`snake_case` for all identifiers — tables, columns, indexes, constraints.
Never use quoted identifiers (`"MyTable"`) — they create case-sensitivity
problems.

```sql
-- CORRECT
CREATE TABLE order_events (
    event_id    TEXT NOT NULL,
    order_id    TEXT NOT NULL,
    new_state   TEXT NOT NULL
);

-- WRONG
CREATE TABLE "OrderEvents" (
    "EventId"   TEXT NOT NULL
);
```

### Keywords

SQL keywords in **UPPERCASE**. Identifiers in `snake_case`. This is the
single most important readability rule.

```sql
-- CORRECT
SELECT order_id, order_state, updated_at
FROM orders
WHERE order_state = 'placed'
  AND is_stuck = FALSE;

-- WRONG
select order_id, order_state, updated_at
from orders
where order_state = 'placed';
```

### Never SELECT *

Always list columns explicitly. `SELECT *` breaks when columns are added or
reordered and hides what data is actually consumed.

```sql
-- CORRECT
SELECT order_id, customer_id, order_state, updated_at
FROM orders;

-- WRONG
SELECT * FROM orders;
```

### Timestamps

Use `TIMESTAMP WITH TIME ZONE` for all timestamp columns. Store and retrieve
in UTC. Never use `TIMESTAMP` (without timezone) — it silently discards
timezone information.

```sql
-- CORRECT
order_date       TIMESTAMP WITH TIME ZONE NOT NULL,
updated_at       TIMESTAMP WITH TIME ZONE NOT NULL,

-- WRONG
order_date       TIMESTAMP NOT NULL,
order_date       TIMESTAMP_NTZ NOT NULL,  -- Snowflake type, not Postgres
```

### DDL Conventions

- All DDL must be idempotent: `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`.
- Primary keys: `TEXT` type using UUIDs generated by the application. Never use `SERIAL` or `BIGSERIAL` — they create auto-increment coupling that breaks when loading data from the simulator.
- Foreign keys: declared as **table-level constraints**, not inline.
- Indexes: explicit `CREATE INDEX` after table definition, not inline.
- Constraints are named: `CONSTRAINT fk_orders_customer FOREIGN KEY ...`

```sql
-- CORRECT
CREATE TABLE IF NOT EXISTS payments (
    payment_id       TEXT NOT NULL,
    order_id         TEXT NOT NULL,
    payment_state    TEXT NOT NULL,
    amount           NUMERIC(12, 2) NOT NULL,
    payment_method   TEXT NOT NULL,
    payment_date     TIMESTAMP WITH TIME ZONE,
    authorization_date TIMESTAMP WITH TIME ZONE,
    capture_date     TIMESTAMP WITH TIME ZONE,
    refund_date      TIMESTAMP WITH TIME ZONE,
    failure_reason   TEXT,
    retry_count      INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT pk_payments PRIMARY KEY (payment_id),
    CONSTRAINT fk_payments_order FOREIGN KEY (order_id)
        REFERENCES orders (order_id)
);

-- WRONG — inline FK, no IF NOT EXISTS, SERIAL pk, FLOAT for money
CREATE TABLE payments (
    payment_id SERIAL PRIMARY KEY,
    order_id TEXT REFERENCES orders(order_id),
    amount FLOAT
);
```

### Money / Amounts

Use `NUMERIC(12, 2)` for all monetary columns. Never `FLOAT` or `REAL` —
floating-point arithmetic produces rounding errors in financial calculations.

### JSON Columns

Use `JSONB` for semi-structured metadata. Never `JSON` (text-stored,
no indexing) or `TEXT` with embedded JSON strings.

```sql
-- CORRECT
metadata JSONB,

-- WRONG
metadata JSON,
metadata TEXT,
```

### Query Formatting

One clause per line. Indent continuation lines by 4 spaces. `AND`/`OR`
operators at the start of the line, not the end.

```sql
-- CORRECT
SELECT
    o.order_id,
    o.order_state,
    p.payment_state,
    p.amount
FROM orders o
JOIN payments p ON p.order_id = o.order_id
WHERE o.order_state != 'cancelled'
  AND p.retry_count < 3
ORDER BY o.order_date DESC;

-- WRONG — everything on one line
SELECT o.order_id, o.order_state, p.payment_state, p.amount FROM orders o JOIN payments p ON p.order_id = o.order_id WHERE o.order_state != 'cancelled' AND p.retry_count < 3;
```

---

## Enforcement Summary

| Rule | Enforced by |
|------|------------|
| Python format | `ruff format` (pre-commit) |
| Python lint | `ruff check` (pre-commit) |
| SQL lint | `sqlfluff lint` (pre-commit) |
| Type hints | Code review + Ruff rules |
| Test coverage | Code review — every public function with branching logic |
| No `SELECT *` | SQLFluff rule `AM04` |
| `TIMESTAMP WITH TIME ZONE` | Code review |
| Named constraints | Code review |

Code review is the backstop for rules that tooling cannot fully automate.
Reviewer agent checks these explicitly on every PR.
