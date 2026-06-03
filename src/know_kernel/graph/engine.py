"""Graph engine — node/edge CRUD and traversal queries."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def add_node(
    conn: sqlite3.Connection, node_id: str, kind: str, attrs: dict[str, Any] | None = None
) -> None:
    conn.execute(
        "INSERT INTO nodes (id, kind, attrs) VALUES (?, ?, ?)",
        (node_id, kind, json.dumps(attrs or {})),
    )


def get_node(conn: sqlite3.Connection, node_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, kind, attrs FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()
    if row is None:
        return None
    return {"id": row[0], "kind": row[1], "attrs": json.loads(row[2])}


def add_edge(
    conn: sqlite3.Connection,
    kind: str,
    source_id: str,
    target_id: str,
    attrs: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        "INSERT INTO edges (kind, source_id, target_id, attrs) VALUES (?, ?, ?, ?)",
        (kind, source_id, target_id, json.dumps(attrs or {})),
    )


def neighbors(
    conn: sqlite3.Connection, node_id: str, direction: str = "out"
) -> list[dict[str, Any]]:
    if direction == "out":
        sql = "SELECT e.kind, e.target_id, n.kind, n.attrs FROM edges e JOIN nodes n ON e.target_id = n.id WHERE e.source_id = ?"
    else:
        sql = "SELECT e.kind, e.source_id, n.kind, n.attrs FROM edges e JOIN nodes n ON e.source_id = n.id WHERE e.target_id = ?"
    rows = conn.execute(sql, (node_id,)).fetchall()
    return [
        {"edge_kind": r[0], "node_id": r[1], "node_kind": r[2], "attrs": json.loads(r[3])}
        for r in rows
    ]
