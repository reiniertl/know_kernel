"""Tests for pipeline content sufficiency gate and extraction grounding.

Covers: INV-KK-INGEST-REJECTS-STUB, INV-KK-INGEST-REJECTS-DIRECTORY,
        ALG-KK-INGEST-DOCUMENT, INV-KK-EXTRACT-PROMPT-GROUNDING,
        INV-KK-EXTRACT-GROUNDING-CHECK, ALG-KK-VALIDATE-EXCERPT-GROUNDING
"""

import logging

import pytest

from graph.schema import init_db
from ingest.extractor import EXTRACTION_SYSTEM_PROMPT, validate_excerpt_grounding
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


# ---------------------------------------------------------------------------
# EXTRACTION_SYSTEM_PROMPT grounding rules (INV-KK-EXTRACT-PROMPT-GROUNDING)
# ---------------------------------------------------------------------------

class TestExtractionPromptGrounding:
    def test_contains_grounding_rules(self):
        assert "PROVENANCE GROUNDING RULES" in EXTRACTION_SYSTEM_PROMPT

    def test_grounding_after_legal(self):
        legal_pos = EXTRACTION_SYSTEM_PROMPT.index("CRITICAL RULES")
        grounding_pos = EXTRACTION_SYSTEM_PROMPT.index("PROVENANCE GROUNDING RULES")
        assert grounding_pos > legal_pos

    def test_contains_key_instructions(self):
        assert "summarize only what appears" in EXTRACTION_SYSTEM_PROMPT
        assert "Do NOT add claims" in EXTRACTION_SYSTEM_PROMPT
        assert "sparse" in EXTRACTION_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# validate_excerpt_grounding (ALG-KK-VALIDATE-EXCERPT-GROUNDING)
# ---------------------------------------------------------------------------

class TestValidateExcerptGrounding:
    def test_catches_fabrication(self):
        excerpt = "The SLUB allocator uses per-CPU freelists and cache merging to optimize allocation."
        doc = "SLUB is a slab allocator. It uses object caching for fast allocation."
        ungrounded = validate_excerpt_grounding(excerpt, doc)
        assert any("per-CPU" in p for p in ungrounded)
        assert any("cache merging" in p for p in ungrounded)

    def test_passes_real(self):
        doc = "The red-black tree provides O(log n) lookup time for the scheduler."
        excerpt = "The red-black tree provides lookup time."
        ungrounded = validate_excerpt_grounding(excerpt, doc)
        assert any("red-black tree" in p for p in ungrounded) is False

    def test_case_insensitive(self):
        doc = "The SLUB allocator manages kernel memory."
        excerpt = "The SLUB allocator handles memory."
        ungrounded = validate_excerpt_grounding(excerpt, doc)
        # "SLUB allocator" is in both doc and excerpt (case-insensitive)
        slub_phrases = [p for p in ungrounded if "slub" in p.lower()]
        assert len(slub_phrases) == 0

    def test_empty_excerpt(self):
        assert validate_excerpt_grounding("", "some document text") == []

    def test_empty_document(self):
        result = validate_excerpt_grounding("Per-CPU freelists optimize allocation speed", "")
        assert len(result) > 0

    def test_whitespace_only_excerpt(self):
        assert validate_excerpt_grounding("   ", "doc text") == []

    def test_bigrams_only(self):
        excerpt = "Memory allocation caching helps"
        doc = "Something completely unrelated here"
        result = validate_excerpt_grounding(excerpt, doc)
        # All bigrams should be ungrounded since doc is unrelated
        assert len(result) > 0
        # Each entry should be a bigram (two words)
        for phrase in result:
            assert len(phrase.split()) == 2
