"""Making a 465-concept review backlog something a human can finish.

MEASURED 2026-09-29: curation_state is 'harvested' for 465 of 465. Edit,
retire, merge, the priority sort and the collision badge all ship and NOT ONE
concept has been reviewed. The backlog is the whole vocabulary, and a backlog
that size is worked in sittings.

Three affordances, and each answers a question the queue could not:
  - which entries need no reading at all (bulk retire)
  - what subsystem an entry belongs to, when the harvest declined to guess
  - how much is left
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from graph.concept_vocabulary import (
    assign_subsystem,
    build_vocabulary_context,
    curation_progress,
    curation_state,
    retire_concepts_bulk,
)
from graph.engine import add_edge, add_node, get_node
from graph.rules import concept_weight
from graph.schema import init_db
from web.app import create_app
from web.routes import WEB_MUTATION_ALLOWLIST

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


def _documented(conn, n, cid):
    """A Concept admitted by canonical documentation, not by weight."""
    add_node(conn, f"src-doc-{n}", "Source", {
        "url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/"
               f"linux.git/tree/Documentation/mm/{n}.rst",
        "source_type": "kernel-doc", "license": "GPL-2.0", "title": f"Doc {n}"})
    add_node(conn, f"ev-doc-{n}", "Evidence", {
        "artifact_class": "A", "contamination_level": "L0", "text": "t"})
    add_edge(conn, "sourced-from", f"ev-doc-{n}", f"src-doc-{n}")
    add_edge(conn, "extracted-from", cid, f"ev-doc-{n}")


def _subsystem(conn, sid, name):
    add_node(conn, sid, "Subsystem", {"name": name})
    return sid


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "backlog.db")
    yield c
    c.close()


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "web-backlog.db"
    c = init_db(path)
    # concept-cachebpf is a real id from the live corpus: CacheBPF is ONE
    # PAPER'S SYSTEM, and the id is the evidence.
    _concept(c, "concept-cachebpf", "eBPF-Customizable Page Cache")
    _concept(c, "concept-schedcp", "LLM-Driven Scheduler Optimization")
    _concept(c, "concept-real", "Page Cache")
    _paper(c, "1", "concept-real")
    _concept(c, "concept-doc", "Read-Copy-Update")
    _documented(c, "rcu", "concept-doc")
    _concept(c, "concept-xarray", "XArray")
    _subsystem(c, "sub-mm", "Memory Management")
    _subsystem(c, "sub-sched", "Scheduler")
    c.commit()
    c.close()
    return str(path)


@pytest.fixture
def curator(db):
    app = create_app(db)

    @app.middleware("http")
    async def _as_curator(request, call_next):
        request.state.user = {"username": "kate", "role": "reviewer",
                              "reviewer": "reviewer-kate"}
        return await call_next(request)

    with TestClient(app) as c:
        yield c


@pytest.fixture
def anon(db):
    with TestClient(create_app(db)) as c:
        yield c


def _attrs(client, cid):
    return json.loads(client.app.state.conn.execute(
        "SELECT attrs FROM nodes WHERE id = ?", (cid,)).fetchone()[0])


# --- bulk retire (ALG-KK-WEB-CONCEPT-RETIRE-BULK) ---------------------------


def test_the_prefixes_are_allowlisted():
    """INV-KK-WEB-MUTATION-ALLOWLISTED."""
    assert "/api/concept-retire-bulk" in WEB_MUTATION_ALLOWLIST
    assert "/api/concept-subsystem/" in WEB_MUTATION_ALLOWLIST


def test_a_bulk_retire_marks_every_one_and_signs_them(curator):
    r = curator.post("/api/concept-retire-bulk",
                     json={"ids": ["concept-cachebpf", "concept-schedcp"]})
    assert r.status_code == 200, r.text
    assert set(r.json()["retired"]) == {"concept-cachebpf", "concept-schedcp"}
    for cid in ("concept-cachebpf", "concept-schedcp"):
        a = _attrs(curator, cid)
        assert curation_state(a) == "retired"
        assert a["reviewed_by"] == "reviewer-kate"
        assert a["reviewed_at"]


def test_a_documented_concept_is_refused_whatever_else_is_true(curator):
    """DOCUMENTATION ADMITS IT under INV-KK-CONCEPT-ADMISSION's reverse route,
    and a bulk action must not be able to contradict the admission rule."""
    r = curator.post("/api/concept-retire-bulk", json={"ids": ["concept-doc"]})
    assert r.status_code == 422
    assert "concept-doc" in r.json()["refused"]
    assert curation_state(_attrs(curator, "concept-doc")) == "harvested"


def test_a_concept_carrying_papers_is_refused(curator):
    r = curator.post("/api/concept-retire-bulk", json={"ids": ["concept-real"]})
    assert r.status_code == 422
    assert "papers" in r.json()["refused"]["concept-real"].lower()


def test_one_refused_id_refuses_the_whole_call(curator):
    """A PARTIAL BULK RETIRE IS WORSE THAN NONE: a caller reading a success
    cannot tell which half happened, and the obvious retry double-signs the
    half that did."""
    r = curator.post("/api/concept-retire-bulk",
                     json={"ids": ["concept-cachebpf", "concept-real"]})
    assert r.status_code == 422
    assert r.json()["retired"] == []
    assert curation_state(_attrs(curator, "concept-cachebpf")) == "harvested"


def test_an_unknown_id_refuses_the_call_and_writes_nothing(curator):
    r = curator.post("/api/concept-retire-bulk",
                     json={"ids": ["concept-cachebpf", "concept-nope"]})
    assert r.status_code == 422
    assert curation_state(_attrs(curator, "concept-cachebpf")) == "harvested"


def test_an_anonymous_bulk_retire_is_refused_and_writes_nothing(anon):
    r = anon.post("/api/concept-retire-bulk", json={"ids": ["concept-cachebpf"]})
    assert r.status_code == 401
    assert curation_state(_attrs(anon, "concept-cachebpf")) == "harvested"


def test_a_body_reviewer_field_is_ignored(curator):
    """INV-KK-REVIEW-ATTRIBUTION-FROM-SESSION."""
    r = curator.post("/api/concept-retire-bulk",
                     json={"ids": ["concept-cachebpf"], "reviewer": "someone"})
    assert r.status_code == 200, r.text
    assert _attrs(curator, "concept-cachebpf")["reviewed_by"] == "reviewer-kate"


def test_a_missing_ids_list_is_422(curator):
    assert curator.post("/api/concept-retire-bulk", json={}).status_code == 422
    assert curator.post(
        "/api/concept-retire-bulk", json={"ids": "concept-cachebpf"}
    ).status_code == 422


def test_bulk_retired_concepts_leave_the_vocabulary(curator):
    """The one that matters most: after retirement the names appear in NO
    vocabulary context offered to any extractor."""
    curator.post("/api/concept-retire-bulk",
                 json={"ids": ["concept-cachebpf", "concept-schedcp"]})
    ctx = build_vocabulary_context(curator.app.state.conn)
    assert "Page Cache" in ctx
    assert "eBPF-Customizable Page Cache" not in ctx
    assert "LLM-Driven Scheduler Optimization" not in ctx


def test_bulk_retire_is_the_same_retirement_as_the_single_route(conn):
    """One implementation of "what retiring means". A second copy is the defect
    this codebase keeps finding."""
    a = _concept(conn, "concept-a", "Alpha")
    b = _concept(conn, "concept-b", "Beta")
    conn.commit()
    retire_concepts_bulk(conn, [a], reviewed_by="r", reviewed_at="2026-09-29")
    from graph.concept_vocabulary import retire_concept
    retire_concept(conn, b, reviewed_by="r", reviewed_at="2026-09-29")
    assert get_node(conn, a)["attrs"] == get_node(conn, b)["attrs"] | {
        "name": "Alpha"}


def test_an_unsigned_bulk_retire_is_refused(conn):
    _concept(conn, "concept-a", "Alpha")
    conn.commit()
    with pytest.raises(ValueError, match="name the human"):
        retire_concepts_bulk(conn, ["concept-a"], reviewed_by="")


def test_an_empty_list_is_a_no_op(conn):
    r = retire_concepts_bulk(conn, [], reviewed_by="r")
    assert r.ok and r.retired == [] and r.refused == {}


# --- subsystem assignment (ALG-KK-WEB-CONCEPT-SUBSYSTEM) --------------------


def test_a_curator_assigns_the_subsystem_the_harvest_declined(curator):
    r = curator.post("/api/concept-subsystem/concept-xarray/sub-mm")
    assert r.status_code == 200, r.text
    assert curator.app.state.conn.execute(
        "SELECT target_id FROM edges WHERE kind='belongs-to' AND source_id=?",
        ("concept-xarray",)).fetchone()[0] == "sub-mm"


def test_assigning_twice_replaces_rather_than_adds(curator):
    """belongs-to is cardinality one, and clearing first is also what makes the
    call idempotent against UNIQUE (kind, source_id, target_id)."""
    curator.post("/api/concept-subsystem/concept-xarray/sub-mm")
    r = curator.post("/api/concept-subsystem/concept-xarray/sub-sched")
    assert r.status_code == 200, r.text
    rows = curator.app.state.conn.execute(
        "SELECT target_id FROM edges WHERE kind='belongs-to' AND source_id=?",
        ("concept-xarray",)).fetchall()
    assert [r[0] for r in rows] == ["sub-sched"]


def test_assigning_the_same_subsystem_twice_does_not_raise(curator):
    curator.post("/api/concept-subsystem/concept-xarray/sub-mm")
    r = curator.post("/api/concept-subsystem/concept-xarray/sub-mm")
    assert r.status_code == 200, r.text


def test_an_unknown_subsystem_is_404_and_writes_nothing(curator):
    r = curator.post("/api/concept-subsystem/concept-xarray/sub-nope")
    assert r.status_code == 404
    assert curator.app.state.conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind='belongs-to' AND source_id=?",
        ("concept-xarray",)).fetchone()[0] == 0


def test_this_route_may_not_create_a_subsystem(conn):
    """Seeding the taxonomy is human curation, not a side effect of using it —
    the same rule that stops the extractor minting a Concept."""
    _concept(conn, "concept-a", "Alpha")
    conn.commit()
    before = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind='Subsystem'").fetchone()[0]
    with pytest.raises(ValueError, match="No Subsystem"):
        assign_subsystem(conn, "concept-a", "sub-invented")
    assert conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind='Subsystem'").fetchone()[0] == before


def test_assigning_does_not_mark_the_concept_reviewed(curator):
    """CLASSIFYING IS NOT READING. A curator who files XArray under Memory
    Management has not necessarily checked its description, and a review state
    that overcounts is the mirror of the undercount the edit route avoids."""
    curator.post("/api/concept-subsystem/concept-xarray/sub-mm")
    assert curation_state(_attrs(curator, "concept-xarray")) == "harvested"


def test_an_anonymous_assign_is_refused_and_writes_nothing(anon):
    r = anon.post("/api/concept-subsystem/concept-xarray/sub-mm")
    assert r.status_code == 401
    assert anon.app.state.conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind='belongs-to' AND source_id=?",
        ("concept-xarray",)).fetchone()[0] == 0


def test_the_detail_page_offers_every_subsystem_and_no_more(curator):
    page = curator.get("/concepts/concept-xarray").text
    assert "Memory Management" in page
    assert "Scheduler" in page
    assert 'value="sub-mm"' in page


# --- progress (IFC-KK-CONCEPT-REVIEW-PRIORITY) ------------------------------


def test_the_progress_count_is_the_corpus_and_not_the_page(curator):
    """A COUNT OF THE PAGE WOULD READ "50 harvested" FOREVER and be worse than
    no count, exactly as a filter narrowing only the page was judged worse than
    none."""
    page = curator.get("/concepts?per_page=10").text
    assert "Review progress" in page
    conn = curator.app.state.conn
    total = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind='Concept'").fetchone()[0]
    assert curation_progress(conn)["total"] == total


def test_absent_curation_state_counts_as_harvested(conn):
    """All the Concepts that predate the field assert the same thing: nobody has
    reviewed them."""
    _concept(conn, "concept-a", "Alpha")
    _concept(conn, "concept-b", "Beta", curation_state="harvested")
    _concept(conn, "concept-c", "Gamma", curation_state="reviewed",
             reviewed_by="r", reviewed_at="2026-09-29")
    _concept(conn, "concept-d", "Delta", curation_state="retired",
             reviewed_by="r", reviewed_at="2026-09-29")
    conn.commit()
    p = curation_progress(conn)
    assert p == {"harvested": 2, "reviewed": 1, "retired": 1, "total": 4}


def test_the_count_moves_when_a_bulk_retire_lands(curator):
    conn = curator.app.state.conn
    before = curation_progress(conn)
    curator.post("/api/concept-retire-bulk",
                 json={"ids": ["concept-cachebpf", "concept-schedcp"]})
    after = curation_progress(conn)
    assert after["retired"] == before["retired"] + 2
    assert after["harvested"] == before["harvested"] - 2
    assert after["total"] == before["total"], "retiring is never a delete"
