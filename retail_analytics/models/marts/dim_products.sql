with products as (
    select
        product_id,
        sku,
        product_name,
        product_category,
        unit_price,
        cost_price,
        dbt_valid_from,
        dbt_valid_to,
        dbt_scd_id
    from {{ ref('products_scd') }}
    where dbt_valid_to is null
),

final as (
    select
        product_id,
        sku,
        product_name,
        product_category,
        unit_price,
        cost_price,
        round(unit_price - cost_price, 2)         as gross_margin_amount,
        round(
            (unit_price - cost_price) / nullif(unit_price, 0),
            4
        )                                          as gross_margin_pct,
        case
            when unit_price < 25    then 'budget'
            when unit_price < 75    then 'mid_range'
            when unit_price < 200   then 'premium'
            else                         'luxury'
        end                                        as price_band,
        dbt_valid_from,
        dbt_scd_id
    from products
)

select * from final
