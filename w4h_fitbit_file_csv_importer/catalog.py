"""Fitbit column/signal descriptions and units.

Ported from w4h-api's vendor-metadata (fitbit.js + shared.js role templates). Mirrors
w4h-sample-fitbit-csv/manifest.yaml. Only ever fills EMPTY fields, so a hand edit in the
mapping review is never overwritten.
"""

import re

from .fitbit_shapes import canonicalize_header

TITLE = "Fitbit CSV import"
DESCRIPTION = "Fitbit CSV files mapped from their column conventions — review each signal before importing."

_SUBJECT_RE = re.compile(r"\b(id|subject|participant|patient)(id)?\b")

# keyed by signal slug, then by canonicalized column header
SIGNALS: dict[str, dict] = {
    "subjects": {
        "description": "Subject enrollment window (study period per participant).",
        "columns": {
            "id": {"description": "Subject identifier (Fitbit-encoded user id in exports)."},
            "startdate": {"description": "Start of data collection window for this subject."},
            "enddate": {"description": "End of data collection window for this subject."},
        },
    },
    "weight": {
        "description": "Body weight log from Fitbit Web API Get Weight Log.",
        "source_url": "https://dev.fitbit.com/build/reference/web-api/body/get-weight-log/",
        "columns": {
            "id": {"description": "Subject identifier."},
            "date": {"description": "Date of measurement."},
            "time": {"description": "Time of measurement (may include timezone)."},
            "weight": {"description": "Weight in kilograms.", "unit": "kg"},
            "bmi": {"description": "Body mass index."},
            "fatpercent": {"description": "Body fat percentage (optional in export)."},
            "source": {"description": "Data source label from Fitbit export."},
        },
        "values": {
            "weight": {"name": "weight_kg", "description": "Weight in kilograms", "unit": "kg"},
            "bmi": {"name": "bmi", "description": "Body mass index"},
            "fatpercent": {"name": "fat_percent", "description": "Body fat percentage"},
        },
    },
    "heart_rate": {
        "description": "Intraday heart rate (wear proxy). Non-zero BPM implies the band is worn.",
        "source_url": "https://dev.fitbit.com/build/reference/web-api/intraday/get-heartrate-intraday-by-date/",
        "sampling_interval": "1min",
        "columns": {
            "id": {"description": "Subject identifier."},
            "date": {"description": "Date of measurement."},
            "timestamp": {"description": "Time of measurement (HH:MM:SS)."},
            "value": {"description": "Heart rate in beats per minute.", "unit": "bpm"},
        },
        "values": {"value": {"name": "bpm", "description": "Heart rate in beats per minute", "unit": "bpm"}},
    },
    "calories": {
        "description": "Intraday calories burned. Optional mets column on rows for validation.",
        "source_url": "https://dev.fitbit.com/build/reference/web-api/intraday/get-activity-intraday-by-date/",
        "sampling_interval": "1min",
        "columns": {
            "id": {"description": "Subject identifier."},
            "date": {"description": "Date of measurement."},
            "time": {"description": "Time of measurement (HH:MM:SS)."},
            "value": {"description": "Calories burned in this interval.", "unit": "kcal"},
            "mets": {"description": "Vendor MET value when present.", "unit": "x10 METs"},
        },
        "values": {
            "value": {"name": "calories", "description": "Calories burned in this interval", "unit": "kcal"},
            "mets": {"name": "mets", "description": "Vendor metabolic equivalent when present", "unit": "x10 METs"},
        },
    },
}


def _role_template(canon: str) -> dict | None:
    """Column-name-only fallback for signals the catalog doesn't cover."""
    if canon == "startdate":
        return {"description": "Start of the enrollment/observation window for this subject."}
    if canon == "enddate":
        return {"description": "End of the enrollment/observation window for this subject."}
    if canon == "date":
        return {"description": "Date of measurement."}
    if canon == "timestamp":
        return {"description": "Timestamp of the measurement."}
    if canon == "time":
        return {"description": "Time of measurement (time of day)."}
    if canon in ("latitude", "lat"):
        return {"description": "Latitude, decimal degrees.", "unit": "decimal degrees"}
    if canon in ("longitude", "lon", "lng", "long"):
        return {"description": "Longitude, decimal degrees.", "unit": "decimal degrees"}
    if _SUBJECT_RE.search(canon):
        return {"description": "Subject identifier."}
    return None


def _signal_def(slug: str) -> dict | None:
    # Accept the file-derived form ("fitbit_heart_rate") as well as the canonical slug.
    return SIGNALS.get(slug) or SIGNALS.get(slug.removeprefix("fitbit_"))


def apply_catalog(manifest: dict) -> None:
    """Fill empty title/description/units from the catalog, in place."""
    if not manifest.get("title"):
        manifest["title"] = TITLE
    if not manifest.get("description"):
        manifest["description"] = DESCRIPTION
    for signal in manifest.get("signals", []):
        sdef = _signal_def(signal.get("slug", "")) or {}
        for key in ("description", "source_url", "sampling_interval"):
            if not signal.get(key) and sdef.get(key):
                signal[key] = sdef[key]
        for col in signal.get("columns", []):
            canon = canonicalize_header(col["name"])
            meta = sdef.get("columns", {}).get(canon) or _role_template(canon)
            if not meta:
                continue
            if not col.get("description") and meta.get("description"):
                col["description"] = meta["description"]
            if not col.get("unit") and meta.get("unit"):
                col["unit"] = meta["unit"]
        for v in signal.get("geomts_mapping", {}).get("values") or []:
            meta = sdef.get("values", {}).get(canonicalize_header(v["source"]))
            if not meta:
                continue
            if meta.get("name") and v.get("name") == v.get("source"):
                v["name"] = meta["name"]
            if not v.get("description") and meta.get("description"):
                v["description"] = meta["description"]
            if not v.get("unit") and meta.get("unit"):
                v["unit"] = meta["unit"]
