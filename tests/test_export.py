"""Tests for the snapshot exporter — the contamination gate."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from know_kernel.graph.schema import init_db
from know_kernel.graph.engine import add_node, add_edge
from know_kernel.export.exporter import (
    ALLOWED_KINDS,
    ExportValidationError,
    export_class_b_snapshot,
    validate_snapshot,
)


@pytest.fixture
def master_db(tmp_path: Path) -> Path:
    """Create a master DB with mixed Class A + B + C content that passes admissibility."""
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


class TestExportClassBSnapshot:
    def test_produces_class_b_only(self, master_db: Path, tmp_path: Path) -> None:
        output = tmp_path / "snapshot.db"
        report = export_class_b_snapshot(master_db, output)
        assert output.exists()
        assert report["class_a_count"] == 0
        assert report["issues"] == []

    def test_allowed_kinds_only(self, master_db: Path, tmp_path: Path) -> None:
        """INV-KK-SNAPSHOT-ALLOWED-KINDS: only Concept, Subsystem, Proposal in output."""
        output = tmp_path / "snapshot.db"
        export_class_b_snapshot(master_db, output)
        conn = sqlite3.connect(str(output))
        kinds = {row[0] for row in conn.execute("SELECT DISTINCT kind FROM nodes").fetchall()}
        conn.close()
        assert kinds <= set(ALLOWED_KINDS)
        assert "Evidence" not in kinds
        assert "Source" not in kinds
        assert "Advisory" not in kinds

    def test_no_dangling_edges(self, master_db: Path, tmp_path: Path) -> None:
        """INV-KK-SNAPSHOT-NO-DANGLING-EDGES: all edge endpoints exist in snapshot."""
        output = tmp_path / "snapshot.db"
        export_class_b_snapshot(master_db, output)
        conn = sqlite3.connect(str(output))
        dangling = conn.execute(
            "SELECT COUNT(*) FROM edges WHERE source_id NOT IN (SELECT id FROM nodes) "
            "OR target_id NOT IN (SELECT id FROM nodes)"
        ).fetchone()[0]
        conn.close()
        assert dangling == 0

    def test_schema_match(self, master_db: Path, tmp_path: Path) -> None:
        """INV-KK-SNAPSHOT-SCHEMA-MATCH: same table schema as master."""
        output = tmp_path / "snapshot.db"
        export_class_b_snapshot(master_db, output)
        master_conn = sqlite3.connect(str(master_db))
        snap_conn = sqlite3.connect(str(output))
        master_tables = {
            row[0]: row[1]
            for row in master_conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type IN ('table','index') "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        }
        snap_tables = {
            row[0]: row[1]
            for row in snap_conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type IN ('table','index') "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        }
        master_conn.close()
        snap_conn.close()
        assert master_tables == snap_tables

    def test_node_counts(self, master_db: Path, tmp_path: Path) -> None:
        output = tmp_path / "snapshot.db"
        report = export_class_b_snapshot(master_db, output)
        assert report["node_count"] == 4  # sub1, c1, c2, prop1
        # belongs-to x2, grounded-in, alternative-to survive; extracted-from, sourced-from, assessed-by filtered
        assert report["edge_count"] == 4

    def test_edge_filtering(self, master_db: Path, tmp_path: Path) -> None:
        """Edges referencing filtered-out nodes must not appear."""
        output = tmp_path / "snapshot.db"
        export_class_b_snapshot(master_db, output)
        conn = sqlite3.connect(str(output))
        edge_kinds = [row[0] for row in conn.execute("SELECT kind FROM edges").fetchall()]
        conn.close()
        assert "extracted-from" not in edge_kinds
        assert "sourced-from" not in edge_kinds
        assert "assessed-by" not in edge_kinds
        assert "belongs-to" in edge_kinds
        assert "grounded-in" in edge_kinds

    def test_contamination_gate_zero_class_a(self, master_db: Path, tmp_path: Path) -> None:
        """INV-KK-CONTAMINATION-GATE + INV-KK-SNAPSHOT-ZERO-CLASS-A."""
        output = tmp_path / "snapshot.db"
        report = export_class_b_snapshot(master_db, output)
        assert report["class_a_count"] == 0

    def test_empty_master_db(self, tmp_path: Path) -> None:
        """Export from an empty master should produce an empty snapshot."""
        master = tmp_path / "empty.db"
        init_db(master).close()
        output = tmp_path / "snapshot.db"
        report = export_class_b_snapshot(master, output)
        assert report["node_count"] == 0
        assert report["edge_count"] == 0
        assert report["issues"] == []

    def test_concepts_only_master(self, tmp_path: Path) -> None:
        """Master with admissible Class B content should export everything."""
        master = tmp_path / "clean.db"
        conn = init_db(master)
        add_node(conn, "sub1", "Subsystem", {"name": "test"})
        add_node(conn, "c1", "Concept", {"name": "X", "description": "x", "artifact_class": "B"})
        add_node(conn, "c2", "Concept", {"name": "Y", "description": "y", "artifact_class": "B"})
        add_node(conn, "src1", "Source", {"url": "http://ex.com", "source_type": "paper", "license": "PD"})
        add_node(conn, "src2", "Source", {"url": "http://ex2.com", "source_type": "paper", "license": "PD"})
        add_node(conn, "ev1", "Evidence", {"artifact_class": "A", "contamination_level": "L0"})
        add_node(conn, "ev2", "Evidence", {"artifact_class": "A", "contamination_level": "L0"})
        add_node(conn, "adv1", "Advisory", {"assessment": "safe"})
        add_node(conn, "adv2", "Advisory", {"assessment": "safe"})
        add_edge(conn, "belongs-to", "c1", "sub1")
        add_edge(conn, "belongs-to", "c2", "sub1")
        add_edge(conn, "extracted-from", "c1", "ev1")
        add_edge(conn, "extracted-from", "c2", "ev2")
        add_edge(conn, "sourced-from", "ev1", "src1")
        add_edge(conn, "sourced-from", "ev2", "src2")
        add_edge(conn, "assessed-by", "src1", "adv1")
        add_edge(conn, "assessed-by", "src2", "adv2")
        add_edge(conn, "refines", "c1", "c2")
        conn.commit()
        conn.close()
        output = tmp_path / "snapshot.db"
        report = export_class_b_snapshot(master, output)
        assert report["node_count"] == 3  # sub1, c1, c2
        assert report["edge_count"] == 3  # belongs-to x2, refines


class TestValidateSnapshot:
    def test_detects_forbidden_kinds(self, tmp_path: Path) -> None:
        db_path = tmp_path / "bad.db"
        conn = init_db(db_path)
        add_node(conn, "c1", "Concept", {"name": "X", "description": "x", "artifact_class": "B"})
        add_node(conn, "ev1", "Evidence", {"artifact_class": "A", "contamination_level": "L0"})
        conn.commit()
        report = validate_snapshot(conn)
        conn.close()
        assert len(report["issues"]) > 0
        assert report["class_a_count"] == 1
        assert "Evidence" in report["issues"][0]
