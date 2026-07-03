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


def research_score(
    conn: sqlite3.Connection,
    concept_id: str,
    window_days: int = 90,
) -> float:
    """Composite research novelty score (ALG-KK-GRAPH-RESEARCH-SCORE).

    INV-KK-GRAPH-RESEARCH-SCORE-FORMULA: 6-component weighted sum.
    INV-KK-GRAPH-RESEARCH-SCORE-PURE: deterministic, no LLM.
    INV-KK-GRAPH-RESEARCH-SCORE-NON-NEGATIVE: >= 0.0.
    """
    since = (datetime.now(tz=None) - timedelta(days=window_days)).strftime("%Y-%m-%d")

    # (a) discussion_density (weight 0.25)
    disc_rows = conn.execute(
        "SELECT n.attrs FROM nodes n "
        "JOIN edges e ON e.source_id = n.id "
        "WHERE e.kind = 'discusses' AND e.target_id = ? "
        "AND n.kind = 'Discussion' AND json_extract(n.attrs, '$.source_date') >= ?",
        (concept_id, since),
    ).fetchall()
    discussion_density = 0.0
    for row in disc_rows:
        attrs = json.loads(row[0])
        pc = attrs.get("participant_count", 0)
        try:
            pc = int(pc)
        except (ValueError, TypeError):
            pc = 0
        discussion_density += min(pc, 50) / 10.0

    # (b) observation_recency (weight 0.20)
    obs_rows = conn.execute(
        "SELECT n.attrs FROM nodes n "
        "JOIN edges e ON e.source_id = n.id "
        "WHERE e.kind = 'observes' AND e.target_id = ? "
        "AND n.kind = 'Observation' AND json_extract(n.attrs, '$.source_date') >= ?",
        (concept_id, since),
    ).fetchall()
    observation_recency = 0.0
    for row in obs_rows:
        attrs = json.loads(row[0])
        conf = attrs.get("confidence", 0)
        try:
            conf = float(conf)
        except (ValueError, TypeError):
            conf = 0.0
        observation_recency += conf

    # (c) evidence_diversity (weight 0.20)
    diversity_rows = conn.execute(
        "SELECT COUNT(DISTINCT json_extract(src.attrs, '$.url')) "
        "FROM edges e1 "
        "JOIN edges e2 ON e2.source_id = e1.target_id AND e2.kind = 'sourced-from' "
        "JOIN nodes src ON src.id = e2.target_id AND src.kind = 'Source' "
        "WHERE e1.kind = 'extracted-from' AND e1.source_id = ? "
        "AND json_extract(src.attrs, '$.url') IS NOT NULL",
        (concept_id,),
    ).fetchone()
    evidence_diversity = float(diversity_rows[0]) if diversity_rows else 0.0

    # (d) proposal_activity (weight 0.15)
    prop_count = conn.execute(
        "SELECT COUNT(*) FROM nodes n "
        "JOIN edges e ON e.source_id = n.id "
        "WHERE e.kind = 'grounded-in' AND e.target_id = ? "
        "AND n.kind = 'Proposal' AND COALESCE(json_extract(n.attrs, '$.status'), '') != 'rejected'",
        (concept_id,),
    ).fetchone()[0]
    proposal_activity = float(prop_count) * 2.0

    # (e) benchmark_coverage (weight 0.10)
    bench_count = conn.execute(
        "SELECT COUNT(*) FROM nodes n "
        "JOIN edges e ON e.source_id = n.id "
        "WHERE e.kind = 'benchmarks' AND e.target_id = ? "
        "AND n.kind = 'Benchmark' AND json_extract(n.attrs, '$.source_date') >= ?",
        (concept_id, since),
    ).fetchone()[0]
    benchmark_coverage = float(bench_count) * 1.5

    # (f) novelty_bonus (weight 0.10)
    solved = _solved_confidence(conn, concept_id)
    fix_count = conn.execute(
        "SELECT COUNT(*) FROM nodes n "
        "JOIN edges e ON e.source_id = n.id "
        "WHERE e.kind = 'patches' AND e.target_id = ? AND n.kind = 'Fix'",
        (concept_id,),
    ).fetchone()[0]
    novelty_bonus = (1.0 - solved) * 5.0
    if fix_count == 0:
        novelty_bonus += 5.0
    elif fix_count <= 2:
        novelty_bonus += 2.0

    score = (
        discussion_density * 0.25
        + observation_recency * 0.20
        + evidence_diversity * 0.20
        + proposal_activity * 0.15
        + benchmark_coverage * 0.10
        + novelty_bonus * 0.10
    )
    return max(0.0, score)


def is_security_only_concept(conn: sqlite3.Connection, concept_id: str) -> bool:
    """INV-KK-GRAPH-RESEARCH-SCORE-NO-SECURITY-ONLY: True if concept's only
    inbound activity is from Vulnerability/Advisory nodes (exploits, assessed-by)."""
    _security_edge_kinds = ("exploits", "affects-subsystem")
    _research_edge_kinds = ("discusses", "observes", "benchmarks", "grounded-in",
                            "profiled-by", "identifies-problem")
    has_research = conn.execute(
        "SELECT 1 FROM edges WHERE kind IN ({}) AND target_id = ? LIMIT 1".format(
            ",".join(f"'{k}'" for k in _research_edge_kinds)),
        (concept_id,),
    ).fetchone()
    if has_research:
        return False
    has_security = conn.execute(
        "SELECT 1 FROM edges e JOIN nodes n ON n.id = e.source_id "
        "WHERE e.target_id = ? AND n.kind IN ('Vulnerability', 'Advisory') LIMIT 1",
        (concept_id,),
    ).fetchone()
    return has_security is not None


def _prerequisite_depth(conn: sqlite3.Connection, concept_id: str) -> int:
    """BFS max depth of prerequisite chain from concept."""
    depth = 0
    current_level = {concept_id}
    visited = {concept_id}
    while current_level:
        next_level: set[str] = set()
        for cid in current_level:
            rows = conn.execute(
                "SELECT target_id FROM edges WHERE kind = 'prerequisite' AND source_id = ?",
                (cid,),
            ).fetchall()
            for r in rows:
                if r[0] not in visited:
                    visited.add(r[0])
                    next_level.add(r[0])
        if next_level:
            depth += 1
        current_level = next_level
    return depth


def _prerequisite_subsystems(conn: sqlite3.Connection, concept_id: str) -> set[str]:
    """Collect distinct subsystems across the prerequisite chain."""
    visited = set()
    queue = [concept_id]
    subsystems: set[str] = set()
    while queue:
        cid = queue.pop(0)
        if cid in visited:
            continue
        visited.add(cid)
        sub_rows = conn.execute(
            "SELECT target_id FROM edges WHERE kind = 'belongs-to' AND source_id = ?",
            (cid,),
        ).fetchall()
        for r in sub_rows:
            subsystems.add(r[0])
        prereq_rows = conn.execute(
            "SELECT target_id FROM edges WHERE kind = 'prerequisite' AND source_id = ?",
            (cid,),
        ).fetchall()
        for r in prereq_rows:
            if r[0] not in visited:
                queue.append(r[0])
    return subsystems


def feasibility_score(
    conn: sqlite3.Connection,
    concept_id: str,
) -> float:
    """Estimate implementation feasibility (ALG-KK-GRAPH-FEASIBILITY-SCORE).

    INV-KK-GRAPH-FEASIBILITY-BOUNDED: result in [0, 10].
    INV-KK-GRAPH-FEASIBILITY-FORMULA: 10 - penalties.
    INV-KK-GRAPH-FEASIBILITY-PURE: deterministic.
    """
    prereq_depth = _prerequisite_depth(conn, concept_id)

    subsystems = _prerequisite_subsystems(conn, concept_id)
    cross_subsystem = 1 if len(subsystems) > 1 else 0

    inv_count = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind = 'governed-by' AND target_id = ?",
        (concept_id,),
    ).fetchone()[0]

    proto_count = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind = 'constrains-composition' AND target_id = ?",
        (concept_id,),
    ).fetchone()[0]

    penalties = (
        prereq_depth * 1.5
        + cross_subsystem * 2.0
        + inv_count * 0.5
        + proto_count * 0.5
    )
    return max(0.0, min(10.0, 10.0 - penalties))


def impact_projection(
    conn: sqlite3.Connection,
    concept_id: str,
) -> dict[str, Any]:
    """Project benefit if research succeeds (ALG-KK-GRAPH-IMPACT-PROJECTION).

    INV-KK-GRAPH-IMPACT-PROJECTION-COMPLETE: returns 7-key dict.
    INV-KK-GRAPH-IMPACT-PROJECTION-FORMULA: total_impact weighted sum.
    """
    problems = get_linked_problems(conn, concept_id)
    problems_addressed = sum(
        1 for p in problems if p.get("status") != "resolved"
    )

    vulns_mitigated = len(get_linked_vulns(conn, concept_id))

    failure_modes_eliminated = len(get_linked_failure_modes(conn, concept_id))

    dependent_rows = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind = 'prerequisite' AND target_id = ?",
        (concept_id,),
    ).fetchone()[0]
    dependent_components = dependent_rows

    perf_count = conn.execute(
        "SELECT COUNT(*) FROM nodes n "
        "JOIN edges e ON e.source_id = n.id "
        "WHERE e.kind = 'profiled-by' AND e.target_id = ? AND n.kind = 'PerformanceProfile'",
        (concept_id,),
    ).fetchone()[0]
    performance_metrics = perf_count

    sub_rows = conn.execute(
        "SELECT DISTINCT target_id FROM edges WHERE kind = 'belongs-to' AND source_id = ?",
        (concept_id,),
    ).fetchall()
    dep_sub_rows = conn.execute(
        "SELECT DISTINCT e2.target_id FROM edges e1 "
        "JOIN edges e2 ON e2.source_id = e1.source_id AND e2.kind = 'belongs-to' "
        "WHERE e1.kind = 'prerequisite' AND e1.target_id = ?",
        (concept_id,),
    ).fetchall()
    all_subs = {r[0] for r in sub_rows} | {r[0] for r in dep_sub_rows}
    subsystems_affected = len(all_subs)

    total_impact = (
        problems_addressed * 2
        + vulns_mitigated * 5
        + failure_modes_eliminated * 3
        + dependent_components * 1
        + performance_metrics * 1.5
        + subsystems_affected * 2
    )

    return {
        "problems_addressed": problems_addressed,
        "vulns_mitigated": vulns_mitigated,
        "failure_modes_eliminated": failure_modes_eliminated,
        "dependent_components": dependent_components,
        "performance_metrics": performance_metrics,
        "subsystems_affected": subsystems_affected,
        "total_impact": total_impact,
    }


def vulnerability_propagation(
    conn: sqlite3.Connection,
    vuln_id: str,
) -> dict[str, Any]:
    """Find all concepts at risk from a vulnerability (ALG-KK-VULN-PROPAGATE).

    INV-KK-VULN-PROP-DIRECT: direct concepts via exploits edge.
    INV-KK-VULN-PROP-PREREQ: dependents via reverse prerequisite.
    INV-KK-VULN-PROP-COMPOSE: composed_with via shared constrains-composition.
    INV-KK-VULN-PROP-INVARIANT: shared_invariant via shared governed-by.
    INV-KK-VULN-PROP-NO-SELF: no self-references in propagated lists.
    """
    direct_rows = conn.execute(
        "SELECT e.target_id FROM edges e "
        "JOIN nodes n ON e.target_id = n.id "
        "WHERE e.kind = 'exploits' AND e.source_id = ? AND n.kind = 'Concept'",
        (vuln_id,),
    ).fetchall()
    direct = [r[0] for r in direct_rows]

    propagated: dict[str, dict[str, list[str]]] = {}
    for cid in direct:
        dep_rows = conn.execute(
            "SELECT source_id FROM edges WHERE kind = 'prerequisite' AND target_id = ?",
            (cid,),
        ).fetchall()
        dependents = [r[0] for r in dep_rows if r[0] != cid]

        protocol_rows = conn.execute(
            "SELECT source_id FROM edges WHERE kind = 'constrains-composition' AND target_id = ?",
            (cid,),
        ).fetchall()
        composed_with: list[str] = []
        for prow in protocol_rows:
            proto_id = prow[0]
            other_rows = conn.execute(
                "SELECT target_id FROM edges "
                "WHERE kind = 'constrains-composition' AND source_id = ? AND target_id != ?",
                (proto_id, cid),
            ).fetchall()
            for orow in other_rows:
                if orow[0] not in composed_with:
                    composed_with.append(orow[0])

        inv_rows = conn.execute(
            "SELECT source_id FROM edges WHERE kind = 'governed-by' AND target_id = ?",
            (cid,),
        ).fetchall()
        shared_invariant: list[str] = []
        for irow in inv_rows:
            inv_id = irow[0]
            other_rows = conn.execute(
                "SELECT target_id FROM edges "
                "WHERE kind = 'governed-by' AND source_id = ? AND target_id != ?",
                (inv_id, cid),
            ).fetchall()
            for orow in other_rows:
                if orow[0] not in shared_invariant:
                    shared_invariant.append(orow[0])

        propagated[cid] = {
            "dependents": dependents,
            "composed_with": composed_with,
            "shared_invariant": shared_invariant,
        }

    return {"direct": direct, "propagated": propagated}
