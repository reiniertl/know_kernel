"""LLM concept extraction â€” Evidence (Class A) â†’ Concepts (Class B) (ALG-KK-LLM-EXTRACT)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from graph.engine import add_edge, add_node
from ingest.gate import SessionGate


EXTRACTION_SYSTEM_PROMPT = """\
You are a concept extraction agent for a kernel-design intelligence system.

Your task: given a document about operating system or kernel design, extract \
abstract concepts â€” the IDEAS, MECHANISMS, and DESIGN PATTERNS described, \
NOT the specific text or expression used to describe them.

CRITICAL RULES â€” LEGAL PROTECTION:
- NEVER quote verbatim from the source material.
- NEVER copy sentences, phrases, or distinctive wording from the source.
- Express each concept in your own words as an abstract description of the mechanism.
- Focus on WHAT the mechanism does and WHY, not HOW the original author expressed it.
- If you cannot describe a concept without copying the source, skip it.

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
  - kind: One of "refines", "contradicts", "prerequisite"
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
  Each invariant may include failure_modes â€" what happens when this \
invariant is violated:
  - failure_modes: A list of consequences. Each entry has:
    - symptom: Observable behavior (e.g., "data corruption", "deadlock", \
"priority inversion")
    - blast_radius: One of "local", "subsystem", "kernel-wide"
    - recoverability: One of "self-healing", "requires-restart", "data-loss"
  Extract 1-3 invariants per concept. Focus on the most critical rules. \
If a concept has no clear invariants, use an empty list.

After listing ALL concepts, add a top-level "interaction_protocols" key \
with coordination rules between concept PAIRS. Each protocol has:
- rule: The coordination constraint in natural language
- ordering: One of "before", "after", "never-during", "must-hold-while"
- violation_mode: What happens if the protocol is violated (one sentence)
- concept_a: Exact name of first participating concept (from your list)
- concept_b: Exact name of second participating concept (from your list)
Extract 0-5 protocols. Only include genuine cross-concept constraints.

Return a JSON object with "concepts" (array, at most 10) and \
"interaction_protocols" (array, at most 5). Focus on the most \
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


def build_extraction_prompt(evidence_text: str) -> str:
    if evidence_text:
        return f"Extract abstract concepts from this document:\n\n{evidence_text}"
    return "Extract abstract concepts from metadata only — no source text available."


ALLOWED_RELATIONSHIP_KINDS = {"refines", "contradicts", "prerequisite"}


@dataclass
class RelationshipResult:
    edges_created: int = 0
    edges_skipped: int = 0


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
    add_edge(conn, "extracted-from", kinv_id, evidence_id)
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
) -> str:
    fm_id = f"fm-{uuid.uuid4().hex[:12]}"
    add_node(conn, fm_id, "FailureMode", {
        "symptom": item["symptom"],
        "blast_radius": item["blast_radius"],
        "recoverability": item["recoverability"],
        "artifact_class": "abstracted-mechanism",
    })
    add_edge(conn, "triggered-by", fm_id, kinv_id)
    add_edge(conn, "extracted-from", fm_id, evidence_id)
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
    add_edge(conn, "extracted-from", proto_id, evidence_id)
    return proto_id


def build_protocol_extraction_prompt(concept_names: list[str]) -> str:
    names_list = ", ".join(concept_names)
    return (
        f"Given these kernel concepts: {names_list}\n\n"
        "Identify coordination rules that govern how these mechanisms must "
        "interact when composed together. Return a JSON array of protocols."
    )


def store_rich_concept(
    conn: sqlite3.Connection, item: dict, evidence_id: str,
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
    add_edge(conn, "extracted-from", concept_id, evidence_id)
    return concept_id


class LLMClient(Protocol):
    def create_message(
        self, model: str, system: str, user: str, max_tokens: int,
    ) -> dict[str, Any]: ...


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
    extraction_model: str = ""
    prompt_tokens: int = 0
    response_tokens: int = 0


class AnthropicClientAdapter:
    def __init__(self) -> None:
        import anthropic
        self._client = anthropic.Anthropic()

    def create_message(
        self, model: str, system: str, user: str, max_tokens: int,
    ) -> dict[str, Any]:
        response = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = response.content[0].text
        return {
            "text": text,
            "prompt_tokens": response.usage.input_tokens,
            "response_tokens": response.usage.output_tokens,
        }


def extract_concepts(
    conn: sqlite3.Connection,
    evidence_id: str,
    gate: SessionGate,
    model: str = "claude-sonnet-4-6",
    dry_run: bool = False,
    client: LLMClient | None = None,
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
        "SELECT source_id FROM edges WHERE kind = 'extracted-from' AND target_id = ?",
        (evidence_id,),
    ).fetchall()
    if existing:
        return ExtractionResult(
            evidence_id=evidence_id,
            concept_ids=[r[0] for r in existing],
            concepts_created=0,
            concepts_skipped=len(existing),
            extraction_model=model,
        )

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

    user_prompt = build_extraction_prompt(evidence_text)

    if dry_run:
        return ExtractionResult(
            evidence_id=evidence_id,
            extraction_model=model,
            prompt_tokens=len(EXTRACTION_SYSTEM_PROMPT.split()) + len(user_prompt.split()),
        )

    if client is None:
        client = AnthropicClientAdapter()

    response = client.create_message(
        model=model,
        system=EXTRACTION_SYSTEM_PROMPT,
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

    if isinstance(parsed, dict):
        concepts_data = parsed.get("concepts", [])
        protocols_data = parsed.get("interaction_protocols", [])
    elif isinstance(parsed, list):
        concepts_data = parsed
        protocols_data = []
    else:
        concepts_data = []
        protocols_data = []

    if not isinstance(concepts_data, list):
        concepts_data = []
    if not isinstance(protocols_data, list):
        protocols_data = []

    concept_ids: list[str] = []
    name_to_id: dict[str, str] = {}
    for item in concepts_data[:10]:
        validated = validate_extraction_item(item)
        if validated is None:
            continue
        concept_id = store_rich_concept(conn, validated, evidence_id)
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
            inv_id = store_kernel_invariant(conn, validated, evidence_id, name_to_id)
            if inv_id:
                invariants_created += 1
                for fm in inv.get("failure_modes", []):
                    validated_fm = validate_failure_mode_item(fm)
                    if validated_fm:
                        store_failure_mode(conn, validated_fm, evidence_id, inv_id)
                        failure_modes_created += 1

    protocols_created = 0
    for proto in protocols_data[:5]:
        validated_proto = validate_protocol_item(proto, name_to_id)
        if validated_proto is None:
            continue
        proto_id = store_interaction_protocol(conn, validated_proto, evidence_id, name_to_id)
        if proto_id:
            protocols_created += 1

    return ExtractionResult(
        evidence_id=evidence_id,
        concept_ids=concept_ids,
        subsystem_ids=subsystem_ids,
        relationships_created=rel_result.edges_created,
        invariants_created=invariants_created,
        failure_modes_created=failure_modes_created,
        protocols_created=protocols_created,
        concepts_created=len(concept_ids),
        concepts_skipped=0,
        extraction_model=model,
        prompt_tokens=response.get("prompt_tokens", 0),
        response_tokens=response.get("response_tokens", 0),
    )
