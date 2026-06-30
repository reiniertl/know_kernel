"""Tests for build_concept_brief (ALG-KK-GRAPH-CONCEPT-BRIEF).

INV-KK-GRAPH-BRIEF-ALL-CATEGORIES: all 15 keys present.
INV-KK-GRAPH-BRIEF-VERBATIM: evidence text verbatim from attrs.
INV-KK-GRAPH-BRIEF-EMPTY-SAFE: no raises for edgeless concepts.
"""

from __future__ import annotations

import json

import pytest

from graph.briefing import build_concept_brief
from graph.engine import add_edge, add_node
from graph.schema import init_db


@pytest.fixture
def brief_db(tmp_path):
    db_path = tmp_path / "brief_test.db"
    conn = init_db(db_path)

    # Subsystem
    add_node(conn, "sub-mem", "Subsystem", {
        "name": "Memory Management",
        "description": "Kernel memory subsystem",
    })

    # Main concept
    add_node(conn, "concept-slub", "Concept", {
        "name": "SLUB Allocator",
        "description": "Slab allocator for kernel objects.",
        "artifact_class": "B",
        "key_properties": ["cache-friendly", "per-cpu"],
        "tradeoffs": ["memory overhead vs speed"],
        "design_rationale": "Replaces SLAB for better performance.",
        "code_examples": [
            {"language": "c", "code": "kmalloc(size, GFP_KERNEL);", "description": "Basic allocation"},
        ],
    })
    add_edge(conn, "belongs-to", "concept-slub", "sub-mem")

    # Source + Evidence (provenance)
    add_node(conn, "src-1", "Source", {
        "url": "https://lkml.org/slub",
        "source_type": "mailing_list",
        "license": "GPL-2.0",
    })
    add_node(conn, "ev-1", "Evidence", {
        "artifact_class": "A",
        "contamination_level": "none",
        "excerpt": "SLUB discussion excerpt",
        "extraction_method": "llm_extraction",
        "source_date": "2024-01-15",
    })
    add_edge(conn, "sourced-from", "ev-1", "src-1")

    # Advisory
    add_node(conn, "adv-1", "Advisory", {
        "assessment": "approved",
        "contamination_confirmed": False,
    })
    add_edge(conn, "assessed-by", "src-1", "adv-1")

    # Problem
    add_node(conn, "prob-uaf", "Problem", {
        "title": "UAF in SLUB",
        "description": "Use-after-free in slab cache.",
        "severity": "critical",
        "status": "open",
        "source_date": "2024-02-01",
        "artifact_class": "B",
    })
    add_edge(conn, "identifies-problem", "prob-uaf", "concept-slub")
    add_edge(conn, "extracted-from", "prob-uaf", "ev-1")

    # Vulnerability
    add_node(conn, "vuln-001", "Vulnerability", {
        "cve_id": "CVE-TEST-001",
        "title": "SLUB heap overflow",
        "description": "Heap overflow in SLUB cache reclaim path.",
        "severity": "high",
        "cvss_score": "7.5",
        "affected_versions": "5.15-6.1",
        "status": "open",
        "source_date": "2024-03-01",
        "artifact_class": "B",
    })
    add_edge(conn, "exploits", "vuln-001", "concept-slub")

    # KernelInvariant
    add_node(conn, "kinv-slab", "KernelInvariant", {
        "predicate": "slab objects must be freed exactly once",
        "strength": "strong",
        "scope": "per-cpu slab caches",
        "artifact_class": "B",
    })
    add_edge(conn, "governed-by", "kinv-slab", "concept-slub")
    add_edge(conn, "extracted-from", "kinv-slab", "ev-1")

    # FailureMode
    add_node(conn, "fm-corrupt", "FailureMode", {
        "symptom": "memory corruption",
        "blast_radius": "kernel-wide",
        "recoverability": "unrecoverable",
        "artifact_class": "B",
    })
    add_edge(conn, "triggered-by", "fm-corrupt", "kinv-slab")
    add_edge(conn, "extracted-from", "fm-corrupt", "ev-1")

    # InteractionProtocol with 2 participant concepts
    add_node(conn, "concept-pagecache", "Concept", {
        "name": "Page Cache",
        "description": "Kernel page cache.",
        "artifact_class": "B",
        "key_properties": ["readahead"],
        "tradeoffs": ["memory vs IO"],
        "design_rationale": "Cache disk pages in RAM.",
    })
    add_node(conn, "ip-slub-page", "InteractionProtocol", {
        "rule": "SLUB must request pages via page allocator API",
        "ordering": "sequential",
        "violation_mode": "silent corruption",
        "artifact_class": "B",
    })
    add_edge(conn, "constrains-composition", "ip-slub-page", "concept-slub")
    add_edge(conn, "constrains-composition", "ip-slub-page", "concept-pagecache")
    add_edge(conn, "extracted-from", "ip-slub-page", "ev-1")

    # PerformanceProfile
    add_node(conn, "perf-alloc", "PerformanceProfile", {
        "metric": "allocation latency",
        "complexity": "O(1) amortized",
        "best_case": "50ns",
        "worst_case": "10us",
        "typical_case": "100ns",
        "conditions": "per-cpu cache hit",
        "artifact_class": "B",
    })
    add_edge(conn, "profiled-by", "perf-alloc", "concept-slub")
    add_edge(conn, "extracted-from", "perf-alloc", "ev-1")

    # Prerequisites
    add_node(conn, "concept-buddy", "Concept", {
        "name": "Buddy Allocator",
        "description": "Page-level allocator.",
        "artifact_class": "B",
        "key_properties": ["power-of-two"],
        "tradeoffs": ["fragmentation vs simplicity"],
        "design_rationale": "Simple page allocation.",
    })
    add_edge(conn, "prerequisite", "concept-slub", "concept-pagecache")
    add_edge(conn, "prerequisite", "concept-buddy", "concept-slub")

    # Fix
    add_node(conn, "fix-uaf", "Fix", {
        "title": "fix UAF in SLUB reclaim",
        "commit_hash": "abc123def",
        "fix_type": "security",
        "source_date": "2024-04-01",
        "artifact_class": "B",
    })
    add_edge(conn, "patches", "fix-uaf", "concept-slub")
    add_edge(conn, "fixes", "fix-uaf", "prob-uaf")

    # Discussion
    add_node(conn, "disc-slub", "Discussion", {
        "title": "SLUB allocator rework discussion",
        "forum": "LKML",
        "participant_count": 15,
        "source_date": "2024-01-20",
        "artifact_class": "B",
    })
    add_edge(conn, "discusses", "disc-slub", "concept-slub")
    add_edge(conn, "extracted-from", "disc-slub", "ev-1")

    # Observation
    add_node(conn, "obs-slub", "Observation", {
        "claim": "SLUB shows 30% fewer cache misses than SLAB",
        "confidence": "high",
        "source_date": "2024-02-15",
        "artifact_class": "B",
    })
    add_edge(conn, "observes", "obs-slub", "concept-slub")
    add_edge(conn, "extracted-from", "obs-slub", "ev-1")

    # Benchmark
    add_node(conn, "bench-throughput", "Benchmark", {
        "metric": "allocation throughput",
        "result_summary": "1.2M allocs/sec on 8-core",
        "conditions": "GFP_KERNEL, 64-byte objects",
        "source_date": "2024-03-10",
        "artifact_class": "B",
    })
    add_edge(conn, "benchmarks", "bench-throughput", "concept-slub")
    add_edge(conn, "extracted-from", "bench-throughput", "ev-1")

    conn.commit()
    return conn


@pytest.fixture
def empty_concept_db(tmp_path):
    db_path = tmp_path / "empty_test.db"
    conn = init_db(db_path)
    add_node(conn, "concept-empty", "Concept", {
        "name": "Empty Concept",
        "description": "Has no edges.",
        "artifact_class": "B",
        "key_properties": [],
        "tradeoffs": [],
        "design_rationale": "",
    })
    conn.commit()
    return conn


# --- INV-KK-GRAPH-BRIEF-ALL-CATEGORIES tests ---

EXPECTED_KEYS = {
    "concept", "subsystem", "scores", "problems", "vulnerabilities",
    "failure_modes", "invariants", "protocols", "profiles",
    "prerequisites", "fixes", "observations", "discussions",
    "benchmarks", "timeline", "code_examples",
}


def test_brief_returns_all_keys(brief_db):
    brief = build_concept_brief(brief_db, "concept-slub")
    assert set(brief.keys()) == EXPECTED_KEYS


def test_brief_concept_fields(brief_db):
    brief = build_concept_brief(brief_db, "concept-slub")
    assert brief["concept"]["name"] == "SLUB Allocator"
    assert brief["concept"]["description"] == "Slab allocator for kernel objects."
    assert brief["concept"]["key_properties"] == ["cache-friendly", "per-cpu"]
    assert brief["concept"]["tradeoffs"] == ["memory overhead vs speed"]
    assert brief["concept"]["design_rationale"] == "Replaces SLAB for better performance."


def test_brief_subsystem(brief_db):
    brief = build_concept_brief(brief_db, "concept-slub")
    assert brief["subsystem"] is not None
    assert brief["subsystem"]["name"] == "Memory Management"


def test_brief_scores_all_five(brief_db):
    brief = build_concept_brief(brief_db, "concept-slub")
    for key in ("heat", "pain", "impact", "leverage", "frontier"):
        assert key in brief["scores"]
        assert isinstance(brief["scores"][key], (int, float))


# --- Evidence tests (INV-KK-GRAPH-BRIEF-VERBATIM) ---

def test_brief_problems(brief_db):
    brief = build_concept_brief(brief_db, "concept-slub")
    assert len(brief["problems"]) == 1
    assert brief["problems"][0]["title"] == "UAF in SLUB"
    assert brief["problems"][0]["description"] == "Use-after-free in slab cache."
    assert brief["problems"][0]["severity"] == "critical"


def test_brief_problems_sorted_by_severity(brief_db):
    """Add a second problem with lower severity and check ordering."""
    add_node(brief_db, "prob-low", "Problem", {
        "title": "Minor SLUB leak",
        "description": "Small memory leak.",
        "severity": "low",
        "status": "open",
        "source_date": "2024-05-01",
        "artifact_class": "B",
    })
    add_edge(brief_db, "identifies-problem", "prob-low", "concept-slub")
    brief_db.commit()

    brief = build_concept_brief(brief_db, "concept-slub")
    assert len(brief["problems"]) >= 2
    severities = [p["severity"] for p in brief["problems"]]
    assert severities.index("critical") < severities.index("low")


def test_brief_vulnerabilities(brief_db):
    brief = build_concept_brief(brief_db, "concept-slub")
    assert len(brief["vulnerabilities"]) == 1
    assert brief["vulnerabilities"][0]["cve_id"] == "CVE-TEST-001"
    assert brief["vulnerabilities"][0]["description"] == "Heap overflow in SLUB cache reclaim path."


def test_brief_failure_modes(brief_db):
    brief = build_concept_brief(brief_db, "concept-slub")
    assert len(brief["failure_modes"]) >= 1
    symptoms = [fm["symptom"] for fm in brief["failure_modes"]]
    assert "memory corruption" in symptoms


def test_brief_invariants(brief_db):
    brief = build_concept_brief(brief_db, "concept-slub")
    assert len(brief["invariants"]) >= 1
    predicates = [inv["predicate"] for inv in brief["invariants"]]
    assert "slab objects must be freed exactly once" in predicates


def test_brief_protocols_with_participants(brief_db):
    brief = build_concept_brief(brief_db, "concept-slub")
    assert len(brief["protocols"]) >= 1
    proto = brief["protocols"][0]
    assert proto["rule"] == "SLUB must request pages via page allocator API"
    participant_names = [p["name"] for p in proto["participant_concepts"]]
    assert "Page Cache" in participant_names


def test_brief_profiles(brief_db):
    brief = build_concept_brief(brief_db, "concept-slub")
    assert len(brief["profiles"]) >= 1
    assert brief["profiles"][0]["metric"] == "allocation latency"
    assert brief["profiles"][0]["complexity"] == "O(1) amortized"


def test_brief_prerequisites_depends_on(brief_db):
    brief = build_concept_brief(brief_db, "concept-slub")
    names = [p["name"] for p in brief["prerequisites"]["depends_on"]]
    assert "Page Cache" in names


def test_brief_prerequisites_depended_on_by(brief_db):
    brief = build_concept_brief(brief_db, "concept-slub")
    names = [p["name"] for p in brief["prerequisites"]["depended_on_by"]]
    assert "Buddy Allocator" in names


def test_brief_fixes_with_resolves(brief_db):
    brief = build_concept_brief(brief_db, "concept-slub")
    assert len(brief["fixes"]) == 1
    fix = brief["fixes"][0]
    assert fix["title"] == "fix UAF in SLUB reclaim"
    assert fix["commit_hash"] == "abc123def"
    assert len(fix["resolves"]) >= 1
    resolved_ids = [r["id"] for r in fix["resolves"]]
    assert "prob-uaf" in resolved_ids


def test_brief_discussions(brief_db):
    brief = build_concept_brief(brief_db, "concept-slub")
    assert len(brief["discussions"]) == 1
    assert brief["discussions"][0]["title"] == "SLUB allocator rework discussion"
    assert brief["discussions"][0]["forum"] == "LKML"


def test_brief_observations(brief_db):
    brief = build_concept_brief(brief_db, "concept-slub")
    assert len(brief["observations"]) == 1
    assert brief["observations"][0]["claim"] == "SLUB shows 30% fewer cache misses than SLAB"


def test_brief_benchmarks(brief_db):
    brief = build_concept_brief(brief_db, "concept-slub")
    assert len(brief["benchmarks"]) == 1
    assert brief["benchmarks"][0]["result_summary"] == "1.2M allocs/sec on 8-core"
    assert brief["benchmarks"][0]["metric"] == "allocation throughput"


def test_brief_timeline_sorted_desc(brief_db):
    brief = build_concept_brief(brief_db, "concept-slub")
    assert len(brief["timeline"]) > 0
    dates = [t["source_date"] for t in brief["timeline"] if t["source_date"]]
    for i in range(len(dates) - 1):
        assert dates[i] >= dates[i + 1], f"Timeline not descending: {dates[i]} < {dates[i+1]}"


def test_brief_code_examples(brief_db):
    brief = build_concept_brief(brief_db, "concept-slub")
    assert len(brief["code_examples"]) == 1
    assert brief["code_examples"][0]["language"] == "c"
    assert "kmalloc" in brief["code_examples"][0]["code"]


# --- INV-KK-GRAPH-BRIEF-EMPTY-SAFE tests ---

def test_brief_empty_concept(empty_concept_db):
    brief = build_concept_brief(empty_concept_db, "concept-empty")
    assert set(brief.keys()) == EXPECTED_KEYS
    assert brief["concept"]["name"] == "Empty Concept"
    assert brief["subsystem"] is None
    assert brief["problems"] == []
    assert brief["vulnerabilities"] == []
    assert brief["failure_modes"] == []
    assert brief["invariants"] == []
    assert brief["protocols"] == []
    assert brief["profiles"] == []
    assert brief["prerequisites"] == {"depends_on": [], "depended_on_by": []}
    assert brief["fixes"] == []
    assert brief["observations"] == []
    assert brief["discussions"] == []
    assert brief["benchmarks"] == []
    assert brief["timeline"] == []
    assert brief["code_examples"] == []
    for key in ("heat", "pain", "impact", "leverage", "frontier"):
        assert brief["scores"][key] == 0.0


def test_brief_nonexistent_concept(brief_db):
    """A concept ID that doesn't exist should return empty brief."""
    brief = build_concept_brief(brief_db, "concept-nonexistent")
    assert set(brief.keys()) == EXPECTED_KEYS
    assert brief["concept"]["name"] == ""
    assert brief["subsystem"] is None
