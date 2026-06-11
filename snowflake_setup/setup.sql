-- =============================================================================
-- Snowflake Trial Account Setup
-- Run as ACCOUNTADMIN once after account creation.
-- Order matters: roles → warehouses → databases → schemas → grants → objects.
-- =============================================================================


-- =============================================================================
-- 1. ROLES
-- =============================================================================

USE ROLE ACCOUNTADMIN;

CREATE ROLE IF NOT EXISTS LOADER
    COMMENT = 'Owns RAW database; runs COPY INTO for initial bulk load and CDC ingestion';

CREATE ROLE IF NOT EXISTS TRANSFORMER
    COMMENT = 'Runs dbt; owns ANALYTICS database; reads RAW';

CREATE ROLE IF NOT EXISTS REPORTER
    COMMENT = 'Read-only access to ANALYTICS for BI tools and ad-hoc queries';

-- Role hierarchy: SYSADMIN inherits all custom roles so the account admin can
-- operate as any role without switching to ACCOUNTADMIN.
GRANT ROLE LOADER      TO ROLE SYSADMIN;
GRANT ROLE TRANSFORMER TO ROLE SYSADMIN;
GRANT ROLE REPORTER    TO ROLE SYSADMIN;

-- Grant roles to the trial account user (replace YOUR_USERNAME if needed).
GRANT ROLE LOADER      TO USER CURRENT_USER();
GRANT ROLE TRANSFORMER TO USER CURRENT_USER();
GRANT ROLE REPORTER    TO USER CURRENT_USER();


-- =============================================================================
-- 2. WAREHOUSES
-- =============================================================================

-- LOADING_WH: used only during bulk load; suspend immediately after.
CREATE WAREHOUSE IF NOT EXISTS LOADING_WH
    WAREHOUSE_SIZE   = 'XSMALL'
    AUTO_SUSPEND     = 60
    AUTO_RESUME      = TRUE
    INITIALLY_SUSPENDED = TRUE
    COMMENT = 'Bulk load and CDC ingestion warehouse';

-- TRANSFORMING_WH: dbt runs; suspend after 5 minutes idle.
CREATE WAREHOUSE IF NOT EXISTS TRANSFORMING_WH
    WAREHOUSE_SIZE   = 'XSMALL'
    AUTO_SUSPEND     = 300
    AUTO_RESUME      = TRUE
    INITIALLY_SUSPENDED = TRUE
    COMMENT = 'dbt transformation warehouse';

-- REPORTING_WH: ad-hoc queries and Snowflake Task execution.
CREATE WAREHOUSE IF NOT EXISTS REPORTING_WH
    WAREHOUSE_SIZE   = 'XSMALL'
    AUTO_SUSPEND     = 60
    AUTO_RESUME      = TRUE
    INITIALLY_SUSPENDED = TRUE
    COMMENT = 'BI queries and Snowflake Task runs';

GRANT USAGE ON WAREHOUSE LOADING_WH      TO ROLE LOADER;
GRANT USAGE ON WAREHOUSE TRANSFORMING_WH TO ROLE TRANSFORMER;
GRANT USAGE ON WAREHOUSE REPORTING_WH    TO ROLE REPORTER;
-- TRANSFORMER also needs REPORTING_WH for Snowflake Tasks (ADR-020).
GRANT USAGE ON WAREHOUSE REPORTING_WH    TO ROLE TRANSFORMER;


-- =============================================================================
-- 3. DATABASES AND SCHEMAS
-- =============================================================================

-- RAW: landing zone — data arrives here from bulk load and CDC.
CREATE DATABASE IF NOT EXISTS RAW
    COMMENT = 'Raw ingestion layer; owned by LOADER';

CREATE SCHEMA IF NOT EXISTS RAW.RETAIL
    COMMENT = 'Source tables for the retail e-commerce simulator';

-- ANALYTICS: dbt output — staging, intermediate, and mart layers.
CREATE DATABASE IF NOT EXISTS ANALYTICS
    COMMENT = 'dbt transformation output; owned by TRANSFORMER';

CREATE SCHEMA IF NOT EXISTS ANALYTICS.STAGING
    COMMENT = 'dbt staging models (views)';

CREATE SCHEMA IF NOT EXISTS ANALYTICS.INTERMEDIATE
    COMMENT = 'dbt intermediate models (ephemeral)';

CREATE SCHEMA IF NOT EXISTS ANALYTICS.MARTS
    COMMENT = 'dbt mart models (tables); consumed by REPORTER';


-- =============================================================================
-- 4. GRANTS — RAW
-- =============================================================================

GRANT OWNERSHIP ON DATABASE RAW   TO ROLE LOADER COPY CURRENT GRANTS;
GRANT OWNERSHIP ON SCHEMA RAW.RETAIL TO ROLE LOADER COPY CURRENT GRANTS;

-- TRANSFORMER reads from RAW (dbt sources).
GRANT USAGE ON DATABASE RAW         TO ROLE TRANSFORMER;
GRANT USAGE ON SCHEMA RAW.RETAIL    TO ROLE TRANSFORMER;
GRANT SELECT ON ALL TABLES IN SCHEMA RAW.RETAIL TO ROLE TRANSFORMER;
-- Future tables in RAW.RETAIL are automatically readable by TRANSFORMER.
GRANT SELECT ON FUTURE TABLES IN SCHEMA RAW.RETAIL TO ROLE TRANSFORMER;


-- =============================================================================
-- 5. GRANTS — ANALYTICS
-- =============================================================================

GRANT OWNERSHIP ON DATABASE ANALYTICS            TO ROLE TRANSFORMER COPY CURRENT GRANTS;
GRANT OWNERSHIP ON SCHEMA ANALYTICS.STAGING      TO ROLE TRANSFORMER COPY CURRENT GRANTS;
GRANT OWNERSHIP ON SCHEMA ANALYTICS.INTERMEDIATE TO ROLE TRANSFORMER COPY CURRENT GRANTS;
GRANT OWNERSHIP ON SCHEMA ANALYTICS.MARTS        TO ROLE TRANSFORMER COPY CURRENT GRANTS;

-- REPORTER reads mart layer.
GRANT USAGE ON DATABASE ANALYTICS         TO ROLE REPORTER;
GRANT USAGE ON SCHEMA ANALYTICS.MARTS     TO ROLE REPORTER;
GRANT SELECT ON ALL TABLES IN SCHEMA ANALYTICS.MARTS TO ROLE REPORTER;
GRANT SELECT ON FUTURE TABLES IN SCHEMA ANALYTICS.MARTS TO ROLE REPORTER;
-- REPORTER also reads staging views (useful for training exercises).
GRANT USAGE ON SCHEMA ANALYTICS.STAGING   TO ROLE REPORTER;
GRANT SELECT ON ALL VIEWS IN SCHEMA ANALYTICS.STAGING TO ROLE REPORTER;
GRANT SELECT ON FUTURE VIEWS IN SCHEMA ANALYTICS.STAGING TO ROLE REPORTER;


-- =============================================================================
-- 6. RAW TABLE DDL
-- =============================================================================
-- All tables live in RAW.RETAIL and are owned by LOADER.
-- Column types match the DuckDB simulator schema (ADR-014, ADR-015, ADR-017).

USE ROLE LOADER;
USE WAREHOUSE LOADING_WH;
USE DATABASE RAW;
USE SCHEMA RETAIL;

-- addresses: standalone geographic entities; shared by household customers.
CREATE TABLE IF NOT EXISTS addresses (
    address_id     VARCHAR(50)   NOT NULL,
    street_address VARCHAR(255)  NOT NULL,
    city           VARCHAR(100)  NOT NULL,
    state          VARCHAR(50)   NOT NULL,
    postal_code    VARCHAR(20)   NOT NULL,
    country        VARCHAR(50)   NOT NULL DEFAULT 'US',
    PRIMARY KEY (address_id)
);

-- customers: each customer belongs to exactly one address (household model).
CREATE TABLE IF NOT EXISTS customers (
    customer_id  VARCHAR(50)   NOT NULL,
    first_name   VARCHAR(100)  NOT NULL,
    last_name    VARCHAR(100)  NOT NULL,
    email        VARCHAR(255)  NOT NULL,
    address_id   VARCHAR(50)   NOT NULL,
    created_at   TIMESTAMP_TZ  NOT NULL,
    PRIMARY KEY (customer_id),
    UNIQUE (email)
);

-- products: no inventory quantity (ADR-017).
CREATE TABLE IF NOT EXISTS products (
    product_id   VARCHAR(50)    NOT NULL,
    sku          VARCHAR(50)    NOT NULL,
    name         VARCHAR(255)   NOT NULL,
    price        NUMBER(10, 2)  NOT NULL,
    cost_price   NUMBER(10, 2)  NOT NULL,
    category     VARCHAR(100)   NOT NULL,
    PRIMARY KEY (product_id)
);

-- orders: snapshot of shipping address at order time survives future moves.
CREATE TABLE IF NOT EXISTS orders (
    order_id            VARCHAR(50)    NOT NULL,
    customer_id         VARCHAR(50)    NOT NULL,
    order_state         VARCHAR(50)    NOT NULL,
    order_date          TIMESTAMP_TZ   NOT NULL,
    updated_at          TIMESTAMP_TZ   NOT NULL,
    subtotal            NUMBER(12, 2),
    tax                 NUMBER(12, 2),
    shipping_cost       NUMBER(12, 2),
    total_amount        NUMBER(12, 2)  NOT NULL,
    shipping_address_id VARCHAR(50)    NOT NULL,
    is_stuck            BOOLEAN        NOT NULL DEFAULT FALSE,
    stuck_reason        VARCHAR(255),
    PRIMARY KEY (order_id)
);

-- order_items: line items; many per order.
CREATE TABLE IF NOT EXISTS order_items (
    order_item_id VARCHAR(50)    NOT NULL,
    order_id      VARCHAR(50)    NOT NULL,
    product_id    VARCHAR(50)    NOT NULL,
    quantity      INTEGER        NOT NULL,
    unit_price    NUMBER(10, 2)  NOT NULL,
    total_price   NUMBER(12, 2)  NOT NULL,
    PRIMARY KEY (order_item_id)
);

-- payments: one payment record per order.
CREATE TABLE IF NOT EXISTS payments (
    payment_id         VARCHAR(50)    NOT NULL,
    order_id           VARCHAR(50)    NOT NULL,
    payment_state      VARCHAR(50)    NOT NULL,
    amount             NUMBER(12, 2)  NOT NULL,
    payment_method     VARCHAR(50)    NOT NULL,
    payment_date       TIMESTAMP_TZ,
    authorization_date TIMESTAMP_TZ,
    capture_date       TIMESTAMP_TZ,
    refund_date        TIMESTAMP_TZ,
    failure_reason     VARCHAR(255),
    retry_count        INTEGER        NOT NULL DEFAULT 0,
    PRIMARY KEY (payment_id)
);

-- order_events: lifecycle state transitions (explicit columns, no JSONB — ADR-014).
CREATE TABLE IF NOT EXISTS order_events (
    event_id        VARCHAR(50)  NOT NULL,
    order_id        VARCHAR(50)  NOT NULL,
    previous_state  VARCHAR(50),
    new_state       VARCHAR(50)  NOT NULL,
    event_timestamp TIMESTAMP_TZ NOT NULL,
    reason          VARCHAR(255),
    retry_count     NUMBER,
    PRIMARY KEY (event_id)
);

-- payment_events: payment lifecycle state transitions (ADR-014).
CREATE TABLE IF NOT EXISTS payment_events (
    event_id        VARCHAR(50)  NOT NULL,
    payment_id      VARCHAR(50)  NOT NULL,
    previous_state  VARCHAR(50),
    new_state       VARCHAR(50)  NOT NULL,
    event_timestamp TIMESTAMP_TZ NOT NULL,
    failure_reason  VARCHAR(255),
    retry_attempt   NUMBER,
    PRIMARY KEY (event_id)
);


-- =============================================================================
-- 7. FILE FORMATS
-- =============================================================================
-- Three formats matching the export layout:
--   CSV            → addresses, customers, products
--   Parquet        → orders, order_items, payments
--   Parquet/Hive   → order_events, payment_events (year=/month= partitioned)

USE ROLE LOADER;
USE DATABASE RAW;
USE SCHEMA RETAIL;

CREATE FILE FORMAT IF NOT EXISTS ff_csv
    TYPE             = CSV
    FIELD_OPTIONALLY_ENCLOSED_BY = '"'
    NULL_IF          = ('', 'NULL', 'null')
    EMPTY_FIELD_AS_NULL = TRUE
    SKIP_HEADER      = 1
    DATE_FORMAT      = 'AUTO'
    TIMESTAMP_FORMAT = 'AUTO'
    COMMENT          = 'CSV with quoted fields and header row; used for addresses, customers, products';

CREATE FILE FORMAT IF NOT EXISTS ff_parquet
    TYPE    = PARQUET
    COMMENT = 'Flat Parquet files; used for orders, order_items, payments';

-- Hive-partitioned Parquet uses the same format object; the partition columns
-- (year, month) are excluded from the file schema — they are parsed from the
-- path using METADATA$FILENAME in the COPY INTO statement.
CREATE FILE FORMAT IF NOT EXISTS ff_parquet_hive
    TYPE    = PARQUET
    COMMENT = 'Hive-partitioned Parquet; used for order_events, payment_events';


-- =============================================================================
-- 8. INTERNAL STAGES
-- =============================================================================
-- One stage per file-format family keeps PUT commands and COPY INTO paths clean.

CREATE STAGE IF NOT EXISTS stg_csv
    FILE_FORMAT = ff_csv
    COMMENT     = 'Staging area for CSV flat files (addresses, customers, products)';

CREATE STAGE IF NOT EXISTS stg_parquet
    FILE_FORMAT = ff_parquet
    COMMENT     = 'Staging area for flat Parquet files (orders, order_items, payments)';

CREATE STAGE IF NOT EXISTS stg_parquet_hive
    FILE_FORMAT = ff_parquet_hive
    COMMENT     = 'Staging area for Hive-partitioned Parquet (order_events, payment_events)';
