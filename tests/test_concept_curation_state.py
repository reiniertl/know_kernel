"""IFC-KK-CONCEPT-CURATION-STATE: whether a human has ever looked at a Concept.

INV-KK-CONCEPT-CURATION-VOCABULARY closes the state set to three words and
makes absent mean "nobody has reviewed this" — which on 2026-09-25 is true of
all 97 Concepts in the corpus, none of which carries any record of human
attention.

THE LOAD-BEARING TEST IN THIS FILE IS THE FIRST ONE. The four attributes are
OPTIONAL and must stay that way: add_node rejects a Concept missing any
REQUIRED attribute, so promoting curation_state to required would make every
one of the 97 existing Concepts unwritable at a stroke. Everything else here
is a detail; that is the property that cannot regress.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from graph.concept_vocabulary import (
    CURATION_ATTRS,
    CURATION_STATES,
    DEFAULT_CURATION_STATE,
    curation_reviewed,
    curation_state,
)
from graph.engine import add_node
from graph.rules import RULES_BY_KIND, check_concept_curation_state
from graph.schema import REQUIRED_ATTRS, init_db
from web.app import create_app

SIX = {
    "name": "Grace Period", "description": "d",
    "artifact_class": "abstracted-mechanism", "key_properties": [],
    "tradeoffs": [], "design_rationale": "r",
}


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "curation.db")
    yield c
    c.close()


def _concept(conn, cid, **extra):
    add_node(conn, cid, "Concept", {**SIX, "name": cid, **extra})
    return cid


# --- the four attributes are optional ---------------------------------------


def test_the_curation_attrs_are_not_required(conn):
    """All 97 existing Concepts carry none of them. If any became required,
    every one of them would stop being writable — which is why this is
    asserted against REQUIRED_ATTRS directly and not only through a write."""
    for attr in CURATION_ATTRS:
        assert attr not in REQUIRED_ATTRS["Concept"], f"{attr} must stay optional"
    assert REQUIRED_ATTRS["Concept"] == (
        "name", "description", "artifact_class",
        "key_properties", "tradeoffs", "design_rationale",
    )


def test_a_concept_with_none_of_them_still_writes(conn):
    """The shape of all 97 as of 2026-09-25."""
    _concept(conn, "concept-legacy")
    conn.commit()
    row = conn.execute(
        "SELECT 1 FROM nodes WHERE id = 'concept-legacy'").fetchone()
    assert row is not None


def test_a_concept_with_none_of_them_still_renders_in_the_browser(tmp_path):
    """Adding the vocabulary must not make the existing corpus unviewable."""
    path = tmp_path / "browser.db"
    c = init_db(path)
    add_node(c, "concept-legacy", "Concept", {**SIX, "name": "Grace Period"})
    c.commit()
    c.close()
    with TestClient(create_app(str(path))) as client:
        text = client.get("/concepts").text
    assert "Grace Period" in text


def test_a_concept_carrying_curation_state_round_trips(tmp_path):
    path = tmp_path / "browser.db"
    c = init_db(path)
    add_node(c, "concept-new", "Concept", {
        **SIX, "name": "Quiescent State Detection",
        "curation_state": "harvested", "harvest_batch": "batch-2026-09-25",
        "reviewed_by": "", "reviewed_at": ""})
    c.commit()
    stored = c.execute(
        "SELECT json_extract(attrs, '$.curation_state'), "
        "json_extract(attrs, '$.harvest_batch') "
        "FROM nodes WHERE id = 'concept-new'").fetchone()
    c.close()
    assert stored == ("harvested", "batch-2026-09-25")
    with TestClient(create_app(str(path))) as client:
        assert "Quiescent State Detection" in client.get("/concepts").text


# --- absent means harvested -------------------------------------------------


def test_absent_reads_as_harvested_not_as_a_fourth_state():
    """Absent is the same CLAIM as harvested — nobody has reviewed this — and
    reading it as anything else would read it as false."""
    assert curation_state({}) == DEFAULT_CURATION_STATE == "harvested"
    assert curation_state(None) == "harvested"
    assert curation_state({"curation_state": ""}) == "harvested"


def test_an_unknown_value_is_returned_rather_than_corrected():
    """Correcting it here would hide exactly what the sweep reports."""
    assert curation_state({"curation_state": "bogus"}) == "bogus"


def test_only_reviewed_counts_as_reviewed():
    assert curation_reviewed({"curation_state": "reviewed"}) is True
    assert curation_reviewed({}) is False
    assert curation_reviewed({"curation_state": "harvested"}) is False
    assert curation_reviewed({"curation_state": "retired"}) is False, (
        "a retired entry was looked at, but it is not trustworthy vocabulary")


# --- the sweep --------------------------------------------------------------


def test_the_sweep_is_clean_against_a_corpus_that_predates_the_field(conn):
    """The shape of the real database on 2026-09-25: 97 Concepts, none
    carrying any curation attribute. Absent is lawful, so this baseline is
    what the first harvest will be measured against."""
    for i in range(5):
        _concept(conn, f"concept-{i}")
    conn.commit()
    assert check_concept_curation_state(conn) == []


def test_a_state_outside_the_vocabulary_is_a_violation(conn):
    _concept(conn, "concept-ok", curation_state="harvested")
    _concept(conn, "concept-bad", curation_state="approved")
    conn.commit()
    v = check_concept_curation_state(conn)
    assert [x.node_id for x in v] == ["concept-bad"]
    assert v[0].rule == "concept-curation-vocabulary"
    assert "harvested, reviewed, retired" in v[0].message


def test_reviewed_without_a_reviewer_is_a_violation(conn):
    """An unsigned review is not a review, and this is the one claim in the
    vocabulary that can be false rather than merely unreadable."""
    _concept(conn, "concept-unsigned", curation_state="reviewed")
    conn.commit()
    v = check_concept_curation_state(conn)
    assert len(v) == 2, "both reviewed_by and reviewed_at are missing"
    assert {x.rule for x in v} == {"concept-curation-unsigned"}


def test_a_signed_review_passes(conn):
    _concept(conn, "concept-signed", curation_state="reviewed",
             reviewed_by="curator@example.com", reviewed_at="2026-09-25")
    conn.commit()
    assert check_concept_curation_state(conn) == []


def test_a_malformed_review_date_is_a_violation(conn):
    _concept(conn, "concept-dated", curation_state="reviewed",
             reviewed_by="curator@example.com", reviewed_at="last Tuesday")
    conn.commit()
    v = check_concept_curation_state(conn)
    assert [x.rule for x in v] == ["concept-curation-date"]


def test_retired_needs_no_signature(conn):
    """What retiring DOES is not decided here — PROMPT 2 owns that. This only
    records that the value is lawful."""
    _concept(conn, "concept-retired", curation_state="retired")
    conn.commit()
    assert check_concept_curation_state(conn) == []


def test_the_sweep_is_not_a_write_gate(conn):
    """Deliberately outside RULES_BY_KIND, for the reason
    check_concept_admission is: a per-node rule runs on every add_node and
    would make writes with nothing to do with this field fail because of the
    97 Concepts that predate it."""
    names = [f.__name__ for fs in RULES_BY_KIND.values() for f in fs]
    assert "check_concept_curation_state" not in names
    # And the proof it does not gate: a Concept with a bogus state still writes.
    _concept(conn, "concept-bogus", curation_state="nonsense")
    conn.commit()
    assert conn.execute(
        "SELECT 1 FROM nodes WHERE id = 'concept-bogus'").fetchone() is not None
    assert len(check_concept_curation_state(conn)) == 1


def test_the_vocabulary_is_closed():
    assert CURATION_STATES == ("harvested", "reviewed", "retired")
