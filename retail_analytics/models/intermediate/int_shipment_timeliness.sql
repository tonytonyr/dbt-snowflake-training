-- Uses order_events to extract actual shipped/delivered transition timestamps.
-- order_events has no event_type column — we pivot on new_state instead.
with orders as (
    select * from {{ ref('stg_retail__orders') }}
),

order_events as (
    select * from {{ ref('stg_retail__order_events') }}
),

transition_timestamps as (
    select
        order_id,
        max(case when new_state = 'shipped'   then event_timestamp end) as shipped_at,
        max(case when new_state = 'delivered' then event_timestamp end) as delivered_at
    from order_events
    group by order_id
),

final as (
    select
        o.order_id,
        o.customer_id,
        o.order_state,
        o.order_date,
        t.shipped_at,
        t.delivered_at,
        datediff('day', o.order_date, t.shipped_at)                     as days_to_ship,
        datediff('day', o.order_date, t.delivered_at)                   as days_to_deliver,
        7                                                                as sla_days,
        case
            when t.delivered_at is not null
                then datediff('day', o.order_date, t.delivered_at) <= 7
        end                                                              as is_on_time
    from orders as o
    left join transition_timestamps as t using (order_id)
)

select * from final
