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
- description: An abstract description of the mechanism or idea (1-3 sentences, \
your own words, no verbatim copying)
- subsystem: The kernel subsystem this concept belongs to (e.g., "Virtual Memory", \
"Scheduler", "Filesystem", "IPC", "Networking", "Device Drivers", "Security")

Return a JSON array of objects with "name", "description", and "subsystem" fields.
Extract at most 10 concepts per document. Focus on the most significant ideas.\
"""

CONCEPT_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "description": {"type": "string"},
            "subsystem": {"type": "string"},
        },
        "required": ["name", "description", "subsystem"],
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

    user_prompt = f"Extract abstract concepts from this document:\n\n{evidence_text}" if evidence_text else f"Extract abstract concepts from Evidence node {evidence_id} (no text available â€” produce concepts from metadata only)."

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
        concepts_data = json.loads(text)
    except (json.JSONDecodeError, KeyError, IndexError):
        concepts_data = []

    if not isinstance(concepts_data, list):
        concepts_data = []

    concept_ids: list[str] = []
    for item in concepts_data[:10]:
        if not isinstance(item, dict) or "name" not in item or "description" not in item:
            continue

        concept_id = f"concept-{uuid.uuid4().hex[:12]}"
        add_node(conn, concept_id, "Concept", {
            "name": item["name"],
            "description": item["description"],
            "artifact_class": "abstracted-mechanism",
        })
        add_edge(conn, "extracted-from", concept_id, evidence_id)
        concept_ids.append(concept_id)

    subsystem_ids: list[str] = []
    if concept_ids:
        from ingest.classifier import assign_subsystems, parse_classification_labels

        classifications = parse_classification_labels(concepts_data[:10], concept_ids)
        class_result = assign_subsystems(conn, concept_ids, classifications)
        subsystem_ids = list(set(class_result.concept_subsystem_map.values()))

    return ExtractionResult(
        evidence_id=evidence_id,
        concept_ids=concept_ids,
        subsystem_ids=subsystem_ids,
        concepts_created=len(concept_ids),
        concepts_skipped=0,
        extraction_model=model,
        prompt_tokens=response.get("prompt_tokens", 0),
        response_tokens=response.get("response_tokens", 0),
    )
