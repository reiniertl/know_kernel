"""INV-KK-LINK-CONFIRMATION-STATE and ALG-KK-WEB-LINK-REVIEW.

The distinction these pin: INV-KK-EXTRACT-EVIDENCE-RECORDED made a link
CHECKABLE — the grounding verdict is on the edge and can be shown to anyone. It
did not make the link CHECKED. A model can produce prose whose bigrams all
appear in the paper and still describe something the paper does not support.
Only a person reading both closes that gap, and these tests are about recording
that they did — never about claiming it happened.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from graph.engine import add_edge, add_node
from graph.rules import check_link_confirmations
from graph.schema import init_db
from ingest.link_confirmation import (
    CONFIRMATION_KEYS,
    CONFIRMATION_STATES,
    clear_confirmation,
    count_confirmations,
    get_confirmation,
    set_confirmation,
)
from web.app import create_app


def _seed(db_path):
    conn = init_db(db_path)
    add_node(conn, "src-1", "Source", {
        "url": "https://example.com/p.pdf", "source_type": "preprint",
        "license": "MIT", "title": "A Paper About Scheduling"})
    add_node(conn, "ev-1", "Evidence", {
        "artifact_class": "licensed-evidence", "contamination_level": "weak-copyleft",
        "text": "The scheduler orders runnable tasks by virtual runtime."})
    add_node(conn, "concept-1", "Concept", {
        "name": "Virtual Runtime Ordering",
        "description": "Tasks are ordered by accumulated CPU time.",
        "artifact_class": "abstracted-mechanism", "key_properties": ["fair"],
        "tradeoffs": ["bookkeeping"], "design_rationale": "Fairness."})
    add_node(conn, "rvr-1", "Reviewer", {"name": "Reinier"})
    add_edge(conn, "sourced-from", "ev-1", "src-1")
    add_edge(conn, "extracted-from", "concept-1", "ev-1", {
        "grounded": False, "ungrounded_count": 3,
        "ungrounded": ["accumulated CPU", "are ordered", "Tasks are"],
        "basis": "evidence-text", "basis_sha256": "abc123",
        "model": "claude-sonnet-4-6", "checked_at": "2026-09-21"})
    conn.commit()
    return conn


@pytest.fixture
def conn(tmp_path):
    c = _seed(tmp_path / "confirm.db")
    yield c
    c.close()


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "confirm_web.db"
    _seed(db_path).close()
    with TestClient(create_app(str(db_path))) as c:
        yield c


# --- the state --------------------------------------------------------------


def test_the_vocabulary_is_two_words_and_absence():
    """'unreviewed' is deliberately NOT a stored value: writing it onto 3,169
    edges would be a migration whose only effect is to assert ignorance."""
    assert CONFIRMATION_STATES == ("confirmed", "rejected")
    assert "unreviewed" not in CONFIRMATION_STATES


def test_a_fresh_link_is_unreviewed_by_construction(conn):
    assert get_confirmation(conn, "concept-1", "ev-1") is None


def test_confirming_records_who_and_when(conn):
    r = set_confirmation(conn, "concept-1", "ev-1", "confirmed", "rvr-1",
                         note="Read the paper; the concept is there.")
    assert r.confirmation == "confirmed"
    assert r.confirmed_by == "rvr-1"
    assert r.confirmed_at

    attrs = json.loads(conn.execute(
        "SELECT attrs FROM edges WHERE kind='extracted-from'").fetchone()[0])
    assert attrs["confirmation"] == "confirmed"
    assert attrs["confirmed_by"] == "rvr-1"
    assert attrs["confirmed_at"] == r.confirmed_at
    assert attrs["confirmation_note"].startswith("Read the paper")


def test_rejecting_is_recorded_the_same_way(conn):
    set_confirmation(conn, "concept-1", "ev-1", "rejected", "rvr-1",
                     note="Excerpt is in the paper but supports nothing.")
    assert get_confirmation(conn, "concept-1", "ev-1") == "rejected"


def test_an_anonymous_confirmation_is_refused(conn):
    with pytest.raises(ValueError, match="requires a reviewer"):
        set_confirmation(conn, "concept-1", "ev-1", "confirmed", "")
    assert get_confirmation(conn, "concept-1", "ev-1") is None


def test_an_unknown_reviewer_is_refused(conn):
    with pytest.raises(ValueError, match="does not exist"):
        set_confirmation(conn, "concept-1", "ev-1", "confirmed", "rvr-nope")


def test_an_invalid_state_is_refused(conn):
    with pytest.raises(ValueError, match="Invalid confirmation"):
        set_confirmation(conn, "concept-1", "ev-1", "probably", "rvr-1")


def test_confirming_leaves_the_grounding_verdict_intact(conn):
    """The two records are independent: a person's judgement must not overwrite
    what the machine measured."""
    set_confirmation(conn, "concept-1", "ev-1", "confirmed", "rvr-1")
    attrs = json.loads(conn.execute(
        "SELECT attrs FROM edges WHERE kind='extracted-from'").fetchone()[0])
    assert attrs["ungrounded_count"] == 3
    assert attrs["basis_sha256"] == "abc123"
    assert attrs["grounded"] is False


def test_a_confirmation_can_be_undone(conn):
    """A reviewer must be able to correct a mistake without the only remedy
    being to assert the opposite."""
    set_confirmation(conn, "concept-1", "ev-1", "confirmed", "rvr-1", note="oops")
    assert clear_confirmation(conn, "concept-1", "ev-1") is True
    assert get_confirmation(conn, "concept-1", "ev-1") is None

    attrs = json.loads(conn.execute(
        "SELECT attrs FROM edges WHERE kind='extracted-from'").fetchone()[0])
    assert not any(k in attrs for k in CONFIRMATION_KEYS)
    assert attrs["basis_sha256"] == "abc123"   # verdict still untouched
    assert clear_confirmation(conn, "concept-1", "ev-1") is False  # idempotent


def test_an_empty_note_is_stored_as_no_note(conn):
    set_confirmation(conn, "concept-1", "ev-1", "confirmed", "rvr-1", note="   ")
    attrs = json.loads(conn.execute(
        "SELECT attrs FROM edges WHERE kind='extracted-from'").fetchone()[0])
    assert "confirmation_note" not in attrs


# --- the counts -------------------------------------------------------------


def test_the_count_is_correct_and_starts_at_zero(conn):
    assert count_confirmations(conn) == {
        "total": 1, "confirmed": 0, "rejected": 0, "unreviewed": 1}
    set_confirmation(conn, "concept-1", "ev-1", "confirmed", "rvr-1")
    assert count_confirmations(conn) == {
        "total": 1, "confirmed": 1, "rejected": 0, "unreviewed": 0}


def test_diagnostics_reports_the_counts(conn):
    from graph.diagnostics import diagnose_graph

    report = diagnose_graph(conn)
    assert report.links_total == 1
    assert report.links_confirmed == 0
    set_confirmation(conn, "concept-1", "ev-1", "confirmed", "rvr-1")
    assert diagnose_graph(conn).links_confirmed == 1


# --- the rule ---------------------------------------------------------------


def test_the_sweep_accepts_a_well_formed_confirmation(conn):
    set_confirmation(conn, "concept-1", "ev-1", "confirmed", "rvr-1")
    assert check_link_confirmations(conn) == []


def test_a_reviewer_recorded_without_an_outcome_is_a_violation(conn):
    """A link cannot record who looked at it without recording what they said."""
    conn.execute("UPDATE edges SET attrs = json_set(attrs, '$.confirmed_by', 'rvr-1') "
                 "WHERE kind = 'extracted-from'")
    v = check_link_confirmations(conn)
    assert v and "no confirmation" in v[0].message


def test_an_unknown_state_written_past_the_store_is_caught(conn):
    conn.execute("UPDATE edges SET attrs = json_set(attrs, '$.confirmation', 'maybe') "
                 "WHERE kind = 'extracted-from'")
    v = check_link_confirmations(conn)
    assert v and "not one of" in v[0].message


def test_confirmation_keys_do_not_break_the_evidence_sweep(conn):
    """INV-KK-EXTRACT-EVIDENCE-RECORDED says an in-scope edge carries EXACTLY
    its key set. Without the permitted-additions clause, confirming a link
    would have made it a violation."""
    from graph.rules import check_link_evidence_recorded

    assert check_link_evidence_recorded(conn).conforming == 1
    set_confirmation(conn, "concept-1", "ev-1", "confirmed", "rvr-1", note="ok")
    sweep = check_link_evidence_recorded(conn)
    assert sweep.violations == []
    assert sweep.conforming == 1


def test_an_arbitrary_extra_key_is_still_rejected(conn):
    """The additions are a fixed set, not an open door."""
    from graph.rules import check_link_evidence_recorded

    conn.execute("UPDATE edges SET attrs = json_set(attrs, '$.vibes', 'good') "
                 "WHERE kind = 'extracted-from'")
    v = check_link_evidence_recorded(conn).violations
    assert v and "vibes" in v[0].message


# --- the completeness dimension --------------------------------------------


def test_links_confirmed_is_binary_and_in_the_dimension_list():
    from ingest.paper_completeness import BINARY_DIMENSIONS

    assert "links_confirmed" in BINARY_DIMENSIONS
    from ingest.paper_completeness import CompletenessVerdict
    assert CompletenessVerdict.__annotations__["links_confirmed"] == "bool"


def test_links_confirmed_is_false_until_every_link_is_confirmed(conn):
    from ingest.paper_completeness import compute_completeness

    assert compute_completeness(conn, "src-1").links_confirmed is False
    set_confirmation(conn, "concept-1", "ev-1", "confirmed", "rvr-1")
    assert compute_completeness(conn, "src-1").links_confirmed is True


def test_one_unconfirmed_link_is_enough_to_make_it_false(conn):
    from ingest.paper_completeness import compute_completeness

    add_node(conn, "concept-2", "Concept", {
        "name": "Second", "description": "Another mechanism.",
        "artifact_class": "abstracted-mechanism", "key_properties": [],
        "tradeoffs": [], "design_rationale": "n/a"})
    add_edge(conn, "extracted-from", "concept-2", "ev-1")

    set_confirmation(conn, "concept-1", "ev-1", "confirmed", "rvr-1")
    assert compute_completeness(conn, "src-1").links_confirmed is False
    set_confirmation(conn, "concept-2", "ev-1", "confirmed", "rvr-1")
    assert compute_completeness(conn, "src-1").links_confirmed is True


def test_a_rejected_link_does_not_count_as_confirmed(conn):
    from ingest.paper_completeness import compute_completeness

    set_confirmation(conn, "concept-1", "ev-1", "rejected", "rvr-1")
    assert compute_completeness(conn, "src-1").links_confirmed is False


def test_a_paper_with_no_links_is_not_vacuously_confirmed(tmp_path):
    """The whole reason for the at-least-one clause. Without it the 2,049
    papers that have no concept link would read as complete."""
    from ingest.paper_completeness import compute_completeness

    c = init_db(tmp_path / "empty.db")
    add_node(c, "src-empty", "Source", {
        "url": "https://example.com/e.pdf", "source_type": "preprint",
        "license": "MIT", "title": "A Paper With No Links"})
    add_node(c, "ev-empty", "Evidence", {
        "artifact_class": "licensed-evidence", "contamination_level": "weak-copyleft"})
    add_edge(c, "sourced-from", "ev-empty", "src-empty")
    c.commit()

    verdict = compute_completeness(c, "src-empty")
    assert verdict.links_concept is False
    assert verdict.links_confirmed is False
    c.close()


# --- the surface ------------------------------------------------------------


def test_the_review_page_shows_concept_paper_and_verdict_together(client):
    page = client.get("/links/review").text
    assert "Virtual Runtime Ordering" in page
    assert "A Paper About Scheduling" in page
    assert "accumulated CPU" in page          # the ungrounded phrases, shown
    assert "Not yet read by anyone." in page


def test_an_unconfirmed_link_is_visibly_unconfirmed_not_absent(client):
    """The failure this guards: hiding unconfirmed links would make the corpus
    look verified rather than make it verified."""
    page = client.get("/links/review?state=unreviewed").text
    assert "Virtual Runtime Ordering" in page
    assert "Not yet read by anyone." in page
    assert "0</strong> confirmed" in page.replace("<strong>", "<strong>")


def test_confirming_through_the_route_records_who_and_when(client):
    resp = client.put("/api/link-confirm/concept-1/ev-1",
                      json={"confirmation": "confirmed", "reviewer_id": "rvr-1",
                            "note": "Checked against the PDF."})
    assert resp.status_code == 200
    assert resp.json()["confirmed_by"] == "rvr-1"
    assert resp.json()["confirmed_at"]

    page = client.get("/links/review?state=confirmed").text
    assert "rvr-1" in page
    assert "Checked against the PDF." in page


def test_the_route_refuses_an_unsigned_confirmation(client):
    resp = client.put("/api/link-confirm/concept-1/ev-1",
                      json={"confirmation": "confirmed"})
    assert resp.status_code == 422
    assert "reviewer" in resp.json()["error"]


def test_the_route_404s_on_a_link_that_does_not_exist(client):
    resp = client.put("/api/link-confirm/concept-1/ev-nope",
                      json={"confirmation": "confirmed", "reviewer_id": "rvr-1"})
    assert resp.status_code == 404


def test_the_confirm_route_is_on_the_mutation_allowlist():
    from web.routes import WEB_MUTATION_ALLOWLIST

    assert "/api/link-confirm/" in WEB_MUTATION_ALLOWLIST


def test_confirming_updates_the_paper_verdict(client):
    client.put("/api/link-confirm/concept-1/ev-1",
               json={"confirmation": "confirmed", "reviewer_id": "rvr-1"})
    assert "Links confirmed" in client.get("/paper/src-1").text


def test_the_state_gates_nothing(client):
    """INV-KK-COMPLETENESS-ADVISORY. An unconfirmed link is filtered from no
    default list and blocked from no route."""
    unfiltered = client.get("/links/review?state=all").text
    assert "Virtual Runtime Ordering" in unfiltered
    # still reachable everywhere it was before anyone reviewed anything
    assert client.get("/paper/src-1").status_code == 200
    assert client.get("/concepts/concept-1").status_code == 200

    # The unfiltered intake view still lists the paper. Nothing is withheld on
    # the strength of a link nobody has reviewed.
    assert "src-1" in client.get("/intake").text

    # And the unreviewed link is still counted in links_concept, which is the
    # dimension somebody would be tempted to make conditional on confirmation.
    from ingest.paper_completeness import compute_completeness
    verdict = compute_completeness(client.app.state.conn, "src-1")
    assert verdict.links_concept is True
    assert verdict.links_confirmed is False


def test_the_health_page_reports_the_confirmation_counts(client):
    text = client.get("/health").text
    assert "onfirmed" in text
    assert client.get("/api/diagnostics").json()["links_total"] == 1
