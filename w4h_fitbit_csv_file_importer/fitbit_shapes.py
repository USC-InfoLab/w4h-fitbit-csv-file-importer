"""Curated Fitbit CSV column shapes, ported from w4h-app's csvProfile.js VENDOR_REGISTRY.fitbit.

A file whose canonical headers overlap a shape by >= SHAPE_MIN_OVERLAP is a "known
Fitbit shape" — informational in the mapping review (Fitbit shapes carry no column
type hints; types come from profiling).
"""

import re

SHAPE_MIN_OVERLAP = 0.9

SHAPES: dict[str, set[str]] = {
    "subjects": {"id", "startdate", "enddate"},
    "weight": {"id", "date", "time", "weight", "bmi", "fatpercent", "source"},
    "calories": {"id", "date", "time", "value", "mets"},
    "single_value_timeseries": {"id", "date", "timestamp", "value"},
    "gps_track": {"id", "date", "timestamp", "latitude", "longitude"},
    "daily_activity": {
        "id", "activitydate", "totalsteps", "totaldistance", "trackerdistance",
        "veryactivedistance", "moderatelyactivedistance", "lightactivedistance",
        "sedentaryactivedistance", "veryactiveminutes", "fairlyactiveminutes",
        "lightlyactiveminutes", "sedentaryminutes", "calories",
    },
    "weight_log": {"id", "date", "weightkg", "weightpounds", "fat", "bmi", "ismanualreport", "logid"},
    "hourly_calories": {"id", "activityhour", "calories"},
    "hourly_intensities": {"id", "activityhour", "totalintensity", "averageintensity"},
    "hourly_steps": {"id", "activityhour", "steptotal"},
    "minute_calories": {"id", "activityminute", "calories"},
    "minute_intensities": {"id", "activityminute", "intensity"},
    "minute_mets": {"id", "activityminute", "mets"},
    "minute_steps": {"id", "activityminute", "steps"},
    "minute_sleep": {"id", "date", "value", "logid"},
    "seconds_timeseries": {"id", "time", "value"},
    "daily_calories": {"id", "activityday", "calories"},
    "daily_intensities": {
        "id", "activityday", "sedentaryminutes", "lightlyactiveminutes", "fairlyactiveminutes",
        "veryactiveminutes", "sedentaryactivedistance", "lightactivedistance",
        "moderatelyactivedistance", "veryactivedistance",
    },
    "daily_steps": {"id", "activityday", "steptotal"},
    "sleep_day": {"id", "sleepday", "totalsleeprecords", "totalminutesasleep", "totaltimeinbed"},
}
# Deliberately no shape for Fitabase's "Wide" per-minute files (60 value columns per
# row): csv-batch imports one CSV row as one GeoMTS row, so they need a reshape first.


def canonicalize_header(header: str) -> str:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(header or ""))
    return re.sub(r"[^a-z0-9]+", "", spaced.lower())


def matched_shape(headers: list[str]) -> str | None:
    canon = {canonicalize_header(h) for h in headers}
    for name, cols in SHAPES.items():
        if len(cols & canon) / len(cols) >= SHAPE_MIN_OVERLAP:
            return name
    return None


_GENERIC = {"id", "date", "time", "timestamp", "value"}
_FITBIT_COLS = set().union(*SHAPES.values()) - _GENERIC


def is_fitbit(headers: list[str]) -> bool:
    """Looser than matched_shape: a known shape, or an Id column plus any Fitbit-specific header.

    Deliberately not stricter: headers cannot tell Fitbit from other datasets that share the generic
    id/date/timestamp/value layout (ICDE demo files pass), and Fitabase Wide files pass too.
    """
    canon = {canonicalize_header(h) for h in headers}
    return matched_shape(headers) is not None or ("id" in canon and bool(canon & _FITBIT_COLS))
