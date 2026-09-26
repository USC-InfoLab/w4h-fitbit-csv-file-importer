# AGENTS.md — w4h-fitbit-csv-file-importer

Importer module for **user-supplied Fitbit CSV files** (notebook + CLI + tests). No bundled production CSVs. The notebook picks files with a chooser. In-app **Run** / `./run.sh` does **not** use the notebook — it calls the CLI on the Admin's files (`W4H_DATA_DIR` upload or `--data-dir` folder). There is no bundled sample run. Do not copy production CSVs into this repo.

- API key via `W4H_API_KEY` in local `.env` only — never in git.
- Do not add direct Postgres / `to_sql` paths; use the W4H API (`POST /datasets/:id/import/csv-batch`).
- The module owns its mapping logic (`profile.py`, `mapping.py`, `reconcile.py`, `catalog.py`, `fitbit_shapes.py`). Do not call any W4H API route except `csv-batch` and `GET /datasets` (notebook picker).
- In-app Run plans the admin's uploaded files (`W4H_DATA_DIR`) in memory. `--data-dir` is a local or mounted folder with a reviewed `manifest.yaml`. Both discover CSVs through `mapping.find_csvs` (subfolders; symlinks only inside the folder). Manifest `file` is relative to that folder and import refuses paths outside it; `sync --file` may name any file.
- Every `csv-batch` payload sends `table_prefix: "fitbit"` (`config.TABLE_PREFIX`) — do not drop it.
- Progress: keep printing `@@PROGRESS@@ {json}` lines (contribution-runner.js parses them).
- Tests: `pytest tests/ -q -m "not integration and not kaggle"`. `contribution.yaml` is the test contract; `tests/test_manifest_files.py` documents the mapping/CSV check (read its docstring first); `-m integration` tests need a running w4h-api; `-m kaggle` needs Kaggle credentials.
