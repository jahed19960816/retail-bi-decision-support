"""Rule-based executive insights brief.

Turns the computed KPI / segment / forecast tables into a short, numbers-first
brief with recommended actions. This always runs (no API key needed); the LLM
assistant can then expand on it, grounded in the same numbers.
"""

import pandas as pd


def _gbp(x: float) -> str:
    if abs(x) >= 1e6:
        return f"£{x / 1e6:.2f}M"
    if abs(x) >= 1e3:
        return f"£{x / 1e3:.0f}K"
    return f"£{x:,.0f}"


def build_facts(results: dict) -> dict:
    """Collect the headline numbers the brief (and the LLM) are allowed to use."""
    kpi = results["kpis"]["headline_kpis"].iloc[0]
    period = results["kpis"]["period_comparison"].set_index("period")
    latest = period.iloc[-1]
    pareto = results["kpis"]["pareto_summary"]
    top_cust_share = float(pareto.query("entity == 'Customers' and quintile == 1")["revenue_share_pct"].iloc[0])
    top_prod_share = float(pareto.query("entity == 'Products' and quintile == 1")["revenue_share_pct"].iloc[0])
    seg = results["segment_profile"].set_index("segment")
    fam = results["kpis"]["product_family"]
    countries = results["kpis"]["country_performance"]
    returns = results["kpis"]["return_hotspots"]
    interval = results["kpis"]["repeat_purchase_interval"].iloc[0]
    fc = results["forecast_improvement"]
    future = results["forecast_future"]
    anomaly = results["anomaly_validation"]

    growing = fam[fam["product_family"] != "Other"].nlargest(2, "yoy_growth_pct")
    shrinking = fam[fam["product_family"] != "Other"].nsmallest(2, "yoy_growth_pct")
    export = countries[countries["country"] != "United Kingdom"]

    return {
        "period": "Dec 2009 - Dec 2011 (UCI Online Retail II, UK online gift wholesaler)",
        "net_revenue": float(kpi["net_revenue"]),
        "gross_revenue": float(kpi["gross_revenue"]),
        "return_rate_pct": float(kpi["return_rate_pct"]),
        "orders": int(kpi["orders"]),
        "customers": int(kpi["customers"]),
        "avg_order_value": float(kpi["avg_order_value"]),
        "repeat_customer_rate_pct": float(kpi["repeat_customer_rate_pct"]),
        "guest_revenue_share_pct": float(kpi["guest_revenue_share_pct"]),
        "yoy_revenue_growth_pct": float(latest["revenue_growth_pct"]),
        "yoy_orders_growth_pct": float(latest["orders_growth_pct"]),
        "yoy_aov_growth_pct": float(latest["aov_growth_pct"]),
        "top20_customers_revenue_share_pct": top_cust_share,
        "top20_products_revenue_share_pct": top_prod_share,
        "segments": {
            name: {
                "customers": int(row["customers"]),
                "customer_share_pct": float(row["customer_share_pct"]),
                "revenue_share_pct": float(row["revenue_share_pct"]),
                "total_revenue": float(row["total_revenue"]),
                "median_recency_days": float(row["median_recency_days"]),
            }
            for name, row in seg.iterrows()
        },
        "fastest_growing_categories": growing[["product_family", "yoy_growth_pct"]].to_dict("records"),
        "declining_categories": shrinking[["product_family", "yoy_growth_pct"]].to_dict("records"),
        "uk_revenue_share_pct": float(countries.loc[countries["country"] == "United Kingdom", "revenue_share_pct"].iloc[0]),
        "top_export_markets": export.head(3)[["country", "net_revenue", "customers"]].to_dict("records"),
        "top_return_losses": returns.head(3)[["description", "returned_value", "return_rate_pct"]].to_dict("records"),
        "median_days_between_orders": float(interval["median_days_between_orders"]),
        "forecast": {
            "daily_wape_pct": fc["model"],
            "best_baseline": fc["best_baseline"],
            "best_baseline_wape_pct": fc["best_baseline_value"],
            "error_reduction_pct": fc["error_reduction_pct"],
            "next_28_days_total": float(future["forecast"].sum()),
        },
        "anomalies": anomaly,
    }


def render_brief(facts: dict) -> str:
    seg = facts["segments"]
    champions = seg.get("Champions", {})
    at_risk = seg.get("At Risk", {})
    growing = ", ".join(f"{r['product_family']} ({r['yoy_growth_pct']:+.0f}%)" for r in facts["fastest_growing_categories"])
    declining = ", ".join(f"{r['product_family']} ({r['yoy_growth_pct']:+.0f}%)" for r in facts["declining_categories"])
    exports = ", ".join(f"{r['country']} ({_gbp(r['net_revenue'])}, {r['customers']} customers)" for r in facts["top_export_markets"])
    top_return = facts["top_return_losses"][0]
    fc = facts["forecast"]
    an = facts["anomalies"]

    lines = [
        "# Executive insights brief",
        "",
        f"_Data: {facts['period']}. Generated automatically from the pipeline outputs._",
        "",
        "## What happened",
        f"- **{_gbp(facts['net_revenue'])} net revenue** from {facts['orders']:,} orders and {facts['customers']:,} identified customers; "
        f"returns cost {facts['return_rate_pct']:.1f}% of gross sales.",
        f"- Latest 12 months vs prior 12: revenue **{facts['yoy_revenue_growth_pct']:+.1f}%** while orders moved "
        f"**{facts['yoy_orders_growth_pct']:+.1f}%** - growth came from bigger baskets (average order value "
        f"{facts['yoy_aov_growth_pct']:+.1f}%), not more orders.",
        f"- Revenue is concentrated: the top 20% of customers generate **{facts['top20_customers_revenue_share_pct']:.0f}%** of revenue "
        f"and the top 20% of products **{facts['top20_products_revenue_share_pct']:.0f}%**.",
        f"- The UK is {facts['uk_revenue_share_pct']:.0f}% of revenue. Biggest export markets: {exports} - "
        "a handful of wholesale accounts per country.",
        "",
        "## Customers",
        f"- **Champions** are {champions.get('customer_share_pct', 0):.0f}% of customers but "
        f"**{champions.get('revenue_share_pct', 0):.0f}% of revenue**.",
        f"- **At Risk**: {at_risk.get('customers', 0):,} customers who used to buy regularly "
        f"(median {at_risk.get('median_recency_days', 0):.0f} days since last order) and account for "
        f"**{_gbp(at_risk.get('total_revenue', 0))}** of historical revenue.",
        f"- {facts['repeat_customer_rate_pct']:.0f}% of customers order more than once; the median gap between orders is "
        f"{facts['median_days_between_orders']:.0f} days.",
        "",
        "## Products",
        f"- Growing categories: {growing}. Declining: {declining}.",
        f"- Biggest return loss: {top_return['description'].title()} ({_gbp(top_return['returned_value'])} returned, "
        f"{top_return['return_rate_pct']:.0f}% of its sales) - bulk orders cancelled shortly after being placed.",
        "",
        "## Forecast & monitoring",
        f"- The 28-day revenue forecast has a daily error (WAPE) of **{fc['daily_wape_pct']:.1f}%**, "
        f"**{fc['error_reduction_pct']:.1f}% lower** than the best simple baseline ({fc['best_baseline'].lower()}, "
        f"{fc['best_baseline_wape_pct']:.1f}%), measured on 6 months the model never saw during selection.",
        f"- Forecast for the next 28 days: **{_gbp(fc['next_28_days_total'])}**, including the Christmas shutdown.",
        f"- The order anomaly detector flags {an['orders_flagged']} orders; flagged orders were later cancelled "
        f"**{an['flagged_cancellation_rate_pct']:.1f}%** of the time vs {an['normal_cancellation_rate_pct']:.1f}% for normal orders "
        f"({an['lift']:.1f}x) - a useful review queue before fulfilment.",
        "",
        "## Recommended actions",
        f"1. **Win back At Risk accounts** - personal outreach to the highest-value ones first; recovering even 10% of their "
        f"historical revenue is worth ~{_gbp(at_risk.get('total_revenue', 0) * 0.10)}.",
        "2. **Protect Champions** with service and early access rather than discounts; losing a few large accounts moves total revenue.",
        "3. **Grow basket size** with the co-purchase pairs from the market-basket analysis (bundles, 'often bought with').",
        "4. **Review flagged large orders** (anomaly queue) before picking stock, to cut costly bulk cancellations.",
        "5. **Plan stock for the Sep-Nov peak** using the 28-day forecast and its 80% interval as the safety-stock range.",
    ]
    return "\n".join(lines) + "\n"


def to_frame(facts: dict) -> pd.DataFrame:
    flat = {k: v for k, v in facts.items() if not isinstance(v, (dict, list))}
    return pd.DataFrame({"metric": list(flat), "value": list(flat.values())})
