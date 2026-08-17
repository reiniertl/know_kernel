"""Tests for the abstract fetcher (ALG-KK-ABSTRACT-FETCH{,-BATCH}).

Every test is offline. Network access goes through an injected `fetch`
callable; no test may open a socket. A route asked for a url the fixture does
not know raises, which is how an unexpected call is caught rather than silently
becoming a miss.

INV-KK-ABSTRACT-SOURCE-ENUM, INV-KK-ABSTRACT-PROVENANCE-RECORDED and
INV-KK-ABSTRACT-MANUAL-PRESERVED each have coverage below.
"""

from __future__ import annotations

import json

import pytest

from graph.engine import add_node, get_node
from graph.schema import init_db
from ingest.abstract_fetcher import (
    MIN_PLAUSIBLE_ABSTRACT_CHARS,
    Identifier,
    fetch_abstract,
    fetch_via_arxiv,
    fetch_via_openalex,
    is_plausible,
    reconstruct_inverted_index,
    resolve_identifier,
)
from ingest.cli_abstracts import candidate_source_ids, run_batch
from ingest.source_abstract import VALID_ABSTRACT_SOURCES, set_abstract


ARXIV_ID = "2401.12345"
DOI = "10.1145/3694715.3695964"

# Long enough to clear the plausibility gate.
REAL_ABSTRACT = (
    "We present Ringleader, a lock-free ring buffer that bounds producer "
    "latency under sustained multi-socket contention. Existing designs serialise "
    "producers behind a shared tail pointer, which collapses under NUMA cache "
    "line bouncing once the producer count exceeds the socket count. Ringleader "
    "partitions the tail into per-socket claims reconciled lazily by the "
    "consumer, trading a small amount of consumer work for a large reduction in "
    "cross-socket traffic. We evaluate on a 128-core four-socket machine and "
    "report a 3.1x throughput improvement at 64 producers with no regression at "
    "low producer counts."
)

ARXIV_ATOM = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/{ARXIV_ID}v1</id>
    <title>Ringleader: Bounded-Latency Lock-Free Ring Buffers</title>
    <summary>{REAL_ABSTRACT}</summary>
  </entry>
</feed>
"""

ARXIV_ATOM_EMPTY = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>
"""


def _inverted(text: str) -> dict:
    """Build an OpenAlex-style inverted index from plain text."""
    index: dict[str, list[int]] = {}
    for position, word in enumerate(text.split()):
        index.setdefault(word, []).append(position)
    return index


def _openalex_body(text: str | None) -> bytes:
    payload = {"abstract_inverted_index": _inverted(text) if text else None}
    return json.dumps(payload).encode()


class FakeFetch:
    """Dict-backed fetch. Unknown urls raise, so stray calls are visible."""

    def __init__(self, responses: dict[str, bytes]):
        self.responses = responses
        self.calls: list[str] = []

    def __call__(self, url: str, headers: dict) -> bytes:
        self.calls.append(url)
        for key, body in self.responses.items():
            if key in url:
                if isinstance(body, Exception):
                    raise body
                return body
        raise AssertionError(f"unexpected fetch: {url}")


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "fetcher.db")
    add_node(c, "src-arxiv", "Source", {
        "url": f"https://arxiv.org/abs/{ARXIV_ID}",
        "source_type": "preprint", "license": "MIT", "title": "Ringleader",
    })
    add_node(c, "src-doi", "Source", {
        "url": f"https://dl.acm.org/doi/{DOI}",
        "source_type": "conference-paper", "license": "MIT", "title": "A Conf Paper",
    })
    add_node(c, "src-blog", "Source", {
        "url": "https://someone.example/notes/osdi25-reading-notes",
        "source_type": "conference-paper", "license": "MIT", "title": "OSDI Paper",
    })
    add_node(c, "sub-1", "Subsystem", {"name": "Scheduler"})
    c.commit()
    yield c
    c.close()


# --- resolver ----------------------------------------------------------------


@pytest.mark.parametrize("url,expected", [
    (f"https://arxiv.org/abs/{ARXIV_ID}", ARXIV_ID),
    (f"https://arxiv.org/pdf/{ARXIV_ID}", ARXIV_ID),
    (f"http://arxiv.org/abs/{ARXIV_ID}v2", f"{ARXIV_ID}v2"),
    ("https://arxiv.org/abs/2401.1234", "2401.1234"),
])
def test_resolver_finds_arxiv_id(url, expected):
    identifier = resolve_identifier(url)
    assert identifier == Identifier(kind="arxiv", value=expected)


def test_resolver_finds_doi():
    identifier = resolve_identifier(f"https://dl.acm.org/doi/{DOI}")
    assert identifier == Identifier(kind="doi", value=DOI)


def test_resolver_strips_trailing_period_from_doi():
    assert resolve_identifier(f"https://doi.org/{DOI}.").value == DOI


def test_resolver_reports_which_identifier_kind_it_found():
    """The kind is what makes a wrong pull diagnosable afterwards."""
    assert resolve_identifier(f"https://arxiv.org/abs/{ARXIV_ID}").kind == "arxiv"
    assert resolve_identifier(f"https://doi.org/{DOI}").kind == "doi"


def test_resolver_finds_nothing_in_a_third_party_url():
    """A reading-notes blog url must not resolve to anything.

    This is the data-quality hazard: one OSDI Source points at a third-party
    write-up. Resolving nothing is correct — it leaves the paper for the manual
    editor instead of attaching someone else's abstract.
    """
    assert resolve_identifier("https://someone.example/notes/osdi25-reading-notes") is None


def test_resolver_ignores_a_bare_year_like_number():
    """The dropped loose fallback would have matched this and pulled a wrong paper."""
    assert resolve_identifier("https://blog.example/2024.12345/my-notes") is None


def test_resolver_handles_missing_url():
    assert resolve_identifier(None) is None
    assert resolve_identifier("") is None


# --- arXiv Atom parsing ------------------------------------------------------


def test_arxiv_route_parses_summary_verbatim():
    fetch = FakeFetch({"export.arxiv.org": ARXIV_ATOM.encode()})
    result = fetch_via_arxiv(Identifier("arxiv", ARXIV_ID), fetch)
    assert result is not None
    text, label = result
    assert label == "arxiv"
    assert text == REAL_ABSTRACT
    assert ARXIV_ID in fetch.calls[0]


def test_arxiv_route_collapses_whitespace():
    atom = ARXIV_ATOM.replace(
        "We present Ringleader", "We\n   present\tRingleader",
    )
    result = fetch_via_arxiv(Identifier("arxiv", ARXIV_ID), FakeFetch({"arxiv": atom.encode()}))
    assert result[0].startswith("We present Ringleader")


def test_arxiv_route_returns_none_on_empty_feed():
    fetch = FakeFetch({"arxiv": ARXIV_ATOM_EMPTY.encode()})
    assert fetch_via_arxiv(Identifier("arxiv", ARXIV_ID), fetch) is None


def test_arxiv_route_returns_none_on_network_error():
    fetch = FakeFetch({"arxiv": OSError("connection reset")})
    assert fetch_via_arxiv(Identifier("arxiv", ARXIV_ID), fetch) is None


def test_arxiv_route_returns_none_on_malformed_xml():
    fetch = FakeFetch({"arxiv": b"<not-xml"})
    assert fetch_via_arxiv(Identifier("arxiv", ARXIV_ID), fetch) is None


def test_arxiv_route_declines_a_doi_identifier():
    assert fetch_via_arxiv(Identifier("doi", DOI), FakeFetch({})) is None


# --- OpenAlex inverted-index reconstruction ----------------------------------


def test_inverted_index_reconstruction_restores_word_order():
    text = "the quick brown fox jumps over the lazy dog"
    assert reconstruct_inverted_index(_inverted(text)) == text


def test_inverted_index_reconstruction_handles_repeated_words():
    """A word at several positions must land at every one of them."""
    text = "a b a c a"
    index = _inverted(text)
    assert index["a"] == [0, 2, 4]
    assert reconstruct_inverted_index(index) == text


def test_inverted_index_reconstruction_handles_non_contiguous_positions():
    assert reconstruct_inverted_index({"beta": [10], "alpha": [2]}) == "alpha beta"


def test_inverted_index_reconstruction_returns_none_when_absent():
    assert reconstruct_inverted_index(None) is None
    assert reconstruct_inverted_index({}) is None


def test_openalex_route_reconstructs_by_doi():
    fetch = FakeFetch({"api.openalex.org": _openalex_body(REAL_ABSTRACT)})
    result = fetch_via_openalex(Identifier("doi", DOI), fetch)
    assert result == (REAL_ABSTRACT, "openalex")
    assert f"doi:{DOI}" in fetch.calls[0]


def test_openalex_route_reaches_arxiv_papers_through_the_arxiv_doi_prefix():
    fetch = FakeFetch({"api.openalex.org": _openalex_body(REAL_ABSTRACT)})
    result = fetch_via_openalex(Identifier("arxiv", f"{ARXIV_ID}v3"), fetch)
    assert result[1] == "openalex"
    # The version suffix is not part of the registered DOI.
    assert f"10.48550/arXiv.{ARXIV_ID}" in fetch.calls[0]
    assert "v3" not in fetch.calls[0]


def test_openalex_route_returns_none_when_index_missing():
    fetch = FakeFetch({"api.openalex.org": _openalex_body(None)})
    assert fetch_via_openalex(Identifier("doi", DOI), fetch) is None


def test_openalex_route_returns_none_on_http_error():
    fetch = FakeFetch({"api.openalex.org": OSError("429")})
    assert fetch_via_openalex(Identifier("doi", DOI), fetch) is None


# --- plausibility gate -------------------------------------------------------


def test_plausibility_gate_rejects_short_text():
    assert not is_plausible("Abstract not available.")
    assert not is_plausible("")
    assert not is_plausible(None)


def test_plausibility_gate_accepts_a_real_abstract():
    assert is_plausible(REAL_ABSTRACT)


def test_plausibility_gate_boundary():
    assert is_plausible("x" * MIN_PLAUSIBLE_ABSTRACT_CHARS)
    assert not is_plausible("x" * (MIN_PLAUSIBLE_ABSTRACT_CHARS - 1))


def test_short_result_leaves_the_source_untouched(conn):
    """A placeholder is discarded, not stored."""
    stub = ARXIV_ATOM.replace(REAL_ABSTRACT, "Abstract not available.")
    fetch = FakeFetch({
        "export.arxiv.org": stub.encode(),
        "api.openalex.org": _openalex_body(None),
    })
    result = fetch_abstract(conn, "src-arxiv", fetch=fetch)
    assert not result.stored
    assert result.reason == "no-plausible-result"

    attrs = get_node(conn, "src-arxiv")["attrs"]
    assert "abstract" not in attrs
    assert "abstract_source" not in attrs


# --- route order and fallback ------------------------------------------------


def test_arxiv_is_preferred_over_openalex(conn):
    """arXiv text is verbatim, so it wins when both routes could answer."""
    fetch = FakeFetch({
        "export.arxiv.org": ARXIV_ATOM.encode(),
        "api.openalex.org": _openalex_body("something else entirely " * 30),
    })
    result = fetch_abstract(conn, "src-arxiv", fetch=fetch)
    assert result.stored
    assert result.abstract_source == "arxiv"
    assert get_node(conn, "src-arxiv")["attrs"]["abstract"] == REAL_ABSTRACT


def test_falls_back_to_openalex_when_arxiv_misses(conn):
    fetch = FakeFetch({
        "export.arxiv.org": ARXIV_ATOM_EMPTY.encode(),
        "api.openalex.org": _openalex_body(REAL_ABSTRACT),
    })
    result = fetch_abstract(conn, "src-arxiv", fetch=fetch)
    assert result.stored
    assert result.abstract_source == "openalex"
    assert len(fetch.calls) == 2


def test_doi_source_uses_openalex_only(conn):
    """No Crossref route, and arXiv cannot answer a DOI."""
    fetch = FakeFetch({"api.openalex.org": _openalex_body(REAL_ABSTRACT)})
    result = fetch_abstract(conn, "src-doi", fetch=fetch)
    assert result.stored
    assert result.abstract_source == "openalex"
    assert result.identifier_kind == "doi"
    assert all("crossref" not in c for c in fetch.calls)


def test_unresolvable_source_makes_no_network_call(conn):
    fetch = FakeFetch({})
    result = fetch_abstract(conn, "src-blog", fetch=fetch)
    assert not result.stored
    assert result.reason == "no-identifier"
    assert fetch.calls == []


def test_fetch_abstract_rejects_non_source_node(conn):
    with pytest.raises(ValueError, match="does not exist"):
        fetch_abstract(conn, "sub-1", fetch=FakeFetch({}))


def test_fetch_abstract_rejects_missing_node(conn):
    with pytest.raises(ValueError, match="does not exist"):
        fetch_abstract(conn, "no-such-id", fetch=FakeFetch({}))


# --- INV-KK-ABSTRACT-PROVENANCE-RECORDED ------------------------------------


def test_every_stored_abstract_records_provenance(conn):
    fetch = FakeFetch({
        "export.arxiv.org": ARXIV_ATOM.encode(),
        "api.openalex.org": _openalex_body(REAL_ABSTRACT),
    })
    for source_id in ("src-arxiv", "src-doi"):
        fetch_abstract(conn, source_id, fetch=fetch)
        attrs = get_node(conn, source_id)["attrs"]
        assert attrs["abstract"].strip()
        assert attrs["abstract_source"].strip()
        assert attrs["abstract_fetched_at"].strip()


def test_recorded_provenance_is_always_in_the_enum(conn):
    """INV-KK-ABSTRACT-SOURCE-ENUM."""
    fetch = FakeFetch({
        "export.arxiv.org": ARXIV_ATOM.encode(),
        "api.openalex.org": _openalex_body(REAL_ABSTRACT),
    })
    for source_id in ("src-arxiv", "src-doi"):
        result = fetch_abstract(conn, source_id, fetch=fetch)
        assert result.abstract_source in VALID_ABSTRACT_SOURCES
        assert get_node(conn, source_id)["attrs"]["abstract_source"] in VALID_ABSTRACT_SOURCES


def test_no_route_emits_the_pdf_label_yet(conn):
    """pdf is declared in the enum but no route produces it in this change."""
    fetch = FakeFetch({
        "export.arxiv.org": ARXIV_ATOM.encode(),
        "api.openalex.org": _openalex_body(REAL_ABSTRACT),
    })
    labels = set()
    for source_id in ("src-arxiv", "src-doi"):
        result = fetch_abstract(conn, source_id, fetch=fetch)
        if result.abstract_source:
            labels.add(result.abstract_source)
    assert labels == {"arxiv", "openalex"}
    assert "pdf" not in labels


# --- INV-KK-ABSTRACT-MANUAL-PRESERVED ---------------------------------------


def test_fetch_declines_to_overwrite_a_manual_abstract(conn):
    typed = "This abstract was typed by a human because no API had it. " * 6
    set_abstract(conn, "src-arxiv", typed, "manual")

    fetch = FakeFetch({})  # any call at all is a failure here
    result = fetch_abstract(conn, "src-arxiv", fetch=fetch)

    assert not result.stored
    assert result.reason == "manual-preserved"
    assert fetch.calls == []

    attrs = get_node(conn, "src-arxiv")["attrs"]
    assert attrs["abstract"] == typed.strip()
    assert attrs["abstract_source"] == "manual"


def test_fetch_does_replace_a_machine_abstract(conn):
    """Preservation is specific to manual — a stale fetched value is refreshable."""
    set_abstract(conn, "src-arxiv", "old " * 100, "openalex")
    fetch = FakeFetch({"export.arxiv.org": ARXIV_ATOM.encode()})
    result = fetch_abstract(conn, "src-arxiv", fetch=fetch)
    assert result.stored
    assert get_node(conn, "src-arxiv")["attrs"]["abstract"] == REAL_ABSTRACT


def test_manual_sources_never_enter_the_candidate_set(conn):
    set_abstract(conn, "src-arxiv", "Typed by hand. " * 20, "manual")
    assert "src-arxiv" not in candidate_source_ids(conn)


# --- batch (ALG-KK-ABSTRACT-FETCH-BATCH) ------------------------------------


def test_candidate_set_is_sources_lacking_an_abstract(conn):
    assert candidate_source_ids(conn) == ["src-arxiv", "src-blog", "src-doi"]


def test_candidate_set_honours_limit(conn):
    assert candidate_source_ids(conn, limit=2) == ["src-arxiv", "src-blog"]


def test_batch_reports_per_route_counts_and_failures(conn):
    fetch = FakeFetch({
        "export.arxiv.org": ARXIV_ATOM.encode(),
        "api.openalex.org": _openalex_body(REAL_ABSTRACT),
    })
    slept: list[float] = []
    report = run_batch(conn, fetch=fetch, sleep=slept.append)

    assert report.considered == 3
    assert report.stored == 2
    assert report.by_route == {"arxiv": 1, "openalex": 1}
    assert report.failures == {"no-identifier": 1}


def test_batch_records_which_identifier_each_abstract_came_from(conn):
    """Diagnosability for the wrong-url hazard."""
    fetch = FakeFetch({
        "export.arxiv.org": ARXIV_ATOM.encode(),
        "api.openalex.org": _openalex_body(REAL_ABSTRACT),
    })
    report = run_batch(conn, fetch=fetch, sleep=lambda s: None)
    detail = {d["source_id"]: d for d in report.stored_detail}
    assert detail["src-arxiv"]["identifier_kind"] == "arxiv"
    assert detail["src-arxiv"]["identifier_value"] == ARXIV_ID
    assert detail["src-doi"]["identifier_kind"] == "doi"
    assert detail["src-doi"]["identifier_value"] == DOI


def test_batch_rate_limits_per_route(conn):
    fetch = FakeFetch({
        "export.arxiv.org": ARXIV_ATOM.encode(),
        "api.openalex.org": _openalex_body(REAL_ABSTRACT),
    })
    slept: list[float] = []
    run_batch(conn, fetch=fetch, sleep=slept.append)
    assert 3.0 in slept   # arXiv
    assert 0.5 in slept   # OpenAlex
    # The unresolvable Source makes no call, so it earns no pause.
    assert len(slept) == 2


def test_batch_commits_each_abstract_so_an_interrupted_run_keeps_progress(conn, tmp_path):
    """Resumability: stop mid-run and the stored abstracts survive."""
    class ExplodingFetch(FakeFetch):
        def __call__(self, url, headers):
            if "openalex" in url:
                raise KeyboardInterrupt("operator stopped the run")
            return super().__call__(url, headers)

    fetch = ExplodingFetch({"export.arxiv.org": ARXIV_ATOM.encode()})
    with pytest.raises(KeyboardInterrupt):
        run_batch(conn, fetch=fetch, sleep=lambda s: None)

    # src-arxiv was committed before the interrupt reached src-doi.
    import sqlite3
    fresh = sqlite3.connect(conn.execute("PRAGMA database_list").fetchone()[2])
    fresh.row_factory = sqlite3.Row
    row = fresh.execute("SELECT attrs FROM nodes WHERE id = 'src-arxiv'").fetchone()
    fresh.close()
    assert REAL_ABSTRACT in row[0]


def test_batch_is_resumable_across_runs(conn):
    fetch = FakeFetch({
        "export.arxiv.org": ARXIV_ATOM.encode(),
        "api.openalex.org": _openalex_body(REAL_ABSTRACT),
    })
    first = run_batch(conn, fetch=fetch, sleep=lambda s: None, limit=1)
    assert first.stored == 1

    second = run_batch(conn, fetch=fetch, sleep=lambda s: None)
    # src-arxiv landed in run one, so run two no longer considers it.
    assert second.considered == 2
    assert "src-arxiv" not in [d["source_id"] for d in second.stored_detail]


def test_batch_dry_run_makes_no_network_call_and_writes_nothing(conn):
    fetch = FakeFetch({})
    report = run_batch(conn, fetch=fetch, sleep=lambda s: None, dry_run=True)

    assert fetch.calls == []
    assert report.considered == 3
    assert report.stored == 0
    assert report.failures == {"arxiv": 1, "doi": 1, "no-identifier": 1}
    assert "abstract" not in get_node(conn, "src-arxiv")["attrs"]


def test_batch_limit_bounds_the_run(conn):
    fetch = FakeFetch({
        "export.arxiv.org": ARXIV_ATOM.encode(),
        "api.openalex.org": _openalex_body(REAL_ABSTRACT),
    })
    report = run_batch(conn, fetch=fetch, sleep=lambda s: None, limit=1)
    assert report.considered == 1
