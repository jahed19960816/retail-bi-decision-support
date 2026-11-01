-- Products losing the most revenue to returns (minimum volume so rates are meaningful).
WITH product AS (
    SELECT
        f.stock_code,
        ANY_VALUE(p.description)                                AS description,
        SUM(f.line_revenue) FILTER (WHERE NOT f.is_return)      AS gross_revenue,
        -SUM(f.line_revenue) FILTER (WHERE f.is_return)         AS returned_value,
        SUM(f.quantity) FILTER (WHERE NOT f.is_return)          AS units_sold,
        -SUM(f.quantity) FILTER (WHERE f.is_return)             AS units_returned
    FROM fact_sales f
    JOIN dim_product p ON f.stock_code = p.stock_code
    GROUP BY f.stock_code
)
SELECT
    stock_code,
    description,
    units_sold,
    units_returned,
    ROUND(gross_revenue, 2)                          AS gross_revenue,
    ROUND(returned_value, 2)                         AS returned_value,
    ROUND(100.0 * returned_value / gross_revenue, 2) AS return_rate_pct
FROM product
WHERE units_sold >= 500 AND gross_revenue >= 2000 AND returned_value > 0
ORDER BY returned_value DESC
LIMIT 20
