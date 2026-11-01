-- Headline business KPIs for the full period (Dec 2009 - Dec 2011).
-- Net revenue = gross sales + returns (returns are negative lines).
WITH sales AS (
    SELECT * FROM fact_sales WHERE NOT is_return
),
returns AS (
    SELECT * FROM fact_sales WHERE is_return
),
customer_orders AS (
    SELECT customer_id, COUNT(DISTINCT invoice) AS orders
    FROM sales
    WHERE customer_id IS NOT NULL
    GROUP BY customer_id
)
SELECT
    ROUND((SELECT SUM(line_revenue) FROM sales), 2)                                    AS gross_revenue,
    ROUND((SELECT -SUM(line_revenue) FROM returns), 2)                                 AS returns_value,
    ROUND((SELECT SUM(line_revenue) FROM fact_sales), 2)                               AS net_revenue,
    ROUND(100.0 * (SELECT -SUM(line_revenue) FROM returns)
                / (SELECT SUM(line_revenue) FROM sales), 2)                            AS return_rate_pct,
    (SELECT COUNT(DISTINCT invoice) FROM sales)                                        AS orders,
    (SELECT COUNT(DISTINCT customer_id) FROM sales)                                    AS customers,
    (SELECT SUM(quantity) FROM sales)                                                  AS units_sold,
    ROUND((SELECT AVG(order_value) FROM v_orders), 2)                                  AS avg_order_value,
    ROUND((SELECT AVG(distinct_products) FROM v_orders), 1)                            AS avg_products_per_order,
    ROUND((SELECT SUM(line_revenue) FROM sales WHERE customer_id IS NOT NULL)
          / (SELECT COUNT(DISTINCT customer_id) FROM sales), 2)                        AS revenue_per_customer,
    ROUND(100.0 * (SELECT COUNT(*) FROM customer_orders WHERE orders > 1)
                / (SELECT COUNT(*) FROM customer_orders), 2)                           AS repeat_customer_rate_pct,
    ROUND(100.0 * (SELECT SUM(line_revenue) FROM sales WHERE is_guest)
                / (SELECT SUM(line_revenue) FROM sales), 2)                            AS guest_revenue_share_pct,
    (SELECT COUNT(DISTINCT stock_code) FROM sales)                                     AS active_products,
    (SELECT COUNT(DISTINCT country) FROM sales)                                        AS countries
