-- =============================================================================
-- Bulk Load — COPY INTO from Internal Stages
--
-- Prerequisites:
--   1. setup.sql has been run (tables, stages, file formats exist)
--   2. Files have been PUT into the correct stages (see commands below)
--
-- PUT commands (run from SnowSQL CLI or VS Code Snowflake extension):
--
--   -- CSV files
--   PUT file:///path/to/exports/addresses.csv      @RAW.RETAIL.stg_csv AUTO_COMPRESS=FALSE;
--   PUT file:///path/to/exports/customers.csv      @RAW.RETAIL.stg_csv AUTO_COMPRESS=FALSE;
--   PUT file:///path/to/exports/products.csv       @RAW.RETAIL.stg_csv AUTO_COMPRESS=FALSE;
--
--   -- Flat Parquet files
--   PUT file:///path/to/exports/orders.parquet     @RAW.RETAIL.stg_parquet AUTO_COMPRESS=FALSE;
--   PUT file:///path/to/exports/order_items.parquet @RAW.RETAIL.stg_parquet AUTO_COMPRESS=FALSE;
--   PUT file:///path/to/exports/payments.parquet   @RAW.RETAIL.stg_parquet AUTO_COMPRESS=FALSE;
--
--   -- Hive-partitioned Parquet (upload entire directory tree)
--   PUT file:///path/to/exports/order_events/year=2024/month=6/data_0.parquet
--       @RAW.RETAIL.stg_parquet_hive/order_events/year=2024/month=6/ AUTO_COMPRESS=FALSE;
--   ... repeat for each partition, or use a shell loop (see load_partitions.ps1)
--
-- =============================================================================

USE ROLE LOADER;
USE WAREHOUSE LOADING_WH;
USE DATABASE RAW;
USE SCHEMA RETAIL;


-- =============================================================================
-- 1. CSV LOADS — addresses, customers, products
-- =============================================================================

COPY INTO addresses (
    address_id,
    street_address,
    city,
    state,
    postal_code,
    country
)
FROM @stg_csv/addresses.csv
FILE_FORMAT = (FORMAT_NAME = ff_csv)
ON_ERROR = ABORT_STATEMENT;

COPY INTO customers (
    customer_id,
    first_name,
    last_name,
    email,
    address_id,
    created_at
)
FROM @stg_csv/customers.csv
FILE_FORMAT = (FORMAT_NAME = ff_csv)
ON_ERROR = ABORT_STATEMENT;

COPY INTO products (
    product_id,
    sku,
    name,
    price,
    cost_price,
    category
)
FROM @stg_csv/products.csv
FILE_FORMAT = (FORMAT_NAME = ff_csv)
ON_ERROR = ABORT_STATEMENT;


-- =============================================================================
-- 2. FLAT PARQUET LOADS — orders, order_items, payments
--
-- Parquet column names must match table column names exactly.
-- Use $1:<column>::<type> syntax to cast from Parquet variant values.
-- =============================================================================

COPY INTO orders (
    order_id,
    customer_id,
    order_state,
    order_date,
    updated_at,
    subtotal,
    tax,
    shipping_cost,
    total_amount,
    shipping_address_id,
    is_stuck,
    stuck_reason
)
FROM (
    SELECT
        $1:order_id::VARCHAR,
        $1:customer_id::VARCHAR,
        $1:order_state::VARCHAR,
        $1:order_date::TIMESTAMP_TZ,
        $1:updated_at::TIMESTAMP_TZ,
        $1:subtotal::NUMBER(12,2),
        $1:tax::NUMBER(12,2),
        $1:shipping_cost::NUMBER(12,2),
        $1:total_amount::NUMBER(12,2),
        $1:shipping_address_id::VARCHAR,
        $1:is_stuck::BOOLEAN,
        $1:stuck_reason::VARCHAR
    FROM @stg_parquet/orders.parquet
)
FILE_FORMAT = (FORMAT_NAME = ff_parquet)
ON_ERROR = ABORT_STATEMENT;

COPY INTO order_items (
    order_item_id,
    order_id,
    product_id,
    quantity,
    unit_price,
    total_price
)
FROM (
    SELECT
        $1:order_item_id::VARCHAR,
        $1:order_id::VARCHAR,
        $1:product_id::VARCHAR,
        $1:quantity::INTEGER,
        $1:unit_price::NUMBER(10,2),
        $1:total_price::NUMBER(12,2)
    FROM @stg_parquet/order_items.parquet
)
FILE_FORMAT = (FORMAT_NAME = ff_parquet)
ON_ERROR = ABORT_STATEMENT;

COPY INTO payments (
    payment_id,
    order_id,
    payment_state,
    amount,
    payment_method,
    payment_date,
    authorization_date,
    capture_date,
    refund_date,
    failure_reason,
    retry_count
)
FROM (
    SELECT
        $1:payment_id::VARCHAR,
        $1:order_id::VARCHAR,
        $1:payment_state::VARCHAR,
        $1:amount::NUMBER(12,2),
        $1:payment_method::VARCHAR,
        $1:payment_date::TIMESTAMP_TZ,
        $1:authorization_date::TIMESTAMP_TZ,
        $1:capture_date::TIMESTAMP_TZ,
        $1:refund_date::TIMESTAMP_TZ,
        $1:failure_reason::VARCHAR,
        $1:retry_count::INTEGER
    FROM @stg_parquet/payments.parquet
)
FILE_FORMAT = (FORMAT_NAME = ff_parquet)
ON_ERROR = ABORT_STATEMENT;


-- =============================================================================
-- 3. HIVE-PARTITIONED PARQUET LOADS — order_events, payment_events
--
-- The Parquet files do not contain year/month columns — those values live in
-- the directory path (year=YYYY/month=M). We parse them from METADATA$FILENAME
-- using REGEXP_SUBSTR and reconstruct event_timestamp from the file data only
-- (the partition path is used for pruning, not stored in the table).
--
-- PATTERN matches all data_*.parquet files under any year=/month= partition.
-- =============================================================================

COPY INTO order_events (
    event_id,
    order_id,
    previous_state,
    new_state,
    event_timestamp,
    reason,
    retry_count
)
FROM (
    SELECT
        $1:event_id::VARCHAR,
        $1:order_id::VARCHAR,
        $1:previous_state::VARCHAR,
        $1:new_state::VARCHAR,
        $1:event_timestamp::TIMESTAMP_TZ,
        $1:reason::VARCHAR,
        $1:retry_count::NUMBER
    FROM @stg_parquet_hive/order_events/
)
FILE_FORMAT  = (FORMAT_NAME = ff_parquet_hive)
PATTERN      = '.*order_events/year=.*/month=.*/data_.*\\.parquet'
ON_ERROR     = ABORT_STATEMENT;

COPY INTO payment_events (
    event_id,
    payment_id,
    previous_state,
    new_state,
    event_timestamp,
    failure_reason,
    retry_attempt
)
FROM (
    SELECT
        $1:event_id::VARCHAR,
        $1:payment_id::VARCHAR,
        $1:previous_state::VARCHAR,
        $1:new_state::VARCHAR,
        $1:event_timestamp::TIMESTAMP_TZ,
        $1:failure_reason::VARCHAR,
        $1:retry_attempt::NUMBER
    FROM @stg_parquet_hive/payment_events/
)
FILE_FORMAT  = (FORMAT_NAME = ff_parquet_hive)
PATTERN      = '.*payment_events/year=.*/month=.*/data_.*\\.parquet'
ON_ERROR     = ABORT_STATEMENT;


-- =============================================================================
-- 4. VERIFICATION
-- =============================================================================

SELECT 'addresses'     AS tbl, COUNT(*) AS row_count FROM addresses
UNION ALL
SELECT 'customers',    COUNT(*) FROM customers
UNION ALL
SELECT 'products',     COUNT(*) FROM products
UNION ALL
SELECT 'orders',       COUNT(*) FROM orders
UNION ALL
SELECT 'order_items',  COUNT(*) FROM order_items
UNION ALL
SELECT 'payments',     COUNT(*) FROM payments
UNION ALL
SELECT 'order_events', COUNT(*) FROM order_events
UNION ALL
SELECT 'payment_events', COUNT(*) FROM payment_events
ORDER BY tbl;
