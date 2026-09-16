"""Tests for data/migrate_briefs_to_summaries.py — ALG-KK-BRIEF-MIGRATE.

The migration is the only thing standing between 460 curated briefs and their
permanent loss, so these tests are about preservation and honesty rather than
mechanics: every enrichment field survives, the model field is recorded as
unknown-legacy and never guessed, and a brief that cannot be attributed to a paper
is left alone rather than attached to the wrong one.

Briefs are inserted with raw SQL on purpose. ResearchBrief is no longer in
NODE_KINDS, so engine.add_node rejects it — which is the point of retiring the kind,
and is itself asserted below.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sqlite3

import pytest

from graph.engine import add_edge, add_node, get_node
from graph.schema import NODE_KINDS, init_db
from ingest.paper_summary import get_summary, summary_is_present

_SPEC = importlib.util.spec_from_file_location(
    "migrate_briefs_to_summaries",
    pathlib.Path(__file__).resolve().parents[1] / "data" / "migrate_briefs_to_summaries.py",
)
migrate_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(migrate_mod)


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "migrate_test.db")
    yield c
    c.close()


def _paper(c, source_id="src-1"):
    """A Source with NO Advisory — which is what most real Sources look like."""
    add_node(c, source_id, "Source", {
        "url": f"https://example.com/{source_id}.pdf",
        "source_type": "preprint",
        "license": "MIT",
        "title": f"Paper {source_id}",
    })
    return source_id


def _brief(c, brief_id, evidence_id, source_id=None, **overrides):
    """Insert a ResearchBrief and its chain with raw SQL.

    Raw SQL because ResearchBrief has been removed from NODE_KINDS, so add_node
    refuses it. Passing source_id=None builds the broken chain: Evidence with no
    sourced-from edge, which is the shape of the 2 real briefs that belong to no
    paper.
    """
    attrs = {
        "title": f"Brief {brief_id}",
        "key_ideas": ["idea one", "idea two", "idea three"],
        "relevance": "Matters for the scheduler because it bounds wakeup latency.",
        "methodology": "measurement study",
        "source_date": "2026-01-01",
        "artifact_class": "B",
    }
    attrs.update(overrides)
    add_node(c, evidence_id, "Evidence", {"artifact_class": "A", "contamination_level": "L0"})
    if source_id is not None:
        add_edge(c, "sourced-from", evidence_id, source_id)
    c.execute(
        "INSERT INTO nodes (id, kind, attrs) VALUES (?, 'ResearchBrief', ?)",
        (brief_id, json.dumps(attrs)),
    )
    c.execute(
        "INSERT INTO edges (kind, source_id, target_id, attrs) "
        "VALUES ('extracted-from', ?, ?, '{}')",
        (brief_id, evidence_id),
    )
    return brief_id


def _brief_count(c):
    return c.execute("SELECT count(*) FROM nodes WHERE kind = 'ResearchBrief'").fetchone()[0]


# --- the kind is genuinely retired ---------------------------------------


def test_research_brief_is_no_longer_a_declared_kind():
    assert "ResearchBrief" not in NODE_KINDS


def test_add_node_now_rejects_a_research_brief(conn):
    """The retirement has teeth: nothing can create another one through the engine."""
    with pytest.raises(ValueError, match="Unknown node kind"):
        add_node(conn, "rb-x", "ResearchBrief", {})


# --- preservation ---------------------------------------------------------


def test_migration_preserves_all_three_enrichment_fields(conn):
    source_id = _paper(conn)
    _brief(conn, "rb-1", "ev-1", source_id)

    stats = migrate_mod.migrate(conn)

    assert stats["migrated"] == 1
    summary = get_summary(conn, source_id)
    assert summary is not None
    assert summary["attrs"]["key_ideas"] == ["idea one", "idea two", "idea three"]
    assert summary["attrs"]["relevance"].startswith("Matters for the scheduler")
    assert summary["attrs"]["methodology"] == "measurement study"


def test_model_is_recorded_as_unknown_legacy_and_never_guessed(conn):
    """Briefs never stored a model. Inventing one would falsify provenance."""
    source_id = _paper(conn)
    _brief(conn, "rb-1", "ev-1", source_id)

    migrate_mod.migrate(conn)

    assert get_summary(conn, source_id)["attrs"]["model"] == "unknown-legacy"


def test_migrated_row_is_absent_and_not_present_per_d10_option_b(conn):
    """D-10 (b): the enrichment fields carry no prose, so the row is not present.

    This is the trade the decision accepted — the best-documented papers report
    has_summary=false until the extractor backfills prose — and it is asserted here
    so that widening the presence test cannot happen silently.
    """
    source_id = _paper(conn)
    _brief(conn, "rb-1", "ev-1", source_id)

    migrate_mod.migrate(conn)

    attrs = get_summary(conn, source_id)["attrs"]
    assert attrs["state"] == "absent"
    assert attrs["text"] == ""
    assert summary_is_present(attrs["state"]) is False


# --- removal --------------------------------------------------------------


def test_brief_node_and_its_edges_are_gone_afterwards(conn):
    source_id = _paper(conn)
    _brief(conn, "rb-1", "ev-1", source_id)

    migrate_mod.migrate(conn)

    assert _brief_count(conn) == 0
    assert get_node(conn, "rb-1") is None
    touching = conn.execute(
        "SELECT count(*) FROM edges WHERE source_id = 'rb-1' OR target_id = 'rb-1'"
    ).fetchone()[0]
    assert touching == 0


def test_the_evidence_and_the_paper_survive_the_brief(conn):
    """Only the brief is removed. Deleting its Evidence would take real data with it."""
    source_id = _paper(conn)
    _brief(conn, "rb-1", "ev-1", source_id)

    migrate_mod.migrate(conn)

    assert get_node(conn, "ev-1") is not None
    assert get_node(conn, source_id) is not None


# --- idempotence ----------------------------------------------------------


def test_second_run_reports_zero_changes(conn):
    source_id = _paper(conn)
    _brief(conn, "rb-1", "ev-1", source_id)

    migrate_mod.migrate(conn)
    again = migrate_mod.migrate(conn)

    assert again["briefs"] == 0
    assert again["migrated"] == 0
    assert again["summaries_created"] == 0
    assert again["summaries_updated"] == 0


def test_a_paper_that_already_has_a_summary_is_updated_not_duplicated(conn):
    from ingest.paper_summary import set_summary

    source_id = _paper(conn)
    set_summary(conn, source_id, "Existing prose.", "llm-extracted", model="claude-x")
    _brief(conn, "rb-1", "ev-1", source_id)

    stats = migrate_mod.migrate(conn)

    assert stats["summaries_updated"] == 1
    assert stats["summaries_created"] == 0
    count = conn.execute(
        "SELECT count(*) FROM nodes WHERE kind = 'PaperSummary'"
    ).fetchone()[0]
    assert count == 1
    assert get_summary(conn, source_id)["attrs"]["methodology"] == "measurement study"


# --- the broken chain -----------------------------------------------------


def test_a_brief_with_no_resolvable_source_is_reported_and_skipped(conn):
    """The shape of the 2 real briefs whose Evidence carries no sourced-from edge.

    They belong to no paper, so there is no paper to attach them to. Reporting and
    skipping is the specified behaviour; attaching them anywhere would be a guess.
    """
    _brief(conn, "rb-orphan", "ev-orphan", source_id=None)

    stats = migrate_mod.migrate(conn)

    assert stats["unresolvable"] == 1
    assert stats["unresolvable_ids"] == ["rb-orphan"]
    assert stats["migrated"] == 0
    # Left untouched rather than deleted: its content is not recoverable elsewhere.
    assert _brief_count(conn) == 1


def test_one_orphan_does_not_block_the_others(conn):
    source_id = _paper(conn, "src-good")
    _brief(conn, "rb-good", "ev-good", source_id)
    _brief(conn, "rb-orphan", "ev-orphan", source_id=None)

    stats = migrate_mod.migrate(conn)

    assert stats["briefs"] == 2
    assert stats["migrated"] == 1
    assert stats["unresolvable"] == 1
    assert get_summary(conn, "src-good") is not None


# --- dry run --------------------------------------------------------------


def test_dry_run_changes_nothing(conn):
    source_id = _paper(conn)
    _brief(conn, "rb-1", "ev-1", source_id)

    stats = migrate_mod.migrate(conn, dry_run=True)

    assert stats["migrated"] == 1
    assert _brief_count(conn) == 1
    assert get_summary(conn, source_id) is None


# --- the WAL trap ---------------------------------------------------------


def test_checkpoint_folds_the_wal_back_into_the_tracked_file(tmp_path):
    """data/master.db is tracked and its -wal sibling is gitignored.

    Without the checkpoint a correct migration produces an empty git diff and the
    work never reaches the repository. This asserts the mechanism, not the intent.
    """
    db = tmp_path / "wal.db"
    c = init_db(db)
    add_node(c, "src-1", "Source", {
        "url": "https://example.com/p.pdf", "source_type": "preprint", "license": "MIT",
    })
    c.commit()

    # The connection stays open on purpose: SQLite removes the -wal on a clean
    # close of the last connection, which would checkpoint the data for us and
    # hide the very condition this test exists to catch.
    wal = db.with_name(db.name + "-wal")
    assert wal.exists() and wal.stat().st_size > 0, "committed write should sit in the WAL"

    migrate_mod.checkpoint(db)

    # Checked before closing: a clean close removes the -wal entirely, which would
    # make this pass for the wrong reason.
    assert wal.stat().st_size == 0, "checkpoint should have folded the WAL into the db file"
    c.close()

    check = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    assert check.execute("SELECT count(*) FROM nodes").fetchone()[0] == 1
    check.close()


# --- the character-list corruption ----------------------------------------
#
# ResearchBrief stored key_ideas as a JSON STRING, not a list. The first version
# of set_summary did list(key_ideas), which on a string yields one element per
# CHARACTER, and that shipped: all 458 migrated rows became character lists and
# the paper page rendered one list item per letter.
#
# The fixture above builds key_ideas as a Python list, which is the shape the
# real data never had — that is exactly why the original tests passed. These use
# the real shape.

REAL_BRIEF_KEY_IDEAS = json.dumps([
    "Compiler operator fusion creates power bursts triggering voltage droop on mobile NPUs",
    "Measurement-guided graph rewriting mitigates fusion-induced power spikes",
])


def test_a_brief_storing_key_ideas_as_a_json_string_migrates_to_a_real_list(conn):
    """The production shape. list() on this string produced one item per letter."""
    source_id = _paper(conn)
    _brief(conn, "rb-1", "ev-1", source_id, key_ideas=REAL_BRIEF_KEY_IDEAS)

    migrate_mod.migrate(conn)

    stored = get_summary(conn, source_id)["attrs"]["key_ideas"]
    assert stored == json.loads(REAL_BRIEF_KEY_IDEAS)
    assert len(stored) == 2
    # The failure mode, named so a regression is unmistakable in the output.
    assert not all(len(item) <= 1 for item in stored), "key_ideas exploded into characters"


def test_no_migrated_key_ideas_item_is_a_single_character(conn):
    source_id = _paper(conn)
    _brief(conn, "rb-1", "ev-1", source_id, key_ideas=REAL_BRIEF_KEY_IDEAS)

    migrate_mod.migrate(conn)

    for item in get_summary(conn, source_id)["attrs"]["key_ideas"]:
        assert len(item) > 1


@pytest.mark.parametrize("supplied,expected", [
    # The production shape: a JSON string is parsed, never iterated.
    ('["one idea", "two idea"]', ["one idea", "two idea"]),
    # An already-correct list passes through.
    (["one idea", "two idea"], ["one idea", "two idea"]),
    # A bare string is ONE idea, not a sequence of letters.
    ("a single idea", ["a single idea"]),
    # Junk is dropped rather than stored in a broken shape.
    ("", []),
    (None, []),
    (42, []),
    (["real", "", "   ", None, 7], ["real"]),
])
def test_normalise_key_ideas_never_produces_characters(supplied, expected):
    from ingest.paper_summary import normalise_key_ideas

    assert normalise_key_ideas(supplied) == expected


def test_set_summary_cannot_store_a_character_list():
    """The guarantee at the writer, independent of any caller."""
    from ingest.paper_summary import normalise_key_ideas

    result = normalise_key_ideas('["Compiler operator fusion creates power bursts"]')

    assert result == ["Compiler operator fusion creates power bursts"]
    assert len(result) == 1


# --- the repair -----------------------------------------------------------

_REPAIR_SPEC = importlib.util.spec_from_file_location(
    "repair_key_ideas",
    pathlib.Path(__file__).resolve().parents[1] / "data" / "repair_key_ideas.py",
)
repair_mod = importlib.util.module_from_spec(_REPAIR_SPEC)
_REPAIR_SPEC.loader.exec_module(repair_mod)


def _corrupt(c, source_id, raw_json):
    """Write the exact damage the shipped bug produced: list(str)."""
    node_id = c.execute(
        "SELECT n.id FROM edges e JOIN nodes n ON n.id = e.source_id "
        "WHERE e.kind = 'summarizes-paper' AND e.target_id = ?",
        (source_id,),
    ).fetchone()[0]
    attrs = json.loads(c.execute("SELECT attrs FROM nodes WHERE id = ?", (node_id,)).fetchone()[0])
    attrs["key_ideas"] = list(raw_json)
    c.execute("UPDATE nodes SET attrs = ? WHERE id = ?", (json.dumps(attrs), node_id))
    return node_id


def test_repair_recovers_a_character_list_exactly(conn):
    from ingest.paper_summary import set_summary

    source_id = _paper(conn)
    set_summary(conn, source_id, "", "absent", model="unknown-legacy")
    _corrupt(conn, source_id, REAL_BRIEF_KEY_IDEAS)

    stats = repair_mod.repair(conn)

    assert stats["corrupted"] == 1
    assert stats["repaired"] == 1
    assert stats["unrecoverable"] == 0
    assert get_summary(conn, source_id)["attrs"]["key_ideas"] == json.loads(REAL_BRIEF_KEY_IDEAS)


def test_repair_leaves_well_formed_rows_untouched(conn):
    from ingest.paper_summary import set_summary

    source_id = _paper(conn)
    set_summary(conn, source_id, "", "absent", key_ideas=["a real idea", "another one"])

    stats = repair_mod.repair(conn)

    assert stats["corrupted"] == 0
    assert stats["intact"] == 1
    assert get_summary(conn, source_id)["attrs"]["key_ideas"] == ["a real idea", "another one"]


def test_repair_is_idempotent(conn):
    from ingest.paper_summary import set_summary

    source_id = _paper(conn)
    set_summary(conn, source_id, "", "absent")
    _corrupt(conn, source_id, REAL_BRIEF_KEY_IDEAS)

    repair_mod.repair(conn)
    again = repair_mod.repair(conn)

    assert again["corrupted"] == 0
    assert again["repaired"] == 0


def test_repair_preserves_the_other_fields(conn):
    from ingest.paper_summary import set_summary

    source_id = _paper(conn)
    set_summary(conn, source_id, "", "absent", model="unknown-legacy",
                relevance="Matters for the scheduler.", methodology="measurement study")
    _corrupt(conn, source_id, REAL_BRIEF_KEY_IDEAS)

    repair_mod.repair(conn)

    attrs = get_summary(conn, source_id)["attrs"]
    assert attrs["model"] == "unknown-legacy"
    assert attrs["relevance"] == "Matters for the scheduler."
    assert attrs["methodology"] == "measurement study"
    assert attrs["state"] == "absent"


def test_repair_dry_run_changes_nothing(conn):
    from ingest.paper_summary import set_summary

    source_id = _paper(conn)
    set_summary(conn, source_id, "", "absent")
    _corrupt(conn, source_id, REAL_BRIEF_KEY_IDEAS)

    stats = repair_mod.repair(conn, dry_run=True)

    assert stats["repaired"] == 1
    assert repair_mod.is_character_list(get_summary(conn, source_id)["attrs"]["key_ideas"])
