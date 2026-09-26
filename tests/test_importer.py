"""Unit tests for profiling, mapping, reconciliation and chunked import — no network."""

import json
import os
import shutil
from pathlib import Path

import pytest

from w4h_fitbit_csv_file_importer.__main__ import main
from w4h_fitbit_csv_file_importer.csv_import import CHUNK_SIZE, import_all, import_signal
from w4h_fitbit_csv_file_importer.manifest import load_manifest, write_manifest
from w4h_fitbit_csv_file_importer.mapping import find_csvs, plan_directory, slug_from_filename
from w4h_fitbit_csv_file_importer.profile import infer_type, profile_csv
from w4h_fitbit_csv_file_importer.reconcile import reconcile_manifest

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
    assert slug_from_filename("fitbit_heart_rate.csv") == "heart_rate"
    assert slug_from_filename("fitbit_subjects.csv") == "subjects"


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
    from w4h_fitbit_csv_file_importer.manifest import write_manifest
    write_manifest(data_dir, manifest)
    assert main(["validate", "--data-dir", str(data_dir)]) == 1
    plan = json.loads((data_dir / "plan.json").read_text())
    assert any("nope" in e for e in plan["review"]["errors"])
    sig["geomts_mapping"]["subject"] = "id"
    write_manifest(data_dir, manifest)
    assert main(["validate", "--data-dir", str(data_dir)]) == 0


def _args():
    return type("A", (), {"data_dir": None})()


def _upload(monkeypatch, folder):
    from w4h_fitbit_csv_file_importer.__main__ import _resolve_sources

    monkeypatch.setenv("W4H_DATA_DIR", str(folder))
    return _resolve_sources(_args())


def test_data_dir_env_plans_in_memory(data_dir, monkeypatch):
    d, planned, sidecar = _upload(monkeypatch, data_dir)
    assert d == data_dir.resolve() and planned["signals"] and sidecar is False
    assert not (data_dir / "manifest.yaml").exists()


def test_no_source_aborts_instead_of_using_a_sample(monkeypatch):
    from w4h_fitbit_csv_file_importer.__main__ import _resolve_sources

    monkeypatch.delenv("W4H_DATA_DIR", raising=False)
    with pytest.raises(SystemExit, match="--data-dir or set W4H_DATA_DIR"):
        _resolve_sources(_args())


@pytest.mark.parametrize(
    "name, content, expected",
    [
        ("other.csv", "a,b\n1,2\n", "Not recognised as a Fitbit CSV export: other.csv"),
        ("Upper.CSV", "a,b\n1,2\n", "Not recognised as a Fitbit CSV export: Upper.CSV"),
        ("empty.csv", "", "Empty file: empty.csv"),
        ("header_only.csv", "Id,ActivityDay,Calories\n", "Empty file (no data rows): header_only.csv"),
        ("bin.csv", b"\xff\xfe\x00\x01", "Unreadable (UnicodeDecodeError): bin.csv"),
    ],
)
def test_upload_gate_names_each_bad_file(data_dir, monkeypatch, name, content, expected):
    (data_dir / name).write_bytes(content if isinstance(content, bytes) else content.encode())
    with pytest.raises(SystemExit) as exc:
        _upload(monkeypatch, data_dir)
    assert expected in str(exc.value)
    assert not any(f.name in str(exc.value) for f in FIXTURES.glob("*.csv"))  # valid files are not blamed


def test_upload_gate_reports_every_problem_at_once(data_dir, monkeypatch):
    (data_dir / "a.csv").write_text("a,b\n1,2\n")
    (data_dir / "b.csv").write_text("a,b\n1,2\n")
    (data_dir / "empty.csv").write_text("")
    with pytest.raises(SystemExit) as exc:
        _upload(monkeypatch, data_dir)
    assert str(exc.value) == "Not recognised as a Fitbit CSV export: a.csv, b.csv; Empty file: empty.csv"


def test_upload_gate_ignores_housekeeping_and_non_csv_files(data_dir, monkeypatch):
    """w4h-api stages .owner.json and .<name>.part beside the CSVs; a folder may hold a manifest."""
    for name in (".owner.json", ".half.csv.part", "manifest.yaml", "notes.txt"):
        (data_dir / name).write_text("x")
    _, planned, _ = _upload(monkeypatch, data_dir)
    assert planned["signals"]


@pytest.mark.parametrize("value", ["", "   ", "/no/such/folder"])
def test_data_dir_env_blank_or_missing_aborts(monkeypatch, value):
    with pytest.raises(SystemExit, match="not a folder"):
        _upload(monkeypatch, value)


def test_data_dir_env_folder_without_csvs_aborts(tmp_path, monkeypatch):
    with pytest.raises(SystemExit, match="No .csv files found"):
        _upload(monkeypatch, tmp_path)


def test_cli_data_dir_wins_over_env(data_dir, monkeypatch):
    from w4h_fitbit_csv_file_importer.__main__ import _resolve_sources

    monkeypatch.setenv("W4H_DATA_DIR", "/no/such/folder")
    d, planned, sidecar = _resolve_sources(type("A", (), {"data_dir": str(data_dir)})())
    assert d == data_dir.resolve() and planned is None and sidecar is True


@pytest.mark.parametrize(
    "headers, expected",
    [
        (["Id", "ActivityDay", "Calories"], True),  # known shape
        (["Id", "Calories"], True),  # trimmed export: Id + Fitbit-specific column
        (["id", "date", "timestamp", "value"], True),  # generic time series shape: ICDE demo files match it too
        (["Id", "Date", "Value"], False),  # no Fitbit-specific column
        (["Id", "Date", "Notes"], False),  # Id but nothing Fitbit-specific
        (["Calories", "Steps"], False),  # no Id
        (["a", "b"], False),
        ([], False),
    ],
)
def test_is_fitbit(headers, expected):
    from w4h_fitbit_csv_file_importer.fitbit_shapes import is_fitbit

    assert is_fitbit(headers) is expected


def _tree(root):
    """root/{daily.csv, sub/hr.csv, sub/deeper/daily.csv} using fixture content."""
    (root / "sub" / "deeper").mkdir(parents=True)
    shutil.copy(FIXTURES / "dailyActivity_merged.csv", root / "daily.csv")
    shutil.copy(FIXTURES / "heartrate_seconds_merged.csv", root / "sub" / "hr.csv")
    shutil.copy(FIXTURES / "dailyActivity_merged.csv", root / "sub" / "deeper" / "daily.csv")
    return root


def test_folder_with_subfolders_plans_and_imports_relative_files(tmp_path, monkeypatch):
    root = _tree(tmp_path / "mounted")
    deeper = root / "sub" / "deeper" / "daily.csv"
    deeper.write_text("".join(deeper.read_text().splitlines(keepends=True)[:2]))  # header + 1 row
    _, manifest, _ = _upload(monkeypatch, root)
    assert [s["file"] for s in manifest["signals"]] == ["daily.csv", "sub/hr.csv", "sub/deeper/daily.csv"]
    assert [s["slug"] for s in manifest["signals"]] == ["daily", "hr", "daily_2"]  # same name, two folders
    assert reconcile_manifest(manifest)["errors"] == []
    client = FakeClient()
    results = import_all(client, "ds", manifest, root)
    assert [r["signal"] for r in results] == ["daily", "hr", "daily_2"]
    rows = {r["signal"]: r["inserted"] for r in results}
    assert rows["daily_2"] == 1 and rows["daily"] > 1  # each signal read its own folder's file


def test_cli_plan_walks_subfolders_like_the_upload_path(tmp_path):
    root = _tree(tmp_path / "mounted")
    assert main(["plan", "--data-dir", str(root)]) == 0
    manifest = load_manifest(root)
    assert {s["file"] for s in manifest["signals"]} == {"daily.csv", "sub/deeper/daily.csv", "sub/hr.csv"}


def test_find_csvs_follows_links_inside_the_root_only(tmp_path):
    root = _tree(tmp_path / "mounted")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    shutil.copy(FIXTURES / "subjects.csv", outside / "leak.csv")
    (root / "inside_link.csv").symlink_to(root / "sub" / "hr.csv")
    (root / "linked_dir").symlink_to(root / "sub", target_is_directory=True)
    (root / "escape.csv").symlink_to(outside / "leak.csv")
    (root / "escape_dir").symlink_to(outside, target_is_directory=True)
    (root / "gone.csv").symlink_to(root / "missing.csv")
    paths, problems = find_csvs(root)
    rels = {p.relative_to(root).as_posix() for p in paths}
    assert "sub/hr.csv" in rels and not {"inside_link.csv", "linked_dir/hr.csv"} & rels  # one file, listed once
    assert not any("leak" in r or r.startswith("escape") for r in rels)
    assert sorted(problems) == [
        ("Broken link", "gone.csv"),
        ("Link leaves the folder", "escape.csv"),
        ("Link leaves the folder", "escape_dir"),
    ]


def test_find_csvs_stops_at_max_depth_and_symlink_loops(tmp_path):
    deep = tmp_path / "a" / "b" / "c" / "d" / "e" / "f"
    deep.mkdir(parents=True)
    shutil.copy(FIXTURES / "subjects.csv", deep / "too_deep.csv")
    (tmp_path / "a" / "loop").symlink_to(tmp_path / "a", target_is_directory=True)
    paths, problems = find_csvs(tmp_path)
    assert paths == []
    assert ("Deeper than 5 folders", "a/b/c/d/e/f") in problems


def test_upload_gate_reports_links_that_leave_the_folder(data_dir, tmp_path_factory, monkeypatch):
    outside = tmp_path_factory.mktemp("outside")
    (outside / "x.csv").write_text("Id,Calories\n1,2\n")
    (data_dir / "x.csv").symlink_to(outside / "x.csv")
    with pytest.raises(SystemExit, match="Link leaves the folder: x.csv"):
        _upload(monkeypatch, data_dir)


def test_import_refuses_manifest_files_outside_the_data_folder(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    (tmp_path / "secret.csv").write_text("Id\n1\n")
    with pytest.raises(ValueError, match="outside the data folder"):
        import_signal(FakeClient(), "ds", {"slug": "x", "file": "../secret.csv"}, root)


def test_bad_utf8_deep_in_a_file_aborts_before_any_post(data_dir):
    manifest = plan_directory(data_dir)
    last = manifest["signals"][-1]["file"]  # earlier signals are fine and must not be posted either
    assert len(manifest["signals"]) > 1
    bad = data_dir / last
    rows = b"1503960366,4/12/2016,5,1.5,1.5,1\n" * 400  # past the 8 KB read buffer and the 20-row preview
    bad.write_bytes(bad.read_bytes() + rows + b"1,4/12/2016,\xff\n")
    client = FakeClient()
    with pytest.raises(SystemExit, match=rf"Unreadable \(UnicodeDecodeError\): {last}"):
        import_all(client, "ds", manifest, data_dir)
    assert client.imports == []


def test_find_csvs_reads_exactly_five_folders_deep(tmp_path):
    ok = tmp_path / "a" / "b" / "c" / "d" / "e"
    ok.mkdir(parents=True)
    shutil.copy(FIXTURES / "subjects.csv", ok / "x.csv")
    too_deep = ok / "f"
    too_deep.mkdir()
    shutil.copy(FIXTURES / "subjects.csv", too_deep / "y.csv")
    paths, problems = find_csvs(tmp_path)
    assert [p.name for p in paths] == ["x.csv"]
    assert problems == [("Deeper than 5 folders", "a/b/c/d/e/f")]


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any folder")
def test_find_csvs_reports_unreadable_folders(tmp_path):
    (tmp_path / "ok.csv").write_text("Id,Calories\n1,2\n")
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "y.csv").write_text("Id,Calories\n1,2\n")
    locked.chmod(0)
    try:
        paths, problems = find_csvs(tmp_path)
    finally:
        locked.chmod(0o700)
    assert [p.name for p in paths] == ["ok.csv"]
    assert problems == [("Unreadable folder", "locked")]


def test_plan_directory_stops_on_links_that_leave_the_folder(data_dir, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (outside / "x.csv").write_text("Id,Calories\n1,2\n")
    (data_dir / "x.csv").symlink_to(outside / "x.csv")
    (data_dir / "gone.csv").symlink_to(data_dir / "missing.csv")
    with pytest.raises(ValueError, match="Broken link: gone.csv; Link leaves the folder: x.csv"):
        plan_directory(data_dir)
    with pytest.raises(SystemExit, match="Link leaves the folder: x.csv"):  # CLI: message, no traceback
        main(["plan", "--data-dir", str(data_dir)])


def test_self_link_does_not_block_planning_or_duplicate_files(tmp_path):
    root = _tree(tmp_path / "mounted")
    (root / "self").symlink_to(root, target_is_directory=True)
    paths, problems = find_csvs(root)
    assert problems == []
    assert sorted(p.relative_to(root).as_posix() for p in paths) == ["daily.csv", "sub/deeper/daily.csv", "sub/hr.csv"]


def test_file_behind_two_links_is_planned_once(tmp_path):
    root = _tree(tmp_path / "mounted")
    (root / "alias.csv").symlink_to(root / "sub" / "hr.csv")
    manifest = plan_directory(root)
    assert [s["file"] for s in manifest["signals"]].count("sub/hr.csv") == 1
    assert "alias.csv" not in {s["file"] for s in manifest["signals"]}


@pytest.mark.parametrize("bad", ["/etc/hostname", "../secret.csv", "sub/../../secret.csv"])
def test_import_refuses_manifest_files_outside_the_data_folder(tmp_path, monkeypatch, bad):
    root = tmp_path / "data"
    (root / "sub").mkdir(parents=True)
    (tmp_path / "secret.csv").write_text("Id\n1\n")
    manifest = plan_directory(FIXTURES)
    manifest["signals"] = manifest["signals"][:1]
    manifest["signals"][0]["file"] = bad
    client = FakeClient()
    with pytest.raises(ValueError, match="outside the data folder"):
        import_all(client, "ds", manifest, root)
    assert client.imports == []
    write_manifest(root, manifest)
    monkeypatch.setenv("W4H_API_KEY", "w4h_sk_test")
    with pytest.raises(SystemExit, match="outside the data folder"):  # CLI: message, no traceback
        main(["import", "--dataset-id", "ds", "--data-dir", str(root)])


def test_manifest_path_with_dotdot_that_stays_inside_is_fine(tmp_path):
    root = tmp_path / "data"
    (root / "sub").mkdir(parents=True)
    shutil.copy(FIXTURES / "dailyActivity_merged.csv", root / "daily.csv")
    manifest = plan_directory(root)
    manifest["signals"][0]["file"] = "sub/../daily.csv"
    assert import_all(FakeClient(), "ds", manifest, root)[0]["inserted"] > 0


def test_sync_file_override_may_point_outside_the_data_folder(tmp_path):
    """`sync --file` names a file explicitly; only the manifest's own paths are confined."""
    root = tmp_path / "data"
    root.mkdir()
    extra = tmp_path / "new_rows.csv"
    shutil.copy(FIXTURES / "dailyActivity_merged.csv", extra)
    manifest = plan_directory(FIXTURES)
    signal = next(s for s in manifest["signals"] if s["slug"] == "dailyactivity")
    assert import_signal(FakeClient(), "ds", signal, root, csv_path=extra)["inserted"] > 0
