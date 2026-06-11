"""Graph engine â€” node/edge CRUD and traversal queries."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from graph.rules import Violation, validate_node
from graph.schema import EDGE_VALID_PAIRS, REQUIRED_ATTRS


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


def _check_supersedes_cycle(conn: sqlite3.Connection, source_id: str, target_id: str) -> bool:
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
            "SELECT target_id FROM edges WHERE kind = 'supersedes' AND source_id = ?",
            (current,),
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
    if kind == "supersedes" and _check_supersedes_cycle(conn, source_id, target_id):
        raise ValueError(
            f"Adding supersedes edge {source_id} -> {target_id} would create a cycle"
        )
    conn.execute(
        "INSERT INTO edges (kind, source_id, target_id, attrs) VALUES (?, ?, ?, ?)",
        (kind, source_id, target_id, json.dumps(attrs or {})),
    )
    if kind == "contradicts":
        existing = conn.execute(
            "SELECT 1 FROM edges WHERE kind = 'contradicts' AND source_id = ? AND target_id = ? LIMIT 1",
            (target_id, source_id),
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO edges (kind, source_id, target_id, attrs) VALUES (?, ?, ?, ?)",
                ("contradicts", target_id, source_id, json.dumps(attrs or {})),
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
    conn.execute("DELETE FROM edges WHERE id = ?", (edge_id,))
    if row[0] == "contradicts":
        conn.execute(
            "DELETE FROM edges WHERE kind = 'contradicts' AND source_id = ? AND target_id = ?",
            (row[2], row[1]),
        )


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
