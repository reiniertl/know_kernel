"""Merging two Concepts: the verb the vocabulary never had.

WHY A MERGE AND NOT A RETIREMENT. Measured 2026-09-28: 41 Concepts collide in
25 pairs and TWENTY of those pairs carry papers on both sides. "NUMA Memory
Policy" holds 1 paper and sits beside "NUMA Topology and Memory Policy" holding
72 — the same mechanism under two names. Retiring the small one keeps its edge,
so its paper stays attached to something no page will ever surface again. That
is a withdrawal wearing the word merge, and it strands evidence.

THE TWO FACTS THAT SHAPE EVERY TEST BELOW, both measured on the live corpus:
a Concept carries EIGHT outbound edge kinds and is the TARGET of SIXTEEN more,
so an outbound-only merge strands 148 discusses edges; and SIXTEEN of the 25
pairs already share at least one neighbour, so the UNIQUE (kind, source_id,
target_id) collision is the common case, not the corner.
"""

from __future__ import annotations

import pytest

from graph.concept_vocabulary import (
    build_vocabulary_context,
    colliding_concepts,
    colliding_pairs,
    curation_state,
    merge_concepts,
)
from graph.engine import add_edge, add_node, get_node
from graph.rules import concept_weight
from graph.schema import init_db

SIX = {
    "description": "d", "artifact_class": "abstracted-mechanism",
    "key_properties": [], "tradeoffs": [], "design_rationale": "r",
}


def _concept(conn, cid, name, **extra):
    add_node(conn, cid, "Concept", {**SIX, "name": name, **extra})
    return cid


def _paper(conn, n, *concept_ids):
    """One Source, one Evidence, and an extracted-from edge from each Concept."""
    add_node(conn, f"src-{n}", "Source", {
        "url": f"https://example.com/{n}", "source_type": "preprint",
        "license": "MIT", "title": f"Paper {n}"})
    add_node(conn, f"ev-{n}", "Evidence", {
        "artifact_class": "A", "contamination_level": "L0", "text": "t"})
    add_edge(conn, "sourced-from", f"ev-{n}", f"src-{n}")
    for cid in concept_ids:
        add_edge(conn, "extracted-from", cid, f"ev-{n}")


def _subsystem(conn, sid, name):
    add_node(conn, sid, "Subsystem", {"name": name})
    return sid


def _kernel(conn, kid, name):
    add_node(conn, kid, "Kernel", {
        "name": name, "description": "d", "kernel_type": "monolithic"})
    return kid


def _discussion(conn, did, cid):
    """The INBOUND half — the 148 edges an outbound-only merge would strand."""
    add_node(conn, did, "Discussion", {
        "title": "t", "forum": "lkml", "participant_count": 3,
        "source_date": "2026-01-01", "artifact_class": "discourse"})
    add_edge(conn, "discusses", did, cid)
    return did


def _supersedes(conn, winner, loser):
    return conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'supersedes' AND source_id = ? "
        "AND target_id = ?", (winner, loser)).fetchone() is not None


def _incident(conn, cid, exclude_supersedes=True):
    sql = ("SELECT kind, source_id, target_id FROM edges "
           "WHERE source_id = ? OR target_id = ?")
    rows = conn.execute(sql, (cid, cid)).fetchall()
    if exclude_supersedes:
        rows = [r for r in rows if r[0] != "supersedes"]
    return rows


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "merge.db")
    yield c
    c.close()


# --- the evidence moves (INV-KK-CONCEPT-MERGE-PRESERVES) --------------------


def test_the_papers_move_to_the_winner(conn):
    """The NUMA case: 1 paper beside 72. Retiring strands it; merging moves it."""
    win = _concept(conn, "concept-win", "NUMA Topology and Memory Policy")
    lose = _concept(conn, "concept-lose", "NUMA Memory Policy")
    _paper(conn, "1", win)
    _paper(conn, "2", win)
    _paper(conn, "3", lose)
    conn.commit()

    result = merge_concepts(conn, lose, win, reviewed_by="reinier")

    assert result.ok
    assert result.weight_before == 2
    assert result.weight_after == 3
    assert concept_weight(conn, lose) == 0
    assert result.moved == 1
    assert result.dropped == 0


def test_every_outbound_kind_moves_not_just_extracted_from(conn):
    """The request named three kinds. A Concept carries eight."""
    win = _concept(conn, "concept-win", "Slab Allocator")
    lose = _concept(conn, "concept-lose", "Slab Allocation")
    other = _concept(conn, "concept-other", "Page Allocator")
    sub = _subsystem(conn, "sub-mm", "mm")
    ker = _kernel(conn, "kernel-linux", "Linux")
    _paper(conn, "1", lose)
    add_edge(conn, "belongs-to", lose, sub)
    add_edge(conn, "implemented-in", lose, ker)
    add_edge(conn, "prerequisite", lose, other)
    add_edge(conn, "refines", lose, other)
    conn.commit()

    result = merge_concepts(conn, lose, win, reviewed_by="reinier")

    assert result.moved == 5
    assert result.dropped == 0
    kinds = {k for k, s, t in _incident(conn, win)}
    assert kinds == {"extracted-from", "belongs-to", "implemented-in",
                     "prerequisite", "refines"}
    assert _incident(conn, lose) == []


def test_inbound_edges_move_too(conn):
    """THE HALF THE REQUEST DID NOT NAME. 148 discusses, 122 observes and 74
    governed-by edges point AT a Concept. Leaving them is the stranding this
    whole change exists to end."""
    win = _concept(conn, "concept-win", "Futex")
    lose = _concept(conn, "concept-lose", "Futexes")
    other = _concept(conn, "concept-other", "Mutex")
    _discussion(conn, "disc-1", lose)
    _discussion(conn, "disc-2", lose)
    add_edge(conn, "prerequisite", other, lose)
    conn.commit()

    result = merge_concepts(conn, lose, win, reviewed_by="reinier")

    assert result.moved == 3
    assert _incident(conn, lose) == []
    assert conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind = 'discusses' AND target_id = ?",
        (win,)).fetchone()[0] == 2


# --- the UNIQUE constraint, which fires on 64% of the real pairs ------------


def test_two_concepts_sharing_an_evidence_do_not_raise(conn):
    """A plain UPDATE raises IntegrityError here, and this is what a duplicate
    pair LOOKS like — 16 of the 25 measured pairs share a neighbour."""
    win = _concept(conn, "concept-win", "Robust Futex")
    lose = _concept(conn, "concept-lose", "Robust Futexes")
    _paper(conn, "1", win, lose)
    conn.commit()

    result = merge_concepts(conn, lose, win, reviewed_by="reinier")

    assert result.moved == 0
    assert result.dropped == 1
    assert result.weight_before == 1
    assert result.weight_after == 1


def test_the_winners_attrs_survive_a_collision(conn):
    """Operator decision 2026-09-28: the winner is canonical. The loser's
    verdict describes a name being withdrawn."""
    win = _concept(conn, "concept-win", "Grace Period")
    lose = _concept(conn, "concept-lose", "Grace Periods")
    _paper(conn, "1", win)
    add_edge(conn, "extracted-from", lose, "ev-1")
    conn.execute(
        "UPDATE edges SET attrs = ? WHERE source_id = ? AND target_id = ?",
        ('{"basis": "evidence-text", "verdict": "keep"}', win, "ev-1"))
    conn.execute(
        "UPDATE edges SET attrs = ? WHERE source_id = ? AND target_id = ?",
        ('{"basis": "unverified-legacy"}', lose, "ev-1"))
    conn.commit()

    merge_concepts(conn, lose, win, reviewed_by="reinier")

    attrs = conn.execute(
        "SELECT attrs FROM edges WHERE kind = 'extracted-from' AND source_id = ? "
        "AND target_id = ?", (win, "ev-1")).fetchone()[0]
    assert "evidence-text" in attrs
    assert "unverified-legacy" not in attrs


def test_the_weight_is_the_union_and_not_the_sum(conn):
    """A test asserting the sum would be asserting a bug."""
    win = _concept(conn, "concept-win", "Page Cache")
    lose = _concept(conn, "concept-lose", "Page Caching")
    _paper(conn, "1", win, lose)   # shared
    _paper(conn, "2", win)
    _paper(conn, "3", lose)
    conn.commit()

    result = merge_concepts(conn, lose, win, reviewed_by="reinier")

    assert result.weight_before == 2
    assert result.weight_after == 3          # union, not 2 + 2
    assert result.moved + result.dropped == 2


def test_moved_plus_dropped_accounts_for_every_edge_the_loser_had(conn):
    """A merge that silently halves a concept's evidence is the failure this
    counting exists to catch."""
    win = _concept(conn, "concept-win", "Huge Page")
    lose = _concept(conn, "concept-lose", "Huge Pages")
    sub = _subsystem(conn, "sub-mm", "mm")
    _paper(conn, "1", win, lose)
    _paper(conn, "2", lose)
    add_edge(conn, "belongs-to", lose, sub)
    _discussion(conn, "disc-1", lose)
    before = len(_incident(conn, lose))
    conn.commit()

    result = merge_concepts(conn, lose, win, reviewed_by="reinier")

    assert before == 4
    assert result.moved + result.dropped == before
    assert _incident(conn, lose) == []


# --- the self-loop, which no pair needs today and every pair might ----------


def test_an_edge_between_the_pair_is_dropped_not_looped(conn):
    """prerequisite, refines and alternative-to run Concept to Concept. Zero of
    the 25 pairs are in this position today, which is why it is handled now."""
    win = _concept(conn, "concept-win", "RCU")
    lose = _concept(conn, "concept-lose", "RCU Grace Period")
    add_edge(conn, "prerequisite", lose, win)
    add_edge(conn, "refines", win, lose)
    conn.commit()

    result = merge_concepts(conn, lose, win, reviewed_by="reinier")

    assert result.moved == 0
    assert result.dropped == 2
    loops = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE source_id = target_id").fetchone()[0]
    assert loops == 0


# --- the loser: retired, named, and superseded ------------------------------


def test_the_loser_is_retired_and_never_deleted(conn):
    """"Why is there no Robust Futexes any more" has an answer here and none
    under a delete."""
    win = _concept(conn, "concept-win", "Lockdep-RCU")
    lose = _concept(conn, "concept-lose", "Lockdep Checking for RCU")
    conn.commit()

    merge_concepts(conn, lose, win, reviewed_by="reinier", reviewed_at="2026-09-28")

    node = get_node(conn, lose)
    assert node is not None
    assert node["attrs"]["name"] == "Lockdep Checking for RCU"
    assert curation_state(node["attrs"]) == "retired"
    assert node["attrs"]["reviewed_by"] == "reinier"
    assert node["attrs"]["reviewed_at"] == "2026-09-28"


def test_one_supersedes_edge_tells_the_two_retirements_apart(conn):
    """The reason 'retired' can mean two shapes without a fourth state word:
    merged-away carries an inbound supersedes edge, judged-wrong does not."""
    win = _concept(conn, "concept-win", "Zswap")
    lose = _concept(conn, "concept-lose", "Zswap Compression")
    conn.commit()

    merge_concepts(conn, lose, win, reviewed_by="reinier")

    assert _supersedes(conn, win, lose)
    assert _incident(conn, lose) == []           # nothing else survives
    assert len(_incident(conn, lose, exclude_supersedes=False)) == 1


def test_the_loser_leaves_the_vocabulary(conn):
    """The one that matters most: after a merge the loser's name appears in NO
    vocabulary context offered to any extractor. A merge that left the name in
    front of the model would re-mint the duplicate on the next harvest."""
    win = _concept(conn, "concept-win", "Transparent Huge Pages")
    lose = _concept(conn, "concept-lose", "Transparent Huge Page Support")
    conn.commit()

    merge_concepts(conn, lose, win, reviewed_by="reinier")

    ctx = build_vocabulary_context(conn)
    assert "Transparent Huge Pages" in ctx
    assert "Transparent Huge Page Support" not in ctx


# --- refusals and idempotence ----------------------------------------------


def test_a_self_merge_is_refused(conn):
    _concept(conn, "concept-1", "Folio")
    conn.commit()
    with pytest.raises(ValueError, match="itself"):
        merge_concepts(conn, "concept-1", "concept-1", reviewed_by="reinier")


def test_an_unknown_id_is_refused_on_either_side(conn):
    _concept(conn, "concept-1", "Folio")
    conn.commit()
    with pytest.raises(ValueError, match="No Concept"):
        merge_concepts(conn, "concept-nope", "concept-1", reviewed_by="reinier")
    with pytest.raises(ValueError, match="No Concept"):
        merge_concepts(conn, "concept-1", "concept-nope", reviewed_by="reinier")


def test_a_non_concept_id_is_refused(conn):
    """A Subsystem id is a plausible typo and must not be merged into anything."""
    _concept(conn, "concept-1", "Folio")
    _subsystem(conn, "sub-mm", "mm")
    conn.commit()
    with pytest.raises(ValueError, match="No Concept"):
        merge_concepts(conn, "sub-mm", "concept-1", reviewed_by="reinier")


def test_an_unsigned_merge_is_refused(conn):
    """A merge nobody signed is not a curation decision."""
    _concept(conn, "concept-win", "Folio")
    _concept(conn, "concept-lose", "Folios")
    conn.commit()
    with pytest.raises(ValueError, match="name the human"):
        merge_concepts(conn, "concept-lose", "concept-win", reviewed_by="")


def test_a_second_identical_call_is_a_no_op_reporting_zero(conn):
    """Idempotence comes from the supersedes edge, not from the loser
    vanishing the way merge_venues' does."""
    win = _concept(conn, "concept-win", "io_uring")
    lose = _concept(conn, "concept-lose", "io_uring Asynchronous I/O")
    _paper(conn, "1", lose)
    conn.commit()

    first = merge_concepts(conn, lose, win, reviewed_by="reinier")
    second = merge_concepts(conn, lose, win, reviewed_by="reinier")

    assert first.moved == 1
    assert second.moved == 0 and second.dropped == 0
    assert second.weight_before == second.weight_after == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind = 'supersedes'").fetchone()[0] == 1


def test_a_refused_merge_writes_nothing(conn):
    win = _concept(conn, "concept-win", "Folio")
    lose = _concept(conn, "concept-lose", "Folios")
    _paper(conn, "1", lose)
    conn.commit()
    with pytest.raises(ValueError):
        merge_concepts(conn, lose, win, reviewed_by="")
    assert concept_weight(conn, lose) == 1
    assert curation_state(get_node(conn, lose)["attrs"]) == "harvested"


# --- the pair the queue can now name ---------------------------------------


def test_colliding_pairs_names_the_counterpart(conn):
    """A curator retyping "NUMA Topology and Memory Policy" will mistype it."""
    a = _concept(conn, "concept-a", "Robust Futex")
    b = _concept(conn, "concept-b", "Robust Futex Support")
    _concept(conn, "concept-c", "Slab Cache")
    conn.commit()

    pairs = colliding_pairs(conn)

    assert len(pairs) == 1
    assert set(pairs[0]) == {a, b}


def test_colliding_concepts_is_a_flattening_and_never_a_second_matcher(conn):
    """A queue whose badge and whose merge button disagreed about what a
    collision is would be worse than either alone."""
    _concept(conn, "concept-a", "Folio")
    _concept(conn, "concept-b", "Folio Marks")
    _concept(conn, "concept-c", "Grace Period")
    conn.commit()

    flat = {cid for pair in colliding_pairs(conn) for cid in pair}
    assert colliding_concepts(conn) == flat
    assert "concept-c" not in flat


def test_a_merged_away_concept_still_collides_until_the_queue_filters_it(conn):
    """Recorded rather than fixed here: the pair remains in the signal because
    the loser keeps its name. The review queue's curation filter is what hides
    it, and that is ALG-KK-WEB-CONCEPTS-LIST's job, not the matcher's."""
    win = _concept(conn, "concept-win", "Folio")
    lose = _concept(conn, "concept-lose", "Folio Marks")
    conn.commit()
    merge_concepts(conn, lose, win, reviewed_by="reinier")
    assert len(colliding_pairs(conn)) == 1
