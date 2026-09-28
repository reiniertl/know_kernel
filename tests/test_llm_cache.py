"""The vocabulary is sent once per run, not once per call.

INV-KK-LLM-CACHE-STABLE-PREFIX: the vocabulary lives in the system prompt, so
the prefix is byte-identical across a run and the provider can cache it.
INV-KK-LLM-CACHE-REPORTED: cached-token counts come from the provider and are
surfaced, never assumed.

MEASURED 2026-09-28, which is why this exists: at 115 Concepts the vocabulary
was ~765 tokens on every one of 3,315 paper calls — 2.54M tokens per run
against 1.66M tokens of paper text. 60% of input was a constant being re-sent,
rising to 98% at 3,000 Concepts.

NOTHING HERE TOUCHES THE NETWORK. Both adapters are exercised against fake SDK
clients; no real adapter is constructed.
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from graph.concept_vocabulary import build_kernel_context, build_vocabulary_context
from graph.engine import add_node
from graph.schema import init_db
from ingest.claim_extractor import build_claim_system_prompt, build_claim_user_prompt
from ingest.doc_harvest import build_harvest_prompt, build_harvest_system_prompt
from ingest.extractor import build_extraction_prompt, get_system_prompt
from ingest.llm_provider import AnthropicClientAdapter, OpenAIClientAdapter

#: claude-sonnet-5 is DEFAULT_PROVIDER's default model and needs this many
#: tokens before an entry is created. A shorter prefix does NOT error — it
#: reports cache_creation_input_tokens 0 and costs full price forever.
SONNET_5_MINIMUM_TOKENS = 1024


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "cache.db")
    for i in range(40):
        add_node(c, f"concept-{i}", "Concept", {
            "name": f"Mechanism Number {i:02d}", "description": "d",
            "artifact_class": "abstracted-mechanism", "key_properties": [],
            "tradeoffs": [], "design_rationale": "r"})
    add_node(c, "k-1", "Kernel", {
        "name": "Linux Mainline", "description": "Upstream.",
        "kernel_type": "monolithic"})
    c.commit()
    yield c
    c.close()


# --- the vocabulary is in the prefix, the document is not -------------------


def test_the_paper_prefix_is_identical_across_papers(conn):
    """THE PROPERTY THE WHOLE CHANGE EXISTS FOR. One differing byte and the
    cache misses, silently."""
    system = get_system_prompt(
        "paper", build_vocabulary_context(conn), build_kernel_context(conn))
    assert system == get_system_prompt(
        "paper", build_vocabulary_context(conn), build_kernel_context(conn))
    first = build_extraction_prompt("PAPER ONE")
    second = build_extraction_prompt("PAPER TWO")
    assert first != second
    for text in ("Mechanism Number 00", "Linux Mainline"):
        assert text in system
        assert text not in first, "a constant is still re-sent per paper"


def test_the_discourse_prefix_carries_the_vocabulary(conn):
    """INV-KK-CLAIM-CONCEPT-CONTEXT, authored 2026-09-28 after being cited
    from claim_extractor.py:118 since the file existed."""
    voc = build_vocabulary_context(conn)
    system = build_claim_system_prompt(voc)
    user = build_claim_user_prompt("SOME DISCOURSE")
    assert "Mechanism Number 00" in system
    assert "Mechanism Number 00" not in user
    assert "SOME DISCOURSE" in user


def test_the_harvest_prefix_carries_both_vocabularies(conn):
    system = build_harvest_system_prompt("VOCABULARY BLOCK", "SUBSYSTEM BLOCK")
    # A distinctive body: HARVEST_SYSTEM_PROMPT itself contains the phrase
    # "THE DOCUMENT ITSELF", so a generic marker collides with the prompt text
    # and the assertion would be testing nothing.
    user = build_harvest_prompt("ZWKPQ UNIQUE BODY MARKER")
    assert "VOCABULARY BLOCK" in system and "SUBSYSTEM BLOCK" in system
    assert "ZWKPQ UNIQUE BODY MARKER" in user
    assert "ZWKPQ UNIQUE BODY MARKER" not in system


def test_the_context_builders_sort_so_the_prefix_is_stable(conn):
    """An unsorted set would reorder between processes and invalidate the
    prefix on every run, while looking perfectly correct in a diff. This is the
    cheapest way to lose the entire saving."""
    assert build_vocabulary_context(conn) == build_vocabulary_context(conn)
    names = build_vocabulary_context(conn).rsplit("\n", 1)[-1].split(", ")
    assert names == sorted(names)


def test_the_prefix_clears_the_minimum_that_fails_silently(conn):
    """Falling under the minimum reports cache_creation_input_tokens 0 and no
    error. The vocabulary ALONE is under it, which is why it shares a block
    with the system prompt rather than sitting in one of its own."""
    voc = build_vocabulary_context(conn)
    system = get_system_prompt("paper", voc, build_kernel_context(conn))
    assert len(system) // 4 > SONNET_5_MINIMUM_TOKENS, (
        f"prefix is ~{len(system)//4} tokens, under the {SONNET_5_MINIMUM_TOKENS} "
        "minimum — it would silently never cache")


def test_the_vocabulary_alone_would_not_have_cleared_it(conn):
    """The measured reason for the design. At 115 Concepts the real vocabulary
    was ~765 tokens against a 1,024 minimum."""
    voc = build_vocabulary_context(conn)
    assert len(voc) // 4 < SONNET_5_MINIMUM_TOKENS
    assert len(get_system_prompt("paper", voc)) // 4 > SONNET_5_MINIMUM_TOKENS


# --- the adapters (fake SDK clients, no network) ----------------------------


class _FakeAnthropic:
    def __init__(self):
        self.messages = self
        self.seen = None

    def create(self, **kwargs):
        self.seen = kwargs
        return SimpleNamespace(
            content=[SimpleNamespace(text="{}")],
            usage=SimpleNamespace(
                input_tokens=10, output_tokens=5,
                cache_read_input_tokens=2400, cache_creation_input_tokens=0),
        )


class _FakeOpenAI:
    def __init__(self):
        self.chat = SimpleNamespace(completions=self)
        self.seen = None

    def create(self, **kwargs):
        self.seen = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))],
            usage=SimpleNamespace(
                prompt_tokens=10, completion_tokens=5,
                prompt_tokens_details=SimpleNamespace(cached_tokens=2400)),
        )


def _anthropic():
    a = AnthropicClientAdapter.__new__(AnthropicClientAdapter)
    a._client = _FakeAnthropic()
    return a


def _openai():
    a = OpenAIClientAdapter.__new__(OpenAIClientAdapter)
    a._client = _FakeOpenAI()
    return a


def test_the_anthropic_adapter_marks_the_system_block_for_caching():
    """cache_control goes on a CONTENT BLOCK, which is why the adapter wraps
    the string rather than the caller doing it — the port stays
    provider-neutral and no caller learns about caching."""
    a = _anthropic()
    a.create_message(model="m", system="SYSTEM", user="USER", max_tokens=10)
    system = a._client.seen["system"]
    assert isinstance(system, list) and len(system) == 1
    assert system[0]["text"] == "SYSTEM"
    assert system[0]["cache_control"] == {"type": "ephemeral"}


def test_the_ttl_is_the_five_minute_default_not_an_hour():
    """A read refreshes the entry's timer at no cost and a corpus run is
    continuous, so five minutes stays warm throughout. The hour would double
    the write price to buy nothing."""
    a = _anthropic()
    a.create_message(model="m", system="SYSTEM", user="USER", max_tokens=10)
    assert "ttl" not in a._client.seen["system"][0]["cache_control"]


def test_the_user_message_is_never_marked_for_caching():
    """It carries the per-document text, which changes every call."""
    a = _anthropic()
    a.create_message(model="m", system="S", user="U", max_tokens=10)
    assert a._client.seen["messages"] == [{"role": "user", "content": "U"}]


@pytest.mark.parametrize("adapter", [_anthropic, _openai])
def test_both_adapters_report_cached_tokens(adapter):
    """INV-KK-LLM-CACHE-REPORTED. Before 2026-09-28 neither did, so the saving
    was unverifiable in both directions — the 18-document harvest of
    2026-09-25 may already have been getting OpenAI cache hits and the run
    report could not have shown it."""
    out = adapter().create_message(model="m", system="S", user="U", max_tokens=10)
    assert out["cached_tokens"] == 2400
    assert isinstance(out["cache_written_tokens"], int)


def test_a_provider_that_reports_nothing_yields_zero_rather_than_a_guess():
    """Read from the provider, never computed. Older SDK responses and models
    that do not cache carry no such field."""
    a = _anthropic()
    a._client.create = lambda **kw: SimpleNamespace(
        content=[SimpleNamespace(text="{}")],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5))
    assert a.create_message(model="m", system="S", user="U",
                            max_tokens=10)["cached_tokens"] == 0

    o = _openai()
    o._client.create = lambda **kw: SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5,
                              prompt_tokens_details=None))
    assert o.create_message(model="m", system="S", user="U",
                            max_tokens=10)["cached_tokens"] == 0
