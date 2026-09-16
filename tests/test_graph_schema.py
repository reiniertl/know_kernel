"""Tests for know_kernel.graph.schema — init_db, table creation, kind enums."""

from __future__ import annotations

import importlib
import pathlib
import sqlite3

import pytest

from graph.schema import (
    DATE_ATTRS,
    EDGE_KINDS,
    EDGE_VALID_PAIRS,
    ID_PREFIXES,
    NODE_KINDS,
    REQUIRED_ATTRS,
    init_db,
)


def test_node_kinds_complete():
    assert set(NODE_KINDS) == {
        "Concept", "Source", "Evidence", "Advisory", "Subsystem",
        "KernelInvariant", "FailureMode", "InteractionProtocol",
        "PerformanceProfile", "CompatibilityAssessment",
        "OptimizationGoal", "UseCaseScenario", "ComparativeAnalysis",
        "Kernel", "Problem", "Observation", "Discussion", "Benchmark",
        "Rejection", "Vulnerability", "Fix", "Proposal", "Trend",
        "Opportunity", "HumanReview", "Reviewer",
        # D-1 Option A: venue is a first-class node, not an attrs string.
        "Venue",
        # D-F: a paper summary is its own node, not Source attrs, because the
        # state vocabulary is ordered and the completeness verdict reads it.
        "PaperSummary",
        # D-A: a persisted, purely informational per-paper verdict.
        "PaperCompleteness",
    }
    # D-9: ResearchBrief retired, its fields absorbed by PaperSummary.
    assert len(NODE_KINDS) == 29


def test_edge_kinds_complete():
    expected = {
        "belongs-to", "extracted-from", "sourced-from", "alternative-to",
        "refines", "contradicts", "prerequisite", "supersedes",
        "assessed-by", "governed-by", "triggered-by", "constrains-composition",
        "profiled-by", "assesses-compatibility",
        "contributes-to", "suited-for", "compares", "implemented-in",
        "identifies-problem", "observes", "discusses", "benchmarks",
        "rejected-for", "grounded-in", "exploits", "affects-subsystem",
        "fixes", "patches", "addresses", "contradicted-by",
        "resulted-in", "motivated-by", "trend-about",
        "opportunity-for", "supported-by", "reviewed-by",
        # INV-KK-VENUE-SOURCE-EDGE: links a Source to its Venue.
        "published-at",
        # IFC-KK-PAPER-SUMMARY: links a PaperSummary to its paper. It absorbed
        # summarizes-for under D-9, which pointed the retired brief kind at a
        # Concept and whose only valid source kind no longer exists.
        "summarizes-paper",
        # IFC-KK-PAPER-COMPLETENESS: links a verdict to its paper.
        "completeness-of",
    }
    assert set(EDGE_KINDS) == expected
    assert len(EDGE_KINDS) == 39


def test_edge_valid_pairs_covers_all_edge_kinds():
    assert set(EDGE_VALID_PAIRS.keys()) == set(EDGE_KINDS)


def test_required_attrs_covers_all_node_kinds():
    assert set(REQUIRED_ATTRS.keys()) == set(NODE_KINDS)


def test_init_db_creates_tables(conn: sqlite3.Connection):
    tables = {
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert "nodes" in tables
    assert "edges" in tables


def test_init_db_enforces_foreign_keys(conn: sqlite3.Connection):
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk == 1


def test_init_db_uses_wal(conn: sqlite3.Connection):
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"


# INV-KK-SCHEMA-KIND-DECLARATION-HONOURED
#
# These two tests used to assert that a raw INSERT of an unknown kind raised
# sqlite3.IntegrityError, i.e. that nodes.kind and edges.kind carried a SQLite CHECK.
# The CHECK has been removed deliberately. It only ever existed on freshly created
# databases: every statement in SCHEMA_SQL is CREATE TABLE IF NOT EXISTS, so it could
# never be applied to data/master.db, which lost it in an earlier rebuild. Test
# fixtures and production therefore disagreed about which kinds were legal.
#
# The guarantee is unchanged and is still tested below — an unknown kind cannot enter
# the graph. What changed is the enforcement point: engine.add_node and engine.add_edge
# now own it, so one rule applies identically to every database. The accepted trade-off
# is that a raw SQL INSERT bypassing the engine is no longer blocked by the database.


def test_add_node_rejects_unknown_kind(conn: sqlite3.Connection):
    import pytest

    from graph.engine import add_node

    with pytest.raises(ValueError, match="Unknown node kind"):
        add_node(conn, "bad", "Bogus", {})


def test_add_edge_rejects_unknown_kind(conn: sqlite3.Connection):
    import pytest

    from graph.engine import add_edge, add_node

    add_node(conn, "n1", "Concept", _concept_attrs())
    add_node(conn, "n2", "Concept", _concept_attrs())
    with pytest.raises(ValueError, match="Unknown edge kind"):
        add_edge(conn, "bogus", "n1", "n2")


def test_kind_columns_carry_no_check_constraint(conn: sqlite3.Connection):
    """A fresh database must not constrain kind in SQL, or it would diverge from live."""
    for table in ("nodes", "edges"):
        ddl = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()[0]
        assert "CHECK" not in ddl.upper(), f"{table} still declares a CHECK: {ddl}"


def test_fresh_and_live_databases_agree_on_kind_enforcement(tmp_path):
    """The whole point of INV-KK-SCHEMA-KIND-DECLARATION-HONOURED.

    A freshly initialised database and data/master.db must accept and reject exactly
    the same kind values. Before this invariant, fresh DBs carried a CHECK that
    data/master.db had lost, so `Bogus` was rejected in tests and accepted in
    production. Skips cleanly if the live DB is not present (e.g. CI).
    """
    import pathlib

    fresh = init_db(tmp_path / "fresh.db")
    fresh_ddl = fresh.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='nodes'"
    ).fetchone()[0]

    live_path = pathlib.Path("data/master.db")
    if not live_path.exists():
        import pytest

        pytest.skip("data/master.db not present")

    live = sqlite3.connect(f"file:{live_path}?mode=ro", uri=True)
    live_ddl = live.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='nodes'"
    ).fetchone()[0]
    live.close()

    assert ("CHECK" in fresh_ddl.upper()) == ("CHECK" in live_ddl.upper())


def test_schema_sql_is_reentrant(tmp_path):
    """init_db must be safe to re-run — the web app executes SCHEMA_SQL every startup."""
    from graph.engine import add_node
    from graph.schema import SCHEMA_SQL

    path = tmp_path / "reentrant.db"
    conn = init_db(path)
    add_node(conn, "concept-1", "Concept", _concept_attrs())
    conn.commit()

    for _ in range(3):
        conn.executescript(SCHEMA_SQL)

    assert conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 1


def test_every_declared_kind_is_honoured_by_every_consumer():
    """INV-KK-SCHEMA-KIND-DECLARATION-HONOURED, all three surfaces in one assertion.

    schema.py declares the legal kinds. Three separate places consume that
    declaration, and each had drifted from it independently. Checking them together
    is what stops a fourth consumer drifting unnoticed: a new consumer that forgets
    a kind fails here, not in whichever feature happens to exercise it.
    """
    import pathlib
    import re

    from graph.engine import add_node
    from graph.rules import RULES_BY_KIND

    # Surface 1 — the Python kind guard is the sole enforcement, so it must read
    # from the declaration itself rather than a copy.
    assert "NODE_KINDS" in add_node.__code__.co_names

    # Surface 2 — validation rules.
    assert set(RULES_BY_KIND) == set(NODE_KINDS), (
        f"RULES_BY_KIND drifted: missing {sorted(set(NODE_KINDS) - set(RULES_BY_KIND))}, "
        f"extra {sorted(set(RULES_BY_KIND) - set(NODE_KINDS))}"
    )

    # Surface 3 — the /viz edge palette.
    html = pathlib.Path("src/web/templates/graph_viz.html").read_text(encoding="utf-8")
    block = html.split("const edgeColor = {")[1].split("};")[0]
    coloured = set(re.findall(r"'([a-z-]+)':", block))
    assert set(EDGE_KINDS) <= coloured, (
        f"edgeColor drifted: missing {sorted(set(EDGE_KINDS) - coloured)}"
    )


def _concept_attrs() -> dict:
    return {
        "name": "X",
        "description": "d",
        "artifact_class": "B",
        "key_properties": [],
        "tradeoffs": [],
        "design_rationale": "r",
    }


def test_edge_unique_constraint(conn: sqlite3.Connection):
    import pytest
    conn.execute("INSERT INTO nodes (id, kind, attrs) VALUES ('n1', 'Concept', '{}')")
    conn.execute("INSERT INTO nodes (id, kind, attrs) VALUES ('n2', 'Concept', '{}')")
    conn.execute("INSERT INTO edges (kind, source_id, target_id, attrs) VALUES ('alternative-to', 'n1', 'n2', '{}')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO edges (kind, source_id, target_id, attrs) VALUES ('alternative-to', 'n1', 'n2', '{}')")


def test_date_attrs_is_frozenset():
    assert isinstance(DATE_ATTRS, frozenset)
    assert "source_date" in DATE_ATTRS


def test_id_prefixes_covers_all_node_kinds():
    assert set(ID_PREFIXES.keys()) == set(NODE_KINDS)


# ---------------------------------------------------------------------------
# INV-KK-NO-OUTWARD-LLM-PATH — the Class A boundary (D-14).
#
# know_kernel is Class A: no code and no Class B abstraction leaves the system
# through an LLM-facing path. The MCP server and the Class B snapshot exporter
# that used to provide that path are retired.
#
# This is the invariant's check. Without it the node would carry a checked-at
# edge to tier-implemented that nothing honours, which is the failure mode
# CLAUDE.md rule #2 exists to prevent.
#
# The directory assertion is not redundant with the import assertion: `git rm`
# leaves an untracked __pycache__ behind, and a leftover directory makes the
# package importable again as an implicit namespace package. That happened
# during this very change and the import check alone passed while it did.
# ---------------------------------------------------------------------------


def test_no_outward_llm_path_packages_are_absent():
    """Neither retired package exists as a directory under src/."""
    src = pathlib.Path(__file__).resolve().parents[1] / "src"
    for name in ("mcp_server", "export"):
        assert not (src / name).exists(), f"src/{name}/ is back"


def test_no_outward_llm_path_packages_are_unimportable():
    for name in ("mcp_server", "export"):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(name)


def test_no_module_imports_the_mcp_sdk():
    """No source file imports the mcp SDK or the retired exporter."""
    src = pathlib.Path(__file__).resolve().parents[1] / "src"
    offenders = []
    for path in src.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import mcp", "from mcp")) or "export.exporter" in stripped:
                offenders.append(f"{path}: {stripped}")
    assert offenders == [], offenders
