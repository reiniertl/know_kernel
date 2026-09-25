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


# --- the third admission route (2026-09-22) ---------------------------------


def _kernel_node(conn, kid, name):
    from graph.engine import add_node
    add_node(conn, kid, "Kernel", {
        "name": name, "description": f"{name}.", "kernel_type": "general-purpose"})


def test_a_concept_in_two_kernels_is_admissible_at_weight_one(conn):
    """The amendment. Zswap and KSM are the real cases: one paper each in this
    corpus, present in several kernels. Weight measures corpus coverage;
    kernel breadth measures curation, which is why it catches what weight
    misses."""
    from graph.engine import add_edge
    from graph.rules import admission_state, concept_weight, seminal_concepts

    cid = _concept(conn, "concept-zswap", "Zswap")
    eid = _paper(conn, "a")
    add_edge(conn, "extracted-from", cid, eid)
    _kernel_node(conn, "k-1", "Linux Mainline")
    _kernel_node(conn, "k-2", "PREEMPT_RT")
    add_edge(conn, "implemented-in", cid, "k-1")
    add_edge(conn, "implemented-in", cid, "k-2")
    conn.commit()

    assert concept_weight(conn, cid) == 1, "still one paper — weight did not move"
    assert admission_state(conn, cid, seminal_concepts(conn)) == "multi-kernel"


def test_one_kernel_is_not_enough(conn):
    """Vmalloc is the case that does NOT benefit: one implemented-in edge, to
    Linux Mainline. The proposal cited it as the motivating example; measuring
    showed the route does not reach it, and the rule must not pretend it does."""
    from graph.engine import add_edge
    from graph.rules import admission_state, seminal_concepts

    cid = _concept(conn, "concept-vmalloc", "Vmalloc")
    eid = _paper(conn, "a")
    add_edge(conn, "extracted-from", cid, eid)
    _kernel_node(conn, "k-1", "Linux Mainline")
    add_edge(conn, "implemented-in", cid, "k-1")
    conn.commit()

    assert admission_state(conn, cid, seminal_concepts(conn)) == "thin"


def test_kernel_breadth_counts_distinct_kernels_not_edges(conn):
    from graph.engine import add_edge
    from graph.rules import kernel_breadth

    cid = _concept(conn, "concept-1", "X")
    _kernel_node(conn, "k-1", "Linux Mainline")
    add_edge(conn, "implemented-in", cid, "k-1")
    conn.commit()
    assert kernel_breadth(conn, cid) == 1


def test_a_concept_already_admissible_on_papers_keeps_that_label(conn):
    """The third route is checked AFTER weight, so a concept clearing the paper
    bar is not relabelled. The states have to stay comparable across the
    amendment or the census before/after means nothing."""
    from graph.engine import add_edge
    from graph.rules import admission_state, seminal_concepts

    cid = _concept(conn, "concept-1", "X")
    for n in ("a", "b"):
        add_edge(conn, "extracted-from", cid, _paper(conn, n))
    _kernel_node(conn, "k-1", "Linux Mainline")
    _kernel_node(conn, "k-2", "PREEMPT_RT")
    add_edge(conn, "implemented-in", cid, "k-1")
    add_edge(conn, "implemented-in", cid, "k-2")
    conn.commit()
    assert admission_state(conn, cid, seminal_concepts(conn)) == "admissible"


def test_the_sweep_counts_multi_kernel_as_admissible(conn):
    from graph.engine import add_edge
    from graph.rules import check_concept_admission

    cid = _concept(conn, "concept-1", "X")
    add_edge(conn, "extracted-from", cid, _paper(conn, "a"))
    _kernel_node(conn, "k-1", "Linux Mainline")
    _kernel_node(conn, "k-2", "PREEMPT_RT")
    add_edge(conn, "implemented-in", cid, "k-1")
    add_edge(conn, "implemented-in", cid, "k-2")
    conn.commit()

    s = check_concept_admission(conn)
    assert s.admissible == 1
    assert s.thin == [] and s.unlinked == []


# --- the fourth route, 2026-09-25: canonical documentation ------------------
#
# Operator decision. A paper PROPOSES; canonical documentation DEFINES, and
# only the second admits a Concept at weight 1. The evidence for the
# distinction is the candidate queue: of 43 names papers proposed, roughly six
# are established classes.


def _doc(conn, n, source_type="kernel-doc"):
    """A canonical-documentation Source and its Evidence."""
    add_node(conn, f"src-doc{n}", "Source", {
        "url": f"https://git.kernel.org/.../tree/Documentation/{n}.rst",
        "source_type": source_type, "license": "GPL-2.0", "title": f"Doc {n}"})
    add_node(conn, f"ev-doc{n}", "Evidence", {
        "artifact_class": "A", "contamination_level": "L0", "text": "body"})
    add_edge(conn, "sourced-from", f"ev-doc{n}", f"src-doc{n}")
    return f"ev-doc{n}"


def _curation(conn, cid, state, **extra):
    import json as _json
    row = conn.execute("SELECT attrs FROM nodes WHERE id = ?", (cid,)).fetchone()
    attrs = {**_json.loads(row[0]), "curation_state": state, **extra}
    conn.execute("UPDATE nodes SET attrs = ? WHERE id = ?",
                 (_json.dumps(attrs), cid))


def test_one_document_admits_a_concept_that_one_paper_would_not(conn):
    """THE PAIR THAT CARRIES THE WHOLE REVERSAL. Identical weight, identical
    shape, different kind of witness — and the states must differ or the
    distinction means nothing."""
    from graph.rules import admission_state, documented_concepts, seminal_concepts

    documented_cid = _concept(conn, "c-doc")
    _link(conn, documented_cid, _doc(conn, "workqueue"))
    paper_cid = _concept(conn, "c-paper")
    _link(conn, paper_cid, _paper(conn, "1"))
    conn.commit()

    assert concept_weight(conn, documented_cid) == 1
    assert concept_weight(conn, paper_cid) == 1
    seminal = seminal_concepts(conn)
    docs = documented_concepts(conn)
    assert admission_state(conn, documented_cid, seminal, docs) == "documented"
    assert admission_state(conn, paper_cid, seminal, docs) == "thin"


def test_two_documents_needed_no_new_route_at_all(conn):
    """Checked BEFORE the fourth route was added. concept_weight counts
    DISTINCT Sources with no source_type filter, so two docs already reached
    weight 2. The fourth route exists solely for the one-document case."""
    from graph.rules import admission_state, seminal_concepts

    cid = _concept(conn, "c-1")
    for name in ("workqueue", "cgroup-v2"):
        _link(conn, cid, _doc(conn, name))
    conn.commit()
    assert concept_weight(conn, cid) == ADMISSIBLE_WEIGHT
    assert admission_state(conn, cid, seminal_concepts(conn)) == "admissible"


def test_a_documented_concept_at_weight_two_still_reads_admissible(conn):
    """The routes are ordered so a Concept clearing an earlier bar keeps
    reporting the earlier state. The census must stay comparable across every
    amendment, or 'admissible: 69' means something different each week."""
    from graph.rules import admission_state, seminal_concepts

    cid = _concept(conn, "c-1")
    _link(conn, cid, _doc(conn, "workqueue"))
    _link(conn, cid, _paper(conn, "1"))
    conn.commit()
    assert admission_state(conn, cid, seminal_concepts(conn)) == "admissible"


def test_only_the_declared_source_types_are_canonical_documentation(conn):
    """IFC-KK-DOC-DEFINED-PROVENANCE. The set is small and closed: every type
    in it is a witness granted the power to admit at weight 1."""
    from graph.rules import DOC_SOURCE_TYPES, documented_concepts

    assert DOC_SOURCE_TYPES == ("kernel-doc",)
    for excluded in ("preprint", "conference-paper", "vulnerability-database",
                     "article", "discourse"):
        assert excluded not in DOC_SOURCE_TYPES

    cid = _concept(conn, "c-cve")
    _link(conn, cid, _doc(conn, "cve", source_type="vulnerability-database"))
    conn.commit()
    assert documented_concepts(conn) == set(), (
        "a CVE record is authoritative about an instance and silent about "
        "whether the mechanism it names is an established class")


def test_documented_concepts_counts_concepts_and_not_every_node_kind(conn):
    """THE TRAP THAT PRODUCED A WRONG NUMBER TWICE. Without the kind filter
    this join returns 153 against a corpus of 97 — PerformanceProfile 50,
    KernelInvariant 46, FailureMode 45, InteractionProtocol 12, all hanging off
    the same doc Evidence."""
    from graph.rules import documented_concepts

    ev = _doc(conn, "workqueue")
    add_node(conn, "pp-1", "PerformanceProfile", {
        "metric": "latency", "complexity": "O(1)", "best_case": "a",
        "worst_case": "b", "typical_case": "c", "conditions": "d",
        "artifact_class": "abstracted-mechanism"})
    add_edge(conn, "extracted-from", "pp-1", ev)
    conn.commit()
    assert documented_concepts(conn) == set()


# --- retired: a state flip, never a delete ---------------------------------


def test_a_retired_concept_is_admissible_under_no_route(conn):
    """Operator decision 2026-09-25. Three papers is ample evidence; a human
    judged the Concept wrong, which outranks all of it."""
    from graph.rules import admission_state, seminal_concepts

    cid = _concept(conn, "c-1")
    for n in ("1", "2", "3"):
        _link(conn, cid, _paper(conn, n))
    _curation(conn, cid, "retired")
    conn.commit()
    assert concept_weight(conn, cid) == 3
    assert admission_state(conn, cid, seminal_concepts(conn)) == "retired"


def test_retirement_outranks_even_the_seminal_marker(conn):
    cid = _concept(conn, "c-1")
    _link(conn, cid, _paper(conn, "1"))
    add_edge(conn, "defined-by", cid, "src-1")
    _curation(conn, cid, "retired")
    conn.commit()
    from graph.rules import admission_state, seminal_concepts
    assert admission_state(conn, cid, seminal_concepts(conn)) == "retired"


def test_retiring_keeps_the_node_and_every_edge(conn):
    """A state flip, never a delete. Papers already linked to the Concept keep
    their links, which is the whole reason the decision went this way."""
    cid = _concept(conn, "c-1")
    _link(conn, cid, _paper(conn, "1"))
    _curation(conn, cid, "retired")
    conn.commit()
    assert conn.execute("SELECT 1 FROM nodes WHERE id = ?", (cid,)).fetchone()
    assert conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind = 'extracted-from' "
        "AND source_id = ?", (cid,)).fetchone()[0] == 1


# --- curation and admission are orthogonal axes ----------------------------


def test_harvested_and_reviewed_reach_the_same_admission_state(conn):
    """BOTH SIDES, WHICH IS THE POINT. Admission measures EVIDENCE; curation
    measures HUMAN ATTENTION. A harvested Concept at weight 2 is as well
    evidenced as a reviewed one at weight 2, and making admission depend on
    review would turn the census into a review-progress bar that collapses to
    near zero after any harvest and says nothing about the vocabulary."""
    from graph.rules import admission_state, seminal_concepts

    harvested = _concept(conn, "c-harvested")
    reviewed = _concept(conn, "c-reviewed")
    for cid, prefix in ((harvested, "h"), (reviewed, "r")):
        for n in (f"{prefix}1", f"{prefix}2"):
            _link(conn, cid, _paper(conn, n))
    _curation(conn, harvested, "harvested", harvest_batch="batch-1")
    _curation(conn, reviewed, "reviewed",
              reviewed_by="curator@example.com", reviewed_at="2026-09-25")
    conn.commit()

    seminal = seminal_concepts(conn)
    assert admission_state(conn, harvested, seminal) == "admissible"
    assert admission_state(conn, reviewed, seminal) == "admissible"


def test_the_sweep_counts_documented_inside_admissible_and_lists_it(conn):
    """Counted inside admissible so the headline number stays one number, and
    listed separately so the harvest's contribution stays attributable rather
    than merged into a total that was already 69."""
    doc_cid = _concept(conn, "c-doc")
    _link(conn, doc_cid, _doc(conn, "workqueue"))
    heavy = _concept(conn, "c-heavy")
    for n in ("1", "2"):
        _link(conn, heavy, _paper(conn, n))
    thin_cid = _concept(conn, "c-thin")
    _link(conn, thin_cid, _paper(conn, "3"))
    gone = _concept(conn, "c-gone")
    _curation(conn, gone, "retired")
    conn.commit()

    sweep = check_concept_admission(conn)
    assert sweep.admissible == 2, "the documented one and the weight-2 one"
    assert sweep.documented == ["c-doc"]
    assert sweep.thin == ["c-thin"]
    assert sweep.retired == ["c-gone"]
    assert sweep.unlinked == []
    assert sweep.total == 4


def test_the_measured_census_of_the_live_corpus_does_not_move(conn):
    """The zero is the point. Measured 2026-09-25 against data/master.db:
    69 admissible, 11 thin, 17 unlinked, 0 seminal of 97 — and ZERO Concepts
    reach a kernel-doc Source, so the fourth route changes nothing today. This
    fixture reproduces that shape in miniature: adding the route must not move
    a corpus that has no doc-linked Concepts in it."""
    heavy = _concept(conn, "c-heavy")
    for n in ("1", "2"):
        _link(conn, heavy, _paper(conn, n))
    thin_cid = _concept(conn, "c-thin")
    _link(conn, thin_cid, _paper(conn, "3"))
    _concept(conn, "c-orphan")
    conn.commit()

    sweep = check_concept_admission(conn)
    assert (sweep.admissible, sweep.thin, sweep.unlinked) == (
        1, ["c-thin"], ["c-orphan"])
    assert sweep.documented == [] and sweep.retired == []
