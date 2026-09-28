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


def test_collisions_use_the_tiers_that_earn_their_place(conn):
    """The signal exists to direct a human minute, so it carries only the
    tiers with measured precision.

    LEVENSHTEIN LEFT ON 2026-09-28. It produced 10 of 35 pairs on the live
    corpus and every one was a different mechanism — Vmalloc~Kmalloc,
    kref~kset, Slab Cache~Swap Cache. Vmalloc and Kmalloc are kept in this
    fixture precisely to assert they NO LONGER collide; matching keeps the
    tier, the signal does not (IFC-KK-CONCEPT-REVIEW-PRIORITY)."""
    _concept(conn, "concept-v", "Vmalloc")
    _concept(conn, "concept-k", "Kmalloc")           # Levenshtein 1 — NOT a collision
    _concept(conn, "concept-io", "io_uring")
    _concept(conn, "concept-ioa", "io_uring Async")   # prefix
    _concept(conn, "concept-hp", "Huge Pages")
    _concept(conn, "concept-thp", "Transparent Huge Pages")  # containment
    _concept(conn, "concept-alone", "Grace Period")
    conn.commit()
    colliding = colliding_concepts(conn)
    assert colliding == {"concept-io", "concept-ioa", "concept-hp", "concept-thp"}
    assert "concept-v" not in colliding, "the Levenshtein false pair came back"
    assert "concept-alone" not in colliding


def test_the_live_corpus_pairs_that_survived_the_2026_09_28_narrowing(conn):
    """Measured 2026-09-25, re-measured 2026-09-28 after the Levenshtein tier
    left the signal: the live corpus went from 54 concepts in 35 pairs to 41
    in 25, and the 10 pairs that disappeared were ALL different mechanisms.

    io_uring against its three variants is a prefix collision and survives —
    those are real near-duplicates a human should merge or distinguish.
    Vmalloc against Kmalloc was the Levenshtein false positive and is gone."""
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
    col = colliding_concepts(conn)
    assert col == {"c-io", "c-ioa", "c-iod", "c-ioo"}
    assert "c-v" not in col and "c-k" not in col
    assert "c-s" not in col


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
        # A PREFIX pair, not a Levenshtein one: the signal dropped that tier
        # on 2026-09-28 and these must still sort first.
        _concept(c, "concept-v", "Folio")
        _concept(c, "concept-k", "Folio Marks")
        mid = _concept(c, "concept-mid", "Yyy Middle")
        _paper(c, "4", mid)

    with _client(tmp_path, build) as client:
        text = client.get("/concepts").text
        order = [text.index(n) for n in ("Folio", "Folio Marks")]
        assert max(order) < text.index("Zzz Heavy"), "collisions did not sort first"
        assert text.index("Zzz Heavy") < text.index("Yyy Middle"), (
            "papers did not sort descending")


def test_a_colliding_row_is_marked_in_the_page(tmp_path):
    def build(c):
        _concept(c, "concept-v", "Folio")
        _concept(c, "concept-k", "Folio Marks")
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


# ---------------------------------------------------------------------------
# The mutating surface: edit and retire (ALG-KK-WEB-CONCEPT-EDIT,
# ALG-KK-WEB-CONCEPT-RETIRE)
# ---------------------------------------------------------------------------

from graph.concept_vocabulary import retire_concept, update_concept  # noqa: E402
from graph.engine import get_node  # noqa: E402


def _full(name="Zswap", **over):
    body = {
        "name": name,
        "description": f"{name} is a mechanism described abstractly.",
        "artifact_class": "abstracted-mechanism",
        "key_properties": ["a property"],
        "tradeoffs": ["a tradeoff"],
        "design_rationale": "Why it is shaped this way.",
    }
    body.update(over)
    return body


@pytest.fixture
def edit_db(tmp_path):
    path = tmp_path / "edit.db"
    c = init_db(path)
    _concept(c, "concept-1", "Zswap", curation_state="harvested",
             harvest_batch="harvest-2026-09-25-abcd1234")
    _concept(c, "concept-2", "Grace Period")
    _paper(c, "1", "concept-1")
    c.commit()
    c.close()
    return str(path)


@pytest.fixture
def admin_client(edit_db):
    app = create_app(edit_db)

    @app.middleware("http")
    async def _as_curator(request, call_next):
        request.state.user = {"username": "root", "role": "admin",
                              "reviewer": "reviewer-root"}
        return await call_next(request)

    with TestClient(app) as c:
        yield c


@pytest.fixture
def anon_client(edit_db):
    """No middleware, so request.state.user is absent — the defensive branch."""
    with TestClient(create_app(edit_db)) as c:
        yield c


def _attrs(client, cid):
    conn = client.app.state.conn
    return json.loads(conn.execute(
        "SELECT attrs FROM nodes WHERE id = ?", (cid,)).fetchone()[0])


# --- edit -------------------------------------------------------------------


def test_an_edit_changes_the_attrs_and_reviews_it_in_one_operation(admin_client):
    """A human who fixed a description has read it. A second button would
    guarantee the state is wrong for everyone who forgets."""
    r = admin_client.put("/api/concept/concept-1",
                         json=_full(description="A much better description."))
    assert r.status_code == 200, r.text
    a = _attrs(admin_client, "concept-1")
    assert a["description"] == "A much better description."
    assert a["curation_state"] == "reviewed"
    assert a["reviewed_by"] == "reviewer-root"
    assert a["reviewed_at"]


def test_a_save_that_changes_nothing_still_marks_it_reviewed(admin_client):
    """Decision 2026-09-25. Pressing save is an affirmative act: it says "I
    have read this and it is right as it stands", which is a useful answer for
    a harvested concept the model got correct."""
    before = _attrs(admin_client, "concept-1")
    r = admin_client.put("/api/concept/concept-1", json=_full("Zswap",
                         description=before["description"]))
    assert r.status_code == 200
    assert _attrs(admin_client, "concept-1")["curation_state"] == "reviewed"


def test_opening_the_page_does_not_mark_it_reviewed(admin_client):
    """A GET asserts nothing — a human can open a page by accident."""
    assert admin_client.get("/concepts/concept-1").status_code == 200
    assert _attrs(admin_client, "concept-1").get("curation_state") == "harvested"


def test_reviewed_by_in_the_body_is_ignored(admin_client):
    """INV-KK-REVIEW-ATTRIBUTION-FROM-SESSION. No request may file a review
    under someone else's name."""
    r = admin_client.put("/api/concept/concept-1", json=_full(
        **{"reviewed_by": "somebody-else", "reviewed_at": "1999-01-01"}))
    assert r.status_code == 200
    a = _attrs(admin_client, "concept-1")
    assert a["reviewed_by"] == "reviewer-root"
    assert a["reviewed_at"] != "1999-01-01"


def test_an_anonymous_caller_is_refused_and_writes_nothing(anon_client):
    before = _attrs(anon_client, "concept-1")
    r = anon_client.put("/api/concept/concept-1", json=_full(description="hijack"))
    assert r.status_code == 401
    assert _attrs(anon_client, "concept-1") == before


def test_an_edit_that_blanks_a_required_attr_is_refused(admin_client):
    """add_node's six-attribute rule must not be circumventable through the
    edit path. update_node_attrs refuses a MISSING attribute but cannot see a
    BLANK, which passes the schema and says nothing."""
    before = _attrs(admin_client, "concept-1")
    r = admin_client.put("/api/concept/concept-1",
                         json=_full(design_rationale="   "))
    assert r.status_code == 422
    assert "design_rationale" in r.json()["error"]
    assert _attrs(admin_client, "concept-1") == before


def test_an_edit_missing_an_attr_entirely_is_refused(admin_client):
    body = _full()
    del body["tradeoffs"]
    r = admin_client.put("/api/concept/concept-1", json=body)
    assert r.status_code == 422
    assert _attrs(admin_client, "concept-1").get("curation_state") == "harvested"


def test_an_empty_list_attr_is_allowed(admin_client):
    """78 of the 97 carry empty key_properties; only strings are checked for
    emptiness."""
    r = admin_client.put("/api/concept/concept-1", json=_full(key_properties=[]))
    assert r.status_code == 200, r.text


def test_editing_a_concept_that_does_not_exist_is_404(admin_client):
    r = admin_client.put("/api/concept/concept-nope", json=_full())
    assert r.status_code == 404


def test_the_edit_form_is_on_the_page(admin_client):
    text = admin_client.get("/concepts/concept-1").text
    assert "concept-edit-form" in text
    assert "this marks it reviewed" in text
    assert "harvest-2026-09-25-abcd1234" in text, "the batch is not shown"


# --- retire -----------------------------------------------------------------


def test_retiring_flips_the_state_and_keeps_every_edge(admin_client):
    before = admin_client.app.state.conn.execute(
        "SELECT COUNT(*) FROM edges").fetchone()[0]
    r = admin_client.post("/api/concept-retire/concept-1")
    assert r.status_code == 200, r.text
    a = _attrs(admin_client, "concept-1")
    assert a["curation_state"] == "retired"
    assert a["reviewed_by"] == "reviewer-root"
    assert admin_client.app.state.conn.execute(
        "SELECT 1 FROM nodes WHERE id = 'concept-1'").fetchone()
    assert admin_client.app.state.conn.execute(
        "SELECT COUNT(*) FROM edges").fetchone()[0] == before


def test_a_retired_concept_leaves_the_vocabulary_through_the_route(admin_client):
    """THE WHOLE POINT. A retirement that left the name in the prompt would be
    a retirement that did not happen."""
    conn = admin_client.app.state.conn
    assert "Zswap" in build_vocabulary_context(conn)
    admin_client.post("/api/concept-retire/concept-1")
    assert "Zswap" not in build_vocabulary_context(conn)
    assert "Grace Period" in build_vocabulary_context(conn)


def test_a_retired_concept_is_admissible_under_no_route(admin_client):
    from graph.rules import admission_state, seminal_concepts

    conn = admin_client.app.state.conn
    admin_client.post("/api/concept-retire/concept-1")
    assert admission_state(conn, "concept-1", seminal_concepts(conn)) == "retired"


def test_editing_a_retired_concept_un_retires_it(admin_client):
    """Un-retiring is the edit route and not a third endpoint. 'reviewed' is
    the honest state: a human looked at it and decided it belongs."""
    admin_client.post("/api/concept-retire/concept-1")
    r = admin_client.put("/api/concept/concept-1", json=_full())
    assert r.status_code == 200
    assert _attrs(admin_client, "concept-1")["curation_state"] == "reviewed"
    assert "Zswap" in build_vocabulary_context(admin_client.app.state.conn)


def test_an_anonymous_caller_cannot_retire(anon_client):
    before = _attrs(anon_client, "concept-1")
    assert anon_client.post("/api/concept-retire/concept-1").status_code == 401
    assert _attrs(anon_client, "concept-1") == before


def test_retiring_something_that_is_not_a_concept_is_404(admin_client):
    assert admin_client.post("/api/concept-retire/src-1").status_code == 404


# --- the store functions, without a router ---------------------------------


def test_the_store_refuses_an_unnamed_editor(conn):
    _concept(conn, "concept-1", "Zswap")
    conn.commit()
    with pytest.raises(ValueError, match="name the human"):
        update_concept(conn, "concept-1", _full(), reviewed_by="")
    with pytest.raises(ValueError, match="name the human"):
        retire_concept(conn, "concept-1", reviewed_by="")


def test_the_store_refuses_a_node_of_the_wrong_kind(conn):
    add_node(conn, "sub-1", "Subsystem", {"name": "Memory"})
    conn.commit()
    with pytest.raises(ValueError, match="No Concept"):
        update_concept(conn, "sub-1", _full(), reviewed_by="r")


def test_an_edit_does_not_disturb_other_attrs(conn):
    """code_examples and the score fields sit on 78 of the 97 and must survive
    an edit — update_node_attrs merges rather than replaces."""
    _concept(conn, "concept-1", "Zswap", code_examples=[{"label": "x"}],
             harvest_batch="harvest-1")
    conn.commit()
    update_concept(conn, "concept-1", _full(), reviewed_by="r")
    a = get_node(conn, "concept-1")["attrs"]
    assert a["code_examples"] == [{"label": "x"}]
    assert a["harvest_batch"] == "harvest-1", "the batch id must survive review"
