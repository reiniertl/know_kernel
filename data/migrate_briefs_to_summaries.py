"""One-time migration of ResearchBrief nodes into PaperSummary (ALG-KK-BRIEF-MIGRATE).

Implements decision D-9: ResearchBrief and PaperSummary were one concept modelled
twice. Every one of the 458 brief-bearing papers carried exactly one brief, so the
brief was per-paper in practice, and 935 of its 937 summarizes-for edges were
derivable from the Source <-Evidence <-Concept chain the graph already holds while
the other 2 dangled. This pass moves the brief's content onto the paper's single
PaperSummary and removes the brief.

WHAT IS PRESERVED, AND WHY IT MATTERS
key_ideas, relevance and methodology all survive. relevance and methodology are
carried by no other node kind in the graph, so a merge that kept only the prose
would silently destroy 460 distinct methodology values and a relevance field whose
median length is 322 characters — none of it reconstructible without re-running the
model at a cost of ~458 calls.

D-10, OPTION (b): A MIGRATED ROW IS 'absent', NOT PRESENT
ResearchBrief never held a prose summary, so there is none to migrate. The row is
therefore written at state "absent" with empty text, carrying the three enrichment
fields. The presence test is NOT widened: "absent" stays outside PRESENT_STATES and
summary_is_present remains a pure function of the state alone, which is what the
completeness verdict and the web layer both assume.

The consequence is accepted deliberately: the 458 best-documented papers report
has_summary=false until ALG-KK-SUMMARY-EXTRACT-BATCH backfills prose. The
alternatives were worse. Widening the presence test would make presence depend on
content rather than state, changing a contract two other modules rely on.
Synthesising prose by joining key_ideas would stamp text no model ever wrote with an
llm-extracted provenance, leaving it indistinguishable from genuine extractor output
forever after. Understating a verdict is recoverable; falsifying provenance is not.

PROVENANCE
model is recorded as the literal "unknown-legacy". ResearchBrief never stored which
model produced it, and these are the first rows the summary state vocabulary will
ever describe. Guessing an identifier would falsify the provenance field on the
entire initial population.

DELETION USES DIRECT SQL
graph.engine.delete_node re-runs validate_node on every dependent and
graph.engine.delete_edge on the edge's source, either of which reaches
rules.check_source_has_advisory on a Source that merely lacks an Advisory — an
unrelated pre-existing gap most real Sources have. The precedents are
ingest.paper_summary._delete_summary and ingest.venue_store._clear_published_at.

IDEMPOTENT AND RE-RUNNABLE
A paper that already carries a PaperSummary is updated in place rather than given a
second one, and a second run finds no briefs left and reports zero changes. A brief
whose Evidence carries no sourced-from edge cannot be attributed to a paper: it is
reported and left untouched, never guessed at and never crashed on.

Usage:
    python data/migrate_briefs_to_summaries.py data/master.db [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from ingest.paper_summary import set_summary

BACKUP_SUFFIX = ".bak-pre-brief-migration"

# ResearchBrief never recorded which model wrote it. Recorded honestly rather than
# guessed; see PROVENANCE above.
LEGACY_MODEL = "unknown-legacy"

# D-10 option (b): the enrichment fields carry no prose, so the row is not present.
MIGRATED_STATE = "absent"


def checkpoint(db: pathlib.Path) -> None:
    """Fold the write-ahead log back into the database file.

    The graph databases run in WAL mode, so a committed write lands in <db>-wal and
    leaves <db> byte-identical until SQLite checkpoints. That matters twice: a backup
    taken by copying <db> alone would omit anything still in the log, and
    data/master.db is a TRACKED file whose -wal sibling is gitignored, so without
    this the run produces a correct database locally and an empty diff.
    """
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def brief_rows(conn: sqlite3.Connection) -> list[tuple[str, dict]]:
    """Every ResearchBrief node, oldest id first so a run is deterministic."""
    rows = conn.execute(
        "SELECT id, attrs FROM nodes WHERE kind = 'ResearchBrief' ORDER BY id"
    ).fetchall()
    out = []
    for brief_id, attrs in rows:
        parsed = json.loads(attrs) if isinstance(attrs, str) else (attrs or {})
        out.append((brief_id, parsed))
    return out


def source_for_brief(conn: sqlite3.Connection, brief_id: str) -> str | None:
    """Resolve brief -extracted-from-> Evidence -sourced-from-> Source.

    Returns None when the chain is broken, which is not an error: 2 of the 460
    briefs hang off Evidence that carries no sourced-from edge and so belong to no
    paper at all.
    """
    row = conn.execute(
        "SELECT es.target_id FROM edges ef "
        "JOIN edges es ON es.source_id = ef.target_id AND es.kind = 'sourced-from' "
        "WHERE ef.source_id = ? AND ef.kind = 'extracted-from' "
        "ORDER BY es.id LIMIT 1",
        (brief_id,),
    ).fetchone()
    return row[0] if row else None


def _delete_brief(conn: sqlite3.Connection, brief_id: str) -> None:
    """Remove a brief and every edge touching it, with direct SQL.

    Direct SQL, not graph.engine.delete_node: see DELETION USES DIRECT SQL above.
    """
    conn.execute("DELETE FROM edges WHERE source_id = ? OR target_id = ?", (brief_id, brief_id))
    conn.execute("DELETE FROM nodes WHERE id = ?", (brief_id,))


def migrate(conn: sqlite3.Connection, dry_run: bool = False) -> dict:
    stats = {
        "briefs": 0,
        "migrated": 0,
        "summaries_created": 0,
        "summaries_updated": 0,
        "unresolvable": 0,
        "unresolvable_ids": [],
    }

    for brief_id, attrs in brief_rows(conn):
        stats["briefs"] += 1
        source_id = source_for_brief(conn, brief_id)
        if source_id is None:
            stats["unresolvable"] += 1
            stats["unresolvable_ids"].append(brief_id)
            continue

        if dry_run:
            stats["migrated"] += 1
            continue

        result = set_summary(
            conn,
            source_id,
            text="",
            state=MIGRATED_STATE,
            model=LEGACY_MODEL,
            key_ideas=attrs.get("key_ideas") or None,
            relevance=attrs.get("relevance") or "",
            methodology=attrs.get("methodology") or "",
        )
        if result.created:
            stats["summaries_created"] += 1
        else:
            stats["summaries_updated"] += 1
        _delete_brief(conn, brief_id)
        stats["migrated"] += 1

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("db", type=pathlib.Path)
    parser.add_argument("--dry-run", action="store_true")
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
        stats = migrate(conn, dry_run=args.dry_run)
        if not args.dry_run:
            conn.commit()
    finally:
        conn.close()

    if not args.dry_run:
        checkpoint(args.db)

    print(f"[{'DRY RUN' if args.dry_run else 'APPLIED'}]")
    for key in ("briefs", "migrated", "summaries_created", "summaries_updated", "unresolvable"):
        print(f"  {key:20s} {stats[key]}")
    if stats["unresolvable_ids"]:
        print("  briefs with no resolvable Source (left untouched, not guessed at):")
        for brief_id in stats["unresolvable_ids"]:
            print(f"    {brief_id}")
    if not args.dry_run and stats["migrated"]:
        print(f"  migrated rows sit at state '{MIGRATED_STATE}' with model '{LEGACY_MODEL}'.")
        print("  ^ D-10 option (b): they carry no prose, so they do not count as present")
        print("    until ALG-KK-SUMMARY-EXTRACT-BATCH backfills it.")


if __name__ == "__main__":
    main()
