"""Tests for know_kernel.graph.rules â€” admissibility rule checkers."""

from __future__ import annotations

import sqlite3

from graph.engine import add_edge, add_node
from graph.rules import (
    Violation,
    check_concept_has_belongs_to,
    check_concept_has_provenance,
    check_evidence_has_source,
    check_proposal_grounding,
    check_source_has_advisory,
    validate_node,
)


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


def test_validate_node_unknown_kind(conn: sqlite3.Connection):
    violations = validate_node(conn, "x", "Subsystem")
    assert violations == []
