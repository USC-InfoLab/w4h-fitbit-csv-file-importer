"""contribution.yaml test contract: required keys + in-repo fixtures."""

from pathlib import Path

from w4h_fitbit_csv_file_importer.contribution import (
    automated_sample_paths,
    load_contribution,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_contribution_yaml_has_required_keys():
    doc = load_contribution()
    assert doc["slug"] == "w4h-fitbit-csv-file-importer"
    assert doc["kind"] == "ingest"
    automated = doc["tests"]["automated"]
    assert automated["sample"]["kind"] == "fixtures"
    assert "live" not in doc["tests"]  # the bundled sample run is gone; files come from the Admin
    keys = {item["key"] for item in doc["inputs"]}
    assert "dataset_id" in keys


def test_automated_sample_is_tiny_in_repo_fixtures():
    paths = automated_sample_paths()
    assert paths
    assert all(p.is_file() and REPO_ROOT / "tests" / "fixtures" in p.parents for p in paths)
