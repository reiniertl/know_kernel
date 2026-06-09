"""Tests for kk-ingest CLI â€” ALG-KK-INGEST-CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ingest.cli", *args],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[1]),
    )


class TestIngestCli:
    def test_ingest_cli_success(self, tmp_path: Path) -> None:
        doc = tmp_path / "doc.txt"
        doc.write_text("MIT License. Copyright 2024 The Authors.")
        db = tmp_path / "master.db"

        result = _run_cli(
            "--db", str(db),
            "--input", str(doc),
            "--url", "https://example.com/doc.txt",
            "--type", "paper",
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        report = json.loads(result.stdout)
        assert report["ingested"] == 1
        assert report["errors"] == 0
        assert len(report["results"]) == 1
        assert report["results"][0]["file"] == str(doc)

    def test_ingest_cli_missing_db(self, tmp_path: Path) -> None:
        doc = tmp_path / "doc.txt"
        doc.write_text("some content")
        invalid_db = tmp_path / "nonexistent_dir" / "db.db"

        result = _run_cli(
            "--db", str(invalid_db),
            "--input", str(doc),
            "--url", "https://example.com/doc.txt",
        )
        assert result.returncode == 2
        assert "Error" in result.stderr

    def test_ingest_cli_missing_input(self, tmp_path: Path) -> None:
        db = tmp_path / "master.db"
        missing = tmp_path / "nonexistent.txt"

        result = _run_cli(
            "--db", str(db),
            "--input", str(missing),
            "--url", "https://example.com/missing.txt",
        )
        assert result.returncode == 2
        assert "Error" in result.stderr

    def test_ingest_cli_directory(self, tmp_path: Path) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "a.txt").write_text("Apache License Version 2.0")
        (docs_dir / "b.txt").write_text("GPL v2 applies to this file")
        db = tmp_path / "master.db"

        result = _run_cli(
            "--db", str(db),
            "--input", str(docs_dir),
            "--url", "https://example.com/docs",
            "--type", "paper",
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        report = json.loads(result.stdout)
        assert report["ingested"] == 2
        assert report["errors"] == 0
