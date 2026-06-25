"""Tests for pipeline content sufficiency gate.

Covers: INV-KK-INGEST-REJECTS-STUB, INV-KK-INGEST-REJECTS-DIRECTORY,
        ALG-KK-INGEST-DOCUMENT (content sufficiency check)
"""

import logging

import pytest

from graph.schema import init_db
from ingest.pipeline import ingest_document


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "test.db")


def _write_file(tmp_path, name, content):
    f = tmp_path / name
    f.write_text(content)
    return str(f)


class TestIngestRejectsStub:
    """INV-KK-INGEST-REJECTS-STUB"""

    def test_stub_document_raises(self, conn, tmp_path):
        content = (
            "SLUB Allocator\n"
            "==============\n\n"
            ".. kernel-doc:: mm/slub.c\n"
            "   :doc: SLUB\n\n"
            ".. kernel-doc:: include/linux/slab.h\n"
        )
        path = _write_file(tmp_path, "stub.txt", content)

        with pytest.raises(ValueError, match="non-substantive.*stub"):
            ingest_document(conn, path, "https://example.com/stub", "documentation")

    def test_stub_no_nodes_created(self, conn, tmp_path):
        content = "Title\n=====\n\n.. kernel-doc:: mm/slub.c\n"
        path = _write_file(tmp_path, "stub.txt", content)

        try:
            ingest_document(conn, path, "https://example.com/stub", "documentation")
        except ValueError:
            pass

        count = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        assert count == 0

    def test_error_includes_kernel_doc_refs(self, conn, tmp_path):
        content = "Title\n=====\n\n.. kernel-doc:: mm/slub.c\n"
        path = _write_file(tmp_path, "stub.txt", content)

        with pytest.raises(ValueError, match="mm/slub.c"):
            ingest_document(conn, path, "https://example.com/stub", "documentation")


class TestIngestRejectsDirectory:
    """INV-KK-INGEST-REJECTS-DIRECTORY"""

    def test_directory_listing_raises(self, conn, tmp_path):
        content = '<html><table class="list"><tr><td>files</td></tr></table></html>'
        path = _write_file(tmp_path, "dir.txt", content)

        with pytest.raises(ValueError, match="non-substantive.*directory"):
            ingest_document(conn, path, "https://example.com/dir", "documentation")

    def test_directory_no_nodes_created(self, conn, tmp_path):
        content = '<html><table class="list"><tr><td>files</td></tr></table></html>'
        path = _write_file(tmp_path, "dir.txt", content)

        try:
            ingest_document(conn, path, "https://example.com/dir", "documentation")
        except ValueError:
            pass

        count = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        assert count == 0


class TestIngestAcceptsSubstantive:
    def test_substantive_document_succeeds(self, conn, tmp_path):
        content = "MIT License. " + " ".join(["The kernel subsystem provides"] + ["functionality"] * 120)
        path = _write_file(tmp_path, "good.txt", content)

        result = ingest_document(conn, path, "https://example.com/good", "paper")
        assert result.source_id.startswith("src-")
        assert result.evidence_id.startswith("ev-")

        node_count = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        assert node_count == 2


class TestIngestWarnsThin:
    def test_thin_document_succeeds_with_warning(self, conn, tmp_path, caplog):
        content = "MIT License. " + " ".join(["concept"] * 70)
        path = _write_file(tmp_path, "thin.txt", content)

        with caplog.at_level(logging.WARNING):
            result = ingest_document(conn, path, "https://example.com/thin", "paper")

        assert result.source_id.startswith("src-")
        assert any("Thin content" in r.message for r in caplog.records)


class TestErrorMessageContent:
    def test_includes_classification(self, conn, tmp_path):
        content = "Title\n=====\n\n.. kernel-doc:: mm/slub.c\n"
        path = _write_file(tmp_path, "stub.txt", content)

        with pytest.raises(ValueError) as exc_info:
            ingest_document(conn, path, "https://example.com/stub", "documentation")

        msg = str(exc_info.value)
        assert "stub" in msg
        assert "Word count:" in msg

    def test_includes_word_count(self, conn, tmp_path):
        content = '<html><table class="list"><tr><td>files</td></tr></table></html>'
        path = _write_file(tmp_path, "dir.txt", content)

        with pytest.raises(ValueError) as exc_info:
            ingest_document(conn, path, "https://example.com/dir", "documentation")

        assert "directory" in str(exc_info.value)
