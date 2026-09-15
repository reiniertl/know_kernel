"""Batch recompute of per-paper completeness verdicts (ALG-KK-COMPLETENESS-COMPUTE).

Walks every paper Source and writes its IFC-KK-PAPER-COMPLETENESS verdict.
Idempotent and re-runnable: a second run over an unchanged graph reports zero
changes, because at most one verdict exists per Source and recompute_paper
overwrites it in place.

This is the currency mechanism, and the only one. There is deliberately no change
tracking, no trigger and no invalidation graph — INV-KK-COMPLETENESS-STALENESS-
TOLERATED says a verdict may lawfully disagree with the graph it describes, and
the operator's requirement was explicitly that completely up-to-date statistics
are not needed. The single-paper web editors refresh their own paper; everything
else waits for a run of this.

EXPECT THE RESULT TO LOOK BAD. Roughly 2,011 of 3,482 papers (58%) report no
extracted data at all, and 1,911 of those do have an abstract. That is a true
finding about the corpus, not a defect in the dimensions. Do not tune a dimension
to improve the number.

Takes a backup of the database before writing, following the
data/master.db.bak-pre-venues and data/master.db.bak-pre-abstracts precedents.

Usage:
    python data/recompute_completeness.py data/master.db [--dry-run] [--limit N]
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import shutil
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from ingest.paper_completeness import (
    BINARY_DIMENSIONS,
    PAPER_SOURCE_TYPES,
    compute_completeness,
    recompute_paper,
)

BACKUP_SUFFIX = ".bak-pre-completeness"


def checkpoint(db: pathlib.Path) -> None:
    """Fold the write-ahead log back into the database file.

    The graph databases run in WAL mode, so a committed write lands in
    <db>-wal and leaves <db> byte-identical until SQLite checkpoints. That
    matters twice here. A backup taken by copying <db> alone would silently
    omit anything still in the log, and data/master.db is a TRACKED file whose
    -wal sibling is gitignored (.gitignore: *.db-wal) — so without this, a run
    of this script produces a correct database locally and an empty diff, and
    the verdicts never reach the repository.
    """
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def paper_ids(conn: sqlite3.Connection, limit: int | None = None) -> list[str]:
    placeholders = ", ".join("?" for _ in PAPER_SOURCE_TYPES)
    sql = (
        f"SELECT id FROM nodes WHERE kind = 'Source' "
        f"AND json_extract(attrs, '$.source_type') IN ({placeholders}) ORDER BY id"
    )
    params: list = list(PAPER_SOURCE_TYPES)
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return [r[0] for r in conn.execute(sql, params).fetchall()]


def _stored_dimensions(conn: sqlite3.Connection, source_id: str) -> dict | None:
    row = conn.execute(
        "SELECT n.attrs FROM edges e JOIN nodes n ON n.id = e.source_id "
        "WHERE e.kind = 'completeness-of' AND e.target_id = ? ORDER BY e.id LIMIT 1",
        (source_id,),
    ).fetchone()
    if row is None:
        return None
    attrs = json.loads(row[0]) if isinstance(row[0], str) else (row[0] or {})
    return {k: attrs.get(k) for k in BINARY_DIMENSIONS}


def recompute_all(
    conn: sqlite3.Connection, dry_run: bool = False, limit: int | None = None
) -> dict:
    ids = paper_ids(conn, limit)
    stats = {
        "papers": len(ids),
        "verdicts_created": 0,
        "verdicts_changed": 0,
        "verdicts_unchanged": 0,
    }
    tally: collections.Counter = collections.Counter()
    states: collections.Counter = collections.Counter()
    nothing_at_all = 0

    for source_id in ids:
        before = _stored_dimensions(conn, source_id)
        verdict = compute_completeness(conn, source_id) if dry_run else recompute_paper(conn, source_id)

        if before is None:
            stats["verdicts_created"] += 1
        elif before != verdict.dimensions:
            stats["verdicts_changed"] += 1
        else:
            stats["verdicts_unchanged"] += 1

        for dim, value in verdict.dimensions.items():
            if value:
                tally[dim] += 1
        states[verdict.summary_state] += 1
        if not any(verdict.dimensions.values()):
            nothing_at_all += 1

    stats["dimensions"] = {d: tally[d] for d in BINARY_DIMENSIONS}
    stats["summary_states"] = dict(states)
    stats["papers_with_nothing"] = nothing_at_all
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("db", type=pathlib.Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--no-backup", action="store_true", help="skip the backup (tests and scratch DBs)"
    )
    args = parser.parse_args()

    if not args.dry_run and not args.no_backup:
        # Checkpoint first, or the backup omits whatever is still in the log.
        checkpoint(args.db)
        backup = args.db.with_name(args.db.name + BACKUP_SUFFIX)
        shutil.copy2(args.db, backup)
        print(f"[backup] {backup}")

    conn = sqlite3.connect(str(args.db))
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        stats = recompute_all(conn, dry_run=args.dry_run, limit=args.limit)
        if not args.dry_run:
            conn.commit()
    finally:
        conn.close()

    if not args.dry_run:
        checkpoint(args.db)

    total = stats["papers"] or 1
    print(f"[{'DRY RUN' if args.dry_run else 'APPLIED'}]")
    for key in ("papers", "verdicts_created", "verdicts_changed", "verdicts_unchanged"):
        print(f"  {key:22s} {stats[key]}")
    print("  dimensions present:")
    for dim, n in stats["dimensions"].items():
        print(f"    {dim:20s} {n:6d}  ({100.0 * n / total:.1f}%)")
    print("  summary states:")
    for state, n in sorted(stats["summary_states"].items()):
        print(f"    {state:20s} {n:6d}")
    n = stats["papers_with_nothing"]
    print(f"  papers with no dimension at all  {n} ({100.0 * n / total:.1f}%)")
    print("  ^ a true finding about the corpus; do not tune dimensions to shrink it.")


if __name__ == "__main__":
    main()
