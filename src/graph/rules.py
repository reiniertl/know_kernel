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
    count = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind = 'sourced-from' AND source_id = ?",
        (node_id,),
    ).fetchone()[0]
    if count != 1:
        return Violation(
            node_id, "evidence-exactly-one-source",
            f"Evidence must have exactly one sourced-from edge, found {count}",
        )
    return None


def check_source_has_advisory(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'assessed-by' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "source-advisory", "Source must have an Advisory")
    return None


def check_kinv_belongs_to_subsystem(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'belongs-to' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "kinv-belongs-to-subsystem", "KernelInvariant must belong-to at least one Subsystem")
    return None


def check_kinv_governed_by_concept(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'governed-by' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "kinv-governed-by", "KernelInvariant must be governed-by at least one Concept")
    return None


def check_failure_mode_trigger(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'triggered-by' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "fm-triggered-by", "FailureMode must be triggered-by at least one KernelInvariant")
    return None


def check_failure_mode_provenance(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'extracted-from' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "fm-provenance", "FailureMode must be extracted-from at least one Evidence")
    return None


def check_protocol_concept_pairs(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    count = conn.execute(
        "SELECT COUNT(DISTINCT target_id) FROM edges WHERE kind = 'constrains-composition' AND source_id = ?",
        (node_id,),
    ).fetchone()[0]
    if count < 2:
        return Violation(
            node_id, "ip-constrains-pair",
            f"InteractionProtocol must constrains-composition at least 2 distinct Concepts, found {count}",
        )
    return None


def check_protocol_provenance(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'extracted-from' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "ip-provenance", "InteractionProtocol must be extracted-from at least one Evidence")
    return None


def check_profile_concept(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    count = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind = 'profiled-by' AND source_id = ?",
        (node_id,),
    ).fetchone()[0]
    if count != 1:
        return Violation(
            node_id, "pp-profiled-by",
            f"PerformanceProfile must have exactly 1 profiled-by edge, found {count}",
        )
    return None


def check_profile_provenance(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'extracted-from' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "pp-provenance", "PerformanceProfile must be extracted-from at least one Evidence")
    return None


def check_compat_concept_pairs(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    count = conn.execute(
        "SELECT COUNT(DISTINCT target_id) FROM edges WHERE kind = 'assesses-compatibility' AND source_id = ?",
        (node_id,),
    ).fetchone()[0]
    if count < 2:
        return Violation(
            node_id, "ca-assesses-pair",
            f"CompatibilityAssessment must assesses-compatibility at least 2 distinct Concepts, found {count}",
        )
    return None


def check_compat_provenance(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'extracted-from' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "ca-provenance", "CompatibilityAssessment must be extracted-from at least one Evidence")
    return None


def check_comparative_concept_pairs(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    count = conn.execute(
        "SELECT COUNT(DISTINCT target_id) FROM edges WHERE kind = 'compares' AND source_id = ?",
        (node_id,),
    ).fetchone()[0]
    if count != 2:
        return Violation(
            node_id, "comparative-exactly-two",
            f"ComparativeAnalysis must compare exactly 2 distinct Concepts, found {count}",
        )
    return None


def check_subsystem_has_children(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'belongs-to' AND target_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "subsystem-has-children", "Subsystem must have at least one belongs-to incoming edge")
    return None


def check_advisory_has_assessor(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'assessed-by' AND target_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "advisory-has-assessor", "Advisory must have at least one assessed-by incoming edge")
    return None


def check_problem_has_concept(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'identifies-problem' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "problem-identifies-concept", "Problem must identifies-problem at least one Concept")
    return None


def check_observation_has_concept(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'observes' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "observation-observes-concept", "Observation must observes at least one Concept")
    return None


def check_discussion_has_concept(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'discusses' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "discussion-discusses-concept", "Discussion must discusses at least one Concept")
    return None


def check_benchmark_has_concept(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'benchmarks' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "benchmark-benchmarks-concept", "Benchmark must benchmarks at least one Concept")
    return None


def check_proposal_has_concept(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'grounded-in' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "proposal-grounded-in-concept", "Proposal must be grounded-in at least one Concept")
    return None


def check_vulnerability_has_concept(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'exploits' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "vulnerability-exploits-concept", "Vulnerability must exploits at least one Concept")
    return None


RULES_BY_KIND = {
    "Concept": [check_concept_has_belongs_to, check_concept_has_provenance],
    "Evidence": [check_evidence_has_source],
    "Source": [check_source_has_advisory],
    "KernelInvariant": [check_kinv_belongs_to_subsystem, check_kinv_governed_by_concept],
    "FailureMode": [check_failure_mode_trigger, check_failure_mode_provenance],
    "InteractionProtocol": [check_protocol_concept_pairs, check_protocol_provenance],
    "PerformanceProfile": [check_profile_concept, check_profile_provenance],
    "CompatibilityAssessment": [check_compat_concept_pairs, check_compat_provenance],
    "ComparativeAnalysis": [check_comparative_concept_pairs],
    "Subsystem": [check_subsystem_has_children],
    "Advisory": [check_advisory_has_assessor],
    "OptimizationGoal": [],
    "UseCaseScenario": [],
    "Kernel": [],
    "Problem": [check_problem_has_concept],
    "Observation": [check_observation_has_concept],
    "Discussion": [check_discussion_has_concept],
    "Benchmark": [check_benchmark_has_concept],
    "Rejection": [],
    "Vulnerability": [check_vulnerability_has_concept],
    "Fix": [],
    "Proposal": [check_proposal_has_concept],
}


def validate_node(conn: sqlite3.Connection, node_id: str, kind: str) -> list[Violation]:
    checks = RULES_BY_KIND.get(kind, [])
    violations = []
    for check in checks:
        v = check(conn, node_id)
        if v is not None:
            violations.append(v)
    return violations
