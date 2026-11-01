import numpy as np
import pandas as pd
import pytest

from retail_bi import anomalies, forecast, rfm


def _daily(n_days=500, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2010-01-01", periods=n_days, freq="D")
    weekly = np.where(idx.day_of_week == 5, 0.0, 30000.0)          # closed on Saturdays
    noise = rng.normal(0, 2000, n_days)
    return pd.Series(np.clip(weekly + noise, 0, None) * (idx.day_of_week != 5), index=idx, name="revenue")


def test_forecast_features_do_not_use_the_future():
    """Changing anything after the cutoff must not change features for the next H days."""
    y = _daily()
    cutoff = y.index[400]
    X = forecast.build_features(y)
    y_changed = y.copy()
    y_changed[y_changed.index >= cutoff] *= 10
    X_changed = forecast.build_features(y_changed)
    window = slice(cutoff, cutoff + pd.Timedelta(days=forecast.H - 1))
    pd.testing.assert_frame_equal(X.loc[window], X_changed.loc[window])


def test_wape():
    actual = pd.Series([100.0, 0.0, 50.0])
    pred = pd.Series([90.0, 10.0, 50.0])
    assert forecast.wape(actual, pred) == pytest.approx(20 / 150 * 100)


def test_backtest_produces_one_prediction_per_test_day():
    y = _daily(560)
    starts = forecast.fold_starts(y, 2)
    bt = forecast.backtest(y, starts, forecast.ModelSpec(max_iter=50))
    assert len(bt) == 2 * forecast.H
    assert bt["model"].notna().all() and (bt["model"] >= 0).all()


def test_daily_anomaly_detects_injected_spike():
    y = _daily()
    spike_day = y.index[300] if y.index[300].day_of_week != 5 else y.index[301]
    y[spike_day] = 200000
    scored = anomalies.daily_anomalies(y)
    assert scored.loc[spike_day, "is_anomaly"]
    assert scored.loc[spike_day, "direction"] == "spike"
    assert scored["is_anomaly"].sum() <= 5


def test_cancellation_matching():
    sales = pd.DataFrame({
        "invoice": ["1", "C2", "3"],
        "customer_id": pd.array([7, 7, 7], dtype="Int64"),
        "stock_code": ["A", "A", "A"],
        "quantity": [100, -100, 5],
        "invoice_date": pd.to_datetime(["2011-01-01 10:00", "2011-01-01 10:20", "2011-03-01 09:00"]),
        "is_return": [False, True, False],
    })
    assert anomalies.cancelled_invoices(sales) == {"1"}


def test_rfm_scores_and_cluster_names():
    rng = np.random.default_rng(1)
    n = 400
    data = pd.DataFrame({
        "customer_id": range(n),
        "recency_days": rng.integers(1, 700, n),
        "frequency": rng.integers(1, 40, n),
        "monetary": rng.gamma(2, 500, n),
    })
    scored = rfm.score_rfm(data)
    for col in ["r_score", "f_score", "m_score"]:
        assert set(scored[col]) == {1, 2, 3, 4, 5}
    # Most recent customers get the highest recency score.
    assert scored.loc[scored["recency_days"].idxmin(), "r_score"] == 5

    profile = pd.DataFrame(
        {"r_score": [4.5, 2.0, 1.5, 4.3], "f_score": [4.8, 3.6, 1.5, 2.6], "m_score": [4.8, 3.7, 1.6, 2.7]},
        index=[0, 1, 2, 3],
    )
    profile["rfm_score"] = profile.sum(axis=1)
    names = rfm.name_clusters(profile)
    assert names == {0: "Champions", 2: "Hibernating", 1: "At Risk", 3: "New / Promising"}
