-- Monthly trend with month-over-month and year-over-year growth (window functions).
WITH first_purchase AS (
    SELECT customer_id, MIN(order_date) AS first_date
    FROM fact_sales
    WHERE NOT is_return AND customer_id IS NOT NULL
    GROUP BY customer_id
),
monthly AS (
    SELECT
        DATE_TRUNC('month', f.order_date)                                   AS month,
        SUM(f.line_revenue)                                                 AS net_revenue,
        SUM(f.line_revenue) FILTER (WHERE NOT f.is_return)                  AS gross_revenue,
        COUNT(DISTINCT f.invoice) FILTER (WHERE NOT f.is_return)            AS orders,
        COUNT(DISTINCT f.customer_id) FILTER (WHERE NOT f.is_return)        AS active_customers,
        COUNT(DISTINCT f.customer_id) FILTER (
            WHERE NOT f.is_return
              AND DATE_TRUNC('month', fp.first_date) = DATE_TRUNC('month', f.order_date)
        )                                                                   AS new_customers,
        SUM(f.quantity) FILTER (WHERE NOT f.is_return)                      AS units
    FROM fact_sales f
    LEFT JOIN first_purchase fp ON f.customer_id = fp.customer_id
    GROUP BY 1
)
SELECT
    month,
    ROUND(net_revenue, 2)                                           AS net_revenue,
    orders,
    active_customers,
    new_customers,
    units,
    ROUND(gross_revenue / orders, 2)                                AS avg_order_value,
    ROUND(100.0 * (net_revenue / LAG(net_revenue, 1) OVER w - 1), 1)  AS mom_growth_pct,
    ROUND(100.0 * (net_revenue / LAG(net_revenue, 12) OVER w - 1), 1) AS yoy_growth_pct,
    month = (SELECT MAX(DATE_TRUNC('month', order_date)) FROM fact_sales) AS is_partial_month
FROM monthly
WINDOW w AS (ORDER BY month)
ORDER BY month
