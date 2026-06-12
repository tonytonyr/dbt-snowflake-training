with enriched as (
    select * from {{ ref('int_orders_enriched') }}
),

with_payments as (
    select * from {{ ref('int_orders_with_payments') }}
),

timeliness as (
    select * from {{ ref('int_shipment_timeliness') }}
),

final as (
    select
        e.order_id,
        e.customer_id,
        e.order_date::date                        as order_date_day,
        e.order_date,
        e.updated_at,
        e.order_state,
        e.shipping_address_id,

        -- line items
        e.line_count,
        e.item_count,
        e.gross_revenue,
        e.gross_margin,

        -- financials
        e.subtotal,
        e.tax,
        e.shipping_cost,
        e.total_amount,

        -- payment
        p.payment_id,
        p.payment_method,
        p.payment_state,
        p.payment_amount,
        p.payment_date,
        p.has_discrepancy,
        p.is_refunded,

        -- timeliness
        t.shipped_at,
        t.delivered_at,
        t.days_to_ship,
        t.days_to_deliver,
        t.is_on_time,

        -- flags
        e.is_stuck,
        e.stuck_reason,
        e.order_state = 'returned'                as is_returned,
        e.order_state = 'cancelled'               as is_cancelled
    from enriched as e
    left join with_payments as p using (order_id)
    left join timeliness as t using (order_id)
)

select * from final
