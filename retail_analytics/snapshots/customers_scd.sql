{% snapshot customers_scd %}

{{
    config(
        target_schema='snapshots',
        unique_key='customer_id',
        strategy='check',
        check_cols=['first_name', 'last_name', 'email', 'address_id'],
    )
}}

select * from {{ ref('stg_retail__customers') }}

{% endsnapshot %}
