"""Inference engine — detects patterns from graph topology (ALG-KK-INFER-TREND).

Trend nodes are computed, never extracted from text. They represent
convergence of independent evidence on a concept within a time window.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from graph.engine import add_edge, add_node, get_node


_EVIDENCE_EDGE_KINDS = (
    "identifies-problem",
    "observes",
    "discusses",
    "benchmarks",
    "rejected-for",
    "grounded-in",
    "exploits",
)


def detect_trends(
    conn: sqlite3.Connection,
    window_days: int = 90,
    min_evidence: int = 3,
) -> list[dict[str, Any]]:
    """Detect evidence convergence trends on concepts.

    INV-KK-TREND-INFERRED: Trends are computed from graph topology.
    INV-KK-TREND-INDEPENDENT: strength = distinct source URLs.
    INV-KK-TREND-WINDOW: window_start/end from source_date.
    INV-KK-TREND-MIN-EVIDENCE: no Trend if < min_evidence sources.
    INV-KK-TREND-CLASS-B: artifact_class always "B".
    """
    since = (datetime.now(tz=None) - timedelta(days=window_days)).strftime("%Y-%m-%d")

    placeholders = ",".join("?" for _ in _EVIDENCE_EDGE_KINDS)
    rows = conn.execute(
        f"SELECT e.source_id, e.target_id, e.kind, n.attrs "
        f"FROM edges e "
        f"JOIN nodes n ON e.source_id = n.id "
        f"JOIN nodes target ON e.target_id = target.id "
        f"WHERE e.kind IN ({placeholders}) "
        f"AND target.kind = 'Concept' "
        f"AND json_extract(n.attrs, '$.source_date') >= ?",
        (*_EVIDENCE_EDGE_KINDS, since),
    ).fetchall()

    concept_evidence: dict[str, list[dict]] = {}
    for ev_id, concept_id, edge_kind, ev_attrs_json in rows:
        ev_attrs = json.loads(ev_attrs_json)
        if concept_id not in concept_evidence:
            concept_evidence[concept_id] = []
        concept_evidence[concept_id].append({
            "evidence_id": ev_id,
            "source_date": ev_attrs.get("source_date", ""),
        })

    evidence_ids_all = set()
    for entries in concept_evidence.values():
        for entry in entries:
            evidence_ids_all.add(entry["evidence_id"])

    source_urls: dict[str, str] = {}
    if evidence_ids_all:
        for ev_id in evidence_ids_all:
            src_rows = conn.execute(
                "SELECT s.attrs FROM edges e1 "
                "JOIN edges e2 ON e2.source_id = e1.target_id AND e2.kind = 'sourced-from' "
                "JOIN nodes s ON e2.target_id = s.id "
                "WHERE e1.kind = 'extracted-from' AND e1.source_id = ?",
                (ev_id,),
            ).fetchall()
            if src_rows:
                src_attrs = json.loads(src_rows[0][0])
                url = src_attrs.get("url", "")
                if url:
                    source_urls[ev_id] = url

    created_trends: list[dict[str, Any]] = []
    now_str = datetime.now(tz=None).strftime("%Y-%m-%dT%H:%M:%S")

    for concept_id, entries in concept_evidence.items():
        urls: set[str] = set()
        dates: list[str] = []
        for entry in entries:
            ev_id = entry["evidence_id"]
            if ev_id in source_urls:
                urls.add(source_urls[ev_id])
            sd = entry["source_date"]
            if sd:
                dates.append(sd)

        if len(urls) < min_evidence:
            continue

        concept_node = get_node(conn, concept_id)
        concept_name = concept_node["attrs"].get("name", concept_id) if concept_node else concept_id

        window_start = min(dates) if dates else since
        window_end = max(dates) if dates else since

        trend_id = f"trend-{concept_id}-{now_str.replace(':', '').replace('-', '')}"
        trend_attrs = {
            "title": f"Convergence on {concept_name}",
            "description": f"{len(urls)} independent sources discussing {concept_name} in {window_days}-day window",
            "strength": len(urls),
            "window_start": window_start,
            "window_end": window_end,
            "artifact_class": "B",
        }
        add_node(conn, trend_id, "Trend", trend_attrs)
        add_edge(conn, "trend-about", trend_id, concept_id)

        created_trends.append({
            "trend_id": trend_id,
            "concept_id": concept_id,
            "strength": len(urls),
            "window_start": window_start,
            "window_end": window_end,
        })

    return created_trends
