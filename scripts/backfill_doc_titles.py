"""Give the untitled kernel-doc Sources the title their own text already holds.

ALG-KK-SEED-DOC-SUBTREE, INV-KK-WEB-CONCEPT-EVIDENCE-SPLIT.

ALL 1,510 kernel-doc SOURCES LACKED A TITLE, measured 2026-09-30, because the
seeder never captured one. Every other type is fully titled — preprint 2883 of
2883, conference-paper 597 of 597 — so the gap was invisible everywhere except
on the concept page, which renders an untitled Source as its node id: a curator
reading Block Groups saw "src-462ab441d987" where blockgroup.rst belonged. A
correctly-labelled Documentation section is still unreadable if every row is a
hash.

NO NETWORK. The title is recovered from the text already stored on each
Source's Evidence node, by the same seed_docs.rst_title the seeder now runs at
seed time. A backfill that re-fetched 1,510 documents would be a second
opportunity to differ from the seeder; this one cannot.

Usage:
    python scripts/backfill_doc_titles.py [--db data/master.db] [--apply]
Without --apply it reports and writes nothing.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from graph.engine import update_node_attrs  # noqa: E402
from graph.rules import DOC_SOURCE_TYPES  # noqa: E402
from ingest.seed_docs import rst_title  # noqa: E402


def untitled_doc_sources(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    """(source_id, url, evidence text) for every untitled documentation Source.

    LEFT JOIN, not JOIN: a Source whose Evidence carries no text is a Source
    this cannot title, and it has to be COUNTED rather than filtered away —
    25 of them exist, and a run that reported 1,485 of 1,485 while silently
    dropping them would be the reporting defect this project keeps finding.
    """
    placeholders = ", ".join("?" for _ in DOC_SOURCE_TYPES)
    rows = conn.execute(
        "SELECT s.id, COALESCE(json_extract(s.attrs, '$.url'), ''), "
        "COALESCE(json_extract(e.attrs, '$.text'), '') "
        "FROM nodes s "
        "LEFT JOIN edges se ON se.target_id = s.id AND se.kind = 'sourced-from' "
        "LEFT JOIN nodes e ON e.id = se.source_id AND e.kind = 'Evidence' "
        f"WHERE s.kind = 'Source' "
        f"AND json_extract(s.attrs, '$.source_type') IN ({placeholders}) "
        "AND COALESCE(json_extract(s.attrs, '$.title'), '') = '' "
        "ORDER BY s.id",
        DOC_SOURCE_TYPES,
    ).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="data/master.db")
    ap.add_argument("--apply", action="store_true",
                    help="write the titles (default: report only)")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    pending = untitled_doc_sources(conn)
    titled = 0
    no_text: list[str] = []
    no_title: list[str] = []
    for source_id, url, text in pending:
        if not text.strip():
            no_text.append(url or source_id)
            continue
        title = rst_title(text)
        if not title:
            no_title.append(url or source_id)
            continue
        titled += 1
        if args.apply:
            update_node_attrs(conn, source_id, {"title": title})
    if args.apply:
        conn.commit()

    print(f"untitled documentation Sources  {len(pending)}")
    print(f"  titled                        {titled}"
          + ("" if args.apply else "  (dry run — nothing written)"))
    print(f"  no text on the Evidence node  {len(no_text)}")
    print(f"  text but no recoverable title {len(no_title)}")
    for url in no_title[:20]:
        print(f"    {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
