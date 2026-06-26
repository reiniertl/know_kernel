"""Graph engine â€” node/edge CRUD and traversal queries."""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from graph.rules import Violation, validate_node
from graph.schema import DATE_ATTRS, EDGE_VALID_PAIRS, REQUIRED_ATTRS

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2})?$")


class AdmissibilityError(Exception):
    def __init__(self, violations: list) -> None:
        self.violations = violations
        msgs = "; ".join(f"[{v.rule}] {v.message}" for v in violations)
        super().__init__(f"Admissibility violations: {msgs}")


def add_node(
    conn: sqlite3.Connection, node_id: str, kind: str, attrs: dict[str, Any] | None = None
) -> None:
    resolved = attrs or {}
    required = REQUIRED_ATTRS.get(kind, ())
    missing = [a for a in required if a not in resolved]
    if missing:
        raise ValueError(
            f"Node '{node_id}' (kind={kind}) missing required attributes: {', '.join(missing)}"
        )
    for attr_name in DATE_ATTRS:
        if attr_name in resolved:
            val = resolved[attr_name]
            if not isinstance(val, str) or not _ISO_DATE_RE.match(val):
                raise ValueError(
                    f"Node '{node_id}' attribute '{attr_name}' must be an ISO-8601 date "
                    f"(e.g., '2026-06-15' or '2026-06-15T10:30:00'), got: {val!r}"
                )
    conn.execute(
        "INSERT INTO nodes (id, kind, attrs) VALUES (?, ?, ?)",
        (node_id, kind, json.dumps(resolved)),
    )


def get_node(conn: sqlite3.Connection, node_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, kind, attrs FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()
    if row is None:
        return None
    return {"id": row[0], "kind": row[1], "attrs": json.loads(row[2])}


_ACYCLIC_EDGE_KINDS = {"supersedes", "refines", "prerequisite"}


def _check_edge_cycle(conn: sqlite3.Connection, kind: str, source_id: str, target_id: str) -> bool:
    visited = set()
    stack = [target_id]
    while stack:
        current = stack.pop()
        if current == source_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        rows = conn.execute(
            "SELECT target_id FROM edges WHERE kind = ? AND source_id = ?",
            (kind, current),
        ).fetchall()
        stack.extend(r[0] for r in rows)
    return False


def add_edge(
    conn: sqlite3.Connection,
    kind: str,
    source_id: str,
    target_id: str,
    attrs: dict[str, Any] | None = None,
) -> None:
    valid_pair = EDGE_VALID_PAIRS.get(kind)
    if valid_pair is None:
        raise ValueError(f"Unknown edge kind: {kind}")
    source_node = get_node(conn, source_id)
    target_node = get_node(conn, target_id)
    if source_node is None:
        raise ValueError(f"Source node '{source_id}' does not exist")
    if target_node is None:
        raise ValueError(f"Target node '{target_id}' does not exist")
    pairs = valid_pair if isinstance(valid_pair, list) else [valid_pair]
    actual = (source_node["kind"], target_node["kind"])
    if actual not in pairs:
        allowed = " or ".join(f"({s} -> {t})" for s, t in pairs)
        raise ValueError(
            f"Edge '{kind}' requires {allowed}, "
            f"got ({source_node['kind']} -> {target_node['kind']})"
        )
    if kind in _ACYCLIC_EDGE_KINDS and _check_edge_cycle(conn, kind, source_id, target_id):
        raise ValueError(
            f"Adding {kind} edge {source_id} -> {target_id} would create a cycle"
        )
    conn.execute(
        "INSERT INTO edges (kind, source_id, target_id, attrs) VALUES (?, ?, ?, ?)",
        (kind, source_id, target_id, json.dumps(attrs or {})),
    )
    if kind in ("contradicts", "contradicted-by"):
        existing = conn.execute(
            "SELECT 1 FROM edges WHERE kind = ? AND source_id = ? AND target_id = ? LIMIT 1",
            (kind, target_id, source_id),
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO edges (kind, source_id, target_id, attrs) VALUES (?, ?, ?, ?)",
                (kind, target_id, source_id, json.dumps(attrs or {})),
            )


def validate_graph(conn: sqlite3.Connection) -> list[Violation]:
    rows = conn.execute("SELECT id, kind FROM nodes").fetchall()
    violations: list[Violation] = []
    for node_id, kind in rows:
        violations.extend(validate_node(conn, node_id, kind))
    return violations


def update_node_attrs(
    conn: sqlite3.Connection, node_id: str, attrs: dict[str, Any]
) -> None:
    node = get_node(conn, node_id)
    if node is None:
        raise ValueError(f"Node '{node_id}' does not exist")
    merged = {**node["attrs"], **attrs}
    required = REQUIRED_ATTRS.get(node["kind"], ())
    missing = [a for a in required if a not in merged]
    if missing:
        raise ValueError(
            f"Node '{node_id}' (kind={node['kind']}) would be missing required attributes: {', '.join(missing)}"
        )
    conn.execute(
        "UPDATE nodes SET attrs = ? WHERE id = ?",
        (json.dumps(merged), node_id),
    )


def delete_node(conn: sqlite3.Connection, node_id: str) -> None:
    node = get_node(conn, node_id)
    if node is None:
        raise ValueError(f"Node '{node_id}' does not exist")
    affected = conn.execute(
        "SELECT DISTINCT e.source_id, n.kind FROM edges e JOIN nodes n ON e.source_id = n.id WHERE e.target_id = ?",
        (node_id,),
    ).fetchall()
    conn.execute("SAVEPOINT delete_node_check")
    conn.execute("DELETE FROM edges WHERE source_id = ? OR target_id = ?", (node_id, node_id))
    conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
    all_violations: list[Violation] = []
    for dep_id, dep_kind in affected:
        all_violations.extend(validate_node(conn, dep_id, dep_kind))
    if all_violations:
        conn.execute("ROLLBACK TO SAVEPOINT delete_node_check")
        conn.execute("RELEASE SAVEPOINT delete_node_check")
        raise AdmissibilityError(all_violations)
    conn.execute("RELEASE SAVEPOINT delete_node_check")


def delete_edge(conn: sqlite3.Connection, edge_id: int) -> None:
    row = conn.execute(
        "SELECT kind, source_id, target_id FROM edges WHERE id = ?", (edge_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"Edge {edge_id} does not exist")
    edge_kind, source_id, target_id = row
    source_node = get_node(conn, source_id)

    conn.execute("SAVEPOINT delete_edge_check")
    conn.execute("DELETE FROM edges WHERE id = ?", (edge_id,))
    if edge_kind in ("contradicts", "contradicted-by"):
        conn.execute(
            "DELETE FROM edges WHERE kind = ? AND source_id = ? AND target_id = ?",
            (edge_kind, target_id, source_id),
        )
    if source_node:
        violations = validate_node(conn, source_id, source_node["kind"])
        if violations:
            conn.execute("ROLLBACK TO SAVEPOINT delete_edge_check")
            conn.execute("RELEASE SAVEPOINT delete_edge_check")
            raise AdmissibilityError(violations)
    conn.execute("RELEASE SAVEPOINT delete_edge_check")


def get_edge(conn: sqlite3.Connection, edge_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, kind, source_id, target_id, attrs FROM edges WHERE id = ?", (edge_id,)
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row[0], "kind": row[1], "source_id": row[2],
        "target_id": row[3], "attrs": json.loads(row[4]),
    }


def list_nodes(
    conn: sqlite3.Connection, kind: str | None = None
) -> list[dict[str, Any]]:
    if kind is not None:
        rows = conn.execute(
            "SELECT id, kind, attrs FROM nodes WHERE kind = ?", (kind,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT id, kind, attrs FROM nodes").fetchall()
    return [{"id": r[0], "kind": r[1], "attrs": json.loads(r[2])} for r in rows]


def query_by_attrs(
    conn: sqlite3.Connection, kind: str, **filters: Any
) -> list[dict[str, Any]]:
    nodes = list_nodes(conn, kind)
    result = []
    for node in nodes:
        if all(node["attrs"].get(k) == v for k, v in filters.items()):
            result.append(node)
    return result


def neighbors(
    conn: sqlite3.Connection, node_id: str, direction: str = "out",
    edge_kind: str | None = None,
) -> list[dict[str, Any]]:
    if direction == "out":
        sql = "SELECT e.kind, e.target_id, n.kind, n.attrs FROM edges e JOIN nodes n ON e.target_id = n.id WHERE e.source_id = ?"
    else:
        sql = "SELECT e.kind, e.source_id, n.kind, n.attrs FROM edges e JOIN nodes n ON e.source_id = n.id WHERE e.target_id = ?"
    params: list[Any] = [node_id]
    if edge_kind is not None:
        sql += " AND e.kind = ?"
        params.append(edge_kind)
    rows = conn.execute(sql, params).fetchall()
    return [
        {"edge_kind": r[0], "node_id": r[1], "node_kind": r[2], "attrs": json.loads(r[3])}
        for r in rows
    ]


_MAX_SUBGRAPH_DEPTH = 5


def subgraph_around(
    conn: sqlite3.Connection,
    node_id: str,
    depth: int = 2,
    edge_kinds: list[str] | None = None,
) -> dict[str, Any]:
    depth = max(0, min(depth, _MAX_SUBGRAPH_DEPTH))
    root = get_node(conn, node_id)
    if root is None:
        return {"nodes": [], "edges": []}

    visited_nodes: dict[str, dict] = {node_id: root}
    collected_edges: list[dict] = []
    frontier = {node_id}

    for _ in range(depth):
        if not frontier:
            break
        next_frontier: set[str] = set()
        for nid in frontier:
            if edge_kinds is not None:
                placeholders = ",".join("?" for _ in edge_kinds)
                rows = conn.execute(
                    f"SELECT id, kind, source_id, target_id, attrs FROM edges "
                    f"WHERE (source_id = ? OR target_id = ?) AND kind IN ({placeholders})",
                    [nid, nid, *edge_kinds],
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, kind, source_id, target_id, attrs FROM edges "
                    "WHERE source_id = ? OR target_id = ?",
                    (nid, nid),
                ).fetchall()
            for eid, ekind, src, tgt, eattrs in rows:
                edge_dict = {"id": eid, "kind": ekind, "source_id": src, "target_id": tgt, "attrs": json.loads(eattrs)}
                if not any(e["id"] == eid for e in collected_edges):
                    collected_edges.append(edge_dict)
                neighbor_id = tgt if src == nid else src
                if neighbor_id not in visited_nodes:
                    neighbor = get_node(conn, neighbor_id)
                    if neighbor is not None:
                        visited_nodes[neighbor_id] = neighbor
                        next_frontier.add(neighbor_id)
        frontier = next_frontier

    return {"nodes": list(visited_nodes.values()), "edges": collected_edges}


def query_edges_by_attrs(
    conn: sqlite3.Connection,
    kind: str | None = None,
    **filters: Any,
) -> list[dict[str, Any]]:
    if kind is not None:
        rows = conn.execute(
            "SELECT id, kind, source_id, target_id, attrs FROM edges WHERE kind = ?",
            (kind,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, kind, source_id, target_id, attrs FROM edges"
        ).fetchall()

    results: list[dict[str, Any]] = []
    for eid, ekind, src, tgt, eattrs in rows:
        parsed = json.loads(eattrs)
        if all(parsed.get(k) == v for k, v in filters.items()):
            results.append({
                "id": eid, "kind": ekind, "source_id": src,
                "target_id": tgt, "attrs": parsed,
            })
    return results


_FITNESS_RANK = {"excellent": 0, "good": 1, "acceptable": 2, "poor": 3}
_MAGNITUDE_SCORE = {"strong": 3, "moderate": 2, "weak": 1}


def compare_neighborhoods(
    conn: sqlite3.Connection,
    id_a: str,
    id_b: str,
    depth: int = 1,
) -> dict[str, Any]:
    sub_a = subgraph_around(conn, id_a, depth=depth)
    sub_b = subgraph_around(conn, id_b, depth=depth)
    ids_a = {n["id"] for n in sub_a["nodes"]} - {id_a}
    ids_b = {n["id"] for n in sub_b["nodes"]} - {id_b}
    all_nodes = {n["id"]: n for n in sub_a["nodes"] + sub_b["nodes"]}
    shared = sorted(ids_a & ids_b)
    only_a = sorted(ids_a - ids_b - {id_b})
    only_b = sorted(ids_b - ids_a - {id_a})
    return {
        "shared": [all_nodes[nid] for nid in shared],
        "only_a": [all_nodes[nid] for nid in only_a],
        "only_b": [all_nodes[nid] for nid in only_b],
    }


def match_scenarios(
    conn: sqlite3.Connection,
    workload_type: str | None = None,
) -> list[dict[str, Any]]:
    scenarios = list_nodes(conn, "UseCaseScenario")
    if workload_type is not None:
        scenarios = [s for s in scenarios if s["attrs"].get("workload_type") == workload_type]
    results: list[dict[str, Any]] = []
    for scenario in scenarios:
        edges = conn.execute(
            "SELECT e.source_id, e.attrs, n.id, n.kind, n.attrs "
            "FROM edges e JOIN nodes n ON e.source_id = n.id "
            "WHERE e.kind = 'suited-for' AND e.target_id = ?",
            (scenario["id"],),
        ).fetchall()
        concepts = []
        for src_id, eattrs, nid, nkind, nattrs in edges:
            parsed_eattrs = json.loads(eattrs)
            concepts.append({
                "id": nid,
                "kind": nkind,
                "attrs": json.loads(nattrs),
                "fitness": parsed_eattrs.get("fitness", "poor"),
            })
        concepts.sort(key=lambda c: _FITNESS_RANK.get(c["fitness"], 99))
        results.append({"scenario": scenario, "concepts": concepts})
    return results


def transitive_impact(
    conn: sqlite3.Connection,
    concept_id: str,
) -> dict[str, Any]:
    result: dict[str, list[dict]] = {
        "invariants": [],
        "failure_modes": [],
        "protocols": [],
        "profiles": [],
        "goals": [],
        "compatibilities": [],
        "comparatives": [],
        "scenarios": [],
    }
    edge_map = {
        "governed-by": ("invariants", "in"),
        "constrains-composition": ("protocols", "in"),
        "profiled-by": ("profiles", "in"),
        "assesses-compatibility": ("compatibilities", "in"),
        "compares": ("comparatives", "in"),
        "contributes-to": ("goals", "out"),
        "suited-for": ("scenarios", "out"),
    }
    for edge_kind, (key, direction) in edge_map.items():
        if direction == "in":
            rows = conn.execute(
                "SELECT n.id, n.kind, n.attrs FROM edges e "
                "JOIN nodes n ON e.source_id = n.id "
                "WHERE e.kind = ? AND e.target_id = ?",
                (edge_kind, concept_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT n.id, n.kind, n.attrs FROM edges e "
                "JOIN nodes n ON e.target_id = n.id "
                "WHERE e.kind = ? AND e.source_id = ?",
                (edge_kind, concept_id),
            ).fetchall()
        for nid, nkind, nattrs in rows:
            result[key].append({"id": nid, "kind": nkind, "attrs": json.loads(nattrs)})
    for inv in list(result["invariants"]):
        fm_rows = conn.execute(
            "SELECT n.id, n.kind, n.attrs FROM edges e "
            "JOIN nodes n ON e.source_id = n.id "
            "WHERE e.kind = 'triggered-by' AND e.target_id = ?",
            (inv["id"],),
        ).fetchall()
        for nid, nkind, nattrs in fm_rows:
            if not any(f["id"] == nid for f in result["failure_modes"]):
                result["failure_modes"].append({"id": nid, "kind": nkind, "attrs": json.loads(nattrs)})
    return result


def ranked_recommendations(
    conn: sqlite3.Connection,
    goal_id: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    edges = conn.execute(
        "SELECT e.source_id, e.attrs, n.id, n.kind, n.attrs "
        "FROM edges e JOIN nodes n ON e.source_id = n.id "
        "WHERE e.kind = 'contributes-to' AND e.target_id = ?",
        (goal_id,),
    ).fetchall()
    candidates = []
    for src_id, eattrs, nid, nkind, nattrs in edges:
        parsed_eattrs = json.loads(eattrs)
        if parsed_eattrs.get("direction") != "improves":
            continue
        impact = transitive_impact(conn, nid)
        impact_size = sum(len(v) for v in impact.values())
        magnitude = _MAGNITUDE_SCORE.get(parsed_eattrs.get("magnitude", ""), 0)
        score = magnitude + impact_size
        candidates.append({
            "concept": {"id": nid, "kind": nkind, "attrs": json.loads(nattrs)},
            "contribution": parsed_eattrs,
            "score": score,
            "impact": impact,
        })
    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates[:limit]


def path_exists(
    conn: sqlite3.Connection, source_id: str, target_id: str,
    edge_kinds: list[str] | None = None,
) -> bool:
    visited = set()
    stack = [source_id]
    while stack:
        current = stack.pop()
        if current == target_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        if edge_kinds is not None:
            placeholders = ",".join("?" for _ in edge_kinds)
            rows = conn.execute(
                f"SELECT target_id FROM edges WHERE source_id = ? AND kind IN ({placeholders})",
                [current, *edge_kinds],
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT target_id FROM edges WHERE source_id = ?", (current,)
            ).fetchall()
        stack.extend(r[0] for r in rows)
    return False


def evidence_in_window(
    conn: sqlite3.Connection,
    kind: str,
    since: str,
    until: str | None = None,
) -> list[dict[str, Any]]:
    if until is not None:
        rows = conn.execute(
            "SELECT id, kind, attrs FROM nodes "
            "WHERE kind = ? "
            "AND json_extract(attrs, '$.source_date') >= ? "
            "AND json_extract(attrs, '$.source_date') <= ? "
            "ORDER BY json_extract(attrs, '$.source_date') ASC",
            (kind, since, until),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, kind, attrs FROM nodes "
            "WHERE kind = ? "
            "AND json_extract(attrs, '$.source_date') >= ? "
            "ORDER BY json_extract(attrs, '$.source_date') ASC",
            (kind, since),
        ).fetchall()
    return [{"id": r[0], "kind": r[1], "attrs": json.loads(r[2])} for r in rows]


def evidence_count_for_concept(
    conn: sqlite3.Connection,
    concept_id: str,
    edge_kind: str,
    since: str,
    until: str | None = None,
) -> int:
    if until is not None:
        row = conn.execute(
            "SELECT COUNT(*) FROM edges e "
            "JOIN nodes n ON e.source_id = n.id "
            "WHERE e.kind = ? AND e.target_id = ? "
            "AND json_extract(n.attrs, '$.source_date') >= ? "
            "AND json_extract(n.attrs, '$.source_date') <= ?",
            (edge_kind, concept_id, since, until),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) FROM edges e "
            "JOIN nodes n ON e.source_id = n.id "
            "WHERE e.kind = ? AND e.target_id = ? "
            "AND json_extract(n.attrs, '$.source_date') >= ?",
            (edge_kind, concept_id, since),
        ).fetchone()
    return row[0]


def concept_timeline(
    conn: sqlite3.Connection,
    concept_id: str,
) -> list[dict[str, Any]]:
    evidence_edge_kinds = (
        "identifies-problem", "observes", "discusses",
        "benchmarks", "rejected-for", "grounded-in", "exploits",
    )
    placeholders = ",".join("?" for _ in evidence_edge_kinds)
    rows = conn.execute(
        f"SELECT n.id, n.kind, n.attrs, json_extract(n.attrs, '$.source_date') as sd "
        f"FROM nodes n "
        f"JOIN edges e ON e.source_id = n.id AND e.target_id = ? "
        f"WHERE e.kind IN ({placeholders}) "
        f"ORDER BY sd ASC",
        (concept_id, *evidence_edge_kinds),
    ).fetchall()
    return [{"id": r[0], "kind": r[1], "attrs": json.loads(r[2]), "source_date": r[3]} for r in rows]
