-- Top 25 products by net revenue, with the running (Pareto) share of total revenue.
WITH product AS (
    SELECT
        f.stock_code,
        ANY_VALUE(p.description)                                  AS description,
        ANY_VALUE(p.product_family)                               AS product_family,
        SUM(f.line_revenue)                                       AS net_revenue,
        SUM(f.quantity) FILTER (WHERE NOT f.is_return)            AS units_sold,
        COUNT(DISTINCT f.invoice) FILTER (WHERE NOT f.is_return)  AS orders,
        -SUM(f.quantity) FILTER (WHERE f.is_return)               AS units_returned
    FROM fact_sales f
    JOIN dim_product p ON f.stock_code = p.stock_code
    GROUP BY f.stock_code
),
ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (ORDER BY net_revenue DESC)              AS revenue_rank,
        100.0 * net_revenue / SUM(net_revenue) OVER ()             AS revenue_share_pct,
        100.0 * SUM(net_revenue) OVER (ORDER BY net_revenue DESC ROWS UNBOUNDED PRECEDING)
              / SUM(net_revenue) OVER ()                           AS cumulative_share_pct
    FROM product
)
SELECT
    revenue_rank,
    stock_code,
    description,
    product_family,
    ROUND(net_revenue, 2)                                                   AS net_revenue,
    units_sold,
    orders,
    ROUND(100.0 * COALESCE(units_returned, 0) / NULLIF(units_sold, 0), 2)   AS unit_return_rate_pct,
    ROUND(revenue_share_pct, 3)                                             AS revenue_share_pct,
    ROUND(cumulative_share_pct, 2)                                          AS cumulative_share_pct
FROM ranked
WHERE revenue_rank <= 25
ORDER BY revenue_rank
