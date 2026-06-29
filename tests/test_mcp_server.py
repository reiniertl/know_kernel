"""Tests for MCP server -- ALG-KK-MCP-QUERY.

INV-KK-MCP-SNAPSHOT-ONLY: only Class B snapshot accepted.
INV-KK-MCP-NO-WRITE: read-only connection enforced.
INV-KK-MCP-TOOLS-EXPOSED: no Evidence/Source/Advisory in tool results.
"""

from __future__ import annotations

import sqlite3

import pytest

import mcp_server.server as srv
from export.exporter import export_class_b_snapshot
from graph.engine import add_edge, add_node
from graph.optimization import (
    create_comparative_analysis,
    create_optimization_goal,
    create_use_case_scenario,
    link_concept_to_goal,
    link_concept_to_scenario,
)
from graph.schema import init_db


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
    add_node(conn, "adv-1", "Advisory", {"assessment": "Cleared for use.", "contamination_confirmed": "none"})
    add_edge(conn, "assessed-by", "src-1", "adv-1")
    # Class B nodes
    add_node(conn, "sub-sched", "Subsystem", {"name": "Scheduler"})
    add_node(conn, "concept-1", "Concept", {
        "name": "Lock-free Queue",
        "description": "A queue without locks using atomic operations.",
        "artifact_class": "B",
        "key_properties": ["atomic operations", "wait-free reads"],
        "tradeoffs": ["ABA problem"],
        "design_rationale": "Eliminates lock contention for concurrent producers and consumers.",
    })
    add_node(conn, "concept-2", "Concept", {
        "name": "RCU",
        "description": "Read-Copy-Update synchronization mechanism.",
        "artifact_class": "B",
        "key_properties": ["lock-free reads", "deferred reclamation"],
        "tradeoffs": ["grace period latency"],
        "design_rationale": "Optimizes read-heavy workloads by deferring memory reclamation.",
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
    assert all(r["kind"] in ("Concept", "Subsystem") for r in results)


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
    """INV-KK-MCP-NO-WRITE: connection opened in read-only URI mode -- writes raise."""
    conn = srv._conn
    assert conn is not None
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM nodes")


@pytest.fixture
def rich_snapshot_path(tmp_path):
    """Snapshot with optimization nodes for query-layer MCP tool tests."""
    master_path = tmp_path / "master.db"
    snap_path = tmp_path / "snapshot.db"

    conn = init_db(master_path)
    add_node(conn, "src-1", "Source", {
        "url": "https://example.com/paper.pdf",
        "source_type": "paper",
        "license": "MIT",
    })
    add_node(conn, "ev-1", "Evidence", {"artifact_class": "A", "contamination_level": "weak-copyleft"})
    add_node(conn, "ev-2", "Evidence", {"artifact_class": "A", "contamination_level": "weak-copyleft"})
    add_edge(conn, "sourced-from", "ev-1", "src-1")
    add_edge(conn, "sourced-from", "ev-2", "src-1")
    add_node(conn, "adv-1", "Advisory", {"assessment": "Cleared.", "contamination_confirmed": "none"})
    add_edge(conn, "assessed-by", "src-1", "adv-1")
    add_node(conn, "sub-sched", "Subsystem", {"name": "Scheduler"})
    add_node(conn, "c1", "Concept", {
        "name": "Lock-free Queue",
        "description": "Queue using atomics.",
        "artifact_class": "B",
        "key_properties": ["atomic ops"],
        "tradeoffs": ["ABA"],
        "design_rationale": "Lock contention elimination.",
    })
    add_node(conn, "c2", "Concept", {
        "name": "RCU",
        "description": "Read-Copy-Update mechanism.",
        "artifact_class": "B",
        "key_properties": ["lock-free reads"],
        "tradeoffs": ["grace period"],
        "design_rationale": "Read-heavy optimization.",
    })
    add_edge(conn, "extracted-from", "c1", "ev-1")
    add_edge(conn, "extracted-from", "c2", "ev-2")
    add_edge(conn, "belongs-to", "c1", "sub-sched")
    add_edge(conn, "belongs-to", "c2", "sub-sched")
    add_node(conn, "ki1", "KernelInvariant", {
        "predicate": "lock ordering must be maintained",
        "strength": "hard",
        "scope": "global",
        "artifact_class": "abstracted-mechanism",
    })
    add_edge(conn, "governed-by", "ki1", "c1")
    add_edge(conn, "belongs-to", "ki1", "sub-sched")
    add_node(conn, "pp1", "PerformanceProfile", {
        "metric": "read latency",
        "complexity": "O(1)",
        "best_case": "fast",
        "worst_case": "slow",
        "typical_case": "fast",
        "conditions": "normal",
        "artifact_class": "abstracted-mechanism",
    })
    add_edge(conn, "profiled-by", "pp1", "c1")
    add_edge(conn, "extracted-from", "pp1", "ev-1")
    goal_id = create_optimization_goal(conn, "Min Latency", "Reduce latency", "latency", "minimize")
    link_concept_to_goal(conn, "c1", goal_id, "improves", "strong")
    link_concept_to_goal(conn, "c2", goal_id, "improves", "weak")
    sc_id = create_use_case_scenario(conn, "RT Workload", "Realtime processing", "cpu-bound", "low-latency")
    link_concept_to_scenario(conn, "c1", sc_id, "excellent")
    link_concept_to_scenario(conn, "c2", sc_id, "good")
    create_comparative_analysis(conn, "c1", "c2", "throughput", "Lock-free Queue", "high contention", "2x throughput")
    conn.commit()
    conn.close()

    export_class_b_snapshot(master_path, snap_path)
    srv.init_snapshot(str(snap_path))
    yield snap_path

    if srv._conn is not None:
        srv._conn.close()
        srv._conn = None


def test_get_impact_surface(rich_snapshot_path):
    result = srv.get_impact_surface("c1")
    assert "invariants" in result
    assert "profiles" in result
    assert "goals" in result
    assert "scenarios" in result
    assert len(result["invariants"]) >= 1
    assert len(result["profiles"]) >= 1
    assert len(result["goals"]) >= 1


def test_find_concepts_for_goal(rich_snapshot_path):
    recs = srv.find_concepts_for_goal("Min Latency")
    assert len(recs) == 2
    assert recs[0]["score"] >= recs[1]["score"]
    assert recs[0]["concept"]["id"] == "c1"


def test_compare_concepts(rich_snapshot_path):
    result = srv.compare_concepts("c1", "c2")
    assert "diff" in result
    assert "comparatives" in result
    assert "shared" in result["diff"]
    assert "only_a" in result["diff"]
    assert "only_b" in result["diff"]
    shared_ids = {n["id"] for n in result["diff"]["shared"]}
    assert "sub-sched" in shared_ids
    assert len(result["comparatives"]) >= 1


def test_match_workload(rich_snapshot_path):
    results = srv.match_workload("cpu-bound")
    assert len(results) >= 1
    concepts = results[0]["concepts"]
    assert len(concepts) >= 2
    assert concepts[0]["fitness"] == "excellent"


def test_explore_subgraph(rich_snapshot_path):
    result = srv.explore_subgraph("c1", depth=1)
    assert "nodes" in result
    assert "edges" in result
    node_ids = {n["id"] for n in result["nodes"]}
    assert "c1" in node_ids
    assert "sub-sched" in node_ids


def test_explore_subgraph_depth_cap(rich_snapshot_path):
    """INV-KK-MCP-EXPLORE-DEPTH-CAP: depth > 3 is capped to 3."""
    result_5 = srv.explore_subgraph("c1", depth=5)
    result_3 = srv.explore_subgraph("c1", depth=3)
    assert {n["id"] for n in result_5["nodes"]} == {n["id"] for n in result_3["nodes"]}


def test_search_concepts_all_kinds(rich_snapshot_path):
    """INV-KK-MCP-SEARCH-ALL-KINDS: search finds all Class B kinds."""
    results = srv.search_concepts("latency")
    kinds_found = {r["kind"] for r in results}
    assert "PerformanceProfile" in kinds_found or "OptimizationGoal" in kinds_found
    results_lock = srv.search_concepts("lock ordering")
    kinds_lock = {r["kind"] for r in results_lock}
    assert "KernelInvariant" in kinds_lock


# --- B1: get_concept expanded to ALLOWED_KINDS ---

def test_mcp_get_concept_returns_kernel_invariant(rich_snapshot_path):
    result = srv.get_concept("ki1")
    assert result is not None
    assert result["kind"] == "KernelInvariant"


def test_mcp_get_concept_returns_performance_profile(rich_snapshot_path):
    result = srv.get_concept("pp1")
    assert result is not None
    assert result["kind"] == "PerformanceProfile"


def test_mcp_get_concept_still_rejects_evidence(snapshot_path):
    """Evidence is excluded from snapshot, so get_concept returns None."""
    result = srv.get_concept("ev-1")
    assert result is None


# --- B2: check_path tool ---

def test_mcp_check_path_reachable(rich_snapshot_path):
    result = srv.check_path("c1", "sub-sched")
    assert result["reachable"] is True


def test_mcp_check_path_unreachable(rich_snapshot_path):
    result = srv.check_path("c1", "ki1")
    assert result["reachable"] is False


def test_mcp_check_path_with_edge_kind_filter(rich_snapshot_path):
    result = srv.check_path("c1", "sub-sched", edge_kinds=["belongs-to"])
    assert result["reachable"] is True
    result2 = srv.check_path("c1", "sub-sched", edge_kinds=["governed-by"])
    assert result2["reachable"] is False


def test_mcp_check_path_missing_node(rich_snapshot_path):
    result = srv.check_path("nonexistent", "c1")
    assert result["reachable"] is False


# --- B3: query_edges tool ---

def test_mcp_query_edges_by_kind(rich_snapshot_path):
    results = srv.query_edges("belongs-to")
    assert len(results) >= 2
    assert all(e["kind"] == "belongs-to" for e in results)


def test_mcp_query_edges_returns_list(rich_snapshot_path):
    results = srv.query_edges("governed-by")
    assert isinstance(results, list)
    assert len(results) >= 1


# --- Evidence-layer kind tests (INV-KK-MCP-SEARCH-ALL-KINDS) ---

EVIDENCE_KINDS = frozenset({
    "Problem", "Observation", "Discussion", "Benchmark",
    "Rejection", "Vulnerability", "Fix", "Proposal",
})


def test_evidence_kinds_in_allowed():
    """All 8 evidence-layer kinds must be in ALLOWED_KINDS."""
    from export.exporter import ALLOWED_KINDS
    allowed = set(ALLOWED_KINDS)
    missing = EVIDENCE_KINDS - allowed
    assert not missing, f"Evidence kinds missing from ALLOWED_KINDS: {missing}"


@pytest.fixture
def evidence_snapshot_path(tmp_path):
    """Snapshot with evidence-layer nodes for MCP searchability tests."""
    master_path = tmp_path / "master.db"
    snap_path = tmp_path / "snapshot.db"

    conn = init_db(master_path)
    add_node(conn, "src-1", "Source", {
        "url": "https://example.com/paper.pdf",
        "source_type": "paper",
        "license": "MIT",
    })
    add_node(conn, "ev-1", "Evidence", {"artifact_class": "A", "contamination_level": "weak-copyleft"})
    add_edge(conn, "sourced-from", "ev-1", "src-1")
    add_node(conn, "adv-1", "Advisory", {"assessment": "Cleared.", "contamination_confirmed": "none"})
    add_edge(conn, "assessed-by", "src-1", "adv-1")

    add_node(conn, "sub-sched", "Subsystem", {"name": "Scheduler"})
    add_node(conn, "concept-1", "Concept", {
        "name": "RCU",
        "description": "Read-Copy-Update synchronization mechanism.",
        "artifact_class": "B",
        "key_properties": ["lock-free reads"],
        "tradeoffs": ["grace period latency"],
        "design_rationale": "Read-heavy optimization.",
    })
    add_edge(conn, "extracted-from", "concept-1", "ev-1")
    add_edge(conn, "belongs-to", "concept-1", "sub-sched")

    add_node(conn, "prob-1", "Problem", {
        "title": "RCU grace period stall",
        "description": "Grace period can stall under heavy load.",
        "severity": "high",
        "status": "open",
        "source_date": "2024-01-15",
        "artifact_class": "B",
    })
    add_edge(conn, "identifies-problem", "prob-1", "concept-1")

    add_node(conn, "vuln-1", "Vulnerability", {
        "cve_id": "CVE-2024-9999",
        "title": "Use-after-free in RCU callback",
        "description": "Callback invoked after memory freed.",
        "severity": "critical",
        "cvss_score": 9.8,
        "affected_versions": "5.15-6.1",
        "status": "patched",
        "source_date": "2024-03-01",
        "artifact_class": "B",
    })
    add_edge(conn, "exploits", "vuln-1", "concept-1")

    add_node(conn, "obs-1", "Observation", {
        "claim": "RCU read-side critical sections show zero overhead.",
        "confidence": "high",
        "source_date": "2024-02-10",
        "artifact_class": "B",
    })
    add_edge(conn, "observes", "obs-1", "concept-1")

    conn.commit()
    conn.close()

    export_class_b_snapshot(master_path, snap_path)
    srv.init_snapshot(str(snap_path))
    yield snap_path

    if srv._conn is not None:
        srv._conn.close()
        srv._conn = None


def test_search_returns_evidence_kinds(evidence_snapshot_path):
    """INV-KK-MCP-SEARCH-ALL-KINDS: evidence-layer nodes are searchable."""
    results = srv.search_concepts("grace period")
    kinds_found = {r["kind"] for r in results}
    assert "Problem" in kinds_found, f"Problem not found, got kinds: {kinds_found}"

    results = srv.search_concepts("CVE")
    kinds_found = {r["kind"] for r in results}
    assert "Vulnerability" in kinds_found, f"Vulnerability not found, got kinds: {kinds_found}"

    results = srv.search_concepts("zero overhead")
    kinds_found = {r["kind"] for r in results}
    assert "Observation" in kinds_found, f"Observation not found, got kinds: {kinds_found}"
