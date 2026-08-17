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


def is_plausible(text: str | None) -> bool:
    """True when `text` is long enough to be a real abstract."""
    if not text:
        return False
    return len(text.strip()) >= MIN_PLAUSIBLE_ABSTRACT_CHARS


def fetch_via_arxiv(identifier: Identifier, fetch: Fetch) -> tuple[str, str] | None:
    """Read the verbatim abstract from the arXiv Atom feed's <summary>."""
    if identifier.kind != "arxiv":
        return None
    url = f"{ARXIV_API}?id_list={identifier.value}&max_results=1"
    try:
        raw = fetch(url, {"User-Agent": USER_AGENT})
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
        data = json.loads(raw)
        text = reconstruct_inverted_index(data.get("abstract_inverted_index"))
        return (text, "openalex") if text else None
    except Exception:
        return None


# arXiv first: its text is verbatim, OpenAlex's is reconstructed.
ROUTES: tuple[Callable[[Identifier, Fetch], tuple[str, str] | None], ...] = (
    fetch_via_arxiv,
    fetch_via_openalex,
)


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

    for route in ROUTES:
        found = route(identifier, fetch)
        if found is None:
            continue
        text, label = found
        if not is_plausible(text):
            continue
        set_abstract(conn, source_id, text, label)
        return FetchResult(
            source_id=source_id, stored=True, reason="stored",
            abstract_source=label,
            identifier_kind=identifier.kind, identifier_value=identifier.value,
            chars=len(text.strip()),
        )

    return FetchResult(
        source_id=source_id, stored=False, reason="no-plausible-result",
        identifier_kind=identifier.kind, identifier_value=identifier.value,
    )
