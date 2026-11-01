-- Category performance (keyword-derived product families) with year-over-year growth.
WITH family AS (
    SELECT
        p.product_family,
        SUM(f.line_revenue) FILTER (WHERE f.order_date < DATE '2010-12-01')             AS revenue_p1,
        SUM(f.line_revenue) FILTER (WHERE f.order_date >= DATE '2010-12-01'
                                      AND f.order_date <  DATE '2011-12-01')            AS revenue_p2,
        SUM(f.line_revenue)                                                             AS net_revenue,
        COUNT(DISTINCT f.stock_code)                                                    AS products,
        100.0 * -SUM(f.line_revenue) FILTER (WHERE f.is_return)
              / SUM(f.line_revenue) FILTER (WHERE NOT f.is_return)                      AS return_rate_pct
    FROM fact_sales f
    JOIN dim_product p ON f.stock_code = p.stock_code
    GROUP BY p.product_family
)
SELECT
    product_family,
    ROUND(net_revenue, 2)                                         AS net_revenue,
    ROUND(100.0 * net_revenue / SUM(net_revenue) OVER (), 2)      AS revenue_share_pct,
    ROUND(revenue_p1, 2)                                          AS revenue_dec09_nov10,
    ROUND(revenue_p2, 2)                                          AS revenue_dec10_nov11,
    ROUND(100.0 * (revenue_p2 / revenue_p1 - 1), 1)               AS yoy_growth_pct,
    products,
    ROUND(return_rate_pct, 2)                                     AS return_rate_pct
FROM family
ORDER BY net_revenue DESC
