"""Live Kaggle integration test: proves the mapping/profiling logic holds up
against the real, unmodified Fitabase export (arashnic/fitbit on Kaggle), not
just the curated `tests/fixtures/`.

Needs Kaggle API credentials (~/.kaggle/kaggle.json, or KAGGLE_USERNAME/KAGGLE_KEY
env vars) — see README "Tests" for setup. Fails loudly if credentials
are missing rather than skipping: this test is meant to be run deliberately with
credentials in hand, not silently no-op.

Run:  pytest tests/test_kaggle_fitbit.py -m kaggle -q
"""

import shutil
from pathlib import Path

import pytest

from w4h_fitbit_csv_file_importer.__main__ import _plan_upload
from w4h_fitbit_csv_file_importer.manifest import write_manifest
from w4h_fitbit_csv_file_importer.mapping import plan_directory
from w4h_fitbit_csv_file_importer.reconcile import reconcile_manifest

KAGGLE_DATASET = "arashnic/fitbit"
# The zip contains two dated Fitabase export folders; this targets the newer one.
PREFERRED_FOLDER_HINT = "4.12.16-5.12.16"
MARKER_FILE = "dailyActivity_merged.csv"
MIN_CSVS = 18  # the newer export folder holds 18 files; fewer means a partial download


def _find_export_dir(root: Path) -> Path:
    """Kaggle's zip nests CSVs one folder down (per date-range export), not flat."""
    candidates = sorted(p.parent for p in root.rglob(MARKER_FILE))
    preferred = [c for c in candidates if PREFERRED_FOLDER_HINT in c.name]
    if not preferred:
        pytest.fail(f"No {PREFERRED_FOLDER_HINT!r} export folder under {root}; found: {[str(c) for c in candidates]}")
    return preferred[0]


def _complete(root: Path) -> bool:
    return any(len(list(d.glob("*.csv"))) >= MIN_CSVS for d in root.rglob("*") if d.is_dir() and PREFERRED_FOLDER_HINT in d.name)


@pytest.fixture(scope="module")
def kaggle_export_dir(tmp_path_factory):
    try:
        import kaggle  # deferred: importing this authenticates against ~/.kaggle/kaggle.json
    except ModuleNotFoundError:
        pytest.fail('kaggle is not installed: pip install -e ".[kaggle]"')
    except OSError as e:
        pytest.fail(f"Kaggle credentials missing (~/.kaggle/kaggle.json or KAGGLE_USERNAME/KAGGLE_KEY): {e}")

    cache_dir = Path.home() / ".cache" / "w4h-fitbit-csv-file-importer" / "kaggle-fitbit"
    if not _complete(cache_dir):
        shutil.rmtree(cache_dir) if cache_dir.exists() else None  # a partial download must not stick
        staging = tmp_path_factory.mktemp("kaggle-download")
        kaggle.api.authenticate()
        kaggle.api.dataset_download_files(KAGGLE_DATASET, path=str(staging), unzip=True)
        assert _complete(staging), f"download from {KAGGLE_DATASET} is missing files"
        cache_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staging), str(cache_dir))
    return _find_export_dir(cache_dir)


@pytest.mark.kaggle
def test_kaggle_export_plans_and_reconciles_cleanly(kaggle_export_dir, tmp_path):
    manifest = plan_directory(kaggle_export_dir)
    assert manifest["signals"], "no signals profiled from the Kaggle export"

    result = reconcile_manifest(manifest)
    assert result["errors"] == [], f"reconcile errors against the real Kaggle export: {result['errors']}"

    slugs = {s["slug"] for s in manifest["signals"]}
    expected = {"dailyactivity", "heartrate_seconds", "weightloginfo"}
    missing = expected - slugs
    assert not missing, f"expected signals not picked up from the real export: {missing}"

    # Prove the manifest is actually writable/reviewable, same as the fixture-based check
    # (tests/test_manifest_files.py) — not just an in-memory dict.
    write_manifest(tmp_path, manifest)
    assert (tmp_path / "manifest.yaml").is_file()


@pytest.mark.kaggle
def test_kaggle_upload_gate_accepts_every_export_file(kaggle_export_dir):
    """The whole real export goes through the same gate as an in-app upload (SystemExit names any rejected file)."""
    folder, manifest, _ = _plan_upload(str(kaggle_export_dir))
    assert len(manifest["signals"]) >= MIN_CSVS
