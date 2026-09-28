"""CLI for seeding documentation subtrees (ALG-KK-SEED-DOC-SUBTREE).

    python -m ingest.cli_seed_docs --db data/master.db --dry-run
    python -m ingest.cli_seed_docs --db data/master.db --limit 5

Defaults to every subtree in DOC_PATH_PREFIXES that is not already seeded.
No model is called and no credential is needed — this writes Sources and
Evidence and reads nothing with an LLM. Running ALG-KK-DOC-HARVEST over what
lands is a separate go-ahead.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys

from graph.rules import DOC_PATH_PREFIXES
from ingest.seed_docs import format_seed_report, seed_subtree

KERNEL_TREE = (
    "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/"
)

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Seed Sources and Evidence from kernel documentation subtrees",
    )
    parser.add_argument("--db", required=True, help="Path to master SQLite database")
    parser.add_argument(
        "--subtree", action="append", dest="subtrees", default=None,
        help="Subtree path such as Documentation/RCU/; repeatable. Must sit in "
             "DOC_PATH_PREFIXES per INV-KK-SEED-PATH-DEFINITIONAL. Omitted "
             "means every definitional subtree.",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Bound each subtree to N documents, applied AFTER the "
             "already-seeded filter so --limit 10 means ten actually fetched.",
    )
    parser.add_argument(
        "--rate-limit", type=float, default=1.0,
        help="Seconds between fetches (INV-KK-VALIDATE-RATE-LIMITED). "
             "git.kernel.org is volunteer-run.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List and fetch, write nothing",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args(argv)

    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")

    subtrees = args.subtrees or [p for p in DOC_PATH_PREFIXES]
    logging.basicConfig(level=logging.INFO)
    conn = sqlite3.connect(args.db)
    reports = []
    try:
        for path in subtrees:
            url = path if path.startswith("http") else KERNEL_TREE + path
            reports.append((path, seed_subtree(
                conn, url, rate_limit=args.rate_limit,
                limit=args.limit, dry_run=args.dry_run)))
    finally:
        conn.close()

    if args.json:
        print(json.dumps({
            "dry_run": args.dry_run,
            "subtrees": [{
                "path": p,
                "seeded": r.seeded,
                "by_reason": r.by_reason(),
                "outcomes": [
                    {"url": o.url, "seeded": o.seeded, "reason": o.reason,
                     "chars": o.chars, "source_id": o.source_id}
                    for o in r.outcomes
                ],
            } for p, r in reports],
            "total_seeded": sum(r.seeded for _, r in reports),
        }, indent=2))
    else:
        for path, report in reports:
            print(f"== {path}")
            print(format_seed_report(report))
        print(f"\ntotal seeded: {sum(r.seeded for _, r in reports)}")

    if not any(r.seeded for _, r in reports) and not args.dry_run:
        print("Nothing seeded.", file=sys.stderr)


if __name__ == "__main__":
    main()
