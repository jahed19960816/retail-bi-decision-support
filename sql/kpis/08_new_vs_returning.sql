-- Monthly revenue split into new customers, returning customers and guest (no customer ID) checkouts.
-- Note: Dec 2009 is the first month of data, so every known customer counts as "new" there.
WITH first_purchase AS (
    SELECT customer_id, DATE_TRUNC('month', MIN(order_date)) AS cohort_month
    FROM fact_sales
    WHERE NOT is_return AND customer_id IS NOT NULL
    GROUP BY customer_id
)
SELECT
    DATE_TRUNC('month', f.order_date) AS month,
    ROUND(SUM(f.line_revenue) FILTER (WHERE f.customer_id IS NOT NULL
                                        AND fp.cohort_month = DATE_TRUNC('month', f.order_date)), 2) AS new_customer_revenue,
    ROUND(SUM(f.line_revenue) FILTER (WHERE f.customer_id IS NOT NULL
                                        AND (fp.cohort_month IS NULL
                                             OR fp.cohort_month <> DATE_TRUNC('month', f.order_date))), 2) AS returning_customer_revenue,
    ROUND(SUM(f.line_revenue) FILTER (WHERE f.customer_id IS NULL), 2) AS guest_revenue
FROM fact_sales f
LEFT JOIN first_purchase fp ON f.customer_id = fp.customer_id
GROUP BY 1
ORDER BY 1
