-- Each order's subtotal must equal the sum of its line items.
-- Returns rows where the delta exceeds $0.01 (float rounding tolerance).
select
    o.order_id,
    o.subtotal                          as order_subtotal,
    sum(oi.line_total)                  as items_subtotal,
    abs(o.subtotal - sum(oi.line_total)) as delta
from {{ ref('stg_retail__orders') }}    as o
join {{ ref('stg_retail__order_items') }} as oi
    on o.order_id = oi.order_id
group by o.order_id, o.subtotal
having abs(o.subtotal - sum(oi.line_total)) > 0.01
