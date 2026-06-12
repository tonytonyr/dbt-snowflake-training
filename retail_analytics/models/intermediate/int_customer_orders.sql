with orders as (
    select * from {{ ref('stg_retail__orders') }}
),

final as (
    select
        customer_id,
        count(order_id)                                                          as order_count,
        min(order_date)                                                          as first_order_date,
        max(order_date)                                                          as last_order_date,
        sum(total_amount)                                                        as total_spend,
        count(case when order_state = 'returned'  then 1 end)                   as returned_order_count,
        count(case when order_state = 'cancelled' then 1 end)                   as cancelled_order_count,
        count(case when order_state = 'returned' then 1 end)
            / nullif(count(order_id), 0)                                        as return_rate,
        max(order_date) >= dateadd('day', -365, current_date)                   as is_active
    from orders
    group by customer_id
)

select * from final
