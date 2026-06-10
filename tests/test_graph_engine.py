"""Tests for know_kernel.graph.engine â€” CRUD ops, edge/attr validation, delete cascade."""

from __future__ import annotations

import sqlite3

import pytest

from graph.engine import (
    AdmissibilityError,
    add_edge,
    add_node,
    delete_edge,
    delete_node,
    get_edge,
    get_node,
    list_nodes,
    neighbors,
    path_exists,
    query_by_attrs,
    update_node_attrs,
)


# --- add_node / get_node ---


def test_add_and_get_node(conn: sqlite3.Connection):
    add_node(conn, "s1", "Subsystem", {"name": "mm"})
    node = get_node(conn, "s1")
    assert node is not None
    assert node["kind"] == "Subsystem"
    assert node["attrs"]["name"] == "mm"


def test_get_node_missing(conn: sqlite3.Connection):
    assert get_node(conn, "nonexistent") is None


# --- INV-KK-NODE-ATTRS-SCHEMA ---


def test_add_node_rejects_missing_required_attrs(conn: sqlite3.Connection):
    with pytest.raises(ValueError, match="missing required attributes"):
        add_node(conn, "c1", "Concept", {"name": "x"})


def test_add_node_concept_requires_name_description_artifact_class(conn: sqlite3.Connection):
    with pytest.raises(ValueError, match="description, artifact_class"):
        add_node(conn, "c1", "Concept", {"name": "x"})


def test_add_node_source_requires_url_source_type_license(conn: sqlite3.Connection):
    with pytest.raises(ValueError, match="missing required"):
        add_node(conn, "s1", "Source", {"url": "http://x"})


def test_add_node_evidence_requires_artifact_class_contamination_level(conn: sqlite3.Connection):
    with pytest.raises(ValueError, match="missing required"):
        add_node(conn, "e1", "Evidence", {})


def test_add_node_advisory_requires_assessment(conn: sqlite3.Connection):
    with pytest.raises(ValueError, match="missing required"):
        add_node(conn, "a1", "Advisory", {})


def test_add_node_subsystem_requires_name(conn: sqlite3.Connection):
    with pytest.raises(ValueError, match="missing required"):
        add_node(conn, "s1", "Subsystem", {})


def test_add_node_proposal_requires_name_description(conn: sqlite3.Connection):
    with pytest.raises(ValueError, match="missing required"):
        add_node(conn, "p1", "Proposal", {"name": "x"})


def test_add_node_accepts_extra_attrs(conn: sqlite3.Connection):
    add_node(conn, "s1", "Subsystem", {"name": "mm", "extra": "val"})
    node = get_node(conn, "s1")
    assert node["attrs"]["extra"] == "val"


# --- add_edge / INV-KK-EDGE-KIND-CONSTRAINTS ---


def test_add_edge_rejects_unknown_kind(populated: sqlite3.Connection):
    with pytest.raises(ValueError, match="Unknown edge kind"):
        add_edge(populated, "bogus", "c1", "c2")


def test_add_edge_rejects_wrong_source_kind(populated: sqlite3.Connection):
    with pytest.raises(ValueError, match="requires.*Concept.*Subsystem"):
        add_edge(populated, "belongs-to", "src1", "sub1")


def test_add_edge_rejects_wrong_target_kind(populated: sqlite3.Connection):
    with pytest.raises(ValueError, match="requires.*Concept.*Subsystem"):
        add_edge(populated, "belongs-to", "c1", "c2")


def test_add_edge_rejects_missing_source(populated: sqlite3.Connection):
    with pytest.raises(ValueError, match="does not exist"):
        add_edge(populated, "belongs-to", "ghost", "sub1")


def test_add_edge_rejects_missing_target(populated: sqlite3.Connection):
    with pytest.raises(ValueError, match="does not exist"):
        add_edge(populated, "belongs-to", "c1", "ghost")


def test_add_edge_valid_belongs_to(populated: sqlite3.Connection):
    count_before = populated.execute("SELECT COUNT(*) FROM edges WHERE kind='belongs-to'").fetchone()[0]
    assert count_before >= 1


def test_add_edge_valid_grounded_in(populated: sqlite3.Connection):
    row = populated.execute(
        "SELECT 1 FROM edges WHERE kind='grounded-in' AND source_id='prop1' AND target_id='c1'"
    ).fetchone()
    assert row is not None


def test_add_edge_grounded_in_rejects_evidence_target(populated: sqlite3.Connection):
    with pytest.raises(ValueError, match="requires.*Proposal.*Concept"):
        add_edge(populated, "grounded-in", "prop1", "ev1")


# --- update_node_attrs ---


def test_update_node_attrs_merges(populated: sqlite3.Connection):
    update_node_attrs(populated, "c1", {"maturity": "stable"})
    node = get_node(populated, "c1")
    assert node["attrs"]["maturity"] == "stable"
    assert node["attrs"]["name"] == "RCU"


def test_update_node_attrs_rejects_nonexistent(conn: sqlite3.Connection):
    with pytest.raises(ValueError, match="does not exist"):
        update_node_attrs(conn, "ghost", {"x": 1})


# --- delete_node / INV-KK-DELETE-CASCADE ---


def test_delete_node_cascades_edges(populated: sqlite3.Connection):
    edges_before = populated.execute(
        "SELECT COUNT(*) FROM edges WHERE source_id='c1' OR target_id='c1'"
    ).fetchone()[0]
    assert edges_before > 0
    delete_node(populated, "c1")
    assert get_node(populated, "c1") is None
    edges_after = populated.execute(
        "SELECT COUNT(*) FROM edges WHERE source_id='c1' OR target_id='c1'"
    ).fetchone()[0]
    assert edges_after == 0


def test_delete_node_nonexistent(conn: sqlite3.Connection):
    with pytest.raises(ValueError, match="does not exist"):
        delete_node(conn, "ghost")


# --- delete_node admissibility cascade (INV-KK-DELETE-CASCADE) ---
# REPRODUCTION TEST: these must FAIL before the fix, PASS after.


def test_delete_evidence_rejects_if_concept_loses_provenance(conn: sqlite3.Connection):
    """Deleting ev1 (only provenance for c1) must be rejected."""
    add_node(conn, "sub1", "Subsystem", {"name": "mm"})
    add_node(conn, "c1", "Concept", {"name": "C", "description": "d", "artifact_class": "B", "key_properties": ["test"], "tradeoffs": [], "design_rationale": "test"})
    add_node(conn, "src1", "Source", {"url": "http://x.com", "source_type": "paper", "license": "PD"})
    add_node(conn, "adv1", "Advisory", {"assessment": "safe"})
    add_node(conn, "ev1", "Evidence", {"artifact_class": "A", "contamination_level": "L0"})
    add_edge(conn, "belongs-to", "c1", "sub1")
    add_edge(conn, "extracted-from", "c1", "ev1")
    add_edge(conn, "sourced-from", "ev1", "src1")
    add_edge(conn, "assessed-by", "src1", "adv1")
    with pytest.raises(AdmissibilityError):
        delete_node(conn, "ev1")


def test_delete_source_rejects_if_evidence_loses_traceability(conn: sqlite3.Connection):
    """Deleting src1 (only source for ev1) must be rejected."""
    add_node(conn, "sub1", "Subsystem", {"name": "mm"})
    add_node(conn, "c1", "Concept", {"name": "C", "description": "d", "artifact_class": "B", "key_properties": ["test"], "tradeoffs": [], "design_rationale": "test"})
    add_node(conn, "src1", "Source", {"url": "http://x.com", "source_type": "paper", "license": "PD"})
    add_node(conn, "adv1", "Advisory", {"assessment": "safe"})
    add_node(conn, "ev1", "Evidence", {"artifact_class": "A", "contamination_level": "L0"})
    add_edge(conn, "belongs-to", "c1", "sub1")
    add_edge(conn, "extracted-from", "c1", "ev1")
    add_edge(conn, "sourced-from", "ev1", "src1")
    add_edge(conn, "assessed-by", "src1", "adv1")
    with pytest.raises(AdmissibilityError):
        delete_node(conn, "src1")


def test_delete_subsystem_rejects_if_concept_loses_belongs_to(conn: sqlite3.Connection):
    """Deleting sub1 (only subsystem for c1) must be rejected."""
    add_node(conn, "sub1", "Subsystem", {"name": "mm"})
    add_node(conn, "c1", "Concept", {"name": "C", "description": "d", "artifact_class": "B", "key_properties": ["test"], "tradeoffs": [], "design_rationale": "test"})
    add_node(conn, "src1", "Source", {"url": "http://x.com", "source_type": "paper", "license": "PD"})
    add_node(conn, "adv1", "Advisory", {"assessment": "safe"})
    add_node(conn, "ev1", "Evidence", {"artifact_class": "A", "contamination_level": "L0"})
    add_edge(conn, "belongs-to", "c1", "sub1")
    add_edge(conn, "extracted-from", "c1", "ev1")
    add_edge(conn, "sourced-from", "ev1", "src1")
    add_edge(conn, "assessed-by", "src1", "adv1")
    with pytest.raises(AdmissibilityError):
        delete_node(conn, "sub1")


def test_delete_advisory_rejects_if_source_loses_assessment(conn: sqlite3.Connection):
    """Deleting adv1 (only advisory for src1) must be rejected."""
    add_node(conn, "sub1", "Subsystem", {"name": "mm"})
    add_node(conn, "c1", "Concept", {"name": "C", "description": "d", "artifact_class": "B", "key_properties": ["test"], "tradeoffs": [], "design_rationale": "test"})
    add_node(conn, "src1", "Source", {"url": "http://x.com", "source_type": "paper", "license": "PD"})
    add_node(conn, "adv1", "Advisory", {"assessment": "safe"})
    add_node(conn, "ev1", "Evidence", {"artifact_class": "A", "contamination_level": "L0"})
    add_edge(conn, "belongs-to", "c1", "sub1")
    add_edge(conn, "extracted-from", "c1", "ev1")
    add_edge(conn, "sourced-from", "ev1", "src1")
    add_edge(conn, "assessed-by", "src1", "adv1")
    with pytest.raises(AdmissibilityError):
        delete_node(conn, "adv1")


def test_delete_node_succeeds_when_no_dependents_violated(conn: sqlite3.Connection):
    """Deleting a node that no other node depends on must succeed."""
    add_node(conn, "sub1", "Subsystem", {"name": "mm"})
    add_node(conn, "adv1", "Advisory", {"assessment": "safe"})
    delete_node(conn, "adv1")
    assert get_node(conn, "adv1") is None


def test_delete_node_succeeds_when_alternate_path_exists(conn: sqlite3.Connection):
    """Deleting ev1 succeeds when c1 still has ev2 as alternate provenance."""
    add_node(conn, "sub1", "Subsystem", {"name": "mm"})
    add_node(conn, "c1", "Concept", {"name": "C", "description": "d", "artifact_class": "B", "key_properties": ["test"], "tradeoffs": [], "design_rationale": "test"})
    add_node(conn, "src1", "Source", {"url": "http://x.com", "source_type": "paper", "license": "PD"})
    add_node(conn, "src2", "Source", {"url": "http://y.com", "source_type": "paper", "license": "PD"})
    add_node(conn, "adv1", "Advisory", {"assessment": "safe"})
    add_node(conn, "adv2", "Advisory", {"assessment": "safe"})
    add_node(conn, "ev1", "Evidence", {"artifact_class": "A", "contamination_level": "L0"})
    add_node(conn, "ev2", "Evidence", {"artifact_class": "A", "contamination_level": "L0"})
    add_edge(conn, "belongs-to", "c1", "sub1")
    add_edge(conn, "extracted-from", "c1", "ev1")
    add_edge(conn, "extracted-from", "c1", "ev2")
    add_edge(conn, "sourced-from", "ev1", "src1")
    add_edge(conn, "sourced-from", "ev2", "src2")
    add_edge(conn, "assessed-by", "src1", "adv1")
    add_edge(conn, "assessed-by", "src2", "adv2")
    delete_node(conn, "ev1")
    assert get_node(conn, "ev1") is None


# --- delete_edge ---


def test_delete_edge_removes_by_id(populated: sqlite3.Connection):
    eid = populated.execute(
        "SELECT id FROM edges WHERE kind='belongs-to' AND source_id='c1'"
    ).fetchone()[0]
    delete_edge(populated, eid)
    assert get_edge(populated, eid) is None


def test_delete_edge_nonexistent(conn: sqlite3.Connection):
    with pytest.raises(ValueError, match="does not exist"):
        delete_edge(conn, 99999)


# --- get_edge ---


def test_get_edge_returns_fields(populated: sqlite3.Connection):
    eid = populated.execute("SELECT id FROM edges LIMIT 1").fetchone()[0]
    edge = get_edge(populated, eid)
    assert edge is not None
    assert "kind" in edge
    assert "source_id" in edge
    assert "target_id" in edge
    assert "attrs" in edge


def test_get_edge_missing(conn: sqlite3.Connection):
    assert get_edge(conn, 99999) is None


# --- list_nodes ---


def test_list_nodes_all(populated: sqlite3.Connection):
    nodes = list_nodes(populated)
    assert len(nodes) == 7


def test_list_nodes_by_kind(populated: sqlite3.Connection):
    concepts = list_nodes(populated, "Concept")
    assert len(concepts) == 2
    assert all(n["kind"] == "Concept" for n in concepts)


def test_list_nodes_empty_kind(populated: sqlite3.Connection):
    result = list_nodes(populated, "Advisory")
    assert len(result) == 1


# --- query_by_attrs ---


def test_query_by_attrs_match(populated: sqlite3.Connection):
    result = query_by_attrs(populated, "Concept", name="RCU")
    assert len(result) == 1
    assert result[0]["id"] == "c1"


def test_query_by_attrs_no_match(populated: sqlite3.Connection):
    result = query_by_attrs(populated, "Concept", name="nonexistent")
    assert len(result) == 0


def test_query_by_attrs_multiple_filters(populated: sqlite3.Connection):
    result = query_by_attrs(populated, "Concept", name="RCU", artifact_class="B")
    assert len(result) == 1


# --- neighbors ---


def test_neighbors_out(populated: sqlite3.Connection):
    out = neighbors(populated, "c1", "out")
    kinds = {n["edge_kind"] for n in out}
    assert "belongs-to" in kinds
    assert "extracted-from" in kinds


def test_neighbors_in(populated: sqlite3.Connection):
    inc = neighbors(populated, "sub1", "in")
    assert len(inc) >= 2


def test_neighbors_edge_kind_filter(populated: sqlite3.Connection):
    out = neighbors(populated, "c1", "out", edge_kind="belongs-to")
    assert all(n["edge_kind"] == "belongs-to" for n in out)
    assert len(out) == 1


# --- path_exists ---


def test_path_exists_direct(populated: sqlite3.Connection):
    assert path_exists(populated, "c1", "sub1", ["belongs-to"])


def test_path_exists_transitive(populated: sqlite3.Connection):
    assert path_exists(populated, "c1", "src1", ["extracted-from", "sourced-from"])


def test_path_exists_no_path(populated: sqlite3.Connection):
    assert not path_exists(populated, "c1", "adv1", ["extracted-from", "sourced-from"])


def test_path_exists_all_edge_kinds(populated: sqlite3.Connection):
    assert path_exists(populated, "c1", "src1")


def test_path_exists_self(populated: sqlite3.Connection):
    assert path_exists(populated, "c1", "c1")
