with source as (
    select * from {{ source('retail', 'products') }}
),

renamed as (
    select
        product_id,
        sku,
        name        as product_name,
        category    as product_category,
        price       as unit_price,
        cost_price
    from source
)

select * from renamed
