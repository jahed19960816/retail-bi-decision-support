"""Monthly acquisition-cohort retention analysis.

A customer's cohort is the month of their first purchase. Retention at month k
is the share of the cohort that bought again k months later.

Caveat: Dec 2009 is the first month of data, so that cohort also contains
existing customers who bought before the dataset starts (left-censoring).
"""

import pandas as pd


def customer_months(sales: pd.DataFrame) -> pd.DataFrame:
    purchases = sales[~sales["is_return"] & sales["customer_id"].notna()]
    months = purchases[["customer_id", "order_date"]].copy()
    months["order_month"] = months["order_date"].dt.to_period("M")
    months = months.drop_duplicates(["customer_id", "order_month"])
    months["cohort"] = months.groupby("customer_id")["order_month"].transform("min")
    months["months_since_first"] = (months["order_month"] - months["cohort"]).apply(lambda offset: offset.n)
    return months


def retention_matrix(sales: pd.DataFrame) -> pd.DataFrame:
    """Rows = cohort month, columns = months since first purchase, values = % of cohort active."""
    months = customer_months(sales)
    counts = months.pivot_table(index="cohort", columns="months_since_first", values="customer_id", aggfunc="nunique")
    sizes = counts[0]
    matrix = counts.divide(sizes, axis=0) * 100
    matrix.insert(0, "cohort_size", sizes)
    matrix.index = matrix.index.astype(str)
    return matrix.round(1)


def average_retention_curve(matrix: pd.DataFrame, exclude_first_cohort: bool = True) -> pd.DataFrame:
    """Customer-weighted average retention by month offset.

    The first cohort is excluded by default because it mixes in pre-existing customers.
    """
    m = matrix.iloc[1:] if exclude_first_cohort else matrix
    sizes = m["cohort_size"]
    curve = []
    for col in [c for c in m.columns if c != "cohort_size"]:
        valid = m[col].notna()
        if valid.sum() == 0 or col == 0:
            continue
        weighted = (m.loc[valid, col] * sizes[valid]).sum() / sizes[valid].sum()
        curve.append({"months_since_first": col, "retention_pct": round(weighted, 1), "cohorts": int(valid.sum())})
    return pd.DataFrame(curve)


def second_order_conversion(sales: pd.DataFrame, window_days: int = 90) -> pd.DataFrame:
    """Share of each cohort that placed a second order within `window_days` of the first."""
    purchases = sales[~sales["is_return"] & sales["customer_id"].notna()]
    orders = purchases.groupby(["customer_id", "invoice"])["order_date"].min().reset_index()
    orders = orders.sort_values(["customer_id", "order_date"])
    orders["order_number"] = orders.groupby("customer_id").cumcount() + 1
    first = orders[orders["order_number"] == 1].set_index("customer_id")["order_date"]
    second = orders[orders["order_number"] == 2].set_index("customer_id")["order_date"]
    df = pd.DataFrame({"first": first, "second": second})
    df["cohort"] = df["first"].dt.to_period("M").astype(str)
    df["converted"] = (df["second"] - df["first"]).dt.days <= window_days
    # Only cohorts with a full observation window are comparable.
    cutoff = sales["order_date"].max() - pd.Timedelta(days=window_days)
    df = df[df["first"] <= cutoff]
    out = df.groupby("cohort").agg(customers=("converted", "size"), converted=("converted", "sum"))
    out[f"second_order_within_{window_days}d_pct"] = (out["converted"] / out["customers"] * 100).round(1)
    return out.reset_index()
