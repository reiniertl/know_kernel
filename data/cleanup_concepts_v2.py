"""Second-pass concept cleanup: remove paper-title concepts that survived v1.

The first cleanup (commit 9a72411) caught concepts >40 chars or with colons.
This pass catches shorter paper-title concepts identified by:
  - Exact match against Source node titles
  - Verb patterns typical of papers, not kernel mechanisms
"""

import json
import sqlite3
import sys
import uuid

sys.path.insert(0, "src")

DB_PATH = "data/master.db"

_BAD_CONCEPT_IDS: set[str] = set()

_TITLE_VERB_PATTERNS = {
    "scaling the", "breaking the", "teaching", "stop pretending",
    "towards", "rethinking",
    "continuation-centric", "virtualizing ebpf", "lock-free multi-word",
    "diagnostic gap analysis",
    "hot-upgradable", "nested virtualization fuzzing",
    "paravirtualized secure containers", "kernel patch evolution",
    "kernel l7 policy offloading", "modular kernel network stack",
}


def identify_bad_concepts(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    concepts = conn.execute(
        "SELECT id, json_extract(attrs, '$.name') FROM nodes WHERE kind = 'Concept'"
    ).fetchall()

    titles = set()
    for r in conn.execute(
        "SELECT json_extract(attrs, '$.title') FROM nodes WHERE kind = 'Source'"
    ).fetchall():
        if r[0]:
            titles.add(r[0].lower().strip())

    bad = []
    for cid, name in concepts:
        if not name:
            bad.append((cid, name or "", "empty"))
            continue
        nl = name.lower().strip()
        if nl in titles:
            bad.append((cid, name, "title-match"))
            continue
        if any(p in nl for p in _TITLE_VERB_PATTERNS):
            bad.append((cid, name, "bad-verb"))
            continue
    return bad


def remove_concept(conn: sqlite3.Connection, concept_id: str) -> int:
    edges_deleted = conn.execute(
        "DELETE FROM edges WHERE source_id = ? OR target_id = ?",
        (concept_id, concept_id),
    ).rowcount
    conn.execute("DELETE FROM nodes WHERE id = ?", (concept_id,))
    return edges_deleted


def reconnect_orphaned_papers(conn: sqlite3.Connection) -> tuple[int, int]:
    sys.path.insert(0, "data")
    from repair_paper_links import (
        find_orphaned_papers,
        get_good_concepts,
        match_paper_to_concepts,
    )

    name_to_id = get_good_concepts(conn)
    orphans = find_orphaned_papers(conn)

    reconnected = 0
    still_orphaned = 0

    for paper in orphans:
        matches = match_paper_to_concepts(paper["title"], paper["text"], name_to_id)
        if matches:
            for concept_id in matches:
                existing = conn.execute(
                    "SELECT 1 FROM edges WHERE kind = 'extracted-from' AND source_id = ? AND target_id = ?",
                    (concept_id, paper["evidence_id"]),
                ).fetchone()
                if not existing:
                    conn.execute(
                        "INSERT INTO edges (kind, source_id, target_id, attrs) VALUES (?, ?, ?, '{}')",
                        ("extracted-from", concept_id, paper["evidence_id"]),
                    )
            reconnected += 1
        else:
            still_orphaned += 1

    return reconnected, still_orphaned


def reseed_orphaned_briefs(conn: sqlite3.Connection) -> int:
    """Delete ResearchBriefs that lost their Concept link and recreate them."""
    from seed_research_briefs import infer_key_ideas, infer_relevance, infer_methodology

    orphaned_rbs = conn.execute("""
        SELECT rb.id, rb.attrs, ev.id as ev_id
        FROM nodes rb
        JOIN edges re ON re.kind = 'extracted-from' AND re.source_id = rb.id
        JOIN nodes ev ON ev.id = re.target_id AND ev.kind = 'Evidence'
        WHERE rb.kind = 'ResearchBrief'
        AND NOT EXISTS (
            SELECT 1 FROM edges ce
            JOIN nodes c ON c.id = ce.source_id AND c.kind = 'Concept'
            WHERE ce.kind = 'extracted-from' AND ce.target_id = ev.id
        )
    """).fetchall()

    if not orphaned_rbs:
        return 0

    deleted = 0
    for rb_id, _, _ in orphaned_rbs:
        conn.execute("DELETE FROM edges WHERE source_id = ? OR target_id = ?", (rb_id, rb_id))
        conn.execute("DELETE FROM nodes WHERE id = ?", (rb_id,))
        deleted += 1

    reseeded = 0
    papers = conn.execute("""
        SELECT DISTINCT s.id, json_extract(s.attrs, '$.title') as title,
               json_extract(s.attrs, '$.published_date') as pub_date,
               ev.id as ev_id
        FROM nodes s
        JOIN edges se ON se.kind = 'sourced-from' AND se.target_id = s.id
        JOIN nodes ev ON ev.id = se.source_id AND ev.kind = 'Evidence'
        WHERE s.kind = 'Source'
        AND json_extract(s.attrs, '$.source_type') IN
            ('paper','preprint','conference-paper','conference-proceedings')
        AND NOT EXISTS (
            SELECT 1 FROM nodes rb
            JOIN edges re ON re.kind = 'extracted-from'
                AND re.source_id = rb.id AND re.target_id = ev.id
            WHERE rb.kind = 'ResearchBrief'
        )
    """).fetchall()

    for source_id, title, pub_date, ev_id in papers:
        title = title or "(untitled)"
        pub_date = pub_date or "2026-01-01"

        concept_rows = conn.execute(
            "SELECT json_extract(c.attrs, '$.name') FROM nodes c "
            "JOIN edges ce ON ce.kind = 'extracted-from' AND ce.source_id = c.id "
            "AND ce.target_id = ? WHERE c.kind = 'Concept'",
            (ev_id,),
        ).fetchall()
        concept_names = [r[0] for r in concept_rows if r[0]]

        subsystem_rows = conn.execute(
            "SELECT DISTINCT json_extract(sub.attrs, '$.name') FROM nodes sub "
            "JOIN edges bt ON bt.kind = 'belongs-to' AND bt.target_id = sub.id "
            "JOIN nodes c ON c.id = bt.source_id AND c.kind = 'Concept' "
            "JOIN edges ce ON ce.kind = 'extracted-from' AND ce.source_id = c.id "
            "AND ce.target_id = ? WHERE sub.kind = 'Subsystem'",
            (ev_id,),
        ).fetchall()
        subsystem_names = [r[0] for r in subsystem_rows if r[0]]

        brief_id = f"rb-{uuid.uuid4().hex[:12]}"
        attrs = json.dumps({
            "title": title,
            "key_ideas": json.dumps(infer_key_ideas(title)),
            "relevance": infer_relevance(title, concept_names, subsystem_names),
            "methodology": infer_methodology(title.lower()),
            "source_date": pub_date,
            "artifact_class": "B",
        })

        conn.execute(
            "INSERT INTO nodes (id, kind, attrs) VALUES (?, 'ResearchBrief', ?)",
            (brief_id, attrs),
        )
        conn.execute(
            "INSERT INTO edges (kind, source_id, target_id, attrs) VALUES ('extracted-from', ?, ?, '{}')",
            (brief_id, ev_id),
        )

        for cn in concept_names:
            cid_row = conn.execute(
                "SELECT id FROM nodes WHERE kind = 'Concept' AND json_extract(attrs, '$.name') = ?",
                (cn,),
            ).fetchone()
            if cid_row:
                try:
                    conn.execute(
                        "INSERT INTO edges (kind, source_id, target_id, attrs) VALUES ('summarizes-for', ?, ?, '{}')",
                        (brief_id, cid_row[0]),
                    )
                except sqlite3.IntegrityError:
                    pass
        reseeded += 1

    return reseeded


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    print("=== Identifying bad concepts ===")
    bad = identify_bad_concepts(conn)

    print(f"\nREMOVE ({len(bad)}):")
    for cid, name, reason in bad:
        print(f"  [{reason}] {cid}: {name}")

    print(f"\n=== Removing {len(bad)} bad concepts ===")
    total_edges = 0
    for cid, name, reason in bad:
        edges = remove_concept(conn, cid)
        total_edges += edges
        print(f"  Removed {cid} ({edges} edges)")
    conn.commit()

    remaining = conn.execute("SELECT count(*) FROM nodes WHERE kind = 'Concept'").fetchone()[0]
    print(f"\nConcepts remaining: {remaining}")

    print("\n=== Reconnecting orphaned papers ===")
    reconnected, still_orphaned = reconnect_orphaned_papers(conn)
    conn.commit()
    print(f"  Reconnected: {reconnected}")
    print(f"  Still orphaned: {still_orphaned}")

    print("\n=== Reseeding orphaned ResearchBriefs ===")
    reseeded = reseed_orphaned_briefs(conn)
    conn.commit()
    print(f"  Reseeded: {reseeded}")

    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()

    print(f"\n=== Summary ===")
    print(f"Bad concepts removed: {len(bad)}")
    print(f"Edges deleted: {total_edges}")
    print(f"Papers reconnected: {reconnected}")
    print(f"Papers still orphaned: {still_orphaned}")
    print(f"ResearchBriefs reseeded: {reseeded}")
    print(f"Concepts remaining: {remaining}")


if __name__ == "__main__":
    main()
