"""Tests for CVE vulnerability tracker -- ALG-KK-VULN-TRACK invariants."""

from __future__ import annotations

import json

import pytest

from graph.engine import add_edge, add_node
from graph.schema import init_db
from ingest.vuln_tracker import (
    CWE_CONCEPT_MAP,
    ParsedCVE,
    cvss_to_severity,
    ingest_cve,
    ingest_cves,
    parse_nvd_response,
)


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "test.db")


def _nvd_vuln(
    cve_id: str = "CVE-2026-12345",
    description: str = "Use-after-free in kernel slab allocator",
    cvss_score: float | None = 7.5,
    cwe_ids: list[str] | None = None,
    version_start: str = "5.15",
    version_end: str = "6.10",
    published: str = "2026-06-15T10:00:00.000",
) -> dict:
    """Build a single NVD API vulnerability entry."""
    metrics = {}
    if cvss_score is not None:
        metrics["cvssMetricV31"] = [{
            "cvssData": {"baseScore": cvss_score},
        }]

    weaknesses = []
    if cwe_ids:
        weaknesses = [{"description": [{"value": cwe} for cwe in cwe_ids]}]

    cpe_match = []
    if version_start and version_end:
        cpe_match = [{"criteria": "cpe:2.3:o:linux:linux_kernel:*", "versionStartIncluding": version_start, "versionEndExcluding": version_end}]

    return {
        "cve": {
            "id": cve_id,
            "descriptions": [{"lang": "en", "value": description}],
            "metrics": metrics,
            "weaknesses": weaknesses,
            "configurations": [{"nodes": [{"cpeMatch": cpe_match}]}] if cpe_match else [],
            "published": published,
        }
    }


def _nvd_response(*vulns) -> dict:
    return {"vulnerabilities": list(vulns)}


# --- INV-KK-VULN-CVSS-SEVERITY tests ---


class TestCvssSeverity:
    def test_critical(self):
        assert cvss_to_severity(9.0) == "critical"
        assert cvss_to_severity(10.0) == "critical"
        assert cvss_to_severity(9.8) == "critical"

    def test_high(self):
        assert cvss_to_severity(7.0) == "high"
        assert cvss_to_severity(8.9) == "high"

    def test_medium(self):
        assert cvss_to_severity(4.0) == "medium"
        assert cvss_to_severity(6.9) == "medium"

    def test_low(self):
        assert cvss_to_severity(0.0) == "low"
        assert cvss_to_severity(3.9) == "low"

    def test_none_defaults_to_medium(self):
        """INV-KK-VULN-CVSS-SEVERITY: missing CVSS defaults to medium."""
        assert cvss_to_severity(None) == "medium"


# --- INV-KK-VULN-CWE-MAP tests ---


class TestCweConceptMap:
    def test_cwe_416_maps_to_rcu_slab(self):
        assert "RCU" in CWE_CONCEPT_MAP["CWE-416"]
        assert "Slab Allocator" in CWE_CONCEPT_MAP["CWE-416"]

    def test_cwe_362_maps_to_locking(self):
        assert "Spinlocks" in CWE_CONCEPT_MAP["CWE-362"]
        assert "Mutexes" in CWE_CONCEPT_MAP["CWE-362"]

    def test_cwe_787_maps_to_page_tables(self):
        assert "Page Tables" in CWE_CONCEPT_MAP["CWE-787"]

    def test_cwe_476_maps_to_vfs(self):
        assert "VFS" in CWE_CONCEPT_MAP["CWE-476"]

    def test_all_entries_are_nonempty(self):
        for cwe, concepts in CWE_CONCEPT_MAP.items():
            assert cwe.startswith("CWE-"), f"{cwe} is not a CWE ID"
            assert len(concepts) > 0, f"{cwe} has no mapped concepts"

    def test_unmapped_cwe_returns_empty(self):
        assert CWE_CONCEPT_MAP.get("CWE-999999", []) == []


# --- NVD response parser tests ---


class TestParseNvdResponse:
    def test_single_cve(self):
        data = _nvd_response(_nvd_vuln())
        cves = parse_nvd_response(data)
        assert len(cves) == 1
        assert cves[0].cve_id == "CVE-2026-12345"

    def test_cvss_score_parsed(self):
        data = _nvd_response(_nvd_vuln(cvss_score=9.8))
        cves = parse_nvd_response(data)
        assert cves[0].cvss_score == 9.8
        assert cves[0].severity == "critical"

    def test_missing_cvss(self):
        data = _nvd_response(_nvd_vuln(cvss_score=None))
        cves = parse_nvd_response(data)
        assert cves[0].cvss_score is None
        assert cves[0].severity == "medium"

    def test_cwe_ids_parsed(self):
        data = _nvd_response(_nvd_vuln(cwe_ids=["CWE-416", "CWE-362"]))
        cves = parse_nvd_response(data)
        assert "CWE-416" in cves[0].cwe_ids
        assert "CWE-362" in cves[0].cwe_ids

    def test_no_cwe(self):
        data = _nvd_response(_nvd_vuln(cwe_ids=None))
        cves = parse_nvd_response(data)
        assert cves[0].cwe_ids == []

    def test_affected_versions_range(self):
        data = _nvd_response(_nvd_vuln(version_start="5.15", version_end="6.10"))
        cves = parse_nvd_response(data)
        assert cves[0].affected_versions == "5.15 - 6.10"

    def test_no_versions(self):
        data = _nvd_response(_nvd_vuln(version_start="", version_end=""))
        cves = parse_nvd_response(data)
        assert cves[0].affected_versions == ""

    def test_published_date_truncated(self):
        """INV-KK-VULN-SOURCE-DATE: published date truncated to YYYY-MM-DD."""
        data = _nvd_response(_nvd_vuln(published="2026-06-15T10:30:00.000"))
        cves = parse_nvd_response(data)
        assert cves[0].published_date == "2026-06-15"

    def test_description_english(self):
        data = _nvd_response(_nvd_vuln(description="English description"))
        cves = parse_nvd_response(data)
        assert cves[0].description == "English description"

    def test_empty_response(self):
        assert parse_nvd_response({"vulnerabilities": []}) == []
        assert parse_nvd_response({}) == []

    def test_multiple_cves(self):
        data = _nvd_response(
            _nvd_vuln(cve_id="CVE-2026-0001"),
            _nvd_vuln(cve_id="CVE-2026-0002"),
            _nvd_vuln(cve_id="CVE-2026-0003"),
        )
        cves = parse_nvd_response(data)
        assert len(cves) == 3
        assert {c.cve_id for c in cves} == {"CVE-2026-0001", "CVE-2026-0002", "CVE-2026-0003"}


# --- Vulnerability node creation tests ---


class TestIngestCve:
    def test_creates_vulnerability_node(self, conn):
        cve = ParsedCVE(
            cve_id="CVE-2026-12345", description="UAF in slab",
            cvss_score=7.5, severity="high", cwe_ids=["CWE-416"],
            affected_versions="5.15 - 6.10", published_date="2026-06-15",
        )
        vuln_id = ingest_cve(conn, cve)
        assert vuln_id is not None
        row = conn.execute("SELECT kind, attrs FROM nodes WHERE id = ?", (vuln_id,)).fetchone()
        assert row[0] == "Vulnerability"
        attrs = json.loads(row[1])
        assert attrs["cve_id"] == "CVE-2026-12345"
        assert attrs["severity"] == "high"
        assert attrs["cvss_score"] == "7.5"
        assert attrs["affected_versions"] == "5.15 - 6.10"
        assert attrs["source_date"] == "2026-06-15"
        assert attrs["artifact_class"] == "B"
        assert attrs["status"] == "unfixed"

    def test_dedup_by_cve_id(self, conn):
        """INV-KK-VULN-CVE-DEDUP: second insertion with same cve_id returns None."""
        cve = ParsedCVE(
            cve_id="CVE-2026-99999", description="dup test",
            cvss_score=5.0, severity="medium", cwe_ids=[],
            affected_versions="", published_date="2026-06-01",
        )
        first = ingest_cve(conn, cve)
        assert first is not None
        second = ingest_cve(conn, cve)
        assert second is None

    def test_exploits_edge_created(self, conn):
        """INV-KK-VULN-CWE-MAP: exploits edge from CWE mapping."""
        concept_id = "concept-rcu"
        add_node(conn, concept_id, "Concept", {
            "name": "RCU", "description": "Read-Copy-Update",
            "key_properties": "[]", "tradeoffs": "[]",
            "design_rationale": "Lock-free reads", "artifact_class": "B",
        })
        cve = ParsedCVE(
            cve_id="CVE-2026-55555", description="UAF in RCU",
            cvss_score=8.0, severity="high", cwe_ids=["CWE-416"],
            affected_versions="6.0 - 6.5", published_date="2026-06-10",
        )
        vuln_id = ingest_cve(conn, cve)
        edge = conn.execute(
            "SELECT 1 FROM edges WHERE kind = 'exploits' AND source_id = ? AND target_id = ?",
            (vuln_id, concept_id),
        ).fetchone()
        assert edge is not None

    def test_no_exploits_edge_for_unmapped_cwe(self, conn):
        """INV-KK-VULN-CWE-MAP: unmapped CWE produces no exploits edge."""
        cve = ParsedCVE(
            cve_id="CVE-2026-77777", description="some vuln",
            cvss_score=5.0, severity="medium", cwe_ids=["CWE-999999"],
            affected_versions="", published_date="2026-06-01",
        )
        vuln_id = ingest_cve(conn, cve)
        edges = conn.execute(
            "SELECT 1 FROM edges WHERE kind = 'exploits' AND source_id = ?",
            (vuln_id,),
        ).fetchall()
        assert len(edges) == 0

    def test_no_exploits_edge_when_concept_missing(self, conn):
        """INV-KK-VULN-CWE-MAP: CWE mapped but no matching Concept in DB."""
        cve = ParsedCVE(
            cve_id="CVE-2026-66666", description="UAF",
            cvss_score=7.0, severity="high", cwe_ids=["CWE-416"],
            affected_versions="", published_date="2026-06-01",
        )
        vuln_id = ingest_cve(conn, cve)
        edges = conn.execute(
            "SELECT 1 FROM edges WHERE kind = 'exploits' AND source_id = ?",
            (vuln_id,),
        ).fetchall()
        assert len(edges) == 0

    def test_missing_cvss_uses_empty_string(self, conn):
        """INV-KK-VULN-CVSS-SEVERITY: missing CVSS stored as empty string."""
        cve = ParsedCVE(
            cve_id="CVE-2026-44444", description="no score",
            cvss_score=None, severity="medium", cwe_ids=[],
            affected_versions="", published_date="2026-06-01",
        )
        vuln_id = ingest_cve(conn, cve)
        attrs = json.loads(conn.execute("SELECT attrs FROM nodes WHERE id = ?", (vuln_id,)).fetchone()[0])
        assert attrs["cvss_score"] == ""
        assert attrs["severity"] == "medium"

    def test_source_date_is_published_date(self, conn):
        """INV-KK-VULN-SOURCE-DATE: source_date from CVE published date."""
        cve = ParsedCVE(
            cve_id="CVE-2026-33333", description="test",
            cvss_score=3.0, severity="low", cwe_ids=[],
            affected_versions="", published_date="2024-01-20",
        )
        vuln_id = ingest_cve(conn, cve)
        attrs = json.loads(conn.execute("SELECT attrs FROM nodes WHERE id = ?", (vuln_id,)).fetchone()[0])
        assert attrs["source_date"] == "2024-01-20"

    def test_title_truncated(self, conn):
        long_desc = "A" * 200
        cve = ParsedCVE(
            cve_id="CVE-2026-22222", description=long_desc,
            cvss_score=5.0, severity="medium", cwe_ids=[],
            affected_versions="", published_date="2026-06-01",
        )
        vuln_id = ingest_cve(conn, cve)
        attrs = json.loads(conn.execute("SELECT attrs FROM nodes WHERE id = ?", (vuln_id,)).fetchone()[0])
        assert len(attrs["title"]) <= 120

    def test_multiple_cwe_multiple_concepts(self, conn):
        """INV-KK-VULN-CWE-MAP: multiple CWEs create multiple exploits edges."""
        for name in ["RCU", "Spinlocks"]:
            add_node(conn, f"concept-{name.lower()}", "Concept", {
                "name": name, "description": f"{name} mechanism",
                "key_properties": "[]", "tradeoffs": "[]",
                "design_rationale": "reason", "artifact_class": "B",
            })
        cve = ParsedCVE(
            cve_id="CVE-2026-11111", description="race + UAF",
            cvss_score=9.0, severity="critical", cwe_ids=["CWE-416", "CWE-362"],
            affected_versions="6.0 - 6.5", published_date="2026-06-01",
        )
        vuln_id = ingest_cve(conn, cve)
        edges = conn.execute(
            "SELECT target_id FROM edges WHERE kind = 'exploits' AND source_id = ?",
            (vuln_id,),
        ).fetchall()
        target_ids = {r[0] for r in edges}
        assert "concept-rcu" in target_ids
        assert "concept-spinlocks" in target_ids


class TestIngestCves:
    def test_batch_ingestion(self, conn):
        data = _nvd_response(
            _nvd_vuln(cve_id="CVE-2026-0001", cvss_score=9.0, cwe_ids=["CWE-416"]),
            _nvd_vuln(cve_id="CVE-2026-0002", cvss_score=5.0),
        )
        vuln_ids = ingest_cves(conn, data)
        assert len(vuln_ids) == 2

    def test_dedup_in_batch(self, conn):
        """INV-KK-VULN-CVE-DEDUP: same CVE ID in two calls only creates one node."""
        data1 = _nvd_response(_nvd_vuln(cve_id="CVE-2026-9999"))
        data2 = _nvd_response(_nvd_vuln(cve_id="CVE-2026-9999"))
        ids1 = ingest_cves(conn, data1)
        ids2 = ingest_cves(conn, data2)
        assert len(ids1) == 1
        assert len(ids2) == 0

    def test_empty_response(self, conn):
        assert ingest_cves(conn, {"vulnerabilities": []}) == []
