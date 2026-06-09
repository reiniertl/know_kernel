"""Shared fixtures for graph engine tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from graph.schema import init_db
from graph.engine import add_node, add_edge


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = init_db(tmp_path / "test.db")
    yield c
    c.close()


@pytest.fixture
def populated(conn: sqlite3.Connection) -> sqlite3.Connection:
    """A graph with one of each node kind and basic edges."""
    add_node(conn, "sub1", "Subsystem", {"name": "scheduler"})
    add_node(conn, "c1", "Concept", {"name": "RCU", "description": "read-copy-update", "artifact_class": "B"})
    add_node(conn, "c2", "Concept", {"name": "rwlock", "description": "read-write lock", "artifact_class": "B"})
    add_node(conn, "src1", "Source", {"url": "http://ex.com", "source_type": "paper", "license": "PD"})
    add_node(conn, "ev1", "Evidence", {"artifact_class": "A", "contamination_level": "L0"})
    add_node(conn, "adv1", "Advisory", {"assessment": "safe"})
    add_node(conn, "prop1", "Proposal", {"name": "use-rcu", "description": "use RCU for sync"})
    add_edge(conn, "belongs-to", "c1", "sub1")
    add_edge(conn, "belongs-to", "c2", "sub1")
    add_edge(conn, "extracted-from", "c1", "ev1")
    add_edge(conn, "sourced-from", "ev1", "src1")
    add_edge(conn, "assessed-by", "src1", "adv1")
    add_edge(conn, "grounded-in", "prop1", "c1")
    return conn


@pytest.fixture
def admissible_master_db(tmp_path: Path) -> Path:
    """A master DB with mixed Class A + B + C content that passes all admissibility rules."""
    db_path = tmp_path / "master.db"
    conn = init_db(db_path)
    add_node(conn, "sub1", "Subsystem", {"name": "scheduler"})
    add_node(conn, "c1", "Concept", {"name": "RCU", "description": "read-copy-update", "artifact_class": "B"})
    add_node(conn, "c2", "Concept", {"name": "rwlock", "description": "read-write lock", "artifact_class": "B"})
    add_node(conn, "src1", "Source", {"url": "http://ex.com", "source_type": "paper", "license": "PD"})
    add_node(conn, "src2", "Source", {"url": "http://ex2.com", "source_type": "paper", "license": "PD"})
    add_node(conn, "ev1", "Evidence", {"artifact_class": "A", "contamination_level": "L0"})
    add_node(conn, "ev2", "Evidence", {"artifact_class": "A", "contamination_level": "L0"})
    add_node(conn, "adv1", "Advisory", {"assessment": "safe"})
    add_node(conn, "adv2", "Advisory", {"assessment": "safe"})
    add_node(conn, "prop1", "Proposal", {"name": "use-rcu", "description": "use RCU for sync"})
    add_edge(conn, "belongs-to", "c1", "sub1")
    add_edge(conn, "belongs-to", "c2", "sub1")
    add_edge(conn, "extracted-from", "c1", "ev1")
    add_edge(conn, "extracted-from", "c2", "ev2")
    add_edge(conn, "sourced-from", "ev1", "src1")
    add_edge(conn, "sourced-from", "ev2", "src2")
    add_edge(conn, "assessed-by", "src1", "adv1")
    add_edge(conn, "assessed-by", "src2", "adv2")
    add_edge(conn, "grounded-in", "prop1", "c1")
    add_edge(conn, "alternative-to", "c1", "c2")
    conn.commit()
    conn.close()
    return db_path
