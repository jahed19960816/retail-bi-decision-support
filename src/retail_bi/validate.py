"""Data validation checks for the clean sales table.

A lightweight, dependency-free take on "data contracts": each check returns a
pass/fail result with evidence, and critical failures stop the pipeline.
"""

from dataclasses import dataclass

import pandas as pd

from retail_bi.clean import KEY_COLUMNS, is_non_product


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str
    critical: bool = True


def run_checks(df: pd.DataFrame) -> list[CheckResult]:
    sales = df[~df["is_return"]]
    returns = df[df["is_return"]]
    results = []

    def check(name: str, passed: bool, detail: str, critical: bool = True) -> None:
        results.append(CheckResult(name, bool(passed), detail, critical))

    required = ["invoice", "stock_code", "description", "quantity", "invoice_date", "unit_price", "country", "line_revenue"]
    nulls = {c: int(df[c].isna().sum()) for c in required}
    check("No nulls in required columns", sum(nulls.values()) == 0, f"null counts: {nulls}")

    dupes = int(df.duplicated(KEY_COLUMNS).sum())
    check("No duplicate lines", dupes == 0, f"{dupes} duplicate lines")

    check("Unit price is positive", (df["unit_price"] > 0).all(), f"min price = {df['unit_price'].min():.3f}")
    check("Sales quantities are positive", (sales["quantity"] > 0).all(), f"min sales qty = {sales['quantity'].min()}")
    check("Return quantities are negative", (returns["quantity"] < 0).all(), f"max return qty = {returns['quantity'].max()}")
    check(
        "Returns are exactly the 'C' invoices",
        (df["is_return"] == df["invoice"].str.startswith("C")).all(),
        "is_return flag matches invoice prefix",
    )

    recomputed = (df["quantity"] * df["unit_price"]).round(2)
    gap = float((recomputed - df["line_revenue"]).abs().max())
    check("Line revenue reconciles to qty x price", gap < 0.01, f"max gap = {gap:.4f}")

    n_non_product = int(is_non_product(df["stock_code"]).sum())
    check("No non-product stock codes", n_non_product == 0, f"{n_non_product} non-product lines")

    lo, hi = df["invoice_date"].min(), df["invoice_date"].max()
    check(
        "Dates inside dataset window",
        lo >= pd.Timestamp("2009-12-01") and hi < pd.Timestamp("2011-12-10"),
        f"{lo} -> {hi}",
    )

    per_invoice_dates = df.groupby("invoice")["invoice_date"].nunique().max()
    check("One timestamp per invoice", per_invoice_dates == 1, f"max distinct timestamps per invoice = {per_invoice_dates}", critical=False)

    per_invoice_customers = df.groupby("invoice")["customer_id"].nunique().max()
    check("One customer per invoice", per_invoice_customers <= 1, f"max customers per invoice = {per_invoice_customers}")

    guest_pct = df["customer_id"].isna().mean() * 100
    check("Guest (no customer ID) share below 30%", guest_pct < 30, f"{guest_pct:.1f}% of lines", critical=False)

    net = df["line_revenue"].sum()
    check("Net revenue is positive", net > 0, f"net revenue = {net:,.2f}")
    return results


def results_frame(results: list[CheckResult]) -> pd.DataFrame:
    return pd.DataFrame([r.__dict__ for r in results])


def assert_valid(results: list[CheckResult]) -> None:
    failed = [r for r in results if r.critical and not r.passed]
    if failed:
        lines = "\n".join(f"- {r.name}: {r.detail}" for r in failed)
        raise ValueError(f"Data validation failed:\n{lines}")
