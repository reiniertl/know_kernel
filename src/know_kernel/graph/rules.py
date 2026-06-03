"""Admissibility rules — enforced on every mutation."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass
class Violation:
    node_id: str
    rule: str
    message: str


def check_concept_has_belongs_to(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'belongs-to' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "concept-belongs-to", "Concept must belong to at least one Subsystem")
    return None


def check_concept_has_provenance(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'extracted-from' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "concept-provenance", "Concept must have at least one extracted-from edge")
    return None


def check_evidence_has_source(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'sourced-from' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "evidence-source", "Evidence must have exactly one sourced-from edge")
    return None


def check_proposal_grounding(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE source_id = ? AND kind = 'grounded-in' AND target_id IN (SELECT id FROM nodes WHERE kind = 'Evidence') LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is not None:
        return Violation(node_id, "proposal-no-evidence", "Proposal may only be grounded-in Concept nodes, never Evidence")
    return None


def check_source_has_advisory(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'assessed-by' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "source-advisory", "Source must have an Advisory")
    return None


RULES_BY_KIND = {
    "Concept": [check_concept_has_belongs_to, check_concept_has_provenance],
    "Evidence": [check_evidence_has_source],
    "Proposal": [check_proposal_grounding],
    "Source": [check_source_has_advisory],
}


def validate_node(conn: sqlite3.Connection, node_id: str, kind: str) -> list[Violation]:
    checks = RULES_BY_KIND.get(kind, [])
    violations = []
    for check in checks:
        v = check(conn, node_id)
        if v is not None:
            violations.append(v)
    return violations
