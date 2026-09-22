"""Search lands on the paper, and the graph stops being the destination.

INV-KK-WEB-SEARCH-RESULT-ROUTED: a result links to the page that renders it.
INV-KK-WEB-SEARCH-FULL-ACCESS: ranking may reorder, it may not exclude.
INV-KK-WEB-QUERY-BOUNDED: the cap is the only thing that removes a match.
ALG-KK-WEB-NODE-DETAIL: /concepts/{id} redirects a Source to its paper page.

Before 2026-09-22 a topical search returned thirty Evidence nodes, each linking
to /concepts/{id} — a page of raw edges whose every exit was another page of
raw edges. The paper was never reachable from the search box.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from graph.engine import add_edge, add_node
from graph.schema import init_db
from web.app import create_app
from web.routes import route_for_node


TOPIC = "quiescent"


@pytest.fixture
def nav_client(tmp_path):
    """One paper about the topic, buried under forty Evidence nodes that also
    match it. That burial is the defect: Evidence sorts before Source
    alphabetically and there are thousands of them in the real corpus."""
    db_path = tmp_path / "nav.db"
    conn = init_db(db_path)
    add_node(conn, "src-target", "Source", {
        "url": "https://example.com/rcu.pdf", "source_type": "paper",
        "license": "MIT", "title": f"A Paper About {TOPIC} state detection"})
    add_node(conn, "concept-target", "Concept", {
        "name": f"{TOPIC.title()} State Detection", "description": "x",
        "artifact_class": "abstracted-mechanism", "key_properties": [],
        "tradeoffs": [], "design_rationale": "n/a"})
    for i in range(40):
        add_node(conn, f"ev-{i:03}", "Evidence", {
            "artifact_class": "A", "contamination_level": "L0",
            "text": f"Body {i} discussing {TOPIC} state detection at length."})
    add_edge(conn, "sourced-from", "ev-000", "src-target")
    conn.commit()
    conn.close()
    app = create_app(str(db_path))
    with TestClient(app) as c:
        yield c


def _results(client, q):
    r = client.get("/api/search", params={"q": q})
    assert r.status_code == 200
    return r.json()


# --- the resolver -----------------------------------------------------------


def test_a_source_resolves_to_the_paper_page():
    assert route_for_node("Source", "src-1") == "/paper/src-1"


@pytest.mark.parametrize("kind", ["Concept", "Evidence", "KernelInvariant",
                                  "FailureMode", "Proposal"])
def test_every_other_kind_resolves_to_the_node_view(kind):
    assert route_for_node(kind, "n-1") == "/concepts/n-1"


def test_the_resolver_is_total():
    """A kind absent from the table must still get a working link. The search
    box has to return something clickable for every kind the graph holds, and
    a KeyError here would render a blank row."""
    url = route_for_node("AKindNobodyHasWrittenYet", "n-1")
    assert url and url.endswith("n-1")


# --- the load-bearing test --------------------------------------------------


def test_a_search_for_a_paper_links_to_the_paper(nav_client):
    """The defect was entirely in the href, so assert the href. A test that
    only checked the row was present would have passed against the bug."""
    hits = [r for r in _results(nav_client, TOPIC) if r["kind"] == "Source"]
    assert hits, "the paper did not come back at all"
    assert hits[0]["url"] == "/paper/src-target"


def test_the_paper_outranks_forty_evidence_nodes(nav_client):
    """The ranking defect. 'ORDER BY kind' is alphabetical and Evidence sorts
    before Source, so the 30-row cap filled with bodies before reaching the
    paper. This passes today only because Source is now ordered first."""
    results = _results(nav_client, TOPIC)
    kinds = [r["kind"] for r in results]
    assert kinds[0] == "Source", f"first result was {kinds[0]}"
    assert kinds.index("Source") < kinds.index("Evidence")


def test_the_rendered_fragment_carries_the_paper_href(nav_client):
    """The JSON is not what a person clicks. Drive the HTMX path too."""
    r = nav_client.get("/api/search", params={"q": TOPIC},
                       headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert 'href="/paper/src-target"' in r.text
    assert 'href="/concepts/src-target"' not in r.text


# --- the constraint the fix must not break ----------------------------------


def test_evidence_is_still_reachable(nav_client):
    """INV-KK-WEB-SEARCH-FULL-ACCESS. Excluding Evidence would have been the
    easy fix and would have withheld a kind from the reader. Ranking reorders;
    it does not gate."""
    kinds = {r["kind"] for r in _results(nav_client, TOPIC)}
    assert "Evidence" in kinds
    assert "Source" in kinds


def test_the_kind_parameter_still_narrows(nav_client):
    """The parameter is a caller-supplied narrowing, and that has not changed."""
    only = _results(nav_client, TOPIC)
    assert len({r["kind"] for r in only}) > 1
    r = nav_client.get("/api/search", params={"q": TOPIC, "kind": "Evidence"})
    assert {x["kind"] for x in r.json()} == {"Evidence"}


def test_the_cap_still_bounds_the_response(nav_client):
    """INV-KK-WEB-QUERY-BOUNDED: 41 nodes match, 30 come back."""
    assert len(_results(nav_client, TOPIC)) == 30


# --- the redirect (ALG-KK-WEB-NODE-DETAIL) ----------------------------------


def test_a_source_at_the_node_route_redirects_to_its_paper(nav_client):
    r = nav_client.get("/concepts/src-target", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/paper/src-target"


def test_the_redirect_fixes_every_caller_not_just_search(nav_client):
    """health.html, impact.html, feed.html, radar.html, link_review.html and
    this view's own neighbour links all send ids to /concepts/{id}. Redirecting
    at the route is what fixes all of them at once."""
    r = nav_client.get("/concepts/src-target")
    assert r.status_code == 200
    assert "A Paper About" in r.text


def test_a_non_source_still_renders_in_place(nav_client):
    r = nav_client.get("/concepts/concept-target", follow_redirects=False)
    assert r.status_code == 200


def test_an_unknown_id_still_404s(nav_client):
    assert nav_client.get("/concepts/no-such-node").status_code == 404
