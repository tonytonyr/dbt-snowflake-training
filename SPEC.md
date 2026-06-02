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
| 4 | CDC from a Postgres operational database into Snowflake via Kafka + Debezium |
| 5 | Airflow orchestration of the full pipeline using Astronomer Cosmos for dbt integration |
| 6 | CI/CD with GitHub Actions — SQL linting, dbt slim CI on PR, full build on merge |
| 7 | GitHub best practices — branching strategy, PRs, commit conventions, branch protection |

---

## Domain: Retail E-Commerce Fulfillment

Chosen because the business logic maps directly to Amazon retail/forecasting experience — cognitive load stays on the new tools, not the domain. Maps well to target employers (DoorDash, Instacart, DSG, Visa).

### Source Schema (8 tables — live in Postgres operational store)

```
customers              products
├── customer_id (PK)   ├── product_id (PK)
├── name               ├── name
├── email              ├── category_id → categories
├── address_line1      ├── supplier_id  → suppliers
├── city               ├── unit_cost
├── state              ├── list_price
├── zip                └── effective_date (SCD Type 2 candidate)
├── segment
└── acquired_channel

orders                 order_items
├── order_id (PK)      ├── order_item_id (PK)
├── customer_id →      ├── order_id → orders
├── order_date         ├── product_id → products
├── status             ├── quantity
│   (placed/confirmed/ ├── unit_price
│    shipped/delivered/└── discount
│    returned)
├── total_amount
└── payment_status

inventory              shipments
├── warehouse_id       ├── shipment_id (PK)
├── product_id →       ├── order_id → orders
├── quantity_on_hand   ├── carrier
├── quantity_reserved  ├── tracking_number
└── snapshot_date      ├── shipped_date
                       ├── estimated_delivery
                       └── actual_delivery

returns                payments
├── return_id (PK)     ├── payment_id (PK)
├── order_id → orders  ├── order_id → orders
├── return_reason      ├── payment_type (card/gift/wallet)
├── refund_amount      ├── amount
├── disposition        ├── processor_response
└── returned_date      └── timestamp
```

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
| Operational DB | Postgres 16 | Phase 1 | ~256 MB |
| E-Commerce Simulator | Python (Docker) | Phase 1 | ~128 MB |
| Cloud Warehouse | Snowflake (trial) | Phase 2 | (external) |
| dbt Core | VS Code Dev Container | Phase 2 | ~256 MB |
| Kafka | Kafka 3.x (KRaft — no ZooKeeper) | Phase 3 | ~512 MB |
| CDC | Debezium Connect | Phase 3 | ~512 MB |
| Airflow | Astro Runtime + Cosmos | Phase 4 | ~2-3 GB |
| **Phase 0-1 total** | | | **~384 MB** |
| **Phase 2 total** | | | **~640 MB** |
| **Phase 3 total** | | | **~1.5 GB** |
| **Phase 4 total** | | | **~4-4.5 GB** |

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
│   │   └── cents_to_dollars.sql
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

### Phase 1 — Operational Store & E-Commerce Simulator (Days 2-4, ~6 hours)

**Goal:** A running Postgres database backed by a Python simulator that can generate realistic historical data in accelerated mode and produce a live event stream in streaming mode. This is the source of truth the rest of the stack is built on.

#### Postgres Schema
- All 8 tables with correct constraints: PKs, FKs, `NOT NULL` where appropriate, indexes on common filter columns (`customer_id`, `order_date`, `status`)
- Schema applied via `simulator/schema.sql` — idempotent (`CREATE TABLE IF NOT EXISTS`)

#### E-Commerce Simulator

The simulator is a Python application with two operating modes. All writes go to Postgres only — Snowflake learns about changes exclusively through the CDC pipeline.

**State Machine (`state_machine.py`)**

Orders move through a defined lifecycle — no random inserts:
```
placed → confirmed → shipped → delivered
                                    └──► returned  (configurable % of delivered orders)

payment_status: pending → paid  (on confirmed)
                pending → failed (small %)
```
Invalid transitions are rejected. This is what makes the `accepted_values` dbt test on `status` meaningful — a simulator bug would surface as a test failure.

**Accelerated Historical Mode**
```
python simulator.py --mode historical --days 365 --acceleration 1000
```
- Simulates 1 year of activity compressed to ~minutes
- Generates: ~5K customers, ~1K products, ~50K orders, ~200K order items
- Produces proportional inventory snapshots, shipments, payments, returns
- Writes directly to Postgres; outputs a completion summary (row counts per table)

**Streaming Mode**
```
python simulator.py --mode stream --rate 10  # 10 new orders/minute
```
- Runs indefinitely at wall-clock pace (configurable rate)
- Emits new orders, advances existing order statuses, generates payments and returns on schedule
- Designed to keep Debezium busy with a realistic event drip
- Graceful shutdown on `SIGTERM` (Docker stop compatible)

**Configuration** (via `.env`):
- `SIM_CUSTOMERS`, `SIM_PRODUCTS` — population sizes
- `SIM_RETURN_RATE` — % of delivered orders that generate a return (default 8%)
- `SIM_PAYMENT_FAILURE_RATE` — % of payments that fail (default 2%)
- `SIM_STREAM_RATE` — new orders per minute in streaming mode

#### Delivered via PR
Branch: `feature/phase-1-postgres-simulator`

**Deliverable:** `docker compose up postgres simulator` runs clean. Accelerated mode populates all 8 tables. Streaming mode produces a visible drip of new rows queryable in Postgres. Row counts and relationships are valid.

---

### Phase 2 — Snowflake + dbt Foundation (Days 5-7, ~8 hours)

**Goal:** Snowflake configured, initial data loaded from Postgres, and the full staging layer running in dbt.

Branch: `feature/phase-2-snowflake-dbt-staging`

1. Create Snowflake trial account
2. Run `snowflake_setup/setup.sql`: warehouse, databases, schemas, roles, grants
3. Initial bulk extract from Postgres → load to `RAW.retail.*` (historical backfill; CDC handles everything after)
4. Set up VS Code Dev Container with dbt Core + dbt-snowflake adapter
5. Configure `profiles.yml` (dev: `ANALYTICS.staging_dev`, prod: `ANALYTICS.staging`)
6. `dbt debug` — confirm connectivity
7. Build all 8 staging models; declare sources with freshness thresholds

**Deliverable:** `dbt run --select staging.*` succeeds. `RAW.retail.*` row counts match Postgres.

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
| Macros | `generate_schema_name()`, `cents_to_dollars()` |
| Packages | `dbt_utils`: surrogate keys, date macros |
| Docs | Column descriptions on all mart models; two exposures |

#### CI/CD (GitHub Actions)
- `ci.yml`: PR trigger → SQLFluff lint → `dbt build --select state:modified+` vs CI Snowflake schema
- `cd.yml`: merge to `main` → full `dbt build` → `dbt docs generate` → upload `manifest.json` artifact (used for slim CI state comparison on next PR)
- Snowflake credentials stored as GitHub Actions secrets — never in code

**Deliverable:** `dbt build --full-refresh` passes all tests. PRs to `main` require green CI.

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

> "I built an end-to-end modern data stack for retail e-commerce fulfillment, starting from first principles. The source is a Python event simulator I wrote — it models the order lifecycle as a state machine and can run in accelerated mode to generate a year of history in minutes, or in streaming mode to produce a live event drip. CDC via Debezium and Kafka streams those changes into Snowflake. I built 20 dbt models across staging, intermediate, and marts — SCD Type 2 snapshots, incremental fact tables, custom data quality tests. Airflow with Astronomer Cosmos orchestrates it at model-level granularity. GitHub Actions runs dbt slim CI on every PR. The whole stack runs in Docker."

---

## Open Items

| # | Item | Status |
|---|------|--------|
| 1 | Snowflake trial account creation timing | Defer to start of Phase 2 |
| 2 | CI Snowflake schema strategy — shared dev schema vs. ephemeral per-PR | Decide at Phase 3 |
| 3 | Confirm RAM headroom before Phase 5 (Airflow) | Check at Phase 4 completion |
| 4 | Slack workspace for Airflow notifications | Optional — substitute log-only |
