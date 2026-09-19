# AGENTS.md — w4h-fitbit-file-csv-importer

Importer module for **user-supplied Fitbit CSV files** (notebook + CLI + tests). No bundled production CSVs: files come from the user/Admin via `W4H_DATA_DIR`. For local dev/testing, reference sibling `../w4h-sample-icde-demo-csv/data` in `.env` — do not copy CSVs into this repo.

- API key via `W4H_API_KEY` in local `.env` only — never in git.
- Do not add direct Postgres / `to_sql` paths; use the W4H API (`POST /datasets/:id/import/csv-batch`).
- The module owns its mapping logic (`profile.py`, `mapping.py`, `reconcile.py`, `catalog.py`, `fitbit_shapes.py`). Do not call any W4H API route except `csv-batch`; the old in-app ingest assistant routes are gone.
- `manifest.yaml` in the data folder (`W4H_DATA_DIR`) is the source of file names and columns, produced by `plan` and **reviewed by a human** before `import`. `import` must never build a mapping itself.
- Every `csv-batch` payload sends `table_prefix: "fitbit"` (`config.TABLE_PREFIX`) — do not drop it; it keeps Fitbit tables from colliding with other vendors' in one dataset schema.
- Progress: keep printing `@@PROGRESS@@ {json}` lines (contribution-runner.js parses them).
- Tests: `pytest tests/ -q`. `tests/test_manifest_files.py` documents the module contract (read its docstring first); `-m integration` tests need a running w4h-api.
