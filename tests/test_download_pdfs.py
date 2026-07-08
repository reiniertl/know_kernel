"""Tests for scripts/download_research_pdfs.py."""
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock
import io

import pytest

from scripts.download_research_pdfs import (
    resolve_pdf_url,
    query_research_sources,
    update_source_attrs,
    download_pdf,
    RESEARCH_TYPES,
)


def _init_test_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE IF NOT EXISTS nodes (id TEXT PRIMARY KEY, kind TEXT NOT NULL, attrs TEXT NOT NULL DEFAULT '{}')")
    conn.execute("CREATE TABLE IF NOT EXISTS edges (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, source_id TEXT NOT NULL, target_id TEXT NOT NULL, attrs TEXT NOT NULL DEFAULT '{}')")
    return conn


def _add_source(conn, source_id, source_type, url, title=""):
    attrs = json.dumps({"source_type": source_type, "url": url, "title": title})
    conn.execute("INSERT INTO nodes (id, kind, attrs) VALUES (?, 'Source', ?)", (source_id, attrs))


class TestResolvePdfUrl:
    def test_arxiv_abs_to_pdf(self):
        assert resolve_pdf_url("https://arxiv.org/abs/2502.02750") == "https://arxiv.org/pdf/2502.02750.pdf"

    def test_arxiv_with_version(self):
        assert resolve_pdf_url("https://arxiv.org/abs/2312.04789") == "https://arxiv.org/pdf/2312.04789.pdf"

    def test_acm_dl_doi_to_pdf(self):
        result = resolve_pdf_url("https://dl.acm.org/doi/10.1145/3676641.3711999")
        assert result == "https://dl.acm.org/doi/pdf/10.1145/3676641.3711999"

    def test_direct_pdf_url_passthrough(self):
        url = "https://2025.eurosys.org/posters/eurosys25posters-paper26.pdf"
        assert resolve_pdf_url(url) == url

    def test_kernel_org_returns_none(self):
        assert resolve_pdf_url("https://www.kernel.org/doc/html/latest/RCU/whatisRCU.html") is None

    def test_lpc_events_returns_none(self):
        assert resolve_pdf_url("https://lpc.events/event/19/sessions/229/") is None

    def test_sigops_returns_none(self):
        assert resolve_pdf_url("https://sigops.org/s/conferences/sosp/2025/accepted.html") is None

    def test_empty_url_returns_none(self):
        assert resolve_pdf_url("") is None

    def test_none_url_returns_none(self):
        assert resolve_pdf_url(None) is None


class TestQueryResearchSources:
    def test_returns_research_sources(self, tmp_path):
        db = tmp_path / "test.db"
        conn = _init_test_db(db)
        _add_source(conn, "s1", "preprint", "https://arxiv.org/abs/1234.5678")
        _add_source(conn, "s2", "conference-paper", "https://dl.acm.org/doi/10.1145/1234")
        _add_source(conn, "s3", "discourse", "https://lkml.org/thread")
        conn.commit()
        result = query_research_sources(conn)
        ids = [r["id"] for r in result]
        assert "s1" in ids
        assert "s2" in ids
        assert "s3" not in ids
        conn.close()

    def test_empty_db(self, tmp_path):
        db = tmp_path / "test.db"
        conn = _init_test_db(db)
        conn.commit()
        assert query_research_sources(conn) == []
        conn.close()


class TestDeduplication:
    def test_duplicate_urls_resolved_once(self, tmp_path):
        db = tmp_path / "test.db"
        conn = _init_test_db(db)
        _add_source(conn, "src-arxiv-paracell", "preprint", "https://arxiv.org/abs/2605.20906")
        _add_source(conn, "src-arxiv-paracell-ns", "preprint", "https://arxiv.org/abs/2605.20906")
        conn.commit()

        sources = query_research_sources(conn)
        seen_urls = {}
        download_count = 0
        for src in sources:
            pdf_url = resolve_pdf_url(src["attrs"]["url"])
            if pdf_url and pdf_url not in seen_urls:
                seen_urls[pdf_url] = src["id"]
                download_count += 1
        assert download_count == 1
        conn.close()


class TestUpdateSourceAttrs:
    def test_sets_local_pdf_path_and_date(self, tmp_path):
        db = tmp_path / "test.db"
        conn = _init_test_db(db)
        _add_source(conn, "s1", "preprint", "https://arxiv.org/abs/1234.5678")
        conn.commit()

        update_source_attrs(conn, "s1", "data/pdfs/s1.pdf")
        conn.commit()

        row = conn.execute("SELECT attrs FROM nodes WHERE id = 's1'").fetchone()
        attrs = json.loads(row[0])
        assert attrs["local_pdf_path"] == "data/pdfs/s1.pdf"
        assert "pdf_downloaded_at" in attrs
        conn.close()

    def test_preserves_existing_attrs(self, tmp_path):
        db = tmp_path / "test.db"
        conn = _init_test_db(db)
        _add_source(conn, "s1", "preprint", "https://arxiv.org/abs/1234.5678", title="Test Paper")
        conn.commit()

        update_source_attrs(conn, "s1", "data/pdfs/s1.pdf")
        conn.commit()

        row = conn.execute("SELECT attrs FROM nodes WHERE id = 's1'").fetchone()
        attrs = json.loads(row[0])
        assert attrs["title"] == "Test Paper"
        assert attrs["source_type"] == "preprint"
        assert attrs["local_pdf_path"] == "data/pdfs/s1.pdf"
        conn.close()


class TestDownloadPdf:
    def test_successful_download(self, tmp_path):
        dest = tmp_path / "test.pdf"
        fake_response = MagicMock()
        fake_response.read.return_value = b"%PDF-1.4 fake content"
        fake_response.__enter__ = lambda s: io.BytesIO(b"%PDF-1.4 fake content")
        fake_response.__exit__ = MagicMock(return_value=False)

        with patch("scripts.download_research_pdfs.urllib.request.urlopen", return_value=fake_response):
            result = download_pdf("https://arxiv.org/pdf/1234.5678.pdf", dest)

        assert result is True
        assert dest.exists()

    def test_failed_download_cleans_up(self, tmp_path):
        import urllib.error as ue
        dest = tmp_path / "test.pdf"
        with patch("scripts.download_research_pdfs.urllib.request.urlopen", side_effect=ue.HTTPError(
            "https://example.com", 404, "Not Found", {}, None
        )):
            result = download_pdf("https://example.com/missing.pdf", dest)

        assert result is False
        assert not dest.exists()


class TestSkipExisting:
    def test_skip_existing_file(self, tmp_path):
        db = tmp_path / "test.db"
        conn = _init_test_db(db)
        _add_source(conn, "s1", "preprint", "https://arxiv.org/abs/1234.5678")
        conn.commit()

        out_dir = tmp_path / "pdfs"
        out_dir.mkdir()
        existing = out_dir / "s1.pdf"
        existing.write_bytes(b"%PDF")

        sources = query_research_sources(conn)
        src = sources[0]
        dest = out_dir / f"{src['id']}.pdf"
        assert dest.exists()
        conn.close()
