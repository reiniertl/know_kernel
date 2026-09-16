"""LLM paper summary extraction (ALG-KK-SUMMARY-EXTRACT).

Produces the whole merged artifact for one paper in ONE model call - prose
summary, key ideas, relevance and methodology - and persists it at state
llm-extracted. The three enrichment fields are the ones IFC-KK-PAPER-SUMMARY
absorbed from the retired brief kind under D-9; asking for them in the same call
is the point, because the corpus previously paid for two separate extractions to
obtain them.

Prompt construction, response parsing, validation and persistence are four
separate functions, and nothing is written until the parsed response has passed
validation. A truncated or malformed reply therefore leaves the graph exactly as
it found it rather than storing a fragment.

THE PROSE IS THE REQUIRED HALF. A reply carrying a valid summary but malformed
or missing enrichment still stores the summary, with the enrichment left unset:
a paper with prose and no key ideas beats no paper at all. A reply whose summary
itself fails validation stores nothing, enrichment included.

Persistence goes through ingest.paper_summary.set_summary — the sole writer for
PaperSummary (ALG-KK-SUMMARY-SET) — rather than writing nodes here. That is what
keeps the state vocabulary enforced in one place.

INV-KK-SUMMARY-LLM-NEVER-HUMAN-STATE. This module may write exactly one state,
llm-extracted. It never writes human-reviewed or human-authored, which assert
that a person acted; it never writes rejected, which asserts that a person
refused; and it never writes absent, because a paper it declines to summarise is
left alone rather than stamped. The ordered vocabulary of decision D-E exists so
a reader can tell a model's output from a person's, and that distinction is
worthless if the extractor can award itself a human state.

INV-KK-SUMMARY-EXTRACT-INPUT-BASIS. Operator decision, 2026-09-16, taken against
measured counts. A summary is derived only from text the paper itself produced:
its abstract, or the text of an Evidence node sourced from it and at least
MIN_INPUT_CHARS long. A paper offering neither is SKIPPED.

  Of the 343 papers with no abstract, all 343 carry a descriptive title and 180
  carry Evidence text of usable length. Falling back to the title would have
  covered every one of them, and the retired brief extractor contained a
  ready-made title-only prompt doing precisely that (recoverable from git
  history) — so the temptation to revive it here is real and foreseeable. It is
  excluded on purpose.
  A title-derived summary is an inference about a paper, not a summary of it,
  and it would be stored as llm-extracted and counted by
  IFC-KK-PAPER-COMPLETENESS as has_summary, indistinguishable from the real
  thing. The 163 papers with neither usable input keep no summary, and the
  completeness verdict reports that truthfully.

anthropic is imported lazily inside AnthropicClientAdapter.__init__ (precedent:
src/ingest/extractor.py), so this module imports with the ingest extra absent and
every test runs against an injected client with no network call.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Protocol

from ingest.paper_summary import set_summary

log = logging.getLogger(__name__)

# The one state this module may write. INV-KK-SUMMARY-LLM-NEVER-HUMAN-STATE.
EXTRACTOR_STATE = "llm-extracted"

# Shortest input worth summarising, in characters. Matches the threshold the
# retired brief extractor applied before it stopped trusting the source text.
MIN_INPUT_CHARS = 100

# Sanity floor for a returned summary. Guards against a model answering "N/A"
# or "Unable to summarise" and that being stored as a real summary.
MIN_SUMMARY_CHARS = 40
MAX_SUMMARY_CHARS = 4000

# INV-KK-SUMMARY-KEY-IDEAS-BOUNDED. The upper bound is what the retired brief
# rule enforced: a list of fifteen "key" ideas is a table of contents, not a
# distillation. The lower bound rejects an empty list asserted as an answer,
# which cannot be told apart from a model that found nothing to say.
MIN_KEY_IDEAS = 1
MAX_KEY_IDEAS = 5

# Why a paper was not summarised. Reported by the batch, never stored on a node:
# a skipped paper keeps NO summary rather than one stamped "absent".
SKIP_NO_USABLE_INPUT = "no-usable-input"
SKIP_INVALID_RESPONSE = "invalid-response"

BASIS_ABSTRACT = "abstract"
BASIS_EVIDENCE = "evidence-text"

SUMMARY_PROMPT = """\
You are a research librarian for a Linux kernel development team.

Given a research paper's abstract or body text, write a short summary for a
kernel engineer deciding whether to read the paper, and extract what the paper
contributes to kernel research.

Return a JSON object with these keys:

"summary": "2 to 4 sentences. What the paper does, how, and what it found."

"key_ideas": [
    "One sentence per research idea or contribution (1-5 items)"
]

"relevance": "1-2 sentences explaining why this matters for Linux kernel
development. Be specific about which kernel subsystems or mechanisms benefit."

"methodology": "The research approach used (e.g., 'eBPF-based tracing',
'formal verification', 'hardware simulation', 'workload characterization',
'static analysis'). One phrase or short sentence."

RULES:
- Summarise and extract ONLY what the given text actually says. Do not
  embellish, and do not infer results the text does not state.
- Lead with the contribution, not with background.
- key_ideas should capture the NOVEL contributions, not background.
- relevance must connect to concrete kernel areas, not vague statements.
- Name concrete kernel subsystems or mechanisms where the text names them.
- The summary is plain prose. No bullet points, no markdown, no heading.
- If the paper is not about kernel/OS topics, set relevance to
  "Not directly kernel-related" and still extract key ideas.
- If the text is too thin to summarise, return {"summary": ""} rather than
  guessing.\
"""


class LLMClient(Protocol):
    def create_message(
        self, model: str, system: str, user: str, max_tokens: int,
    ) -> dict[str, Any]: ...


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
        return {
            "text": response.content[0].text,
            "prompt_tokens": response.usage.input_tokens,
            "response_tokens": response.usage.output_tokens,
        }


@dataclass
class SummaryExtraction:
    """Outcome of one extraction attempt. `stored` is the only success signal."""

    source_id: str
    stored: bool = False
    summary_id: str = ""
    state: str = ""
    basis: str = ""
    text: str = ""
    model: str = ""
    prompt_tokens: int = 0
    response_tokens: int = 0
    skipped: str = ""
    # The three enrichment fields, empty when the reply did not carry them. An
    # extraction that stored prose alone is still stored=True: see validate_summary.
    key_ideas: list[str] = field(default_factory=list)
    relevance: str = ""
    methodology: str = ""


def select_input(conn: sqlite3.Connection, source_id: str) -> tuple[str, str]:
    """Choose the text to summarise. Returns (text, basis); ("", "") if none.

    Implements INV-KK-SUMMARY-EXTRACT-INPUT-BASIS: the abstract first, then the
    longest sufficiently long Evidence text, then nothing. The paper title is
    never an input, however descriptive it is.
    """
    row = conn.execute(
        "SELECT kind, json_extract(attrs, '$.abstract') FROM nodes WHERE id = ?",
        (source_id,),
    ).fetchone()
    if row is None or row[0] != "Source":
        raise ValueError(f"Source node '{source_id}' does not exist")

    abstract = (row[1] or "").strip()
    if abstract:
        return abstract, BASIS_ABSTRACT

    evidence = conn.execute(
        "SELECT json_extract(ev.attrs, '$.text') AS t FROM edges e "
        "JOIN nodes ev ON ev.id = e.source_id AND ev.kind = 'Evidence' "
        "WHERE e.kind = 'sourced-from' AND e.target_id = ? "
        "ORDER BY length(coalesce(t, '')) DESC LIMIT 1",
        (source_id,),
    ).fetchone()
    text = (evidence[0] or "").strip() if evidence else ""
    if len(text) >= MIN_INPUT_CHARS:
        return text, BASIS_EVIDENCE

    return "", ""


def parse_llm_response(text: str) -> dict:
    """Strip an optional code fence and parse JSON. Returns {} on anything else."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        text = text.rsplit("```", 1)[0]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _validate_key_ideas(raw: object) -> list[str] | None:
    """Return the cleaned key_ideas list, or None if it is unusable.

    INV-KK-SUMMARY-KEY-IDEAS-BOUNDED: 1 to 5 non-empty items. Blank strings are
    dropped before counting, so a reply padding a short list with "" is judged on
    what it actually said rather than on its length.
    """
    if not isinstance(raw, list):
        return None
    cleaned = [s.strip() for s in raw if isinstance(s, str) and s.strip()]
    if not (MIN_KEY_IDEAS <= len(cleaned) <= MAX_KEY_IDEAS):
        return None
    return cleaned


def _validate_text_field(raw: object) -> str:
    """A non-empty stripped string, or "" — the signal for "not supplied"."""
    return raw.strip() if isinstance(raw, str) and raw.strip() else ""


def validate_summary(parsed: dict) -> dict | None:
    """Return the validated fields, or None if the response is unusable.

    None means NOTHING is written, enrichment included. An empty "summary" is a
    valid response the prompt explicitly asks for when the text is too thin, and
    it is treated the same way as a malformed one: no summary is stored, because
    a summary that says nothing is worse than an honest absence.

    THE PROSE IS THE REQUIRED HALF. The three enrichment fields are graded
    separately and never sink the summary: a reply with valid prose but a
    malformed key_ideas, or with no enrichment keys at all, is a PARTIAL SUCCESS.
    The returned dict then simply omits what did not validate, and set_summary
    writes only what is present rather than storing empty placeholders — an empty
    list stored as though it were an answer would be indistinguishable from a
    model that genuinely found nothing.

    Returns keys: "summary" always; "key_ideas", "relevance" and "methodology"
    only when they validated.
    """
    if not isinstance(parsed, dict):
        return None
    summary = parsed.get("summary")
    if not isinstance(summary, str):
        return None
    summary = summary.strip()
    if not (MIN_SUMMARY_CHARS <= len(summary) <= MAX_SUMMARY_CHARS):
        return None

    validated: dict = {"summary": summary}

    key_ideas = _validate_key_ideas(parsed.get("key_ideas"))
    if key_ideas is not None:
        validated["key_ideas"] = key_ideas
    relevance = _validate_text_field(parsed.get("relevance"))
    if relevance:
        validated["relevance"] = relevance
    methodology = _validate_text_field(parsed.get("methodology"))
    if methodology:
        validated["methodology"] = methodology
    return validated


def extract_summary(
    conn: sqlite3.Connection,
    source_id: str,
    model: str = "claude-sonnet-5",
    dry_run: bool = False,
    client: LLMClient | None = None,
) -> SummaryExtraction:
    """Extract and store one paper summary (ALG-KK-SUMMARY-EXTRACT).

    Raises ValueError if `source_id` names no node or names a node that is not a
    Source. Every other failure is reported on the result rather than raised: a
    paper with no usable input, and a model reply that does not validate, both
    return stored=False having written nothing.
    """
    text, basis = select_input(conn, source_id)
    if not basis:
        return SummaryExtraction(source_id=source_id, skipped=SKIP_NO_USABLE_INPUT)

    if dry_run:
        return SummaryExtraction(
            source_id=source_id,
            basis=basis,
            model=model,
            prompt_tokens=len(SUMMARY_PROMPT.split()) + len(text.split()),
        )

    if client is None:
        client = AnthropicClientAdapter()

    response = client.create_message(
        model=model, system=SUMMARY_PROMPT, user=text, max_tokens=1024,
    )

    result = SummaryExtraction(
        source_id=source_id,
        basis=basis,
        model=model,
        prompt_tokens=response.get("prompt_tokens", 0),
        response_tokens=response.get("response_tokens", 0),
    )

    validated = validate_summary(parse_llm_response(response.get("text", "")))
    if validated is None:
        log.warning("Invalid LLM summary response for source %s", source_id)
        result.skipped = SKIP_INVALID_RESPONSE
        return result

    # INV-KK-SUMMARY-LLM-NEVER-HUMAN-STATE: the state is the module constant,
    # never a parameter and never taken from the model's reply.
    stored = set_summary(
        conn,
        source_id,
        validated["summary"],
        EXTRACTOR_STATE,
        model=model,
        key_ideas=validated.get("key_ideas"),
        relevance=validated.get("relevance", ""),
        methodology=validated.get("methodology", ""),
    )

    result.stored = True
    result.summary_id = stored.summary_id
    result.state = stored.state
    result.text = validated["summary"]
    result.key_ideas = validated.get("key_ideas", [])
    result.relevance = validated.get("relevance", "")
    result.methodology = validated.get("methodology", "")
    return result
