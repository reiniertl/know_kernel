"""ALG-KK-DOC-HARVEST: what canonical documentation DEFINES.

The second extraction path. ALG-KK-LLM-EXTRACT asks a PAPER "which of these
known concepts is this about" and is forbidden to mint; this asks a DOCUMENT
"what mechanisms does this document DEFINE" and writes them.

EVERY CALL HERE GOES THROUGH AN INJECTED CLIENT. A test that reached a model
API would be a defect in the test, not a stronger test.
"""

from __future__ import annotations

import json

import pytest

from graph.concept_vocabulary import CURATION_ATTRS
from graph.engine import add_edge, add_node
from graph.rules import RULES_BY_KIND, admission_state, seminal_concepts
from graph.schema import REQUIRED_ATTRS, init_db
from ingest.doc_harvest import (
    MECHANISM_CLASS,
    build_subsystem_context,
    harvest_document,
    match_subsystem_name,
    new_batch_id,
    resolve_subsystem_names,
    select_doc_evidence,
)


class MockLLMClient:
    """Returns canned replies in order. Records every call."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = []

    def create_message(self, model, system, user, max_tokens):
        self.calls.append({"model": model, "system": system, "user": user})
        reply = self._replies.pop(0) if self._replies else {"text": "{}"}
        return reply


def _reply(concepts, subsystem="Memory Management"):
    return {"text": json.dumps({"subsystem": subsystem, "concepts": concepts})}


def _mech(name, **over):
    item = {
        "name": name,
        "description": f"{name} is a mechanism that solves a real problem.",
        "artifact_class": MECHANISM_CLASS,
        "key_properties": ["bounded", "lock-free"],
        "tradeoffs": ["costs memory"],
        "design_rationale": "Because the alternative does not scale.",
    }
    item.update(over)
    return item


def _doc_source(conn, n, text="The kernel provides a mechanism for this.",
                source_type="kernel-doc"):
    add_node(conn, f"src-{n}", "Source", {
        "url": f"https://git.kernel.org/.../tree/Documentation/{n}.rst",
        "source_type": source_type, "license": "GPL-2.0", "title": f"Doc {n}"})
    add_node(conn, f"ev-{n}", "Evidence", {
        "artifact_class": "licensed-evidence",
        "contamination_level": "strong-copyleft", "text": text})
    add_edge(conn, "sourced-from", f"ev-{n}", f"src-{n}")
    return f"ev-{n}"


def _existing_concept(conn, cid, name):
    add_node(conn, cid, "Concept", {
        "name": name, "description": "d", "artifact_class": MECHANISM_CLASS,
        "key_properties": [], "tradeoffs": [], "design_rationale": "r"})
    return cid


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "harvest.db")
    add_node(c, "sub-mm", "Subsystem", {"name": "Memory Management"})
    add_node(c, "sub-sched", "Subsystem", {"name": "Scheduler"})
    yield c
    c.close()


# --- a harvested concept is written whole, with both edges ------------------


def test_a_harvested_concept_carries_all_six_attrs_and_both_edges(conn):
    """INV-KK-HARVEST-CONCEPT-COMPLETE plus the two edges
    RULES_BY_KIND["Concept"] sweeps for. Without them every harvested concept
    books two sweep violations."""
    ev = _doc_source(conn, "zswap")
    batch = new_batch_id()
    client = MockLLMClient([_reply([_mech("Compressed Swap Cache")])])

    result = harvest_document(conn, ev, batch, client=client, model="m")
    conn.commit()

    assert len(result.concepts_created) == 1
    cid = result.concepts_created[0]
    attrs = json.loads(conn.execute(
        "SELECT attrs FROM nodes WHERE id = ?", (cid,)).fetchone()[0])
    for a in REQUIRED_ATTRS["Concept"]:
        assert attrs.get(a), f"{a} missing or blank"
    assert attrs["artifact_class"] == MECHANISM_CLASS
    assert attrs["curation_state"] == "harvested"
    assert attrs["harvest_batch"] == batch

    for kind, target in (("extracted-from", ev), ("belongs-to", "sub-mm")):
        assert conn.execute(
            "SELECT 1 FROM edges WHERE kind = ? AND source_id = ? AND target_id = ?",
            (kind, cid, target)).fetchone(), f"no {kind} edge"

    # And the two sweep rules it must satisfy actually pass.
    for rule in RULES_BY_KIND["Concept"]:
        assert rule(conn, cid) is None, rule.__name__


def test_the_provenance_edge_carries_the_batch_and_a_verdict(conn):
    """The ninth provenance writer. INV-KK-EXTRACT-PROVENANCE requires the
    verdict; INV-KK-HARVEST-BATCH-REVERTIBLE requires the batch id."""
    ev = _doc_source(conn, "workqueue")
    batch = new_batch_id()
    harvest_document(conn, ev, batch,
                     client=MockLLMClient([_reply([_mech("Work Stealing")])]),
                     model="m")
    conn.commit()
    raw = conn.execute(
        "SELECT attrs FROM edges WHERE kind = 'extracted-from'").fetchone()[0]
    attrs = json.loads(raw)
    assert attrs["harvest_batch"] == batch
    assert "grounded" in attrs and "basis" in attrs and attrs["model"] == "m"


def test_the_curation_attrs_are_the_ones_the_schema_calls_optional(conn):
    ev = _doc_source(conn, "a")
    harvest_document(conn, ev, new_batch_id(),
                     client=MockLLMClient([_reply([_mech("Grace Period")])]))
    conn.commit()
    attrs = json.loads(conn.execute(
        "SELECT attrs FROM nodes WHERE kind = 'Concept'").fetchone()[0])
    for a in CURATION_ATTRS:
        assert a in attrs


# --- match first, create second --------------------------------------------


def test_a_name_already_in_the_vocabulary_attaches_and_creates_nothing(conn):
    """THE VOCABULARY IMPROVING RATHER THAN GROWING, and worth more than the
    creations. Driven through the real three-tier matcher."""
    _existing_concept(conn, "concept-zswap", "Zswap")
    ev = _doc_source(conn, "zswap")
    batch = new_batch_id()
    before = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind = 'Concept'").fetchone()[0]

    result = harvest_document(conn, ev, batch,
                              client=MockLLMClient([_reply([_mech("Zswap")])]))
    conn.commit()

    assert result.concepts_created == []
    assert result.concepts_attached == ["concept-zswap"]
    assert conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind = 'Concept'").fetchone()[0] == before
    assert conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'extracted-from' "
        "AND source_id = 'concept-zswap' AND target_id = ?", (ev,)).fetchone()


def test_an_attachment_is_what_takes_a_thin_concept_over_the_bar(conn):
    """Zswap sits at weight 1 and reads 'thin' because this corpus holds one
    paper about it. The doc takes it to weight 2 without a single new node."""
    cid = _existing_concept(conn, "concept-zswap", "Zswap")
    add_node(conn, "src-p", "Source", {
        "url": "https://example.com/p", "source_type": "preprint",
        "license": "MIT", "title": "A paper"})
    add_node(conn, "ev-p", "Evidence", {
        "artifact_class": "A", "contamination_level": "L0", "text": "t"})
    add_edge(conn, "sourced-from", "ev-p", "src-p")
    add_edge(conn, "extracted-from", cid, "ev-p")
    conn.commit()
    assert admission_state(conn, cid, seminal_concepts(conn)) == "thin"

    ev = _doc_source(conn, "zswap")
    harvest_document(conn, ev, new_batch_id(),
                     client=MockLLMClient([_reply([_mech("Zswap")])]))
    conn.commit()
    assert admission_state(conn, cid, seminal_concepts(conn)) == "admissible"


def test_a_near_miss_matches_rather_than_duplicating(conn):
    """The shared matcher fuzzes to Levenshtein 2, so a plural or a dropped
    hyphen attaches instead of minting a near-duplicate."""
    _existing_concept(conn, "concept-gp", "Grace Period")
    ev = _doc_source(conn, "rcu")
    result = harvest_document(conn, ev, new_batch_id(),
                              client=MockLLMClient([_reply([_mech("Grace Periods")])]))
    conn.commit()
    assert result.concepts_created == []
    assert result.concepts_attached == ["concept-gp"]


def test_one_document_naming_the_same_concept_twice_creates_it_once(conn):
    ev = _doc_source(conn, "a")
    result = harvest_document(
        conn, ev, new_batch_id(),
        client=MockLLMClient([_reply([_mech("Work Stealing"),
                                      _mech("Work Stealing")])]))
    conn.commit()
    assert len(result.concepts_created) == 1
    assert len(result.concepts_attached) == 1


# --- a tunable is not a mechanism -------------------------------------------


def test_a_tunable_is_rejected_and_counted(conn):
    """Without this filter an admin-guide document yields twenty parameters and
    the landfill the admission rule was written against returns in a new
    costume. The 43 names in concept_candidates are what happens when nothing
    enforces it on a path that writes."""
    ev = _doc_source(conn, "zswap")
    result = harvest_document(conn, ev, new_batch_id(), client=MockLLMClient([
        _reply([_mech("Compressed Swap Cache"),
                _mech("max_pool_percent", artifact_class="tunable"),
                _mech("zswap.enabled", artifact_class="parameter")])]))
    conn.commit()
    assert len(result.concepts_created) == 1
    assert result.rejected_not_mechanism == 2
    assert conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind = 'Concept'").fetchone()[0] == 1


def test_an_incomplete_proposal_writes_nothing_and_is_counted(conn):
    """No attribute is defaulted to satisfy the schema: a blank rationale
    passes add_node and says nothing, and is exactly the thin entry the
    admission rule exists to exclude."""
    ev = _doc_source(conn, "a")
    result = harvest_document(conn, ev, new_batch_id(), client=MockLLMClient([
        _reply([_mech("Half A Concept", design_rationale=""),
                _mech("No Properties", key_properties=[]),
                _mech("Real Mechanism")])]))
    conn.commit()
    assert len(result.concepts_created) == 1
    assert result.rejected_incomplete == 2


def test_a_malformed_reply_yields_nothing_and_does_not_raise(conn):
    ev = _doc_source(conn, "a")
    result = harvest_document(conn, ev, new_batch_id(),
                              client=MockLLMClient([{"text": "not json at all"}]))
    conn.commit()
    assert result.concepts_created == [] and result.concepts_attached == []
    assert conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind = 'Concept'").fetchone()[0] == 0


# --- the subsystem comes from a closed list ---------------------------------


def test_the_prompt_carries_the_subsystem_names(conn):
    ctx = build_subsystem_context(conn)
    assert "Memory Management" in ctx and "Scheduler" in ctx
    assert '"none"' in ctx


def test_an_unmatched_subsystem_writes_no_edge_and_is_counted(conn):
    """A wrong belongs-to is worse than none, and nothing here creates a
    Subsystem."""
    ev = _doc_source(conn, "a")
    result = harvest_document(
        conn, ev, new_batch_id(),
        client=MockLLMClient([_reply([_mech("Work Stealing")],
                                     subsystem="Quantum Subsystem")]))
    conn.commit()
    assert result.subsystem_unmatched == "Quantum Subsystem"
    assert conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind = 'belongs-to'").fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind = 'Subsystem'").fetchone()[0] == 2


def test_the_subsystem_match_is_exact_not_fuzzy(conn):
    subs = resolve_subsystem_names(conn)
    assert match_subsystem_name(subs, "Memory Management") == "sub-mm"
    assert match_subsystem_name(subs, "memory management") == "sub-mm"
    assert match_subsystem_name(subs, "Memory Manager") is None
    assert match_subsystem_name(subs, "none") is None
    assert match_subsystem_name(subs, "") is None


# --- selection, the bound, the dry run --------------------------------------


def test_documents_with_no_text_are_filtered_before_the_limit(conn):
    """The 241-empty lesson from ALG-KK-EXTRACT-CLI: --limit 10 must mean ten
    documents actually sent, not ten candidates of which some are dropped."""
    for n in ("a", "b"):
        _doc_source(conn, n, text="real prose here")
    for n in ("c", "d"):
        _doc_source(conn, n, text="")
    conn.commit()
    with_text, skipped = select_doc_evidence(conn)
    assert sorted(with_text) == ["ev-a", "ev-b"]
    assert sorted(skipped) == ["ev-c", "ev-d"]


def test_only_canonical_documentation_is_selected(conn):
    _doc_source(conn, "doc", source_type="kernel-doc")
    _doc_source(conn, "paper", source_type="preprint")
    conn.commit()
    with_text, _ = select_doc_evidence(conn)
    assert with_text == ["ev-doc"]


def test_a_dry_run_constructs_no_client_and_writes_nothing(conn):
    """The property exists so someone deciding whether to pay for the real run
    can size it first. The client here fails if touched at all."""
    class ExplodingClient:
        def create_message(self, *a, **k):
            raise AssertionError("a dry run must not reach the client")

    ev = _doc_source(conn, "a")
    before = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    result = harvest_document(conn, ev, new_batch_id(),
                              client=ExplodingClient(), dry_run=True)
    conn.commit()
    assert result.dry_run and result.prompt_chars > 0
    assert result.concepts_created == []
    assert conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == before


def test_the_prompt_carries_the_vocabulary_and_the_document(conn):
    _existing_concept(conn, "concept-1", "Grace Period")
    ev = _doc_source(conn, "a", text="UNIQUE DOCUMENT BODY")
    client = MockLLMClient([_reply([])])
    harvest_document(conn, ev, new_batch_id(), client=client)
    user = client.calls[0]["user"]
    assert "Grace Period" in user
    assert "Memory Management" in user
    assert "UNIQUE DOCUMENT BODY" in user
    assert "RCU is NOT one concept" in client.calls[0]["system"]
    assert "max_pool_percent" in client.calls[0]["system"]
