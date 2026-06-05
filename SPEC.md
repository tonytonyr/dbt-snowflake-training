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
