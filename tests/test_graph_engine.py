"""Tests for know_kernel.graph.engine â€” CRUD ops, edge/attr validation, delete cascade."""

from __future__ import annotations

import sqlite3

import pytest

from graph.engine import (
    AdmissibilityError,
    add_edge,
    add_node,
    compare_neighborhoods,
    delete_edge,
    delete_node,
    get_edge,
    get_node,
    list_nodes,
    match_scenarios,
    neighbors,
    path_exists,
    query_by_attrs,
    query_edges_by_attrs,
    ranked_recommendations,
    subgraph_around,
    transitive_impact,
    update_node_attrs,
)


# --- add_node / get_node ---


def test_add_and_get_node(conn: sqlite3.Connection):
    add_node(conn, "s1", "Subsystem", {"name": "mm"})
    node = get_node(conn, "s1")
    assert node is not None
    assert node["kind"] == "Subsystem"
    assert node["attrs"]["name"] == "mm"


def test_get_node_missing(conn: sqlite3.Connection):
    assert get_node(conn, "nonexistent") is None


# --- INV-KK-NODE-ATTRS-SCHEMA ---


def test_add_node_rejects_missing_required_attrs(conn: sqlite3.Connection):
    with pytest.raises(ValueError, match="missing required attributes"):
        add_node(conn, "c1", "Concept", {"name": "x"})


def test_add_node_concept_requires_name_description_artifact_class(conn: sqlite3.Connection):
    with pytest.raises(ValueError, match="description, artifact_class"):
        add_node(conn, "c1", "Concept", {"name": "x"})


def test_add_node_source_requires_url_source_type_license(conn: sqlite3.Connection):
    with pytest.raises(ValueError, match="missing required"):
        add_node(conn, "s1", "Source", {"url": "http://x"})


def test_add_node_evidence_requires_artifact_class_contamination_level(conn: sqlite3.Connection):
    with pytest.raises(ValueError, match="missing required"):
        add_node(conn, "e1", "Evidence", {})


def test_add_node_advisory_requires_assessment(conn: sqlite3.Connection):
    with pytest.raises(ValueError, match="missing required"):
        add_node(conn, "a1", "Advisory", {})


def test_add_node_subsystem_requires_name(conn: sqlite3.Connection):
    with pytest.raises(ValueError, match="missing required"):
        add_node(conn, "s1", "Subsystem", {})


def test_add_node_accepts_extra_attrs(conn: sqlite3.Connection):
    add_node(conn, "s1", "Subsystem", {"name": "mm", "extra": "val"})
    node = get_node(conn, "s1")
    assert node["attrs"]["extra"] == "val"


# --- add_edge / INV-KK-EDGE-KIND-CONSTRAINTS ---


def test_add_edge_rejects_unknown_kind(populated: sqlite3.Connection):
    with pytest.raises(ValueError, match="Unknown edge kind"):
        add_edge(populated, "bogus", "c1", "c2")


def test_add_edge_rejects_wrong_source_kind(populated: sqlite3.Connection):
    with pytest.raises(ValueError, match="requires.*Concept.*Subsystem"):
        add_edge(populated, "belongs-to", "src1", "sub1")


def test_add_edge_rejects_wrong_target_kind(populated: sqlite3.Connection):
    with pytest.raises(ValueError, match="requires.*Concept.*Subsystem"):
        add_edge(populated, "belongs-to", "c1", "c2")


def test_add_edge_rejects_missing_source(populated: sqlite3.Connection):
    with pytest.raises(ValueError, match="does not exist"):
        add_edge(populated, "belongs-to", "ghost", "sub1")


def test_add_edge_rejects_missing_target(populated: sqlite3.Connection):
    with pytest.raises(ValueError, match="does not exist"):
        add_edge(populated, "belongs-to", "c1", "ghost")


def test_add_edge_valid_belongs_to(populated: sqlite3.Connection):
    count_before = populated.execute("SELECT COUNT(*) FROM edges WHERE kind='belongs-to'").fetchone()[0]
    assert count_before >= 1


# --- update_node_attrs ---


def test_update_node_attrs_merges(populated: sqlite3.Connection):
    update_node_attrs(populated, "c1", {"maturity": "stable"})
    node = get_node(populated, "c1")
    assert node["attrs"]["maturity"] == "stable"
    assert node["attrs"]["name"] == "RCU"


def test_update_node_attrs_rejects_nonexistent(conn: sqlite3.Connection):
    with pytest.raises(ValueError, match="does not exist"):
        update_node_attrs(conn, "ghost", {"x": 1})


# --- delete_node / INV-KK-DELETE-CASCADE ---


def test_delete_node_cascades_edges(populated: sqlite3.Connection):
    edges_before = populated.execute(
        "SELECT COUNT(*) FROM edges WHERE source_id='c1' OR target_id='c1'"
    ).fetchone()[0]
    assert edges_before > 0
    delete_node(populated, "c1")
    assert get_node(populated, "c1") is None
    edges_after = populated.execute(
        "SELECT COUNT(*) FROM edges WHERE source_id='c1' OR target_id='c1'"
    ).fetchone()[0]
    assert edges_after == 0


def test_delete_node_nonexistent(conn: sqlite3.Connection):
    with pytest.raises(ValueError, match="does not exist"):
        delete_node(conn, "ghost")


# --- delete_node admissibility cascade (INV-KK-DELETE-CASCADE) ---
# REPRODUCTION TEST: these must FAIL before the fix, PASS after.


def test_delete_evidence_rejects_if_concept_loses_provenance(conn: sqlite3.Connection):
    """Deleting ev1 (only provenance for c1) must be rejected."""
    add_node(conn, "sub1", "Subsystem", {"name": "mm"})
    add_node(conn, "c1", "Concept", {"name": "C", "description": "d", "artifact_class": "B", "key_properties": ["test"], "tradeoffs": [], "design_rationale": "test"})
    add_node(conn, "src1", "Source", {"url": "http://x.com", "source_type": "paper", "license": "PD"})
    add_node(conn, "adv1", "Advisory", {"assessment": "safe", "contamination_confirmed": "none"})
    add_node(conn, "ev1", "Evidence", {"artifact_class": "A", "contamination_level": "L0"})
    add_edge(conn, "belongs-to", "c1", "sub1")
    add_edge(conn, "extracted-from", "c1", "ev1")
    add_edge(conn, "sourced-from", "ev1", "src1")
    add_edge(conn, "assessed-by", "src1", "adv1")
    with pytest.raises(AdmissibilityError):
        delete_node(conn, "ev1")


def test_delete_source_rejects_if_evidence_loses_traceability(conn: sqlite3.Connection):
    """Deleting src1 (only source for ev1) must be rejected."""
    add_node(conn, "sub1", "Subsystem", {"name": "mm"})
    add_node(conn, "c1", "Concept", {"name": "C", "description": "d", "artifact_class": "B", "key_properties": ["test"], "tradeoffs": [], "design_rationale": "test"})
    add_node(conn, "src1", "Source", {"url": "http://x.com", "source_type": "paper", "license": "PD"})
    add_node(conn, "adv1", "Advisory", {"assessment": "safe", "contamination_confirmed": "none"})
    add_node(conn, "ev1", "Evidence", {"artifact_class": "A", "contamination_level": "L0"})
    add_edge(conn, "belongs-to", "c1", "sub1")
    add_edge(conn, "extracted-from", "c1", "ev1")
    add_edge(conn, "sourced-from", "ev1", "src1")
    add_edge(conn, "assessed-by", "src1", "adv1")
    with pytest.raises(AdmissibilityError):
        delete_node(conn, "src1")


def test_delete_subsystem_rejects_if_concept_loses_belongs_to(conn: sqlite3.Connection):
    """Deleting sub1 (only subsystem for c1) must be rejected."""
    add_node(conn, "sub1", "Subsystem", {"name": "mm"})
    add_node(conn, "c1", "Concept", {"name": "C", "description": "d", "artifact_class": "B", "key_properties": ["test"], "tradeoffs": [], "design_rationale": "test"})
    add_node(conn, "src1", "Source", {"url": "http://x.com", "source_type": "paper", "license": "PD"})
    add_node(conn, "adv1", "Advisory", {"assessment": "safe", "contamination_confirmed": "none"})
    add_node(conn, "ev1", "Evidence", {"artifact_class": "A", "contamination_level": "L0"})
    add_edge(conn, "belongs-to", "c1", "sub1")
    add_edge(conn, "extracted-from", "c1", "ev1")
    add_edge(conn, "sourced-from", "ev1", "src1")
    add_edge(conn, "assessed-by", "src1", "adv1")
    with pytest.raises(AdmissibilityError):
        delete_node(conn, "sub1")


def test_delete_advisory_rejects_if_source_loses_assessment(conn: sqlite3.Connection):
    """Deleting adv1 (only advisory for src1) must be rejected."""
    add_node(conn, "sub1", "Subsystem", {"name": "mm"})
    add_node(conn, "c1", "Concept", {"name": "C", "description": "d", "artifact_class": "B", "key_properties": ["test"], "tradeoffs": [], "design_rationale": "test"})
    add_node(conn, "src1", "Source", {"url": "http://x.com", "source_type": "paper", "license": "PD"})
    add_node(conn, "adv1", "Advisory", {"assessment": "safe", "contamination_confirmed": "none"})
    add_node(conn, "ev1", "Evidence", {"artifact_class": "A", "contamination_level": "L0"})
    add_edge(conn, "belongs-to", "c1", "sub1")
    add_edge(conn, "extracted-from", "c1", "ev1")
    add_edge(conn, "sourced-from", "ev1", "src1")
    add_edge(conn, "assessed-by", "src1", "adv1")
    with pytest.raises(AdmissibilityError):
        delete_node(conn, "adv1")


def test_delete_node_succeeds_when_no_dependents_violated(conn: sqlite3.Connection):
    """Deleting a node that no other node depends on must succeed."""
    add_node(conn, "sub1", "Subsystem", {"name": "mm"})
    add_node(conn, "adv1", "Advisory", {"assessment": "safe", "contamination_confirmed": "none"})
    delete_node(conn, "adv1")
    assert get_node(conn, "adv1") is None


def test_delete_node_succeeds_when_alternate_path_exists(conn: sqlite3.Connection):
    """Deleting ev1 succeeds when c1 still has ev2 as alternate provenance."""
    add_node(conn, "sub1", "Subsystem", {"name": "mm"})
    add_node(conn, "c1", "Concept", {"name": "C", "description": "d", "artifact_class": "B", "key_properties": ["test"], "tradeoffs": [], "design_rationale": "test"})
    add_node(conn, "src1", "Source", {"url": "http://x.com", "source_type": "paper", "license": "PD"})
    add_node(conn, "src2", "Source", {"url": "http://y.com", "source_type": "paper", "license": "PD"})
    add_node(conn, "adv1", "Advisory", {"assessment": "safe", "contamination_confirmed": "none"})
    add_node(conn, "adv2", "Advisory", {"assessment": "safe", "contamination_confirmed": "none"})
    add_node(conn, "ev1", "Evidence", {"artifact_class": "A", "contamination_level": "L0"})
    add_node(conn, "ev2", "Evidence", {"artifact_class": "A", "contamination_level": "L0"})
    add_edge(conn, "belongs-to", "c1", "sub1")
    add_edge(conn, "extracted-from", "c1", "ev1")
    add_edge(conn, "extracted-from", "c1", "ev2")
    add_edge(conn, "sourced-from", "ev1", "src1")
    add_edge(conn, "sourced-from", "ev2", "src2")
    add_edge(conn, "assessed-by", "src1", "adv1")
    add_edge(conn, "assessed-by", "src2", "adv2")
    delete_node(conn, "ev1")
    assert get_node(conn, "ev1") is None


# --- delete_edge ---


def test_delete_edge_removes_by_id(populated: sqlite3.Connection):
    add_node(populated, "sub2", "Subsystem", {"name": "mm"})
    add_edge(populated, "belongs-to", "c1", "sub2")
    eid = populated.execute(
        "SELECT id FROM edges WHERE kind='belongs-to' AND source_id='c1' AND target_id='sub1'"
    ).fetchone()[0]
    delete_edge(populated, eid)
    assert get_edge(populated, eid) is None


def test_delete_edge_nonexistent(conn: sqlite3.Connection):
    with pytest.raises(ValueError, match="does not exist"):
        delete_edge(conn, 99999)


# --- get_edge ---


def test_get_edge_returns_fields(populated: sqlite3.Connection):
    eid = populated.execute("SELECT id FROM edges LIMIT 1").fetchone()[0]
    edge = get_edge(populated, eid)
    assert edge is not None
    assert "kind" in edge
    assert "source_id" in edge
    assert "target_id" in edge
    assert "attrs" in edge


def test_get_edge_missing(conn: sqlite3.Connection):
    assert get_edge(conn, 99999) is None


# --- list_nodes ---


def test_list_nodes_all(populated: sqlite3.Connection):
    nodes = list_nodes(populated)
    assert len(nodes) == 6


def test_list_nodes_by_kind(populated: sqlite3.Connection):
    concepts = list_nodes(populated, "Concept")
    assert len(concepts) == 2
    assert all(n["kind"] == "Concept" for n in concepts)


def test_list_nodes_empty_kind(populated: sqlite3.Connection):
    result = list_nodes(populated, "Advisory")
    assert len(result) == 1


# --- query_by_attrs ---


def test_query_by_attrs_match(populated: sqlite3.Connection):
    result = query_by_attrs(populated, "Concept", name="RCU")
    assert len(result) == 1
    assert result[0]["id"] == "c1"


def test_query_by_attrs_no_match(populated: sqlite3.Connection):
    result = query_by_attrs(populated, "Concept", name="nonexistent")
    assert len(result) == 0


def test_query_by_attrs_multiple_filters(populated: sqlite3.Connection):
    result = query_by_attrs(populated, "Concept", name="RCU", artifact_class="B")
    assert len(result) == 1


# --- neighbors ---


def test_neighbors_out(populated: sqlite3.Connection):
    out = neighbors(populated, "c1", "out")
    kinds = {n["edge_kind"] for n in out}
    assert "belongs-to" in kinds
    assert "extracted-from" in kinds


def test_neighbors_in(populated: sqlite3.Connection):
    inc = neighbors(populated, "sub1", "in")
    assert len(inc) >= 2


def test_neighbors_edge_kind_filter(populated: sqlite3.Connection):
    out = neighbors(populated, "c1", "out", edge_kind="belongs-to")
    assert all(n["edge_kind"] == "belongs-to" for n in out)
    assert len(out) == 1


# --- path_exists ---


def test_path_exists_direct(populated: sqlite3.Connection):
    assert path_exists(populated, "c1", "sub1", ["belongs-to"])


def test_path_exists_transitive(populated: sqlite3.Connection):
    assert path_exists(populated, "c1", "src1", ["extracted-from", "sourced-from"])


def test_path_exists_no_path(populated: sqlite3.Connection):
    assert not path_exists(populated, "c1", "adv1", ["extracted-from", "sourced-from"])


def test_path_exists_all_edge_kinds(populated: sqlite3.Connection):
    assert path_exists(populated, "c1", "src1")


def test_path_exists_self(populated: sqlite3.Connection):
    assert path_exists(populated, "c1", "c1")


# --- KernelInvariant ---

KINV_ATTRS = {
    "predicate": "No reader observes a partially-updated structure",
    "strength": "safety",
    "scope": "per-operation",
    "artifact_class": "abstracted-mechanism",
}


def test_kernel_invariant_node_creation(conn: sqlite3.Connection):
    add_node(conn, "ki1", "KernelInvariant", KINV_ATTRS)
    node = get_node(conn, "ki1")
    assert node is not None
    assert node["kind"] == "KernelInvariant"
    assert node["attrs"]["predicate"] == KINV_ATTRS["predicate"]


def test_kernel_invariant_rejects_missing_attrs(conn: sqlite3.Connection):
    with pytest.raises(ValueError, match="missing required"):
        add_node(conn, "ki1", "KernelInvariant", {"predicate": "x"})


def test_governed_by_edge_valid(populated: sqlite3.Connection):
    add_node(populated, "ki1", "KernelInvariant", KINV_ATTRS)
    add_edge(populated, "governed-by", "ki1", "c1")
    row = populated.execute(
        "SELECT 1 FROM edges WHERE kind='governed-by' AND source_id='ki1' AND target_id='c1'"
    ).fetchone()
    assert row is not None


def test_governed_by_edge_invalid_source(populated: sqlite3.Connection):
    with pytest.raises(ValueError, match="requires"):
        add_edge(populated, "governed-by", "c1", "c2")


def test_belongs_to_kernel_invariant(populated: sqlite3.Connection):
    add_node(populated, "ki1", "KernelInvariant", KINV_ATTRS)
    add_edge(populated, "belongs-to", "ki1", "sub1")
    row = populated.execute(
        "SELECT 1 FROM edges WHERE kind='belongs-to' AND source_id='ki1' AND target_id='sub1'"
    ).fetchone()
    assert row is not None


def test_extracted_from_kernel_invariant(populated: sqlite3.Connection):
    add_node(populated, "ki1", "KernelInvariant", KINV_ATTRS)
    add_edge(populated, "extracted-from", "ki1", "ev1")
    row = populated.execute(
        "SELECT 1 FROM edges WHERE kind='extracted-from' AND source_id='ki1' AND target_id='ev1'"
    ).fetchone()
    assert row is not None


# --- Query layer: subgraph_around + query_edges_by_attrs ---


class TestSubgraphAround:
    def test_subgraph_around_depth_1(self, conn: sqlite3.Connection) -> None:
        add_node(conn, "sub1", "Subsystem", {"name": "sched"})
        add_node(conn, "c1", "Concept", {"name": "A", "description": "a", "artifact_class": "abstracted-mechanism", "key_properties": ["x"], "tradeoffs": [], "design_rationale": "r"})
        add_node(conn, "c2", "Concept", {"name": "B", "description": "b", "artifact_class": "abstracted-mechanism", "key_properties": ["y"], "tradeoffs": [], "design_rationale": "r"})
        add_node(conn, "c3", "Concept", {"name": "C", "description": "c", "artifact_class": "abstracted-mechanism", "key_properties": ["z"], "tradeoffs": [], "design_rationale": "r"})
        add_edge(conn, "belongs-to", "c1", "sub1")
        add_edge(conn, "refines", "c2", "c1")
        add_edge(conn, "refines", "c3", "c2")
        result = subgraph_around(conn, "c1", depth=1)
        assert "nodes" in result
        assert "edges" in result
        node_ids = {n["id"] for n in result["nodes"]}
        assert "c1" in node_ids
        assert "sub1" in node_ids
        assert "c2" in node_ids
        assert "c3" not in node_ids

    def test_subgraph_around_depth_2(self, conn: sqlite3.Connection) -> None:
        add_node(conn, "sub1", "Subsystem", {"name": "sched"})
        add_node(conn, "c1", "Concept", {"name": "A", "description": "a", "artifact_class": "abstracted-mechanism", "key_properties": ["x"], "tradeoffs": [], "design_rationale": "r"})
        add_node(conn, "c2", "Concept", {"name": "B", "description": "b", "artifact_class": "abstracted-mechanism", "key_properties": ["y"], "tradeoffs": [], "design_rationale": "r"})
        add_node(conn, "c3", "Concept", {"name": "C", "description": "c", "artifact_class": "abstracted-mechanism", "key_properties": ["z"], "tradeoffs": [], "design_rationale": "r"})
        add_edge(conn, "belongs-to", "c1", "sub1")
        add_edge(conn, "refines", "c2", "c1")
        add_edge(conn, "refines", "c3", "c2")
        result = subgraph_around(conn, "c1", depth=2)
        node_ids = {n["id"] for n in result["nodes"]}
        assert "c3" in node_ids
        assert len(result["edges"]) == 3

    def test_subgraph_around_edge_filter(self, conn: sqlite3.Connection) -> None:
        add_node(conn, "sub1", "Subsystem", {"name": "sched"})
        add_node(conn, "c1", "Concept", {"name": "A", "description": "a", "artifact_class": "abstracted-mechanism", "key_properties": ["x"], "tradeoffs": [], "design_rationale": "r"})
        add_node(conn, "c2", "Concept", {"name": "B", "description": "b", "artifact_class": "abstracted-mechanism", "key_properties": ["y"], "tradeoffs": [], "design_rationale": "r"})
        add_edge(conn, "belongs-to", "c1", "sub1")
        add_edge(conn, "refines", "c2", "c1")
        result = subgraph_around(conn, "c1", depth=1, edge_kinds=["refines"])
        node_ids = {n["id"] for n in result["nodes"]}
        assert "c2" in node_ids
        assert "sub1" not in node_ids


class TestQueryEdgesByAttrs:
    def test_query_edges_by_attrs(self, conn: sqlite3.Connection) -> None:
        from graph.optimization import create_optimization_goal, link_concept_to_goal
        add_node(conn, "sub1", "Subsystem", {"name": "test"})
        add_node(conn, "c1", "Concept", {"name": "A", "description": "a", "artifact_class": "abstracted-mechanism", "key_properties": ["x"], "tradeoffs": [], "design_rationale": "r"})
        add_node(conn, "c2", "Concept", {"name": "B", "description": "b", "artifact_class": "abstracted-mechanism", "key_properties": ["y"], "tradeoffs": [], "design_rationale": "r"})
        goal_id = create_optimization_goal(conn, "Min Latency", "d", "latency", "minimize")
        link_concept_to_goal(conn, "c1", goal_id, "improves", "strong")
        link_concept_to_goal(conn, "c2", goal_id, "worsens", "weak")
        improves = query_edges_by_attrs(conn, kind="contributes-to", direction="improves")
        assert len(improves) == 1
        assert improves[0]["source_id"] == "c1"
        assert improves[0]["attrs"]["magnitude"] == "strong"
        all_ct = query_edges_by_attrs(conn, kind="contributes-to")
        assert len(all_ct) == 2


# --- Query layer part 2: compare_neighborhoods, match_scenarios, transitive_impact, ranked_recommendations ---

CONCEPT_ATTRS = {"name": "X", "description": "d", "artifact_class": "abstracted-mechanism", "key_properties": ["x"], "tradeoffs": [], "design_rationale": "r"}


class TestCompareNeighborhoods:
    def test_compare_neighborhoods_shared(self, conn: sqlite3.Connection) -> None:
        add_node(conn, "sub1", "Subsystem", {"name": "sched"})
        add_node(conn, "c1", "Concept", {**CONCEPT_ATTRS, "name": "A"})
        add_node(conn, "c2", "Concept", {**CONCEPT_ATTRS, "name": "B"})
        add_node(conn, "c3", "Concept", {**CONCEPT_ATTRS, "name": "Shared"})
        add_edge(conn, "belongs-to", "c1", "sub1")
        add_edge(conn, "belongs-to", "c2", "sub1")
        add_edge(conn, "refines", "c3", "c1")
        add_edge(conn, "refines", "c3", "c2")
        result = compare_neighborhoods(conn, "c1", "c2", depth=1)
        shared_ids = {n["id"] for n in result["shared"]}
        assert "sub1" in shared_ids
        assert "c3" in shared_ids
        only_a_ids = {n["id"] for n in result["only_a"]}
        only_b_ids = {n["id"] for n in result["only_b"]}
        assert "c2" not in only_a_ids
        assert "c1" not in only_b_ids

    def test_compare_neighborhoods_symmetric(self, conn: sqlite3.Connection) -> None:
        add_node(conn, "sub1", "Subsystem", {"name": "sched"})
        add_node(conn, "c1", "Concept", {**CONCEPT_ATTRS, "name": "A"})
        add_node(conn, "c2", "Concept", {**CONCEPT_ATTRS, "name": "B"})
        add_node(conn, "c3", "Concept", {**CONCEPT_ATTRS, "name": "OnlyA"})
        add_edge(conn, "belongs-to", "c1", "sub1")
        add_edge(conn, "belongs-to", "c2", "sub1")
        add_edge(conn, "refines", "c3", "c1")
        ab = compare_neighborhoods(conn, "c1", "c2", depth=1)
        ba = compare_neighborhoods(conn, "c2", "c1", depth=1)
        assert {n["id"] for n in ab["shared"]} == {n["id"] for n in ba["shared"]}
        assert {n["id"] for n in ab["only_a"]} == {n["id"] for n in ba["only_b"]}
        assert {n["id"] for n in ab["only_b"]} == {n["id"] for n in ba["only_a"]}


class TestMatchScenarios:
    def test_match_scenarios(self, conn: sqlite3.Connection) -> None:
        from graph.optimization import create_use_case_scenario, link_concept_to_scenario
        add_node(conn, "sub1", "Subsystem", {"name": "test"})
        add_node(conn, "c1", "Concept", {**CONCEPT_ATTRS, "name": "A"})
        add_node(conn, "c2", "Concept", {**CONCEPT_ATTRS, "name": "B"})
        sc_id = create_use_case_scenario(conn, "RT Workload", "realtime", "cpu-bound", "low-latency")
        link_concept_to_scenario(conn, "c1", sc_id, "excellent")
        link_concept_to_scenario(conn, "c2", sc_id, "poor")
        results = match_scenarios(conn, workload_type="cpu-bound")
        assert len(results) == 1
        concepts = results[0]["concepts"]
        assert len(concepts) == 2
        assert concepts[0]["fitness"] == "excellent"
        assert concepts[1]["fitness"] == "poor"
        assert concepts[0]["id"] == "c1"
        empty = match_scenarios(conn, workload_type="io-bound")
        assert len(empty) == 0


class TestTransitiveImpact:
    def test_transitive_impact(self, conn: sqlite3.Connection) -> None:
        from graph.optimization import create_optimization_goal, create_use_case_scenario, link_concept_to_goal, link_concept_to_scenario
        add_node(conn, "sub1", "Subsystem", {"name": "mm"})
        add_node(conn, "c1", "Concept", {**CONCEPT_ATTRS, "name": "RCU"})
        add_edge(conn, "belongs-to", "c1", "sub1")
        add_node(conn, "ki1", "KernelInvariant", KINV_ATTRS)
        add_edge(conn, "governed-by", "ki1", "c1")
        add_node(conn, "fm1", "FailureMode", {"symptom": "crash", "blast_radius": "subsystem", "recoverability": "reboot", "artifact_class": "abstracted-mechanism"})
        add_edge(conn, "triggered-by", "fm1", "ki1")
        add_node(conn, "ip1", "InteractionProtocol", {"rule": "lock-order", "ordering": "strict", "violation_mode": "deadlock", "artifact_class": "abstracted-mechanism"})
        add_edge(conn, "constrains-composition", "ip1", "c1")
        add_node(conn, "pp1", "PerformanceProfile", {"metric": "read latency", "complexity": "O(1)", "best_case": "fast", "worst_case": "slow", "typical_case": "fast", "conditions": "normal", "artifact_class": "abstracted-mechanism"})
        add_edge(conn, "profiled-by", "pp1", "c1")
        goal_id = create_optimization_goal(conn, "Min Latency", "d", "latency", "minimize")
        link_concept_to_goal(conn, "c1", goal_id, "improves", "strong")
        sc_id = create_use_case_scenario(conn, "RT", "realtime", "cpu-bound", "low-latency")
        link_concept_to_scenario(conn, "c1", sc_id, "excellent")
        result = transitive_impact(conn, "c1")
        assert len(result["invariants"]) == 1
        assert result["invariants"][0]["id"] == "ki1"
        assert len(result["failure_modes"]) == 1
        assert result["failure_modes"][0]["id"] == "fm1"
        assert len(result["protocols"]) == 1
        assert len(result["profiles"]) == 1
        assert len(result["goals"]) == 1
        assert len(result["scenarios"]) == 1


class TestRankedRecommendations:
    def test_ranked_recommendations(self, conn: sqlite3.Connection) -> None:
        from graph.optimization import create_optimization_goal, link_concept_to_goal
        add_node(conn, "sub1", "Subsystem", {"name": "test"})
        add_node(conn, "c1", "Concept", {**CONCEPT_ATTRS, "name": "A"})
        add_node(conn, "c2", "Concept", {**CONCEPT_ATTRS, "name": "B"})
        add_node(conn, "c3", "Concept", {**CONCEPT_ATTRS, "name": "C"})
        goal_id = create_optimization_goal(conn, "Min Latency", "d", "latency", "minimize")
        link_concept_to_goal(conn, "c1", goal_id, "improves", "strong")
        link_concept_to_goal(conn, "c2", goal_id, "improves", "weak")
        link_concept_to_goal(conn, "c3", goal_id, "worsens", "strong")
        recs = ranked_recommendations(conn, goal_id)
        assert len(recs) == 2
        assert recs[0]["concept"]["id"] == "c1"
        assert recs[1]["concept"]["id"] == "c2"
        assert recs[0]["score"] >= recs[1]["score"]
        assert "impact" in recs[0]

    def test_ranked_recommendations_limit(self, conn: sqlite3.Connection) -> None:
        from graph.optimization import create_optimization_goal, link_concept_to_goal
        add_node(conn, "sub1", "Subsystem", {"name": "test"})
        add_node(conn, "c1", "Concept", {**CONCEPT_ATTRS, "name": "A"})
        add_node(conn, "c2", "Concept", {**CONCEPT_ATTRS, "name": "B"})
        add_node(conn, "c3", "Concept", {**CONCEPT_ATTRS, "name": "C"})
        goal_id = create_optimization_goal(conn, "Min Latency", "d", "latency", "minimize")
        link_concept_to_goal(conn, "c1", goal_id, "improves", "strong")
        link_concept_to_goal(conn, "c2", goal_id, "improves", "moderate")
        link_concept_to_goal(conn, "c3", goal_id, "improves", "weak")
        recs = ranked_recommendations(conn, goal_id, limit=2)
        assert len(recs) == 2
        assert recs[0]["score"] >= recs[1]["score"]


# --- INV-KK-CONTRADICTED-SYMMETRIC ---


def test_contradicted_by_symmetric(conn: sqlite3.Connection):
    add_node(conn, "obs1", "Observation", {
        "claim": "X is true", "confidence": "0.9",
        "source_date": "2026-01-01", "artifact_class": "B",
    })
    add_node(conn, "obs2", "Observation", {
        "claim": "X is false", "confidence": "0.8",
        "source_date": "2026-01-02", "artifact_class": "B",
    })
    add_edge(conn, "contradicted-by", "obs1", "obs2")
    reverse = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'contradicted-by' AND source_id = 'obs2' AND target_id = 'obs1'"
    ).fetchone()
    assert reverse is not None


# --- INV-KK-DATE-FORMAT ---


def test_source_date_valid_date(conn: sqlite3.Connection):
    add_node(conn, "prob1", "Problem", {
        "title": "test", "description": "test", "severity": "low",
        "status": "open", "source_date": "2026-06-15", "artifact_class": "B",
    })
    node = get_node(conn, "prob1")
    assert node is not None


def test_source_date_valid_datetime(conn: sqlite3.Connection):
    add_node(conn, "prob1", "Problem", {
        "title": "test", "description": "test", "severity": "low",
        "status": "open", "source_date": "2026-06-15T10:30:00", "artifact_class": "B",
    })
    node = get_node(conn, "prob1")
    assert node is not None


def test_source_date_invalid_rejected(conn: sqlite3.Connection):
    with pytest.raises(ValueError, match="ISO-8601"):
        add_node(conn, "prob1", "Problem", {
            "title": "test", "description": "test", "severity": "low",
            "status": "open", "source_date": "yesterday", "artifact_class": "B",
        })
