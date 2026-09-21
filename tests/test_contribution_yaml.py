"""contribution.yaml test contract: fixtures + optional sibling W4H sample files."""

from pathlib import Path

from w4h_fitbit_csv_file_importer.contribution import (
    automated_sample_paths,
    live_sample_paths,
    load_contribution,
)
from w4h_fitbit_csv_file_importer.mapping import plan_files
from w4h_fitbit_csv_file_importer.reconcile import reconcile_manifest

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_contribution_yaml_has_required_keys():
    doc = load_contribution()
    assert doc["slug"] == "w4h-fitbit-csv-file-importer"
    assert doc["kind"] == "ingest"
    automated = doc["tests"]["automated"]
    live = doc["tests"]["live"]
    assert automated["sample"]["kind"] == "fixtures"
    assert live["sample"]["kind"] in {"sibling", "fixtures"}
    keys = {item["key"] for item in doc["inputs"]}
    assert "dataset_id" in keys


def test_automated_sample_is_tiny_in_repo_fixtures():
    paths = automated_sample_paths()
    assert paths
    assert all(p.is_file() and REPO_ROOT / "tests" / "fixtures" in p.parents for p in paths)


def test_live_sample_is_sibling_repo_or_fixture_fallback():
    source, paths = live_sample_paths()
    assert source in {"w4h-sample-fitbit-csv", "fixtures"}
    assert paths and all(p.is_file() for p in paths)
    if source == "w4h-sample-fitbit-csv":
        assert {p.name for p in paths} == {
            "fitbit_subjects.csv",
            "fitbit_heart_rate.csv",
            "fitbit_calories.csv",
            "fitbit_weight.csv",
        }


def test_live_sample_plans_without_mapping_errors():
    source, paths = live_sample_paths()
    manifest = plan_files(paths)
    review = reconcile_manifest(manifest)
    assert review["errors"] == []
    if source == "w4h-sample-fitbit-csv":
        assert {s["slug"] for s in manifest["signals"]} == {"subjects", "heart_rate", "calories", "weight"}
