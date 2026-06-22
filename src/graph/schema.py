"""SQLite schema definition and migrations for the concept store."""

from __future__ import annotations

import sqlite3
from pathlib import Path

NODE_KINDS = ("Concept", "Source", "Evidence", "Advisory", "Subsystem", "KernelInvariant", "FailureMode", "InteractionProtocol", "PerformanceProfile", "CompatibilityAssessment", "OptimizationGoal", "UseCaseScenario", "ComparativeAnalysis", "Kernel")

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
    "governed-by",
    "triggered-by",
    "constrains-composition",
    "profiled-by",
    "assesses-compatibility",
    "contributes-to",
    "suited-for",
    "compares",
    "implemented-in",
)

EDGE_VALID_PAIRS: dict[str, tuple[str, str] | list[tuple[str, str]]] = {
    "belongs-to": [("Concept", "Subsystem"), ("KernelInvariant", "Subsystem")],
    "extracted-from": [("Concept", "Evidence"), ("KernelInvariant", "Evidence"), ("FailureMode", "Evidence"), ("InteractionProtocol", "Evidence"), ("PerformanceProfile", "Evidence"), ("CompatibilityAssessment", "Evidence"), ("ComparativeAnalysis", "Evidence")],
    "sourced-from": ("Evidence", "Source"),
    "alternative-to": ("Concept", "Concept"),
    "refines": ("Concept", "Concept"),
    "contradicts": ("Concept", "Concept"),
    "prerequisite": ("Concept", "Concept"),
    "supersedes": ("Concept", "Concept"),
    "assessed-by": ("Source", "Advisory"),
    "governed-by": ("KernelInvariant", "Concept"),
    "triggered-by": ("FailureMode", "KernelInvariant"),
    "constrains-composition": ("InteractionProtocol", "Concept"),
    "profiled-by": ("PerformanceProfile", "Concept"),
    "assesses-compatibility": ("CompatibilityAssessment", "Concept"),
    "contributes-to": ("Concept", "OptimizationGoal"),
    "suited-for": ("Concept", "UseCaseScenario"),
    "compares": ("ComparativeAnalysis", "Concept"),
    "implemented-in": ("Concept", "Kernel"),
}

REQUIRED_ATTRS: dict[str, tuple[str, ...]] = {
    "Concept": ("name", "description", "artifact_class", "key_properties", "tradeoffs", "design_rationale"),
    "Source": ("url", "source_type", "license"),
    "Evidence": ("artifact_class", "contamination_level"),
    "Advisory": ("assessment", "contamination_confirmed"),
    "Subsystem": ("name",),
    "KernelInvariant": ("predicate", "strength", "scope", "artifact_class"),
    "FailureMode": ("symptom", "blast_radius", "recoverability", "artifact_class"),
    "InteractionProtocol": ("rule", "ordering", "violation_mode", "artifact_class"),
    "PerformanceProfile": ("metric", "complexity", "best_case", "worst_case", "typical_case", "conditions", "artifact_class"),
    "CompatibilityAssessment": ("synergy", "rationale", "conditions", "artifact_class"),
    "OptimizationGoal": ("name", "description", "metric", "direction"),
    "UseCaseScenario": ("name", "description", "workload_type", "constraints"),
    "ComparativeAnalysis": ("dimension", "winner", "conditions", "quantitative_delta", "artifact_class"),
    "Kernel": ("name", "description", "kernel_type"),
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
