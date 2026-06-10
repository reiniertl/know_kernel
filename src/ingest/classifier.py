"""Subsystem auto-classification — ALG-KK-CLASSIFY-RESOLVE-SUBSYSTEM,
ALG-KK-CLASSIFY-PARSE-LLM, IF-KK-CLASSIFICATION-RESULT."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass

from graph.engine import add_node


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
