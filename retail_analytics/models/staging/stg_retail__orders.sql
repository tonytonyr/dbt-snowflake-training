with source as (
    select * from {{ source('retail', 'orders') }}
),

renamed as (
    select
        order_id,
        customer_id,
        order_date,
        status                                      as order_status,
        total_amount,
        updated_at
    from source
)

select * from renamed
