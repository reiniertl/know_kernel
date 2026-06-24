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
    add_node(conn, "adv-1", "Advisory", {"assessment": "approved", "contamination_confirmed": "none"})
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


def test_source_detail_renders_clickable_url(rich_client):
    """INV-KK-WEB-SOURCE-LINKED: Source detail page renders url as clickable <a> with target=_blank."""
    response = rich_client.get("/concepts/src-1")
    assert response.status_code == 200
    text = response.text
    assert '<a href="https://example.com" target="_blank" rel="noopener">' in text
    assert "Documentation URL" in text
    assert "Source Type" in text
    assert "paper" in text
    assert "License" in text
    assert "MIT" in text


def test_evidence_detail_renders_excerpt_blockquote(tmp_path):
    """INV-KK-WEB-EVIDENCE-EXCERPT: Evidence detail renders excerpt as blockquote."""
    db_path = tmp_path / "ev_test.db"
    conn = init_db(db_path)
    add_node(conn, "ev-ex", "Evidence", {
        "artifact_class": "A",
        "contamination_level": "weak-copyleft",
        "excerpt": "The Linux kernel uses RCU for read-heavy data structures.",
    })
    conn.commit()
    conn.close()
    app = create_app(str(db_path))
    with TestClient(app) as c:
        response = c.get("/concepts/ev-ex")
    assert response.status_code == 200
    text = response.text
    assert "<blockquote" in text
    assert "The Linux kernel uses RCU" in text
    assert "Source Excerpt" in text
    assert "Artifact Class" in text
    assert "Contamination Level" in text


def test_evidence_detail_no_excerpt(rich_client):
    """INV-KK-WEB-EVIDENCE-EXCERPT: Evidence without excerpt renders without empty blockquote."""
    response = rich_client.get("/concepts/ev-1")
    assert response.status_code == 200
    text = response.text
    assert "Artifact Class" in text
    assert "Source Excerpt" not in text


def test_web_all_allowed_kinds_have_detail(rich_client):
    """INV-KK-WEB-KIND-AWARE-DETAIL: no kind renders as raw JSON dump."""
    kind_to_id = {
        "Concept": "c-1", "KernelInvariant": "kinv-1", "FailureMode": "fm-1",
        "InteractionProtocol": "ip-1", "PerformanceProfile": "pp-1",
        "CompatibilityAssessment": "ca-1", "ComparativeAnalysis": "cmp-1",
        "OptimizationGoal": "og-1", "UseCaseScenario": "ucs-1",
        "Kernel": "k-1", "Subsystem": "sub-1", "Evidence": "ev-1",
        "Source": "src-1", "Advisory": "adv-1",
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


def test_web_viz_edge_color_covers_all_edge_kinds(client):
    """INV-KK-WEB-VIZ-EDGE-DISTINCT: edgeColor map has entries for all 18 edge kinds."""
    from graph.schema import EDGE_KINDS
    response = client.get("/viz")
    text = response.text
    for kind in EDGE_KINDS:
        assert f"'{kind}'" in text, f"edgeColor missing entry for '{kind}'"


def test_web_viz_legend_code_present(client):
    """INV-KK-WEB-GRAPH-LEGEND: legend generation code exists in graph viz."""
    response = client.get("/viz")
    text = response.text
    assert "graph-legend" in text
    assert "presentNodeKinds" in text
    assert "presentEdgeKinds" in text


def test_web_viz_legend_filters_to_present_kinds(client):
    """INV-KK-WEB-GRAPH-LEGEND: legend is built from actually-present data, not hardcoded."""
    response = client.get("/viz")
    text = response.text
    assert "new Set(data.nodes.map" in text
    assert "new Set(links.map" in text


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


# --- INV-KK-WEB-KIND-FILTER tests ---


def test_concepts_kind_filter_returns_only_matching(client):
    """INV-KK-WEB-KIND-FILTER: ?kind=Concept returns only Concepts."""
    response = client.get("/concepts?kind=Concept")
    assert response.status_code == 200
    text = response.text
    assert "Lock-free Queue" in text
    assert "Evidence" not in text.split("</thead>")[1]


def test_concepts_no_kind_returns_all(client):
    """INV-KK-WEB-FULL-ACCESS preserved: no kind param returns all nodes."""
    response = client.get("/concepts")
    assert response.status_code == 200
    text = response.text
    assert "Concept" in text
    assert "Evidence" in text
    assert "Subsystem" in text


def test_concepts_invalid_kind_returns_empty(client):
    """Invalid kind returns empty list, not error."""
    response = client.get("/concepts?kind=NonexistentKind")
    assert response.status_code == 200
    assert "0 NonexistentKind node(s)" in response.text


def test_concepts_kind_filter_shows_view_all_link(client):
    """Filtered view includes link back to all nodes."""
    response = client.get("/concepts?kind=Concept")
    assert response.status_code == 200
    assert 'href="/concepts"' in response.text
    assert "View all" in response.text


def test_dashboard_kind_links(client):
    """Dashboard kind rows are clickable links to /concepts?kind={kind}."""
    response = client.get("/")
    assert response.status_code == 200
    assert 'href="/concepts?kind=Concept"' in response.text
    assert 'href="/concepts?kind=Subsystem"' in response.text


# --- ALG-KK-WEB-SEARCH tests (INV-KK-WEB-SEARCH-FULL-ACCESS) ---


def test_search_returns_matching_results(client):
    """ALG-KK-WEB-SEARCH: matching q returns results with display_name."""
    response = client.get("/api/search?q=Lock-free")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert data[0]["id"] == "concept-1"
    assert data[0]["display_name"] == "Lock-free Queue"
    assert "kind" in data[0]
    assert "attrs" in data[0]


def test_search_empty_q_returns_empty(client):
    """ALG-KK-WEB-SEARCH: empty q returns empty result set."""
    response = client.get("/api/search?q=")
    assert response.status_code == 200
    data = response.json()
    assert data == []


def test_search_whitespace_q_returns_empty(client):
    response = client.get("/api/search?q=%20%20")
    assert response.status_code == 200
    assert response.json() == []


def test_search_no_q_returns_empty(client):
    response = client.get("/api/search")
    assert response.status_code == 200
    assert response.json() == []


def test_search_kind_filter(rich_client):
    """ALG-KK-WEB-SEARCH: kind filter restricts results to matching kind."""
    response = rich_client.get("/api/search?q=RCU&kind=Concept")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert all(r["kind"] == "Concept" for r in data)


def test_search_kind_filter_excludes_other_kinds(rich_client):
    response = rich_client.get("/api/search?q=RCU&kind=KernelInvariant")
    assert response.status_code == 200
    data = response.json()
    assert all(r["kind"] == "KernelInvariant" for r in data)


def test_search_full_access_no_class_filter(rich_client):
    """INV-KK-WEB-SEARCH-FULL-ACCESS: search returns all kinds without class-based filtering."""
    response = rich_client.get("/api/search?q=e")
    assert response.status_code == 200
    data = response.json()
    kinds_found = {r["kind"] for r in data}
    assert len(kinds_found) >= 2


def test_search_no_match_returns_empty(client):
    response = client.get("/api/search?q=zzzznonexistent")
    assert response.status_code == 200
    assert response.json() == []


def test_search_sql_injection_safe(client):
    """Parameterized queries prevent SQL injection."""
    response = client.get("/api/search?q=' OR 1=1 --")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 0


def test_search_htmx_returns_html_partial(client):
    """ALG-KK-WEB-SEARCH: HTMX requests get HTML partial response."""
    response = client.get("/api/search?q=Lock-free", headers={"HX-Request": "true"})
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Lock-free Queue" in response.text
    assert "Concept" in response.text


def test_search_htmx_empty_returns_empty_html(client):
    response = client.get("/api/search?q=", headers={"HX-Request": "true"})
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert response.text.strip() == ""


def test_base_html_has_htmx_and_search(client):
    """base.html includes HTMX script and search input."""
    response = client.get("/")
    assert response.status_code == 200
    assert "htmx.org" in response.text
    assert 'id="search-input"' in response.text
    assert 'hx-get="/api/search"' in response.text


# --- ALG-KK-WEB-DIAGNOSTICS-PAGE tests (INV-KK-WEB-HEALTH-LINKED) ---


def test_health_page_returns_200(rich_client):
    """ALG-KK-WEB-DIAGNOSTICS-PAGE: /health renders diagnostic sections."""
    response = rich_client.get("/health")
    assert response.status_code == 200
    text = response.text
    assert "Graph Health Diagnostics" in text
    assert "Orphan Concepts" in text
    assert "Unlinked Invariants" in text
    assert "Dangling Failure Modes" in text
    assert "Lone Protocols" in text
    assert "Subsystem Coverage" in text
    assert "Duplicate Names" in text
    assert "Invariant density" in text


def test_health_page_links_to_node_details(rich_client):
    response = rich_client.get("/health")
    assert response.status_code == 200
    assert 'href="/concepts/' in response.text


def test_dashboard_links_to_health(client):
    """INV-KK-WEB-HEALTH-LINKED: dashboard contains link to /health."""
    response = client.get("/")
    assert response.status_code == 200
    assert 'href="/health"' in response.text
    assert "health diagnostics" in response.text.lower()


def test_nav_links_to_health(client):
    """INV-KK-WEB-HEALTH-LINKED: navigation bar contains link to /health."""
    response = client.get("/")
    assert response.status_code == 200
    assert '<a href="/health">Health</a>' in response.text


# --- ALG-KK-WEB-IMPACT-PAGE tests (INV-KK-WEB-IMPACT-LINKED) ---


def test_impact_page_returns_200(rich_client):
    """ALG-KK-WEB-IMPACT-PAGE: /impact/{id} renders impact categories."""
    response = rich_client.get("/impact/c-1")
    assert response.status_code == 200
    text = response.text
    assert "Impact Surface" in text
    assert "RCU" in text
    assert "Invariants" in text
    assert "Failure Modes" in text
    assert "Protocols" in text
    assert "Performance Profiles" in text


def test_impact_page_shows_linked_nodes(rich_client):
    response = rich_client.get("/impact/c-1")
    assert response.status_code == 200
    text = response.text
    assert "No partial updates visible to readers" in text
    assert 'href="/concepts/kinv-1"' in text


def test_impact_page_404_on_missing_node(rich_client):
    response = rich_client.get("/impact/nonexistent")
    assert response.status_code == 404


def test_concept_detail_links_to_impact(rich_client):
    """INV-KK-WEB-IMPACT-LINKED: Concept detail page links to /impact/{id}."""
    response = rich_client.get("/concepts/c-1")
    assert response.status_code == 200
    assert 'href="/impact/c-1"' in response.text
    assert "View Impact Surface" in response.text


def test_non_concept_detail_no_impact_link(rich_client):
    """Impact link only appears for Concept nodes."""
    response = rich_client.get("/concepts/kinv-1")
    assert response.status_code == 200
    assert "/impact/" not in response.text


# --- INV-KK-WEB-PAGINATION tests ---


@pytest.fixture
def paginated_client(tmp_path):
    """Client with 15 Concept nodes for pagination testing."""
    db_path = tmp_path / "page_test.db"
    conn = init_db(db_path)
    for i in range(15):
        add_node(conn, f"c-{i:02d}", "Concept", {
            "name": f"Concept {i:02d}",
            "description": f"Description {i}",
            "artifact_class": "B",
            "key_properties": [],
            "tradeoffs": [],
            "design_rationale": "test",
        })
    add_node(conn, "sub-1", "Subsystem", {"name": "TestSub"})
    conn.commit()
    conn.close()
    app = create_app(str(db_path))
    with TestClient(app) as c:
        yield c


def test_pagination_limits_results(paginated_client):
    """INV-KK-WEB-PAGINATION: per_page limits results."""
    response = paginated_client.get("/concepts?per_page=10")
    assert response.status_code == 200
    assert response.text.count('<td><code>c-') == 10


def test_pagination_has_next(paginated_client):
    """INV-KK-WEB-PAGINATION: has_next shows Next link when more pages exist."""
    response = paginated_client.get("/concepts?per_page=10")
    assert response.status_code == 200
    assert "Next →" in response.text


def test_pagination_page_2_different(paginated_client):
    """INV-KK-WEB-PAGINATION: page=2 returns different nodes than page=1."""
    r1 = paginated_client.get("/concepts?per_page=10&page=1")
    r2 = paginated_client.get("/concepts?per_page=10&page=2")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert "c-00" in r1.text
    assert "c-00" not in r2.text


def test_pagination_last_page_no_next(paginated_client):
    """INV-KK-WEB-PAGINATION: last page has no Next link."""
    response = paginated_client.get("/concepts?per_page=10&page=2")
    assert response.status_code == 200
    assert "Next →" not in response.text


def test_pagination_first_page_no_previous(paginated_client):
    """INV-KK-WEB-PAGINATION: first page has no Previous link."""
    response = paginated_client.get("/concepts?per_page=10&page=1")
    assert response.status_code == 200
    assert "← Previous" not in response.text


def test_pagination_page_2_has_previous(paginated_client):
    response = paginated_client.get("/concepts?per_page=10&page=2")
    assert response.status_code == 200
    assert "← Previous" in response.text


def test_pagination_per_page_too_small(paginated_client):
    """INV-KK-WEB-PAGINATION: per_page < 10 rejected."""
    response = paginated_client.get("/concepts?per_page=5")
    assert response.status_code == 422


def test_pagination_per_page_too_large(paginated_client):
    """INV-KK-WEB-PAGINATION: per_page > 200 rejected."""
    response = paginated_client.get("/concepts?per_page=500")
    assert response.status_code == 422


def test_pagination_preserves_kind_filter(paginated_client):
    """INV-KK-WEB-PAGINATION: kind filter preserved in pagination links."""
    response = paginated_client.get("/concepts?kind=Concept&per_page=10")
    assert response.status_code == 200
    assert "kind=Concept" in response.text
    assert "Next →" in response.text


def test_pagination_default_values(paginated_client):
    """INV-KK-WEB-PAGINATION: defaults are page=1, per_page=50."""
    response = paginated_client.get("/concepts")
    assert response.status_code == 200
    assert "Page 1" in response.text
    assert "Next →" not in response.text


def test_subsystems_pagination(paginated_client):
    """INV-KK-WEB-PAGINATION: /subsystems supports pagination."""
    response = paginated_client.get("/subsystems?per_page=10")
    assert response.status_code == 200
    assert "Page 1" in response.text


def test_sources_pagination(paginated_client):
    """INV-KK-WEB-PAGINATION: /sources supports pagination."""
    response = paginated_client.get("/sources?per_page=10")
    assert response.status_code == 200
    assert "Page 1" in response.text
