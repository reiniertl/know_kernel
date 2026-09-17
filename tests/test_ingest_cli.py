"""Tests for kk-ingest CLI — ALG-KK-INGEST-CLI."""

from __future__ import annotations

import json
import sqlite3
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


# ---------------------------------------------------------------------------
# D-15b: summary extraction as a final stage of kk-ingest.
#
# It is a STAGE, not a call inside ingest_document. ingest_document is
# per-document, synchronous and offline; extraction is a rate-limited network
# call. Inline, one API failure would leave a document written but unsummarised
# with nothing recording which half failed. As a stage the documents are already
# committed before the first model call — which is what
# test_a_failed_summary_stage_keeps_the_documents actually proves.
#
# Every test here drives an INJECTED client and makes no network call, following
# the pattern src/ingest/summary_extractor.py documents for exactly this reason.
# ---------------------------------------------------------------------------

_SUMMARY = ("This paper delegates Linux paging policy to user space via eBPF hooks. "
            "It reports a measurable reduction in page-fault latency on NUMA hardware.")


class _StageClient:
    """Returns a valid summary, or raises to simulate an API failure."""

    def __init__(self, raise_on_call: bool = False):
        self.calls: list[str] = []
        self.raise_on_call = raise_on_call

    def create_message(self, model: str, system: str, user: str, max_tokens: int) -> dict:
        if self.raise_on_call:
            raise RuntimeError("simulated API failure")
        self.calls.append(user)
        return {"text": json.dumps({"summary": _SUMMARY}),
                "prompt_tokens": 11, "response_tokens": 22}


def _substantive(tmp_path: Path, name: str = "paper.txt") -> Path:
    doc = tmp_path / name
    doc.write_text(
        "Scheduler latency under sustained load is dominated by run queue "
        "contention rather than by context switch cost. " * 12
    )
    return doc


def _run_main(argv: list[str], client=None) -> None:
    """kk-ingest in-process, so a client can be injected. main() exits."""
    from ingest.cli import main

    with pytest.raises(SystemExit) as exc:
        main(argv, client=client)
    assert exc.value.code == 0, "ingestion itself must have succeeded"


def _summaries(db: Path) -> list[tuple[str, str]]:
    conn = sqlite3.connect(str(db))
    try:
        return [
            (r[0], json.loads(r[1])["state"])
            for r in conn.execute("SELECT id, attrs FROM nodes WHERE kind = 'PaperSummary'")
        ]
    finally:
        conn.close()


class TestSummaryStage:
    def test_the_stage_runs_after_the_documents_land(self, tmp_path: Path) -> None:
        db = tmp_path / "master.db"
        client = _StageClient()

        _run_main(["--db", str(db), "--input", str(_substantive(tmp_path)),
                   "--url", "https://example.com/p", "--type", "preprint"], client=client)

        assert len(client.calls) == 1, "one document, one model call"
        rows = _summaries(db)
        assert len(rows) == 1
        assert rows[0][1] == "llm-extracted"

    def test_skip_summaries_suppresses_the_stage(self, tmp_path: Path) -> None:
        db = tmp_path / "master.db"
        client = _StageClient(raise_on_call=True)

        _run_main(["--db", str(db), "--input", str(_substantive(tmp_path)),
                   "--url", "https://example.com/p", "--type", "preprint",
                   "--skip-summaries"], client=client)

        assert _summaries(db) == []
        conn = sqlite3.connect(str(db))
        try:
            assert conn.execute("SELECT count(*) FROM nodes WHERE kind='Source'").fetchone()[0] == 1
        finally:
            conn.close()

    def test_a_failed_summary_stage_keeps_the_documents(self, tmp_path: Path) -> None:
        """The whole argument for a stage over an inline call, proven."""
        db = tmp_path / "master.db"
        client = _StageClient(raise_on_call=True)

        _run_main(["--db", str(db), "--input", str(_substantive(tmp_path)),
                   "--url", "https://example.com/p", "--type", "preprint"], client=client)

        conn = sqlite3.connect(str(db))
        try:
            assert conn.execute("SELECT count(*) FROM nodes WHERE kind='Source'").fetchone()[0] == 1
            assert conn.execute("SELECT count(*) FROM nodes WHERE kind='Evidence'").fetchone()[0] == 1
            assert conn.execute(
                "SELECT count(*) FROM edges WHERE kind='sourced-from'"
            ).fetchone()[0] == 1
        finally:
            conn.close()
        assert _summaries(db) == [], "the summary is what was lost, not the document"

    def test_the_stage_is_scoped_to_what_this_run_ingested(self, tmp_path: Path) -> None:
        """Unscoped, one ingest would summarise every unsummarised paper in the
        database. The second run must cost exactly one call, not two."""
        db = tmp_path / "master.db"
        first, second = _substantive(tmp_path, "a.txt"), _substantive(tmp_path, "b.txt")

        skip = _StageClient(raise_on_call=True)
        _run_main(["--db", str(db), "--input", str(first), "--url", "https://example.com/a",
                   "--type", "preprint", "--skip-summaries"], client=skip)
        assert _summaries(db) == []

        client = _StageClient()
        _run_main(["--db", str(db), "--input", str(second), "--url", "https://example.com/b",
                   "--type", "preprint"], client=client)

        assert len(client.calls) == 1, "the unsummarised first paper must be left alone"
        assert len(_summaries(db)) == 1
