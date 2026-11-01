-- Revenue concentration: how much revenue comes from each quintile of customers and products?
WITH customer_revenue AS (
    SELECT customer_id, SUM(line_revenue) AS revenue
    FROM fact_sales
    WHERE customer_id IS NOT NULL
    GROUP BY customer_id
),
product_revenue AS (
    SELECT stock_code, SUM(line_revenue) AS revenue
    FROM fact_sales
    GROUP BY stock_code
),
customer_quintiles AS (
    SELECT revenue, NTILE(5) OVER (ORDER BY revenue DESC) AS quintile FROM customer_revenue
),
product_quintiles AS (
    SELECT revenue, NTILE(5) OVER (ORDER BY revenue DESC) AS quintile FROM product_revenue
)
SELECT
    'Customers' AS entity,
    quintile,
    COUNT(*) AS members,
    ROUND(SUM(revenue), 2) AS revenue,
    ROUND(100.0 * SUM(revenue) / SUM(SUM(revenue)) OVER (), 2) AS revenue_share_pct
FROM customer_quintiles
GROUP BY quintile
UNION ALL
SELECT
    'Products',
    quintile,
    COUNT(*),
    ROUND(SUM(revenue), 2),
    ROUND(100.0 * SUM(revenue) / SUM(SUM(revenue)) OVER (), 2)
FROM product_quintiles
GROUP BY quintile
ORDER BY entity, quintile
