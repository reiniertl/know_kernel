"""Research brief extraction from papers (ALG-KK-RESEARCH-BRIEF-EXTRACT).

Extracts per-paper research briefs (key ideas, relevance, methodology)
from Evidence text via LLM. Each paper gets at most one ResearchBrief
(INV-KK-RESEARCH-BRIEF-ONE-PER-PAPER).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from graph.engine import add_edge, add_node

log = logging.getLogger(__name__)


RESEARCH_BRIEF_PROMPT = """\
You are a research intelligence agent for a kernel development team.

Given a research paper's abstract or full text, extract a RESEARCH BRIEF
that captures what this paper contributes to kernel research.

Return a JSON object with these keys:

"key_ideas": [
    "One sentence per research idea or contribution (1-5 items)"
]

"relevance": "1-2 sentences explaining why this matters for Linux kernel
development. Be specific about which kernel subsystems or mechanisms benefit."

"methodology": "The research approach used (e.g., 'eBPF-based tracing',
'formal verification', 'hardware simulation', 'workload characterization',
'static analysis'). One phrase or short sentence."

RULES:
- Extract ONLY what the paper actually says. Do not embellish.
- key_ideas should capture the NOVEL contributions, not background.
- relevance must connect to concrete kernel areas, not vague statements.
- If the paper is not about kernel/OS topics, set relevance to
  "Not directly kernel-related" and still extract key ideas.\
"""

TITLE_ONLY_PROMPT = """\
You are a research intelligence agent for a kernel development team.

You are given ONLY the title of a research paper. Based on the title,
infer the likely research direction and extract a RESEARCH BRIEF.

Return a JSON object with these keys:

"key_ideas": [
    "One sentence per likely research contribution inferred from the title (1-3 items)"
]

"relevance": "1-2 sentences explaining why this likely matters for Linux
kernel development. Be specific about which kernel subsystems or mechanisms
may benefit."

"methodology": "The likely research approach (e.g., 'eBPF-based tracing',
'formal verification', 'performance benchmarking'). One phrase."

RULES:
- Infer conservatively from the title. Do not fabricate specifics.
- If the title gives no kernel/OS signal, set relevance to
  "Cannot determine kernel relevance from title alone".\
"""


class LLMClient(Protocol):
    def create_message(
        self, model: str, system: str, user: str, max_tokens: int,
    ) -> dict[str, Any]: ...


@dataclass
class ResearchBriefResult:
    evidence_id: str
    brief_id: str = ""
    key_ideas_count: int = 0
    concepts_linked: int = 0
    extraction_model: str = ""
    prompt_tokens: int = 0
    response_tokens: int = 0


def validate_research_brief(parsed: dict) -> dict | None:
    """Validate LLM output (INV-KK-RESEARCH-BRIEF-HAS-IDEAS)."""
    if not isinstance(parsed, dict):
        return None
    key_ideas = parsed.get("key_ideas")
    if not isinstance(key_ideas, list):
        return None
    key_ideas = [s.strip() for s in key_ideas if isinstance(s, str) and s.strip()]
    if not (1 <= len(key_ideas) <= 5):
        return None
    relevance = parsed.get("relevance", "")
    if not isinstance(relevance, str) or not relevance.strip():
        return None
    methodology = parsed.get("methodology", "")
    if not isinstance(methodology, str) or not methodology.strip():
        return None
    return {
        "key_ideas": key_ideas,
        "relevance": relevance.strip(),
        "methodology": methodology.strip(),
    }


def parse_llm_response(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        text = text.rsplit("```", 1)[0]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def extract_research_brief(
    conn: sqlite3.Connection,
    evidence_id: str,
    source_date: str,
    model: str = "claude-sonnet-4-6",
    dry_run: bool = False,
    client: LLMClient | None = None,
    source_text: str | None = None,
    paper_title: str = "",
    title_only: bool = False,
) -> ResearchBriefResult:
    """Extract a ResearchBrief from a paper's Evidence text (ALG-KK-RESEARCH-BRIEF-EXTRACT).

    INV-KK-RESEARCH-BRIEF-LINKED: creates extracted-from edge to Evidence.
    INV-KK-RESEARCH-BRIEF-ONE-PER-PAPER: caller must ensure no duplicate.
    """
    row = conn.execute(
        "SELECT id, kind, attrs FROM nodes WHERE id = ?", (evidence_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Node '{evidence_id}' does not exist")

    if source_text is None:
        attrs = json.loads(row[2]) if row[2] else {}
        source_text = attrs.get("text", "")

    if title_only or not source_text or len(source_text.strip()) < 100:
        system_prompt = TITLE_ONLY_PROMPT
        user_prompt = f"Paper title: {paper_title}" if paper_title else f"Paper title: (unknown)"
        effective_model = "claude-haiku-4-5"
    else:
        system_prompt = RESEARCH_BRIEF_PROMPT
        user_prompt = f"Paper title: {paper_title}\n\n{source_text}" if paper_title else source_text
        effective_model = model

    if dry_run:
        return ResearchBriefResult(
            evidence_id=evidence_id,
            extraction_model=effective_model,
            prompt_tokens=len(system_prompt.split()) + len(user_prompt.split()),
        )

    if client is None:
        from ingest.extractor import AnthropicClientAdapter
        client = AnthropicClientAdapter()

    response = client.create_message(
        model=effective_model,
        system=system_prompt,
        user=user_prompt,
        max_tokens=2048,
    )

    parsed = parse_llm_response(response["text"])
    validated = validate_research_brief(parsed)

    result = ResearchBriefResult(
        evidence_id=evidence_id,
        extraction_model=effective_model,
        prompt_tokens=response.get("prompt_tokens", 0),
        response_tokens=response.get("response_tokens", 0),
    )

    if validated is None:
        log.warning("Invalid LLM response for evidence %s", evidence_id)
        return result

    brief_id = f"rb-{uuid.uuid4().hex[:12]}"
    add_node(conn, brief_id, "ResearchBrief", {
        "title": paper_title or "(untitled)",
        "key_ideas": json.dumps(validated["key_ideas"]),
        "relevance": validated["relevance"],
        "methodology": validated["methodology"],
        "source_date": source_date,
        "artifact_class": "B",
    })

    add_edge(conn, "extracted-from", brief_id, evidence_id)

    concepts_linked = 0
    concept_rows = conn.execute(
        "SELECT source_id FROM edges WHERE kind = 'extracted-from' AND target_id = ? "
        "AND source_id IN (SELECT id FROM nodes WHERE kind = 'Concept')",
        (evidence_id,),
    ).fetchall()
    for (concept_id,) in concept_rows:
        add_edge(conn, "summarizes-for", brief_id, concept_id)
        concepts_linked += 1

    result.brief_id = brief_id
    result.key_ideas_count = len(validated["key_ideas"])
    result.concepts_linked = concepts_linked

    return result
