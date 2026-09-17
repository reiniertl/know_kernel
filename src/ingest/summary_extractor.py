"""LLM paper summary extraction (ALG-KK-SUMMARY-EXTRACT).

Produces the whole merged artifact for one paper in ONE model call - prose
prose - and persists it at state llm-extracted.

D-15a removed the three enrichment fields key_ideas, relevance and methodology
from PaperSummary, reversing the D-9 absorption, so the prompt no longer asks for
them and the response contract no longer carries them. The call count is
unchanged: it was always one.

Prompt construction, response parsing, validation and persistence are four
separate functions, and nothing is written until the parsed response has passed
validation. A truncated or malformed reply therefore leaves the graph exactly as
it found it rather than storing a fragment.

A reply whose summary fails validation stores nothing.

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

TWO PROVIDERS, ONE PORT. LLMClient is the whole contract: create_message returns
exactly {"text", "prompt_tokens", "response_tokens"}, and each adapter normalises
its own SDK onto those three keys because the SDKs agree on none of the names.
The caller picks with --provider, which is authoritative — no model name is ever
parsed to infer a provider, so an unrecognised identifier fails loudly at the API
instead of being routed silently to the wrong SDK. See ANN-KK-SUMMARY-PROVIDER-SPLIT
for why the project runs two providers and which paths were deliberately left on
Anthropic.

EACH SDK IS IMPORTED INSIDE ITS ADAPTER'S __init__, NEVER AT MODULE LEVEL
(precedent: src/ingest/extractor.py). That is what lets this module import with
the ingest extra absent and with NEITHER SDK installed, which is in turn what lets
every test inject a fake client and make no network call. Moving either import to
the top of the file would break the suite's offline property.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
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

# Why a paper was not summarised. Reported by the batch, never stored on a node:
# a skipped paper keeps NO summary rather than one stamped "absent".
SKIP_NO_USABLE_INPUT = "no-usable-input"
SKIP_INVALID_RESPONSE = "invalid-response"

BASIS_ABSTRACT = "abstract"
BASIS_EVIDENCE = "evidence-text"

SUMMARY_PROMPT = """\
You are a research librarian for a Linux kernel development team.

Given a research paper's abstract or body text, write a short summary for a
kernel engineer deciding whether to read the paper.

Return a JSON object with one key:

"summary": "2 to 4 sentences. What the paper does, how, and what it found."

RULES:
- Summarise ONLY what the given text actually says. Do not embellish, and do
  not infer results the text does not state.
- Lead with the contribution, not with background.
- Name concrete kernel subsystems or mechanisms where the text names them.
- The summary is plain prose. No bullet points, no markdown, no heading.
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


class OpenAIClientAdapter:
    """The same port, spoken to OpenAI.

    Three normalisations, none of them optional. OpenAI has no system parameter,
    so the system prompt becomes a leading message with role "system". The reply
    text is choices[0].message.content rather than content[0].text. And the usage
    fields are prompt_tokens / completion_tokens rather than input / output. The
    dict this returns must carry exactly the three keys the Protocol names,
    because validate_summary parses response["text"] as the raw model string.
    """

    def __init__(self) -> None:
        import openai

        self._client = openai.OpenAI()

    def create_message(
        self, model: str, system: str, user: str, max_tokens: int,
    ) -> dict[str, Any]:
        response = self._client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        usage = response.usage
        return {
            # content is None rather than "" when the model returns nothing;
            # validate_summary would reject None as not-a-str, but "" is the
            # honest reading and the path it already handles.
            "text": response.choices[0].message.content or "",
            "prompt_tokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
            "response_tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
        }


# Provider is authoritative: it selects the adapter AND the default model.
# Deliberately NOT inferred from the model name — a prefix rule silently
# misroutes any identifier it does not recognise, and this codebase already
# refuses one silent-inference shortcut in INV-KK-SUMMARY-EXTRACT-INPUT-BASIS.
PROVIDERS = {
    "anthropic": (AnthropicClientAdapter, "claude-sonnet-5"),
    "openai": (OpenAIClientAdapter, "gpt-4o-mini"),
}
DEFAULT_PROVIDER = "anthropic"


def default_model_for(provider: str) -> str:
    """The model used when --model is not given. Raises on an unknown provider."""
    if provider not in PROVIDERS:
        raise ValueError(
            f"Unknown provider '{provider}'. Must be one of: " + ", ".join(sorted(PROVIDERS))
        )
    return PROVIDERS[provider][1]


def client_for(provider: str) -> LLMClient:
    """Construct the adapter for a provider. The SDK import happens here."""
    if provider not in PROVIDERS:
        raise ValueError(
            f"Unknown provider '{provider}'. Must be one of: " + ", ".join(sorted(PROVIDERS))
        )
    return PROVIDERS[provider][0]()


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



def validate_summary(parsed: dict) -> dict | None:
    """Return the validated summary, or None if the response is unusable.

    None means nothing is written. An empty "summary" is a valid response the
    prompt explicitly asks for when the text is too thin, and it is treated the
    same way as a malformed one: no summary is stored, because a summary that
    says nothing is worse than an honest absence.

    Under D-15a there is only one field to grade. An earlier revision graded three
    enrichment fields separately so that a malformed one could not sink the prose;
    those fields no longer exist on PaperSummary, so the partial-success path went
    with them.

    Returns {"summary": str}.
    """
    if not isinstance(parsed, dict):
        return None
    summary = parsed.get("summary")
    if not isinstance(summary, str):
        return None
    summary = summary.strip()
    if not (MIN_SUMMARY_CHARS <= len(summary) <= MAX_SUMMARY_CHARS):
        return None
    return {"summary": summary}


def extract_summary(
    conn: sqlite3.Connection,
    source_id: str,
    model: str = "",
    dry_run: bool = False,
    client: LLMClient | None = None,
    provider: str = DEFAULT_PROVIDER,
) -> SummaryExtraction:
    """Extract and store one paper summary (ALG-KK-SUMMARY-EXTRACT).

    Raises ValueError if `source_id` names no node or names a node that is not a
    Source. Every other failure is reported on the result rather than raised: a
    paper with no usable input, and a model reply that does not validate, both
    return stored=False having written nothing.
    """
    # Provider decides the default model; --model overrides it. Resolved here so
    # that the identifier recorded on PaperSummary.model is the one actually used.
    model = model or default_model_for(provider)

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
        client = client_for(provider)

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
    )

    result.stored = True
    result.summary_id = stored.summary_id
    result.state = stored.state
    result.text = validated["summary"]
    return result
