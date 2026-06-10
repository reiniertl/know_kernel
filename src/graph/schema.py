"""SQLite schema definition and migrations for the concept store."""

from __future__ import annotations

import sqlite3
from pathlib import Path

NODE_KINDS = ("Concept", "Source", "Evidence", "Advisory", "Subsystem", "Proposal")

EDGE_KINDS = (
    "belongs-to",
    "extracted-from",
    "sourced-from",
    "alternative-to",
    "refines",
    "contradicts",
    "prerequisite",
    "supersedes",
    "assessed-by",
    "grounded-in",
)

EDGE_VALID_PAIRS: dict[str, tuple[str, str]] = {
    "belongs-to": ("Concept", "Subsystem"),
    "extracted-from": ("Concept", "Evidence"),
    "sourced-from": ("Evidence", "Source"),
    "alternative-to": ("Concept", "Concept"),
    "refines": ("Concept", "Concept"),
    "contradicts": ("Concept", "Concept"),
    "prerequisite": ("Concept", "Concept"),
    "supersedes": ("Concept", "Concept"),
    "assessed-by": ("Source", "Advisory"),
    "grounded-in": ("Proposal", "Concept"),
}

REQUIRED_ATTRS: dict[str, tuple[str, ...]] = {
    "Concept": ("name", "description", "artifact_class", "key_properties", "tradeoffs", "design_rationale"),
    "Source": ("url", "source_type", "license"),
    "Evidence": ("artifact_class", "contamination_level"),
    "Advisory": ("assessment",),
    "Subsystem": ("name",),
    "Proposal": ("name", "description"),
}

SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ({node_placeholders})),
    attrs TEXT NOT NULL DEFAULT '{{}}'
);

CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK (kind IN ({edge_placeholders})),
    source_id TEXT NOT NULL REFERENCES nodes(id),
    target_id TEXT NOT NULL REFERENCES nodes(id),
    attrs TEXT NOT NULL DEFAULT '{{}}',
    UNIQUE (kind, source_id, target_id)
);

CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_kind ON edges(kind);
CREATE INDEX IF NOT EXISTS idx_nodes_kind ON nodes(kind);
""".format(
    node_placeholders=", ".join(f"'{k}'" for k in NODE_KINDS),
    edge_placeholders=", ".join(f"'{k}'" for k in EDGE_KINDS),
)


def init_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA_SQL)
    return conn
