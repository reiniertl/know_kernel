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

    # 17. Batch-resolve source URLs via provenance chain
    all_evidence_ids: list[str] = []
    evidence_collections = (
        problems, vulnerabilities, failure_modes, invariants,
        protocols, profiles, fixes, observations, discussions,
        benchmarks,
    )
    for item_list in evidence_collections:
        for item in item_list:
            all_evidence_ids.append(item["id"])

    source_urls: dict[str, str] = {}
    if all_evidence_ids:
        placeholders = ",".join("?" for _ in all_evidence_ids)
        url_rows = conn.execute(
            f"SELECT e1.source_id, json_extract(s.attrs, '$.url') "
            f"FROM edges e1 "
            f"JOIN edges e2 ON e2.source_id = e1.target_id "
            f"AND e2.kind = 'sourced-from' "
            f"JOIN nodes s ON e2.target_id = s.id "
            f"WHERE e1.kind = 'extracted-from' "
            f"AND e1.source_id IN ({placeholders})",
            all_evidence_ids,
        ).fetchall()
        for row in url_rows:
            if row[1]:
                source_urls[row[0]] = row[1]

    for item_list in evidence_collections:
        for item in item_list:
            item["source_url"] = source_urls.get(item["id"], "")

    for item in timeline:
        item["source_url"] = source_urls.get(item.get("id", ""), "")

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


# ---------------------------------------------------------------------------
# Motivation classification (ALG-KK-GRAPH-CLASSIFY-MOTIVATIONS)
# ---------------------------------------------------------------------------

_PERFORMANCE_KEYWORDS = frozenset({
    "latency", "throughput", "overhead", "bottleneck", "faster", "slower",
    "regression", "improvement", "speedup", "bandwidth", "iops", "cycles",
    "cache miss", "tlb miss", "context switch",
})

_SCALABILITY_KEYWORDS = frozenset({
    "numa", "core count", "128 cores", "256 cores", "512 cores",
    "scalab", "contention", "lock contention", "per-cpu", "per-node",
    "cache line bouncing", "false sharing", "thundering herd",
    "multi-socket", "cross-node", "numa node", "memory node",
})

_EFFICIENCY_KEYWORDS = frozenset({
    "memory overhead", "memory footprint", "power consumption", "energy",
    "cpu utilization", "wasted", "footprint", "bloat", "fragmentation",
    "internal fragmentation", "external fragmentation", "metadata overhead",
    "housekeeping", "idle power", "thermal",
})

_HARDWARE_KEYWORDS = frozenset({
    "hardware", "instruction", "cxl", "pcie", "nvme", "accelerat",
    "fpga", "gpu", "dpu", "amx", "sve", "sme", "tdx", "sev",
    "persistent memory", "pmem", "ddr5", "hbm", "cxl.mem",
    "device class", "new device", "hardware capability",
})

_HARDWARE_SUBSYSTEMS = frozenset({
    "Device Drivers", "Virtualization", "Storage Stack",
    "Firmware Interface", "Cryptography",
})

_MOTIVATION_ICONS: dict[str, str] = {
    "security": "\U0001f534",
    "stability": "⚠️",
    "performance": "⚡",
    "scalability": "\U0001f4c8",
    "efficiency": "\U0001f4a1",
    "hardware_enablement": "\U0001f527",
    "maintainability": "\U0001f504",
}

_MOTIVATION_LABELS: dict[str, str] = {
    "security": "SECURITY",
    "stability": "STABILITY",
    "performance": "PERFORMANCE",
    "scalability": "SCALABILITY",
    "efficiency": "EFFICIENCY",
    "hardware_enablement": "HARDWARE ENABLEMENT",
    "maintainability": "MAINTAINABILITY",
}


def _text_has_keywords(text: str, keywords: frozenset[str]) -> bool:
    """Check if *text* contains any keyword (case-insensitive)."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)


def classify_motivations(brief: dict[str, Any]) -> list[dict[str, Any]]:
    """Classify a concept brief into 1-7 orthogonal motivation categories.

    Returns a list of dicts, each with:
      category, icon, label, headline, evidence,
      blast_radius, actionable, cross_links

    Only triggered categories are returned, in priority order.
    """
    motivations: list[dict[str, Any]] = []

    blast_radius = {
        "count": len(brief["prerequisites"]["depended_on_by"]),
        "components": brief["prerequisites"]["depended_on_by"],
    }
    dep_count = blast_radius["count"]

    # --- SECURITY ---
    vulns = brief["vulnerabilities"]
    if vulns:
        severity_counts: dict[str, int] = {}
        for v in vulns:
            s = v.get("severity", "medium")
            severity_counts[s] = severity_counts.get(s, 0) + 1
        severity_parts = []
        for s in ("critical", "high", "medium", "low"):
            if severity_counts.get(s):
                severity_parts.append(f"{severity_counts[s]} {s}")
        headline = (
            f"{len(vulns)} active vulnerabilit"
            f"{'y' if len(vulns) == 1 else 'ies'}"
            f" ({', '.join(severity_parts)})"
        )
        if dep_count > 0:
            headline += (
                f". {dep_count} additional component"
                f"{'s' if dep_count != 1 else ''}"
                " at risk through coupling"
            )
        evidence = [
            {
                "type": "vulnerability",
                "id": v["id"],
                "source_url": v.get("source_url", ""),
                "cve_id": v["cve_id"],
                "text": f"{v['cve_id']}: {v['description']}",
                "severity": v.get("severity", "medium"),
                "cvss": v.get("cvss_score", 0.0),
                "affected_versions": v.get("affected_versions", ""),
                "status": v.get("status", ""),
            }
            for v in vulns
        ]
        actionable = (
            f"Fixing {'this vulnerability' if len(vulns) == 1 else 'these vulnerabilities'} "
            f"eliminates {len(vulns)} active attack surface"
            f"{'s' if len(vulns) != 1 else ''}"
        )
        if dep_count > 0:
            actionable += f" and removes exposure from {dep_count} dependent component{'s' if dep_count != 1 else ''}"
        actionable += "."
        motivations.append({
            "category": "security",
            "icon": _MOTIVATION_ICONS["security"],
            "label": _MOTIVATION_LABELS["security"],
            "headline": headline,
            "evidence": evidence,
            "blast_radius": blast_radius,
            "actionable": actionable,
            "cross_links": [],
        })

    # --- STABILITY ---
    failure_modes = brief["failure_modes"]
    critical_problems = [
        p for p in brief["problems"]
        if p.get("severity") in ("critical", "high")
    ]
    if failure_modes or critical_problems:
        parts: list[str] = []
        fm_evidence: list[dict[str, Any]] = []
        if failure_modes:
            top_fm = failure_modes[0]
            parts.append(
                f"Known failure mode: \"{top_fm['symptom']}\""
                f" (blast radius: {top_fm['blast_radius']},"
                f" {top_fm['recoverability']})"
            )
            fm_evidence.extend(
                {
                    "type": "failure_mode",
                    "id": fm["id"],
                    "source_url": fm.get("source_url", ""),
                    "text": fm["symptom"],
                    "blast_radius": fm["blast_radius"],
                    "recoverability": fm.get("recoverability", ""),
                }
                for fm in failure_modes
            )
        if brief["invariants"]:
            top_inv = brief["invariants"][0]
            parts.append(f"Invariant at risk: \"{top_inv['predicate']}\"")
            fm_evidence.extend(
                {
                    "type": "invariant",
                    "id": inv["id"],
                    "source_url": inv.get("source_url", ""),
                    "text": inv["predicate"],
                    "strength": inv.get("strength", ""),
                    "scope": inv.get("scope", ""),
                }
                for inv in brief["invariants"]
            )
        if critical_problems:
            parts.append(
                f"{len(critical_problems)} open"
                f" {critical_problems[0]['severity']}"
                f" problem{'s' if len(critical_problems) != 1 else ''}"
            )
            fm_evidence.extend(
                {
                    "type": "problem",
                    "id": p["id"],
                    "source_url": p.get("source_url", ""),
                    "text": p["title"],
                    "description": p["description"],
                    "severity": p["severity"],
                    "status": p.get("status", ""),
                }
                for p in critical_problems
            )
        _BLAST_ORDER = {"kernel-wide": 3, "subsystem": 2, "local": 1}
        _RECOV_ORDER = {"unrecoverable": 3, "requires-restart": 2, "self-healing": 1}
        worst_blast = max(
            (fm["blast_radius"] for fm in failure_modes),
            key=lambda b: _BLAST_ORDER.get(b, 0),
            default="local",
        ) if failure_modes else "local"
        worst_recovery = max(
            (fm.get("recoverability", "") for fm in failure_modes),
            key=lambda r: _RECOV_ORDER.get(r, 0),
            default="unknown",
        ) if failure_modes else "unknown"
        fm_count = len(failure_modes) + len(critical_problems)
        actionable = (
            f"Fixing this eliminates {fm_count} known crash/corruption path"
            f"{'s' if fm_count != 1 else ''} "
            f"(worst case: {worst_blast}, {worst_recovery})"
        )
        if dep_count > 0:
            actionable += f" and restores invariant guarantees for {dep_count} dependent component{'s' if dep_count != 1 else ''}"
        actionable += "."
        motivations.append({
            "category": "stability",
            "icon": _MOTIVATION_ICONS["stability"],
            "label": _MOTIVATION_LABELS["stability"],
            "headline": ". ".join(parts),
            "evidence": fm_evidence,
            "blast_radius": blast_radius,
            "actionable": actionable,
            "cross_links": [],
        })

    # --- PERFORMANCE ---
    profiles = brief["profiles"]
    benchmarks = brief["benchmarks"]
    perf_observations = [
        o for o in brief["observations"]
        if _text_has_keywords(o["claim"], _PERFORMANCE_KEYWORDS)
    ]
    if profiles or benchmarks or perf_observations:
        parts = []
        perf_evidence: list[dict[str, Any]] = []
        if profiles:
            top_prof = profiles[0]
            parts.append(
                f"{top_prof['metric']}: {top_prof['best_case']}"
                f" best → {top_prof['worst_case']} worst"
            )
            perf_evidence.extend(
                {
                    "type": "profile",
                    "id": p["id"],
                    "source_url": p.get("source_url", ""),
                    "text": (
                        f"{p['metric']}: {p['best_case']}"
                        f" → {p['worst_case']}"
                        f" ({p['conditions']})"
                    ),
                    "metric": p["metric"],
                    "best_case": p["best_case"],
                    "worst_case": p["worst_case"],
                    "typical_case": p["typical_case"],
                    "conditions": p["conditions"],
                    "complexity": p["complexity"],
                }
                for p in profiles
            )
        if benchmarks:
            perf_evidence.extend(
                {
                    "type": "benchmark",
                    "id": b["id"],
                    "source_url": b.get("source_url", ""),
                    "text": b["result_summary"],
                    "conditions": b.get("conditions", ""),
                }
                for b in benchmarks
            )
        if perf_observations:
            for o in perf_observations:
                parts.append(f"\"{o['claim']}\"")
            perf_evidence.extend(
                {
                    "type": "observation",
                    "id": o["id"],
                    "source_url": o.get("source_url", ""),
                    "text": o["claim"],
                }
                for o in perf_observations
            )
        if profiles:
            top = profiles[0]
            actionable = (
                f"Closing the gap between {top['best_case']} (best) and "
                f"{top['worst_case']} (worst) on {top['metric']} "
                f"under {top['conditions']}."
            )
        elif benchmarks:
            actionable = f"Benchmark data shows optimization opportunity: {benchmarks[0]['result_summary']}."
        else:
            actionable = "Performance observations indicate measurable optimization opportunity."
        motivations.append({
            "category": "performance",
            "icon": _MOTIVATION_ICONS["performance"],
            "label": _MOTIVATION_LABELS["performance"],
            "headline": (
                ". ".join(parts) if parts else "Performance data available"
            ),
            "evidence": perf_evidence,
            "blast_radius": blast_radius,
            "actionable": actionable,
            "cross_links": [],
        })

    # --- SCALABILITY ---
    scaling_items: list[dict[str, Any]] = []
    for p in brief["problems"]:
        if _text_has_keywords(p["description"], _SCALABILITY_KEYWORDS):
            scaling_items.append({
                "type": "problem", "id": p["id"],
                "source_url": p.get("source_url", ""),
                "text": p["description"],
            })
    for o in brief["observations"]:
        if _text_has_keywords(o["claim"], _SCALABILITY_KEYWORDS):
            scaling_items.append({
                "type": "observation", "id": o["id"],
                "source_url": o.get("source_url", ""),
                "text": o["claim"],
            })
    for d in brief["discussions"]:
        if _text_has_keywords(d["title"], _SCALABILITY_KEYWORDS):
            scaling_items.append({
                "type": "discussion", "id": d["id"],
                "source_url": d.get("source_url", ""),
                "text": d["title"],
                "forum": d.get("forum", ""),
            })
    if scaling_items:
        motivations.append({
            "category": "scalability",
            "icon": _MOTIVATION_ICONS["scalability"],
            "label": _MOTIVATION_LABELS["scalability"],
            "headline": scaling_items[0]["text"],
            "evidence": scaling_items,
            "blast_radius": blast_radius,
            "actionable": "Removes scaling wall, enabling linear throughput growth with core count and NUMA topology.",
            "cross_links": [],
        })

    # --- EFFICIENCY ---
    efficiency_items: list[dict[str, Any]] = []
    for p in profiles:
        if _text_has_keywords(p["metric"], _EFFICIENCY_KEYWORDS):
            efficiency_items.append({
                "type": "profile", "id": p["id"],
                "source_url": p.get("source_url", ""),
                "text": f"{p['metric']}: {p['worst_case']}",
            })
    for o in brief["observations"]:
        if _text_has_keywords(o["claim"], _EFFICIENCY_KEYWORDS):
            efficiency_items.append({
                "type": "observation", "id": o["id"],
                "source_url": o.get("source_url", ""),
                "text": o["claim"],
            })
    for p in brief["problems"]:
        if _text_has_keywords(p["description"], _EFFICIENCY_KEYWORDS):
            efficiency_items.append({
                "type": "problem", "id": p["id"],
                "source_url": p.get("source_url", ""),
                "text": p["description"],
            })
    if efficiency_items:
        first_text = efficiency_items[0]["text"]
        motivations.append({
            "category": "efficiency",
            "icon": _MOTIVATION_ICONS["efficiency"],
            "label": _MOTIVATION_LABELS["efficiency"],
            "headline": first_text,
            "evidence": efficiency_items,
            "blast_radius": blast_radius,
            "actionable": f"Reclaims resources currently wasted on {first_text.split(':')[0].lower()} without sacrificing functionality.",
            "cross_links": [],
        })

    # --- HARDWARE ENABLEMENT ---
    hw_evidence_items: list[dict[str, Any]] = []
    for d in brief["discussions"]:
        if _text_has_keywords(d["title"], _HARDWARE_KEYWORDS):
            hw_evidence_items.append({
                "type": "discussion", "id": d["id"],
                "source_url": d.get("source_url", ""),
                "text": d["title"],
            })
    for o in brief["observations"]:
        if _text_has_keywords(o["claim"], _HARDWARE_KEYWORDS):
            hw_evidence_items.append({
                "type": "observation", "id": o["id"],
                "source_url": o.get("source_url", ""),
                "text": o["claim"],
            })
    hw_from_description = _text_has_keywords(
        brief["concept"]["description"], _HARDWARE_KEYWORDS
    )
    hw_from_subsystem = (
        brief["subsystem"] is not None
        and brief["subsystem"]["name"] in _HARDWARE_SUBSYSTEMS
        and brief["scores"]["heat"] > brief["scores"]["pain"]
    )
    if hw_evidence_items or hw_from_description or hw_from_subsystem:
        parts = []
        if hw_from_description:
            parts.append(
                f"{brief['concept']['name']} interfaces"
                " with hardware capabilities"
            )
            hw_evidence_items.append({
                "type": "concept_description",
                "id": brief["concept"]["id"],
                "source_url": "",
                "text": brief["concept"]["description"][:200],
            })
        if hw_from_subsystem:
            parts.append(
                f"Active area in {brief['subsystem']['name']}"
                " subsystem (heat > pain)"
            )
        if hw_evidence_items:
            parts.append(hw_evidence_items[0]["text"])
        hw_cross_links: list[str] = []
        if brief["profiles"] or brief["benchmarks"]:
            hw_cross_links.append("performance")
        actionable = "Unlocks hardware capabilities that software currently cannot exploit."
        if brief["profiles"]:
            top = brief["profiles"][0]
            actionable += (
                f" Direct performance gains expected: {top['metric']} "
                f"currently {top['worst_case']} worst case."
            )
        motivations.append({
            "category": "hardware_enablement",
            "icon": _MOTIVATION_ICONS["hardware_enablement"],
            "label": _MOTIVATION_LABELS["hardware_enablement"],
            "headline": (
                ". ".join(parts)
                if parts
                else "Hardware-related activity"
            ),
            "evidence": hw_evidence_items,
            "blast_radius": blast_radius,
            "actionable": actionable,
            "cross_links": hw_cross_links,
        })

    # --- MAINTAINABILITY ---
    fixes = brief["fixes"]
    regression_fixes = [
        f for f in fixes if f.get("fix_type") == "regression-fix"
    ]
    if len(fixes) >= 3 or regression_fixes:
        parts = [
            f"{len(fixes)} patch"
            f"{'es' if len(fixes) != 1 else ''}"
            " in recent window"
        ]
        if regression_fixes:
            parts.append(
                f"{len(regression_fixes)} regression fix"
                f"{'es' if len(regression_fixes) != 1 else ''}"
            )
        actionable = f"Reduces patch churn from {len(fixes)} patches in recent window"
        if regression_fixes:
            actionable += f", eliminates {len(regression_fixes)} regression cycle{'s' if len(regression_fixes) != 1 else ''}"
        actionable += ". Future changes become cheaper and safer."
        motivations.append({
            "category": "maintainability",
            "icon": _MOTIVATION_ICONS["maintainability"],
            "label": _MOTIVATION_LABELS["maintainability"],
            "headline": (
                ", including ".join(parts) if len(parts) > 1 else parts[0]
            ),
            "evidence": [
                {
                    "type": "fix",
                    "id": f["id"],
                    "source_url": f.get("source_url", ""),
                    "text": f["title"],
                    "fix_type": f.get("fix_type", "unknown"),
                    "commit": f.get("commit_hash", ""),
                    "source_date": f.get("source_date", ""),
                    "resolves": f.get("resolves", []),
                }
                for f in fixes
            ],
            "blast_radius": blast_radius,
            "actionable": actionable,
            "cross_links": [],
        })

    return motivations


def classify_source_motivations(
    conn: sqlite3.Connection, source_id: str,
) -> list[str]:
    """Return motivation labels grounded in a single Source's evidence chain.

    Only considers nodes extracted from this source's Evidence, so labels
    reflect what the paper actually discusses, not concept-level aggregates.
    """
    ev_ids = [
        r[0] for r in conn.execute(
            "SELECT source_id FROM edges "
            "WHERE kind = 'sourced-from' AND target_id = ?",
            (source_id,),
        ).fetchall()
    ]
    if not ev_ids:
        return []

    ph = ",".join("?" for _ in ev_ids)
    child_rows = conn.execute(
        f"SELECT n.kind, n.attrs FROM nodes n "
        f"JOIN edges e ON e.source_id = n.id "
        f"WHERE e.kind = 'extracted-from' AND e.target_id IN ({ph})",
        ev_ids,
    ).fetchall()

    _SOURCE_TEXT_FIELDS = {
        **{k: v for k, v in _VERBATIM_TEXT_FIELD.items()},
        "PerformanceProfile": "metric",
        "KernelInvariant": "predicate",
        "FailureMode": "symptom",
        "InteractionProtocol": "rule",
    }

    kinds_present: set[str] = set()
    texts_by_kind: dict[str, list[str]] = {}
    for kind, raw_attrs in child_rows:
        kinds_present.add(kind)
        attrs = json.loads(raw_attrs) if isinstance(raw_attrs, str) else (raw_attrs or {})
        field = _SOURCE_TEXT_FIELDS.get(kind, "title")
        text = attrs.get(field, attrs.get("description", ""))
        if text:
            texts_by_kind.setdefault(kind, []).append(text)

    labels: list[str] = []
    all_texts = [t for ts in texts_by_kind.values() for t in ts]

    if "Vulnerability" in kinds_present:
        labels.append("SECURITY")

    if "FailureMode" in kinds_present or [
        t for t in texts_by_kind.get("Problem", [])
        if any(kw in t.lower() for kw in ("critical", "high"))
    ]:
        labels.append("STABILITY")

    if (
        "PerformanceProfile" in kinds_present
        or "Benchmark" in kinds_present
        or any(_text_has_keywords(t, _PERFORMANCE_KEYWORDS) for t in all_texts)
    ):
        labels.append("PERFORMANCE")

    if any(_text_has_keywords(t, _SCALABILITY_KEYWORDS) for t in all_texts):
        labels.append("SCALABILITY")

    if any(_text_has_keywords(t, _EFFICIENCY_KEYWORDS) for t in all_texts):
        labels.append("EFFICIENCY")

    if any(_text_has_keywords(t, _HARDWARE_KEYWORDS) for t in all_texts):
        labels.append("HARDWARE ENABLEMENT")

    fix_texts = texts_by_kind.get("Fix", [])
    if len(fix_texts) >= 3 or any("regression" in t.lower() for t in fix_texts):
        labels.append("MAINTAINABILITY")

    return labels


# ---------------------------------------------------------------------------
# Argument paragraph (ALG-KK-GRAPH-BUILD-ARGUMENT)
# ---------------------------------------------------------------------------


def build_argument_paragraph(
    node_attrs: dict[str, Any],
    briefs: list[dict[str, Any]],
    motivations: list[dict[str, Any]],
    window_days: int = 90,
) -> str:
    """Compose a deterministic argument paragraph from structured data.

    Every sentence maps to a specific graph data count. NOT LLM-generated —
    same inputs always produce identical output.
    """
    if not briefs:
        return ""

    parts: list[str] = []
    concept_names = [b["concept"]["name"] for b in briefs]
    source_urls = set()
    for b in briefs:
        for ev in b.get("timeline", []):
            url = ev.get("source_url", "")
            if url:
                source_urls.add(url)
    source_count = len(source_urls) or sum(
        len(b["discussions"]) + len(b["observations"]) for b in briefs
    )

    if source_count > 0:
        parts.append(
            f"{source_count} independent source"
            f"{'s' if source_count != 1 else ''} "
            f"discuss{'es' if source_count == 1 else ''} "
            f"{' and '.join(concept_names)}"
            f" over the last {window_days} days."
        )

    cat_names = {m["category"] for m in motivations}

    if "security" in cat_names:
        vuln_count = sum(len(b["vulnerabilities"]) for b in briefs)
        dominant = _dominant_severity(briefs)
        parts.append(
            f"The convergence is driven by {vuln_count} "
            f"{dominant.upper()}-severity "
            f"vulnerabilit{'y' if vuln_count == 1 else 'ies'} "
            f"in active code paths."
        )

    if "stability" in cat_names:
        fm_count = sum(len(b["failure_modes"]) for b in briefs)
        connector = "Combined with" if "security" in cat_names else "Driven by"
        parts.append(
            f"{connector} {fm_count} known failure "
            f"mode{'s' if fm_count != 1 else ''} "
            f"that can cause system instability."
        )

    if (
        "performance" in cat_names
        and "security" not in cat_names
        and "stability" not in cat_names
    ):
        parts.append(
            "Performance profiling shows measurable optimization opportunity."
        )

    dep_count = sum(
        len(b["prerequisites"]["depended_on_by"]) for b in briefs
    )
    if dep_count > 0:
        dep_names = [
            d["name"]
            for b in briefs
            for d in b["prerequisites"]["depended_on_by"]
        ]
        shown = dep_names[:4]
        suffix = "..." if len(dep_names) > 4 else ""
        parts.append(
            f"{dep_count} component"
            f"{'s' if dep_count != 1 else ''} "
            f"depend{'s' if dep_count == 1 else ''} on "
            f"{concept_names[0]}: {', '.join(shown)}{suffix}. "
            f"A fix here would resolve exposure across all of them."
        )

    frontier = briefs[0]["scores"]["frontier"]
    pain = briefs[0]["scores"]["pain"]
    heat = briefs[0]["scores"]["heat"]
    dominant_score = "pain" if pain > heat else "heat"
    parts.append(
        f"Frontier score: {frontier:.1f} "
        f"(heat={heat:.1f}, pain={pain:.1f}). "
        f"{'Pain dominates' if dominant_score == 'pain' else 'Activity dominates'}"
        f" the frontier score."
    )

    return " ".join(parts)


def _dominant_severity(briefs: list[dict[str, Any]]) -> str:
    """Return the most common severity across all vulnerabilities in briefs."""
    severities = [
        v.get("severity", "medium")
        for b in briefs
        for v in b["vulnerabilities"]
    ]
    if not severities:
        return "medium"
    return max(set(severities), key=severities.count)