"""Inference engine — detects patterns from graph topology.

ALG-KK-INFER-TREND: Trend nodes from evidence convergence.
ALG-KK-INFER-OPPORTUNITY: Opportunity nodes from high-frontier concepts.
ALG-KK-IDEA-FEED: Top-level orchestrator combining trends + opportunities.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from graph.engine import add_edge, add_node, get_node, list_nodes
from graph.scoring import compute_all_scores, frontier_score


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


_SUPPORTED_EVIDENCE_KINDS = ("Problem", "Observation", "Discussion", "Benchmark")
_EVIDENCE_EDGE_MAP = {
    "Problem": "identifies-problem",
    "Observation": "observes",
    "Discussion": "discusses",
    "Benchmark": "benchmarks",
}


def detect_opportunities(
    conn: sqlite3.Connection,
    min_frontier: float = 8.0,
    window_days: int = 90,
) -> list[dict[str, Any]]:
    """Detect high-frontier research opportunities (ALG-KK-INFER-OPPORTUNITY).

    INV-KK-OPP-FRONTIER-GATE: only concepts with frontier >= min_frontier.
    INV-KK-OPP-SUPPORTED: every Opportunity has >= 1 supported-by edge.
    INV-KK-OPP-CONFIDENCE: confidence = evidence_count / (evidence_count + 5).
    INV-KK-OPP-CLASS-B: artifact_class always "B".
    """
    concepts = list_nodes(conn, kind="Concept")
    now_str = datetime.now(tz=None).strftime("%Y-%m-%dT%H:%M:%S")
    created: list[dict[str, Any]] = []

    for concept in concepts:
        cid = concept["id"]
        fs = frontier_score(conn, cid, window_days=window_days)
        if fs < min_frontier:
            continue

        evidence_ids: list[str] = []
        evidence_summaries: list[str] = []
        for kind in _SUPPORTED_EVIDENCE_KINDS:
            edge_kind = _EVIDENCE_EDGE_MAP[kind]
            rows = conn.execute(
                "SELECT n.id, n.attrs FROM nodes n "
                "JOIN edges e ON e.source_id = n.id "
                "WHERE e.kind = ? AND e.target_id = ? AND n.kind = ?",
                (edge_kind, cid, kind),
            ).fetchall()
            for row in rows:
                evidence_ids.append(row[0])
                attrs = json.loads(row[1])
                if kind == "Problem":
                    evidence_summaries.append(f"Problem: {attrs.get('title', '')}")
                elif kind == "Observation":
                    evidence_summaries.append(f"Observation: {attrs.get('claim', '')}")
                elif kind == "Discussion":
                    evidence_summaries.append(f"Discussion: {attrs.get('title', '')}")
                elif kind == "Benchmark":
                    evidence_summaries.append(f"Benchmark: {attrs.get('metric', '')}")

        if not evidence_ids:
            continue

        concept_name = concept["attrs"].get("name", cid)
        evidence_count = len(evidence_ids)
        confidence = evidence_count / (evidence_count + 5)

        desc_parts = [f"High-frontier opportunity for {concept_name} (frontier_score={fs:.1f})."]
        if evidence_summaries:
            desc_parts.append("Supporting evidence: " + "; ".join(evidence_summaries[:5]))

        opp_id = f"opp-{cid}-{now_str.replace(':', '').replace('-', '')}"
        opp_attrs = {
            "title": f"Investigate {concept_name}",
            "description": " ".join(desc_parts),
            "confidence": round(confidence, 4),
            "frontier_score": round(fs, 4),
            "artifact_class": "B",
        }
        add_node(conn, opp_id, "Opportunity", opp_attrs)
        add_edge(conn, "opportunity-for", opp_id, cid)

        for ev_id in evidence_ids:
            add_edge(conn, "supported-by", opp_id, ev_id)

        created.append({
            "opportunity_id": opp_id,
            "concept_id": cid,
            "frontier_score": round(fs, 4),
            "confidence": round(confidence, 4),
            "evidence_count": evidence_count,
        })

    return created


def generate_idea_feed(
    conn: sqlite3.Connection,
    min_frontier: float = 8.0,
    window_days: int = 90,
) -> list[dict[str, Any]]:
    """Top-level idea feed combining trends + opportunities (ALG-KK-IDEA-FEED).

    INV-KK-IDEA-FEED-RANKED: results sorted by frontier_score descending.
    """
    trends = detect_trends(conn, window_days=window_days)
    opportunities = detect_opportunities(conn, min_frontier=min_frontier, window_days=window_days)

    feed: list[dict[str, Any]] = []

    for opp in opportunities:
        cid = opp["concept_id"]
        scores = compute_all_scores(conn, cid, window_days=window_days)
        feed.append({
            "type": "opportunity",
            "id": opp["opportunity_id"],
            "concept_id": cid,
            "frontier_score": opp["frontier_score"],
            "confidence": opp["confidence"],
            "evidence_count": opp["evidence_count"],
            "scores": scores,
        })

    for trend in trends:
        cid = trend["concept_id"]
        scores = compute_all_scores(conn, cid, window_days=window_days)
        feed.append({
            "type": "trend",
            "id": trend["trend_id"],
            "concept_id": cid,
            "frontier_score": scores["frontier"],
            "strength": trend["strength"],
            "window_start": trend["window_start"],
            "window_end": trend["window_end"],
            "scores": scores,
        })

    feed.sort(key=lambda x: x["frontier_score"], reverse=True)
    return feed
