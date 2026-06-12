{{
  config(
    materialized     = 'incremental',
    unique_key       = 'order_id',
    on_schema_change = 'sync_all_columns'
  )
}}

with orders as (
    select * from {{ ref('fct_orders') }}
    where is_returned = true
    {% if is_incremental() %}
    -- Newly-returned orders will have updated_at freshly bumped by fct_orders' MERGE.
    -- Anchor on max(returned_at) from this table so we don't reprocess old returns.
    and updated_at >= dateadd('day', -3, (select max(returned_at) from {{ this }}))
    {% endif %}
),

order_events as (
    select * from {{ ref('stg_retail__order_events') }}
),

return_events as (
    select
        order_id,
        max(case when new_state = 'returned' then event_timestamp end) as returned_at
    from order_events
    group by order_id
),

final as (
    select
        o.order_id,
        o.customer_id,
        o.order_date_day,
        o.order_date,
        o.total_amount          as order_amount,
        o.gross_margin          as order_margin,
        o.payment_id,
        o.payment_method,
        o.payment_amount        as refund_amount,
        o.payment_state,
        r.returned_at,
        datediff(
            'day',
            o.order_date,
            r.returned_at
        )                       as days_to_return
    from orders as o
    left join return_events as r using (order_id)
)

select * from final
