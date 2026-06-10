with source as (
    select * from {{ source('retail', 'order_events') }}
),

renamed as (
    select
        event_id,
        order_id,
        event_type,
        from_state,
        to_state,
        reason,
        retry_count,
        created_at
    from source
)

select * from renamed
