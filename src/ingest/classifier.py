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
        # THE SAME CHECK THE KernelInvariant BRANCH TWENTY LINES BELOW ALREADY
        # MAKES, and the asymmetry was the defect. edges carries
        # UNIQUE (kind, source_id, target_id), so re-classifying a Concept that
        # already belongs to this Subsystem raises IntegrityError — which is
        # every successful re-link on a mature vocabulary. It never fired in the
        # 2026-09-21 batches because those MINTED their concepts, so every
        # belongs-to edge was new; INV-KK-EXTRACT-CONCEPT-MATCHED stopped the
        # minting, and this surfaced on the first run that actually reused.
        # Measured 2026-09-28: the only two papers to fail a 1,302-paper
        # re-derivation were the two that matched — "Agile TLB Prefetching"
        # against Translation Lookaside Buffer and "Should BBR be the default
        # TCP Congestion Control Protocol?" against TCP Congestion Control.
        # Papers that MATCH were the papers that broke.
        #
        # THAT CHECK WAS NECESSARY AND NOT SUFFICIENT, FOUND 2026-09-30. It asks
        # whether THIS EXACT pair exists and never whether the Concept already
        # belongs to a DIFFERENT Subsystem, so repeated classification runs
        # ACCUMULATED homes instead of replacing them. Nine live Concepts had
        # two or three each: Page Cache sat in File Systems, Security AND
        # Virtual Memory; Transparent Huge Pages in Memory Management,
        # Networking and Virtual Memory.
        #
        # CLEAR-THEN-ADD, the way assign_subsystem has always done it, per
        # INV-KK-CONCEPT-SUBSYSTEM-SINGLE. Clearing first also subsumes the
        # UNIQUE-constraint guard above: a re-classification into the SAME
        # subsystem now deletes and re-adds rather than skipping, which is
        # idempotent and one query shorter to reason about.
        #
        # THIS IS THE ONLY WRITER THAT NEEDED IT. doc_harvest._create and
        # promote_candidate mint a fresh Concept and write its FIRST edge, so
        # they have nothing to duplicate — measured on 2026-09-30, when a
        # 99-document harvest added 163 Concepts and 121 belongs-to edges and
        # produced ZERO new violations.
        conn.execute(
            "DELETE FROM edges WHERE kind='belongs-to' AND source_id=?",
            (concept_id,),
        )
        add_edge(conn, "belongs-to", concept_id, subsystem_id)
        concept_subsystem_map[concept_id] = subsystem_id

    for concept_id, subsystem_id in concept_subsystem_map.items():
        kinv_rows = conn.execute(
            "SELECT source_id FROM edges WHERE kind='governed-by' AND target_id=?",
            (concept_id,),
        ).fetchall()
        for (kinv_id,) in kinv_rows:
            existing = conn.execute(
                "SELECT 1 FROM edges WHERE kind='belongs-to' AND source_id=? AND target_id=?",
                (kinv_id, subsystem_id),
            ).fetchone()
            if not existing:
                add_edge(conn, "belongs-to", kinv_id, subsystem_id)

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
