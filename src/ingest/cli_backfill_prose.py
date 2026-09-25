"""CLI for the prose backfill (ALG-KK-BACKFILL-SOURCE-PROSE).

    python -m ingest.cli_backfill_prose --db data/master.db \
        --source-type kernel-doc --dry-run

WHY THIS EXISTS AT ALL. Measured 2026-09-25 on data/master.db: all 43
kernel-doc Evidence nodes carried text = "", and kernel-doc yielded 0 concepts
from 43 Sources against conference-paper's 69 from 597. Nothing had ever read
those documents — validate_all_sources fetched every one of them and dropped
the text on the floor. Concept harvest from canonical documentation cannot
begin until they are readable.

THIS REACHES THE NETWORK AND NOTHING ELSE IN THE INGEST PATH DOES SO FOR FREE:
no model, no credential, no cost. Run it with --dry-run first; the dry run
fetches and classifies but writes nothing, so it answers "what would this
store" without touching the database.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys

from ingest.validate_sources import backfill_source_prose, generate_backfill_report

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Fetch Source URLs and store the prose on their Evidence nodes",
    )
    parser.add_argument("--db", required=True, help="Path to master SQLite database")
    parser.add_argument(
        "--source-type", action="append", dest="source_types", default=None,
        help="Restrict to Sources of this source_type; repeatable. "
             "Omitted means every Source in the database.",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Bound the run to N Sources. Applied AFTER selection, matching "
             "ALG-KK-EXTRACT-CLI, so --limit 10 means ten documents fetched.",
    )
    parser.add_argument(
        "--rate-limit", type=float, default=1.0,
        help="Seconds between fetches (INV-KK-VALIDATE-RATE-LIMITED). "
             "git.kernel.org is volunteer-run; do not lower this without a "
             "reason you would give its maintainers.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Fetch and classify, write nothing",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON rather than text")
    args = parser.parse_args(argv)

    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.rate_limit < 0:
        parser.error("--rate-limit must not be negative")

    logging.basicConfig(level=logging.INFO)
    conn = sqlite3.connect(args.db)
    try:
        report = backfill_source_prose(
            conn,
            rate_limit=args.rate_limit,
            source_types=tuple(args.source_types) if args.source_types else None,
            limit=args.limit,
            dry_run=args.dry_run,
        )
    finally:
        conn.close()

    if args.json:
        print(json.dumps({
            "dry_run": report.dry_run,
            "examined": report.examined,
            "stored": report.stored,
            "by_classification": report.by_classification(),
            "outcomes": [
                {"source_id": o.source_id, "url": o.url, "fetch_url": o.fetch_url,
                 "classification": o.classification, "stored": o.stored,
                 "chars": o.chars, "reason": o.reason}
                for o in report.outcomes
            ],
        }, indent=2))
    else:
        print(generate_backfill_report(report))

    if report.examined == 0:
        print("No Sources selected.", file=sys.stderr)


if __name__ == "__main__":
    main()
