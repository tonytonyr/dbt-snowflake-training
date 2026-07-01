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

### Decided — Stream Mode Pending-Transitions Queue is Phase 4a work (ADR-019)
Stream mode still finalizes all lifecycle events at order creation time rather than
dripping state changes over real wall-clock time at the configured `compression_ratio`.
No longer an open question — scoped as item 4 of Phase 4a in `SPEC.md` (see 2026-07-01
session note above). Implement before Phase 4b/4c; the CDC consumer and schema-evolution
exercise both depend on a realistic drip of discrete `UPDATE`s to be interesting.

### Simulator Realism Levers (still deferred, not CDC-blocking)
See `docs/SIMULATOR_REALISM_LEVERS.md` for full spec.

| Lever | Status |
|-------|--------|
| 1 — Customer acquisition (seasonal `created_at`) | ✅ Complete |
| 2 — Time-of-day order distribution | Deferred |
| 3 — Product lifecycle (stars/duds, launch spikes) | Deferred |

### Phase 3 residual items (not blocking Phase 4, but worth clearing)
See the 2026-07-01 session note above for full context.
- Confirm Phase 3d full-refresh baseline was run against prod (`dbt run --select fct_orders
  fct_payments fct_returns --full-refresh --target prod`)
- Confirm Phase 3e post-merge steps were run against prod (time spine table, `mf list
  metrics`, `mf query` smoke test)
- Snowflake Semantic Views publishing — blocked on missing `dbt_semantic_view` package;
  revisit if/when it lands on the dbt Hub index
- Persistent dbt docs hosting (GitHub Pages / S3 / dbt Cloud) instead of per-run artifact download

### Before Phase 4: MetricFlow mechanics review
User asked for a dedicated review session on dbt Semantic Layer + MetricFlow mechanics
(semantic model/measure/metric/saved-query relationships, entity-based joins,
metric_time vs agg_time_dimension, mf CLI workflow) before starting Phase 4. This has not
happened yet as a standalone teaching session — do this first, or at minimum ask whether
the user still wants it before diving into Phase 4 CDC work.

---

## Current Phase

**Phase 4 — CDC Ingestion (next)**

### 2026-07-01 — Phase 4 lesson plan authored (SPEC.md rewrite)

**No code changes this session — planning only.** `SPEC.md`'s Phase 4 section was rewritten
from a single 7-step block into five sub-phases (mirroring the Phase 2a/2b and Phase 3a–3e
lettering pattern), each its own branch:
- **4.0 — Infrastructure Bring-Up & Validation** (new — the "0 section" gate): stands up
  `postgres`, `kafka` (KRaft), `schema-registry`, `connect` (Debezium) in Docker Compose and
  requires 6 explicit health checks (container health, `wal_level=logical`, Kafka broker
  reachability, Schema Registry `/subjects`, Connect `/connector-plugins`, `.env.example`
  updated) to pass **before** any connector or consumer code is written.
- **4a — Simulator → Postgres migration + realism fixes** (Platform Engineer)
- **4b — Debezium connector + Avro/Schema Registry** (Platform Engineer, ADR-024)
- **4c — CDC consumer + Snowflake MERGE** (Pipeline Engineer)
- **4d — Schema evolution exercise** (Pipeline Engineer)

**Simulator review found four concrete gaps, now scoped as Phase 4a work items** (this is the
"revisit the simulator" ask — assessed, not yet implemented):
1. Postgres has been a code path in `simulator/db.py` since Phase 1 but has **never been
   exercised against a real Postgres server** — no test in `simulator/tests/` targets it, and
   there's no `simulator/requirements.txt` pinning `psycopg2`.
2. **Latent bug:** `db.py`'s Postgres `_get_conn` (`db.py:144-153`) returns a connection to the
   pool on exception with no `conn.rollback()` — would poison the pooled connection for the next
   borrower the first time a real error occurs (e.g., the email-uniqueness collision
   `stream_mode` already anticipates). Invisible against DuckDB (no pool); needs a fix before
   Postgres is load-bearing.
3. **ADR-019's pending-transitions queue is still not implemented.** `stream_mode` still calls
   `simulate_order_lifecycle()` synchronously right after `insert_order()` — the full lifecycle
   lands in one transaction instantly, not the realistic drip of spaced-out `UPDATE`s that makes
   the Phase 4 CDC demo (and the 4d schema-evolution exercise) meaningful. This was flagged as
   an open item after the 2026-06-04 session and never picked up — now it's the single
   highest-priority Phase 4a item.
4. **Stale ADR-016 code still live:** `pick_customer()`/`create_new_customer()` runtime
   injection (superseded by ADR-018's pre-generated `created_at` approach) is still called from
   `stream_mode`'s hot path. Needs to be replaced with the `created_at <= sim_clock.now()` filter
   ADR-018/019 already specify, or deleted if unused elsewhere.

**Erratum caught and corrected (not an ADR reopening):** ADR-024's decision text and the
original SPEC.md Phase 4 step 2 both named a `returns` table for Debezium to watch — no such
table exists in the schema (returns are `orders.order_state = 'returned'` + `order_events`
rows). Corrected watch-list going forward: `orders`, `order_items`, `payments`. ADR-024 itself
is left untouched per the "decisions are permanent" convention — this is flagged as a factual
correction in SPEC.md, not a superseding decision.

**No new ADRs this session** — sub-phase branch structure and the "returns" fix are execution
planning, not architectural decisions. ADR-005, ADR-006, ADR-018, ADR-019, ADR-024 all still
active and unchanged.

**Next:** Begin Phase 4.0 (`feature/phase-4-0-infra-bringup`) — Docker Compose service bring-up
and the 6-point validation checklist, before touching Phase 4a simulator work.

### 2026-07-01 — Phase 4.0 executed and validated live (same session)

Wrote `lessons/phase-4/phase-4-plan.md` (overview across all 5 sub-phases) and
`lessons/phase-4/phase-4-0-training.md` (fully fleshed-out 4.0 training doc), then actually
built and ran the stack against a live Docker Desktop instance rather than writing it from
memory — two real failures found and fixed in the process:

1. **Debezium 3.x is Java-17-only; `confluentinc/cp-kafka-connect-base:7.6.1` ships Java 11.**
   Pinning `debezium/debezium-connector-postgresql:latest` resolved to `3.2.6-2` and failed at
   Connect startup with `UnsupportedClassVersionError`. Fixed by querying Confluent Hub's
   version API and pinning `2.5.4-2` — the last Java-11-compatible line.
2. **Connect container OOM-killed at `mem_limit: 768m`** (`docker inspect` confirmed
   `OOMKilled=true`, exit 137). `cp-kafka-connect-base` scans ~15 bundled Confluent component
   classpaths at startup, not just the two this image adds — the scan needs more headroom than
   the JVM heap alone. Fixed by raising the limit to `1536m` (heap stayed at `-Xmx768m`).

**Real files created (this is the first Docker Compose stack in the project):**
- `docker-compose.yml` — `postgres` (16, `wal_level=logical`), `kafka` (KRaft, `cp-kafka:7.6.1`,
  no ZooKeeper per ADR-005), `schema-registry` (`cp-schema-registry:7.6.1`), `connect` (custom
  build)
- `docker/kafka-connect-avro/Dockerfile` — `cp-kafka-connect-base:7.6.1` +
  `confluent-hub install` for the Debezium Postgres connector and Confluent's Avro converter.
  Debezium's own image doesn't bundle Confluent's Avro converter (Confluent-distributed, not
  part of the Debezium project) — starting from Confluent's Connect base (which ships the
  `confluent-hub` CLI) and installing both components into it avoided guessing raw Maven jar
  coordinates.
- `.env.example` — Postgres credentials + `KAFKA_CLUSTER_ID` placeholders (first `.env.example`
  in this repo — none existed before, a pre-existing small gap not otherwise fixed this session)

**All 6 validation checks passed against the live stack** (full output in the training doc):
container health, `wal_level=logical`, Kafka broker reachability, Schema Registry `/subjects`
returning `[]`, Connect `/connector-plugins` listing
`io.debezium.connector.postgresql.PostgresConnector`, no secrets committed.

**Stack was left running** at session end (`docker compose ps` shows all 4 healthy) so Phase 4a
can start immediately next session without re-running bring-up. Nothing has been committed yet.

**No new ADRs** — the Java-version pin and memory limit are implementation facts discovered by
testing, not architectural decisions; both are documented as code comments in
`docker-compose.yml`/`Dockerfile` and in the training doc's "What Actually Happened" section.

### 2026-07-01 — Phase 3 loose-ends cleanup + Phase 4 planning (ADR-024)

**Closed this session:**
- `shipped_revenue` metric added (PR #25) — second `agg_time_dimension` (`shipped_date`,
  `expr: shipped_at`) on `sem_orders`, alongside the existing `order_date`. Delivered-order
  revenue anchored to ship date instead of order date, for fulfilment-timing questions
  distinct from order-timing questions. Validated with `dbt parse` (no error). Lesson doc
  (`lessons/phase-3/phase-3e-semantic-layer.md`, local-only per `.gitignore`) documents the
  pattern and a gotcha: metrics with different `agg_time_dimension`s can be queried together,
  but only by grouping on generic `metric_time` — grouping by a *named* dimension
  (`order__order_date`) fails once metrics with mixed `agg_time_dimension`s are in the same
  request.
- **ADR-024 added** (PR #24): Avro serialization + Schema Registry for Phase 4 CDC events.
  Rides on Kafka infra Phase 4 already scopes — not a reopening of ADR-008 (DataHub/OpenMetadata
  exclusion), which was about a full data catalog, not schema-contract enforcement. `SPEC.md`
  Phase 4 section updated: Debezium configured with `AvroConverter`, `BACKWARD` compatibility
  on the three watched subjects, and a deliberate schema-evolution exercise (accept a nullable
  column add, reject a breaking change) added as a Phase 4 deliverable.
- Repo housekeeping: merged PR #24 and #25 (both green CI, squash-merged, branches
  auto-deleted). Also deleted 3 stale local/remote branches left over from already-merged,
  squash-merged PRs (#15, #22, #23): `chore/phase-3e-docs`, `feature/phase-3a-intermediate-models`,
  `feature/phase-3e-semantic-layer`. These showed as "not merged" under `git branch --merged`
  only because squash merges rewrite the commit SHA — verified via `gh pr list --search
  "head:<branch>"` that each had a merged PR before deleting. Added a `.gitignore` rule for
  `retail_analytics/order_v_ship.csv` (ad-hoc `mf` query scratch output, not a deliverable).

**Still open, not blocking Phase 4 start — see "Open Items" below:**
- Phase 3d full-refresh baseline never confirmed as run against prod
- Phase 3e post-merge steps (time spine, `mf list metrics`, smoke test) never confirmed as run against prod
- Snowflake Semantic Views publishing (ADR-021 item 5) — blocked, package not on dbt Hub
- Persistent dbt docs hosting — flagged since Phase 3c, never picked up

**No new ADRs beyond ADR-024.**

---

Phase 3e (Semantic Layer) is complete and merged (PR #22).

**Phase 3e delivered:**
- `models/marts/metricflow_time_spine.sql` — Snowflake GENERATOR, 10-year window 2022–2032, `agg_time_dimension` registered via `+meta: time_spine: true` in `dbt_project.yml`
- `models/semantic_models/sem_orders.yml` — primary entity `order`, foreign entity `customer`, time dimension `order_date`, 6 measures (order_count, revenue, gross_revenue, gross_margin, returned_orders, cancelled_orders); all measures carry `agg_time_dimension: order_date`
- `models/semantic_models/sem_customers.yml` — primary entity `customer`, 5 dimensions (cohort_month, cohort_year, state, customer_segment, is_active)
- `models/semantic_models/sem_products.yml` — primary entity `product`, 2 dimensions (product_category, price_band)
- `models/metrics/retail_metrics.yml` — 7 metrics: order_count, revenue, average_order_value, returned_orders, return_rate, cumulative_revenue, revenue_wow (WoW uses `offset_window: "1 week"` on a revenue input alias)
- `models/saved_queries/retail_saved_queries.yml` — 3 saved queries using `Dimension()`/`TimeDimension()` string syntax required by dbt 1.9+
- `requirements.txt` — explicit pip deps (`dbt-snowflake>=1.9.0`, `dbt-metricflow[snowflake]>=1.8.0`)
- CI: `dbt parse` step validates semantic manifest on every PR; `dbt-metricflow[snowflake]` in pip install

**Key gotchas fixed this session:**
- dbt 1.9+ removed `metric-paths`, `saved-queries-paths`, `semantic-model-paths` as top-level `dbt_project.yml` keys — files must live inside `models/` and are auto-discovered
- `snowflake-labs/dbt_semantic_view` does not exist in the dbt Hub package index — Snowflake Semantic Views publishing is a manual `dbt run-operation` step, not a package dependency
- Derived metrics reference other **metrics**, not measures directly — `returned_orders` needed its own simple metric wrapper before `return_rate` could compose it
- MetricFlow requires `measure` as an object (`{name: ...}`) not a bare string in dbt 1.11
- Saved query `group_by` requires `"Dimension('entity__dim')"` / `"TimeDimension('metric_time', 'week')"` string syntax — plain `metric_time__week` is CLI-only
- Every measure needs `agg_time_dimension` pointing to a time dimension so MetricFlow can resolve `metric_time` queries
- `mf validate-configs` cannot find `~/.dbt/profiles.yml` in CI — replaced with `dbt parse` which uses the same profile path as all other dbt commands

**Post-merge manual steps (run locally against prod):**
```bash
cd retail_analytics
export SNOWFLAKE_PASSWORD="..."
dbt run --select metricflow_time_spine --target prod  # create the time spine table
mf list metrics                                       # verify 7 metrics visible
mf query --metrics revenue --group-by metric_time__week  # smoke test
```

Phase 3d (incremental fact tables) is complete and merged (PR #20).

**Phase 3d delivered:**
- `models/marts/fct_orders.sql` — incremental, unique_key=order_id, -3d lookback on updated_at
- `models/marts/fct_payments.sql` — incremental, unique_key=payment_id, GREATEST across all four lifecycle timestamps with COALESCE sentinels for nullable dates
- `models/marts/fct_returns.sql` — incremental, unique_key=order_id, anchored on max(returned_at) from {{ this }}
- `models/marts/schema.yml` — dbt_utils.recency warn test on fct_orders (pipeline health canary)
- `.sqlfluff` — added LT02 and RF02 to excludes (Jinja templater false positives in is_incremental blocks)

**Key facts:**
- `on_schema_change = 'sync_all_columns'` on all three — auto-adds columns, fails loudly on removals
- dim_* tables stay as `table` materialization — small and SCD2 requires full rebuilds
- After first merge, must run `dbt run --select fct_orders fct_payments fct_returns --full-refresh --target prod` to establish baseline before incremental logic activates
- Full-refresh runbook: always cascade fct_orders + fct_returns together; avoid during business hours (DROP TABLE creates brief gap)

Phase 3c is complete and merged (PR #18).

**Phase 3c delivered:**
- `models/staging/sources.yml` — source freshness on `orders` (updated_at) and `payment_events` (event_timestamp): warn 24h, error 48h
- `tests/assert_order_totals_balance.sql` — singular test: order subtotal must match sum of line items within $0.01
- `macros/classify_price_band.sql` — utility macro extracted from `dim_products` inline CASE; model updated to call it
- `.sqlfluff` — linter config matching project style (excludes LT01/LT09/ST06/ST07)
- `.github/workflows/ci.yml` — on PR: SQLFluff lint + `dbt build --select state:modified+` (downloads prod manifest artifact; falls back to full build on first run)
- `.github/workflows/cd.yml` — on merge to main: full `dbt build` + `dbt docs generate` + uploads manifest (30-day) and docs (7-day) artifacts
- `SNOWFLAKE_PASSWORD` stored as GitHub Actions secret — no credentials in code

**CI/CD gotchas fixed this session:**
- `profiles.yml` is gitignored — must be written at runtime in CI from the secret via `cat > ~/.dbt/profiles.yml`
- SQLFluff dbt templater requires `dbt deps` to run before linting (needs packages installed)
- Squash merges on GitHub create a new SHA — after merge, sync local main with `git fetch origin && git reset --hard origin/main`, not `git pull` (pull creates a spurious merge commit)

**dbt docs — how to view the artifact:**
CD uploads a `dbt-docs` artifact (manifest.json + catalog.json + index.html) to each run.
Download from **Actions → CD → latest run → Artifacts → dbt-docs**, unzip, then serve locally:
```
python -m http.server 8080
```
Open `http://localhost:8080`. Direct file:// access won't work (browser blocks local JSON reads).
**Future improvement:** host docs persistently on GitHub Pages, S3, or dbt Cloud — planned for Phase 3d alongside the Semantic Layer (ADR-021).

Phase 3b is complete and merged (PR #16).

**Phase 3b delivered:**
- `snapshots/customers_scd.sql` — SCD Type 2, check strategy on name/email/address_id
- `snapshots/products_scd.sql` — SCD Type 2, check strategy on name/category/price
- `models/marts/dim_date.sql` — calendar spine 2022-01-01 → 2028-12-31 via Snowflake GENERATOR
- `models/marts/dim_customers.sql` — current SCD2 row + address join + lifetime order metrics + cohort_month + customer_segment
- `models/marts/dim_products.sql` — current SCD2 row + gross_margin_pct + price_band
- `models/marts/fct_orders.sql` — conformed fact joining all 3 intermediate models
- `models/marts/fct_returns.sql` — returned orders with returned_at + days_to_return
- `models/marts/fct_payments.sql` — payment lifecycle with hours_to_authorize / hours_to_capture
- `models/marts/schema.yml` — full column descriptions + 32 data tests, all passing
- `models/marts/exposures.yml` — revenue_dashboard + payment_health_report exposures
- `dbt build --select marts.*` — 38/38 PASS (6 models + 32 tests)

**Gotcha fixed this session:**
- `dbt_project.yml` had global `+strategy: timestamp` / `+updated_at: updated_at` for snapshots.
  dbt project-level config overrides block-level config, so the `check` strategy inside each
  snapshot file was silently ignored. Fix: removed both keys from `dbt_project.yml`; each
  snapshot now controls its own strategy. Keep this in mind — never set a global snapshot
  strategy unless all snapshots share the same source column.


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
