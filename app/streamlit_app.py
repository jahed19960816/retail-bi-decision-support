"""Retail BI & Decision Support - interactive app.

Run:  streamlit run app/streamlit_app.py   (after `python run_pipeline.py`)
"""

import json
import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retail_bi import assistant, config  # noqa: E402

st.set_page_config(page_title="Retail BI & Decision Support", page_icon="📊", layout="wide")

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
NEUTRAL = "#a8a7a1"
TABLES = config.TABLES_DIR


# ---------- data access ----------

def warehouse_ready() -> bool:
    return config.WAREHOUSE_DB.exists() and (config.REPORTS_DIR / "facts.json").exists()


@st.cache_data(show_spinner=False)
def sql(query: str, params: tuple = ()) -> pd.DataFrame:
    with assistant.read_only_connection() as con:
        return con.execute(query, list(params)).df()


@st.cache_data(show_spinner=False)
def table(name: str) -> pd.DataFrame:
    return pd.read_csv(TABLES / f"{name}.csv")


@st.cache_data(show_spinner=False)
def facts() -> dict:
    return json.loads((config.REPORTS_DIR / "facts.json").read_text())


def gbp(x: float) -> str:
    if abs(x) >= 1e6:
        return f"£{x / 1e6:.2f}M"
    if abs(x) >= 1e3:
        return f"£{x / 1e3:.1f}K"
    return f"£{x:,.0f}"


def pct_delta(new: float, old: float) -> str | None:
    if not old:
        return None
    return f"{(new / old - 1) * 100:+.1f}% vs prior period"


# ---------- pages ----------

def page_overview():
    st.title("Business overview")
    bounds = sql("SELECT MIN(order_date) AS lo, MAX(order_date) AS hi FROM fact_sales").iloc[0]
    countries = sql("SELECT country, SUM(line_revenue) r FROM fact_sales GROUP BY 1 ORDER BY r DESC")["country"].tolist()

    # One filter row that scopes every chart on the page.
    c1, c2 = st.columns([2, 3])
    picked_range = c1.date_input(
        "Date range", value=(bounds["lo"].date(), bounds["hi"].date()),
        min_value=bounds["lo"].date(), max_value=bounds["hi"].date(),
    )
    chosen = c2.multiselect("Countries (empty = all)", countries, default=[])
    if not isinstance(picked_range, tuple) or len(picked_range) != 2:
        st.info("Pick an end date to update the dashboard.")
        return
    start, end = picked_range

    where = "order_date BETWEEN ? AND ?"
    params: list = [pd.Timestamp(start), pd.Timestamp(end)]
    if chosen:
        where += f" AND country IN ({','.join('?' * len(chosen))})"
        params += chosen

    # Equal-length prior period for deltas.
    span = pd.Timestamp(end) - pd.Timestamp(start)
    prev_params = [pd.Timestamp(start) - span - pd.Timedelta(days=1), pd.Timestamp(start) - pd.Timedelta(days=1)] + params[2:]

    kpi_sql = f"""
        SELECT SUM(line_revenue) AS net_revenue,
               COUNT(DISTINCT invoice) FILTER (WHERE NOT is_return) AS orders,
               COUNT(DISTINCT customer_id) FILTER (WHERE NOT is_return) AS customers,
               SUM(line_revenue) FILTER (WHERE NOT is_return)
                 / NULLIF(COUNT(DISTINCT invoice) FILTER (WHERE NOT is_return), 0) AS aov,
               100.0 * -SUM(line_revenue) FILTER (WHERE is_return)
                 / NULLIF(SUM(line_revenue) FILTER (WHERE NOT is_return), 0) AS return_rate
        FROM fact_sales WHERE {where}"""
    cur = sql(kpi_sql, tuple(params)).iloc[0]
    prev = sql(kpi_sql, tuple(prev_params)).iloc[0]
    has_prev = pd.notna(prev["net_revenue"])

    k = st.columns(5)
    k[0].metric("Net revenue", gbp(cur["net_revenue"] or 0), pct_delta(cur["net_revenue"], prev["net_revenue"]) if has_prev else None)
    k[1].metric("Orders", f"{int(cur['orders'] or 0):,}", pct_delta(cur["orders"], prev["orders"]) if has_prev else None)
    k[2].metric("Customers", f"{int(cur['customers'] or 0):,}", pct_delta(cur["customers"], prev["customers"]) if has_prev else None)
    k[3].metric("Avg order value", gbp(cur["aov"] or 0), pct_delta(cur["aov"], prev["aov"]) if has_prev else None)
    k[4].metric("Return rate", f"{(cur['return_rate'] or 0):.2f}%",
                f"{cur['return_rate'] - prev['return_rate']:+.2f} pts" if has_prev and pd.notna(prev["return_rate"]) else None,
                delta_color="inverse")

    monthly = sql(f"""
        SELECT DATE_TRUNC('month', order_date) AS month, SUM(line_revenue) AS net_revenue,
               COUNT(DISTINCT invoice) FILTER (WHERE NOT is_return) AS orders
        FROM fact_sales WHERE {where} GROUP BY 1 ORDER BY 1""", tuple(params))
    st.subheader("Monthly net revenue")
    st.altair_chart(
        alt.Chart(monthly).mark_bar(color=SERIES[0], cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
            x=alt.X("yearmonth(month):T", title=None),
            y=alt.Y("net_revenue:Q", title="Net revenue (£)", axis=alt.Axis(format="~s")),
            tooltip=[alt.Tooltip("yearmonth(month):T", title="Month"),
                     alt.Tooltip("net_revenue:Q", title="Net revenue (£)", format=",.0f"),
                     alt.Tooltip("orders:Q", title="Orders", format=",")],
        ).properties(height=320),
        width="stretch",
    )

    left, right = st.columns(2)
    top = sql(f"""
        SELECT p.description AS product, p.product_family, SUM(f.line_revenue) AS net_revenue
        FROM fact_sales f JOIN dim_product p ON f.stock_code = p.stock_code
        WHERE {where.replace('order_date', 'f.order_date').replace('country', 'f.country')}
        GROUP BY ALL ORDER BY net_revenue DESC LIMIT 10""", tuple(params))
    left.subheader("Top 10 products")
    left.altair_chart(
        alt.Chart(top).mark_bar(color=SERIES[0], cornerRadiusTopRight=3, cornerRadiusBottomRight=3).encode(
            y=alt.Y("product:N", sort="-x", title=None),
            x=alt.X("net_revenue:Q", title="Net revenue (£)", axis=alt.Axis(format="~s")),
            tooltip=["product", "product_family", alt.Tooltip("net_revenue:Q", format=",.0f", title="Net revenue (£)")],
        ).properties(height=330),
        width="stretch",
    )
    fam = sql(f"""
        SELECT p.product_family, SUM(f.line_revenue) AS net_revenue
        FROM fact_sales f JOIN dim_product p ON f.stock_code = p.stock_code
        WHERE {where.replace('order_date', 'f.order_date').replace('country', 'f.country')}
        GROUP BY 1 ORDER BY 2 DESC""", tuple(params))
    right.subheader("Revenue by product family")
    right.altair_chart(
        alt.Chart(fam).mark_bar(color=SERIES[0], cornerRadiusTopRight=3, cornerRadiusBottomRight=3).encode(
            y=alt.Y("product_family:N", sort="-x", title=None),
            x=alt.X("net_revenue:Q", title="Net revenue (£)", axis=alt.Axis(format="~s")),
            tooltip=["product_family", alt.Tooltip("net_revenue:Q", format=",.0f", title="Net revenue (£)")],
        ).properties(height=330),
        width="stretch",
    )

    with st.expander("Executive insights brief (auto-generated)", expanded=False):
        st.markdown((config.REPORTS_DIR / "insights.md").read_text())


def page_customers():
    st.title("Customers: RFM segments & retention")
    prof = table("segment_profile")
    cols = st.columns(len(prof))
    for col, (_, row) in zip(cols, prof.iterrows()):
        col.metric(f"{row['segment']} · customers", f"{int(row['customers']):,}",
                   f"{row['revenue_share_pct']:.0f}% of revenue", delta_color="off")

    shares = prof.melt(id_vars="segment", value_vars=["customer_share_pct", "revenue_share_pct"],
                       var_name="measure", value_name="share")
    shares["measure"] = shares["measure"].map({"customer_share_pct": "% of customers", "revenue_share_pct": "% of revenue"})
    st.altair_chart(
        alt.Chart(shares).mark_bar(cornerRadiusTopRight=3, cornerRadiusBottomRight=3).encode(
            y=alt.Y("segment:N", sort=prof["segment"].tolist(), title=None),
            yOffset="measure:N",
            x=alt.X("share:Q", title="Share (%)"),
            color=alt.Color("measure:N", scale=alt.Scale(range=SERIES[:2]), legend=alt.Legend(title=None, orient="top")),
            tooltip=["segment", "measure", alt.Tooltip("share:Q", format=".1f")],
        ).properties(height=300),
        width="stretch",
    )
    st.subheader("What to do with each segment")
    st.dataframe(
        prof[["segment", "customers", "median_recency_days", "avg_orders", "avg_revenue", "revenue_share_pct", "recommended_action"]],
        hide_index=True, width="stretch",
    )

    st.subheader("Cohort retention (% of each monthly cohort active N months later)")
    ret = table("cohort_retention").set_index("cohort")
    long = ret.drop(columns="cohort_size").reset_index().melt(id_vars="cohort", var_name="month", value_name="retention").dropna()
    long["month"] = long["month"].astype(int)
    long = long[(long["month"] >= 1) & (long["month"] <= 12)]
    st.altair_chart(
        alt.Chart(long).mark_rect().encode(
            x=alt.X("month:O", title="Months since first purchase"),
            y=alt.Y("cohort:O", title=None),
            color=alt.Color("retention:Q", scale=alt.Scale(scheme="blues", domain=[0, 50]), title="% active"),
            tooltip=["cohort", "month", alt.Tooltip("retention:Q", format=".1f", title="% active")],
        ).properties(height=560),
        width="stretch",
    )
    st.caption("The Dec 2009 cohort includes customers who bought before the data starts, so its retention is overstated.")

    st.subheader("Look up a customer")
    seg = table("customer_segments")
    cid = st.number_input("Customer ID", min_value=int(seg["customer_id"].min()), max_value=int(seg["customer_id"].max()),
                          value=int(seg.sort_values("monetary", ascending=False)["customer_id"].iloc[0]))
    match = seg[seg["customer_id"] == cid]
    if match.empty:
        st.info("No segment for this customer ID (unknown, or returns cancelled out all purchases).")
    else:
        r = match.iloc[0]
        st.write(f"**Segment:** {r['segment']} · RFM code {r['rfm_code']} · last order {int(r['recency_days'])} days ago · "
                 f"{int(r['frequency'])} orders · {gbp(r['monetary'])} net revenue")
        st.write(f"**Recommended action:** {r['recommended_action']}")


def page_products():
    st.title("Products & markets")
    fam = table("kpi_product_family")
    st.subheader("Category growth (Dec 2010 – Nov 2011 vs prior 12 months)")
    fam["direction"] = fam["yoy_growth_pct"].apply(lambda v: "Growing" if v >= 0 else "Declining")
    st.altair_chart(
        alt.Chart(fam).mark_bar(cornerRadiusTopRight=3, cornerRadiusBottomRight=3).encode(
            y=alt.Y("product_family:N", sort="-x", title=None),
            x=alt.X("yoy_growth_pct:Q", title="YoY growth (%)"),
            color=alt.Color("direction:N", scale=alt.Scale(domain=["Growing", "Declining"], range=["#2a78d6", "#e34948"]),
                            legend=alt.Legend(title=None, orient="top")),
            tooltip=["product_family", alt.Tooltip("yoy_growth_pct:Q", format="+.1f", title="YoY %"),
                     alt.Tooltip("revenue_dec10_nov11:Q", format=",.0f", title="Latest-year revenue (£)"),
                     alt.Tooltip("return_rate_pct:Q", format=".2f", title="Return rate %")],
        ).properties(height=330),
        width="stretch",
    )
    st.subheader("Frequently bought together (market basket)")
    basket = table("kpi_market_basket")
    st.dataframe(basket[["product_a", "product_b", "pair_orders", "confidence_a_to_b_pct", "lift"]].head(15),
                 hide_index=True, width="stretch")
    st.caption("Lift = how many times more often the pair is bought together than if purchases were independent. "
               "Use high-lift pairs for bundles and 'often bought with' recommendations.")

    left, right = st.columns(2)
    left.subheader("Biggest return losses")
    left.dataframe(table("kpi_return_hotspots")[["description", "returned_value", "return_rate_pct"]].head(10),
                   hide_index=True, width="stretch")
    right.subheader("Export markets")
    right.dataframe(table("kpi_country_performance").query("country != 'United Kingdom'")
                    [["country", "net_revenue", "orders", "customers", "avg_order_value"]].head(10),
                    hide_index=True, width="stretch")


def page_forecast():
    st.title("Sales forecast (next 28 days)")
    f = facts()["forecast"]
    c = st.columns(3)
    c[0].metric("Forecast, next 28 days", gbp(f["next_28_days_total"]))
    c[1].metric("Model error (daily WAPE)", f"{f['daily_wape_pct']:.1f}%",
                f"{f['error_reduction_pct']:.1f}% lower than best baseline", delta_color="normal")
    c[2].metric("Best baseline", f"{f['best_baseline_wape_pct']:.1f}%", f["best_baseline"], delta_color="off")

    hist = sql("SELECT order_date AS date, SUM(line_revenue) AS value FROM fact_sales "
               "WHERE order_date >= (SELECT MAX(order_date) FROM fact_sales) - INTERVAL 70 DAY GROUP BY 1 ORDER BY 1")
    hist["series"] = "Actual"
    fut = sql("SELECT date, forecast AS value, lower_80, upper_80 FROM daily_forecast ORDER BY date")
    fut["series"] = "Forecast"
    band = alt.Chart(fut).mark_area(opacity=0.18, color=SERIES[1]).encode(x="date:T", y="lower_80:Q", y2="upper_80:Q")
    lines = alt.Chart(pd.concat([hist, fut[["date", "value", "series"]]])).mark_line(strokeWidth=2).encode(
        x=alt.X("date:T", title=None),
        y=alt.Y("value:Q", title="Daily net revenue (£)", axis=alt.Axis(format="~s")),
        color=alt.Color("series:N", scale=alt.Scale(range=SERIES[:2]), legend=alt.Legend(title=None, orient="top")),
        tooltip=[alt.Tooltip("date:T"), "series", alt.Tooltip("value:Q", format=",.0f", title="£")],
    )
    st.altair_chart((band + lines).properties(height=360), width="stretch")
    st.caption("Shaded band = 80% prediction interval (quantile gradient boosting). Saturdays and the Christmas shutdown are ~£0.")

    st.subheader("How good is the model? (6-month backtest)")
    scores = table("forecast_scores")
    st.dataframe(scores, hide_index=True, width="stretch")
    bt = table("forecast_backtest")
    bt["date"] = pd.to_datetime(bt["date"])
    weekly = bt.set_index("date")[["actual", "model"]].resample("W-SUN").sum().reset_index().melt(
        id_vars="date", var_name="series", value_name="value")
    weekly["series"] = weekly["series"].map({"actual": "Actual", "model": "Forecast (28 days ahead)"})
    st.altair_chart(
        alt.Chart(weekly).mark_line(point=True, strokeWidth=2).encode(
            x=alt.X("date:T", title="Week"), y=alt.Y("value:Q", title="Weekly revenue (£)", axis=alt.Axis(format="~s")),
            color=alt.Color("series:N", scale=alt.Scale(range=SERIES[:2]), legend=alt.Legend(title=None, orient="top")),
            tooltip=[alt.Tooltip("date:T", title="Week ending"), "series", alt.Tooltip("value:Q", format=",.0f", title="£")],
        ).properties(height=300),
        width="stretch",
    )
    with st.expander("Model selection (validation window, Jan – Jun 2011)"):
        st.dataframe(table("forecast_model_selection"), hide_index=True)


def page_anomalies():
    st.title("Anomaly monitoring")
    a = facts()["anomalies"]
    c = st.columns(3)
    c[0].metric("Orders flagged for review", f"{a['orders_flagged']}")
    c[1].metric("Cancellation rate, flagged", f"{a['flagged_cancellation_rate_pct']}%")
    c[2].metric("Cancellation rate, other orders", f"{a['normal_cancellation_rate_pct']}%", f"{a['lift']}x lift", delta_color="off")
    st.subheader("Order review queue")
    q = table("order_anomalies")
    st.dataframe(q[["invoice", "invoice_date", "customer_id", "country", "order_value", "max_line_qty", "main_driver",
                    "was_cancelled", "anomaly_score"]].head(50), hide_index=True, width="stretch")
    st.subheader("Unusual days")
    st.dataframe(table("daily_anomalies_top")[["date", "actual", "expected", "robust_z", "direction", "invoice",
                                                "order_value", "country", "largest_order_share_pct"]],
                 hide_index=True, width="stretch")
    st.image(str(config.FIGURES_DIR / "08_daily_anomalies.png"), width="stretch")


def show_answer(ans: assistant.Answer):
    if ans.error:
        st.error(ans.error)
    if ans.narrative:
        st.markdown(ans.narrative)
    if not ans.result.empty:
        st.dataframe(ans.result, hide_index=True, width="stretch")
        numeric = ans.result.select_dtypes("number").columns
        first = ans.result.columns[0]
        if len(ans.result) > 1 and len(numeric) >= 1 and first not in numeric:
            st.bar_chart(ans.result.set_index(first)[numeric[0]], color=SERIES[0])
    if ans.sql:
        with st.expander("SQL used (verify before acting)"):
            st.code(ans.sql, language="sql")
            if ans.explanation:
                st.caption(ans.explanation)


def page_assistant():
    st.title("Ask your data")
    online = assistant.llm_available()
    if online:
        st.success(f"AI assistant online ({assistant.MODEL}). Questions become read-only SQL, run locally; "
                   "the answer is written only from the query result.")
    else:
        st.info("Offline mode: no Claude API credentials found. Pick a curated question below, or set "
                "`ANTHROPIC_API_KEY` and restart to ask anything in plain English.")

    st.write("**Try a question:**")
    picked = None
    cols = st.columns(2)
    for i, q in enumerate(assistant.EXAMPLE_QUESTIONS):
        if cols[i % 2].button(q, width="stretch"):
            picked = q

    if online:
        typed = st.text_input("Or ask your own question", placeholder="e.g. Which customers in Germany spent the most in 2011?")
        question = typed or picked
        if question:
            with st.spinner("Writing SQL, running it, and summarising..."):
                ans = assistant.ask(question)
            st.subheader(question)
            show_answer(ans)
        st.divider()
        if st.button("Generate AI leadership brief from the pipeline facts"):
            with st.spinner("Writing brief..."):
                try:
                    st.markdown(assistant.ai_brief(facts()))
                except RuntimeError as exc:
                    st.error(str(exc))
    elif picked:
        st.subheader(picked)
        show_answer(assistant.run_example(picked))


def page_quality():
    st.title("Data quality & validation")
    st.markdown((config.REPORTS_DIR / "data_quality.md").read_text())


PAGES = {
    "Overview": page_overview,
    "Customers": page_customers,
    "Products & markets": page_products,
    "Forecast": page_forecast,
    "Anomalies": page_anomalies,
    "Ask your data (AI)": page_assistant,
    "Data quality": page_quality,
}


def main():
    st.sidebar.title("Retail BI")
    st.sidebar.caption("UCI Online Retail II · Dec 2009 – Dec 2011 · 1M+ transactions")
    if not warehouse_ready():
        st.error("Warehouse not found. Run `python run_pipeline.py` first, then restart the app.")
        return
    choice = st.sidebar.radio("Page", list(PAGES))
    PAGES[choice]()


main()
