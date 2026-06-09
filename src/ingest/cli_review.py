"""CLI entry point for the review service (ALG-KK-REVIEW-CLI)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from graph.schema import init_db
from ingest.reviewer import review_source


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="kk-review",
        description="Review a Source node and create an Advisory in the know_kernel database.",
    )
    parser.add_argument("--db", required=True, help="Path to master SQLite database")
    parser.add_argument("--source-id", required=True, help="Source node ID to review")
    parser.add_argument("--assessment", required=True, help="Assessment text")
    parser.add_argument(
        "--confirm-level", required=True,
        help="Confirmed contamination level (public-domain, weak-copyleft, strong-copyleft, patent-sensitive, unknown-provenance)",
    )
    args = parser.parse_args()

    try:
        conn = init_db(Path(args.db))
    except Exception as exc:
        print(f"Error: cannot open database '{args.db}': {exc}", file=sys.stderr)
        sys.exit(2)

    try:
        result = review_source(conn, args.source_id, args.assessment, args.confirm_level)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)

    conn.commit()

    print(json.dumps({
        "advisory_id": result.advisory_id,
        "source_id": result.source_id,
        "assessment_text": result.assessment_text,
        "contamination_confirmed": result.contamination_confirmed,
    }, indent=2))


if __name__ == "__main__":
    main()
