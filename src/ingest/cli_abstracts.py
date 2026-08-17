"""Batch abstract fetch (ALG-KK-ABSTRACT-FETCH-BATCH).

Walks the Sources that carry no abstract, applies ALG-KK-ABSTRACT-FETCH to
each, and respects each API's published rate.

Resumability is a requirement, not a refinement: 2887 arXiv papers at a 3
second rate is well over two hours, so the run WILL be interrupted at some
point. Every stored abstract is committed immediately, so stopping the run
keeps the abstracts already won instead of discarding a half-written batch.
Re-running skips whatever landed, because the candidate query selects on the
absence of an abstract.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from graph.schema import init_db
from ingest.abstract_fetcher import (
    ARXIV_RATE_LIMIT_SECONDS,
    OPENALEX_RATE_LIMIT_SECONDS,
    Fetch,
    _urllib_fetch,
    fetch_abstract,
    resolve_identifier,
)


@dataclass
class BatchReport:
    considered: int = 0
    stored: int = 0
    by_route: dict[str, int] = field(default_factory=dict)
    failures: dict[str, int] = field(default_factory=dict)
    # Kept so a wrong pull stays diagnosable: which identifier each stored
    # abstract actually came from.
    stored_detail: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "considered": self.considered,
            "stored": self.stored,
            "by_route": self.by_route,
            "failures": self.failures,
            "stored_detail": self.stored_detail,
        }


def candidate_source_ids(conn: sqlite3.Connection, limit: int | None = None) -> list[str]:
    """Sources carrying no abstract, in stable id order.

    Selecting on absence is what makes the batch resumable and what keeps it
    off hand-entered text: a manual abstract is a present abstract, so those
    rows never enter the candidate set at all
    (INV-KK-ABSTRACT-MANUAL-PRESERVED, belt and braces alongside the check in
    fetch_abstract).
    """
    sql = (
        "SELECT id FROM nodes WHERE kind = 'Source' "
        "AND (json_extract(attrs, '$.abstract') IS NULL "
        "OR trim(json_extract(attrs, '$.abstract')) = '') "
        "ORDER BY id"
    )
    params: list = []
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return [row[0] for row in conn.execute(sql, params).fetchall()]


def _pause_for(route_kind: str, sleep) -> None:
    """Wait the published interval for whichever API we just called."""
    if route_kind == "arxiv":
        sleep(ARXIV_RATE_LIMIT_SECONDS)
    else:
        sleep(OPENALEX_RATE_LIMIT_SECONDS)


def run_batch(
    conn: sqlite3.Connection,
    fetch: Fetch = _urllib_fetch,
    sleep=time.sleep,
    limit: int | None = None,
    dry_run: bool = False,
    progress=None,
) -> BatchReport:
    """Apply ALG-KK-ABSTRACT-FETCH across the candidate Sources."""
    report = BatchReport()
    source_ids = candidate_source_ids(conn, limit)

    for source_id in source_ids:
        report.considered += 1

        if dry_run:
            row = conn.execute(
                "SELECT json_extract(attrs, '$.url') FROM nodes WHERE id = ?",
                (source_id,),
            ).fetchone()
            identifier = resolve_identifier(row[0] if row else None)
            key = identifier.kind if identifier else "no-identifier"
            report.failures[key] = report.failures.get(key, 0) + 1
            if progress:
                progress(f"[dry-run] {source_id} -> {key}")
            continue

        try:
            result = fetch_abstract(conn, source_id, fetch=fetch)
        except ValueError as exc:
            report.failures["error"] = report.failures.get("error", 0) + 1
            if progress:
                progress(f"{source_id} ERROR {exc}")
            continue

        if result.stored:
            # Commit per abstract — this is the resumability guarantee.
            conn.commit()
            report.stored += 1
            label = result.abstract_source or "unknown"
            report.by_route[label] = report.by_route.get(label, 0) + 1
            report.stored_detail.append({
                "source_id": source_id,
                "abstract_source": label,
                "identifier_kind": result.identifier_kind,
                "identifier_value": result.identifier_value,
                "chars": result.chars,
            })
            if progress:
                progress(f"{source_id} OK {label} ({result.chars}ch)")
        else:
            report.failures[result.reason] = report.failures.get(result.reason, 0) + 1
            if progress:
                progress(f"{source_id} {result.reason}")

        if result.identifier_kind:
            _pause_for(result.identifier_kind, sleep)

    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="kk-abstracts",
        description="Populate Source abstracts from arXiv and OpenAlex.",
    )
    parser.add_argument("--db", required=True, help="Path to master SQLite database")
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Process at most N candidate Sources (bounded run)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report which identifier each candidate resolves to without calling any API",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Suppress per-paper progress lines",
    )
    args = parser.parse_args()

    try:
        conn = init_db(Path(args.db))
    except Exception as exc:
        print(f"Error: cannot open database '{args.db}': {exc}", file=sys.stderr)
        sys.exit(2)

    def progress(line: str) -> None:
        print(line, file=sys.stderr, flush=True)

    report = run_batch(
        conn,
        limit=args.limit,
        dry_run=args.dry_run,
        progress=None if args.quiet else progress,
    )

    if not args.dry_run:
        conn.commit()

    print(json.dumps(report.as_dict(), indent=2))


if __name__ == "__main__":
    main()
