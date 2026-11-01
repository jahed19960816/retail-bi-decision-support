# Executive insights brief

_Data: Dec 2009 - Dec 2011 (UCI Online Retail II, UK online gift wholesaler). Generated automatically from the pipeline outputs._

## What happened
- **£18.93M net revenue** from 39,516 orders and 5,852 identified customers; returns cost 3.6% of gross sales.
- Latest 12 months vs prior 12: revenue **+1.9%** while orders moved **-4.0%** - growth came from bigger baskets (average order value +6.8%), not more orders.
- Revenue is concentrated: the top 20% of customers generate **77%** of revenue and the top 20% of products **78%**.
- The UK is 85% of revenue. Biggest export markets: Ireland (£603K, 3 customers), Netherlands (£546K, 22 customers), Germany (£375K, 107 customers) - a handful of wholesale accounts per country.

## Customers
- **Champions** are 20% of customers but **74% of revenue**.
- **At Risk**: 1,442 customers who used to buy regularly (median 184 days since last order) and account for **£2.68M** of historical revenue.
- 72% of customers order more than once; the median gap between orders is 25 days.

## Products
- Growing categories: Christmas & Seasonal (+18%), Bags & Storage (+11%). Declining: Jewellery & Accessories (-28%), Candles & Lighting (-15%).
- Biggest return loss: Paper Craft , Little Birdie (£168K returned, 100% of its sales) - bulk orders cancelled shortly after being placed.

## Forecast & monitoring
- The 28-day revenue forecast has a daily error (WAPE) of **28.2%**, **10.7% lower** than the best simple baseline (last year, same weekday, 31.6%), measured on 6 months the model never saw during selection.
- Forecast for the next 28 days: **£493K**, including the Christmas shutdown.
- The order anomaly detector flags 181 orders; flagged orders were later cancelled **11.6%** of the time vs 5.8% for normal orders (2.0x) - a useful review queue before fulfilment.

## Recommended actions
1. **Win back At Risk accounts** - personal outreach to the highest-value ones first; recovering even 10% of their historical revenue is worth ~£268K.
2. **Protect Champions** with service and early access rather than discounts; losing a few large accounts moves total revenue.
3. **Grow basket size** with the co-purchase pairs from the market-basket analysis (bundles, 'often bought with').
4. **Review flagged large orders** (anomaly queue) before picking stock, to cut costly bulk cancellations.
5. **Plan stock for the Sep-Nov peak** using the 28-day forecast and its 80% interval as the safety-stock range.
