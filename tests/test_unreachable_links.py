"""Retiring the legacy links nobody can check — and keeping a concept's last one.

THE POPULATION IS DEFINED BY WHAT CANNOT BE ASKED. Measured 2026-09-29: 289
unverified-legacy Concept links survived the re-derivation. 25 sit on Evidence
carrying text and are a work queue --all-relink will clear. The other 264 sit on
134 Evidence with NO TEXT — the paper was recorded from a citation and the body
was never fetched — so extract_concepts has nothing to read and never will.

THE RULE IS A COMPROMISE AND THESE TESTS PIN BOTH HALVES. Of the 57 concepts
holding those links, 35 would lose every piece of evidence they have and none of
the 35 is documented. Signal Delivery, OOM Killer, Ftrace, Namespaces, Seccomp
and Vmalloc are among them.
"""

from __future__ import annotations

import json

import pytest

from graph.engine import add_edge, add_node
from graph.rules import (
    LEGACY_UNVERIFIED_BASIS,
    concept_weight,
    documented_concepts,
    retire_unreachable_links,
    unreachable_legacy_links,
)
from graph.schema import init_db

SIX = {
    "description": "d", "artifact_class": "abstracted-mechanism",
    "key_properties": [], "tradeoffs": [], "design_rationale": "r",
}
FAILURE_MODE = {"symptom": "stall", "blast_radius": "task",
                "recoverability": "automatic",
                "artifact_class": "abstracted-mechanism"}


def _concept(conn, cid, name):
    add_node(conn, cid, "Concept", {**SIX, "name": name})
    return cid


def _evidence(conn, n, text=""):
    add_node(conn, f"src-{n}", "Source", {
        "url": f"https://example.com/{n}", "source_type": "preprint",
        "license": "MIT", "title": f"Paper {n}"})
    add_node(conn, f"ev-{n}", "Evidence", {
        "artifact_class": "A", "contamination_level": "L0", "text": text})
    add_edge(conn, "sourced-from", f"ev-{n}", f"src-{n}")
    return f"ev-{n}"


def _legacy(conn, cid, eid):
    add_edge(conn, "extracted-from", cid, eid, {
        "basis": LEGACY_UNVERIFIED_BASIS, "superseded": False,
        "mechanism": "title regex"})


def _current(conn, cid, eid):
    add_edge(conn, "extracted-from", cid, eid, {
        "basis": "evidence-text", "checked_at": "2026-09-29"})


def _attrs(conn, cid, eid):
    row = conn.execute(
        "SELECT attrs FROM edges WHERE kind='extracted-from' AND source_id=? "
        "AND target_id=?", (cid, eid)).fetchone()
    return json.loads(row[0]) if row and row[0] else {}


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "unreachable.db")
    yield c
    c.close()


# --- the selection ----------------------------------------------------------


def test_only_links_on_text_less_evidence_are_selected(conn):
    cid = _concept(conn, "concept-1", "Scheduling Classes")
    blind = _evidence(conn, "blind")
    readable = _evidence(conn, "readable", text="a real paper body")
    _legacy(conn, cid, blind)
    _legacy(conn, cid, readable)
    conn.commit()

    assert unreachable_legacy_links(conn) == [(cid, blind)]


def test_a_current_link_is_never_selected(conn):
    cid = _concept(conn, "concept-1", "Page Cache")
    blind = _evidence(conn, "blind")
    _current(conn, cid, blind)
    conn.commit()
    assert unreachable_legacy_links(conn) == []


def test_an_already_superseded_link_is_not_reselected(conn):
    cid = _concept(conn, "concept-1", "Page Cache")
    other = _evidence(conn, "other", text="body")
    _current(conn, cid, other)
    blind = _evidence(conn, "blind")
    _legacy(conn, cid, blind)
    conn.commit()
    retire_unreachable_links(conn)
    conn.commit()
    assert unreachable_legacy_links(conn) == []


def test_another_node_kinds_edge_is_never_selected(conn):
    """THE kind='Concept' FILTER, WHICH THIS CODEBASE HAS GOT WRONG FIVE TIMES.
    extracted-from runs from thirteen node kinds into Evidence and this sweep
    concerns exactly one. A FailureMode sharing an Evidence with a Concept must
    come through untouched."""
    cid = _concept(conn, "concept-1", "Scheduling Classes")
    other = _evidence(conn, "other", text="body")
    _current(conn, cid, other)
    blind = _evidence(conn, "blind")
    _legacy(conn, cid, blind)
    add_node(conn, "fm-1", "FailureMode", FAILURE_MODE)
    add_edge(conn, "extracted-from", "fm-1", blind, {
        "basis": LEGACY_UNVERIFIED_BASIS, "superseded": False})
    conn.commit()

    assert unreachable_legacy_links(conn) == [(cid, blind)]
    retire_unreachable_links(conn)
    conn.commit()
    assert _attrs(conn, "fm-1", blind)["superseded"] is False


# --- the last-evidence exception --------------------------------------------


def test_a_link_is_retired_when_the_concept_keeps_other_evidence(conn):
    cid = _concept(conn, "concept-1", "Scheduling Classes")
    _current(conn, cid, _evidence(conn, "good", text="a real body"))
    blind = _evidence(conn, "blind")
    _legacy(conn, cid, blind)
    conn.commit()
    assert concept_weight(conn, cid) == 2

    r = retire_unreachable_links(conn)
    conn.commit()

    assert r.retired == 1 and r.kept == 0
    assert r.concepts_touched == 1 and r.concepts_spared == 0
    assert _attrs(conn, cid, blind)["superseded"] is True
    assert concept_weight(conn, cid) == 1


def test_a_concepts_last_evidence_is_kept(conn):
    """35 of 57 concepts are in this position and none of them is documented.
    Keeping the link is not a claim that it is true; it is a judgement that a
    vocabulary silently knowing nothing about the OOM Killer is worse."""
    cid = _concept(conn, "concept-oom", "OOM Killer")
    blind = _evidence(conn, "blind")
    _legacy(conn, cid, blind)
    conn.commit()

    r = retire_unreachable_links(conn)
    conn.commit()

    assert r.retired == 0 and r.kept == 1
    assert r.concepts_touched == 0 and r.concepts_spared == 1
    assert _attrs(conn, cid, blind)["superseded"] is False
    assert concept_weight(conn, cid) == 1


def test_all_of_a_concepts_unreachable_links_go_together(conn):
    """The exception is per CONCEPT, not per link: a concept with three bad links
    and one good one loses all three."""
    cid = _concept(conn, "concept-1", "Scheduling Classes")
    _current(conn, cid, _evidence(conn, "good", text="a real body"))
    blind = [_evidence(conn, f"b{i}") for i in range(3)]
    for eid in blind:
        _legacy(conn, cid, eid)
    conn.commit()

    r = retire_unreachable_links(conn)
    conn.commit()

    assert r.retired == 3 and r.kept == 0
    assert all(_attrs(conn, cid, e)["superseded"] is True for e in blind)


def test_the_two_populations_are_counted_separately(conn):
    spared = _concept(conn, "concept-oom", "OOM Killer")
    _legacy(conn, spared, _evidence(conn, "b1"))
    _legacy(conn, spared, _evidence(conn, "b2"))
    touched = _concept(conn, "concept-sched", "Scheduling Classes")
    _current(conn, touched, _evidence(conn, "good", text="body"))
    _legacy(conn, touched, _evidence(conn, "b3"))
    conn.commit()

    r = retire_unreachable_links(conn)

    assert (r.retired, r.kept) == (1, 2)
    assert (r.concepts_touched, r.concepts_spared) == (1, 1)


# --- what the sweep must not do ---------------------------------------------


def test_no_concept_verdict_is_written(conn):
    """INV-KK-EXTRACT-NEGATIVE-VERDICT means "a model READ this paper and
    concluded it matches nothing". Writing it where nothing was read would be a
    lie in the graph, and would withdraw the paper from --all-relink forever."""
    cid = _concept(conn, "concept-1", "Scheduling Classes")
    _current(conn, cid, _evidence(conn, "good", text="body"))
    blind = _evidence(conn, "blind")
    _legacy(conn, cid, blind)
    conn.commit()

    retire_unreachable_links(conn)
    conn.commit()

    assert conn.execute(
        "SELECT json_extract(attrs, '$.concept_verdict') FROM nodes WHERE id=?",
        (blind,)).fetchone()[0] is None


def test_nothing_is_deleted(conn):
    cid = _concept(conn, "concept-1", "Scheduling Classes")
    _current(conn, cid, _evidence(conn, "good", text="body"))
    blind = _evidence(conn, "blind")
    _legacy(conn, cid, blind)
    conn.commit()
    nodes = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]

    retire_unreachable_links(conn)
    conn.commit()

    assert conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == nodes
    assert conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == edges
    assert _attrs(conn, cid, blind)["basis"] == LEGACY_UNVERIFIED_BASIS


def test_a_second_run_is_a_no_op_reporting_zero(conn):
    cid = _concept(conn, "concept-1", "Scheduling Classes")
    _current(conn, cid, _evidence(conn, "good", text="body"))
    _legacy(conn, cid, _evidence(conn, "blind"))
    conn.commit()

    first = retire_unreachable_links(conn)
    conn.commit()
    second = retire_unreachable_links(conn)

    assert first.retired == 1
    assert second.retired == 0 and second.kept == 0
    assert second.concepts_touched == 0


def test_a_dry_run_reports_and_writes_nothing(conn):
    cid = _concept(conn, "concept-1", "Scheduling Classes")
    _current(conn, cid, _evidence(conn, "good", text="body"))
    blind = _evidence(conn, "blind")
    _legacy(conn, cid, blind)
    conn.commit()

    r = retire_unreachable_links(conn, dry_run=True)

    assert r.retired == 1
    assert _attrs(conn, cid, blind)["superseded"] is False


def test_the_retired_link_records_why(conn):
    """A later reader can ask what was removed and on what grounds."""
    cid = _concept(conn, "concept-1", "Scheduling Classes")
    _current(conn, cid, _evidence(conn, "good", text="body"))
    blind = _evidence(conn, "blind")
    _legacy(conn, cid, blind)
    conn.commit()

    retire_unreachable_links(conn)
    conn.commit()

    a = _attrs(conn, cid, blind)
    assert a["superseded"] is True
    assert a["superseded_reason"] == "unreachable-legacy"


# ---------------------------------------------------------------------------
# THE PROPERTY THE WHOLE DEBT-PAYMENT ROUTE DEPENDS ON, pinned 2026-09-29.
#
# INV-KK-LINK-LAST-EVIDENCE-KEPT says the 94 surviving links are paid off by
# DOCUMENTING the 35 concepts that hold them. That only works if a concept's
# documentation counts toward _weight_without_unreachable — and the suspicion
# was that it does not, because that query counts SOURCES and a documented
# concept may carry no papers at all. If the suspicion were right the debt
# would be unpayable by documenting anything, forever, and nothing exercised
# it either way.
# ---------------------------------------------------------------------------

def _doc_evidence(conn, n, text="real kernel prose. " * 20):
    """A canonical-documentation Evidence, which is what pays the debt."""
    add_node(conn, f"src-{n}", "Source", {
        "url": f"https://git.kernel.org/x/tree/Documentation/mm/{n}.rst",
        "source_type": "kernel-doc", "license": "GPL-2.0", "title": n})
    add_node(conn, f"ev-{n}", "Evidence", {
        "artifact_class": "A", "contamination_level": "L0", "text": text})
    add_edge(conn, "sourced-from", f"ev-{n}", f"src-{n}")
    return f"ev-{n}"


def test_a_documented_concept_with_zero_papers_loses_its_legacy_link(conn):
    """THE CASE THAT DECIDES WHETHER THE DEBT CAN BE PAID AT ALL. Documentation
    reaches its Source by the same extracted-from then sourced-from traversal a
    paper does, so it counts — the concept is no longer relying on the legacy
    link and the sweep takes it."""
    cid = _concept(conn, "c-doc", "Documented No Papers")
    _current(conn, cid, _doc_evidence(conn, "highmem"))
    legacy = _legacy_evidence = _evidence(conn, "leg", text="")
    _legacy(conn, cid, legacy)
    conn.commit()

    assert cid in documented_concepts(conn)
    report = retire_unreachable_links(conn)
    assert report.retired == 1, "a documented concept was spared as a last resort"
    assert report.concepts_spared == 0
    assert _attrs(conn, cid, legacy).get("superseded") is True


def test_a_concept_with_only_a_legacy_link_still_keeps_it(conn):
    """The compromise INV-KK-LINK-LAST-EVIDENCE-KEPT exists for: a vocabulary
    silently knowing nothing about the OOM Killer is worse than one holding a
    marked, suspect link to it."""
    cid = _concept(conn, "c-bare", "Bare Legacy Only")
    legacy = _evidence(conn, "solo", text="")
    _legacy(conn, cid, legacy)
    conn.commit()

    report = retire_unreachable_links(conn)
    assert report.retired == 0
    assert report.concepts_spared == 1
    assert _attrs(conn, cid, legacy).get("superseded") is not True


def test_the_sweep_is_a_no_op_the_second_time(conn):
    cid = _concept(conn, "c-doc2", "Documented Twice Swept")
    _current(conn, cid, _doc_evidence(conn, "vmalloc"))
    _legacy(conn, cid, _evidence(conn, "leg2", text=""))
    conn.commit()

    assert retire_unreachable_links(conn).retired == 1
    again = retire_unreachable_links(conn)
    assert again.retired == 0 and again.kept == 0 and again.concepts_touched == 0


def test_documentation_absent_does_not_change_what_the_sweep_spares(conn):
    """INV-KK-CONCEPT-DOCUMENTATION-ABSENT must not suppress the sparing.
    Knowing a concept's silence is PERMANENT makes its one suspect link more
    necessary rather than less."""
    from graph.concept_vocabulary import mark_documentation_absent

    cid = _concept(conn, "c-signal", "Signal Delivery")
    legacy = _evidence(conn, "sig", text="")
    _legacy(conn, cid, legacy)
    assert mark_documentation_absent(
        conn, cid, "defined by kernel/signal.c; no Documentation/ page", "reiniertl")
    conn.commit()

    report = retire_unreachable_links(conn)
    assert report.retired == 0, "marking a concept undocumentable dropped its last link"
    assert report.concepts_spared == 1
