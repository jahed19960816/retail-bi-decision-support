-- When do customers order? Orders and revenue by weekday and hour (for a heatmap).
SELECT
    ISODOW(invoice_date)        AS day_of_week,
    DAYNAME(invoice_date)       AS day_name,
    HOUR(invoice_date)          AS hour,
    COUNT(DISTINCT invoice)     AS orders,
    ROUND(SUM(line_revenue), 2) AS revenue
FROM fact_sales
WHERE NOT is_return
GROUP BY ALL
ORDER BY day_of_week, hour
