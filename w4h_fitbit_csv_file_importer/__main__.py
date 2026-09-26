"""CLI entry: w4h-fitbit-csv-file-import

  plan      profile CSVs (--data-dir, or the uploaded files in W4H_DATA_DIR)
  validate  re-check and rewrite the reviewed manifest.yaml in --data-dir
  import    load every CSV
  sync      append one CSV for one signal
"""

import argparse
import csv
import os
import sys
from pathlib import Path

from .client import W4HClient
from .config import dataset_id as env_dataset_id
from .csv_import import import_all, import_signal
from .fitbit_shapes import is_fitbit
from .manifest import load_manifest, signal_by_slug, write_manifest, write_plan
from .mapping import build_manifest, find_csvs, plan_directory
from .profile import profile_csv
from .reconcile import reconcile_manifest


def _check(manifest: dict) -> dict:
    review = reconcile_manifest(manifest)
    if review["errors"]:
        raise SystemExit("Mapping has errors — fix manifest.yaml and re-run:\n  " + "\n  ".join(review["errors"]))
    return review


def _print_plan(manifest: dict, review: dict) -> None:
    for sig in manifest["signals"]:
        m = sig["geomts_mapping"]
        print(f"{sig['slug']}: subject={m['subject']} time={m['time']} values={[v['name'] for v in m['values']]}")
    for c in review["corrections"]:
        print(f"corrected {c['signal_slug']} {c['field']}: {c['reason']}")
    for e in review["errors"]:
        print(f"ERROR {e}")


def _resolve_sources(args) -> tuple[Path, dict | None, bool]:
    """Return (data_dir, planned_manifest_or_None, write_sidecar).

    --data-dir: that folder (subfolders included) + reviewed-manifest flow.
    W4H_DATA_DIR: the admin's uploaded files, planned in memory (in-app Run).
    """
    if getattr(args, "data_dir", None):
        return Path(args.data_dir).resolve(), None, True
    upload_dir = os.environ.get("W4H_DATA_DIR")
    if upload_dir is not None:
        return _plan_upload(upload_dir)
    raise SystemExit("Pass --data-dir or set W4H_DATA_DIR to the folder with your Fitbit CSV files")


def _plan_upload(upload_dir: str) -> tuple[Path, dict, bool]:
    """Plan the admin's staged files; abort naming every file that cannot be imported."""
    folder = Path(upload_dir.strip()).resolve() if upload_dir.strip() else None
    if folder is None or not folder.is_dir():
        raise SystemExit(f"W4H_DATA_DIR is not a folder: {upload_dir!r}")
    paths, found = find_csvs(folder)
    problems: dict[str, list[str]] = {}
    for why, rel in found:
        problems.setdefault(why, []).append(rel)
    profiles = []
    for p in paths:
        rel = p.relative_to(folder).as_posix()
        try:
            profile = profile_csv(p)
        except (OSError, UnicodeDecodeError, csv.Error) as e:
            problems.setdefault(f"Unreadable ({type(e).__name__})", []).append(rel)
            continue
        profile["name"] = rel
        if not profile["headers"]:
            problems.setdefault("Empty file", []).append(rel)
        elif not profile["rows_seen"]:
            problems.setdefault("Empty file (no data rows)", []).append(rel)
        elif not is_fitbit(profile["headers"]):
            problems.setdefault("Not recognised as a Fitbit CSV export", []).append(rel)
        else:
            profiles.append(profile)
    if problems:
        raise SystemExit("; ".join(f"{why}: {', '.join(names)}" for why, names in problems.items()))
    if not profiles:
        raise SystemExit(f"No .csv files found in W4H_DATA_DIR ({folder})")
    print(f"Using {len(profiles)} uploaded file(s):")
    for profile in profiles:
        print(f"  {profile['name']}")
    return folder, build_manifest(profiles), False


def _main(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(
        description="Import Fitbit CSV files into W4H (API key from .env or in-app Run)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p, needs_dataset=True):
        if needs_dataset:
            p.add_argument("--dataset-id", default=env_dataset_id(), help="Target catalog dataset id")
        p.add_argument("--data-dir", help="Folder of CSVs, subfolders included (default: W4H_DATA_DIR)")

    common(sub.add_parser("plan", help="Build a draft mapping for review"), False)
    common(sub.add_parser("validate", help="Re-check manifest.yaml in --data-dir"), False)
    p_import = sub.add_parser("import", help="Load every CSV")
    common(p_import)
    p_import.add_argument("--mode", choices=["replace", "append"], default="append")
    p_sync = sub.add_parser("sync", help="Append one CSV for one signal")
    common(p_sync)
    p_sync.add_argument("--signal", required=True, help="Signal slug")
    p_sync.add_argument("--file", help="CSV path (default: the manifest's file for the signal)")

    args = parser.parse_args(argv)
    data_dir, planned, write_sidecar = _resolve_sources(args)

    if args.command == "plan":
        manifest = planned if planned is not None else plan_directory(data_dir)
        review = reconcile_manifest(manifest)
        if write_sidecar:
            write_manifest(data_dir, manifest)
            write_plan(data_dir, manifest, review)
            dest = data_dir / "manifest.yaml"
        else:
            dest = "(no file written: planned in memory from W4H_DATA_DIR)"
        _print_plan(manifest, review)
        print(f"Review {dest}, then run `import`." if write_sidecar else f"Plan {dest}.")
        return 1 if review["errors"] else 0

    if args.command == "validate":
        if planned is not None:
            parser.error("validate needs --data-dir pointing at a folder with manifest.yaml")
        manifest = load_manifest(data_dir)
        review = reconcile_manifest(manifest)
        write_manifest(data_dir, manifest)
        write_plan(data_dir, manifest, review)
        for c in review["corrections"]:
            print(f"corrected {c['signal_slug']} {c['field']}: {c['reason']}")
        for e in review["errors"]:
            print(f"ERROR {e}")
        print("manifest OK" if not review["errors"] else "manifest has errors")
        return 1 if review["errors"] else 0

    if not args.dataset_id:
        parser.error("--dataset-id is required (in-app Run passes it in the process environment)")
    manifest = planned if planned is not None else load_manifest(data_dir)
    _check(manifest)
    client = W4HClient()

    if args.command == "import":
        for r in import_all(client, args.dataset_id, manifest, data_dir, mode=args.mode):
            print(
                f"{r['signal']}: inserted={r['inserted']} skipped={r['skipped']} "
                f"→ {r.get('physical_schema')}.{r.get('physical_table')}"
            )
        return 0

    signal = signal_by_slug(manifest, args.signal)
    csv_path = Path(args.file).resolve() if args.file else None
    r = import_signal(client, args.dataset_id, signal, data_dir, mode="append", csv_path=csv_path)
    print(f"sync {r['signal']}: inserted={r['inserted']} skipped={r['skipped']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except (ValueError, FileNotFoundError) as e:  # bad manifest paths, missing CSVs: message, not traceback
        raise SystemExit(str(e)) from e


if __name__ == "__main__":
    sys.exit(main())
