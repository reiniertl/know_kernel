"""CLI entry point for the ingestion service (ALG-KK-INGEST-CLI)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from know_kernel.graph.schema import init_db
from know_kernel.ingest.gate import SessionGate
from know_kernel.ingest.pipeline import ingest_document


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="kk-ingest",
        description="Ingest documents into the know_kernel master database.",
    )
    parser.add_argument("--db", required=True, help="Path to master SQLite database")
    parser.add_argument("--input", required=True, help="File or directory to ingest")
    parser.add_argument("--url", required=True, help="Source URL for the document(s)")
    parser.add_argument(
        "--type", dest="source_type", default="paper",
        help="Source type (paper, code, discussion, etc.)",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: input path not found: {args.input}", file=sys.stderr)
        sys.exit(2)

    try:
        conn = init_db(Path(args.db))
    except Exception as exc:
        print(f"Error: cannot open database '{args.db}': {exc}", file=sys.stderr)
        sys.exit(2)

    files = sorted(f for f in input_path.rglob("*") if f.is_file()) \
        if input_path.is_dir() else [input_path]

    gate = SessionGate()

    results = []
    errors = []

    for fp in files:
        try:
            result = ingest_document(conn, str(fp), args.url, args.source_type, gate=gate)
            results.append({
                "file": str(fp),
                "source_id": result.source_id,
                "evidence_id": result.evidence_id,
                "contamination_level": result.scan_result.contamination_level.value,
                "licenses_found": result.scan_result.licenses_found,
                "file_type": result.file_type,
                "text_length": result.text_length,
            })
        except Exception as exc:
            print(f"Error ingesting {fp}: {exc}", file=sys.stderr)
            errors.append({"file": str(fp), "error": str(exc)})

    conn.commit()

    print(json.dumps({
        "ingested": len(results),
        "errors": len(errors),
        "results": results,
        "error_details": errors,
    }, indent=2))

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
