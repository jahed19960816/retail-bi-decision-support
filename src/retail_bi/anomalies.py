"""Anomaly detection at two levels.

1. Daily revenue: robust z-score of each day against the median of the same
   weekday in the surrounding +/- 4 weeks (median/MAD are not dragged around
   by the outliers they are meant to find).
2. Orders: Isolation Forest on *contextual* invoice features - how an order
   compares with that customer's usual order and with the usual line quantity
   of the products in it (an 80,995-unit line of a product normally bought in
   dozens is suspicious; a big order from a big wholesaler is not). To check the
   detector is useful, we compare how often flagged orders were later cancelled.
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from retail_bi import config

MAD_SCALE = 1.4826  # makes MAD comparable to a standard deviation for normal data


def daily_anomalies(daily: pd.Series, window_weeks: int = 4, threshold: float = 3.5) -> pd.DataFrame:
    """Flag days whose revenue is far from the typical value for that weekday and season."""
    df = daily.to_frame("actual")
    neighbours = [daily.shift(7 * k) for k in range(-window_weeks, window_weeks + 1) if k != 0]
    stacked = pd.concat(neighbours, axis=1)
    df["expected"] = stacked.median(axis=1)
    mad = stacked.sub(df["expected"], axis=0).abs().median(axis=1) * MAD_SCALE
    # Floor the scale so quiet weekdays do not turn small wobbles into "anomalies".
    floor = 0.10 * daily[daily > 0].median()
    df["scale"] = np.maximum(mad, floor)
    df["robust_z"] = (df["actual"] - df["expected"]) / df["scale"]
    df["is_anomaly"] = (df["robust_z"].abs() > threshold) & (df["expected"] > 0)
    # The extract ends at midday on its last date, so that day is incomplete rather than anomalous.
    df.loc[df.index.max(), "is_anomaly"] = False
    df["direction"] = np.where(df["robust_z"] > 0, "spike", "drop")
    df.index.name = "date"
    return df.round(2)


def explain_daily(anomalies: pd.DataFrame, sales: pd.DataFrame, top: int = 15) -> pd.DataFrame:
    """Attach the largest order of each anomalous day so a reviewer can see what drove it."""
    flagged = anomalies[anomalies["is_anomaly"]].copy()
    orders = (
        sales[~sales["is_return"]]
        .groupby(["order_date", "invoice"])
        .agg(order_value=("line_revenue", "sum"), customer_id=("customer_id", "first"), country=("country", "first"))
        .reset_index()
        .sort_values("order_value", ascending=False)
        .drop_duplicates("order_date")
        .set_index("order_date")
    )
    flagged = flagged.join(orders, how="left")
    flagged["largest_order_share_pct"] = (flagged["order_value"] / flagged["actual"].where(flagged["actual"] > 0) * 100).round(1)
    flagged = flagged.reindex(flagged["robust_z"].abs().sort_values(ascending=False).index)
    return flagged.head(top).reset_index()


def order_features(sales: pd.DataFrame) -> pd.DataFrame:
    purchases = sales[~sales["is_return"]].copy()
    typical_qty = purchases.groupby("stock_code")["quantity"].transform("median")
    purchases["qty_vs_typical"] = purchases["quantity"] / typical_qty
    orders = purchases.groupby("invoice").agg(
        invoice_date=("invoice_date", "min"),
        customer_id=("customer_id", "first"),
        country=("country", "first"),
        order_value=("line_revenue", "sum"),
        units=("quantity", "sum"),
        lines=("stock_code", "size"),
        distinct_products=("stock_code", "nunique"),
        max_line_qty=("quantity", "max"),
        avg_unit_price=("unit_price", "mean"),
        max_qty_vs_typical=("qty_vs_typical", "max"),
    )
    customer_median = orders.groupby("customer_id")["order_value"].transform("median")
    orders["value_vs_customer_median"] = (orders["order_value"] / customer_median).fillna(1.0)
    orders["customer_orders"] = orders.groupby("customer_id")["order_value"].transform("size").fillna(1)
    orders["hour"] = orders["invoice_date"].dt.hour
    orders["is_guest"] = orders["customer_id"].isna().astype(int)
    orders["is_uk"] = (orders["country"] == "United Kingdom").astype(int)
    orders["was_cancelled"] = orders.index.isin(cancelled_invoices(sales))
    return orders


def cancelled_invoices(sales: pd.DataFrame, within_days: int = 30) -> set:
    """Sales invoices with at least one line reversed by a cancellation within `within_days`.

    A line is matched when the same customer cancels the same product and the same quantity.
    """
    cols = ["invoice", "customer_id", "stock_code", "quantity", "invoice_date"]
    buys = sales.loc[~sales["is_return"] & sales["customer_id"].notna(), cols]
    cancels = sales.loc[sales["is_return"] & sales["customer_id"].notna(), cols].copy()
    cancels["quantity"] = -cancels["quantity"]
    matched = buys.merge(cancels, on=["customer_id", "stock_code", "quantity"], suffixes=("", "_cancel"))
    gap = matched["invoice_date_cancel"] - matched["invoice_date"]
    matched = matched[(gap >= pd.Timedelta(0)) & (gap <= pd.Timedelta(days=within_days))]
    return set(matched["invoice"])


MODEL_FEATURES = ["log_order_value", "log_value_vs_customer", "log_max_qty_vs_typical", "log_max_line_qty", "log_avg_unit_price", "log_distinct_products"]


def order_anomalies(orders: pd.DataFrame, contamination: float = 0.01) -> pd.DataFrame:
    X = pd.DataFrame(index=orders.index)
    X["log_order_value"] = np.log1p(orders["order_value"])
    X["log_value_vs_customer"] = np.log(orders["value_vs_customer_median"])
    X["log_max_qty_vs_typical"] = np.log(orders["max_qty_vs_typical"])
    # Absolute size still matters when a product or customer has no history to compare against.
    X["log_max_line_qty"] = np.log1p(orders["max_line_qty"])
    X["log_avg_unit_price"] = np.log1p(orders["avg_unit_price"])
    X["log_distinct_products"] = np.log1p(orders["distinct_products"])

    model = IsolationForest(n_estimators=300, contamination=contamination, random_state=config.RANDOM_STATE)
    model.fit(X[MODEL_FEATURES])
    out = orders.copy()
    out["anomaly_score"] = -model.score_samples(X[MODEL_FEATURES])  # higher = more unusual
    # Review queue for risky orders: only unusually LARGE orders are flagged
    # (a tiny order from a big customer is odd but carries no fulfilment or credit risk).
    is_large = (
        (orders["value_vs_customer_median"] > 1)
        | (orders["max_qty_vs_typical"] > 1)
        | (orders["max_line_qty"] > orders["max_line_qty"].quantile(0.99))
    )
    out["is_anomaly"] = (model.predict(X[MODEL_FEATURES]) == -1) & is_large

    # Plain-English reason: the feature furthest from typical (robust z-score).
    med = X.median()
    mad = (X - med).abs().median().replace(0, np.nan) * MAD_SCALE
    z = ((X - med) / mad).abs()
    readable = {
        "log_order_value": "order value",
        "log_value_vs_customer": "unusual size for this customer",
        "log_max_qty_vs_typical": "unusual quantity for a product",
        "log_max_line_qty": "very large line quantity",
        "log_avg_unit_price": "unit price",
        "log_distinct_products": "number of products",
    }
    out["main_driver"] = z[list(readable)].idxmax(axis=1).map(readable)
    return out.sort_values("anomaly_score", ascending=False)


def anomaly_validation(scored: pd.DataFrame) -> dict:
    """Is the detector picking up genuinely problematic orders? Compare cancellation rates."""
    flagged = scored[scored["is_anomaly"]]
    normal = scored[~scored["is_anomaly"]]
    flagged_rate = flagged["was_cancelled"].mean() * 100
    normal_rate = normal["was_cancelled"].mean() * 100
    return {
        "orders_scored": len(scored),
        "orders_flagged": len(flagged),
        "flagged_cancellation_rate_pct": round(flagged_rate, 1),
        "normal_cancellation_rate_pct": round(normal_rate, 1),
        "lift": round(flagged_rate / normal_rate, 1) if normal_rate else None,
        "flagged_order_value_share_pct": round(flagged["order_value"].sum() / scored["order_value"].sum() * 100, 1),
    }
