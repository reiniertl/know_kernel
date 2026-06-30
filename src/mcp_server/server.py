"""MCP server -- exposes Class B concepts to opencode via MCP protocol.

ALG-KK-MCP-QUERY: query the Class B-only snapshot DB (15 tools).
INV-KK-MCP-SNAPSHOT-ONLY: only the snapshot path is opened; master DB never accessed.
INV-KK-MCP-NO-WRITE: snapshot DB opened read-only (uri mode=ro).
INV-KK-MCP-TOOLS-EXPOSED: exactly 15 tools; no Evidence/Source/Advisory in results.
INV-KK-MCP-EXPLORE-DEPTH-CAP: explore_subgraph caps depth at 3.
INV-KK-MCP-SEARCH-ALL-KINDS: search_concepts uses dynamic ALLOWED_KINDS from exporter.
INV-KK-MCP-IDEA-FEED-RANKED: get_idea_feed returns ideas sorted by frontier desc.
INV-KK-MCP-SCORES-COMPLETE: get_concept_scores returns all 5 score types.
INV-KK-MCP-HOT-AREAS-SUBSYSTEM: get_hot_areas aggregates heat per subsystem.
INV-KK-MCP-PROBLEMS-SEVERITY: get_problems_for_concept returns problems sorted by severity.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from mcp.server.fastmcp import FastMCP

from export.exporter import ALLOWED_KINDS
from graph.engine import (
    compare_neighborhoods,
    get_node,
    match_scenarios,
    path_exists,
    query_edges_by_attrs,
    ranked_recommendations,
    subgraph_around,
    transitive_impact,
)
from graph.scoring import compute_all_scores, heat_score

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
    placeholders = ",".join("?" for _ in ALLOWED_KINDS)
    row = conn.execute(
        f"SELECT id, kind, attrs FROM nodes WHERE id = ? AND kind IN ({placeholders})",
        (id, *ALLOWED_KINDS),
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
    """Get all Concept nodes belonging to a given Subsystem via belongs-to edges."""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT n.id, n.kind, n.attrs FROM nodes n
           JOIN edges e ON e.source_id = n.id AND e.kind = 'belongs-to' AND e.target_id = ?
           WHERE n.kind = 'Concept'
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


@mcp.tool()
def check_path(source_id: str, target_id: str, edge_kinds: list[str] | None = None) -> dict[str, Any]:
    """Check if a path exists between two nodes in the graph.

    ALG-KK-MCP-PATH-EXISTS: delegates to engine.path_exists().
    Returns {reachable: bool}. If edge_kinds is provided, only follows those edge kinds.
    """
    conn = _get_conn()
    row_s = conn.execute("SELECT id FROM nodes WHERE id = ?", (source_id,)).fetchone()
    row_t = conn.execute("SELECT id FROM nodes WHERE id = ?", (target_id,)).fetchone()
    if row_s is None or row_t is None:
        return {"reachable": False}
    reachable = path_exists(conn, source_id, target_id, edge_kinds)
    return {"reachable": reachable}


@mcp.tool()
def query_edges(kind: str, filters: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Query edges by kind and optional attribute filters.

    ALG-KK-MCP-QUERY-EDGES: delegates to engine.query_edges_by_attrs().
    Filters results to edges where both endpoints are ALLOWED_KINDS.
    Returns at most 50 results.
    """
    conn = _get_conn()
    results = query_edges_by_attrs(conn, kind, **(filters or {}))
    allowed = set(ALLOWED_KINDS)
    node_kinds: dict[str, str] = {}
    for edge in results:
        for nid in (edge["source_id"], edge["target_id"]):
            if nid not in node_kinds:
                row = conn.execute("SELECT kind FROM nodes WHERE id = ?", (nid,)).fetchone()
                node_kinds[nid] = row["kind"] if row else ""
    filtered = [
        e for e in results
        if node_kinds.get(e["source_id"], "") in allowed
        and node_kinds.get(e["target_id"], "") in allowed
    ]
    return filtered[:50]


_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}


@mcp.tool()
def get_idea_feed(
    subsystem: str | None = None, top_k: int = 10, window_days: int = 90,
) -> list[dict[str, Any]]:
    """Get ranked idea feed (opportunities + trends) sorted by frontier_score desc.

    INV-KK-MCP-IDEA-FEED-RANKED: sorted by frontier_score descending.
    Optional subsystem filter restricts to ideas linked to concepts in that subsystem.
    Reads existing Opportunity/Trend nodes from snapshot (INV-KK-MCP-SNAPSHOT-ONLY).
    """
    conn = _get_conn()
    ideas: list[dict[str, Any]] = []
    for row in conn.execute(
        "SELECT id, kind, attrs FROM nodes WHERE kind = 'Opportunity' ORDER BY id"
    ).fetchall():
        node = _row_to_dict(row)
        attrs = node.get("attrs") or {}
        fs = attrs.get("frontier_score", 0)
        if isinstance(fs, str):
            try:
                fs = float(fs)
            except ValueError:
                fs = 0
        concept_id = None
        concept_name = None
        opp_edge = conn.execute(
            "SELECT target_id FROM edges WHERE kind = 'opportunity-for' AND source_id = ?",
            (node["id"],),
        ).fetchone()
        if opp_edge:
            concept_id = opp_edge[0]
            cn = get_node(conn, concept_id)
            if cn:
                concept_name = (cn["attrs"] or {}).get("name", concept_id)
        ideas.append({
            "type": "opportunity",
            "id": node["id"],
            "concept_id": concept_id,
            "concept_name": concept_name,
            "title": attrs.get("title", node["id"]),
            "frontier_score": fs,
            "confidence": attrs.get("confidence"),
        })
    for row in conn.execute(
        "SELECT id, kind, attrs FROM nodes WHERE kind = 'Trend' ORDER BY id"
    ).fetchall():
        node = _row_to_dict(row)
        attrs = node.get("attrs") or {}
        concept_id = None
        concept_name = None
        trend_edge = conn.execute(
            "SELECT target_id FROM edges WHERE kind = 'trend-about' AND source_id = ?",
            (node["id"],),
        ).fetchone()
        if trend_edge:
            concept_id = trend_edge[0]
            cn = get_node(conn, concept_id)
            if cn:
                concept_name = (cn["attrs"] or {}).get("name", concept_id)
        scores = compute_all_scores(conn, concept_id, window_days=window_days) if concept_id else {}
        fs = scores.get("frontier", 0)
        ideas.append({
            "type": "trend",
            "id": node["id"],
            "concept_id": concept_id,
            "concept_name": concept_name,
            "title": attrs.get("title", node["id"]),
            "frontier_score": fs,
            "strength": attrs.get("strength"),
        })
    ideas.sort(key=lambda x: x["frontier_score"], reverse=True)
    if subsystem:
        ideas = [
            i for i in ideas
            if i.get("concept_id") and conn.execute(
                "SELECT 1 FROM edges WHERE kind = 'belongs-to' AND source_id = ? AND target_id = ?",
                (i["concept_id"], subsystem),
            ).fetchone()
        ]
    return ideas[:top_k]


@mcp.tool()
def get_concept_scores(concept_id: str) -> dict[str, Any]:
    """Get all 5 scores for a concept: heat, pain, impact, leverage, frontier.

    INV-KK-MCP-SCORES-COMPLETE: returns all 5 score types.
    Returns empty dict if concept not found.
    """
    conn = _get_conn()
    row = conn.execute(
        "SELECT id FROM nodes WHERE id = ? AND kind = 'Concept'", (concept_id,)
    ).fetchone()
    if row is None:
        return {}
    return compute_all_scores(conn, concept_id)


@mcp.tool()
def get_hot_areas(top_k: int = 10, window_days: int = 30) -> list[dict[str, Any]]:
    """Get subsystems ranked by aggregate heat score.

    INV-KK-MCP-HOT-AREAS-SUBSYSTEM: aggregates heat per subsystem via belongs-to edges.
    """
    conn = _get_conn()
    sub_rows = conn.execute(
        "SELECT id, kind, attrs FROM nodes WHERE kind = 'Subsystem' ORDER BY id"
    ).fetchall()
    results: list[dict[str, Any]] = []
    for sr in sub_rows:
        sub = _row_to_dict(sr)
        sub_id = sub["id"]
        concept_rows = conn.execute(
            "SELECT e.source_id FROM edges e "
            "JOIN nodes n ON e.source_id = n.id AND n.kind = 'Concept' "
            "WHERE e.kind = 'belongs-to' AND e.target_id = ?",
            (sub_id,),
        ).fetchall()
        concept_ids = [r[0] for r in concept_rows]
        if not concept_ids:
            continue
        total_heat = sum(heat_score(conn, cid, window_days=window_days) for cid in concept_ids)
        attrs = sub.get("attrs") or {}
        results.append({
            "subsystem_id": sub_id,
            "name": attrs.get("name", sub_id),
            "concept_count": len(concept_ids),
            "heat": total_heat,
        })
    results.sort(key=lambda x: x["heat"], reverse=True)
    return results[:top_k]


@mcp.tool()
def get_problems_for_concept(concept_id: str) -> list[dict[str, Any]]:
    """Get open problems for a concept, sorted by severity descending.

    INV-KK-MCP-PROBLEMS-SEVERITY: sorted by severity (critical > high > medium > low).
    """
    conn = _get_conn()
    rows = conn.execute(
        "SELECT n.id, n.kind, n.attrs FROM nodes n "
        "JOIN edges e ON e.source_id = n.id "
        "WHERE e.kind = 'identifies-problem' AND e.target_id = ? AND n.kind = 'Problem'",
        (concept_id,),
    ).fetchall()
    problems = [_row_to_dict(r) for r in rows]
    problems.sort(
        key=lambda p: _SEVERITY_RANK.get((p.get("attrs") or {}).get("severity", ""), 0),
        reverse=True,
    )
    return problems


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
