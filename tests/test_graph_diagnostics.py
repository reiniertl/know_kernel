"""Tests for graph diagnostics — ALG-KK-DIAG-GRAPH-HEALTH.

INV-KK-DIAG-REPORT-COMPLETE: all 7 diagnostic categories verified.
"""

from __future__ import annotations

import pytest

from graph.diagnostics import DiagnosticReport, diagnose_graph
from graph.engine import add_edge, add_node
from graph.schema import init_db


def _concept(conn, cid, name="Test Concept"):
    add_node(conn, cid, "Concept", {
        "name": name,
        "description": "desc",
        "artifact_class": "B",
        "key_properties": ["p1"],
        "tradeoffs": ["t1"],
        "design_rationale": "rationale",
    })


def _subsystem(conn, sid, name="TestSub"):
    add_node(conn, sid, "Subsystem", {"name": name})


def _invariant(conn, iid):
    add_node(conn, iid, "KernelInvariant", {
        "predicate": "forall x. P(x)",
        "strength": "safety",
        "scope": "global",
        "artifact_class": "B",
    })


def _failure_mode(conn, fid):
    add_node(conn, fid, "FailureMode", {
        "symptom": "crash",
        "blast_radius": "kernel-wide",
        "recoverability": "requires-restart",
        "artifact_class": "B",
    })


def _protocol(conn, pid):
    add_node(conn, pid, "InteractionProtocol", {
        "rule": "acquire before access",
        "ordering": "before",
        "violation_mode": "deadlock",
        "artifact_class": "B",
    })


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "diag_test.db"
    c = init_db(db_path)
    yield c
    c.close()


def test_diag_clean_graph_no_issues(conn):
    _subsystem(conn, "sub-1", "Scheduler")
    _concept(conn, "c-1", "CFS")
    add_edge(conn, "belongs-to", "c-1", "sub-1")
    _invariant(conn, "inv-1")
    add_edge(conn, "governed-by", "inv-1", "c-1")
    _failure_mode(conn, "fm-1")
    add_edge(conn, "triggered-by", "fm-1", "inv-1")
    _protocol(conn, "ip-1")
    _concept(conn, "c-2", "Spinlock")
    add_edge(conn, "belongs-to", "c-2", "sub-1")
    add_edge(conn, "constrains-composition", "ip-1", "c-1")
    add_edge(conn, "constrains-composition", "ip-1", "c-2")
    conn.commit()

    report = diagnose_graph(conn)
    assert report.orphan_concepts == []
    assert report.unlinked_invariants == []
    assert report.dangling_failure_modes == []
    assert report.lone_protocols == []


def test_diag_detects_orphan_concept(conn):
    _concept(conn, "orphan-1", "Orphan")
    conn.commit()

    report = diagnose_graph(conn)
    assert "orphan-1" in report.orphan_concepts


def test_diag_detects_unlinked_invariant(conn):
    _invariant(conn, "unlinked-inv")
    conn.commit()

    report = diagnose_graph(conn)
    assert "unlinked-inv" in report.unlinked_invariants


def test_diag_detects_dangling_failure_mode(conn):
    _failure_mode(conn, "dangling-fm")
    conn.commit()

    report = diagnose_graph(conn)
    assert "dangling-fm" in report.dangling_failure_modes


def test_diag_detects_lone_protocol(conn):
    _protocol(conn, "lone-ip")
    _concept(conn, "c-lone", "LoneConcept")
    add_edge(conn, "constrains-composition", "lone-ip", "c-lone")
    conn.commit()

    report = diagnose_graph(conn)
    assert "lone-ip" in report.lone_protocols


def test_diag_subsystem_coverage_counts(conn):
    _subsystem(conn, "sub-a", "Memory")
    _subsystem(conn, "sub-b", "Scheduler")
    _concept(conn, "c-a1", "PageTable")
    _concept(conn, "c-a2", "TLB")
    _concept(conn, "c-b1", "CFS")
    add_edge(conn, "belongs-to", "c-a1", "sub-a")
    add_edge(conn, "belongs-to", "c-a2", "sub-a")
    add_edge(conn, "belongs-to", "c-b1", "sub-b")
    conn.commit()

    report = diagnose_graph(conn)
    assert report.subsystem_coverage["Memory"] == 2
    assert report.subsystem_coverage["Scheduler"] == 1


def test_diag_invariant_density_calculation(conn):
    for i in range(3):
        _concept(conn, f"c-d-{i}", f"Concept{i}")
    for i in range(6):
        _invariant(conn, f"inv-d-{i}")
    conn.commit()

    report = diagnose_graph(conn)
    assert report.invariant_density == pytest.approx(2.0)


def test_diag_detects_duplicate_names(conn):
    _concept(conn, "dup-1", "RCU")
    _concept(conn, "dup-2", "rcu")
    conn.commit()

    report = diagnose_graph(conn)
    dup_names = [name for name, _ in report.duplicate_names]
    assert "rcu" in dup_names
    dup_entry = next(e for e in report.duplicate_names if e[0] == "rcu")
    assert set(dup_entry[1]) == {"dup-1", "dup-2"}


def test_orphan_problems_detected(conn):
    add_node(conn, "prob1", "Problem", {
        "title": "orphan", "description": "test", "severity": "low",
        "status": "open", "source_date": "2026-01-01", "artifact_class": "B",
    })
    conn.commit()
    report = diagnose_graph(conn)
    assert "prob1" in report.orphan_problems


def test_orphan_problems_clean(populated):
    report = diagnose_graph(populated)
    assert len(report.orphan_problems) == 0


def test_orphan_observations_detected(conn):
    add_node(conn, "obs1", "Observation", {
        "claim": "test", "confidence": "0.5",
        "source_date": "2026-01-01", "artifact_class": "B",
    })
    conn.commit()
    report = diagnose_graph(conn)
    assert "obs1" in report.orphan_observations


def test_orphan_observations_clean(populated):
    report = diagnose_graph(populated)
    assert len(report.orphan_observations) == 0


def test_unlinked_vulnerabilities_detected(conn):
    add_node(conn, "vuln1", "Vulnerability", {
        "cve_id": "CVE-2026-00001", "title": "test", "description": "test",
        "severity": "low", "cvss_score": "3.0", "affected_versions": "",
        "status": "unfixed", "source_date": "2026-01-01", "artifact_class": "B",
    })
    conn.commit()
    report = diagnose_graph(conn)
    assert "vuln1" in report.unlinked_vulnerabilities


def test_unlinked_vulnerabilities_clean(populated):
    report = diagnose_graph(populated)
    assert len(report.unlinked_vulnerabilities) == 0


def test_diag_total_counts(conn):
    _subsystem(conn, "sub-tc", "Sub")
    _concept(conn, "c-tc", "Concept")
    add_edge(conn, "belongs-to", "c-tc", "sub-tc")
    conn.commit()

    report = diagnose_graph(conn)
    assert report.total_nodes == 2
    assert report.total_edges == 1
