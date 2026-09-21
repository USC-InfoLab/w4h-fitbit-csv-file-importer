# AGENTS.md — w4h-fitbit-csv-file-importer

Importer module for **user-supplied Fitbit CSV files** (notebook + CLI + tests). No bundled production CSVs. The notebook picks files with a chooser. In-app **Run** / `./run.sh` does **not** use the notebook — it calls the CLI and loads the sibling `../w4h-sample-fitbit-csv` files listed in `config.HARDCODED_CSV_FILES`. Do not copy those CSVs into this repo.

- API key via `W4H_API_KEY` in local `.env` only — never in git.
- Do not add direct Postgres / `to_sql` paths; use the W4H API (`POST /datasets/:id/import/csv-batch`).
- The module owns its mapping logic (`profile.py`, `mapping.py`, `reconcile.py`, `catalog.py`, `fitbit_shapes.py`). Do not call any W4H API route except `csv-batch` and `GET /datasets` (notebook picker).
- In-app Run plans the hardcoded sibling files in memory. `--data-dir` is CLI-only for a local folder with a reviewed `manifest.yaml`.
- Every `csv-batch` payload sends `table_prefix: "fitbit"` (`config.TABLE_PREFIX`) — do not drop it.
- Progress: keep printing `@@PROGRESS@@ {json}` lines (contribution-runner.js parses them).
- Tests: `pytest tests/ -q`. `tests/test_manifest_files.py` documents the module contract (read its docstring first); `-m integration` tests need a running w4h-api.
