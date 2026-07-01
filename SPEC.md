# Project Spec: Modern Data Stack Learning Sprint

## Purpose

A self-contained learning project to close skill gaps in **dbt** and **Snowflake**, with supporting exposure to **CDC ingestion**, **Airflow orchestration**, and **CI/CD**. The project is portfolio-grade: the architecture, patterns, and decisions should be defensible in a senior DE interview. Work is done in public on GitHub so the commit history itself demonstrates the build progression.

---

## Learning Objectives (Priority Order)

| Priority | Objective |
|----------|-----------|
| 1 | dbt project structure, layering (staging → intermediate → marts), and the `ref()`/`source()` DAG |
| 2 | Snowflake fundamentals: virtual warehouses, RBAC, database/schema design, query performance |
| 3 | dbt quality patterns: schema tests, custom tests, snapshots, incremental models, macros, docs |
| 4 | dbt Semantic Layer: MetricFlow semantic models, metric definitions, time spine, saved queries; Snowflake Semantic Views integration |
| 5 | CDC from a Postgres operational database into Snowflake via Kafka + Debezium, with Avro serialization and Schema Registry-enforced schema evolution |
| 6 | Airflow orchestration of the full pipeline using Astronomer Cosmos for dbt integration |
| 7 | CI/CD with GitHub Actions — SQL linting, dbt slim CI on PR, full build on merge |
| 8 | GitHub best practices — branching strategy, PRs, commit conventions, branch protection |

---

## Domain: Retail E-Commerce Fulfillment

Chosen because the business logic maps directly to Amazon retail/forecasting experience — cognitive load stays on the new tools, not the domain. Maps well to target employers (DoorDash, Instacart, DSG, Visa).

### Source Schema (8 tables)

> **As-built** — reflects actual simulator DDL in `simulator/db.py`.
> Phase 1–3 uses DuckDB locally; Phase 4 migrates to Postgres for CDC.

```
addresses                    customers
├── address_id (PK)          ├── customer_id (PK)
├── street_address           ├── first_name
├── city                     ├── last_name
├── state                    ├── email (UNIQUE)
├── postal_code              ├── address_id → addresses
└── country                  └── created_at TIMESTAMPTZ

products                     orders
├── product_id (PK)          ├── order_id (PK)
├── sku (UNIQUE)             ├── customer_id → customers
├── name                     ├── order_date TIMESTAMPTZ
├── category                 ├── status
├── price                    │   (placed/confirmed/shipped/
└── cost_price               │    delivered/returned/cancelled)
                             ├── total_amount
                             └── updated_at TIMESTAMPTZ

order_items                  payments
├── order_item_id (PK)       ├── payment_id (PK)
├── order_id → orders        ├── order_id → orders
├── product_id → products    ├── payment_method
├── quantity                 ├── payment_state
└── unit_price               │   (pending/authorized/captured/
                             │    failed/refunded)
                             └── amount

order_events                 payment_events
├── event_id (PK)            ├── event_id (PK)
├── order_id → orders        ├── payment_id → payments
├── event_type               ├── event_type
├── from_state               ├── from_state
├── to_state                 ├── to_state
├── reason TEXT              ├── failure_reason TEXT
├── retry_count INTEGER      ├── retry_attempt INTEGER
└── created_at TIMESTAMPTZ   └── created_at TIMESTAMPTZ
```

**Design notes:**
- `addresses` is standalone; `customers.address_id` FK captures the household model (multiple customers share one address — ADR-015)
- No inventory table — all products assumed always available (ADR-017)
- Event tables use explicit typed columns, not JSONB (ADR-014)
- `order_events` / `payment_events` are append-only CDC-friendly audit logs

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  Operational Layer (Docker)                                     │
│                                                                 │
│  E-Commerce Simulator (Python)                                  │
│  ├── Accelerated mode  ──►  Postgres 16  (historical backfill)  │
│  └── Streaming mode    ──►  Postgres 16  (live event drip)      │
│                                  │                              │
│                          Debezium + Kafka (KRaft)               │
│                          CDC events: c / u / d, Avro-encoded    │
│                                  │                              │
│                          Schema Registry                        │
│                          (compatibility: BACKWARD)               │
└──────────────────────────────────┬──────────────────────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  Snowflake                  │
                    │  RAW.retail.*               │
                    │  (bulk load + CDC upserts)  │
                    │                             │
                    │  dbt Core                   │
                    │  staging → intermediate     │
                    │         → marts             │
                    │         → semantic layer    │
                    │           (MetricFlow)      │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  Snowflake Semantic Views   │
                    │  (dbt_semantic_view pkg)    │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  Airflow + Cosmos (@daily)  │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  GitHub Actions (CI/CD)     │
                    │  PR: slim CI                │
                    │  main: full build + docs    │
                    └─────────────────────────────┘
```

---

## Infrastructure Stack

### Services by Phase

| Service | Technology | Phase Introduced | Est. RAM |
|---------|------------|-----------------|----------|
| Version control | GitHub | Phase 0 | — |
| Local operational DB | **DuckDB** (default) | Phase 1 | minimal |
| E-Commerce Simulator | Python (local) | Phase 1 | ~128 MB |
| Postgres (CDC source) | Postgres 16 (Docker) | Phase 4 | ~256 MB |
| Cloud Warehouse | Snowflake (trial) | Phase 2 | (external) |
| dbt Core | VS Code Dev Container | Phase 2 | ~256 MB |
| Snowflake Tasks | Native Snowflake | Phase 2–3 | (external) |
| dbt Semantic Layer (MetricFlow) | dbt Core 1.8+ | Phase 3d | (external) |
| Snowflake Semantic Views | Native Snowflake | Phase 3d | (external) |
| Kafka | Kafka 3.x (KRaft — no ZooKeeper) | Phase 4 | ~512 MB |
| CDC | Debezium Connect | Phase 4 | ~512 MB |
| Schema Registry | Confluent Schema Registry | Phase 4 | ~200-300 MB |
| Airflow | Astro Runtime + Cosmos | Phase 4+ | ~2-3 GB |
| **Phase 0-1 total** | | | **~128 MB** |
| **Phase 2-3 total** | | | **~384 MB** |
| **Phase 4 total** | | | **~1.7-1.8 GB** |
| **Phase 4+ (Airflow) total** | | | **~4.2-4.8 GB** |

**Database strategy (ADR-006 / ADR-020):**
- DuckDB is the default for Phase 1–3 local development — no server required
- Postgres introduced in Phase 4 as the CDC source (Debezium requires a WAL-enabled RDBMS)
- Snowflake Tasks orchestrate Snowflake-side batch jobs in Phase 2–3; Airflow + Cosmos takes over cross-system coordination in Phase 4+

### dbt Development Environment

| Mode | When Used |
|------|-----------|
| **VS Code Dev Container** | Active development — full VSCode + dbt Power User extension inside the container |
| **Docker Compose service** | Airflow-triggered and CI runs |

Same base image in both modes. Defined in `.devcontainer/devcontainer.json`, reused by Compose.

### Airflow + dbt: Astronomer Cosmos

Community standard (2025) — Cosmos parses the dbt project into individual Airflow tasks (one per model), giving per-model retry, automatic `ref()`-derived dependency ordering, and model-level observability in the Airflow UI.

---

## Project Structure

```
dbt_snowflake_training/
├── .devcontainer/
│   └── devcontainer.json                 # VS Code dev container (dbt + Python)
├── .github/
│   ├── workflows/
│   │   ├── ci.yml                        # PR: lint + dbt slim CI
│   │   └── cd.yml                        # Merge to main: full build + docs
│   └── pull_request_template.md          # PR checklist
├── .pre-commit-config.yaml               # SQLFluff + YAML lint
├── docker-compose.yml                    # All services
├── .env                                  # Creds (gitignored)
├── .env.example                          # Committed template
├── SPEC.md
├── simulator/
│   ├── simulator.py                      # E-commerce event simulator
│   ├── state_machine.py                  # Order lifecycle state machine
│   ├── schema.sql                        # Postgres DDL (all 8 tables)
│   └── requirements.txt
├── snowflake_setup/
│   └── setup.sql                         # Warehouses, databases, schemas, roles, grants
├── retail_analytics/                     # dbt project root
│   ├── dbt_project.yml
│   ├── packages.yml
│   ├── profiles.yml                      # (gitignored)
│   ├── .sqlfluff
│   ├── macros/
│   │   ├── generate_schema_name.sql
│   │   └── (additional macros added in Phase 3)
│   ├── models/
│   │   ├── staging/
│   │   │   ├── sources.yml
│   │   │   └── stg_retail__*.sql         (8 models)
│   │   ├── intermediate/
│   │   │   └── int_*.sql                 (4 models)
│   │   └── marts/
│   │       ├── dim_*.sql                 (4 models)
│   │       ├── fct_*.sql                 (3 models)
│   │       └── exposures.yml
│   ├── semantic_models/
│   │   ├── sem_orders.yml                # entities, dimensions, measures on fct_orders
│   │   ├── sem_customers.yml             # entities + dimensions on dim_customers
│   │   └── sem_products.yml              # entities + dimensions on dim_products
│   ├── metrics/
│   │   └── retail_metrics.yml            # revenue, aov, order_count, return_rate, etc.
│   ├── saved_queries/
│   │   └── retail_saved_queries.yml      # pre-defined metric+dimension combos for BI
│   ├── snapshots/
│   │   ├── customers_scd.sql
│   │   └── products_scd.sql
│   ├── tests/
│   │   └── assert_order_totals_balance.sql
│   └── analyses/
│       └── return_rate_by_segment.sql
├── airflow/
│   ├── dags/
│   │   ├── retail_fulfillment_pipeline.py
│   │   └── retail_snowflake_maintenance.py
│   └── Dockerfile                        # Astro Runtime + Cosmos
└── docs/
    └── runbook.md
```

---

## Phases

---

### Phase 0 — GitHub Setup & Project Foundation (Day 1, ~2 hours)

**Goal:** A properly configured public GitHub repository that enforces good engineering hygiene from the first commit. Every subsequent phase is delivered via PR — the commit history tells the story of the build.

#### GitHub Repository Setup
1. Create public repo `dbt-snowflake-training` on GitHub
2. Push the existing local directory as the initial commit (`SPEC.md`, `.gitignore`, `README.md` stub)
3. Configure **branch protection on `main`**:
   - Require pull request before merging (no direct push)
   - Require at least 1 approving review (self-review acceptable for a solo project — the discipline matters)
   - Require status checks to pass before merging (CI must be green)
   - Require branches to be up to date before merging

#### Branching Strategy
This project uses **GitHub Flow** — simple, linear, and appropriate for a solo or small-team project:

```
main          ← always deployable; protected
  └── feature/phase-1-postgres-setup
  └── feature/phase-2-snowflake-dbt
  └── fix/stg-orders-null-handling
  └── chore/update-dbt-deps
```

Branch naming convention: `<type>/<short-description>`
- `feature/` — new capability
- `fix/` — bug or data quality correction
- `chore/` — dependency updates, config changes, non-functional work
- `docs/` — documentation only

#### Commit Message Convention
[Conventional Commits](https://www.conventionalcommits.org/) standard:
```
<type>(<scope>): <short description>

feat(simulator): add order state machine with lifecycle transitions
fix(staging): handle null actual_delivery in stg_retail__shipments
chore(deps): bump dbt-snowflake to 1.9.0
docs(runbook): add CDC lag recovery steps
test(marts): add assert_order_totals_balance custom test
```

Types: `feat`, `fix`, `chore`, `docs`, `test`, `refactor`, `ci`

#### PR Workflow
- Every phase delivered as one or more PRs — no commits directly to `main`
- PR template (`.github/pull_request_template.md`) includes:
  - What changed and why
  - How to test locally
  - Checklist: tests pass, linting clean, `.env.example` updated if new vars added

#### Pre-commit Hooks
Install `pre-commit` locally:
```
pre-commit install
```
Hooks run on every `git commit`:
- **SQLFluff** — lint `.sql` files (dialect: snowflake)
- **YAML lint** — validate `sources.yml`, `dbt_project.yml`, etc.
- **trailing-whitespace**, **end-of-file-fixer** — standard hygiene

**Deliverable:** Public GitHub repo with branch protection active. A test PR (adding `.gitignore`) is opened, passes (no CI yet), and merged. Pre-commit hooks run clean on the first real commit.

---

### Phase 1 — Operational Store & E-Commerce Simulator ✅ Substantially Complete

**Goal:** A Python simulator that generates realistic historical data in accelerated mode and produces a live event stream in streaming mode. DuckDB is the local store for Phase 1–3; Postgres is introduced in Phase 4 for CDC.

#### Schema
8 tables implemented in `simulator/db.py` DDL — see Source Schema section above.
Applied idempotently at bootstrap. DuckDB default; Postgres switchable via `config.yaml`.

#### E-Commerce Simulator

**State Machine (`simulator/state_machine.py`)**
```
placed → confirmed → shipped → delivered
                                   └──► returned

payment: pending → authorized → captured
         pending → failed
```
Invalid transitions are rejected. The `accepted_values` dbt test on `orders.status` is meaningful because the simulator enforces valid transitions.

**Historical Mode**
```bash
python -m simulator.main --historical 24   # 24 months of history
```
- Seasonal demand curve (Dec peaks, Jan/Feb slumps) — mirrors `_MONTHLY_WEIGHT` in `generator.py`
- Customers filtered by `created_at <= end_date` — future-dated customers excluded naturally
- Lifecycle event timestamps fan out from `order_date` with realistic per-transition delays
- **Volumes (current):** 200K addresses, 340K customers, 25K products, 200K orders

**Stream Mode**
```bash
python -m simulator.main --stream [--duration SECONDS]
```
- Places new orders continuously at configurable rate
- `--duration` bounds the run for testing; omit to run indefinitely
- **Pending (ADR-019):** transition queue so CDC consumers see state changes drip over real time at `compression_ratio`

**Bootstrap**
```bash
python -m simulator.main --bootstrap   # loads samples/*.csv into DB
```

**Configuration** (`simulator/config.yaml`):
- `database.type`: `duckdb` (default) or `postgres`
- `database.path`: DuckDB file path
- `simulation.num_orders`: target order count for historical mode
- `stream.compression_ratio`: governs simulated-time cadence (ADR-019, pending implementation)

**Bootstrap data** (`samples/`):
- Generated by `samples/simulator_base_data.ipynb`
- `created_at` uses seasonal weights × linear acquisition decay (ADR-018)
- `PRIMARY_DECAY_FLOOR=0.40`, `HH_DECAY_FLOOR=0.10` — independent knobs
- Household members sampled from blended pool, bounded by primary's `created_at`; bisect trim for performance
- Window: `2022-06-01 → 2028-06-01` giving 2 years of forward runway for stream mode

**Test suite:** 69/69 passing, ruff clean. All tests run against real in-memory DuckDB.

#### Remaining Phase 1 Work
- Stream mode pending-transitions queue (ADR-019)
- Open PRs for all Phase 1 work (currently all on `main`)
- Realism Levers 2 (time-of-day) and 3 (product lifecycle) — can follow Phase 2

**Deliverable:** `python -m simulator.main --bootstrap && python -m simulator.main --historical 24` populates all 8 tables. Row counts and temporal ordering are valid.

---

### Phase 2 — Snowflake + dbt Foundation (Days 5-7, ~8 hours)

**Goal:** Snowflake configured, initial data loaded from DuckDB into Snowflake using format-appropriate bulk load patterns, and the full staging layer running in dbt.

> **Trial strategy:** Complete Phase 2a entirely before creating your Snowflake account.
> The trial clock starts on signup — everything in 2a can be done locally with zero Snowflake usage.

---

#### Phase 2a — Local Prep (before Snowflake signup)

Branch: `feature/phase-2a-local-prep`

1. Set up VS Code Dev Container with dbt Core + dbt-snowflake adapter
2. Scaffold the dbt project (`retail_analytics/`) — `dbt_project.yml`, `packages.yml`,
   directory structure, macros, stub `sources.yml`
3. Write all 8 staging model SQL files (they can be authored and linted offline;
   they just can't be executed yet)
4. Export data from DuckDB to flat files (DuckDB `COPY TO` syntax):
   - **CSV** — `addresses`, `customers`, `products` (reference tables)
   - **Flat Parquet** — `orders`, `order_items`, `payments` (transactional, single file per table)
   - **Hive-partitioned Parquet** — `order_events`, `payment_events` (event tables, partitioned by `year/month`)
   ```sql
   -- CSV example
   COPY (SELECT * FROM addresses) TO 'exports/addresses.csv' (HEADER, DELIMITER ',');
   -- Flat Parquet example
   COPY (SELECT * FROM orders) TO 'exports/orders.parquet' (FORMAT PARQUET);
   -- Hive-partitioned Parquet example (produces exports/order_events/year=2022/month=06/...)
   COPY (SELECT *, YEAR(created_at) AS year, MONTH(created_at) AS month FROM order_events)
       TO 'exports/order_events' (FORMAT PARQUET, PARTITION_BY (year, month));
   ```
5. Write `snowflake_setup/setup.sql` — warehouses, databases, schemas, roles, grants,
   file formats (CSV, Parquet, Parquet with Hive partitioning), named stage definitions
6. Write all `COPY INTO` load scripts for all three formats (ready to execute on day 1 of trial):
   - **CSV load** — named file format (`TYPE = CSV`, `SKIP_HEADER = 1`,
     `NULL_IF = ('', 'NULL')`, `EMPTY_FIELD_AS_NULL = TRUE`); `PUT` + `COPY INTO`
   - **Flat Parquet load** — named file format (`TYPE = PARQUET`); `PUT` + `COPY INTO`
     with `MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE`
   - **Hive-partitioned Parquet load** — `COPY INTO` with `PATTERN` clause for
     partition selection; `METADATA$FILENAME` virtual column to extract partition
     values from path; optionally create an External Table to query files in-place

   | Format | Tables | Schema source | Key Snowflake concept |
   |--------|--------|---------------|-----------------------|
   | CSV | addresses, customers, products | Defined in file format | `NULL_IF`, `EMPTY_FIELD_AS_NULL`, column ordering |
   | Flat Parquet | orders, order_items, payments | Embedded in file | `MATCH_BY_COLUMN_NAME` |
   | Hive-partitioned Parquet | order_events, payment_events | Embedded + path | `PATTERN`, `METADATA$FILENAME`, External Tables |

**Deliverable:** Dev container running, dbt project scaffolded, export files on disk, all SQL scripts written and SQLFluff-clean. Nothing requires a live Snowflake connection.

---

#### Phase 2b — Snowflake Active (trial clock running)

Branch: `feature/phase-2b-snowflake-load-and-staging`

1. Create Snowflake trial account
2. Run `snowflake_setup/setup.sql` — all objects created in one shot
3. `PUT` export files to internal stage; run all `COPY INTO` load scripts
4. Verify row counts in `RAW.retail.*` match DuckDB source tables
5. Configure `profiles.yml` (dev: `ANALYTICS.staging_dev`, prod: `ANALYTICS.staging`)
6. `dbt debug` — confirm connectivity
7. `dbt run --select staging.*` — execute the pre-written staging models

**Deliverable:** `dbt run --select staging.*` succeeds. `RAW.retail.*` row counts match DuckDB.

---

### Phase 3 — Complete dbt Project + CI/CD (Days 8-12, ~15 hours)

**Goal:** All three model layers, full quality patterns, documentation, and GitHub Actions CI/CD.

Each layer delivered as its own PR:
- `feature/phase-3a-intermediate-models`
- `feature/phase-3b-mart-models`
- `feature/phase-3c-tests-docs-cicd`

#### Intermediate Layer (4 models)
- `int_orders_enriched` — orders + items + products, `line_total`
- `int_inventory_daily` — daily snapshot deduplication
- `int_shipments_sla` — `on_time_delivery` flag, `days_late`
- `int_payment_reconciliation` — payments matched to orders, discrepancy flag

#### Marts Layer (7 models)
- `dim_customers`, `dim_products` — SCD Type 2 via dbt snapshot
- `dim_date` — calendar dimension
- `fct_orders` — conformed fact, all dimension keys
- `fct_inventory_daily` — incremental model
- `fct_returns`, `fct_payments`

#### Quality Patterns
| Pattern | Implementation |
|---------|---------------|
| Generic tests | `unique`, `not_null`, `relationships`, `accepted_values` |
| Custom tests | Order total vs line items; refund ≤ order total |
| Source freshness | Orders warn/error thresholds; Inventory warn/error thresholds |
| Snapshots | SCD Type 2 on customers and products |
| Incremental | `fct_inventory_daily` — `unique_key` + `updated_at` |
| Macros | `generate_schema_name()`, custom utility macros |
| Packages | `dbt_utils`: surrogate keys, date macros |
| Docs | Column descriptions on all mart models; two exposures |

#### CI/CD (GitHub Actions)
- `ci.yml`: PR trigger → SQLFluff lint → `dbt build --select state:modified+` vs CI Snowflake schema
- `cd.yml`: merge to `main` → full `dbt build` → `dbt docs generate` → upload `manifest.json` artifact (used for slim CI state comparison on next PR)
- Snowflake credentials stored as GitHub Actions secrets — never in code

**Deliverable:** `dbt build --full-refresh` passes all tests. PRs to `main` require green CI.

---

### Phase 3d — dbt Semantic Layer (Days 12-13, ~6 hours)

**Goal:** Define business metrics once in dbt YAML using MetricFlow; query them via the dbt CLI and publish them as native Snowflake Semantic Views. Demonstrates the "single source of truth for metrics" pattern that eliminates BI tool fragmentation.

Branch: `feature/phase-3d-semantic-layer`

#### What Is the Semantic Layer

The dbt Semantic Layer (powered by MetricFlow) sits between your mart models and downstream consumers. Instead of each BI tool computing `revenue` its own way, you define it once in YAML and every tool queries through the same definition:

```
fct_orders (mart)  →  semantic model (entities + measures)  →  metrics YAML  →  mf query / BI tool
```

MetricFlow translates metric queries into warehouse SQL at query time — it does not materialize additional tables.

#### Setup

1. Verify dbt Core ≥ 1.8 in the dev container (`dbt --version`)
2. Add `dbt-metricflow[snowflake]` to `retail_analytics/requirements.txt`
3. Add MetricFlow time spine model:
   ```sql
   -- models/marts/metricflow_time_spine.sql
   SELECT DATEADD(DAY, SEQ4(), '2022-01-01'::DATE) AS date_day
   FROM TABLE(GENERATOR(ROWCOUNT => 3650))
   ```
   Configure in `dbt_project.yml`:
   ```yaml
   models:
     retail_analytics:
       marts:
         metricflow_time_spine:
           +meta:
             time_spine: true
   ```

#### Semantic Models (3 files in `semantic_models/`)

**`sem_orders.yml`** — built on `fct_orders`:
```yaml
semantic_models:
  - name: orders
    model: ref('fct_orders')
    entities:
      - name: order_id
        type: primary
      - name: customer_id
        type: foreign
        expr: customer_id
    dimensions:
      - name: order_date
        type: time
        type_params:
          time_granularity: day
      - name: status
        type: categorical
      - name: product_category
        type: categorical
    measures:
      - name: order_count
        agg: count
        expr: order_id
      - name: revenue
        agg: sum
        expr: total_amount
      - name: returned_orders
        agg: count_distinct
        expr: "CASE WHEN status = 'returned' THEN order_id END"
```

**`sem_customers.yml`** — built on `dim_customers`:
entities (customer_id primary), dimensions (region, signup_cohort_month, is_active)

**`sem_products.yml`** — built on `dim_products`:
entities (product_id primary), dimensions (category, price_band)

#### Metrics (`metrics/retail_metrics.yml`)

| Metric | Type | Description |
|--------|------|-------------|
| `order_count` | simple | COUNT of orders |
| `revenue` | simple | SUM of `total_amount` |
| `average_order_value` | derived | `revenue / order_count` |
| `return_rate` | derived | `returned_orders / order_count` |
| `cumulative_revenue` | cumulative | Running total revenue |
| `revenue_wow` | derived | Week-over-week revenue growth % |

Example metric YAML:
```yaml
metrics:
  - name: average_order_value
    label: Average Order Value
    type: derived
    type_params:
      expr: revenue / order_count
      metrics:
        - revenue
        - order_count
```

#### Saved Queries (`saved_queries/retail_saved_queries.yml`)

Pre-defined metric+dimension combos consumable by BI tools without ad-hoc query construction:
- `weekly_revenue_by_category` — `revenue` + `order_date__week` + `product_category`
- `customer_cohort_aov` — `average_order_value` + `signup_cohort_month` + `region`
- `return_rate_trend` — `return_rate` + `order_date__month`

#### Querying Metrics

```bash
# List available metrics
mf list metrics

# Query revenue by week
mf query --metrics revenue --group-by metric_time__week

# Query AOV by product category
mf query --metrics average_order_value --group-by product_category

# Return rate month over month
mf query --metrics return_rate --group-by metric_time__month --order metric_time__month
```

#### Snowflake Semantic Views Integration (ADR-021)

The `dbt_semantic_view` package (Snowflake Labs, GA March 2026) publishes dbt metrics as native Snowflake Semantic View objects — zero-cost native database objects queryable by any SQL client.

1. Add to `packages.yml`:
   ```yaml
   packages:
     - package: snowflake-labs/dbt_semantic_view
       version: [">=0.1.0"]
   ```
2. Run `dbt deps && dbt run-operation publish_semantic_views`
3. Verify in Snowflake UI: `ANALYTICS.marts` schema should show semantic view objects
4. Query directly from any SQL client — no dbt CLI required

**Comparison exercise:** Query the same metric two ways — `mf query` (MetricFlow path) vs. direct Snowflake Semantic View SQL. Observe identical results, different execution paths.

#### Key Concepts Demonstrated

| Concept | Why It Matters |
|---------|---------------|
| Single metric definition | Revenue computed identically in every BI tool |
| MetricFlow time spine | Consistent grain control across all time-series metrics |
| Derived metrics | Composing complex metrics from simpler building blocks |
| Saved queries | BI-ready metric packs without ad-hoc query sprawl |
| Snowflake Semantic Views | Native Snowflake objects — no dbt runtime needed at query time |
| dbt vs. Snowflake paths | Two valid approaches; knowing both is the interview differentiator |

**Deliverable:** `mf list metrics` returns all 6 metrics. `mf query --metrics revenue --group-by metric_time__week` returns correct weekly totals matching raw SQL against `fct_orders`. Snowflake Semantic Views visible in the Snowflake UI.

---

### Phase 4 — CDC Ingestion (Days 13-15, ~10-12 hours)

**Goal:** Postgres → Debezium → Kafka → Snowflake CDC pipeline live, with Avro-encoded events
and Schema Registry-enforced compatibility (ADR-024). The simulator's streaming mode drives
continuous change events through the full stack.

> **Erratum carried from ADR-024 / original spec:** step 2 below previously named `returns` as
> a watched table. No such table exists — the schema (see Source Schema above) has no physical
> `returns` table; a return is `orders.order_state = 'returned'` plus a row in `order_events`.
> This plan watches **`orders`, `order_items`, `payments`** instead. ADR-024's decision text
> (Avro + Schema Registry + `BACKWARD` compatibility) is unaffected and is not reopened — this
> is a factual table-name correction, not an architectural change.

Phase 4 is split into five sub-phases, each its own branch/PR, following the same pattern as
Phase 2a/2b and Phase 3a–3e. **4.0 is a hard gate** — do not start connector or consumer work
against infrastructure that hasn't been individually verified healthy.

| Sub-phase | Branch | Owner (per `.agents/`) |
|-----------|--------|------------------------|
| 4.0 — Infra bring-up & validation | `feature/phase-4-0-infra-bringup` | Platform Engineer |
| 4a — Simulator → Postgres migration + realism fixes | `feature/phase-4a-simulator-postgres` | Platform Engineer |
| 4b — Debezium connector + Avro/Schema Registry | `feature/phase-4b-debezium-avro-connector` | Platform Engineer |
| 4c — CDC consumer + Snowflake MERGE | `feature/phase-4c-cdc-consumer-snowflake` | Pipeline Engineer |
| 4d — Schema evolution exercise | `feature/phase-4d-schema-evolution` | Pipeline Engineer |

---

#### Phase 4.0 — Infrastructure Bring-Up & Validation

**Goal:** Every new Docker Compose service is provably healthy in isolation before any
connector config or consumer code is written against it. This is the "0 section" — a smoke-test
gate, not a feature.

**Components added to `docker-compose.yml`:**

| Service | Image family | Role | Est. RAM (per SPEC Infra Stack table) |
|---------|--------------|------|----------------------------------------|
| `postgres` | `postgres:16` | CDC source; simulator's only write target (ADR-006) | ~256 MB |
| `kafka` | Confluent/Apache Kafka, KRaft mode (ADR-005) | Event transport, no ZooKeeper | ~512 MB |
| `schema-registry` | `confluentinc/cp-schema-registry` | Avro schema contracts (ADR-024) | ~200-300 MB |
| `connect` (Debezium) | `debezium/connect` (or `quay.io/debezium/connect`) | Runs the Postgres source connector | ~512 MB |

Config notes (Platform Engineer behavioral rules apply — explicit `mem_limit`/`cpus`, no
credentials in the compose file, idempotent restarts):
- `postgres` service: `command: ["postgres", "-c", "wal_level=logical"]` — Debezium's
  `pgoutput` plugin (built into Postgres 10+, no extension install needed) requires logical
  replication enabled at the server level, not just a role grant.
- `kafka`: KRaft envs (`KAFKA_PROCESS_ROLES`, `KAFKA_NODE_ID`, `KAFKA_CONTROLLER_QUORUM_VOTERS`)
  per ADR-005 — no `zookeeper` service.
- `schema-registry`: `SCHEMA_REGISTRY_KAFKASTORE_BOOTSTRAP_SERVERS` pointed at the `kafka`
  service; this is what makes it a "lightweight REST service backed by a Kafka topic" per
  ADR-024, not a standalone datastore.
- `connect`: `CONNECT_KEY_CONVERTER` / `CONNECT_VALUE_CONVERTER` set to
  `io.confluent.connect.avro.AvroConverter` with `*.schema.registry.url` pointed at
  `schema-registry` — set here at the worker level so every connector on this worker defaults
  to Avro without repeating it per-connector.

**Validation checklist (run before touching 4a):**

| # | Check | Command |
|---|-------|---------|
| 0.1 | All four containers report healthy | `docker compose ps` — every service `Up (healthy)` |
| 0.2 | Postgres has logical replication enabled | `docker compose exec postgres psql -U <user> -c "SHOW wal_level;"` → `logical` |
| 0.3 | Kafka broker is reachable and KRaft quorum is healthy | `docker compose exec kafka kafka-broker-api-versions --bootstrap-server localhost:9092` |
| 0.4 | Schema Registry REST API is up, no subjects yet | `curl localhost:8081/subjects` → `[]` |
| 0.5 | Kafka Connect REST API is up and the Debezium Postgres plugin is loaded | `curl localhost:8083/connector-plugins` → includes `io.debezium.connector.postgresql.PostgresConnector` |
| 0.6 | No secrets committed | `.env.example` updated with new placeholder vars (Postgres user/password, registry/connect URLs); real values only in `.env` (gitignored) |

**Deliverable:** `docker compose up -d` brings up all four new services; all six checks above
pass with zero connectors or consumer code written yet.

---

#### Phase 4a — Simulator → Postgres Migration + Realism Fixes

**Goal:** The simulator's `database.type: postgres` path (already written in `simulator/db.py`,
but never exercised against a real Postgres server — no test in `simulator/tests/` targets it)
becomes the live write path, and stream mode actually behaves the way ADR-019 already specifies.
This is the "revisit the simulator" work — four concrete gaps found by reviewing `db.py`,
`main.py`, and `generator.py` against ADR-018/019 before Phase 4 starts:

1. **Point config at the new Postgres service.** `simulator/config.yaml` → `database.type:
   postgres`; `DATABASE_URL` env var (or `.env`) points at the Compose `postgres` service.
   `simulator.duckdb` remains the Phase 1–3 default for local dbt/dev-target work (ADR-022) —
   this is a CDC-source-only switch, not a repo-wide default change.

2. **Add `simulator/requirements.txt`.** The simulator has never had a pinned dependency file —
   `duckdb`, `faker`, `pandas`, `psycopg2` (or `psycopg2-binary`) have been installed ad hoc.
   Postgres becoming a real, running dependency (not just an untested code branch) is the
   forcing function to pin this now.

3. **Fix a latent bug in `db.py`'s Postgres `_get_conn`** (`simulator/db.py:144-153`): on
   exception, the connection is returned to the pool via `finally: self._pool.putconn(conn)`
   with **no `conn.rollback()`**. Any failed statement (e.g., the email-uniqueness
   `IntegrityError` that `stream_mode` already anticipates and retries around) leaves that
   pooled connection in an aborted-transaction state for whichever caller borrows it next —
   every subsequent statement on that connection fails with `current transaction is aborted`
   until something happens to roll it back. This was invisible against DuckDB (single
   connection, no pool) and would surface for the first time once Postgres is actually load-
   bearing. Fix: wrap the `yield` in `try/except: conn.rollback(); raise`.

4. **Implement the ADR-019 pending-transitions queue in `stream_mode`.** Today,
   `stream_mode` (`simulator/main.py:107-156`) calls `simulate_order_lifecycle()` synchronously
   right after `insert_order()` — the *entire* lifecycle (placed → confirmed → shipped →
   delivered/returned, every event timestamp) is computed and written in one transaction before
   the loop's `time.sleep(tick)`. This is the exact gap flagged in `CLAUDE.md`'s open items: a
   CDC consumer watching this today sees one `INSERT` immediately followed by one `UPDATE`
   already carrying the order's *final* state — not the drip of discrete, spaced-out state
   transitions that makes a CDC demo interesting. `docs/SIMULATOR_REALISM_LEVERS.md` (Stream
   Mode Architecture section) already specifies the fix: maintain an in-memory
   `PendingTransition {order_id, next_state, fire_at_real_time}` queue; each tick, pop due
   transitions, emit one state `UPDATE` + one event row per transition, and reschedule the
   order's next transition using `simulated_delay / compression_ratio`. This is the single
   highest-value simulator change for Phase 4 — without it, the schema-evolution exercise in
   4d and the CDC consumer in 4c have nothing realistic to watch.

5. **Retire the stale ADR-016 runtime-injection path from `stream_mode`'s hot path.**
   `pick_customer()` / `create_new_customer()` (`generator.py:271-311`) still implement the
   pre-ADR-018 "inject a new customer at a random per-order rate" behavior, and `main.py`'s
   `stream_mode` still calls them. ADR-018 superseded this — customer growth is now baked into
   pre-generated `created_at` dates, and both simulators are supposed to filter
   `eligible = [c for c in customers if c.created_at <= sim_clock.now()]`. Replace the
   `pick_customer` call in `stream_mode` with that filter (the sorted-`created_at` + `bisect`
   pattern already used in `generate_historical_orders` is directly reusable). Keep
   `create_new_customer`/`pick_customer` only if there's a concrete edge-case test that still
   wants them — otherwise delete them; don't leave superseded logic live in the hot path.

6. **Publication + replica identity for Debezium.** `CREATE PUBLICATION dbz_publication FOR
   TABLE orders, order_items, payments;` (matching the corrected watch-list above).
   `REPLICA IDENTITY DEFAULT` (Postgres default) is sufficient — this schema has no hard
   `DELETE`s anywhere in `db.py`, so Debezium never needs a full before-image for a tombstone.
   Document this reasoning in a code comment near the publication DDL rather than an ADR — it's
   an operational note, not an architectural decision.

7. **Run the existing 69-test suite against live Postgres, not just in-memory DuckDB.** Add a
   Postgres-backed test tier (a `docker compose` Postgres fixture, or reuse the Phase 4.0
   service) so `test_db.py` exercises the Postgres branch of every method it currently only
   exercises against DuckDB.

**Deliverable:** `python -m simulator.main --bootstrap` and `--historical 1` succeed against the
live Postgres service. `--stream --duration 120` produces a visible trickle of discrete
`UPDATE`s — `SELECT * FROM order_events ORDER BY event_timestamp DESC LIMIT 20` shows staggered,
non-simultaneous timestamps, not one batch landing at once. Full test suite green against both
DuckDB and Postgres.

---

#### Phase 4b — Debezium Connector + Avro/Schema Registry (ADR-024)

1. Register the Postgres source connector via the Kafka Connect REST API (`POST
   localhost:8083/connectors`): `plugin.name: pgoutput`, `slot.name`, `publication.name:
   dbz_publication`, `publication.autocreate.mode: disabled` (the publication is already
   created by `bootstrap_schema()` in 4a — fail loud if it's ever missing rather than
   autocreate a mismatched one), `table.include.list: public.orders,public.order_items,
   public.payments` (corrected per the erratum above), `snapshot.mode: never` (Debezium 2.5.x
   naming — 3.x renamed this to `no_data`; only stream new changes, skip an initial snapshot
   of the ~250K+ rows already in these tables from Phase 2's bulk load and Phase 4a's testing).
2. `key.converter` / `value.converter`: `io.confluent.connect.avro.AvroConverter`,
   `*.schema.registry.url` pointed at the `schema-registry` service (per-connector override is
   redundant if already set at the worker level in 4.0, but set explicitly here for clarity).
3. Set subject compatibility mode to `BACKWARD` for the three connector subjects via the
   Schema Registry REST API (`PUT /config/<subject>`).
4. Validate topics: `retail.public.orders`, `retail.public.order_items`,
   `retail.public.payments` are created once stream mode (from 4a) starts producing writes.
5. Inspect one message per topic with `kafka-avro-console-consumer` — confirm the schema-ID
   wire prefix and the Debezium before/after payload envelope.
6. **Erratum on top of 4a's `REPLICA IDENTITY DEFAULT is sufficient` reasoning:** it isn't.
   That reasoning only considered DELETEs (this schema has none). `REPLICA IDENTITY DEFAULT`
   also means every `UPDATE`'s `before` image is `null` regardless of deletes — confirmed
   empirically once real messages were inspected. Fixed by switching `orders`, `order_items`,
   `payments` to `REPLICA IDENTITY FULL` (now part of `db.py`'s `_ensure_publication`, so it's
   applied on every bootstrap, not a one-off manual fix).
7. **See the flow without Snowflake:** `scripts/cdc_tail.py` — a standalone consumer that
   deserializes Avro against the registry and pretty-prints every `CREATE`/`UPDATE`/`DELETE`
   (table, key, changed fields) live, so the CDC flow is directly observable before Phase 4c's
   Snowflake consumer exists. A fresh consumer group per run (default: only new events from
   now on; `--replay` opts into a fixed group + full history instead).

**Key Concepts:**
- Debezium event structure (before/after payloads, op codes: `c` / `u` / `d`)
- Kafka topic naming: `<topic.prefix>.<schema>.<table>`
- Avro schema definition and wire format (schema ID prefix + binary payload)
- Schema Registry compatibility modes (`BACKWARD` / `FORWARD` / `FULL`) and what each permits
- `pgoutput` as the native Postgres logical decoding plugin — no extension install required
- `REPLICA IDENTITY FULL` vs `DEFAULT` — what Postgres actually captures in the WAL for an
  `UPDATE`'s old row, independent of whether the table ever sees `DELETE`s

**Deliverable:** Three Kafka topics receiving Avro-encoded CDC events as simulator stream mode
(from 4a) runs. `curl localhost:8081/subjects` shows three registered subjects, all `BACKWARD`.
`scripts/cdc_tail.py` shows real `CREATE`/`UPDATE` events with correct field-level diffs while
stream mode runs, with no Snowflake connection involved.

---

#### Phase 4c — CDC Consumer + Snowflake MERGE

1. Python consumer (`confluent-kafka` + `AvroDeserializer`) — consumer group ID and offset
   strategy (`earliest`, so a restart replays from the last committed offset rather than
   silently skipping) documented in code comments per the Pipeline Engineer's behavioral rules.
2. Handle Debezium op codes `c` / `u` / `d` explicitly. This schema has no hard deletes today
   (per the 4a replica-identity note) — the `d` path should log and no-op deliberately, not
   silently swallow a code path that can't currently be exercised.
3. Dead-letter topic/table for malformed or unparseable events — never silently dropped.
4. `MERGE` into `RAW.retail.*` in Snowflake, keyed by each table's PK — idempotent, replay-safe.
   Every MERGE stamps a `_cdc_loaded_at` (`CURRENT_TIMESTAMP()`) column — needed by the
   reconciliation check in step 6, not optional bookkeeping.
5. Run `dbt run --select fct_orders+` incrementally — confirm rows are picked up with no
   full-refresh required.
6. **CDC reconciliation via the Postgres event log.** `order_events`/`payment_events` are
   deliberately excluded from `dbz_publication` (4a) — they never flow through Debezium/Kafka/
   this consumer, which makes them an independent oracle rather than a check that could pass
   even if the pipeline drops the same events every time. Two checks, both needing Postgres +
   Snowflake connections in the same process/session:
   - **Correctness:** `SELECT DISTINCT ON (order_id) order_id, new_state, event_timestamp FROM
     order_events ORDER BY order_id, event_timestamp DESC` (Postgres) — the last known state per
     order — diffed against `RAW.retail.orders.order_state` (Snowflake) for the same `order_id`.
     A mismatch is either lag or a dropped message; step below disambiguates.
   - **Lag:** `snowflake._cdc_loaded_at - postgres.order_events.event_timestamp`, per order —
     real end-to-end pipeline latency, not a guess.
   - Delivered as **both** a reusable script (`scripts/validate_cdc_reconciliation.py`) and a
     notebook (`notebooks/02_cdc_reconciliation.ipynb`, matching the
     `01_simulator_data_quality.ipynb` convention) that imports the script's query logic for
     visualization — one source of truth for the queries, two ways to run them.

**Key Concepts:**
- MERGE/upsert in Snowflake for CDC targets
- Incremental model deduplication via `unique_key`
- How the initial bulk load (Phase 2) and CDC (Phase 4) connect — offset management
- Validating a pipeline against data that never passed through it, vs. re-checking a system
  against itself

**Deliverable:** Order status changes written by the simulator's stream mode (Postgres) appear
in `fct_orders` after an incremental `dbt run`, with no full-refresh required.
`validate_cdc_reconciliation.py` (and the notebook) show zero state mismatches and a lag
distribution consistent with `compression_ratio`-scaled transition delays.

---

#### Phase 4d — Schema Evolution Exercise

1. **Accepted change:** `ALTER TABLE orders ADD COLUMN gift_wrap BOOLEAN;` in Postgres. Confirm
   the registry accepts the new Avro schema version under `BACKWARD` compatibility (new field is
   nullable) and the consumer from 4c keeps deserializing without a redeploy.
2. **Rejected change:** attempt a breaking change (e.g., `ALTER TABLE orders ALTER COLUMN
   total_amount TYPE TEXT;` or drop an existing column). Confirm the registry rejects the write
   under `BACKWARD` compatibility.
3. Re-run `validate_cdc_reconciliation.py` after the accepted change — proves the pipeline is
   still correctly landing state (not just that the registry accepted the schema) with the new
   column flowing through end to end.
4. Document all outcomes — the resulting compatibility error message, and what a consumer
   would have seen without Schema Registry in place — in `docs/runbook.md`.

**Deliverable:** One accepted schema evolution and one rejected breaking change, both observed
and documented. This is the concrete artifact that makes "schema evolution and compatibility
contracts" a defensible interview talking point (per ADR-024's stated goal) rather than a
name-drop.

---

### Phase 5 — Airflow Orchestration (Days 16-18, ~8 hours)

**Goal:** Airflow with Cosmos orchestrates the full pipeline. The simulator's streaming mode is the event source; Airflow schedules the dbt runs.

Branch: `feature/phase-5-airflow-orchestration`

**Resource checkpoint:** Astro Runtime adds ~2-3GB RAM. If constrained, pause Kafka + Debezium during Airflow exercises — they are not needed simultaneously.

#### DAG 1: `retail_fulfillment_pipeline` (@daily)
```
check_source_freshness  (SnowflakeOperator)
    → validate_row_counts  (PythonOperator — XCom: counts dict)
    → branch: skip_if_no_changes | proceed
    → dbt_staging  (Cosmos DbtTaskGroup)
    → dbt_intermediate  (Cosmos DbtTaskGroup)
    → dbt_marts  (Cosmos DbtTaskGroup)
    → dbt_tests  (Cosmos — per-model, automatic)
    → notify  (PythonOperator)
```

#### DAG 2: `retail_snowflake_maintenance` (@weekly)
```
dbt_snapshots  (Cosmos)
    → dbt_source_freshness  (BashOperator)
    → snowflake_housekeeping  (SnowflakeOperator — CLONE dev from prod)
```

#### Airflow Concepts Demonstrated
| Concept | Where Used |
|---------|-----------|
| Cosmos DbtTaskGroup | Model-level tasks, `ref()` dependency ordering |
| Connections | Snowflake, Postgres, Slack webhook |
| Variables | `snowflake_warehouse`, `dbt_project_dir` |
| XComs | Row counts from validation to branch decision |
| Branching | Skip if no source changes |
| Retries + backoff | Snowflake load tasks |
| SLAs | dbt run within 2 hours |
| Sensors | Wait for CDC batch before triggering load |

**Deliverable:** Both DAGs run end-to-end. Airflow UI at `localhost:8080` shows model-level Cosmos task graph.

---

### Phase 6 — Polish & Portfolio (Days 19-20, ~4 hours)

Branch: `feature/phase-6-portfolio-polish`

1. README: architecture diagram, dbt lineage screenshot, `docker compose up` quickstart
2. Incident runbook (`docs/runbook.md`): CDC lag, dbt test failure, Snowflake warehouse stall
3. Performance exercise: profile a slow mart model, add clustering key, show Snowflake query profile before/after
4. Data quality story: introduce duplicate `order_id` in simulator → dbt test catches it → fix and re-run — interview narrative

**Deliverable:** Public repo presentable as a portfolio artifact. Full stack starts with `docker compose up`.

---

### Phase 7 — Stretch: Iceberg + Trino Lakehouse Migration (optional, post-Phase 6)

**Goal:** Migrate the Snowflake mart layer to an open lakehouse architecture using Apache Iceberg as the table format and Trino as the query engine. Demonstrate that the dbt transformation logic is largely portable across execution engines by swapping the adapter.

Branch: `feature/phase-7-iceberg-trino`

**Status:** Under consideration — see ADR-023 for open questions and proposed scope.

#### Motivation

Iceberg + Trino (or Spark) is the dominant open lakehouse pattern at companies running large-scale data platforms. Demonstrating a migration story — same dbt DAG, same SQL, different adapter — directly answers the "what happens when you need to move off Snowflake?" interview question.

#### Infrastructure (Docker Compose additions)

| Service | Role |
|---------|------|
| **MinIO** | S3-compatible local object store — holds Iceberg data files |
| **Nessie** | Iceberg catalog — tracks table metadata, supports Git-like branching |
| **Trino** | Distributed SQL query engine — reads/writes Iceberg tables via Nessie connector |

#### Migration steps

1. Export Snowflake marts to Parquet (reuse the `export_duckdb.py` pattern from Phase 2a)
2. Upload Parquet to MinIO; register as Iceberg tables in Nessie
3. Add a `trino` profile output to `profiles.yml` pointing at the local Trino cluster
4. Install `dbt-trino`; run `dbt build --target trino`
5. Validate results: same metric queries, same output from both Snowflake and Trino paths
6. Document what changed (adapter, catalog config, any dialect guards) vs. what didn't (model SQL, DAG, tests, MetricFlow definitions)

#### Key Concepts Demonstrated

| Concept | Why It Matters |
|---------|---------------|
| Apache Iceberg table format | Open standard — data readable by any engine (Trino, Spark, Snowflake, DuckDB) |
| Nessie catalog | Git-like branching for data — create a branch, test a migration, merge or discard |
| `dbt-trino` adapter | Portable transformation logic — DAG and SQL survive an engine swap |
| MinIO as local S3 | Test object-store patterns without cloud costs |
| Two-engine comparison | Same query, same result, different execution path — the migration proof point |

**Deliverable:** `dbt build --target trino` passes all models and tests. `mf query --metrics revenue --group-by metric_time__week` returns identical results against both Snowflake and Trino targets.

---

### Phase 8 — Stretch: Local Dev Target (DuckDB or Postgres) to Minimize Snowflake Cost

**Goal:** Add a cheap local dev target so that day-to-day `dbt run` iteration never touches Snowflake credits or prod tables. CI and prod continue to target Snowflake; local development targets DuckDB or Postgres.

Branch: `feature/phase-8-local-dev-target`

**Status:** Under consideration — see ADR-022 for option analysis.

#### Motivation

Snowflake trial credits are finite. Aggressive local iteration (debugging a model, iterating on a macro, running tests) should be free. The `DBT_TARGET` environment variable pattern — `dev` points at DuckDB/Postgres, `prod` points at Snowflake — is a common real-world setup and worth demonstrating explicitly.

#### Option A — DuckDB

```yaml
# profiles.yml addition
retail_analytics:
  outputs:
    dev:
      type: duckdb
      path: /workspace/retail_analytics/dev.duckdb
      threads: 4
    prod:
      type: snowflake
      # ... existing Snowflake config
  target: "{{ env_var('DBT_TARGET', 'dev') }}"
```

**Trade-off:** DuckDB dialect diverges from Snowflake on `TABLE(GENERATOR(...))`, some window functions, and Snowflake-specific materializations. Models using these constructs need `{{ target.type == 'snowflake' }}` guards.

#### Option B — Postgres

```yaml
dev:
  type: postgres
  host: localhost
  port: 5432
  dbname: retail_dev
  # ... rest of Postgres config
```

**Trade-off:** More standard SQL dialect than DuckDB; closer to what Phase 4 CDC work will use against the operational Postgres. Requires Docker running locally.

#### Key Concepts Demonstrated

| Concept | Why It Matters |
|---------|---------------|
| Multi-target `profiles.yml` | Isolate dev from prod; control via env var |
| `{{ target.type }}` guards | Dialect-aware SQL for cross-adapter compatibility |
| Credit-aware development | Local dev = free; CI/prod = intentional Snowflake spend |

---

## CI/CD Summary

| Stage | Tool | Trigger | What Runs |
|-------|------|---------|-----------|
| Pre-commit | pre-commit + SQLFluff | Every local commit | SQL lint, YAML validation |
| Pull Request | GitHub Actions (`ci.yml`) | PR open / push to PR branch | SQLFluff, `dbt build --select state:modified+` |
| Merge to main | GitHub Actions (`cd.yml`) | Push to `main` | Full `dbt build`, `dbt test`, `dbt docs generate`, manifest upload |
| Secrets | GitHub Actions secrets | All workflows | Snowflake creds — never in code |

---

## Interview Narrative (Target)

> "I built an end-to-end modern data stack for retail e-commerce fulfillment, starting from first principles. The source is a Python event simulator I wrote — it models the order lifecycle as a state machine and can run in accelerated mode to generate a year of history in minutes, or in streaming mode to produce a live event drip. CDC via Debezium and Kafka streams those changes into Snowflake, with events Avro-encoded and validated against a Schema Registry so schema changes on the source are caught at write time instead of breaking consumers downstream. I built 20 dbt models across staging, intermediate, and marts — SCD Type 2 snapshots, incremental fact tables, custom data quality tests — and a semantic layer on top using MetricFlow: six business metrics defined once in YAML, queryable via the dbt CLI or published as native Snowflake Semantic Views so any SQL client can consume them without re-implementing the logic. Airflow with Astronomer Cosmos orchestrates it at model-level granularity. GitHub Actions runs dbt slim CI on every PR. The whole stack runs in Docker."

---

## Open Items

| # | Item | Status |
|---|------|--------|
| 1 | Snowflake trial account creation timing | Defer to start of Phase 2 |
| 2 | CI Snowflake schema strategy — shared dev schema vs. ephemeral per-PR | Decide at Phase 3 |
| 3 | Confirm RAM headroom before Phase 5 (Airflow) | Check at Phase 4 completion |
| 4 | Slack workspace for Airflow notifications | Optional — substitute log-only |
| 5 | Local dev target (DuckDB vs Postgres) to minimize Snowflake credit burn | Under consideration — ADR-022 |
| 6 | Iceberg + Trino lakehouse migration as stretch phase | Under consideration — ADR-023 |
