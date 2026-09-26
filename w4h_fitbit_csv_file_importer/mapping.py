"""Build a GeoMTS mapping manifest from local CSV profiles — no API call.

Ported from w4h-api's buildSignalDeterministic()/buildManifestDeterministic(). Rules:
filename-stem slug; id-like column is the subject; date + bare time-of-day combine into
the time axis; a lone full timestamp/date is the axis; lat/lon pair is geo; remaining
numeric columns are values (none when there is no time axis); dedupe covers subject + time.
"""

import os
import re
from pathlib import Path

from .catalog import apply_catalog
from .config import VENDOR
from .fitbit_shapes import canonicalize_header, matched_shape
from .profile import profile_csv

_SUBJECT_RE = re.compile(r"\b(id|subject|participant|patient)([_-]?id)?\b", re.I)
_SUBJECT_COMPOUND = {"participantidentifier", "participantid", "subjectid", "patientid"}
_NUMERIC = {"integer", "bigint", "double precision", "numeric"}
_LAT_RE = re.compile(r"^(lat|latitude)$", re.I)
_LON_RE = re.compile(r"^(lon|lng|long|longitude)$", re.I)
_DATE_NAME_RE = re.compile(r"^date$", re.I)
_TIME_NAME_RE = re.compile(r"^(time|timestamp)$", re.I)


def slug_from_filename(name: str) -> str:
    """Drop Fitabase export suffixes (_merged, Narrow, Wide): heartrate_seconds_merged -> heartrate_seconds.

    A leading `fitbit_` on the stem is the sample-package / export prefix, not the
    signal — strip it so fitbit_heart_rate.csv maps to heart_rate (same slug the
    catalogued Fitbit sample importer uses).
    """
    stem = re.sub(r"\.[^./]+$", "", str(name or "")).lower()
    stem = re.sub(r"[_-]?merged$", "", stem)
    stem = re.sub(r"[_-]?(narrow|wide)$", "", stem)
    stem = re.sub(r"[^a-z0-9]+", "_", stem).strip("_")
    if stem.startswith("fitbit_"):
        stem = stem[len("fitbit_") :]
    return stem or "signal"


def _is_subject(header: str) -> bool:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", header)
    spaced = re.sub(r"[_-]+", " ", spaced)
    return bool(_SUBJECT_RE.search(spaced)) or canonicalize_header(header) in _SUBJECT_COMPOUND


def build_signal(profile: dict) -> dict:
    # First occurrence of each header wins: duplicate names can't become physical columns.
    columns, seen = [], set()
    for header, type_ in zip(profile["headers"], profile["inferred_types"]):
        if header in seen:
            continue
        seen.add(header)
        columns.append({"name": header, "type": type_, "description": ""})
    names = [c["name"] for c in columns]
    type_of = {c["name"]: c["type"] for c in columns}

    subject = next((h for h in names if _is_subject(h)), None)
    if subject:  # an identifier is text, never the integer its digits infer as
        type_of[subject] = "text"
        next(c for c in columns if c["name"] == subject)["type"] = "text"

    date_typed = [h for h in names if type_of[h] == "date"]
    ts_typed = [h for h in names if type_of[h] == "timestamp"]
    date_col = next((h for h in names if _DATE_NAME_RE.match(h)), None) or (
        date_typed[0] if len(date_typed) == 1 else None
    )
    time_col = next(
        (h for h in names if h != date_col and _TIME_NAME_RE.match(h) and type_of[h] != "timestamp"),
        None,
    )
    full_ts = ts_typed[0] if len(ts_typed) == 1 else None

    time = None
    if date_col and time_col:
        time = {"combine": [date_col, time_col]}
        next(c for c in columns if c["name"] == time_col)["type"] = "text"  # bare time-of-day (ADR-008)
    elif full_ts:
        time = {"column": full_ts}
    elif date_col:
        time = {"column": date_col}
    time_cols = time.get("combine") or [time["column"]] if time else []

    lat = next((h for h in names if _LAT_RE.match(h)), None)
    lon = next((h for h in names if _LON_RE.match(h)), None)
    geo = {"lat": lat, "lon": lon} if lat and lon else None

    used = {subject, *time_cols, *([lat, lon] if geo else [])} - {None}
    values = (
        []
        if time is None
        else [
            {"source": c["name"], "name": c["name"], "type": c["type"], "description": ""}
            for c in columns
            if c["name"] not in used and c["type"] in _NUMERIC
        ]
    )

    slug = slug_from_filename(Path(profile["name"]).name)
    mapping = {"signal_type": slug, "subject": subject, "time": time, "values": values}
    if geo:
        mapping["geo"] = geo
    signal = {
        "slug": slug,
        "file": profile["name"],
        "delimiter": profile.get("delimiter", ","),
        "description": "",
        "columns": columns,
        "geomts_mapping": mapping,
        "dedupe_columns": [c for c in [subject, *time_cols] if c],
    }
    shape = matched_shape(profile["headers"])
    if shape:
        signal["matched_shape"] = shape
    return signal


def build_manifest(profiles: list[dict]) -> dict:
    signals, counts = [], {}
    for profile in profiles:
        sig = build_signal(profile)
        counts[sig["slug"]] = counts.get(sig["slug"], 0) + 1
        if counts[sig["slug"]] > 1:  # keep slugs unique across same-stem files
            sig["slug"] = f"{sig['slug']}_{counts[sig['slug']]}"
            sig["geomts_mapping"]["signal_type"] = sig["slug"]
        signals.append(sig)
    manifest = {"vendor": VENDOR, "format": "csv", "version": "1.0.0", "signals": signals}
    apply_catalog(manifest)
    return manifest


MAX_DEPTH = 5  # subfolder levels below the root; also stops symlink loops


def find_csvs(root: Path) -> tuple[list[Path], list[tuple[str, str]]]:
    """Every .csv under root, walking subfolders and following symlinks that stay inside root.

    Returns (paths, problems); problems are (reason, relative path) for links that leave the
    folder or point nowhere, subfolders that cannot be read, and subfolders below MAX_DEPTH.
    Dot-files and dot-folders (the API's .owner.json / .<name>.part) and non-.csv files are
    ignored. Links back to an enclosing folder are skipped, and a file reachable through several
    links is listed once, under its real path.
    """
    root = Path(root).resolve()
    paths: list[Path] = []
    problems: list[tuple[str, str]] = []
    if not os.access(root, os.R_OK | os.X_OK):
        problems.append(("Unreadable folder", "."))
        return paths, problems

    def unreadable(err: OSError) -> None:
        problems.append(("Unreadable folder", Path(err.filename).relative_to(root).as_posix()))

    def inside(p: Path) -> bool:
        return p.resolve().is_relative_to(root)

    for dirpath, dirnames, filenames in os.walk(root, followlinks=True, onerror=unreadable):
        here = Path(dirpath)
        rel_dir = here.relative_to(root)
        keep = []
        for d in sorted(dirnames):
            rel = (rel_dir / d).as_posix()
            if d.startswith("."):
                continue
            target = (here / d).resolve()
            if target in (here.resolve(), *here.resolve().parents):
                continue  # link back to a folder already being walked: nothing new to read
            if not inside(here / d):
                problems.append(("Link leaves the folder", rel))
            elif len(rel_dir.parts) + 1 > MAX_DEPTH:
                problems.append((f"Deeper than {MAX_DEPTH} folders", rel))
            else:
                keep.append(d)
        dirnames[:] = keep
        for name in sorted(filenames):
            p = here / name
            if name.startswith(".") or p.suffix.lower() != ".csv":
                continue
            rel = p.relative_to(root).as_posix()
            if not p.exists():
                problems.append(("Broken link", rel))
            elif not inside(p):
                problems.append(("Link leaves the folder", rel))
            else:
                paths.append(p)
    once: dict[Path, Path] = {}
    for p in paths:  # same file behind several links: keep the non-link path
        once[p.resolve()] = p if p == p.resolve() else once.get(p.resolve(), p)
    return [once.pop(p.resolve()) for p in paths if p.resolve() in once], problems


def plan_files(csv_files: list[Path], root: Path | None = None) -> dict:
    """Profile the given CSVs (in list order) and return a draft manifest (nothing written).

    With `root`, each signal's `file` is the path relative to it (files may live in subfolders).
    """
    paths = [Path(p) for p in csv_files]
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        raise FileNotFoundError("CSV file(s) not found:\n  " + "\n  ".join(missing))
    if not paths:
        raise FileNotFoundError("No .csv files to plan")
    profiles = [profile_csv(p) for p in paths]
    if root is not None:
        for prof, p in zip(profiles, paths):
            prof["name"] = p.relative_to(Path(root).resolve()).as_posix()
    empty = [p["name"] for p in profiles if not p["headers"]]
    if empty:
        raise ValueError(f"Empty or headerless CSV file(s): {', '.join(empty)}")
    return build_manifest(profiles)


def plan_directory(data_dir: Path) -> dict:
    """Profile every .csv under data_dir (subfolders included) and return a draft manifest (nothing written)."""
    csv_files, problems = find_csvs(data_dir)
    if problems:
        raise ValueError("; ".join(f"{why}: {rel}" for why, rel in problems))
    if not csv_files:
        raise FileNotFoundError(f"No .csv files found in {data_dir}")
    return plan_files(csv_files, root=Path(data_dir))
