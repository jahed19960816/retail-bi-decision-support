# Data quality report

Source: UCI Online Retail II (1,067,371 raw rows, two yearly Excel sheets).

## Cleaning steps

| step | reason | rows_before | rows_removed | rows_after |
|---|---|---|---|---|
| Remove sheet overlap | 2010-12-01..09 appears in both yearly sheets; keep one copy | 1067371 | 22523 | 1044848 |
| Remove exact duplicates | Identical line entered more than once | 1044848 | 11814 | 1033034 |
| Remove bad-debt adjustments | Accounting entries, not sales | 1033034 | 6 | 1033028 |
| Remove non-product lines | Postage, fees, manual adjustments, vouchers, tests | 1033028 | 5793 | 1027235 |
| Remove zero/negative prices | Free items and stock write-offs | 1027235 | 5965 | 1021270 |
| Remove stock write-offs | Non-invoice lines with quantity <= 0 | 1021270 | 0 | 1021270 |
| Remove malformed returns | Cancellation lines must have quantity < 0 | 1021270 | 0 | 1021270 |

## Result

- Clean lines: **1,021,270** (1,003,355 sales + 17,915 returns)
- Orders: 39,516 · customers: 5,852 · products: 4,739 · countries: 43
- Period: 2009-12-01 07:45:00 -> 2011-12-09 12:50:00
- Gross revenue £19,643,309.77, returns £-716,462.57, net £18,926,847.20
- Lines without a customer ID: 22.8% raw -> 22.2% clean (kept for revenue KPIs, excluded from customer analytics)

## Validation checks

| name | passed | detail | critical |
|---|---|---|---|
| No nulls in required columns | PASS | null counts: {'invoice': 0, 'stock_code': 0, 'description': 0, 'quantity': 0, 'invoice_date': 0, 'unit_price': 0, 'country': 0, 'line_revenue': 0} | True |
| No duplicate lines | PASS | 0 duplicate lines | True |
| Unit price is positive | PASS | min price = 0.001 | True |
| Sales quantities are positive | PASS | min sales qty = 1 | True |
| Return quantities are negative | PASS | max return qty = -1 | True |
| Returns are exactly the 'C' invoices | PASS | is_return flag matches invoice prefix | True |
| Line revenue reconciles to qty x price | PASS | max gap = 0.0000 | True |
| No non-product stock codes | PASS | 0 non-product lines | True |
| Dates inside dataset window | PASS | 2009-12-01 07:45:00 -> 2011-12-09 12:50:00 | True |
| One timestamp per invoice | WARN | max distinct timestamps per invoice = 2 | False |
| One customer per invoice | PASS | max customers per invoice = 1 | True |
| Guest (no customer ID) share below 30% | PASS | 22.2% of lines | False |
| Net revenue is positive | PASS | net revenue = 18,926,847.20 | True |

## Known limitations

- Some refunds were booked as manual ('M') adjustments without a product code; these are removed with the other
  non-product lines, so a few reversed orders (e.g. invoice 556444, £38,970) still count as sales. The order
  anomaly detector flags them for review.
- Dec 2009 is the first month of data, so it contains customers who bought before the dataset starts
  (cohort and 'new customer' figures for that month are overstated).
- Product families are keyword-derived from descriptions (about 5% of revenue stays in 'Other').
