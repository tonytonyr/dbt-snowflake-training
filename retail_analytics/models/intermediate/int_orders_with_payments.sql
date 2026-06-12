with orders as (
    select * from {{ ref('stg_retail__orders') }}
),

payments as (
    select * from {{ ref('stg_retail__payments') }}
),

final as (
    select
        o.order_id,
        o.customer_id,
        o.order_state,
        o.order_date,
        o.total_amount,
        p.payment_id,
        p.payment_method,
        p.payment_state,
        p.amount              as payment_amount,
        p.payment_date,
        p.authorization_date,
        p.capture_date,
        p.refund_date,
        p.failure_reason,
        p.retry_count         as payment_retry_count,
        abs(o.total_amount - p.amount)            as amount_discrepancy,
        abs(o.total_amount - p.amount) > 0.01     as has_discrepancy,
        p.payment_state = 'refunded'              as is_refunded
    from orders as o
    left join payments as p using (order_id)
)

select * from final
