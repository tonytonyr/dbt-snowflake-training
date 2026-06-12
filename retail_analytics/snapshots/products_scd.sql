{% snapshot products_scd %}

{{
    config(
        target_schema='snapshots',
        unique_key='product_id',
        strategy='check',
        check_cols=['product_name', 'product_category', 'unit_price', 'cost_price'],
    )
}}

select * from {{ ref('stg_retail__products') }}

{% endsnapshot %}
