"""The one LLM provider port (ANN-KK-SUMMARY-PROVIDER-SPLIT, resolved).

LLMClient is the whole contract: create_message returns exactly
{"text", "prompt_tokens", "response_tokens"}, and each adapter normalises its
own SDK onto those three keys because the SDKs agree on none of the names.

WHY THIS MODULE EXISTS. Until 2026-09-21 these definitions lived in
ingest/summary_extractor.py, and ingest/extractor.py carried its OWN LLMClient
and AnthropicClientAdapter — the same two shapes, minus the OpenAI half. That
is why the summary path could run on an OpenAI credential and the concept
extractor could not run at all. ANN-KK-SUMMARY-PROVIDER-SPLIT called the split
temporary and named its own resolution: "convert the remaining two paths to the
same provider port this one now uses". This is that port, moved here so neither
caller owns it and no third copy has to be written.

The move is a MOVE. summary_extractor re-exports every name below, so its
callers and tests import exactly what they imported before.

EACH SDK IS IMPORTED INSIDE ITS ADAPTER'S __init__, NEVER AT MODULE LEVEL. That
is what lets this module import with neither SDK installed, which is in turn
what lets every test inject a fake client and make no network call. Moving
either import to the top of the file would break the suite's offline property.

The caller picks with --provider, which is AUTHORITATIVE — no model name is
ever parsed to infer a provider, so an unrecognised identifier fails loudly at
the API instead of being routed silently to the wrong SDK.
"""

from __future__ import annotations

from typing import Any, Protocol


class LLMClient(Protocol):
    """The provider port. UNCHANGED BY THE 2026-09-28 CACHING WORK, deliberately.

    Prompt caching is provider-specific — Anthropic needs cache_control on a
    content block, OpenAI does it automatically — and both are satisfiable
    inside the adapters, which already receive the system string. Widening this
    signature to carry structured content or a cache flag was considered and
    refused: it would encode a provider concept into a provider-neutral port
    and break all eight test doubles, for no behaviour the adapters cannot
    reach on their own. Operator decision 2026-09-28.

    Returns a dict carrying text, prompt_tokens, response_tokens, and — since
    2026-09-28, per INV-KK-LLM-CACHE-REPORTED — cached_tokens and
    cache_written_tokens, both read from the provider's own usage report.
    """

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
        # INV-KK-LLM-CACHE-STABLE-PREFIX. The system prompt carries the
        # vocabulary and is byte-identical across every call of a run, so it is
        # the cacheable prefix. cache_control goes on a CONTENT BLOCK, which is
        # why the string is wrapped here rather than at the call site — the
        # port stays provider-neutral and no caller learns about caching.
        #
        # ALWAYS ON, by operator decision 2026-09-28. This project's traffic is
        # batch by construction: a corpus run is thousands of calls sharing one
        # prefix. Break-even is two requests (write 1.25x, read 0.1x), so a
        # one-off call pays 25% more on the system portion and every batch
        # saves about 90%. A prefix under the model's minimum simply does not
        # cache — no error, no charge.
        #
        # The 5-minute TTL is deliberate over "1h". A read refreshes the entry's
        # timer at no cost and a corpus run is continuous, so five minutes stays
        # warm for the whole run; the hour would double the write price to buy
        # nothing.
        response = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=[{
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user}],
        )
        usage = response.usage
        return {
            "text": response.content[0].text,
            "prompt_tokens": usage.input_tokens,
            "response_tokens": usage.output_tokens,
            # INV-KK-LLM-CACHE-REPORTED. Read from the provider, never computed.
            # A zero across repeated calls that share a prefix means something
            # is invalidating it, and every cause is silent.
            "cached_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
            "cache_written_tokens": getattr(
                usage, "cache_creation_input_tokens", 0) or 0,
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
        # INV-KK-LLM-CACHE-REPORTED, fourth normalisation. OpenAI caches
        # automatically once a stable prefix leads the request — there is no
        # flag to set — and reports the hit nested under
        # prompt_tokens_details.cached_tokens rather than at the top level.
        # BEFORE 2026-09-28 THIS WAS NOT READ AT ALL, so the 18-document
        # harvest of 2026-09-25 may already have been getting cache hits and
        # the run report could not have shown it either way.
        details = getattr(usage, "prompt_tokens_details", None) if usage else None
        return {
            # content is None rather than "" when the model returns nothing;
            # validate_summary would reject None as not-a-str, but "" is the
            # honest reading and the path it already handles.
            "text": response.choices[0].message.content or "",
            "prompt_tokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
            "response_tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
            "cached_tokens": getattr(details, "cached_tokens", 0) or 0 if details else 0,
            # OpenAI does not distinguish a cache write; the port reports 0
            # rather than inventing a number, which is what "read from the
            # provider, never computed" means.
            "cache_written_tokens": 0,
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
