-- Market basket analysis: product pairs bought together more often than chance (lift > 1).
-- Restricted to the 300 most-ordered products to keep the self-join fast.
WITH order_items AS (
    SELECT DISTINCT invoice, stock_code
    FROM fact_sales
    WHERE NOT is_return
),
n_orders AS (
    SELECT COUNT(DISTINCT invoice) AS n FROM order_items
),
popular AS (
    SELECT stock_code, COUNT(*) AS item_orders
    FROM order_items
    GROUP BY stock_code
    ORDER BY item_orders DESC, stock_code  -- tie-break so the top 300 is the same on every run
    LIMIT 300
),
pairs AS (
    SELECT a.stock_code AS item_a, b.stock_code AS item_b, COUNT(*) AS pair_orders
    FROM order_items a
    JOIN order_items b
      ON a.invoice = b.invoice AND a.stock_code < b.stock_code
    WHERE a.stock_code IN (SELECT stock_code FROM popular)
      AND b.stock_code IN (SELECT stock_code FROM popular)
    GROUP BY 1, 2
)
SELECT
    pairs.item_a,
    pa.description                                                       AS product_a,
    pairs.item_b,
    pb.description                                                       AS product_b,
    pair_orders,
    ROUND(100.0 * pair_orders / n_orders.n, 3)                           AS support_pct,
    ROUND(100.0 * pair_orders / ca.item_orders, 1)                       AS confidence_a_to_b_pct,
    ROUND(100.0 * pair_orders / cb.item_orders, 1)                       AS confidence_b_to_a_pct,
    ROUND(pair_orders * n_orders.n * 1.0 / (ca.item_orders * cb.item_orders), 2) AS lift
FROM pairs
CROSS JOIN n_orders
JOIN popular ca     ON ca.stock_code = pairs.item_a
JOIN popular cb     ON cb.stock_code = pairs.item_b
JOIN dim_product pa ON pa.stock_code = pairs.item_a
JOIN dim_product pb ON pb.stock_code = pairs.item_b
WHERE pair_orders >= 300
ORDER BY lift DESC, pair_orders DESC, pairs.item_a, pairs.item_b
LIMIT 30
