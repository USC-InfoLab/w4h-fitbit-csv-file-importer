# W4H Fitbit CSV File Importer

Notebook + CLI to import **Fitbit CSV files you supply** into W4H. Pick your own files (or point the CLI at a folder); the importer builds a GeoMTS mapping from their headers, lets you review it, and ingests them through the W4H API. No Fitbit API access needed. Credentials stay in a local `.env` (never committed).

**Publisher:** usc-infolab · **Kinds:** notebook, CLI · **Language:** Python

## Who should do what

| Role | What to do |
|------|------------|
| **Admin** | Ingest your CSVs into **your team's** catalog. Use the CLI (`import` / `sync`) for cron and incremental updates. |
| **User** | Use analysis contributions against loaded datasets. You cannot add datasets or edit raw tables. |
| **Super admin** | May seed/replace canonical **W4H Samples** datasets. Everyone else treats sandbox as read. |

## How it works

1. **Files** — one CSV per signal, with a header row, UTF-8. Subfolders are read too (up to 5 levels; symlinks are followed only when they stay inside the folder). The **notebook** has a file chooser. **In-app Run / `./run.sh` do not use the notebook** — they call the CLI on the Admin's files: uploaded (`W4H_DATA_DIR`) or a folder (`--data-dir`, e.g. a mounted volume). There is no bundled sample run.
2. **Plan (mapping)** — `plan` profiles each CSV locally (delimiter, headers and inferred column types incl. US dates and bigint ids — **never row values sent anywhere**), builds a GeoMTS mapping in this package (no API call, no AI key), runs the six deterministic checks, and writes `manifest.yaml` + `plan.json` next to the CSVs. **A human reviews and can edit the mapping before anything is imported.**
3. **Import** — `import --data-dir` refuses to run without the reviewed `manifest.yaml` (in-app uploads are planned in memory), then streams rows in 500-row chunks to `POST /datasets/:id/import/csv-batch` with `table_prefix: "fitbit"`. Rows already loaded are skipped using the manifest's `dedupe_columns`. Progress is reported through `@@PROGRESS@@` lines for the in-app progress bar.

`manifest.yaml` is the source of file names and columns; there are no hard-coded file names. Its contract is documented in [`tests/test_manifest_files.py`](tests/test_manifest_files.py).

## Prerequisites

- Running **w4h-api** and a personal API key (Profile → API keys)
- A dataset you can ingest into (create it in the Admin UI first)
- Python 3.10+

## Dev testing

This repo holds **code only** — no production CSVs. Automated tests use the small bundled `tests/fixtures/` (offline).

```bash
cp .env.example .env   # API key and base URL only — not file paths
pytest tests/ -q -m "not integration and not kaggle"   # required automated tests (tiny fixtures)
./run.sh plan --data-dir /path/to/csvs                  # then review manifest.yaml
./run.sh import --dataset-id my-fitbit-data --data-dir /path/to/csvs
```

In-app Run injects `W4H_API_KEY` / `W4H_API_BASE` / `W4H_DATASET_ID`, plus `W4H_DATA_DIR` for the Admin's uploaded files. With neither `--data-dir` nor `W4H_DATA_DIR` the CLI stops and says so. `--data-dir` is the reviewed-manifest flow (`plan`, edit `manifest.yaml`, `import`); `W4H_DATA_DIR` plans in memory and writes no manifest. Rows go in with `table_prefix: "fitbit"`.

**Mount a folder.** `--data-dir` (or `W4H_DATA_DIR`) may be a mounted volume, e.g. `docker run -v /data/fitbit:/mnt/fitbit … --data-dir /mnt/fitbit`. Subfolders are read up to 5 levels deep; deeper folders, unreadable folders, and symlinks that leave the folder or point nowhere stop the run and are named. A symlink whose target stays inside the folder is followed; a file reachable through several links is read once.

**In-app upload.** When the Admin picks files in **Run import…**, the API stages them and sets `W4H_DATA_DIR`; the importer plans them in memory and imports. The gate checks each file and stops naming every problem file and why: unreadable or not UTF-8 (the first rows are checked at plan time, the whole file before anything is posted), empty, header only (no data rows), a link that leaves the folder or points nowhere, or not a Fitbit export (`fitbit_shapes.is_fitbit`: a known Fitbit shape, or an Id column plus a Fitbit column). Files that are not `.csv`, and dot-files, are ignored. Known limits: the gate reads headers only, so other datasets with the same generic layout (the ICDE demo files) pass, and Fitabase "Wide" per-minute files pass and import as one 60-column signal — use the Narrow file.

How to ship a new module: **w4h-docs** `guide/contribute-a-module.md`.

## Credentials

```bash
cp .env.example .env
# Edit .env — W4H_API_KEY (and W4H_API_BASE if the API is not on localhost:2026)
```

Never commit `.env` or paste keys into notebook outputs.

## Install

```bash
pip install -e ".[dev,notebook]"
```

## Notebook (primary)

Open [`notebook/import_fitbit_csv_file.ipynb`](notebook/import_fitbit_csv_file.ipynb) and run the cells in order: **pick dataset (from the API) → pick files → review mapping → import**. The import cell offers `append` (safe to re-run) or `replace` (truncates each signal's table first — do not use on shared datasets). In-app Run does not use the notebook: the Admin creates the dataset in the app and the runner passes that id into `run.sh`.

## CLI (admins)

```bash
w4h-fitbit-csv-file-import plan --data-dir /path/to/csvs      # draft mapping -> review manifest.yaml
export W4H_API_KEY=w4h_sk_...   # or use .env
w4h-fitbit-csv-file-import import --dataset-id my-fitbit-data --data-dir /path/to/csvs --mode append
```

`--data-dir` defaults to `W4H_DATA_DIR`. `--mode replace` truncates each signal's table on its first batch.

## One-command run (`run.sh`)

```bash
./run.sh plan --data-dir /path/to/csvs      # then review manifest.yaml
./run.sh import --dataset-id my-fitbit-data --data-dir /path/to/csvs   # or: ./run.sh sync --data-dir ... --signal heart_rate --file ...
```

Bootstraps a local `.venv`, installs this package, and runs the CLI. If `W4H_API_KEY` isn't set, `import` and `sync` prompt for it in a terminal (and for the API base URL if `W4H_API_BASE` isn't set) and offer to save both to `.env`; `plan` and `validate` need no key. The in-app Run trigger sets `W4H_API_KEY`/`W4H_API_BASE`/`W4H_DATASET_ID` (and `W4H_DATA_DIR` for uploads) in the process environment (not via this repo's `.env`).

## Incremental sync (cron)

Append a new CSV for one signal (slug from the reviewed `manifest.yaml` in `--data-dir`; the file may live anywhere); rows already loaded are skipped:

```bash
w4h-fitbit-csv-file-import sync --dataset-id my-fitbit-data --data-dir /path/to/csvs --signal heart_rate --file /path/to/new_heart_rate.csv
```

```cron
0 2 * * * cd /path/to/w4h-fitbit-csv-file-importer && ./run.sh sync --dataset-id my-fitbit-data --data-dir /data/fitbit --signal heart_rate --file /data/fitbit_heart_rate_delta.csv >> /var/log/w4h-fitbit-sync.log 2>&1
```

## Tests

```bash
pytest tests/ -q -m "not integration and not kaggle"   # unit tests + module contract check (no network)
pytest tests/test_manifest_files.py -q      # just the manifest/CSV contract check
```

- [`tests/test_contribution_yaml.py`](tests/test_contribution_yaml.py) — `contribution.yaml` has the required keys; the automated sample is `tests/fixtures/`.
- [`tests/test_importer.py`](tests/test_importer.py) — profiling, mapping (Fitabase-style US dates, bigint ids, geo, subjects), the six reconcile checks, and chunked import against a fake client. Fixtures in `tests/fixtures/`.
- [`tests/test_manifest_files.py`](tests/test_manifest_files.py) — verifies a `manifest.yaml` planned from `tests/fixtures/` and that every CSV it lists exists with a matching header. Its docstring documents the module contract; copy it as a template.
- [`tests/test_kaggle_fitbit.py`](tests/test_kaggle_fitbit.py) (`kaggle`) — plans + reconciles the real Kaggle `arashnic/fitbit` export; needs `~/.kaggle/kaggle.json` (or `KAGGLE_USERNAME`/`KAGGLE_KEY`) and `pip install -e ".[kaggle]"`. Run: `pytest tests/test_kaggle_fitbit.py -m kaggle -q`.
- Optional API test, needs a running w4h-api:

```bash
export W4H_API_KEY=... W4H_DATASET_ID=my-fitbit-data
pytest tests/test_import_api.py -m integration -q
```

## API

Uses `POST /datasets/:id/import/csv-batch` (plus `GET /datasets` for the notebook's dataset picker); no direct database access. Every payload carries `table_prefix: "fitbit"` so Fitbit tables never collide with other vendors' tables that share a signal slug (e.g. `heart_rate`) in the same dataset schema — see [ADR-016](https://github.com/USC-InfoLab/w4h-docs/blob/main/dev/ADR-016-paired-sample-importer-repos.md).
