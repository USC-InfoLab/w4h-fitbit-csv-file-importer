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
