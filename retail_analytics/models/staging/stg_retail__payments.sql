with source as (
    select * from {{ source('retail', 'payments') }}
),

renamed as (
    select
        payment_id,
        order_id,
        payment_state,
        amount,
        payment_method,
        payment_date,
        authorization_date,
        capture_date,
        refund_date,
        failure_reason,
        retry_count
    from source
)

select * from renamed
