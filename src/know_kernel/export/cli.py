"""CLI entry point for the snapshot exporter."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from know_kernel.export.exporter import ExportValidationError, export_class_b_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="kk-export",
        description="Export a Class B-only snapshot from the master knowledge base.",
    )
    parser.add_argument("--master-db", type=Path, required=True, help="Path to the master SQLite DB")
    parser.add_argument("--output-db", type=Path, required=True, help="Path for the output snapshot DB")
    args = parser.parse_args()

    if not args.master_db.exists():
        print(f"Error: master DB not found: {args.master_db}", file=sys.stderr)
        sys.exit(2)

    if args.output_db.exists():
        print(f"Error: output path already exists: {args.output_db}", file=sys.stderr)
        sys.exit(2)

    try:
        report = export_class_b_snapshot(args.master_db, args.output_db)
    except ExportValidationError as e:
        for issue in e.issues:
            print(f"FAIL: {issue}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)

    json.dump(report, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
