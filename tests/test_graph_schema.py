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
        "belongs-to", "extracted-from", "sourced-from", "defined-by",
        # IFC-KK-PAPER-KERNEL: which kernel a PAPER is about.
        "about-kernel",
        "alternative-to",
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
    # 41 since 2026-09-22. Two landed that day: defined-by, the seminal marker
    # IFC-KK-CONCEPT-SEMINAL-MARKER had specified since D-12 and which add_edge
    # rejected as an unknown kind until then; and about-kernel, which is the
    # first edge in the schema with a Kernel TARGET other than implemented-in.
    assert len(EDGE_KINDS) == 41


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
    """INV-KK-SCHEMA-KIND-DECLARATION-HONOURED, both surviving surfaces in one assertion.

    schema.py declares the legal kinds. Separate places consume that declaration,
    and each had drifted from it independently. Checking them together is what stops
    a new consumer drifting unnoticed: one that forgets a kind fails here, not in
    whichever feature happens to exercise it.

    A third surface — the /viz edgeColor palette in graph_viz.html — was asserted
    here until 2026-09-22. The page was retired (ANN-KK-WEB-VIZ-RETIRED) and the
    template deleted with it, so the consumer no longer exists and EDGE_KINDS now
    has no rendering consumer at all. This is not a weakened guard: nothing failing
    was suppressed. If a later page draws coloured edges, its palette re-enters
    here as surface 3.
    """
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

    # Surface 3 was the /viz edge palette. It went with the page on 2026-09-22;
    # no consumer of EDGE_KINDS renders, so there is nothing left to compare.
    assert not pathlib.Path("src/web/templates/graph_viz.html").exists(), (
        "graph_viz.html is back — restore the edgeColor assertion as surface 3"
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


# ---------------------------------------------------------------------------
# Referential integrity of the shipped graph.
#
# data/master.db carried 5 extracted-from edges whose target Evidence node did
# not exist: three to ev-conf-aabd4cc6 and two to ev-conf-8a97279c. Nothing in
# the engine forbids that — add_edge validates the edge kind and the endpoint
# kinds, but a later delete_node that misses a dependent leaves the edge behind
# pointing at nothing. The web layer joins through extracted-from constantly, so
# a dangling edge is a row that silently drops out of every query rather than an
# error anyone sees. These assert the condition directly instead of trusting the
# deletion that removed them.
# ---------------------------------------------------------------------------


def _master_db() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[1] / "data" / "master.db"


def test_master_db_has_no_edge_with_a_missing_target():
    db = _master_db()
    if not db.exists():
        pytest.skip("data/master.db not present")
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT e.kind, e.source_id, e.target_id FROM edges e "
            "WHERE NOT EXISTS (SELECT 1 FROM nodes n WHERE n.id = e.target_id)"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [], f"{len(rows)} edge(s) point at a missing target: {rows[:10]}"


def test_master_db_has_no_edge_with_a_missing_source():
    db = _master_db()
    if not db.exists():
        pytest.skip("data/master.db not present")
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT e.kind, e.source_id, e.target_id FROM edges e "
            "WHERE NOT EXISTS (SELECT 1 FROM nodes n WHERE n.id = e.source_id)"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [], f"{len(rows)} edge(s) have a missing source: {rows[:10]}"


# --- IFC-KK-PAPER-KERNEL: which kernel a paper is about ---------------------


def _kernel_fixture(conn):
    from graph.engine import add_node
    add_node(conn, "src-1", "Source", {
        "url": "https://example.com/p.pdf", "source_type": "paper",
        "license": "MIT", "title": "A paper"})
    add_node(conn, "ev-1", "Evidence", {
        "artifact_class": "licensed-evidence",
        "contamination_level": "weak-copyleft", "text": "t"})
    add_node(conn, "k-1", "Kernel", {
        "name": "Linux Mainline", "description": "Upstream.",
        "kernel_type": "general-purpose"})
    add_node(conn, "concept-1", "Concept", {
        "name": "Vmalloc", "description": "d",
        "artifact_class": "abstracted-mechanism", "key_properties": [],
        "tradeoffs": [], "design_rationale": "r"})
    conn.commit()


def test_about_kernel_is_accepted_from_a_source(conn: sqlite3.Connection):
    """The decided pair. Operator chose Source over Evidence on 2026-09-22
    because Source is what a reader filters by and is the stable layer —
    Evidence is re-derived and would orphan the association every relink."""
    from graph.engine import add_edge
    _kernel_fixture(conn)
    add_edge(conn, "about-kernel", "src-1", "k-1")
    conn.commit()
    assert conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind = 'about-kernel'").fetchone()[0] == 1


def test_about_kernel_is_refused_from_evidence(conn: sqlite3.Connection):
    """The pair NOT chosen must be rejected, or the decision is decorative."""
    import pytest
    from graph.engine import add_edge
    _kernel_fixture(conn)
    with pytest.raises(ValueError):
        add_edge(conn, "about-kernel", "ev-1", "k-1")


def test_about_kernel_is_refused_from_a_concept(conn: sqlite3.Connection):
    """A Concept reaches a Kernel by implemented-in. about-kernel is about a
    PAPER, and letting a Concept use it would make the two edges synonyms."""
    import pytest
    from graph.engine import add_edge
    _kernel_fixture(conn)
    with pytest.raises(ValueError):
        add_edge(conn, "about-kernel", "concept-1", "k-1")


def test_about_kernel_is_refused_pointing_at_a_non_kernel(conn: sqlite3.Connection):
    import pytest
    from graph.engine import add_edge
    _kernel_fixture(conn)
    with pytest.raises(ValueError):
        add_edge(conn, "about-kernel", "src-1", "concept-1")


def test_a_source_may_carry_two_kernels(conn: sqlite3.Connection):
    """Cardinality is deliberately NOT capped at one. The extractor answers with
    a single name so writes at most one, but a comparison paper genuinely
    concerns two kernels and a human must be able to say so without a schema
    change. That the extractor cannot express it is the extractor's limit."""
    from graph.engine import add_edge, add_node
    _kernel_fixture(conn)
    add_node(conn, "k-2", "Kernel", {
        "name": "PREEMPT_RT", "description": "Realtime.", "kernel_type": "real-time"})
    add_edge(conn, "about-kernel", "src-1", "k-1")
    add_edge(conn, "about-kernel", "src-1", "k-2")
    conn.commit()
    assert conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind = 'about-kernel' AND source_id = 'src-1'"
    ).fetchone()[0] == 2


def test_kernel_had_exactly_one_edge_pair_before_this(conn: sqlite3.Connection):
    """The measurement that motivated the edge, pinned so it stays true.

    Scanning EDGE_VALID_PAIRS for the string "Kernel" finds four entries and
    three of them are a near-miss: governed-by, triggered-by and belongs-to all
    involve KernelInvariant, a different node kind sharing a prefix. Only
    implemented-in and now about-kernel touch a real Kernel.
    """
    def pairs(v):
        return v if isinstance(v, list) else [v]
    touching = {
        k for k, v in EDGE_VALID_PAIRS.items()
        if any("Kernel" in (s, t) for s, t in pairs(v))
    }
    assert touching == {"implemented-in", "about-kernel"}
