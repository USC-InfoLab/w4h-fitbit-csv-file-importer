"""Integration test against a running w4h-api. Run: pytest -m integration -q

Needs W4H_API_KEY (and optionally W4H_API_BASE / W4H_DATASET_ID); skipped otherwise.
"""

import os

import pytest

from w4h_fitbit_csv_file_importer.client import W4HClient


@pytest.mark.integration
def test_import_subjects_batch():
    if not os.environ.get("W4H_API_KEY", "").strip():
        pytest.skip("W4H_API_KEY not set")
    dataset_id = os.environ.get("W4H_DATASET_ID", "").strip()
    if not dataset_id:
        pytest.skip("W4H_DATASET_ID not set")
    result = W4HClient().import_csv_batch(
        dataset_id,
        {
            "signal": "subjects",
            "mode": "append",
            "dedupe_columns": ["id"],
            "columns": [
                {"name": "id", "type": "text"},
                {"name": "start_date", "type": "date"},
                {"name": "end_date", "type": "date"},
            ],
            "rows": [{"id": "test-subj", "start_date": "2020-01-01", "end_date": "2020-01-02"}],
            "source_name": "Fitbit",
            "description": "integration test row",
        },
    )
    assert result.get("success") is True
