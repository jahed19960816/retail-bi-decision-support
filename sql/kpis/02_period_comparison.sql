-- Compare two complete 12-month periods (Dec-Nov). Dec 2011 is excluded because it is partial.
WITH tagged AS (
    SELECT
        *,
        CASE
            WHEN order_date >= DATE '2009-12-01' AND order_date < DATE '2010-12-01' THEN 'Dec 2009 - Nov 2010'
            WHEN order_date >= DATE '2010-12-01' AND order_date < DATE '2011-12-01' THEN 'Dec 2010 - Nov 2011'
        END AS period
    FROM fact_sales
),
period_kpis AS (
    SELECT
        period,
        SUM(line_revenue)                                              AS net_revenue,
        COUNT(DISTINCT invoice) FILTER (WHERE NOT is_return)           AS orders,
        COUNT(DISTINCT customer_id) FILTER (WHERE NOT is_return)       AS customers,
        SUM(line_revenue) FILTER (WHERE NOT is_return)
            / COUNT(DISTINCT invoice) FILTER (WHERE NOT is_return)     AS avg_order_value,
        100.0 * -SUM(line_revenue) FILTER (WHERE is_return)
            / SUM(line_revenue) FILTER (WHERE NOT is_return)           AS return_rate_pct
    FROM tagged
    WHERE period IS NOT NULL
    GROUP BY period
)
SELECT
    period,
    ROUND(net_revenue, 2)      AS net_revenue,
    orders,
    customers,
    ROUND(avg_order_value, 2)  AS avg_order_value,
    ROUND(return_rate_pct, 2)  AS return_rate_pct,
    ROUND(100.0 * (net_revenue / LAG(net_revenue) OVER w - 1), 1)         AS revenue_growth_pct,
    ROUND(100.0 * (orders / LAG(orders) OVER w - 1), 1)                   AS orders_growth_pct,
    ROUND(100.0 * (customers / LAG(customers) OVER w - 1), 1)             AS customers_growth_pct,
    ROUND(100.0 * (avg_order_value / LAG(avg_order_value) OVER w - 1), 1) AS aov_growth_pct
FROM period_kpis
WINDOW w AS (ORDER BY period)
ORDER BY period
