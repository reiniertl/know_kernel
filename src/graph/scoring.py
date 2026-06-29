"""Scoring engine for concept heat, pain, and related metrics (Phase 6).

Computes scores from graph topology and temporal evidence. All scores
use source_date (real-world publication date), never ingestion time.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from graph.engine import (
    evidence_count_for_concept,
    list_nodes,
    transitive_impact,
    update_node_attrs,
)


_HEAT_EDGE_KINDS = ("discusses", "observes", "benchmarks", "grounded-in")


def heat_score(
    conn: sqlite3.Connection,
    concept_id: str,
    window_days: int = 30,
) -> float:
    """Count evidence nodes linked to this concept within a time window (ALG-KK-SCORE-HEAT).

    INV-KK-SCORE-HEAT-WINDOW: uses source_date, not ingestion time.
    INV-KK-SCORE-HEAT-EDGES: counts via discusses, observes, benchmarks, grounded-in.
    INV-KK-SCORE-NON-NEGATIVE: returns >= 0.0.
    """
    since = (datetime.now(tz=None) - timedelta(days=window_days)).strftime("%Y-%m-%d")
    total = 0
    for ek in _HEAT_EDGE_KINDS:
        total += evidence_count_for_concept(conn, concept_id, ek, since)
    return float(total)


def get_linked_problems(
    conn: sqlite3.Connection, concept_id: str,
) -> list[dict[str, Any]]:
    """Fetch Problem nodes linked to a concept via identifies-problem edge."""
    rows = conn.execute(
        "SELECT n.id, n.attrs FROM nodes n "
        "JOIN edges e ON e.source_id = n.id "
        "WHERE e.kind = 'identifies-problem' AND e.target_id = ? AND n.kind = 'Problem'",
        (concept_id,),
    ).fetchall()
    return [{"id": r[0], **json.loads(r[1])} for r in rows]


def get_linked_failure_modes(
    conn: sqlite3.Connection, concept_id: str,
) -> list[dict[str, Any]]:
    """Fetch FailureMode nodes linked via triggered-by→governed-by chain."""
    rows = conn.execute(
        "SELECT fm.id, fm.attrs FROM nodes fm "
        "JOIN edges e1 ON e1.source_id = fm.id AND e1.kind = 'triggered-by' "
        "JOIN edges e2 ON e2.source_id = e1.target_id AND e2.kind = 'governed-by' "
        "WHERE e2.target_id = ? AND fm.kind = 'FailureMode'",
        (concept_id,),
    ).fetchall()
    return [{"id": r[0], **json.loads(r[1])} for r in rows]


def get_linked_vulns(
    conn: sqlite3.Connection, concept_id: str,
) -> list[dict[str, Any]]:
    """Fetch Vulnerability nodes linked to a concept via exploits edge."""
    rows = conn.execute(
        "SELECT n.id, n.attrs FROM nodes n "
        "JOIN edges e ON e.source_id = n.id "
        "WHERE e.kind = 'exploits' AND e.target_id = ? AND n.kind = 'Vulnerability'",
        (concept_id,),
    ).fetchall()
    return [{"id": r[0], **json.loads(r[1])} for r in rows]


def cvss_weight(vuln: dict[str, Any]) -> float:
    """Map CVSS score to weight bracket (INV-KK-SCORE-CVSS-BRACKETS).

    >=9.0 -> 4.0 (critical), >=7.0 -> 3.0 (high),
    >=4.0 -> 2.0 (medium), <4.0 -> 1.0 (low).
    """
    try:
        cvss = float(vuln.get("cvss_score", "0"))
    except (ValueError, TypeError):
        return 1.0
    if cvss >= 9.0:
        return 4.0
    if cvss >= 7.0:
        return 3.0
    if cvss >= 4.0:
        return 2.0
    return 1.0


def pain_score(
    conn: sqlite3.Connection,
    concept_id: str,
) -> float:
    """Weighted sum of Problems, FailureModes, and Vulnerabilities (ALG-KK-SCORE-PAIN).

    INV-KK-SCORE-PAIN-WEIGHTS: Problem=2x, FailureMode=3x, Vulnerability=5x*CVSS.
    INV-KK-SCORE-NON-NEGATIVE: returns >= 0.0.
    """
    problems = get_linked_problems(conn, concept_id)
    failure_modes = get_linked_failure_modes(conn, concept_id)
    vulns = get_linked_vulns(conn, concept_id)

    score = 0.0
    score += len(problems) * 2.0
    score += len(failure_modes) * 3.0
    score += sum(cvss_weight(v) * 5.0 for v in vulns)
    return score


_LEVERAGE_SEVERITY_WEIGHTS = {
    "critical": 4.0,
    "high": 3.0,
    "medium": 2.0,
    "low": 1.0,
}


def impact_score(
    conn: sqlite3.Connection,
    concept_id: str,
) -> float:
    """Count distinct downstream nodes via transitive_impact (ALG-KK-SCORE-IMPACT).

    INV-KK-SCORE-NON-NEGATIVE: returns >= 0.0.
    """
    impact = transitive_impact(conn, concept_id)
    return float(sum(len(v) for v in impact.values()))


def leverage_score(
    conn: sqlite3.Connection,
    concept_id: str,
) -> float:
    """Sum severity weights for linked Problems (ALG-KK-SCORE-LEVERAGE).

    INV-KK-SCORE-LEVERAGE-WEIGHTS: critical=4, high=3, medium=2, low=1.
    INV-KK-SCORE-NON-NEGATIVE: returns >= 0.0.
    """
    problems = get_linked_problems(conn, concept_id)
    return sum(
        _LEVERAGE_SEVERITY_WEIGHTS.get(p.get("severity", "low"), 1.0)
        for p in problems
    )


def _solved_confidence(
    conn: sqlite3.Connection,
    concept_id: str,
) -> float:
    """Ratio of resolved problems to total problems (INV-KK-SCORE-SOLVED-RATIO)."""
    problems = get_linked_problems(conn, concept_id)
    if not problems:
        return 0.0
    resolved = sum(1 for p in problems if p.get("status") == "resolved")
    return resolved / len(problems)


def frontier_score(
    conn: sqlite3.Connection,
    concept_id: str,
    window_days: int = 90,
) -> float:
    """Composite frontier score (ALG-KK-SCORE-FRONTIER).

    INV-KK-SCORE-FRONTIER-FORMULA: heat*0.3 + pain*0.3 + leverage*0.3 - solved*10.
    INV-KK-SCORE-NON-NEGATIVE: floored at 0.0.
    """
    h = heat_score(conn, concept_id, window_days=window_days)
    p = pain_score(conn, concept_id)
    lev = leverage_score(conn, concept_id)
    solved = _solved_confidence(conn, concept_id)
    raw = h * 0.3 + p * 0.3 + lev * 0.3 - solved * 10.0
    return max(0.0, raw)


def compute_all_scores(
    conn: sqlite3.Connection,
    concept_id: str,
    window_days: int = 90,
) -> dict[str, float]:
    """Return all 5 scores for a concept."""
    return {
        "heat": heat_score(conn, concept_id, window_days=window_days),
        "pain": pain_score(conn, concept_id),
        "impact": impact_score(conn, concept_id),
        "leverage": leverage_score(conn, concept_id),
        "frontier": frontier_score(conn, concept_id, window_days=window_days),
    }


def refresh_scores(
    conn: sqlite3.Connection,
    concept_ids: list[str] | None = None,
    window_days: int = 90,
) -> int:
    """Batch recompute + cache scores as node attrs (ALG-KK-SCORE-REFRESH).

    INV-KK-SCORE-CACHE-ATTR: stores _scores dict + _scores_computed_at timestamp.
    INV-KK-SCORE-REFRESH-ALL: None concept_ids refreshes all Concept nodes.
    Returns count of concepts refreshed.
    """
    if concept_ids is None:
        concepts = list_nodes(conn, kind="Concept")
        concept_ids = [c["id"] for c in concepts]
    now = datetime.now(tz=None).strftime("%Y-%m-%dT%H:%M:%S")
    for cid in concept_ids:
        scores = compute_all_scores(conn, cid, window_days=window_days)
        update_node_attrs(conn, cid, {
            "_scores": json.dumps(scores),
            "_scores_computed_at": now,
        })
    return len(concept_ids)
