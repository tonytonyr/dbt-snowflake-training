with source as (
    select * from {{ source('retail', 'payment_events') }}
),

renamed as (
    select
        event_id,
        payment_id,
        event_type,
        previous_state,
        new_state,
        failure_reason,
        retry_attempt,
        event_timestamp
    from source
)

select * from renamed
