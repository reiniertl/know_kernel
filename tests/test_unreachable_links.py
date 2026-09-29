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
