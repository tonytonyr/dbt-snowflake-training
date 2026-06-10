with source as (
    select * from {{ source('retail', 'customers') }}
),

renamed as (
    select
        customer_id,
        first_name,
        last_name,
        email,
        address_id,
        created_at
    from source
)

select * from renamed
