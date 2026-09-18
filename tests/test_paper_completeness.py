"""Tests for ingest.paper_completeness — IFC-KK-PAPER-COMPLETENESS.

Covers ALG-KK-COMPLETENESS-COMPUTE, INV-KK-COMPLETENESS-ADVISORY and
INV-KK-COMPLETENESS-STALENESS-TOLERATED, plus the batch pass in
data/recompute_completeness.py.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

from graph.engine import add_edge, add_node, update_node_attrs
from graph.schema import init_db
from ingest.paper_completeness import (
    BINARY_DIMENSIONS,
    PAPER_SOURCE_TYPES,
    compute_completeness,
    get_verdict,
    recompute_paper,
    recompute_paper_if_present,
)
from ingest.paper_summary import SUMMARY_STATES, set_summary


def _load_batch_module():
    path = pathlib.Path(__file__).resolve().parents[1] / "data" / "recompute_completeness.py"
    spec = importlib.util.spec_from_file_location("recompute_completeness", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["recompute_completeness"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "completeness_test.db")
    yield c
    c.close()


def _paper(c, source_id="src-1", abstract=None, source_type="preprint"):
    """A paper Source with NO Advisory — what most real Sources look like."""
    attrs = {
        "url": f"https://example.com/{source_id}.pdf",
        "source_type": source_type,
        "license": "MIT",
        "title": f"Paper {source_id}",
    }
    if abstract:
        attrs["abstract"] = abstract
    add_node(c, source_id, "Source", attrs)
    return source_id


def _concept(c, source_id, concept_id="c1", evidence_id="ev1"):
    """Attach a Concept to a paper through the two-hop Evidence chain."""
    add_node(c, evidence_id, "Evidence", {"artifact_class": "A", "contamination_level": "L0"})
    add_node(c, concept_id, "Concept", {
        "name": "RCU", "description": "read-copy-update", "artifact_class": "B",
        "key_properties": [], "tradeoffs": [], "design_rationale": "r",
    })
    add_edge(c, "sourced-from", evidence_id, source_id)
    add_edge(c, "extracted-from", concept_id, evidence_id)
    return concept_id


# --- each dimension, independently ---------------------------------------


def test_paper_with_nothing_scores_all_false(conn):
    src = _paper(conn)
    v = compute_completeness(conn, src)
    assert v.dimensions == dict.fromkeys(BINARY_DIMENSIONS, False)
    assert v.summary_state == "absent"


def test_abstract_alone(conn):
    src = _paper(conn, abstract="We present a scheduler.")
    v = compute_completeness(conn, src)
    assert v.has_abstract is True
    assert v.links_concept is False
    assert v.links_subsystem is False


def test_whitespace_only_abstract_is_not_an_abstract(conn):
    src = _paper(conn, abstract="   \n  ")
    assert compute_completeness(conn, src).has_abstract is False


def test_concepts_without_an_abstract(conn):
    src = _paper(conn)
    _concept(conn, src)
    v = compute_completeness(conn, src)
    assert v.links_concept is True
    assert v.has_abstract is False
    # The Concept has no belongs-to yet, so the redundancy does not hold here.
    assert v.links_subsystem is False


def test_subsystem_is_a_third_hop_off_the_concept(conn):
    src = _paper(conn)
    cid = _concept(conn, src)
    assert compute_completeness(conn, src).links_subsystem is False

    add_node(conn, "sub1", "Subsystem", {"name": "scheduler"})
    add_edge(conn, "belongs-to", cid, "sub1")
    assert compute_completeness(conn, src).links_subsystem is True


def test_kernel_is_a_separate_third_hop(conn):
    """D-7 kept links_kernel distinct from links_subsystem; they move independently."""
    src = _paper(conn)
    cid = _concept(conn, src)
    add_node(conn, "sub1", "Subsystem", {"name": "scheduler"})
    add_edge(conn, "belongs-to", cid, "sub1")

    v = compute_completeness(conn, src)
    assert v.links_subsystem is True
    assert v.links_kernel is False

    add_node(conn, "kernel-1", "Kernel", {
        "name": "Linux Mainline", "description": "d", "kernel_type": "mainline",
    })
    add_edge(conn, "implemented-in", cid, "kernel-1")
    assert compute_completeness(conn, src).links_kernel is True


def test_invariant_hangs_off_evidence_not_off_a_concept(conn):
    src = _paper(conn)
    add_node(conn, "ev1", "Evidence", {"artifact_class": "A", "contamination_level": "L0"})
    add_edge(conn, "sourced-from", "ev1", src)
    assert compute_completeness(conn, src).links_invariant is False

    add_node(conn, "kinv-1", "KernelInvariant", {
        "predicate": "p", "strength": "strong", "scope": "s", "artifact_class": "B",
    })
    add_edge(conn, "extracted-from", "kinv-1", "ev1")
    v = compute_completeness(conn, src)
    assert v.links_invariant is True
    assert v.links_concept is False


@pytest.mark.parametrize("state", SUMMARY_STATES)
def test_summary_in_each_declared_state(conn, state):
    """has_summary follows the D-E presence test; summary_state carries the raw value."""
    src = _paper(conn)
    text = "" if state == "absent" else "A summary."
    reviewer = "rvr-1" if state in ("human-reviewed", "human-authored") else ""
    set_summary(conn, src, text, state, reviewed_by=reviewer)

    v = compute_completeness(conn, src)
    assert v.summary_state == state
    assert v.has_summary is (state in ("llm-extracted", "human-reviewed", "human-authored"))


def test_rejected_ranks_with_absent_not_above_it(conn):
    src = _paper(conn)
    set_summary(conn, src, "Bad summary.", "rejected")
    v = compute_completeness(conn, src)
    assert v.summary_state == "rejected"
    assert v.has_summary is False


# --- what counts as a paper ----------------------------------------------


@pytest.mark.parametrize("source_type", PAPER_SOURCE_TYPES)
def test_every_paper_type_gets_a_verdict(conn, source_type):
    src = _paper(conn, f"src-{source_type}", source_type=source_type)
    assert compute_completeness(conn, src).source_id == src


def test_non_paper_sources_get_no_verdict(conn):
    src = _paper(conn, "src-news", source_type="media-outlet")
    with pytest.raises(ValueError, match="is not a paper"):
        compute_completeness(conn, src)
    # ...and the best-effort wrapper stays silent rather than raising.
    recompute_paper_if_present(conn, src)
    assert get_verdict(conn, src) is None


def test_unknown_id_raises(conn):
    with pytest.raises(ValueError, match="does not exist"):
        compute_completeness(conn, "src-nope")


# --- persistence, staleness, idempotence ---------------------------------


def test_recompute_persists_a_node_and_an_edge(conn):
    src = _paper(conn, abstract="Text.")
    v = recompute_paper(conn, src)
    assert v.created is True
    assert v.verdict_id.startswith("pcomp-")

    node = get_verdict(conn, src)
    assert node["kind"] == "PaperCompleteness"
    assert node["attrs"]["has_abstract"] is True
    edges = conn.execute(
        "SELECT source_id, target_id FROM edges WHERE kind = 'completeness-of'"
    ).fetchall()
    assert edges == [(v.verdict_id, src)]


def test_computation_time_is_recorded(conn):
    """INV-KK-COMPLETENESS-STALENESS-TOLERATED: readers need to see the age."""
    import datetime

    src = _paper(conn)
    assert get_verdict(conn, src) is None
    v = recompute_paper(conn, src)
    assert v.computed_at == datetime.date.today().isoformat()
    assert get_verdict(conn, src)["attrs"]["computed_at"] == v.computed_at


def test_recompute_replaces_rather_than_accumulates(conn):
    src = _paper(conn)
    first = recompute_paper(conn, src)
    add_node(conn, "x", "Subsystem", {"name": "s"})  # unrelated change
    second = recompute_paper(conn, src)

    assert second.created is False
    assert second.verdict_id == first.verdict_id
    assert conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind = 'PaperCompleteness'"
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind = 'completeness-of'"
    ).fetchone()[0] == 1


def test_verdict_follows_the_graph_when_recomputed(conn):
    src = _paper(conn)
    assert recompute_paper(conn, src).links_concept is False
    _concept(conn, src)
    assert recompute_paper(conn, src).links_concept is True


def test_a_stale_verdict_is_not_an_error(conn):
    """The graph may move under a verdict; nothing detects or repairs that."""
    src = _paper(conn)
    recompute_paper(conn, src)
    _concept(conn, src)  # graph now disagrees with the stored verdict

    stored = get_verdict(conn, src)
    assert stored["attrs"]["links_concept"] is False
    assert compute_completeness(conn, src).links_concept is True
    # Reading the stale verdict raises nothing and repairs nothing.
    assert get_verdict(conn, src)["attrs"]["links_concept"] is False


# --- INV-KK-COMPLETENESS-ADVISORY ----------------------------------------


def test_an_all_false_verdict_blocks_no_write(conn):
    """The verdict is informational: nothing branches on it to refuse an action."""
    src = _paper(conn)
    v = recompute_paper(conn, src)
    assert not any(v.dimensions.values())

    # Every public write path still accepts this paper.
    from ingest.source_abstract import set_abstract

    assert set_abstract(conn, src, "Now it has one.", "manual", recompute=True).abstract
    assert set_summary(conn, src, "A summary.", "llm-extracted", recompute=True).ok
    _concept(conn, src)
    assert recompute_paper(conn, src).has_abstract is True


def test_recompute_failure_never_fails_the_edit_that_triggered_it(conn):
    """A non-paper Source still accepts an abstract with recompute requested."""
    from ingest.source_abstract import set_abstract

    src = _paper(conn, "src-doc", source_type="kernel-doc")
    result = set_abstract(conn, src, "Documentation text.", "manual", recompute=True)
    assert result.abstract == "Documentation text."
    assert get_verdict(conn, src) is None


def test_write_points_do_not_recompute_by_default(conn):
    """Bulk callers must not pay a verdict write per row."""
    from ingest.source_abstract import set_abstract

    src = _paper(conn)
    set_abstract(conn, src, "Fetched in bulk.", "arxiv")
    assert get_verdict(conn, src) is None

    set_summary(conn, src, "A summary.", "llm-extracted")
    assert get_verdict(conn, src) is None


def test_web_editor_does_recompute(conn):
    from ingest.source_abstract import set_abstract

    src = _paper(conn)
    set_abstract(conn, src, "Typed by a human.", "manual", recompute=True)
    assert get_verdict(conn, src)["attrs"]["has_abstract"] is True


# --- the batch pass -------------------------------------------------------


def test_batch_is_idempotent_and_reports_zero_changes_on_a_second_run(conn):
    batch = _load_batch_module()
    _paper(conn, "src-a", abstract="A.")
    _paper(conn, "src-b")
    _paper(conn, "src-news", source_type="media-outlet")  # not a paper

    first = batch.recompute_all(conn)
    assert first["papers"] == 2
    assert first["verdicts_created"] == 2
    assert first["verdicts_changed"] == 0

    second = batch.recompute_all(conn)
    assert second["papers"] == 2
    assert second["verdicts_created"] == 0
    assert second["verdicts_changed"] == 0
    assert second["verdicts_unchanged"] == 2

    assert conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind = 'PaperCompleteness'"
    ).fetchone()[0] == 2


def test_batch_notices_a_real_change(conn):
    batch = _load_batch_module()
    src = _paper(conn, "src-a")
    batch.recompute_all(conn)
    _concept(conn, src)

    stats = batch.recompute_all(conn)
    assert stats["verdicts_changed"] == 1
    assert stats["dimensions"]["links_concept"] == 1


def test_batch_dry_run_writes_nothing(conn):
    batch = _load_batch_module()
    _paper(conn, "src-a", abstract="A.")
    stats = batch.recompute_all(conn, dry_run=True)
    assert stats["papers"] == 1
    assert stats["dimensions"]["has_abstract"] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind = 'PaperCompleteness'"
    ).fetchone()[0] == 0


def test_batch_skips_non_papers(conn):
    batch = _load_batch_module()
    _paper(conn, "src-news", source_type="media-outlet")
    assert batch.recompute_all(conn)["papers"] == 0


# ---------------------------------------------------------------------------
# title_verified — the seventh dimension (2026-09-18).
#
# It records that the title WAS CHECKED against the document its identifier
# resolves to. It does not record that the paper is coherent, and these tests
# exist partly to keep that distinction from eroding: the temptation to read a
# green tick as "this record is correct" is exactly what let 516 displaced
# titles sit in a corpus that reported itself complete.
# ---------------------------------------------------------------------------


def test_title_verified_is_false_when_nothing_has_checked(conn):
    """The default. False means no check happened, never that the title is wrong."""
    sid = _paper(conn)
    assert compute_completeness(conn, sid).title_verified is False


def test_title_verified_is_true_once_a_reconciliation_has_stamped_it(conn):
    sid = _paper(conn)
    update_node_attrs(conn, sid, {"title_reconciled_at": "2026-09-18"})
    assert compute_completeness(conn, sid).title_verified is True


def test_title_verified_is_binary(conn):
    """Decision D-A: dimensions are present-or-not. A confidence score would
    report certainty the measurement does not support."""
    sid = _paper(conn)
    update_node_attrs(conn, sid, {"title_reconciled_at": "2026-09-18"})
    value = compute_completeness(conn, sid).title_verified
    assert value is True or value is False
    assert isinstance(value, bool)


def test_title_verified_says_nothing_about_the_other_dimensions(conn):
    """A record can be checked and still empty, or complete and unchecked. The
    dimension is independent of the six that measure presence."""
    checked_but_empty = _paper(conn, "src-checked")
    update_node_attrs(conn, checked_but_empty, {"title_reconciled_at": "2026-09-18"})
    v = compute_completeness(conn, checked_but_empty)
    assert v.title_verified is True
    assert v.has_abstract is False and v.has_summary is False

    full_but_unchecked = _paper(conn, "src-full", abstract="A real abstract here.")
    v2 = compute_completeness(conn, full_but_unchecked)
    assert v2.has_abstract is True
    assert v2.title_verified is False


def test_title_verified_gates_nothing(conn):
    """INV-KK-COMPLETENESS-ADVISORY. The verdict is informational; an unchecked
    or incoherent paper is described, never withheld."""
    sid = _paper(conn, abstract="A real abstract here.")
    verdict = compute_completeness(conn, sid)
    assert verdict.title_verified is False
    # Computing it neither raises nor suppresses anything else.
    assert verdict.has_abstract is True
    assert verdict.source_id == sid


def test_title_verified_is_in_the_declared_dimension_tuple():
    """The tuple is what IFC-KK-PAPER-COMPLETENESS declares and what the web
    labels iterate; a dimension missing from it would compute and never show."""
    assert "title_verified" in BINARY_DIMENSIONS
    assert len(BINARY_DIMENSIONS) == 7
