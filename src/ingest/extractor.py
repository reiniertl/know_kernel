"""LLM concept extraction -- Evidence (Class A) -> Concepts (Class B) (ALG-KK-LLM-EXTRACT)."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from graph.engine import add_edge, add_node
from graph.concept_vocabulary import (
    build_kernel_context,
    build_vocabulary_context,
    match_kernel_name,
    fuzzy_match_concept,
    record_candidate,
    resolve_concept_names,
)
from graph.rules import VALID_EVIDENCE_BASES
from ingest.llm_provider import (
    DEFAULT_PROVIDER,
    LLMClient,
    client_for,
    default_model_for,
)
from ingest.gate import SessionGate

log = logging.getLogger(__name__)

#: The model used when a caller names none. Resolved from the shared port
#: rather than written out, so the two paths cannot drift again: this file
#: said "claude-sonnet-4-6" while summary_extractor said "claude-sonnet-5",
#: and only one of those is a live model id.
DEFAULT_EXTRACTION_MODEL = default_model_for(DEFAULT_PROVIDER)



EXTRACTION_SYSTEM_PROMPT = """\
You are a concept extraction agent for a kernel-design intelligence system.

Your task: given a document about operating system or kernel design, extract \
abstract concepts --" the IDEAS, MECHANISMS, and DESIGN PATTERNS described, \
NOT the specific text or expression used to describe them.

CRITICAL RULES --" LEGAL PROTECTION:
- NEVER quote verbatim from the source material.
- NEVER copy sentences, phrases, or distinctive wording from the source.
- Express each concept in your own words as an abstract description of the mechanism.
- Focus on WHAT the mechanism does and WHY, not HOW the original author expressed it.
- If you cannot describe a concept without copying the source, skip it.

PROVENANCE GROUNDING RULES:
- Your evidence excerpt MUST summarize only what appears in the provided document text.
- Do NOT add claims about features, APIs, or design details that are not mentioned in the document.
- If the document is sparse (short or mostly code), your excerpt should reflect that -- a brief excerpt is better than a fabricated detailed one.
- The concepts you extract must be supported by the document content. If the document does not discuss a topic in sufficient detail to extract a concept, skip it.
- Do NOT use your general training knowledge to embellish or augment what the document says.

For each concept, provide:
- name: A short descriptive name (2-5 words)
- description: An abstract description of the mechanism (3-5 sentences, \
your own words, covering WHAT it does, HOW it works at a high level, \
and WHERE in the system it operates)
- key_properties: A list of 3-5 defining properties or characteristics \
(e.g., "O(log n) lookup time", "lazy allocation", "hardware-assisted")
- tradeoffs: A list of 1-3 limitations or costs (e.g., "internal \
fragmentation with large pages", "increased context switch overhead"). \
Empty list if no significant tradeoffs.
- design_rationale: One sentence explaining WHY this approach was chosen \
over alternatives
- subsystem: The kernel subsystem (e.g., "Virtual Memory", "Scheduler", \
"Filesystem", "IPC", "Networking", "Device Drivers", "Security")
- relationships: A list of connections to OTHER concepts you are \
extracting in this same batch. Each entry has:
  - target: The exact name of the other concept
  - kind: One of:
    - "refines" -- this concept is a more specific version of the target
    - "contradicts" -- this concept and the target cannot coexist
    - "prerequisite" -- this concept requires the target to exist first
    - "alternative-to" -- this concept and the target solve the same problem differently
    - "supersedes" -- this concept replaces the target entirely
  - reason: One sentence explaining the relationship
  If a concept has no relationships, use an empty list.
- invariants: A list of rules or properties that MUST HOLD for this \
concept to function correctly. Each entry has:
  - predicate: A clear statement of what must be true (e.g., "No reader \
can observe a partially-updated data structure")
  - strength: One of "safety" (violation = corruption), "liveness" \
(violation = deadlock/starvation), "performance" (violation = regression), \
"structural" (violation = design inconsistency)
  - scope: One of "per-operation", "per-object", "system-wide"
  Each invariant may include failure_modes --" what happens when this \
invariant is violated:
  - failure_modes: A list of consequences. Each entry has:
    - symptom: Observable behavior (e.g., "data corruption", "deadlock", \
"priority inversion")
    - blast_radius: One of "local", "subsystem", "kernel-wide"
    - recoverability: One of "self-healing", "requires-restart", "data-loss"
  Extract 1-3 invariants per concept. Focus on the most critical rules. \
If a concept has no clear invariants, use an empty list.

For each concept, also extract performance_profiles -- quantitative \
performance characteristics. Each entry has:
- metric: What is measured (e.g., "read latency", "memory overhead")
- complexity: Big-O or qualitative bound (e.g., "O(1)", "O(log n)", "constant")
- best_case: Behavior description under best conditions
- worst_case: Behavior description under worst conditions
- typical_case: Behavior description under typical conditions
- conditions: Under what workload or configuration this holds
Extract 1-3 profiles per concept. Empty list if no clear metrics.

After listing ALL concepts, add a top-level "interaction_protocols" key \
with coordination rules between concept PAIRS. Each protocol has:
- rule: The coordination constraint in natural language
- ordering: One of "before", "after", "never-during", "must-hold-while"
- violation_mode: What happens if the protocol is violated (one sentence)
- concept_a: Exact name of first participating concept (from your list)
- concept_b: Exact name of second participating concept (from your list)
Extract 0-5 protocols. Only include genuine cross-concept constraints.

Add a top-level "compatibility_assessments" key with synergy analyses \
between concept PAIRS. Each assessment has:
- synergy: One of "synergistic", "neutral", "antagonistic"
- rationale: Why these concepts are or are not compatible
- conditions: Under what conditions this assessment holds
- concept_a: Exact name of first concept (from your list)
- concept_b: Exact name of second concept (from your list)
Extract 0-5 assessments. Only include genuine synergy analyses.

Add a top-level "comparative_analyses" key with head-to-head comparisons \
between concept PAIRS on specific dimensions. Each analysis has:
- dimension: What is compared (e.g., "memory overhead", "latency")
- winner: Which concept is better on this dimension (or "tie")
- conditions: Under what conditions
- quantitative_delta: Measured difference if available (empty string if not)
- concept_a: Exact name of first concept (from your list)
- concept_b: Exact name of second concept (from your list)
Extract 0-5 analyses. Only include genuine measurable comparisons.

Return a JSON object with "concepts" (array, at most 10), \
"interaction_protocols" (array, at most 5), \
"compatibility_assessments" (array, at most 5), and \
"comparative_analyses" (array, at most 5). Focus on the most \
significant ideas.\
"""

CONCEPT_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "description": {"type": "string"},
            "key_properties": {"type": "array", "items": {"type": "string"}},
            "tradeoffs": {"type": "array", "items": {"type": "string"}},
            "design_rationale": {"type": "string"},
            "subsystem": {"type": "string"},
            "relationships": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "target": {"type": "string"},
                        "kind": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["target", "kind", "reason"],
                },
            },
            "invariants": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "predicate": {"type": "string"},
                        "strength": {"type": "string"},
                        "scope": {"type": "string"},
                        "failure_modes": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "symptom": {"type": "string"},
                                    "blast_radius": {"type": "string"},
                                    "recoverability": {"type": "string"},
                                },
                                "required": ["symptom", "blast_radius", "recoverability"],
                            },
                        },
                    },
                    "required": ["predicate", "strength", "scope"],
                },
            },
            "performance_profiles": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "metric": {"type": "string"},
                        "complexity": {"type": "string"},
                        "best_case": {"type": "string"},
                        "worst_case": {"type": "string"},
                        "typical_case": {"type": "string"},
                        "conditions": {"type": "string"},
                    },
                    "required": ["metric", "complexity", "best_case", "worst_case", "typical_case", "conditions"],
                },
            },
        },
        "required": ["name", "description", "key_properties", "tradeoffs", "design_rationale", "subsystem", "relationships", "invariants"],
    },
}


_VALIDATE_REQUIRED_KEYS = ("name", "description", "key_properties", "tradeoffs", "design_rationale", "subsystem")


def validate_extraction_item(item: Any) -> dict | None:
    if not isinstance(item, dict):
        return None
    for key in _VALIDATE_REQUIRED_KEYS:
        if key not in item:
            return None
    kp = item["key_properties"]
    if not isinstance(kp, list) or len(kp) == 0:
        return None
    rationale = item["design_rationale"]
    if not isinstance(rationale, str) or not rationale.strip():
        return None
    tradeoffs = item["tradeoffs"]
    if not isinstance(tradeoffs, list):
        return None
    sanitized = {
        "name": str(item["name"]).strip(),
        "description": str(item["description"]).strip(),
        "key_properties": [str(s).strip() for s in kp if isinstance(s, str)],
        "tradeoffs": [str(s).strip() for s in tradeoffs if isinstance(s, str)],
        "design_rationale": rationale.strip(),
        "subsystem": str(item["subsystem"]).strip(),
    }
    if not sanitized["key_properties"]:
        return None
    if "relationships" in item:
        sanitized["relationships"] = item["relationships"]
    return sanitized


DISCOURSE_EXTRACTION_ADDENDUM = """\

DISCOURSE SOURCE RULES (INV-KK-EXTRACT-DISCOURSE-RULES):
This source is a factual discourse item (news article, mailing list thread, \
forum post, or conference notes). The following modified rules apply:
- Factual claims, problem statements, and technical observations may be \
stated directly without rephrasing.
- Only CREATIVE EXPRESSION (metaphors, distinctive literary phrasing, \
opinion editorials) must be rephrased.
- Focus on extracting WHAT people are saying about kernel mechanisms, \
not the mechanisms themselves.
- The PROVENANCE GROUNDING RULES above still apply: only extract what \
the source actually says.\
"""


def build_extraction_prompt(
    evidence_text: str, source_type: str | None = None,
    vocabulary: str = "", kernels: str = "",
) -> str:
    """Build the user prompt, with the curated vocabulary when one is given.

    The vocabulary is the half that was missing on 2026-09-21. A matcher was
    added that day and matched 0 of 114 candidates, because a model never shown
    the vocabulary proposes "uSTM" and "BR-WFD Algorithm" — names no matcher
    can rescue. ALG-KK-CLAIM-EXTRACT has always done this on the discourse
    path. Defaults to empty so every existing caller and test is unaffected.
    """
    if source_type == "discourse":
        prefix = "Extract abstract concepts from this discourse source:\n\n"
    else:
        prefix = "Extract abstract concepts from this document:\n\n"
    head = f"{vocabulary}\n\n" if vocabulary else ""
    # The kernel vocabulary sits beside the concept one (IFC-KK-PAPER-KERNEL).
    # Four names, so the cost is negligible; both default to empty so every
    # existing caller and test is unaffected.
    if kernels:
        head += f"{kernels}\n\n"
    if evidence_text:
        return f"{head}{prefix}{evidence_text}"
    return head + "Extract abstract concepts from metadata only -- no source text available."


def get_system_prompt(
    source_type: str | None = None, vocabulary: str = "", kernels: str = "",
) -> str:
    """The system prompt, and since 2026-09-28 the vocabulary travels with it.

    INV-KK-LLM-CACHE-STABLE-PREFIX. The vocabulary used to be prepended to the
    USER prompt, which put a ~765-token constant in front of every one of 3,315
    paper calls — 2.54M tokens per run against 1.66M tokens of paper text, so
    60% of input was the same bytes re-sent, rising to 98% at 3,000 Concepts.
    Here it is part of the prefix that is identical across a run and can be
    cached once.

    IT MUST SHARE A BLOCK WITH THE SYSTEM PROMPT, not sit in one of its own.
    The minimum cacheable prefix is model-dependent — 1,024 tokens on
    claude-sonnet-5 — and falling under it does not error, it silently caches
    nothing. The vocabulary alone is ~765 tokens and would never cache; joined
    to the ~1,540-token system prompt it is ~2,418 and clears every current
    model's minimum.

    Both arguments default to empty so every existing caller and test is
    unaffected, the same convention build_extraction_prompt uses.
    """
    base = EXTRACTION_SYSTEM_PROMPT
    if source_type == "discourse":
        base += DISCOURSE_EXTRACTION_ADDENDUM
    tail = "\n\n".join(part for part in (vocabulary, kernels) if part)
    return f"{base}\n\n{tail}" if tail else base


def validate_excerpt_grounding(excerpt: str, document_text: str) -> list[str]:
    """Check that key phrases in the excerpt appear in the document text
    (ALG-KK-VALIDATE-EXCERPT-GROUNDING).

    Extracts consecutive word bigrams from the excerpt, checks each against
    document_text via case-insensitive substring match. Returns list of
    ungrounded phrases (empty = fully grounded).
    """
    if not excerpt or not excerpt.strip():
        return []

    words = excerpt.split()
    bigrams: set[str] = set()
    for i in range(len(words) - 1):
        w1 = words[i].strip(".,;:!?()\"'")
        w2 = words[i + 1].strip(".,;:!?()\"'")
        if len(w1) >= 3 and len(w2) >= 3:
            bigrams.add(f"{w1} {w2}")

    if not bigrams:
        return []

    if not document_text or not document_text.strip():
        return sorted(bigrams)

    doc_lower = document_text.lower()

    ungrounded = []
    for phrase in sorted(bigrams):
        if phrase.lower() not in doc_lower:
            ungrounded.append(phrase)

    return ungrounded


ALLOWED_RELATIONSHIP_KINDS = {"refines", "contradicts", "prerequisite", "alternative-to", "supersedes"}


@dataclass
class RelationshipResult:
    edges_created: int = 0
    edges_skipped: int = 0


# INV-KK-EXTRACT-EVIDENCE-RECORDED.
#
# Before 2026-09-21 every extracted-from edge was written bare: of 18,256 edges
# in the graph, 96 carried any attrs and all 96 were contributes-to. A link said
# a paper was about a topic and offered nothing to check that against.
#
# The obvious payload — the cited excerpt — is forbidden here. The block headed
# "CRITICAL RULES --" LEGAL PROTECTION" in EXTRACTION_SYSTEM_PROMPT tells the
# model never to quote verbatim and to skip any concept it cannot describe
# without copying, and INV-KK-EXTRACT-OUTPUT-CLASS-B says no Class A content
# leaks into the output. So the edge carries a VERDICT and a LOCATOR instead:
# what the check said, which document it was run against, and a fingerprint of
# that document. The phrases stored are bigrams of the created node's OWN
# paraphrase, so no source prose enters the graph.
#
# EXPECT grounded=False. Measured 2026-09-21 across 1,758 Concept links whose
# Evidence carried text, ZERO were fully grounded, median 27 ungrounded phrases.
# The check compares bigrams of a deliberate paraphrase against the source, so
# it can essentially never return empty while the legal-protection rules stand.
# The count and the phrases are the signal; passing is not the goal.

BASIS_EVIDENCE_TEXT = "evidence-text"
BASIS_NONE = "none"

#: Cap on phrases stored per edge. ungrounded_count carries the true total, so
#: the cap bounds storage without hiding the size of the disagreement.
MAX_UNGROUNDED_RECORDED = 20


def build_evidence_attrs(
    claim_text: str,
    document_text: str,
    model: str = "",
    basis: str = BASIS_EVIDENCE_TEXT,
) -> dict[str, Any]:
    """Grounding verdict for one created node, to be stored on its
    extracted-from edge (INV-KK-EXTRACT-EVIDENCE-RECORDED).

    Returns basis=BASIS_NONE with an empty fingerprint when there is no document
    to check against — an unverifiable link says so rather than claiming a pass.
    """
    checked_at = date.today().isoformat()
    if not document_text or not claim_text:
        return {
            "grounded": False,
            "ungrounded_count": 0,
            "ungrounded": [],
            "basis": BASIS_NONE,
            "basis_sha256": "",
            "model": model,
            "checked_at": checked_at,
        }
    ungrounded = validate_excerpt_grounding(claim_text, document_text)
    return {
        "grounded": not ungrounded,
        "ungrounded_count": len(ungrounded),
        "ungrounded": ungrounded[:MAX_UNGROUNDED_RECORDED],
        "basis": basis,
        "basis_sha256": hashlib.sha256(document_text.encode("utf-8")).hexdigest(),
        "model": model,
        "checked_at": checked_at,
    }


def wire_relationships(
    conn: sqlite3.Connection,
    concepts_data: list[dict],
    concept_name_to_id: dict[str, str],
) -> RelationshipResult:
    created = 0
    skipped = 0
    for item in concepts_data:
        if not isinstance(item, dict):
            continue
        source_name = item.get("name", "").lower()
        source_id = concept_name_to_id.get(source_name)
        if not source_id:
            continue
        for rel in item.get("relationships", []):
            if not isinstance(rel, dict):
                skipped += 1
                continue
            target_name = rel.get("target", "").strip().lower()
            kind = rel.get("kind", "").strip()
            if kind not in ALLOWED_RELATIONSHIP_KINDS:
                skipped += 1
                continue
            target_id = concept_name_to_id.get(target_name)
            if not target_id:
                skipped += 1
                continue
            if source_id == target_id:
                skipped += 1
                continue
            # The second unguarded writer on the re-link path, fixed with the
            # first. A relationship this pair already carries is not an error
            # and not a new edge: a re-derivation re-asks the same question of
            # the same paper and should reach the same answer without raising
            # part way through a paid batch.
            if conn.execute(
                "SELECT 1 FROM edges WHERE kind=? AND source_id=? AND target_id=?",
                (kind, source_id, target_id),
            ).fetchone():
                skipped += 1
                continue
            add_edge(conn, kind, source_id, target_id)
            created += 1
    return RelationshipResult(edges_created=created, edges_skipped=skipped)


VALID_STRENGTHS = {"safety", "liveness", "performance", "structural"}
VALID_SCOPES = {"per-operation", "per-object", "system-wide"}


def validate_invariant_item(item: Any) -> dict | None:
    if not isinstance(item, dict):
        return None
    for key in ("predicate", "strength", "scope", "concept_name"):
        if key not in item:
            return None
    predicate = item["predicate"]
    if not isinstance(predicate, str) or not predicate.strip():
        return None
    strength = item["strength"]
    if not isinstance(strength, str) or strength.strip() not in VALID_STRENGTHS:
        return None
    scope = item["scope"]
    if not isinstance(scope, str) or scope.strip() not in VALID_SCOPES:
        return None
    concept_name = item["concept_name"]
    if not isinstance(concept_name, str) or not concept_name.strip():
        return None
    return {
        "predicate": predicate.strip(),
        "strength": strength.strip(),
        "scope": scope.strip(),
        "concept_name": concept_name.strip(),
    }


def store_kernel_invariant(
    conn: sqlite3.Connection,
    item: dict,
    evidence_id: str,
    concept_name_to_id: dict[str, str],
    evidence_text: str = "",
    model: str = "",
) -> str | None:
    concept_id = concept_name_to_id.get(item["concept_name"].lower())
    if not concept_id:
        return None
    kinv_id = f"kinv-{uuid.uuid4().hex[:12]}"
    add_node(conn, kinv_id, "KernelInvariant", {
        "predicate": item["predicate"],
        "strength": item["strength"],
        "scope": item["scope"],
        "artifact_class": "abstracted-mechanism",
    })
    add_edge(conn, "governed-by", kinv_id, concept_id)
    add_edge(
        conn, "extracted-from", kinv_id, evidence_id,
        build_evidence_attrs(item["predicate"], evidence_text, model),
    )
    return kinv_id


VALID_BLAST_RADII = {"local", "subsystem", "kernel-wide"}
VALID_RECOVERABILITIES = {"self-healing", "requires-restart", "data-loss"}


def validate_failure_mode_item(item: Any) -> dict | None:
    if not isinstance(item, dict):
        return None
    for key in ("symptom", "blast_radius", "recoverability"):
        if key not in item:
            return None
    symptom = item["symptom"]
    if not isinstance(symptom, str) or not symptom.strip():
        return None
    blast_radius = item["blast_radius"]
    if not isinstance(blast_radius, str) or blast_radius.strip() not in VALID_BLAST_RADII:
        return None
    recoverability = item["recoverability"]
    if not isinstance(recoverability, str) or recoverability.strip() not in VALID_RECOVERABILITIES:
        return None
    return {
        "symptom": symptom.strip(),
        "blast_radius": blast_radius.strip(),
        "recoverability": recoverability.strip(),
    }


def store_failure_mode(
    conn: sqlite3.Connection,
    item: dict,
    evidence_id: str,
    kinv_id: str,
    evidence_text: str = "",
    model: str = "",
) -> str:
    fm_id = f"fm-{uuid.uuid4().hex[:12]}"
    add_node(conn, fm_id, "FailureMode", {
        "symptom": item["symptom"],
        "blast_radius": item["blast_radius"],
        "recoverability": item["recoverability"],
        "artifact_class": "abstracted-mechanism",
    })
    add_edge(conn, "triggered-by", fm_id, kinv_id)
    add_edge(
        conn, "extracted-from", fm_id, evidence_id,
        build_evidence_attrs(item["symptom"], evidence_text, model),
    )
    return fm_id


VALID_ORDERINGS = {"before", "after", "never-during", "must-hold-while"}


def validate_protocol_item(item: Any, concept_name_to_id: dict[str, str]) -> dict | None:
    if not isinstance(item, dict):
        return None
    for key in ("rule", "ordering", "concept_a", "concept_b"):
        if key not in item:
            return None
    rule = item["rule"]
    if not isinstance(rule, str) or not rule.strip():
        return None
    ordering = item["ordering"]
    if not isinstance(ordering, str) or ordering.strip() not in VALID_ORDERINGS:
        return None
    concept_a = item["concept_a"]
    concept_b = item["concept_b"]
    if not isinstance(concept_a, str) or not concept_a.strip():
        return None
    if not isinstance(concept_b, str) or not concept_b.strip():
        return None
    a_name = concept_a.strip().lower()
    b_name = concept_b.strip().lower()
    if a_name == b_name:
        return None
    if a_name not in concept_name_to_id or b_name not in concept_name_to_id:
        return None
    violation_mode = item.get("violation_mode", "")
    return {
        "rule": rule.strip(),
        "ordering": ordering.strip(),
        "concept_a": concept_a.strip(),
        "concept_b": concept_b.strip(),
        "violation_mode": str(violation_mode).strip() if violation_mode else "",
    }


def store_interaction_protocol(
    conn: sqlite3.Connection,
    item: dict,
    evidence_id: str,
    concept_name_to_id: dict[str, str],
    evidence_text: str = "",
    model: str = "",
) -> str | None:
    a_id = concept_name_to_id.get(item["concept_a"].lower())
    b_id = concept_name_to_id.get(item["concept_b"].lower())
    if not a_id or not b_id:
        return None
    proto_id = f"proto-{uuid.uuid4().hex[:12]}"
    add_node(conn, proto_id, "InteractionProtocol", {
        "rule": item["rule"],
        "ordering": item["ordering"],
        "violation_mode": item.get("violation_mode", ""),
        "artifact_class": "abstracted-mechanism",
    })
    add_edge(conn, "constrains-composition", proto_id, a_id)
    add_edge(conn, "constrains-composition", proto_id, b_id)
    add_edge(
        conn, "extracted-from", proto_id, evidence_id,
        build_evidence_attrs(item["rule"], evidence_text, model),
    )
    return proto_id


def build_protocol_extraction_prompt(concept_names: list[str]) -> str:
    names_list = ", ".join(concept_names)
    return (
        f"Given these kernel concepts: {names_list}\n\n"
        "Identify coordination rules that govern how these mechanisms must "
        "interact when composed together. Return a JSON array of protocols."
    )


def validate_performance_profile_item(item: Any) -> dict | None:
    if not isinstance(item, dict):
        return None
    for key in ("metric", "complexity", "best_case", "worst_case", "typical_case", "conditions"):
        if key not in item:
            return None
        val = item[key]
        if not isinstance(val, str) or not val.strip():
            return None
    return {
        "metric": item["metric"].strip(),
        "complexity": item["complexity"].strip(),
        "best_case": item["best_case"].strip(),
        "worst_case": item["worst_case"].strip(),
        "typical_case": item["typical_case"].strip(),
        "conditions": item["conditions"].strip(),
    }


def store_performance_profile(
    conn: sqlite3.Connection,
    item: dict,
    evidence_id: str,
    concept_name_to_id: dict[str, str],
    concept_name: str,
    evidence_text: str = "",
    model: str = "",
) -> str | None:
    concept_id = concept_name_to_id.get(concept_name.lower())
    if not concept_id:
        return None
    profile_id = f"profile-{uuid.uuid4().hex[:12]}"
    add_node(conn, profile_id, "PerformanceProfile", {
        "metric": item["metric"],
        "complexity": item["complexity"],
        "best_case": item["best_case"],
        "worst_case": item["worst_case"],
        "typical_case": item["typical_case"],
        "conditions": item["conditions"],
        "artifact_class": "abstracted-mechanism",
    })
    add_edge(conn, "profiled-by", profile_id, concept_id)
    add_edge(
        conn, "extracted-from", profile_id, evidence_id,
        build_evidence_attrs(item["conditions"], evidence_text, model),
    )
    return profile_id


VALID_SYNERGIES = {"synergistic", "neutral", "antagonistic"}


def validate_compatibility_item(item: Any, concept_name_to_id: dict[str, str]) -> dict | None:
    if not isinstance(item, dict):
        return None
    for key in ("synergy", "rationale", "conditions", "concept_a", "concept_b"):
        if key not in item:
            return None
    synergy = item["synergy"]
    if not isinstance(synergy, str) or synergy.strip() not in VALID_SYNERGIES:
        return None
    rationale = item["rationale"]
    if not isinstance(rationale, str) or not rationale.strip():
        return None
    conditions = item["conditions"]
    if not isinstance(conditions, str) or not conditions.strip():
        return None
    concept_a = item["concept_a"]
    concept_b = item["concept_b"]
    if not isinstance(concept_a, str) or not concept_a.strip():
        return None
    if not isinstance(concept_b, str) or not concept_b.strip():
        return None
    a_name = concept_a.strip().lower()
    b_name = concept_b.strip().lower()
    if a_name == b_name:
        return None
    if a_name not in concept_name_to_id or b_name not in concept_name_to_id:
        return None
    return {
        "synergy": synergy.strip(),
        "rationale": rationale.strip(),
        "conditions": conditions.strip(),
        "concept_a": concept_a.strip(),
        "concept_b": concept_b.strip(),
    }


def store_compatibility_assessment(
    conn: sqlite3.Connection,
    item: dict,
    evidence_id: str,
    concept_name_to_id: dict[str, str],
    evidence_text: str = "",
    model: str = "",
) -> str | None:
    a_id = concept_name_to_id.get(item["concept_a"].lower())
    b_id = concept_name_to_id.get(item["concept_b"].lower())
    if not a_id or not b_id:
        return None
    compat_id = f"compat-{uuid.uuid4().hex[:12]}"
    add_node(conn, compat_id, "CompatibilityAssessment", {
        "synergy": item["synergy"],
        "rationale": item["rationale"],
        "conditions": item["conditions"],
        "artifact_class": "abstracted-mechanism",
    })
    add_edge(conn, "assesses-compatibility", compat_id, a_id)
    add_edge(conn, "assesses-compatibility", compat_id, b_id)
    add_edge(
        conn, "extracted-from", compat_id, evidence_id,
        build_evidence_attrs(item["rationale"], evidence_text, model),
    )
    return compat_id


def validate_comparative_item(
    item: Any, concept_name_to_id: dict[str, str],
) -> dict | None:
    if not isinstance(item, dict):
        return None
    dimension = item.get("dimension", "")
    winner = item.get("winner", "")
    conditions = item.get("conditions", "")
    quantitative_delta = item.get("quantitative_delta", "")
    concept_a = item.get("concept_a", "")
    concept_b = item.get("concept_b", "")
    if not isinstance(dimension, str) or not dimension.strip():
        return None
    if not isinstance(winner, str) or not winner.strip():
        return None
    if not isinstance(concept_a, str) or not concept_a.strip():
        return None
    if not isinstance(concept_b, str) or not concept_b.strip():
        return None
    a_name = concept_a.strip().lower()
    b_name = concept_b.strip().lower()
    if a_name == b_name:
        return None
    if a_name not in concept_name_to_id or b_name not in concept_name_to_id:
        return None
    return {
        "dimension": dimension.strip(),
        "winner": winner.strip(),
        "conditions": conditions.strip() if isinstance(conditions, str) else "",
        "quantitative_delta": quantitative_delta.strip() if isinstance(quantitative_delta, str) else "",
        "concept_a": concept_a.strip(),
        "concept_b": concept_b.strip(),
    }


def store_comparative_analysis(
    conn: sqlite3.Connection,
    item: dict,
    evidence_id: str,
    concept_name_to_id: dict[str, str],
    evidence_text: str = "",
    model: str = "",
) -> str | None:
    a_id = concept_name_to_id.get(item["concept_a"].lower())
    b_id = concept_name_to_id.get(item["concept_b"].lower())
    if not a_id or not b_id:
        return None
    analysis_id = f"comparative-{uuid.uuid4().hex[:12]}"
    add_node(conn, analysis_id, "ComparativeAnalysis", {
        "dimension": item["dimension"],
        "winner": item["winner"],
        "conditions": item["conditions"],
        "quantitative_delta": item["quantitative_delta"],
        "artifact_class": "abstracted-mechanism",
    })
    add_edge(conn, "compares", analysis_id, a_id)
    add_edge(conn, "compares", analysis_id, b_id)
    add_edge(
        conn, "extracted-from", analysis_id, evidence_id,
        build_evidence_attrs(item["conditions"], evidence_text, model),
    )
    return analysis_id


def store_rich_concept(
    conn: sqlite3.Connection, item: dict, evidence_id: str,
    evidence_text: str = "",
    model: str = "",
) -> str:
    concept_id = f"concept-{uuid.uuid4().hex[:12]}"
    add_node(conn, concept_id, "Concept", {
        "name": item["name"],
        "description": item["description"],
        "artifact_class": "abstracted-mechanism",
        "key_properties": item["key_properties"],
        "tradeoffs": item["tradeoffs"],
        "design_rationale": item["design_rationale"],
    })
    add_edge(
        conn, "extracted-from", concept_id, evidence_id,
        build_evidence_attrs(item["description"], evidence_text, model),
    )
    return concept_id


def normalise_concept_name(name: str) -> str:
    """The key concept identity is matched on in re-link mode.

    casefold rather than lower: the corpus carries names from paper titles and
    the difference matters for the handful that are not plain ASCII.
    """
    return " ".join(str(name).split()).casefold()


def find_concept_by_name(conn: sqlite3.Connection, name: str) -> str | None:
    """The existing Concept with this name, if there is exactly one.

    Returns None on a tie. Two Concepts already sharing a name is a corpus
    defect, and picking one arbitrarily would attach a paper's provenance to a
    coin flip — minting a new node is the honest outcome there.
    """
    key = normalise_concept_name(name)
    if not key:
        return None
    hits = [
        row[0] for row in conn.execute(
            "SELECT id, json_extract(attrs, '$.name') FROM nodes "
            "WHERE kind = 'Concept'"
        ).fetchall()
        if normalise_concept_name(row[1] or "") == key
    ]
    return hits[0] if len(hits) == 1 else None


def attach_existing_concept(
    conn: sqlite3.Connection, concept_id: str, item: dict, evidence_id: str,
    evidence_text: str = "",
    model: str = "",
) -> str:
    """The EIGHTH provenance writer (INV-KK-EXTRACT-PROVENANCE), re-link only.

    Links a Concept that ALREADY EXISTS to the Evidence being re-derived. The
    other seven mint a node and then link it; this one only links, which is
    the whole point: store_rich_concept never looks up by name, and the
    title-regex linker it replaces reused 77 Concepts across 1,433 papers.
    Re-deriving through minting alone would take a 97-node vocabulary into
    five figures of near-duplicates, each arriving at weight 1 and so in
    violation of INV-KK-CONCEPT-ADMISSION.

    It writes the same build_evidence_attrs verdict as the other seven, so the
    structural claim that no extractor-written edge can be bare still holds.

    IT UPDATES RATHER THAN INSERTS WHEN THE LINK ALREADY EXISTS, and that is
    the common case, not an edge case. The 77 reused Concepts already point at
    the papers being re-derived, and the edges table carries
    UNIQUE (kind, source_id, target_id) — a plain insert would raise
    IntegrityError on the majority of the 1,433 papers, part way through a
    paid run. The same link acquiring a real verdict in place of a legacy
    marker is the correct outcome: it becomes the current edge and is NOT
    superseded, because it is the replacement.
    """
    attrs = build_evidence_attrs(item["description"], evidence_text, model)
    already = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'extracted-from' "
        "AND source_id = ? AND target_id = ?", (concept_id, evidence_id),
    ).fetchone()
    if already is not None:
        conn.execute(
            "UPDATE edges SET attrs = ? WHERE kind = 'extracted-from' "
            "AND source_id = ? AND target_id = ?",
            (json.dumps(attrs), concept_id, evidence_id))
        return concept_id
    add_edge(
        conn, "extracted-from", concept_id, evidence_id,
        attrs,
    )
    return concept_id


def edge_carries_a_current_verdict(attrs: dict | None) -> bool:
    """Whether a provenance edge still stands as this paper's live link.

    Current means: a basis the evidence rule accepts, and not superseded. The
    out-of-scope markers — unverified-legacy, claim-extract-unverified,
    extractor-preverdict, mechanism-unattributed — are deliberately NOT
    current, because an edge carrying one is exactly an edge awaiting
    re-derivation. This one predicate drives both --all-relink's selection and
    INV-KK-EXTRACT-RELINK-CONVERGENT's guard, which is why a failed run
    resumes rather than skips.
    """
    if not isinstance(attrs, dict):
        return False
    if attrs.get("superseded") is True:
        return False
    return attrs.get("basis") in VALID_EVIDENCE_BASES


def _is_concept(conn: sqlite3.Connection, node_id: str) -> bool:
    """Whether this edge's source is a Concept and not one of the other twelve.

    THE FILTER THIS CODEBASE KEEPS FORGETTING. extracted-from runs from thirteen
    node kinds into Evidence, so any query or sweep that reasons about "the
    concept links on this paper" and omits the kind test is reasoning about all
    thirteen. It has produced a wrong answer four separate times.
    """
    row = conn.execute("SELECT kind FROM nodes WHERE id = ?", (node_id,)).fetchone()
    return bool(row) and row[0] == "Concept"


def evidence_has_a_current_answer(
    conn: sqlite3.Connection, evidence_id: str, edges: list | None = None
) -> bool:
    """Whether this paper has already been answered, by a link or by a verdict.

    ONE DEFINITION USED IN TWO PLACES, deliberately, because that is what makes
    a failed run resume rather than skip: --all-relink's selection and
    extract_concepts' own relink guard must agree about what "already done"
    means or the selection offers papers the function returns early on.

    IT GAINED THE SECOND CLAUSE ON 2026-09-28 (INV-KK-EXTRACT-NEGATIVE-VERDICT).
    Until then "answered" meant "carries a current edge", which cannot express
    the answer the majority of this corpus actually has: the model read the
    paper and it is about NONE of the known concepts. Such a paper ends with no
    concept link at all, so there is no edge left to carry the verdict and it is
    recorded on the Evidence instead. Without it the relink queue never shrinks
    on these papers — measured 1,322 before a paid 20-paper batch and 1,322
    after — and every future run pays again to reach the same conclusion.
    """
    if edges is None:
        edges = conn.execute(
            "SELECT source_id, attrs FROM edges "
            "WHERE kind = 'extracted-from' AND target_id = ?", (evidence_id,),
        ).fetchall()
    for _, raw in edges:
        try:
            attrs = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            attrs = {}
        if edge_carries_a_current_verdict(attrs):
            return True
    return evidence_carries_a_no_match_verdict(conn, evidence_id)


def evidence_carries_a_no_match_verdict(
    conn: sqlite3.Connection, evidence_id: str
) -> bool:
    """Whether a run already concluded this paper matches nothing.

    Re-opening the question is a DELIBERATE act, not an accident of the next
    run: a vocabulary that gains 200 networking concepts tomorrow makes some of
    these verdicts stale, and clearing the attribute is what makes that re-run
    selectable without re-examining the whole corpus.
    """
    row = conn.execute(
        "SELECT json_extract(attrs, '$.concept_verdict.result') FROM nodes "
        "WHERE id = ?", (evidence_id,),
    ).fetchone()
    return bool(row) and row[0] == "no-match"


def record_no_match_verdict(
    conn: sqlite3.Connection, evidence_id: str, model: str, at: str = ""
) -> None:
    """Write the answer "this paper is about none of them" onto the Evidence.

    IT NAMES THE MODEL AND THE DATE so a later reader can ask which run reached
    it. The honest state of "Improving IoT Intrusion Detection Through
    SMOTE-Based Oversampling" is a paper with NO concept link; a graph that says
    nothing about a paper is correct where one saying it is about Linux Security
    Modules is not.
    """
    from graph.engine import update_node_attrs

    update_node_attrs(conn, evidence_id, {
        "concept_verdict": {
            "result": "no-match",
            "model": model,
            "at": at or date.today().isoformat(),
        },
    })


def mark_edges_superseded(
    conn: sqlite3.Connection, evidence_id: str, source_ids: list[str]
) -> int:
    """Retire the named edges into this Evidence. Returns how many moved.

    Called only AFTER at least one replacement edge exists. Superseding first
    and then failing to extract would leave a paper whose only links are
    retired ones, which is worse than the state it started in.
    """
    moved = 0
    for source_id in source_ids:
        row = conn.execute(
            "SELECT attrs FROM edges WHERE kind = 'extracted-from' "
            "AND source_id = ? AND target_id = ?", (source_id, evidence_id),
        ).fetchone()
        if row is None:
            continue
        try:
            attrs = json.loads(row[0]) if row[0] else {}
        except json.JSONDecodeError:
            attrs = {}
        if not isinstance(attrs, dict) or attrs.get("superseded") is True:
            continue
        attrs["superseded"] = True
        conn.execute(
            "UPDATE edges SET attrs = ? WHERE kind = 'extracted-from' "
            "AND source_id = ? AND target_id = ?",
            (json.dumps(attrs), source_id, evidence_id))
        moved += 1
    return moved


@dataclass
class ExtractionResult:
    evidence_id: str
    concept_ids: list[str] = field(default_factory=list)
    concepts_created: int = 0
    concepts_skipped: int = 0
    subsystem_ids: list[str] = field(default_factory=list)
    relationships_created: int = 0
    invariants_created: int = 0
    failure_modes_created: int = 0
    protocols_created: int = 0
    profiles_created: int = 0
    compatibilities_created: int = 0
    comparatives_created: int = 0
    extraction_model: str = ""
    prompt_tokens: int = 0
    response_tokens: int = 0
    #: INV-KK-LLM-CACHE-REPORTED. The adapters have returned these since the
    #: prompt-caching change and they reached nothing: the one number saying
    #: whether the cached prefix is being hit was unobservable on the path that
    #: spends the most money. A ZERO here means the prefix is being invalidated,
    #: and every cause of that is silent.
    cached_tokens: int = 0
    cache_written_tokens: int = 0
    #: Re-link mode only. concepts_reused counts links made to a Concept that
    #: already existed; edges_superseded counts old links retired, and is zero
    #: whenever concepts_created and concepts_reused are both zero.
    concepts_reused: int = 0
    edges_superseded: int = 0
    #: Names the model proposed that the vocabulary did not contain. They are
    #: queued in concept_candidates (IFC-KK-CONCEPT-CANDIDATE), not created.
    concepts_rejected: int = 0
    #: IFC-KK-PAPER-KERNEL. The Kernel the paper was associated with, or "".
    #: Empty is the EXPECTED value on this corpus: most papers are not about a
    #: specific kernel, and "none" is a permitted answer that writes no edge.
    kernel_id: str = ""
    #: A kernel name the model returned that is not in the Kernel table. Dropped,
    #: never created (INV-KK-PAPER-KERNEL-MATCHED). Unlike a rejected concept it
    #: is NOT queued: seeding kernels is human curation, not a work queue, per
    #: ANN-KK-KERNEL-CURATION-GAP.
    kernels_rejected: int = 0


def extract_concepts(
    conn: sqlite3.Connection,
    evidence_id: str,
    gate: SessionGate,
    model: str = DEFAULT_EXTRACTION_MODEL,
    dry_run: bool = False,
    client: LLMClient | None = None,
    source_type: str | None = None,
    relink: bool = False,
    record_candidates: bool = True,
) -> ExtractionResult:
    """Extract abstract Concepts from an Evidence node via LLM.

    Implements ALG-KK-LLM-EXTRACT steps 1-8. Uses SessionGate to enforce
    INV-KK-EXTRACT-SESSION-ENFORCED. All created Concepts are Class B
    (INV-KK-EXTRACT-OUTPUT-CLASS-B) with extracted-from provenance
    (INV-KK-EXTRACT-PROVENANCE). Idempotent (INV-KK-EXTRACT-IDEMPOTENT).
    """
    row = conn.execute(
        "SELECT id, kind, attrs FROM nodes WHERE id = ? AND kind = 'Evidence'",
        (evidence_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Evidence node '{evidence_id}' does not exist")

    gate.record_class_a_access()

    existing = conn.execute(
        "SELECT source_id, attrs FROM edges "
        "WHERE kind = 'extracted-from' AND target_id = ?",
        (evidence_id,),
    ).fetchall()
    if existing and not relink:
        # INV-KK-EXTRACT-IDEMPOTENT, default mode: any edge at all stops us.
        return ExtractionResult(
            evidence_id=evidence_id,
            concept_ids=[r[0] for r in existing],
            concepts_created=0,
            concepts_skipped=len(existing),
            extraction_model=model,
        )
    if existing and relink:
        # INV-KK-EXTRACT-RELINK-CONVERGENT: a CURRENT edge stops us; a legacy
        # marker does not, because that is the edge we are here to replace.
        parsed_existing = []
        for source_id, raw in existing:
            try:
                parsed_existing.append(
                    (source_id, json.loads(raw) if raw else {}))
            except json.JSONDecodeError:
                parsed_existing.append((source_id, {}))
        if evidence_has_a_current_answer(conn, evidence_id, existing):
            return ExtractionResult(
                evidence_id=evidence_id,
                concept_ids=[sid for sid, _ in parsed_existing],
                concepts_created=0,
                concepts_skipped=len(parsed_existing),
                extraction_model=model,
            )
    # ONLY CONCEPT EDGES ARE THIS RUN'S TO RETIRE, AND THE FILTER IS LOAD-BEARING.
    # extracted-from carries THIRTEEN valid source kinds (graph.schema) and this
    # function re-derives exactly one of them. Without the filter a re-link
    # retires the provenance of the other six writers named by
    # INV-KK-EXTRACT-PROVENANCE — measured 2026-09-28 across 40 papers, 5 of 25
    # superseded edges were a FailureMode, a PerformanceProfile, an Observation
    # and a KernelInvariant, none of which this run made any claim about. At
    # 1,302 papers that is roughly 325 edges retired by a verdict that was never
    # about them.
    superseding_candidates = [
        r[0] for r in existing
        if relink and _is_concept(conn, r[0])
    ] if relink else []

    source_row = conn.execute(
        "SELECT target_id FROM edges WHERE kind = 'sourced-from' AND source_id = ?",
        (evidence_id,),
    ).fetchone()
    source_id = source_row[0] if source_row else None

    ev_text_row = conn.execute(
        "SELECT attrs FROM nodes WHERE id = ?", (evidence_id,)
    ).fetchone()
    ev_attrs = json.loads(ev_text_row[0]) if ev_text_row else {}

    evidence_text = ev_attrs.get("text", "")
    if not evidence_text and source_id:
        src_attrs_row = conn.execute(
            "SELECT attrs FROM nodes WHERE id = ?", (source_id,)
        ).fetchone()
        if src_attrs_row:
            src_attrs = json.loads(src_attrs_row[0])
            evidence_text = src_attrs.get("text", "")

    if source_type is None and source_id:
        src_type_row = conn.execute(
            "SELECT attrs FROM nodes WHERE id = ?", (source_id,)
        ).fetchone()
        if src_type_row:
            st_attrs = json.loads(src_type_row[0])
            source_type = st_attrs.get("source_type")

    # The vocabularies go in the SYSTEM prompt so the prefix is stable across
    # the run and cacheable (INV-KK-LLM-CACHE-STABLE-PREFIX); the user prompt
    # carries only this paper's text.
    vocabulary = build_vocabulary_context(conn)
    kernels = build_kernel_context(conn)
    system_prompt = get_system_prompt(source_type, vocabulary, kernels)
    user_prompt = build_extraction_prompt(evidence_text, source_type)

    if dry_run:
        return ExtractionResult(
            evidence_id=evidence_id,
            extraction_model=model,
            prompt_tokens=len(system_prompt.split()) + len(user_prompt.split()),
        )

    if client is None:
        client = client_for(DEFAULT_PROVIDER)

    response = client.create_message(
        model=model,
        system=system_prompt,
        user=user_prompt,
        max_tokens=4096,
    )

    try:
        text = response["text"].strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        parsed = json.loads(text)
    except (json.JSONDecodeError, KeyError, IndexError):
        parsed = []

    # IFC-KK-PAPER-KERNEL. Only a dict response can carry it; the bare-list
    # form predates the field and legitimately has no kernel to report.
    kernel_named = parsed.get("kernel", "") if isinstance(parsed, dict) else ""

    if isinstance(parsed, dict):
        concepts_data = parsed.get("concepts", [])
        protocols_data = parsed.get("interaction_protocols", [])
        compat_data = parsed.get("compatibility_assessments", [])
        comparative_data = parsed.get("comparative_analyses", [])
    elif isinstance(parsed, list):
        concepts_data = parsed
        protocols_data = []
        compat_data = []
        comparative_data = []
    else:
        concepts_data = []
        protocols_data = []
        compat_data = []
        comparative_data = []

    if not isinstance(concepts_data, list):
        concepts_data = []
    if not isinstance(protocols_data, list):
        protocols_data = []
    if not isinstance(compat_data, list):
        compat_data = []
    if not isinstance(comparative_data, list):
        comparative_data = []

    concept_ids: list[str] = []
    concepts_reused = 0
    concepts_rejected = 0
    vocabulary_ids = resolve_concept_names(conn)
    today = date.today().isoformat()
    name_to_id: dict[str, str] = {}
    for item in concepts_data[:10]:
        validated = validate_extraction_item(item)
        if validated is None:
            continue
        # INV-KK-EXTRACT-CONCEPT-MATCHED: link to the vocabulary, never mint.
        # store_rich_concept is NOT reached from here any more. The other six
        # writers still mint their own nodes, and that stays correct — a
        # FailureMode or a PerformanceProfile IS paper-specific. A Concept is
        # a shared class by definition, which is the whole distinction.
        matched = fuzzy_match_concept(validated["name"], vocabulary_ids)
        if matched is None:
            # Not a failure. A name two distinct Sources reach for on their own
            # is the weight-2 evidence INV-KK-CONCEPT-ADMISSION asks for, and
            # this records it BEFORE a node exists rather than after 114 do.
            #
            # THE QUEUE IS OPT-OUT FROM 2026-09-28, AND THE COUNT NEVER IS.
            # IFC-KK-CONCEPT-CANDIDATE reads a proposal as "a name worth
            # considering for the vocabulary", which is true of a kernel paper
            # and false of the re-link population: measured across 40 papers,
            # the proposals were RowHammer Vulnerability, LeakyHammer Attack,
            # Dynamic Information Leak Fuzzing and NIFuzz, because the papers
            # are about IoT intrusion detection and DRAM side channels rather
            # than about kernels. Queuing ~3,000 of those into a 43-row
            # hand-reviewed queue would destroy the queue to record something
            # already known. concepts_rejected is ALWAYS counted, because it is
            # what INV-KK-EXTRACT-NEGATIVE-VERDICT reads to tell an answer from
            # a crash — suppressing the rows may never suppress the verdict.
            if record_candidates:
                record_candidate(conn, validated["name"], evidence_id, today)
            concepts_rejected += 1
            continue
        concept_id = attach_existing_concept(
            conn, matched, validated, evidence_id,
            evidence_text=evidence_text, model=model)
        concepts_reused += 1
        concept_ids.append(concept_id)
        name_to_id[validated["name"].lower()] = concept_id

    subsystem_ids: list[str] = []
    if concept_ids:
        from ingest.classifier import assign_subsystems, parse_classification_labels

        classifications = parse_classification_labels(concepts_data[:10], concept_ids)
        class_result = assign_subsystems(conn, concept_ids, classifications)
        subsystem_ids = list(set(class_result.concept_subsystem_map.values()))

    rel_result = wire_relationships(conn, concepts_data[:10], name_to_id)

    invariants_created = 0
    failure_modes_created = 0
    for item in concepts_data[:10]:
        if not isinstance(item, dict):
            continue
        for inv in item.get("invariants", []):
            inv["concept_name"] = item.get("name", "")
            validated = validate_invariant_item(inv)
            if validated is None:
                continue
            inv_id = store_kernel_invariant(
                conn, validated, evidence_id, name_to_id,
                evidence_text=evidence_text, model=model)
            if inv_id:
                invariants_created += 1
                for fm in inv.get("failure_modes", []):
                    validated_fm = validate_failure_mode_item(fm)
                    if validated_fm:
                        store_failure_mode(
                            conn, validated_fm, evidence_id, inv_id,
                            evidence_text=evidence_text, model=model)
                        failure_modes_created += 1

    protocols_created = 0
    for proto in protocols_data[:5]:
        validated_proto = validate_protocol_item(proto, name_to_id)
        if validated_proto is None:
            continue
        proto_id = store_interaction_protocol(
            conn, validated_proto, evidence_id, name_to_id,
            evidence_text=evidence_text, model=model)
        if proto_id:
            protocols_created += 1

    profiles_created = 0
    for item in concepts_data[:10]:
        if not isinstance(item, dict):
            continue
        concept_name = item.get("name", "")
        for profile in item.get("performance_profiles", []):
            validated_profile = validate_performance_profile_item(profile)
            if validated_profile is None:
                continue
            profile_id = store_performance_profile(
                conn, validated_profile, evidence_id, name_to_id, concept_name,
                evidence_text=evidence_text, model=model,
            )
            if profile_id:
                profiles_created += 1

    compatibilities_created = 0
    for compat in compat_data[:10]:
        validated_compat = validate_compatibility_item(compat, name_to_id)
        if validated_compat is None:
            continue
        compat_id = store_compatibility_assessment(
            conn, validated_compat, evidence_id, name_to_id,
            evidence_text=evidence_text, model=model)
        if compat_id:
            compatibilities_created += 1

    comparatives_created = 0
    for comp in comparative_data[:10]:
        validated_comp = validate_comparative_item(comp, name_to_id)
        if validated_comp is None:
            continue
        comp_id = store_comparative_analysis(
            conn, validated_comp, evidence_id, name_to_id,
            evidence_text=evidence_text, model=model)
        if comp_id:
            comparatives_created += 1

    # Post-extraction grounding check (INV-KK-EXTRACT-GROUNDING-CHECK)
    if evidence_text:
        for item in concepts_data[:10]:
            if not isinstance(item, dict):
                continue
            desc = item.get("description", "")
            if desc:
                ungrounded = validate_excerpt_grounding(desc, evidence_text)
                if ungrounded:
                    log.warning(
                        "Grounding check: concept '%s' has ungrounded phrases: %s",
                        item.get("name", "?"), ungrounded,
                    )

    # INV-KK-EXTRACT-RELINK-CONVERGENT: retire the old links only once their
    # replacements exist. concepts_created == 0 implies edges_superseded == 0.
    edges_superseded = 0
    if relink and concept_ids:
        edges_superseded = mark_edges_superseded(
            conn, evidence_id,
            [sid for sid in superseding_candidates if sid not in concept_ids])
    elif relink and concepts_rejected:
        # INV-KK-EXTRACT-NEGATIVE-VERDICT. The model READ the paper and proposed
        # names; none of them is in the vocabulary. That is an ANSWER and it is
        # the right one — measured 2026-09-28, 19 of 20 papers in the relink
        # queue are about IoT intrusion detection, VR keystroke inference or
        # RowHammer, and their legacy links are substring matches on the title
        # ("Blockchain" -> Block Device Layer). The false links go, no link
        # replaces them, and the paper stops being asked.
        #
        # concepts_rejected == 0 IS THE OTHER CASE AND IT IS UNCHANGED: nothing
        # parseable came back, nothing is touched, and the next run retries —
        # ev-arxiv-027e07c3 on 2026-09-21, which succeeded on its retry.
        edges_superseded = mark_edges_superseded(
            conn, evidence_id, superseding_candidates)
        record_no_match_verdict(conn, evidence_id, model, today)

    # IFC-KK-PAPER-KERNEL: associate the PAPER, not the Evidence, and only with
    # a Kernel that already exists (INV-KK-PAPER-KERNEL-MATCHED). A name the
    # table does not hold is counted and dropped — extraction may not change how
    # many Kernels exist, exactly as it may not change how many Concepts exist.
    kernel_id = ""
    kernels_rejected = 0
    if kernel_named and source_id:
        matched = match_kernel_name(conn, kernel_named)
        if matched:
            # Upsert: a relink run re-asks the same question of the same paper,
            # and a plain INSERT would raise on UNIQUE (kind, source_id,
            # target_id) part-way through a paid batch.
            already = conn.execute(
                "SELECT 1 FROM edges WHERE kind = 'about-kernel' "
                "AND source_id = ? AND target_id = ?", (source_id, matched),
            ).fetchone()
            if not already:
                add_edge(conn, "about-kernel", source_id, matched,
                         {"basis": "llm-extracted", "extracted_at": today})
            kernel_id = matched
        elif normalise_concept_name(kernel_named) != "none":
            kernels_rejected = 1

    return ExtractionResult(
        evidence_id=evidence_id,
        concept_ids=concept_ids,
        subsystem_ids=subsystem_ids,
        concepts_reused=concepts_reused,
        concepts_rejected=concepts_rejected,
        kernel_id=kernel_id,
        kernels_rejected=kernels_rejected,
        edges_superseded=edges_superseded,
        relationships_created=rel_result.edges_created,
        invariants_created=invariants_created,
        failure_modes_created=failure_modes_created,
        protocols_created=protocols_created,
        profiles_created=profiles_created,
        compatibilities_created=compatibilities_created,
        comparatives_created=comparatives_created,
        concepts_created=len(concept_ids) - concepts_reused,
        concepts_skipped=0,
        extraction_model=model,
        prompt_tokens=response.get("prompt_tokens", 0),
        response_tokens=response.get("response_tokens", 0),
        cached_tokens=response.get("cached_tokens", 0),
        cache_written_tokens=response.get("cache_written_tokens", 0),
    )
