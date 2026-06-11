"""Tests for know_kernel.graph.schema â€” init_db, table creation, kind enums."""

from __future__ import annotations

import sqlite3

from graph.schema import (
    EDGE_KINDS,
    EDGE_VALID_PAIRS,
    NODE_KINDS,
    REQUIRED_ATTRS,
    init_db,
)


def test_node_kinds_complete():
    assert set(NODE_KINDS) == {"Concept", "Source", "Evidence", "Advisory", "Subsystem", "Proposal", "KernelInvariant"}


def test_edge_kinds_complete():
    expected = {
        "belongs-to", "extracted-from", "sourced-from", "alternative-to",
        "refines", "contradicts", "prerequisite", "supersedes",
        "assessed-by", "grounded-in", "governed-by",
    }
    assert set(EDGE_KINDS) == expected


def test_edge_valid_pairs_covers_all_edge_kinds():
    assert set(EDGE_VALID_PAIRS.keys()) == set(EDGE_KINDS)


def test_required_attrs_covers_all_node_kinds():
    assert set(REQUIRED_ATTRS.keys()) == set(NODE_KINDS)


def test_init_db_creates_tables(conn: sqlite3.Connection):
    tables = {
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert "nodes" in tables
    assert "edges" in tables


def test_init_db_enforces_foreign_keys(conn: sqlite3.Connection):
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk == 1


def test_init_db_uses_wal(conn: sqlite3.Connection):
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"


def test_node_kind_check_constraint(conn: sqlite3.Connection):
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO nodes (id, kind, attrs) VALUES ('bad', 'Bogus', '{}')")


def test_edge_kind_check_constraint(conn: sqlite3.Connection):
    import pytest
    conn.execute("INSERT INTO nodes (id, kind, attrs) VALUES ('n1', 'Concept', '{}')")
    conn.execute("INSERT INTO nodes (id, kind, attrs) VALUES ('n2', 'Concept', '{}')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO edges (kind, source_id, target_id, attrs) VALUES ('bogus', 'n1', 'n2', '{}')"
        )


def test_edge_unique_constraint(conn: sqlite3.Connection):
    import pytest
    conn.execute("INSERT INTO nodes (id, kind, attrs) VALUES ('n1', 'Concept', '{}')")
    conn.execute("INSERT INTO nodes (id, kind, attrs) VALUES ('n2', 'Concept', '{}')")
    conn.execute("INSERT INTO edges (kind, source_id, target_id, attrs) VALUES ('alternative-to', 'n1', 'n2', '{}')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO edges (kind, source_id, target_id, attrs) VALUES ('alternative-to', 'n1', 'n2', '{}')")
