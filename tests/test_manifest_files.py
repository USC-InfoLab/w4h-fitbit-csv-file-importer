"""Setup check for this module: does `manifest.yaml` match the CSV files on disk?

Run:  pytest tests/test_manifest_files.py -q

HOW A W4H IMPORTER MODULE IS PUT TOGETHER
-----------------------------------------
A module is a repo that turns CSV files plus a `manifest.yaml` (the reviewed
mapping) into W4H signals. This test is the smallest check that a module is wired up
correctly, and it is a template for new modules: copy it, and it should pass
against your own `manifest.yaml` without edits.

`manifest.yaml` contract (what these tests enforce)
    Top level    vendor, format, version, title, signals
    Each signal  slug            unique id, e.g. "heart_rate"
                 file            CSV path relative to the data root, e.g. "data/x.csv"
                 columns         list of {name, type}; must equal the CSV header row,
                                 in the same order
                 geomts_mapping  how rows become GeoMTS points:
                                   signal_type  matches the slug
                                   subject      a column name
                                   time         null, {combine: [col, col]} or {column: col}
                                   geo          absent/null, or {lat: col, lon: col}
                                   values       list of {source: col, name, type}
                                 Every column referenced here must exist in `columns`.

Where the manifest and CSV files live
    This test plans the bundled `tests/fixtures/` CSVs into a temp folder.
    In-app Run uses `config.HARDCODED_CSV_FILES` (sibling sample package).
    The notebook uses a file chooser.

To create a new module
    1. Put your CSVs in a folder and write (or generate) a `manifest.yaml` following the contract.
    2. Run this file against that folder's mapping (or copy the fixture pattern).
    3. Fix whatever it reports; each assertion message names the signal and column at fault.
"""

import csv
import shutil
from pathlib import Path

import pytest
import yaml

from w4h_fitbit_csv_file_importer.manifest import write_manifest
from w4h_fitbit_csv_file_importer.mapping import plan_directory

REPO_ROOT = Path(__file__).resolve().parent.parent
REQUIRED_TOP_LEVEL = ("vendor", "format", "version", "title", "signals")
REQUIRED_SIGNAL_KEYS = ("slug", "file", "columns", "geomts_mapping")


@pytest.fixture(scope="module")
def data_root(tmp_path_factory):
    """Plan the bundled test fixtures into a temp folder."""
    root = tmp_path_factory.mktemp("planned")
    for f in (REPO_ROOT / "tests" / "fixtures").glob("*.csv"):
        shutil.copy(f, root / f.name)
    write_manifest(root, plan_directory(root))
    return root


@pytest.fixture(scope="module")
def manifest(data_root):
    """The parsed manifest.yaml in the data root."""
    path = data_root / "manifest.yaml"
    assert path.is_file(), f"manifest.yaml not found at {path} — run `plan` and review it"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_manifest_has_required_top_level_keys(manifest):
    missing = [k for k in REQUIRED_TOP_LEVEL if k not in manifest]
    assert not missing, f"manifest.yaml is missing top-level keys: {missing}"
    assert manifest["signals"], "manifest.yaml declares no signals"


def test_signals_have_required_keys_and_unique_slugs(manifest):
    slugs = []
    for signal in manifest["signals"]:
        missing = [k for k in REQUIRED_SIGNAL_KEYS if k not in signal]
        assert not missing, f"signal {signal.get('slug')!r} is missing keys: {missing}"
        slugs.append(signal["slug"])
    assert len(slugs) == len(set(slugs)), f"duplicate signal slugs: {slugs}"


def test_geomts_mapping_references_declared_columns(manifest):
    """Every column named in a mapping (subject, time, geo, values) must exist in `columns`."""
    for signal in manifest["signals"]:
        slug = signal["slug"]
        declared = {c["name"] for c in signal["columns"]}
        mapping = signal["geomts_mapping"]
        assert mapping["signal_type"] == slug, f"{slug}: signal_type is {mapping['signal_type']!r}"

        referenced = [mapping["subject"]]
        if mapping.get("time"):
            referenced += mapping["time"].get("combine") or [mapping["time"]["column"]]
        if mapping.get("geo"):
            referenced += [mapping["geo"]["lat"], mapping["geo"]["lon"]]
        referenced += [v["source"] for v in mapping.get("values") or []]

        unknown = [c for c in referenced if c not in declared]
        assert not unknown, f"{slug}: geomts_mapping references undeclared columns {unknown}"


def test_csv_files_exist_and_headers_match_manifest(manifest, data_root):
    """Each signal's CSV exists and its header row equals the manifest's column names."""
    for signal in manifest["signals"]:
        slug = signal["slug"]
        path = data_root / signal["file"]
        assert path.is_file(), f"{slug}: CSV not found at {path}"
        with path.open(newline="", encoding="utf-8") as f:
            header = next(csv.reader(f), None)
        expected = [c["name"] for c in signal["columns"]]
        assert header == expected, f"{slug}: header {header} != manifest columns {expected}"
