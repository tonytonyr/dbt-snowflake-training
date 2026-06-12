{{
  config(
    materialized     = 'incremental',
    unique_key       = 'payment_id',
    on_schema_change = 'sync_all_columns'
  )
}}

with payments as (
    select * from {{ ref('stg_retail__payments') }}
    {% if is_incremental() %}
    -- Use GREATEST across all lifecycle timestamps so late-arriving captures/refunds
    -- are caught. COALESCE nulls to a sentinel because Snowflake GREATEST returns NULL
    -- if any argument is NULL.
    where greatest(
        payment_date,
        coalesce(authorization_date, '1900-01-01'::timestamp),
        coalesce(capture_date,       '1900-01-01'::timestamp),
        coalesce(refund_date,        '1900-01-01'::timestamp)
    ) >= dateadd('day', -3, (select max(payment_date) from {{ this }}))
    {% endif %}
),

orders as (
    select
        order_id,
        customer_id,
        order_date,
        order_state,
        total_amount            as order_amount
    from {{ ref('stg_retail__orders') }}
),

final as (
    select
        p.payment_id,
        p.order_id,
        o.customer_id,
        o.order_date::date      as order_date_day,
        o.order_date,
        o.order_state,
        p.payment_method,
        p.payment_state,
        p.amount                as payment_amount,
        o.order_amount,
        abs(o.order_amount - p.amount) > 0.01   as has_discrepancy,
        p.payment_date,
        p.authorization_date,
        p.capture_date,
        p.refund_date,
        p.failure_reason,
        p.retry_count,
        datediff(
            'hour',
            p.payment_date,
            p.authorization_date
        )                       as hours_to_authorize,
        datediff(
            'hour',
            p.authorization_date,
            p.capture_date
        )                       as hours_to_capture,
        p.payment_state = 'refunded'            as is_refunded,
        p.payment_state = 'failed'              as is_failed
    from payments as p
    inner join orders as o using (order_id)
)

select * from final
