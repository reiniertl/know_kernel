"""Tests for kk-extract CLI â€” ALG-KK-EXTRACT-CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from graph.engine import add_edge, add_node
from graph.schema import init_db


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ingest.cli_extract", *args],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[1]),
    )


def _setup_evidence(db_path: Path) -> str:
    conn = init_db(db_path)
    add_node(conn, "src-cli-ext", "Source", {
        "url": "https://example.com/paper.txt",
        "source_type": "paper",
        "license": "MIT",
    })
    add_node(conn, "ev-cli-ext", "Evidence", {
        "artifact_class": "licensed-evidence",
        "contamination_level": "weak-copyleft",
        "text": "This paper discusses virtual memory management techniques.",
    })
    add_edge(conn, "sourced-from", "ev-cli-ext", "src-cli-ext")
    conn.commit()
    conn.close()
    return "ev-cli-ext"


class TestExtractCli:
    def test_dry_run_single_evidence(self, tmp_path: Path) -> None:
        db = tmp_path / "master.db"
        eid = _setup_evidence(db)
        result = _run_cli(
            "--db", str(db),
            "--evidence-id", eid,
            "--dry-run",
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        report = json.loads(result.stdout)
        assert report["extracted"] == 1
        assert report["errors"] == 0
        assert report["results"][0]["evidence_id"] == eid
        assert report["results"][0]["concepts_created"] == 0

    def test_dry_run_all_unextracted(self, tmp_path: Path) -> None:
        db = tmp_path / "master.db"
        _setup_evidence(db)
        result = _run_cli(
            "--db", str(db),
            "--all-unextracted",
            "--dry-run",
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        report = json.loads(result.stdout)
        assert report["extracted"] == 1

    def test_nonexistent_db(self, tmp_path: Path) -> None:
        invalid_db = tmp_path / "nonexistent_dir" / "db.db"
        result = _run_cli(
            "--db", str(invalid_db),
            "--evidence-id", "ev-test",
        )
        assert result.returncode == 2
        assert "Error" in result.stderr

    def test_nonexistent_evidence_id(self, tmp_path: Path) -> None:
        db = tmp_path / "master.db"
        init_db(db).close()
        result = _run_cli(
            "--db", str(db),
            "--evidence-id", "ev-nonexistent",
        )
        assert result.returncode == 1
        assert "Error" in result.stderr

    def test_all_unextracted_empty(self, tmp_path: Path) -> None:
        db = tmp_path / "master.db"
        init_db(db).close()
        result = _run_cli(
            "--db", str(db),
            "--all-unextracted",
            "--dry-run",
        )
        assert result.returncode == 0
        report = json.loads(result.stdout)
        assert report["extracted"] == 0
