# AGENTS.md — w4h-fitbit-csv-file-importer

Importer module for **user-supplied Fitbit CSV files** (notebook + CLI + tests). No bundled production CSVs. The notebook picks files with a chooser. In-app **Run** / `./run.sh` does **not** use the notebook — it calls the CLI and loads the live sample declared in `contribution.yaml` (sibling `w4h-sample-fitbit-csv`, falling back to `tests/fixtures/`). Do not copy production CSVs into this repo. The shared W4H architecture overview is at the end of this file.

## Where this repo fits in W4H

- **Layer:** contribution, kinds `notebook` + `cli`, catalog slug `w4h-fitbit-csv-file-importer`, **`runnable = true`**.
- **How it differs from `w4h-sample-fitbit-csv-importer`:** the sample importer loads one known package with a hand-written `manifest.yaml`. This repo handles **arbitrary Fitbit/Fitabase exports a researcher brings**: it profiles headers locally (no row values leave the machine, no AI key), drafts a GeoMTS mapping (`profile.py` → `mapping.py` → `reconcile.py`, six deterministic checks), has a human review `manifest.yaml`, and only then ingests.
- **Half-built upload path:** `w4h-api` already stages user files for this slug only (`UPLOAD_SLUGS` in `routes/contributions.js`, `lib/contribution-uploads.js`) and passes the folder to `run.sh` as `W4H_DATA_DIR`. This package does not read `W4H_DATA_DIR` yet (only `--data-dir`), and `w4h-app` has no upload UI, so in-app Run still uses the `contribution.yaml` live sample.
- **It is the template for new ingest modules.** `contribution.yaml` is the module contract (`tests.automated` / `tests.live` / `inputs`) that `w4h-api/lib/contribution-runner.js` reads to find the live sample sibling. `tests/test_manifest_files.py` documents the manifest/CSV contract; `w4h-docs/guide/contribute-a-module.md` points authors here.
- **Interop:** it sends the same `table_prefix: "fitbit"` as the sample importer, so a dataset loaded by either has the same `fitbit_*` tables and works with `w4h-sql-compute-mets` and the Analytics tab.

## Rules

- API key via `W4H_API_KEY` in local `.env` only — never in git.
- Do not add direct Postgres / `to_sql` paths; use the W4H API (`POST /datasets/:id/import/csv-batch`).
- The module owns its mapping logic (`profile.py`, `mapping.py`, `reconcile.py`, `catalog.py`, `fitbit_shapes.py`). Do not call any W4H API route except `csv-batch` and `GET /datasets` (notebook picker).
- In-app Run plans the yaml live sample in memory. `--data-dir` is CLI-only for a local folder with a reviewed `manifest.yaml`.
- Every `csv-batch` payload sends `table_prefix: "fitbit"` (`config.TABLE_PREFIX`) — do not drop it.
- Progress: keep printing `@@PROGRESS@@ {json}` lines (contribution-runner.js parses them).
- Tests: `pytest tests/ -q`. `contribution.yaml` is the test contract; `tests/test_manifest_files.py` documents the mapping/CSV check (read its docstring first); `-m integration` tests need a running w4h-api.

<!-- BEGIN w4h-system-overview: identical in every W4H repo's AGENTS.md. Edit all copies together. -->

## W4H system overview (shared across all repos)

**W4H (Wearables for Health) Toolkit** loads wearable-device data into PostgreSQL, organizes it by team, project and dataset, controls access, and runs curated analyses on it. Each signal is a **GeoMTS** (Geospatial Multivariate Time Series) table whose roles (`subject`, `time`, optional `geo`, `values[]`) are stored in `w4h.tables.mapping_json`, not in fixed column names. Three repos form the platform, one packages it, and the rest are **contributions** listed in the in-app catalog (`w4h.contributions`).

| Repo | Role |
|---|---|
| `w4h-api` | Express API and Postgres DDL (`w4h` schema): auth, ACL, ingest, catalog, contribution runner, SQL engine. Port 2026 |
| `w4h-app` | Vue 3 + Vite SPA; talks only to `w4h-api`. Port 5173 |
| `w4h-docs` | Product rules, MVP, ADRs and guides; imported by the API as in-app Help. Owns product decisions |
| `w4h-docker` | Compose stack (`api`, `app`, `notebooks`) built from sibling repos; Postgres is external |
| `w4h-sample-fitbit-csv`, `w4h-sample-icde-demo-csv` | Synthetic sample CSVs plus `manifest.yaml` (ICDE includes a `gps_track` geo signal) |
| `w4h-sample-fitbit-csv-importer`, `w4h-sample-icde-demo-csv-importer` | Runnable importers (notebook, CLI, `run.sh`) for those samples |
| `w4h-fitbit-csv-file-importer` | Runnable importer for user-supplied Fitbit CSVs: profile headers, review a drafted mapping, ingest |
| `w4h-sql-compute-mets` | SQL contribution (YAML + SQL template) that `w4h-api` executes in-process |
| `fft_approximate` | Postgres C extension, catalog slug `fft-approximate`; no API involvement |
| `w4h-demo-approximate-queries` | Notebook comparing `fft_approximate` with exact averages over direct Postgres |

**Main flows:**

1. **Ingest:** importers post 500-row chunks to `POST /datasets/:id/import/csv-batch`. `lib/ingest-csv.js` creates `ds_<dataset_id>.<table_prefix>_<signal>` and upserts its `w4h.tables` mapping.
2. **In-app Run (ADR-022):** `POST /contributions/:slug/run` makes `lib/contribution-runner.js` spawn `../<slug>/run.sh` with the user's `W4H_API_KEY`, `W4H_API_BASE` and `W4H_DATASET_ID`. Stdout lines `@@PROGRESS@@ {json}` drive the progress bar.
3. **SQL analytics (ADR-023):** `lib/sql-contribution-engine.js` reads `../<slug>/manifest.yaml` and `sql/`, binds identifiers from `w4h.tables`, and runs in-process. There is no free-SQL endpoint.
4. **Extensions:** the operator installs `fft_approximate` on their Postgres; notebooks call it directly.

**Layout:** clone every repo as a sibling in one folder. The API finds contributions at `../<slug>` (override `CONTRIBUTION_RUNNER_REPO_ROOT`) and docs at `DOCS_REPO_PATH=../w4h-docs`.

**Cross-repo changes:** `w4h-api` first (regenerate `API_INDEX.md`), then `w4h-app`, then `w4h-docs`. Catalog rows are seeded in `w4h-api/data/schema.sql`. Start at `w4h-docs/dev/mvp.md` and `w4h-docs/dev/ADR-README.md` for decisions, and `w4h-docs/dev/developer-setup.md` for local setup, getting an API key, test personas, troubleshooting, per-repo test commands, default branches and a glossary. Do not commit or push unless asked; never commit `.env` files, API keys or participant data.

<!-- END w4h-system-overview -->
