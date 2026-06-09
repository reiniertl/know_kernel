"""Tests for the kk-export CLI entry point."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from graph.schema import init_db
from graph.engine import add_node, add_edge


@pytest.fixture
def cli_master_db(tmp_path: Path) -> Path:
    """Admissible master DB for CLI tests."""
    db_path = tmp_path / "master.db"
    conn = init_db(db_path)
    add_node(conn, "sub1", "Subsystem", {"name": "scheduler"})
    add_node(conn, "c1", "Concept", {"name": "RCU", "description": "read-copy-update", "artifact_class": "B"})
    add_node(conn, "src1", "Source", {"url": "http://ex.com", "source_type": "paper", "license": "PD"})
    add_node(conn, "ev1", "Evidence", {"artifact_class": "A", "contamination_level": "L0"})
    add_node(conn, "adv1", "Advisory", {"assessment": "safe"})
    add_edge(conn, "belongs-to", "c1", "sub1")
    add_edge(conn, "extracted-from", "c1", "ev1")
    add_edge(conn, "sourced-from", "ev1", "src1")
    add_edge(conn, "assessed-by", "src1", "adv1")
    conn.commit()
    conn.close()
    return db_path


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "export.cli", *args],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[1]),
    )


class TestExportCli:
    def test_success_exit_code(self, cli_master_db: Path, tmp_path: Path) -> None:
        output = tmp_path / "snapshot.db"
        result = _run_cli("--master-db", str(cli_master_db), "--output-db", str(output))
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert output.exists()

    def test_json_output_structure(self, cli_master_db: Path, tmp_path: Path) -> None:
        output = tmp_path / "snapshot.db"
        result = _run_cli("--master-db", str(cli_master_db), "--output-db", str(output))
        assert result.returncode == 0, f"stderr: {result.stderr}"
        report = json.loads(result.stdout)
        assert "node_count" in report
        assert "edge_count" in report
        assert "class_a_count" in report
        assert "issues" in report
        assert report["class_a_count"] == 0
        assert report["issues"] == []

    def test_node_count_in_report(self, cli_master_db: Path, tmp_path: Path) -> None:
        output = tmp_path / "snapshot.db"
        result = _run_cli("--master-db", str(cli_master_db), "--output-db", str(output))
        report = json.loads(result.stdout)
        assert report["node_count"] == 2  # sub1, c1
        assert report["edge_count"] == 1  # belongs-to

    def test_missing_master_db_exit_2(self, tmp_path: Path) -> None:
        output = tmp_path / "snapshot.db"
        result = _run_cli("--master-db", str(tmp_path / "nonexistent.db"), "--output-db", str(output))
        assert result.returncode == 2
        assert "not found" in result.stderr

    def test_output_already_exists_exit_2(self, cli_master_db: Path, tmp_path: Path) -> None:
        output = tmp_path / "exists.db"
        output.write_text("")
        result = _run_cli("--master-db", str(cli_master_db), "--output-db", str(output))
        assert result.returncode == 2
        assert "already exists" in result.stderr

    def test_missing_args_exit_nonzero(self) -> None:
        result = _run_cli()
        assert result.returncode != 0

    def test_validation_failure_exit_1(self, tmp_path: Path) -> None:
        """Master DB with admissibility violations â†’ exit 1."""
        master = tmp_path / "bad.db"
        conn = init_db(master)
        add_node(conn, "c1", "Concept", {"name": "X", "description": "x", "artifact_class": "B"})
        conn.commit()
        conn.close()
        output = tmp_path / "snapshot.db"
        result = _run_cli("--master-db", str(master), "--output-db", str(output))
        assert result.returncode == 1
        assert "FAIL" in result.stderr
