# CLAUDE.md — Project Context

Auto-loaded by Claude Code at session start. Read this file first, then
`SPEC.md`, `DECISIONS.md`, and `AI_WORKFLOW.md` in that order.

---

## Project Conventions

**Commits:** Conventional Commits — `<type>(<scope>): <description>`
Types: `feat`, `fix`, `chore`, `docs`, `test`, `refactor`, `ci`

**Branches:** GitHub Flow — `<type>/<short-description>` off `main`
Types: `feature/`, `fix/`, `chore/`, `docs/`

**Decisions:** Recorded in `DECISIONS.md` as ADRs. Settled decisions are not
re-litigated unless the engineer explicitly says "reopen ADR-XXX".

**Agent sync:** `.agents/` is source of truth. `.opencode/prompts/` is derived.
Run `python scripts/sync_agents.py --check` to verify sync state.

---

## Session Notes

### 2026-06-05 — Generator tail-spike fix + DuckDB write performance

**Two correctness/performance bugs found and fixed:**

**Bug 1 — Exaggerated order volume tail in historical runs (`simulator/generator.py`):**
`generate_historical_orders` pre-sampled all order dates with seasonal weights, then when a
randomly-chosen customer's `created_at` was after the sampled date it **replaced the order date**
with a random date in `[customer.created_at, end_date]`. Customers created near `end_date`
always had their orders pushed to the very end, producing an artificial spike in the last
weeks of any historical run. Fixed by sorting eligible customers by `created_at` once and using
`bisect.bisect_right` per order date to sample only from customers who actually existed on that
date. Seasonal date distribution is fully preserved — no date-shifting.

**Bug 2 — DuckDB bulk write throughput (`simulator/db.py`):**
`_insert_batch` and `_bulk_insert` used `cursor.executemany` with row-by-row `?` parameter
binding for DuckDB. Benchmarked at 27.6 s for 50K rows — writing 200K orders took ~80 minutes.
Fixed by replacing the DuckDB path with a pandas zero-copy route: build a `DataFrame` from the
rows and run `conn.execute("INSERT INTO t SELECT * FROM df")`. Same benchmark: 0.05 s — 550×
faster. Full 200K-order historical write now completes in ~30 seconds.

**Verification notebook updated (`notebooks/01_simulator_data_quality.ipynb`):**
Added section **3b — Year-over-Year Weekly Order Volume**: each year plotted as a separate line
on a shared Jan–Dec x-axis so same-period comparisons are immediate. Partial years shown as
dashed lines. Annual totals printed below the chart.

**Historical run results (post-fix):**
- `--bootstrap`: 200K addresses, 340,452 customers, 25K products loaded in ~9 s
- `--historical 24`: 200,000 orders generated + written in ~13 min total (write phase ~30 s)
- 24/24 data quality checks passing
- YoY weekly chart shows flat-to-slight-decay pattern consistent with `PRIMARY_DECAY_FLOOR=0.40`
  in the bootstrap notebook (expected behaviour, not a bug)

**No new ADRs** — both fixes were correctness/performance bugs, not architectural decisions.

---

### 2026-06-05 — Bootstrap regeneration + clean historical run

**Bootstrap notebook fully rewritten (`samples/simulator_base_data.ipynb`):**
- Seasonal + linear acquisition decay replacing flat-random `created_at` (ADR-018 implemented)
- Two independent decay floor knobs: `PRIMARY_DECAY_FLOOR=0.40`, `HH_DECAY_FLOOR=0.10`
- Household pool built once, per-row sampling uses `bisect` trim — no per-row rebuild
- Window: `2022-06-01 → 2028-06-01` (4yr back, 2yr forward)
- Original notebook preserved as `simulator_base_data.ipynb.bak`

**New CSV volumes (`samples/`):**
- `addresses.csv` — 200,000 rows
- `customers.csv` — 340,452 rows (household model, seasonal created_at)
- `products.csv` — 25,000 rows (unchanged)

**Clean historical run completed:**
- `simulator.duckdb` deleted (was locked by DataGrip connection)
- `--bootstrap` loaded all three CSVs cleanly
- `--historical 24` completed: 200,000 orders, 140,783 customers excluded as future-dated (forward window working as designed)
- `payment_events` concern from previous session considered resolved — clean run to completion

**Open items closed this session:**
- Payment events incomplete (was caused by mid-run kill, not a code bug — clean run confirmed)
- Lever 1 Phase A (seasonal `created_at`) implemented and data regenerated

---

### 2026-06-04 — Architecture decisions (simulator realism + orchestration)

Three ADRs added this session (018–020). No code written — discussion and doc updates only.

**ADR-018 — Customer pre-generation replaces runtime injection:**
The large dormant customer population (~255K, majority never ordered) is repurposed as the organic growth mechanism. The bootstrap notebook generates `created_at` with a seasonal curve extending 2 years forward. Both simulators filter `created_at <= current_sim_time` — the eligible pool grows naturally. Lever 1 Phase B (runtime household injection) is removed from scope. `new_customer_rate_max` config knob retired.

**ADR-019 — Compression ratio as project-wide constant:**
`compression_ratio` in `config.yaml` governs stream mode and Snowflake batch cadence. Stream mode now maintains a pending-transitions queue (orders drip state changes over real time) rather than batch-finalizing all events at creation. At ratio 60: 1 real min = 1 simulated hour; a 30-min session = ~30 simulated hours = 1–2 "daily" Snowflake batch cycles.

**ADR-020 — Snowflake Tasks as initial orchestrator:**
Snowflake Tasks schedule batch jobs (compiled dbt SQL / stored procedures) at intervals derived from `compression_ratio`. No external scheduler needed for Phase 1–3. Airflow + Cosmos (ADR-004) activates in Phase 4 for cross-system coordination. Batch steps are discrete callable units to make Airflow migration a structural lift-and-shift.

**Docs updated:** `DECISIONS.md` (ADRs 018–020), `docs/SIMULATOR_REALISM_LEVERS.md` (Lever 1 Phase B superseded, stream mode architecture section added).

---

## Open Items — Pick Up Next Session

### Simulator work is paused — move to Phase 2
Phase 1 simulator is considered done for now. Levers 2/3 and stream mode
pending-transitions queue are deferred until after Phase 2 work begins.

### Simulator Realism Levers
See `docs/SIMULATOR_REALISM_LEVERS.md` for full spec.

| Lever | Status |
|-------|--------|
| 1 — Customer acquisition (seasonal `created_at`) | ✅ Complete — CSV regenerated, tail-spike bug fixed |
| 2 — Time-of-day order distribution | Deferred post-Phase 2 |
| 3 — Product lifecycle (stars/duds, launch spikes) | Deferred post-Phase 2 |

### Stream Mode Pending-Transitions Queue (ADR-019)
Stream mode still finalizes all lifecycle events at order creation time. Needs a
pending-transitions queue so CDC consumers see state changes drip over real
wall-clock time at the configured `compression_ratio`. Deferred post-Phase 2.

### Open PRs
All Phase 1 work is on `main` — no PRs opened yet. Before or alongside Phase 2:
- Open PR for simulator core (state machine, db, generator, main)
- Open PR for bootstrap data generation notebook rewrite
- Open PR for realism lever 1 + tail-spike fix + DuckDB write perf fix

---

## Current Phase

**Phase 3 — Intermediate Models, Marts, and Snowflake Tasks (next)**

Phase 2b is complete and merged (PR #13).

**Phase 2b delivered:**
- Snowflake trial account: `NHUKSVM-HV76137.snowflakecomputing.com`, user `tonyjrossignol`
- SnowSQL configured via `~/.snowsql/config` — `snowsql` connects without flags
- All 8 tables loaded into `RAW.RETAIL` — verified row counts:
  - addresses: 200,000 | customers: 340,452 | products: 25,000
  - orders: 200,000 | order_items: 600,484 | payments: 200,000
  - order_events: 587,593 | payment_events: 406,905
- `dbt run --select staging.*` — 8 views green in `ANALYTICS.STAGING`
- `schema.yml` added: descriptions + 66 data tests, all passing
- `persist_docs` enabled — column descriptions visible in Snowflake Horizon Catalog
- Discovered `cancelled` as a valid `order_state` (added to accepted_values test)

**Key environment facts (critical for Phase 3):**
- Dev container path: `/workspace/retail_analytics`
- `profiles.yml` lives inside the repo at `retail_analytics/profiles.yml`
- `generate_schema_name` macro: models land in schema as named (no target prefix) — staging → `ANALYTICS.STAGING`
- Snowflake UI uses "Workspaces" layout — SQL files via **Workspaces → + → SQL File**

**Key schema facts (verified against live Snowflake data):**
- All IDs are strings: `ord_xxx`, `cust_xxx`, `addr_xxx`, `prod_xxx`, `pay_xxx`, `evt_xxx`, `item_xxx`
- `orders.order_state` values: placed, confirmed, shipped, delivered, returned, cancelled
- `payments.payment_state` values: pending, authorized, captured, failed, refunded
- `payments` has 4 lifecycle timestamps: `payment_date`, `authorization_date`, `capture_date`, `refund_date`
- `order_events` / `payment_events` have no `event_type` column
- `products` staging renames: `name→product_name`, `category→product_category`, `price→unit_price`
- `order_items` staging renames: `total_price→line_total`

**Background — Phase 1 complete:**
Simulator functional, 69/69 tests passing. 200K orders / 340K customers / 200K addresses / 25K products.
dbt Semantic Layer (MetricFlow + Snowflake Semantic Views) added as Phase 3d — see ADR-021.

---

## Session Notes

### 2026-06-03 — Phase 1 session (simulator realism fixes)

**Two correctness gaps identified and fixed:**

**Gap 1 — flat event timestamps:** `simulate_order_lifecycle` was stamping every
lifecycle event with the same `now` value. Fixed by walking a `current_time` clock
forward from `order_date` using realistic per-transition delay windows:
- placed → confirmed: 0–30 min; confirmed → shipped: 1 hr–3 days;
  shipped → delivered: 2–7 days; delivered → returned: 1–30 days.
`orders.updated_at` now reflects the final lifecycle event time (not wall-clock
`NOW()`). `finalize_order` accepts an optional `final_updated_at` param.

**Gap 2 — orders could predate customers:** `generate_historical_orders` was
picking customers uniformly at random with no check against `customer.created_at`.
Fixed by: (a) loading `created_at` in `db.load_customers()`; (b) pre-filtering to
customers who existed before `end_date`; (c) using
`max(start_date, customer.created_at)` as the effective order-date floor per order.
Orders in-flight at query time (placed near `end_date`, not yet delivered) are
intentional — they test dbt incremental logic.

**`--duration SECONDS` added to stream mode:** `stream_mode` now accepts an
optional `duration_secs` parameter; the CLI exposes `--duration` so stream runs
can be time-bounded for testing. Without it, stream runs forever as before.

**Test suite: 69/69 passing, ruff clean.**
New test classes: `TestEventTimestamps` (events after order_date, monotonic,
`updated_at` correct), `TestStreamDuration` (exits on deadline, inserts orders),
`TestGenerateHistoricalOrders` (temporal constraint cases). `test_db.py` asserts
`created_at` is returned as a timezone-aware datetime.

**No new ADRs** — all changes were correctness fixes, not architectural decisions.

**Open items for next session:**
1. Open PRs for all Phase 1 work (currently all on `main` unstaged)
2. End-to-end smoke test: run `--bootstrap` then `--historical 12` against
   a real DuckDB file and spot-check row counts and state distributions
3. Decide product catalog size — 25K products may be large for training
   exercises; 1K–5K is ADR-011 target but overridden by notebook default

### 2026-06-03 — Phase 1 session (initial)

**Schema decisions made this session:**
- Address/customer relationship redesigned (ADR-015): `addresses` is now a
  standalone table; `customers.address_id` FK replaces the old
  `addresses.customer_id` + `address_type` model. Household concept (multiple
  customers sharing one address) is captured naturally via shared FK.
- `customers.region` dropped — redundant given `customers.address_id`.
- `products.inventory_quantity` dropped (ADR-017) — inventory management is
  out of scope; all products assumed always available.
- JSONB replaced with explicit typed columns in event tables (ADR-014):
  `order_events` gets `reason TEXT, retry_count INTEGER`;
  `payment_events` gets `failure_reason TEXT, retry_attempt INTEGER`.
- New customer injection rate added (ADR-016): `random.uniform(0, 0.10)` per
  order, configurable via `simulation.new_customer_rate_max` in `config.yaml`.

**Bootstrap data generated (`samples/`):**
- `addresses.csv` — 150,000 rows, population-weighted US zip geography
- `customers.csv` — ~255K rows, household model (families share address_id)
- `products.csv` — 25,000 rows, 6 categories, realistic name/price/margin
- `samples/simulator_base_data.ipynb` — notebook that generates all three;
  confirmed executable via `jupyter nbconvert --to notebook --execute`.
- All volumes are tunable variables, not ADR-level decisions (ADR-015).

**Simulator fully rewritten:**
- `simulator/config.yaml` — restructured: `database` section, `bootstrap.csv_dir`,
  `new_customer_rate_max: 0.10`, `num_orders: 50000`
- `simulator/db.py` — DuckDB/Postgres adapter via `_get_conn()` context manager;
  correct DDL for all 8 tables; CSV loader (`seed_from_csv`); `finalize_order`
  batches all lifecycle events in one transaction; no pool leaks
- `simulator/generator.py` — runtime concerns only: `generate_order`,
  `generate_historical_orders`, `create_new_customer`, `pick_customer`
- `simulator/main.py` — clean 3-mode CLI; `historical_mode` loads from DB;
  `stream_mode` uses DB pool + new customer injection; dead code removed
- `simulator/tests/` — all tests against real in-memory DuckDB (no mocks)

**Database strategy:**
- DuckDB is the default (`config.yaml: database.type: duckdb`). No server
  needed for local development or testing.
- Postgres switchable via `database.type: postgres` + `DATABASE_URL` env var.
- Infrastructure (Docker Compose, Dockerfile) deferred — not needed until
  Postgres is required for CDC pipeline work in Phase 4.

**ADRs added:** ADR-014 (JSONB → explicit columns), ADR-015 (address/customer
household model + tunable volumes), ADR-016 (new customer injection rate),
ADR-017 (inventory excluded).

### 2026-06-02 — Phase 0 session
Completed: Phase 0 fully delivered. GitHub remote created at
`https://github.com/tonytonyr/dbt-snowflake-training`. Branch protection
enabled on `main` (PR required, no direct push). Two PRs merged:
PR #1 `feature/phase-0-github-setup` — pre-commit config, SQLFluff config,
PR template. PR #2 `chore/gitignore-cleanup` — excluded `lessons/`,
`.skill-evals/`, `.claude/` from version control. Stale branches
(`feature/phase-0-github-setup`, `chore/gitignore-cleanup`) can be deleted
locally. `lessons/phase-0/github-setup.md` written (gitignored, local only).
No SQL linter added for Postgres — Snowflake dialect only, intentional (see
lessons doc). No new ADRs this session — ADR-001 through ADR-012 all active.
Next: Begin Phase 1. Architect must review and approve the state machine
design (order lifecycle: placed→confirmed→shipped→delivered→returned) before
Platform Engineer starts `simulator/state_machine.py`.
Open: None.
