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


def test_concepts_list_shows_display_names(client):
    """INV-KK-WEB-DISPLAY-NAME: list shows human-readable names, not raw IDs as primary text."""
    response = client.get("/concepts")
    assert response.status_code == 200
    text = response.text
    assert "Lock-free Queue" in text
    assert "Scheduler" in text
    assert "https://example.com/paper.pdf" in text


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


def test_web_edge_links_show_names(rich_client):
    """ALG-KK-WEB-KIND-DETAIL: edge links display resolved names, not raw IDs."""
    response = rich_client.get("/concepts/c-1")
    assert response.status_code == 200
    text = response.text
    assert "kinv-1" not in text or "No partial updates" in text, \
        "Edge link should show invariant predicate, not raw ID"
    assert "(KernelInvariant)" in text
    assert "(Subsystem)" in text


def test_web_detail_heading_shows_display_name(rich_client):
    """INV-KK-WEB-DISPLAY-NAME: detail page <h1> shows display_name, not raw ID."""
    response = rich_client.get("/concepts/c-1")
    assert response.status_code == 200
    text = response.text
    assert "<h1>RCU</h1>" in text
    assert "<code>c-1</code>" in text


def test_web_detail_heading_invariant(rich_client):
    """INV-KK-WEB-DISPLAY-NAME: KernelInvariant heading shows truncated predicate."""
    response = rich_client.get("/concepts/kinv-1")
    assert response.status_code == 200
    text = response.text
    assert "<h1>No partial updates visible to readers</h1>" in text
    assert "<code>kinv-1</code>" in text


def test_web_detail_no_duplicate_h2_name(rich_client):
    """Redundant <h2> name headings removed from Concept, OptGoal, UseCase, Kernel."""
    for nid in ("c-1", "og-1", "ucs-1", "k-1"):
        response = rich_client.get(f"/concepts/{nid}")
        assert response.status_code == 200
        assert response.text.count("<h2>") == 0 or "<h2>Attributes</h2>" in response.text or \
            "<h2>Edges</h2>" in response.text, \
            f"{nid} still has a redundant <h2> name heading"


def test_web_graph_viz_has_display_fields(client):
    """INV-KK-WEB-VIZ-TOOLTIP: graph viz JS contains per-kind field resolution."""
    response = client.get("/viz")
    assert response.status_code == 200
    text = response.text
    assert "displayFields" in text
    assert "KernelInvariant" in text
    assert "'predicate'" in text
    assert "'symptom'" in text


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


# --- ALG-KK-WEB-QUERY-ROUTES tests (INV-KK-WEB-QUERY-DELEGATES) ---

def test_web_api_impact_returns_all_categories(rich_client):
    response = rich_client.get("/api/impact/c-1")
    assert response.status_code == 200
    data = response.json()
    assert "invariants" in data
    assert "failure_modes" in data
    assert "protocols" in data
    assert len(data["invariants"]) >= 1


def test_web_api_impact_404_on_missing_node(rich_client):
    response = rich_client.get("/api/impact/nonexistent")
    assert response.status_code == 404


def test_web_api_compare_returns_diff_structure(rich_client):
    response = rich_client.get("/api/compare/c-1/kinv-1")
    assert response.status_code == 200
    data = response.json()
    assert "diff" in data
    assert "comparatives" in data
    diff = data["diff"]
    assert "shared" in diff
    assert "only_a" in diff
    assert "only_b" in diff


def test_web_api_recommendations_returns_list(rich_client):
    response = rich_client.get("/api/recommendations/og-1")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_web_api_match_returns_scenarios(rich_client):
    response = rich_client.get("/api/match?workload_type=high-throughput")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_web_api_match_400_on_missing_param(rich_client):
    response = rich_client.get("/api/match")
    assert response.status_code == 400


# --- ALG-KK-WEB-GRAPH-VIZ tests ---

def test_web_viz_route_returns_html(client):
    response = client.get("/viz")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_web_viz_contains_graph_fetch(client):
    response = client.get("/viz")
    assert "/graph" in response.text


def test_web_viz_contains_d3_reference(client):
    response = client.get("/viz")
    assert "d3" in response.text.lower()


# --- ALG-KK-WEB-DISPLAY-NAME unit tests ---

from web.routes import display_name_for_node


class TestDisplayNameForNode:
    """Unit tests for display_name_for_node (ALG-KK-WEB-DISPLAY-NAME)."""

    def test_concept_uses_name(self):
        assert display_name_for_node("Concept", {"name": "RCU"}, "c-1") == "RCU"

    def test_source_uses_url(self):
        assert display_name_for_node("Source", {"url": "https://example.com"}, "s-1") == "https://example.com"

    def test_source_truncates_at_80(self):
        long_url = "https://example.com/" + "a" * 80
        result = display_name_for_node("Source", {"url": long_url}, "s-1")
        assert len(result) == 83  # 80 + "..."
        assert result.endswith("...")

    def test_source_no_truncation_at_boundary(self):
        url_80 = "x" * 80
        assert display_name_for_node("Source", {"url": url_80}, "s-1") == url_80

    def test_evidence_uses_description(self):
        assert display_name_for_node("Evidence", {"description": "Sample evidence"}, "ev-abc12345") == "Sample evidence"

    def test_evidence_fallback_without_description(self):
        assert display_name_for_node("Evidence", {}, "ev-abc12345") == "Evidence abc12345"

    def test_evidence_fallback_empty_description(self):
        assert display_name_for_node("Evidence", {"description": ""}, "ev-abc12345") == "Evidence abc12345"

    def test_advisory_uses_assessment(self):
        assert display_name_for_node("Advisory", {"assessment": "approved"}, "adv-1") == "approved"

    def test_advisory_truncates_at_60(self):
        long_text = "a" * 70
        result = display_name_for_node("Advisory", {"assessment": long_text}, "adv-1")
        assert len(result) == 63  # 60 + "..."
        assert result.endswith("...")

    def test_subsystem_uses_name(self):
        assert display_name_for_node("Subsystem", {"name": "Scheduler"}, "sub-1") == "Scheduler"

    def test_proposal_uses_name(self):
        assert display_name_for_node("Proposal", {"name": "Add RCU v2"}, "prop-1") == "Add RCU v2"

    def test_kernel_invariant_uses_predicate(self):
        assert display_name_for_node("KernelInvariant", {"predicate": "No stale reads"}, "kinv-1") == "No stale reads"

    def test_kernel_invariant_truncates_at_60(self):
        long_pred = "p" * 65
        result = display_name_for_node("KernelInvariant", {"predicate": long_pred}, "kinv-1")
        assert len(result) == 63
        assert result.endswith("...")

    def test_failure_mode_uses_symptom(self):
        assert display_name_for_node("FailureMode", {"symptom": "Deadlock"}, "fm-1") == "Deadlock"

    def test_interaction_protocol_uses_rule(self):
        assert display_name_for_node("InteractionProtocol", {"rule": "No sleep under spinlock"}, "ip-1") == "No sleep under spinlock"

    def test_performance_profile_uses_metric(self):
        assert display_name_for_node("PerformanceProfile", {"metric": "latency"}, "pp-1") == "latency"

    def test_performance_profile_truncates_at_40(self):
        long_metric = "m" * 50
        result = display_name_for_node("PerformanceProfile", {"metric": long_metric}, "pp-1")
        assert len(result) == 43  # 40 + "..."
        assert result.endswith("...")

    def test_compatibility_assessment_uses_synergy(self):
        assert display_name_for_node("CompatibilityAssessment", {"synergy": "high"}, "ca-1") == "high"

    def test_optimization_goal_uses_name(self):
        assert display_name_for_node("OptimizationGoal", {"name": "Min Latency"}, "og-1") == "Min Latency"

    def test_use_case_scenario_uses_name(self):
        assert display_name_for_node("UseCaseScenario", {"name": "HPC Server"}, "ucs-1") == "HPC Server"

    def test_comparative_analysis_uses_dimension(self):
        assert display_name_for_node("ComparativeAnalysis", {"dimension": "throughput"}, "cmp-1") == "throughput"

    def test_kernel_uses_name(self):
        assert display_name_for_node("Kernel", {"name": "Linux"}, "k-1") == "Linux"

    def test_missing_attrs_falls_back_to_id(self):
        assert display_name_for_node("Concept", {}, "c-1") == "c-1"

    def test_none_field_falls_back_to_id(self):
        assert display_name_for_node("Concept", {"name": None}, "c-1") == "c-1"

    def test_whitespace_only_falls_back_to_id(self):
        assert display_name_for_node("Concept", {"name": "   "}, "c-1") == "c-1"

    def test_unknown_kind_falls_back_to_id(self):
        assert display_name_for_node("UnknownKind", {"name": "foo"}, "unk-1") == "unk-1"

    def test_deterministic(self):
        a = display_name_for_node("Concept", {"name": "RCU"}, "c-1")
        b = display_name_for_node("Concept", {"name": "RCU"}, "c-1")
        assert a == b
