"""Project paths and shared settings."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Keep matplotlib's font cache inside the project instead of the user's home directory.
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".cache" / "matplotlib"))

DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
WAREHOUSE_DIR = ROOT / "data" / "warehouse"
WAREHOUSE_DB = WAREHOUSE_DIR / "retail.duckdb"

SQL_DIR = ROOT / "sql"
REPORTS_DIR = ROOT / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"
TABLES_DIR = REPORTS_DIR / "tables"
POWERBI_DATA_DIR = ROOT / "powerbi" / "data"

DATASET_URL = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"
RAW_ZIP = DATA_RAW / "online_retail_ii.zip"
RAW_XLSX_NAME = "online_retail_II.xlsx"

RANDOM_STATE = 42

# Forecasting: predict the next 28 days (4 weeks), a typical replenishment planning window.
FORECAST_HORIZON_DAYS = 28
BACKTEST_FOLDS = 6


def ensure_dirs() -> None:
    for path in (DATA_RAW, DATA_PROCESSED, WAREHOUSE_DIR, FIGURES_DIR, TABLES_DIR, POWERBI_DATA_DIR):
        path.mkdir(parents=True, exist_ok=True)
