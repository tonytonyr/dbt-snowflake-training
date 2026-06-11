FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    dbt-core==1.8.9 \
    dbt-snowflake==1.8.4 \
    dbt-metricflow[snowflake]==0.7.0 \
    sqlfluff==3.3.0 \
    sqlfluff-templater-dbt==3.3.0 \
    pre-commit