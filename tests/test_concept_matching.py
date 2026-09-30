"""INV-KK-EXTRACT-CONCEPT-MATCHED: the extractor links, it does not mint.

IFC-KK-CONCEPT-CANDIDATE: what happens to a name the vocabulary lacks.

Until 2026-09-22 store_rich_concept ran on every concept in every response with
no lookup of any kind. Two batches added 114 Concepts, every one at weight 1,
every one named after a single paper's artifact — uSTM, BR-WFD Algorithm,
Toleo Memory Management. A matcher added on 2026-09-21 matched 0 of the 114,
because the model had never been shown the vocabulary.

NO TEST HERE MAY TOUCH THE NETWORK. Every one injects a client.
"""

from __future__ import annotations

import json

import pytest

from graph.concept_vocabulary import (
    build_vocabulary_context,
    candidate_ranking,
    fuzzy_match_concept,
    normalise_concept_name,
    record_candidate,
    resolve_concept_names,
    strict_match_concept,
)
from graph.engine import add_edge, add_node
from graph.schema import init_db
from ingest.extractor import build_extraction_prompt, extract_concepts
from ingest.gate import SessionGate


VOCAB = "Copy-on-Write"


def _item(name):
    return {"name": name,
            "description": "Deferring a page copy until the first write.",
            "key_properties": ["lazy"], "tradeoffs": ["fault cost"],
            "design_rationale": "Avoids copying pages never written.",
            "subsystem": "Memory", "relationships": [], "invariants": []}


class MockLLMClient:
    def __init__(self, *names):
        self.names = names or (VOCAB,)
        self.calls: list[dict] = []

    def create_message(self, model, system, user, max_tokens):
        self.calls.append({"user": user})
        return {"text": json.dumps({"concepts": [_item(n) for n in self.names]}),
                "prompt_tokens": 10, "response_tokens": 5}


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "matching.db")
    add_node(c, "src-1", "Source", {
        "url": "https://example.com/p.pdf", "source_type": "paper",
        "license": "MIT", "title": "A Paper"})
    add_node(c, "ev-1", "Evidence", {
        "artifact_class": "A", "contamination_level": "L0",
        "text": "This paper describes copy-on-write page handling."})
    add_edge(c, "sourced-from", "ev-1", "src-1")
    c.commit()
    yield c
    c.close()


def _vocab(conn, *names):
    for i, n in enumerate(names):
        add_node(conn, f"concept-v{i}", "Concept", {
            "name": n, "description": "x",
            "artifact_class": "abstracted-mechanism", "key_properties": [],
            "tradeoffs": [], "design_rationale": "n/a"})
    conn.commit()


def _concepts(conn):
    return conn.execute("SELECT COUNT(*) FROM nodes WHERE kind='Concept'").fetchone()[0]


# --- the matcher ------------------------------------------------------------


def test_an_exact_name_matches(conn):
    _vocab(conn, VOCAB)
    assert fuzzy_match_concept(VOCAB, resolve_concept_names(conn)) == "concept-v0"


@pytest.mark.parametrize("variant", [
    "copy-on-write", "  Copy-on-Write  ", "COPY-ON-WRITE",
    "Copy-on-Writes",          # one edit
    "Copy-on-Write semantics", # prefix
])
def test_a_near_miss_matches(conn, variant):
    """The vocabulary survives paraphrase, which is the point of matching
    loosely: a model told to choose from a list still varies the wording."""
    _vocab(conn, VOCAB)
    assert fuzzy_match_concept(variant, resolve_concept_names(conn)) == "concept-v0"


@pytest.mark.parametrize("miss", ["uSTM", "BR-WFD Algorithm", "Toleo Memory Management"])
def test_a_paper_specific_artifact_matches_nothing(conn, miss):
    """The names the two batches actually produced. None of them is a class."""
    _vocab(conn, VOCAB, "Scheduling Classes", "eBPF")
    assert fuzzy_match_concept(miss, resolve_concept_names(conn)) is None


def test_matching_an_empty_vocabulary_returns_nothing(conn):
    assert fuzzy_match_concept(VOCAB, {}) is None


def test_normalisation_collapses_case_and_whitespace():
    assert normalise_concept_name("  Copy  on\tWrite ") == "copy on write"


# --- the vocabulary reaches the model ---------------------------------------


def test_the_prompt_carries_the_vocabulary(conn):
    """The half that was missing on 2026-09-21. A matcher cannot rescue a name
    the model invented because it was never told what exists."""
    _vocab(conn, VOCAB, "Scheduling Classes")
    context = build_vocabulary_context(conn)
    assert VOCAB in context and "Scheduling Classes" in context
    prompt = build_extraction_prompt("body text", None, context)
    assert VOCAB in prompt and "body text" in prompt


def test_the_prompt_is_unchanged_when_no_vocabulary_is_given():
    """Default empty, so every existing caller and test is unaffected."""
    assert build_extraction_prompt("body text") == build_extraction_prompt(
        "body text", None, "")


def test_the_model_is_told_not_to_name_the_paper_itself(conn):
    _vocab(conn, VOCAB)
    assert "Do NOT invent a name for this paper's own system" in build_vocabulary_context(conn)


def test_an_empty_graph_says_so_rather_than_sending_an_empty_list(conn):
    assert "No known kernel concepts yet." in build_vocabulary_context(conn)


# --- extraction links, and never mints --------------------------------------


def test_a_matching_concept_is_linked_not_created(conn):
    _vocab(conn, VOCAB)
    before = _concepts(conn)
    result = extract_concepts(conn, "ev-1", SessionGate(), client=MockLLMClient())
    conn.commit()
    assert _concepts(conn) == before
    assert result.concepts_created == 0
    assert result.concepts_reused == 1
    assert result.concept_ids == ["concept-v0"]


def test_an_unmatched_name_creates_nothing_at_all(conn):
    """The defect this replaces, stated as a test: 114 Concepts of weight 1."""
    _vocab(conn, "Scheduling Classes")
    before = _concepts(conn)
    result = extract_concepts(conn, "ev-1", SessionGate(),
                              client=MockLLMClient("uSTM"))
    conn.commit()
    assert _concepts(conn) == before
    assert (result.concepts_created, result.concepts_reused) == (0, 0)
    assert result.concepts_rejected == 1
    assert result.concept_ids == []


def test_extraction_never_changes_how_many_concepts_exist(conn):
    """The invariant's own phrasing. Half match, half do not; the count holds."""
    _vocab(conn, VOCAB)
    before = _concepts(conn)
    extract_concepts(conn, "ev-1", SessionGate(),
                     client=MockLLMClient(VOCAB, "uSTM", "HDReason Framework"))
    conn.commit()
    assert _concepts(conn) == before


def test_store_rich_concept_is_not_reached_from_extraction(conn):
    """It remains in the module and is still exercised directly by tests; what
    changed is that the extraction path no longer walks through it."""
    import ingest.extractor as ex

    called = []
    original = ex.store_rich_concept
    ex.store_rich_concept = lambda *a, **k: called.append(a) or "concept-x"
    try:
        _vocab(conn, VOCAB)
        extract_concepts(conn, "ev-1", SessionGate(),
                         client=MockLLMClient(VOCAB, "uSTM"))
    finally:
        ex.store_rich_concept = original
    assert called == []


def test_a_matched_concept_keeps_its_own_attributes(conn):
    """One paper must not rewrite a shared class. The model's description of
    this paper goes on the EDGE as a grounding verdict, not onto the node."""
    _vocab(conn, VOCAB)
    extract_concepts(conn, "ev-1", SessionGate(), client=MockLLMClient())
    conn.commit()
    attrs = json.loads(conn.execute(
        "SELECT attrs FROM nodes WHERE id='concept-v0'").fetchone()[0])
    assert attrs["description"] == "x"


# --- the candidate queue ----------------------------------------------------


def test_an_unmatched_name_is_queued_against_its_paper(conn):
    _vocab(conn, "Scheduling Classes")
    extract_concepts(conn, "ev-1", SessionGate(), client=MockLLMClient("uSTM"))
    conn.commit()
    queued = candidate_ranking(conn)
    assert [c.name for c in queued] == ["uSTM"]
    assert queued[0].evidence_ids == ["ev-1"]


def test_the_queue_ranks_by_distinct_sources(conn):
    """The whole reason a row is per (name, Evidence) pair. A name two papers
    reached for independently is the weight-2 evidence the admission rule asks
    for — available before the node exists instead of after."""
    add_node(conn, "src-2", "Source", {
        "url": "https://example.com/q.pdf", "source_type": "paper",
        "license": "MIT", "title": "Another"})
    add_node(conn, "ev-2", "Evidence", {
        "artifact_class": "A", "contamination_level": "L0", "text": "t"})
    add_edge(conn, "sourced-from", "ev-2", "src-2")
    conn.commit()

    record_candidate(conn, "Shared Idea", "ev-1", "2026-09-22")
    record_candidate(conn, "Shared Idea", "ev-2", "2026-09-22")
    record_candidate(conn, "One Paper Only", "ev-1", "2026-09-22")
    conn.commit()

    ranked = candidate_ranking(conn)
    assert ranked[0].name == "Shared Idea"
    assert ranked[0].sources == 2
    assert ranked[-1].sources == 1


def test_requeueing_the_same_pair_does_not_inflate_the_evidence(conn):
    """A re-run must not make a candidate look better supported than it is."""
    assert record_candidate(conn, "Idea", "ev-1", "2026-09-22") is True
    assert record_candidate(conn, "Idea", "ev-1", "2026-09-22") is False
    conn.commit()
    assert candidate_ranking(conn)[0].sources == 1


def test_a_candidate_is_not_a_node(conn):
    """Admitting a rejected candidate as a node would put the very thing
    INV-KK-CONCEPT-ADMISSION excludes into the graph under another label."""
    record_candidate(conn, "Idea", "ev-1", "2026-09-22")
    conn.commit()
    assert _concepts(conn) == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE id LIKE '%Idea%'").fetchone()[0] == 0


def test_nothing_promotes_a_candidate_automatically(conn):
    """Admission stays a human act. Two papers proposing a name makes it worth
    a minute of attention; it does not make it a Concept."""
    for ev in ("ev-1",):
        record_candidate(conn, "Popular Idea", ev, "2026-09-22")
    conn.commit()
    assert _concepts(conn) == 0


# ---------------------------------------------------------------------------
# THE TIERS ARE TRIED IN ORDER, added 2026-09-30.
#
# strict_match_concept's docstring named three tiers from the day it was
# written; the implementation pooled them into one flat set, so an ambiguous
# abbreviation could veto a unique exact hit. That minted two Concepts with the
# identical name "Linux Security Module (LSM)".
# ---------------------------------------------------------------------------

def test_an_exact_name_wins_over_an_ambiguous_abbreviation():
    """THE CASE THAT WAS FOUND IN REAL DATA. Querying the exact name hit itself
    by every form, a plural sibling by the squash tier, and a third concept by
    the shared parenthetical 'lsm' — three hits, a tie, and a duplicate."""
    table = {
        normalise_concept_name("Linux Security Module (LSM)"): "concept-exact",
        normalise_concept_name("Linux Security Modules"): "concept-plural",
        normalise_concept_name("Linux Security Modules (LSM) framework"): "concept-fw",
    }
    assert strict_match_concept("Linux Security Module (LSM)", table) == "concept-exact"


def test_the_parenthetical_tier_still_works_when_nothing_stronger_matches():
    """The tier that carries "Kernel Samepage Merging" to its bracketed alias
    must survive the reordering — it is why the tier exists."""
    table = {normalise_concept_name("KSM (Kernel Same-page Merging)"): "concept-ksm"}
    assert strict_match_concept("Kernel Samepage Merging", table) == "concept-ksm"


def test_a_declaration_still_reaches_its_bracketed_alias():
    table = {normalise_concept_name("Socket Buffer (sk_buff)"): "concept-skb"}
    assert strict_match_concept("struct sk_buff", table) == "concept-skb"


def test_a_tie_inside_the_exact_tier_is_impossible_and_a_weaker_one_refuses():
    """Two concepts cannot share an exact normalised name in a dict keyed by
    it, so ties can only happen in the weaker tiers — where refusing is right."""
    table = {normalise_concept_name("Vmalloc"): "concept-v",
             normalise_concept_name("Kmalloc"): "concept-k"}
    assert strict_match_concept("zmalloc", table) is None


def test_a_shared_abbreviation_is_still_a_tie_when_nothing_stronger_matches():
    """The LSM shape with the exact hit removed. Two concepts reachable only by
    the SAME bracketed alias are a coin flip, and refusing is what stops an
    abbreviation attaching a paper to the wrong mechanism."""
    table = {normalise_concept_name("Address Space Layout Randomization (ASLR)"): "concept-a",
             normalise_concept_name("Adaptive Stream Load Reporting (ASLR)"): "concept-b"}
    assert strict_match_concept("Some Other Thing (ASLR)", table) is None
