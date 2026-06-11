with source as (
    select * from {{ source('retail', 'order_events') }}
),

renamed as (
    select
        event_id,
        order_id,
        previous_state,
        new_state,
        event_timestamp,
        reason,
        retry_count
    from source
)

select * from renamed
