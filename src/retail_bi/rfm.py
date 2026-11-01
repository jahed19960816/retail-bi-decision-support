"""RFM customer segmentation.

1. Build Recency / Frequency / Monetary per known customer.
2. Score each dimension 1-5 by quintile (classic RFM scoring, easy to explain).
3. Cluster customers with K-Means (k=4) on log-scaled, standardised RFM values.
4. Name each cluster from its profile and attach a recommended action.

k=4 is a business choice (four segments a marketing team can act on); the
silhouette scores for k=2..8 are saved alongside so the trade-off is visible.
"""

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from retail_bi import config

N_SEGMENTS = 4

SEGMENT_ACTIONS = {
    "Champions": "Protect: VIP service, early access to new ranges, referral asks. Avoid blanket discounts.",
    "Loyal Customers": "Grow: cross-sell frequently co-purchased items, volume-tier pricing, account check-ins.",
    "At Risk": "Win back now: personal outreach to high-value accounts, time-limited reorder offer within 30 days.",
    "New / Promising": "Convert to repeat: onboarding sequence and a second-order incentive within 60 days.",
    "Hibernating": "Low-cost reactivation email only; suppress from expensive campaigns.",
}


def build_rfm(sales: pd.DataFrame, snapshot: pd.Timestamp | None = None) -> pd.DataFrame:
    """Recency (days), Frequency (orders) and Monetary (net revenue) per known customer."""
    known = sales[sales["customer_id"].notna()]
    if snapshot is None:
        snapshot = sales["order_date"].max() + pd.Timedelta(days=1)
    purchases = known[~known["is_return"]]
    rfm = purchases.groupby("customer_id").agg(
        last_purchase=("order_date", "max"),
        first_purchase=("order_date", "min"),
        frequency=("invoice", "nunique"),
    )
    rfm["monetary"] = known.groupby("customer_id")["line_revenue"].sum().reindex(rfm.index)
    rfm["recency_days"] = (snapshot - rfm["last_purchase"]).dt.days
    rfm["tenure_days"] = (snapshot - rfm["first_purchase"]).dt.days
    # Customers whose returns cancel out all purchases carry no value to segment.
    rfm = rfm[rfm["monetary"] > 0]
    return rfm.reset_index()


def score_rfm(rfm: pd.DataFrame) -> pd.DataFrame:
    out = rfm.copy()
    # rank(method="first") breaks ties so qcut always finds 5 distinct bins.
    out["r_score"] = pd.qcut(out["recency_days"].rank(method="first"), 5, labels=[5, 4, 3, 2, 1]).astype(int)
    out["f_score"] = pd.qcut(out["frequency"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
    out["m_score"] = pd.qcut(out["monetary"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
    out["rfm_score"] = out["r_score"] + out["f_score"] + out["m_score"]
    out["rfm_code"] = out["r_score"].astype(str) + out["f_score"].astype(str) + out["m_score"].astype(str)
    return out


def _features(rfm: pd.DataFrame) -> np.ndarray:
    raw = np.column_stack([np.log1p(rfm["recency_days"]), np.log1p(rfm["frequency"]), np.log1p(rfm["monetary"])])
    return StandardScaler().fit_transform(raw)


def silhouette_by_k(rfm: pd.DataFrame, ks=range(2, 9)) -> pd.DataFrame:
    X = _features(rfm)
    rows = []
    for k in ks:
        model = KMeans(n_clusters=k, n_init=10, random_state=config.RANDOM_STATE).fit(X)
        rows.append({"k": k, "inertia": round(model.inertia_, 1), "silhouette": round(silhouette_score(X, model.labels_), 4)})
    return pd.DataFrame(rows)


def name_clusters(profile: pd.DataFrame) -> dict[int, str]:
    """Map cluster ids to business names using their average R/F/M scores.

    Highest overall score -> Champions, lowest -> Hibernating. Of the two middle
    clusters, the one that buys more often is "Loyal Customers" if it is also
    recent, otherwise "At Risk"; the other becomes "New / Promising" when it is
    the more recent of the two, else "At Risk".
    """
    order = profile.sort_values("rfm_score", ascending=False).index.tolist()
    names = {order[0]: "Champions", order[-1]: "Hibernating"}
    a, b = order[1], order[2]
    frequent, other = (a, b) if profile.loc[a, "f_score"] >= profile.loc[b, "f_score"] else (b, a)
    frequent_is_recent = profile.loc[frequent, "r_score"] >= profile.loc[other, "r_score"]
    if frequent_is_recent:
        names[frequent], names[other] = "Loyal Customers", "At Risk"
    else:
        names[frequent], names[other] = "At Risk", "New / Promising"
    return names


def segment_customers(rfm_scored: pd.DataFrame) -> pd.DataFrame:
    X = _features(rfm_scored)
    model = KMeans(n_clusters=N_SEGMENTS, n_init=20, random_state=config.RANDOM_STATE).fit(X)
    out = rfm_scored.copy()
    out["cluster"] = model.labels_
    profile = out.groupby("cluster")[["r_score", "f_score", "m_score", "rfm_score"]].mean()
    out["segment"] = out["cluster"].map(name_clusters(profile))
    out["recommended_action"] = out["segment"].map(SEGMENT_ACTIONS)
    return out


def segment_profile(segmented: pd.DataFrame) -> pd.DataFrame:
    total_customers = len(segmented)
    total_revenue = segmented["monetary"].sum()
    prof = segmented.groupby("segment").agg(
        customers=("customer_id", "size"),
        avg_recency_days=("recency_days", "mean"),
        median_recency_days=("recency_days", "median"),
        avg_orders=("frequency", "mean"),
        avg_revenue=("monetary", "mean"),
        median_revenue=("monetary", "median"),
        total_revenue=("monetary", "sum"),
    )
    prof["customer_share_pct"] = prof["customers"] / total_customers * 100
    prof["revenue_share_pct"] = prof["total_revenue"] / total_revenue * 100
    prof["recommended_action"] = prof.index.map(SEGMENT_ACTIONS)
    prof = prof.sort_values("avg_revenue", ascending=False).round(1)
    return prof.reset_index()
