with source as (
    select * from {{ source('retail', 'payments') }}
),

renamed as (
    select
        payment_id,
        order_id,
        payment_method,
        payment_state,
        amount
    from source
)

select * from renamed
