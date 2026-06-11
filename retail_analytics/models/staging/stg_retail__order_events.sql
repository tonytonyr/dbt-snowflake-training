with source as (
    select * from {{ source('retail', 'order_events') }}
),

renamed as (
    select
        event_id,
        order_id,
        event_type,
        previous_state,
        new_state,
        reason,
        retry_count,
        event_timestamp
    from source
)

select * from renamed
