"""Load W4H_API_KEY from environment / .env (never committed)."""

import os
from pathlib import Path

from dotenv import load_dotenv

_PKG_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PKG_ROOT / ".env")

VENDOR = "fitbit"
# Namespaces physical tables in the dataset schema so Fitbit signals (e.g. heart_rate)
# never collide with other vendors'. Sent in every csv-batch payload — do not drop it.
TABLE_PREFIX = "fitbit"

# Stepping-stone files for in-app Run / ./run.sh (same package as the catalogued
# Fitbit sample importer). Do not copy those CSVs into this repo.
SIBLING_SAMPLE_REPO = "../w4h-sample-fitbit-csv"
HARDCODED_CSV_FILES = (
    "data/fitbit_subjects.csv",
    "data/fitbit_heart_rate.csv",
    "data/fitbit_calories.csv",
    "data/fitbit_weight.csv",
)


def require_api_key() -> str:
    key = os.environ.get("W4H_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "Set W4H_API_KEY in your environment or .env (copy .env.example). "
            "Generate from W4H Profile → API keys."
        )
    return key


def api_base() -> str:
    return os.environ.get("W4H_API_BASE", "http://localhost:2026").rstrip("/")


def dataset_id() -> str:
    """Id from the process environment (in-app Run). Empty if unset."""
    return os.environ.get("W4H_DATASET_ID", "").strip()


def sibling_sample_root() -> Path:
    return (_PKG_ROOT / SIBLING_SAMPLE_REPO).resolve()


def hardcoded_csv_paths() -> list[Path]:
    """Sibling sample CSVs used by in-app Run / ./run.sh."""
    root = sibling_sample_root()
    paths = [(root / rel).resolve() for rel in HARDCODED_CSV_FILES]
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        raise FileNotFoundError(
            "Sibling Fitbit sample CSVs not found — clone w4h-sample-fitbit-csv "
            "next to this repo:\n  " + "\n  ".join(missing)
        )
    return paths
