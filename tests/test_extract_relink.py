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
    # THE OLD LINK IS NOW RETIRED, AND THE ASSERTION BELOW WAS INVERTED ON
    # 2026-09-28. This test said "nothing was superseded, because nothing
    # replaced it", which is exactly the behaviour a paid 20-paper batch showed
    # to be non-terminating: the model READ the paper, proposed a name the
    # vocabulary does not hold, and the false title-derived link survived to be
    # re-examined by every future run. concepts_rejected > 0 is the proof an
    # answer was given, and INV-KK-EXTRACT-NEGATIVE-VERDICT records it. Nothing
    # REPLACES the link because nothing should: the honest state of a paper
    # about none of our concepts is no concept link at all.
    assert result.edges_superseded == 1
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


def test_the_report_names_concepts_rejected(monkeypatch, capsys, corpus):
    """The number that was computed and thrown away.

    extract_concepts has carried concepts_rejected on ExtractionResult since
    the matching path landed, and the unit test above asserts it. But main()
    builds its per-result dict field by field and simply omitted this one, so
    the 20-paper run of 2026-09-22 printed no rejection count at all while
    writing 43 candidate rows. A report that is silently incomplete is worse
    than one that is visibly wrong, and this is the number an operator reads
    to judge whether the vocabulary covers the corpus.

    This test runs the CLI for real — NOT --dry-run, because a dry run returns
    before a client exists and would never reach the counting. client_for is
    replaced, so no network call is made; a version of this test that reached
    the network would be a defect in the test.
    """
    import sqlite3

    from ingest import cli_extract

    monkeypatch.setattr(cli_extract, "client_for", lambda provider: MockLLMClient())
    before = sqlite3.connect(corpus).execute(
        "SELECT COUNT(*) FROM nodes WHERE kind='Concept'").fetchone()[0]

    code, report = _run_cli(monkeypatch, capsys,
                            "--db", corpus, "--all-relink", "--limit", "1")

    assert code == 0
    # The mock proposes Copy-on-Write; the corpus vocabulary holds only
    # "Old r1"/"Old r2"/"Old r3", so it matches nothing and is queued.
    assert report["results"][0]["concepts_rejected"] == 1
    assert report["concepts_rejected"] == 1, "and it reaches the run totals"
    assert report["concepts_created"] == 0, "a rejection is not a creation"

    after = sqlite3.connect(corpus)
    assert after.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind='Concept'").fetchone()[0] == before
    assert after.execute(
        "SELECT COUNT(*) FROM concept_candidates").fetchone()[0] == 1, \
        "the rejected name is queued for a human, not discarded"


def test_every_counter_in_a_result_reaches_the_report(monkeypatch, capsys, corpus):
    """The hand-built dict is the defect, so guard its shape and not one field.

    main() maps ExtractionResult onto JSON field by field. concepts_rejected
    was dropped that way and nothing noticed for a whole paid batch. Every
    counter the report claims to total must be present in each per-result
    dict, or the sum() over them raises KeyError rather than reporting zero.
    """
    monkeypatch.setattr(
        __import__("ingest.cli_extract", fromlist=["x"]),
        "client_for", lambda provider: MockLLMClient())
    _, report = _run_cli(monkeypatch, capsys,
                         "--db", corpus, "--all-relink", "--limit", "1")

    totalled = {"concepts_created", "concepts_reused",
                "concepts_rejected", "edges_superseded"}
    for row in report["results"]:
        missing = totalled - set(row)
        assert not missing, f"per-result dict dropped {sorted(missing)}"
        for k in totalled:
            assert report[k] == sum(r[k] for r in report["results"])


# --- IFC-KK-PAPER-KERNEL: which kernel the paper is about -------------------


def _kernel(conn, name):
    add_node(conn, f"k-{normalise_concept_name(name).replace(' ', '-')}", "Kernel", {
        "name": name, "description": f"{name}.", "kernel_type": "general-purpose"})
    conn.commit()


class KernelMockClient:
    """Returns a dict response naming a kernel, the shape the field needs."""

    def __init__(self, kernel, concepts=None):
        self.kernel = kernel
        self.concepts = [] if concepts is None else concepts
        self.calls: list[dict] = []

    def create_message(self, model, system, user, max_tokens):
        # system is recorded since 2026-09-28: the vocabularies live there now
        # (INV-KK-LLM-CACHE-STABLE-PREFIX), so a double that discarded it could
        # not see what the model was actually shown.
        self.calls.append({"model": model, "system": system, "user": user})
        return {"text": json.dumps({"concepts": self.concepts, "kernel": self.kernel}),
                "prompt_tokens": 100, "response_tokens": 50}


def test_a_named_kernel_is_associated_with_the_paper_not_the_evidence(conn):
    """Operator decision: the edge hangs off Source, the stable layer."""
    eid = _paper(conn, "p")
    _kernel(conn, "Linux Mainline")
    result = extract_concepts(conn, eid, SessionGate(),
                              client=KernelMockClient("Linux Mainline"))
    conn.commit()

    assert result.kernel_id == "k-linux-mainline"
    assert result.kernels_rejected == 0
    rows = conn.execute(
        "SELECT source_id, target_id FROM edges WHERE kind = 'about-kernel'").fetchall()
    assert rows == [("src-p", "k-linux-mainline")], "the edge is not on the Source"


def test_none_writes_no_edge_at_all(conn):
    """'none' is a permitted answer and is EXPECTED to be the common one.

    This corpus is broad systems research, not kernel documentation — the
    concept vocabulary matched 0 of 43 proposed names on 2026-09-22. Forcing a
    choice from a four-item list would manufacture a Linux association for
    every paper that is not about a kernel, and those edges would be
    indistinguishable from real ones.
    """
    eid = _paper(conn, "p")
    _kernel(conn, "Linux Mainline")
    result = extract_concepts(conn, eid, SessionGate(),
                              client=KernelMockClient("none"))
    conn.commit()
    assert result.kernel_id == ""
    assert result.kernels_rejected == 0, "'none' is an answer, not a rejection"
    assert conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind = 'about-kernel'").fetchone()[0] == 0


def test_a_kernel_not_in_the_table_is_DROPPED_and_never_created(conn):
    """INV-KK-PAPER-KERNEL-MATCHED. The same rule concepts follow: extraction
    must not change how many Kernels exist. Seeding non-Linux kernels is human
    curation (ANN-KK-KERNEL-CURATION-GAP) and no model judgement substitutes."""
    eid = _paper(conn, "p")
    _kernel(conn, "Linux Mainline")
    before = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind = 'Kernel'").fetchone()[0]

    result = extract_concepts(conn, eid, SessionGate(),
                              client=KernelMockClient("seL4"))
    conn.commit()

    assert result.kernel_id == ""
    assert result.kernels_rejected == 1, "a dropped name must be counted, not silent"
    assert conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind = 'Kernel'").fetchone()[0] == before
    assert conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind = 'about-kernel'").fetchone()[0] == 0


def test_the_kernel_vocabulary_reaches_the_prompt(conn):
    """The failure of NOT showing a vocabulary is measured: a matcher that
    required an unseen exact name matched 0 of 114 candidates."""
    eid = _paper(conn, "p")
    _kernel(conn, "Linux Mainline")
    _kernel(conn, "PREEMPT_RT")
    client = KernelMockClient("none")
    extract_concepts(conn, eid, SessionGate(), client=client)
    prompt = client.calls[0]["user"]
    # Moved into the system prompt 2026-09-28 (INV-KK-LLM-CACHE-STABLE-PREFIX):
    # the kernel names are constant across a run and belong in the cached
    # prefix, not re-sent with every paper. Asserted against what the client
    # actually received rather than a reconstruction of it.
    system = client.calls[0]["system"]
    assert "Linux Mainline" in system and "PREEMPT_RT" in system
    assert "Linux Mainline" not in prompt, "still re-sent per paper"
    assert '"none"' in system, "the none option must still be visible"


def test_matching_is_exact_and_does_not_fuzz_like_the_concept_matcher(conn):
    """Four proper nouns given verbatim: a near miss is not a paraphrase to
    rescue, and associating a paper with the WRONG kernel is worse than none."""
    eid = _paper(conn, "p")
    _kernel(conn, "Linux Mainline")
    result = extract_concepts(conn, eid, SessionGate(),
                              client=KernelMockClient("Linux Mainlin"))
    conn.commit()
    assert result.kernel_id == ""
    assert result.kernels_rejected == 1


def test_re_running_does_not_duplicate_the_association(conn):
    """A relink run re-asks the same question of the same paper. A plain INSERT
    would raise on UNIQUE (kind, source_id, target_id) mid-batch."""
    eid = _paper(conn, "p")
    _kernel(conn, "Linux Mainline")
    for _ in range(3):
        extract_concepts(conn, eid, SessionGate(),
                         client=KernelMockClient("Linux Mainline"))
        conn.commit()
    assert conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind = 'about-kernel'").fetchone()[0] == 1


def test_a_bare_list_response_carries_no_kernel_and_does_not_error(conn):
    """The list form predates the field; it must degrade, not raise."""
    eid = _paper(conn, "p")
    _kernel(conn, "Linux Mainline")
    result = extract_concepts(conn, eid, SessionGate(), client=MockLLMClient())
    conn.commit()
    assert result.kernel_id == ""
    assert result.kernels_rejected == 0


def test_the_cli_reports_the_kernel_counters(monkeypatch, capsys, corpus):
    import sqlite3
    from ingest import cli_extract

    c = sqlite3.connect(corpus)
    _kernel(c, "Linux Mainline")
    c.close()

    monkeypatch.setattr(cli_extract, "client_for",
                        lambda provider: KernelMockClient("Linux Mainline"))
    _, report = _run_cli(monkeypatch, capsys,
                         "--db", corpus, "--all-relink", "--limit", "1")
    assert report["kernels_associated"] == 1
    assert report["kernels_rejected"] == 0
    assert report["results"][0]["kernel_id"] == "k-linux-mainline"


# --- the negative verdict (INV-KK-EXTRACT-NEGATIVE-VERDICT) -----------------
#
# FOUND BY A PAID BATCH ON 2026-09-28. Twenty papers from the relink queue:
# concepts_reused 0, concepts_rejected 57, edges_superseded 0, queue 1,322
# before and 1,322 after. The model read every paper and correctly concluded
# each was about none of 296 kernel concepts, and the machinery could not tell
# that answer from a crash — so the false link survived and the paper stayed in
# the queue to be paid for again. The legacy linker was substring-matching
# titles: "A Task Equalization Algorithm Incorporating BLOCKCHAIN" was linked
# to Block Device Layer, and "Improving IoT Intrusion Detection" to Linux
# Security Modules. Two concepts hold 798 of the 2,022 legacy links.

class NoMatchClient:
    """Proposes names, none of which the vocabulary contains — the measured
    majority case, not a corner."""

    def __init__(self):
        self.calls: list[dict] = []

    def create_message(self, model, system, user, max_tokens):
        self.calls.append({"model": model, "user": user})
        return {"text": json.dumps({"concepts": [{
            "name": "RowHammer Vulnerability",
            "description": "Repeated DRAM row access flipping adjacent bits.",
            "key_properties": ["row-granular"], "tradeoffs": ["refresh cost"],
            "design_rationale": "n/a", "subsystem": "Memory",
            "relationships": [], "invariants": [],
        }]}), "prompt_tokens": 3400, "response_tokens": 200,
            "cached_tokens": 2048, "cache_written_tokens": 0}


class UnparseableClient:
    """Returns nothing usable — the TRANSIENT failure, which must still retry.
    ev-arxiv-027e07c3 on 2026-09-21 was this shape and succeeded on its retry."""

    def __init__(self):
        self.calls: list[dict] = []

    def create_message(self, model, system, user, max_tokens):
        self.calls.append({"model": model, "user": user})
        return {"text": "not json at all", "prompt_tokens": 3400,
                "response_tokens": 5}


def _verdict(conn, eid):
    row = conn.execute(
        "SELECT json_extract(attrs, '$.concept_verdict') FROM nodes WHERE id = ?",
        (eid,)).fetchone()
    return json.loads(row[0]) if row and row[0] else None


def test_a_paper_about_nothing_we_know_has_its_false_link_retired(conn):
    """The answer "none of these" is an ANSWER. The honest state of an IoT
    intrusion-detection paper is NO concept link, not a link to Linux Security
    Modules."""
    eid = _paper(conn, "1", "A study of IoT intrusion detection with SMOTE.")
    cid = _concept(conn, "concept-lsm", "Linux Security Modules")
    _legacy_link(conn, cid, eid)

    r = extract_concepts(conn, eid, SessionGate(), client=NoMatchClient(),
                         relink=True)

    assert r.concepts_reused == 0
    assert r.concepts_created == 0
    assert r.concepts_rejected == 1
    assert r.edges_superseded == 1
    assert _edge_attrs(conn, cid, eid)["superseded"] is True
    assert _verdict(conn, eid)["result"] == "no-match"


def test_the_answered_paper_leaves_the_relink_queue(conn):
    """THE NUMBER THAT MADE THIS A DEFECT: the queue stood at 1,322 before a
    paid batch and 1,322 after. Selection and the in-function guard read one
    predicate, so a paper the selection skips is one the function would have
    returned early on."""
    eid = _paper(conn, "1", "A study of IoT intrusion detection with SMOTE.")
    cid = _concept(conn, "concept-lsm", "Linux Security Modules")
    _legacy_link(conn, cid, eid)
    assert eid in select_for_relink(conn)

    extract_concepts(conn, eid, SessionGate(), client=NoMatchClient(),
                     relink=True)
    conn.commit()

    assert eid not in select_for_relink(conn)


def test_a_second_run_on_an_answered_paper_calls_no_model(conn):
    """Convergence, for the negative case: the second run does no work at all."""
    eid = _paper(conn, "1", "A study of IoT intrusion detection with SMOTE.")
    _legacy_link(conn, _concept(conn, "concept-lsm", "Linux Security Modules"), eid)
    extract_concepts(conn, eid, SessionGate(), client=NoMatchClient(), relink=True)
    conn.commit()

    second = NoMatchClient()
    r = extract_concepts(conn, eid, SessionGate(), client=second, relink=True)

    assert second.calls == []
    assert r.concepts_created == 0
    assert r.edges_superseded == 0


def test_an_unparseable_answer_is_still_retried_and_touches_nothing(conn):
    """THE CASE THE OLD FAILURE PATH WAS WRITTEN FOR, and it is unchanged.
    concepts_rejected == 0 is what tells it apart: the model proposed no names
    at all, so nothing was read and nothing was concluded."""
    eid = _paper(conn, "1")
    cid = _concept(conn, "concept-cow", "Copy-on-Write")
    _legacy_link(conn, cid, eid)

    r = extract_concepts(conn, eid, SessionGate(), client=UnparseableClient(),
                         relink=True)
    conn.commit()

    assert r.concepts_rejected == 0
    assert r.edges_superseded == 0
    assert _edge_attrs(conn, cid, eid)["superseded"] is False
    assert _verdict(conn, eid) is None
    assert eid in select_for_relink(conn), "a crashed run must be retried"


def test_a_match_still_supersedes_and_writes_no_verdict(conn):
    """The positive path is untouched: a replacement exists, so the old link is
    retired and no no-match verdict is written."""
    eid = _paper(conn, "1")
    old = _concept(conn, "concept-lsm", "Linux Security Modules")
    _concept(conn, "concept-cow", "Copy-on-Write")
    _legacy_link(conn, old, eid)

    r = extract_concepts(conn, eid, SessionGate(), client=MockLLMClient(),
                         relink=True)
    conn.commit()

    assert r.concepts_reused == 1
    assert r.edges_superseded == 1
    assert _verdict(conn, eid) is None
    assert eid not in select_for_relink(conn)


def test_the_verdict_is_not_written_outside_relink_mode(conn):
    """A first extraction that matches nothing has no false link to retire, and
    inventing a verdict there would withdraw a paper from --all-unextracted
    that was never mis-linked in the first place."""
    eid = _paper(conn, "1", "A study of IoT intrusion detection with SMOTE.")

    r = extract_concepts(conn, eid, SessionGate(), client=NoMatchClient())
    conn.commit()

    assert r.concepts_rejected == 1
    assert r.edges_superseded == 0
    assert _verdict(conn, eid) is None


def test_cached_tokens_reaches_the_result(conn):
    """INV-KK-LLM-CACHE-REPORTED. The adapters have returned it since the
    prompt-caching change and it reached nothing — the one number saying whether
    the cached prefix is being hit was unobservable on the path that spends the
    most money. A ZERO means the prefix is being invalidated, and every cause of
    that is silent."""
    eid = _paper(conn, "1", "A study of IoT intrusion detection with SMOTE.")
    _legacy_link(conn, _concept(conn, "concept-lsm", "Linux Security Modules"), eid)

    r = extract_concepts(conn, eid, SessionGate(), client=NoMatchClient(),
                         relink=True)

    assert r.cached_tokens == 2048
    assert r.cache_written_tokens == 0
    assert r.prompt_tokens == 3400


# --- the candidate queue is opt-out, the count never is ---------------------


def test_no_candidates_suppresses_the_rows_and_never_the_count(conn):
    """MEASURED ACROSS 40 PAPERS: the re-link population proposes RowHammer
    Vulnerability, LeakyHammer Attack and NIFuzz, because the papers are about
    DRAM side channels rather than kernels. Queuing ~3,000 of those into a
    43-row hand-reviewed queue destroys the queue to record something already
    known. concepts_rejected must survive it: INV-KK-EXTRACT-NEGATIVE-VERDICT
    reads that counter to tell an answer from a crash, so suppressing the rows
    may never suppress the verdict."""
    from graph.concept_vocabulary import candidate_ranking

    eid = _paper(conn, "1", "A study of IoT intrusion detection with SMOTE.")
    cid = _concept(conn, "concept-lsm", "Linux Security Modules")
    _legacy_link(conn, cid, eid)

    r = extract_concepts(conn, eid, SessionGate(), client=NoMatchClient(),
                         relink=True, record_candidates=False)
    conn.commit()

    assert candidate_ranking(conn) == []
    assert r.concepts_rejected == 1
    assert r.edges_superseded == 1
    assert _verdict(conn, eid)["result"] == "no-match"
    assert eid not in select_for_relink(conn)


def test_the_queue_is_written_by_default(conn):
    """The flag is an opt-OUT. A kernel paper proposing a genuinely new name is
    the case IFC-KK-CONCEPT-CANDIDATE exists for, and it stays the default."""
    from graph.concept_vocabulary import candidate_ranking

    eid = _paper(conn, "1", "A study of IoT intrusion detection with SMOTE.")
    _legacy_link(conn, _concept(conn, "concept-lsm", "Linux Security Modules"), eid)

    extract_concepts(conn, eid, SessionGate(), client=NoMatchClient(), relink=True)
    conn.commit()

    assert {c.name for c in candidate_ranking(conn)} == {"RowHammer Vulnerability"}


# --- only concept edges are a re-link's to retire --------------------------
#
# MEASURED 2026-09-28 ON COMMITTED DATA, and it is why a 1,302-paper run was
# killed 253 papers in. extracted-from carries THIRTEEN valid source kinds and
# a re-link re-derives exactly one of them, but superseding_candidates was
# built from every edge into the Evidence. Of 25 edges superseded across 40
# papers, FIVE belonged to other writers: 2 FailureMode, 1 PerformanceProfile,
# 1 Observation, 1 KernelInvariant. At full scale that is ~325 edges retired by
# a verdict that was never about them. The kind='Concept' filter is the trap
# this codebase has now fallen into four times.


def _other_writer(conn, node_id, kind, eid, attrs):
    """An edge from one of the OTHER six provenance writers into the same
    Evidence (INV-KK-EXTRACT-PROVENANCE)."""
    add_node(conn, node_id, kind, attrs)
    add_edge(conn, "extracted-from", node_id, eid, {
        "basis": LEGACY_UNVERIFIED_BASIS, "superseded": False})
    conn.commit()
    return node_id


FAILURE_MODE = {"symptom": "stall", "blast_radius": "task",
                "recoverability": "automatic",
                "artifact_class": "abstracted-mechanism"}
OBSERVATION = {"claim": "latency rose", "confidence": "medium",
               "source_date": "2026-01-01", "artifact_class": "discourse"}


def test_a_no_match_verdict_leaves_other_writers_edges_alone(conn):
    """A verdict about CONCEPTS may not retire a FailureMode's provenance."""
    eid = _paper(conn, "1", "A study of IoT intrusion detection with SMOTE.")
    cid = _concept(conn, "concept-lsm", "Linux Security Modules")
    _legacy_link(conn, cid, eid)
    fm = _other_writer(conn, "fm-1", "FailureMode", eid, FAILURE_MODE)
    ob = _other_writer(conn, "obs-1", "Observation", eid, OBSERVATION)

    r = extract_concepts(conn, eid, SessionGate(), client=NoMatchClient(),
                         relink=True, record_candidates=False)
    conn.commit()

    assert r.edges_superseded == 1, "only the Concept edge is this run's to retire"
    assert _edge_attrs(conn, cid, eid)["superseded"] is True
    assert _edge_attrs(conn, fm, eid)["superseded"] is False
    assert _edge_attrs(conn, ob, eid)["superseded"] is False


def test_a_successful_relink_leaves_other_writers_edges_alone(conn):
    """The positive path had the same defect and it is fixed in one place."""
    eid = _paper(conn, "1")
    old = _concept(conn, "concept-lsm", "Linux Security Modules")
    _concept(conn, "concept-cow", "Copy-on-Write")
    _legacy_link(conn, old, eid)
    fm = _other_writer(conn, "fm-1", "FailureMode", eid, FAILURE_MODE)

    r = extract_concepts(conn, eid, SessionGate(), client=MockLLMClient(),
                         relink=True)
    conn.commit()

    assert r.concepts_reused == 1
    assert r.edges_superseded == 1
    assert _edge_attrs(conn, old, eid)["superseded"] is True
    assert _edge_attrs(conn, fm, eid)["superseded"] is False


def test_another_writers_edge_does_not_make_a_paper_look_answered(conn):
    """The mirror of the same trap on the SELECTION side. A paper whose only
    current edge belongs to a FailureMode still needs its concept link
    re-derived — and edge_carries_a_current_verdict reads every kind."""
    eid = _paper(conn, "1")
    cid = _concept(conn, "concept-lsm", "Linux Security Modules")
    _legacy_link(conn, cid, eid)
    add_node(conn, "fm-1", "FailureMode", FAILURE_MODE)
    add_edge(conn, "extracted-from", "fm-1", eid, {
        "basis": BASIS_EVIDENCE_TEXT, "checked_at": "2026-09-28"})
    conn.commit()

    # RECORDED, NOT FIXED HERE. select_for_relink reads every extracted-from
    # edge, so a current FailureMode edge masks a legacy Concept link. It is
    # measured at ZERO on the live corpus — all 1,433 legacy-linked Evidence are
    # selected — so closing it would be a change with no instance to justify it.
    # This test pins the behaviour so the day it stops being zero is loud.
    assert eid not in select_for_relink(conn)
    masked = conn.execute(
        "SELECT COUNT(*) FROM edges e JOIN nodes n ON e.source_id = n.id "
        "WHERE e.kind = 'extracted-from' AND e.target_id = ? AND n.kind = 'Concept' "
        "AND json_extract(e.attrs, '$.basis') = ?", (eid, LEGACY_UNVERIFIED_BASIS),
    ).fetchone()[0]
    assert masked == 1, "the legacy concept link is still there, unre-derived"


# --- a retired link is not evidence ----------------------------------------
#
# 'superseded' appeared NOWHERE in graph.rules until 2026-09-28, so marking a
# false link retired changed no weight, no admission state and no position in
# the review queue. That made the whole re-derivation unobservable: the point
# of retiring the legacy links is to correct the weights they inflated, and the
# rule reading those weights was not looking. Measured on the live corpus, the
# title-regex links account for Scheduling Classes 435 of 440, Linux Security
# Modules 347 of 358, and ALL of Adaptive CXL Memory Tiering, NUMA Topology,
# eBPF and KVM.


def test_a_superseded_link_stops_counting_toward_weight(conn):
    from graph.rules import concept_weight

    cid = _concept(conn, "concept-lsm", "Linux Security Modules")
    for n in ("a", "b", "c"):
        eid = _paper(conn, n)
        _legacy_link(conn, cid, eid)
    assert concept_weight(conn, cid) == 3

    conn.execute(
        "UPDATE edges SET attrs = json_set(attrs, '$.superseded', json('true')) "
        "WHERE kind = 'extracted-from' AND source_id = ? AND target_id = ?",
        (cid, "ev-a"))
    conn.commit()

    assert concept_weight(conn, cid) == 2


def test_the_negative_verdict_lowers_the_weight_it_should(conn):
    """End to end: the run retires the false link AND the number a curator
    reads goes down. Either half alone is worthless."""
    from graph.rules import concept_weight

    eid = _paper(conn, "1", "A study of IoT intrusion detection with SMOTE.")
    cid = _concept(conn, "concept-lsm", "Linux Security Modules")
    _legacy_link(conn, cid, eid)
    assert concept_weight(conn, cid) == 1

    extract_concepts(conn, eid, SessionGate(), client=NoMatchClient(),
                     relink=True, record_candidates=False)
    conn.commit()

    assert concept_weight(conn, cid) == 0


def test_the_papers_page_and_the_badge_cannot_disagree(conn):
    """A page listing papers the badge no longer counts is worse than either
    being wrong alone, so both read graph.rules.not_superseded."""
    from graph.rules import concept_weight
    from web.routes import _CONCEPT_PAPERS_SQL

    cid = _concept(conn, "concept-lsm", "Linux Security Modules")
    for n in ("a", "b"):
        _legacy_link(conn, cid, _paper(conn, n))
    conn.execute(
        "UPDATE edges SET attrs = json_set(attrs, '$.superseded', json('true')) "
        "WHERE kind = 'extracted-from' AND source_id = ? AND target_id = ?",
        (cid, "ev-a"))
    conn.commit()

    listed = conn.execute(_CONCEPT_PAPERS_SQL, (cid, 50, 0)).fetchall()
    assert len(listed) == concept_weight(conn, cid) == 1


# --- a re-link of a paper that MATCHES must not raise -----------------------
#
# MEASURED 2026-09-28: the only two papers to fail a 1,302-paper re-derivation
# were the two that matched the vocabulary — "Agile TLB Prefetching" against
# Translation Lookaside Buffer, and "Should BBR be the default TCP Congestion
# Control Protocol?" against TCP Congestion Control. Papers that MATCH were the
# papers that broke, which is the worst possible selectivity for a re-link
# whose entire purpose is to find matches.
#
# Two unguarded add_edge calls: classifier.assign_subsystems wrote belongs-to
# without checking, while the KernelInvariant branch twenty lines below it
# checked — and wire_relationships wrote its edge the same way. Neither fired
# in the 2026-09-21 batches because those MINTED their concepts, so every
# belongs-to edge was new. INV-KK-EXTRACT-CONCEPT-MATCHED stopped the minting,
# and this surfaced on the first run that actually reused.


def test_relinking_a_concept_that_already_belongs_somewhere_does_not_raise(conn):
    from graph.rules import concept_weight

    eid = _paper(conn, "1")
    cid = _concept(conn, "concept-cow", "Copy-on-Write")
    add_node(conn, "sub-memory", "Subsystem", {"name": "Memory"})
    add_edge(conn, "belongs-to", cid, "sub-memory")
    _legacy_link(conn, cid, eid)
    conn.commit()

    r = extract_concepts(conn, eid, SessionGate(), client=MockLLMClient(),
                         relink=True)
    conn.commit()

    assert r.concepts_reused == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind='belongs-to' AND source_id=?",
        (cid,)).fetchone()[0] == 1, "one edge, not a duplicate and not a raise"


def test_a_relationship_the_pair_already_carries_is_skipped_not_raised(conn):
    eid = _paper(conn, "1")
    cid = _concept(conn, "concept-cow", "Copy-on-Write")
    other = _concept(conn, "concept-pt", "Page Table")
    add_edge(conn, "prerequisite", cid, other)
    _legacy_link(conn, cid, eid)
    conn.commit()

    client = MockLLMClient(concepts=[{
        **CONCEPTS[0],
        "relationships": [{"kind": "prerequisite", "target": "Page Table"}],
    }, {
        "name": "Page Table", "description": "Mapping virtual to physical.",
        "key_properties": ["hierarchical"], "tradeoffs": ["walk cost"],
        "design_rationale": "n/a", "subsystem": "Memory",
        "relationships": [], "invariants": [],
    }])
    r = extract_concepts(conn, eid, SessionGate(), client=client, relink=True)
    conn.commit()

    assert r.concepts_reused == 2
    assert conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind='prerequisite' AND source_id=? "
        "AND target_id=?", (cid, other)).fetchone()[0] == 1


def test_a_matched_relink_supersedes_the_legacy_link_end_to_end(conn):
    """THE WHOLE POINT, and it could not happen before this fix: a paper that
    matches gets its new link AND loses its false one, in one call that
    completes."""
    from graph.rules import concept_weight

    eid = _paper(conn, "1")
    cow = _concept(conn, "concept-cow", "Copy-on-Write")
    lsm = _concept(conn, "concept-lsm", "Linux Security Modules")
    add_node(conn, "sub-memory", "Subsystem", {"name": "Memory"})
    add_edge(conn, "belongs-to", cow, "sub-memory")
    _legacy_link(conn, lsm, eid)
    conn.commit()
    assert concept_weight(conn, lsm) == 1

    r = extract_concepts(conn, eid, SessionGate(), client=MockLLMClient(),
                         relink=True)
    conn.commit()

    assert r.concepts_reused == 1
    assert r.edges_superseded == 1
    assert concept_weight(conn, lsm) == 0
    assert concept_weight(conn, cow) == 1
    assert eid not in select_for_relink(conn)
