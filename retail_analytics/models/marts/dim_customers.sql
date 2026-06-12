with customers as (
    select
        customer_id,
        first_name,
        last_name,
        email,
        address_id,
        created_at,
        dbt_valid_from,
        dbt_valid_to,
        dbt_scd_id
    from {{ ref('customers_scd') }}
    where dbt_valid_to is null
),

addresses as (
    select * from {{ ref('stg_retail__addresses') }}
),

customer_orders as (
    select * from {{ ref('int_customer_orders') }}
),

final as (
    select
        c.customer_id,
        c.first_name,
        c.last_name,
        c.email,
        c.address_id,
        a.city,
        a.state,
        a.postal_code,
        a.country,
        c.created_at,
        to_char(c.created_at, 'YYYY-MM')         as cohort_month,
        year(c.created_at)                        as cohort_year,
        coalesce(co.order_count, 0)               as lifetime_order_count,
        coalesce(co.total_spend, 0)               as lifetime_spend,
        co.first_order_date,
        co.last_order_date,
        coalesce(co.return_rate, 0)               as return_rate,
        coalesce(co.is_active, false)             as is_active,
        case
            when co.order_count is null         then 'never_ordered'
            when co.order_count = 1             then 'one_time'
            when co.order_count between 2 and 4 then 'repeat'
            else                                     'loyal'
        end                                       as customer_segment,
        c.dbt_valid_from,
        c.dbt_scd_id
    from customers as c
    left join addresses as a using (address_id)
    left join customer_orders as co using (customer_id)
)

select * from final
