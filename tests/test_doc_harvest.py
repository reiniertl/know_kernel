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
    SKIP_LINKED,
    SKIP_RETIRED,
    SKIP_REVIEWED,
    build_subsystem_context,
    harvest_document,
    match_subsystem_name,
    new_batch_id,
    resolve_subsystem_names,
    revert_batch,
    select_doc_evidence,
    document_announces_a_procedure,
    document_is_navigation,
    PROCEDURAL_OPENING_CHARS,
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
    with_text, skipped, _, _, _ = select_doc_evidence(conn)
    assert sorted(with_text) == ["ev-a", "ev-b"]
    assert sorted(skipped) == ["ev-c", "ev-d"]


def test_only_canonical_documentation_is_selected(conn):
    _doc_source(conn, "doc", source_type="kernel-doc")
    _doc_source(conn, "paper", source_type="preprint")
    conn.commit()
    with_text, _, _, _, _ = select_doc_evidence(conn)
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


def test_the_vocabularies_are_in_the_system_prompt_and_the_document_alone_in_the_user(conn):
    """INV-KK-LLM-CACHE-STABLE-PREFIX. Both vocabularies are constant across a
    batch, so they belong in the prefix that can be cached; only the document
    varies. This is the placement assertion — the content assertion is that
    nothing the model sees has changed."""
    _existing_concept(conn, "concept-1", "Grace Period")
    ev = _doc_source(conn, "a", text="UNIQUE DOCUMENT BODY")
    client = MockLLMClient([_reply([])])
    harvest_document(conn, ev, new_batch_id(), client=client)
    system, user = client.calls[0]["system"], client.calls[0]["user"]

    for constant in ("Grace Period", "Memory Management",
                     "RCU is NOT one concept", "max_pool_percent"):
        assert constant in system, f"{constant} left the cacheable prefix"
        assert constant not in user, f"{constant} is still re-sent per document"

    assert "UNIQUE DOCUMENT BODY" in user
    assert "UNIQUE DOCUMENT BODY" not in system, "the document polluted the prefix"


def test_the_harvest_prefix_is_byte_identical_across_documents(conn):
    """The whole point: if the prefix differs by one byte the cache misses and
    nothing says so."""
    _existing_concept(conn, "concept-1", "Grace Period")
    first = _doc_source(conn, "a", text="FIRST DOCUMENT")
    second = _doc_source(conn, "b", text="SECOND DOCUMENT")
    client = MockLLMClient([_reply([]), _reply([])])
    batch = new_batch_id()
    harvest_document(conn, first, batch, client=client)
    harvest_document(conn, second, batch, client=client)
    assert client.calls[0]["system"] == client.calls[1]["system"]
    assert client.calls[0]["user"] != client.calls[1]["user"]


# --- revert (INV-KK-HARVEST-BATCH-REVERTIBLE) -------------------------------


def _counts(conn):
    return (conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0])


def test_harvest_then_revert_restores_the_graph_exactly(conn):
    """THE TEST THAT MATTERS MOST. A batch that cannot be undone is a batch
    that must not be run."""
    _existing_concept(conn, "concept-zswap", "Zswap")
    ev = _doc_source(conn, "zswap")
    conn.commit()
    before_nodes, before_edges = _counts(conn)
    before_attrs = json.loads(conn.execute(
        "SELECT attrs FROM nodes WHERE id = 'concept-zswap'").fetchone()[0])

    batch = new_batch_id()
    result = harvest_document(conn, ev, batch, client=MockLLMClient([
        _reply([_mech("Zswap"), _mech("Compressed Swap Cache"),
                _mech("Writeback Throttling")])]))
    conn.commit()
    assert len(result.concepts_created) == 2
    assert len(result.concepts_attached) == 1
    assert _counts(conn) != (before_nodes, before_edges)

    report = revert_batch(conn, batch)
    assert report.clean, report.skipped
    assert len(report.concepts_deleted) == 2
    assert report.edges_detached == 1
    assert _counts(conn) == (before_nodes, before_edges)
    after_attrs = json.loads(conn.execute(
        "SELECT attrs FROM nodes WHERE id = 'concept-zswap'").fetchone()[0])
    assert after_attrs == before_attrs, "a pre-existing Concept was modified"


def test_revert_detaches_from_a_pre_existing_concept_without_deleting_it(conn):
    """The edge carries the batch id while its source node does not, so it
    must be found by the edge. Finding it by the node would either miss it or
    delete a Concept belonging to the original 97."""
    _existing_concept(conn, "concept-zswap", "Zswap")
    ev = _doc_source(conn, "zswap")
    batch = new_batch_id()
    harvest_document(conn, ev, batch,
                     client=MockLLMClient([_reply([_mech("Zswap")])]))
    conn.commit()

    revert_batch(conn, batch)
    assert conn.execute(
        "SELECT 1 FROM nodes WHERE id = 'concept-zswap'").fetchone()
    assert conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind = 'extracted-from' "
        "AND source_id = 'concept-zswap'").fetchone()[0] == 0


def test_revert_skips_a_concept_a_human_reviewed_and_says_so(conn):
    """Per-concept skip with a loud report. Refusing the whole batch was
    considered and refused: one reviewed concept out of two hundred would block
    the revert entirely, which is the situation a revert exists for."""
    ev = _doc_source(conn, "a")
    batch = new_batch_id()
    result = harvest_document(conn, ev, batch, client=MockLLMClient([
        _reply([_mech("Reviewed One"), _mech("Untouched One")])]))
    conn.commit()
    reviewed = result.concepts_created[0]
    attrs = json.loads(conn.execute(
        "SELECT attrs FROM nodes WHERE id = ?", (reviewed,)).fetchone()[0])
    attrs.update({"curation_state": "reviewed", "reviewed_by": "curator@example.com",
                  "reviewed_at": "2026-09-26"})
    conn.execute("UPDATE nodes SET attrs = ? WHERE id = ?",
                 (json.dumps(attrs), reviewed))
    conn.commit()

    report = revert_batch(conn, batch)
    assert not report.clean
    assert [s.concept_id for s in report.skipped] == [reviewed]
    assert report.skipped[0].reason == SKIP_REVIEWED
    assert "curator@example.com" in report.skipped[0].detail
    assert conn.execute("SELECT 1 FROM nodes WHERE id = ?", (reviewed,)).fetchone()
    assert len(report.concepts_deleted) == 1


def test_revert_skips_a_retired_concept(conn):
    """A human judged it wrong; the judgement outlives the batch."""
    ev = _doc_source(conn, "a")
    batch = new_batch_id()
    result = harvest_document(conn, ev, batch,
                              client=MockLLMClient([_reply([_mech("Wrong One")])]))
    conn.commit()
    cid = result.concepts_created[0]
    attrs = json.loads(conn.execute(
        "SELECT attrs FROM nodes WHERE id = ?", (cid,)).fetchone()[0])
    attrs["curation_state"] = "retired"
    conn.execute("UPDATE nodes SET attrs = ? WHERE id = ?", (json.dumps(attrs), cid))
    conn.commit()

    report = revert_batch(conn, batch)
    assert [s.reason for s in report.skipped] == [SKIP_RETIRED]
    assert conn.execute("SELECT 1 FROM nodes WHERE id = ?", (cid,)).fetchone()


def test_revert_skips_a_concept_a_later_paper_run_linked(conn):
    """Cascading was refused: it restores the node count exactly and destroys
    paper links a later run computed and paid for."""
    ev = _doc_source(conn, "a")
    batch = new_batch_id()
    result = harvest_document(conn, ev, batch, client=MockLLMClient([
        _reply([_mech("Linked One"), _mech("Untouched One")])]))
    conn.commit()
    linked = result.concepts_created[0]

    add_node(conn, "src-p", "Source", {
        "url": "https://example.com/p", "source_type": "preprint",
        "license": "MIT", "title": "A later paper"})
    add_node(conn, "ev-p", "Evidence", {
        "artifact_class": "A", "contamination_level": "L0", "text": "t"})
    add_edge(conn, "sourced-from", "ev-p", "src-p")
    add_edge(conn, "extracted-from", linked, "ev-p", {"basis": "evidence-text"})
    conn.commit()

    report = revert_batch(conn, batch)
    assert [s.concept_id for s in report.skipped] == [linked]
    assert report.skipped[0].reason == SKIP_LINKED
    assert conn.execute("SELECT 1 FROM nodes WHERE id = ?", (linked,)).fetchone()
    assert conn.execute(
        "SELECT 1 FROM edges WHERE source_id = ? AND target_id = 'ev-p'",
        (linked,)).fetchone(), "the later paper's link was destroyed"


def test_revert_touches_no_other_batch(conn):
    ev = _doc_source(conn, "a")
    first = new_batch_id()
    harvest_document(conn, ev, first,
                     client=MockLLMClient([_reply([_mech("From First")])]))
    conn.commit()
    ev2 = _doc_source(conn, "b")
    second = new_batch_id()
    r2 = harvest_document(conn, ev2, second,
                          client=MockLLMClient([_reply([_mech("From Second")])]))
    conn.commit()

    report = revert_batch(conn, first)
    assert report.clean
    assert conn.execute("SELECT 1 FROM nodes WHERE id = ?",
                        (r2.concepts_created[0],)).fetchone()


def test_a_revert_dry_run_reports_and_deletes_nothing(conn):
    ev = _doc_source(conn, "a")
    batch = new_batch_id()
    harvest_document(conn, ev, batch,
                     client=MockLLMClient([_reply([_mech("Work Stealing")])]))
    conn.commit()
    before = _counts(conn)
    report = revert_batch(conn, batch, dry_run=True)
    assert report.dry_run and len(report.concepts_deleted) == 1
    assert _counts(conn) == before


def test_reverting_an_unknown_batch_is_a_clean_no_op(conn):
    _existing_concept(conn, "concept-1", "Zswap")
    conn.commit()
    before = _counts(conn)
    report = revert_batch(conn, "harvest-2020-01-01-deadbeef")
    assert report.clean and report.concepts_deleted == []
    assert _counts(conn) == before


# --- the CLI (ALG-KK-DOC-HARVEST-CLI) ---------------------------------------


def _db_with_docs(tmp_path, n, text="real prose about a mechanism"):
    path = tmp_path / "cli.db"
    c = init_db(path)
    add_node(c, "sub-mm", "Subsystem", {"name": "Memory Management"})
    for i in range(n):
        _doc_source(c, f"d{i}", text=text)
    c.commit()
    c.close()
    return str(path)


def test_cli_dry_run_constructs_no_client(tmp_path, monkeypatch, capsys):
    """ALG-KK-EXTRACT-CLI's contract, followed rather than reinvented: each
    adapter builds its SDK client in __init__ and that raises without a
    credential, so sizing a batch has to work for someone who has none."""
    from ingest import cli_harvest

    def exploding_client_for(provider):
        raise AssertionError("a dry run must construct no client")

    monkeypatch.setattr(cli_harvest, "client_for", exploding_client_for)
    db = _db_with_docs(tmp_path, 3)
    cli_harvest.main(["--db", db, "--dry-run"])
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True
    assert out["attempted"] == 3 and out["concepts_created"] == 0


def test_cli_limit_bounds_what_is_actually_sent(tmp_path, monkeypatch, capsys):
    """--limit 2 means two documents sent, not two considered."""
    from ingest import cli_harvest

    client = MockLLMClient([_reply([_mech(f"Mechanism {i}")]) for i in range(10)])
    monkeypatch.setattr(cli_harvest, "client_for", lambda p: client)
    db = _db_with_docs(tmp_path, 6)
    cli_harvest.main(["--db", db, "--limit", "2"])
    out = json.loads(capsys.readouterr().out)
    assert out["selected"] == 6
    assert out["attempted"] == 2
    assert len(client.calls) == 2


def test_cli_limit_applies_after_the_empty_filter(tmp_path, monkeypatch, capsys):
    from ingest import cli_harvest

    client = MockLLMClient([_reply([_mech(f"M{i}")]) for i in range(10)])
    monkeypatch.setattr(cli_harvest, "client_for", lambda p: client)
    path = tmp_path / "cli.db"
    c = init_db(path)
    add_node(c, "sub-mm", "Subsystem", {"name": "Memory Management"})
    for i in range(3):
        _doc_source(c, f"empty{i}", text="")
    for i in range(3):
        _doc_source(c, f"full{i}", text="real prose about a mechanism")
    c.commit()
    c.close()

    cli_harvest.main(["--db", str(path), "--limit", "2"])
    out = json.loads(capsys.readouterr().out)
    assert out["skipped_empty"] == 3
    assert out["attempted"] == 2 and len(client.calls) == 2


def test_cli_report_names_every_rejection_category(tmp_path, monkeypatch, capsys):
    """A single 'rejected' count cannot be acted on. Built from the dataclass
    with asdict, so a field added later cannot be dropped by omission — which
    is what ALG-KK-EXTRACT-CLI's hand-built dict did for a whole run."""
    from ingest import cli_harvest

    monkeypatch.setattr(cli_harvest, "client_for", lambda p: MockLLMClient([
        _reply([_mech("Good One"),
                _mech("a_tunable", artifact_class="tunable"),
                _mech("Half One", tradeoffs=[])],
               subsystem="Nonexistent Subsystem")]))
    db = _db_with_docs(tmp_path, 1)
    cli_harvest.main(["--db", db])
    out = json.loads(capsys.readouterr().out)
    assert out["concepts_created"] == 1
    assert out["rejected_not_mechanism"] == 1
    assert out["rejected_incomplete"] == 1
    assert out["subsystems_unmatched"] == 1
    assert out["batch_id"].startswith("harvest-")


def test_cli_revert_exits_zero_when_clean(tmp_path, monkeypatch, capsys):
    from ingest import cli_harvest
    import sqlite3 as _sqlite3

    monkeypatch.setattr(cli_harvest, "client_for", lambda p: MockLLMClient(
        [_reply([_mech("Work Stealing")])]))
    db = _db_with_docs(tmp_path, 1)
    cli_harvest.main(["--db", db])
    batch = json.loads(capsys.readouterr().out)["batch_id"]

    with pytest.raises(SystemExit) as exc:
        cli_harvest.main(["--db", db, "--revert", batch])
    assert exc.value.code == 0
    c = _sqlite3.connect(db)
    assert c.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind = 'Concept'").fetchone()[0] == 0
    c.close()


def test_cli_revert_exits_nonzero_when_anything_was_skipped(tmp_path, monkeypatch,
                                                            capsys):
    """So a partial revert can never be mistaken for a clean one by a script or
    by a person reading a prompt."""
    from ingest import cli_harvest
    import sqlite3 as _sqlite3

    monkeypatch.setattr(cli_harvest, "client_for", lambda p: MockLLMClient(
        [_reply([_mech("Reviewed One")])]))
    db = _db_with_docs(tmp_path, 1)
    cli_harvest.main(["--db", db])
    batch = json.loads(capsys.readouterr().out)["batch_id"]

    c = _sqlite3.connect(db)
    cid = c.execute("SELECT id FROM nodes WHERE kind = 'Concept'").fetchone()[0]
    attrs = json.loads(c.execute(
        "SELECT attrs FROM nodes WHERE id = ?", (cid,)).fetchone()[0])
    attrs.update({"curation_state": "reviewed", "reviewed_by": "curator@example.com",
                  "reviewed_at": "2026-09-26"})
    c.execute("UPDATE nodes SET attrs = ? WHERE id = ?", (json.dumps(attrs), cid))
    c.commit()
    c.close()

    with pytest.raises(SystemExit) as exc:
        cli_harvest.main(["--db", db, "--revert", batch])
    assert exc.value.code == 1
    printed = capsys.readouterr().out
    assert "SKIPPED" in printed and "curator@example.com" in printed
    assert "did NOT come out whole" in printed


# ---------------------------------------------------------------------------
# What the first real batch taught, 2026-09-25 (INV-KK-HARVEST-NAME-IS-A-CLASS)
#
# 18 documents, gpt-4o-mini, 24 created, 7 attached, ZERO rejected in either
# category — and roughly ten of the 24 were wrong. Every case below is a name
# that batch actually produced. It was reverted; these tests are what stops it
# happening again.
# ---------------------------------------------------------------------------

from graph.concept_vocabulary import (  # noqa: E402
    contained_in,
    normalise_concept_name,
    strict_match_concept,
)
from ingest.doc_harvest import name_is_a_class  # noqa: E402


@pytest.mark.parametrize("bad", [
    "struct sk_buff",   # the system prompt's OWN example of what not to create
    "skb_clone",        # a function name
    "shared sk_buff",   # a phrase, not a name
    "kmalloc()",
    "__free_pages",
])
def test_code_shaped_names_are_not_classes(bad):
    assert name_is_a_class(bad) is False


@pytest.mark.parametrize("good", [
    "Transparent Huge Page Support", "Whiteouts", "Metadata-only Copy Up",
    "RAID", "Constant Bandwidth Server (CBS)", "ext4", "Zswap",
])
def test_real_class_names_survive(good):
    assert name_is_a_class(good) is True


def test_the_filter_cannot_tell_io_uring_from_skb_clone_and_says_so():
    """A KNOWN AND ACCEPTED LIMITATION, pinned rather than hidden.

    "io_uring" and "skb_clone" are the same shape — lowercase, underscored —
    and one is an established mechanism while the other is a function. Nothing
    structural separates them, so the filter refuses both. The cost is a
    legitimately-underscored NEW mechanism being rejected; that rejection is
    visible in rejected_not_a_class and recoverable by admitting the name once
    by hand, after which matching carries it forever. The alternative is
    admitting every function name in the kernel, which is what the batch of
    2026-09-25 actually did.
    """
    assert name_is_a_class("io_uring") is False
    assert name_is_a_class("skb_clone") is False


def test_a_name_that_is_already_a_subsystem_is_refused(conn):
    """The batch produced a Concept called "Virtual Memory" while a Subsystem
    of that name exists — every belongs-to edge becomes ambiguous to a reader."""
    subs = resolve_subsystem_names(conn)
    assert name_is_a_class("Memory Management", subs) is False
    assert name_is_a_class("Memory Reclaim", subs) is True


def test_the_filter_runs_after_matching_so_io_uring_still_attaches(conn):
    """io_uring is a bare lowercase identifier AND an established Concept. A
    name already admitted has been judged by a human once; only an unmatched
    name reaches the shape test."""
    _existing_concept(conn, "concept-io", "io_uring")
    ev = _doc_source(conn, "io")
    result = harvest_document(conn, ev, new_batch_id(),
                              client=MockLLMClient([_reply([_mech("io_uring")])]))
    conn.commit()
    assert result.concepts_attached == ["concept-io"]
    assert result.rejected_not_a_class == 0


def test_a_code_shaped_proposal_is_rejected_and_counted(conn):
    """rejected_not_mechanism was ZERO across 18 documents because
    artifact_class reads what the MODEL CLAIMS. These proposals all claim
    'abstracted-mechanism' and are refused on the shape of the name."""
    ev = _doc_source(conn, "skbuff")
    result = harvest_document(conn, ev, new_batch_id(), client=MockLLMClient([
        _reply([_mech("struct sk_buff"), _mech("skb_clone"),
                _mech("shared sk_buff"), _mech("Socket Buffer Cloning")])]))
    conn.commit()
    assert len(result.concepts_created) == 1
    assert result.rejected_not_a_class == 3
    assert result.rejected_not_mechanism == 0, (
        "the artifact_class check is a formality; the name check is the filter")


# --- the six duplicates the fuzzy matcher missed ---------------------------


@pytest.mark.parametrize("proposed,existing", [
    ("Kernel Samepage Merging", "KSM (Kernel Same-page Merging)"),
    ("Directory Entry Cache (dcache)", "Dentry Cache (dcache)"),
    ("struct sk_buff", "Socket Buffer (sk_buff)"),
    ("Grace Periods", "Grace Period"),
    ("Transparent Huge Page", "Transparent Huge Pages"),
])
def test_the_strict_matcher_catches_what_levenshtein_could_not(proposed, existing):
    """Levenshtein 2 cannot reach across a whole word. Every pair here is one
    the 2026-09-25 batch duplicated."""
    table = {normalise_concept_name(existing): "concept-x"}
    assert strict_match_concept(proposed, table) == "concept-x"


@pytest.mark.parametrize("proposed,existing", [
    ("Kmalloc", "Vmalloc"),                      # the Levenshtein-1 false positive
    ("Huge Pages", "Transparent Huge Pages"),    # genuinely different mechanisms
    ("Memory Reclaim", "Memory Ballooning"),
])
def test_the_strict_matcher_refuses_proximity(proposed, existing):
    """Identity after normalisation, never proximity. On this path a false
    match SUPPRESSES a legitimate concept rather than writing a wrong link."""
    table = {normalise_concept_name(existing): "concept-x"}
    assert strict_match_concept(proposed, table) is None


def test_an_exact_name_beats_an_ambiguous_plural():
    """INVERTED 2026-09-30, EXPLICITLY, BECAUSE IT ENCODED THE DEFECT.

    This asserted None: "grace period" hit "Grace Period" by its exact name AND
    "Grace Periods" by the squash tier's plural stripping, and the flat form-set
    called that a tie. But refusing here is how the vocabulary acquires a THIRD
    "Grace Period" — which is exactly what happened on 2026-09-30, when batch
    9e2419bc minted "Linux Security Module (LSM)" twice because an ambiguous
    abbreviation vetoed a unique exact hit.

    A query whose FULL NAME is in the vocabulary attaches to the concept of that
    name. The plural sibling remains a collision pair for a human to resolve;
    that is the review queue's job and not the matcher's.
    """
    table = {normalise_concept_name("Grace Period"): "concept-a",
             normalise_concept_name("Grace Periods"): "concept-b"}
    assert strict_match_concept("grace period", table) == "concept-a"


def test_a_tie_within_one_tier_still_attaches_to_nothing():
    """The tie rule itself is unchanged and still right. Two concepts reachable
    only by the SAME tier, neither by a stronger one, stay a coin flip."""
    table = {normalise_concept_name("KSM (Kernel Same-page Merging)"): "concept-a",
             normalise_concept_name("Kernel Samepage Merging"): "concept-b"}
    assert strict_match_concept("kernel same page merging", table) is None


def test_containment_surfaces_the_pair_it_must_not_merge():
    """"Huge Pages" in "Transparent Huge Pages" is a DIFFERENT mechanism;
    "Transparent Huge Page Support" is contained the same way and is the SAME
    one. Nothing in their shape separates them, so containment feeds the review
    queue and never the matcher."""
    assert contained_in("huge page", "transparent huge pages") is True
    assert strict_match_concept(
        "Huge Pages",
        {normalise_concept_name("Transparent Huge Pages"): "c"}) is None
    assert contained_in("numa memory policy",
                        "numa topology and memory policy") is True
    assert contained_in("memory reclaim", "memory ballooning") is False


# ---------------------------------------------------------------------------
# Two batches over one corpus (INV-KK-HARVEST-BATCH-REVERTIBLE, corrected
# 2026-09-28)
#
# The predicate quantified over ONE batch and the hazard only appears with two:
# _attach UPDATES an existing edge rather than inserting a second one, so a
# re-read rewrote harvest_batch on edges the previous batch had written and
# made BOTH reverts lossy. Caught before a second batch ran.
# ---------------------------------------------------------------------------

from ingest.doc_harvest import ForeignEdgeError  # noqa: E402


def test_selection_excludes_documents_already_harvested(conn):
    ev_done = _doc_source(conn, "done")
    ev_new = _doc_source(conn, "new")
    harvest_document(conn, ev_done, new_batch_id(),
                     client=MockLLMClient([_reply([_mech("Work Stealing")])]))
    conn.commit()

    unread, empty, already, _, _ = select_doc_evidence(conn)
    assert unread == [ev_new]
    assert already == [ev_done]
    assert empty == []


def test_a_non_concept_edge_does_not_count_as_harvested(conn):
    """Evidence carries extracted-from edges from PerformanceProfile,
    KernelInvariant, FailureMode and InteractionProtocol too. Measured
    2026-09-28: 17 of 132 doc Evidence carry a Concept edge and 18 carry ANY
    extracted-from edge — the difference is core-api/kernel-api.rst, which the
    old pre-verdict extractor read and the harvest never did. A filter on "any
    extracted-from edge" would skip it permanently."""
    ev = _doc_source(conn, "kernel-api")
    add_node(conn, "pp-1", "PerformanceProfile", {
        "metric": "latency", "complexity": "O(1)", "best_case": "a",
        "worst_case": "b", "typical_case": "c", "conditions": "d",
        "artifact_class": "abstracted-mechanism"})
    add_edge(conn, "extracted-from", "pp-1", ev)
    conn.commit()

    unread, _, already, _, _ = select_doc_evidence(conn)
    assert unread == [ev], "a non-Concept edge was mistaken for a harvest"
    assert already == []


def test_include_harvested_restores_the_whole_corpus(conn):
    ev_done = _doc_source(conn, "done")
    ev_new = _doc_source(conn, "new")
    harvest_document(conn, ev_done, new_batch_id(),
                     client=MockLLMClient([_reply([_mech("Work Stealing")])]))
    conn.commit()
    unread, _, already, _, _ = select_doc_evidence(conn, include_harvested=True)
    assert sorted(unread) == sorted([ev_done, ev_new])
    assert already == []


def test_a_second_batch_never_takes_the_first_batch_s_edge(conn):
    """THE PROPERTY THE CORRECTION EXISTS FOR, asserted at the edge rather
    than through the selection, because _attach must hold even under
    --include-harvested."""
    _existing_concept(conn, "concept-zswap", "Zswap")
    ev = _doc_source(conn, "zswap")
    first = new_batch_id()
    harvest_document(conn, ev, first,
                     client=MockLLMClient([_reply([_mech("Zswap")])]))
    conn.commit()

    second = new_batch_id()
    result = harvest_document(conn, ev, second,
                              client=MockLLMClient([_reply([_mech("Zswap")])]))
    conn.commit()

    assert result.attached_foreign == 1
    assert result.concepts_attached == []
    owner = json.loads(conn.execute(
        "SELECT attrs FROM edges WHERE kind = 'extracted-from' "
        "AND source_id = 'concept-zswap'").fetchone()[0])["harvest_batch"]
    assert owner == first, "the second batch took ownership of the first's edge"


def test_both_batches_revert_independently_over_one_corpus(conn):
    """Before the 2026-09-28 correction neither revert could undo these:
    revert(second) deleted an edge the first created, and revert(first)
    skipped its own Concepts as linked-outside-batch."""
    _existing_concept(conn, "concept-zswap", "Zswap")
    ev_a = _doc_source(conn, "a")
    ev_b = _doc_source(conn, "b")
    conn.commit()
    before = _counts(conn)

    first = new_batch_id()
    harvest_document(conn, ev_a, first, client=MockLLMClient([
        _reply([_mech("Zswap"), _mech("First Mechanism")])]))
    conn.commit()

    second = new_batch_id()
    harvest_document(conn, ev_b, second,
                     client=MockLLMClient([_reply([_mech("Second Mechanism")])]))
    conn.commit()

    r2 = revert_batch(conn, second)
    assert r2.clean, r2.skipped
    r1 = revert_batch(conn, first)
    assert r1.clean, r1.skipped
    assert _counts(conn) == before

    # and the pre-existing Concept kept its provenance throughout
    assert conn.execute(
        "SELECT 1 FROM nodes WHERE id = 'concept-zswap'").fetchone()


def test_the_foreign_edge_error_names_the_owning_batch(conn):
    _existing_concept(conn, "concept-1", "Zswap")
    ev = _doc_source(conn, "a")
    first = new_batch_id()
    harvest_document(conn, ev, first,
                     client=MockLLMClient([_reply([_mech("Zswap")])]))
    conn.commit()
    from ingest.doc_harvest import _attach
    with pytest.raises(ForeignEdgeError) as exc:
        _attach(conn, "concept-1", ev, "harvest-other", "t", "m", "d")
    assert exc.value.owner == first


def test_the_cache_figure_reaches_the_result(conn):
    """INV-KK-LLM-CACHE-REPORTED. A zero across a batch sharing one prefix
    means something is invalidating it, and every cause is silent."""
    class CachingClient(MockLLMClient):
        def create_message(self, model, system, user, max_tokens):
            out = super().create_message(model, system, user, max_tokens)
            out["cached_tokens"] = 2419
            return out

    ev = _doc_source(conn, "a")
    result = harvest_document(conn, ev, new_batch_id(),
                              client=CachingClient([_reply([_mech("Work Stealing")])]))
    assert result.cached_tokens == 2419


# ---------------------------------------------------------------------------
# INV-KK-HARVEST-DOCUMENT-DEFINES — a document whose SUBJECT is a procedure
# is refused before the model is called.
#
# The strings below are the real openings of the real documents that shaped
# the rule, taken from data/master.db on 2026-09-29.
# ---------------------------------------------------------------------------

#: filesystems/adding-new-filesystems.rst — the document that defeated
#: INV-KK-SEED-PATH-DEFINITIONAL by sitting in a sanctioned design directory.
#: It produced "Filesystem Submission Process" and "Filesystem Maintenance
#: Commitment", neither of which is a mechanism.
_ADDING_NEW_FILESYSTEMS = (
    ".. SPDX-License-Identifier: GPL-2.0\n\n.. _adding_new_filesystems:\n\n"
    "Adding New Filesystems\n======================\n\n"
    "This document describes what is involved in adding a new filesystem to "
    "the\nLinux kernel.\n\nEvery filesystem merged into the kernel becomes the "
    "collective responsibility\nof the VFS maintainers and the wider filesystem "
    "development community.\n"
)

#: RCU/checklist.rst — "Review Checklist for RCU Patches". Procedural in FORM
#: and about RCU in SUBSTANCE; it legitimately created SRCU (Sleepable RCU)
#: and RCU Callbacks. This is why "checklist" is not a marker.
_RCU_CHECKLIST = (
    ".. SPDX-License-Identifier: GPL-2.0\n\n"
    "================================\nReview Checklist for RCU Patches\n"
    "================================\n\n\n"
    "This document contains a checklist for producing and reviewing patches\n"
    "that make use of RCU.  Violating any of the rules listed below will\n"
    "result in the same sort of problems that leaving out a locking primitive\n"
    "would cause.\n"
)


def test_a_document_about_adding_a_filesystem_is_refused():
    """The exact document that produced the two process concepts."""
    assert document_announces_a_procedure(_ADDING_NEW_FILESYSTEMS)


def test_a_checklist_about_a_mechanism_is_not_refused():
    """SUBJECT, NOT FORM. RCU/checklist.rst is a review checklist and it
    created SRCU (Sleepable RCU) and RCU Callbacks — both legitimate. An
    earlier draft of this rule carried "checklist" as a marker and would have
    thrown those away, which is how the marker list came to name the ACT a
    document describes rather than the shape it takes."""
    assert not document_announces_a_procedure(_RCU_CHECKLIST)


def test_a_mechanism_document_that_mentions_patches_later_is_not_refused():
    """Only the opening is read. A design document may well say "send your
    patches" in a closing section, and refusing it for that would cost a real
    mechanism for a line that is not what the document is about."""
    text = (
        "Work Stealing\n=============\n\nThis document defines the work "
        "stealing scheduler used by the kernel's per-CPU run queues. "
        + ("Idle CPUs steal runnable tasks from busier neighbours. " * 60)
        + "\n\nTo report bugs, send your patches to the maintainer.\n"
    )
    assert len(text) > PROCEDURAL_OPENING_CHARS
    assert "send your patches" in text.lower()
    assert not document_announces_a_procedure(text)


def test_an_empty_document_is_not_a_procedure():
    assert not document_announces_a_procedure("")
    assert not document_announces_a_procedure(None)


def test_a_procedural_document_is_refused_at_selection(conn):
    """It never reaches a prompt, so the refusal costs nothing."""
    ev_proc = _doc_source(conn, "adding", text=_ADDING_NEW_FILESYSTEMS)
    ev_mech = _doc_source(conn, "vfs", text="VFS\n===\n\nThis document defines "
                                            "the virtual filesystem switch.")
    conn.commit()
    unread, empty, already, procedural, _ = select_doc_evidence(conn)
    assert unread == [ev_mech]
    assert procedural == [ev_proc]
    assert already == []
    assert empty == []


def test_include_harvested_does_not_restore_a_procedural_document(conn):
    """--include-harvested exists to re-read a document DELIBERATELY. A
    document this rule refuses is one nothing should read at all, so the flag
    does not reach it."""
    ev_proc = _doc_source(conn, "adding", text=_ADDING_NEW_FILESYSTEMS)
    ev_mech = _doc_source(conn, "vfs", text="VFS\n===\n\nThis document defines "
                                            "the virtual filesystem switch.")
    conn.commit()
    unread, _, _, procedural, _ = select_doc_evidence(conn, include_harvested=True)
    assert unread == [ev_mech]
    assert procedural == [ev_proc]


def test_a_procedural_document_is_never_sent_to_the_model(conn):
    """The end-to-end property: no client call, no Concept, no edge. The
    client here raises if touched at all."""
    class ExplodingClient:
        def create_message(self, **kwargs):
            raise AssertionError("a refused document reached the model")

    ev_proc = _doc_source(conn, "adding", text=_ADDING_NEW_FILESYSTEMS)
    conn.commit()
    unread, _, _, procedural, _ = select_doc_evidence(conn)
    assert procedural == [ev_proc]
    for ev in unread:
        harvest_document(conn, ev, new_batch_id(), client=ExplodingClient())
    concepts = conn.execute(
        "SELECT COUNT(*) FROM edges x JOIN nodes n ON n.id = x.source_id "
        "WHERE x.kind = 'extracted-from' AND x.target_id = ? "
        "AND n.kind = 'Concept'", (ev_proc,)).fetchone()[0]
    assert concepts == 0


def test_the_name_filter_still_passes_the_names_this_rule_catches():
    """WHY A THIRD FILTER EXISTS, pinned so nobody removes it as redundant.
    INV-KK-HARVEST-NAME-IS-A-CLASS reads the SHAPE of a name, and both process
    concepts are perfectly well-formed names. The document rule is the only
    thing standing between them and the vocabulary."""
    assert name_is_a_class("Filesystem Submission Process")
    assert name_is_a_class("Filesystem Maintenance Commitment")


# ---------------------------------------------------------------------------
# THE PATH FILTER ON SELECTION, added 2026-09-30.
#
# --limit applies AFTER select_doc_evidence, which orders by Evidence id — a
# hash — so a bound of 99 returned an arbitrary 99 documents drawn from every
# subtree at once. INV-KK-HARVEST-BATCH-REVERTIBLE makes one batch the unit of
# undo, so a batch mixing trace/ with userspace-api/media/ can neither be read
# nor reverted usefully.
# ---------------------------------------------------------------------------

def test_a_subtree_filter_selects_only_that_subtree(conn):
    _doc_source(conn, "trace/ftrace")
    _doc_source(conn, "block/queue")
    _doc_source(conn, "userspace-api/media/v4l/ioctl")
    conn.commit()

    unread, _, _, _, _ = select_doc_evidence(
        conn, path_prefixes=("Documentation/trace/",))
    assert unread == ["ev-trace/ftrace"]


def test_several_subtrees_are_a_union(conn):
    _doc_source(conn, "trace/ftrace")
    _doc_source(conn, "block/queue")
    _doc_source(conn, "userspace-api/media/v4l/ioctl")
    conn.commit()

    unread, _, _, _, _ = select_doc_evidence(
        conn, path_prefixes=("Documentation/trace/", "Documentation/block/"))
    assert sorted(unread) == ["ev-block/queue", "ev-trace/ftrace"]


def test_no_filter_still_selects_everything(conn):
    """The default must not change: an unfiltered run reads the whole corpus."""
    _doc_source(conn, "trace/ftrace")
    _doc_source(conn, "block/queue")
    conn.commit()

    unread, _, _, _, _ = select_doc_evidence(conn)
    assert len(unread) == 2


def test_the_filter_does_not_reach_past_the_already_harvested_exclusion(conn):
    """It narrows selection; it does not weaken
    INV-KK-HARVEST-BATCH-REVERTIBLE's default exclusion."""
    done = _doc_source(conn, "trace/done")
    _doc_source(conn, "trace/new")
    harvest_document(conn, done, new_batch_id(),
                     client=MockLLMClient([_reply([_mech("Work Stealing")])]))
    conn.commit()

    unread, _, already, _, _ = select_doc_evidence(
        conn, path_prefixes=("Documentation/trace/",))
    assert unread == ["ev-trace/new"]
    assert already == [done]


def test_the_filter_cannot_admit_a_path_seeding_would_refuse(conn):
    """SELECTION, NOT ADMISSION. INV-KK-SEED-PATH-DEFINITIONAL decides what
    may ENTER as kernel-doc and is enforced at seeding; this only chooses among
    what is already there. A prefix matching nothing selects nothing — it
    cannot conjure a document the seed rule refused."""
    _doc_source(conn, "trace/ftrace")
    conn.commit()

    unread, _, _, _, _ = select_doc_evidence(
        conn, path_prefixes=("Documentation/process/",))
    assert unread == []


# ---------------------------------------------------------------------------
# INV-KK-HARVEST-DOCUMENT-DEFINES, second genre: a table of contents.
#
# ALG-KK-SEED-DOC-SUBTREE claimed a subtree's index.rst "will be refused as a
# stub". It is not: classify_content refuses a document for being SHORT, and
# trace/index.rst carries 2,077 characters of prose before its toctree. It was
# harvested and minted "Tracing Frameworks" and "Ring Buffer" from a list of
# links.
# ---------------------------------------------------------------------------

def _toctree_page(prose_lines: int, entry_lines: int) -> str:
    head = "Linux Tracing Technologies Guide\n=====\n\n"
    prose = "".join(f"Some real prose about tracing, line {i}.\n"
                    for i in range(prose_lines))
    toc = "\n.. toctree::\n   :maxdepth: 2\n"
    toc += "".join(f"   some-document-{i}\n" for i in range(entry_lines))
    return head + prose + toc


def test_a_table_of_contents_is_refused():
    assert document_is_navigation(_toctree_page(prose_lines=3, entry_lines=40))


def test_a_design_document_that_merely_carries_a_toctree_is_kept():
    """THE MEASUREMENT THAT CHOSE DOMINANCE OVER PRESENCE. 60 of 1,510
    kernel-doc documents contain a toctree and only 24 are index pages;
    refusing on the directive would discard mm/process_addrs.rst (47,256
    characters) and mm/damon/design.rst (47,184), which are exactly the design
    documents this corpus exists for."""
    assert not document_is_navigation(_toctree_page(prose_lines=400, entry_lines=6))


def test_a_document_with_no_toctree_at_all_is_kept():
    assert not document_is_navigation("Ftrace\n======\n\n" + "Real prose.\n" * 50)


def test_an_empty_document_is_not_navigation():
    assert not document_is_navigation("")
    assert not document_is_navigation(None)


def test_navigation_is_counted_apart_from_procedural(conn):
    """Two refusals with different causes reported as one number is a number
    nobody can act on — the same reason listing-failed is counted apart from
    unreachable."""
    ev_nav = _doc_source(conn, "trace/index", text=_toctree_page(3, 40))
    ev_proc = _doc_source(conn, "adding", text=_ADDING_NEW_FILESYSTEMS)
    ev_real = _doc_source(conn, "ftrace",
                          text="Ftrace\n======\n\nThis document defines the "
                               "function tracer. " * 20)
    conn.commit()

    unread, _, _, procedural, navigation = select_doc_evidence(conn)
    assert unread == [ev_real]
    assert procedural == [ev_proc]
    assert navigation == [ev_nav]


def test_include_harvested_does_not_restore_a_navigation_page(conn):
    ev_nav = _doc_source(conn, "trace/index", text=_toctree_page(3, 40))
    ev_real = _doc_source(conn, "ftrace",
                          text="Ftrace\n======\n\nThis defines the tracer. " * 20)
    conn.commit()

    unread, _, _, _, navigation = select_doc_evidence(conn, include_harvested=True)
    assert unread == [ev_real]
    assert navigation == [ev_nav]


# ---------------------------------------------------------------------------
# INV-KK-HARVEST-READ-RECORDED — a read is recorded even when it yields nothing.
#
# The third instance of one shape in one week. A directory that could not be
# LISTED looked like a directory with no files; a concept nobody had LINKED
# looked like one nothing could link; and a document READ that defined no
# reusable mechanism looked exactly like one never opened. Batch
# harvest-2026-09-30-9e2419bc read 99 documents, 10 yielded nothing, and those
# ten were offered straight back to the next run.
# ---------------------------------------------------------------------------

def test_a_document_that_yields_nothing_is_not_re_selected(conn):
    """THE DEFECT, stated as the property it broke."""
    ev = _doc_source(conn, "coresight-tpdm")
    harvest_document(conn, ev, new_batch_id(),
                     client=MockLLMClient([_reply([])]))
    conn.commit()

    unread, _, already, _, _ = select_doc_evidence(conn)
    assert unread == [], "a document read and found empty was offered again"
    assert already == [ev]


def test_the_mark_carries_the_batch_that_read_it(conn):
    """A flag would not be enough: INV-KK-HARVEST-BATCH-REVERTIBLE makes the
    batch the unit of undo, and a run that produced little is the one most
    likely to be repeated by someone who assumes it never ran."""
    from graph.engine import get_node
    ev = _doc_source(conn, "stat")
    batch = new_batch_id()
    harvest_document(conn, ev, batch, client=MockLLMClient([_reply([])]))
    conn.commit()

    assert get_node(conn, ev)["attrs"]["harvest_read_batch"] == batch


def test_a_yielding_document_is_marked_too(conn):
    """The mark records the READ, not the outcome — otherwise the two states
    are distinguishable only by the thing that was missing in the first place."""
    from graph.engine import get_node
    ev = _doc_source(conn, "ftrace")
    batch = new_batch_id()
    harvest_document(conn, ev, batch,
                     client=MockLLMClient([_reply([_mech("Work Stealing")])]))
    conn.commit()

    assert get_node(conn, ev)["attrs"]["harvest_read_batch"] == batch


def test_include_harvested_still_reaches_a_no_yield_document(conn):
    """That flag exists for a deliberate re-read, and a no-yield document is
    exactly the kind worth re-reading after the prompt changes."""
    ev = _doc_source(conn, "debugging")
    harvest_document(conn, ev, new_batch_id(),
                     client=MockLLMClient([_reply([])]))
    conn.commit()

    unread, _, _, _, _ = select_doc_evidence(conn, include_harvested=True)
    assert unread == [ev]


def test_reverting_a_batch_that_yielded_nothing_restores_the_document(conn):
    """Without this the undo would be NEARLY complete — the concepts gone but
    the documents still counted as read, which is the worst of both states."""
    ev = _doc_source(conn, "switching-sched")
    batch = new_batch_id()
    harvest_document(conn, ev, batch, client=MockLLMClient([_reply([])]))
    conn.commit()
    assert select_doc_evidence(conn)[0] == []

    revert_batch(conn, batch)
    unread, _, already, _, _ = select_doc_evidence(conn)
    assert unread == [ev], "a reverted document stayed marked as read"
    assert already == []


def test_reverting_one_batch_leaves_another_batch_s_marks(conn):
    """The UPDATE is scoped by batch id."""
    ev_a = _doc_source(conn, "aaa")
    ev_b = _doc_source(conn, "bbb")
    batch_a, batch_b = new_batch_id(), new_batch_id()
    harvest_document(conn, ev_a, batch_a, client=MockLLMClient([_reply([])]))
    harvest_document(conn, ev_b, batch_b, client=MockLLMClient([_reply([])]))
    conn.commit()

    revert_batch(conn, batch_a)
    unread, _, _, _, _ = select_doc_evidence(conn)
    assert unread == [ev_a]
