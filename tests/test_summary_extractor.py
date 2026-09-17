"""Tests for ingest.summary_extractor — ALG-KK-SUMMARY-EXTRACT.

Covers INV-KK-SUMMARY-LLM-NEVER-HUMAN-STATE and
INV-KK-SUMMARY-EXTRACT-INPUT-BASIS, plus the batch in ingest.cli_summaries
(ALG-KK-SUMMARY-EXTRACT-BATCH).

NO TEST MAKES A NETWORK CALL. Every path takes an injected client, following
tests/test_ingest_extractor.py's MockLLMClient.
"""

from __future__ import annotations

import json

import pytest

from graph.engine import add_edge, add_node
from graph.schema import init_db
from ingest.cli_summaries import candidate_source_ids, run_batch
from ingest.paper_summary import SUMMARY_STATES, get_summary, set_summary
from ingest.summary_extractor import (
    BASIS_ABSTRACT,
    BASIS_EVIDENCE,
    EXTRACTOR_STATE,
    MIN_INPUT_CHARS,
    MIN_SUMMARY_CHARS,
    SKIP_INVALID_RESPONSE,
    SKIP_NO_USABLE_INPUT,
    extract_summary,
    parse_llm_response,
    select_input,
    validate_summary,
)

GOOD = "This paper delegates Linux paging policy to user space via eBPF hooks. It reports a measurable reduction in page-fault latency on NUMA hardware."


class MockLLMClient:
    """Records what it was asked, returns what it was told to."""

    def __init__(self, text: str | None = None, raise_on_call: bool = False):
        self.text = json.dumps({"summary": GOOD}) if text is None else text
        self.calls: list[dict] = []
        self.raise_on_call = raise_on_call

    def create_message(self, model: str, system: str, user: str, max_tokens: int) -> dict:
        if self.raise_on_call:
            raise AssertionError("the model must not be called on this path")
        self.calls.append(
            {"model": model, "system": system, "user": user, "max_tokens": max_tokens}
        )
        return {"text": self.text, "prompt_tokens": 11, "response_tokens": 22}


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "summary_extract_test.db")
    yield c
    c.close()


def _paper(c, source_id="src-1", abstract=None, source_type="preprint", title="A Paper About Kernel Paging Policies"):
    attrs = {
        "url": f"https://example.com/{source_id}.pdf",
        "source_type": source_type,
        "license": "MIT",
        "title": title,
    }
    if abstract:
        attrs["abstract"] = abstract
    add_node(c, source_id, "Source", attrs)
    return source_id


def _evidence(c, source_id, text, evidence_id=None):
    evidence_id = evidence_id or f"ev-{source_id}"
    add_node(c, evidence_id, "Evidence", {
        "artifact_class": "A", "contamination_level": "L0", "text": text,
    })
    add_edge(c, "sourced-from", evidence_id, source_id)
    return evidence_id


# --- parsing and validation ----------------------------------------------


def test_well_formed_response_parses_and_validates():
    parsed = parse_llm_response(json.dumps({"summary": GOOD}))
    # validate_summary returns the validated fields as a dict, not bare prose,
    # now that one call yields four of them.
    assert validate_summary(parsed)["summary"] == GOOD


def test_fenced_json_is_parsed():
    fenced = "```json\n" + json.dumps({"summary": GOOD}) + "\n```"
    assert validate_summary(parse_llm_response(fenced))["summary"] == GOOD


@pytest.mark.parametrize("bad", [
    "not json at all",
    "[1, 2, 3]",
    '{"summary": 42}',
    '{"summary": ""}',
    '{"wrong_key": "' + "x" * 80 + '"}',
    "",
])
def test_malformed_responses_do_not_validate(bad):
    assert validate_summary(parse_llm_response(bad)) is None


def test_a_too_short_summary_is_rejected():
    """Guards against 'N/A' being stored as a real summary."""
    assert validate_summary({"summary": "N/A"}) is None
    assert len("N/A") < MIN_SUMMARY_CHARS


# --- INV-KK-SUMMARY-EXTRACT-INPUT-BASIS ----------------------------------


def test_abstract_is_preferred_input(conn):
    src = _paper(conn, abstract="A" * 200)
    _evidence(conn, src, "B" * 500)
    text, basis = select_input(conn, src)
    assert basis == BASIS_ABSTRACT
    assert text.startswith("A")


def test_evidence_text_is_the_fallback(conn):
    src = _paper(conn)
    _evidence(conn, src, "B" * 500)
    text, basis = select_input(conn, src)
    assert basis == BASIS_EVIDENCE
    assert text.startswith("B")


def test_short_evidence_text_is_not_usable(conn):
    src = _paper(conn)
    _evidence(conn, src, "B" * (MIN_INPUT_CHARS - 1))
    assert select_input(conn, src) == ("", "")


def test_a_descriptive_title_is_never_an_input(conn):
    """The decisive case: 343 papers have no abstract but all have real titles.

    Falling back to the title is what research_brief_extractor does for
    ResearchBrief, and it is excluded here on purpose.
    """
    src = _paper(conn, title="PageFlex: Flexible User-space Delegation of Linux Paging Policies with eBPF")
    assert select_input(conn, src) == ("", "")

    client = MockLLMClient(raise_on_call=True)
    result = extract_summary(conn, src, client=client)
    assert result.stored is False
    assert result.skipped == SKIP_NO_USABLE_INPUT
    assert get_summary(conn, src) is None
    assert client.calls == []


def test_the_title_is_not_sent_to_the_model(conn):
    src = _paper(conn, abstract="A" * 200, title="UNIQUE-TITLE-TOKEN")
    client = MockLLMClient()
    extract_summary(conn, src, client=client)
    assert "UNIQUE-TITLE-TOKEN" not in client.calls[0]["user"]


# --- INV-KK-SUMMARY-LLM-NEVER-HUMAN-STATE --------------------------------


def test_the_state_written_is_always_llm_extracted(conn):
    src = _paper(conn, abstract="A" * 200)
    result = extract_summary(conn, src, client=MockLLMClient())
    assert result.stored is True
    assert result.state == EXTRACTOR_STATE == "llm-extracted"
    assert get_summary(conn, src)["attrs"]["state"] == "llm-extracted"


def test_the_extractor_can_never_write_a_human_state(conn):
    """Not even a model returning a state can change it: the state is a constant."""
    src = _paper(conn, abstract="A" * 200)
    hostile = json.dumps({"summary": GOOD, "state": "human-authored", "reviewed_by": "rvr-1"})
    extract_summary(conn, src, client=MockLLMClient(text=hostile))

    node = get_summary(conn, src)
    assert node["attrs"]["state"] == "llm-extracted"
    assert node["attrs"]["reviewed_by"] == ""


def test_extractor_state_is_not_a_human_state():
    assert EXTRACTOR_STATE in SUMMARY_STATES
    assert EXTRACTOR_STATE not in ("human-reviewed", "human-authored", "rejected", "absent")


# --- nothing is written unless validation passes --------------------------


def test_a_malformed_response_writes_nothing(conn):
    src = _paper(conn, abstract="A" * 200)
    result = extract_summary(conn, src, client=MockLLMClient(text="{not json"))
    assert result.stored is False
    assert result.skipped == SKIP_INVALID_RESPONSE
    assert get_summary(conn, src) is None


def test_an_empty_summary_writes_nothing(conn):
    """The prompt asks for {"summary": ""} when the text is too thin."""
    src = _paper(conn, abstract="A" * 200)
    result = extract_summary(conn, src, client=MockLLMClient(text=json.dumps({"summary": ""})))
    assert result.stored is False
    assert get_summary(conn, src) is None


def test_dry_run_calls_no_model_and_writes_nothing(conn):
    src = _paper(conn, abstract="A" * 200)
    client = MockLLMClient(raise_on_call=True)
    result = extract_summary(conn, src, dry_run=True, client=client)
    assert result.stored is False
    assert result.basis == BASIS_ABSTRACT
    assert get_summary(conn, src) is None


def test_unknown_or_non_source_id_raises(conn):
    add_node(conn, "sub1", "Subsystem", {"name": "scheduler"})
    with pytest.raises(ValueError, match="does not exist"):
        extract_summary(conn, "src-nope", client=MockLLMClient())
    with pytest.raises(ValueError, match="does not exist"):
        extract_summary(conn, "sub1", client=MockLLMClient())


def test_re_extracting_replaces_rather_than_accumulates(conn):
    src = _paper(conn, abstract="A" * 200)
    extract_summary(conn, src, client=MockLLMClient())
    second = "A second pass produced this different summary of the very same paper text."
    extract_summary(conn, src, client=MockLLMClient(text=json.dumps({"summary": second})))

    assert conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind = 'PaperSummary'"
    ).fetchone()[0] == 1
    assert get_summary(conn, src)["attrs"]["text"] == second


# --- ALG-KK-SUMMARY-EXTRACT-BATCH ----------------------------------------


def test_batch_skips_papers_that_already_have_a_usable_summary(conn):
    a = _paper(conn, "src-a", abstract="A" * 200)
    b = _paper(conn, "src-b", abstract="B" * 200)
    set_summary(conn, b, "Already summarised by a model.", "llm-extracted")

    assert candidate_source_ids(conn) == [a]


def test_batch_never_overwrites_human_work(conn):
    src = _paper(conn, abstract="A" * 200)
    set_summary(conn, src, "A human wrote this.", "human-authored", reviewed_by="rvr-1")

    assert candidate_source_ids(conn) == []
    client = MockLLMClient(raise_on_call=True)
    run_batch(conn, client=client, pause=0)
    assert get_summary(conn, src)["attrs"]["text"] == "A human wrote this."


def test_batch_reconsiders_absent_and_rejected(conn):
    """Neither is a usable summary, so both stay candidates."""
    a = _paper(conn, "src-a", abstract="A" * 200)
    b = _paper(conn, "src-b", abstract="B" * 200)
    set_summary(conn, a, "", "absent")
    set_summary(conn, b, "A model wrote this and a human refused it.", "rejected")
    assert sorted(candidate_source_ids(conn)) == [a, b]


def test_batch_reports_basis_and_skips(conn):
    _paper(conn, "src-abs", abstract="A" * 200)
    src_ev = _paper(conn, "src-ev")
    _evidence(conn, src_ev, "B" * 500)
    _paper(conn, "src-none", title="A Real Title But Nothing Else")

    report = run_batch(conn, client=MockLLMClient(), pause=0)
    assert report.considered == 3
    assert report.stored == 2
    assert report.by_basis == {BASIS_ABSTRACT: 1, BASIS_EVIDENCE: 1}
    assert report.skipped == {SKIP_NO_USABLE_INPUT: 1}


def test_batch_ignores_non_papers(conn):
    _paper(conn, "src-news", abstract="A" * 200, source_type="media-outlet")
    assert candidate_source_ids(conn) == []


def test_batch_limit_is_respected(conn):
    for i in range(4):
        _paper(conn, f"src-{i}", abstract="A" * 200)
    assert len(candidate_source_ids(conn, limit=2)) == 2


def test_batch_is_resumable(conn):
    """A second run considers only what the first did not store."""
    _paper(conn, "src-a", abstract="A" * 200)
    _paper(conn, "src-b", abstract="B" * 200)

    first = run_batch(conn, limit=1, client=MockLLMClient(), pause=0)
    assert first.stored == 1

    second = run_batch(conn, client=MockLLMClient(), pause=0)
    assert second.considered == 1
    assert second.stored == 1
    assert run_batch(conn, client=MockLLMClient(raise_on_call=True), pause=0).considered == 0


# --- D-15a: the reply is prose alone --------------------------------------
#
# This block replaces the D-9 "four fields from one call" suite. Seven tests that
# existed solely to exercise key_ideas, relevance and methodology were REMOVED
# with the fields: the four-field persistence test, the one-call test, the
# prose-only partial-success test, the key_ideas bound test, the
# bad-ideas-does-not-sink-the-prose test, the blank-item test and the
# exactly-MAX_KEY_IDEAS test. The four below assert properties that survive the
# change and are rewired to a prose-only reply rather than deleted.

PROSE_REPLY = {"summary": GOOD}


def _prose_client(**overrides):
    payload = dict(PROSE_REPLY)
    payload.update(overrides)
    return MockLLMClient(json.dumps(payload))


def test_a_failing_summary_writes_nothing(conn):
    """The prose gates the whole write."""
    source_id = _paper(conn, abstract="x" * 200)

    result = extract_summary(conn, source_id, client=_prose_client(summary="N/A"))

    assert result.stored is False
    assert result.skipped == SKIP_INVALID_RESPONSE
    assert get_summary(conn, source_id) is None


def test_state_is_llm_extracted_even_when_the_reply_claims_otherwise(conn):
    """INV-KK-SUMMARY-LLM-NEVER-HUMAN-STATE: the state is never read from the model."""
    source_id = _paper(conn, abstract="x" * 200)
    client = _prose_client(state="human-authored", reviewed_by="rvr-1")

    result = extract_summary(conn, source_id, client=client)

    assert result.stored is True
    assert result.state == EXTRACTOR_STATE
    assert get_summary(conn, source_id)["attrs"]["state"] == EXTRACTOR_STATE


def test_the_prompt_asks_for_prose_alone(conn):
    """D-15a: the prompt names summary and nothing else."""
    from ingest.summary_extractor import SUMMARY_PROMPT

    assert '"summary"' in SUMMARY_PROMPT
    for retired in ("key_ideas", "relevance", "methodology"):
        assert retired not in SUMMARY_PROMPT


def test_reextraction_replaces_rather_than_duplicating(conn):
    """Idempotent at the store level."""
    source_id = _paper(conn, abstract="x" * 200)

    extract_summary(conn, source_id, client=_prose_client())
    extract_summary(conn, source_id, client=_prose_client(summary="A second summary of the paper, long enough to validate."))

    count = conn.execute(
        "SELECT count(*) FROM nodes WHERE kind = 'PaperSummary'"
    ).fetchone()[0]
    assert count == 1
    assert get_summary(conn, source_id)["attrs"]["text"].startswith("A second summary")


def test_a_legacy_four_field_reply_stores_prose_and_nothing_else(conn):
    """A model still answering in the old shape must not resurrect the fields."""
    source_id = _paper(conn, abstract="x" * 200)
    legacy = MockLLMClient(json.dumps({
        "summary": GOOD,
        "key_ideas": ["Delegates paging policy to user space."],
        "relevance": "Matters for the memory-management subsystem.",
        "methodology": "eBPF-based tracing",
    }))

    result = extract_summary(conn, source_id, client=legacy)

    assert result.stored is True
    attrs = get_summary(conn, source_id)["attrs"]
    assert attrs["text"] == GOOD
    for retired in ("key_ideas", "relevance", "methodology"):
        assert retired not in attrs
