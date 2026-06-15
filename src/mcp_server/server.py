"""MCP server -- exposes Class B concepts to opencode via MCP protocol.

ALG-KK-MCP-QUERY: query the Class B-only snapshot DB (9 tools).
INV-KK-MCP-SNAPSHOT-ONLY: only the snapshot path is opened; master DB never accessed.
INV-KK-MCP-NO-WRITE: snapshot DB opened read-only (uri mode=ro).
INV-KK-MCP-TOOLS-EXPOSED: exactly 9 tools; no Evidence/Source/Advisory in results.
INV-KK-MCP-EXPLORE-DEPTH-CAP: explore_subgraph caps depth at 3.
INV-KK-MCP-SEARCH-ALL-KINDS: search_concepts uses dynamic ALLOWED_KINDS from exporter.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from mcp.server.fastmcp import FastMCP

from export.exporter import ALLOWED_KINDS
from graph.engine import (
    compare_neighborhoods,
    match_scenarios,
    ranked_recommendations,
    subgraph_around,
    transitive_impact,
)

mcp = FastMCP("know_kernel")

_conn: sqlite3.Connection | None = None

_FORBIDDEN_KINDS = frozenset({"Evidence", "Source", "Advisory"})


def _get_conn() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("Snapshot DB not initialized. Call init_snapshot(path) first.")
    return _conn


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    if "attrs" in d and isinstance(d["attrs"], str):
        try:
            d["attrs"] = json.loads(d["attrs"])
        except (ValueError, TypeError):
            d["attrs"] = {}
    return d


def init_snapshot(path: str) -> None:
    """Open the snapshot DB read-only and validate it is Class B-only.

    INV-KK-MCP-SNAPSHOT-ONLY: validates no Evidence/Source/Advisory nodes exist.
    INV-KK-MCP-NO-WRITE: opens with uri=True, mode=ro.

    Raises ValueError if forbidden node kinds are found.
    Raises sqlite3.OperationalError if the path is not a valid SQLite DB.
    """
    global _conn
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    forbidden_count = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind IN ('Evidence', 'Source', 'Advisory')"
    ).fetchone()[0]
    if forbidden_count > 0:
        conn.close()
        raise ValueError(
            f"Not a Class B-only snapshot: found {forbidden_count} forbidden node(s) "
            f"(Evidence/Source/Advisory). The MCP server only accepts kk-export snapshots."
        )
    _conn = conn


@mcp.tool()
def search_concepts(query: str) -> list[dict[str, Any]]:
    """Search Class B nodes by name or description keyword.

    Uses dynamic ALLOWED_KINDS from exporter (INV-KK-MCP-SEARCH-ALL-KINDS).
    Evidence, Source, and Advisory nodes are never returned (INV-KK-MCP-TOOLS-EXPOSED).
    """
    conn = _get_conn()
    placeholders = ",".join("?" for _ in ALLOWED_KINDS)
    rows = conn.execute(
        f"""SELECT id, kind, attrs FROM nodes
           WHERE kind IN ({placeholders})
             AND (json_extract(attrs, '$.name') LIKE ?
                  OR json_extract(attrs, '$.description') LIKE ?
                  OR attrs LIKE ?)
           ORDER BY kind, id
           LIMIT 50""",
        (*ALLOWED_KINDS, f"%{query}%", f"%{query}%", f"%{query}%"),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


@mcp.tool()
def get_concept(id: str) -> dict[str, Any] | None:
    """Get a Class B node by ID with its graph edges.

    Returns None if the node does not exist or is not a Class B kind.
    Only returns edges between allowed kinds.
    """
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, kind, attrs FROM nodes WHERE id = ? AND kind IN ('Concept', 'Subsystem', 'Proposal')",
        (id,),
    ).fetchone()
    if row is None:
        return None
    node = _row_to_dict(row)
    edge_rows = conn.execute(
        "SELECT kind, source_id, target_id FROM edges WHERE source_id = ? OR target_id = ? ORDER BY kind",
        (id, id),
    ).fetchall()
    node["edges"] = [dict(e) for e in edge_rows]
    return node


@mcp.tool()
def list_subsystems() -> list[dict[str, Any]]:
    """List all Subsystem nodes in the snapshot."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, kind, attrs FROM nodes WHERE kind = 'Subsystem' ORDER BY id"
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


@mcp.tool()
def get_subsystem_concepts(subsystem_id: str) -> list[dict[str, Any]]:
    """Get all Concept/Proposal nodes belonging to a given Subsystem via belongs-to edges."""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT n.id, n.kind, n.attrs FROM nodes n
           JOIN edges e ON e.source_id = n.id AND e.kind = 'belongs-to' AND e.target_id = ?
           WHERE n.kind IN ('Concept', 'Proposal')
           ORDER BY n.id""",
        (subsystem_id,),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


_MCP_MAX_DEPTH = 3


@mcp.tool()
def get_impact_surface(concept_id: str) -> dict[str, Any]:
    """Get the full impact surface for a Concept: invariants, failure modes,
    protocols, profiles, goals, compatibilities, comparatives, scenarios."""
    conn = _get_conn()
    return transitive_impact(conn, concept_id)


@mcp.tool()
def find_concepts_for_goal(goal_name: str) -> list[dict[str, Any]]:
    """Find Concepts that contribute to an OptimizationGoal, ranked by score.

    Looks up the goal by name, then calls ranked_recommendations().
    """
    conn = _get_conn()
    goals = conn.execute(
        "SELECT id FROM nodes WHERE kind = 'OptimizationGoal' "
        "AND json_extract(attrs, '$.name') = ?",
        (goal_name,),
    ).fetchall()
    if not goals:
        return []
    return ranked_recommendations(conn, goals[0][0])


@mcp.tool()
def compare_concepts(id_a: str, id_b: str) -> dict[str, Any]:
    """Compare two Concepts: neighborhood diff + any ComparativeAnalysis nodes."""
    conn = _get_conn()
    diff = compare_neighborhoods(conn, id_a, id_b, depth=1)
    comp_rows = conn.execute(
        """SELECT n.id, n.kind, n.attrs FROM nodes n
           JOIN edges e1 ON e1.source_id = n.id AND e1.kind = 'compares' AND e1.target_id = ?
           JOIN edges e2 ON e2.source_id = n.id AND e2.kind = 'compares' AND e2.target_id = ?
           WHERE n.kind = 'ComparativeAnalysis'""",
        (id_a, id_b),
    ).fetchall()
    comparatives = [_row_to_dict(r) for r in comp_rows]
    return {"diff": diff, "comparatives": comparatives}


@mcp.tool()
def match_workload(workload_type: str) -> list[dict[str, Any]]:
    """Find UseCaseScenarios matching a workload type with suited Concepts."""
    conn = _get_conn()
    return match_scenarios(conn, workload_type=workload_type)


@mcp.tool()
def explore_subgraph(node_id: str, depth: int = 2) -> dict[str, Any]:
    """Explore the neighborhood of a node via multi-hop BFS.

    INV-KK-MCP-EXPLORE-DEPTH-CAP: depth is capped at 3.
    """
    conn = _get_conn()
    capped_depth = min(depth, _MCP_MAX_DEPTH)
    return subgraph_around(conn, node_id, depth=capped_depth)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="kk-mcp",
        description="know_kernel MCP server -- serves Class B concepts to LLM tools.",
    )
    parser.add_argument(
        "--snapshot", required=True,
        help="Path to Class B-only snapshot DB (produced by kk-export).",
    )
    args = parser.parse_args()
    init_snapshot(args.snapshot)
    mcp.run()


if __name__ == "__main__":
    main()
