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


def test_a_merged_away_concept_leaves_the_collision_signal(conn):
    """THIS ASSERTION WAS INVERTED ON 2026-09-29, AND THE OLD ONE WAS THE BUG.
    It read "the pair remains in the signal because the loser keeps its name",
    with a note deferring the fix to the review queue's filter. Retiring
    fourteen paper artifacts then made SIX of 29 collision pairs noise about
    concepts already dealt with, and build_vocabulary_context had excluded
    retired concepts since 2026-09-25 — so the generator was simply
    inconsistent with the rest of the system."""
    win = _concept(conn, "concept-win", "Folio")
    lose = _concept(conn, "concept-lose", "Folio Marks")
    conn.commit()
    assert len(colliding_pairs(conn)) == 1
    merge_concepts(conn, lose, win, reviewed_by="reinier")
    conn.commit()
    assert colliding_pairs(conn) == []


# --- through the real router (ALG-KK-WEB-CONCEPT-MERGE) ---------------------


import json as _json

from fastapi.testclient import TestClient

from web.app import create_app
from web.routes import WEB_MUTATION_ALLOWLIST


@pytest.fixture
def merge_db(tmp_path):
    path = tmp_path / "web-merge.db"
    c = init_db(path)
    _concept(c, "concept-win", "NUMA Topology and Memory Policy")
    _concept(c, "concept-lose", "NUMA Memory Policy")
    _concept(c, "concept-far", "Grace Period")
    _subsystem(c, "sub-mm", "mm")
    _paper(c, "1", "concept-win")
    _paper(c, "2", "concept-lose")
    add_edge(c, "belongs-to", "concept-lose", "sub-mm")
    _discussion(c, "disc-1", "concept-lose")
    c.commit()
    c.close()
    return str(path)


@pytest.fixture
def curator_client(merge_db):
    """An AUTHENTICATED but non-admin curator — the bar this route sets."""
    app = create_app(merge_db)

    @app.middleware("http")
    async def _as_curator(request, call_next):
        request.state.user = {"username": "kate", "role": "reviewer",
                              "reviewer": "reviewer-kate"}
        return await call_next(request)

    with TestClient(app) as c:
        yield c


@pytest.fixture
def anon_client(merge_db):
    """No middleware, so request.state.user is absent."""
    with TestClient(create_app(merge_db)) as c:
        yield c


def _db_attrs(client, cid):
    return _json.loads(client.app.state.conn.execute(
        "SELECT attrs FROM nodes WHERE id = ?", (cid,)).fetchone()[0])


def test_the_prefix_is_on_the_mutation_allowlist(merge_db):
    """INV-KK-WEB-MUTATION-ALLOWLISTED."""
    assert "/api/concept-merge/" in WEB_MUTATION_ALLOWLIST


def test_a_curator_merges_and_the_response_says_what_moved(curator_client):
    r = curator_client.post("/api/concept-merge/concept-lose/concept-win")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["moved"] == 3          # extracted-from, belongs-to, discusses
    assert body["dropped"] == 0
    assert body["weight_before"] == 1
    assert body["weight_after"] == 2
    assert body["winner_name"] == "NUMA Topology and Memory Policy"
    assert body["loser_name"] == "NUMA Memory Policy"


def test_the_editor_comes_from_the_session_and_a_body_field_is_ignored(curator_client):
    """INV-KK-REVIEW-ATTRIBUTION-FROM-SESSION. This route reads no body at all,
    so a reviewer field cannot even be offered."""
    r = curator_client.post("/api/concept-merge/concept-lose/concept-win",
                            json={"reviewer": "somebody-else"})
    assert r.status_code == 200, r.text
    assert _db_attrs(curator_client, "concept-lose")["reviewed_by"] == "reviewer-kate"


def test_a_non_admin_curator_is_enough(curator_client):
    """THE VENUE PRECEDENT IS DELIBERATELY NOT FOLLOWED. An admin gate would
    make page one of the review queue unactionable by the person it was built
    for. The fixture's role is 'reviewer', not 'admin'."""
    r = curator_client.post("/api/concept-merge/concept-lose/concept-win")
    assert r.status_code == 200, r.text


def test_an_anonymous_caller_is_refused_and_writes_nothing(anon_client):
    r = anon_client.post("/api/concept-merge/concept-lose/concept-win")
    assert r.status_code == 401
    assert _db_attrs(anon_client, "concept-lose").get("curation_state") != "retired"
    assert concept_weight(anon_client.app.state.conn, "concept-lose") == 1


def test_an_unknown_concept_is_404(curator_client):
    r = curator_client.post("/api/concept-merge/concept-nope/concept-win")
    assert r.status_code == 404
    assert "No Concept" in r.json()["error"]


def test_a_self_merge_is_422(curator_client):
    r = curator_client.post("/api/concept-merge/concept-win/concept-win")
    assert r.status_code == 422
    assert "itself" in r.json()["error"]


def test_a_second_call_through_the_route_is_a_no_op(curator_client):
    first = curator_client.post("/api/concept-merge/concept-lose/concept-win")
    second = curator_client.post("/api/concept-merge/concept-lose/concept-win")
    assert first.json()["moved"] == 3
    assert second.status_code == 200
    assert second.json()["moved"] == 0 and second.json()["dropped"] == 0


def test_the_merged_concept_leaves_the_vocabulary_the_extractor_is_shown(curator_client):
    """The one that matters most, asserted through the real route."""
    curator_client.post("/api/concept-merge/concept-lose/concept-win")
    ctx = build_vocabulary_context(curator_client.app.state.conn)
    assert "NUMA Topology and Memory Policy" in ctx
    assert "NUMA Memory Policy" not in ctx.replace(
        "NUMA Topology and Memory Policy", "")


# --- the affordance names the counterpart ----------------------------------


def test_the_detail_page_offers_the_named_counterpart_both_ways(curator_client):
    """A curator retyping the name will mistype it, so the page presses a
    button naming the specific other entry — and offers both directions,
    because which one wins is the curator's judgement."""
    page = curator_client.get("/concepts/concept-lose").text
    assert "This name collides" in page
    assert "NUMA Topology and Memory Policy" in page
    assert "mergeConcept('concept-lose', 'concept-win'" in page
    assert "mergeConcept('concept-win', 'concept-lose'" in page


def test_a_concept_that_collides_with_nothing_gets_no_merge_control(curator_client):
    page = curator_client.get("/concepts/concept-far").text
    assert "This name collides" not in page


def test_an_already_merged_counterpart_is_not_offered_again(curator_client):
    """A retired counterpart is not a merge a curator should be offered twice."""
    curator_client.post("/api/concept-merge/concept-lose/concept-win")
    page = curator_client.get("/concepts/concept-win").text
    assert "This name collides" not in page


def test_the_list_names_what_each_row_collides_with(curator_client):
    """The badge said "name collides" and not what WITH, which is why the only
    affordance it could have offered was a text field."""
    page = curator_client.get("/concepts").text
    assert "collides with" in page
    assert 'href="/concepts/concept-win"' in page
    assert 'href="/concepts/concept-lose"' in page


# --- a pair a human decided against (ALG-KK-WEB-CONCEPT-DISTINCT) -----------
#
# ELEVEN LIVE PAIRS ARE NOT MERGES and nothing could record that: a curator who
# decides against Folio ~ Folio Marks today sees it again tomorrow, which is how
# a review queue becomes something people stop opening. Every one of these would
# have been a WRONG merge, and a wrong merge is the single error in this
# vocabulary that nothing ever finds again — the evidence of the merged-away
# concept is now attached to the survivor.


def _distinct_db(tmp_path):
    path = tmp_path / "distinct.db"
    c = init_db(path)
    _concept(c, "concept-folio", "Folio")
    _concept(c, "concept-marks", "Folio Marks")
    _concept(c, "concept-far", "Grace Period")
    c.commit()
    c.close()
    return str(path)


@pytest.fixture
def distinct_client(tmp_path):
    app = create_app(_distinct_db(tmp_path))

    @app.middleware("http")
    async def _as_curator(request, call_next):
        request.state.user = {"username": "kate", "role": "reviewer",
                              "reviewer": "reviewer-kate"}
        return await call_next(request)

    with TestClient(app) as c:
        yield c


def test_the_distinct_prefix_is_allowlisted():
    assert "/api/concept-distinct/" in WEB_MUTATION_ALLOWLIST


def test_a_decided_pair_leaves_the_collision_signal(conn):
    a = _concept(conn, "concept-folio", "Folio")
    b = _concept(conn, "concept-marks", "Folio Marks")
    conn.commit()
    assert len(colliding_pairs(conn)) == 1

    from graph.concept_vocabulary import record_distinct
    assert record_distinct(conn, a, b) is True
    conn.commit()

    assert colliding_pairs(conn) == []
    assert colliding_concepts(conn) == set()


def test_either_direction_suppresses_the_pair(conn):
    """The relation is symmetric in meaning; storing it twice would let the two
    halves drift."""
    a = _concept(conn, "concept-folio", "Folio")
    b = _concept(conn, "concept-marks", "Folio Marks")
    conn.commit()
    add_edge(conn, "contradicts", b, a)   # b -> a, the reverse of what a curator
    conn.commit()                          # pressing on Folio's page would write
    assert colliding_pairs(conn) == []


def test_recording_the_same_pair_twice_adds_nothing(conn):
    """THE ENGINE ALREADY TREATS contradicts AS SYMMETRIC, found by this test
    rather than assumed: graph.engine.add_edge writes the reverse edge itself
    for this kind, so ONE call leaves TWO rows — and they cannot drift, because
    nothing writes one without the other."""
    from graph.concept_vocabulary import record_distinct
    a = _concept(conn, "concept-folio", "Folio")
    b = _concept(conn, "concept-marks", "Folio Marks")
    conn.commit()
    assert record_distinct(conn, a, b) is True
    assert conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind='contradicts'").fetchone()[0] == 2
    assert record_distinct(conn, b, a) is False
    conn.commit()
    assert conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind='contradicts'").fetchone()[0] == 2


def test_a_concept_cannot_be_distinct_from_itself(conn):
    from graph.concept_vocabulary import record_distinct
    _concept(conn, "concept-folio", "Folio")
    conn.commit()
    with pytest.raises(ValueError, match="itself"):
        record_distinct(conn, "concept-folio", "concept-folio")


def test_both_concepts_survive_untouched(conn):
    """It suppresses the PAIRING and nothing else."""
    from graph.concept_vocabulary import record_distinct
    a = _concept(conn, "concept-folio", "Folio")
    b = _concept(conn, "concept-marks", "Folio Marks")
    _paper(conn, "1", a)
    conn.commit()
    record_distinct(conn, a, b)
    conn.commit()
    assert curation_state(get_node(conn, a)["attrs"]) == "harvested"
    assert curation_state(get_node(conn, b)["attrs"]) == "harvested"
    assert concept_weight(conn, a) == 1
    assert "Folio" in build_vocabulary_context(conn)
    assert "Folio Marks" in build_vocabulary_context(conn)


def test_a_retired_concept_leaves_the_collision_signal(conn):
    """A PLAIN BUG UNTIL 2026-09-29. build_vocabulary_context has excluded
    retired concepts since 2026-09-25 and this generator did not, so retiring
    fourteen paper artifacts left SIX of 29 pairs as noise about concepts
    already dealt with."""
    _concept(conn, "concept-iouring", "io_uring")
    _concept(conn, "concept-async", "io_uring Asynchronous I/O")
    conn.commit()
    assert len(colliding_pairs(conn)) == 1

    from graph.concept_vocabulary import retire_concept
    retire_concept(conn, "concept-async", reviewed_by="reviewer-kate")
    conn.commit()

    assert colliding_pairs(conn) == []


def test_the_route_records_and_the_pair_disappears(distinct_client):
    r = distinct_client.post("/api/concept-distinct/concept-folio/concept-marks")
    assert r.status_code == 200, r.text
    assert r.json()["written"] is True
    assert colliding_pairs(distinct_client.app.state.conn) == []


def test_the_route_is_idempotent(distinct_client):
    distinct_client.post("/api/concept-distinct/concept-folio/concept-marks")
    r = distinct_client.post("/api/concept-distinct/concept-marks/concept-folio")
    assert r.status_code == 200, r.text
    assert r.json()["written"] is False


def test_an_unknown_concept_is_404(distinct_client):
    r = distinct_client.post("/api/concept-distinct/concept-folio/concept-nope")
    assert r.status_code == 404


def test_a_self_pair_is_422(distinct_client):
    r = distinct_client.post("/api/concept-distinct/concept-folio/concept-folio")
    assert r.status_code == 422


def test_an_anonymous_caller_is_refused_and_writes_nothing(tmp_path):
    with TestClient(create_app(_distinct_db(tmp_path))) as c:
        r = c.post("/api/concept-distinct/concept-folio/concept-marks")
        assert r.status_code == 401
        assert c.app.state.conn.execute(
            "SELECT COUNT(*) FROM edges WHERE kind='contradicts'").fetchone()[0] == 0


def test_the_detail_page_offers_the_not_the_same_control(distinct_client):
    page = distinct_client.get("/concepts/concept-folio").text
    assert "Not the same thing" in page
    assert "markDistinct('concept-folio', 'concept-marks'" in page


def test_a_decided_pair_is_gone_from_the_detail_page(distinct_client):
    distinct_client.post("/api/concept-distinct/concept-folio/concept-marks")
    page = distinct_client.get("/concepts/concept-folio").text
    assert "This name collides" not in page


# ---------------------------------------------------------------------------
# INV-KK-CONCEPT-DOCUMENTATION-ABSENT / ALG-KK-WEB-CONCEPT-DOCUMENTATION-ABSENT
#
# "unlinked" says nobody has linked a concept. It has never been able to say
# that nothing COULD. Signal Delivery is defined by kernel/signal.c and has no
# Documentation/ page, and until this existed it was indistinguishable from
# the 32 concepts merely waiting for a seeding run.
# ---------------------------------------------------------------------------

def test_the_documentation_absent_prefix_is_allowlisted():
    assert "/api/concept-documentation-absent/" in WEB_MUTATION_ALLOWLIST


def test_marking_documentation_absent_records_a_reason_and_an_author(conn):
    from graph.concept_vocabulary import mark_documentation_absent
    cid = _concept(conn, "concept-signal", "Signal Delivery")
    conn.commit()

    assert mark_documentation_absent(
        conn, cid, "defined by kernel/signal.c; no Documentation/ page",
        "reviewer-kate") is True
    conn.commit()

    from graph.engine import get_node
    attrs = get_node(conn, cid)["attrs"]
    assert attrs["documentation_absent"] is True
    assert "kernel/signal.c" in attrs["documentation_absent_reason"]
    assert attrs["reviewed_by"] == "reviewer-kate"


def test_marking_does_not_change_the_curation_state(conn):
    """THE REASON IT IS AN ATTRIBUTE AND NOT A FOURTH STATE. The two facts are
    orthogonal, and a fourth state would make an unread concept stop counting
    as unreviewed — corrupting the one number the progress count keeps honest."""
    from graph.concept_vocabulary import mark_documentation_absent, curation_progress
    cid = _concept(conn, "concept-signal2", "Signal Delivery")
    conn.commit()
    before = curation_progress(conn)

    mark_documentation_absent(conn, cid, "no Documentation/ page", "reviewer-kate")
    conn.commit()

    assert curation_progress(conn) == before, "an undocumentable concept left the backlog"


def test_an_empty_reason_is_refused(conn):
    """Without a reason the mark is indistinguishable from a curator who did
    not look."""
    from graph.concept_vocabulary import mark_documentation_absent
    cid = _concept(conn, "concept-signal3", "Signal Delivery")
    conn.commit()
    with pytest.raises(ValueError):
        mark_documentation_absent(conn, cid, "   ", "reviewer-kate")
    with pytest.raises(ValueError):
        mark_documentation_absent(conn, cid, "a real reason", "")


def test_marking_twice_writes_nothing_the_second_time(conn):
    from graph.concept_vocabulary import mark_documentation_absent
    cid = _concept(conn, "concept-signal4", "Signal Delivery")
    conn.commit()
    assert mark_documentation_absent(conn, cid, "no page", "reviewer-kate") is True
    assert mark_documentation_absent(conn, cid, "no page", "reviewer-kate") is False


def test_an_unknown_concept_is_refused(conn):
    from graph.concept_vocabulary import mark_documentation_absent
    with pytest.raises(ValueError, match="No Concept"):
        mark_documentation_absent(conn, "concept-nope", "no page", "reviewer-kate")


def test_the_route_refuses_an_anonymous_caller_and_writes_nothing(tmp_path):
    """INV-KK-REVIEW-ATTRIBUTION-FROM-SESSION. The mark is a CLAIM ABOUT THE
    KERNEL and someone has to own it."""
    app = create_app(_distinct_db(tmp_path))
    with TestClient(app) as anon:
        r = anon.post("/api/concept-documentation-absent/concept-folio",
                      json={"reason": "no page"})
    assert r.status_code == 401


def test_the_route_marks_through_the_real_router(distinct_client):
    r = distinct_client.post("/api/concept-documentation-absent/concept-folio",
                             json={"reason": "defined in mm/folio.c, no page"})
    assert r.status_code == 200, r.text
    assert r.json()["written"] is True

    again = distinct_client.post("/api/concept-documentation-absent/concept-folio",
                                 json={"reason": "defined in mm/folio.c, no page"})
    assert again.json()["written"] is False


def test_the_route_refuses_an_empty_reason(distinct_client):
    r = distinct_client.post("/api/concept-documentation-absent/concept-folio",
                             json={"reason": ""})
    assert r.status_code == 422


def test_the_route_404s_on_an_unknown_concept(distinct_client):
    r = distinct_client.post("/api/concept-documentation-absent/concept-nope",
                             json={"reason": "no page"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# A MERGE MUST NOT BREAK INV-KK-CONCEPT-SUBSYSTEM-SINGLE.
#
# Found 2026-09-30, by a merge that did. _edge_exists asks whether the winner
# has this edge to the SAME target — the right test for a kind that may repeat
# and the wrong one for a kind that may not. Merging "Page Table Hierarchy"
# (Virtual Memory) into "Hierarchical Page Tables" (Memory Management) moved a
# SECOND belongs-to onto the winner.
# ---------------------------------------------------------------------------

def test_a_merge_does_not_give_the_winner_two_subsystems(conn):
    from graph.concept_vocabulary import merge_concepts
    w = _concept(conn, "concept-w", "Hierarchical Page Tables")
    l = _concept(conn, "concept-l", "Page Table Hierarchy")
    add_node(conn, "sub-mm", "Subsystem", {"name": "Memory Management"})
    add_node(conn, "sub-vm", "Subsystem", {"name": "Virtual Memory"})
    add_edge(conn, "belongs-to", w, "sub-mm")
    add_edge(conn, "belongs-to", l, "sub-vm")
    conn.commit()

    merge_concepts(conn, l, w, "reviewer-kate")
    conn.commit()

    subs = conn.execute(
        "SELECT target_id FROM edges WHERE kind='belongs-to' AND source_id=?",
        (w,)).fetchall()
    assert len(subs) == 1, "the merge gave the winner two subsystems"
    assert subs[0][0] == "sub-mm", \
        "the winner's own subsystem must survive, not the loser's"


def test_a_merge_still_carries_the_subsystem_when_the_winner_has_none(conn):
    """Dropping is only right when the winner ALREADY has one. A winner with
    no home should inherit the loser's."""
    from graph.concept_vocabulary import merge_concepts
    w = _concept(conn, "concept-w2", "Winner")
    l = _concept(conn, "concept-l2", "Loser")
    add_node(conn, "sub-vm2", "Subsystem", {"name": "Virtual Memory"})
    add_edge(conn, "belongs-to", l, "sub-vm2")
    conn.commit()

    merge_concepts(conn, l, w, "reviewer-kate")
    conn.commit()

    subs = conn.execute(
        "SELECT target_id FROM edges WHERE kind='belongs-to' AND source_id=?",
        (w,)).fetchall()
    assert [r[0] for r in subs] == ["sub-vm2"]


def test_a_merge_still_repoints_edge_kinds_that_may_repeat(conn):
    """The drop is scoped to cardinality-one kinds. extracted-from may repeat
    and must still move — that is what a merge is for."""
    from graph.concept_vocabulary import merge_concepts
    w = _concept(conn, "concept-w3", "Winner")
    l = _concept(conn, "concept-l3", "Loser")
    add_node(conn, "src-x", "Source", {"url": "https://x/1", "source_type": "preprint",
                                       "license": "MIT", "title": "P"})
    add_node(conn, "ev-x", "Evidence", {"artifact_class": "A",
                                        "contamination_level": "L0", "text": "t"})
    add_edge(conn, "sourced-from", "ev-x", "src-x")
    add_edge(conn, "extracted-from", l, "ev-x")
    conn.commit()

    r = merge_concepts(conn, l, w, "reviewer-kate")
    conn.commit()

    assert r.moved >= 1
    assert conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind='extracted-from' AND source_id=?",
        (w,)).fetchone()[0] == 1
