"""Tests for src/ingest/validate_sources.py.

Covers: ALG-KK-CLASSIFY-SOURCE-CONTENT, ALG-KK-EXTRACT-KERNEL-DOC-REFS,
        INV-KK-SOURCE-CONTENT-SUFFICIENT, ALG-KK-VALIDATE-SOURCE-CONTENT,
        ALG-KK-RESOLVE-DIRECTORY-SOURCE, INV-KK-VALIDATE-RATE-LIMITED
"""

import json
import sqlite3
import time

import pytest

from ingest.validate_sources import (
    ContentClassification,
    SourceValidationResult,
    build_replacement_url,
    classify_content,
    extract_kernel_doc_refs,
    generate_report,
    resolve_directory_url,
    validate_all_sources,
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


# ---------------------------------------------------------------------------
# resolve_directory_url (ALG-KK-RESOLVE-DIRECTORY-SOURCE)
# ---------------------------------------------------------------------------

_MOCK_DIR_HTML = """
<html><body>
<table class="list">
<tr><td><a href="../">parent directory</a></td></tr>
<tr><td><a href="index.rst">index.rst</a></td></tr>
<tr><td><a href="overview.rst">overview.rst</a></td></tr>
<tr><td><a href="internals.rst">internals.rst</a></td></tr>
<tr><td><a href="main.c">main.c</a></td></tr>
<tr><td><a href="helper.h">helper.h</a></td></tr>
<tr><td><a href="Makefile">Makefile</a></td></tr>
</table>
</body></html>
"""


class TestResolveDirectoryUrl:
    def test_filters_and_orders(self):
        results = resolve_directory_url(
            "https://example.com/tree/Documentation/mm",
            fetch_fn=lambda _url: _MOCK_DIR_HTML,
        )
        assert len(results) >= 4
        assert results[0].endswith("index.rst")
        assert all(".rst" in u or ".c" in u or ".h" in u for u in results)
        assert "Makefile" not in " ".join(results)

    def test_empty_fetch(self):
        results = resolve_directory_url(
            "https://example.com/tree/empty",
            fetch_fn=lambda _url: "",
        )
        assert results == []

    def test_no_index(self):
        html = '<a href="notes.rst">notes.rst</a><a href="core.c">core.c</a>'
        results = resolve_directory_url(
            "https://example.com/tree/dir",
            fetch_fn=lambda _url: html,
        )
        assert len(results) == 2
        assert results[0].endswith("notes.rst")


# ---------------------------------------------------------------------------
# validate_all_sources (ALG-KK-VALIDATE-SOURCE-CONTENT)
# ---------------------------------------------------------------------------

def _make_test_db():
    """Create an in-memory DB with Source nodes for testing."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE nodes (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            attrs TEXT NOT NULL DEFAULT '{}'
        )
    """)
    conn.execute("""
        CREATE TABLE edges (
            kind TEXT NOT NULL,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL
        )
    """)
    return conn


def _add_source(conn, source_id, url):
    conn.execute(
        "INSERT INTO nodes (id, kind, attrs) VALUES (?, 'Source', ?)",
        (source_id, json.dumps({"url": url, "source_type": "documentation"})),
    )
    conn.commit()


class TestValidateAllSources:
    def test_mixed_sources(self):
        conn = _make_test_db()
        _add_source(conn, "src-good", "https://example.com/good")
        _add_source(conn, "src-stub", "https://example.com/stub")
        _add_source(conn, "src-dir", "https://example.com/dir")

        substantive_text = " ".join(["word"] * 150)
        stub_text = "Title\n=====\n\n.. kernel-doc:: mm/slub.c\n"
        dir_text = '<table class="list"><tr><td>files</td></tr></table>'

        def mock_fetch(url):
            if "good" in url:
                return substantive_text
            elif "stub" in url:
                return stub_text
            elif "dir" in url:
                return dir_text
            return ""

        results = validate_all_sources(conn, fetch_fn=mock_fetch, rate_limit=0.0)
        by_id = {r.source_id: r for r in results}

        assert by_id["src-good"].classification == "substantive"
        assert by_id["src-stub"].classification == "stub"
        assert len(by_id["src-stub"].suggested_replacement_urls) > 0
        assert by_id["src-dir"].classification == "directory"

    def test_empty_url_unreachable(self):
        conn = _make_test_db()
        _add_source(conn, "src-empty", "")

        results = validate_all_sources(conn, fetch_fn=lambda _: "", rate_limit=0.0)
        assert results[0].classification == "unreachable"

    def test_no_sources(self):
        conn = _make_test_db()
        results = validate_all_sources(conn, fetch_fn=lambda _: "", rate_limit=0.0)
        assert results == []


# ---------------------------------------------------------------------------
# Rate limiting (INV-KK-VALIDATE-RATE-LIMITED)
# ---------------------------------------------------------------------------

class TestRateLimiting:
    def test_rate_limiting_respected(self):
        conn = _make_test_db()
        _add_source(conn, "src-1", "https://example.com/a")
        _add_source(conn, "src-2", "https://example.com/b")

        fetch_times: list[float] = []

        def timed_fetch(url):
            fetch_times.append(time.monotonic())
            return " ".join(["word"] * 150)

        validate_all_sources(conn, fetch_fn=timed_fetch, rate_limit=0.1)

        assert len(fetch_times) == 2
        gap = fetch_times[1] - fetch_times[0]
        assert gap >= 0.09  # allow small float imprecision


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------

class TestGenerateReport:
    def test_report_format(self):
        results = [
            SourceValidationResult(
                source_id="src-1", url="https://example.com/good",
                classification="substantive", word_count=200,
            ),
            SourceValidationResult(
                source_id="src-2", url="https://example.com/stub",
                classification="stub", word_count=10,
                kernel_doc_refs=["mm/slub.c"],
                suggested_replacement_urls=["https://git.kernel.org/.../mm/slub.c"],
            ),
            SourceValidationResult(
                source_id="src-3", url="https://example.com/thin",
                classification="thin", word_count=60,
            ),
        ]
        report = generate_report(results)
        assert "# Source Content Validation Report" in report
        assert "| substantive | 1 |" in report
        assert "| stub | 1 |" in report
        assert "| thin | 1 |" in report
        assert "**Total** | **3**" in report
        assert "src-2" in report
        assert "Needs Manual Review" in report
        assert "Stub Sources" in report

    def test_report_empty(self):
        report = generate_report([])
        assert "**Total** | **0**" in report


# ---------------------------------------------------------------------------
# SourceValidationResult dataclass
# ---------------------------------------------------------------------------

class TestSourceValidationResult:
    def test_defaults(self):
        r = SourceValidationResult(source_id="s1", url="u1", classification="substantive")
        assert r.word_count == 0
        assert r.kernel_doc_refs == []
        assert r.suggested_replacement_urls == []
        assert r.prose_excerpt == ""
