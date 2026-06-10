"""Subsystem auto-classification — ALG-KK-CLASSIFY-RESOLVE-SUBSYSTEM,
ALG-KK-CLASSIFY-ASSIGN, ALG-KK-CLASSIFY-PARSE-LLM, IF-KK-CLASSIFICATION-RESULT."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass

from graph.engine import add_edge, add_node


@dataclass
class ClassificationResult:
    concept_subsystem_map: dict[str, str]
    subsystems_created: int
    subsystems_reused: int


def resolve_subsystem(conn: sqlite3.Connection, label: str) -> str:
    stripped = label.strip()
    if not stripped:
        raise ValueError("Subsystem label must be a non-empty string")

    lower_label = stripped.lower()
    rows = conn.execute(
        "SELECT id, attrs FROM nodes WHERE kind = 'Subsystem'"
    ).fetchall()

    for row_id, attrs_json in rows:
        attrs = json.loads(attrs_json)
        if attrs.get("name", "").lower() == lower_label:
            return row_id

    new_id = f"sub-{uuid.uuid4().hex[:12]}"
    add_node(conn, new_id, "Subsystem", {"name": stripped})
    return new_id


def assign_subsystems(
    conn: sqlite3.Connection,
    concept_ids: list[str],
    classifications: dict[str, str],
) -> ClassificationResult:
    concept_subsystem_map: dict[str, str] = {}
    seen_subsystems: dict[str, bool] = {}

    for concept_id in concept_ids:
        label = classifications[concept_id]
        existing_before = set(
            row[0]
            for row in conn.execute(
                "SELECT id FROM nodes WHERE kind = 'Subsystem'"
            ).fetchall()
        )
        subsystem_id = resolve_subsystem(conn, label)
        is_new = subsystem_id not in existing_before
        if subsystem_id not in seen_subsystems:
            seen_subsystems[subsystem_id] = is_new
        add_edge(conn, "belongs-to", concept_id, subsystem_id)
        concept_subsystem_map[concept_id] = subsystem_id

    created = sum(1 for v in seen_subsystems.values() if v)
    reused = sum(1 for v in seen_subsystems.values() if not v)

    return ClassificationResult(
        concept_subsystem_map=concept_subsystem_map,
        subsystems_created=created,
        subsystems_reused=reused,
    )


def parse_classification_labels(
    concepts_data: list[dict], concept_ids: list[str]
) -> dict[str, str]:
    result: dict[str, str] = {}
    for i, cid in enumerate(concept_ids):
        if i < len(concepts_data):
            raw = concepts_data[i].get("subsystem", "")
            label = raw.strip() if isinstance(raw, str) else ""
        else:
            label = ""
        result[cid] = label if label else "Unclassified"
    return result
