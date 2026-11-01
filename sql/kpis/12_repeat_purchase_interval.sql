-- How long do customers take to come back? Days between consecutive orders (LAG window).
WITH orders AS (
    SELECT customer_id, invoice, MIN(order_date) AS order_date
    FROM fact_sales
    WHERE NOT is_return AND customer_id IS NOT NULL
    GROUP BY customer_id, invoice
),
gaps AS (
    SELECT
        customer_id,
        DATE_DIFF('day', LAG(order_date) OVER (PARTITION BY customer_id ORDER BY order_date), order_date) AS days_since_prev
    FROM orders
)
SELECT
    COUNT(*) FILTER (WHERE days_since_prev IS NOT NULL)          AS repeat_orders,
    ROUND(MEDIAN(days_since_prev), 1)                            AS median_days_between_orders,
    ROUND(AVG(days_since_prev), 1)                               AS mean_days_between_orders,
    ROUND(QUANTILE_CONT(days_since_prev, 0.75), 1)               AS p75_days_between_orders,
    ROUND(100.0 * COUNT(*) FILTER (WHERE days_since_prev <= 90)
                / COUNT(*) FILTER (WHERE days_since_prev IS NOT NULL), 1) AS pct_repeat_within_90_days
FROM gaps
