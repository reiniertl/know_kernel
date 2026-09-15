"""Tests for ingest.paper_summary — IFC-KK-PAPER-SUMMARY, ALG-KK-SUMMARY-SET.

Covers INV-KK-SUMMARY-STATE-VOCABULARY and both carve-outs documented in the
module: the Source is not revalidated after a write, and summary nodes are
removed with direct SQL rather than through the engine's delete helpers.
"""

from __future__ import annotations

import pytest

from graph.engine import add_node, get_node
from graph.rules import check_summary_state_valid
from graph.schema import init_db
from ingest.paper_summary import (
    PRESENT_STATES,
    SUMMARY_STATES,
    clear_summary,
    get_summary,
    set_summary,
    summary_is_present,
)


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "summary_test.db")
    yield c
    c.close()


def _source(c, source_id="src-1", source_type="preprint"):
    """A Source with NO Advisory — which is what most real Sources look like."""
    add_node(c, source_id, "Source", {
        "url": f"https://example.com/{source_id}.pdf",
        "source_type": source_type,
        "license": "MIT",
        "title": f"Paper {source_id}",
    })
    return source_id


# --- INV-KK-SUMMARY-STATE-VOCABULARY -------------------------------------


def test_state_vocabulary_is_frozen_and_ordered():
    assert SUMMARY_STATES == (
        "absent",
        "llm-extracted",
        "human-reviewed",
        "human-authored",
        "rejected",
    )
    assert isinstance(SUMMARY_STATES, tuple)


def test_presence_test_excludes_absent_and_rejected():
    """'rejected' ranks with 'absent', not above it — the verdict reads the state."""
    assert PRESENT_STATES == ("llm-extracted", "human-reviewed", "human-authored")
    for state in PRESENT_STATES:
        assert summary_is_present(state) is True
    for state in ("absent", "rejected"):
        assert summary_is_present(state) is False
    assert summary_is_present(None) is False


def test_set_summary_rejects_unknown_state(conn):
    src = _source(conn)
    with pytest.raises(ValueError, match="Invalid summary state"):
        set_summary(conn, src, "text", "machine-guessed")


@pytest.mark.parametrize("state", SUMMARY_STATES)
def test_every_declared_state_is_accepted(conn, state):
    """The vocabulary is not merely declared — every value in it actually works."""
    src = _source(conn)
    text = "" if state == "absent" else "A summary."
    reviewer = "rvr-1" if state in ("human-reviewed", "human-authored") else ""
    result = set_summary(conn, src, text, state, reviewed_by=reviewer)
    assert result.ok
    assert result.state == state


def test_rule_rejects_a_state_outside_the_vocabulary(conn):
    """The RULES_BY_KIND entry is a real rule, not an empty list."""
    src = _source(conn)
    set_summary(conn, src, "A summary.", "llm-extracted")
    summary_id = get_summary(conn, src)["id"]

    assert check_summary_state_valid(conn, summary_id) is None

    # Write a bad state past the store, the way a stray script would.
    conn.execute(
        "UPDATE nodes SET attrs = json_set(attrs, '$.state', 'bogus') WHERE id = ?",
        (summary_id,),
    )
    violation = check_summary_state_valid(conn, summary_id)
    assert violation is not None
    assert "bogus" in violation.message


# --- validation before writing -------------------------------------------


def test_set_summary_rejects_a_non_source(conn):
    add_node(conn, "sub1", "Subsystem", {"name": "scheduler"})
    with pytest.raises(ValueError, match="does not exist"):
        set_summary(conn, "sub1", "A summary.", "llm-extracted")


def test_set_summary_rejects_an_unknown_id(conn):
    with pytest.raises(ValueError, match="does not exist"):
        set_summary(conn, "src-nope", "A summary.", "llm-extracted")


@pytest.mark.parametrize("text", ["", "   ", None])
def test_set_summary_rejects_empty_text_for_a_present_state(conn, text):
    src = _source(conn)
    with pytest.raises(ValueError, match="must be non-empty"):
        set_summary(conn, src, text, "llm-extracted")


def test_absent_cannot_carry_text(conn):
    """State and content may not disagree; the verdict trusts the state."""
    src = _source(conn)
    with pytest.raises(ValueError, match="cannot carry summary text"):
        set_summary(conn, src, "A summary.", "absent")


@pytest.mark.parametrize("state", ["human-reviewed", "human-authored"])
def test_human_states_require_a_reviewer(conn, state):
    src = _source(conn)
    with pytest.raises(ValueError, match="requires reviewed_by"):
        set_summary(conn, src, "A summary.", state)


def test_nothing_is_written_when_validation_fails(conn):
    src = _source(conn)
    with pytest.raises(ValueError):
        set_summary(conn, src, "A summary.", "not-a-state")
    assert get_summary(conn, src) is None


# --- ALG-KK-SUMMARY-SET: one per paper, replace not accumulate ------------


def test_set_summary_creates_node_and_edge(conn):
    src = _source(conn)
    result = set_summary(conn, src, "First.", "llm-extracted", model="claude-opus-5")
    assert result.created is True
    assert result.summary_id.startswith("psum-")

    node = get_summary(conn, src)
    assert node["kind"] == "PaperSummary"
    assert node["attrs"]["text"] == "First."
    assert node["attrs"]["state"] == "llm-extracted"
    assert node["attrs"]["model"] == "claude-opus-5"
    assert node["attrs"]["set_at"]

    edges = conn.execute(
        "SELECT source_id, target_id FROM edges WHERE kind = 'summarizes-paper'"
    ).fetchall()
    assert edges == [(result.summary_id, src)]


def test_resetting_replaces_rather_than_accumulates(conn):
    src = _source(conn)
    first = set_summary(conn, src, "First.", "llm-extracted")
    second = set_summary(conn, src, "Second.", "human-authored", reviewed_by="rvr-1")

    assert second.created is False
    assert second.summary_id == first.summary_id

    assert conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind = 'PaperSummary'"
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind = 'summarizes-paper'"
    ).fetchone()[0] == 1

    node = get_summary(conn, src)
    assert node["attrs"]["text"] == "Second."
    assert node["attrs"]["state"] == "human-authored"
    assert node["attrs"]["reviewed_by"] == "rvr-1"


def test_summaries_on_different_papers_are_independent(conn):
    a = _source(conn, "src-a")
    b = _source(conn, "src-b")
    set_summary(conn, a, "Summary A.", "llm-extracted")
    set_summary(conn, b, "Summary B.", "llm-extracted")
    assert get_summary(conn, a)["attrs"]["text"] == "Summary A."
    assert get_summary(conn, b)["attrs"]["text"] == "Summary B."


def test_clear_summary_is_idempotent(conn):
    src = _source(conn)
    set_summary(conn, src, "First.", "llm-extracted")

    assert clear_summary(conn, src).rows == 1
    assert get_summary(conn, src) is None
    assert conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind = 'summarizes-paper'"
    ).fetchone()[0] == 0

    # Second call changes nothing and does not raise.
    assert clear_summary(conn, src).rows == 0


# --- carve-out 1, proven rather than asserted ----------------------------


def test_source_without_an_advisory_accepts_a_summary(conn):
    """The carve-out that makes this module work at all.

    rules.check_source_has_advisory requires every Source to have an Advisory,
    and the great majority of real Sources do not. If set_summary revalidated the
    Source after writing, this would raise AdmissibilityError and the feature
    would be unusable on the actual corpus.
    """
    from graph.rules import validate_node

    src = _source(conn)

    # Establish the premise rather than assuming it: this Source really is
    # invalid by the Source rules, and would be rejected by a revalidating write.
    violations = validate_node(conn, src, "Source")
    assert violations, "premise broken: the fixture Source unexpectedly validates"

    result = set_summary(conn, src, "A summary of an unadvised paper.", "llm-extracted")
    assert result.ok
    assert get_summary(conn, src)["attrs"]["text"] == "A summary of an unadvised paper."


def test_clearing_a_summary_does_not_trip_source_validation(conn):
    """Carve-out 2: engine.delete_node/delete_edge would raise here."""
    src = _source(conn)
    set_summary(conn, src, "A summary.", "llm-extracted")
    assert clear_summary(conn, src).ok
    assert get_node(conn, src) is not None
