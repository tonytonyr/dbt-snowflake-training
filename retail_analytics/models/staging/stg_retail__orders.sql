with source as (
    select * from {{ source('retail', 'orders') }}
),

renamed as (
    select
        order_id,
        customer_id,
        order_state,
        order_date,
        updated_at,
        subtotal,
        tax,
        shipping_cost,
        total_amount,
        shipping_address_id,
        is_stuck,
        stuck_reason
    from source
)

select * from renamed
