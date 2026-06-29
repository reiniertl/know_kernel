"""Scoring engine for concept heat, pain, and related metrics (Phase 6).

Computes scores from graph topology and temporal evidence. All scores
use source_date (real-world publication date), never ingestion time.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from graph.engine import evidence_count_for_concept


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
