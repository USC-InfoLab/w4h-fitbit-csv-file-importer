"""Load W4H_API_KEY and related settings from environment / .env (never committed)."""

import os
from pathlib import Path

from dotenv import load_dotenv

_PKG_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PKG_ROOT / ".env")

VENDOR = "fitbit"
# Namespaces physical tables in the dataset schema so Fitbit signals (e.g. heart_rate)
# never collide with other vendors'. Sent in every csv-batch payload — do not drop it.
TABLE_PREFIX = "fitbit"

# Stepping-stone default for in-app Run / `./run.sh` when W4H_DATA_DIR is unset:
# load the sibling Fitbit sample package (same files as w4h-sample-fitbit-csv-importer)
# so results can be compared in the app. Do not copy those CSVs into this repo.
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
    return os.environ.get("W4H_DATASET_ID", "").strip()


def sibling_sample_root() -> Path:
    raw = os.environ.get("W4H_SAMPLE_FITBIT_CSV_PATH", SIBLING_SAMPLE_REPO).strip()
    p = Path(raw)
    if not p.is_absolute():
        p = (_PKG_ROOT / p).resolve()
    return p


def hardcoded_csv_paths() -> list[Path]:
    """Resolved sibling sample CSVs used when W4H_DATA_DIR is unset (in-app Run)."""
    root = sibling_sample_root()
    paths = [(root / rel).resolve() for rel in HARDCODED_CSV_FILES]
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        raise FileNotFoundError(
            "Sibling Fitbit sample CSVs not found (clone w4h-sample-fitbit-csv next to "
            f"this repo, or set W4H_SAMPLE_FITBIT_CSV_PATH / W4H_DATA_DIR):\n  "
            + "\n  ".join(missing)
        )
    return paths


def data_dir_from_env() -> str:
    return os.environ.get("W4H_DATA_DIR", "").strip()


def data_dir() -> Path:
    """Folder holding the CSV files (and, when set by the user, manifest.yaml)."""
    raw = data_dir_from_env()
    if raw:
        p = Path(raw)
        if not p.is_absolute():
            p = (_PKG_ROOT / p).resolve()
        return p
    return hardcoded_csv_paths()[0].parent
