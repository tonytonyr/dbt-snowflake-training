with source as (
    select * from {{ source('retail', 'payment_events') }}
),

renamed as (
    select
        event_id,
        payment_id,
        event_type,
        from_state,
        to_state,
        failure_reason,
        retry_attempt,
        created_at
    from source
)

select * from renamed
