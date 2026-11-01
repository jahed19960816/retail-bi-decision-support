"""Run the full analytics pipeline:  python run_pipeline.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from retail_bi.pipeline import run  # noqa: E402

if __name__ == "__main__":
    run()
