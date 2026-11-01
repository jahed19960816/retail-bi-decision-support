-- Revenue, orders, customers and share by country.
SELECT
    country,
    ROUND(SUM(line_revenue), 2)                                         AS net_revenue,
    COUNT(DISTINCT invoice) FILTER (WHERE NOT is_return)                AS orders,
    COUNT(DISTINCT customer_id)                                         AS customers,
    ROUND(SUM(line_revenue) FILTER (WHERE NOT is_return)
          / NULLIF(COUNT(DISTINCT invoice) FILTER (WHERE NOT is_return), 0), 2) AS avg_order_value,
    ROUND(100.0 * SUM(line_revenue) / SUM(SUM(line_revenue)) OVER (), 2) AS revenue_share_pct,
    RANK() OVER (ORDER BY SUM(line_revenue) DESC)                       AS revenue_rank
FROM fact_sales
GROUP BY country
ORDER BY net_revenue DESC
