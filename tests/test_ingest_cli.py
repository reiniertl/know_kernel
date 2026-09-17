"""Tests for kk-ingest CLI — ALG-KK-INGEST-CLI."""

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


# ---------------------------------------------------------------------------
# INV-KK-PAPER-SOURCE-TYPE-VOCABULARY.
#
# Three modules carried their own copy of "which source types are papers" and
# two disagreed with the third: cli_summaries named the narrow set while
# web.routes and batch_score each added 'paper'. The disagreement selected the
# same rows, because no Source has ever carried source_type 'paper' — but
# kk-ingest DEFAULTED new Sources to exactly that phantom value, so every
# ingested document was typed out of consideration before anything read it.
#
# The narrow set is canonical (operator decision 2026-09-17). Nothing in the
# language keeps three literal copies in step, so these tests are the
# enforcement: without them the invariant would be a claim rather than a rule.
# ---------------------------------------------------------------------------

CANONICAL_PAPER_TYPES = ("preprint", "conference-paper", "conference-proceedings")


def _sql_type_lists(path: str) -> list[set[str]]:
    """Every ('a','b',...) literal in a file that names source types."""
    import re

    text = (Path(__file__).resolve().parents[1] / path).read_text(encoding="utf-8")
    found = []
    for match in re.finditer(r"\(('(?:[a-z-]+)'(?:\s*,\s*'(?:[a-z-]+)')*)\)", text):
        values = {v.strip().strip("'") for v in match.group(1).split(",")}
        if "preprint" in values:
            found.append(values)
    return found


class TestPaperSourceTypeVocabulary:
    def test_cli_default_type_is_in_the_canonical_set(self) -> None:
        """The default must be a value the summary batch will actually consider."""
        from ingest.cli import main  # noqa: F401  (import proves the module loads)

        text = (Path(__file__).resolve().parents[1] / "src/ingest/cli.py").read_text()
        assert 'default="preprint"' in text
        assert "preprint" in CANONICAL_PAPER_TYPES

    def test_summary_batch_uses_the_canonical_set(self) -> None:
        from ingest.cli_summaries import PAPER_SOURCE_TYPES

        assert set(PAPER_SOURCE_TYPES) == set(CANONICAL_PAPER_TYPES)

    @pytest.mark.parametrize("path", ["src/web/routes.py", "src/ingest/batch_score.py"])
    def test_sql_copies_agree_with_the_canonical_set(self, path: str) -> None:
        lists = _sql_type_lists(path)
        assert lists, f"{path}: found no source-type list to check"
        for values in lists:
            assert values == set(CANONICAL_PAPER_TYPES), (
                f"{path} names {sorted(values)}, canonical is {sorted(CANONICAL_PAPER_TYPES)}"
            )
