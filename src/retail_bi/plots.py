"""Static report figures (PNG) with one consistent, colour-blind-safe style.

Style rules: light surface, hairline solid gridlines, thin marks, one y-axis per
chart, categorical colours in a fixed validated order, a single blue ramp for
magnitude, blue/red only for polarity. Every figure's data is also saved as a
CSV table in reports/tables (the accessible "table view").
"""

from retail_bi import config  # noqa: F401  (sets MPLCONFIGDIR before matplotlib loads)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
NEUTRAL_BAR = "#c3c2b7"
POSITIVE, NEGATIVE = "#2a78d6", "#e34948"
CRITICAL = "#d03b3b"
BLUE_RAMP = LinearSegmentedColormap.from_list(
    "blue_ramp", ["#f5f9fe", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#2a78d6", "#1c5cab", "#104281", "#0d366b"]
)

plt.rcParams.update({
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "font.family": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
    "font.size": 10,
    "text.color": INK,
    "axes.labelcolor": INK_2,
    "axes.edgecolor": AXIS,
    "axes.linewidth": 0.8,
    "axes.titlesize": 13,
    "axes.titleweight": "bold",
    "axes.titlelocation": "left",
    "axes.titlepad": 14,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.color": GRID,
    "grid.linewidth": 0.6,
    "grid.linestyle": "-",
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "xtick.labelcolor": INK_2,
    "ytick.labelcolor": INK_2,
    "legend.frameon": False,
    "lines.linewidth": 2,
})


def _gbp(x, _pos=None):
    if abs(x) >= 1e6:
        return f"£{x / 1e6:.1f}M"
    if abs(x) >= 1e3:
        return f"£{x / 1e3:.0f}K"
    return f"£{x:.0f}"


def _subtitle(ax, text):
    ax.text(0, 1.01, text, transform=ax.transAxes, color=INK_2, fontsize=9.5, va="bottom")


def _save(fig, name):
    path = config.FIGURES_DIR / f"{name}.png"
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return path


def monthly_revenue_yoy(monthly: pd.DataFrame):
    """Two 12-month periods overlaid by month so seasonality and growth are comparable."""
    m = monthly[~monthly["is_partial_month"]].copy()
    m["month"] = pd.to_datetime(m["month"])
    periods = {
        "Dec 2009 – Nov 2010": (pd.Timestamp("2009-12-01"), pd.Timestamp("2010-11-01")),
        "Dec 2010 – Nov 2011": (pd.Timestamp("2010-12-01"), pd.Timestamp("2011-11-01")),
    }
    fig, ax = plt.subplots(figsize=(9, 4.6))
    labels = None
    peak_shares = []
    for i, (name, (start, end)) in enumerate(periods.items()):
        part = m[(m["month"] >= start) & (m["month"] <= end)]
        labels = part["month"].dt.strftime("%b").tolist()
        peak_shares.append(part.loc[part["month"].dt.month.isin([9, 10, 11]), "net_revenue"].sum() / part["net_revenue"].sum() * 100)
        ax.plot(range(len(part)), part["net_revenue"], color=SERIES[i], marker="o", markersize=4, label=name)
        # Stagger the two end labels so they never overlap.
        ax.annotate(f"£{part['net_revenue'].iloc[-1] / 1e6:.2f}M", (len(part) - 1, part["net_revenue"].iloc[-1]),
                    xytext=(8, -9 if i == 0 else 9), textcoords="offset points", va="center", color=INK_2, fontsize=9)
    ax.set_xticks(range(len(labels)), labels)
    ax.set_xlim(-0.4, len(labels) - 0.2)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(_gbp))
    ax.set_ylim(0, None)
    ax.grid(axis="x", visible=False)
    ax.set_title("Monthly net revenue: year 2 vs year 1")
    _subtitle(ax, f"Same seasonal shape both years; Sep–Nov brings in {min(peak_shares):.0f}–{max(peak_shares):.0f}% of annual revenue")
    ax.legend(loc="upper left")
    return _save(fig, "01_monthly_revenue_yoy")


def revenue_mix(mix: pd.DataFrame):
    df = mix.copy()
    df["month"] = pd.to_datetime(df["month"])
    df = df.set_index("month")[["returning_customer_revenue", "new_customer_revenue", "guest_revenue"]].clip(lower=0)
    fig, ax = plt.subplots(figsize=(10, 4.6))
    x = np.arange(len(df))
    bottom = np.zeros(len(df))
    names = {"returning_customer_revenue": "Returning customers", "new_customer_revenue": "New customers", "guest_revenue": "Guest checkout (no ID)"}
    for i, col in enumerate(df.columns):
        ax.bar(x, df[col], bottom=bottom, width=0.8, color=SERIES[i], edgecolor=SURFACE, linewidth=1.2, label=names[col])
        bottom += df[col].to_numpy()
    ax.set_xticks(x[::2], df.index[::2].strftime("%b %y"), rotation=0, fontsize=8.5)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(_gbp))
    ax.grid(axis="x", visible=False)
    ax.set_title("Where monthly revenue comes from")
    _subtitle(ax, "Returning customers carry the business; Dec 2009 counts everyone as new (first month of data)")
    ax.legend(loc="upper left", ncols=3)
    return _save(fig, "02_revenue_mix_new_vs_returning")


def rfm_segments(profile: pd.DataFrame):
    p = profile.set_index("segment")[["customer_share_pct", "revenue_share_pct"]]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    y = np.arange(len(p))
    h = 0.36
    ax.barh(y - h / 2, p["customer_share_pct"], height=h, color=SERIES[0], label="% of customers")
    ax.barh(y + h / 2, p["revenue_share_pct"], height=h, color=SERIES[1], label="% of revenue")
    for yi, (c, r) in enumerate(zip(p["customer_share_pct"], p["revenue_share_pct"])):
        ax.text(c + 0.8, yi - h / 2, f"{c:.0f}%", va="center", fontsize=9, color=INK_2)
        ax.text(r + 0.8, yi + h / 2, f"{r:.0f}%", va="center", fontsize=9, color=INK_2)
    ax.set_yticks(y, p.index)
    ax.invert_yaxis()
    ax.xaxis.set_major_formatter(mticker.PercentFormatter(decimals=0))
    ax.set_xlim(0, max(p.max()) * 1.15)
    ax.grid(axis="y", visible=False)
    ax.set_title("RFM segments: share of customers vs share of revenue")
    _subtitle(ax, "K-Means (k=4) on log-scaled Recency, Frequency, Monetary")
    ax.legend(loc="lower right")
    return _save(fig, "03_rfm_segments")


def cohort_heatmap(matrix: pd.DataFrame, max_months: int = 12):
    m = matrix.drop(columns="cohort_size").iloc[:, 1:max_months + 1]
    fig, ax = plt.subplots(figsize=(10, 7))
    im = ax.imshow(m.to_numpy(dtype=float), cmap=BLUE_RAMP, aspect="auto", vmin=0, vmax=50)
    ax.set_xticks(range(m.shape[1]), [str(c) for c in m.columns])
    ax.set_yticks(range(m.shape[0]), [f"{idx}  (n={int(n)})" for idx, n in zip(m.index, matrix["cohort_size"])], fontsize=8.5)
    for (i, j), v in np.ndenumerate(m.to_numpy(dtype=float)):
        if not np.isnan(v):
            ax.text(j, i, f"{v:.0f}", ha="center", va="center", fontsize=7.5, color="#ffffff" if v >= 30 else INK)
    ax.grid(False)
    ax.set_xlabel("Months since first purchase")
    ax.set_title("Customer retention by acquisition cohort (% active)", pad=22)
    _subtitle(ax, "Dec 2009 cohort includes pre-existing customers (data starts Dec 2009)")
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    cb.outline.set_visible(False)
    cb.ax.yaxis.set_major_formatter(mticker.PercentFormatter(decimals=0))
    return _save(fig, "04_cohort_retention")


def forecast_backtest(bt: pd.DataFrame, best_baseline: str):
    weekly = bt.resample("W-SUN")[["actual", "model", best_baseline]].sum(min_count=1)
    days = bt["actual"].resample("W-SUN").size()
    weekly = weekly[days >= 5]  # drop partial weeks at the edges of the test window
    fig, ax = plt.subplots(figsize=(10, 4.6))
    ax.plot(weekly.index, weekly["actual"], color=SERIES[0], marker="o", markersize=4, label="Actual")
    ax.plot(weekly.index, weekly["model"], color=SERIES[1], marker="o", markersize=4, label="Model forecast (28 days ahead)")
    ax.plot(weekly.index, weekly[best_baseline], color=MUTED, linewidth=1.5, label=f"Baseline: {best_baseline.lower()}")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(_gbp))
    ax.set_ylim(0, None)
    ax.set_title("Backtest on the last 6 months (never seen during model selection)")
    _subtitle(ax, "Weekly totals of daily forecasts; each 28-day block was forecast using only data before it")
    ax.legend(loc="upper left")
    return _save(fig, "05_forecast_backtest")


def forecast_error_comparison(scores: pd.DataFrame, metric: str = "daily_wape_pct"):
    s = scores.sort_values(metric, ascending=True)
    fig, ax = plt.subplots(figsize=(9, 3.4))
    colors = [SERIES[0] if m.startswith("Model") else NEUTRAL_BAR for m in s["method"]]
    ax.barh(s["method"], s[metric], color=colors, height=0.55)
    for yi, v in enumerate(s[metric]):
        ax.text(v + 0.5, yi, f"{v:.1f}%", va="center", fontsize=9, color=INK_2)
    ax.invert_yaxis()
    ax.xaxis.set_major_formatter(mticker.PercentFormatter(decimals=0))
    ax.grid(axis="y", visible=False)
    ax.set_title("Forecast error (WAPE, lower is better)")
    _subtitle(ax, "Daily net revenue, 28-day horizon, 6 rolling test folds")
    return _save(fig, "06_forecast_error_comparison")


def forecast_future(daily: pd.Series, future: pd.DataFrame, history_days: int = 70):
    hist = daily.iloc[-history_days:]
    fig, ax = plt.subplots(figsize=(10, 4.4))
    ax.plot(hist.index, hist.values, color=SERIES[0], linewidth=1.5, label="Actual daily revenue")
    ax.fill_between(future.index, future["lower_80"], future["upper_80"], color=SERIES[1], alpha=0.18, linewidth=0, label="80% interval")
    ax.plot(future.index, future["forecast"], color=SERIES[1], linewidth=1.8, label="Forecast")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(_gbp))
    ax.set_ylim(0, None)
    total = future["forecast"].sum()
    ax.set_title("Next 28 days: daily revenue forecast")
    _subtitle(ax, f"Forecast total {_gbp(total)}; model expects the usual Christmas shutdown (≈24 Dec – 3 Jan)")
    ax.legend(loc="upper left")
    return _save(fig, "07_forecast_next_28_days")


def daily_anomalies(daily_scored: pd.DataFrame):
    d = daily_scored
    fig, ax = plt.subplots(figsize=(11, 4.4))
    ax.plot(d.index, d["actual"], color=SERIES[0], linewidth=0.9, label="Daily net revenue")
    spikes = d[d["is_anomaly"] & (d["direction"] == "spike")]
    drops = d[d["is_anomaly"] & (d["direction"] == "drop")]
    ax.scatter(spikes.index, spikes["actual"], marker="^", s=46, color=CRITICAL, edgecolor=SURFACE, linewidth=1, zorder=3, label=f"Spike ({len(spikes)})")
    ax.scatter(drops.index, drops["actual"], marker="v", s=46, color=INK_2, edgecolor=SURFACE, linewidth=1, zorder=3, label=f"Drop ({len(drops)})")
    royal = pd.Timestamp("2011-04-29")
    if royal in drops.index:
        ax.annotate("29 Apr 2011: Royal Wedding\nbank holiday", (royal, 0), xytext=(30, 125), textcoords="offset points",
                    ha="center", fontsize=8.5, color=INK_2,
                    bbox=dict(boxstyle="round,pad=0.3", facecolor=SURFACE, edgecolor=AXIS, linewidth=0.6),
                    arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.8))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(_gbp))
    ax.set_title("Daily revenue anomalies")
    _subtitle(ax, "Robust z-score vs the same weekday in the surrounding ±4 weeks (|z| > 3.5). "
                  "Drops are mostly UK bank holidays; spikes are single large wholesale orders")
    ax.legend(loc="upper left")
    return _save(fig, "08_daily_anomalies")


def weekday_hour_heatmap(wh: pd.DataFrame):
    pivot = wh.pivot_table(index=["day_of_week", "day_name"], columns="hour", values="revenue", fill_value=0)
    fig, ax = plt.subplots(figsize=(10, 3.6))
    im = ax.imshow(pivot.to_numpy(), cmap=BLUE_RAMP, aspect="auto")
    ax.set_xticks(range(pivot.shape[1]), [f"{h}:00" for h in pivot.columns], fontsize=8.5)
    ax.set_yticks(range(pivot.shape[0]), [name[:3] for _, name in pivot.index])
    ax.grid(False)
    ax.set_title("When revenue happens: weekday × hour")
    _subtitle(ax, "Weekday late mornings to mid-afternoon dominate; no Saturday trading")
    cb = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02, format=mticker.FuncFormatter(_gbp))
    cb.outline.set_visible(False)
    return _save(fig, "09_weekday_hour_heatmap")


def pareto_curves(customer_rev: pd.Series, product_rev: pd.Series):
    fig, ax = plt.subplots(figsize=(7.5, 5))
    for i, (name, rev) in enumerate({"Customers": customer_rev, "Products": product_rev}.items()):
        r = np.sort(rev.clip(lower=0).to_numpy())[::-1]
        x = np.arange(1, len(r) + 1) / len(r) * 100
        y = np.cumsum(r) / r.sum() * 100
        ax.plot(x, y, color=SERIES[i], label=name)
        y20 = y[np.searchsorted(x, 20)]
        ax.scatter([20], [y20], color=SERIES[i], s=40, zorder=3, edgecolor=SURFACE, linewidth=1.5)
        ax.annotate(f"Top 20% of {name.lower()} = {y20:.0f}% of revenue", (20, y20), xytext=(12, -14 - 16 * i),
                    textcoords="offset points", fontsize=9, color=INK_2)
    ax.plot([0, 100], [0, 100], color=AXIS, linewidth=1)
    ax.xaxis.set_major_formatter(mticker.PercentFormatter(decimals=0))
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(decimals=0))
    ax.set_xlabel("Share of customers / products (ranked by revenue)")
    ax.set_ylabel("Cumulative share of net revenue")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 101)
    ax.set_title("Revenue concentration (Pareto)")
    ax.legend(loc="lower right")
    return _save(fig, "10_pareto_concentration")


def product_family_growth(fam: pd.DataFrame):
    f = fam.sort_values("yoy_growth_pct")
    fig, ax = plt.subplots(figsize=(9, 4.4))
    colors = [POSITIVE if v >= 0 else NEGATIVE for v in f["yoy_growth_pct"]]
    ax.barh(f["product_family"], f["yoy_growth_pct"], color=colors, height=0.6)
    for yi, (v, rev) in enumerate(zip(f["yoy_growth_pct"], f["revenue_dec10_nov11"])):
        ax.text(v + (0.8 if v >= 0 else -0.8), yi, f"{v:+.0f}%  ({_gbp(rev)})", va="center",
                ha="left" if v >= 0 else "right", fontsize=8.5, color=INK_2)
    ax.axvline(0, color=AXIS, linewidth=1)
    ax.xaxis.set_major_formatter(mticker.PercentFormatter(decimals=0))
    lim = max(abs(f["yoy_growth_pct"]).max() * 1.6, 10)
    ax.set_xlim(-lim, lim)
    ax.grid(axis="y", visible=False)
    ax.set_title("Category growth, Dec 2010–Nov 2011 vs prior year")
    _subtitle(ax, "Keyword-derived product families; label shows latest-year revenue")
    return _save(fig, "11_category_growth")


def top_countries(countries: pd.DataFrame, n: int = 10):
    c = countries[countries["country"] != "United Kingdom"].head(n).iloc[::-1]
    uk_share = countries.loc[countries["country"] == "United Kingdom", "revenue_share_pct"].iloc[0]
    fig, ax = plt.subplots(figsize=(8.5, 4.4))
    ax.barh(c["country"], c["net_revenue"], color=SERIES[0], height=0.6)
    for yi, (v, cust) in enumerate(zip(c["net_revenue"], c["customers"])):
        ax.text(v * 1.01, yi, f"{_gbp(v)} · {cust} customers", va="center", fontsize=8.5, color=INK_2)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(_gbp))
    ax.set_xlim(0, c["net_revenue"].max() * 1.35)
    ax.grid(axis="y", visible=False)
    ax.set_title(f"Top {n} markets outside the UK")
    _subtitle(ax, f"The UK is {uk_share:.0f}% of revenue; a few large wholesale accounts drive each export market")
    return _save(fig, "12_top_export_markets")
