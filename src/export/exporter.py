"""Snapshot exporter â€” produces a Class B-only SQLite DB from the master.

This is the contamination gate for LLM consumption. It filters out all
Class A content so the MCP server is clean by construction.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from graph.engine import validate_graph
from graph.schema import init_db

ALLOWED_KINDS = ("Concept", "Subsystem", "Proposal", "KernelInvariant", "FailureMode")


class ExportValidationError(Exception):
    def __init__(self, issues: list[str]) -> None:
        self.issues = issues
        super().__init__(f"Snapshot validation failed: {'; '.join(issues)}")


def export_class_b_snapshot(master_db: Path, output_db: Path) -> dict[str, Any]:
    master_conn = sqlite3.connect(str(master_db))
    master_conn.execute("PRAGMA foreign_keys=ON")

    violations = validate_graph(master_conn)
    if violations:
        master_conn.close()
        msgs = [f"[{v.rule}] {v.node_id}: {v.message}" for v in violations]
        raise ExportValidationError(msgs)

    snap_conn = init_db(output_db)

    placeholders = ",".join("?" for _ in ALLOWED_KINDS)
    nodes = master_conn.execute(
        f"SELECT id, kind, attrs FROM nodes WHERE kind IN ({placeholders})",
        ALLOWED_KINDS,
    ).fetchall()

    for node_id, kind, attrs in nodes:
        snap_conn.execute(
            "INSERT INTO nodes (id, kind, attrs) VALUES (?, ?, ?)",
            (node_id, kind, attrs),
        )

    node_ids = {row[0] for row in nodes}
    edges = master_conn.execute(
        "SELECT kind, source_id, target_id, attrs FROM edges"
    ).fetchall()
    for edge_kind, source_id, target_id, attrs in edges:
        if source_id in node_ids and target_id in node_ids:
            snap_conn.execute(
                "INSERT INTO edges (kind, source_id, target_id, attrs) VALUES (?, ?, ?, ?)",
                (edge_kind, source_id, target_id, attrs),
            )

    snap_conn.commit()

    report = validate_snapshot(snap_conn, master_conn)
    snap_conn.close()
    master_conn.close()

    if report["issues"]:
        raise ExportValidationError(report["issues"])

    return report


def _get_schema_tables(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type IN ('table', 'index') AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return {name: sql for name, sql in rows}


def validate_snapshot(
    conn: sqlite3.Connection, master_conn: sqlite3.Connection | None = None
) -> dict[str, Any]:
    issues: list[str] = []

    forbidden = conn.execute(
        "SELECT kind, COUNT(*) FROM nodes WHERE kind NOT IN ('Concept', 'Subsystem', 'Proposal', 'KernelInvariant', 'FailureMode') GROUP BY kind"
    ).fetchall()
    for kind, count in forbidden:
        issues.append(f"Snapshot contains {count} forbidden {kind} node(s)")

    dangling = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE source_id NOT IN (SELECT id FROM nodes) OR target_id NOT IN (SELECT id FROM nodes)"
    ).fetchone()[0]
    if dangling > 0:
        issues.append(f"Snapshot has {dangling} dangling edge(s)")

    if master_conn is not None:
        master_schema = _get_schema_tables(master_conn)
        snap_schema = _get_schema_tables(conn)
        if master_schema != snap_schema:
            diff_keys = set(master_schema.keys()) ^ set(snap_schema.keys())
            issues.append(f"Schema mismatch: differing objects: {sorted(diff_keys)}")

    node_count = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    edge_count = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]

    return {
        "node_count": node_count,
        "edge_count": edge_count,
        "issues": issues,
        "class_a_count": sum(c for _, c in forbidden),
    }
