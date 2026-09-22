"""SQLite schema definition and migrations for the concept store."""

from __future__ import annotations

import sqlite3
from pathlib import Path

NODE_KINDS = ("Concept", "Source", "Evidence", "Advisory", "Subsystem", "KernelInvariant", "FailureMode", "InteractionProtocol", "PerformanceProfile", "CompatibilityAssessment", "OptimizationGoal", "UseCaseScenario", "ComparativeAnalysis", "Kernel", "Problem", "Observation", "Discussion", "Benchmark", "Rejection", "Vulnerability", "Fix", "Proposal", "Trend", "Opportunity", "HumanReview", "Reviewer", "Venue", "PaperSummary", "PaperCompleteness")

EDGE_KINDS = (
    "belongs-to",
    "extracted-from",
    "sourced-from",
    # IFC-KK-CONCEPT-SEMINAL-MARKER, per D-12. Absent from this list until
    # 2026-09-22, which is why zero defined-by edges existed: the seminal
    # marker was not merely unused, add_edge refused it as an unknown kind, so
    # INV-KK-CONCEPT-ADMISSION's only escape hatch could never be exercised.
    "defined-by",
    # IFC-KK-PAPER-KERNEL. Which kernel a PAPER is about — the signal the graph
    # could not carry until 2026-09-22. Kernel appeared in exactly ONE entry of
    # EDGE_VALID_PAIRS before this, implemented-in = (Concept, Kernel). The near
    # miss is worth naming: governed-by, triggered-by and belongs-to all involve
    # KernelInvariant, a DIFFERENT kind that merely shares a prefix.
    "about-kernel",
    "alternative-to",
    "refines",
    "contradicts",
    "prerequisite",
    "supersedes",
    "assessed-by",
    "governed-by",
    "triggered-by",
    "constrains-composition",
    "profiled-by",
    "assesses-compatibility",
    "contributes-to",
    "suited-for",
    "compares",
    "implemented-in",
    "identifies-problem",
    "observes",
    "discusses",
    "benchmarks",
    "rejected-for",
    "grounded-in",
    "exploits",
    "affects-subsystem",
    "fixes",
    "patches",
    "addresses",
    "contradicted-by",
    "resulted-in",
    "motivated-by",
    "trend-about",
    "opportunity-for",
    "supported-by",
    "reviewed-by",
    "published-at",
    # IFC-KK-PAPER-SUMMARY: links a PaperSummary to the paper it summarises.
    "summarizes-paper",
    # IFC-KK-PAPER-COMPLETENESS: links a verdict to the paper it describes.
    "completeness-of",
)

EDGE_VALID_PAIRS: dict[str, tuple[str, str] | list[tuple[str, str]]] = {
    "belongs-to": [("Concept", "Subsystem"), ("KernelInvariant", "Subsystem")],
    "extracted-from": [("Concept", "Evidence"), ("KernelInvariant", "Evidence"), ("FailureMode", "Evidence"), ("InteractionProtocol", "Evidence"), ("PerformanceProfile", "Evidence"), ("CompatibilityAssessment", "Evidence"), ("ComparativeAnalysis", "Evidence"), ("Problem", "Evidence"), ("Observation", "Evidence"), ("Discussion", "Evidence"), ("Benchmark", "Evidence"), ("Rejection", "Evidence"), ("Proposal", "Evidence")],
    "sourced-from": ("Evidence", "Source"),
    "defined-by": ("Concept", "Source"),
    # On the Source and not the Evidence, per operator decision 2026-09-22:
    # Source is what a reader filters by and is the STABLE layer. Evidence is
    # re-derived — --all-relink selected 1,538 of them on 2026-09-21 — so an
    # association hanging there would be rebuilt or orphaned on every run while
    # the paper it describes had not changed. Cardinality is deliberately not
    # capped at one: the extractor answers with a single name and so writes at
    # most one, but a comparison paper genuinely concerns two kernels and a
    # human should be able to say so without a schema change.
    "about-kernel": ("Source", "Kernel"),
    # INV-KK-VENUE-SOURCE-EDGE: a Source is linked to its Venue by this edge, and
    # to at most one. The raw Source.attrs.venue string is retained as provenance
    # but is no longer what the viewer groups on.
    "published-at": ("Source", "Venue"),
    # IFC-KK-PAPER-SUMMARY: the only edge from a summary to the paper it describes.
    # It absorbed the summarizes-for edge under D-9, which pointed the retired brief
    # kind at a Concept; 935 of those 937 edges were derivable from the
    # Source <-Evidence <-Concept chain, so dropping them cost no connectivity.
    "summarizes-paper": ("PaperSummary", "Source"),
    "completeness-of": ("PaperCompleteness", "Source"),
    "alternative-to": ("Concept", "Concept"),
    "refines": ("Concept", "Concept"),
    "contradicts": ("Concept", "Concept"),
    "prerequisite": ("Concept", "Concept"),
    "supersedes": ("Concept", "Concept"),
    "assessed-by": ("Source", "Advisory"),
    "governed-by": ("KernelInvariant", "Concept"),
    "triggered-by": ("FailureMode", "KernelInvariant"),
    "constrains-composition": ("InteractionProtocol", "Concept"),
    "profiled-by": ("PerformanceProfile", "Concept"),
    "assesses-compatibility": ("CompatibilityAssessment", "Concept"),
    "contributes-to": ("Concept", "OptimizationGoal"),
    "suited-for": ("Concept", "UseCaseScenario"),
    "compares": ("ComparativeAnalysis", "Concept"),
    "implemented-in": ("Concept", "Kernel"),
    "identifies-problem": ("Problem", "Concept"),
    "observes": ("Observation", "Concept"),
    "discusses": ("Discussion", "Concept"),
    "benchmarks": ("Benchmark", "Concept"),
    "rejected-for": ("Rejection", "Concept"),
    "grounded-in": ("Proposal", "Concept"),
    "exploits": ("Vulnerability", "Concept"),
    "affects-subsystem": ("Vulnerability", "Subsystem"),
    "fixes": [("Fix", "Problem"), ("Fix", "Vulnerability")],
    "patches": ("Fix", "Concept"),
    "addresses": ("Proposal", "Problem"),
    "contradicted-by": ("Observation", "Observation"),
    "resulted-in": [("Discussion", "Proposal"), ("Discussion", "Rejection")],
    "motivated-by": ("Benchmark", "Problem"),
    "trend-about": ("Trend", "Concept"),
    "opportunity-for": ("Opportunity", "Concept"),
    "supported-by": [("Opportunity", "Problem"), ("Opportunity", "Observation"), ("Opportunity", "Discussion"), ("Opportunity", "Benchmark")],
    "reviewed-by": ("Source", "HumanReview"),
}

REQUIRED_ATTRS: dict[str, tuple[str, ...]] = {
    "Concept": ("name", "description", "artifact_class", "key_properties", "tradeoffs", "design_rationale"),
    "Source": ("url", "source_type", "license"),
    "Evidence": ("artifact_class", "contamination_level"),
    "Advisory": ("assessment", "contamination_confirmed"),
    "Subsystem": ("name",),
    "KernelInvariant": ("predicate", "strength", "scope", "artifact_class"),
    "FailureMode": ("symptom", "blast_radius", "recoverability", "artifact_class"),
    "InteractionProtocol": ("rule", "ordering", "violation_mode", "artifact_class"),
    "PerformanceProfile": ("metric", "complexity", "best_case", "worst_case", "typical_case", "conditions", "artifact_class"),
    "CompatibilityAssessment": ("synergy", "rationale", "conditions", "artifact_class"),
    "OptimizationGoal": ("name", "description", "metric", "direction"),
    "UseCaseScenario": ("name", "description", "workload_type", "constraints"),
    "ComparativeAnalysis": ("dimension", "winner", "conditions", "quantitative_delta", "artifact_class"),
    "Kernel": ("name", "description", "kernel_type"),
    "Problem": ("title", "description", "severity", "status", "source_date", "artifact_class"),
    "Observation": ("claim", "confidence", "source_date", "artifact_class"),
    "Discussion": ("title", "forum", "participant_count", "source_date", "artifact_class"),
    "Benchmark": ("metric", "result_summary", "conditions", "source_date", "artifact_class"),
    "Rejection": ("proposal_title", "reason", "rejector", "source_date", "artifact_class"),
    "Vulnerability": ("cve_id", "title", "description", "severity", "cvss_score", "affected_versions", "status", "source_date", "artifact_class"),
    "Fix": ("title", "commit_hash", "fix_type", "source_date", "artifact_class"),
    "Proposal": ("name", "description", "status", "source_date", "artifact_class"),
    "Trend": ("title", "description", "strength", "window_start", "window_end", "artifact_class"),
    "Opportunity": ("title", "description", "confidence", "frontier_score", "artifact_class"),
    "HumanReview": ("reviewer", "score", "verdict", "rationale", "review_date", "artifact_class"),
    "Reviewer": ("name",),
    "Venue": ("name", "venue_type"),
    # text may be empty (states absent and rejected carry no usable text), but the
    # key must be present so a reader never has to distinguish missing from empty.
    # model, set_at and reviewed_by are optional: see IFC-KK-PAPER-SUMMARY.
    # key_ideas, relevance and methodology were absorbed here from the retired
    # brief kind under D-9 and removed again under D-15a. A PaperSummary is prose
    # plus its provenance; nothing else is stored on it.
    "PaperSummary": ("text", "state"),
    # Every dimension is required: a verdict missing one is not a partial
    # verdict, it is an unreadable one, and INV-KK-COMPLETENESS-ADVISORY makes
    # the verdict useless for anything except being read.
    "PaperCompleteness": (
        "computed_at", "has_abstract", "has_summary", "summary_state",
        "links_concept", "links_subsystem", "links_kernel", "links_invariant",
    ),
}

DATE_ATTRS = frozenset({"source_date", "window_start", "window_end", "review_date"})

ID_PREFIXES = {
    "Concept": "concept-",
    "Source": "src-",
    "Evidence": "ev-",
    "Advisory": "adv-",
    "Subsystem": "sub-",
    "KernelInvariant": "kinv-",
    "FailureMode": "fm-",
    "InteractionProtocol": "ip-",
    "PerformanceProfile": "pp-",
    "CompatibilityAssessment": "ca-",
    "OptimizationGoal": "goal-",
    "UseCaseScenario": "scenario-",
    "ComparativeAnalysis": "cmpan-",
    "Kernel": "kernel-",
    "Problem": "prob-",
    "Observation": "obs-",
    "Discussion": "disc-",
    "Benchmark": "bench-",
    "Rejection": "rej-",
    "Vulnerability": "vuln-",
    "Fix": "fix-",
    "Proposal": "prop-",
    "Trend": "trend-",
    "Opportunity": "opp-",
    "HumanReview": "hrev-",
    "Reviewer": "rvr-",
    "Venue": "venue-",
    "PaperSummary": "psum-",
    "PaperCompleteness": "pcomp-",
}

# INV-KK-SCHEMA-KIND-DECLARATION-HONOURED: kind is deliberately NOT constrained by a
# SQLite CHECK. It used to be, and the constraint is still absent from data/master.db,
# which was rebuilt at some point without it (the quoted table name in its
# sqlite_master entry is the tell). Because every statement here is
# CREATE TABLE IF NOT EXISTS, neither init_db nor the web app's lifespan can ever
# repair an existing table, so the CHECK only ever applied to freshly created
# databases. The result was that test fixtures and production disagreed about which
# kinds are legal. Enforcement therefore lives in Python, in engine.add_node, which
# validates against NODE_KINDS the same way add_edge already validates against
# EDGE_VALID_PAIRS. One rule, applied identically to every database.
SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    attrs TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES nodes(id),
    target_id TEXT NOT NULL REFERENCES nodes(id),
    attrs TEXT NOT NULL DEFAULT '{}',
    UNIQUE (kind, source_id, target_id)
);

-- IFC-KK-CONCEPT-CANDIDATE: names the extractor proposed that the curated
-- vocabulary did not contain. NOT a node kind, deliberately — admitting a
-- rejected candidate as a node would put the very thing
-- INV-KK-CONCEPT-ADMISSION excludes into the graph under another label. One
-- row per (name, Evidence) pair so distinct-Source weight can be counted
-- before the Concept exists rather than after.
CREATE TABLE IF NOT EXISTS concept_candidates (
    normalised  TEXT NOT NULL,
    name        TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    proposed_at TEXT NOT NULL,
    PRIMARY KEY (normalised, evidence_id)
);

CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_kind ON edges(kind);
CREATE INDEX IF NOT EXISTS idx_nodes_kind ON nodes(kind);
"""


def init_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA_SQL)
    return conn
