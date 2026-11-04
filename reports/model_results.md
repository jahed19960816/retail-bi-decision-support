# Model results

## 1. Sales forecasting (28 days ahead, daily net revenue)

Every feature is known at least 28 days in advance (lags >= 28 days, last year's values, calendar),
so one model forecasts the whole next 4 weeks without leaking future data.

**Model selection** on the validation window (6 x 28-day folds, Jan-Jun 2011):

| spec | validation_daily_wape_pct |
|---|---|
| gbm_mse_shallow+last_year_30 | 31.72 |
| gbm_mse_shallow | 31.83 |
| gbm_mae_shallow | 31.87 |
| gbm_mae | 32.10 |
| gbm_mse_shallow+last_year_50 | 32.76 |
| gbm_mse | 33.88 |
| gbm_log_mse | 72.16 |

Selected: `gbm_mse_shallow+last_year_30` (HistGradientBoostingRegressor, squared_error, max_leaf_nodes=7, blended 30% with last year's same-weekday value).

**Test results** on the last 6 x 28-day folds (25 Jun - 9 Dec 2011), never used for selection:

| method | daily_wape_pct | weekly_wape_pct | mae | rmse | bias_pct | coverage_pct |
|---|---|---|---|---|---|---|
| Model: gradient boosting + last-year blend | 28.21 | 14.40 | 9,133.00 | 13,183.00 | -5.59 | 100.00 |
| Seasonal naive (same weekday, 4 weeks ago) | 41.32 | 22.19 | 13,375.00 | 19,090.00 | -12.54 | 100.00 |
| 4-week same-weekday average | 33.21 | 20.29 | 10,751.00 | 16,014.00 | -15.89 | 100.00 |
| Last year, same weekday | 31.60 | 15.54 | 10,230.00 | 15,285.00 | -5.01 | 100.00 |

- Daily WAPE **28.21%** vs best baseline (Last year, same weekday) 31.60% -> **10.7% lower error**.
- Weekly WAPE 14.40% vs 15.54% -> 7.3% lower error.
- WAPE = sum(|actual - forecast|) / sum(actual). Lower is better. The model also has lower bias than the
  short-term baselines, which under-forecast the autumn ramp-up.

**80% range for each day.** Quantile gradient boosting was rejected on the validation window: about 18% of days
have zero revenue, which pinned its low edge at 0. The range now comes from past backtest errors instead.

- On open days, actual revenue usually landed between 0.55x and 1.69x the forecast. The range is the forecast times those multipliers. Saturdays are closed, so they run from 0 up to the forecast.
- Checked on the test folds over 144 open days, calibrating each fold only on earlier folds: **83.3%** of days fell inside (target 80%), 9.0% below and 7.6% above.
- The range applies to one day at a time. Adding up daily edges does not give an 80% range for a week or a month.

## 2. Customer segmentation (RFM + K-Means)

Silhouette score by number of clusters (log-scaled, standardised R/F/M):

| k | inertia | silhouette |
|---|---|---|
| 2.00 | 8,540.70 | 0.44 |
| 3.00 | 6,317.30 | 0.35 |
| 4.00 | 4,886.10 | 0.37 |
| 5.00 | 4,066.50 | 0.34 |
| 6.00 | 3,542.30 | 0.33 |
| 7.00 | 3,178.80 | 0.31 |
| 8.00 | 2,893.20 | 0.29 |

k = 4 is the best of k = 3..8 and gives four segments a marketing team can act on (k = 2 scores higher but
only separates 'active' from 'inactive').

| segment | customers | avg_recency_days | median_recency_days | avg_orders | avg_revenue | median_revenue | total_revenue | customer_share_pct | revenue_share_pct |
|---|---|---|---|---|---|---|---|---|---|
| Champions | 1189 | 28.20 | 17.00 | 19.10 | 10,133.30 | 4,808.90 | 12,048,534.60 | 20.40 | 73.60 |
| At Risk | 1442 | 227.30 | 184.50 | 5.10 | 1,857.90 | 1,431.00 | 2,679,069.80 | 24.70 | 16.40 |
| New / Promising | 1253 | 29.10 | 24.00 | 3.00 | 818.30 | 705.10 | 1,025,356.20 | 21.50 | 6.30 |
| Hibernating | 1950 | 395.40 | 402.00 | 1.40 | 311.80 | 266.40 | 608,035.80 | 33.40 | 3.70 |

## 3. Cohort retention

Customer-weighted average retention (excluding the left-censored Dec 2009 cohort):

| months_since_first | retention_pct | cohorts |
|---|---|---|
| 1.00 | 20.70 | 23.00 |
| 2.00 | 21.30 | 22.00 |
| 3.00 | 20.80 | 21.00 |
| 4.00 | 19.30 | 20.00 |
| 5.00 | 18.50 | 19.00 |
| 6.00 | 18.20 | 18.00 |
| 7.00 | 18.40 | 17.00 |
| 8.00 | 16.30 | 16.00 |
| 9.00 | 14.70 | 15.00 |
| 10.00 | 13.20 | 14.00 |
| 11.00 | 13.90 | 13.00 |
| 12.00 | 18.10 | 12.00 |

## 4. Anomaly detection

- Daily revenue: 42 anomalous days (robust z-score > 3.5 vs the same weekday
  in the surrounding +/-4 weeks), e.g. the 29 Apr 2011 Royal Wedding bank holiday.
- Orders: Isolation Forest on contextual features flags 181 unusually large orders. Flagged orders were later cancelled **11.6%** of the time vs 5.8% for other orders (**2.0x lift**), and the queue
  includes the two biggest cancelled bulk orders (80,995 and 74,215 units).
