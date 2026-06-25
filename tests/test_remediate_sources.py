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
    remediate_stub_sources,
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
        assert "Skipped (no refs):** 1" in report
        assert "src-1" in report
        assert "mm/slub.c" in report
        assert "src-2" in report

    def test_report_empty(self):
        report = generate_remediation_report([])
        assert "Stub sources replaced:** 0" in report
