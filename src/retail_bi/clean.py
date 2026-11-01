"""Clean raw transactions into an analysis-ready sales fact table.

Every rule is logged with the number of rows it removed so the data-quality
report can show exactly how the raw file became the clean table.

Design decisions
----------------
* Cancellations (invoice starting with "C") are KEPT as negative "return" lines,
  so net revenue = gross sales + returns. Dropping them would overstate revenue
  (e.g. an 80,995-unit order that was cancelled minutes later).
* Lines without a Customer ID are KEPT for revenue KPIs (guest checkouts) and
  excluded only from customer-level analysis (RFM, cohorts).
* Non-product lines (postage, fees, manual adjustments, vouchers, test items)
  are removed from the product sales table.
"""

from dataclasses import dataclass, field

import pandas as pd

# The two source sheets overlap: both contain 2010-12-01 .. 2010-12-09.
OVERLAP_SHEET = "Year 2009-2010"
OVERLAP_START = pd.Timestamp("2010-12-01")

NON_PRODUCT_CODES = {
    "POST", "DOT", "C2",                      # postage / carriage
    "M", "D", "S", "B", "CRUK",               # manual, discount, samples, bad debt, charity commission
    "BANK CHARGES", "AMAZONFEE",              # fees
    "ADJUST", "ADJUST2",                      # manual stock adjustments
    "TEST001", "TEST002",                     # test products
}
NON_PRODUCT_PREFIXES = ("GIFT_",)            # gift vouchers

COUNTRY_NAME_FIXES = {
    "EIRE": "Ireland",
    "RSA": "South Africa",
    "USA": "United States",
    "Korea": "South Korea",
    "Czech Republic": "Czechia",
}

KEY_COLUMNS = ["invoice", "stock_code", "description", "quantity", "invoice_date", "unit_price", "customer_id", "country"]


@dataclass
class CleaningLog:
    steps: list = field(default_factory=list)

    def record(self, step: str, reason: str, before: int, after: int) -> None:
        self.steps.append(
            {"step": step, "reason": reason, "rows_before": before, "rows_removed": before - after, "rows_after": after}
        )

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.steps)


def is_non_product(stock_code: pd.Series) -> pd.Series:
    code = stock_code.str.upper()
    return code.isin(NON_PRODUCT_CODES) | code.str.startswith(NON_PRODUCT_PREFIXES)


def _drop(df: pd.DataFrame, mask: pd.Series, log: CleaningLog, step: str, reason: str) -> pd.DataFrame:
    before = len(df)
    out = df.loc[~mask]
    log.record(step, reason, before, len(out))
    return out


def clean_transactions(raw: pd.DataFrame) -> tuple[pd.DataFrame, CleaningLog]:
    """Apply the cleaning rules and return (clean line-level table, log)."""
    log = CleaningLog()
    df = raw.copy()
    df["invoice"] = df["invoice"].str.strip()
    df["stock_code"] = df["stock_code"].str.strip().str.upper()
    df["description"] = df["description"].str.strip()

    df = _drop(
        df,
        (df["source_sheet"] == OVERLAP_SHEET) & (df["invoice_date"] >= OVERLAP_START),
        log,
        "Remove sheet overlap",
        "2010-12-01..09 appears in both yearly sheets; keep one copy",
    )

    # One canonical description per product (the most frequent spelling), applied
    # before de-duplication so lines that differ only by a typo are caught too.
    canonical = (
        df.dropna(subset=["description"])
        .groupby(["stock_code", "description"])
        .size()
        .rename("n")
        .reset_index()
        .sort_values(["stock_code", "n"], ascending=[True, False])
        .drop_duplicates("stock_code")
        .set_index("stock_code")["description"]
    )
    df["description"] = df["stock_code"].map(canonical).fillna("UNKNOWN PRODUCT")

    df = _drop(df, df.duplicated(KEY_COLUMNS), log, "Remove exact duplicates", "Identical line entered more than once")
    df = _drop(df, df["invoice"].str.startswith("A"), log, "Remove bad-debt adjustments", "Accounting entries, not sales")
    df = _drop(df, is_non_product(df["stock_code"]), log, "Remove non-product lines", "Postage, fees, manual adjustments, vouchers, tests")
    df = _drop(df, df["unit_price"] <= 0, log, "Remove zero/negative prices", "Free items and stock write-offs")

    is_cancel = df["invoice"].str.startswith("C")
    df = _drop(df, ~is_cancel & (df["quantity"] <= 0), log, "Remove stock write-offs", "Non-invoice lines with quantity <= 0")
    is_cancel = df["invoice"].str.startswith("C")
    df = _drop(df, is_cancel & (df["quantity"] >= 0), log, "Remove malformed returns", "Cancellation lines must have quantity < 0")

    df = df.drop(columns="source_sheet")
    df["is_return"] = df["invoice"].str.startswith("C")
    df["line_revenue"] = (df["quantity"] * df["unit_price"]).round(2)
    df["order_date"] = df["invoice_date"].dt.normalize()
    df["country"] = df["country"].replace(COUNTRY_NAME_FIXES)
    df["is_guest"] = df["customer_id"].isna()

    df = df.sort_values(["invoice_date", "invoice"]).reset_index(drop=True)
    return df, log


def profile(raw: pd.DataFrame, clean: pd.DataFrame) -> dict:
    """Headline numbers for the data-quality report."""
    sales = clean[~clean["is_return"]]
    returns = clean[clean["is_return"]]
    return {
        "raw_rows": len(raw),
        "clean_rows": len(clean),
        "sales_lines": len(sales),
        "return_lines": len(returns),
        "raw_missing_customer_pct": round(raw["customer_id"].isna().mean() * 100, 1),
        "clean_missing_customer_pct": round(clean["customer_id"].isna().mean() * 100, 1),
        "invoices": clean.loc[~clean["is_return"], "invoice"].nunique(),
        "customers": sales["customer_id"].nunique(),
        "products": clean["stock_code"].nunique(),
        "countries": clean["country"].nunique(),
        "date_min": str(clean["invoice_date"].min()),
        "date_max": str(clean["invoice_date"].max()),
        "gross_revenue": round(sales["line_revenue"].sum(), 2),
        "returns_value": round(returns["line_revenue"].sum(), 2),
        "net_revenue": round(clean["line_revenue"].sum(), 2),
    }
