# W4H Fitbit File CSV Importer

Notebook + CLI to import **Fitbit CSV files you supply** into W4H. Pick your own files (or point the CLI at a folder); the importer builds a GeoMTS mapping from their headers, lets you review it, and ingests them through the W4H API. No Fitbit API access needed. Credentials stay in a local `.env` (never committed).

**Publisher:** usc-infolab · **Kinds:** notebook, CLI · **Language:** Python

## Who should do what

| Role | What to do |
|------|------------|
| **Admin** | Ingest your CSVs into **your team's** catalog. Use the CLI (`import` / `sync`) for cron and incremental updates. |
| **User** | Use analysis contributions against loaded datasets. You cannot add datasets or edit raw tables. |
| **Super admin** | May seed/replace canonical **W4H Samples** datasets. Everyone else treats sandbox as read. |

## How it works

1. **Files** — one CSV per signal, with a header row, UTF-8, in one folder (`W4H_DATA_DIR`). In the notebook you choose them with a file selector; in the app the Admin uploads them.
2. **Plan (mapping)** — `plan` profiles each CSV locally (delimiter, headers and inferred column types incl. US dates and bigint ids — **never row values sent anywhere**), builds a GeoMTS mapping in this package (no API call, no AI key), runs the six deterministic checks, and writes `manifest.yaml` + `plan.json` next to the CSVs. **A human reviews and can edit the mapping before anything is imported.**
3. **Import** — `import` refuses to run without the reviewed `manifest.yaml`, then streams rows in 500-row chunks to `POST /datasets/:id/import/csv-batch` with `table_prefix: "fitbit"`. Rows already loaded are skipped using the manifest's `dedupe_columns`. Progress is reported through `@@PROGRESS@@` lines for the in-app progress bar.

`manifest.yaml` is the source of file names and columns; there are no hard-coded file names. Its contract is documented in [`tests/test_manifest_files.py`](tests/test_manifest_files.py).

## Prerequisites

- Running **w4h-api** and a personal API key (Profile → API keys)
- A dataset you can ingest into (create it in the Admin UI first)
- Python 3.10+

## Dev testing with sibling sample data

This repo holds **code only** — no production CSVs. For local end-to-end testing, clone the ICDE sample data package **next to** this repo and point `W4H_DATA_DIR` at its `data/` folder (same sibling pattern as [w4h-sample-icde-demo-csv-importer](https://github.com/USC-InfoLab/w4h-sample-icde-demo-csv-importer)):

```
W4H/
  w4h-sample-icde-demo-csv/
  w4h-fitbit-csv-file-importer/
```

```bash
cp .env.example .env
# In .env:
#   W4H_DATA_DIR=../w4h-sample-icde-demo-csv/data
#   W4H_API_KEY=w4h_sk_...
#   W4H_DATASET_ID=my-fitbit-file-test   # empty throwaway dataset

./run.sh plan      # writes manifest.yaml next to the CSVs — review it
./run.sh import
```

Use a **throwaway dataset** for this: the importer always sends `table_prefix: "fitbit"`, so ICDE-shaped files exercise mapping and chunk import but land in `fitbit_*` tables, not `icde_demo_*`.

`plan` writes `manifest.yaml` and `plan.json` **into** `W4H_DATA_DIR`. To avoid touching the canonical sample package, copy its `data/` folder to a working directory (e.g. `/tmp/icde-dev-data/`) and point `W4H_DATA_DIR` there instead.

Unit tests keep using bundled `tests/fixtures/` (small, offline). To run the manifest contract against the sibling folder instead:

```bash
export W4H_DATA_DIR=../w4h-sample-icde-demo-csv/data
./run.sh plan   # once, if manifest.yaml is not there yet
pytest tests/test_manifest_files.py -q
```

## Credentials

```bash
cp .env.example .env
# Edit .env — set W4H_API_KEY, W4H_DATASET_ID and W4H_DATA_DIR
```

Never commit `.env` or paste keys into notebook outputs.

## Install

```bash
pip install -e ".[dev,notebook]"
```

## Notebook (primary)

Open [`notebook/import_fitbit_file_csv.ipynb`](notebook/import_fitbit_file_csv.ipynb) and run the cells in order: **pick files → review mapping → import**. The import cell offers `append` (safe to re-run) or `replace` (truncates each signal's table first — do not use on shared datasets).

## CLI (admins)

```bash
w4h-fitbit-file-csv-import plan --data-dir /path/to/csvs      # draft mapping -> review manifest.yaml
export W4H_API_KEY=w4h_sk_...   # or use .env
w4h-fitbit-file-csv-import import --dataset-id my-fitbit-data --data-dir /path/to/csvs --mode append
```

`--data-dir` defaults to `W4H_DATA_DIR`. `--mode replace` truncates each signal's table on its first batch.

## One-command run (`run.sh`)

```bash
./run.sh plan            # then review manifest.yaml
./run.sh import          # or: ./run.sh sync --signal heart_rate --file ...
```

Bootstraps a local `.venv`, installs this package, and runs the CLI. If `W4H_API_KEY` isn't already set in your environment, it prompts for it (and the API base URL) and offers to save both to `.env`. Set `W4H_API_KEY`/`W4H_API_BASE`/`W4H_DATASET_ID`/`W4H_DATA_DIR` beforehand to run non-interactively — this is the same entrypoint the in-app "Run" trigger uses.

## Incremental sync (cron)

Append a new CSV for one signal (slug from `manifest.yaml`); rows already loaded are skipped:

```bash
w4h-fitbit-file-csv-import sync --dataset-id my-fitbit-data --signal heart_rate --file /path/to/new_heart_rate.csv
```

```cron
0 2 * * * cd /path/to/w4h-fitbit-file-csv-importer && ./run.sh sync --dataset-id my-fitbit-data --signal heart_rate --file /data/fitbit_heart_rate_delta.csv >> /var/log/w4h-fitbit-sync.log 2>&1
```

## Tests

```bash
pytest tests/ -q                            # unit tests + module contract check (no network)
pytest tests/test_manifest_files.py -q      # just the manifest/CSV contract check
```

- [`tests/test_importer.py`](tests/test_importer.py) — profiling, mapping (Fitabase-style US dates, bigint ids, geo, subjects), the six reconcile checks, and chunked import against a fake client. Fixtures in `tests/fixtures/`.
- [`tests/test_manifest_files.py`](tests/test_manifest_files.py) — verifies a `manifest.yaml` (in `W4H_DATA_DIR`, else one planned from the fixtures) and that every CSV it lists exists with a matching header. Its docstring documents the module contract and how to create a new module; copy it as a template.
- Optional API test, needs a running w4h-api:

```bash
export W4H_API_KEY=... W4H_DATASET_ID=my-fitbit-data
pytest tests/test_import_api.py -m integration -q
```

## API

Uses only `POST /datasets/:id/import/csv-batch` (no direct database access, no other endpoints). Every payload carries `table_prefix: "fitbit"` so Fitbit tables never collide with other vendors' tables that share a signal slug (e.g. `heart_rate`) in the same dataset schema — see [ADR-016](https://github.com/USC-InfoLab/w4h-docs/blob/main/dev/ADR-016-paired-sample-importer-repos.md).
