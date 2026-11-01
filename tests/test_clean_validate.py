import pandas as pd
import pytest

from retail_bi.clean import clean_transactions
from retail_bi.validate import assert_valid, run_checks


def _row(invoice, code, qty, price, when, customer=12345, desc="WHITE MUG", sheet="Year 2010-2011", country="United Kingdom"):
    return {
        "invoice": invoice, "stock_code": code, "description": desc, "quantity": qty,
        "invoice_date": pd.Timestamp(when), "unit_price": price, "customer_id": customer,
        "country": country, "source_sheet": sheet,
    }


@pytest.fixture
def raw():
    rows = [
        _row("500001", "22423", 2, 10.0, "2011-01-05 10:00"),
        _row("500001", "22423", 2, 10.0, "2011-01-05 10:00"),                        # exact duplicate
        _row("500001", "22423", 2, 10.0, "2011-01-05 10:00", desc="WHITE  MUG"),      # duplicate with typo
        _row("500002", "POST", 1, 18.0, "2011-01-05 11:00", desc="POSTAGE"),         # non-product
        _row("500003", "85123A", 6, 0.0, "2011-01-06 09:00"),                         # zero price
        _row("500004", "85123A", -10, 2.5, "2011-01-06 09:30"),                       # stock write-off
        _row("A500005", "B", 1, -500.0, "2011-01-07 09:00", desc="Adjust bad debt"),  # bad-debt adjustment
        _row("C500006", "22423", -1, 10.0, "2011-01-08 12:00"),                       # genuine return
        _row("490001", "22423", 1, 10.0, "2010-12-03 10:00", sheet="Year 2009-2010"), # sheet overlap copy
        _row("490001", "22423", 1, 10.0, "2010-12-03 10:00"),                         # kept copy
        _row("500007", "85123A", 3, 2.5, "2011-01-09 10:00", customer=None, country="EIRE"),
    ]
    df = pd.DataFrame(rows)
    df["customer_id"] = df["customer_id"].astype("Int64")
    return df


def test_cleaning_rules_remove_the_right_rows(raw):
    clean, log = clean_transactions(raw)
    removed = log.to_frame().set_index("step")["rows_removed"].to_dict()
    assert removed["Remove sheet overlap"] == 1
    assert removed["Remove exact duplicates"] == 2          # the plain duplicate and the typo duplicate
    assert removed["Remove bad-debt adjustments"] == 1
    assert removed["Remove non-product lines"] == 1
    assert removed["Remove zero/negative prices"] == 1
    assert removed["Remove stock write-offs"] == 1
    assert len(clean) == 4


def test_returns_are_kept_as_negative_revenue(raw):
    clean, _ = clean_transactions(raw)
    ret = clean[clean["is_return"]]
    assert len(ret) == 1 and ret["line_revenue"].iloc[0] == -10.0
    assert clean["line_revenue"].sum() == pytest.approx(20.0 + 10.0 - 10.0 + 7.5)


def test_guest_lines_kept_and_country_names_fixed(raw):
    clean, _ = clean_transactions(raw)
    guest = clean[clean["is_guest"]]
    assert len(guest) == 1 and guest["country"].iloc[0] == "Ireland"


def test_clean_output_passes_validation(raw):
    clean, _ = clean_transactions(raw)
    assert_valid(run_checks(clean))


def test_validation_catches_broken_data(raw):
    clean, _ = clean_transactions(raw)
    broken = clean.copy()
    broken.loc[broken.index[0], "unit_price"] = -1.0
    with pytest.raises(ValueError, match="Unit price is positive"):
        assert_valid(run_checks(broken))
