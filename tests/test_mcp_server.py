"""Tests for MCP server — ALG-KK-MCP-QUERY.

INV-KK-MCP-SNAPSHOT-ONLY: only Class B snapshot accepted.
INV-KK-MCP-NO-WRITE: read-only connection enforced.
INV-KK-MCP-TOOLS-EXPOSED: no Evidence/Source/Advisory in tool results.
"""

from __future__ import annotations

import sqlite3

import pytest

import know_kernel.mcp_server.server as srv
from know_kernel.export.exporter import export_class_b_snapshot
from know_kernel.graph.engine import add_edge, add_node
from know_kernel.graph.schema import init_db


@pytest.fixture
def snapshot_path(tmp_path):
    """Create a Class B-only snapshot and init the server against it."""
    master_path = tmp_path / "master.db"
    snap_path = tmp_path / "snapshot.db"

    conn = init_db(master_path)
    # Source + Evidence needed to satisfy graph rules for export
    add_node(conn, "src-1", "Source", {
        "url": "https://example.com/paper.pdf",
        "source_type": "paper",
        "license": "MIT",
    })
    add_node(conn, "ev-1", "Evidence", {"artifact_class": "A", "contamination_level": "weak-copyleft"})
    add_node(conn, "ev-2", "Evidence", {"artifact_class": "A", "contamination_level": "weak-copyleft"})
    add_edge(conn, "sourced-from", "ev-1", "src-1")
    add_edge(conn, "sourced-from", "ev-2", "src-1")
    add_node(conn, "adv-1", "Advisory", {"assessment": "Cleared for use."})
    add_edge(conn, "assessed-by", "src-1", "adv-1")
    # Class B nodes
    add_node(conn, "sub-sched", "Subsystem", {"name": "Scheduler"})
    add_node(conn, "concept-1", "Concept", {
        "name": "Lock-free Queue",
        "description": "A queue without locks using atomic operations.",
        "artifact_class": "B",
    })
    add_node(conn, "concept-2", "Concept", {
        "name": "RCU",
        "description": "Read-Copy-Update synchronization mechanism.",
        "artifact_class": "B",
    })
    add_edge(conn, "extracted-from", "concept-1", "ev-1")
    add_edge(conn, "extracted-from", "concept-2", "ev-2")
    add_edge(conn, "belongs-to", "concept-1", "sub-sched")
    add_edge(conn, "belongs-to", "concept-2", "sub-sched")
    conn.commit()
    conn.close()

    export_class_b_snapshot(master_path, snap_path)
    srv.init_snapshot(str(snap_path))
    yield snap_path

    if srv._conn is not None:
        srv._conn.close()
        srv._conn = None  # type: ignore[assignment]


def test_search_concepts_returns_matches(snapshot_path):
    results = srv.search_concepts("Queue")
    assert len(results) >= 1
    ids = [r["id"] for r in results]
    assert "concept-1" in ids
    assert all(r["kind"] in ("Concept", "Subsystem", "Proposal") for r in results)


def test_get_concept_by_id(snapshot_path):
    result = srv.get_concept("concept-1")
    assert result is not None
    assert result["id"] == "concept-1"
    assert result["kind"] == "Concept"
    assert "edges" in result


def test_list_subsystems(snapshot_path):
    results = srv.list_subsystems()
    assert len(results) >= 1
    assert all(r["kind"] == "Subsystem" for r in results)
    ids = [r["id"] for r in results]
    assert "sub-sched" in ids


def test_no_evidence_in_results(snapshot_path):
    """INV-KK-MCP-TOOLS-EXPOSED: Evidence/Source/Advisory never appear in tool output."""
    detail = srv.get_concept("concept-1")
    all_nodes = (
        srv.search_concepts("") +
        ([detail] if detail else []) +
        srv.list_subsystems() +
        srv.get_subsystem_concepts("sub-sched")
    )
    for node in all_nodes:
        assert node.get("kind") not in ("Evidence", "Source", "Advisory"), (
            f"Forbidden kind {node.get('kind')!r} found for node {node.get('id')!r}"
        )


def test_snapshot_only_no_master(tmp_path):
    """INV-KK-MCP-SNAPSHOT-ONLY: refuses a DB that contains Evidence/Source/Advisory."""
    master_path = tmp_path / "master.db"
    conn = init_db(master_path)
    add_node(conn, "ev-1", "Evidence", {
        "artifact_class": "A",
        "contamination_level": "weak-copyleft",
    })
    conn.commit()
    conn.close()

    old_conn = srv._conn
    try:
        with pytest.raises(ValueError, match="Class B-only"):
            srv.init_snapshot(str(master_path))
    finally:
        srv._conn = old_conn  # type: ignore[assignment]


def test_read_only_connection(snapshot_path):
    """INV-KK-MCP-NO-WRITE: connection opened in read-only URI mode — writes raise."""
    conn = srv._conn
    assert conn is not None
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM nodes")
