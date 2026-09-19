"""Unit tests for profiling, mapping, reconciliation and chunked import — no network."""

import json
import shutil
from pathlib import Path

import pytest

from w4h_fitbit_file_csv_importer.__main__ import main
from w4h_fitbit_file_csv_importer.csv_import import CHUNK_SIZE, import_all, import_signal
from w4h_fitbit_file_csv_importer.manifest import load_manifest
from w4h_fitbit_file_csv_importer.mapping import plan_directory, slug_from_filename
from w4h_fitbit_file_csv_importer.profile import infer_type, profile_csv
from w4h_fitbit_file_csv_importer.reconcile import reconcile_manifest

FIXTURES = Path(__file__).parent / "fixtures"


class FakeClient:
    """Stub W4HClient: records import payloads, returns canned API responses."""

    def __init__(self):
        self.imports = []

    def import_csv_batch(self, dataset_id, payload):
        self.imports.append((dataset_id, payload))
        n = len(payload["rows"])
        return {"inserted": n, "skipped": 0, "physical_schema": "ds_t", "physical_table": payload["signal"]}


@pytest.fixture
def data_dir(tmp_path):
    for f in FIXTURES.glob("*.csv"):
        shutil.copy(f, tmp_path / f.name)
    return tmp_path


def _signal(manifest, slug):
    return next(s for s in manifest["signals"] if s["slug"] == slug)


def test_infer_type():
    assert infer_type(["1", "2"]) == "integer"
    assert infer_type(["1", "2.5"]) == "double precision"
    assert infer_type(["2022-01-01"]) == "date"
    assert infer_type(["4/12/2016"]) == "date"  # US date (Fitabase)
    assert infer_type(["2022-01-01 10:00:00"]) == "timestamp"
    assert infer_type(["4/12/2016 7:21:00 AM"]) == "timestamp"  # US datetime (Fitabase)
    assert infer_type(["1503960366", "8877689391"]) == "bigint"  # Fitbit user id overflows int4
    assert infer_type(["abc", "1"]) == "text"
    assert infer_type(["", " "]) == "text"
    assert infer_type(["True", "False"]) == "boolean"


def test_profile_detects_delimiter_and_strips_bom(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("﻿id;date;value\na;2022-01-01;3\n", encoding="utf-8")
    profile = profile_csv(p)
    assert profile["delimiter"] == ";"
    assert profile["headers"] == ["id", "date", "value"]
    assert profile["inferred_types"] == ["text", "date", "integer"]


def test_slug_drops_fitabase_suffixes():
    assert slug_from_filename("heartrate_seconds_merged.csv") == "heartrate_seconds"
    assert slug_from_filename("minuteCaloriesNarrow_merged.csv") == "minutecalories"
    assert slug_from_filename("dailyActivity_merged.csv") == "dailyactivity"


def test_plan_maps_fitabase_daily_activity(data_dir):
    manifest = plan_directory(data_dir)
    sig = _signal(manifest, "dailyactivity")
    m = sig["geomts_mapping"]
    assert m["subject"] == "Id"
    assert m["time"] == {"column": "ActivityDate"}
    assert [v["source"] for v in m["values"]] == ["TotalSteps", "TotalDistance", "Calories"]
    assert sig["dedupe_columns"] == ["Id", "ActivityDate"]
    assert {c["name"]: c["type"] for c in sig["columns"]}["Id"] == "text"  # subject forced to text


def test_plan_maps_each_shape(data_dir):
    manifest = plan_directory(data_dir)
    hr = _signal(manifest, "heartrate_seconds")["geomts_mapping"]
    assert hr["time"] == {"column": "Time"} and hr["values"][0]["source"] == "Value"
    subjects = _signal(manifest, "subjects")["geomts_mapping"]
    assert subjects["time"] is None and subjects["values"] == []
    gps = _signal(manifest, "gps_track")
    assert gps["geomts_mapping"]["geo"] == {"lat": "latitude", "lon": "longitude"}
    assert gps["geomts_mapping"]["time"] == {"combine": ["date", "timestamp"]}
    assert gps["dedupe_columns"] == ["id", "date", "timestamp"]
    assert {c["name"]: c["type"] for c in gps["columns"]}["timestamp"] == "text"  # bare time-of-day


def test_plan_output_needs_no_corrections(data_dir):
    manifest = plan_directory(data_dir)
    review = reconcile_manifest(manifest)
    assert review["errors"] == [] and review["corrections"] == []


def test_reconcile_corrects_time_and_dedupe_and_reports_diff():
    manifest = {
        "vendor": "fitbit",
        "signals": [{
            "slug": "hr", "file": "hr.csv",
            "columns": [{"name": "id", "type": "text"}, {"name": "date", "type": "date"},
                        {"name": "time", "type": "timestamp"}, {"name": "value", "type": "integer"}],
            "geomts_mapping": {"subject": "id", "time": {"column": "date"}, "values": []},
            "dedupe_columns": ["id", "time"],
        }],
    }
    review = reconcile_manifest(manifest)
    fields = {c["field"] for c in review["corrections"]}
    assert {"columns[time].type", "geomts_mapping.time", "dedupe_columns"} <= fields
    sig = manifest["signals"][0]
    assert sig["geomts_mapping"]["time"] == {"combine": ["date", "time"]}
    assert sig["dedupe_columns"] == ["id", "time", "date"]
    assert review["errors"] == []


def test_reconcile_blocks_dangling_refs_and_bad_types():
    manifest = {
        "vendor": "fitbit",
        "signals": [{
            "slug": "x", "file": "x.csv",
            "columns": [{"name": "id", "type": "uuid"}],
            "geomts_mapping": {"subject": "nope", "time": None, "values": []},
            "dedupe_columns": ["ghost"],
        }],
    }
    errors = " | ".join(reconcile_manifest(manifest)["errors"])
    assert "unrecognized type" in errors and "subject" in errors and "ghost" in errors


def test_reconcile_requires_a_subject():
    manifest = {"vendor": "fitbit", "signals": [{"slug": "x", "file": "x.csv",
                "columns": [{"name": "a", "type": "text"}],
                "geomts_mapping": {"subject": None, "time": None, "values": []}}]}
    assert any("subject is required" in e for e in reconcile_manifest(manifest)["errors"])


def test_plan_command_writes_manifest_and_plan_json(data_dir):
    assert main(["plan", "--data-dir", str(data_dir)]) == 0
    assert load_manifest(data_dir)["vendor"] == "fitbit"
    plan = json.loads((data_dir / "plan.json").read_text())
    assert plan["review"]["errors"] == [] and len(plan["manifest"]["signals"]) == 5


def test_plan_rejects_empty_and_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        plan_directory(tmp_path)
    (tmp_path / "empty.csv").write_text("")
    with pytest.raises(ValueError, match="empty.csv"):
        plan_directory(tmp_path)


def test_import_requires_reviewed_manifest(data_dir):
    with pytest.raises(FileNotFoundError, match="run `plan` first"):
        load_manifest(data_dir)


def test_import_chunks_prefix_and_first_chunk_replace(tmp_path):
    n = CHUNK_SIZE * 2 + 1
    (tmp_path / "hr.csv").write_text("id,date,timestamp,value\n" + "\n".join(f"s,2022-01-01,00:00:{i % 60:02d},{i}" for i in range(n)) + "\n")
    client = FakeClient()
    signal = {"slug": "hr", "file": "hr.csv", "columns": [], "dedupe_columns": ["id"], "sampling_interval": "1min",
              "geomts_mapping": {"subject": "id"}}
    result = import_signal(client, "ds", signal, tmp_path, mode="replace")
    assert [p["mode"] for _, p in client.imports] == ["replace", "append", "append"]
    assert all(p["table_prefix"] == "fitbit" for _, p in client.imports)
    assert client.imports[0][1]["mapping"]["sampling_interval"] == "1min"
    assert result["inserted"] == n


def test_import_uses_manifest_delimiter_and_progress_markers(tmp_path, capsys):
    (tmp_path / "a.csv").write_text("id;date;value\nx;2022-01-01;3\n")
    signal = {"slug": "a", "file": "a.csv", "delimiter": ";", "columns": [], "geomts_mapping": {}}
    client = FakeClient()
    import_all(client, "ds", {"signals": [signal]}, tmp_path)
    assert client.imports[0][1]["rows"] == [{"id": "x", "date": "2022-01-01", "value": "3"}]
    out = capsys.readouterr().out
    line = next(l for l in out.splitlines() if l.startswith("@@PROGRESS@@ "))
    progress = json.loads(line.split(" ", 1)[1])
    assert progress["signal"] == "a" and progress["signal_index"] == 1 and progress["rows_total"] == 1


def test_import_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        import_signal(FakeClient(), "ds", {"slug": "x", "file": "x.csv"}, tmp_path)


def test_validate_command_applies_corrections_and_reports_errors(data_dir, capsys):
    assert main(["plan", "--data-dir", str(data_dir)]) == 0
    manifest = load_manifest(data_dir)
    sig = _signal(manifest, "subjects")
    sig["geomts_mapping"]["subject"] = "nope"  # a bad hand edit
    from w4h_fitbit_file_csv_importer.manifest import write_manifest
    write_manifest(data_dir, manifest)
    assert main(["validate", "--data-dir", str(data_dir)]) == 1
    plan = json.loads((data_dir / "plan.json").read_text())
    assert any("nope" in e for e in plan["review"]["errors"])
    sig["geomts_mapping"]["subject"] = "id"
    write_manifest(data_dir, manifest)
    assert main(["validate", "--data-dir", str(data_dir)]) == 0
