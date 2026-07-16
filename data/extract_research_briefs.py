"""Batch extraction of ResearchBrief nodes (ALG-KK-RESEARCH-BRIEF-BATCH).

Iterates all research Source nodes that have Evidence but no linked
ResearchBrief. Runs ALG-KK-RESEARCH-BRIEF-EXTRACT for each.
Migrates schema CHECK constraints before extraction.
"""

import json
import sqlite3
import sys
import time

sys.path.insert(0, "src")

DB_PATH = "data/master.db"

RESEARCH_SOURCE_TYPES = ("paper", "preprint", "conference-paper", "conference-proceedings")


def migrate_schema(conn: sqlite3.Connection) -> None:
    """Drop CHECK constraints on nodes/edges tables to allow new kinds (D5).

    Replaces the table DDL in sqlite_master with clean versions that
    have no CHECK constraint. App-level validation in add_node() enforces
    kind membership.
    """
    conn.execute("PRAGMA writable_schema = ON")

    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='nodes'",
    ).fetchone()
    if row and "CHECK" in row[0]:
        nodes_sql = (
            'CREATE TABLE "nodes" (\n'
            "    id TEXT PRIMARY KEY,\n"
            "    kind TEXT NOT NULL,\n"
            "    attrs TEXT NOT NULL DEFAULT '{}'\n"
            ")"
        )
        conn.execute(
            "UPDATE sqlite_master SET sql = ? WHERE type='table' AND name='nodes'",
            (nodes_sql,),
        )
        print("  Migrated nodes: removed CHECK constraint")

    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='edges'",
    ).fetchone()
    if row and "CHECK" in row[0]:
        edges_sql = (
            'CREATE TABLE "edges" (\n'
            "    id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            "    kind TEXT NOT NULL,\n"
            "    source_id TEXT NOT NULL REFERENCES nodes(id),\n"
            "    target_id TEXT NOT NULL REFERENCES nodes(id),\n"
            "    attrs TEXT NOT NULL DEFAULT '{}',\n"
            "    UNIQUE (kind, source_id, target_id)\n"
            ")"
        )
        conn.execute(
            "UPDATE sqlite_master SET sql = ? WHERE type='table' AND name='edges'",
            (edges_sql,),
        )
        print("  Migrated edges: removed CHECK constraint")

    conn.execute("PRAGMA writable_schema = OFF")
    conn.commit()


def find_papers_without_brief(conn: sqlite3.Connection) -> list[dict]:
    """Find Source nodes with Evidence but no linked ResearchBrief."""
    rows = conn.execute("""
        SELECT s.id as source_id, s.attrs as s_attrs,
               ev.id as ev_id, ev.attrs as ev_attrs
        FROM nodes s
        JOIN edges se ON se.kind = 'sourced-from' AND se.target_id = s.id
        JOIN nodes ev ON ev.id = se.source_id AND ev.kind = 'Evidence'
        WHERE s.kind = 'Source'
        AND json_extract(s.attrs, '$.source_type') IN (?, ?, ?, ?)
        AND NOT EXISTS (
            SELECT 1 FROM nodes rb
            JOIN edges re ON re.kind = 'extracted-from'
                AND re.source_id = rb.id AND re.target_id = ev.id
            WHERE rb.kind = 'ResearchBrief'
        )
    """, RESEARCH_SOURCE_TYPES).fetchall()

    result = []
    for r in rows:
        s_attrs = json.loads(r[1]) if isinstance(r[1], str) else (r[1] or {})
        ev_attrs = json.loads(r[3]) if isinstance(r[3], str) else (r[3] or {})
        result.append({
            "source_id": r[0],
            "evidence_id": r[2],
            "title": s_attrs.get("title", ""),
            "text": ev_attrs.get("text", ev_attrs.get("description", "")),
            "source_date": s_attrs.get("published_date", "2026-01-01"),
            "source_type": s_attrs.get("source_type", "paper"),
        })
    return result


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    print("=== Schema Migration ===")
    migrate_schema(conn)

    print("\n=== Finding papers without ResearchBrief ===")
    papers = find_papers_without_brief(conn)
    print(f"Papers to process: {len(papers)}")

    from ingest.research_brief_extractor import extract_research_brief

    extracted = 0
    errors = 0
    total_prompt_tokens = 0
    total_response_tokens = 0

    for i, paper in enumerate(papers, 1):
        text = paper["text"] or ""
        title = paper["title"] or "(untitled)"
        is_title_only = len(text.strip()) < 100

        mode = "title-only" if is_title_only else "full-text"
        print(f"\n[{i}/{len(papers)}] {mode}: {title[:70]}...")

        try:
            result = extract_research_brief(
                conn,
                evidence_id=paper["evidence_id"],
                source_date=paper["source_date"],
                source_text=text if not is_title_only else None,
                paper_title=title,
                title_only=is_title_only,
            )
            conn.commit()

            if result.brief_id:
                print(f"  -> {result.brief_id}: {result.key_ideas_count} ideas, "
                      f"{result.concepts_linked} concepts, "
                      f"model={result.extraction_model}")
                extracted += 1
            else:
                print(f"  -> SKIPPED (invalid LLM response)")

            total_prompt_tokens += result.prompt_tokens
            total_response_tokens += result.response_tokens

            time.sleep(0.1)

        except Exception as e:
            print(f"  -> ERROR: {e}")
            errors += 1
            conn.rollback()

    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()

    print(f"\n=== Summary ===")
    print(f"Extracted: {extracted}")
    print(f"Errors: {errors}")
    print(f"Total processed: {len(papers)}")
    print(f"Tokens: {total_prompt_tokens} prompt, {total_response_tokens} response")


if __name__ == "__main__":
    main()
