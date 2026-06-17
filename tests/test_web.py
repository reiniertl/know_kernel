"""Tests for know_kernel web API â€” ALG-KK-WEB-SERVE.

INV-KK-WEB-READ-ONLY: no write endpoints.
INV-KK-WEB-FULL-ACCESS: all node kinds served to humans.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from graph.engine import add_edge, add_node
from graph.schema import init_db
from web.app import create_app


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "web_test.db"
    conn = init_db(db_path)
    add_node(conn, "concept-1", "Concept", {
        "name": "Lock-free Queue",
        "description": "A queue implementation without locks.",
        "artifact_class": "B",
        "key_properties": ["atomic operations"],
        "tradeoffs": ["ABA problem"],
        "design_rationale": "Eliminates lock contention.",
    })
    add_node(conn, "ev-1", "Evidence", {
        "artifact_class": "A",
        "contamination_level": "weak-copyleft",
    })
    add_node(conn, "sub-1", "Subsystem", {"name": "Scheduler"})
    add_node(conn, "src-1", "Source", {
        "url": "https://example.com/paper.pdf",
        "source_type": "paper",
        "license": "MIT",
    })
    add_edge(conn, "extracted-from", "concept-1", "ev-1")
    add_edge(conn, "sourced-from", "ev-1", "src-1")
    conn.commit()
    conn.close()

    app = create_app(str(db_path))
    with TestClient(app) as c:
        yield c


def test_dashboard_returns_200(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Dashboard" in response.text


def test_concepts_list_returns_all_kinds(client):
    response = client.get("/concepts")
    assert response.status_code == 200
    text = response.text
    assert "Concept" in text
    assert "Evidence" in text
    assert "Source" in text
    assert "Subsystem" in text


def test_concept_detail_returns_node(client):
    response = client.get("/concepts/concept-1")
    assert response.status_code == 200
    assert "concept-1" in response.text
    assert "Concept" in response.text


def test_graph_json_returns_nodes_and_edges(client):
    response = client.get("/graph")
    assert response.status_code == 200
    data = response.json()
    assert "nodes" in data
    assert "edges" in data
    node_ids = {n["id"] for n in data["nodes"]}
    assert "concept-1" in node_ids
    assert "ev-1" in node_ids
    assert len(data["edges"]) >= 2


def test_no_write_endpoints(client):
    assert client.post("/").status_code == 405
    assert client.put("/concepts/concept-1").status_code == 405
    assert client.delete("/concepts/concept-1").status_code == 405


def test_serves_evidence_nodes(client):
    """INV-KK-WEB-FULL-ACCESS: Evidence (Class A) nodes are visible to humans."""
    response = client.get("/graph")
    assert response.status_code == 200
    data = response.json()
    evidence_nodes = [n for n in data["nodes"] if n["kind"] == "Evidence"]
    assert len(evidence_nodes) >= 1
    assert evidence_nodes[0]["id"] == "ev-1"


def test_web_concept_detail_renders_properties(client):
    """INV-KK-WEB-KIND-AWARE-DETAIL: Concept renders key_properties as list, not raw JSON."""
    response = client.get("/concepts/concept-1")
    assert response.status_code == 200
    text = response.text
    assert "<li>atomic operations</li>" in text
    assert "<li>ABA problem</li>" in text
    assert "design_rationale" not in text or "Eliminates lock contention" in text


@pytest.fixture
def rich_client(tmp_path):
    """Client with all node kinds for kind-aware testing."""
    db_path = tmp_path / "rich_test.db"
    conn = init_db(db_path)
    add_node(conn, "c-1", "Concept", {
        "name": "RCU", "description": "Read-Copy-Update", "artifact_class": "B",
        "key_properties": ["grace period"], "tradeoffs": ["memory overhead"],
        "design_rationale": "Optimizes read-heavy workloads.",
    })
    add_node(conn, "kinv-1", "KernelInvariant", {
        "predicate": "No partial updates visible to readers",
        "strength": "safety", "scope": "global", "artifact_class": "B",
    })
    add_node(conn, "fm-1", "FailureMode", {
        "symptom": "Stale data read", "blast_radius": "kernel-wide",
        "recoverability": "self-healing", "artifact_class": "B",
    })
    add_node(conn, "ip-1", "InteractionProtocol", {
        "rule": "No sleeping under spinlock", "ordering": "never-during",
        "violation_mode": "deadlock", "artifact_class": "B",
    })
    add_node(conn, "pp-1", "PerformanceProfile", {
        "metric": "latency", "complexity": "O(1)", "best_case": "1ns",
        "worst_case": "100ns", "typical_case": "10ns", "conditions": "no contention",
        "artifact_class": "B",
    })
    add_node(conn, "ca-1", "CompatibilityAssessment", {
        "synergy": "high", "rationale": "Complementary locking",
        "conditions": "same subsystem", "artifact_class": "B",
    })
    add_node(conn, "cmp-1", "ComparativeAnalysis", {
        "dimension": "throughput", "winner": "RCU",
        "quantitative_delta": "3x faster", "conditions": "read-heavy workload",
        "artifact_class": "B",
    })
    add_node(conn, "og-1", "OptimizationGoal", {
        "name": "Minimize Latency", "description": "Reduce p99",
        "metric": "p99_ms", "direction": "minimize",
    })
    add_node(conn, "ucs-1", "UseCaseScenario", {
        "name": "High-throughput server", "description": "Network stack",
        "workload_type": "high-throughput", "constraints": "bounded memory",
    })
    add_node(conn, "k-1", "Kernel", {
        "name": "Linux", "description": "Monolithic kernel",
        "kernel_type": "monolithic",
    })
    add_node(conn, "sub-1", "Subsystem", {"name": "Scheduler"})
    add_node(conn, "ev-1", "Evidence", {
        "artifact_class": "A", "contamination_level": "weak-copyleft",
    })
    add_node(conn, "src-1", "Source", {
        "url": "https://example.com", "source_type": "paper", "license": "MIT",
    })
    add_node(conn, "adv-1", "Advisory", {"assessment": "approved"})
    add_node(conn, "prop-1", "Proposal", {"name": "Add RCU v2", "description": "Next-gen RCU"})
    add_edge(conn, "governed-by", "kinv-1", "c-1")
    add_edge(conn, "triggered-by", "fm-1", "kinv-1")
    add_edge(conn, "constrains-composition", "ip-1", "c-1")
    add_edge(conn, "belongs-to", "c-1", "sub-1")
    add_edge(conn, "extracted-from", "c-1", "ev-1")
    conn.commit()
    conn.close()
    app = create_app(str(db_path))
    with TestClient(app) as c:
        yield c


def test_web_invariant_detail_renders_strength_badge(rich_client):
    """INV-KK-WEB-KIND-AWARE-DETAIL: KernelInvariant shows strength badge."""
    response = rich_client.get("/concepts/kinv-1")
    assert response.status_code == 200
    text = response.text
    assert "badge-safety" in text
    assert "safety" in text
    assert "<blockquote>" in text


def test_web_failure_mode_detail_renders_blast_radius(rich_client):
    """INV-KK-WEB-KIND-AWARE-DETAIL: FailureMode shows blast_radius badge."""
    response = rich_client.get("/concepts/fm-1")
    assert response.status_code == 200
    text = response.text
    assert "badge-blast-kernel-wide" in text
    assert "badge-recovery-self-healing" in text


def test_web_protocol_detail_renders_ordering(rich_client):
    """INV-KK-WEB-KIND-AWARE-DETAIL: InteractionProtocol shows ordering badge."""
    response = rich_client.get("/concepts/ip-1")
    assert response.status_code == 200
    text = response.text
    assert "never-during" in text
    assert "badge-structural" in text


def test_web_edges_grouped_by_kind(rich_client):
    """INV-KK-WEB-EDGE-GROUPED: edges grouped into labeled sections with count badges."""
    response = rich_client.get("/concepts/c-1")
    assert response.status_code == 200
    text = response.text
    assert "edge-group" in text
    assert "belongs-to" in text
    assert "extracted-from" in text
    assert '<span class="count">' in text


def test_web_all_allowed_kinds_have_detail(rich_client):
    """INV-KK-WEB-KIND-AWARE-DETAIL: no kind renders as raw JSON dump."""
    kind_to_id = {
        "Concept": "c-1", "KernelInvariant": "kinv-1", "FailureMode": "fm-1",
        "InteractionProtocol": "ip-1", "PerformanceProfile": "pp-1",
        "CompatibilityAssessment": "ca-1", "ComparativeAnalysis": "cmp-1",
        "OptimizationGoal": "og-1", "UseCaseScenario": "ucs-1",
        "Kernel": "k-1", "Subsystem": "sub-1", "Evidence": "ev-1",
        "Source": "src-1", "Advisory": "adv-1", "Proposal": "prop-1",
    }
    for kind, nid in kind_to_id.items():
        response = rich_client.get(f"/concepts/{nid}")
        assert response.status_code == 200, f"{kind} ({nid}) returned {response.status_code}"
        text = response.text
        assert "attrs-section" in text or "edge-group" in text, \
            f"{kind} ({nid}) missing structured rendering"
