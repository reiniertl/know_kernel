"""CLI entry point for the paper scoring service (ALG-KK-REVIEW-CLI)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from graph.schema import init_db
from ingest.paper_scorer import review_paper


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="kk-score",
        description="Score a Source node for impact and create a HumanReview in the know_kernel database.",
    )
    parser.add_argument("--db", required=True, help="Path to master SQLite database")
    parser.add_argument("--source-id", required=True, help="Source node ID to review")
    parser.add_argument("--score", required=True, type=int, help="Impact score 1-5")
    parser.add_argument(
        "--verdict", required=True,
        choices=["accept", "reject"],
        help="Review verdict",
    )
    parser.add_argument("--rationale", required=True, help="Assessment rationale text")
    parser.add_argument("--reviewer", required=True, help="Reviewer identifier (name or email)")
    args = parser.parse_args()

    try:
        conn = init_db(Path(args.db))
    except Exception as exc:
        print(f"Error: cannot open database '{args.db}': {exc}", file=sys.stderr)
        sys.exit(2)

    try:
        result = review_paper(conn, args.source_id, args.reviewer, args.score, args.verdict, args.rationale)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)

    conn.commit()

    print(json.dumps({
        "review_id": result.review_id,
        "source_id": result.source_id,
        "reviewer": result.reviewer,
        "score": result.score,
        "verdict": result.verdict,
        "rationale": result.rationale,
    }, indent=2))


if __name__ == "__main__":
    main()
