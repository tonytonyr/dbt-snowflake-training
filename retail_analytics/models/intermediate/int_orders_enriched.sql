with orders as (
    select * from {{ ref('stg_retail__orders') }}
),

order_items as (
    select * from {{ ref('stg_retail__order_items') }}
),

products as (
    select * from {{ ref('stg_retail__products') }}
),

items_with_products as (
    select
        oi.order_item_id,
        oi.order_id,
        oi.product_id,
        oi.quantity,
        oi.unit_price,
        oi.line_total,
        p.product_name,
        p.product_category,
        p.cost_price,
        oi.quantity * (oi.unit_price - p.cost_price) as line_margin
    from order_items as oi
    inner join products as p using (product_id)
),

order_item_agg as (
    select
        order_id,
        count(order_item_id)     as line_count,
        sum(quantity)            as item_count,
        sum(line_total)          as gross_revenue,
        sum(line_margin)         as gross_margin
    from items_with_products
    group by order_id
),

final as (
    select
        o.order_id,
        o.customer_id,
        o.order_state,
        o.order_date,
        o.updated_at,
        o.subtotal,
        o.tax,
        o.shipping_cost,
        o.total_amount,
        o.shipping_address_id,
        o.is_stuck,
        o.stuck_reason,
        agg.line_count,
        agg.item_count,
        agg.gross_revenue,
        agg.gross_margin
    from orders as o
    inner join order_item_agg as agg using (order_id)
)

select * from final
