import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV_PATH = PROJECT_ROOT / "data" / "combined_rated_ads.csv"

def get_csv_path() -> Path:
    """Return the configured dataset path, resolved independently of the CWD."""
    return Path(os.getenv("COMBINED_ADS_CSV", DEFAULT_CSV_PATH)).expanduser().resolve()
