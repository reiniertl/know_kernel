"""One provider port, shared by all three LLM paths.

ANN-KK-SUMMARY-PROVIDER-SPLIT: the split this resolves.
ALG-KK-EXTRACT-CLI: --provider, authoritative and never inferred.

Until 2026-09-21 the port existed three times: in summary_extractor.py with
both adapters, and in extractor.py and claim_extractor.py with the Anthropic
half only. That is why the summary path could run on an OpenAI credential and
the two extractors could not run at all.

NOTHING HERE MAY TOUCH THE NETWORK. No test constructs a real adapter.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from graph.schema import init_db
from ingest import claim_extractor, extractor, summary_extractor
from ingest.llm_provider import (
    DEFAULT_PROVIDER,
    PROVIDERS,
    AnthropicClientAdapter,
    LLMClient,
    OpenAIClientAdapter,
    client_for,
    default_model_for,
)


# --- one port, not three ----------------------------------------------------


def test_every_path_shares_one_protocol():
    """Three copies of a Protocol is three chances for them to drift."""
    assert extractor.LLMClient is LLMClient
    assert claim_extractor.LLMClient is LLMClient
    assert summary_extractor.LLMClient is LLMClient


def test_summary_extractor_still_exports_what_its_callers_import():
    """The move was a MOVE. cli.py, cli_summaries.py and
    test_summary_extractor.py import these names from summary_extractor, and
    they must keep working without being touched."""
    for name in ("LLMClient", "AnthropicClientAdapter", "OpenAIClientAdapter",
                 "PROVIDERS", "DEFAULT_PROVIDER", "client_for",
                 "default_model_for"):
        assert getattr(summary_extractor, name) is globals()[name], name


def test_no_module_defines_its_own_adapter_any_more():
    from pathlib import Path
    repo = Path(__file__).resolve().parent.parent
    offenders = []
    for path in sorted((repo / "src").rglob("*.py")):
        if path.name == "llm_provider.py":
            continue
        text = path.read_text(encoding="utf-8")
        for marker in ("class LLMClient(Protocol)", "class AnthropicClientAdapter",
                       "class OpenAIClientAdapter"):
            if marker in text:
                offenders.append(f"{path.relative_to(repo)}: {marker}")
    assert offenders == []


# --- the offline property ---------------------------------------------------


def test_importing_the_port_imports_neither_sdk():
    """Each SDK is imported inside its adapter's __init__, never at module
    level. That is what lets the suite run with neither SDK installed and with
    no credential, which is what keeps every test offline. A top-level import
    would break that silently — nothing else would fail."""
    code = (
        "import sys; import ingest.llm_provider as m; "
        "print('anthropic' in sys.modules, 'openai' in sys.modules)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, cwd="src", check=True).stdout.strip()
    assert out == "False False"


# --- the registry -----------------------------------------------------------


def test_the_two_providers_and_their_defaults():
    assert set(PROVIDERS) == {"anthropic", "openai"}
    assert default_model_for("anthropic") == "claude-sonnet-5"
    assert default_model_for("openai") == "gpt-4o-mini"


def test_the_stale_model_id_is_gone_from_every_default():
    """extractor.py said claude-sonnet-4-6 and summary_extractor said
    claude-sonnet-5. Only one of those is a live id, and carrying both is how
    a default drifts from the model that actually answers."""
    assert extractor.DEFAULT_EXTRACTION_MODEL == "claude-sonnet-5"
    assert claim_extractor.DEFAULT_CLAIM_MODEL == "claude-sonnet-5"
    assert extractor.DEFAULT_EXTRACTION_MODEL == default_model_for(DEFAULT_PROVIDER)


@pytest.mark.parametrize("fn", [default_model_for, client_for])
def test_an_unknown_provider_fails_loudly(fn):
    with pytest.raises(ValueError, match="Unknown provider"):
        fn("gemini")


def test_the_default_provider_is_unchanged_by_this_port():
    """Nothing may start calling a different vendor silently: a run on OpenAI
    is always an explicit --provider openai, visible in the shell history."""
    assert DEFAULT_PROVIDER == "anthropic"


# --- the CLI surface --------------------------------------------------------


def _cli(monkeypatch, capsys, *argv):
    from ingest import cli_extract
    monkeypatch.setattr("sys.argv", ["kk-extract", *argv])
    with pytest.raises(SystemExit) as exc:
        cli_extract.main()
    out = capsys.readouterr().out
    return exc.value.code, (json.loads(out) if out.strip().startswith("{") else None)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "prov.db"
    init_db(path).close()
    return str(path)


def test_provider_selects_the_default_model(monkeypatch, capsys, db):
    _, report = _cli(monkeypatch, capsys, "--db", db, "--all-relink",
                     "--provider", "openai", "--dry-run")
    assert (report["provider"], report["model"]) == ("openai", "gpt-4o-mini")


def test_omitting_provider_uses_the_anthropic_default(monkeypatch, capsys, db):
    _, report = _cli(monkeypatch, capsys, "--db", db, "--all-relink", "--dry-run")
    assert (report["provider"], report["model"]) == ("anthropic", "claude-sonnet-5")


def test_naming_a_model_does_not_reroute_the_provider(monkeypatch, capsys, db):
    """The rule summary_extractor states: provider is authoritative and no
    model name is ever parsed to infer one. Asking OpenAI for a Claude model
    must reach the OpenAI adapter and fail there, loudly, rather than being
    quietly redirected to Anthropic."""
    _, report = _cli(monkeypatch, capsys, "--db", db, "--all-relink",
                     "--provider", "openai", "--model", "claude-sonnet-5",
                     "--dry-run")
    assert report["provider"] == "openai"
    assert report["model"] == "claude-sonnet-5"


def test_an_unknown_provider_is_refused_by_argparse(monkeypatch, capsys, db):
    code, _ = _cli(monkeypatch, capsys, "--db", db, "--all-relink",
                   "--provider", "gemini", "--dry-run")
    assert code == 2


def test_a_dry_run_constructs_no_client_at_all(monkeypatch, capsys, db):
    """Load-bearing: sizing a batch must work with no credential, because that
    is how anyone decides whether to pay for the real one. Each adapter builds
    its SDK client in __init__ and that raises without a key."""
    def explode(provider):
        raise AssertionError(f"a dry run constructed a {provider} client")
    monkeypatch.setattr("ingest.cli_extract.client_for", explode)
    code, report = _cli(monkeypatch, capsys, "--db", db, "--all-relink",
                        "--provider", "openai", "--dry-run")
    assert code == 0
    assert report["provider"] == "openai"


def test_a_real_run_builds_the_client_once_before_any_paper(monkeypatch, capsys, db):
    """One client for the batch, not one per paper — and constructed BEFORE
    the loop, so a missing credential fails the whole run immediately instead
    of erroring 1,321 times or leaving a half-finished corpus."""
    built = []

    class Fake:
        def create_message(self, model, system, user, max_tokens):
            return {"text": "{}", "prompt_tokens": 0, "response_tokens": 0}

    def counting(provider):
        built.append(provider)
        return Fake()

    monkeypatch.setattr("ingest.cli_extract.client_for", counting)
    code, report = _cli(monkeypatch, capsys, "--db", db, "--all-relink",
                        "--provider", "openai")
    assert built == ["openai"]
    assert report["attempted"] == 0
