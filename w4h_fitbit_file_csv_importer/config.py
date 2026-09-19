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

# Sibling sample data for local dev/testing only — not bundled in this repo (ADR-016 style).
# Set W4H_DATA_DIR to this path (or override) in .env; never commit CSVs here.
DEV_SAMPLE_DATA_DIR = "../w4h-sample-icde-demo-csv/data"


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


def dev_sample_data_dir() -> Path:
    """Resolved path to sibling sample CSVs for local testing (see README)."""
    p = Path(DEV_SAMPLE_DATA_DIR)
    if not p.is_absolute():
        p = (_PKG_ROOT / p).resolve()
    return p


def data_dir() -> Path:
    """Folder holding the user-supplied CSV files (and the manifest.yaml built from them)."""
    raw = os.environ.get("W4H_DATA_DIR", "").strip()
    if not raw:
        raise RuntimeError(
            "Set W4H_DATA_DIR to the folder containing your Fitbit CSV files "
            f"(dev: clone w4h-sample-icde-demo-csv next to this repo and set "
            f"W4H_DATA_DIR={DEV_SAMPLE_DATA_DIR} in .env — see README)."
        )
    p = Path(raw)
    if not p.is_absolute():
        p = (_PKG_ROOT / p).resolve()
    return p
