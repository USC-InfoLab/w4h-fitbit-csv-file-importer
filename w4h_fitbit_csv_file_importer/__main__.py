"""CLI entry: w4h-fitbit-csv-file-import

  plan      profile the CSVs, write a draft manifest.yaml + plan.json for review
  validate  re-check an edited manifest.yaml and rewrite plan.json (the reviewer's re-validate step)
  import  load every CSV (reviewed manifest, or the hardcoded sibling sample when W4H_DATA_DIR is unset)
  sync    append one CSV for one signal (cron-friendly)
"""

import argparse
import sys
from pathlib import Path

from .client import W4HClient
from .config import data_dir as env_data_dir
from .config import data_dir_from_env, dataset_id as env_dataset_id
from .config import hardcoded_csv_paths
from .csv_import import import_all, import_signal
from .manifest import load_manifest, signal_by_slug, write_manifest, write_plan
from .mapping import plan_directory, plan_files
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


def _resolve_sources(args) -> tuple[Path, dict, bool]:
    """Return (data_dir, manifest, wrote_sidecar).

    In-app Run / `./run.sh` leave W4H_DATA_DIR unset: plan the hardcoded sibling
    CSVs in memory and do not write manifest.yaml into that sample package.
    An explicit --data-dir or W4H_DATA_DIR keeps the reviewed-manifest flow.
    """
    explicit = bool(getattr(args, "data_dir", None) or data_dir_from_env())
    if explicit:
        data_dir = Path(args.data_dir).resolve() if args.data_dir else env_data_dir()
        return data_dir, None, True
    paths = hardcoded_csv_paths()
    print("Using hardcoded sibling sample CSVs:")
    for p in paths:
        print(f"  {p}")
    return paths[0].parent, plan_files(paths), False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import Fitbit CSV files from a local folder into W4H (API key from .env)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p, needs_dataset=True):
        if needs_dataset:
            p.add_argument("--dataset-id", default=env_dataset_id(), help="Target catalog dataset id")
        p.add_argument("--data-dir", help="Folder with the CSVs (default: $W4H_DATA_DIR or sibling sample)")

    common(sub.add_parser("plan", help="Build a draft mapping for review (writes manifest.yaml + plan.json)"), False)
    common(sub.add_parser("validate", help="Re-check manifest.yaml (writes plan.json with the corrected manifest)"), False)
    p_import = sub.add_parser("import", help="Load every CSV using the reviewed manifest.yaml")
    common(p_import)
    p_import.add_argument("--mode", choices=["replace", "append"], default="append")
    p_sync = sub.add_parser("sync", help="Append one CSV for one signal (cron-friendly)")
    common(p_sync)
    p_sync.add_argument("--signal", required=True, help="Signal slug from manifest.yaml")
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
            dest = "(not written — sibling sample; in-app Run plans in memory)"
        _print_plan(manifest, review)
        print(f"Review {dest}, then run `import`.")
        return 1 if review["errors"] else 0

    if args.command == "validate":
        if planned is not None:
            parser.error("validate needs a reviewed manifest.yaml — pass --data-dir or set W4H_DATA_DIR")
        manifest = load_manifest(data_dir)
        review = reconcile_manifest(manifest)
        write_manifest(data_dir, manifest)  # corrections are applied in place
        write_plan(data_dir, manifest, review)
        for c in review["corrections"]:
            print(f"corrected {c['signal_slug']} {c['field']}: {c['reason']}")
        for e in review["errors"]:
            print(f"ERROR {e}")
        print("manifest OK" if not review["errors"] else "manifest has errors")
        return 1 if review["errors"] else 0

    if not args.dataset_id:
        parser.error("--dataset-id or W4H_DATASET_ID is required")
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


if __name__ == "__main__":
    sys.exit(main())
