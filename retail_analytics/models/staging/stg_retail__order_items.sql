with source as (
    select * from {{ source('retail', 'order_items') }}
),

renamed as (
    select
        order_item_id,
        order_id,
        product_id,
        quantity,
        unit_price,
        total_price             as line_total
    from source
)

select * from renamed
