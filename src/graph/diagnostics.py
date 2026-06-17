"""Graph health diagnostics — ALG-KK-DIAG-GRAPH-HEALTH.

INV-KK-DIAG-REPORT-COMPLETE: all 7 diagnostic categories present.
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
    total_nodes: int = 0
    total_edges: int = 0


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

    return report
