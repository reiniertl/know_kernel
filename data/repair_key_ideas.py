"""Repair PaperSummary.key_ideas rows corrupted into character lists.

RETAINED AS A BUG RECORD, NOT AS A RUNNABLE TOOL. Decision D-15a removed
key_ideas from PaperSummary entirely, so there is no longer a field for this
script to repair and running it will find nothing. It is kept because the
account below is the only written record of a failure that reached production,
and the shape of that failure - a lossy-looking operation that was silently
lossless, caught only by looking at the rendered page - is worth keeping.

WHAT WENT WRONG
The retired ResearchBrief kind stored key_ideas as a JSON *string*, not a list.
data/migrate_briefs_to_summaries.py passed that value straight to set_summary,
which did `list(key_ideas)` — and list() on a string yields one element per
CHARACTER. All 458 migrated rows were written as e.g.
    ['[', '"', 'C', 'o', 'm', 'p', 'i', 'l', 'e', 'r', ...]
instead of
    ['Compiler operator fusion creates power bursts...', ...]
and the paper page rendered one list item per character.

The write path is fixed in ingest.paper_summary.normalise_key_ideas, which
parses a string rather than iterating it. This script repairs the rows that were
already written.

WHY THE DAMAGE IS FULLY REVERSIBLE
list(s) is lossless for a string s: "".join(list(s)) == s. So a corrupted row is
recovered exactly by joining its characters back together and parsing the JSON
that results. Nothing is inferred and nothing is re-extracted. Rows that are
already well formed are left untouched, so this is idempotent and safe to re-run.

Usage:
    python data/repair_key_ideas.py data/master.db [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

BACKUP_SUFFIX = ".bak-pre-key-ideas-repair"


def checkpoint(db: pathlib.Path) -> None:
    """Fold the write-ahead log back into the database file.

    data/master.db is tracked and its -wal sibling is gitignored, so without this
    the repair is correct locally and invisible to git.
    """
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def is_character_list(value: object) -> bool:
    """A list whose every item is a single character — the corrupted shape.

    Deliberately strict: a genuine key_ideas entry is a sentence, so a list of
    one-character strings cannot be real data. A single-element list like ["x"]
    is also caught, but such a value is not a usable research idea either.
    """
    return (
        isinstance(value, list)
        and len(value) > 0
        and all(isinstance(item, str) and len(item) <= 1 for item in value)
    )


def recover(value: list) -> list[str] | None:
    """Rejoin a character list into the JSON it was made from, or None."""
    try:
        parsed = json.loads("".join(value))
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, list):
        return None
    cleaned = [item.strip() for item in parsed if isinstance(item, str) and item.strip()]
    return cleaned or None


def repair(conn: sqlite3.Connection, dry_run: bool = False) -> dict:
    stats = {"summaries": 0, "corrupted": 0, "repaired": 0, "unrecoverable": 0, "intact": 0}
    unrecoverable: list[str] = []

    rows = conn.execute(
        "SELECT id, attrs FROM nodes WHERE kind = 'PaperSummary' ORDER BY id"
    ).fetchall()

    for node_id, raw in rows:
        stats["summaries"] += 1
        attrs = json.loads(raw) if isinstance(raw, str) else (raw or {})
        value = attrs.get("key_ideas")
        if not is_character_list(value):
            stats["intact"] += 1
            continue

        stats["corrupted"] += 1
        recovered = recover(value)
        if recovered is None:
            stats["unrecoverable"] += 1
            unrecoverable.append(node_id)
            continue

        stats["repaired"] += 1
        if dry_run:
            continue
        attrs["key_ideas"] = recovered
        conn.execute("UPDATE nodes SET attrs = ? WHERE id = ?", (json.dumps(attrs), node_id))

    stats["unrecoverable_ids"] = unrecoverable
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("db", type=pathlib.Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()

    if not args.dry_run and not args.no_backup:
        checkpoint(args.db)
        backup = args.db.with_name(args.db.name + BACKUP_SUFFIX)
        shutil.copy2(args.db, backup)
        print(f"[backup] {backup}")

    conn = sqlite3.connect(str(args.db))
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        stats = repair(conn, dry_run=args.dry_run)
        if not args.dry_run:
            conn.commit()
    finally:
        conn.close()

    if not args.dry_run:
        checkpoint(args.db)

    print(f"[{'DRY RUN' if args.dry_run else 'APPLIED'}]")
    for key in ("summaries", "intact", "corrupted", "repaired", "unrecoverable"):
        print(f"  {key:16s} {stats[key]}")
    for node_id in stats["unrecoverable_ids"]:
        print(f"    unrecoverable: {node_id}")


if __name__ == "__main__":
    main()
