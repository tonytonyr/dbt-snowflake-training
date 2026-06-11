with source as (
    select * from {{ source('retail', 'payment_events') }}
),

renamed as (
    select
        event_id,
        payment_id,
        previous_state,
        new_state,
        event_timestamp,
        failure_reason,
        retry_attempt
    from source
)

select * from renamed
