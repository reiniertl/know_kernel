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
    ContainerRecordFound,
    MIN_PLAUSIBLE_CHARS_BY_ROUTE,
    RouteTransportError,
    TITLE_SEARCH_MATCH_FLOOR,
    is_plausible,
    titles_match_closely,
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


def test_arxiv_route_raises_on_network_error():
    """Previously returned None, which made a dead transport indistinguishable
    from a paper with no abstract. export.arxiv.org returns HTTP 406 to this
    environment for every request, and the batch reported it as a missing
    abstract."""
    fetch = FakeFetch({"arxiv": OSError("connection reset")})
    with pytest.raises(RouteTransportError) as exc:
        fetch_via_arxiv(Identifier("arxiv", ARXIV_ID), fetch)
    assert exc.value.route == "arxiv"


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


def test_openalex_route_raises_on_http_error():
    fetch = FakeFetch({"api.openalex.org": OSError("429")})
    with pytest.raises(RouteTransportError) as exc:
        fetch_via_openalex(Identifier("doi", DOI), fetch)
    assert exc.value.route == "openalex"


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
    assert result.reason == "abstract-too-short"

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


def test_an_unresolvable_source_now_falls_through_to_a_title_search(conn):
    """CONTRACT CHANGE, 2026-09-18. This asserted that a Source with no
    identifier made NO network call at all. That guarantee was traded
    deliberately: 323 papers carry a venue landing page with no arXiv id and no
    DOI, and the title is the only query left. The protection is no longer
    "never ask" but the 0.80 title match and the venue check in search_by_title.
    """
    fetch = FakeFetch({"api.openalex.org": b'{"results": []}'})
    result = fetch_abstract(conn, "src-blog", fetch=fetch)
    assert not result.stored
    assert result.reason == "no-title-match"
    assert fetch.calls, "the title search should have been attempted"


def test_a_source_with_neither_identifier_nor_title_asks_nothing(conn):
    """no-identifier now means 'nothing to search with', which is distinct from
    'the search ran and found nothing'."""
    add_node(conn, "src-bare", "Source", {
        "url": "https://someone.example/notes", "source_type": "conference-paper",
        "license": "MIT", "title": "",
    })
    fetch = FakeFetch({})
    result = fetch_abstract(conn, "src-bare", fetch=fetch)
    assert result.reason == "no-identifier"
    assert not fetch.calls, "nothing to ask with, so nothing should be asked"

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
    # src-blog has no identifier, so it now falls through to a title search
    # rather than stopping at no-identifier (contract change, 2026-09-18).
    assert report.failures == {"no-title-match": 1}


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
    # src-blog has no identifier but does have a title, so a real run would
    # attempt a title search on it (2026-09-18). The dry run says so without
    # asking, which is what makes it useful.
    assert report.failures == {"arxiv": 1, "doi": 1, "would-title-search": 1}
    assert "abstract" not in get_node(conn, "src-arxiv")["attrs"]


def test_batch_limit_bounds_the_run(conn):
    fetch = FakeFetch({
        "export.arxiv.org": ARXIV_ATOM.encode(),
        "api.openalex.org": _openalex_body(REAL_ABSTRACT),
    })
    report = run_batch(conn, fetch=fetch, sleep=lambda s: None, limit=1)
    assert report.considered == 1


# --- the failure taxonomy ----------------------------------------------------
#
# Before 2026-09-18 every non-success collapsed into "no-plausible-result". A
# 406 from arXiv, a Source carrying a proceedings-volume DOI, and a genuinely
# abstract-less paper all reported identically, so a broken transport read as
# missing data. These pin the codes apart.


def test_transport_failure_and_empty_result_get_different_codes(conn):
    dead = FakeFetch({"arxiv": OSError("406"), "api.openalex.org": OSError("406")})
    assert fetch_abstract(conn, "src-arxiv", fetch=dead).reason == "transport-error"

    empty = FakeFetch({
        "export.arxiv.org": ARXIV_ATOM_EMPTY.encode(),
        "api.openalex.org": _openalex_body(None),
    })
    assert fetch_abstract(conn, "src-doi", fetch=empty).reason == "no-abstract-in-record"


def test_a_declining_route_does_not_mask_a_transport_failure(conn):
    """src-doi carries a DOI, so the arXiv route declines it outright. That
    decline must not be counted as evidence about the paper — otherwise it
    outranks OpenAlex's dead transport and reports a missing abstract for a
    connection that never answered."""
    fetch = FakeFetch({"api.openalex.org": OSError("406")})
    assert fetch_abstract(conn, "src-doi", fetch=fetch).reason == "transport-error"


def test_a_container_doi_is_not_reported_as_not_found(conn):
    """A proceedings-volume DOI RESOLVES; the answer is just about the wrong
    document. Saying "not found" sends the reader after the API instead of after
    the Source's DOI, which is where the fault actually is."""
    import json as _json

    body = _json.dumps({
        "type": "paratext",
        "title": "Proceedings of the ACM SIGOPS 31st Symposium on Operating Systems Principles",
        "abstract_inverted_index": None,
    }).encode()
    fetch = FakeFetch({"api.openalex.org": body})

    result = fetch_abstract(conn, "src-doi", fetch=fetch)

    assert not result.stored
    assert result.reason == "resolved-to-container"


def test_the_container_exception_carries_what_it_resolved_to():
    import json as _json

    body = _json.dumps({"type": "paratext", "title": "Proceedings of Something"}).encode()
    with pytest.raises(ContainerRecordFound) as exc:
        fetch_via_openalex(Identifier("doi", DOI), FakeFetch({"api.openalex.org": body}))
    assert exc.value.title == "Proceedings of Something"


# --- per-route plausibility floors -------------------------------------------


def test_openalex_floor_is_lower_than_the_arxiv_floor():
    assert MIN_PLAUSIBLE_CHARS_BY_ROUTE["openalex"] < MIN_PLAUSIBLE_CHARS_BY_ROUTE["arxiv"]


def test_a_reconstructed_abstract_below_the_arxiv_floor_is_accepted_for_openalex():
    """The 8 real abstracts discarded on 2026-09-18 ran 135-235 characters."""
    text = "x" * 200
    assert is_plausible(text, "openalex")
    assert not is_plausible(text, "arxiv")


def test_placeholders_are_still_rejected_on_both_routes():
    for label in ("arxiv", "openalex"):
        assert not is_plausible("Abstract not available.", label)
        assert not is_plausible("", label)
        assert not is_plausible(None, label)


def test_is_plausible_without_a_label_keeps_the_strict_floor():
    """Every caller predating the split passed one argument."""
    assert is_plausible("x" * MIN_PLAUSIBLE_ABSTRACT_CHARS)
    assert not is_plausible("x" * (MIN_PLAUSIBLE_ABSTRACT_CHARS - 1))


# --- the title-search route --------------------------------------------------
#
# 323 papers carry a venue landing page with no arXiv id and no DOI anywhere in
# the url, so the only query available is the title we already hold. That makes
# the answer only as good as the question, which is a weaker claim than either
# identifier route makes and is labelled as one.


def _search_body(title, venue=None, abstract=True, work_type="conference-paper"):
    import json as _json
    work = {"title": title, "type": work_type}
    if abstract:
        work["abstract_inverted_index"] = {w: [i] for i, w in enumerate(REAL_ABSTRACT.split())}
    if venue is not None:
        work["primary_location"] = {"source": {"display_name": venue}}
    return _json.dumps({"results": [work]}).encode()


TITLE = "SCRUTINIZER: Towards Secure Forensics on Compromised TrustZone"


def test_a_title_search_finds_the_right_paper(conn):
    add_node(conn, "src-venue", "Source", {
        "url": "https://www.ndss-symposium.org/ndss-paper/scrutinizer",
        "source_type": "conference-paper", "license": "MIT",
        "title": TITLE, "venue": "NDSS",
    })
    fetch = FakeFetch({"api.openalex.org": _search_body(TITLE)})
    result = fetch_abstract(conn, "src-venue", fetch=fetch)
    assert result.stored
    assert result.abstract_source == "openalex-title-search"


def test_a_plausible_but_wrong_paper_is_refused(conn):
    """THE WHOLE RISK. A title search returns the best match for whatever it is
    given; a Source whose title belonged to another paper would otherwise
    receive that paper's abstract, stamped as though it had been looked up."""
    add_node(conn, "src-venue", "Source", {
        "url": "https://www.usenix.org/conference/osdi26/presentation/x",
        "source_type": "conference-paper", "license": "MIT",
        "title": "A Programming Model for Disaggregated Memory over CXL",
        "venue": "OSDI",
    })
    # Same field, similar words, different paper.
    wrong = "A Programming Model for Persistent Memory over CXL Interconnects and Fabrics"
    result = fetch_abstract(conn, "src-venue", fetch=FakeFetch({"api.openalex.org": _search_body(wrong)}))
    assert not result.stored
    assert result.reason == "no-title-match"
    assert "abstract" not in get_node(conn, "src-venue")["attrs"]


def test_a_contradicting_venue_is_refused(conn):
    add_node(conn, "src-venue", "Source", {
        "url": "https://www.usenix.org/conference/osdi26/presentation/x",
        "source_type": "conference-paper", "license": "MIT",
        "title": TITLE, "venue": "OSDI",
    })
    body = _search_body(TITLE, venue="Zenodo (CERN European Organization for Nuclear Research)")
    result = fetch_abstract(conn, "src-venue", fetch=FakeFetch({"api.openalex.org": body}))
    assert not result.stored
    assert result.reason == "no-title-match"


def test_an_absent_venue_is_not_a_contradiction(conn):
    """Measured 2026-09-18: only 1 of 4 matches carried any OpenAlex venue.
    Treating absence as failure would reject every good match for missing data."""
    add_node(conn, "src-venue", "Source", {
        "url": "https://www.usenix.org/conference/osdi26/presentation/x",
        "source_type": "conference-paper", "license": "MIT",
        "title": TITLE, "venue": "SOSP",
    })
    result = fetch_abstract(conn, "src-venue", fetch=FakeFetch({"api.openalex.org": _search_body(TITLE)}))
    assert result.stored


def test_a_partially_matching_venue_agrees(conn):
    add_node(conn, "src-venue", "Source", {
        "url": "https://www.usenix.org/conference/osdi26/presentation/x",
        "source_type": "conference-paper", "license": "MIT",
        "title": TITLE, "venue": "OSDI",
    })
    body = _search_body(TITLE, venue="USENIX OSDI Symposium")
    assert fetch_abstract(conn, "src-venue", fetch=FakeFetch({"api.openalex.org": body})).stored


def test_no_search_result_is_reported_not_stored(conn):
    import json as _json
    add_node(conn, "src-venue", "Source", {
        "url": "https://www.usenix.org/conference/osdi26/presentation/x",
        "source_type": "conference-paper", "license": "MIT",
        "title": TITLE, "venue": "OSDI",
    })
    empty = _json.dumps({"results": []}).encode()
    assert fetch_abstract(conn, "src-venue", fetch=FakeFetch({"api.openalex.org": empty})).reason == "no-title-match"


def test_the_title_search_floor_is_far_above_the_difference_floor():
    """0.35 judges two titles DIFFERENT. 0.80 asserts they name the same work,
    which is the stronger claim needed when the query is what is being trusted."""
    assert TITLE_SEARCH_MATCH_FLOOR > MIN_PLAUSIBLE_ABSTRACT_CHARS / 1000
    assert TITLE_SEARCH_MATCH_FLOOR >= 0.8
    assert titles_match_closely(TITLE, TITLE)
    assert not titles_match_closely(TITLE, "Some Entirely Different Paper About Scheduling")


def test_the_title_search_label_is_its_own_provenance_class():
    """openalex means the authority was asked about a document. This means it
    was asked which document best matches a string. Different confidence."""
    assert "openalex-title-search" in MIN_PLAUSIBLE_CHARS_BY_ROUTE
    assert "openalex-title-search" != "openalex"


def test_the_dry_run_reports_the_title_search_it_would_attempt(conn):
    """A dry run exists to say what a real run would do. After the title-search
    route landed it reported "no-identifier" for 412 papers it would in fact
    attempt, which told the operator the route was inert."""
    report = run_batch(conn, fetch=FakeFetch({}), dry_run=True, sleep=lambda _: None)
    assert report.failures.get("would-title-search") == 1
    assert "no-identifier" not in report.failures


def test_the_dry_run_still_reports_nothing_to_search_with(conn):
    add_node(conn, "src-bare", "Source", {
        "url": "https://someone.example/notes", "source_type": "conference-paper",
        "license": "MIT", "title": "",
    })
    report = run_batch(conn, fetch=FakeFetch({}), dry_run=True, sleep=lambda _: None)
    assert report.failures.get("no-identifier") == 1
