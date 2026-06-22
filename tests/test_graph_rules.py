"""Tests for know_kernel.graph.rules â€” admissibility rule checkers."""

from __future__ import annotations

import sqlite3

from graph.engine import add_edge, add_node
from graph.rules import (
    RULES_BY_KIND,
    Violation,
    check_advisory_has_assessor,
    check_compat_concept_pairs,
    check_compat_provenance,
    check_comparative_concept_pairs,
    check_concept_has_belongs_to,
    check_concept_has_provenance,
    check_evidence_has_source,
    check_failure_mode_provenance,
    check_failure_mode_trigger,
    check_kinv_belongs_to_subsystem,
    check_kinv_governed_by_concept,
    check_profile_concept,
    check_profile_provenance,
    check_proposal_grounding,
    check_protocol_concept_pairs,
    check_protocol_provenance,
    check_source_has_advisory,
    check_subsystem_has_children,
    validate_node,
)
from graph.schema import NODE_KINDS


# --- INV-KK-CONCEPT-SUBSYSTEM ---


def test_concept_belongs_to_pass(populated: sqlite3.Connection):
    assert check_concept_has_belongs_to(populated, "c1") is None


def test_concept_belongs_to_fail(conn: sqlite3.Connection):
    add_node(conn, "c1", "Concept", {"name": "x", "description": "d", "artifact_class": "B", "key_properties": ["test"], "tradeoffs": [], "design_rationale": "test"})
    v = check_concept_has_belongs_to(conn, "c1")
    assert isinstance(v, Violation)
    assert "belongs-to" in v.message.lower() or "Subsystem" in v.message


# --- INV-KK-CONCEPT-PROVENANCE ---


def test_concept_provenance_pass(populated: sqlite3.Connection):
    assert check_concept_has_provenance(populated, "c1") is None


def test_concept_provenance_fail(conn: sqlite3.Connection):
    add_node(conn, "c1", "Concept", {"name": "x", "description": "d", "artifact_class": "B", "key_properties": ["test"], "tradeoffs": [], "design_rationale": "test"})
    v = check_concept_has_provenance(conn, "c1")
    assert isinstance(v, Violation)


# --- INV-KK-EVIDENCE-TRACEABLE / INV-KK-EVIDENCE-EXACTLY-ONE-SOURCE ---


def test_evidence_source_pass(populated: sqlite3.Connection):
    assert check_evidence_has_source(populated, "ev1") is None


def test_evidence_source_fail_zero(conn: sqlite3.Connection):
    add_node(conn, "ev1", "Evidence", {"artifact_class": "A", "contamination_level": "L0"})
    v = check_evidence_has_source(conn, "ev1")
    assert isinstance(v, Violation)
    assert "found 0" in v.message


def test_evidence_source_fail_two(populated: sqlite3.Connection):
    add_node(populated, "src2", "Source", {"url": "http://x", "source_type": "repo", "license": "GPL"})
    populated.execute(
        "INSERT INTO edges (kind, source_id, target_id, attrs) VALUES ('sourced-from', 'ev1', 'src2', '{}')"
    )
    v = check_evidence_has_source(populated, "ev1")
    assert isinstance(v, Violation)
    assert "found 2" in v.message


# --- INV-KK-PROPOSAL-NO-EVIDENCE ---


def test_proposal_grounding_pass(populated: sqlite3.Connection):
    assert check_proposal_grounding(populated, "prop1") is None


def test_proposal_grounding_fail(populated: sqlite3.Connection):
    populated.execute(
        "INSERT INTO edges (kind, source_id, target_id, attrs) VALUES ('grounded-in', 'prop1', 'ev1', '{}')"
    )
    v = check_proposal_grounding(populated, "prop1")
    assert isinstance(v, Violation)
    assert "Evidence" in v.message


# --- INV-KK-SOURCE-ADVISORY ---


def test_source_advisory_pass(populated: sqlite3.Connection):
    assert check_source_has_advisory(populated, "src1") is None


def test_source_advisory_fail(conn: sqlite3.Connection):
    add_node(conn, "src1", "Source", {"url": "http://x", "source_type": "paper", "license": "PD"})
    v = check_source_has_advisory(conn, "src1")
    assert isinstance(v, Violation)


# --- validate_node dispatcher ---


def test_validate_node_concept_clean(populated: sqlite3.Connection):
    violations = validate_node(populated, "c1", "Concept")
    assert violations == []


def test_validate_node_concept_violations(conn: sqlite3.Connection):
    add_node(conn, "c1", "Concept", {"name": "x", "description": "d", "artifact_class": "B", "key_properties": ["test"], "tradeoffs": [], "design_rationale": "test"})
    violations = validate_node(conn, "c1", "Concept")
    assert len(violations) == 2
    rules = {v.rule for v in violations}
    assert "concept-belongs-to" in rules
    assert "concept-provenance" in rules


def test_validate_node_no_rules_kind(conn: sqlite3.Connection):
    add_node(conn, "og1", "OptimizationGoal", {"name": "perf", "description": "d", "metric": "latency", "direction": "minimize"})
    violations = validate_node(conn, "og1", "OptimizationGoal")
    assert violations == []


# --- INV-KK-KINV-SUBSYSTEM ---


def test_kinv_belongs_to_subsystem_pass(conn: sqlite3.Connection):
    add_node(conn, "sub1", "Subsystem", {"name": "sched"})
    add_node(conn, "kinv1", "KernelInvariant", {"predicate": "P", "strength": "safety", "scope": "global", "artifact_class": "B"})
    add_edge(conn, "belongs-to", "kinv1", "sub1")
    assert check_kinv_belongs_to_subsystem(conn, "kinv1") is None


def test_kinv_belongs_to_subsystem_fail(conn: sqlite3.Connection):
    add_node(conn, "kinv1", "KernelInvariant", {"predicate": "P", "strength": "safety", "scope": "global", "artifact_class": "B"})
    v = check_kinv_belongs_to_subsystem(conn, "kinv1")
    assert isinstance(v, Violation)
    assert "belongs-to" in v.message.lower() or "Subsystem" in v.message


# --- INV-KK-KINV-GOVERNED-BY ---


def test_kinv_governed_by_concept_pass(conn: sqlite3.Connection):
    add_node(conn, "c1", "Concept", {"name": "x", "description": "d", "artifact_class": "B", "key_properties": [], "tradeoffs": [], "design_rationale": "r"})
    add_node(conn, "kinv1", "KernelInvariant", {"predicate": "P", "strength": "safety", "scope": "global", "artifact_class": "B"})
    add_edge(conn, "governed-by", "kinv1", "c1")
    assert check_kinv_governed_by_concept(conn, "kinv1") is None


def test_kinv_governed_by_concept_fail(conn: sqlite3.Connection):
    add_node(conn, "kinv1", "KernelInvariant", {"predicate": "P", "strength": "safety", "scope": "global", "artifact_class": "B"})
    v = check_kinv_governed_by_concept(conn, "kinv1")
    assert isinstance(v, Violation)
    assert "governed-by" in v.message.lower()


# --- INV-KK-FM-TRIGGERED-BY ---


def test_failure_mode_trigger_pass(conn: sqlite3.Connection):
    add_node(conn, "kinv1", "KernelInvariant", {"predicate": "P", "strength": "safety", "scope": "global", "artifact_class": "B"})
    add_node(conn, "fm1", "FailureMode", {"symptom": "crash", "blast_radius": "local", "recoverability": "self-healing", "artifact_class": "B"})
    add_edge(conn, "triggered-by", "fm1", "kinv1")
    assert check_failure_mode_trigger(conn, "fm1") is None


def test_failure_mode_trigger_fail(conn: sqlite3.Connection):
    add_node(conn, "fm1", "FailureMode", {"symptom": "crash", "blast_radius": "local", "recoverability": "self-healing", "artifact_class": "B"})
    v = check_failure_mode_trigger(conn, "fm1")
    assert isinstance(v, Violation)
    assert "triggered-by" in v.message.lower()


# --- INV-KK-FM-PROVENANCE ---


def test_failure_mode_provenance_pass(conn: sqlite3.Connection):
    add_node(conn, "ev1", "Evidence", {"artifact_class": "A", "contamination_level": "L0"})
    add_node(conn, "fm1", "FailureMode", {"symptom": "crash", "blast_radius": "local", "recoverability": "self-healing", "artifact_class": "B"})
    add_edge(conn, "extracted-from", "fm1", "ev1")
    assert check_failure_mode_provenance(conn, "fm1") is None


def test_failure_mode_provenance_fail(conn: sqlite3.Connection):
    add_node(conn, "fm1", "FailureMode", {"symptom": "crash", "blast_radius": "local", "recoverability": "self-healing", "artifact_class": "B"})
    v = check_failure_mode_provenance(conn, "fm1")
    assert isinstance(v, Violation)
    assert "extracted-from" in v.message.lower()


# --- INV-KK-IP-CONSTRAINS-PAIR ---


def test_protocol_concept_pairs_pass(conn: sqlite3.Connection):
    add_node(conn, "c1", "Concept", {"name": "x", "description": "d", "artifact_class": "B", "key_properties": [], "tradeoffs": [], "design_rationale": "r"})
    add_node(conn, "c2", "Concept", {"name": "y", "description": "d", "artifact_class": "B", "key_properties": [], "tradeoffs": [], "design_rationale": "r"})
    add_node(conn, "ip1", "InteractionProtocol", {"rule": "no sleep", "ordering": "never-during", "violation_mode": "deadlock", "artifact_class": "B"})
    add_edge(conn, "constrains-composition", "ip1", "c1")
    add_edge(conn, "constrains-composition", "ip1", "c2")
    assert check_protocol_concept_pairs(conn, "ip1") is None


def test_protocol_concept_pairs_fail_one(conn: sqlite3.Connection):
    add_node(conn, "c1", "Concept", {"name": "x", "description": "d", "artifact_class": "B", "key_properties": [], "tradeoffs": [], "design_rationale": "r"})
    add_node(conn, "ip1", "InteractionProtocol", {"rule": "no sleep", "ordering": "never-during", "violation_mode": "deadlock", "artifact_class": "B"})
    add_edge(conn, "constrains-composition", "ip1", "c1")
    v = check_protocol_concept_pairs(conn, "ip1")
    assert isinstance(v, Violation)
    assert "found 1" in v.message


# --- INV-KK-IP-PROVENANCE ---


def test_protocol_provenance_pass(conn: sqlite3.Connection):
    add_node(conn, "ev1", "Evidence", {"artifact_class": "A", "contamination_level": "L0"})
    add_node(conn, "ip1", "InteractionProtocol", {"rule": "no sleep", "ordering": "never-during", "violation_mode": "deadlock", "artifact_class": "B"})
    add_edge(conn, "extracted-from", "ip1", "ev1")
    assert check_protocol_provenance(conn, "ip1") is None


def test_protocol_provenance_fail(conn: sqlite3.Connection):
    add_node(conn, "ip1", "InteractionProtocol", {"rule": "no sleep", "ordering": "never-during", "violation_mode": "deadlock", "artifact_class": "B"})
    v = check_protocol_provenance(conn, "ip1")
    assert isinstance(v, Violation)
    assert "extracted-from" in v.message.lower()


# --- validate_node for new kinds ---


def test_validate_node_kernel_invariant_clean(conn: sqlite3.Connection):
    add_node(conn, "sub1", "Subsystem", {"name": "sched"})
    add_node(conn, "c1", "Concept", {"name": "x", "description": "d", "artifact_class": "B", "key_properties": [], "tradeoffs": [], "design_rationale": "r"})
    add_node(conn, "kinv1", "KernelInvariant", {"predicate": "P", "strength": "safety", "scope": "global", "artifact_class": "B"})
    add_edge(conn, "belongs-to", "kinv1", "sub1")
    add_edge(conn, "governed-by", "kinv1", "c1")
    violations = validate_node(conn, "kinv1", "KernelInvariant")
    assert violations == []


def test_validate_node_kernel_invariant_violations(conn: sqlite3.Connection):
    add_node(conn, "kinv1", "KernelInvariant", {"predicate": "P", "strength": "safety", "scope": "global", "artifact_class": "B"})
    violations = validate_node(conn, "kinv1", "KernelInvariant")
    assert len(violations) == 2
    rules = {v.rule for v in violations}
    assert "kinv-belongs-to-subsystem" in rules
    assert "kinv-governed-by" in rules


# --- INV-KK-PP-PROFILED-BY ---


def test_profile_concept_pass(conn: sqlite3.Connection):
    add_node(conn, "c1", "Concept", {"name": "x", "description": "d", "artifact_class": "B", "key_properties": [], "tradeoffs": [], "design_rationale": "r"})
    add_node(conn, "pp1", "PerformanceProfile", {"metric": "latency", "complexity": "O(1)", "best_case": "1ms", "worst_case": "10ms", "typical_case": "5ms", "conditions": "normal", "artifact_class": "B"})
    add_edge(conn, "profiled-by", "pp1", "c1")
    assert check_profile_concept(conn, "pp1") is None


def test_profile_concept_fail_zero(conn: sqlite3.Connection):
    add_node(conn, "pp1", "PerformanceProfile", {"metric": "latency", "complexity": "O(1)", "best_case": "1ms", "worst_case": "10ms", "typical_case": "5ms", "conditions": "normal", "artifact_class": "B"})
    v = check_profile_concept(conn, "pp1")
    assert isinstance(v, Violation)
    assert "found 0" in v.message


# --- INV-KK-PP-PROVENANCE ---


def test_profile_provenance_pass(conn: sqlite3.Connection):
    add_node(conn, "ev1", "Evidence", {"artifact_class": "A", "contamination_level": "L0"})
    add_node(conn, "pp1", "PerformanceProfile", {"metric": "latency", "complexity": "O(1)", "best_case": "1ms", "worst_case": "10ms", "typical_case": "5ms", "conditions": "normal", "artifact_class": "B"})
    add_edge(conn, "extracted-from", "pp1", "ev1")
    assert check_profile_provenance(conn, "pp1") is None


def test_profile_provenance_fail(conn: sqlite3.Connection):
    add_node(conn, "pp1", "PerformanceProfile", {"metric": "latency", "complexity": "O(1)", "best_case": "1ms", "worst_case": "10ms", "typical_case": "5ms", "conditions": "normal", "artifact_class": "B"})
    v = check_profile_provenance(conn, "pp1")
    assert isinstance(v, Violation)
    assert "extracted-from" in v.message.lower()


# --- INV-KK-CA-ASSESSES-PAIR ---


def test_compat_concept_pairs_pass(conn: sqlite3.Connection):
    add_node(conn, "c1", "Concept", {"name": "x", "description": "d", "artifact_class": "B", "key_properties": [], "tradeoffs": [], "design_rationale": "r"})
    add_node(conn, "c2", "Concept", {"name": "y", "description": "d", "artifact_class": "B", "key_properties": [], "tradeoffs": [], "design_rationale": "r"})
    add_node(conn, "ca1", "CompatibilityAssessment", {"synergy": "high", "rationale": "good", "conditions": "normal", "artifact_class": "B"})
    add_edge(conn, "assesses-compatibility", "ca1", "c1")
    add_edge(conn, "assesses-compatibility", "ca1", "c2")
    assert check_compat_concept_pairs(conn, "ca1") is None


def test_compat_concept_pairs_fail_one(conn: sqlite3.Connection):
    add_node(conn, "c1", "Concept", {"name": "x", "description": "d", "artifact_class": "B", "key_properties": [], "tradeoffs": [], "design_rationale": "r"})
    add_node(conn, "ca1", "CompatibilityAssessment", {"synergy": "high", "rationale": "good", "conditions": "normal", "artifact_class": "B"})
    add_edge(conn, "assesses-compatibility", "ca1", "c1")
    v = check_compat_concept_pairs(conn, "ca1")
    assert isinstance(v, Violation)
    assert "found 1" in v.message


# --- INV-KK-CA-PROVENANCE ---


def test_compat_provenance_pass(conn: sqlite3.Connection):
    add_node(conn, "ev1", "Evidence", {"artifact_class": "A", "contamination_level": "L0"})
    add_node(conn, "ca1", "CompatibilityAssessment", {"synergy": "high", "rationale": "good", "conditions": "normal", "artifact_class": "B"})
    add_edge(conn, "extracted-from", "ca1", "ev1")
    assert check_compat_provenance(conn, "ca1") is None


def test_compat_provenance_fail(conn: sqlite3.Connection):
    add_node(conn, "ca1", "CompatibilityAssessment", {"synergy": "high", "rationale": "good", "conditions": "normal", "artifact_class": "B"})
    v = check_compat_provenance(conn, "ca1")
    assert isinstance(v, Violation)
    assert "extracted-from" in v.message.lower()


# --- INV-KK-COMPARATIVE-EXACTLY-TWO ---


def test_comparative_concept_pairs_pass(conn: sqlite3.Connection):
    add_node(conn, "c1", "Concept", {"name": "x", "description": "d", "artifact_class": "B", "key_properties": [], "tradeoffs": [], "design_rationale": "r"})
    add_node(conn, "c2", "Concept", {"name": "y", "description": "d", "artifact_class": "B", "key_properties": [], "tradeoffs": [], "design_rationale": "r"})
    add_node(conn, "cmp1", "ComparativeAnalysis", {"dimension": "speed", "winner": "c1", "conditions": "normal", "quantitative_delta": "2x", "artifact_class": "B"})
    add_edge(conn, "compares", "cmp1", "c1")
    add_edge(conn, "compares", "cmp1", "c2")
    assert check_comparative_concept_pairs(conn, "cmp1") is None


def test_comparative_concept_pairs_fail_one(conn: sqlite3.Connection):
    add_node(conn, "c1", "Concept", {"name": "x", "description": "d", "artifact_class": "B", "key_properties": [], "tradeoffs": [], "design_rationale": "r"})
    add_node(conn, "cmp1", "ComparativeAnalysis", {"dimension": "speed", "winner": "c1", "conditions": "normal", "quantitative_delta": "2x", "artifact_class": "B"})
    add_edge(conn, "compares", "cmp1", "c1")
    v = check_comparative_concept_pairs(conn, "cmp1")
    assert isinstance(v, Violation)
    assert "found 1" in v.message


# --- INV-KK-SUBSYSTEM-HAS-CHILDREN ---


def test_subsystem_has_children_pass(conn: sqlite3.Connection):
    add_node(conn, "sub1", "Subsystem", {"name": "sched"})
    add_node(conn, "c1", "Concept", {"name": "x", "description": "d", "artifact_class": "B", "key_properties": [], "tradeoffs": [], "design_rationale": "r"})
    add_edge(conn, "belongs-to", "c1", "sub1")
    assert check_subsystem_has_children(conn, "sub1") is None


def test_subsystem_has_children_fail(conn: sqlite3.Connection):
    add_node(conn, "sub1", "Subsystem", {"name": "sched"})
    v = check_subsystem_has_children(conn, "sub1")
    assert isinstance(v, Violation)
    assert "belongs-to" in v.message.lower()


# --- INV-KK-ADVISORY-HAS-ASSESSOR ---


def test_advisory_has_assessor_pass(conn: sqlite3.Connection):
    add_node(conn, "src1", "Source", {"url": "http://x", "source_type": "paper", "license": "PD"})
    add_node(conn, "adv1", "Advisory", {"assessment": "safe"})
    add_edge(conn, "assessed-by", "src1", "adv1")
    assert check_advisory_has_assessor(conn, "adv1") is None


def test_advisory_has_assessor_fail(conn: sqlite3.Connection):
    add_node(conn, "adv1", "Advisory", {"assessment": "safe"})
    v = check_advisory_has_assessor(conn, "adv1")
    assert isinstance(v, Violation)
    assert "assessed-by" in v.message.lower()


# --- INV-KK-RULES-FULL-COVERAGE ---


def test_rules_by_kind_covers_all_node_kinds():
    assert set(RULES_BY_KIND.keys()) == set(NODE_KINDS)
