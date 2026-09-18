"""Graph health diagnostics — ALG-KK-DIAG-GRAPH-HEALTH.

INV-KK-DIAG-REPORT-COMPLETE: every declared field is present on every report.
Seven of them are orphan CATEGORIES (lists of node ids), five are aggregates,
and six are intake COUNTS. A category that found nothing is an empty list and a
count that found nothing is 0; neither is ever an absent field, because "the
check found nothing" and "the check did not run" must not look alike.

THE INTAKE COUNTS WERE ADDED 2026-09-18, and until then this module did not
contain the string "Source" at all. It described the concept graph in detail and
said nothing about the 3,482 papers that graph is derived from — so the fact
that 333 papers had no abstract, that 321 of those had no identifier to fetch one
with, and that not one of 3,295 summaries had been read by a person were all
established by hand, after a corpus-wide extraction run had already shipped on
that data.

They are COUNTS, not per-paper rows. ALG-KK-WEB-INTAKE-LIST owns the per-paper
view; duplicating it here would create two places that can disagree about the
same question. The dimension vocabulary is IFC-KK-PAPER-COMPLETENESS's, reused
rather than reinvented.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field


@dataclass
class DiagnosticReport:
    orphan_concepts: list[str] = field(default_factory=list)
    unlinked_invariants: list[str] = field(default_factory=list)
    dangling_failure_modes: list[str] = field(default_factory=list)
    lone_protocols: list[str] = field(default_factory=list)
    subsystem_coverage: dict[str, int] = field(default_factory=dict)
    invariant_density: float = 0.0
    duplicate_names: list[tuple[str, list[str]]] = field(default_factory=list)
    orphan_problems: list[str] = field(default_factory=list)
    orphan_observations: list[str] = field(default_factory=list)
    unlinked_vulnerabilities: list[str] = field(default_factory=list)
    total_nodes: int = 0
    total_edges: int = 0
    # --- intake (ALG-KK-DIAG-GRAPH-HEALTH, 2026-09-18) ---
    papers_total: int = 0
    papers_without_abstract: int = 0
    # No abstract AND no arXiv id or DOI resolvable from the url, so there is no
    # automated route to one: these need a title search or a human.
    papers_without_identifier: int = 0
    # No usable text on any Evidence node either, so they cannot be summarised
    # from their own content and are invisible to ALG-KK-SUMMARY-EXTRACT.
    papers_without_evidence_text: int = 0
    # Satisfying not one of the six dimensions IFC-KK-PAPER-COMPLETENESS defines.
    papers_no_dimension: int = 0
    # State llm-extracted with no person having read them. A green tick against
    # has_summary says a summary exists, never that anyone endorsed it.
    summaries_unreviewed: int = 0


# The canonical paper vocabulary (INV-KK-PAPER-SOURCE-TYPE-VOCABULARY).
_PAPER_SOURCE_TYPES = ("preprint", "conference-paper", "conference-proceedings")

# The six dimensions IFC-KK-PAPER-COMPLETENESS defines. Reused, not reinvented.
_COMPLETENESS_DIMENSIONS = (
    "has_abstract", "has_summary", "links_concept",
    "links_subsystem", "links_kernel", "links_invariant",
)


def _count_intake(conn: sqlite3.Connection, report: DiagnosticReport) -> None:
    """Corpus-level intake counts. Counts only — the per-paper view is
    ALG-KK-WEB-INTAKE-LIST, and two implementations of the same question would
    eventually disagree."""
    from ingest.abstract_fetcher import resolve_identifier

    placeholders = ", ".join("?" for _ in _PAPER_SOURCE_TYPES)
    papers = conn.execute(
        f"SELECT id, attrs FROM nodes WHERE kind = 'Source' "
        f"AND json_extract(attrs, '$.source_type') IN ({placeholders})",
        _PAPER_SOURCE_TYPES,
    ).fetchall()
    report.papers_total = len(papers)

    for source_id, raw in papers:
        attrs = json.loads(raw) if isinstance(raw, str) else (raw or {})
        if (attrs.get("abstract") or "").strip():
            continue
        report.papers_without_abstract += 1
        if resolve_identifier(attrs.get("url")) is None:
            report.papers_without_identifier += 1

    report.papers_without_evidence_text = conn.execute(
        f"SELECT COUNT(*) FROM nodes s WHERE s.kind = 'Source' "
        f"AND json_extract(s.attrs, '$.source_type') IN ({placeholders}) "
        f"AND NOT EXISTS ("
        f"  SELECT 1 FROM edges e JOIN nodes ev ON ev.id = e.source_id AND ev.kind = 'Evidence' "
        f"  WHERE e.kind = 'sourced-from' AND e.target_id = s.id "
        f"    AND COALESCE(json_extract(ev.attrs, '$.text'), '') <> '')",
        _PAPER_SOURCE_TYPES,
    ).fetchone()[0]

    for (raw,) in conn.execute("SELECT attrs FROM nodes WHERE kind = 'PaperCompleteness'"):
        verdict = json.loads(raw) if isinstance(raw, str) else (raw or {})
        if not any(verdict.get(d) for d in _COMPLETENESS_DIMENSIONS):
            report.papers_no_dimension += 1

    report.summaries_unreviewed = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind = 'PaperSummary' "
        "AND json_extract(attrs, '$.state') = 'llm-extracted'"
    ).fetchone()[0]


def diagnose_graph(conn: sqlite3.Connection) -> DiagnosticReport:
    report = DiagnosticReport()

    report.orphan_concepts = [
        r[0]
        for r in conn.execute(
            "SELECT n.id FROM nodes n "
            "WHERE n.kind = 'Concept' "
            "AND n.id NOT IN ("
            "  SELECT e.source_id FROM edges e WHERE e.kind = 'belongs-to'"
            ")"
        ).fetchall()
    ]

    report.unlinked_invariants = [
        r[0]
        for r in conn.execute(
            "SELECT n.id FROM nodes n "
            "WHERE n.kind = 'KernelInvariant' "
            "AND n.id NOT IN ("
            "  SELECT e.source_id FROM edges e WHERE e.kind = 'governed-by'"
            ")"
        ).fetchall()
    ]

    report.dangling_failure_modes = [
        r[0]
        for r in conn.execute(
            "SELECT n.id FROM nodes n "
            "WHERE n.kind = 'FailureMode' "
            "AND n.id NOT IN ("
            "  SELECT e.source_id FROM edges e WHERE e.kind = 'triggered-by'"
            ")"
        ).fetchall()
    ]

    rows = conn.execute(
        "SELECT n.id, COUNT(e.id) AS edge_count "
        "FROM nodes n "
        "LEFT JOIN edges e ON e.source_id = n.id AND e.kind = 'constrains-composition' "
        "WHERE n.kind = 'InteractionProtocol' "
        "GROUP BY n.id "
        "HAVING edge_count < 2"
    ).fetchall()
    report.lone_protocols = [r[0] for r in rows]

    report.orphan_problems = [
        r[0]
        for r in conn.execute(
            "SELECT n.id FROM nodes n "
            "WHERE n.kind = 'Problem' "
            "AND n.id NOT IN ("
            "  SELECT e.source_id FROM edges e WHERE e.kind = 'identifies-problem'"
            ")"
        ).fetchall()
    ]

    report.orphan_observations = [
        r[0]
        for r in conn.execute(
            "SELECT n.id FROM nodes n "
            "WHERE n.kind = 'Observation' "
            "AND n.id NOT IN ("
            "  SELECT e.source_id FROM edges e WHERE e.kind = 'observes'"
            ")"
        ).fetchall()
    ]

    report.unlinked_vulnerabilities = [
        r[0]
        for r in conn.execute(
            "SELECT n.id FROM nodes n "
            "WHERE n.kind = 'Vulnerability' "
            "AND n.id NOT IN ("
            "  SELECT e.source_id FROM edges e WHERE e.kind = 'exploits'"
            ")"
        ).fetchall()
    ]

    sub_rows = conn.execute(
        "SELECT n.attrs, COUNT(e.source_id) AS concept_count "
        "FROM nodes n "
        "LEFT JOIN edges e ON e.target_id = n.id AND e.kind = 'belongs-to' "
        "WHERE n.kind = 'Subsystem' "
        "GROUP BY n.id"
    ).fetchall()
    for attrs_json, count in sub_rows:
        attrs = json.loads(attrs_json)
        name = attrs.get("name", "unknown")
        report.subsystem_coverage[name] = count

    concept_count = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind = 'Concept'"
    ).fetchone()[0]
    invariant_count = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind = 'KernelInvariant'"
    ).fetchone()[0]
    report.invariant_density = (
        invariant_count / concept_count if concept_count > 0 else 0.0
    )

    dup_rows = conn.execute(
        "SELECT LOWER(json_extract(attrs, '$.name')) AS lname, "
        "GROUP_CONCAT(id) AS ids "
        "FROM nodes WHERE kind = 'Concept' "
        "GROUP BY lname HAVING COUNT(*) > 1"
    ).fetchall()
    for lname, ids_str in dup_rows:
        report.duplicate_names.append((lname, ids_str.split(",")))

    report.total_nodes = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    report.total_edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]

    _count_intake(conn, report)

    return report
