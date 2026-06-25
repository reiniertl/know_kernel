"""Tests for src/ingest/validate_sources.py.

Covers: ALG-KK-CLASSIFY-SOURCE-CONTENT, ALG-KK-EXTRACT-KERNEL-DOC-REFS,
        INV-KK-SOURCE-CONTENT-SUFFICIENT
"""

import pytest

from ingest.validate_sources import (
    ContentClassification,
    build_replacement_url,
    classify_content,
    extract_kernel_doc_refs,
)


# ---------------------------------------------------------------------------
# classify_content — substantive
# ---------------------------------------------------------------------------

class TestClassifySubstantive:
    def test_html_with_prose(self):
        text = " ".join(["word"] * 150)
        result = classify_content(text)
        assert result.classification == "substantive"
        assert result.word_count >= 100

    def test_rst_with_prose_and_directives(self):
        prose = " ".join(["The kernel subsystem provides"] + ["functionality"] * 100)
        text = f"Title\n=====\n\n{prose}\n\n.. kernel-doc:: mm/slub.c\n"
        result = classify_content(text)
        assert result.classification == "substantive"
        assert result.word_count >= 100
        assert "mm/slub.c" in result.kernel_doc_refs

    def test_prose_excerpt_populated(self):
        text = "This is a real document. " * 50
        result = classify_content(text)
        assert result.classification == "substantive"
        assert len(result.prose_excerpt) > 0


# ---------------------------------------------------------------------------
# classify_content — stub
# ---------------------------------------------------------------------------

class TestClassifyStub:
    def test_kernel_doc_only(self):
        text = (
            "SLUB Allocator\n"
            "==============\n\n"
            ".. kernel-doc:: mm/slub.c\n"
            "   :doc: SLUB\n\n"
            ".. kernel-doc:: include/linux/slab.h\n"
        )
        result = classify_content(text)
        assert result.classification == "stub"
        assert result.word_count < 50
        assert "mm/slub.c" in result.kernel_doc_refs
        assert "include/linux/slab.h" in result.kernel_doc_refs

    def test_stub_with_minimal_prose(self):
        text = (
            "Memory\n======\n\n"
            "See the source.\n\n"
            ".. kernel-doc:: mm/page_alloc.c\n"
        )
        result = classify_content(text)
        assert result.classification == "stub"
        assert result.word_count < 50


# ---------------------------------------------------------------------------
# classify_content — directory
# ---------------------------------------------------------------------------

class TestClassifyDirectory:
    def test_tree_listing_table(self):
        text = '<html><table class="list"><tr><td>Documentation/mm</td></tr></table></html>'
        result = classify_content(text)
        assert result.classification == "directory"

    def test_ls_mode_marker(self):
        text = '<td class="ls-mode">drwxr-xr-x</td>'
        result = classify_content(text)
        assert result.classification == "directory"

    def test_drwxr_marker(self):
        text = "drwxr-xr-x  2 root root 4096 Jan  1 00:00 mm"
        result = classify_content(text)
        assert result.classification == "directory"


# ---------------------------------------------------------------------------
# classify_content — thin
# ---------------------------------------------------------------------------

class TestClassifyThin:
    def test_borderline_content(self):
        words = " ".join(["concept"] * 70)
        text = f"Title\n=====\n\n{words}\n"
        result = classify_content(text)
        assert result.classification == "thin"
        assert 50 <= result.word_count < 100

    def test_thin_at_boundary(self):
        words = " ".join(["word"] * 50)
        text = words
        result = classify_content(text)
        assert result.classification == "thin"


# ---------------------------------------------------------------------------
# classify_content — unreachable
# ---------------------------------------------------------------------------

class TestClassifyUnreachable:
    def test_empty_string(self):
        result = classify_content("")
        assert result.classification == "unreachable"

    def test_none(self):
        result = classify_content(None)
        assert result.classification == "unreachable"

    def test_whitespace_only(self):
        result = classify_content("   \n\t\n  ")
        assert result.classification == "unreachable"

    def test_very_sparse_no_directives(self):
        result = classify_content("hello world")
        assert result.classification == "unreachable"
        assert result.word_count < 50


# ---------------------------------------------------------------------------
# extract_kernel_doc_refs
# ---------------------------------------------------------------------------

class TestExtractKernelDocRefs:
    def test_single_directive(self):
        text = ".. kernel-doc:: mm/slub.c\n   :doc: SLUB\n"
        refs = extract_kernel_doc_refs(text)
        assert refs == ["mm/slub.c"]

    def test_multiple_directives(self):
        text = (
            ".. kernel-doc:: mm/slub.c\n"
            "   :doc: SLUB\n\n"
            ".. kernel-doc:: include/linux/slab.h\n"
            "   :functions: kmalloc\n\n"
            ".. kernel-doc:: mm/slab_common.c\n"
        )
        refs = extract_kernel_doc_refs(text)
        assert refs == ["mm/slub.c", "include/linux/slab.h", "mm/slab_common.c"]

    def test_no_directives(self):
        text = "This is a regular document with no kernel-doc references.\n"
        refs = extract_kernel_doc_refs(text)
        assert refs == []

    def test_indented_directive(self):
        text = "  .. kernel-doc:: drivers/net/ethernet/intel/e1000e/netdev.c\n"
        refs = extract_kernel_doc_refs(text)
        assert refs == ["drivers/net/ethernet/intel/e1000e/netdev.c"]


# ---------------------------------------------------------------------------
# build_replacement_url
# ---------------------------------------------------------------------------

class TestBuildReplacementUrl:
    def test_c_file(self):
        url = build_replacement_url("mm/slub.c")
        assert url == (
            "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/mm/slub.c"
        )

    def test_header_file(self):
        url = build_replacement_url("include/linux/slab.h")
        assert url == (
            "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/include/linux/slab.h"
        )

    def test_strips_leading_slash(self):
        url = build_replacement_url("/mm/slub.c")
        assert "tree/mm/slub.c" in url
        assert "tree//mm" not in url


# ---------------------------------------------------------------------------
# ContentClassification dataclass
# ---------------------------------------------------------------------------

class TestContentClassificationDataclass:
    def test_defaults(self):
        cc = ContentClassification(classification="unreachable")
        assert cc.word_count == 0
        assert cc.kernel_doc_refs == []
        assert cc.prose_excerpt == ""

    def test_all_fields(self):
        cc = ContentClassification(
            classification="stub",
            word_count=12,
            kernel_doc_refs=["mm/slub.c"],
            prose_excerpt="SLUB Allocator",
        )
        assert cc.classification == "stub"
        assert cc.word_count == 12
        assert cc.kernel_doc_refs == ["mm/slub.c"]
        assert cc.prose_excerpt == "SLUB Allocator"
