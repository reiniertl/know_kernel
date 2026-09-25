"""Admissibility rules — enforced on every mutation."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field


@dataclass
class Violation:
    node_id: str
    rule: str
    message: str


def check_concept_has_belongs_to(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'belongs-to' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "concept-belongs-to", "Concept must belong to at least one Subsystem")
    return None


def check_concept_has_provenance(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'extracted-from' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "concept-provenance", "Concept must have at least one extracted-from edge")
    return None


def check_evidence_has_source(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    count = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind = 'sourced-from' AND source_id = ?",
        (node_id,),
    ).fetchone()[0]
    if count != 1:
        return Violation(
            node_id, "evidence-exactly-one-source",
            f"Evidence must have exactly one sourced-from edge, found {count}",
        )
    return None


def check_source_has_advisory(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'assessed-by' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "source-advisory", "Source must have an Advisory")
    return None


def check_venue_name_unique(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    """INV-KK-VENUE-NAME-UNIQUE: one canonical name, one Venue node.

    Without this a venue renders as two rows in the viewer and a merge has no
    single target to merge into.
    """
    row = conn.execute(
        "SELECT json_extract(attrs, '$.name') FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()
    name = row[0] if row else None
    if not name:
        return Violation(node_id, "venue-name", "Venue must have a name")
    clash = conn.execute(
        "SELECT id FROM nodes WHERE kind = 'Venue' AND id != ? "
        "AND json_extract(attrs, '$.name') = ? LIMIT 1",
        (node_id, name),
    ).fetchone()
    if clash is not None:
        return Violation(
            node_id, "venue-name-unique", f"Venue name '{name}' is already used by {clash[0]}"
        )
    return None


def check_summary_state_valid(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    """INV-KK-SUMMARY-STATE-VOCABULARY: the state vocabulary is closed.

    The completeness verdict reads the state rather than the text, so a state
    outside the vocabulary is not a cosmetic problem: it makes the verdict
    unanswerable. Imported lazily to keep graph.rules free of an ingest import.
    """
    from ingest.paper_summary import SUMMARY_STATES

    row = conn.execute(
        "SELECT json_extract(attrs, '$.state') FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()
    state = row[0] if row else None
    if not state:
        return Violation(node_id, "summary-state", "PaperSummary must have a state")
    if state not in SUMMARY_STATES:
        return Violation(
            node_id,
            "summary-state-vocabulary",
            f"PaperSummary state '{state}' is not one of: " + ", ".join(SUMMARY_STATES),
        )
    return None


def check_completeness_dimensions_binary(
    conn: sqlite3.Connection, node_id: str
) -> Violation | None:
    """IFC-KK-PAPER-COMPLETENESS, decision D-A: presence, never counts.

    Every dimension is a bare boolean. A count or a score here would be a
    different feature wearing the same node kind, and the first thing anyone
    would do with a number is compare it against a threshold — which is exactly
    what D-A ruled out and INV-KK-COMPLETENESS-ADVISORY forbids acting on.
    """
    from ingest.paper_completeness import BINARY_DIMENSIONS

    row = conn.execute("SELECT attrs FROM nodes WHERE id = ?", (node_id,)).fetchone()
    if row is None:
        return None
    attrs = json.loads(row[0]) if isinstance(row[0], str) else (row[0] or {})
    for dim in BINARY_DIMENSIONS:
        if dim not in attrs:
            return Violation(
                node_id, "completeness-dimension-missing", f"Verdict is missing '{dim}'"
            )
        if not isinstance(attrs[dim], bool):
            return Violation(
                node_id,
                "completeness-dimension-not-binary",
                f"Dimension '{dim}' must be a bool, got {type(attrs[dim]).__name__}",
            )
    return None


def check_kinv_belongs_to_subsystem(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'belongs-to' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "kinv-belongs-to-subsystem", "KernelInvariant must belong-to at least one Subsystem")
    return None


def check_kinv_governed_by_concept(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'governed-by' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "kinv-governed-by", "KernelInvariant must be governed-by at least one Concept")
    return None


def check_failure_mode_trigger(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'triggered-by' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "fm-triggered-by", "FailureMode must be triggered-by at least one KernelInvariant")
    return None


def check_failure_mode_provenance(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'extracted-from' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "fm-provenance", "FailureMode must be extracted-from at least one Evidence")
    return None


def check_protocol_concept_pairs(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    count = conn.execute(
        "SELECT COUNT(DISTINCT target_id) FROM edges WHERE kind = 'constrains-composition' AND source_id = ?",
        (node_id,),
    ).fetchone()[0]
    if count < 2:
        return Violation(
            node_id, "ip-constrains-pair",
            f"InteractionProtocol must constrains-composition at least 2 distinct Concepts, found {count}",
        )
    return None


def check_protocol_provenance(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'extracted-from' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "ip-provenance", "InteractionProtocol must be extracted-from at least one Evidence")
    return None


def check_profile_concept(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    count = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind = 'profiled-by' AND source_id = ?",
        (node_id,),
    ).fetchone()[0]
    if count != 1:
        return Violation(
            node_id, "pp-profiled-by",
            f"PerformanceProfile must have exactly 1 profiled-by edge, found {count}",
        )
    return None


def check_profile_provenance(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'extracted-from' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "pp-provenance", "PerformanceProfile must be extracted-from at least one Evidence")
    return None


def check_compat_concept_pairs(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    count = conn.execute(
        "SELECT COUNT(DISTINCT target_id) FROM edges WHERE kind = 'assesses-compatibility' AND source_id = ?",
        (node_id,),
    ).fetchone()[0]
    if count < 2:
        return Violation(
            node_id, "ca-assesses-pair",
            f"CompatibilityAssessment must assesses-compatibility at least 2 distinct Concepts, found {count}",
        )
    return None


def check_compat_provenance(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'extracted-from' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "ca-provenance", "CompatibilityAssessment must be extracted-from at least one Evidence")
    return None


def check_comparative_concept_pairs(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    count = conn.execute(
        "SELECT COUNT(DISTINCT target_id) FROM edges WHERE kind = 'compares' AND source_id = ?",
        (node_id,),
    ).fetchone()[0]
    if count != 2:
        return Violation(
            node_id, "comparative-exactly-two",
            f"ComparativeAnalysis must compare exactly 2 distinct Concepts, found {count}",
        )
    return None


def check_subsystem_has_children(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'belongs-to' AND target_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "subsystem-has-children", "Subsystem must have at least one belongs-to incoming edge")
    return None


def check_advisory_has_assessor(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'assessed-by' AND target_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "advisory-has-assessor", "Advisory must have at least one assessed-by incoming edge")
    return None


def check_problem_has_concept(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'identifies-problem' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "problem-identifies-concept", "Problem must identifies-problem at least one Concept")
    return None


def check_observation_has_concept(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'observes' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "observation-observes-concept", "Observation must observes at least one Concept")
    return None


def check_discussion_has_concept(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'discusses' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "discussion-discusses-concept", "Discussion must discusses at least one Concept")
    return None


def check_benchmark_has_concept(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'benchmarks' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "benchmark-benchmarks-concept", "Benchmark must benchmarks at least one Concept")
    return None


def check_proposal_has_concept(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'grounded-in' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "proposal-grounded-in-concept", "Proposal must be grounded-in at least one Concept")
    return None


def check_vulnerability_has_concept(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'exploits' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "vulnerability-exploits-concept", "Vulnerability must exploits at least one Concept")
    return None


RULES_BY_KIND = {
    "Concept": [check_concept_has_belongs_to, check_concept_has_provenance],
    "Evidence": [check_evidence_has_source],
    "Source": [check_source_has_advisory],
    "KernelInvariant": [check_kinv_belongs_to_subsystem, check_kinv_governed_by_concept],
    "FailureMode": [check_failure_mode_trigger, check_failure_mode_provenance],
    "InteractionProtocol": [check_protocol_concept_pairs, check_protocol_provenance],
    "PerformanceProfile": [check_profile_concept, check_profile_provenance],
    "CompatibilityAssessment": [check_compat_concept_pairs, check_compat_provenance],
    "ComparativeAnalysis": [check_comparative_concept_pairs],
    "Subsystem": [check_subsystem_has_children],
    "Advisory": [check_advisory_has_assessor],
    "OptimizationGoal": [],
    "UseCaseScenario": [],
    "Kernel": [],
    "Problem": [check_problem_has_concept],
    "Observation": [check_observation_has_concept],
    "Discussion": [check_discussion_has_concept],
    "Benchmark": [check_benchmark_has_concept],
    "Rejection": [],
    "Vulnerability": [check_vulnerability_has_concept],
    "Fix": [],
    "Proposal": [check_proposal_has_concept],
    "Trend": [],
    "Opportunity": [],
    "Reviewer": [],
    # INV-KK-SCHEMA-KIND-DECLARATION-HONOURED: every kind in NODE_KINDS must appear
    # here. HumanReview was added to NODE_KINDS without a rule entry, which left it
    # silently unvalidated. Empty is deliberate, matching the other kinds above that
    # carry no structural requirement of their own: a HumanReview is a leaf record
    # whose reviewed-by edge is enforced by EDGE_VALID_PAIRS at insert time.
    "HumanReview": [],
    "Venue": [check_venue_name_unique],
    "PaperSummary": [check_summary_state_valid],
    "PaperCompleteness": [check_completeness_dimensions_binary],
}


def validate_node(conn: sqlite3.Connection, node_id: str, kind: str) -> list[Violation]:
    checks = RULES_BY_KIND.get(kind, [])
    violations = []
    for check in checks:
        v = check(conn, node_id)
        if v is not None:
            violations.append(v)
    return violations


# ---------------------------------------------------------------------------
# INV-KK-EXTRACT-EVIDENCE-RECORDED — a sweep over provenance edges.
#
# This is deliberately NOT wired into RULES_BY_KIND. Those rules are per-node
# and are run by validate_node on every write; this property is per-EDGE, and
# attaching it to a node kind would both re-check the same edges once per
# endpoint and make all 2,022 legacy Concepts invalid, which would break
# unrelated writes to make a new invariant look satisfied. The invariant is
# scoped by date precisely so the legacy edges are out of scope, not so they
# can be hidden.
#
# THE BLIND SPOT, STATED RATHER THAN PAPERED OVER. The edges table has no
# creation timestamp, so an edge's date is knowable only from the checked_at
# this invariant asks it to carry. A bare edge written today is therefore
# indistinguishable from a bare edge written in August. The sweep reports it as
# UNDATED rather than guessing: undated edges are counted and returned
# separately, and that count is the measure of how much of the graph predates
# the rule. It should fall to zero when the corpus is re-derived.
# ---------------------------------------------------------------------------

#: The exact attribute set an in-scope provenance edge must carry.
EVIDENCE_ATTR_KEYS = (
    "grounded", "ungrounded_count", "ungrounded",
    "basis", "basis_sha256", "model", "checked_at",
)

#: Edges checked on or after this date are in scope. Earlier ones were written
#: by src/ingest/semantic_link.py from a title regex and carry no verdict.
EVIDENCE_RECORDED_FROM = "2026-09-21"

VALID_EVIDENCE_BASES = ("evidence-text", "none")

#: INV-KK-LINK-CONFIRMATION-STATE. The only keys permitted ALONGSIDE the
#: required set. Without this the "exactly these keys" rule below would make a
#: reviewed edge a violation the moment a person confirmed it. They stay
#: optional: their absence is what "nobody has looked at this" means.
CONFIRMATION_ATTR_KEYS = (
    "confirmation", "confirmed_by", "confirmed_at", "confirmation_note",
)

VALID_CONFIRMATIONS = ("confirmed", "rejected")


#: Marker carried by the 2,022 links that predate the evidence rule. It is
#: deliberately NOT in VALID_EVIDENCE_BASES: an edge that is IN SCOPE and claims
#: this basis must still be a violation, because the point is to retire the
#: mechanism, not to legitimise it.
LEGACY_UNVERIFIED_BASIS = "unverified-legacy"

#: The other three markers, added 2026-09-21 for the 1,147 edges the legacy
#: pass did not touch. One basis would have described them the way one basis
#: described the 2,022, and it would have been a worse description: those came
#: from a single known-bad mechanism, these come from at least three origins
#: and one of them is a LIVE, SANCTIONED writer. See ANN-KK-UNLINKED-PROVENANCE-
#: CENSUS and INV-KK-CLAIM-EXTRACT-EVIDENCE-BARE.
#:
#: Like LEGACY_UNVERIFIED_BASIS, none of these is in VALID_EVIDENCE_BASES: an
#: edge that is IN SCOPE and claims one is still a violation.
CLAIM_EXTRACT_UNVERIFIED_BASIS = "claim-extract-unverified"
EXTRACTOR_PREVERDICT_BASIS = "extractor-preverdict"
MECHANISM_UNATTRIBUTED_BASIS = "mechanism-unattributed"

#: Every marker that means "out of scope, and here is what is known about why".
OUT_OF_SCOPE_BASES = (
    LEGACY_UNVERIFIED_BASIS,
    CLAIM_EXTRACT_UNVERIFIED_BASIS,
    EXTRACTOR_PREVERDICT_BASIS,
    MECHANISM_UNATTRIBUTED_BASIS,
)


@dataclass
class EvidenceSweep:
    """Outcome of check_link_evidence_recorded.

    undated and the marked counts are all out of scope, and the split is the
    whole point: a marked edge is known to predate the rule and says what is
    known about its origin, while an undated one is simply unaccounted for.
    Re-derivation should drive both to zero; only the second is a surprise.

    legacy_marked is kept as its own field rather than folded into
    marked_by_basis because it is the one population whose mechanism is known
    to be WRONG rather than merely unrecorded, and callers written before the
    other three markers existed still read it.
    """
    conforming: int
    undated: int
    violations: list[Violation]
    legacy_marked: int = 0
    marked_by_basis: dict[str, int] = field(default_factory=dict)

    @property
    def marked(self) -> int:
        """Every out-of-scope edge that carries a marker, legacy included."""
        return sum(self.marked_by_basis.values())


def check_link_evidence_recorded(
    conn: sqlite3.Connection, since: str = EVIDENCE_RECORDED_FROM
) -> EvidenceSweep:
    """Sweep every extracted-from edge for its recorded grounding verdict.

    An edge is IN SCOPE if it carries a checked_at of `since` or later. In-scope
    edges must carry exactly EVIDENCE_ATTR_KEYS, a known basis, a fingerprint
    present iff the basis is not 'none', and a grounded flag that agrees with
    ungrounded_count. Edges with no checked_at are counted as undated and are
    not violations — see the note above on why they cannot be dated.
    """
    rows = conn.execute(
        "SELECT source_id, target_id, attrs FROM edges WHERE kind = 'extracted-from'"
    ).fetchall()

    conforming = 0
    undated = 0
    legacy_marked = 0
    marked_by_basis: dict[str, int] = {}
    violations: list[Violation] = []

    for source_id, target_id, raw in rows:
        try:
            attrs = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except json.JSONDecodeError:
            violations.append(Violation(
                source_id, "INV-KK-EXTRACT-EVIDENCE-RECORDED",
                f"extracted-from edge to '{target_id}' has unparseable attrs"))
            continue

        checked_at = attrs.get("checked_at")
        if not checked_at:
            # An edge with no date cannot be placed in or out of scope, because
            # the edges table records no creation time. A marked legacy edge at
            # least says why it has none.
            basis = attrs.get("basis")
            if basis in OUT_OF_SCOPE_BASES:
                marked_by_basis[basis] = marked_by_basis.get(basis, 0) + 1
                if basis == LEGACY_UNVERIFIED_BASIS:
                    legacy_marked += 1
            else:
                undated += 1
            continue
        if checked_at < since:
            continue

        def bad(msg: str) -> None:
            violations.append(Violation(
                source_id, "INV-KK-EXTRACT-EVIDENCE-RECORDED",
                f"extracted-from edge to '{target_id}': {msg}"))

        missing = [k for k in EVIDENCE_ATTR_KEYS if k not in attrs]
        if missing:
            bad(f"missing {', '.join(missing)}")
            continue
        extra = [k for k in attrs
                 if k not in EVIDENCE_ATTR_KEYS and k not in CONFIRMATION_ATTR_KEYS]
        if extra:
            bad(f"unexpected attrs {', '.join(sorted(extra))}")
            continue
        if attrs["basis"] not in VALID_EVIDENCE_BASES:
            bad(f"basis '{attrs['basis']}' is not one of {VALID_EVIDENCE_BASES}")
            continue
        has_fp = bool(attrs["basis_sha256"])
        if has_fp != (attrs["basis"] != "none"):
            bad("basis_sha256 must be present iff basis is not 'none'")
            continue
        expected = attrs["basis"] != "none" and attrs["ungrounded_count"] == 0
        if bool(attrs["grounded"]) != expected:
            bad(f"grounded={attrs['grounded']} disagrees with "
                f"basis={attrs['basis']} ungrounded_count={attrs['ungrounded_count']}")
            continue
        if len(attrs["ungrounded"]) > attrs["ungrounded_count"]:
            bad("stored phrases outnumber ungrounded_count")
            continue
        conforming += 1

    return EvidenceSweep(conforming=conforming, undated=undated,
                         violations=violations, legacy_marked=legacy_marked,
                         marked_by_basis=marked_by_basis)


#: INV-KK-CONCEPT-ADMISSION scopes itself to concepts admitted after this date.
#: The 33 below the line are grandfathered per D-12.
CONCEPT_ADMISSION_FROM = "2026-09-16"

#: A Concept is admissible at this many DISTINCT Sources, or with a seminal
#: marker. Distinct Sources, not distinct Evidence: two Evidence nodes from one
#: paper are one paper.
ADMISSIBLE_WEIGHT = 2


@dataclass
class AdmissionSweep:
    """Outcome of check_concept_admission.

    thin and unlinked are reported SEPARATELY from violations, and the split is
    the finding. Weight is a proxy for "established class" and it misfires on a
    thin corpus: BBR Congestion Control, Dentry Cache, Devicetree, KSM, Vmalloc
    and Zswap all sat at weight 1 on 2026-09-22 because this corpus holds one
    paper about each, not because a single paper invented them. Calling those
    violations would be measuring corpus coverage and reporting it as concept
    quality.
    """
    admissible: int
    thin: list[str]
    unlinked: list[str]
    seminal: int
    violations: list[Violation]
    #: Concepts admitted by the fourth route, 2026-09-25 — provenance in
    #: canonical documentation. Counted INSIDE admissible, and listed here as
    #: well so the harvest's contribution is attributable rather than merged
    #: into a number that was already 69.
    documented: list[str] = field(default_factory=list)
    #: Retired Concepts, which are admissible under no route. Reported apart
    #: from every other bucket: a retirement is a human judgement about the
    #: concept, not a fact about the corpus like thin, and not a gap like
    #: unlinked.
    retired: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (self.admissible + len(self.thin) + len(self.unlinked)
                + len(self.retired))


def concept_weight(conn: sqlite3.Connection, concept_id: str) -> int:
    """Distinct Sources reachable concept -extracted-from-> Evidence
    -sourced-from-> Source. This is the weight INV-KK-CONCEPT-ADMISSION means.
    """
    row = conn.execute(
        "SELECT COUNT(DISTINCT s.target_id) FROM edges e "
        "JOIN edges s ON s.source_id = e.target_id AND s.kind = 'sourced-from' "
        "WHERE e.kind = 'extracted-from' AND e.source_id = ?", (concept_id,)
    ).fetchone()
    return row[0] if row else 0


def seminal_concepts(conn: sqlite3.Connection) -> set[str]:
    """Every Concept carrying a defined-by marker, in one query.

    Read once per sweep or per page render, never once per row: the concept
    browser paginates and INV-KK-WEB-QUERY-BOUNDED caps enrichment at the page
    size, so a per-row membership query would be the thing it forbids.
    """
    return {
        r[0] for r in conn.execute(
            "SELECT DISTINCT source_id FROM edges WHERE kind = 'defined-by'")
    }


#: A Concept implemented in this many DISTINCT Kernels is an established class
#: by construction. Added 2026-09-22 as INV-KK-CONCEPT-ADMISSION's third route.
#: BETTER evidence than two papers, because two papers can be the same research
#: group twice while two kernels cannot.
ADMISSIBLE_KERNELS = 2


def kernel_breadth(conn: sqlite3.Connection, concept_id: str) -> int:
    """Distinct Kernels a Concept is implemented-in.

    The third admission route. Unlike concept_weight this counts curation, not
    corpus coverage, which is exactly why it catches what weight misses: Zswap
    and KSM sit at one paper each in this corpus while being present in several
    kernels.
    """
    row = conn.execute(
        "SELECT COUNT(DISTINCT target_id) FROM edges "
        "WHERE kind = 'implemented-in' AND source_id = ?", (concept_id,)
    ).fetchone()
    return row[0] if row else 0


#: IFC-KK-DOC-DEFINED-PROVENANCE. The source types that count as canonical
#: documentation for INV-KK-CONCEPT-ADMISSION's fourth route, added 2026-09-25.
#:
#: SMALL AND CLOSED, DELIBERATELY. Every type added here is a new class of
#: witness granted the power to admit a Concept at weight 1. preprint and
#: conference-paper can never join it without repealing the paper ban;
#: vulnerability-database is the near-miss and is out, because a CVE record is
#: authoritative about an instance and silent about whether the mechanism it
#: names is an established class. Other kernels' documentation trees are what
#: would legitimately join it — see ANN-KK-KERNEL-CURATION-GAP.
DOC_SOURCE_TYPES = ("kernel-doc",)


def documented_concepts(conn: sqlite3.Connection) -> set[str]:
    """Every Concept whose provenance reaches a canonical-documentation Source.

    One query, for the reason seminal_concepts is one query: the concept
    browser paginates and a per-row membership check is what
    INV-KK-WEB-QUERY-BOUNDED forbids.

    THE kind = 'Concept' FILTER IS LOAD-BEARING AND WAS GOT WRONG TWICE. The
    same join without it counts every node kind hanging off doc Evidence and
    returns 153 against a corpus of 97 Concepts — PerformanceProfile 50,
    KernelInvariant 46, FailureMode 45, InteractionProtocol 12. The true
    Concept count on 2026-09-25 is ZERO.
    """
    placeholders = ", ".join("?" for _ in DOC_SOURCE_TYPES)
    rows = conn.execute(
        "SELECT DISTINCT e.source_id FROM edges e "
        "JOIN nodes n ON n.id = e.source_id AND n.kind = 'Concept' "
        "JOIN edges s ON s.source_id = e.target_id AND s.kind = 'sourced-from' "
        "JOIN nodes src ON src.id = s.target_id "
        "WHERE e.kind = 'extracted-from' "
        f"AND json_extract(src.attrs, '$.source_type') IN ({placeholders})",
        DOC_SOURCE_TYPES,
    ).fetchall()
    return {r[0] for r in rows}


def retired_concepts(conn: sqlite3.Connection) -> set[str]:
    """Every Concept a human has judged wrong, in one query.

    Retirement is a STATE FLIP and never a delete (INV-KK-CONCEPT-CURATION-
    VOCABULARY, operator decision 2026-09-25), so these nodes still exist and
    still carry their edges — which is exactly why the sweep has to ask.
    """
    return {
        r[0] for r in conn.execute(
            "SELECT id FROM nodes WHERE kind = 'Concept' "
            "AND json_extract(attrs, '$.curation_state') = 'retired'")
    }


def admission_state(
    conn: sqlite3.Connection,
    concept_id: str,
    seminal: set[str],
    documented: set[str] | None = None,
    retired: set[str] | None = None,
) -> str:
    """Classify ONE Concept: seminal, admissible, thin or unlinked.

    THE SINGLE IMPLEMENTATION OF THE ADMISSION THRESHOLD. check_concept_admission
    tallies this function over the corpus and the concept browser renders it per
    row, so the sweep and the page cannot disagree about which concepts are
    admissible. Extracted 2026-09-22 with operator approval under CLAUDE.md rule
    4; the alternative was a second copy of the weight test in the web layer, and
    a page that contradicted the sweep would discredit both.

    `seminal` is passed in rather than queried here so that a caller classifying
    many concepts pays for one query and not one per concept.
    """
    if documented is None:
        documented = documented_concepts(conn)
    if retired is None:
        retired = retired_concepts(conn)

    # FIRST, and ahead of every route. A retired Concept is admissible under
    # none of them whatever its weight: a human has judged it wrong, which is a
    # statement about the evidence and not about whether anyone has read it.
    # Operator decision 2026-09-25. This is the ONLY point at which curation
    # state and admission touch — the two are otherwise orthogonal axes, and
    # making admission depend on review would turn the census into a
    # review-progress bar that collapses after any harvest.
    if concept_id in retired:
        return "retired"
    if concept_id in seminal:
        return "seminal"
    weight = concept_weight(conn, concept_id)
    if weight >= ADMISSIBLE_WEIGHT:
        return "admissible"
    # The third route, 2026-09-22. Checked AFTER weight so a concept that
    # already clears the paper bar keeps reading as "admissible" rather than
    # being relabelled — the states must stay comparable across the amendment.
    if kernel_breadth(conn, concept_id) >= ADMISSIBLE_KERNELS:
        return "multi-kernel"
    # The fourth route, 2026-09-25, and last for the same reason the third is
    # not first. A Concept defined in TWO documents already reached weight 2
    # through the first disjunct — concept_weight has no source_type filter, so
    # that case needed no new rule and was checked before this one was added.
    # This exists for the ONE-document case, which the harvest will produce far
    # more of.
    if concept_id in documented:
        return "documented"
    return "unlinked" if weight == 0 else "thin"


def check_concept_admission(conn: sqlite3.Connection) -> AdmissionSweep:
    """Sweep every Concept for INV-KK-CONCEPT-ADMISSION.

    DELIBERATELY NOT IN RULES_BY_KIND, for the reason
    check_link_evidence_recorded is not: those rules are per-node and run on
    every write, so a Concept below the weight line would make writes that have
    nothing to do with this invariant fail. Operator decision 2026-09-22 —
    report, do not gate. Enforcement against NEW concepts is structural and
    lives elsewhere: INV-KK-EXTRACT-CONCEPT-MATCHED stops the extractor
    creating them at all.

    Returns no violations today. That is not vacuity — it is the date scope
    doing its job, and the thin list is where the signal actually is.
    """
    seminal = seminal_concepts(conn)
    documented_set = documented_concepts(conn)
    retired_set = retired_concepts(conn)
    admissible = 0
    thin: list[str] = []
    unlinked: list[str] = []
    documented: list[str] = []
    retired: list[str] = []
    violations: list[Violation] = []

    for (concept_id,) in conn.execute(
        "SELECT id FROM nodes WHERE kind = 'Concept' ORDER BY id"
    ).fetchall():
        state = admission_state(conn, concept_id, seminal,
                                documented_set, retired_set)
        if state == "retired":
            retired.append(concept_id)
        elif state in ("seminal", "admissible", "multi-kernel", "documented"):
            admissible += 1
            if state == "documented":
                documented.append(concept_id)
        elif state == "unlinked":
            unlinked.append(concept_id)
        else:
            thin.append(concept_id)

    return AdmissionSweep(admissible=admissible, thin=thin, unlinked=unlinked,
                          seminal=len(seminal), violations=violations,
                          documented=documented, retired=retired)


_ISO_DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def check_concept_curation_state(conn: sqlite3.Connection) -> list[Violation]:
    """Sweep every Concept for INV-KK-CONCEPT-CURATION-VOCABULARY.

    Two things are checked and they fail for different reasons. A
    curation_state outside the closed vocabulary makes the field unreadable —
    nothing downstream can decide whether that Concept has been reviewed. A
    state of 'reviewed' with no reviewed_by or no reviewed_at is readable and
    false: it claims a human acted without naming which human or when, and an
    unsigned review is the one thing this field exists to make impossible.

    DELIBERATELY NOT IN RULES_BY_KIND, for the reason check_concept_admission
    is not: those rules are per-node and run on every add_node, so a Concept
    that predates this field would make writes with nothing to do with it fail.
    All 97 Concepts as of 2026-09-25 carry no curation attribute at all.

    Returns no violations against the corpus of 2026-09-25, and that is the
    point rather than a weakness: absent is lawful, so the clean sweep is the
    baseline the first harvest will be measured against.

    Imported lazily to keep graph.rules free of a cycle with
    graph.concept_vocabulary, which imports nothing from here.
    """
    from graph.concept_vocabulary import CURATION_STATES, SIGNED_CURATION_STATES

    violations: list[Violation] = []
    rows = conn.execute(
        "SELECT id, attrs FROM nodes WHERE kind = 'Concept' ORDER BY id"
    ).fetchall()

    for concept_id, attrs_json in rows:
        attrs = json.loads(attrs_json) if isinstance(attrs_json, str) else (attrs_json or {})
        state = attrs.get("curation_state") or ""
        if not state:
            # Absent is lawful and means "nobody has reviewed this". It is not
            # a fourth state and is not a violation.
            continue
        if state not in CURATION_STATES:
            violations.append(Violation(
                concept_id, "concept-curation-vocabulary",
                f"Concept curation_state '{state}' is not one of: "
                + ", ".join(CURATION_STATES),
            ))
            continue
        if state in SIGNED_CURATION_STATES:
            if not (attrs.get("reviewed_by") or ""):
                violations.append(Violation(
                    concept_id, "concept-curation-unsigned",
                    f"Concept curation_state '{state}' must name reviewed_by",
                ))
            reviewed_at = attrs.get("reviewed_at") or ""
            if not reviewed_at:
                violations.append(Violation(
                    concept_id, "concept-curation-unsigned",
                    f"Concept curation_state '{state}' must carry reviewed_at",
                ))
            elif not _ISO_DATE_PREFIX_RE.match(reviewed_at):
                violations.append(Violation(
                    concept_id, "concept-curation-date",
                    f"Concept reviewed_at '{reviewed_at}' is not an ISO-8601 date",
                ))

    return violations


def check_link_confirmations(conn: sqlite3.Connection) -> list[Violation]:
    """INV-KK-LINK-CONFIRMATION-STATE, over every extracted-from edge.

    Unlike check_link_evidence_recorded this is NOT date-scoped: a person can
    review a legacy title-regex link, and 191 of those are known wrong, so the
    review surface is exactly where that would be discovered.
    """
    violations: list[Violation] = []
    rows = conn.execute(
        "SELECT source_id, target_id, attrs FROM edges WHERE kind = 'extracted-from'"
    ).fetchall()

    for source_id, target_id, raw in rows:
        try:
            attrs = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except json.JSONDecodeError:
            continue  # reported by check_link_evidence_recorded

        def bad(msg: str) -> None:
            violations.append(Violation(
                source_id, "INV-KK-LINK-CONFIRMATION-STATE",
                f"extracted-from edge to '{target_id}': {msg}"))

        state = attrs.get("confirmation")
        present = [k for k in CONFIRMATION_ATTR_KEYS if k in attrs]

        if state is None:
            # A link cannot record who reviewed it without recording the outcome.
            if present:
                bad(f"carries {', '.join(sorted(present))} with no confirmation")
            continue
        if state not in VALID_CONFIRMATIONS:
            bad(f"confirmation '{state}' is not one of {VALID_CONFIRMATIONS}")
            continue
        if not attrs.get("confirmed_by"):
            bad("confirmed without a reviewer")
            continue
        if not attrs.get("confirmed_at"):
            bad("confirmed without a date")
    return violations
