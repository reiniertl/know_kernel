"""The concept browser — the surface that makes a vocabulary curatable.

ALG-KK-WEB-CONCEPTS-LIST: the paginated vocabulary.
ALG-KK-WEB-CONCEPT-PAPERS: the papers behind one concept, which are the same
    rows INV-KK-CONCEPT-ADMISSION counts to decide whether it is admissible.
INV-KK-WEB-QUERY-BOUNDED: both routes bound their fetch to the page size.
INV-KK-WEB-SEARCH-RESULT-ROUTED: every paper row lands on /paper/{id}.

Until these routes existed NOTHING COULD REGISTER A CONCEPT: the extractor
stopped minting on 2026-09-22 and store_rich_concept became unreachable, so the
vocabulary was frozen at 97 with no way in but hand-written SQL.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from graph.engine import add_edge, add_node
from graph.schema import init_db
from web.app import create_app


def _concept(conn, cid, name):
    add_node(conn, cid, "Concept", {
        "name": name, "description": f"What {name} is.",
        "artifact_class": "abstracted-mechanism", "key_properties": [],
        "tradeoffs": [], "design_rationale": "r"})
    return cid


def _paper(conn, n, title=None):
    add_node(conn, f"src-{n}", "Source", {
        "url": f"https://example.com/{n}.pdf", "source_type": "paper",
        "license": "MIT", "title": title or f"Paper {n}", "venue": "OSDI"})
    add_node(conn, f"ev-{n}", "Evidence", {
        "artifact_class": "licensed-evidence",
        "contamination_level": "weak-copyleft", "text": "t"})
    add_edge(conn, "sourced-from", f"ev-{n}", f"src-{n}")
    return f"ev-{n}"


def _link(conn, cid, eid):
    add_edge(conn, "extracted-from", cid, eid)


@pytest.fixture
def db(tmp_path):
    """A vocabulary with one concept of each admission state.

    heavy   — 3 papers, admissible on evidence
    thin    — 1 paper, below the bar and with no marker
    marked  — 1 paper AND a defined-by edge, admissible by the seminal route
    orphan  — no papers at all
    """
    path = tmp_path / "browser.db"
    conn = init_db(path)
    for c, n in (("concept-heavy", "Scheduling Classes"), ("concept-thin", "Zswap"),
                 ("concept-marked", "Futex"), ("concept-orphan", "Devicetree")):
        _concept(conn, c, n)
    add_node(conn, "sub-1", "Subsystem", {"name": "Memory"})
    add_edge(conn, "belongs-to", "concept-heavy", "sub-1")
    add_node(conn, "k-1", "Kernel", {
        "name": "Linux Mainline", "description": "Upstream.", "kernel_type": "monolithic"})
    add_node(conn, "k-2", "Kernel", {
        "name": "PREEMPT_RT", "description": "Realtime.", "kernel_type": "monolithic"})
    add_edge(conn, "implemented-in", "concept-heavy", "k-1")
    add_edge(conn, "implemented-in", "concept-heavy", "k-2")

    for i in (1, 2, 3):
        _link(conn, "concept-heavy", _paper(conn, f"h{i}", f"Heavy paper {i}"))
    _link(conn, "concept-thin", _paper(conn, "t1"))
    _link(conn, "concept-marked", _paper(conn, "m1"))
    add_edge(conn, "defined-by", "concept-marked", "src-m1")
    conn.commit()
    conn.close()
    return str(path)


@pytest.fixture
def client(db):
    with TestClient(create_app(db)) as c:
        yield c


# --- the list ---------------------------------------------------------------

def test_the_list_renders_every_concept_with_its_admission_state(client):
    text = client.get("/concepts").text
    assert "Scheduling Classes" in text
    assert "Zswap" in text
    for state in ("admissible", "thin", "unlinked", "seminal"):
        assert state in text, f"no row reported {state}"


def test_a_row_carries_subsystem_papers_and_kernels(client):
    text = client.get("/concepts").text
    assert "Memory" in text, "subsystem missing"
    assert "Linux Mainline" in text and "PREEMPT_RT" in text, "kernels missing"
    assert "/concepts/concept-heavy/papers" in text, "paper count is not a link"


def test_the_seminal_marker_admits_a_concept_that_weight_alone_would_not(client):
    """concept-marked has ONE paper — below ADMISSIBLE_WEIGHT — and is
    admissible only because a human named the Source that defined it.

    This is the pair that matters. concept-thin has exactly the same weight and
    must NOT read as admissible, or the marker means nothing.
    """
    from graph.rules import admission_state, seminal_concepts
    import sqlite3
    conn = sqlite3.connect(client.app.state.conn.execute(
        "PRAGMA database_list").fetchone()[2])
    seminal = seminal_concepts(conn)
    assert admission_state(conn, "concept-marked", seminal) == "seminal"
    assert admission_state(conn, "concept-thin", seminal) == "thin"
    conn.close()


def test_the_list_is_bounded_by_per_page(tmp_path):
    """INV-KK-WEB-QUERY-BOUNDED, with MORE concepts than fit on a page.

    per_page has a floor of 10, so a four-concept fixture cannot demonstrate
    truncation at all — it needs a vocabulary larger than the smallest legal
    page. 25 concepts over a page of 10 is the smallest honest case.
    """
    path = tmp_path / "many_concepts.db"
    conn = init_db(path)
    for i in range(25):
        _concept(conn, f"concept-{i:02d}", f"Concept {i:02d}")
    conn.commit()
    conn.close()

    with TestClient(create_app(str(path))) as c:
        first = c.get("/concepts?per_page=10&page=1").text
        second = c.get("/concepts?per_page=10&page=2").text
        third = c.get("/concepts?per_page=10&page=3").text

        assert first.count("<td>\n        <a href=\"/concepts/concept-") == 10, \
            "page 1 rendered more rows than per_page"
        assert "Concept 00" in first and "Concept 09" in first
        assert "Concept 10" not in first, "page 1 leaked a row from page 2"
        assert "Concept 10" in second and "Concept 00" not in second
        assert "Concept 24" in third
        # 25 concepts, 10 per page: page 3 holds the last 5 and offers no next.
        assert "page=4" not in third, "a next link past the end of the corpus"


def test_per_page_is_refused_outside_its_bounds(client):
    assert client.get("/concepts?per_page=9").status_code == 422
    assert client.get("/concepts?per_page=201").status_code == 422
    assert client.get("/concepts?page=0").status_code == 422


def test_the_name_filter_narrows_the_list(client):
    text = client.get("/concepts?q=zswap").text
    assert "Zswap" in text
    assert "Scheduling Classes" not in text


# --- the papers route -------------------------------------------------------

def test_the_papers_route_lists_every_paper_behind_a_concept(client):
    text = client.get("/concepts/concept-heavy/papers").text
    for i in (1, 2, 3):
        assert f"Heavy paper {i}" in text


def test_every_paper_row_links_to_the_paper_and_not_back_into_the_graph(client):
    """INV-KK-WEB-SEARCH-RESULT-ROUTED — the graph is the index, the paper is
    the destination. A row linking to /concepts/{id} would rebuild exactly the
    navigation defect search_results.html had."""
    text = client.get("/concepts/concept-heavy/papers").text
    assert 'href="/paper/src-h1"' in text
    assert 'href="/concepts/src-h1"' not in text


def test_the_papers_route_is_bounded(tmp_path):
    """INV-KK-WEB-QUERY-BOUNDED on the papers route, with more papers than a page.

    This is the case that actually matters: Scheduling Classes carries 440 and
    Linux Security Modules 358, so an unbounded papers route is not a
    theoretical risk on this corpus.
    """
    path = tmp_path / "many_papers.db"
    conn = init_db(path)
    _concept(conn, "concept-big", "Big")
    for i in range(25):
        _link(conn, "concept-big", _paper(conn, f"b{i:02d}", f"Big paper {i:02d}"))
    conn.commit()
    conn.close()

    with TestClient(create_app(str(path))) as c:
        first = c.get("/concepts/concept-big/papers?per_page=10&page=1").text
        second = c.get("/concepts/concept-big/papers?per_page=10&page=2").text
        assert first.count("Big paper") == 10, "page 1 exceeded per_page"
        assert second.count("Big paper") == 10
        assert "Big paper 00" in first and "Big paper 00" not in second
        assert "25 papers" in first, "the total is still reported in full"


def test_the_papers_count_equals_the_admission_weight(client):
    """The papers page and concept_weight must agree, because they are the
    same traversal. If they ever differ, the badge is lying about its evidence."""
    import sqlite3
    from graph.rules import concept_weight
    conn = sqlite3.connect(client.app.state.conn.execute(
        "PRAGMA database_list").fetchone()[2])
    assert concept_weight(conn, "concept-heavy") == 3
    text = client.get("/concepts/concept-heavy/papers").text
    assert "3 papers" in text
    conn.close()


def test_papers_for_an_unknown_concept_is_404(client):
    assert client.get("/concepts/concept-nope/papers").status_code == 404


def test_a_concept_with_no_papers_says_so_rather_than_rendering_empty(client):
    text = client.get("/concepts/concept-orphan/papers").text
    assert "No papers are linked" in text


# --- the detail page --------------------------------------------------------

def test_the_detail_page_previews_papers_and_links_to_the_full_list(client):
    text = client.get("/concepts/concept-heavy").text
    assert "Heavy paper 1" in text
    assert 'href="/paper/src-h1"' in text
    assert "Papers (3)" in text


def test_the_detail_preview_is_bounded_and_offers_the_full_route(tmp_path):
    """A concept with more papers than the preview size must not render them
    all inline — that is the unbounded render INV-KK-WEB-QUERY-BOUNDED forbids,
    and Scheduling Classes really does carry 440."""
    path = tmp_path / "many.db"
    conn = init_db(path)
    _concept(conn, "concept-big", "Big")
    for i in range(12):
        _link(conn, "concept-big", _paper(conn, f"b{i}", f"Big paper {i}"))
    conn.commit()
    conn.close()
    with TestClient(create_app(str(path))) as c:
        text = c.get("/concepts/concept-big").text
        assert text.count("Big paper") <= 5, "detail page rendered an unbounded list"
        assert "See all 12 papers" in text
        assert c.get("/concepts/concept-big/papers").text.count("Big paper") == 12


# --- admission: the mutating half ------------------------------------------
#
# ALG-KK-WEB-CONCEPT-ADMIT and INV-KK-WEB-ADMIT-HONOURS-ADMISSION.
#
# The load-bearing pair is the two weight-1 tests: a promotion WITHOUT a
# seminal marker must be refused and one WITH a marker allowed. A suite that
# asserted only the happy path would pass against a browser that ignored the
# admission rule entirely, which is the whole thing this route could get wrong.

import json as _json

from graph.concept_vocabulary import (
    candidate_sources,
    dismiss_candidate,
    promote_candidate,
)


def _queue(conn, name, evidence_ids):
    from graph.concept_vocabulary import record_candidate
    for eid in evidence_ids:
        record_candidate(conn, name, eid, "2026-09-22")


@pytest.fixture
def queued(tmp_path):
    """Two queued candidates: one at weight 1, one at weight 2.

    Weight 1 is not the edge case here — all 43 candidates queued on
    2026-09-22 sit at exactly one Source, so the refusal path is the normal one.
    """
    path = tmp_path / "queue.db"
    conn = init_db(path)
    add_node(conn, "sub-1", "Subsystem", {"name": "Memory"})
    e1 = _paper(conn, "q1", "The paper that invented it")
    e2 = _paper(conn, "q2", "A second, independent paper")
    e3 = _paper(conn, "q3", "One lonely paper")
    _queue(conn, "Tiered Memory", [e1, e2])   # two distinct Sources
    _queue(conn, "uSTM", [e3])                 # one
    conn.commit()
    conn.close()
    return str(path)


@pytest.fixture
def admin_client(queued):
    app = create_app(queued)

    @app.middleware("http")
    async def _as_curator(request, call_next):
        request.state.user = {"username": "root", "role": "admin",
                              "reviewer": "reviewer-root"}
        return await call_next(request)

    with TestClient(app) as c:
        yield c


def _full_attrs(name):
    return {
        "name": name,
        "description": f"{name} is a mechanism described abstractly.",
        "artifact_class": "abstracted-mechanism",
        "key_properties": ["a property"],
        "tradeoffs": ["a tradeoff"],
        "design_rationale": "Why it is shaped this way.",
    }


def test_the_queue_page_lists_candidates_with_their_weight(admin_client):
    text = admin_client.get("/concepts/candidates").text
    assert "Tiered Memory" in text and "uSTM" in text
    assert "below threshold" in text, "the weight-1 candidate is not flagged"


def test_a_candidate_above_the_threshold_is_admitted_without_a_marker(admin_client):
    r = admin_client.post("/api/concept-admit/tiered memory",
                          json=_full_attrs("Tiered Memory"))
    assert r.status_code == 200, r.text
    cid = r.json()["concept_id"]

    conn = admin_client.app.state.conn
    row = conn.execute("SELECT attrs FROM nodes WHERE id = ?", (cid,)).fetchone()
    attrs = _json.loads(row[0])
    for k in ("name", "description", "artifact_class", "key_properties",
              "tradeoffs", "design_rationale"):
        assert attrs.get(k), f"promoted Concept is missing {k}"
    assert attrs["admitted_by"] == "reviewer-root"
    assert conn.execute(
        "SELECT COUNT(*) FROM concept_candidates WHERE normalised = 'tiered memory'"
    ).fetchone()[0] == 0, "the queue still offers an admitted candidate"


def test_a_weight_one_candidate_is_REFUSED_without_a_seminal_marker(admin_client):
    """The half of the pair that a happy-path-only suite would miss."""
    conn = admin_client.app.state.conn
    before = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind = 'Concept'").fetchone()[0]

    r = admin_client.post("/api/concept-admit/ustm", json=_full_attrs("uSTM"))

    assert r.status_code == 422, r.text
    assert "seminal" in r.json()["error"].lower() or "defined" in r.json()["error"].lower()
    assert conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind = 'Concept'").fetchone()[0] == before, \
        "a refused promotion still wrote a Concept"
    assert conn.execute(
        "SELECT COUNT(*) FROM concept_candidates WHERE normalised = 'ustm'"
    ).fetchone()[0] > 0, "a refused promotion consumed the queue row"


def test_a_weight_one_candidate_IS_admitted_with_a_seminal_marker(admin_client):
    """The other half. IFC-KK-CONCEPT-SEMINAL-MARKER's first use in this corpus."""
    body = {**_full_attrs("uSTM"), "seminal_source_id": "src-q3"}
    r = admin_client.post("/api/concept-admit/ustm", json=body)
    assert r.status_code == 200, r.text
    cid = r.json()["concept_id"]

    conn = admin_client.app.state.conn
    marker = conn.execute(
        "SELECT target_id FROM edges WHERE kind = 'defined-by' AND source_id = ?",
        (cid,)).fetchall()
    assert [m[0] for m in marker] == ["src-q3"], "the marker was not written"

    # And the concept now reads as admissible by the seminal route, not by weight.
    from graph.rules import admission_state, concept_weight, seminal_concepts
    assert concept_weight(conn, cid) == 0, "no extracted-from edges were invented"
    assert admission_state(conn, cid, seminal_concepts(conn)) == "seminal"


def test_the_marker_must_name_a_source_and_is_never_guessed(admin_client):
    """At weight 1 there is exactly one proposing Source, so defaulting would
    look helpful — and would promote every candidate automatically."""
    body = {**_full_attrs("uSTM"), "seminal_source_id": "sub-1"}
    r = admin_client.post("/api/concept-admit/ustm", json=body)
    assert r.status_code == 422
    assert "Source" in r.json()["error"]


def test_a_promotion_missing_any_required_attribute_is_refused(admin_client):
    for drop in ("description", "artifact_class", "key_properties",
                 "tradeoffs", "design_rationale"):
        body = _full_attrs("Tiered Memory")
        body[drop] = "" if isinstance(body[drop], str) else []
        r = admin_client.post("/api/concept-admit/tiered memory", json=body)
        assert r.status_code == 422, f"blank {drop} was accepted"
        assert drop in r.json()["error"]


def test_an_anonymous_caller_cannot_admit(queued):
    """INV-KK-REVIEW-ATTRIBUTION-FROM-SESSION: no session, no admission. The
    gate never lets an anonymous request this far, so this is the defence
    behind the defence."""
    with TestClient(create_app(queued)) as c:
        r = c.post("/api/concept-admit/tiered memory", json=_full_attrs("Tiered Memory"))
        assert r.status_code == 401
        assert c.app.state.conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE kind = 'Concept'").fetchone()[0] == 0


def test_the_body_cannot_name_the_admitting_curator(admin_client):
    """Attribution comes from the session and an admitted_by field is ignored."""
    body = {**_full_attrs("Tiered Memory"), "admitted_by": "someone-else"}
    r = admin_client.post("/api/concept-admit/tiered memory", json=body)
    assert r.status_code == 200
    attrs = _json.loads(admin_client.app.state.conn.execute(
        "SELECT attrs FROM nodes WHERE id = ?", (r.json()["concept_id"],)
    ).fetchone()[0])
    assert attrs["admitted_by"] == "reviewer-root"


def test_admitting_an_unqueued_name_is_404(admin_client):
    r = admin_client.post("/api/concept-admit/never-proposed",
                          json=_full_attrs("Never Proposed"))
    assert r.status_code == 404


def test_a_name_that_does_not_match_its_queue_row_is_refused(admin_client):
    """The form pre-fills the name and a curator may edit it; editing it into a
    different concept would admit something nobody proposed."""
    r = admin_client.post("/api/concept-admit/ustm",
                          json={**_full_attrs("Something Else Entirely"),
                                "seminal_source_id": "src-q3"})
    assert r.status_code == 422
    assert "normalise" in r.json()["error"]


def test_dismissing_a_candidate_removes_it_and_writes_no_node(admin_client):
    conn = admin_client.app.state.conn
    before = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    r = admin_client.post("/api/concept-dismiss/ustm")
    assert r.status_code == 200
    assert conn.execute(
        "SELECT COUNT(*) FROM concept_candidates WHERE normalised = 'ustm'"
    ).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == before


def test_promotion_is_one_transaction(queued):
    """A refused promotion leaves nothing behind — not a node, not an edge, not
    a consumed queue row. A half-applied admission would leave a Concept the
    queue still offers."""
    import sqlite3
    conn = sqlite3.connect(queued)
    before = (conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
              conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
              conn.execute("SELECT COUNT(*) FROM concept_candidates").fetchone()[0])
    with pytest.raises(ValueError):
        promote_candidate(conn, "ustm", _full_attrs("uSTM"), "reviewer-root")
    after = (conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
             conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
             conn.execute("SELECT COUNT(*) FROM concept_candidates").fetchone()[0])
    assert after == before
    conn.close()


def test_candidate_sources_counts_distinct_papers_not_evidence(queued):
    import sqlite3
    conn = sqlite3.connect(queued)
    assert candidate_sources(conn, "tiered memory") == 2
    assert candidate_sources(conn, "ustm") == 1
    conn.close()


def test_the_new_prefixes_are_on_the_mutation_allowlist():
    from web.routes import WEB_MUTATION_ALLOWLIST
    assert "/api/concept-admit/" in WEB_MUTATION_ALLOWLIST
    assert "/api/concept-dismiss/" in WEB_MUTATION_ALLOWLIST
