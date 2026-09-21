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
