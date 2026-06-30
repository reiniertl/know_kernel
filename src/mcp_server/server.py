"""MCP server -- exposes Class B concepts to opencode via MCP protocol.

ALG-KK-MCP-QUERY: query the Class B-only snapshot DB (19 tools).
INV-KK-MCP-SNAPSHOT-ONLY: only the snapshot path is opened; master DB never accessed.
INV-KK-MCP-NO-WRITE: snapshot DB opened read-only (uri mode=ro).
INV-KK-MCP-TOOLS-EXPOSED: exactly 19 tools; no Evidence/Source/Advisory in results.
INV-KK-MCP-EXPLORE-DEPTH-CAP: explore_subgraph caps depth at 3.
INV-KK-MCP-SEARCH-ALL-KINDS: search_concepts uses dynamic ALLOWED_KINDS from exporter.
INV-KK-MCP-IDEA-FEED-RANKED: get_idea_feed returns ideas sorted by frontier desc.
INV-KK-MCP-SCORES-COMPLETE: get_concept_scores returns all 5 score types.
INV-KK-MCP-HOT-AREAS-SUBSYSTEM: get_hot_areas aggregates heat per subsystem.
INV-KK-MCP-PROBLEMS-SEVERITY: get_problems_for_concept returns problems sorted by severity.
INV-KK-MCP-CONVERGENCE-INDEPENDENT: get_convergence counts distinct source URLs.
INV-KK-MCP-VULN-IMPACT-PROPAGATE: get_vulnerability_impact delegates to vulnerability_propagation.
INV-KK-MCP-RECENT-VULNS-WINDOW: get_recent_vulns filters by source_date window.
INV-KK-MCP-RECENT-FIXES-WINDOW: get_recent_fixes filters by source_date window.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
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
from graph.scoring import compute_all_scores, heat_score, vulnerability_propagation

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


@mcp.tool()
def get_convergence(concept_ids: list[str]) -> dict[str, Any]:
    """Check if concepts see converging independent evidence.

    INV-KK-MCP-CONVERGENCE-INDEPENDENT: counts distinct evidence nodes
    (observations, problems, discussions, etc.) linked to the given concepts.
    Since Source/Evidence nodes are stripped from the Class B snapshot,
    convergence is measured by counting distinct evidence-layer nodes
    linked via identifies-problem, observes, discusses, benchmarks,
    rejected-for, grounded-in edges.
    """
    conn = _get_conn()
    if not concept_ids:
        return {"concept_ids": [], "evidence_per_concept": {}, "shared_evidence": [], "common_problems": [], "convergence_score": 0}

    evidence_edge_kinds = ("identifies-problem", "observes", "discusses", "benchmarks", "rejected-for", "grounded-in")
    concept_evidence: dict[str, set[str]] = {}
    concept_problems: dict[str, set[str]] = {}

    for cid in concept_ids:
        evidence: set[str] = set()
        problems: set[str] = set()
        for ek in evidence_edge_kinds:
            ev_rows = conn.execute(
                "SELECT source_id FROM edges WHERE kind = ? AND target_id = ?",
                (ek, cid),
            ).fetchall()
            for ev_row in ev_rows:
                ev_id = ev_row[0]
                evidence.add(ev_id)
                ev_node = conn.execute("SELECT kind FROM nodes WHERE id = ?", (ev_id,)).fetchone()
                if ev_node and ev_node[0] == "Problem":
                    problems.add(ev_id)
        concept_evidence[cid] = evidence
        concept_problems[cid] = problems

    all_evidence_sets = [e for e in concept_evidence.values() if e]
    shared_evidence: list[str] = []
    if len(all_evidence_sets) >= 2:
        shared = all_evidence_sets[0]
        for e in all_evidence_sets[1:]:
            shared = shared & e
        shared_evidence = sorted(shared)

    all_problem_sets = [p for p in concept_problems.values() if p]
    common_problems: list[str] = []
    if len(all_problem_sets) >= 2:
        common = all_problem_sets[0]
        for p in all_problem_sets[1:]:
            common = common & p
        common_problems = sorted(common)

    all_evidence_ids: set[str] = set()
    for e in concept_evidence.values():
        all_evidence_ids |= e
    convergence_score = len(all_evidence_ids)

    evidence_per_concept = {cid: len(concept_evidence.get(cid, set())) for cid in concept_ids}

    return {
        "concept_ids": concept_ids,
        "evidence_per_concept": evidence_per_concept,
        "shared_evidence": shared_evidence,
        "common_problems": common_problems,
        "convergence_score": convergence_score,
    }


@mcp.tool()
def get_vulnerability_impact(vuln_id: str) -> dict[str, Any]:
    """Get cross-module impact of a vulnerability.

    INV-KK-MCP-VULN-IMPACT-PROPAGATE: delegates to vulnerability_propagation()
    from ALG-KK-VULN-PROPAGATE and enriches with affected subsystem names.
    """
    conn = _get_conn()
    row = conn.execute(
        "SELECT id FROM nodes WHERE id = ? AND kind = 'Vulnerability'", (vuln_id,)
    ).fetchone()
    if row is None:
        return {"error": "not_found", "vuln_id": vuln_id}

    result = vulnerability_propagation(conn, vuln_id)

    all_concept_ids: set[str] = set(result["direct"])
    for cid, coupling in result["propagated"].items():
        all_concept_ids.add(cid)
        for lst in coupling.values():
            all_concept_ids.update(lst)

    affected_subsystems: list[dict[str, str]] = []
    seen_subs: set[str] = set()
    for cid in all_concept_ids:
        sub_rows = conn.execute(
            "SELECT e.target_id, json_extract(n.attrs, '$.name') "
            "FROM edges e JOIN nodes n ON e.target_id = n.id "
            "WHERE e.kind = 'belongs-to' AND e.source_id = ? AND n.kind = 'Subsystem'",
            (cid,),
        ).fetchall()
        for sr in sub_rows:
            if sr[0] not in seen_subs:
                seen_subs.add(sr[0])
                affected_subsystems.append({"id": sr[0], "name": sr[1] or sr[0]})

    return {
        "vuln_id": vuln_id,
        "direct": result["direct"],
        "propagated": result["propagated"],
        "affected_subsystems": affected_subsystems,
    }


@mcp.tool()
def get_recent_vulns(
    subsystem: str | None = None,
    window_days: int = 30,
    min_severity: str = "medium",
) -> list[dict[str, Any]]:
    """Get recent vulnerabilities filtered by source_date window.

    INV-KK-MCP-RECENT-VULNS-WINDOW: filters by source_date, not ingestion time.
    Sorted by CVSS score descending.
    """
    conn = _get_conn()
    since = (datetime.now(UTC) - timedelta(days=window_days)).strftime("%Y-%m-%d")
    severity_min_rank = _SEVERITY_RANK.get(min_severity, 2)

    rows = conn.execute(
        "SELECT id, kind, attrs FROM nodes WHERE kind = 'Vulnerability' "
        "AND json_extract(attrs, '$.source_date') >= ? ORDER BY id",
        (since,),
    ).fetchall()

    results: list[dict[str, Any]] = []
    for row in rows:
        node = _row_to_dict(row)
        attrs = node.get("attrs") or {}
        sev = attrs.get("severity", "low")
        if _SEVERITY_RANK.get(sev, 0) < severity_min_rank:
            continue

        if subsystem:
            exploited_rows = conn.execute(
                "SELECT target_id FROM edges WHERE kind = 'exploits' AND source_id = ?",
                (node["id"],),
            ).fetchall()
            in_subsystem = False
            for er in exploited_rows:
                sub_check = conn.execute(
                    "SELECT 1 FROM edges WHERE kind = 'belongs-to' AND source_id = ? AND target_id = ?",
                    (er[0], subsystem),
                ).fetchone()
                if sub_check:
                    in_subsystem = True
                    break
            if not in_subsystem:
                continue

        propagation = vulnerability_propagation(conn, node["id"])
        prop_count = sum(
            len(v.get("dependents", [])) + len(v.get("composed_with", [])) + len(v.get("shared_invariant", []))
            for v in propagation.get("propagated", {}).values()
        )
        results.append({
            "id": node["id"],
            "cve_id": attrs.get("cve_id", ""),
            "title": attrs.get("title", node["id"]),
            "severity": sev,
            "cvss_score": attrs.get("cvss_score", ""),
            "source_date": attrs.get("source_date", ""),
            "status": attrs.get("status", ""),
            "direct_concepts": len(propagation.get("direct", [])),
            "propagated_concepts": prop_count,
        })

    results.sort(
        key=lambda v: float(v.get("cvss_score", 0) or 0),
        reverse=True,
    )
    return results


@mcp.tool()
def get_recent_fixes(
    subsystem: str | None = None,
    window_days: int = 30,
    fix_type: str | None = None,
) -> list[dict[str, Any]]:
    """Get recent fixes filtered by source_date window.

    INV-KK-MCP-RECENT-FIXES-WINDOW: filters by source_date, not ingestion time.
    Sorted by source_date descending (most recent first).
    """
    conn = _get_conn()
    since = (datetime.now(UTC) - timedelta(days=window_days)).strftime("%Y-%m-%d")

    rows = conn.execute(
        "SELECT id, kind, attrs FROM nodes WHERE kind = 'Fix' "
        "AND json_extract(attrs, '$.source_date') >= ? ORDER BY id",
        (since,),
    ).fetchall()

    results: list[dict[str, Any]] = []
    for row in rows:
        node = _row_to_dict(row)
        attrs = node.get("attrs") or {}

        if fix_type and attrs.get("fix_type", "") != fix_type:
            continue

        if subsystem:
            patch_rows = conn.execute(
                "SELECT target_id FROM edges WHERE kind = 'patches' AND source_id = ?",
                (node["id"],),
            ).fetchall()
            in_subsystem = False
            for pr in patch_rows:
                sub_check = conn.execute(
                    "SELECT 1 FROM edges WHERE kind = 'belongs-to' AND source_id = ? AND target_id = ?",
                    (pr[0], subsystem),
                ).fetchone()
                if sub_check:
                    in_subsystem = True
                    break
            if not in_subsystem:
                continue

        fix_rows = conn.execute(
            "SELECT target_id FROM edges WHERE kind = 'fixes' AND source_id = ?",
            (node["id"],),
        ).fetchall()
        resolves: list[dict[str, str]] = []
        for fr in fix_rows:
            target_node = conn.execute(
                "SELECT id, kind, json_extract(attrs, '$.title') as title, "
                "json_extract(attrs, '$.cve_id') as cve_id FROM nodes WHERE id = ?",
                (fr[0],),
            ).fetchone()
            if target_node:
                entry: dict[str, str] = {"id": target_node[0], "kind": target_node[1]}
                if target_node[2]:
                    entry["title"] = target_node[2]
                if target_node[3]:
                    entry["cve_id"] = target_node[3]
                resolves.append(entry)

        results.append({
            "id": node["id"],
            "title": attrs.get("title", node["id"]),
            "commit_hash": attrs.get("commit_hash", ""),
            "fix_type": attrs.get("fix_type", ""),
            "source_date": attrs.get("source_date", ""),
            "resolves": resolves,
        })

    results.sort(key=lambda f: f.get("source_date", ""), reverse=True)
    return results


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
