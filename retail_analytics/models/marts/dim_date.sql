with date_spine as (
    select
        dateadd(day, seq4(), '2022-01-01'::date) as date_day
    from table(generator(rowcount => 2557))
),

final as (
    select
        date_day,
        dayofweek(date_day)                                      as day_of_week_num,
        dayname(date_day)                                        as day_name,
        day(date_day)                                            as day_of_month,
        dayofyear(date_day)                                      as day_of_year,
        weekofyear(date_day)                                     as week_of_year,
        month(date_day)                                          as month_num,
        monthname(date_day)                                      as month_name,
        quarter(date_day)                                        as quarter_num,
        year(date_day)                                           as year_num,
        date_trunc('week', date_day)                             as week_start_date,
        date_trunc('month', date_day)                            as month_start_date,
        date_trunc('quarter', date_day)                          as quarter_start_date,
        to_char(date_day, 'YYYY-MM')                             as year_month,
        dayofweek(date_day) in (0, 6)                            as is_weekend
    from date_spine
)

select * from final
