"""Tests for graph.optimization — OptimizationGoal and UseCaseScenario creation and linking."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from graph.schema import init_db
from graph.engine import add_node, add_edge
from graph.optimization import (
    create_comparative_analysis,
    create_kernel,
    create_optimization_goal,
    create_use_case_scenario,
    link_concept_to_goal,
    link_concept_to_kernel,
    link_concept_to_scenario,
)
from export.exporter import export_class_b_snapshot


class TestCreateOptimizationGoal:
    def test_create_goal(self, conn: sqlite3.Connection) -> None:
        goal_id = create_optimization_goal(conn, "Minimize Latency", "Reduce read latency", "latency", "minimize")
        assert goal_id.startswith("goal-")
        row = conn.execute("SELECT kind, attrs FROM nodes WHERE id = ?", (goal_id,)).fetchone()
        assert row[0] == "OptimizationGoal"
        attrs = json.loads(row[1])
        assert attrs["name"] == "Minimize Latency"
        assert attrs["description"] == "Reduce read latency"
        assert attrs["metric"] == "latency"
        assert attrs["direction"] == "minimize"

    def test_create_goal_invalid_direction(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError, match="direction"):
            create_optimization_goal(conn, "Bad Goal", "desc", "metric", "upward")


class TestLinkConceptToGoal:
    def test_link_concept_to_goal(self, conn: sqlite3.Connection) -> None:
        add_node(conn, "sub1", "Subsystem", {"name": "test"})
        add_node(conn, "c1", "Concept", {"name": "RCU", "description": "x", "artifact_class": "abstracted-mechanism", "key_properties": ["lock-free"], "tradeoffs": [], "design_rationale": "test"})
        add_edge(conn, "belongs-to", "c1", "sub1")
        goal_id = create_optimization_goal(conn, "Min Latency", "desc", "latency", "minimize")
        link_concept_to_goal(conn, "c1", goal_id, "improves", "strong")
        edge = conn.execute(
            "SELECT kind, attrs FROM edges WHERE source_id = ? AND target_id = ?",
            ("c1", goal_id),
        ).fetchone()
        assert edge[0] == "contributes-to"
        edge_attrs = json.loads(edge[1])
        assert edge_attrs["direction"] == "improves"
        assert edge_attrs["magnitude"] == "strong"

    def test_link_concept_to_goal_invalid_direction(self, conn: sqlite3.Connection) -> None:
        add_node(conn, "sub1", "Subsystem", {"name": "test"})
        add_node(conn, "c1", "Concept", {"name": "X", "description": "x", "artifact_class": "abstracted-mechanism", "key_properties": ["a"], "tradeoffs": [], "design_rationale": "test"})
        goal_id = create_optimization_goal(conn, "G", "d", "m", "minimize")
        with pytest.raises(ValueError, match="direction"):
            link_concept_to_goal(conn, "c1", goal_id, "up", "strong")

    def test_link_concept_to_goal_invalid_magnitude(self, conn: sqlite3.Connection) -> None:
        add_node(conn, "sub1", "Subsystem", {"name": "test"})
        add_node(conn, "c1", "Concept", {"name": "X", "description": "x", "artifact_class": "abstracted-mechanism", "key_properties": ["a"], "tradeoffs": [], "design_rationale": "test"})
        goal_id = create_optimization_goal(conn, "G", "d", "m", "maximize")
        with pytest.raises(ValueError, match="magnitude"):
            link_concept_to_goal(conn, "c1", goal_id, "improves", "huge")


class TestCreateUseCaseScenario:
    def test_create_scenario(self, conn: sqlite3.Connection) -> None:
        scenario_id = create_use_case_scenario(conn, "CPU-Bound Batch", "Heavy CPU workload", "cpu-bound", "single-node")
        assert scenario_id.startswith("scenario-")
        row = conn.execute("SELECT kind, attrs FROM nodes WHERE id = ?", (scenario_id,)).fetchone()
        assert row[0] == "UseCaseScenario"
        attrs = json.loads(row[1])
        assert attrs["name"] == "CPU-Bound Batch"
        assert attrs["description"] == "Heavy CPU workload"
        assert attrs["workload_type"] == "cpu-bound"
        assert attrs["constraints"] == "single-node"


class TestLinkConceptToScenario:
    def test_link_concept_to_scenario(self, conn: sqlite3.Connection) -> None:
        add_node(conn, "sub1", "Subsystem", {"name": "test"})
        add_node(conn, "c1", "Concept", {"name": "RCU", "description": "x", "artifact_class": "abstracted-mechanism", "key_properties": ["lock-free"], "tradeoffs": [], "design_rationale": "test"})
        add_edge(conn, "belongs-to", "c1", "sub1")
        scenario_id = create_use_case_scenario(conn, "RT Workload", "real-time", "real-time", "< 1ms deadline")
        link_concept_to_scenario(conn, "c1", scenario_id, "excellent")
        edge = conn.execute(
            "SELECT kind, attrs FROM edges WHERE source_id = ? AND target_id = ?",
            ("c1", scenario_id),
        ).fetchone()
        assert edge[0] == "suited-for"
        edge_attrs = json.loads(edge[1])
        assert edge_attrs["fitness"] == "excellent"

    def test_link_concept_to_scenario_invalid_fitness(self, conn: sqlite3.Connection) -> None:
        add_node(conn, "sub1", "Subsystem", {"name": "test"})
        add_node(conn, "c1", "Concept", {"name": "X", "description": "x", "artifact_class": "abstracted-mechanism", "key_properties": ["a"], "tradeoffs": [], "design_rationale": "test"})
        scenario_id = create_use_case_scenario(conn, "S", "d", "batch", "none")
        with pytest.raises(ValueError, match="fitness"):
            link_concept_to_scenario(conn, "c1", scenario_id, "amazing")


class TestGoalScenarioInSnapshot:
    def test_goal_scenario_in_snapshot(self, tmp_path: Path) -> None:
        master = tmp_path / "master.db"
        conn = init_db(master)

        add_node(conn, "sub1", "Subsystem", {"name": "scheduler"})
        add_node(conn, "c1", "Concept", {
            "name": "RCU", "description": "Read-Copy-Update",
            "artifact_class": "abstracted-mechanism",
            "key_properties": ["lock-free reads"], "tradeoffs": [],
            "design_rationale": "Fast read-side critical sections",
        })
        add_node(conn, "src1", "Source", {"url": "http://ex.com", "source_type": "paper", "license": "PD"})
        add_node(conn, "ev1", "Evidence", {"artifact_class": "verbatim-extract", "contamination_level": "L1"})
        add_node(conn, "adv1", "Advisory", {"assessment": "safe", "contamination_confirmed": "none"})
        add_edge(conn, "belongs-to", "c1", "sub1")
        add_edge(conn, "extracted-from", "c1", "ev1")
        add_edge(conn, "sourced-from", "ev1", "src1")
        add_edge(conn, "assessed-by", "src1", "adv1")

        goal_id = create_optimization_goal(conn, "Min Latency", "Reduce latency", "latency", "minimize")
        link_concept_to_goal(conn, "c1", goal_id, "improves", "strong")

        scenario_id = create_use_case_scenario(conn, "RT Workload", "real-time tasks", "real-time", "< 1ms")
        link_concept_to_scenario(conn, "c1", scenario_id, "excellent")

        conn.commit()
        conn.close()

        output = tmp_path / "snapshot.db"
        report = export_class_b_snapshot(master, output)
        assert report["issues"] == []
        assert report["class_a_count"] == 0

        snap_conn = sqlite3.connect(str(output))
        kinds = {row[0] for row in snap_conn.execute("SELECT DISTINCT kind FROM nodes").fetchall()}
        assert "OptimizationGoal" in kinds
        assert "UseCaseScenario" in kinds

        ct_edges = snap_conn.execute("SELECT attrs FROM edges WHERE kind = 'contributes-to'").fetchall()
        assert len(ct_edges) == 1
        ct_attrs = json.loads(ct_edges[0][0])
        assert ct_attrs["direction"] == "improves"
        assert ct_attrs["magnitude"] == "strong"

        sf_edges = snap_conn.execute("SELECT attrs FROM edges WHERE kind = 'suited-for'").fetchall()
        assert len(sf_edges) == 1
        sf_attrs = json.loads(sf_edges[0][0])
        assert sf_attrs["fitness"] == "excellent"

        snap_conn.close()


class TestCreateComparativeAnalysis:
    def test_create_comparative_manual(self, conn: sqlite3.Connection) -> None:
        add_node(conn, "sub1", "Subsystem", {"name": "test"})
        add_node(conn, "c1", "Concept", {"name": "RCU", "description": "x", "artifact_class": "abstracted-mechanism", "key_properties": ["lock-free"], "tradeoffs": [], "design_rationale": "test"})
        add_node(conn, "c2", "Concept", {"name": "Spinlock", "description": "y", "artifact_class": "abstracted-mechanism", "key_properties": ["simple"], "tradeoffs": [], "design_rationale": "test"})
        analysis_id = create_comparative_analysis(conn, "c1", "c2", "read latency", "RCU", "read-heavy", "10x faster")
        assert analysis_id.startswith("comparative-")
        row = conn.execute("SELECT kind, attrs FROM nodes WHERE id = ?", (analysis_id,)).fetchone()
        assert row[0] == "ComparativeAnalysis"
        attrs = json.loads(row[1])
        assert attrs["dimension"] == "read latency"
        assert attrs["winner"] == "RCU"
        assert attrs["artifact_class"] == "abstracted-mechanism"
        edges = conn.execute("SELECT target_id FROM edges WHERE kind = 'compares' AND source_id = ?", (analysis_id,)).fetchall()
        targets = {e[0] for e in edges}
        assert len(targets) == 2
        assert "c1" in targets
        assert "c2" in targets
        prov_edges = conn.execute("SELECT COUNT(*) FROM edges WHERE kind = 'extracted-from' AND source_id = ?", (analysis_id,)).fetchone()[0]
        assert prov_edges == 0

    def test_comparative_in_snapshot(self, tmp_path: Path) -> None:
        master = tmp_path / "master.db"
        conn = init_db(master)
        add_node(conn, "sub1", "Subsystem", {"name": "scheduler"})
        add_node(conn, "c1", "Concept", {
            "name": "RCU", "description": "Read-Copy-Update",
            "artifact_class": "abstracted-mechanism",
            "key_properties": ["lock-free reads"], "tradeoffs": [],
            "design_rationale": "Fast read-side critical sections",
        })
        add_node(conn, "c2", "Concept", {
            "name": "Spinlock", "description": "Spin-based lock",
            "artifact_class": "abstracted-mechanism",
            "key_properties": ["simple mutual exclusion"], "tradeoffs": [],
            "design_rationale": "Basic synchronization primitive",
        })
        add_node(conn, "src1", "Source", {"url": "http://ex.com", "source_type": "paper", "license": "PD"})
        add_node(conn, "ev1", "Evidence", {"artifact_class": "verbatim-extract", "contamination_level": "L1"})
        add_node(conn, "adv1", "Advisory", {"assessment": "safe", "contamination_confirmed": "none"})
        add_edge(conn, "belongs-to", "c1", "sub1")
        add_edge(conn, "belongs-to", "c2", "sub1")
        add_edge(conn, "extracted-from", "c1", "ev1")
        add_edge(conn, "extracted-from", "c2", "ev1")
        add_edge(conn, "sourced-from", "ev1", "src1")
        add_edge(conn, "assessed-by", "src1", "adv1")
        analysis_id = create_comparative_analysis(conn, "c1", "c2", "read latency", "RCU", "read-heavy", "10x")
        conn.commit()
        conn.close()

        output = tmp_path / "snapshot.db"
        report = export_class_b_snapshot(master, output)
        assert report["issues"] == []

        snap_conn = sqlite3.connect(str(output))
        kinds = {row[0] for row in snap_conn.execute("SELECT DISTINCT kind FROM nodes").fetchall()}
        assert "ComparativeAnalysis" in kinds
        compares_edges = snap_conn.execute("SELECT COUNT(*) FROM edges WHERE kind = 'compares'").fetchone()[0]
        assert compares_edges == 2
        snap_conn.close()


class TestCreateKernel:
    def test_create_kernel(self, conn: sqlite3.Connection) -> None:
        kernel_id = create_kernel(conn, "Linux", "Monolithic Unix-like kernel", "monolithic")
        assert kernel_id.startswith("kernel-")
        row = conn.execute("SELECT kind, attrs FROM nodes WHERE id = ?", (kernel_id,)).fetchone()
        assert row[0] == "Kernel"
        attrs = json.loads(row[1])
        assert attrs["name"] == "Linux"
        assert attrs["description"] == "Monolithic Unix-like kernel"
        assert attrs["kernel_type"] == "monolithic"

    def test_create_kernel_empty_name(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError, match="name"):
            create_kernel(conn, "", "A kernel", "monolithic")

    def test_create_kernel_invalid_type(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError, match="kernel_type"):
            create_kernel(conn, "BadKernel", "desc", "exokernel")


class TestLinkConceptToKernel:
    def test_link_concept_to_kernel(self, conn: sqlite3.Connection) -> None:
        add_node(conn, "sub1", "Subsystem", {"name": "test"})
        add_node(conn, "c1", "Concept", {"name": "RCU", "description": "x", "artifact_class": "abstracted-mechanism", "key_properties": ["lock-free"], "tradeoffs": [], "design_rationale": "test"})
        add_edge(conn, "belongs-to", "c1", "sub1")
        kernel_id = create_kernel(conn, "Linux", "Monolithic Unix-like kernel", "monolithic")
        link_concept_to_kernel(conn, "c1", kernel_id, since_version="2.5", maturity="production", variant_notes="Tree RCU variant")
        edge = conn.execute(
            "SELECT kind, attrs FROM edges WHERE source_id = ? AND target_id = ?",
            ("c1", kernel_id),
        ).fetchone()
        assert edge[0] == "implemented-in"
        edge_attrs = json.loads(edge[1])
        assert edge_attrs["since_version"] == "2.5"
        assert edge_attrs["maturity"] == "production"
        assert edge_attrs["variant_notes"] == "Tree RCU variant"

    def test_link_concept_to_kernel_invalid_maturity(self, conn: sqlite3.Connection) -> None:
        add_node(conn, "sub1", "Subsystem", {"name": "test"})
        add_node(conn, "c1", "Concept", {"name": "X", "description": "x", "artifact_class": "abstracted-mechanism", "key_properties": ["a"], "tradeoffs": [], "design_rationale": "test"})
        kernel_id = create_kernel(conn, "Linux", "desc", "monolithic")
        with pytest.raises(ValueError, match="maturity"):
            link_concept_to_kernel(conn, "c1", kernel_id, maturity="stable")

    def test_link_concept_to_kernel_default_maturity(self, conn: sqlite3.Connection) -> None:
        add_node(conn, "sub1", "Subsystem", {"name": "test"})
        add_node(conn, "c1", "Concept", {"name": "RCU", "description": "x", "artifact_class": "abstracted-mechanism", "key_properties": ["lock-free"], "tradeoffs": [], "design_rationale": "test"})
        add_edge(conn, "belongs-to", "c1", "sub1")
        kernel_id = create_kernel(conn, "Linux", "desc", "monolithic")
        link_concept_to_kernel(conn, "c1", kernel_id)
        edge = conn.execute(
            "SELECT attrs FROM edges WHERE kind = 'implemented-in' AND source_id = ? AND target_id = ?",
            ("c1", kernel_id),
        ).fetchone()
        edge_attrs = json.loads(edge[0])
        assert edge_attrs["maturity"] == "production"


class TestKernelInSnapshot:
    def test_kernel_in_snapshot(self, tmp_path: Path) -> None:
        master = tmp_path / "master.db"
        conn = init_db(master)

        add_node(conn, "sub1", "Subsystem", {"name": "scheduler"})
        add_node(conn, "c1", "Concept", {
            "name": "RCU", "description": "Read-Copy-Update",
            "artifact_class": "abstracted-mechanism",
            "key_properties": ["lock-free reads"], "tradeoffs": [],
            "design_rationale": "Fast read-side critical sections",
        })
        add_node(conn, "src1", "Source", {"url": "http://ex.com", "source_type": "paper", "license": "PD"})
        add_node(conn, "ev1", "Evidence", {"artifact_class": "verbatim-extract", "contamination_level": "L1"})
        add_node(conn, "adv1", "Advisory", {"assessment": "safe", "contamination_confirmed": "none"})
        add_edge(conn, "belongs-to", "c1", "sub1")
        add_edge(conn, "extracted-from", "c1", "ev1")
        add_edge(conn, "sourced-from", "ev1", "src1")
        add_edge(conn, "assessed-by", "src1", "adv1")

        kernel_id = create_kernel(conn, "Linux", "Monolithic Unix-like kernel", "monolithic")
        link_concept_to_kernel(conn, "c1", kernel_id, since_version="2.5", maturity="production")

        conn.commit()
        conn.close()

        output = tmp_path / "snapshot.db"
        report = export_class_b_snapshot(master, output)
        assert report["issues"] == []
        assert report["class_a_count"] == 0

        snap_conn = sqlite3.connect(str(output))
        kinds = {row[0] for row in snap_conn.execute("SELECT DISTINCT kind FROM nodes").fetchall()}
        assert "Kernel" in kinds

        impl_edges = snap_conn.execute("SELECT attrs FROM edges WHERE kind = 'implemented-in'").fetchall()
        assert len(impl_edges) == 1
        impl_attrs = json.loads(impl_edges[0][0])
        assert impl_attrs["maturity"] == "production"
        assert impl_attrs["since_version"] == "2.5"

        prov_edges = snap_conn.execute(
            "SELECT COUNT(*) FROM edges WHERE kind = 'extracted-from' AND source_id = ?",
            (kernel_id,),
        ).fetchone()[0]
        assert prov_edges == 0

        snap_conn.close()
