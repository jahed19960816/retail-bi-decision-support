"""End-to-end pipeline: raw Excel -> clean data -> DuckDB warehouse -> SQL KPIs ->
segmentation, cohorts, forecasting, anomalies -> figures, reports, Power BI export."""

import json
import time

import pandas as pd

from retail_bi import anomalies, cohorts, config, forecast, insights, plots, powerbi_export, rfm
from retail_bi.clean import clean_transactions, profile
from retail_bi.ingest import load_raw
from retail_bi.validate import assert_valid, results_frame, run_checks
from retail_bi.warehouse import add_tables, build_dim_customer, build_dim_date, build_dim_product, build_warehouse, run_kpi_queries


def _md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join("" if pd.isna(v) else (f"{v:,.2f}" if isinstance(v, float) else str(v)) for v in row) + " |")
    return "\n".join(lines)


def _step(name: str):
    print(f"\n==> {name}")
    return time.perf_counter()


def _done(t0: float) -> None:
    print(f"    done in {time.perf_counter() - t0:.1f}s")


def write_data_quality_report(raw, log_df, prof, checks_df) -> None:
    lines = [
        "# Data quality report",
        "",
        f"Source: UCI Online Retail II ({prof['raw_rows']:,} raw rows, two yearly Excel sheets).",
        "",
        "## Cleaning steps",
        "",
        _md_table(log_df),
        "",
        "## Result",
        "",
        f"- Clean lines: **{prof['clean_rows']:,}** ({prof['sales_lines']:,} sales + {prof['return_lines']:,} returns)",
        f"- Orders: {prof['invoices']:,} · customers: {prof['customers']:,} · products: {prof['products']:,} · countries: {prof['countries']}",
        f"- Period: {prof['date_min']} -> {prof['date_max']}",
        f"- Gross revenue £{prof['gross_revenue']:,.2f}, returns £{prof['returns_value']:,.2f}, net £{prof['net_revenue']:,.2f}",
        f"- Lines without a customer ID: {prof['raw_missing_customer_pct']}% raw -> {prof['clean_missing_customer_pct']}% clean "
        "(kept for revenue KPIs, excluded from customer analytics)",
        "",
        "## Validation checks",
        "",
        _md_table(checks_df.assign(passed=checks_df["passed"].map({True: "PASS", False: "WARN"}))),
        "",
        "## Known limitations",
        "",
        "- Some refunds were booked as manual ('M') adjustments without a product code; these are removed with the other",
        "  non-product lines, so a few reversed orders (e.g. invoice 556444, £38,970) still count as sales. The order",
        "  anomaly detector flags them for review.",
        "- Dec 2009 is the first month of data, so it contains customers who bought before the dataset starts",
        "  (cohort and 'new customer' figures for that month are overstated).",
        "- Product families are keyword-derived from descriptions (about 5% of revenue stays in 'Other').",
    ]
    (config.REPORTS_DIR / "data_quality.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_model_report(selection, scores, improvement, weekly_improvement, spec, multipliers, band_check, sil, seg_profile, curve, anomaly_eval, daily_flagged) -> None:
    lines = [
        "# Model results",
        "",
        "## 1. Sales forecasting (28 days ahead, daily net revenue)",
        "",
        "Every feature is known at least 28 days in advance (lags >= 28 days, last year's values, calendar),",
        "so one model forecasts the whole next 4 weeks without leaking future data.",
        "",
        "**Model selection** on the validation window (6 x 28-day folds, Jan-Jun 2011):",
        "",
        _md_table(selection),
        "",
        f"Selected: `{spec.name}` (HistGradientBoostingRegressor, {spec.loss}, max_leaf_nodes={spec.max_leaf_nodes}, "
        f"blended {int(spec.blend_last_year * 100)}% with last year's same-weekday value).",
        "",
        "**Test results** on the last 6 x 28-day folds (25 Jun - 9 Dec 2011), never used for selection:",
        "",
        _md_table(scores),
        "",
        f"- Daily WAPE **{improvement['model']:.2f}%** vs best baseline ({improvement['best_baseline']}) "
        f"{improvement['best_baseline_value']:.2f}% -> **{improvement['error_reduction_pct']:.1f}% lower error**.",
        f"- Weekly WAPE {weekly_improvement['model']:.2f}% vs {weekly_improvement['best_baseline_value']:.2f}% -> "
        f"{weekly_improvement['error_reduction_pct']:.1f}% lower error.",
        "- WAPE = sum(|actual - forecast|) / sum(actual). Lower is better. The model also has lower bias than the",
        "  short-term baselines, which under-forecast the autumn ramp-up.",
        "",
        "**80% range for each day.** Quantile gradient boosting was rejected on the validation window: about 18% of days",
        "have zero revenue, which pinned its low edge at 0. The range now comes from past backtest errors instead.",
        "",
        f"- On open days, actual revenue usually landed between {multipliers[0]:.2f}x and {multipliers[1]:.2f}x the forecast. "
        "The range is the forecast times those multipliers. Saturdays are closed, so they run from 0 up to the forecast.",
        f"- Checked on the test folds over {band_check['open_days']} open days, calibrating each fold only on earlier folds: "
        f"**{band_check['coverage_pct']}%** of days fell inside (target 80%), {band_check['below_lower_pct']}% below and "
        f"{band_check['above_upper_pct']}% above.",
        "- The range applies to one day at a time. Adding up daily edges does not give an 80% range for a week or a month.",
        "",
        "## 2. Customer segmentation (RFM + K-Means)",
        "",
        "Silhouette score by number of clusters (log-scaled, standardised R/F/M):",
        "",
        _md_table(sil),
        "",
        "k = 4 is the best of k = 3..8 and gives four segments a marketing team can act on (k = 2 scores higher but",
        "only separates 'active' from 'inactive').",
        "",
        _md_table(seg_profile.drop(columns=["recommended_action"])),
        "",
        "## 3. Cohort retention",
        "",
        "Customer-weighted average retention (excluding the left-censored Dec 2009 cohort):",
        "",
        _md_table(curve.head(12)),
        "",
        "## 4. Anomaly detection",
        "",
        f"- Daily revenue: {int(daily_flagged['is_anomaly'].sum())} anomalous days (robust z-score > 3.5 vs the same weekday",
        "  in the surrounding +/-4 weeks), e.g. the 29 Apr 2011 Royal Wedding bank holiday.",
        f"- Orders: Isolation Forest on contextual features flags {anomaly_eval['orders_flagged']} unusually large orders. "
        f"Flagged orders were later cancelled **{anomaly_eval['flagged_cancellation_rate_pct']}%** of the time vs "
        f"{anomaly_eval['normal_cancellation_rate_pct']}% for other orders (**{anomaly_eval['lift']}x lift**), and the queue",
        "  includes the two biggest cancelled bulk orders (80,995 and 74,215 units).",
    ]
    (config.REPORTS_DIR / "model_results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> dict:
    config.ensure_dirs()
    started = time.perf_counter()

    t = _step("1/8 Load raw data")
    raw = load_raw()
    _done(t)

    t = _step("2/8 Clean & validate")
    sales, log = clean_transactions(raw)
    checks = run_checks(sales)
    assert_valid(checks)
    checks_df = results_frame(checks)
    prof = profile(raw, sales)
    sales.to_parquet(config.DATA_PROCESSED / "sales_clean.parquet", index=False)
    log.to_frame().to_csv(config.TABLES_DIR / "data_quality_log.csv", index=False)
    checks_df.to_csv(config.TABLES_DIR / "data_validation_checks.csv", index=False)
    write_data_quality_report(raw, log.to_frame(), prof, checks_df)
    print(f"    {prof['raw_rows']:,} raw rows -> {prof['clean_rows']:,} clean lines; "
          f"{int(checks_df['passed'].sum())}/{len(checks_df)} checks passed")
    _done(t)

    t = _step("3/8 Build DuckDB warehouse & run SQL KPIs")
    build_warehouse(sales)
    kpis = run_kpi_queries()
    print(f"    {len(kpis)} SQL result tables written to reports/tables")
    _done(t)

    t = _step("4/8 RFM segmentation & cohorts")
    rfm_scored = rfm.score_rfm(rfm.build_rfm(sales))
    sil = rfm.silhouette_by_k(rfm_scored)
    segmented = rfm.segment_customers(rfm_scored)
    seg_profile = rfm.segment_profile(segmented)
    segmented.to_csv(config.TABLES_DIR / "customer_segments.csv", index=False)
    seg_profile.to_csv(config.TABLES_DIR / "segment_profile.csv", index=False)
    sil.to_csv(config.TABLES_DIR / "segment_silhouette.csv", index=False)
    retention = cohorts.retention_matrix(sales)
    curve = cohorts.average_retention_curve(retention)
    conversion = cohorts.second_order_conversion(sales)
    retention.to_csv(config.TABLES_DIR / "cohort_retention.csv")
    curve.to_csv(config.TABLES_DIR / "cohort_retention_curve.csv", index=False)
    conversion.to_csv(config.TABLES_DIR / "cohort_second_order_conversion.csv", index=False)
    _done(t)

    t = _step("5/8 Forecasting (model selection, backtest, next 28 days)")
    daily = forecast.daily_revenue(sales)
    spec, selection = forecast.select_spec(daily)
    bt = forecast.backtest(daily, forecast.fold_starts(daily, config.BACKTEST_FOLDS), spec)
    scores = forecast.score(bt)
    improvement = forecast.improvement_vs_best_baseline(scores)
    weekly_improvement = forecast.improvement_vs_best_baseline(scores, "weekly_wape_pct")
    history = forecast.backtest(daily, forecast.fold_starts(daily, 2 * config.BACKTEST_FOLDS, skip_folds=config.BACKTEST_FOLDS), spec)
    band_check = forecast.score_interval(history, bt)
    multipliers = forecast.interval_multipliers(pd.concat([history, bt]))
    future = forecast.forecast_future(daily, spec, multipliers)
    pd.DataFrame([band_check]).to_csv(config.TABLES_DIR / "forecast_interval_check.csv", index=False)
    selection.to_csv(config.TABLES_DIR / "forecast_model_selection.csv", index=False)
    scores.to_csv(config.TABLES_DIR / "forecast_scores.csv", index=False)
    bt.round(2).to_csv(config.TABLES_DIR / "forecast_backtest.csv")
    future.to_csv(config.TABLES_DIR / "forecast_next_28_days.csv")
    print(f"    selected {spec.name}; daily WAPE {improvement['model']:.2f}% vs best baseline "
          f"{improvement['best_baseline_value']:.2f}% ({improvement['error_reduction_pct']:.1f}% lower)")
    _done(t)

    t = _step("6/8 Anomaly detection")
    daily_scored = anomalies.daily_anomalies(daily)
    daily_top = anomalies.explain_daily(daily_scored, sales)
    order_scores = anomalies.order_anomalies(anomalies.order_features(sales))
    anomaly_eval = anomalies.anomaly_validation(order_scores)
    daily_top.to_csv(config.TABLES_DIR / "daily_anomalies_top.csv", index=False)
    order_scores[order_scores["is_anomaly"]].to_csv(config.TABLES_DIR / "order_anomalies.csv")
    print(f"    {int(daily_scored['is_anomaly'].sum())} anomalous days; {anomaly_eval['orders_flagged']} orders flagged "
          f"({anomaly_eval['lift']}x cancellation lift)")
    _done(t)

    t = _step("7/8 Figures, reports & insights")
    plots.monthly_revenue_yoy(kpis["monthly_performance"])
    plots.revenue_mix(kpis["new_vs_returning"])
    plots.rfm_segments(seg_profile)
    plots.cohort_heatmap(retention)
    plots.forecast_backtest(bt, improvement["best_baseline"])
    plots.forecast_error_comparison(scores)
    plots.forecast_future(daily, future)
    plots.daily_anomalies(daily_scored)
    plots.weekday_hour_heatmap(kpis["weekday_hour"])
    plots.pareto_curves(
        sales[sales["customer_id"].notna()].groupby("customer_id")["line_revenue"].sum(),
        sales.groupby("stock_code")["line_revenue"].sum(),
    )
    plots.product_family_growth(kpis["product_family"])
    plots.top_countries(kpis["country_performance"])
    write_model_report(selection, scores, improvement, weekly_improvement, spec, multipliers, band_check, sil, seg_profile, curve, anomaly_eval, daily_scored)

    results = {
        "kpis": kpis, "segment_profile": seg_profile, "forecast_improvement": improvement,
        "forecast_future": future, "anomaly_validation": anomaly_eval,
    }
    facts = insights.build_facts(results)
    (config.REPORTS_DIR / "insights.md").write_text(insights.render_brief(facts), encoding="utf-8")
    (config.REPORTS_DIR / "facts.json").write_text(json.dumps(facts, indent=2, default=str), encoding="utf-8")
    _done(t)

    t = _step("8/8 Warehouse extras & Power BI export")
    add_tables({
        "customer_segments": segmented[["customer_id", "recency_days", "frequency", "monetary", "r_score", "f_score",
                                        "m_score", "rfm_code", "segment"]],
        "daily_forecast": future.reset_index(),
        "forecast_backtest": bt.reset_index()[["date", "fold", "actual", "model"]],
        "order_anomalies": order_scores[order_scores["is_anomaly"]].reset_index()[
            ["invoice", "invoice_date", "customer_id", "country", "order_value", "anomaly_score", "main_driver", "was_cancelled"]],
    })
    dims = {"dim_product": build_dim_product(sales), "dim_customer": build_dim_customer(sales), "dim_date": build_dim_date(sales)}
    written = powerbi_export.export(sales, dims, segmented, seg_profile, daily, bt, future, retention, order_scores)
    print("    " + "\n    ".join(written))
    _done(t)

    print(f"\nPipeline finished in {time.perf_counter() - started:.0f}s. See reports/ and powerbi/data/.")
    return facts
