"""INV-KK-CONCEPT-ADMISSION: a Concept is an established class.

The invariant has said since 2026-09-16 that "Papers are linked to a curated
vocabulary rather than minting a concept each", and until 2026-09-22 nothing
checked it — it was declared enforced with an empty container and no code in
src/ consulted it. Two extraction batches added 114 Concepts of weight 1
without a murmur.

These tests cover the detector. The structural half — stopping the extractor
creating them at all — is INV-KK-EXTRACT-CONCEPT-MATCHED.
"""

from __future__ import annotations

import pytest

from graph.engine import add_edge, add_node
from graph.rules import (
    ADMISSIBLE_WEIGHT,
    AdmissionSweep,
    check_concept_admission,
    concept_weight,
)
from graph.schema import init_db


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "admission.db")
    yield c
    c.close()


def _concept(conn, cid, name="C"):
    add_node(conn, cid, "Concept", {
        "name": name, "description": "x", "artifact_class": "abstracted-mechanism",
        "key_properties": [], "tradeoffs": [], "design_rationale": "n/a"})
    return cid


def _paper(conn, n):
    add_node(conn, f"src-{n}", "Source", {
        "url": f"https://example.com/{n}", "source_type": "paper",
        "license": "MIT", "title": f"Paper {n}"})
    add_node(conn, f"ev-{n}", "Evidence", {
        "artifact_class": "A", "contamination_level": "L0", "text": "body"})
    add_edge(conn, "sourced-from", f"ev-{n}", f"src-{n}")
    return f"ev-{n}"


def _link(conn, cid, eid):
    add_edge(conn, "extracted-from", cid, eid)


# --- weight -----------------------------------------------------------------


def test_weight_counts_distinct_sources_not_distinct_evidence(conn):
    """The invariant says so in capitals, and the distinction is the whole
    rule: two Evidence nodes from one paper are one paper. A concept cited
    twice by the same author is not an established class."""
    cid = _concept(conn, "c-1")
    add_node(conn, "src-a", "Source", {
        "url": "https://example.com/a", "source_type": "paper",
        "license": "MIT", "title": "One Paper"})
    for ev in ("ev-a1", "ev-a2"):
        add_node(conn, ev, "Evidence", {
            "artifact_class": "A", "contamination_level": "L0", "text": "b"})
        add_edge(conn, "sourced-from", ev, "src-a")
        _link(conn, cid, ev)
    conn.commit()
    assert concept_weight(conn, cid) == 1


def test_weight_rises_with_a_second_paper(conn):
    cid = _concept(conn, "c-1")
    for n in ("1", "2"):
        _link(conn, cid, _paper(conn, n))
    conn.commit()
    assert concept_weight(conn, cid) == ADMISSIBLE_WEIGHT


def test_an_unlinked_concept_weighs_nothing(conn):
    _concept(conn, "c-1")
    conn.commit()
    assert concept_weight(conn, "c-1") == 0


# --- the sweep --------------------------------------------------------------


def test_two_papers_make_a_concept_admissible(conn):
    cid = _concept(conn, "c-1")
    for n in ("1", "2"):
        _link(conn, cid, _paper(conn, n))
    conn.commit()
    sweep = check_concept_admission(conn)
    assert (sweep.admissible, sweep.thin, sweep.unlinked) == (1, [], [])


def test_one_paper_is_thin_and_not_a_violation(conn):
    """THE FINDING, not a detail. Weight is a proxy for "established class" and
    it misfires on a thin corpus — Vmalloc, Dentry Cache and Signal Delivery
    all sat at weight 1 on 2026-09-22 because this corpus holds one paper about
    each, not because one paper invented them. Reporting those as violations
    would measure corpus coverage and call it concept quality."""
    cid = _concept(conn, "c-thin", "Vmalloc")
    _link(conn, cid, _paper(conn, "1"))
    conn.commit()
    sweep = check_concept_admission(conn)
    assert sweep.thin == [cid]
    assert sweep.violations == []
    assert sweep.admissible == 0


def test_no_paper_at_all_is_reported_separately_from_thin(conn):
    """Different states deserve different numbers: 'one paper so far' and
    'nothing points at this' are not the same problem."""
    _concept(conn, "c-none")
    thin = _concept(conn, "c-thin")
    _link(conn, thin, _paper(conn, "1"))
    conn.commit()
    sweep = check_concept_admission(conn)
    assert sweep.unlinked == ["c-none"]
    assert sweep.thin == ["c-thin"]


def test_a_seminal_marker_admits_a_single_source_concept(conn):
    """IFC-KK-CONCEPT-SEMINAL-MARKER, per D-12: a defined-by edge names WHICH
    paper defined the class. Zero such edges existed in the corpus on
    2026-09-22, so this route had never once been exercised."""
    cid = _concept(conn, "c-1")
    eid = _paper(conn, "1")
    _link(conn, cid, eid)
    add_edge(conn, "defined-by", cid, "src-1")
    conn.commit()
    sweep = check_concept_admission(conn)
    assert (sweep.admissible, sweep.seminal) == (1, 1)
    assert sweep.thin == []


def test_the_sweep_accounts_for_every_concept(conn):
    """A census that does not add up is not a census."""
    for i in range(4):
        _concept(conn, f"c-{i}")
    _link(conn, "c-1", _paper(conn, "1"))
    for n in ("2", "3"):
        _link(conn, "c-2", _paper(conn, n))
    conn.commit()
    sweep = check_concept_admission(conn)
    assert sweep.total == 4
    assert sweep.admissible + len(sweep.thin) + len(sweep.unlinked) == 4


def test_the_sweep_is_not_a_per_node_rule(conn):
    """DELIBERATELY outside RULES_BY_KIND. A per-node rule runs on every
    add_node, so a Concept below the weight line would fail writes that have
    nothing to do with this invariant — which is exactly why
    check_link_evidence_recorded sits outside it too."""
    from graph.rules import RULES_BY_KIND
    names = [getattr(f, "__name__", "") for fs in RULES_BY_KIND.values() for f in fs]
    assert "check_concept_admission" not in names


def test_an_empty_graph_sweeps_cleanly(conn):
    sweep = check_concept_admission(conn)
    assert isinstance(sweep, AdmissionSweep)
    assert sweep.total == 0
    assert sweep.violations == []
