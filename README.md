# dbt-snowflake-training

A portfolio-grade modern data stack for retail e-commerce fulfillment, built
to close skill gaps in dbt and Snowflake and demonstrate production-representative
data engineering patterns.

## Stack

| Layer | Technology |
|---|---|
| Operational source | Postgres 16 |
| Event simulation | Python (two-mode: historical backfill + live stream) |
| CDC ingestion | Debezium + Kafka (KRaft) |
| Cloud warehouse | Snowflake |
| Transformation | dbt Core (staging → intermediate → marts) |
| Orchestration | Airflow + Astronomer Cosmos |
| CI/CD | GitHub Actions (slim CI on PR, full build on merge) |

## Domain

Retail e-commerce fulfillment: customers, orders, order items, products,
inventory, shipments, returns, and payments — 8 tables, realistic order
lifecycle modeled as a state machine.

## Status

🚧 Under construction — see [SPEC.md](SPEC.md) for the full build plan.

---

*Full README with architecture diagram, dbt lineage graph, and quickstart
instructions coming in Phase 6.*
