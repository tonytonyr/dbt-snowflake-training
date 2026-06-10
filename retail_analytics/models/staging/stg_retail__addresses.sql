with source as (
    select * from {{ source('retail', 'addresses') }}
),

renamed as (
    select
        address_id,
        street_address,
        city,
        state,
        postal_code,
        country
    from source
)

select * from renamed
