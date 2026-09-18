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


# ---------------------------------------------------------------------------
# Intake counts (ALG-KK-DIAG-GRAPH-HEALTH, 2026-09-18).
#
# Before these existed the module did not contain the string "Source". It
# reported on the concept graph in detail and said nothing about the papers that
# graph is derived from, so every intake defect this corpus had was found by
# hand after the fact.
# ---------------------------------------------------------------------------


def _paper(conn, sid, url="https://example.com/x", abstract="", evidence_text=None,
           source_type="preprint"):
    attrs = {"url": url, "source_type": source_type, "license": "MIT", "title": sid}
    if abstract:
        attrs["abstract"] = abstract
    add_node(conn, sid, "Source", attrs)
    if evidence_text is not None:
        ev = f"ev-{sid}"
        add_node(conn, ev, "Evidence", {
            "artifact_class": "A", "contamination_level": "L0",
            "description": "d", "text": evidence_text,
        })
        add_edge(conn, "sourced-from", ev, sid)
    return sid


def _verdict(conn, sid, **dims):
    base = dict.fromkeys(
        ("has_abstract", "has_summary", "links_concept",
         "links_subsystem", "links_kernel", "links_invariant"), False)
    base.update(dims)
    base["computed_at"] = "2026-09-18"
    base.setdefault("summary_state", "absent")  # required attr on PaperCompleteness
    add_node(conn, f"pcomp-{sid}", "PaperCompleteness", base)
    add_edge(conn, "completeness-of", f"pcomp-{sid}", sid)


def test_intake_counts_papers_and_missing_abstracts(conn):
    _paper(conn, "src-a", abstract="An abstract long enough to be real.")
    _paper(conn, "src-b")
    report = diagnose_graph(conn)
    assert report.papers_total == 2
    assert report.papers_without_abstract == 1


def test_a_paper_with_no_identifier_cannot_be_fetched_automatically(conn):
    """The 321 USENIX-family papers: no arXiv id and no DOI in the url, so no
    automated route to an abstract exists at all."""
    _paper(conn, "src-arxiv", url="https://arxiv.org/abs/2407.15805")
    _paper(conn, "src-doi", url="https://dl.acm.org/doi/10.1145/3694715.3695984")
    _paper(conn, "src-venue", url="https://www.usenix.org/conference/osdi26/presentation/x")
    report = diagnose_graph(conn)
    assert report.papers_without_abstract == 3
    assert report.papers_without_identifier == 1


def test_intake_counts_papers_with_no_evidence_text(conn):
    """These can be summarised from nothing: no abstract and no usable text."""
    _paper(conn, "src-with", evidence_text="Some real body text about scheduling.")
    _paper(conn, "src-empty-text", evidence_text="")
    _paper(conn, "src-none")
    report = diagnose_graph(conn)
    assert report.papers_without_evidence_text == 2


def test_intake_counts_papers_satisfying_no_dimension(conn):
    _paper(conn, "src-some")
    _verdict(conn, "src-some", has_abstract=True)
    _paper(conn, "src-none")
    _verdict(conn, "src-none")
    report = diagnose_graph(conn)
    assert report.papers_no_dimension == 1


def test_intake_counts_unreviewed_summaries(conn):
    """All 3,295 summaries in the real corpus are llm-extracted and none has been
    read by a person. has_summary says one exists, never that anyone endorsed it."""
    _paper(conn, "src-p")
    for sid, state in (("psum-1", "llm-extracted"), ("psum-2", "llm-extracted"),
                       ("psum-3", "human-reviewed")):
        add_node(conn, sid, "PaperSummary", {
            "text": "A stored summary of the paper.", "state": state,
            "model": "gpt-4o-mini", "reviewed_by": "", "set_at": "2026-09-18",
        })
    report = diagnose_graph(conn)
    assert report.summaries_unreviewed == 2


def test_only_paper_source_types_are_counted(conn):
    """INV-KK-PAPER-SOURCE-TYPE-VOCABULARY: kernel-doc and discourse Sources are
    legal and are not papers."""
    _paper(conn, "src-paper", source_type="preprint")
    _paper(conn, "src-doc", source_type="kernel-doc")
    _paper(conn, "src-chat", source_type="discourse")
    assert diagnose_graph(conn).papers_total == 1


def test_every_declared_field_is_present_on_a_report(conn):
    """INV-KK-DIAG-REPORT-COMPLETE. A count of zero is a measurement; an absent
    field would mean the check never ran, and the two must not look alike."""
    import dataclasses

    report = diagnose_graph(conn)
    for f in dataclasses.fields(DiagnosticReport):
        assert hasattr(report, f.name), f.name


def test_the_intake_counts_do_not_disturb_the_concept_graph_counts(conn):
    """The failure mode for this change is quietly altering an existing
    dimension while adding new ones. Build a graph with known concept-graph
    shape AND paper intake, and assert the original categories are untouched."""
    _concept(conn, "c-orphan")                      # no belongs-to -> orphan
    _subsystem(conn, "sub-1")
    _concept(conn, "c-linked")
    add_edge(conn, "belongs-to", "c-linked", "sub-1")
    _invariant(conn, "inv-1")                       # no governed-by -> unlinked
    _failure_mode(conn, "fm-1")                     # no triggered-by -> dangling
    _protocol(conn, "proto-1")                      # lone
    _paper(conn, "src-noise", evidence_text="")     # intake, should not interfere
    _verdict(conn, "src-noise")

    report = diagnose_graph(conn)

    assert report.orphan_concepts == ["c-orphan"]
    assert report.unlinked_invariants == ["inv-1"]
    assert report.dangling_failure_modes == ["fm-1"]
    assert report.lone_protocols == ["proto-1"]
    assert report.subsystem_coverage == {"TestSub": 1}
    # ...and the intake counts did see the paper.
    assert report.papers_total == 1
    assert report.papers_no_dimension == 1
