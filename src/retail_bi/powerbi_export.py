"""Export a Power BI-ready star schema (CSV) to powerbi/data.

Tables
------
fact_sales            line-level sales and returns (one row per invoice line)
dim_product           product master with keyword-derived product_family
dim_customer          customer master with cohort and RFM segment/scores
dim_date              calendar table (mark as date table in Power BI)
fact_forecast         daily actuals, backtest predictions and the 28-day forward forecast
fact_cohort_retention cohort x months-since-first-purchase retention (long format)
segment_profile       one row per RFM segment with recommended action
order_anomalies       orders flagged for review by the anomaly detector
"""

import pandas as pd

from retail_bi import config


def export(sales: pd.DataFrame, dims: dict[str, pd.DataFrame], segmented: pd.DataFrame, segment_profile: pd.DataFrame,
           daily: pd.Series, backtest: pd.DataFrame, future: pd.DataFrame, retention: pd.DataFrame,
           order_scores: pd.DataFrame) -> list[str]:
    out = config.POWERBI_DATA_DIR
    out.mkdir(parents=True, exist_ok=True)
    written = []

    def save(frame: pd.DataFrame, name: str) -> None:
        frame.to_csv(out / f"{name}.csv", index=False, date_format="%Y-%m-%d %H:%M:%S")
        written.append(f"{name}.csv ({len(frame):,} rows)")

    fact = sales[["invoice", "stock_code", "customer_id", "country", "invoice_date", "order_date",
                  "quantity", "unit_price", "line_revenue", "is_return", "is_guest"]].copy()
    fact["order_date"] = fact["order_date"].dt.date
    save(fact, "fact_sales")

    save(dims["dim_product"], "dim_product")

    seg_cols = ["customer_id", "recency_days", "frequency", "monetary", "r_score", "f_score", "m_score",
                "rfm_score", "rfm_code", "segment", "recommended_action"]
    customer = dims["dim_customer"].merge(segmented[seg_cols], on="customer_id", how="left")
    customer["segment"] = customer["segment"].fillna("No net purchases")
    save(customer, "dim_customer")

    date = dims["dim_date"].copy()
    date["date"] = date["date"].dt.date
    save(date, "dim_date")

    fc = daily.rename("actual").to_frame()
    fc = fc.join(backtest[["model"]].rename(columns={"model": "backtest_prediction"}), how="left")
    fc = pd.concat([fc, future.rename(columns={"forecast": "forward_forecast"})], axis=0)
    fc.index.name = "date"
    fc = fc.reset_index()
    fc["date"] = fc["date"].dt.date
    save(fc, "fact_forecast")

    long = (
        retention.drop(columns="cohort_size")
        .reset_index()
        .melt(id_vars="cohort", var_name="months_since_first", value_name="retention_pct")
        .dropna()
    )
    long = long.merge(retention["cohort_size"].reset_index(), on="cohort")
    save(long, "fact_cohort_retention")

    save(segment_profile, "segment_profile")

    flagged = order_scores[order_scores["is_anomaly"]].reset_index()
    save(flagged[["invoice", "invoice_date", "customer_id", "country", "order_value", "units", "distinct_products",
                  "max_line_qty", "anomaly_score", "main_driver", "was_cancelled"]], "order_anomalies")
    return written
