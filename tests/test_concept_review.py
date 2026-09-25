"""The review surface: the queue that makes bulk harvest survivable.

The operator's words: "I do not need human approval when doing this in bulk.
What I need is a review mechanism so a human can edit and update the concept if
needed." This file covers the READ half — the curation filter and the
prioritisation. The edit and retire routes are beside it.

THE LOAD-BEARING DISTINCTION IN THIS FILE is that ?curation= is a real WHERE
clause while ?state= beside it is not. A review queue that inherited the
admission filter's page-local limitation would show a curator 50 of 3,000
harvested concepts and call it the backlog.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from graph.concept_vocabulary import (
    build_vocabulary_context,
    colliding_concepts,
)
from graph.engine import add_edge, add_node
from graph.schema import init_db
from web.app import create_app

SIX = {
    "description": "d", "artifact_class": "abstracted-mechanism",
    "key_properties": [], "tradeoffs": [], "design_rationale": "r",
}


def _concept(conn, cid, name, **extra):
    add_node(conn, cid, "Concept", {**SIX, "name": name, **extra})
    return cid


def _paper(conn, n, cid):
    add_node(conn, f"src-{n}", "Source", {
        "url": f"https://example.com/{n}", "source_type": "preprint",
        "license": "MIT", "title": f"Paper {n}"})
    add_node(conn, f"ev-{n}", "Evidence", {
        "artifact_class": "A", "contamination_level": "L0", "text": "t"})
    add_edge(conn, "sourced-from", f"ev-{n}", f"src-{n}")
    add_edge(conn, "extracted-from", cid, f"ev-{n}")


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "review.db")
    yield c
    c.close()


# --- a retired concept leaves the vocabulary (INV-KK-VOCABULARY-EXCLUDES-RETIRED)


def test_a_retired_concept_is_not_offered_to_the_extractor(conn):
    """THE DIFFERENCE BETWEEN RETIRING A CONCEPT AND PRETENDING TO. Without
    this the next extraction run puts the retired entry straight back in front
    of the model under "choose concept names from this list"."""
    _concept(conn, "concept-good", "Grace Period")
    _concept(conn, "concept-bad", "Random Forest", curation_state="retired")
    conn.commit()
    ctx = build_vocabulary_context(conn)
    assert "Grace Period" in ctx
    assert "Random Forest" not in ctx


def test_retiring_withdraws_the_offer_and_not_the_record(conn):
    """It keeps its node and every edge — that is the whole point of a state
    over a delete."""
    cid = _concept(conn, "concept-bad", "Random Forest", curation_state="retired")
    _paper(conn, "1", cid)
    conn.commit()
    assert conn.execute("SELECT 1 FROM nodes WHERE id = ?", (cid,)).fetchone()
    assert conn.execute(
        "SELECT COUNT(*) FROM edges WHERE source_id = ?", (cid,)).fetchone()[0] == 1
    assert "Random Forest" not in build_vocabulary_context(conn)


def test_absent_curation_state_stays_in_the_vocabulary(conn):
    """All 97 Concepts that predate the field carry nothing, and absent is not
    retired."""
    _concept(conn, "concept-1", "Vmalloc")
    _concept(conn, "concept-2", "Zswap", curation_state="harvested")
    _concept(conn, "concept-3", "Futex", curation_state="reviewed")
    conn.commit()
    ctx = build_vocabulary_context(conn)
    for name in ("Vmalloc", "Zswap", "Futex"):
        assert name in ctx


# --- the collision signal ---------------------------------------------------


def test_collisions_use_the_matcher_that_actually_runs(conn):
    """A queue flagging collisions the matcher would not make would be
    reporting a different program than the one that runs. All three tiers."""
    _concept(conn, "concept-v", "Vmalloc")
    _concept(conn, "concept-k", "Kmalloc")          # Levenshtein 1
    _concept(conn, "concept-io", "io_uring")
    _concept(conn, "concept-ioa", "io_uring Async")  # prefix
    _concept(conn, "concept-alone", "Grace Period")
    conn.commit()
    colliding = colliding_concepts(conn)
    assert colliding == {"concept-v", "concept-k", "concept-io", "concept-ioa"}
    assert "concept-alone" not in colliding


def test_the_measured_four_collisions_of_the_live_corpus(conn):
    """Measured 2026-09-25 against data/master.db. The plan recorded "ZERO
    homonyms today", which is true of EXACT names and false of the matcher:
    io_uring against three io_uring* entries, and Vmalloc against Kmalloc — a
    FALSE POSITIVE between two different allocators, and the more important of
    the four because of what it does on the harvest path."""
    for cid, name in (
        ("c-io", "io_uring"),
        ("c-ioa", "io_uring Asynchronous I/O"),
        ("c-iod", "io_uring Database Integration"),
        ("c-ioo", "io_uring Observability Tool"),
        ("c-v", "Vmalloc"),
        ("c-k", "Kmalloc"),
        ("c-s", "Scheduling Classes"),
    ):
        _concept(conn, cid, name)
    conn.commit()
    assert len(colliding_concepts(conn)) == 6
    assert "c-s" not in colliding_concepts(conn)


# --- the list page ----------------------------------------------------------


def _client(tmp_path, build):
    path = tmp_path / "web.db"
    c = init_db(path)
    build(c)
    c.commit()
    c.close()
    return TestClient(create_app(str(path)))


def test_the_curation_filter_is_a_where_clause_reaching_past_page_one(tmp_path):
    """THE TEST THAT DISTINGUISHES THIS FILTER FROM THE ADMISSION FILTER BESIDE
    IT. 30 reviewed concepts sort before the one harvested concept by name, so
    a page-local filter would return nothing on page 1. A WHERE clause returns
    it."""
    def build(c):
        for i in range(30):
            _concept(c, f"concept-a{i:02d}", f"AAA Reviewed {i:02d}",
                     curation_state="reviewed", reviewed_by="r",
                     reviewed_at="2026-09-25")
        _concept(c, "concept-zz", "ZZZ Harvested", curation_state="harvested")

    with _client(tmp_path, build) as client:
        page1 = client.get("/concepts?per_page=10&page=1")
        assert "ZZZ Harvested" not in page1.text, "fixture no longer proves anything"
        filtered = client.get("/concepts?per_page=10&page=1&curation=harvested")
        assert "ZZZ Harvested" in filtered.text
        assert "AAA Reviewed" not in filtered.text


def test_the_harvested_filter_includes_concepts_with_no_curation_state(tmp_path):
    """All 97 that predate the field. A queue showing empty while 97 unreviewed
    concepts sat in the corpus would be wrong in the most misleading
    direction."""
    def build(c):
        _concept(c, "concept-old", "Predates The Field")
        _concept(c, "concept-new", "Freshly Harvested", curation_state="harvested")
        _concept(c, "concept-done", "Already Reviewed", curation_state="reviewed",
                 reviewed_by="r", reviewed_at="2026-09-25")

    with _client(tmp_path, build) as client:
        text = client.get("/concepts?curation=harvested").text
        assert "Predates The Field" in text
        assert "Freshly Harvested" in text
        assert "Already Reviewed" not in text


def test_the_retired_filter_still_lists_them(tmp_path):
    """Retirement withdraws the offer, not the record — so the browser must
    still be able to show them."""
    def build(c):
        _concept(c, "concept-r", "Retired One", curation_state="retired")

    with _client(tmp_path, build) as client:
        assert "Retired One" in client.get("/concepts?curation=retired").text


def test_collisions_sort_first_then_papers_descending(tmp_path):
    """IFC-KK-CONCEPT-REVIEW-PRIORITY. The colliding pair carries ZERO papers
    and must still outrank a 3-paper concept, or the signal does nothing."""
    def build(c):
        heavy = _concept(c, "concept-heavy", "Zzz Heavy")
        for n in ("1", "2", "3"):
            _paper(c, n, heavy)
        _concept(c, "concept-v", "Vmalloc")
        _concept(c, "concept-k", "Kmalloc")
        mid = _concept(c, "concept-mid", "Yyy Middle")
        _paper(c, "4", mid)

    with _client(tmp_path, build) as client:
        text = client.get("/concepts").text
        order = [text.index(n) for n in ("Kmalloc", "Vmalloc")]
        assert max(order) < text.index("Zzz Heavy"), "collisions did not sort first"
        assert text.index("Zzz Heavy") < text.index("Yyy Middle"), (
            "papers did not sort descending")


def test_a_colliding_row_is_marked_in_the_page(tmp_path):
    def build(c):
        _concept(c, "concept-v", "Vmalloc")
        _concept(c, "concept-k", "Kmalloc")
        _concept(c, "concept-a", "Grace Period")

    with _client(tmp_path, build) as client:
        assert "name collides" in client.get("/concepts").text


def test_the_page_says_the_curation_filter_reaches_the_whole_vocabulary(tmp_path):
    """The admission filter's banner says "on this page only". This one must
    NOT, because it is not true of it — and a filter that lied about
    completeness would be worse than no filter."""
    def build(c):
        _concept(c, "concept-1", "Zswap", curation_state="harvested")

    with _client(tmp_path, build) as client:
        text = client.get("/concepts?curation=harvested").text
        assert "whole vocabulary" in text
        assert "on this page only" not in text


def test_an_unknown_curation_value_does_not_filter(tmp_path):
    """It is checked against CURATION_STATES rather than interpolated, so a
    junk value cannot reach the SQL."""
    def build(c):
        _concept(c, "concept-1", "Zswap")

    with _client(tmp_path, build) as client:
        assert "Zswap" in client.get("/concepts?curation=%27%20OR%201%3D1--").text
