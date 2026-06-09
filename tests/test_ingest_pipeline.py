"""Tests for ingest_document â€” INV-KK-INGEST-CREATES-EVIDENCE."""

import pytest

from graph.engine import validate_graph
from graph.schema import init_db
from ingest.gate import SessionGate, SessionViolationError
from ingest.scanner import ArtifactClass
from ingest.pipeline import IngestResult, ingest_document


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "test.db")


@pytest.fixture
def doc_file(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("MIT License. Copyright 2024 The Authors.")
    return str(f)


class TestIngestDocument:
    def test_ingest_creates_source_and_evidence(self, conn, doc_file):
        result = ingest_document(conn, doc_file, "https://example.com/doc.txt", "paper")
        source = conn.execute(
            "SELECT id, kind FROM nodes WHERE id = ?", (result.source_id,)
        ).fetchone()
        evidence = conn.execute(
            "SELECT id, kind FROM nodes WHERE id = ?", (result.evidence_id,)
        ).fetchone()
        assert source is not None and source[1] == "Source"
        assert evidence is not None and evidence[1] == "Evidence"

    def test_ingest_creates_sourced_from_edge(self, conn, doc_file):
        result = ingest_document(conn, doc_file, "https://example.com/doc.txt", "paper")
        edge = conn.execute(
            "SELECT 1 FROM edges WHERE kind = 'sourced-from' AND source_id = ? AND target_id = ?",
            (result.evidence_id, result.source_id),
        ).fetchone()
        assert edge is not None

    def test_ingest_evidence_is_class_a(self, conn, doc_file):
        result = ingest_document(conn, doc_file, "https://example.com/doc.txt", "paper")
        assert result.scan_result.artifact_class == ArtifactClass.A

    def test_ingest_validates_graph_after_write(self, conn, doc_file):
        result = ingest_document(conn, doc_file, "https://example.com/doc.txt", "paper")
        violations = validate_graph(conn)
        ev_violations = [v for v in violations if v.node_id == result.evidence_id]
        assert ev_violations == []

    def test_ingest_nonexistent_file_raises(self, conn, tmp_path):
        with pytest.raises(FileNotFoundError):
            ingest_document(
                conn,
                str(tmp_path / "nonexistent.txt"),
                "https://example.com/missing.txt",
                "paper",
            )

    def test_ingest_proposal_mode_rejects_class_a(self, conn, doc_file):
        gate = SessionGate()
        gate.record_proposal()
        with pytest.raises(SessionViolationError):
            ingest_document(conn, doc_file, "https://example.com/doc.txt", "paper", gate=gate)

    def test_ingest_clean_gate_enters_extraction_mode(self, conn, doc_file):
        gate = SessionGate()
        ingest_document(conn, doc_file, "https://example.com/doc.txt", "paper", gate=gate)
        assert gate.is_extraction_mode is True

    def test_ingest_empty_file_raises(self, conn, tmp_path):
        empty = tmp_path / "empty.txt"
        empty.write_bytes(b"")
        with pytest.raises(ValueError, match="Empty document"):
            ingest_document(conn, str(empty), "https://example.com/empty.txt", "paper")

    def test_no_advisory_after_ingest(self, conn, doc_file):
        """INV-KK-INGEST-SOURCE-HAS-ADVISORY: ingestion creates no Advisory nodes."""
        ingest_document(conn, doc_file, "https://example.com/doc.txt", "paper")
        count = conn.execute("SELECT COUNT(*) FROM nodes WHERE kind = 'Advisory'").fetchone()[0]
        assert count == 0
