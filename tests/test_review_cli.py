"""Tests for kk-review CLI â€” ALG-KK-REVIEW-CLI."""

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
        [sys.executable, "-m", "ingest.cli_review", *args],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[1]),
    )


def _setup_source(db_path: Path) -> str:
    conn = init_db(db_path)
    add_node(conn, "src-cli-test", "Source", {
        "url": "https://example.com/test.txt",
        "source_type": "paper",
        "license": "MIT",
    })
    add_node(conn, "ev-cli-test", "Evidence", {
        "artifact_class": "licensed-evidence",
        "contamination_level": "weak-copyleft",
    })
    add_edge(conn, "sourced-from", "ev-cli-test", "src-cli-test")
    conn.commit()
    conn.close()
    return "src-cli-test"


class TestReviewCli:
    def test_review_cli_success(self, tmp_path: Path) -> None:
        db = tmp_path / "master.db"
        source_id = _setup_source(db)
        result = _run_cli(
            "--db", str(db),
            "--source-id", source_id,
            "--assessment", "License confirmed as MIT.",
            "--confirm-level", "weak-copyleft",
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        report = json.loads(result.stdout)
        assert report["source_id"] == source_id
        assert report["assessment_text"] == "License confirmed as MIT."
        assert report["contamination_confirmed"] == "weak-copyleft"
        assert "advisory_id" in report

    def test_review_cli_nonexistent_source(self, tmp_path: Path) -> None:
        db = tmp_path / "master.db"
        init_db(db).close()
        result = _run_cli(
            "--db", str(db),
            "--source-id", "src-nonexistent",
            "--assessment", "Some text.",
            "--confirm-level", "weak-copyleft",
        )
        assert result.returncode == 1
        assert "Error" in result.stderr

    def test_review_cli_invalid_db(self, tmp_path: Path) -> None:
        invalid_db = tmp_path / "nonexistent_dir" / "db.db"
        result = _run_cli(
            "--db", str(invalid_db),
            "--source-id", "src-test",
            "--assessment", "Some text.",
            "--confirm-level", "weak-copyleft",
        )
        assert result.returncode == 2
        assert "Error" in result.stderr
