"""Tests for scripts/remediate_sources.py.

Covers: ALG-KK-REMEDIATE-STUB-SOURCE, INV-KK-REMEDIATION-BACKUP,
        INV-KK-STUB-SOURCE-REPLACED
"""

import json
import os
import sqlite3
import tempfile

import pytest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from remediate_sources import (
    RemediationResult,
    backup_database,
    generate_remediation_report,
    remediate_directory_sources,
    remediate_stub_sources,
    update_code_example_urls,
)
from ingest.validate_sources import SourceValidationResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_test_db(path=":memory:"):
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS nodes (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            attrs TEXT NOT NULL DEFAULT '{}'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS edges (
            kind TEXT NOT NULL,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def _add_source(conn, source_id, url):
    conn.execute(
        "INSERT INTO nodes (id, kind, attrs) VALUES (?, 'Source', ?)",
        (source_id, json.dumps({"url": url, "source_type": "documentation"})),
    )
    conn.commit()


def _get_url(conn, source_id):
    row = conn.execute("SELECT attrs FROM nodes WHERE id = ?", (source_id,)).fetchone()
    return json.loads(row[0])["url"] if row else None


# ---------------------------------------------------------------------------
# backup_database (INV-KK-REMEDIATION-BACKUP)
# ---------------------------------------------------------------------------

class TestBackupDatabase:
    def test_backup_created(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = _make_test_db(db_path)
        _add_source(conn, "src-1", "https://example.com")
        conn.close()

        backup_path = backup_database(db_path)
        assert os.path.exists(backup_path)
        assert backup_path == f"{db_path}.pre-remediation"

        backup_conn = sqlite3.connect(backup_path)
        row = backup_conn.execute("SELECT id FROM nodes").fetchone()
        assert row[0] == "src-1"
        backup_conn.close()

    def test_backup_before_writes(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = _make_test_db(db_path)
        _add_source(conn, "src-1", "https://old.url")
        conn.close()

        backup_database(db_path)

        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE nodes SET attrs = ? WHERE id = 'src-1'",
            (json.dumps({"url": "https://new.url"}),),
        )
        conn.commit()
        conn.close()

        backup_conn = sqlite3.connect(f"{db_path}.pre-remediation")
        old_url = json.loads(
            backup_conn.execute("SELECT attrs FROM nodes WHERE id = 'src-1'").fetchone()[0]
        )["url"]
        assert old_url == "https://old.url"
        backup_conn.close()


# ---------------------------------------------------------------------------
# remediate_stub_sources (ALG-KK-REMEDIATE-STUB-SOURCE)
# ---------------------------------------------------------------------------

class TestRemediateStubSources:
    def test_stub_source_url_updated(self):
        conn = _make_test_db()
        _add_source(conn, "src-stub", "https://old.example.com/slab.rst")

        vr = [SourceValidationResult(
            source_id="src-stub",
            url="https://old.example.com/slab.rst",
            classification="stub",
            kernel_doc_refs=["mm/slub.c"],
        )]

        results = remediate_stub_sources(conn, vr)
        assert len(results) == 1
        assert results[0].action == "stub_replaced"
        assert "mm/slub.c" in results[0].new_url

        new_url = _get_url(conn, "src-stub")
        assert "mm/slub.c" in new_url
        assert new_url.startswith("https://git.kernel.org/")

    def test_stub_prefers_c_over_h(self):
        conn = _make_test_db()
        _add_source(conn, "src-multi", "https://old.example.com/slab.rst")

        vr = [SourceValidationResult(
            source_id="src-multi",
            url="https://old.example.com/slab.rst",
            classification="stub",
            kernel_doc_refs=["include/linux/slab.h", "mm/slub.c", "mm/slab_common.c"],
        )]

        results = remediate_stub_sources(conn, vr)
        assert results[0].kernel_doc_ref == "mm/slub.c"
        assert "mm/slub.c" in results[0].new_url

    def test_substantive_source_unchanged(self):
        conn = _make_test_db()
        _add_source(conn, "src-good", "https://example.com/good-doc")

        vr = [SourceValidationResult(
            source_id="src-good",
            url="https://example.com/good-doc",
            classification="substantive",
            word_count=200,
        )]

        results = remediate_stub_sources(conn, vr)
        assert len(results) == 0

        url = _get_url(conn, "src-good")
        assert url == "https://example.com/good-doc"

    def test_stub_no_refs_skipped(self):
        conn = _make_test_db()
        _add_source(conn, "src-norefs", "https://example.com/norefs.rst")

        vr = [SourceValidationResult(
            source_id="src-norefs",
            url="https://example.com/norefs.rst",
            classification="stub",
            kernel_doc_refs=[],
        )]

        results = remediate_stub_sources(conn, vr)
        assert len(results) == 1
        assert results[0].action == "skipped"

        url = _get_url(conn, "src-norefs")
        assert url == "https://example.com/norefs.rst"

    def test_multiple_stubs_remediated(self):
        conn = _make_test_db()
        _add_source(conn, "src-a", "https://example.com/a.rst")
        _add_source(conn, "src-b", "https://example.com/b.rst")

        vr = [
            SourceValidationResult(
                source_id="src-a", url="https://example.com/a.rst",
                classification="stub", kernel_doc_refs=["mm/a.c"],
            ),
            SourceValidationResult(
                source_id="src-b", url="https://example.com/b.rst",
                classification="stub", kernel_doc_refs=["net/b.c"],
            ),
        ]

        results = remediate_stub_sources(conn, vr)
        replaced = [r for r in results if r.action == "stub_replaced"]
        assert len(replaced) == 2

        assert "mm/a.c" in _get_url(conn, "src-a")
        assert "net/b.c" in _get_url(conn, "src-b")


# ---------------------------------------------------------------------------
# generate_remediation_report
# ---------------------------------------------------------------------------

class TestRemediationReport:
    def test_report_lists_changes(self):
        results = [
            RemediationResult(
                source_id="src-1",
                old_url="https://old.com/slab.rst",
                new_url="https://git.kernel.org/.../mm/slub.c",
                action="stub_replaced",
                kernel_doc_ref="mm/slub.c",
            ),
            RemediationResult(
                source_id="src-2",
                old_url="https://old.com/norefs.rst",
                new_url="https://old.com/norefs.rst",
                action="skipped",
            ),
        ]
        report = generate_remediation_report(results)
        assert "# Source Remediation Report" in report
        assert "Stub sources replaced:** 1" in report
        assert "Skipped:** 1" in report
        assert "src-1" in report
        assert "mm/slub.c" in report
        assert "src-2" in report

    def test_report_empty(self):
        report = generate_remediation_report([])
        assert "Stub sources replaced:** 0" in report

    def test_report_with_directory_and_code_examples(self):
        results = [
            RemediationResult(
                source_id="src-dir", old_url="https://example.com/dir",
                new_url="https://example.com/dir/index.rst",
                action="directory_replaced",
            ),
            RemediationResult(
                source_id="src-flag", old_url="https://example.com/ambig",
                new_url="https://example.com/ambig",
                action="flagged_ambiguous",
            ),
        ]
        report = generate_remediation_report(results, code_example_count=3)
        assert "Directory sources replaced:** 1" in report
        assert "Directory sources flagged (ambiguous):** 1" in report
        assert "Code examples updated:** 3" in report
        assert "src-dir" in report
        assert "Flagged for Manual Review" in report


# ---------------------------------------------------------------------------
# remediate_directory_sources (ALG-KK-REMEDIATE-DIRECTORY-SOURCE)
# ---------------------------------------------------------------------------

class TestRemediateDirectorySources:
    def test_directory_resolved_to_index_rst(self):
        conn = _make_test_db()
        _add_source(conn, "src-dir", "https://example.com/tree/dir")

        vr = [SourceValidationResult(
            source_id="src-dir",
            url="https://example.com/tree/dir",
            classification="directory",
            suggested_replacement_urls=[
                "https://example.com/tree/dir/index.rst",
                "https://example.com/tree/dir/notes.rst",
                "https://example.com/tree/dir/main.c",
            ],
        )]

        results = remediate_directory_sources(conn, vr)
        assert len(results) == 1
        assert results[0].action == "directory_replaced"
        assert results[0].new_url.endswith("index.rst")
        assert _get_url(conn, "src-dir").endswith("index.rst")

    def test_directory_single_candidate(self):
        conn = _make_test_db()
        _add_source(conn, "src-dir", "https://example.com/tree/dir")

        vr = [SourceValidationResult(
            source_id="src-dir",
            url="https://example.com/tree/dir",
            classification="directory",
            suggested_replacement_urls=["https://example.com/tree/dir/only.rst"],
        )]

        results = remediate_directory_sources(conn, vr)
        assert results[0].action == "directory_replaced"
        assert results[0].new_url.endswith("only.rst")

    def test_directory_flagged_ambiguous(self):
        conn = _make_test_db()
        _add_source(conn, "src-dir", "https://example.com/tree/dir")

        vr = [SourceValidationResult(
            source_id="src-dir",
            url="https://example.com/tree/dir",
            classification="directory",
            suggested_replacement_urls=[
                "https://example.com/tree/dir/a.rst",
                "https://example.com/tree/dir/b.rst",
            ],
        )]

        results = remediate_directory_sources(conn, vr)
        assert results[0].action == "flagged_ambiguous"
        assert _get_url(conn, "src-dir") == "https://example.com/tree/dir"

    def test_directory_no_candidates_skipped(self):
        conn = _make_test_db()
        _add_source(conn, "src-dir", "https://example.com/tree/empty")

        vr = [SourceValidationResult(
            source_id="src-dir",
            url="https://example.com/tree/empty",
            classification="directory",
            suggested_replacement_urls=[],
        )]

        results = remediate_directory_sources(conn, vr)
        assert results[0].action == "skipped"

    def test_substantive_not_touched(self):
        conn = _make_test_db()
        _add_source(conn, "src-good", "https://example.com/good")

        vr = [SourceValidationResult(
            source_id="src-good",
            url="https://example.com/good",
            classification="substantive",
        )]

        results = remediate_directory_sources(conn, vr)
        assert len(results) == 0


# ---------------------------------------------------------------------------
# update_code_example_urls (ALG-KK-UPDATE-CODE-EXAMPLE-URLS)
# ---------------------------------------------------------------------------

def _add_concept(conn, concept_id, code_examples):
    conn.execute(
        "INSERT INTO nodes (id, kind, attrs) VALUES (?, 'Concept', ?)",
        (concept_id, json.dumps({
            "name": "Test",
            "description": "Test concept",
            "code_examples": code_examples,
        })),
    )
    conn.commit()


def _get_code_examples(conn, concept_id):
    row = conn.execute("SELECT attrs FROM nodes WHERE id = ?", (concept_id,)).fetchone()
    return json.loads(row[0])["code_examples"] if row else []


class TestUpdateCodeExampleUrls:
    def test_url_updated_after_source_change(self):
        conn = _make_test_db()
        _add_concept(conn, "c1", [
            {"label": "Example", "code": "x", "source_url": "https://old.com/slab.rst"},
        ])

        results = [RemediationResult(
            source_id="src-1", old_url="https://old.com/slab.rst",
            new_url="https://git.kernel.org/.../mm/slub.c",
            action="stub_replaced",
        )]

        count = update_code_example_urls(conn, results)
        assert count == 1

        examples = _get_code_examples(conn, "c1")
        assert examples[0]["source_url"] == "https://git.kernel.org/.../mm/slub.c"

    def test_url_unchanged_no_match(self):
        conn = _make_test_db()
        _add_concept(conn, "c1", [
            {"label": "Example", "code": "x", "source_url": "https://other.com/doc"},
        ])

        results = [RemediationResult(
            source_id="src-1", old_url="https://old.com/slab.rst",
            new_url="https://git.kernel.org/.../mm/slub.c",
            action="stub_replaced",
        )]

        count = update_code_example_urls(conn, results)
        assert count == 0

        examples = _get_code_examples(conn, "c1")
        assert examples[0]["source_url"] == "https://other.com/doc"

    def test_example_without_source_url_unchanged(self):
        conn = _make_test_db()
        _add_concept(conn, "c1", [
            {"label": "Example", "code": "x"},
        ])

        results = [RemediationResult(
            source_id="src-1", old_url="https://old.com/slab.rst",
            new_url="https://new.com/slub.c",
            action="stub_replaced",
        )]

        count = update_code_example_urls(conn, results)
        assert count == 0

        examples = _get_code_examples(conn, "c1")
        assert "source_url" not in examples[0]

    def test_multiple_examples_partial_update(self):
        conn = _make_test_db()
        _add_concept(conn, "c1", [
            {"label": "Ex1", "code": "a", "source_url": "https://old.com/slab.rst"},
            {"label": "Ex2", "code": "b", "source_url": "https://other.com/doc"},
            {"label": "Ex3", "code": "c"},
        ])

        results = [RemediationResult(
            source_id="src-1", old_url="https://old.com/slab.rst",
            new_url="https://new.com/slub.c",
            action="stub_replaced",
        )]

        count = update_code_example_urls(conn, results)
        assert count == 1

        examples = _get_code_examples(conn, "c1")
        assert examples[0]["source_url"] == "https://new.com/slub.c"
        assert examples[1]["source_url"] == "https://other.com/doc"
        assert "source_url" not in examples[2]

    def test_no_remediation_results(self):
        conn = _make_test_db()
        _add_concept(conn, "c1", [
            {"label": "Ex", "code": "x", "source_url": "https://example.com"},
        ])

        count = update_code_example_urls(conn, [])
        assert count == 0
