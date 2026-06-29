"""Tests for scoring engine (ALG-KK-SCORE-HEAT, ALG-KK-SCORE-PAIN)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from graph.engine import add_edge, add_node
from graph.schema import init_db
from graph.scoring import (
    cvss_weight,
    get_linked_failure_modes,
    get_linked_problems,
    get_linked_vulns,
    heat_score,
    pain_score,
)


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    db = tmp_path / "test.db"
    c = init_db(db)
    yield c
    c.close()


def _add_concept(conn: sqlite3.Connection, name: str, cid: str | None = None) -> str:
    cid = cid or f"concept-{name.lower().replace(' ', '-')}"
    add_node(conn, cid, "Concept", {
        "name": name,
        "description": f"Test concept {name}",
        "artifact_class": "abstracted-mechanism",
        "key_properties": ["test"],
        "tradeoffs": [],
        "design_rationale": "test",
    })
    return cid


def _add_discussion(conn: sqlite3.Connection, concept_id: str, source_date: str) -> str:
    did = f"disc-{source_date}-{concept_id[:8]}"
    add_node(conn, did, "Discussion", {
        "title": f"Discussion {did}",
        "forum": "lkml",
        "participant_count": 5,
        "source_date": source_date,
        "artifact_class": "B",
    })
    add_edge(conn, "discusses", did, concept_id)
    return did


def _add_observation(conn: sqlite3.Connection, concept_id: str, source_date: str) -> str:
    oid = f"obs-{source_date}-{concept_id[:8]}"
    add_node(conn, oid, "Observation", {
        "claim": f"Observation {oid}",
        "confidence": 0.8,
        "source_date": source_date,
        "artifact_class": "B",
    })
    add_edge(conn, "observes", oid, concept_id)
    return oid


def _add_benchmark(conn: sqlite3.Connection, concept_id: str, source_date: str) -> str:
    bid = f"bench-{source_date}-{concept_id[:8]}"
    add_node(conn, bid, "Benchmark", {
        "metric": "throughput",
        "result_summary": "10% faster",
        "conditions": "128 cores",
        "source_date": source_date,
        "artifact_class": "B",
    })
    add_edge(conn, "benchmarks", bid, concept_id)
    return bid


def _add_proposal(conn: sqlite3.Connection, concept_id: str, source_date: str) -> str:
    pid = f"prop-{source_date}-{concept_id[:8]}"
    add_node(conn, pid, "Proposal", {
        "name": f"Proposal {pid}",
        "description": "test proposal",
        "status": "draft",
        "source_date": source_date,
        "artifact_class": "B",
    })
    add_edge(conn, "grounded-in", pid, concept_id)
    return pid


def _add_problem(conn: sqlite3.Connection, concept_id: str, severity: str = "medium") -> str:
    pid = f"prob-{severity}-{concept_id[:8]}"
    add_node(conn, pid, "Problem", {
        "title": f"Problem {pid}",
        "description": "test problem",
        "severity": severity,
        "status": "open",
        "source_date": "2026-06-01",
        "artifact_class": "B",
    })
    add_edge(conn, "identifies-problem", pid, concept_id)
    return pid


def _add_vulnerability(
    conn: sqlite3.Connection, concept_id: str, cvss: str = "7.5", cve_id: str = "CVE-2026-0001",
) -> str:
    vid = f"vuln-{cve_id}"
    add_node(conn, vid, "Vulnerability", {
        "cve_id": cve_id,
        "title": f"Vuln {cve_id}",
        "description": "test vulnerability",
        "severity": "high",
        "cvss_score": cvss,
        "affected_versions": "6.0-6.10",
        "status": "unfixed",
        "source_date": "2026-06-01",
        "artifact_class": "B",
    })
    add_edge(conn, "exploits", vid, concept_id)
    return vid


def _add_failure_mode(conn: sqlite3.Connection, concept_id: str) -> str:
    kinv_id = f"kinv-{concept_id[:8]}"
    add_node(conn, kinv_id, "KernelInvariant", {
        "predicate": "test invariant",
        "strength": "safety",
        "scope": "per-operation",
        "artifact_class": "abstracted-mechanism",
    })
    add_edge(conn, "governed-by", kinv_id, concept_id)

    fm_id = f"fm-{concept_id[:8]}"
    add_node(conn, fm_id, "FailureMode", {
        "symptom": "data corruption",
        "blast_radius": "kernel-wide",
        "recoverability": "data-loss",
        "artifact_class": "abstracted-mechanism",
    })
    add_edge(conn, "triggered-by", fm_id, kinv_id)
    return fm_id


def _recent_date(days_ago: int = 0) -> str:
    return (datetime.now(tz=None) - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def _old_date(days_ago: int = 60) -> str:
    return (datetime.now(tz=None) - timedelta(days=days_ago)).strftime("%Y-%m-%d")


# ── Heat score tests (ALG-KK-SCORE-HEAT) ──


class TestHeatScore:
    def test_zero_evidence(self, conn):
        """INV-KK-SCORE-NON-NEGATIVE: no evidence = 0.0."""
        cid = _add_concept(conn, "RCU")
        assert heat_score(conn, cid) == 0.0

    def test_evidence_within_window(self, conn):
        cid = _add_concept(conn, "RCU")
        _add_discussion(conn, cid, _recent_date(5))
        _add_observation(conn, cid, _recent_date(10))
        _add_benchmark(conn, cid, _recent_date(15))
        assert heat_score(conn, cid, window_days=30) == 3.0

    def test_evidence_outside_window(self, conn):
        cid = _add_concept(conn, "RCU")
        _add_discussion(conn, cid, _old_date(60))
        _add_observation(conn, cid, _old_date(90))
        assert heat_score(conn, cid, window_days=30) == 0.0

    def test_mixed_in_and_out_window(self, conn):
        cid = _add_concept(conn, "Scheduler")
        _add_discussion(conn, cid, _recent_date(5))
        _add_discussion(conn, cid, _old_date(60))
        _add_observation(conn, cid, _recent_date(10))
        _add_benchmark(conn, cid, _old_date(90))
        assert heat_score(conn, cid, window_days=30) == 2.0

    def test_grounded_in_counted(self, conn):
        """INV-KK-SCORE-HEAT-EDGES: grounded-in is one of the 4 edge kinds."""
        cid = _add_concept(conn, "Folios")
        _add_proposal(conn, cid, _recent_date(3))
        assert heat_score(conn, cid, window_days=30) == 1.0

    def test_all_four_edge_kinds(self, conn):
        """INV-KK-SCORE-HEAT-EDGES: all 4 edge kinds contribute."""
        cid = _add_concept(conn, "VM")
        _add_discussion(conn, cid, _recent_date(1))
        _add_observation(conn, cid, _recent_date(2))
        _add_benchmark(conn, cid, _recent_date(3))
        _add_proposal(conn, cid, _recent_date(4))
        assert heat_score(conn, cid, window_days=30) == 4.0

    def test_custom_window(self, conn):
        cid = _add_concept(conn, "RCU")
        _add_discussion(conn, cid, _recent_date(10))
        _add_discussion(conn, cid, _recent_date(50))
        assert heat_score(conn, cid, window_days=7) == 0.0
        assert heat_score(conn, cid, window_days=15) == 1.0
        assert heat_score(conn, cid, window_days=60) == 2.0

    def test_nonexistent_concept(self, conn):
        assert heat_score(conn, "concept-nonexistent") == 0.0

    def test_evidence_not_linked_to_concept(self, conn):
        cid1 = _add_concept(conn, "RCU")
        cid2 = _add_concept(conn, "Slab")
        _add_discussion(conn, cid2, _recent_date(5))
        assert heat_score(conn, cid1, window_days=30) == 0.0


# ── CVSS weight tests (INV-KK-SCORE-CVSS-BRACKETS) ──


class TestCvssWeight:
    def test_critical(self):
        assert cvss_weight({"cvss_score": "9.0"}) == 4.0
        assert cvss_weight({"cvss_score": "10.0"}) == 4.0
        assert cvss_weight({"cvss_score": "9.8"}) == 4.0

    def test_high(self):
        assert cvss_weight({"cvss_score": "7.0"}) == 3.0
        assert cvss_weight({"cvss_score": "8.9"}) == 3.0

    def test_medium(self):
        assert cvss_weight({"cvss_score": "4.0"}) == 2.0
        assert cvss_weight({"cvss_score": "6.9"}) == 2.0

    def test_low(self):
        assert cvss_weight({"cvss_score": "3.9"}) == 1.0
        assert cvss_weight({"cvss_score": "0.0"}) == 1.0
        assert cvss_weight({"cvss_score": "1.5"}) == 1.0

    def test_missing_score(self):
        assert cvss_weight({}) == 1.0

    def test_empty_string(self):
        assert cvss_weight({"cvss_score": ""}) == 1.0

    def test_unparseable(self):
        assert cvss_weight({"cvss_score": "N/A"}) == 1.0

    def test_boundary_8_9(self):
        assert cvss_weight({"cvss_score": "8.99"}) == 3.0

    def test_boundary_6_9(self):
        assert cvss_weight({"cvss_score": "6.99"}) == 2.0


# ── Pain score tests (ALG-KK-SCORE-PAIN) ──


class TestPainScore:
    def test_zero_pain(self, conn):
        """INV-KK-SCORE-NON-NEGATIVE: no problems/vulns = 0.0."""
        cid = _add_concept(conn, "RCU")
        assert pain_score(conn, cid) == 0.0

    def test_problems_weighted_2x(self, conn):
        """INV-KK-SCORE-PAIN-WEIGHTS: Problems contribute 2x."""
        cid = _add_concept(conn, "RCU")
        _add_problem(conn, cid, "high")
        assert pain_score(conn, cid) == 2.0

    def test_multiple_problems(self, conn):
        cid = _add_concept(conn, "Slab")
        _add_problem(conn, cid, "high")
        _add_problem(conn, cid, "low")
        assert pain_score(conn, cid) == 4.0

    def test_failure_modes_weighted_3x(self, conn):
        """INV-KK-SCORE-PAIN-WEIGHTS: FailureModes contribute 3x."""
        cid = _add_concept(conn, "RCU")
        _add_failure_mode(conn, cid)
        assert pain_score(conn, cid) == 3.0

    def test_vulnerability_weighted_5x_cvss(self, conn):
        """INV-KK-SCORE-PAIN-WEIGHTS: Vulns contribute 5x * CVSS weight."""
        cid = _add_concept(conn, "Slab")
        _add_vulnerability(conn, cid, cvss="9.5", cve_id="CVE-2026-0001")
        assert pain_score(conn, cid) == 5.0 * 4.0  # 5x * critical(4)

    def test_medium_vuln(self, conn):
        cid = _add_concept(conn, "VFS")
        _add_vulnerability(conn, cid, cvss="5.0", cve_id="CVE-2026-0002")
        assert pain_score(conn, cid) == 5.0 * 2.0  # 5x * medium(2)

    def test_combined_pain(self, conn):
        cid = _add_concept(conn, "MM")
        _add_problem(conn, cid, "critical")
        _add_failure_mode(conn, cid)
        _add_vulnerability(conn, cid, cvss="7.5", cve_id="CVE-2026-0003")
        expected = 2.0 + 3.0 + (5.0 * 3.0)  # problem + fm + vuln(high)
        assert pain_score(conn, cid) == expected

    def test_multiple_vulns(self, conn):
        cid = _add_concept(conn, "Net")
        _add_vulnerability(conn, cid, cvss="9.8", cve_id="CVE-2026-0010")
        _add_vulnerability(conn, cid, cvss="4.0", cve_id="CVE-2026-0011")
        expected = (5.0 * 4.0) + (5.0 * 2.0)  # critical + medium
        assert pain_score(conn, cid) == expected

    def test_nonexistent_concept(self, conn):
        assert pain_score(conn, "concept-ghost") == 0.0


# ── Helper tests ──


class TestGetLinkedProblems:
    def test_returns_problems(self, conn):
        cid = _add_concept(conn, "RCU")
        _add_problem(conn, cid, "high")
        probs = get_linked_problems(conn, cid)
        assert len(probs) == 1
        assert probs[0]["severity"] == "high"

    def test_empty_when_none(self, conn):
        cid = _add_concept(conn, "RCU")
        assert get_linked_problems(conn, cid) == []


class TestGetLinkedVulns:
    def test_returns_vulns(self, conn):
        cid = _add_concept(conn, "Slab")
        _add_vulnerability(conn, cid, cvss="8.0", cve_id="CVE-2026-0020")
        vulns = get_linked_vulns(conn, cid)
        assert len(vulns) == 1
        assert vulns[0]["cvss_score"] == "8.0"

    def test_empty_when_none(self, conn):
        cid = _add_concept(conn, "RCU")
        assert get_linked_vulns(conn, cid) == []


class TestGetLinkedFailureModes:
    def test_returns_failure_modes(self, conn):
        cid = _add_concept(conn, "RCU")
        _add_failure_mode(conn, cid)
        fms = get_linked_failure_modes(conn, cid)
        assert len(fms) == 1
        assert fms[0]["symptom"] == "data corruption"

    def test_empty_when_none(self, conn):
        cid = _add_concept(conn, "RCU")
        assert get_linked_failure_modes(conn, cid) == []
