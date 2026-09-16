"""Batch paper summary extraction (ALG-KK-SUMMARY-EXTRACT-BATCH).

Walks the papers that carry no summary and applies ALG-KK-SUMMARY-EXTRACT to
each.

Candidates are selected on the ABSENCE of a usable summary. That is what makes
the run resumable — stopping and re-running skips whatever already landed — and
it is also what keeps the pass off human work: a human-reviewed or
human-authored summary is a present summary, so those papers never enter the
candidate set at all. The same reasoning is why cli_abstracts selects on the
absence of an abstract and thereby never overwrites a manual one.

Every stored summary is committed immediately. A pass over thousands of papers
against a rate-limited API will be interrupted, and an interrupted run must keep
the summaries it already won rather than discard a half-written batch.

Papers with neither an abstract nor usable Evidence text are skipped and
reported, never stamped. See INV-KK-SUMMARY-EXTRACT-INPUT-BASIS.

Usage:
    python -m ingest.cli_summaries data/master.db [--dry-run] [--limit N]
"""

from __future__ import annotations

import argparse
import collections
import json
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from ingest.paper_summary import PRESENT_STATES
from ingest.summary_extractor import extract_summary

# Which Sources are papers, matching ingest.paper_completeness.
PAPER_SOURCE_TYPES = ("preprint", "conference-paper", "conference-proceedings")

# Courtesy pause between model calls.
CALL_INTERVAL_SECONDS = 0.5


@dataclass
class BatchReport:
    considered: int = 0
    stored: int = 0
    by_basis: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "considered": self.considered,
            "stored": self.stored,
            "by_basis": self.by_basis,
            "skipped": self.skipped,
        }


def candidate_source_ids(
    conn: sqlite3.Connection, limit: int | None = None
) -> list[str]:
    """Papers with no summary in a present state, in stable id order.

    A paper whose summary is 'absent' or 'rejected' IS a candidate: neither is a
    usable summary. A human-authored one is not, and neither is a human-reviewed
    one — re-extracting over human work is the thing this query exists to
    prevent.
    """
    placeholders = ", ".join("?" for _ in PAPER_SOURCE_TYPES)
    present = ", ".join("?" for _ in PRESENT_STATES)
    sql = (
        f"SELECT n.id FROM nodes n "
        f"WHERE n.kind = 'Source' "
        f"  AND json_extract(n.attrs, '$.source_type') IN ({placeholders}) "
        f"  AND NOT EXISTS ("
        f"    SELECT 1 FROM edges e JOIN nodes s ON s.id = e.source_id "
        f"    WHERE e.kind = 'summarizes-paper' AND e.target_id = n.id "
        f"      AND json_extract(s.attrs, '$.state') IN ({present})) "
        f"ORDER BY n.id"
    )
    params: list = [*PAPER_SOURCE_TYPES, *PRESENT_STATES]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return [r[0] for r in conn.execute(sql, params).fetchall()]


def run_batch(
    conn: sqlite3.Connection,
    dry_run: bool = False,
    limit: int | None = None,
    client=None,
    pause: float = CALL_INTERVAL_SECONDS,
) -> BatchReport:
    report = BatchReport()
    basis: collections.Counter = collections.Counter()
    skipped: collections.Counter = collections.Counter()

    for source_id in candidate_source_ids(conn, limit):
        report.considered += 1
        result = extract_summary(
            conn, source_id, dry_run=dry_run, client=client
        )
        if result.skipped:
            skipped[result.skipped] += 1
            continue
        if result.basis:
            basis[result.basis] += 1
        if result.stored:
            report.stored += 1
            # Commit per paper: an interrupted run keeps what it already won.
            conn.commit()
        if pause and not dry_run:
            time.sleep(pause)

    report.by_basis = dict(basis)
    report.skipped = dict(skipped)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("db", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--pause", type=float, default=CALL_INTERVAL_SECONDS,
        help="seconds between model calls",
    )
    args = parser.parse_args(argv)

    conn = sqlite3.connect(str(args.db))
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        report = run_batch(conn, dry_run=args.dry_run, limit=args.limit, pause=args.pause)
        if not args.dry_run:
            conn.commit()
    finally:
        conn.close()

    print(f"[{'DRY RUN' if args.dry_run else 'APPLIED'}]")
    print(json.dumps(report.as_dict(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
