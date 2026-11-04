"""Daily net-revenue forecasting, 28 days ahead.

Setup
-----
* Target: daily net revenue (closed days = 0).
* Every feature is known at least `H` = 28 days before the forecast date
  (lags >= 28 days, calendar features), so a single model can forecast the
  whole next 4 weeks without leaking future information.
* Model: gradient-boosted trees (scikit-learn HistGradientBoostingRegressor).
* 80% range for each day: the forecast times the 10th and 90th percentile of
  actual / forecast on open days in past backtest folds. Quantile models were
  rejected on the validation window: about 18% of days have zero revenue, which
  pinned their 10th percentile at 0.

Evaluation
----------
Rolling-origin backtest with 28-day folds. Model settings are chosen on a
VALIDATION window (the 6 folds before the test window) and the final numbers
are reported on the TEST window (the last 6 folds = last ~6 months of data),
compared against simple baselines a planner would otherwise use.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from retail_bi import config

H = config.FORECAST_HORIZON_DAYS
SAME_DOW_LAGS = [28, 35, 42, 49]
CLOSED_DOW = 5  # Saturday: the shop does not trade (99% of Saturdays have zero revenue)

BASELINES = {
    "Seasonal naive (same weekday, 4 weeks ago)": "lag_28",
    "4-week same-weekday average": "same_dow_mean_4w",
    "Last year, same weekday": "lag_364",
}


def daily_revenue(sales: pd.DataFrame) -> pd.Series:
    s = sales.groupby("order_date")["line_revenue"].sum()
    idx = pd.date_range(s.index.min(), s.index.max(), freq="D")
    return s.reindex(idx, fill_value=0.0).rename("revenue")


def _days_to_christmas(idx: pd.DatetimeIndex) -> np.ndarray:
    this_year = pd.to_datetime({"year": idx.year, "month": 12, "day": 25})
    next_year = pd.to_datetime({"year": idx.year + 1, "month": 12, "day": 25})
    delta = (this_year.values - idx.values).astype("timedelta64[D]").astype(int)
    delta_next = (next_year.values - idx.values).astype("timedelta64[D]").astype(int)
    return np.where(delta >= 0, delta, delta_next)


def build_features(y: pd.Series, end: pd.Timestamp | None = None) -> pd.DataFrame:
    """Feature matrix for every day from the start of `y` up to `end` (may extend H days past `y`)."""
    end = end or y.index.max()
    idx = pd.date_range(y.index.min(), end, freq="D")
    s = y.reindex(idx)
    X = pd.DataFrame(index=idx)
    X["dow"] = idx.day_of_week
    X["month"] = idx.month
    X["day_of_month"] = idx.day
    X["day_of_year"] = idx.day_of_year
    X["week_of_year"] = idx.isocalendar().week.astype(int).to_numpy()
    X["days_to_christmas"] = _days_to_christmas(idx)
    for lag in SAME_DOW_LAGS + [56]:
        X[f"lag_{lag}"] = s.shift(lag)
    X["same_dow_mean_4w"] = X[[f"lag_{lag}" for lag in SAME_DOW_LAGS]].mean(axis=1)
    known = s.shift(H)  # value known H days before the target date
    X["roll_mean_7"] = known.rolling(7, min_periods=5).mean()
    X["roll_mean_28"] = known.rolling(28, min_periods=20).mean()
    X["roll_std_28"] = known.rolling(28, min_periods=20).std()
    X["lag_364"] = s.shift(364)
    X["lag_364_mean_7"] = s.shift(361).rolling(7, min_periods=5).mean()  # days t-367 .. t-361
    X["yoy_level_ratio"] = X["roll_mean_28"] / s.shift(H + 364).rolling(28, min_periods=20).mean()
    # Last year's value scaled by recent year-over-year growth: what a planner would pencil in.
    X["growth_adj_lag_364"] = X["lag_364_mean_7"] * X["yoy_level_ratio"]
    return X


@dataclass
class ModelSpec:
    name: str = "gbm"
    target: str = "raw"            # "raw" or "log1p"
    loss: str = "squared_error"    # "squared_error" (mean) or "absolute_error" (median, matches WAPE)
    learning_rate: float = 0.05
    max_iter: int = 400
    max_leaf_nodes: int = 15
    min_samples_leaf: int = 15
    l2_regularization: float = 1.0
    # Forecast combination: blend weight given to last year's same-weekday value (0 = model only).
    blend_last_year: float = 0.0

    def model(self) -> HistGradientBoostingRegressor:
        return HistGradientBoostingRegressor(
            loss=self.loss,
            learning_rate=self.learning_rate,
            max_iter=self.max_iter,
            max_leaf_nodes=self.max_leaf_nodes,
            min_samples_leaf=self.min_samples_leaf,
            l2_regularization=self.l2_regularization,
            random_state=config.RANDOM_STATE,
        )


def _fit_predict(spec: ModelSpec, X_train, y_train, X_test) -> np.ndarray:
    # Early folds have < 1 year of history, so yearly features can be entirely empty there.
    usable = [c for c in X_train.columns if X_train[c].nunique(dropna=True) > 1]
    target = np.log1p(y_train.clip(lower=0)) if spec.target == "log1p" else y_train
    model = spec.model().fit(X_train[usable], target)
    pred = model.predict(X_test[usable])
    if spec.target == "log1p":
        pred = np.expm1(pred)
    return np.clip(pred, 0, None)


def _blend(spec: ModelSpec, pred: np.ndarray, X_test: pd.DataFrame) -> np.ndarray:
    if not spec.blend_last_year:
        return pred
    last_year = X_test["lag_364"].to_numpy()
    blended = (1 - spec.blend_last_year) * pred + spec.blend_last_year * last_year
    return np.where(np.isnan(last_year), pred, blended)


def _train_mask(X: pd.DataFrame, y: pd.Series, before: pd.Timestamp) -> pd.Series:
    # Need at least the short lags; long (yearly) lags may be NaN, which the model handles.
    return (X.index < before) & X["same_dow_mean_4w"].notna() & y.reindex(X.index).notna()


def fold_starts(y: pd.Series, n_folds: int, skip_folds: int = 0) -> list[pd.Timestamp]:
    """Start dates of the last `n_folds` H-day folds, optionally shifted back by `skip_folds` folds."""
    last = y.index.max()
    first_start = last - pd.Timedelta(days=H * (n_folds + skip_folds) - 1)
    return [first_start + pd.Timedelta(days=H * i) for i in range(n_folds)]


def backtest(y: pd.Series, starts: list[pd.Timestamp], spec: ModelSpec) -> pd.DataFrame:
    """Rolling-origin backtest: for each fold, train on everything before it, predict the next H days."""
    X = build_features(y)
    rows = []
    for k, start in enumerate(starts, 1):
        end = start + pd.Timedelta(days=H - 1)
        train = _train_mask(X, y, start)
        test_idx = X.loc[start:end].index
        pred = _blend(spec, _fit_predict(spec, X[train], y[train], X.loc[test_idx]), X.loc[test_idx])
        fold = pd.DataFrame({"fold": k, "actual": y.loc[test_idx], "model": pred}, index=test_idx)
        for label, column in BASELINES.items():
            fold[label] = X.loc[test_idx, column].values
        rows.append(fold)
    out = pd.concat(rows)
    out.index.name = "date"
    return out


def wape(actual: pd.Series, pred: pd.Series) -> float:
    mask = pred.notna()
    return float((actual[mask] - pred[mask]).abs().sum() / actual[mask].abs().sum() * 100)


def score(bt: pd.DataFrame) -> pd.DataFrame:
    """Daily and weekly WAPE, MAE, RMSE and bias for the model and each baseline."""
    methods = ["model"] + list(BASELINES)
    weekly = bt.groupby([bt["fold"], pd.Grouper(freq="W-SUN")])[["actual"] + methods].sum(min_count=1)
    rows = []
    for m in methods:
        valid = bt[m].notna()
        err = bt.loc[valid, m] - bt.loc[valid, "actual"]
        rows.append({
            "method": "Model: gradient boosting + last-year blend" if m == "model" else m,
            "daily_wape_pct": round(wape(bt["actual"], bt[m]), 2),
            "weekly_wape_pct": round(wape(weekly["actual"], weekly[m]), 2),
            "mae": round(err.abs().mean(), 0),
            "rmse": round(float(np.sqrt((err ** 2).mean())), 0),
            "bias_pct": round(err.sum() / bt.loc[valid, "actual"].sum() * 100, 2),
            "coverage_pct": round(valid.mean() * 100, 1),
        })
    return pd.DataFrame(rows)


def improvement_vs_best_baseline(scores: pd.DataFrame, metric: str = "daily_wape_pct") -> dict:
    model_row = scores.iloc[0]
    baselines = scores.iloc[1:]
    best = baselines.loc[baselines[metric].idxmin()]
    return {
        "metric": metric,
        "model": float(model_row[metric]),
        "best_baseline": best["method"],
        "best_baseline_value": float(best[metric]),
        "error_reduction_pct": round((1 - model_row[metric] / best[metric]) * 100, 1),
    }


def interval_multipliers(bt: pd.DataFrame) -> tuple[float, float]:
    """How far actuals landed from the forecast on open days: 10th and 90th percentile of actual / forecast."""
    open_days = bt[(bt.index.day_of_week != CLOSED_DOW) & (bt["model"] > 0)]
    low, high = np.quantile(open_days["actual"] / open_days["model"], [0.10, 0.90])
    return min(max(float(low), 0.0), 1.0), max(float(high), 1.0)


def interval(pred: pd.Series, multipliers: tuple[float, float]) -> pd.DataFrame:
    """80% range for each day: the forecast times the multipliers. Closed days run from 0 up to the forecast."""
    is_open = pred.index.day_of_week != CLOSED_DOW
    return pd.DataFrame({
        "lower_80": (pred * multipliers[0]).where(is_open, 0.0),
        "upper_80": (pred * multipliers[1]).where(is_open, pred),
    })


def score_interval(history: pd.DataFrame, test: pd.DataFrame) -> dict:
    """Out-of-sample check of the band on open days: each test fold is calibrated only on folds before it."""
    parts = []
    for fold, rows in test.groupby("fold"):
        past = pd.concat([history, test[test["fold"] < fold]])
        parts.append(rows.join(interval(rows["model"], interval_multipliers(past))))
    scored = pd.concat(parts)
    scored = scored[scored.index.day_of_week != CLOSED_DOW]
    below, above = scored["actual"] < scored["lower_80"], scored["actual"] > scored["upper_80"]
    return {
        "open_days": len(scored),
        "coverage_pct": round(float((~below & ~above).mean() * 100), 1),
        "below_lower_pct": round(float(below.mean() * 100), 1),
        "above_upper_pct": round(float(above.mean() * 100), 1),
    }


def forecast_future(y: pd.Series, spec: ModelSpec, multipliers: tuple[float, float], horizon: int = H) -> pd.DataFrame:
    """Train on all history and forecast the next `horizon` days with an 80% range."""
    end = y.index.max() + pd.Timedelta(days=horizon)
    X = build_features(y, end=end)
    train = _train_mask(X, y, y.index.max() + pd.Timedelta(days=1))
    future_idx = X.index[X.index > y.index.max()]
    pred = pd.Series(_blend(spec, _fit_predict(spec, X[train], y[train], X.loc[future_idx]), X.loc[future_idx]), index=future_idx)
    out = interval(pred, multipliers)
    out.insert(0, "forecast", pred)
    out.index.name = "date"
    return out.round(2)


CANDIDATE_SPECS = [
    ModelSpec(name="gbm_mse", loss="squared_error"),
    ModelSpec(name="gbm_mse_shallow", loss="squared_error", max_leaf_nodes=7, min_samples_leaf=25, max_iter=300),
    ModelSpec(name="gbm_mae", loss="absolute_error"),
    ModelSpec(name="gbm_mae_shallow", loss="absolute_error", max_leaf_nodes=7, min_samples_leaf=25, max_iter=300),
    ModelSpec(name="gbm_log_mse", target="log1p", loss="squared_error"),
    ModelSpec(name="gbm_mse_shallow+last_year_30", loss="squared_error", max_leaf_nodes=7, min_samples_leaf=25, max_iter=300, blend_last_year=0.3),
    ModelSpec(name="gbm_mse_shallow+last_year_50", loss="squared_error", max_leaf_nodes=7, min_samples_leaf=25, max_iter=300, blend_last_year=0.5),
]


def select_spec(y: pd.Series) -> tuple[ModelSpec, pd.DataFrame]:
    """Pick the candidate with the lowest daily WAPE on the validation folds (before the test window)."""
    val_starts = fold_starts(y, config.BACKTEST_FOLDS, skip_folds=config.BACKTEST_FOLDS)
    rows = []
    for spec in CANDIDATE_SPECS:
        bt = backtest(y, val_starts, spec)
        rows.append({"spec": spec.name, "validation_daily_wape_pct": round(wape(bt["actual"], bt["model"]), 2)})
    table = pd.DataFrame(rows).sort_values("validation_daily_wape_pct")
    best = next(s for s in CANDIDATE_SPECS if s.name == table.iloc[0]["spec"])
    return best, table
