"""Download the UCI Online Retail II dataset and load it into a single DataFrame.

The source workbook has two sheets ("Year 2009-2010" and "Year 2010-2011").
Reading 1M+ rows from Excel is slow, so the combined raw table is cached as Parquet.
"""

import shutil
import urllib.request
import zipfile

import pandas as pd

from retail_bi import config

RAW_PARQUET = config.DATA_PROCESSED / "raw_combined.parquet"

COLUMN_MAP = {
    "Invoice": "invoice",
    "StockCode": "stock_code",
    "Description": "description",
    "Quantity": "quantity",
    "InvoiceDate": "invoice_date",
    "Price": "unit_price",
    "Customer ID": "customer_id",
    "Country": "country",
}


def download_dataset(force: bool = False) -> None:
    """Fetch the dataset zip from the UCI repository if it is not already present."""
    config.ensure_dirs()
    if config.RAW_ZIP.exists() and not force:
        return
    print(f"Downloading {config.DATASET_URL} ...")
    with urllib.request.urlopen(config.DATASET_URL) as response, open(config.RAW_ZIP, "wb") as out:
        shutil.copyfileobj(response, out)


def _read_workbook() -> pd.DataFrame:
    with zipfile.ZipFile(config.RAW_ZIP) as zf, zf.open(config.RAW_XLSX_NAME) as fh:
        sheets = pd.read_excel(
            fh,
            sheet_name=None,
            dtype={"Invoice": str, "StockCode": str, "Description": str, "Country": str},
            engine="openpyxl",
        )
    frames = []
    for sheet_name, frame in sheets.items():
        frame = frame.rename(columns=COLUMN_MAP)
        frame["source_sheet"] = sheet_name
        frames.append(frame)
    df = pd.concat(frames, ignore_index=True)
    df["customer_id"] = df["customer_id"].astype("Int64")
    df["invoice_date"] = pd.to_datetime(df["invoice_date"])
    return df


def load_raw(refresh: bool = False) -> pd.DataFrame:
    """Return the raw combined transactions (both sheets), using the Parquet cache when available."""
    download_dataset()
    if RAW_PARQUET.exists() and not refresh:
        return pd.read_parquet(RAW_PARQUET)
    print("Reading Excel workbook (one-time, ~1-2 minutes) ...")
    df = _read_workbook()
    df.to_parquet(RAW_PARQUET, index=False)
    return df
