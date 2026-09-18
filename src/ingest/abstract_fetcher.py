"""Fetch Source abstracts from public metadata APIs (ALG-KK-ABSTRACT-FETCH).

Routes, in the order they are tried:

  arxiv     the arXiv Atom API. Returns the author's abstract verbatim, so it
            is preferred whenever an arXiv id can be resolved.
  openalex  reconstructed from abstract_inverted_index, a word-to-positions
            map. The text comes back in the right order but is rebuilt from a
            bag of positions, so it is NOT word-for-word the published
            abstract. INV-KK-ABSTRACT-SOURCE-ENUM keeps its label distinct
            from arxiv for exactly this reason.

Every network call goes through an injected `fetch` callable. The default is
the only place urllib appears, so the test suite never opens a socket.

Rate limiting is deliberately NOT done here — it belongs to the batch walk
(ALG-KK-ABSTRACT-FETCH-BATCH), so that fetching one abstract stays fast and
testable.
"""

from __future__ import annotations

import json
import re
import sqlite3
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Callable

from graph.engine import get_node
from ingest.source_abstract import set_abstract


ARXIV_API = "http://export.arxiv.org/api/query"
OPENALEX_API = "https://api.openalex.org/works"

# OpenAlex marks a proceedings VOLUME — the book the papers sit in — with this
# work type. Several Sources carry the volume's DOI rather than their own paper's
# (10.1145/3731569, 10.1145/3694715, 10.1145/3713082 among them), and OpenAlex
# resolves those happily: the lookup SUCCEEDS and returns a record titled e.g.
# "Proceedings of the ACM SIGOPS 31st Symposium on Operating Systems Principles",
# which has no abstract. Reporting that as "not found" hides the real fault,
# which is that the Source carries the wrong DOI. 12 of 20 resolvable candidates
# failed this way on 2026-09-18.
OPENALEX_CONTAINER_TYPE = "paratext"

# OpenAlex asks for a contact address in the User-Agent to reach its polite
# pool, which is what buys the 0.5s rate rather than a harsher one.
USER_AGENT = "know_kernel/0.1 (mailto:reiniertl@gmail.com)"

ARXIV_RATE_LIMIT_SECONDS = 3.0
OPENALEX_RATE_LIMIT_SECONDS = 0.5

# A real abstract is never this short. The gate exists to reject placeholders —
# "Abstract not available", a one-line teaser, the body of an error page —
# rather than to judge quality.
#
# The prior-art scripts carried an 800 figure, but that was their SELECTION
# predicate (length(Evidence.text) < 800 meaning "this row holds a fake
# summary, go repair it"), not their acceptance gate; their actual acceptance
# gates were 100, 200 and 500. Reusing 800 here would discard real data:
# USENIX and ACM abstracts routinely land at 600-900 characters. 250 clears
# every genuine abstract while still catching the placeholders.
MIN_PLAUSIBLE_ABSTRACT_CHARS = 250

# PER-ROUTE FLOORS. Operator decision, 2026-09-18.
#
# 250 was calibrated on arXiv and USENIX text and holds there. It does NOT hold
# for OpenAlex, whose abstracts are REBUILT from abstract_inverted_index and come
# back materially shorter than the published text. Measured over the 20
# resolvable candidates on 2026-09-18: 8 returned a genuine abstract, every one
# between 135 and 235 characters, and the 250 floor discarded all 8 — including
# this, at 226 characters and plainly real:
#
#   "Web applications are governed by privacy policies, but developers lack
#    practical abstractions to ensure that their code actually abides by these
#    policies. This leads to frequent ov..."
#
# The two labels were already kept distinct by INV-KK-ABSTRACT-SOURCE-ENUM
# precisely because openalex text is not word-for-word, so that is where the
# different floor belongs. 120 clears every measured case while still rejecting
# placeholders such as "Abstract not available." at ~23 characters.
#
# The arxiv floor is UNCHANGED. Its calibration was never the problem.
MIN_PLAUSIBLE_CHARS_BY_ROUTE = {
    "arxiv": 250,
    "openalex": 120,
}

# Strict, anchored on the arxiv.org host. The prior art also carried a bare
# r'(\d{4}\.\d{4,5})' fallback, which matches a year-like number in ANY url and
# would silently attach an unrelated paper's abstract. That fallback is dropped
# on purpose — see the third-party-url hazard.
_ARXIV_URL_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?)")
_DOI_RE = re.compile(r"(10\.\d{4,}/[^\s]+)")

_VERSION_SUFFIX_RE = re.compile(r"v\d+$")
_WHITESPACE_RE = re.compile(r"\s+")

_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


Fetch = Callable[[str, dict], bytes]


@dataclass(frozen=True)
class Identifier:
    """Which identifier the resolver actually found, and its value.

    The kind is carried through to the caller so that a wrong pull stays
    diagnosable after the fact: some Source urls point at a third-party write-up
    rather than the paper, and knowing which identifier was used is what makes
    the bad row findable later.
    """

    kind: str  # "arxiv" | "doi"
    value: str


class ContainerRecordFound(Exception):
    """The identifier resolved, but to a proceedings volume rather than a paper.

    A distinct outcome from "no record": the lookup worked and the answer is that
    this Source is carrying a container DOI. The fault is in the Source, not in
    the route, and saying "not found" would send anyone investigating to the
    wrong place.
    """

    def __init__(self, identifier: Identifier, title: str) -> None:
        super().__init__(f"{identifier.kind}:{identifier.value} resolved to container {title!r}")
        self.identifier = identifier
        self.title = title


class RouteTransportError(Exception):
    """The route could not be reached at all.

    Raised when the fetch callable itself fails, so that a transport failure is
    never reported as an empty result. export.arxiv.org returns HTTP 406 to this
    environment for every request — http and https, with and without a
    User-Agent — and the previous bare `except Exception: return None` reported
    that as "no-plausible-result", which said the abstract was missing when in
    truth the question was never asked.
    """

    def __init__(self, route: str, cause: BaseException) -> None:
        super().__init__(f"{route}: {cause}")
        self.route = route
        self.cause = cause


@dataclass
class FetchResult:
    source_id: str
    stored: bool
    reason: str
    abstract_source: str | None = None
    identifier_kind: str | None = None
    identifier_value: str | None = None
    chars: int = 0


def _urllib_fetch(url: str, headers: dict) -> bytes:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read()


def resolve_identifier(url: str | None) -> Identifier | None:
    """Derive an arXiv id or a DOI from a Source url, saying which it found.

    Returns None when the url names neither — a third-party blog write-up, a
    venue landing page, a bare title search. Those Sources have no automated
    route and stay manual by design.
    """
    if not url:
        return None

    match = _ARXIV_URL_RE.search(url)
    if match:
        return Identifier(kind="arxiv", value=match.group(1))

    match = _DOI_RE.search(url)
    if match:
        return Identifier(kind="doi", value=match.group(1).rstrip("."))

    return None


def reconstruct_inverted_index(index: dict | None) -> str | None:
    """Rebuild abstract text from OpenAlex's word-to-positions map."""
    if not index:
        return None
    positions: dict[int, str] = {}
    for word, position_list in index.items():
        for position in position_list:
            positions[position] = word
    if not positions:
        return None
    return " ".join(positions[k] for k in sorted(positions))


def is_plausible(text: str | None, source_label: str | None = None) -> bool:
    """True when `text` is long enough to be a real abstract for its route.

    `source_label` selects the route's floor. Omitting it applies the strict
    default, which is what every caller predating the per-route split did.
    """
    if not text:
        return False
    floor = MIN_PLAUSIBLE_CHARS_BY_ROUTE.get(source_label, MIN_PLAUSIBLE_ABSTRACT_CHARS)
    return len(text.strip()) >= floor


def fetch_via_arxiv(identifier: Identifier, fetch: Fetch) -> tuple[str, str] | None:
    """Read the verbatim abstract from the arXiv Atom feed's <summary>."""
    if identifier.kind != "arxiv":
        return None
    url = f"{ARXIV_API}?id_list={identifier.value}&max_results=1"
    try:
        raw = fetch(url, {"User-Agent": USER_AGENT})
    except Exception as exc:  # transport only — never a data problem
        raise RouteTransportError("arxiv", exc) from exc
    try:
        root = ET.fromstring(raw)
        entries = root.findall("atom:entry", _ATOM_NS)
        if not entries:
            return None
        summary = entries[0].find("atom:summary", _ATOM_NS)
        if summary is None or not summary.text:
            return None
        text = _WHITESPACE_RE.sub(" ", summary.text).strip()
        return (text, "arxiv") if text else None
    except Exception:
        return None


def fetch_via_openalex(identifier: Identifier, fetch: Fetch) -> tuple[str, str] | None:
    """Reconstruct the abstract from OpenAlex's inverted index.

    An arXiv id reaches OpenAlex through its registered DOI prefix; a DOI is
    used as-is.
    """
    if identifier.kind == "doi":
        url = f"{OPENALEX_API}/doi:{identifier.value}"
    elif identifier.kind == "arxiv":
        bare = _VERSION_SUFFIX_RE.sub("", identifier.value)
        url = f"{OPENALEX_API}/doi:10.48550/arXiv.{bare}"
    else:
        return None

    try:
        raw = fetch(url, {"User-Agent": USER_AGENT})
    except Exception as exc:  # transport only — never a data problem
        raise RouteTransportError("openalex", exc) from exc
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if data.get("type") == OPENALEX_CONTAINER_TYPE:
        raise ContainerRecordFound(identifier, data.get("title") or "")
    text = reconstruct_inverted_index(data.get("abstract_inverted_index"))
    return (text, "openalex") if text else None


# arXiv first: its text is verbatim, OpenAlex's is reconstructed.
ROUTES: tuple[Callable[[Identifier, Fetch], tuple[str, str] | None], ...] = (
    fetch_via_arxiv,
    fetch_via_openalex,
)

# Which identifier kinds each route can answer for. A route that DECLINES an
# identifier has not failed and must contribute no outcome: fetch_via_arxiv
# returns None for a DOI, and counting that as "no abstract in the record" would
# let it outrank a genuine transport failure on the other route — reporting
# missing data for a dead connection, which is the exact confusion this taxonomy
# exists to end.
ROUTE_IDENTIFIER_KINDS: dict[object, tuple[str, ...]] = {
    fetch_via_arxiv: ("arxiv",),
    fetch_via_openalex: ("arxiv", "doi"),
}


def fetch_abstract(
    conn: sqlite3.Connection,
    source_id: str,
    fetch: Fetch = _urllib_fetch,
) -> FetchResult:
    """Populate one Source's abstract (ALG-KK-ABSTRACT-FETCH).

    Tries each route in order and stores the first plausible result through
    part 1's set_abstract, which is what records provenance
    (INV-KK-ABSTRACT-PROVENANCE-RECORDED).

    A hand-entered abstract is never replaced
    (INV-KK-ABSTRACT-MANUAL-PRESERVED). Raises ValueError if `source_id` names
    no node or names a node of another kind.
    """
    node = get_node(conn, source_id)
    if node is None or node["kind"] != "Source":
        raise ValueError(f"Source node '{source_id}' does not exist")

    attrs = node["attrs"]

    existing = (attrs.get("abstract") or "").strip()
    if existing and attrs.get("abstract_source") == "manual":
        return FetchResult(
            source_id=source_id, stored=False, reason="manual-preserved",
            abstract_source="manual",
        )

    identifier = resolve_identifier(attrs.get("url"))
    if identifier is None:
        return FetchResult(source_id=source_id, stored=False, reason="no-identifier")

    # Why each route declined, most informative last. A transport failure means
    # the question was never asked; a container means it was asked and answered
    # about the wrong document; too-short means a real abstract was found and
    # judged unusable. Collapsing these into one code is what made a 406 look
    # like a missing abstract.
    outcomes: list[str] = []
    for route in ROUTES:
        if identifier.kind not in ROUTE_IDENTIFIER_KINDS[route]:
            continue  # declined, not failed
        try:
            found = route(identifier, fetch)
        except RouteTransportError:
            outcomes.append("transport-error")
            continue
        except ContainerRecordFound:
            outcomes.append("resolved-to-container")
            continue
        if found is None:
            outcomes.append("no-abstract-in-record")
            continue
        text, label = found
        if not is_plausible(text, label):
            outcomes.append("abstract-too-short")
            continue
        set_abstract(conn, source_id, text, label)
        return FetchResult(
            source_id=source_id, stored=True, reason="stored",
            abstract_source=label,
            identifier_kind=identifier.kind, identifier_value=identifier.value,
            chars=len(text.strip()),
        )

    # Rank by how much each outcome tells the operator. "too short" names a real
    # abstract we chose not to store; "container" names a wrong DOI on the
    # Source; those both beat a bare miss, and a pure transport failure last of
    # all because it says nothing about the paper.
    for reason in ("abstract-too-short", "resolved-to-container",
                   "no-abstract-in-record", "transport-error"):
        if reason in outcomes:
            break
    else:
        reason = "no-plausible-result"

    return FetchResult(
        source_id=source_id, stored=False, reason=reason,
        identifier_kind=identifier.kind, identifier_value=identifier.value,
    )
