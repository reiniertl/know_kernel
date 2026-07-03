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
    compute_all_scores,
    cvss_weight,
    feasibility_score,
    frontier_score,
    get_linked_failure_modes,
    get_linked_problems,
    get_linked_vulns,
    heat_score,
    impact_projection,
    impact_score,
    leverage_score,
    pain_score,
    refresh_scores,
    research_score,
    vulnerability_propagation,
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


# ── Impact score tests (ALG-KK-SCORE-IMPACT) ──


def _add_kernel_invariant(conn: sqlite3.Connection, concept_id: str, tag: str = "a") -> str:
    kinv_id = f"kinv-{tag}-{concept_id[:8]}"
    add_node(conn, kinv_id, "KernelInvariant", {
        "predicate": f"invariant {tag}",
        "strength": "safety",
        "scope": "per-operation",
        "artifact_class": "abstracted-mechanism",
    })
    add_edge(conn, "governed-by", kinv_id, concept_id)
    return kinv_id


def _add_optimization_goal(conn: sqlite3.Connection, concept_id: str, tag: str = "a") -> str:
    gid = f"goal-{tag}-{concept_id[:8]}"
    add_node(conn, gid, "OptimizationGoal", {
        "name": f"Goal {tag}",
        "description": f"test goal {tag}",
        "metric": "throughput",
        "direction": "maximize",
    })
    add_edge(conn, "contributes-to", concept_id, gid)
    return gid


class TestImpactScore:
    def test_isolated_concept(self, conn):
        """INV-KK-SCORE-NON-NEGATIVE: no downstream = 0.0."""
        cid = _add_concept(conn, "RCU")
        assert impact_score(conn, cid) == 0.0

    def test_with_invariants(self, conn):
        cid = _add_concept(conn, "Slab")
        _add_kernel_invariant(conn, cid, "x")
        _add_kernel_invariant(conn, cid, "y")
        assert impact_score(conn, cid) == 2.0

    def test_with_goals(self, conn):
        cid = _add_concept(conn, "VM")
        _add_optimization_goal(conn, cid, "perf")
        assert impact_score(conn, cid) == 1.0

    def test_hub_concept(self, conn):
        cid = _add_concept(conn, "Net")
        _add_kernel_invariant(conn, cid, "a")
        _add_kernel_invariant(conn, cid, "b")
        _add_optimization_goal(conn, cid, "lat")
        _add_failure_mode(conn, cid)
        assert impact_score(conn, cid) >= 4.0

    def test_nonexistent_concept(self, conn):
        assert impact_score(conn, "concept-ghost") == 0.0


# ── Leverage score tests (ALG-KK-SCORE-LEVERAGE) ──


class TestLeverageScore:
    def test_no_problems(self, conn):
        """INV-KK-SCORE-NON-NEGATIVE: no problems = 0.0."""
        cid = _add_concept(conn, "RCU")
        assert leverage_score(conn, cid) == 0.0

    def test_critical_weight(self, conn):
        """INV-KK-SCORE-LEVERAGE-WEIGHTS: critical = 4."""
        cid = _add_concept(conn, "Slab")
        _add_problem(conn, cid, "critical")
        assert leverage_score(conn, cid) == 4.0

    def test_high_weight(self, conn):
        cid = _add_concept(conn, "VM")
        _add_problem(conn, cid, "high")
        assert leverage_score(conn, cid) == 3.0

    def test_medium_weight(self, conn):
        cid = _add_concept(conn, "Net")
        _add_problem(conn, cid, "medium")
        assert leverage_score(conn, cid) == 2.0

    def test_low_weight(self, conn):
        cid = _add_concept(conn, "VFS")
        _add_problem(conn, cid, "low")
        assert leverage_score(conn, cid) == 1.0

    def test_mixed_severities(self, conn):
        cid = _add_concept(conn, "MM")
        _add_problem(conn, cid, "critical")
        _add_problem(conn, cid, "low")
        assert leverage_score(conn, cid) == 5.0  # 4 + 1

    def test_nonexistent_concept(self, conn):
        assert leverage_score(conn, "concept-ghost") == 0.0


# ── Frontier score tests (ALG-KK-SCORE-FRONTIER) ──


class TestFrontierScore:
    def test_zero_everything(self, conn):
        """INV-KK-SCORE-NON-NEGATIVE: no data = 0.0."""
        cid = _add_concept(conn, "RCU")
        assert frontier_score(conn, cid) == 0.0

    def test_formula_with_known_inputs(self, conn):
        """INV-KK-SCORE-FRONTIER-FORMULA: verify the composite formula."""
        cid = _add_concept(conn, "Slab")
        _add_discussion(conn, cid, _recent_date(5))
        _add_problem(conn, cid, "high")
        # heat=1.0 (1 discussion in window), pain=2.0 (1 problem*2x),
        # leverage=3.0 (high=3), solved=0.0 (no resolved)
        # frontier = 1.0*0.3 + 2.0*0.3 + 3.0*0.3 - 0.0*10 = 1.8
        assert frontier_score(conn, cid, window_days=90) == pytest.approx(1.8)

    def test_all_resolved_negative_contribution(self, conn):
        """INV-KK-SCORE-SOLVED-RATIO: all resolved → solved_confidence=1.0."""
        cid = _add_concept(conn, "VM")
        pid = _add_problem(conn, cid, "medium")
        conn.execute(
            "UPDATE nodes SET attrs = json_set(attrs, '$.status', 'resolved') WHERE id = ?",
            (pid,),
        )
        # heat=0, pain=2.0, leverage=2.0, solved=1.0
        # raw = 0*0.3 + 2.0*0.3 + 2.0*0.3 - 1.0*10 = 1.2 - 10 = -8.8
        # floored at 0.0
        assert frontier_score(conn, cid) == 0.0

    def test_partial_resolved(self, conn):
        cid = _add_concept(conn, "Net")
        pid1 = _add_problem(conn, cid, "critical")
        _add_problem(conn, cid, "high")
        conn.execute(
            "UPDATE nodes SET attrs = json_set(attrs, '$.status', 'resolved') WHERE id = ?",
            (pid1,),
        )
        # heat=0, pain=4.0 (2 problems*2x), leverage=7.0 (4+3), solved=0.5
        # raw = 0*0.3 + 4.0*0.3 + 7.0*0.3 - 0.5*10 = 3.3 - 5.0 = -1.7 → 0.0
        assert frontier_score(conn, cid) == 0.0

    def test_frontier_nonexistent(self, conn):
        assert frontier_score(conn, "concept-ghost") == 0.0


# ── compute_all_scores tests ──


class TestComputeAllScores:
    def test_returns_all_five_keys(self, conn):
        cid = _add_concept(conn, "RCU")
        scores = compute_all_scores(conn, cid)
        assert set(scores.keys()) == {"heat", "pain", "impact", "leverage", "frontier"}

    def test_all_zero_for_empty_concept(self, conn):
        cid = _add_concept(conn, "Slab")
        scores = compute_all_scores(conn, cid)
        assert all(v == 0.0 for v in scores.values())

    def test_values_match_individual_functions(self, conn):
        cid = _add_concept(conn, "VM")
        _add_discussion(conn, cid, _recent_date(5))
        _add_problem(conn, cid, "high")
        scores = compute_all_scores(conn, cid, window_days=90)
        assert scores["heat"] == heat_score(conn, cid, window_days=90)
        assert scores["pain"] == pain_score(conn, cid)
        assert scores["impact"] == impact_score(conn, cid)
        assert scores["leverage"] == leverage_score(conn, cid)
        assert scores["frontier"] == frontier_score(conn, cid, window_days=90)


# ── refresh_scores tests (ALG-KK-SCORE-REFRESH) ──


class TestRefreshScores:
    def test_caches_in_attrs(self, conn):
        """INV-KK-SCORE-CACHE-ATTR: _scores + _scores_computed_at stored in attrs."""
        cid = _add_concept(conn, "RCU")
        refresh_scores(conn, [cid])
        row = conn.execute("SELECT attrs FROM nodes WHERE id = ?", (cid,)).fetchone()
        attrs = json.loads(row[0])
        assert "_scores" in attrs
        assert "_scores_computed_at" in attrs
        cached = json.loads(attrs["_scores"])
        assert set(cached.keys()) == {"heat", "pain", "impact", "leverage", "frontier"}

    def test_timestamp_is_iso8601(self, conn):
        cid = _add_concept(conn, "Slab")
        refresh_scores(conn, [cid])
        row = conn.execute("SELECT attrs FROM nodes WHERE id = ?", (cid,)).fetchone()
        attrs = json.loads(row[0])
        ts = attrs["_scores_computed_at"]
        datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")

    def test_refresh_all_concepts(self, conn):
        """INV-KK-SCORE-REFRESH-ALL: None refreshes all Concept nodes."""
        cid1 = _add_concept(conn, "RCU", "concept-rcu-all")
        cid2 = _add_concept(conn, "Slab", "concept-slab-all")
        count = refresh_scores(conn, None)
        assert count == 2
        for cid in [cid1, cid2]:
            row = conn.execute("SELECT attrs FROM nodes WHERE id = ?", (cid,)).fetchone()
            attrs = json.loads(row[0])
            assert "_scores" in attrs

    def test_refresh_specific_ids(self, conn):
        cid1 = _add_concept(conn, "RCU", "concept-rcu-spec")
        cid2 = _add_concept(conn, "Slab", "concept-slab-spec")
        count = refresh_scores(conn, [cid1])
        assert count == 1
        row1 = conn.execute("SELECT attrs FROM nodes WHERE id = ?", (cid1,)).fetchone()
        row2 = conn.execute("SELECT attrs FROM nodes WHERE id = ?", (cid2,)).fetchone()
        assert "_scores" in json.loads(row1[0])
        assert "_scores" not in json.loads(row2[0])

    def test_returns_count(self, conn):
        _add_concept(conn, "A", "concept-a")
        _add_concept(conn, "B", "concept-b")
        _add_concept(conn, "C", "concept-c")
        assert refresh_scores(conn, None) == 3

    def test_scores_update_on_refresh(self, conn):
        cid = _add_concept(conn, "RCU", "concept-rcu-upd")
        refresh_scores(conn, [cid])
        row = conn.execute("SELECT attrs FROM nodes WHERE id = ?", (cid,)).fetchone()
        scores1 = json.loads(json.loads(row[0])["_scores"])
        assert scores1["heat"] == 0.0
        _add_discussion(conn, cid, _recent_date(3))
        refresh_scores(conn, [cid])
        row = conn.execute("SELECT attrs FROM nodes WHERE id = ?", (cid,)).fetchone()
        scores2 = json.loads(json.loads(row[0])["_scores"])
        assert scores2["heat"] == 1.0


def _add_fix(conn: sqlite3.Connection, concept_id: str, tag: str = "a") -> str:
    fid = f"fix-{tag}-{concept_id[:8]}"
    add_node(conn, fid, "Fix", {
        "title": f"Fix {tag}",
        "commit_hash": f"abc{tag}123",
        "fix_type": "patch",
        "source_date": "2026-06-15",
        "artifact_class": "B",
    })
    add_edge(conn, "patches", fid, concept_id)
    return fid


def _add_evidence_source(
    conn: sqlite3.Connection, concept_id: str, url: str, tag: str = "a",
) -> tuple[str, str]:
    eid = f"ev-{tag}-{concept_id[:8]}"
    add_node(conn, eid, "Evidence", {
        "description": f"Evidence {tag}",
        "artifact_class": "B",
        "contamination_level": "L0",
    })
    sid = f"src-{tag}-{concept_id[:8]}"
    add_node(conn, sid, "Source", {
        "url": url,
        "title": f"Source {tag}",
        "source_type": "article",
        "license": "CC-BY-4.0",
        "source_date": "2026-06-01",
    })
    add_edge(conn, "extracted-from", concept_id, eid)
    add_edge(conn, "sourced-from", eid, sid)
    return eid, sid


# ── Research score tests (ALG-KK-GRAPH-RESEARCH-SCORE) ──


class TestResearchScore:
    def test_research_score_returns_float(self, conn):
        cid = _add_concept(conn, "RCU")
        result = research_score(conn, cid)
        assert isinstance(result, float)

    def test_research_score_pure(self, conn):
        """INV-KK-GRAPH-RESEARCH-SCORE-PURE: same inputs → same output."""
        cid = _add_concept(conn, "Slab")
        _add_discussion(conn, cid, _recent_date(5))
        r1 = research_score(conn, cid, window_days=90)
        r2 = research_score(conn, cid, window_days=90)
        assert r1 == r2

    def test_research_score_zero_for_empty_concept(self, conn):
        """INV-KK-GRAPH-RESEARCH-SCORE-NON-NEGATIVE: empty concept still >= 0."""
        cid = _add_concept(conn, "Empty")
        score = research_score(conn, cid)
        assert score >= 0.0
        # novelty_bonus exists even for empty concepts (no fixes, no problems)
        # novelty = (1.0 - 0.0) * 5.0 + 5.0 = 10.0, weighted 0.10 = 1.0
        assert score == pytest.approx(1.0)

    def test_research_score_increases_with_discussions(self, conn):
        """More discussions in window → higher score."""
        cid = _add_concept(conn, "VM")
        s0 = research_score(conn, cid, window_days=90)
        _add_discussion(conn, cid, _recent_date(5))
        s1 = research_score(conn, cid, window_days=90)
        _add_discussion(conn, cid, _recent_date(10))
        s2 = research_score(conn, cid, window_days=90)
        assert s1 > s0
        assert s2 > s1

    def test_research_score_weights_participant_count(self, conn):
        """INV-KK-GRAPH-RESEARCH-SCORE-FORMULA: participant_count weighted."""
        cid = _add_concept(conn, "Net")
        did = f"disc-pc-{cid[:8]}"
        add_node(conn, did, "Discussion", {
            "title": "Big discussion",
            "forum": "lkml",
            "participant_count": 30,
            "source_date": _recent_date(5),
            "artifact_class": "B",
        })
        add_edge(conn, "discusses", did, cid)
        # discussion_density = min(30, 50)/10 = 3.0, weighted 0.25 = 0.75
        # novelty_bonus = (1-0)*5 + 5 = 10, weighted 0.10 = 1.0
        # total should include 0.75 from discussion density
        score = research_score(conn, cid, window_days=90)
        assert score >= 1.75  # at least 0.75 + 1.0

    def test_research_score_rewards_evidence_diversity(self, conn):
        """More distinct source URLs → higher evidence_diversity component."""
        cid = _add_concept(conn, "IO")
        s0 = research_score(conn, cid, window_days=90)
        _add_evidence_source(conn, cid, "https://example.com/a", "a")
        s1 = research_score(conn, cid, window_days=90)
        _add_evidence_source(conn, cid, "https://example.com/b", "b")
        s2 = research_score(conn, cid, window_days=90)
        assert s1 > s0
        assert s2 > s1

    def test_research_score_rewards_proposals(self, conn):
        """Proposals via grounded-in increase score."""
        cid = _add_concept(conn, "Sched")
        s0 = research_score(conn, cid, window_days=90)
        _add_proposal(conn, cid, _recent_date(3))
        s1 = research_score(conn, cid, window_days=90)
        assert s1 > s0

    def test_research_score_novelty_bonus(self, conn):
        """INV-KK-GRAPH-RESEARCH-SCORE-FORMULA: no fixes → higher novelty bonus."""
        cid_no_fix = _add_concept(conn, "Novel", "concept-novel")
        cid_with_fix = _add_concept(conn, "Fixed", "concept-fixed")
        _add_fix(conn, cid_with_fix, "f1")
        _add_fix(conn, cid_with_fix, "f2")
        _add_fix(conn, cid_with_fix, "f3")
        score_no_fix = research_score(conn, cid_no_fix, window_days=90)
        score_with_fix = research_score(conn, cid_with_fix, window_days=90)
        assert score_no_fix > score_with_fix


    def test_is_security_only_concept_true(self, conn):
        """INV-KK-GRAPH-RESEARCH-SCORE-NO-SECURITY-ONLY: concept with only vulns is security-only."""
        from graph.scoring import is_security_only_concept
        cid = _add_concept(conn, "SecOnly", "concept-seconly")
        add_node(conn, "vuln-test1", "Vulnerability", {
            "cve_id": "CVE-2026-0001", "title": "Test vuln", "description": "d",
            "severity": "high", "cvss_score": 7.5, "affected_versions": "6.x",
            "status": "open", "source_date": "2026-06-01", "artifact_class": "B",
        })
        add_edge(conn, "exploits", "vuln-test1", cid)
        assert is_security_only_concept(conn, cid) is True

    def test_is_security_only_concept_false_with_discussions(self, conn):
        """INV-KK-GRAPH-RESEARCH-SCORE-NO-SECURITY-ONLY: concept with discussions is not security-only."""
        from graph.scoring import is_security_only_concept
        cid = _add_concept(conn, "WithDisc", "concept-withdisc")
        _add_discussion(conn, cid, "2026-06-01")
        add_node(conn, "vuln-test2", "Vulnerability", {
            "cve_id": "CVE-2026-0002", "title": "Test vuln 2", "description": "d",
            "severity": "high", "cvss_score": 7.5, "affected_versions": "6.x",
            "status": "open", "source_date": "2026-06-01", "artifact_class": "B",
        })
        add_edge(conn, "exploits", "vuln-test2", cid)
        assert is_security_only_concept(conn, cid) is False

    def test_is_security_only_concept_false_no_vulns(self, conn):
        """INV-KK-GRAPH-RESEARCH-SCORE-NO-SECURITY-ONLY: concept with no vulns is not security-only."""
        from graph.scoring import is_security_only_concept
        cid = _add_concept(conn, "NoVuln", "concept-novuln")
        assert is_security_only_concept(conn, cid) is False


def _add_subsystem(conn: sqlite3.Connection, name: str) -> str:
    sid = f"sub-{name.lower()}"
    add_node(conn, sid, "Subsystem", {"name": name})
    return sid


def _add_perf_profile(conn: sqlite3.Connection, concept_id: str, tag: str = "a") -> str:
    pid = f"pp-{tag}-{concept_id[:8]}"
    add_node(conn, pid, "PerformanceProfile", {
        "metric": "latency",
        "complexity": "O(1)",
        "best_case": "1ms",
        "typical_case": "5ms",
        "worst_case": "50ms",
        "conditions": "128 cores",
        "artifact_class": "abstracted-mechanism",
    })
    add_edge(conn, "profiled-by", pid, concept_id)
    return pid


# ── Feasibility score tests (ALG-KK-GRAPH-FEASIBILITY-SCORE) ──


class TestFeasibilityScore:
    def test_feasibility_score_bounded(self, conn):
        """INV-KK-GRAPH-FEASIBILITY-BOUNDED: always in [0, 10]."""
        cid = _add_concept(conn, "RCU")
        score = feasibility_score(conn, cid)
        assert 0.0 <= score <= 10.0

    def test_feasibility_score_max_for_standalone(self, conn):
        """Standalone concept with no prereqs/invariants/protocols → 10.0."""
        cid = _add_concept(conn, "Simple")
        assert feasibility_score(conn, cid) == 10.0

    def test_feasibility_score_decreases_with_depth(self, conn):
        """INV-KK-GRAPH-FEASIBILITY-FORMULA: deeper prereq chain → lower score."""
        cid_a = _add_concept(conn, "A", "concept-feas-a")
        cid_b = _add_concept(conn, "B", "concept-feas-b")
        cid_c = _add_concept(conn, "C", "concept-feas-c")
        add_edge(conn, "prerequisite", cid_a, cid_b)
        add_edge(conn, "prerequisite", cid_b, cid_c)
        # depth=2 for A, depth=1 for B, depth=0 for C
        score_a = feasibility_score(conn, cid_a)
        score_b = feasibility_score(conn, cid_b)
        score_c = feasibility_score(conn, cid_c)
        assert score_c > score_b > score_a

    def test_feasibility_score_cross_subsystem_penalty(self, conn):
        """INV-KK-GRAPH-FEASIBILITY-FORMULA: cross-subsystem → -2.0 penalty."""
        cid_a = _add_concept(conn, "X", "concept-cross-a")
        cid_b = _add_concept(conn, "Y", "concept-cross-b")
        sub1 = _add_subsystem(conn, "MM")
        sub2 = _add_subsystem(conn, "Net")
        add_edge(conn, "belongs-to", cid_a, sub1)
        add_edge(conn, "belongs-to", cid_b, sub2)
        add_edge(conn, "prerequisite", cid_a, cid_b)
        score = feasibility_score(conn, cid_a)
        # depth=1 → 1.5, cross_subsystem=1 → 2.0, total penalty=3.5
        assert score == pytest.approx(6.5)


# ── Impact projection tests (ALG-KK-GRAPH-IMPACT-PROJECTION) ──


class TestImpactProjection:
    def test_impact_projection_returns_dict(self, conn):
        """INV-KK-GRAPH-IMPACT-PROJECTION-COMPLETE: returns 7-key dict."""
        cid = _add_concept(conn, "RCU")
        result = impact_projection(conn, cid)
        assert isinstance(result, dict)
        expected_keys = {
            "problems_addressed", "vulns_mitigated",
            "failure_modes_eliminated", "dependent_components",
            "performance_metrics", "subsystems_affected", "total_impact",
        }
        assert set(result.keys()) == expected_keys

    def test_impact_projection_counts_problems(self, conn):
        """Unresolved problems are counted, resolved are not."""
        cid = _add_concept(conn, "Slab")
        pid1 = _add_problem(conn, cid, "high")
        _add_problem(conn, cid, "medium")
        conn.execute(
            "UPDATE nodes SET attrs = json_set(attrs, '$.status', 'resolved') WHERE id = ?",
            (pid1,),
        )
        result = impact_projection(conn, cid)
        assert result["problems_addressed"] == 1

    def test_impact_projection_total_formula(self, conn):
        """INV-KK-GRAPH-IMPACT-PROJECTION-FORMULA: verify weighted sum."""
        cid = _add_concept(conn, "VM", "concept-impact-vm")
        _add_problem(conn, cid, "high")  # 1 problem → *2
        _add_vulnerability(conn, cid, cvss="7.0", cve_id="CVE-2026-IMP1")  # 1 vuln → *5
        _add_failure_mode(conn, cid)  # 1 fm → *3
        _add_perf_profile(conn, cid, "lat")  # 1 pp → *1.5
        sub = _add_subsystem(conn, "VMSub")
        add_edge(conn, "belongs-to", cid, sub)  # 1 sub → *2
        result = impact_projection(conn, cid)
        expected = 1*2 + 1*5 + 1*3 + 0*1 + 1*1.5 + 1*2
        assert result["total_impact"] == pytest.approx(expected)


# ── Vulnerability propagation tests (ALG-KK-VULN-PROPAGATE) ──


def _add_interaction_protocol(conn: sqlite3.Connection, concept_ids: list[str], tag: str = "p") -> str:
    pid = f"ip-{tag}"
    add_node(conn, pid, "InteractionProtocol", {
        "rule": f"protocol {tag}",
        "ordering": "total",
        "violation_mode": "fault",
        "artifact_class": "abstracted-mechanism",
    })
    for cid in concept_ids:
        add_edge(conn, "constrains-composition", pid, cid)
    return pid


class TestVulnerabilityPropagation:
    def test_full_topology(self, conn):
        """Full test: vuln exploits A, B prereqs A, protocol links A+C, invariant links A+D."""
        cid_a = _add_concept(conn, "Slab", "concept-slab-prop")
        cid_b = _add_concept(conn, "PageCache", "concept-pagecache")
        cid_c = _add_concept(conn, "RCU", "concept-rcu-prop")
        cid_d = _add_concept(conn, "VFS", "concept-vfs-prop")

        vid = _add_vulnerability(conn, cid_a, cvss="9.0", cve_id="CVE-2026-PROP-1")

        add_edge(conn, "prerequisite", cid_b, cid_a)

        _add_interaction_protocol(conn, [cid_a, cid_c], "proto1")

        kinv_id = f"kinv-shared-prop"
        add_node(conn, kinv_id, "KernelInvariant", {
            "predicate": "shared invariant",
            "strength": "safety",
            "scope": "per-operation",
            "artifact_class": "abstracted-mechanism",
        })
        add_edge(conn, "governed-by", kinv_id, cid_a)
        add_edge(conn, "governed-by", kinv_id, cid_d)

        result = vulnerability_propagation(conn, vid)

        assert result["direct"] == [cid_a]
        assert cid_a in result["propagated"]
        prop = result["propagated"][cid_a]
        assert cid_b in prop["dependents"]
        assert cid_c in prop["composed_with"]
        assert cid_d in prop["shared_invariant"]

    def test_no_exploits(self, conn):
        """Vuln with no exploits edge → empty results."""
        vid = "vuln-orphan"
        add_node(conn, vid, "Vulnerability", {
            "cve_id": "CVE-2026-ORPHAN",
            "title": "Orphan vuln",
            "description": "no exploits",
            "severity": "low",
            "cvss_score": "2.0",
            "affected_versions": "6.0",
            "status": "unfixed",
            "source_date": "2026-06-01",
            "artifact_class": "B",
        })
        result = vulnerability_propagation(conn, vid)
        assert result["direct"] == []
        assert result["propagated"] == {}

    def test_no_coupling(self, conn):
        """Concept with no coupling edges → empty propagation lists."""
        cid = _add_concept(conn, "Isolated", "concept-isolated-prop")
        vid = _add_vulnerability(conn, cid, cvss="7.0", cve_id="CVE-2026-ISOL")
        result = vulnerability_propagation(conn, vid)
        assert result["direct"] == [cid]
        prop = result["propagated"][cid]
        assert prop["dependents"] == []
        assert prop["composed_with"] == []
        assert prop["shared_invariant"] == []

    def test_no_self_reference(self, conn):
        """INV-KK-VULN-PROP-NO-SELF: concept not in its own propagated lists."""
        cid_a = _add_concept(conn, "SelfTest", "concept-self-test")
        cid_b = _add_concept(conn, "Other", "concept-other-self")
        vid = _add_vulnerability(conn, cid_a, cvss="8.0", cve_id="CVE-2026-SELF")

        _add_interaction_protocol(conn, [cid_a, cid_b], "proto-self")

        result = vulnerability_propagation(conn, vid)
        prop = result["propagated"][cid_a]
        assert cid_a not in prop["dependents"]
        assert cid_a not in prop["composed_with"]
        assert cid_a not in prop["shared_invariant"]

    def test_multiple_exploited_concepts(self, conn):
        """Vuln exploiting multiple concepts."""
        cid_a = _add_concept(conn, "MultiA", "concept-multi-a")
        cid_b = _add_concept(conn, "MultiB", "concept-multi-b")

        vid = "vuln-multi"
        add_node(conn, vid, "Vulnerability", {
            "cve_id": "CVE-2026-MULTI",
            "title": "Multi vuln",
            "description": "hits two concepts",
            "severity": "high",
            "cvss_score": "8.0",
            "affected_versions": "6.0",
            "status": "unfixed",
            "source_date": "2026-06-01",
            "artifact_class": "B",
        })
        add_edge(conn, "exploits", vid, cid_a)
        add_edge(conn, "exploits", vid, cid_b)

        result = vulnerability_propagation(conn, vid)
        assert set(result["direct"]) == {cid_a, cid_b}
        assert cid_a in result["propagated"]
        assert cid_b in result["propagated"]

    def test_nonexistent_vuln(self, conn):
        """Nonexistent vuln ID → empty."""
        result = vulnerability_propagation(conn, "vuln-ghost")
        assert result["direct"] == []
        assert result["propagated"] == {}

    def test_multiple_shared_invariants(self, conn):
        """Multiple invariants each shared with different concepts."""
        cid_a = _add_concept(conn, "Core", "concept-core-shinv")
        cid_b = _add_concept(conn, "ExtB", "concept-ext-b")
        cid_c = _add_concept(conn, "ExtC", "concept-ext-c")
        vid = _add_vulnerability(conn, cid_a, cvss="9.0", cve_id="CVE-2026-SHINV")

        kinv1 = "kinv-sh1"
        add_node(conn, kinv1, "KernelInvariant", {
            "predicate": "inv 1", "strength": "safety",
            "scope": "per-operation", "artifact_class": "abstracted-mechanism",
        })
        add_edge(conn, "governed-by", kinv1, cid_a)
        add_edge(conn, "governed-by", kinv1, cid_b)

        kinv2 = "kinv-sh2"
        add_node(conn, kinv2, "KernelInvariant", {
            "predicate": "inv 2", "strength": "safety",
            "scope": "per-operation", "artifact_class": "abstracted-mechanism",
        })
        add_edge(conn, "governed-by", kinv2, cid_a)
        add_edge(conn, "governed-by", kinv2, cid_c)

        result = vulnerability_propagation(conn, vid)
        shared = result["propagated"][cid_a]["shared_invariant"]
        assert cid_b in shared
        assert cid_c in shared

    def test_no_duplicate_composed(self, conn):
        """Multiple protocols between same concepts don't produce duplicates."""
        cid_a = _add_concept(conn, "DupA", "concept-dup-a")
        cid_b = _add_concept(conn, "DupB", "concept-dup-b")
        vid = _add_vulnerability(conn, cid_a, cvss="7.0", cve_id="CVE-2026-DUP")

        _add_interaction_protocol(conn, [cid_a, cid_b], "proto-dup1")
        _add_interaction_protocol(conn, [cid_a, cid_b], "proto-dup2")

        result = vulnerability_propagation(conn, vid)
        composed = result["propagated"][cid_a]["composed_with"]
        assert composed.count(cid_b) == 1
