"""Tests for know_kernel web API — ALG-KK-WEB-SERVE.

INV-KK-WEB-FULL-ACCESS: all node kinds served to humans.
INV-KK-WEB-MUTATION-ALLOWLISTED: every mutating route sits behind an allowlisted
prefix, asserted by test_every_mutating_route_is_on_the_allowlist.

The read-only invariant line that used to sit here made the same false claim as
the one removed from src/web/routes.py: this suite has exercised write endpoints
since the review API landed.
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
        "source_type": "preprint",
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
        "url": "https://example.com", "source_type": "preprint", "license": "MIT",
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
    assert "preprint" in text
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


def test_concept_detail_renders_code_examples(tmp_path):
    """INV-KK-WEB-CODE-DISPLAY: Concept with code_examples renders pre/code blocks with source link."""
    db_path = tmp_path / "code_test.db"
    conn = init_db(db_path)
    add_node(conn, "c-code", "Concept", {
        "name": "Test Concept",
        "description": "A test.",
        "artifact_class": "B",
        "key_properties": [],
        "tradeoffs": [],
        "design_rationale": "test",
        "code_examples": [
            {"label": "Basic usage", "language": "c", "code": "int x = 1;", "source_url": "https://example.com/src"},
        ],
    })
    conn.commit()
    conn.close()
    app = create_app(str(db_path))
    with TestClient(app) as c:
        response = c.get("/concepts/c-code")
    assert response.status_code == 200
    text = response.text
    assert "Code Examples" in text
    assert "Basic usage" in text
    assert "int x = 1;" in text
    assert '<code class="language-c">' in text
    assert '<a href="https://example.com/src"' in text
    assert "source" in text


def test_concept_detail_code_examples_no_source_url(tmp_path):
    """INV-KK-WEB-CODE-DISPLAY: Code example without source_url renders without broken link."""
    db_path = tmp_path / "code_test2.db"
    conn = init_db(db_path)
    add_node(conn, "c-nosrc", "Concept", {
        "name": "No Source", "description": "test", "artifact_class": "B",
        "key_properties": [], "tradeoffs": [], "design_rationale": "test",
        "code_examples": [{"label": "Inline", "language": "c", "code": "return 0;"}],
    })
    conn.commit()
    conn.close()
    app = create_app(str(db_path))
    with TestClient(app) as c:
        response = c.get("/concepts/c-nosrc")
    assert response.status_code == 200
    text = response.text
    assert "Inline" in text
    assert "return 0;" in text
    assert "source" not in text.split("Code Examples")[1].split("</div>")[0] or \
           'href="None"' not in text


def test_concept_detail_no_code_examples(rich_client):
    """INV-KK-WEB-CODE-DISPLAY: Concept without code_examples renders normally."""
    response = rich_client.get("/concepts/c-1")
    assert response.status_code == 200
    assert "Code Examples" not in response.text


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


# --- INV-KK-WEB-RELATED-CODE / INV-KK-WEB-RELATED-CODE-ABSENT tests ---


def test_invariant_detail_shows_related_code(tmp_path):
    """INV-KK-WEB-RELATED-CODE: KernelInvariant shows code from connected Concept."""
    db_path = tmp_path / "rel_code.db"
    conn = init_db(db_path)
    add_node(conn, "c-1", "Concept", {
        "name": "Spinlock", "description": "test", "artifact_class": "B",
        "key_properties": [], "tradeoffs": [], "design_rationale": "test",
        "code_examples": [{"label": "spin_lock", "language": "c", "code": "spin_lock(&lock);"}],
    })
    add_node(conn, "kinv-1", "KernelInvariant", {
        "predicate": "No sleeping under spinlock", "strength": "safety",
        "scope": "global", "artifact_class": "B",
    })
    add_edge(conn, "governed-by", "kinv-1", "c-1")
    conn.commit()
    conn.close()
    app = create_app(str(db_path))
    with TestClient(app) as c:
        response = c.get("/concepts/kinv-1")
    assert response.status_code == 200
    text = response.text
    assert "Related Code" in text
    assert "spin_lock" in text
    assert "Spinlock" in text
    assert 'href="/concepts/c-1"' in text


def test_invariant_no_related_code_when_concept_has_none(tmp_path):
    """INV-KK-WEB-RELATED-CODE-ABSENT: No Related Code when connected concept has no examples."""
    db_path = tmp_path / "rel_no_code.db"
    conn = init_db(db_path)
    add_node(conn, "c-1", "Concept", {
        "name": "Test", "description": "test", "artifact_class": "B",
        "key_properties": [], "tradeoffs": [], "design_rationale": "test",
    })
    add_node(conn, "kinv-1", "KernelInvariant", {
        "predicate": "test", "strength": "safety",
        "scope": "global", "artifact_class": "B",
    })
    add_edge(conn, "governed-by", "kinv-1", "c-1")
    conn.commit()
    conn.close()
    app = create_app(str(db_path))
    with TestClient(app) as c:
        response = c.get("/concepts/kinv-1")
    assert response.status_code == 200
    assert "Related Code" not in response.text


def test_protocol_shows_related_code(tmp_path):
    """INV-KK-WEB-RELATED-CODE: InteractionProtocol shows code from connected Concept."""
    db_path = tmp_path / "ip_rel_code.db"
    conn = init_db(db_path)
    add_node(conn, "c-1", "Concept", {
        "name": "Spinlock", "description": "test", "artifact_class": "B",
        "key_properties": [], "tradeoffs": [], "design_rationale": "test",
        "code_examples": [{"label": "lock", "language": "c", "code": "spin_lock(&l);"}],
    })
    add_node(conn, "ip-1", "InteractionProtocol", {
        "rule": "No sleep under spinlock", "ordering": "never-during",
        "violation_mode": "deadlock", "artifact_class": "B",
    })
    add_edge(conn, "constrains-composition", "ip-1", "c-1")
    conn.commit()
    conn.close()
    app = create_app(str(db_path))
    with TestClient(app) as c:
        response = c.get("/concepts/ip-1")
    assert response.status_code == 200
    text = response.text
    assert "Related Code" in text
    assert "spin_lock" in text


# --- INV-KK-WEB-RELATED-CODE-TWOHOP tests ---


def test_failure_mode_shows_related_code_via_invariant(tmp_path):
    """INV-KK-WEB-RELATED-CODE-TWOHOP: FailureMode shows code from Concept via KernelInvariant hop."""
    db_path = tmp_path / "fm_rel_code.db"
    conn = init_db(db_path)
    add_node(conn, "c-1", "Concept", {
        "name": "RCU", "description": "test", "artifact_class": "B",
        "key_properties": [], "tradeoffs": [], "design_rationale": "test",
        "code_examples": [{"label": "rcu_lock", "language": "c", "code": "rcu_read_lock();"}],
    })
    add_node(conn, "kinv-1", "KernelInvariant", {
        "predicate": "test", "strength": "safety",
        "scope": "global", "artifact_class": "B",
    })
    add_node(conn, "fm-1", "FailureMode", {
        "symptom": "Stale read", "blast_radius": "local",
        "recoverability": "self-healing", "artifact_class": "B",
    })
    add_edge(conn, "governed-by", "kinv-1", "c-1")
    add_edge(conn, "triggered-by", "fm-1", "kinv-1")
    conn.commit()
    conn.close()
    app = create_app(str(db_path))
    with TestClient(app) as c:
        response = c.get("/concepts/fm-1")
    assert response.status_code == 200
    text = response.text
    assert "Related Code" in text
    assert "rcu_read_lock" in text
    assert 'href="/concepts/c-1"' in text
    assert "RCU" in text


def test_failure_mode_no_related_code_when_no_concept_code(tmp_path):
    """INV-KK-WEB-RELATED-CODE-TWOHOP: No Related Code when two-hop Concept has no examples."""
    db_path = tmp_path / "fm_no_code.db"
    conn = init_db(db_path)
    add_node(conn, "c-1", "Concept", {
        "name": "Test", "description": "test", "artifact_class": "B",
        "key_properties": [], "tradeoffs": [], "design_rationale": "test",
    })
    add_node(conn, "kinv-1", "KernelInvariant", {
        "predicate": "test", "strength": "safety",
        "scope": "global", "artifact_class": "B",
    })
    add_node(conn, "fm-1", "FailureMode", {
        "symptom": "Stale read", "blast_radius": "local",
        "recoverability": "self-healing", "artifact_class": "B",
    })
    add_edge(conn, "governed-by", "kinv-1", "c-1")
    add_edge(conn, "triggered-by", "fm-1", "kinv-1")
    conn.commit()
    conn.close()
    app = create_app(str(db_path))
    with TestClient(app) as c:
        response = c.get("/concepts/fm-1")
    assert response.status_code == 200
    assert "Related Code" not in response.text


# --- ALG-KK-WEB-DISPLAY-NAME: evidence-layer kinds ---


def test_display_name_problem():
    from web.routes import display_name_for_node
    assert display_name_for_node("Problem", {"title": "Grace period latency"}, "prob-123") == "Grace period latency"


def test_display_name_vulnerability():
    from web.routes import display_name_for_node
    assert display_name_for_node("Vulnerability", {"cve_id": "CVE-2026-99999"}, "vuln-123") == "CVE-2026-99999"


def test_display_name_vulnerability_no_cve():
    from web.routes import display_name_for_node
    result = display_name_for_node("Vulnerability", {"cve_id": "", "title": "Use-after-free in RCU"}, "vuln-123")
    assert result == "Use-after-free in RCU"


def test_display_name_proposal():
    from web.routes import display_name_for_node
    assert display_name_for_node("Proposal", {"name": "NUMA batching"}, "prop-123") == "NUMA batching"


def test_display_name_observation():
    from web.routes import display_name_for_node
    long_claim = "A" * 80
    result = display_name_for_node("Observation", {"claim": long_claim}, "obs-123")
    assert result == "A" * 60 + "..."


def test_display_name_fix():
    from web.routes import display_name_for_node
    long_title = "B" * 80
    result = display_name_for_node("Fix", {"title": long_title}, "fix-123")
    assert result == "B" * 60 + "..."


# --- Radar, Vulns, API endpoints (Stage 16) ---


@pytest.fixture
def radar_vuln_client(tmp_path):
    """Client with subsystems, concepts, vulns, fixes, and opportunities for radar/vuln testing."""
    db_path = tmp_path / "radar_vuln.db"
    conn = init_db(db_path)
    add_node(conn, "sub-sched", "Subsystem", {"name": "Scheduler"})
    add_node(conn, "sub-mm", "Subsystem", {"name": "Memory Management"})
    add_node(conn, "sub-empty", "Subsystem", {"name": "Empty Subsystem"})
    add_node(conn, "concept-rcu", "Concept", {
        "name": "RCU", "description": "Read-Copy-Update", "artifact_class": "B",
        "key_properties": [], "tradeoffs": [], "design_rationale": "test",
    })
    add_node(conn, "concept-slab", "Concept", {
        "name": "SLAB Allocator", "description": "Slab allocation", "artifact_class": "B",
        "key_properties": [], "tradeoffs": [], "design_rationale": "test",
    })
    add_edge(conn, "belongs-to", "concept-rcu", "sub-sched")
    add_edge(conn, "belongs-to", "concept-slab", "sub-mm")
    add_node(conn, "vuln-1", "Vulnerability", {
        "cve_id": "CVE-2026-0001", "title": "Use-after-free in RCU",
        "cvss_score": 9.8, "severity": "critical",
        "description": "A critical use-after-free vulnerability in RCU subsystem.",
        "affected_versions": "6.1-6.5", "status": "open", "source_date": "2026-06-15",
        "artifact_class": "B",
    })
    add_node(conn, "vuln-2", "Vulnerability", {
        "cve_id": "CVE-2026-0002", "title": "Info leak in slab",
        "cvss_score": 5.5, "severity": "medium",
        "description": "Information disclosure in SLAB allocator.",
        "affected_versions": "6.3-6.5", "status": "open", "source_date": "2026-06-10",
        "artifact_class": "B",
    })
    add_edge(conn, "exploits", "vuln-1", "concept-rcu")
    add_edge(conn, "exploits", "vuln-2", "concept-slab")
    add_node(conn, "fix-1", "Fix", {
        "title": "Fix RCU grace period", "commit_hash": "abc123",
        "fix_type": "patch", "source_date": "2026-06-18", "artifact_class": "B",
    })
    add_edge(conn, "patches", "fix-1", "concept-rcu")
    add_node(conn, "opp-rcu", "Opportunity", {
        "title": "Investigate RCU latency",
        "description": "High-frontier opportunity",
        "confidence": 0.5, "frontier_score": 15.0,
        "artifact_class": "B",
    })
    add_edge(conn, "opportunity-for", "opp-rcu", "concept-rcu")
    add_node(conn, "prob-rcu-1", "Problem", {
        "title": "RCU grace period stalls", "description": "Grace periods stall under load",
        "severity": "high", "status": "open", "source_date": "2026-06-15", "artifact_class": "B",
    })
    add_edge(conn, "supported-by", "opp-rcu", "prob-rcu-1")
    add_node(conn, "concept-dep", "Concept", {
        "name": "CFS", "description": "Completely Fair Scheduler", "artifact_class": "B",
        "key_properties": [], "tradeoffs": [], "design_rationale": "test",
    })
    add_edge(conn, "prerequisite", "concept-dep", "concept-rcu")
    # KernelInvariant for concept-rcu
    add_node(conn, "kinv-rcu", "KernelInvariant", {
        "predicate": "RCU read-side critical sections must not sleep",
        "strength": "strong",
        "scope": "all RCU flavors",
        "artifact_class": "B",
    })
    add_edge(conn, "governed-by", "kinv-rcu", "concept-rcu")
    # Fix for vuln-1
    add_edge(conn, "fixes", "fix-1", "vuln-1")
    add_node(conn, "trend-slab", "Trend", {
        "title": "SLAB convergence", "description": "Trend for slab",
        "strength": 3, "window_start": "2026-06-01", "window_end": "2026-06-20",
        "artifact_class": "B",
    })
    add_edge(conn, "trend-about", "trend-slab", "concept-slab")
    conn.commit()
    conn.close()
    app = create_app(str(db_path))
    with TestClient(app) as c:
        yield c


# --- ALG-KK-WEB-RADAR tests ---
#
# /radar was created on 2026-06-29 (eb1a7d0) as a subsystem VULNERABILITY radar:
# heading "Subsystem Radar", one row per subsystem carrying vuln and fix counts. It
# was rewritten on 2026-07-15 (534d725, then 5f08345) into a research radar: papers
# grouped by subsystem, then by concept, with a paper drill-down. These tests were
# last touched on 2026-07-09, six days before that rewrite, and until now still
# asserted the old semantics against radar_vuln_client -- a fixture holding no Source
# and no Evidence nodes at all. The page correctly rendered "0 research papers across
# 0 subsystems" and the assertions searched an empty table, so they failed while the
# page was working. Rewritten below against the current semantics, with a fixture
# that supplies the chain the route actually queries.


@pytest.fixture
def research_radar_client(tmp_path):
    """Client whose graph carries the chain /radar traverses.

    The route joins Concept -extracted-from-> Evidence -sourced-from-> Source, and
    keeps only Sources whose source_type is a paper kind. Scheduler gets two papers
    and Memory Management one, so subsystem ordering (by descending paper count) is
    deterministic. Empty Subsystem has no concept and must not be rendered.
    """
    db_path = tmp_path / "research_radar.db"
    conn = init_db(db_path)

    add_node(conn, "sub-sched", "Subsystem", {"name": "Scheduler"})
    add_node(conn, "sub-mm", "Subsystem", {"name": "Memory Management"})
    add_node(conn, "sub-empty", "Subsystem", {"name": "Empty Subsystem"})

    def _concept(node_id, name, description):
        add_node(conn, node_id, "Concept", {
            "name": name,
            "description": description,
            "artifact_class": "B",
            "key_properties": [],
            "tradeoffs": [],
            "design_rationale": "test",
        })

    _concept("concept-rcu", "RCU", "Read-Copy-Update for scheduler latency")
    _concept("concept-slab", "SLAB Allocator", "Slab allocation for memory management")
    add_edge(conn, "belongs-to", "concept-rcu", "sub-sched")
    add_edge(conn, "belongs-to", "concept-slab", "sub-mm")

    papers = [
        ("src-rcu-1", "ev-rcu-1", "concept-rcu", "Scalable RCU Grace Periods", "2026-06-01"),
        ("src-rcu-2", "ev-rcu-2", "concept-rcu", "RCU Under Memory Pressure", "2026-06-20"),
        ("src-slab-1", "ev-slab-1", "concept-slab", "SLAB Fragmentation Revisited", "2026-05-10"),
    ]
    for source_id, evidence_id, concept_id, title, published in papers:
        add_node(conn, source_id, "Source", {
            "url": f"https://example.com/{source_id}.pdf",
            "source_type": "preprint",
            "license": "MIT",
            "title": title,
            "published_date": published,
        })
        add_node(conn, evidence_id, "Evidence", {
            "artifact_class": "A",
            "contamination_level": "weak-copyleft",
        })
        add_edge(conn, "sourced-from", evidence_id, source_id)
        add_edge(conn, "extracted-from", concept_id, evidence_id)

    conn.commit()
    conn.close()

    app = create_app(str(db_path))
    with TestClient(app) as c:
        yield c


def test_radar_returns_200(research_radar_client):
    response = research_radar_client.get("/radar")
    assert response.status_code == 200
    assert "Research Radar" in response.text


def test_radar_shows_subsystems_with_concepts(research_radar_client):
    """Shows every subsystem reached by at least one paper, and no others."""
    response = research_radar_client.get("/radar")
    assert response.status_code == 200
    text = response.text
    assert "Scheduler" in text
    assert "Memory Management" in text
    assert "Empty Subsystem" not in text


def test_radar_shows_paper_counts(research_radar_client):
    """Per-subsystem paper counts, and the total across subsystems.

    Replaces test_radar_shows_vuln_and_fix_counts: the current radar reports papers,
    not vulnerabilities. Scheduler has two papers via concept-rcu, Memory Management
    one via concept-slab.
    """
    response = research_radar_client.get("/radar")
    text = response.text
    assert "3 research papers across 2 subsystems" in text

    sched_row = text[text.find("Scheduler"):text.find("Memory Management")]
    assert "<td>2</td>" in sched_row, sched_row


def test_radar_nests_papers_under_their_concept(research_radar_client):
    """The drill-down carries the paper titles and links to /paper/{source_id}."""
    text = research_radar_client.get("/radar").text
    assert "RCU" in text
    assert "SLAB Allocator" in text
    assert "Scalable RCU Grace Periods" in text
    assert "/paper/src-rcu-1" in text


def test_dashboard_links_to_radar(radar_vuln_client):
    response = radar_vuln_client.get("/")
    assert 'href="/radar"' in response.text


def test_nav_has_radar_link(radar_vuln_client):
    response = radar_vuln_client.get("/")
    assert 'href="/radar"' in response.text
    assert ">Radar<" in response.text


# --- ALG-KK-WEB-VENUES / VENUE-EDIT / VENUE-MERGE tests ---


@pytest.fixture
def venue_client(tmp_path):
    """Graph carrying the real collision pairs plus venue-less Sources.

    Mirrors the shape of the live corpus: several raw spellings that must
    collapse to one canonical venue (INV-KK-VENUE-NORMALISED), and Sources with
    no venue at all, which must still be rendered.
    """
    from ingest.venue_store import set_venue

    db_path = tmp_path / "venue_web.db"
    conn = init_db(db_path)

    def _src(sid, venue, source_type="preprint", date="2026-06-01"):
        add_node(conn, sid, "Source", {
            "url": f"https://example.com/{sid}.pdf",
            "source_type": source_type,
            "license": "MIT",
            "title": f"Paper {sid}",
            "published_date": date,
        })
        if venue:
            set_venue(conn, sid, venue, "conference")

    _src("src-osdi-1", "OSDI 2026")
    _src("src-osdi-2", "OSDI")
    _src("src-osdi-3", "OSDI 2025")
    _src("src-sosp-1", "SOSP")
    _src("src-sosp-2", "SOSP 2025")
    # Two venue-less Sources with distinct source_types.
    _src("src-none-1", None, source_type="kernel-doc")
    _src("src-none-2", None, source_type="discourse")

    conn.commit()
    conn.close()
    app = create_app(str(db_path))
    with TestClient(app) as c:
        yield c


def test_venues_returns_200(venue_client):
    response = venue_client.get("/venues")
    assert response.status_code == 200
    assert "Venues" in response.text


def test_venues_groups_by_canonical_name(venue_client):
    """The three OSDI spellings are one entry, not three."""
    text = venue_client.get("/venues").text
    assert text.count(">OSDI<") == 1
    assert text.count(">SOSP<") == 1
    assert "OSDI 2026" not in text
    assert "SOSP 2025" not in text


def test_venues_paper_counts_match_the_collapsed_groups(venue_client):
    text = venue_client.get("/venues").text
    osdi = text[text.find(">OSDI<"):]
    assert "<td>3</td>" in osdi[:200], osdi[:200]


def test_venues_nests_papers_under_their_venue(venue_client):
    text = venue_client.get("/venues").text
    assert "/paper/src-osdi-1" in text
    assert "/paper/src-sosp-1" in text


def test_venues_shows_the_no_venue_bucket(venue_client):
    """The venue-less Sources are surfaced, not silently dropped."""
    text = venue_client.get("/venues").text
    assert "No venue recorded" in text
    assert "/paper/src-none-1" in text
    assert "/paper/src-none-2" in text


def test_venues_query_count_is_bounded(venue_client):
    """INV-KK-WEB-QUERY-BOUNDED: a fixed number of queries, not per-paper."""
    conn = venue_client.app.state.conn
    seen = []
    conn.set_trace_callback(seen.append)
    try:
        assert venue_client.get("/venues").status_code == 200
    finally:
        conn.set_trace_callback(None)
    selects = [q for q in seen if q.strip().upper().startswith("SELECT")]
    assert len(selects) <= 3, selects


def test_sources_route_is_gone(venue_client):
    assert venue_client.get("/sources").status_code == 404


def test_venue_edit_sets_a_venue(venue_client):
    response = venue_client.put("/api/venue/src-none-1", json={"venue": "NSDI 2025"})
    assert response.status_code == 200
    assert response.json()["venue"] == "NSDI"
    assert "NSDI" in venue_client.get("/venues").text


def test_venue_edit_404_for_unknown_source(venue_client):
    assert venue_client.put("/api/venue/src-nope", json={"venue": "NSDI"}).status_code == 404


def test_venue_edit_422_for_empty_venue(venue_client):
    assert venue_client.put("/api/venue/src-none-1", json={"venue": "  "}).status_code == 422


def test_venue_edit_422_for_missing_field(venue_client):
    assert venue_client.put("/api/venue/src-none-1", json={}).status_code == 422


def test_venue_merge_requires_admin(venue_client):
    """INV-KK-VENUE-MUTATION-AUTHORISED: no user resolved means no merge."""
    response = venue_client.post("/api/venue/merge", json={"from": "SOSP", "to": "OSDI"})
    assert response.status_code == 403


def test_venue_merge_succeeds_for_an_admin(tmp_path):
    from ingest.venue_store import set_venue

    db_path = tmp_path / "venue_admin.db"
    conn = init_db(db_path)
    for sid, venue in (("src-1", "OSDI"), ("src-2", "SOSP")):
        add_node(conn, sid, "Source", {
            "url": f"https://example.com/{sid}", "source_type": "preprint",
            "license": "MIT", "title": sid,
        })
        set_venue(conn, sid, venue, "conference")
    conn.commit()
    conn.close()

    app = create_app(str(db_path))

    @app.middleware("http")
    async def _as_admin(request, call_next):
        request.state.user = {"username": "root", "role": "admin"}
        return await call_next(request)

    with TestClient(app) as c:
        response = c.post("/api/venue/merge", json={"from": "SOSP", "to": "OSDI"})
        assert response.status_code == 200, response.text
        assert response.json()["rows"] == 1
        text = c.get("/venues").text
        assert ">SOSP<" not in text


def test_every_mutating_route_is_on_the_allowlist(venue_client):
    """INV-KK-WEB-MUTATION-ALLOWLISTED, checked against the live router."""
    from web.routes import WEB_MUTATION_ALLOWLIST

    offenders = []
    for route in venue_client.app.router.routes:
        methods = getattr(route, "methods", set()) or set()
        if methods & {"POST", "PUT", "DELETE"}:
            path = getattr(route, "path", "")
            if not path.startswith(WEB_MUTATION_ALLOWLIST):
                offenders.append(f"{sorted(methods)} {path}")
    assert not offenders, offenders


def test_every_spec_id_cited_in_src_web_exists_in_the_dag():
    """No dangling citations from src/web/ (WP7 guard).

    Docstring citations are this project's only spec-to-code link, and they had
    drifted badly: 246 of 316 KK ids cited across src/ named no node. This test
    pins the web layer at zero, so a citation of a node that was never authored,
    or that has since been removed, fails here instead of quietly rotting.

    Skipped when the RIL is unavailable (no node, or no built spec.db), because
    the spec graph is a local cache rather than a checked-in artifact.
    """
    import json
    import pathlib
    import re
    import subprocess

    try:
        proc = subprocess.run(
            ["npm", "run", "ril", "--", "query", "nodes", "--json"],
            capture_output=True, text=True, timeout=120,
            cwd=pathlib.Path(__file__).resolve().parents[1],
        )
    except (OSError, subprocess.TimeoutExpired):  # pragma: no cover
        pytest.skip("RIL unavailable")
    start = proc.stdout.find("{")
    if proc.returncode != 0 or start == -1:  # pragma: no cover
        pytest.skip("RIL returned no node set")

    payload = json.loads(proc.stdout[start:])
    values = list(payload.values()) if isinstance(payload, dict) else payload
    existing = {v["id"] for v in values if isinstance(v, dict) and "id" in v}
    if not existing:  # pragma: no cover
        pytest.skip("empty spec graph")

    token = re.compile(r"\b(?:INV|ALG|IFC|MOD|ERR|ANN)-KK-[A-Z0-9-]+[A-Z0-9]")
    web = pathlib.Path(__file__).resolve().parents[1] / "src" / "web"
    dangling: dict[str, list[str]] = {}
    for path in sorted(web.rglob("*")):
        if not path.is_file() or path.suffix not in (".py", ".html"):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for cited in token.findall(line):
                if cited not in existing:
                    dangling.setdefault(cited, []).append(f"{path.name}:{lineno}")

    assert not dangling, "spec ids cited in src/web/ that name no node: " + json.dumps(
        dangling, indent=2, sort_keys=True
    )


# --- Paper summary + completeness on the paper page ---
#
# IFC-KK-PAPER-SUMMARY, IFC-KK-PAPER-COMPLETENESS, ALG-KK-WEB-SUMMARY-EDIT.


def _summary_paper(conn, sid="src-p1", abstract="An abstract about kernel paging."):
    add_node(conn, sid, "Source", {
        "url": f"https://example.com/{sid}.pdf",
        "source_type": "preprint",
        "license": "MIT",
        "title": f"Paper {sid}",
        "published_date": "2026-06-01",
        "abstract": abstract,
    })
    return sid


@pytest.fixture
def summary_client(tmp_path):
    """A paper with no summary and no verdict — the empty case."""
    db_path = tmp_path / "summary_web.db"
    conn = init_db(db_path)
    _summary_paper(conn)
    conn.commit()
    conn.close()
    app = create_app(str(db_path))

    @app.middleware("http")
    async def _as_user(request, call_next):
        request.state.user = {"username": "kate", "role": "user", "reviewer": "kate"}
        return await call_next(request)

    with TestClient(app) as c:
        yield c


def _build_paper_db(tmp_path, name, state=None, text="A model wrote this summary of the paper.",
                    with_verdict=True, concepts=0):
    from ingest.paper_completeness import recompute_paper
    from ingest.paper_summary import set_summary

    db_path = tmp_path / name
    conn = init_db(db_path)
    sid = _summary_paper(conn)
    if state is not None:
        reviewer = "kate" if state in ("human-reviewed", "human-authored") else ""
        set_summary(conn, sid, "" if state == "absent" else text, state, model="claude-sonnet-5",
                    reviewed_by=reviewer)
    for i in range(concepts):
        add_node(conn, f"ev-{i}", "Evidence", {"artifact_class": "A", "contamination_level": "L0"})
        add_node(conn, f"c-{i}", "Concept", {
            "name": f"Concept {i}", "description": "d", "artifact_class": "B",
            "key_properties": [], "tradeoffs": [], "design_rationale": "r",
        })
        add_edge(conn, "sourced-from", f"ev-{i}", sid)
        add_edge(conn, "extracted-from", f"c-{i}", f"ev-{i}")
    if with_verdict:
        recompute_paper(conn, sid)
    conn.commit()
    conn.close()
    return db_path, sid


def _client_for(db_path):
    app = create_app(str(db_path))

    @app.middleware("http")
    async def _as_user(request, call_next):
        request.state.user = {"username": "kate", "role": "user", "reviewer": "kate"}
        return await call_next(request)

    return TestClient(app)


def test_paper_page_omits_the_summary_text_when_there_is_none(summary_client):
    body = summary_client.get("/paper/src-p1").text
    assert body.count("No summary yet.") == 1
    assert "A model wrote this" not in body


def test_summary_renders_below_the_abstract(tmp_path):
    db_path, sid = _build_paper_db(tmp_path, "below.db", state="llm-extracted")
    with _client_for(db_path) as c:
        body = c.get(f"/paper/{sid}").text
    assert "A model wrote this summary of the paper." in body
    assert body.index("id=\"abstract-section\"") < body.index("id=\"summary-section\"")


@pytest.mark.parametrize("state,marker", [
    ("absent", "No summary yet."),
    ("llm-extracted", "unreviewed &mdash; model output"),
    ("human-reviewed", "checked by a human"),
    ("human-authored", "written by a human"),
    ("rejected", "rejected"),
])
def test_each_declared_state_renders_distinguishably(tmp_path, state, marker):
    """INV-KK-SUMMARY-STATE-VOCABULARY: all five states, each visibly different."""
    db_path, sid = _build_paper_db(tmp_path, f"state_{state}.db", state=state)
    with _client_for(db_path) as c:
        body = c.get(f"/paper/{sid}").text
    assert marker in body


def test_a_human_summary_reads_as_more_trustworthy_than_a_model_one(tmp_path):
    human_db, sid = _build_paper_db(tmp_path, "human.db", state="human-reviewed")
    llm_db, _ = _build_paper_db(tmp_path, "llm.db", state="llm-extracted")
    with _client_for(human_db) as c:
        human = c.get(f"/paper/{sid}").text
    with _client_for(llm_db) as c:
        llm = c.get(f"/paper/{sid}").text

    assert "checked by a person against the paper" in human
    assert "No person has checked it." in llm
    assert "No person has checked it." not in human


# --- completeness rendering (INV-KK-COMPLETENESS-ADVISORY) ---


def test_every_dimension_renders_including_the_non_gating_one(tmp_path):
    from ingest.paper_completeness import BINARY_DIMENSIONS

    db_path, sid = _build_paper_db(tmp_path, "verdict.db", state="llm-extracted", concepts=1)
    with _client_for(db_path) as c:
        body = c.get(f"/paper/{sid}").text

    for dim in BINARY_DIMENSIONS:
        assert f'data-dimension="{dim}"' in body, dim
    # D-B: recorded, never gating — and it must be visible even though it is false
    # for every paper in the corpus today.
    assert "Kernel invariant" in body
    assert "it never gates anything" in body


def test_absent_dimensions_are_shown_not_hidden(tmp_path):
    """The verdict must not hide anything — a false dimension still renders."""
    db_path, sid = _build_paper_db(tmp_path, "sparse.db", concepts=0)
    with _client_for(db_path) as c:
        body = c.get(f"/paper/{sid}").text
    assert body.count('data-dimension=') == 6
    assert "not present" in body


def test_a_failing_verdict_disables_nothing(tmp_path):
    """INV-KK-COMPLETENESS-ADVISORY: an all-false paper renders the same controls."""
    bare_db, sid = _build_paper_db(tmp_path, "bare.db", concepts=0)
    full_db, _ = _build_paper_db(tmp_path, "full.db", state="human-authored", concepts=0)
    with _client_for(bare_db) as c:
        bare = c.get(f"/paper/{sid}").text
    with _client_for(full_db) as c:
        full = c.get(f"/paper/{sid}").text

    for control in ("toggleSummaryForm()", "saveSummary(event)", "summary-edit"):
        assert control in bare, control
        assert control in full, control
    assert bare.count("attrs-section") == full.count("attrs-section")


def test_page_renders_without_a_verdict(tmp_path):
    db_path, sid = _build_paper_db(tmp_path, "noverdict.db", with_verdict=False)
    with _client_for(db_path) as c:
        response = c.get(f"/paper/{sid}")
    assert response.status_code == 200
    assert "No completeness record for this paper yet." in response.text


# --- query discipline ---


def _selects_for(client, path, needle=None):
    conn = client.app.state.conn
    seen = []
    conn.set_trace_callback(seen.append)
    try:
        assert client.get(path).status_code == 200
    finally:
        conn.set_trace_callback(None)
    selects = [q for q in seen if q.strip().upper().startswith("SELECT")]
    if needle:
        return [q for q in selects if needle in q]
    return selects


def test_summary_and_verdict_cost_one_query_each_regardless_of_concepts(tmp_path):
    """The summary and verdict lookups sit outside every loop.

    The page as a whole is NOT query-bounded — paper_detail runs per-concept
    enrichment that predates this work — so this asserts the property this
    change is responsible for: the two new lookups are constant, not per-item.
    """
    small_db, sid = _build_paper_db(tmp_path, "q_small.db", state="llm-extracted", concepts=1)
    large_db, _ = _build_paper_db(tmp_path, "q_large.db", state="llm-extracted", concepts=6)

    for db_path in (small_db, large_db):
        with _client_for(db_path) as c:
            assert len(_selects_for(c, f"/paper/{sid}", "summarizes-paper")) == 1
            assert len(_selects_for(c, f"/paper/{sid}", "completeness-of")) == 1


# --- ALG-KK-WEB-SUMMARY-EDIT ---


def test_summary_edit_is_on_the_allowlist():
    """INV-KK-WEB-MUTATION-ALLOWLISTED."""
    from web.routes import WEB_MUTATION_ALLOWLIST

    assert "/api/summary/" in WEB_MUTATION_ALLOWLIST


def test_summary_edit_sets_a_human_authored_summary(summary_client):
    response = summary_client.put(
        "/api/summary/src-p1", json={"text": "I read this paper and here is the gist.",
                                     "state": "human-authored"})
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "human-authored"
    body = summary_client.get("/paper/src-p1").text
    assert "I read this paper and here is the gist." in body
    assert "written by a human" in body


def test_summary_edit_attributes_to_the_session_not_the_body(summary_client):
    """INV-KK-WEB-SUMMARY-STATE-AUTHORITY: a reviewed_by in the body is ignored."""
    response = summary_client.put(
        "/api/summary/src-p1",
        json={"text": "Attribution test summary text goes here.",
              "state": "human-reviewed", "reviewed_by": "someone-else"})
    assert response.status_code == 200, response.text
    body = summary_client.get("/paper/src-p1").text
    assert "kate" in body
    assert "someone-else" not in body


@pytest.mark.parametrize("state", ["llm-extracted", "not-a-state", "absent"])
def test_summary_edit_refuses_states_a_human_may_not_set(summary_client, state):
    """A person may not launder their own text as a model's."""
    response = summary_client.put(
        "/api/summary/src-p1", json={"text": "Some text that is long enough.", "state": state})
    assert response.status_code == 422, response.text


def test_summary_edit_404_for_unknown_source(summary_client):
    response = summary_client.put(
        "/api/summary/src-nope", json={"text": "x" * 40, "state": "human-authored"})
    assert response.status_code == 404


def test_summary_edit_422_for_empty_text(summary_client):
    response = summary_client.put(
        "/api/summary/src-p1", json={"text": "   ", "state": "human-authored"})
    assert response.status_code == 422


def test_summary_edit_refreshes_the_completeness_verdict(summary_client):
    """A human is watching, so the page must reflect the edit."""
    import json

    conn = summary_client.app.state.conn
    summary_client.put("/api/summary/src-p1",
                       json={"text": "A summary long enough to be stored.",
                             "state": "human-authored"})
    row = conn.execute(
        "SELECT n.attrs FROM edges e JOIN nodes n ON n.id = e.source_id "
        "WHERE e.kind = 'completeness-of' AND e.target_id = 'src-p1'"
    ).fetchone()
    assert row is not None
    assert json.loads(row[0])["has_summary"] is True


# --- ONE BLOCK, NOT TWO (ALG-KK-WEB-PAPER-DETAIL) ------------------------
#
# D-15a removed key_ideas, relevance and methodology from PaperSummary, and the
# markup that rendered them went with it. SEVEN tests that existed only to prove
# the four fields rendered together were removed with the fields: the four-field
# render test, the single-state-badge test, the prose-only-no-empty-headings
# test, the enrichment-without-prose test, the no-extra-query test, the
# removed-brief-query test and its enrichment reach-the-page assertion.
#
# What remains are the structural properties that survive D-15a, rewired to a
# prose-only summary, plus two tests that pin the new shape.


def _build_summary_db(tmp_path, name, state="llm-extracted",
                      text="A model wrote this summary of the paper.",
                      concepts=0, legacy_attrs=None):
    """A paper with one summary. legacy_attrs injects retired keys directly into
    the attrs JSON, which is the only way to produce them now that set_summary
    refuses them — that is what makes the D-15a render test meaningful."""
    import json as _json

    from ingest.paper_completeness import recompute_paper
    from ingest.paper_summary import set_summary

    db_path = tmp_path / name
    conn = init_db(db_path)
    sid = _summary_paper(conn)
    set_summary(conn, sid, text, state, model="claude-sonnet-5")
    if legacy_attrs:
        row = conn.execute(
            "SELECT n.id, n.attrs FROM edges e JOIN nodes n ON n.id = e.source_id "
            "WHERE e.kind = 'summarizes-paper' AND e.target_id = ?", (sid,)
        ).fetchone()
        attrs = _json.loads(row[1])
        attrs.update(legacy_attrs)
        conn.execute("UPDATE nodes SET attrs = ? WHERE id = ?", (_json.dumps(attrs), row[0]))
    for i in range(concepts):
        add_node(conn, f"ev-{i}", "Evidence", {"artifact_class": "A", "contamination_level": "L0"})
        add_node(conn, f"c-{i}", "Concept", {
            "name": f"Concept {i}", "description": "d", "artifact_class": "B",
            "key_properties": [], "tradeoffs": [], "design_rationale": "r",
        })
        add_edge(conn, "sourced-from", f"ev-{i}", sid)
        add_edge(conn, "extracted-from", f"c-{i}", f"ev-{i}")
    recompute_paper(conn, sid)
    conn.commit()
    conn.close()
    return db_path, sid


def test_the_page_has_no_separate_brief_section(tmp_path):
    db_path, sid = _build_summary_db(tmp_path, "nobrief.db")
    with _client_for(db_path) as c:
        text = c.get(f"/paper/{sid}").text
    assert "Research Brief" not in text
    assert "ResearchBrief" not in text


def test_abstract_precedes_the_summary(tmp_path):
    db_path, sid = _build_summary_db(tmp_path, "order.db")
    with _client_for(db_path) as c:
        text = c.get(f"/paper/{sid}").text
    assert text.index("Abstract") < text.index("Summary")


def test_the_page_never_queries_for_a_brief(tmp_path):
    db_path, sid = _build_summary_db(tmp_path, "noquery.db", concepts=3)
    with _client_for(db_path) as c:
        selects = _selects_for(c, f"/paper/{sid}")
    assert not [q for q in selects if "ResearchBrief" in q]


def test_retired_fields_left_in_attrs_are_never_rendered(tmp_path):
    """D-15a. A row predating the change still carries the three keys in its
    attrs JSON until the data migration strips them; the page must ignore them."""
    db_path, sid = _build_summary_db(tmp_path, "legacy.db", legacy_attrs={
        "key_ideas": ["Delegates paging policy to user space."],
        "relevance": "Matters for the memory-management subsystem.",
        "methodology": "eBPF-based tracing",
    })
    with _client_for(db_path) as c:
        text = c.get(f"/paper/{sid}").text
    assert "Key Ideas" not in text
    assert "Delegates paging policy" not in text
    assert "memory-management subsystem" not in text
    assert "eBPF-based tracing" not in text


def test_an_absent_summary_says_so_and_shows_nothing_else(tmp_path):
    """The contradiction that started this work, pinned from both sides.

    A row with state 'absent' and no prose used to render Key Ideas and Relevance
    and then print 'No summary yet.' underneath them. The line itself is correct
    and stays — it carries the Add summary affordance — but with the three fields
    gone there is now no content above it for it to contradict."""
    db_path, sid = _build_summary_db(tmp_path, "absent.db", state="absent", text="")
    with _client_for(db_path) as c:
        text = c.get(f"/paper/{sid}").text
    assert "No summary yet." in text
    assert "Key Ideas" not in text
    assert "Relevance" not in text


# ---------------------------------------------------------------------------
# Feed card field naming — ALG-KK-WEB-FEED-CARD, ALG-KK-WEB-FEED-LIST,
# ALG-KK-WEB-FEED-SEND, INV-KK-FEED-SUMMARY-MAX-WORDS.
#
# The card shipped the CONCEPT's description under a key named "summary". That
# was merely loose until PaperSummary landed on the same Source; after that, a
# consumer reading card["summary"] got concept boilerplate while believing it
# held the paper's summary, and /api/feed/send forwarded it outward. The key is
# now "concept_description".
#
# These endpoints had NO tests before this change, which is why the mislabel
# survived. The leak test below is the one that matters: it fails if anybody
# ever wires the real summary into this field without renaming it again.
# ---------------------------------------------------------------------------


def test_feed_card_ships_no_key_named_summary(client):
    """The mislabelled key is gone from the JSON, not merely unused."""
    response = client.get("/api/feed/card/src-1")
    assert response.status_code == 200
    item = response.json()["item"]
    assert "summary" not in item


def test_feed_card_concept_description_holds_the_concept_description(client):
    """The renamed key carries what it claims to: the attached Concept's text."""
    response = client.get("/api/feed/card/src-1")
    item = response.json()["item"]
    assert item["concept_description"] == "A queue implementation without locks."


def test_paper_summary_does_not_leak_into_the_concept_description(client):
    """A Source carrying a real PaperSummary must not see it reach this field.

    Written through ingest.paper_summary.set_summary rather than a hand-built
    node so the fixture has the shape production writes — the key_ideas
    corruption got through because a fixture used a shape production never had.
    """
    from ingest.paper_summary import set_summary

    conn = client.app.state.conn
    set_summary(
        conn,
        "src-1",
        text="MEASURED PAPER SUMMARY PROSE that must never appear on the card.",
        state="llm-extracted",
        model="test-model",
    )
    conn.commit()

    item = client.get("/api/feed/card/src-1").json()["item"]
    assert item["concept_description"] == "A queue implementation without locks."
    assert "MEASURED PAPER SUMMARY PROSE" not in item["concept_description"]
    assert "MEASURED PAPER SUMMARY PROSE" not in client.get(
        "/api/feed/card/src-1"
    ).text


def test_feed_page_renders_the_concept_description(client):
    """/feed renders the renamed template variable, not an empty cell."""
    response = client.get("/feed")
    assert response.status_code == 200
    assert "A queue implementation without locks." in response.text


# ---------------------------------------------------------------------------
# "Why This Matters" removal — ALG-KK-WEB-PAPER-DETAIL, D-11 option (i), D-15.
#
# The block was built by classify_motivations(brief), which takes a concept
# brief and NO source id, so it was a pure function of the paper's concept set
# rather than of the paper. Measured before removal: 1238 of the 1433
# concept-bearing papers (86.4%) share their whole concept set with another
# paper, and 372 papers rendered byte-identical text under a heading presenting
# it as a finding about the paper in front of the reader.
#
# THESE TESTS NEED THEIR OWN FIXTURE. The default `client` graph attaches a
# Concept with no vulnerabilities, so the removed classifier returned [] for it
# and the block never rendered even before the removal — tests written against
# that fixture pass in both directions and prove nothing. This fixture hangs a
# Vulnerability off the concept via an `exploits` edge, which is what the old
# security branch keyed on, so the block DID render here before the change.
#
# The paper-grounded classify_source_motivations is NOT affected and still
# serves /feed; the radar keyword classifier still serves /radar.
# ---------------------------------------------------------------------------


@pytest.fixture
def motivating_client(tmp_path):
    db_path = tmp_path / "motivating.db"
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
    add_node(conn, "src-1", "Source", {
        "url": "https://example.com/paper.pdf",
        "source_type": "preprint",
        "license": "MIT",
        "title": "A Paper",
    })
    # The trigger for the removed security branch.
    add_node(conn, "vuln-1", "Vulnerability", {
        "cve_id": "CVE-TEST-001",
        "title": "Queue heap overflow",
        "description": "Heap overflow in the lock-free queue reclaim path.",
        "severity": "high",
        "cvss_score": "7.5",
        "affected_versions": "5.15-6.1",
        "status": "open",
        "source_date": "2024-03-01",
        "artifact_class": "B",
    })
    add_edge(conn, "extracted-from", "concept-1", "ev-1")
    add_edge(conn, "sourced-from", "ev-1", "src-1")
    add_edge(conn, "exploits", "vuln-1", "concept-1")
    conn.commit()
    conn.close()

    app = create_app(str(db_path))
    with TestClient(app) as c:
        yield c


def test_paper_page_renders_no_why_this_matters_block(motivating_client):
    response = motivating_client.get("/paper/src-1")
    assert response.status_code == 200
    assert "Why This Matters" not in response.text


def test_paper_page_renders_no_motivation_evidence_furniture(motivating_client):
    """None of the removed block's evidence framing survives.

    The concept description itself is NOT asserted absent: it legitimately
    appears in the concept card grid, which lists what attaches to the paper
    rather than making a claim about it. The defect was the HARDWARE ENABLEMENT
    branch citing brief["concept"]["description"][:200] AS EVIDENCE under a
    heading that framed it as a finding about this paper.
    """
    response = motivating_client.get("/paper/src-1")
    for marker in ("If addressed:", "Blast radius:", "SECURITY", "CVE-TEST-001"):
        assert marker not in response.text, f"motivation furniture survives: {marker}"


def test_paper_page_still_lists_its_concepts(motivating_client):
    """Removing the block must not take the concept card grid with it.

    build_concept_brief survives the removal because it still supplies the
    subsystem; this pins that the page keeps showing which concepts attach.
    """
    response = motivating_client.get("/paper/src-1")
    assert response.status_code == 200
    assert "Lock-free Queue" in response.text
