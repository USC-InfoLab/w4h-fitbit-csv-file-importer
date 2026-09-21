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

1. **Files** — one CSV per signal, with a header row, UTF-8. The **notebook** has a file chooser. **In-app Run / `./run.sh` do not use the notebook** — they call the CLI and load the live sample in [`contribution.yaml`](contribution.yaml) (sibling `w4h-sample-fitbit-csv`, or `tests/fixtures/` if that repo is not checked out).
2. **Plan (mapping)** — `plan` profiles each CSV locally (delimiter, headers and inferred column types incl. US dates and bigint ids — **never row values sent anywhere**), builds a GeoMTS mapping in this package (no API call, no AI key), runs the six deterministic checks, and writes `manifest.yaml` + `plan.json` next to the CSVs. **A human reviews and can edit the mapping before anything is imported.**
3. **Import** — `import` refuses to run without the reviewed `manifest.yaml`, then streams rows in 500-row chunks to `POST /datasets/:id/import/csv-batch` with `table_prefix: "fitbit"`. Rows already loaded are skipped using the manifest's `dedupe_columns`. Progress is reported through `@@PROGRESS@@` lines for the in-app progress bar.

`manifest.yaml` is the source of file names and columns; there are no hard-coded file names. Its contract is documented in [`tests/test_manifest_files.py`](tests/test_manifest_files.py).

## Prerequisites

- Running **w4h-api** and a personal API key (Profile → API keys)
- A dataset you can ingest into (create it in the Admin UI first)
- Python 3.10+

## Dev testing with sibling sample data

This repo holds **code only** — no production CSVs. Clone the Fitbit sample data package **next to** this repo (same sibling pattern as [w4h-sample-fitbit-csv-importer](https://github.com/USC-InfoLab/w4h-sample-fitbit-csv-importer)):

```
W4H/
  w4h-sample-fitbit-csv/
  w4h-fitbit-csv-file-importer/
```

Live sample files (used by `./run.sh` / in-app Run — listed in `contribution.yaml`):

```
../w4h-sample-fitbit-csv/data/fitbit_subjects.csv
../w4h-sample-fitbit-csv/data/fitbit_heart_rate.csv
../w4h-sample-fitbit-csv/data/fitbit_calories.csv
../w4h-sample-fitbit-csv/data/fitbit_weight.csv
```

```bash
cp .env.example .env   # API key + dataset id only — not file paths
pytest tests/ -q -m "not integration"   # required automated tests (tiny fixtures)
./run.sh import        # same entry the in-app Run button uses
```

In-app Run injects `W4H_API_KEY` / `W4H_DATASET_ID`. It does not pass files yet; it loads the yaml live sample, plans those files in memory (does not write `manifest.yaml` into the sample package), and ingests them with `table_prefix: "fitbit"`, so tables should match a dataset loaded by **Fitbit CSV importer**. If the sibling sample repo is missing, it falls back to `tests/fixtures/`.

The notebook is the user-file path (chooser). `--data-dir` is CLI-only if you want a local folder.

Automated tests use bundled `tests/fixtures/` (small, offline). How to ship a new module: **w4h-docs** `guide/contribute-a-module.md`.

## Credentials

```bash
cp .env.example .env
# Edit .env — W4H_API_KEY only
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

`--data-dir` is optional (default: `contribution.yaml` live sample). `--mode replace` truncates each signal's table on its first batch.

## One-command run (`run.sh`)

```bash
./run.sh plan            # then review manifest.yaml
./run.sh import          # or: ./run.sh sync --signal heart_rate --file ...
```

Bootstraps a local `.venv`, installs this package, and runs the CLI. If `W4H_API_KEY` isn't already set in your environment, it prompts for it (and the API base URL) and offers to save both to `.env`. The in-app Run trigger sets `W4H_API_KEY`/`W4H_API_BASE`/`W4H_DATASET_ID` in the process environment (not via this repo's `.env`).

## Incremental sync (cron)

Append a new CSV for one signal (slug from `manifest.yaml`); rows already loaded are skipped:

```bash
w4h-fitbit-csv-file-import sync --dataset-id my-fitbit-data --signal heart_rate --file /path/to/new_heart_rate.csv
```

```cron
0 2 * * * cd /path/to/w4h-fitbit-csv-file-importer && ./run.sh sync --dataset-id my-fitbit-data --signal heart_rate --file /data/fitbit_heart_rate_delta.csv >> /var/log/w4h-fitbit-sync.log 2>&1
```

## Tests

```bash
pytest tests/ -q                            # unit tests + module contract check (no network)
pytest tests/test_manifest_files.py -q      # just the manifest/CSV contract check
```

- [`tests/test_contribution_yaml.py`](tests/test_contribution_yaml.py) — `contribution.yaml` has the required keys; automated sample is `tests/fixtures/`; live sample is the sibling Fitbit package or that fixture fallback.
- [`tests/test_importer.py`](tests/test_importer.py) — profiling, mapping (Fitabase-style US dates, bigint ids, geo, subjects), the six reconcile checks, and chunked import against a fake client. Fixtures in `tests/fixtures/`.
- [`tests/test_manifest_files.py`](tests/test_manifest_files.py) — verifies a `manifest.yaml` planned from `tests/fixtures/` and that every CSV it lists exists with a matching header. Its docstring documents the module contract; copy it as a template.
- Optional API test, needs a running w4h-api:

```bash
export W4H_API_KEY=... W4H_DATASET_ID=my-fitbit-data
pytest tests/test_import_api.py -m integration -q
```

## API

Uses only `POST /datasets/:id/import/csv-batch` (no direct database access, no other endpoints). Every payload carries `table_prefix: "fitbit"` so Fitbit tables never collide with other vendors' tables that share a signal slug (e.g. `heart_rate`) in the same dataset schema — see [ADR-016](https://github.com/USC-InfoLab/w4h-docs/blob/main/dev/ADR-016-paired-sample-importer-repos.md).
