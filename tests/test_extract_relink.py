"""Making the re-derivation runnable — the code, not the run.

ALG-KK-EXTRACT-CLI: --limit, --all-relink, and skipping papers with no input.
INV-KK-EXTRACT-RELINK-CONVERGENT: running it twice does the work once.
INV-KK-EXTRACT-IDEMPOTENT: unchanged, and still fires in the default mode.
INV-KK-EXTRACT-PROVENANCE: the eighth writer.

NO TEST HERE MAY MAKE A NETWORK CALL. Every path either injects a client or
takes --dry-run, which returns before any client is constructed. A test that
reached the network would be a defect in the test, not a passing run.
"""

from __future__ import annotations

import json

import pytest

from graph.engine import add_edge, add_node, get_node
from graph.rules import (
    LEGACY_UNVERIFIED_BASIS,
    MECHANISM_UNATTRIBUTED_BASIS,
    VALID_EVIDENCE_BASES,
)
from graph.schema import init_db
from ingest.cli_extract import (
    drop_evidence_with_no_input,
    select_for_relink,
    select_unextracted,
)
from ingest.extractor import (
    BASIS_EVIDENCE_TEXT,
    BASIS_NONE,
    attach_existing_concept,
    edge_carries_a_current_verdict,
    extract_concepts,
    find_concept_by_name,
    normalise_concept_name,
)
from ingest.gate import SessionGate


TEXT = "This paper describes page table walking and copy-on-write in kernels."

CONCEPTS = [{
    "name": "Copy-on-Write",
    "description": "Deferring a page copy until the first write to it.",
    "key_properties": ["lazy", "page-granular"],
    "tradeoffs": ["fault cost on first write"],
    "design_rationale": "Avoids copying pages that are never written.",
    "subsystem": "Memory",
    "relationships": [],
    "invariants": [],
}]


class MockLLMClient:
    """Records every call so a test can assert the model was NOT consulted."""

    def __init__(self, concepts=None):
        self.concepts = CONCEPTS if concepts is None else concepts
        self.calls: list[dict] = []

    def create_message(self, model, system, user, max_tokens):
        self.calls.append({"model": model, "user": user})
        return {"text": json.dumps({"concepts": self.concepts}),
                "prompt_tokens": 100, "response_tokens": 50}


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "relink.db")
    yield c
    c.close()


def _paper(conn, n, text=TEXT):
    add_node(conn, f"src-{n}", "Source", {
        "url": f"https://example.com/{n}.pdf", "source_type": "paper",
        "license": "MIT", "title": f"Paper {n}"})
    add_node(conn, f"ev-{n}", "Evidence", {
        "artifact_class": "licensed-evidence",
        "contamination_level": "weak-copyleft", "text": text})
    add_edge(conn, "sourced-from", f"ev-{n}", f"src-{n}")
    conn.commit()
    return f"ev-{n}"


def _concept(conn, cid, name):
    add_node(conn, cid, "Concept", {
        "name": name, "description": "x",
        "artifact_class": "abstracted-mechanism", "key_properties": [],
        "tradeoffs": [], "design_rationale": "n/a"})
    conn.commit()
    return cid


def _legacy_link(conn, cid, eid):
    add_edge(conn, "extracted-from", cid, eid, {
        "basis": LEGACY_UNVERIFIED_BASIS, "grounded": False,
        "superseded": False, "mechanism": "title regex"})
    conn.commit()


def _edge_attrs(conn, cid, eid):
    row = conn.execute(
        "SELECT attrs FROM edges WHERE kind='extracted-from' "
        "AND source_id=? AND target_id=?", (cid, eid)).fetchone()
    return json.loads(row[0]) if row and row[0] else None


# --- the constant this all turns on ----------------------------------------


def test_the_extractors_bases_have_not_drifted_from_the_rules_module():
    """edge_carries_a_current_verdict reads VALID_EVIDENCE_BASES from
    graph.rules while extractor.py defines BASIS_* of its own. Two copies of
    one vocabulary is the defect this codebase keeps finding, so the agreement
    is asserted rather than assumed."""
    assert set(VALID_EVIDENCE_BASES) == {BASIS_EVIDENCE_TEXT, BASIS_NONE}


@pytest.mark.parametrize("attrs,expected", [
    ({"basis": "evidence-text", "checked_at": "2026-09-21"}, True),
    ({"basis": "none"}, True),
    ({"basis": "evidence-text", "superseded": True}, False),
    ({"basis": LEGACY_UNVERIFIED_BASIS}, False),
    ({"basis": MECHANISM_UNATTRIBUTED_BASIS}, False),
    ({}, False),
    (None, False),
])
def test_what_counts_as_a_current_verdict(attrs, expected):
    """An out-of-scope marker is deliberately NOT current: an edge carrying
    one is exactly an edge awaiting re-derivation."""
    assert edge_carries_a_current_verdict(attrs) is expected


# --- selection --------------------------------------------------------------


def test_the_two_batch_modes_partition_the_corpus(conn):
    """Nothing is in both and nothing is in neither. This is the property that
    makes --all-relink the complement of --all-unextracted rather than an
    overlapping second pass."""
    fresh = _paper(conn, "fresh")
    legacy = _paper(conn, "legacy")
    _legacy_link(conn, _concept(conn, "concept-a", "Alpha"), legacy)

    unextracted, relink = select_unextracted(conn), select_for_relink(conn)
    assert set(unextracted) == {fresh}
    assert set(relink) == {legacy}
    assert set(unextracted) & set(relink) == set()
    assert set(unextracted) | set(relink) == {fresh, legacy}


def test_relink_selects_exactly_what_the_old_flag_skipped(conn):
    """--all-unextracted computes the Evidence that already have an edge and
    skips them. That set IS the re-derivation population."""
    linked = _paper(conn, "linked")
    _legacy_link(conn, _concept(conn, "concept-a", "Alpha"), linked)
    assert linked not in select_unextracted(conn)
    assert linked in select_for_relink(conn)


def test_an_evidence_with_a_current_verdict_is_not_selected_for_relink(conn):
    done = _paper(conn, "done")
    cid = _concept(conn, "concept-a", "Alpha")
    add_edge(conn, "extracted-from", cid, done, {
        "basis": "evidence-text", "grounded": False, "ungrounded_count": 1,
        "ungrounded": ["a b"], "basis_sha256": "ab" * 32,
        "model": "m", "checked_at": "2026-09-21"})
    conn.commit()
    assert select_for_relink(conn) == []


def test_one_current_edge_is_enough_even_beside_a_legacy_one(conn):
    """A paper part-way through re-derivation must not be selected twice."""
    mixed = _paper(conn, "mixed")
    _legacy_link(conn, _concept(conn, "concept-old", "Old"), mixed)
    add_edge(conn, "extracted-from", _concept(conn, "concept-new", "New"), mixed, {
        "basis": "none", "grounded": False, "ungrounded_count": 0,
        "ungrounded": [], "basis_sha256": "", "model": "m",
        "checked_at": "2026-09-21"})
    conn.commit()
    assert select_for_relink(conn) == []


# --- the empty-input filter -------------------------------------------------


def test_a_paper_with_no_text_is_dropped_rather_than_sent(conn):
    """The model would be paid to read nothing."""
    good, empty = _paper(conn, "good"), _paper(conn, "empty", text="")
    usable, skipped = drop_evidence_with_no_input(conn, [good, empty])
    assert usable == [good]
    assert skipped == [empty]


def test_the_filter_runs_before_the_limit_so_n_means_n_sent(conn):
    """--limit 2 must mean two papers actually sent, not two candidates of
    which one evaporates."""
    ids = [_paper(conn, "e1", text=""), _paper(conn, "e2"), _paper(conn, "e3")]
    usable, skipped = drop_evidence_with_no_input(conn, ids)
    assert len(skipped) == 1
    assert len(usable[:2]) == 2


# --- concept identity in re-link mode --------------------------------------


def test_a_name_is_matched_case_and_whitespace_insensitively():
    assert normalise_concept_name("  Copy-On-Write  ") == "copy-on-write"
    assert normalise_concept_name("Copy  on\tWrite") == "copy on write"


def test_an_existing_concept_is_found_by_name(conn):
    cid = _concept(conn, "concept-cow", "Copy-on-Write")
    assert find_concept_by_name(conn, "  copy-on-WRITE ") == cid


def test_a_duplicate_name_yields_no_match_rather_than_a_coin_flip(conn):
    """Two Concepts sharing a name is a corpus defect. Picking one would
    attach a paper's provenance to an arbitrary choice; minting is honest."""
    _concept(conn, "concept-a", "Copy-on-Write")
    _concept(conn, "concept-b", "copy-on-write")
    assert find_concept_by_name(conn, "Copy-on-Write") is None


def test_the_eighth_writer_records_a_verdict_like_the_other_seven(conn):
    eid = _paper(conn, "p")
    cid = _concept(conn, "concept-cow", "Copy-on-Write")
    attach_existing_concept(conn, cid, CONCEPTS[0], eid, TEXT, "model-x")
    conn.commit()
    attrs = _edge_attrs(conn, cid, eid)
    assert attrs["basis"] == BASIS_EVIDENCE_TEXT
    assert attrs["model"] == "model-x"
    assert attrs["checked_at"]
    assert edge_carries_a_current_verdict(attrs)


def test_the_eighth_writer_updates_an_existing_link_instead_of_failing(conn):
    """The edges table carries UNIQUE (kind, source_id, target_id) and the 77
    reused Concepts already point at the papers being re-derived, so a plain
    insert would raise IntegrityError on the common case — part way through a
    paid run."""
    eid = _paper(conn, "p")
    cid = _concept(conn, "concept-cow", "Copy-on-Write")
    _legacy_link(conn, cid, eid)
    attach_existing_concept(conn, cid, CONCEPTS[0], eid, TEXT, "model-x")
    conn.commit()
    rows = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind='extracted-from' "
        "AND source_id=? AND target_id=?", (cid, eid)).fetchone()[0]
    assert rows == 1
    assert _edge_attrs(conn, cid, eid)["basis"] == BASIS_EVIDENCE_TEXT


# --- re-link end to end -----------------------------------------------------


def test_the_default_mode_still_stops_on_any_existing_edge(conn):
    """INV-KK-EXTRACT-IDEMPOTENT is unchanged."""
    eid = _paper(conn, "p")
    _legacy_link(conn, _concept(conn, "concept-a", "Alpha"), eid)
    client = MockLLMClient()
    result = extract_concepts(conn, eid, SessionGate(), client=client)
    assert result.concepts_created == 0
    assert client.calls == [], "the default mode must not call the model"


def test_relink_walks_past_a_legacy_edge_and_writes_a_verdict(conn):
    eid = _paper(conn, "p")
    old = _concept(conn, "concept-old", "Something Else")
    _concept(conn, "concept-cow", "Copy-on-Write")   # the vocabulary entry
    _legacy_link(conn, old, eid)
    client = MockLLMClient()
    result = extract_concepts(conn, eid, SessionGate(), client=client, relink=True)
    conn.commit()

    assert len(client.calls) == 1
    # INV-KK-EXTRACT-CONCEPT-MATCHED: linked, not minted.
    assert result.concepts_created == 0
    assert result.concepts_reused == 1
    assert result.edges_superseded == 1
    assert _edge_attrs(conn, old, eid)["superseded"] is True
    assert edge_carries_a_current_verdict(_edge_attrs(conn, "concept-cow", eid))


def test_relink_reuses_a_concept_that_already_exists_by_name(conn):
    """Without this the 77-concept vocabulary becomes five figures of
    near-duplicates, every one at weight 1 and so in violation of
    INV-KK-CONCEPT-ADMISSION."""
    eid = _paper(conn, "p")
    existing = _concept(conn, "concept-cow", "Copy-on-Write")
    _legacy_link(conn, _concept(conn, "concept-old", "Something Else"), eid)
    before = conn.execute("SELECT COUNT(*) FROM nodes WHERE kind='Concept'").fetchone()[0]

    result = extract_concepts(conn, eid, SessionGate(),
                              client=MockLLMClient(), relink=True)
    conn.commit()

    after = conn.execute("SELECT COUNT(*) FROM nodes WHERE kind='Concept'").fetchone()[0]
    assert after == before, "re-link must not mint a Concept that already exists"
    assert result.concepts_reused == 1
    assert result.concepts_created == 0
    assert result.concept_ids == [existing]


def test_relink_queues_a_candidate_when_no_concept_of_that_name_exists(conn):
    """This test asserted the opposite until 2026-09-22 — that an unmatched
    name is MINTED. INV-KK-EXTRACT-CONCEPT-MATCHED forbids it: 114 Concepts of
    weight 1 arrived that way over two batches. It is recorded as a candidate
    for a person to admit, and nothing is created."""
    from graph.concept_vocabulary import candidate_ranking

    eid = _paper(conn, "p")
    _legacy_link(conn, _concept(conn, "concept-old", "Something Else"), eid)
    before = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind='Concept'").fetchone()[0]

    result = extract_concepts(conn, eid, SessionGate(),
                              client=MockLLMClient(), relink=True)
    conn.commit()

    assert result.concepts_created == 0
    assert result.concepts_reused == 0
    assert result.concepts_rejected == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind='Concept'").fetchone()[0] == before
    # And nothing was superseded, because nothing replaced it.
    assert result.edges_superseded == 0
    queued = {c.name for c in candidate_ranking(conn)}
    assert "Copy-on-Write" in queued


def test_running_relink_twice_does_the_work_once(conn):
    """INV-KK-EXTRACT-RELINK-CONVERGENT. This is what makes re-running an
    interrupted USD-scale batch safe."""
    eid = _paper(conn, "p")
    _legacy_link(conn, _concept(conn, "concept-old", "Something Else"), eid)
    _concept(conn, "concept-cow", "Copy-on-Write")   # the vocabulary entry

    first_client = MockLLMClient()
    first = extract_concepts(conn, eid, SessionGate(), client=first_client, relink=True)
    conn.commit()
    assert first.concepts_reused == 1 and len(first_client.calls) == 1

    second_client = MockLLMClient()
    second = extract_concepts(conn, eid, SessionGate(), client=second_client, relink=True)
    conn.commit()
    assert second_client.calls == [], "the second run must not call the model"
    assert (second.concepts_created, second.concepts_reused,
            second.edges_superseded) == (0, 0, 0)
    assert select_for_relink(conn) == [], "and the paper is no longer selected"


def test_a_failed_relink_supersedes_nothing_and_is_retried(conn):
    """Superseding first and then extracting nothing would leave a paper whose
    only links are retired ones — worse than where it started."""
    eid = _paper(conn, "p")
    old = _concept(conn, "concept-old", "Something Else")
    _legacy_link(conn, old, eid)

    result = extract_concepts(conn, eid, SessionGate(),
                              client=MockLLMClient(concepts=[]), relink=True)
    conn.commit()
    assert (result.concepts_created, result.edges_superseded) == (0, 0)
    assert _edge_attrs(conn, old, eid)["superseded"] is False
    assert select_for_relink(conn) == [eid], "and it comes back next run"


def test_a_relink_dry_run_writes_nothing_and_calls_nothing(conn):
    eid = _paper(conn, "p")
    old = _concept(conn, "concept-old", "Something Else")
    _legacy_link(conn, old, eid)
    before = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]

    client = MockLLMClient()
    result = extract_concepts(conn, eid, SessionGate(), dry_run=True,
                              client=client, relink=True)

    assert client.calls == []
    assert result.prompt_tokens > 0, "a dry run still builds the prompt"
    assert conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == before
    assert _edge_attrs(conn, old, eid)["superseded"] is False


# --- the CLI surface (ALG-KK-EXTRACT-CLI) -----------------------------------
#
# Every case below passes --dry-run. extract_concepts returns before it
# constructs AnthropicClientAdapter, so no client exists and no call is made.


def _run_cli(monkeypatch, capsys, *argv):
    from ingest import cli_extract
    monkeypatch.setattr("sys.argv", ["kk-extract", *argv])
    with pytest.raises(SystemExit) as exc:
        cli_extract.main()
    out = capsys.readouterr().out
    return exc.value.code, (json.loads(out) if out.strip().startswith("{") else None)


@pytest.fixture
def corpus(tmp_path):
    """Three papers needing re-derivation, two never extracted, one empty."""
    path = tmp_path / "cli.db"
    c = init_db(path)
    for n in ("r1", "r2", "r3"):
        _paper(c, n)
        _legacy_link(c, _concept(c, f"concept-{n}", f"Old {n}"), f"ev-{n}")
    _paper(c, "u1")
    _paper(c, "u2")
    _paper(c, "e1", text="")
    c.commit()
    c.close()
    return str(path)


def test_limit_bounds_the_batch(monkeypatch, capsys, corpus):
    code, report = _run_cli(monkeypatch, capsys,
                            "--db", corpus, "--all-relink", "--limit", "2", "--dry-run")
    assert code == 0
    assert report["mode"] == "relink"
    assert report["selected"] == 3
    assert report["attempted"] == 2


def test_without_a_limit_the_whole_selection_runs(monkeypatch, capsys, corpus):
    _, report = _run_cli(monkeypatch, capsys,
                         "--db", corpus, "--all-relink", "--dry-run")
    assert (report["selected"], report["attempted"]) == (3, 3)


def test_relink_and_unextracted_select_disjoint_sets(monkeypatch, capsys, corpus):
    _, relink = _run_cli(monkeypatch, capsys,
                         "--db", corpus, "--all-relink", "--dry-run")
    _, fresh = _run_cli(monkeypatch, capsys,
                        "--db", corpus, "--all-unextracted", "--dry-run")
    assert relink["selected"] == 3
    # u1 and u2; the empty paper is filtered out before the count.
    assert fresh["selected"] == 2
    assert fresh["skipped_empty"] == 1


def test_a_limit_is_refused_for_a_single_evidence_id(monkeypatch, capsys, corpus):
    code, _ = _run_cli(monkeypatch, capsys,
                       "--db", corpus, "--evidence-id", "ev-r1", "--limit", "5")
    assert code == 2


def test_a_limit_below_one_is_refused(monkeypatch, capsys, corpus):
    code, _ = _run_cli(monkeypatch, capsys,
                       "--db", corpus, "--all-relink", "--limit", "0", "--dry-run")
    assert code == 2


def test_the_batch_modes_remain_mutually_exclusive(monkeypatch, capsys, corpus):
    code, _ = _run_cli(monkeypatch, capsys, "--db", corpus,
                       "--all-relink", "--all-unextracted", "--dry-run")
    assert code == 2


def test_a_dry_run_leaves_the_database_untouched(monkeypatch, capsys, corpus):
    import sqlite3
    before = sqlite3.connect(corpus).execute(
        "SELECT COUNT(*) FROM edges").fetchone()[0]
    _run_cli(monkeypatch, capsys, "--db", corpus, "--all-relink", "--dry-run")
    after = sqlite3.connect(corpus).execute(
        "SELECT COUNT(*) FROM edges").fetchone()[0]
    assert after == before
