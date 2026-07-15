"""Clean up paper-title Concept nodes from master.db (ALG-KK-DATA-CLEANUP-CONCEPTS).

Identifies Concept nodes with paper-title-like names (>40 chars or containing ':'),
removes them, and re-links orphaned claim nodes to matching good Concepts.
"""
import json
import sqlite3
import sys

sys.path.insert(0, "src")
from ingest.claim_extractor import fuzzy_match_concept

DB_PATH = "data/master.db"
MAX_NAME_LEN = 40

_CLAIM_EDGE_KINDS = (
    "discusses", "observes", "benchmarks", "grounded-in",
    "identifies-problem", "rejected-for", "exploits",
)


def is_bad_concept(name: str) -> bool:
    if not name:
        return True
    if len(name) > MAX_NAME_LEN:
        return True
    if ":" in name:
        return True
    return False


def get_good_concept_map(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute(
        "SELECT id, json_extract(attrs, '$.name') as name FROM nodes WHERE kind = 'Concept'"
    ).fetchall()
    return {r[1].lower(): r[0] for r in rows if r[1] and not is_bad_concept(r[1])}


def find_source_for_concept(conn: sqlite3.Connection, concept_id: str) -> str | None:
    ev_row = conn.execute(
        "SELECT target_id FROM edges WHERE kind = 'extracted-from' AND source_id = ?",
        (concept_id,),
    ).fetchone()
    if not ev_row:
        return None
    src_row = conn.execute(
        "SELECT target_id FROM edges WHERE kind = 'sourced-from' AND source_id = ?",
        (ev_row[0],),
    ).fetchone()
    return src_row[0] if src_row else None


def find_good_concepts_for_source(conn: sqlite3.Connection, source_id: str, bad_ids: set[str]) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT c.id FROM nodes c "
        "JOIN edges ce ON ce.kind = 'extracted-from' AND ce.source_id = c.id "
        "JOIN nodes ev ON ev.id = ce.target_id AND ev.kind = 'Evidence' "
        "JOIN edges se ON se.kind = 'sourced-from' AND se.source_id = ev.id AND se.target_id = ? "
        "WHERE c.kind = 'Concept'",
        (source_id,),
    ).fetchall()
    return [r[0] for r in rows if r[0] not in bad_ids]


def find_claim_nodes_for_concept(conn: sqlite3.Connection, concept_id: str) -> list[tuple[str, str]]:
    results = []
    for edge_kind in _CLAIM_EDGE_KINDS:
        rows = conn.execute(
            "SELECT source_id FROM edges WHERE kind = ? AND target_id = ?",
            (edge_kind, concept_id),
        ).fetchall()
        for r in rows:
            results.append((r[0], edge_kind))
    return results


def relink_claims(conn: sqlite3.Connection, claims: list[tuple[str, str]], target_concept_id: str) -> int:
    relinked = 0
    for claim_id, edge_kind in claims:
        existing = conn.execute(
            "SELECT 1 FROM edges WHERE kind = ? AND source_id = ? AND target_id = ?",
            (edge_kind, claim_id, target_concept_id),
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO edges (kind, source_id, target_id, attrs) VALUES (?, ?, ?, '{}')",
                (edge_kind, claim_id, target_concept_id),
            )
            relinked += 1
    return relinked


def remove_concept(conn: sqlite3.Connection, concept_id: str) -> None:
    conn.execute("DELETE FROM edges WHERE source_id = ? OR target_id = ?", (concept_id, concept_id))
    conn.execute("DELETE FROM nodes WHERE id = ?", (concept_id,))


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    all_concepts = conn.execute(
        "SELECT id, json_extract(attrs, '$.name') as name, json_extract(attrs, '$.description') as desc "
        "FROM nodes WHERE kind = 'Concept'"
    ).fetchall()

    bad_concepts = [(r["id"], r["name"], r["desc"] or "") for r in all_concepts if is_bad_concept(r["name"] or "")]
    bad_ids = {bc[0] for bc in bad_concepts}
    good_map = get_good_concept_map(conn)

    print(f"Total Concept nodes: {len(all_concepts)}")
    print(f"Bad (paper-title) Concepts: {len(bad_concepts)}")
    print(f"Good Concepts: {len(good_map)}")
    print()

    removed = 0
    relinked_count = 0
    orphaned = 0

    for concept_id, name, desc in bad_concepts:
        source_id = find_source_for_concept(conn, concept_id)
        claims = find_claim_nodes_for_concept(conn, concept_id)

        target_id = None
        if source_id:
            good_for_source = find_good_concepts_for_source(conn, source_id, bad_ids)
            if good_for_source:
                target_id = good_for_source[0]

        if not target_id and desc:
            words = desc.split()[:5]
            for w in words:
                if len(w) > 3:
                    match = fuzzy_match_concept(w, good_map, max_distance=1)
                    if match:
                        target_id = match
                        break

        if target_id and claims:
            n = relink_claims(conn, claims, target_id)
            relinked_count += n
            good_name = next((k for k, v in good_map.items() if v == target_id), target_id)
            print(f"  RELINK {concept_id} ({name[:50]}...) -> {good_name} ({n} claims)")
        elif claims:
            orphaned += len(claims)
            print(f"  ORPHAN {concept_id} ({name[:50]}...) — {len(claims)} claims left unlinked")
        else:
            print(f"  REMOVE {concept_id} ({name[:50]}...) — no claims")

        remove_concept(conn, concept_id)
        removed += 1

    conn.commit()
    conn.close()

    print(f"\n=== Summary ===")
    print(f"Removed:   {removed} bad Concept nodes")
    print(f"Relinked:  {relinked_count} claim edges to good Concepts")
    print(f"Orphaned:  {orphaned} claim edges left unlinked")

    remaining = len(all_concepts) - removed
    print(f"Remaining: {remaining} Concept nodes")


if __name__ == "__main__":
    main()
