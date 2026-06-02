Here's the accelerated combined learning plan.

---

# Combined Learning Sprint: dbt + Airflow + Snowflake

## Domain Choice: **Retail E-Commerce Fulfillment Pipeline**

This domain is ideal because:
- 6+ years in Amazon retail forecasting — deep schema intuition without learning a new industry
- Naturally complex relationships across customers, products, orders, inventory, payments, returns
- Inherent CDC (order status lifecycle), dimensional modeling (star schema), and time-series patterns
- Maps directly to DoorDash (order lifecycle), Instacart (retail/grocery), DSG (sports retail), and even Visa (payment reconciliation)

---

## Source Schema (Postgres — already running in your Docker project)

**8 tables** with rich relationships:

```
customers              products
├── customer_id (PK)   ├── product_id (PK)
├── name               ├── name
├── email              ├── category_id → categories
├── address_line1      ├── supplier_id  → suppliers
├── city               ├── unit_cost
├── state              ├── list_price
├── zip                 └── effective_date (SCD Type 2)
├── segment
└── acquired_channel

orders                 order_items
├── order_id (PK)      ├── order_item_id (PK)
├── customer_id →      ├── order_id → orders
├── order_date         ├── product_id → products
├── status             ├── quantity
│   (placed/confirmed/ ├── unit_price
│    shipped/delivered/ └── discount
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

**Why this is complex enough:** SCD Type 2 on products, CDC on order status, 5+ fact tables across orders/inventory/returns/payments, conformed dimensions, cross-source reconciliation (payments vs orders vs returns).

---

## Phase 1: Snowflake Warehouse (Days 1-2, ~6-8 hours)

### Day 1 — Snowflake Sandbox Setup
- Create Snowflake trial account (30 days free, $400 credit)
- Set up warehouse (`RETAIL_WH`) — XS, auto-suspend, auto-resume
- Create databases: `RAW`, `STAGING`, `ANALYTICS`
- Create schemas: `RAW.retail`, `STAGING.dbt_staging`, `ANALYTICS.marts`
- Create RBAC roles: `loader`, `transformer`, `analyst`
- Install `snowflake-connector-python` and `dbt-snowflake` locally

### Day 2 — Seed the Source Data
- Generate synthetic retail data (Python script) — 100K orders, 1M line items, 1K products, 10K customers, 2 years of history
- Load to Snowflake `RAW.retail.*` via Python bulk insert
- Verify with exploratory SQL
- Write a stored procedure (`SP_CHECK_FRESHNESS()`) to validate row counts

**Deliverable:** Working Snowflake warehouse with seeded data, roles, and a freshness check proc.

---

## Phase 2: dbt-core Modeling (Days 3-10, ~15-20 hours)

Build a complete dbt project (`retail_analytics`) with 15-20 models across three layers:

### Staging Layer (`staging/` — 8 models, 1:1 with source)

```
stg_retail__customers.sql
stg_retail__products.sql        ← CAST, rename columns, basic cleaning
stg_retail__orders.sql
stg_retail__order_items.sql
stg_retail__inventory.sql       ← snapshot deduplication
stg_retail__shipments.sql       ← handle NULL actual_delivery
stg_retail__returns.sql
stg_retail__payments.sql
```

### Intermediate Layer (`intermediate/` — 4 models)

```
int_orders_enriched.sql         ← join orders + items + products, pre-calc line_total
int_inventory_daily.sql         ← daily snapshot of qty_on_hand per product/warehouse
int_shipments_sla.sql           ← calculate on_time_delivery flag, days_late
int_payment_reconciliation.sql  ← match payments to orders, flag discrepancies
```

### Marts Layer (`marts/` — 6 models)

```
dim_customers.sql               ← SCD Type 2 on address/segment changes
dim_products.sql                ← SCD Type 2 on price changes
dim_date.sql                    ← calendar dimension (day, week, month, quarter, holiday flag)
fct_orders.sql                  ← one row per order, conformed dimensions
fct_inventory_daily.sql         ← fact table for stock-level analysis
fct_returns.sql                 ← returns with reason, refund, disposition
```

### dbt Quality Patterns (must demonstrate)
- **Schema tests:** `unique`, `not_null`, `relationships` (referential integrity), `accepted_values` on `status`
- **Custom tests:** order total = sum(line_items) ± tolerance; return.refund ≤ order.total
- **Macros:** `generate_schema_name()` custom macro for env-aware schemas; `get_custom_schema()` for dev/prod
- **Snapshots:** SCD Type 2 on `dim_customers` and `dim_products` using `dbt snapshot`
- **Incremental models:** `fct_inventory_daily` as incremental (daily snapshots — millions of rows)
- **Documentation:** `dbt docs generate` + `dbt docs serve` — at least 5 models with column-level descriptions
- **Sources:** `sources.yml` declaring freshness thresholds (orders: 1 hour, inventory: 24 hours)
- **Exposures:** define `executive_dashboard` and `operations_dashboard` as exposures

### dbt Project Structure
```
retail_analytics/
├── dbt_project.yml
├── packages.yml              ← dbt_utils installed for surrogate keys, date macros
├── macros/
│   ├── generate_schema_name.sql
│   └── cents_to_dollars.sql  ← reusable macro
├── models/
│   ├── staging/
│   │   ├── sources.yml
│   │   ├── stg_retail__*.sql
│   ├── intermediate/
│   │   ├── int_*.sql
│   └── marts/
│       ├── dim_*.sql
│       ├── fct_*.sql
│       └── exposures.yml
├── tests/
│   └── assert_order_totals_balance.sql
├── snapshots/
│   ├── customers_scd.sql
│   └── products_scd.sql
└── analyses/
    └── return_rate_by_segment.sql
```

**Deliverable:** Complete dbt project targeting Snowflake. Run `dbt build --full-refresh` successfully. Freshness, uniqueness, and referential integrity tests all passing.

---

## Phase 3: Airflow Orchestration (Days 10-12, ~8-10 hours)

Add Airflow to the Docker data lake project to orchestrate the end-to-end pipeline:

### Docker Compose Additions
Add to existing `docker-compose.yml`:
```yaml
  postgres:    ← existing
  debezium:    ← existing
  flink:       ← existing
  spark:       ← existing
  trino:       ← existing
  airflow-webserver:  ← NEW
  airflow-scheduler:  ← NEW
  airflow-init:       ← NEW (runs once)
  redis:              ← NEW (Celery broker)
```

### Airflow DAG: `retail_fulfillment_pipeline`

```
DAG: retail_fulfillment_pipeline
Schedule: @daily
Catchup: False

┌─────────────────────────────────────────────────────────────┐
│ 1. CDC Ingestion                                            │
│    PostgresOperator → check order/return status changes     │
│    (triggers Debezium snapshot via SQL if needed)           │
├─────────────────────────────────────────────────────────────┤
│ 2. Raw Data Validation                                      │
│    PythonOperator → validate_source_row_counts              │
│    PythonOperator → check_schema_drift (column mismatch)    │
├─────────────────────────────────────────────────────────────┤
│ 3. Snowflake Load                                           │
│    PythonOperator → COPY INTO or SnowflakeOperator          │
│    (bulk load changed partitions)                           │
├─────────────────────────────────────────────────────────────┤
│ 4. dbt Transformations                                      │
│    BashOperator → dbt run --select staging.*                │
│    BashOperator → dbt run --select intermediate.*           │
│    BashOperator → dbt run --select marts.*                  │
├─────────────────────────────────────────────────────────────┤
│ 5. dbt Testing                                              │
│    BashOperator → dbt test --select source:* (freshness)    │
│    BashOperator → dbt test --select staging.*               │
│    BashOperator → dbt test --select marts.*                 │
├─────────────────────────────────────────────────────────────┤
│ 6. dbt Docs                                                 │
│    BashOperator → dbt docs generate                         │
├─────────────────────────────────────────────────────────────┤
│ 7. Slack/Notification                                       │
│    PythonOperator → notify on failure/success               │
└─────────────────────────────────────────────────────────────┘
```

### Airflow Concepts to Demonstrate
- **Connections:** Postgres connection, Snowflake connection, Slack webhook
- **Variables:** `snowflake_warehouse`, `dbt_project_dir`, `alert_email`
- **XComs:** pass row counts between tasks for validation
- **Branching:** skip downstream if no source changes detected
- **Retries:** 3 retries with exponential backoff on Snowflake loads
- **SLAs:** dbt run must complete within 2 hours
- **Sensors:** wait for upstream CDC batch completion

### Additional DAG: `retail_snowflake_maintenance`
```
Schedule: @weekly
├── dbt snapshot (SCD tracking)
├── dbt source freshness (all sources)
└── SnowflakeOperator → OPTIMIZE/CLONE/VACUUM
```

**Deliverable:** Two working Airflow DAGs orchestrating the full pipeline. Airflow UI accessible at `localhost:8080`. DAGs execute successfully end-to-end.

---

## Phase 4: Integration & Polish (Days 12-14, ~6-8 hours)

### End-to-End Production Readiness

1. **GitHub repo:** Push the entire project (Docker compose, dbt project, Airflow DAGs, Python scripts, seed data generator) to a public repo
2. **README:** Project architecture diagram, setup instructions, dbt lineage graph screenshot
3. **Add dbt to Docker compose:** `dbt-core` as a service in the compose file so the pipeline is fully self-contained
4. **Write an incident runbook:** What to do if CDC lags, if dbt tests fail, if Snowflake warehouse stalls — demonstrates DataOps mindset
5. **Optimize one dbt model:** Profile query performance, add clustering keys on `dim_date`, show before/after query plans
6. **Document a data quality issue:** Introduce a "bug" in seed data (duplicate order_ids), show how dbt tests catch it, show the fix — this makes a great interview story

**Deliverable:** GitHub repo + README. The whole stack (`docker compose up`) runs end-to-end: CDC → Snowflake → dbt → Airflow → tested marts.

---

## Weekly Timeline

| Week | Days | Focus | Hours |
|------|------|-------|-------|
| **Week 1** | Days 1-2 | Snowflake setup, seed data, first dbt staging models | 6-8 |
| | Days 3-5 | dbt intermediate + marts models, tests, docs | 8-10 |
| **Week 2** | Days 6-7 | dbt snapshots, incremental models, macros, fresh dbt project refactor | 6-8 |
| | Days 8-10 | Airflow Docker setup, first DAG, Postgres → Snowflake load | 8-10 |
| **Week 3** | Days 10-12 | Second DAG, error handling, sensors, retries | 6-8 |
| | Days 12-14 | GitHub repo, README, polish, interview narrative prep | 4-6 |

**Total: ~40 hours over 14 days.**

---

## Interview-Ready Talking Points

After completing this sprint, you can say:

> "I built an end-to-end modern data stack for retail e-commerce fulfillment: Postgres source with CDC via Debezium, Snowflake as the cloud warehouse with RBAC and workload management, 20 dbt models across staging/intermediate/marts layers with SCD Type 2 snapshots, custom data quality tests, and Airflow orchestrating the full pipeline with SLA monitoring and automated retries. The project exercises the exact patterns I'd use on day one."

This directly addresses the top 3 gaps from the cross-role analysis.kk/