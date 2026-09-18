"""Tests for ALG-KK-SOURCE-TITLE-RECONCILE.

Every test drives an injected fetch callable. No socket is opened, following the
pattern src/ingest/abstract_fetcher.py documents for exactly this reason.
"""

from __future__ import annotations

import json

import pytest

from graph.engine import add_node, get_node
from graph.schema import init_db
from ingest.abstract_fetcher import Identifier, RouteTransportError
from ingest.title_reconcile import (
    TITLE_MATCH_FLOOR,
    authoritative_title,
    reconcile_title,
    run_batch,
    titles_agree,
)

ARXIV_URL = "https://arxiv.org/abs/2503.12788"
REAL_TITLE = "Byzantine-Tolerant Consensus in GPU-Inspired Shared Memory"
WRONG_TITLE = "WOW: Workflow-Aware Data Movement and Task Scheduling for Dynamic Workflows"


class FakeFetch:
    """Dict-backed fetch. Unknown urls raise, so stray calls are visible."""

    def __init__(self, responses):
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


def _oa(title, work_type="preprint"):
    return json.dumps({"title": title, "type": work_type}).encode()


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "reconcile.db")
    yield c
    c.close()


def _source(c, sid="src-1", url=ARXIV_URL, title=WRONG_TITLE, source_type="preprint"):
    add_node(c, sid, "Source", {
        "url": url, "source_type": source_type, "license": "MIT", "title": title,
    })
    return sid


# --- the comparison ----------------------------------------------------------


def test_identical_titles_agree():
    assert titles_agree(REAL_TITLE, REAL_TITLE)


def test_unrelated_titles_do_not_agree():
    assert not titles_agree(WRONG_TITLE, REAL_TITLE)


def test_a_subtitle_difference_still_agrees():
    """The floor must tolerate real-world title variation, or reconciliation
    would rewrite titles that were already correct."""
    assert titles_agree(
        "Byzantine-Tolerant Consensus in GPU-Inspired Shared Memory",
        "Byzantine-Tolerant Consensus in GPU-Inspired Shared Memory: An Extended Study",
    )


def test_an_empty_title_never_agrees():
    assert not titles_agree("", REAL_TITLE)
    assert not titles_agree(REAL_TITLE, None)


def test_the_floor_is_documented_and_blunt():
    assert 0 < TITLE_MATCH_FLOOR < 1


# --- what the authority will and will not answer ------------------------------


def test_a_container_record_is_not_treated_as_a_title():
    """A proceedings volume's title is not the paper's title, and writing it
    would replace one wrong title with another."""
    fetch = FakeFetch({"openalex": _oa("Proceedings of SOSP", "paratext")})
    assert authoritative_title(Identifier("doi", "10.1145/3731569"), fetch) is None


def test_a_transport_failure_raises_rather_than_reading_as_no_title(conn):
    fetch = FakeFetch({"openalex": OSError("406")})
    with pytest.raises(RouteTransportError):
        authoritative_title(Identifier("arxiv", "2503.12788"), fetch)


# --- reconciliation ----------------------------------------------------------


def test_a_mismatched_title_is_replaced(conn):
    sid = _source(conn)
    outcome, change = reconcile_title(conn, sid, fetch=FakeFetch({"openalex": _oa(REAL_TITLE)}))
    assert outcome == "reconciled"
    assert change["was"] == WRONG_TITLE and change["now"] == REAL_TITLE
    attrs = get_node(conn, sid)["attrs"]
    assert attrs["title"] == REAL_TITLE


def test_the_old_title_is_preserved(conn):
    """The corpus is not losing information; it is recording that it held a
    title belonging to another paper."""
    sid = _source(conn)
    reconcile_title(conn, sid, fetch=FakeFetch({"openalex": _oa(REAL_TITLE)}))
    assert get_node(conn, sid)["attrs"]["title_before_reconcile"] == WRONG_TITLE


def test_a_matching_title_is_left_alone(conn):
    sid = _source(conn, title=REAL_TITLE)
    outcome, change = reconcile_title(conn, sid, fetch=FakeFetch({"openalex": _oa(REAL_TITLE)}))
    assert outcome == "agrees" and change is None
    assert "title_before_reconcile" not in get_node(conn, sid)["attrs"]


def test_nothing_but_the_title_is_touched(conn):
    """url, identifier, abstract and Evidence already agree with each other. The
    title is the one field shown to be wrong, and the only one written."""
    add_node(conn, "src-2", "Source", {
        "url": ARXIV_URL, "source_type": "preprint", "license": "MIT",
        "title": WRONG_TITLE, "abstract": "A real abstract about shared memory.",
        "venue": "arXiv", "published_date": "2026-01-01",
    })
    before = dict(get_node(conn, "src-2")["attrs"])
    reconcile_title(conn, "src-2", fetch=FakeFetch({"openalex": _oa(REAL_TITLE)}))
    after = get_node(conn, "src-2")["attrs"]
    for key in ("url", "source_type", "license", "abstract", "venue", "published_date"):
        assert after[key] == before[key], key


def test_a_source_with_no_identifier_is_skipped_not_guessed(conn):
    """323 papers have no arXiv id or DOI in their url. There is no authority to
    reconcile them against, so they are left exactly as they are."""
    sid = _source(conn, url="https://www.usenix.org/conference/osdi26/presentation/x")
    outcome, change = reconcile_title(conn, sid, fetch=FakeFetch({}))
    assert outcome == "no-identifier" and change is None
    assert get_node(conn, sid)["attrs"]["title"] == WRONG_TITLE


def test_a_transport_failure_changes_nothing(conn):
    sid = _source(conn)
    outcome, _ = reconcile_title(conn, sid, fetch=FakeFetch({"openalex": OSError("406")}))
    assert outcome == "transport-error"
    assert get_node(conn, sid)["attrs"]["title"] == WRONG_TITLE


def test_dry_run_reports_without_writing(conn):
    sid = _source(conn)
    outcome, change = reconcile_title(
        conn, sid, fetch=FakeFetch({"openalex": _oa(REAL_TITLE)}), dry_run=True)
    assert outcome == "reconciled" and change["now"] == REAL_TITLE
    assert get_node(conn, sid)["attrs"]["title"] == WRONG_TITLE


# --- the batch ---------------------------------------------------------------


def test_the_batch_only_considers_papers(conn):
    """INV-KK-PAPER-SOURCE-TYPE-VOCABULARY: kernel-doc and discourse are legal
    source types and are not papers."""
    _source(conn, "src-paper", source_type="preprint")
    _source(conn, "src-doc", source_type="kernel-doc")
    report = run_batch(conn, fetch=FakeFetch({"openalex": _oa(REAL_TITLE)}), pause=0)
    assert report.considered == 1


def test_the_batch_records_every_change_for_audit(conn):
    _source(conn, "src-a")
    _source(conn, "src-b", title=REAL_TITLE)
    report = run_batch(conn, fetch=FakeFetch({"openalex": _oa(REAL_TITLE)}), pause=0)
    assert report.reconciled == 1
    assert report.changes[0]["source_id"] == "src-a"
    assert report.changes[0]["was"] == WRONG_TITLE


# --- the confirmed examples, as a regression guard ---------------------------


@pytest.mark.parametrize("sid,wrong,real", [
    ("src-arxiv-00013612",
     "AgenTEE: Confidential LLM Agent Execution on Edge Devices",
     "Committed SAE-Feature Traces for Audited-Session Substitution Detection"),
    ("src-arxiv-bfe5ab9f",
     "WOW: Workflow-Aware Data Movement and Task Scheduling for Dynamic Workflows",
     "Byzantine-Tolerant Consensus in GPU-Inspired Shared Memory"),
])
def test_the_confirmed_examples_reconcile(conn, sid, wrong, real):
    """Read by hand on 2026-09-18. On each, the identifier, abstract and summary
    agreed with each other and only the title dissented. These must not silently
    come back."""
    _source(conn, sid, title=wrong)
    outcome, change = reconcile_title(conn, sid, fetch=FakeFetch({"openalex": _oa(real)}))
    assert outcome == "reconciled"
    assert change["now"] == real


def test_a_less_specific_authority_title_is_refused(conn):
    """Several ACM records hold only the short name before the colon. Replacing
    the fuller stored title with that stub loses information and fixes nothing.
    Four records were damaged this way by the first corpus run."""
    sid = _source(conn, title="PathFS: A File System for the Hierarchical Edge")
    outcome, change = reconcile_title(conn, sid, fetch=FakeFetch({"openalex": _oa("PathFS")}))
    assert outcome == "authority-less-specific"
    assert change is None
    assert get_node(conn, sid)["attrs"]["title"] == "PathFS: A File System for the Hierarchical Edge"
    assert "title_before_reconcile" not in get_node(conn, sid)["attrs"]


def test_a_more_specific_authority_title_is_still_applied(conn):
    """The guard must not block genuine expansions, which are the common case:
    an abbreviated stored title replaced by the full published one."""
    sid = _source(conn, title="TinyContainer: Multi-Tenant Microcontroller Containers")
    full = ("TinyContainer: Container Runtime Middleware Enabling Multi-tenant "
            "Microcontroller Applications and Services on Constrained Devices")
    outcome, _ = reconcile_title(conn, sid, fetch=FakeFetch({"openalex": _oa(full)}))
    assert outcome == "reconciled"
    assert get_node(conn, sid)["attrs"]["title"] == full
