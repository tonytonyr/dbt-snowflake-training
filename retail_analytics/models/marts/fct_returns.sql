with orders as (
    select * from {{ ref('fct_orders') }}
    where is_returned = true
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
