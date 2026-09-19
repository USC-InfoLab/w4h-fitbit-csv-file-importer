"""CSV read + chunked API import (no full-file load)."""

import csv
import json
from pathlib import Path
from typing import Iterator

from .client import W4HClient
from .config import TABLE_PREFIX

CHUNK_SIZE = 500
SOURCE_NAME = "Fitbit"
# contribution-runner.js parses lines with this prefix into the run's structured
# `progress` column (drives the in-app progress bar) instead of the raw log.
PROGRESS_MARKER = "@@PROGRESS@@"


def iter_csv_rows(csv_path: Path, chunk_size: int = CHUNK_SIZE, delimiter: str = ",") -> Iterator[list[dict]]:
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f, delimiter=delimiter)
        headers = [h.strip() for h in next(reader, [])]
        chunk: list[dict] = []
        for cells in reader:
            if not cells:
                continue
            chunk.append({h: (cells[i] if i < len(cells) else "") for i, h in enumerate(headers)})
            if len(chunk) >= chunk_size:
                yield chunk
                chunk = []
        if chunk:
            yield chunk


def count_csv_rows(csv_path: Path) -> int:
    """Cheap upfront row count (one pass, no full-file load) for progress reporting."""
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        return max(sum(1 for line in f if line.strip()) - 1, 0)


def import_signal(
    client: W4HClient,
    dataset_id: str,
    signal: dict,
    data_dir: Path,
    mode: str = "append",
    csv_path: Path | None = None,
    signal_index: int = 1,
    signal_count: int = 1,
) -> dict:
    slug = signal["slug"]
    csv_path = (csv_path or Path(data_dir) / Path(signal["file"]).name).resolve()
    if not csv_path.is_file():
        raise FileNotFoundError(f"CSV missing for signal {slug!r}: {csv_path}")

    try:
        total_rows = count_csv_rows(csv_path)
    except (OSError, csv.Error, UnicodeDecodeError):
        total_rows = None  # progress is cosmetic; don't fail the import over it
    total_chunks = -(-total_rows // CHUNK_SIZE) if total_rows else None

    mapping = dict(signal.get("geomts_mapping") or {})
    if signal.get("sampling_interval"):
        mapping["sampling_interval"] = signal["sampling_interval"]

    total_inserted = total_skipped = rows_done = 0
    last_physical: dict = {}
    for chunk_index, chunk in enumerate(
        iter_csv_rows(csv_path, delimiter=signal.get("delimiter", ",")), start=1
    ):
        payload = {
            "signal": slug,
            "table_prefix": TABLE_PREFIX,
            # "replace" truncates, so only the very first chunk may carry it.
            "mode": mode if chunk_index == 1 else "append",
            "dedupe_columns": signal.get("dedupe_columns", []),
            "columns": signal.get("columns", []),
            "mapping": mapping,
            "description": signal.get("description", ""),
            "source_name": SOURCE_NAME,
            "source_url": signal.get("source_url"),
            "rows": chunk,
        }
        result = client.import_csv_batch(dataset_id, payload)
        total_inserted += int(result.get("inserted", 0))
        total_skipped += int(result.get("skipped", 0))
        last_physical = {
            "physical_schema": result.get("physical_schema"),
            "physical_table": result.get("physical_table"),
        }
        rows_done += len(chunk)
        of = f"/{total_chunks}" if total_chunks else ""
        rows_of = f"/{total_rows}" if total_rows else ""
        print(
            f"{slug}: chunk {chunk_index}{of} ({rows_done}{rows_of} rows, "
            f"inserted={total_inserted} skipped={total_skipped})",
            flush=True,
        )
        print(
            f"{PROGRESS_MARKER} "
            + json.dumps(
                {
                    "signal": slug,
                    "signal_index": signal_index,
                    "signal_count": signal_count,
                    "rows_done": rows_done,
                    "rows_total": total_rows,
                    "inserted": total_inserted,
                    "skipped": total_skipped,
                }
            ),
            flush=True,
        )

    return {"signal": slug, "inserted": total_inserted, "skipped": total_skipped, **last_physical}


def import_all(
    client: W4HClient, dataset_id: str, manifest: dict, data_dir: Path, mode: str = "append"
) -> list[dict]:
    signals = manifest.get("signals", [])
    return [
        import_signal(
            client, dataset_id, signal, data_dir, mode=mode, signal_index=i, signal_count=len(signals)
        )
        for i, signal in enumerate(signals, start=1)
    ]
