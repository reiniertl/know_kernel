"""Tests for structural constraints â€” symmetric contradicts, acyclic supersedes, path_exists."""

from __future__ import annotations

import sqlite3

import pytest

from graph.engine import add_edge, add_node, path_exists


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
    from graph.engine import delete_edge

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
    add_node(populated, "c3", "Concept", {"name": "spin", "description": "spinlock", "artifact_class": "B"})
    add_edge(populated, "supersedes", "c1", "c2")
    add_edge(populated, "supersedes", "c2", "c3")
    row = populated.execute(
        "SELECT 1 FROM edges WHERE kind='supersedes' AND source_id='c2' AND target_id='c3'"
    ).fetchone()
    assert row is not None


def test_supersedes_cycle_rejected(populated: sqlite3.Connection):
    add_node(populated, "c3", "Concept", {"name": "spin", "description": "spinlock", "artifact_class": "B"})
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
