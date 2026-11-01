"""Integration tests against the real warehouse (skipped until `python run_pipeline.py` has run)."""

import pandas as pd
import pytest

from retail_bi import config
from retail_bi.warehouse import connect, run_sql_file

pytestmark = pytest.mark.skipif(not config.WAREHOUSE_DB.exists(), reason="run `python run_pipeline.py` first")


@pytest.fixture(scope="module")
def sales():
    return pd.read_parquet(config.DATA_PROCESSED / "sales_clean.parquet")


@pytest.mark.parametrize("path", sorted((config.SQL_DIR / "kpis").glob("*.sql")), ids=lambda p: p.stem)
def test_every_kpi_query_runs(path):
    with connect() as con:
        assert len(run_sql_file(con, path)) > 0


def test_sql_kpis_match_pandas(sales):
    with connect() as con:
        kpi = run_sql_file(con, config.SQL_DIR / "kpis" / "01_headline_kpis.sql").iloc[0]
    purchases = sales[~sales["is_return"]]
    assert kpi["net_revenue"] == pytest.approx(sales["line_revenue"].sum(), abs=0.05)
    assert kpi["orders"] == purchases["invoice"].nunique()
    assert kpi["customers"] == purchases["customer_id"].nunique()
    aov = purchases.groupby("invoice")["line_revenue"].sum().mean()
    assert kpi["avg_order_value"] == pytest.approx(aov, abs=0.01)


def test_monthly_revenue_sums_to_total(sales):
    with connect() as con:
        monthly = run_sql_file(con, config.SQL_DIR / "kpis" / "03_monthly_performance.sql")
    assert monthly["net_revenue"].sum() == pytest.approx(sales["line_revenue"].sum(), abs=1.0)
    assert monthly["is_partial_month"].sum() == 1


def test_assistant_self_corrects_a_failing_query(monkeypatch):
    """The assistant retries once with the DuckDB error, then explains the successful result (no API call)."""
    import json

    from retail_bi import assistant

    replies = iter([
        json.dumps({"sql": "SELECT no_such_column FROM fact_sales", "explanation": "first try"}),
        json.dumps({"sql": "SELECT COUNT(*) AS orders FROM v_orders", "explanation": "count orders"}),
        "There were 39,516 orders.",
    ])
    prompts = []

    def fake_create(client, system, user, effort, max_tokens=8000, json_schema=None):
        prompts.append(user)
        return next(replies)

    monkeypatch.setattr(assistant, "_client", lambda: object())
    monkeypatch.setattr(assistant, "_create", fake_create)
    ans = assistant.ask("How many orders were there?")
    assert ans.error == ""
    assert ans.attempts == 2
    assert "no_such_column" in prompts[1] and "Error" in prompts[1]
    assert int(ans.result["orders"].iloc[0]) == 39516
    assert ans.narrative.startswith("There were")


def test_assistant_offline_examples_all_run():
    from retail_bi import assistant

    for question in assistant.EXAMPLE_QUESTIONS:
        assert not assistant.run_example(question).result.empty, question
