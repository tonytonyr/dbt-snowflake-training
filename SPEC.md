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
| 5 | CDC from a Postgres operational database into Snowflake via Kafka + Debezium |
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
│                          CDC events: c / u / d                  │
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
| Airflow | Astro Runtime + Cosmos | Phase 4+ | ~2-3 GB |
| **Phase 0-1 total** | | | **~128 MB** |
| **Phase 2-3 total** | | | **~384 MB** |
| **Phase 4 total** | | | **~1.5 GB** |
| **Phase 4+ (Airflow) total** | | | **~4-4.5 GB** |

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
fct_orders (mart)  →  semantic model (entities + measures)  →  metrics YAML  →  dbt sl query / BI tool
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
dbt sl list metrics

# Query revenue by week
dbt sl query --metrics revenue --group-by metric_time__week

# Query AOV by product category
dbt sl query --metrics average_order_value --group-by product_category

# Return rate month over month
dbt sl query --metrics return_rate --group-by metric_time__month --order metric_time__month
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

**Comparison exercise:** Query the same metric two ways — `dbt sl query` (MetricFlow path) vs. direct Snowflake Semantic View SQL. Observe identical results, different execution paths.

#### Key Concepts Demonstrated

| Concept | Why It Matters |
|---------|---------------|
| Single metric definition | Revenue computed identically in every BI tool |
| MetricFlow time spine | Consistent grain control across all time-series metrics |
| Derived metrics | Composing complex metrics from simpler building blocks |
| Saved queries | BI-ready metric packs without ad-hoc query sprawl |
| Snowflake Semantic Views | Native Snowflake objects — no dbt runtime needed at query time |
| dbt vs. Snowflake paths | Two valid approaches; knowing both is the interview differentiator |

**Deliverable:** `dbt sl list metrics` returns all 6 metrics. `dbt sl query --metrics revenue --group-by metric_time__week` returns correct weekly totals matching raw SQL against `fct_orders`. Snowflake Semantic Views visible in the Snowflake UI.

---

### Phase 4 — CDC Ingestion (Days 13-15, ~8 hours)

**Goal:** Postgres → Debezium → Kafka → Snowflake CDC pipeline live. The simulator's streaming mode drives continuous change events through the full stack.

Branch: `feature/phase-4-cdc-pipeline`

1. Add Kafka (KRaft) + Debezium Connect to Docker Compose
2. Configure Debezium connector on `orders`, `order_items`, `returns`
3. Python consumer reads CDC events from Kafka, upserts to `RAW.retail` in Snowflake via MERGE
4. Start simulator in streaming mode — watch events flow end-to-end
5. Run `dbt run --select fct_orders+` incrementally — confirm rows picked up

**Key Concepts:**
- Debezium event structure (before/after payloads, op codes: `c` / `u` / `d`)
- Kafka topic naming: `<server>.<schema>.<table>`
- MERGE/upsert in Snowflake for CDC targets
- Incremental model deduplication via `unique_key`
- How the initial bulk load (Phase 2) and CDC (Phase 4) connect — offset management

**Deliverable:** Simulator streaming mode running. Order status changes in Postgres appear in `fct_orders` after an incremental dbt run, with no full-refresh required.

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

## CI/CD Summary

| Stage | Tool | Trigger | What Runs |
|-------|------|---------|-----------|
| Pre-commit | pre-commit + SQLFluff | Every local commit | SQL lint, YAML validation |
| Pull Request | GitHub Actions (`ci.yml`) | PR open / push to PR branch | SQLFluff, `dbt build --select state:modified+` |
| Merge to main | GitHub Actions (`cd.yml`) | Push to `main` | Full `dbt build`, `dbt test`, `dbt docs generate`, manifest upload |
| Secrets | GitHub Actions secrets | All workflows | Snowflake creds — never in code |

---

## Interview Narrative (Target)

> "I built an end-to-end modern data stack for retail e-commerce fulfillment, starting from first principles. The source is a Python event simulator I wrote — it models the order lifecycle as a state machine and can run in accelerated mode to generate a year of history in minutes, or in streaming mode to produce a live event drip. CDC via Debezium and Kafka streams those changes into Snowflake. I built 20 dbt models across staging, intermediate, and marts — SCD Type 2 snapshots, incremental fact tables, custom data quality tests — and a semantic layer on top using MetricFlow: six business metrics defined once in YAML, queryable via the dbt CLI or published as native Snowflake Semantic Views so any SQL client can consume them without re-implementing the logic. Airflow with Astronomer Cosmos orchestrates it at model-level granularity. GitHub Actions runs dbt slim CI on every PR. The whole stack runs in Docker."

---

## Open Items

| # | Item | Status |
|---|------|--------|
| 1 | Snowflake trial account creation timing | Defer to start of Phase 2 |
| 2 | CI Snowflake schema strategy — shared dev schema vs. ephemeral per-PR | Decide at Phase 3 |
| 3 | Confirm RAM headroom before Phase 5 (Airflow) | Check at Phase 4 completion |
| 4 | Slack workspace for Airflow notifications | Optional — substitute log-only |
