"""Concept briefing helper (ALG-KK-GRAPH-CONCEPT-BRIEF).

Builds a complete research brief dict for a Concept node by querying the
full graph depth across 15 data categories.

INV-KK-GRAPH-BRIEF-ALL-CATEGORIES: all 15 keys always present.
INV-KK-GRAPH-BRIEF-VERBATIM: evidence text copied verbatim from node attrs.
INV-KK-GRAPH-BRIEF-EMPTY-SAFE: no raises for concepts with no edges.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from graph.engine import concept_timeline, transitive_impact
from graph.scoring import (
    compute_all_scores,
    get_linked_failure_modes,
    get_linked_problems,
    get_linked_vulns,
)

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

_VERBATIM_TEXT_FIELD: dict[str, str] = {
    "Problem": "title",
    "Observation": "claim",
    "Discussion": "title",
    "Benchmark": "result_summary",
    "Vulnerability": "description",
    "Rejection": "proposal_title",
    "Proposal": "name",
}


def build_concept_brief(
    conn: sqlite3.Connection,
    concept_id: str,
    window_days: int = 90,
) -> dict[str, Any]:
    """Query the full graph depth for a concept, returning a 15-key dict."""

    # 1. Fetch concept node
    row = conn.execute(
        "SELECT id, kind, attrs FROM nodes WHERE id = ? AND kind = 'Concept'",
        (concept_id,),
    ).fetchone()
    if row is None:
        return _empty_brief(concept_id)
    attrs = json.loads(row[2]) if isinstance(row[2], str) else (row[2] or {})
    concept = {
        "id": row[0],
        "name": attrs.get("name", ""),
        "description": attrs.get("description", ""),
        "key_properties": attrs.get("key_properties", []),
        "tradeoffs": attrs.get("tradeoffs", []),
        "design_rationale": attrs.get("design_rationale", ""),
    }

    # 2. Fetch subsystem
    sub_row = conn.execute(
        "SELECT n.id, json_extract(n.attrs, '$.name') as name "
        "FROM edges e JOIN nodes n ON e.target_id = n.id "
        "WHERE e.kind = 'belongs-to' AND e.source_id = ? AND n.kind = 'Subsystem'",
        (concept_id,),
    ).fetchone()
    subsystem = {"id": sub_row[0], "name": sub_row[1]} if sub_row else None

    # 3. Compute scores
    scores = compute_all_scores(conn, concept_id, window_days=window_days)

    # 4. Fetch problems — sorted by severity
    problems_raw = get_linked_problems(conn, concept_id)
    problems = [
        {
            "id": p["id"],
            "title": p.get("title", ""),
            "description": p.get("description", ""),
            "severity": p.get("severity", "medium"),
            "status": p.get("status", "open"),
            "source_date": p.get("source_date", ""),
        }
        for p in problems_raw
    ]
    problems.sort(key=lambda p: _SEVERITY_ORDER.get(p["severity"], 99))

    # 5. Fetch vulnerabilities — sorted by cvss_score descending
    vulns_raw = get_linked_vulns(conn, concept_id)
    vulnerabilities = [
        {
            "id": v["id"],
            "cve_id": v.get("cve_id", ""),
            "title": v.get("title", ""),
            "description": v.get("description", ""),
            "severity": v.get("severity", ""),
            "cvss_score": v.get("cvss_score", ""),
            "affected_versions": v.get("affected_versions", ""),
            "status": v.get("status", ""),
            "source_date": v.get("source_date", ""),
        }
        for v in vulns_raw
    ]
    vulnerabilities.sort(
        key=lambda v: float(v["cvss_score"]) if v["cvss_score"] else 0,
        reverse=True,
    )

    # 6. Fetch failure modes
    fm_raw = get_linked_failure_modes(conn, concept_id)
    failure_modes = [
        {
            "id": fm["id"],
            "symptom": fm.get("symptom", ""),
            "blast_radius": fm.get("blast_radius", ""),
            "recoverability": fm.get("recoverability", ""),
        }
        for fm in fm_raw
    ]

    # 7. Fetch invariants, protocols, profiles via transitive_impact
    impact = transitive_impact(conn, concept_id)

    invariants = [
        {
            "id": inv["id"],
            "predicate": inv.get("attrs", {}).get("predicate", ""),
            "strength": inv.get("attrs", {}).get("strength", ""),
            "scope": inv.get("attrs", {}).get("scope", ""),
        }
        for inv in impact["invariants"]
    ]

    protocols_raw = impact["protocols"]
    protocols = []
    for proto in protocols_raw:
        proto_attrs = proto.get("attrs", {})
        # 8. Resolve protocol participant concepts
        participant_rows = conn.execute(
            "SELECT n.id, json_extract(n.attrs, '$.name') as name "
            "FROM edges e JOIN nodes n ON e.target_id = n.id "
            "WHERE e.kind = 'constrains-composition' AND e.source_id = ? "
            "AND e.target_id != ? AND n.kind = 'Concept'",
            (proto["id"], concept_id),
        ).fetchall()
        protocols.append({
            "id": proto["id"],
            "rule": proto_attrs.get("rule", ""),
            "ordering": proto_attrs.get("ordering", ""),
            "violation_mode": proto_attrs.get("violation_mode", ""),
            "participant_concepts": [
                {"id": pr[0], "name": pr[1]} for pr in participant_rows
            ],
        })

    profiles = [
        {
            "id": prof["id"],
            "metric": prof.get("attrs", {}).get("metric", ""),
            "complexity": prof.get("attrs", {}).get("complexity", ""),
            "best_case": prof.get("attrs", {}).get("best_case", ""),
            "worst_case": prof.get("attrs", {}).get("worst_case", ""),
            "typical_case": prof.get("attrs", {}).get("typical_case", ""),
            "conditions": prof.get("attrs", {}).get("conditions", ""),
        }
        for prof in impact["profiles"]
    ]

    # Deduplicate failure_modes from transitive_impact with those from step 6
    seen_fm_ids = {fm["id"] for fm in failure_modes}
    for fm in impact["failure_modes"]:
        if fm["id"] not in seen_fm_ids:
            seen_fm_ids.add(fm["id"])
            failure_modes.append({
                "id": fm["id"],
                "symptom": fm.get("attrs", {}).get("symptom", ""),
                "blast_radius": fm.get("attrs", {}).get("blast_radius", ""),
                "recoverability": fm.get("attrs", {}).get("recoverability", ""),
            })

    # 9. Fetch prerequisites (outgoing — what this concept depends on)
    depends_on_rows = conn.execute(
        "SELECT n.id, json_extract(n.attrs, '$.name') as name "
        "FROM edges e JOIN nodes n ON e.target_id = n.id "
        "WHERE e.kind = 'prerequisite' AND e.source_id = ? AND n.kind = 'Concept'",
        (concept_id,),
    ).fetchall()

    # 10. Fetch prerequisites (incoming — what depends on this concept)
    depended_on_by_rows = conn.execute(
        "SELECT n.id, json_extract(n.attrs, '$.name') as name "
        "FROM edges e JOIN nodes n ON e.source_id = n.id "
        "WHERE e.kind = 'prerequisite' AND e.target_id = ? AND n.kind = 'Concept'",
        (concept_id,),
    ).fetchall()

    prerequisites = {
        "depends_on": [{"id": r[0], "name": r[1]} for r in depends_on_rows],
        "depended_on_by": [{"id": r[0], "name": r[1]} for r in depended_on_by_rows],
    }

    # 11. Fetch fixes (patches edge incoming to concept)
    fix_rows = conn.execute(
        "SELECT n.id, n.attrs FROM nodes n "
        "JOIN edges e ON e.source_id = n.id "
        "WHERE e.kind = 'patches' AND e.target_id = ? AND n.kind = 'Fix'",
        (concept_id,),
    ).fetchall()
    fixes = []
    for fr in fix_rows:
        fa = json.loads(fr[1]) if isinstance(fr[1], str) else (fr[1] or {})
        resolves_rows = conn.execute(
            "SELECT n.id, n.kind, json_extract(n.attrs, '$.title') as title "
            "FROM edges e JOIN nodes n ON e.target_id = n.id "
            "WHERE e.kind = 'fixes' AND e.source_id = ?",
            (fr[0],),
        ).fetchall()
        fixes.append({
            "id": fr[0],
            "title": fa.get("title", ""),
            "commit_hash": fa.get("commit_hash", ""),
            "fix_type": fa.get("fix_type", ""),
            "source_date": fa.get("source_date", ""),
            "resolves": [
                {"id": rr[0], "kind": rr[1], "title": rr[2] or ""}
                for rr in resolves_rows
            ],
        })

    # 12. Fetch discussions
    disc_rows = conn.execute(
        "SELECT n.id, n.attrs FROM nodes n "
        "JOIN edges e ON e.source_id = n.id "
        "WHERE e.kind = 'discusses' AND e.target_id = ? AND n.kind = 'Discussion'",
        (concept_id,),
    ).fetchall()
    discussions = sorted(
        [
            {
                "id": r[0],
                "title": (json.loads(r[1]) if isinstance(r[1], str) else (r[1] or {})).get("title", ""),
                "forum": (json.loads(r[1]) if isinstance(r[1], str) else (r[1] or {})).get("forum", ""),
                "participant_count": (json.loads(r[1]) if isinstance(r[1], str) else (r[1] or {})).get("participant_count", 0),
                "source_date": (json.loads(r[1]) if isinstance(r[1], str) else (r[1] or {})).get("source_date", ""),
            }
            for r in disc_rows
        ],
        key=lambda d: d["source_date"],
        reverse=True,
    )

    # 13. Fetch observations
    obs_rows = conn.execute(
        "SELECT n.id, n.attrs FROM nodes n "
        "JOIN edges e ON e.source_id = n.id "
        "WHERE e.kind = 'observes' AND e.target_id = ? AND n.kind = 'Observation'",
        (concept_id,),
    ).fetchall()
    observations = sorted(
        [
            {
                "id": r[0],
                "claim": (json.loads(r[1]) if isinstance(r[1], str) else (r[1] or {})).get("claim", ""),
                "confidence": (json.loads(r[1]) if isinstance(r[1], str) else (r[1] or {})).get("confidence", ""),
                "source_date": (json.loads(r[1]) if isinstance(r[1], str) else (r[1] or {})).get("source_date", ""),
            }
            for r in obs_rows
        ],
        key=lambda o: o["source_date"],
        reverse=True,
    )

    # 14. Fetch benchmarks
    bench_rows = conn.execute(
        "SELECT n.id, n.attrs FROM nodes n "
        "JOIN edges e ON e.source_id = n.id "
        "WHERE e.kind = 'benchmarks' AND e.target_id = ? AND n.kind = 'Benchmark'",
        (concept_id,),
    ).fetchall()
    benchmarks = sorted(
        [
            {
                "id": r[0],
                "metric": (json.loads(r[1]) if isinstance(r[1], str) else (r[1] or {})).get("metric", ""),
                "result_summary": (json.loads(r[1]) if isinstance(r[1], str) else (r[1] or {})).get("result_summary", ""),
                "conditions": (json.loads(r[1]) if isinstance(r[1], str) else (r[1] or {})).get("conditions", ""),
                "source_date": (json.loads(r[1]) if isinstance(r[1], str) else (r[1] or {})).get("source_date", ""),
            }
            for r in bench_rows
        ],
        key=lambda b: b["source_date"],
        reverse=True,
    )

    # 15. Build unified timeline (concept_timeline returns ASC, we reverse)
    timeline_raw = concept_timeline(conn, concept_id)
    timeline = [
        {
            "source_date": item.get("source_date", ""),
            "kind": item["kind"],
            "id": item["id"],
            "text": item.get("attrs", {}).get(
                _VERBATIM_TEXT_FIELD.get(item["kind"], "title"), ""
            ),
        }
        for item in reversed(timeline_raw)
    ]

    # 16. Extract code examples
    code_examples = attrs.get("code_examples", [])

    return {
        "concept": concept,
        "subsystem": subsystem,
        "scores": scores,
        "problems": problems,
        "vulnerabilities": vulnerabilities,
        "failure_modes": failure_modes,
        "invariants": invariants,
        "protocols": protocols,
        "profiles": profiles,
        "prerequisites": prerequisites,
        "fixes": fixes,
        "observations": observations,
        "discussions": discussions,
        "benchmarks": benchmarks,
        "timeline": timeline,
        "code_examples": code_examples,
    }


def _empty_brief(concept_id: str) -> dict[str, Any]:
    """Return a brief with all keys present but empty data."""
    return {
        "concept": {
            "id": concept_id,
            "name": "",
            "description": "",
            "key_properties": [],
            "tradeoffs": [],
            "design_rationale": "",
        },
        "subsystem": None,
        "scores": {
            "heat": 0.0,
            "pain": 0.0,
            "impact": 0.0,
            "leverage": 0.0,
            "frontier": 0.0,
        },
        "problems": [],
        "vulnerabilities": [],
        "failure_modes": [],
        "invariants": [],
        "protocols": [],
        "profiles": [],
        "prerequisites": {"depends_on": [], "depended_on_by": []},
        "fixes": [],
        "observations": [],
        "discussions": [],
        "benchmarks": [],
        "timeline": [],
        "code_examples": [],
    }
