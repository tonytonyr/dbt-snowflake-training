{% macro classify_price_band(price_column) %}
    case
        when {{ price_column }} < 25    then 'budget'
        when {{ price_column }} < 75    then 'mid_range'
        when {{ price_column }} < 200   then 'premium'
        else                                 'luxury'
    end
{% endmacro %}
