# Power BI dashboard: build guide

Everything Power BI needs is already prepared by the Python pipeline:

- **Data:** `powerbi/data/*.csv`, a clean star schema. Create it with `python run_pipeline.py`.
- **Measures:** `powerbi/measures.dax`, 30+ DAX measures to paste in.
- **Design:** the page layouts below (5 analytical pages).

> **Mac users:** Power BI Desktop runs only on Windows. Options: a Windows PC or laptop, a Windows VM
> (Parallels or UTM), or a cloud Windows desktop. The free Power BI web service can show reports, but
> building the data model and DAX is far easier in Desktop.

---

## 1. Load the data (Home → Get data → Text/CSV)

Load all eight files from `powerbi/data/`:

| File | Rows | Role |
|---|---|---|
| fact_sales.csv | ~1.02M | Fact table: one row per invoice line (returns are negative) |
| dim_product.csv | 4.7K | Product master + `product_family` |
| dim_customer.csv | 5.9K | Customer master + cohort + RFM `segment` / scores |
| dim_date.csv | 739 | Calendar |
| fact_forecast.csv | 767 | Daily actuals, backtest predictions, 28-day forecast + 80% band |
| fact_cohort_retention.csv | 325 | Cohort × months-since-first-purchase retention % |
| segment_profile.csv | 4 | One row per segment with the recommended action |
| order_anomalies.csv | 181 | Orders flagged for review |

In Power Query, check these column types:
- `fact_sales[order_date]`, `dim_date[date]` and `fact_forecast[date]`: **Date**
- `fact_sales[invoice_date]`: Date/Time
- `customer_id`: Whole number
- `is_return` and `is_guest`: True/False

Then click **Close & Apply**.

## 2. Model view: relationships (all single-direction, many-to-one)

| From (many) | To (one) |
|---|---|
| fact_sales[stock_code] | dim_product[stock_code] |
| fact_sales[customer_id] | dim_customer[customer_id] |
| fact_sales[order_date] | dim_date[date] |
| fact_forecast[date] | dim_date[date] |

Then:
- **Mark `dim_date` as a date table:** Table tools → Mark as date table → `date`.
- **Sort the month names:** sort `dim_date[month_name]` by `dim_date[month]` (Column tools → Sort by column).
- **Add the measures:** create a blank `_Measures` table and paste in the measures from `measures.dax`. Format the money measures as Currency (£) and the % measures as Percentage.

## 3. Report pages

Use a consistent theme: blue `#2a78d6` as the main series colour, orange `#eb6834` for the
comparison series, and grey for baselines. Put the **slicers in one row across the top of each page**:
Date (between), Country, and Product family.

### Page 1: Executive overview
- KPI cards: Net Revenue, Orders, Customers, Avg Order Value and Return Rate %, each with **Revenue YoY %** (or the matching YoY measure) as the subtitle.
- Line chart: `dim_date[year_month]` × Net Revenue and Net Revenue PY.
- Bar chart: top 10 countries by Net Revenue.
- Bar chart: Net Revenue by `dim_product[product_family]`.
- Smart narrative visual (Insert → Smart narrative): auto-generated text summary.

### Page 2: Customers & segments
- Cards: Champions Revenue, At Risk Revenue, At Risk Customers.
- Clustered bar: `dim_customer[segment]` × customer count and Segment Revenue Share %.
- Scatter: recency_days (x) × monetary (y), with the legend set to `segment` and the size set to frequency.
- Table: `segment_profile` with `recommended_action`.
- Matrix (cohort heatmap): rows = `fact_cohort_retention[cohort]`, columns = `months_since_first`, values = average of `retention_pct`, with conditional formatting set to background colour, white → blue.

### Page 3: Products & returns
- Table: top 20 products by Net Revenue, with Units Sold, Return Rate % and Product Revenue Rank.
- Bar chart: product_family × Revenue YoY %, with conditional colour (blue for positive, red for negative).
- Decomposition tree: Net Revenue → product_family → description.

### Page 4: Forecast & monitoring
- Line chart: `fact_forecast[date]` × Actual Revenue (forecast table), Backtest Prediction and Forward Forecast. Use **Error bars** (Analytics pane) on Forward Forecast with Forecast Lower 80 and Forecast Upper 80, or a shaded band.
- Card: Backtest WAPE % (it should show about 28%).
- Table: `order_anomalies` sorted by anomaly_score, with conditional icons on `was_cancelled`.

### Page 5: Ask the data
- **Q&A visual** (Insert → Q&A). Add suggested questions such as "net revenue by country" and "top 10 products by net revenue".

## 4. Publish

Save the report as `powerbi/Retail_BI_Dashboard.pbix`. Export each page as a PNG (File → Export) into `reports/figures/powerbi_*.png` for the README.
Optionally, publish to the Power BI service and use **Publish to web** to get a public link for the resume and LinkedIn. Only do this with public data like this dataset.
