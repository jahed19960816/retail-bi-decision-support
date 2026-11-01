import pytest

from retail_bi.assistant import SQLGuardError, guard_sql


@pytest.mark.parametrize("sql", [
    "SELECT 1",
    "select country, sum(line_revenue) from fact_sales group by 1;",
    "WITH t AS (SELECT * FROM v_orders) SELECT COUNT(*) FROM t",
    "SELECT * FROM fact_sales ORDER BY invoice_date LIMIT 10 OFFSET 5",
    "-- top products\nSELECT stock_code FROM dim_product",
])
def test_read_only_queries_are_allowed(sql):
    assert guard_sql(sql)


@pytest.mark.parametrize("sql", [
    "DROP TABLE fact_sales",
    "DELETE FROM fact_sales",
    "SELECT 1; DROP TABLE fact_sales",
    "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT * FROM read_parquet('data/raw/x.parquet')",
    "COPY fact_sales TO 'out.csv'",
    "ATTACH 'other.db'",
    "INSTALL httpfs",
    "UPDATE fact_sales SET quantity = 0",
    "",
])
def test_writes_and_file_access_are_blocked(sql):
    with pytest.raises(SQLGuardError):
        guard_sql(sql)
