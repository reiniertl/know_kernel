"""Tests for structural constraints â€” symmetric contradicts, acyclic supersedes, path_exists."""

from __future__ import annotations

import sqlite3

import pytest

from graph.engine import AdmissibilityError, add_edge, add_node, delete_edge, path_exists


# --- INV-KK-CONTRADICTS-SYMMETRIC ---


def test_contradicts_auto_inserts_reverse(populated: sqlite3.Connection):
    add_edge(populated, "contradicts", "c1", "c2")
    row = populated.execute(
        "SELECT 1 FROM edges WHERE kind='contradicts' AND source_id='c2' AND target_id='c1'"
    ).fetchone()
    assert row is not None


def test_contradicts_explicit_reverse_hits_unique(populated: sqlite3.Connection):
    add_edge(populated, "contradicts", "c1", "c2")
    import sqlite3 as _sqlite3
    with pytest.raises(_sqlite3.IntegrityError):
        add_edge(populated, "contradicts", "c2", "c1")
    count = populated.execute(
        "SELECT COUNT(*) FROM edges WHERE kind='contradicts' AND source_id='c2' AND target_id='c1'"
    ).fetchone()[0]
    assert count == 1


def test_contradicts_delete_removes_reverse(populated: sqlite3.Connection):
    add_edge(populated, "contradicts", "c1", "c2")
    eid = populated.execute(
        "SELECT id FROM edges WHERE kind='contradicts' AND source_id='c1' AND target_id='c2'"
    ).fetchone()[0]
    delete_edge(populated, eid)
    reverse = populated.execute(
        "SELECT 1 FROM edges WHERE kind='contradicts' AND source_id='c2' AND target_id='c1'"
    ).fetchone()
    assert reverse is None


# --- INV-KK-SUPERSEDES-ACYCLIC ---


def test_supersedes_direct_ok(populated: sqlite3.Connection):
    add_edge(populated, "supersedes", "c1", "c2")
    row = populated.execute(
        "SELECT 1 FROM edges WHERE kind='supersedes' AND source_id='c1' AND target_id='c2'"
    ).fetchone()
    assert row is not None


def test_supersedes_chain_ok(populated: sqlite3.Connection):
    add_node(populated, "c3", "Concept", {"name": "spin", "description": "spinlock", "artifact_class": "B", "key_properties": ["test"], "tradeoffs": [], "design_rationale": "test"})
    add_edge(populated, "supersedes", "c1", "c2")
    add_edge(populated, "supersedes", "c2", "c3")
    row = populated.execute(
        "SELECT 1 FROM edges WHERE kind='supersedes' AND source_id='c2' AND target_id='c3'"
    ).fetchone()
    assert row is not None


def test_supersedes_cycle_rejected(populated: sqlite3.Connection):
    add_node(populated, "c3", "Concept", {"name": "spin", "description": "spinlock", "artifact_class": "B", "key_properties": ["test"], "tradeoffs": [], "design_rationale": "test"})
    add_edge(populated, "supersedes", "c1", "c2")
    add_edge(populated, "supersedes", "c2", "c3")
    with pytest.raises(ValueError, match="cycle"):
        add_edge(populated, "supersedes", "c3", "c1")


def test_supersedes_self_cycle_rejected(populated: sqlite3.Connection):
    with pytest.raises(ValueError, match="cycle"):
        add_edge(populated, "supersedes", "c1", "c1")


# --- path_exists edge cases ---


def test_path_exists_empty_graph(conn: sqlite3.Connection):
    add_node(conn, "s1", "Subsystem", {"name": "x"})
    add_node(conn, "s2", "Subsystem", {"name": "y"})
    assert not path_exists(conn, "s1", "s2")


def test_path_exists_filtered_no_match(populated: sqlite3.Connection):
    assert not path_exists(populated, "c1", "sub1", ["extracted-from"])


def test_path_exists_filtered_match(populated: sqlite3.Connection):
    assert path_exists(populated, "c1", "sub1", ["belongs-to"])


# --- INV-KK-CYCLE-DETECTION-EDGES (refines) ---


def test_refines_chain_ok(populated: sqlite3.Connection):
    add_node(populated, "c3", "Concept", {"name": "spin", "description": "spinlock", "artifact_class": "B", "key_properties": ["test"], "tradeoffs": [], "design_rationale": "test"})
    add_edge(populated, "refines", "c1", "c2")
    add_edge(populated, "refines", "c2", "c3")
    row = populated.execute(
        "SELECT 1 FROM edges WHERE kind='refines' AND source_id='c2' AND target_id='c3'"
    ).fetchone()
    assert row is not None


def test_refines_cycle_rejected(populated: sqlite3.Connection):
    add_node(populated, "c3", "Concept", {"name": "spin", "description": "spinlock", "artifact_class": "B", "key_properties": ["test"], "tradeoffs": [], "design_rationale": "test"})
    add_edge(populated, "refines", "c1", "c2")
    add_edge(populated, "refines", "c2", "c3")
    with pytest.raises(ValueError, match="cycle"):
        add_edge(populated, "refines", "c3", "c1")


def test_refines_self_cycle_rejected(populated: sqlite3.Connection):
    with pytest.raises(ValueError, match="cycle"):
        add_edge(populated, "refines", "c1", "c1")


# --- INV-KK-CYCLE-DETECTION-EDGES (prerequisite) ---


def test_prerequisite_chain_ok(populated: sqlite3.Connection):
    add_node(populated, "c3", "Concept", {"name": "spin", "description": "spinlock", "artifact_class": "B", "key_properties": ["test"], "tradeoffs": [], "design_rationale": "test"})
    add_edge(populated, "prerequisite", "c1", "c2")
    add_edge(populated, "prerequisite", "c2", "c3")
    row = populated.execute(
        "SELECT 1 FROM edges WHERE kind='prerequisite' AND source_id='c2' AND target_id='c3'"
    ).fetchone()
    assert row is not None


def test_prerequisite_cycle_rejected(populated: sqlite3.Connection):
    add_node(populated, "c3", "Concept", {"name": "spin", "description": "spinlock", "artifact_class": "B", "key_properties": ["test"], "tradeoffs": [], "design_rationale": "test"})
    add_edge(populated, "prerequisite", "c1", "c2")
    add_edge(populated, "prerequisite", "c2", "c3")
    with pytest.raises(ValueError, match="cycle"):
        add_edge(populated, "prerequisite", "c3", "c1")


# --- INV-KK-DELETE-EDGE-VALIDATES ---


def test_delete_edge_validates_source_rejects(populated: sqlite3.Connection):
    """Deleting the only sourced-from edge from Evidence raises AdmissibilityError."""
    eid = populated.execute(
        "SELECT id FROM edges WHERE kind='sourced-from' AND source_id='ev1'"
    ).fetchone()[0]
    with pytest.raises(AdmissibilityError):
        delete_edge(populated, eid)
    remaining = populated.execute(
        "SELECT 1 FROM edges WHERE kind='sourced-from' AND source_id='ev1'"
    ).fetchone()
    assert remaining is not None


def test_delete_edge_redundant_succeeds(populated: sqlite3.Connection):
    """Deleting a redundant belongs-to edge (when another remains) succeeds."""
    add_node(populated, "sub2", "Subsystem", {"name": "mm"})
    add_edge(populated, "belongs-to", "c1", "sub2")
    add_node(populated, "c_extra", "Concept", {"name": "extra", "description": "d", "artifact_class": "B", "key_properties": [], "tradeoffs": [], "design_rationale": "r"})
    add_edge(populated, "belongs-to", "c_extra", "sub2")
    eid = populated.execute(
        "SELECT id FROM edges WHERE kind='belongs-to' AND source_id='c1' AND target_id='sub2'"
    ).fetchone()[0]
    delete_edge(populated, eid)
    remaining = populated.execute(
        "SELECT 1 FROM edges WHERE kind='belongs-to' AND source_id='c1' AND target_id='sub2'"
    ).fetchone()
    assert remaining is None
