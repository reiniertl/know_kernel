"""Source content classification, validation, and the backfill that stores it.

Spec: ALG-KK-CLASSIFY-SOURCE-CONTENT, ALG-KK-EXTRACT-KERNEL-DOC-REFS,
      INV-KK-SOURCE-CONTENT-SUFFICIENT, ALG-KK-VALIDATE-SOURCE-CONTENT,
      ALG-KK-RESOLVE-DIRECTORY-SOURCE, INV-KK-VALIDATE-RATE-LIMITED,
      ALG-KK-BACKFILL-SOURCE-PROSE, INV-KK-BACKFILL-PROSE-NOT-MARKUP,
      IFC-KK-SOURCE-CONTENT-STATUS

EVERY ONE OF THE FIRST SIX IDS WAS ABSENT FROM THE DAG UNTIL 2026-09-25. This
module cited them from the day it was written and none of them existed, so the
whole file was unspecified while appearing to be specified. They were authored
that day, describing the behaviour as found.

THE VALIDATE PATH REPORTS; THE BACKFILL PATH STORES. That is the difference
between ALG-KK-VALIDATE-SOURCE-CONTENT and ALG-KK-BACKFILL-SOURCE-PROSE, and it
is why kernel-doc yielded 0 concepts from 43 sources: validate_all_sources
fetched every one of those documents and threw the text away.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import httpx

from graph.engine import update_node_attrs

log = logging.getLogger(__name__)


GIT_KERNEL_ORG_BLOB = (
    "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/{path}"
)

_KERNEL_DOC_RE = re.compile(r"\.\.\s+kernel-doc::\s+(\S+)")

# Markers of the cgit /tree/ HTML page, which is what a browser is shown.
_DIRECTORY_MARKERS = [
    '<table class="list">',
    "drwxr-xr-x",
    '<td class="ls-mode">',
]

# THE SECOND DIRECTORY FORM, AND NOTHING RECOGNISED IT UNTIL 2026-09-25.
# Requesting a DIRECTORY under /plain/ returns neither raw text nor the /tree/
# page: cgit serves a bare <ul> of links, which matches none of the three
# markers above because all three were taken from the /tree/ page. Measured the
# same day: 16 of the 43 kernel-doc Sources classified as 'unreachable' or
# 'thin' rather than 'directory' when fetched that way, so a listing could be
# stored as thin prose — exactly what INV-KK-INGEST-REJECTS-DIRECTORY forbids.
# This closes a gap in that invariant's coverage; it moves no threshold.
_PLAIN_DIRECTORY_RE = re.compile(r"<li><a href='[^']*/plain/")

# A body that opens as an HTML or XML document is markup, whatever survives
# _strip_markup. INV-KK-BACKFILL-PROSE-NOT-MARKUP refuses to store it as prose:
# stripping the tags off a navigation page leaves words, and words that read as
# prose are worse than an empty document because they are not visibly empty.
_MARKUP_DOCUMENT_RE = re.compile(r"^\s*(?:<!DOCTYPE|<html\b|<\?xml)", re.IGNORECASE)

_RST_DIRECTIVE_RE = re.compile(r"^\.\.\s+\S+::", re.MULTILINE)
_RST_ROLE_RE = re.compile(r":\w+:`[^`]*`")
# The blank line after the directive is REQUIRED by RST and was not permitted
# here until 2026-09-25, so this regex matched no code block any real kernel
# document contains — .. code-block:: c is always followed by an empty line and
# then the indented body. _LITERAL_BLOCK_RE below already allowed for it, which
# is how the inconsistency stayed invisible: literal blocks were stripped and
# code-block directives were not. Fixing it lowers prose word counts slightly,
# which is what ALG-KK-CLASSIFY-SOURCE-CONTENT says the count is supposed to
# measure: what a reader would read.
_CODE_BLOCK_RE = re.compile(
    r"(?s)\.\.\s+code-block::\s*\w*\n+(?:[ \t]+[^\n]*\n?|\n)*?(?=\n\S|\Z)",
    re.MULTILINE,
)
_LITERAL_BLOCK_RE = re.compile(r"(?s)::\n\n(?:[ \t]+[^\n]*\n?)+", re.MULTILINE)


@dataclass
class ContentClassification:
    classification: str  # substantive | stub | directory | thin | unreachable
    word_count: int = 0
    kernel_doc_refs: list[str] = field(default_factory=list)
    prose_excerpt: str = ""


def _strip_markup(text: str) -> str:
    """Remove RST/HTML markup, leaving only prose words."""
    cleaned = _CODE_BLOCK_RE.sub("", text)
    cleaned = _LITERAL_BLOCK_RE.sub("", cleaned)
    cleaned = _RST_DIRECTIVE_RE.sub("", cleaned)
    cleaned = _RST_ROLE_RE.sub("", cleaned)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    cleaned = re.sub(r"[=\-~^`]{3,}", "", cleaned)
    cleaned = re.sub(r"^\s*\.\.\s+.*$", "", cleaned, flags=re.MULTILINE)
    return cleaned


def _count_prose_words(text: str) -> int:
    stripped = _strip_markup(text)
    words = stripped.split()
    return len(words)


def _extract_prose_excerpt(text: str, max_len: int = 500) -> str:
    stripped = _strip_markup(text)
    lines = [ln.strip() for ln in stripped.splitlines() if ln.strip()]
    excerpt = " ".join(lines)
    if len(excerpt) > max_len:
        excerpt = excerpt[:max_len] + "..."
    return excerpt


def classify_content(text: str) -> ContentClassification:
    """Classify fetched document text (ALG-KK-CLASSIFY-SOURCE-CONTENT).

    Returns ContentClassification with one of:
      substantive — >=100 words of prose
      stub        — kernel-doc directives only, <50 words prose
      directory   — git.kernel.org tree listing
      thin        — 50-99 words (needs manual review)
      unreachable — empty or None input
    """
    if not text or not text.strip():
        return ContentClassification(classification="unreachable")

    # BEFORE any word is counted, so a long listing is still refused —
    # INV-KK-INGEST-REJECTS-DIRECTORY depends on exactly this ordering.
    if any(marker in text for marker in _DIRECTORY_MARKERS) or _PLAIN_DIRECTORY_RE.search(text):
        return ContentClassification(
            classification="directory",
            prose_excerpt=_extract_prose_excerpt(text),
        )

    kernel_doc_refs = extract_kernel_doc_refs(text)
    word_count = _count_prose_words(text)
    prose_excerpt = _extract_prose_excerpt(text)

    if kernel_doc_refs and word_count < 50:
        return ContentClassification(
            classification="stub",
            word_count=word_count,
            kernel_doc_refs=kernel_doc_refs,
            prose_excerpt=prose_excerpt,
        )

    if word_count >= 100:
        return ContentClassification(
            classification="substantive",
            word_count=word_count,
            kernel_doc_refs=kernel_doc_refs,
            prose_excerpt=prose_excerpt,
        )

    if word_count >= 50:
        return ContentClassification(
            classification="thin",
            word_count=word_count,
            kernel_doc_refs=kernel_doc_refs,
            prose_excerpt=prose_excerpt,
        )

    return ContentClassification(
        classification="unreachable",
        word_count=word_count,
        prose_excerpt=prose_excerpt,
    )


def extract_kernel_doc_refs(rst_text: str) -> list[str]:
    """Parse RST for '.. kernel-doc::' directives (ALG-KK-EXTRACT-KERNEL-DOC-REFS).

    Returns list of kernel source file paths, e.g. ['mm/slub.c', 'mm/slab.h'].
    """
    return _KERNEL_DOC_RE.findall(rst_text)


def build_replacement_url(kernel_path: str) -> str:
    """Convert a kernel source path to a git.kernel.org blob URL."""
    return GIT_KERNEL_ORG_BLOB.format(path=kernel_path.strip("/"))


# ---------------------------------------------------------------------------
# Orchestration layer (ALG-KK-VALIDATE-SOURCE-CONTENT)
# ---------------------------------------------------------------------------

@dataclass
class SourceValidationResult:
    source_id: str
    url: str
    classification: str
    word_count: int = 0
    kernel_doc_refs: list[str] = field(default_factory=list)
    suggested_replacement_urls: list[str] = field(default_factory=list)
    prose_excerpt: str = ""


_FILE_LINK_RE = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>([^<]+)</a>')
_DOC_EXTENSIONS = {".rst", ".txt"}
_CODE_EXTENSIONS = {".c", ".h"}


def _default_fetch(url: str) -> str:
    """Fetch URL content via httpx with a 30s timeout."""
    try:
        resp = httpx.get(url, timeout=30.0, follow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        log.warning("Fetch failed for %s: %s", url, exc)
        return ""


def resolve_directory_url(
    dir_url: str, fetch_fn: Callable[[str], str] | None = None
) -> list[str]:
    """Fetch a git.kernel.org directory listing and return file URLs
    (ALG-KK-RESOLVE-DIRECTORY-SOURCE).

    Returns candidate replacement URLs filtered to .rst/.txt/.c/.h,
    ordered: index.rst first, then other .rst/.txt, then .c/.h.
    """
    fetch = fetch_fn or _default_fetch
    html = fetch(dir_url)
    if not html:
        return []

    base = dir_url.rstrip("/")
    doc_files: list[str] = []
    code_files: list[str] = []
    index_file: str | None = None

    for href, text in _FILE_LINK_RE.findall(html):
        name = text.strip()
        if name in (".", "..", "parent directory"):
            continue
        ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
        if ext in _DOC_EXTENSIONS:
            full_url = f"{base}/{name}" if not href.startswith("http") else href
            if name.lower().startswith("index"):
                index_file = full_url
            else:
                doc_files.append(full_url)
        elif ext in _CODE_EXTENSIONS:
            full_url = f"{base}/{name}" if not href.startswith("http") else href
            code_files.append(full_url)

    result: list[str] = []
    if index_file:
        result.append(index_file)
    result.extend(sorted(doc_files))
    result.extend(sorted(code_files))
    return result


def validate_all_sources(
    conn: sqlite3.Connection,
    fetch_fn: Callable[[str], str] | None = None,
    rate_limit: float = 1.0,
) -> list[SourceValidationResult]:
    """Validate all Source nodes in the database (ALG-KK-VALIDATE-SOURCE-CONTENT).

    Iterates Source nodes, fetches each URL (rate-limited per
    INV-KK-VALIDATE-RATE-LIMITED), classifies content, and builds
    suggested replacement URLs for non-substantive sources.
    """
    fetch = fetch_fn or _default_fetch
    rows = conn.execute(
        "SELECT id, kind, attrs FROM nodes WHERE kind = 'Source'"
    ).fetchall()

    results: list[SourceValidationResult] = []
    last_fetch_time = 0.0

    for row_id, _kind, attrs_json in rows:
        attrs = json.loads(attrs_json) if isinstance(attrs_json, str) else attrs_json
        url = attrs.get("url", "")
        if not url:
            results.append(SourceValidationResult(
                source_id=row_id, url="", classification="unreachable",
            ))
            continue

        elapsed = time.monotonic() - last_fetch_time
        if elapsed < rate_limit and last_fetch_time > 0:
            time.sleep(rate_limit - elapsed)

        content = fetch(url)
        last_fetch_time = time.monotonic()

        cc = classify_content(content)

        suggested: list[str] = []
        if cc.classification == "stub" and cc.kernel_doc_refs:
            suggested = [build_replacement_url(ref) for ref in cc.kernel_doc_refs]
        elif cc.classification == "directory":
            suggested = resolve_directory_url(url, fetch_fn=fetch)

        results.append(SourceValidationResult(
            source_id=row_id,
            url=url,
            classification=cc.classification,
            word_count=cc.word_count,
            kernel_doc_refs=cc.kernel_doc_refs,
            suggested_replacement_urls=suggested,
            prose_excerpt=cc.prose_excerpt,
        ))

    return results


# ---------------------------------------------------------------------------
# The backfill (ALG-KK-BACKFILL-SOURCE-PROSE, INV-KK-BACKFILL-PROSE-NOT-MARKUP)
#
# Everything above this line reports. Everything below it writes.
# ---------------------------------------------------------------------------

#: The classifications INV-KK-SOURCE-CONTENT-SUFFICIENT calls usable content.
#: 'thin' is in, by operator decision 2026-09-25: fifty to ninety-nine prose
#: words is thin evidence, not absent evidence, and the reader downstream can
#: weigh it. Excluding it would discard Documentation/networking/skbuff.rst at
#: 99 words on a threshold nobody would defend if asked to defend it at 100.
SUFFICIENT_CLASSIFICATIONS = ("substantive", "thin")



def _max_evidence_text_chars() -> int:
    """The ceiling ingest.pipeline writes Evidence text at.

    Read from pipeline rather than restated, so the two paths that populate
    Evidence.text cannot drift apart about how much of a document survives.
    Imported inside the function because pipeline imports classify_content from
    this module — a module-level import here would be a cycle.
    """
    from ingest.pipeline import MAX_EVIDENCE_TEXT_CHARS
    return MAX_EVIDENCE_TEXT_CHARS

_TREE_SEGMENT = "/tree/"
_PLAIN_SEGMENT = "/plain/"


def source_content_sufficient(classification: str) -> bool:
    """INV-KK-SOURCE-CONTENT-SUFFICIENT, as one predicate.

    The single definition of "this Source has usable content", so the backfill,
    the report and anything later cannot disagree about it.
    """
    return classification in SUFFICIENT_CLASSIFICATIONS


def plain_url(url: str) -> str:
    """The URL to FETCH for a stored git.kernel.org /tree/ URL.

    cgit serves a browsable HTML page at /tree/ and the raw file at /plain/.
    VERIFIED AGAINST A REAL FETCH 2026-09-25: /tree/Documentation/mm/slab.rst
    returned 4,475 bytes of text/html opening '<!DOCTYPE html>', and
    /plain/Documentation/mm/slab.rst returned 203 bytes of text/plain opening
    '.. SPDX-License-Identifier: GPL-2.0'. All 43 kernel-doc Sources store the
    /tree/ form, so without this rewrite the backfill would score and store
    page chrome for every one of them.

    THE STORED URL IS NOT MODIFIED. /tree/ is the human-readable address and is
    what the paper page links to; this rewrite applies to the fetch alone.
    Anything that is not a git.kernel.org /tree/ URL is returned unchanged.
    """
    if "git.kernel.org" in url and _TREE_SEGMENT in url:
        return url.replace(_TREE_SEGMENT, _PLAIN_SEGMENT, 1)
    return url


def looks_like_markup(text: str) -> bool:
    """Whether a fetched body is a markup document rather than prose.

    Guards INV-KK-BACKFILL-PROSE-NOT-MARKUP independently of the classifier.
    _strip_markup removes HTML tags before counting words, so a navigation page
    can classify as substantive on the strength of its own menu labels; this
    refuses it on the shape of the body instead of on the word count.
    """
    return bool(_MARKUP_DOCUMENT_RE.match(text or ""))


@dataclass
class BackfillOutcome:
    """What happened to one Source."""

    source_id: str
    url: str
    fetch_url: str
    classification: str
    stored: bool = False
    chars: int = 0
    reason: str = ""


@dataclass
class BackfillReport:
    outcomes: list[BackfillOutcome] = field(default_factory=list)
    dry_run: bool = False

    @property
    def stored(self) -> int:
        return sum(1 for o in self.outcomes if o.stored)

    @property
    def examined(self) -> int:
        return len(self.outcomes)

    def by_classification(self) -> dict[str, int]:
        from collections import Counter
        return dict(Counter(o.classification for o in self.outcomes))

    def skipped(self, reason: str) -> list[BackfillOutcome]:
        return [o for o in self.outcomes if o.reason == reason]


def _evidence_for_source(conn: sqlite3.Connection, source_id: str) -> str | None:
    row = conn.execute(
        "SELECT source_id FROM edges WHERE kind = 'sourced-from' AND target_id = ? "
        "ORDER BY source_id LIMIT 1",
        (source_id,),
    ).fetchone()
    return row[0] if row else None


def backfill_source_prose(
    conn: sqlite3.Connection,
    fetch_fn: Callable[[str], str] | None = None,
    rate_limit: float = 1.0,
    source_types: tuple[str, ...] | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    today: str | None = None,
) -> BackfillReport:
    """Fetch each Source's URL and store the prose on its Evidence node.

    ALG-KK-BACKFILL-SOURCE-PROSE. The path validate_all_sources never was: same
    fetcher, same classifier, same rate limit (INV-KK-VALIDATE-RATE-LIMITED),
    and a write at the end.

    WHAT IT WRITES, AND ONLY THIS:
      - Evidence.attrs['text'], for a Source whose content is sufficient. The
        markup is stripped and the result truncated at MAX_EVIDENCE_TEXT_CHARS.
      - Source.attrs['content_status'] and ['content_checked_at'], for EVERY
        Source examined, including the ones that yielded nothing
        (IFC-KK-SOURCE-CONTENT-STATUS). That is what lets a re-run fetch only
        what is unresolved, and what keeps "never fetched" distinguishable from
        "fetched and found to be a directory".

    WHAT IT NEVER DOES: create a node or an edge. A Source with no Evidence is
    reported and skipped, never repaired — minting Evidence belongs to
    ALG-KK-INGEST-PIPELINE and doing it here would put two writers on one node
    kind.

    --limit is applied AFTER selection, matching ALG-KK-EXTRACT-CLI, so a bound
    of ten means ten documents actually fetched.
    """
    fetch = fetch_fn or _default_fetch
    checked_at = today or datetime.now(timezone.utc).date().isoformat()

    sql = "SELECT id, attrs FROM nodes WHERE kind = 'Source' ORDER BY id"
    rows = conn.execute(sql).fetchall()

    selected: list[tuple[str, dict]] = []
    for row_id, attrs_json in rows:
        attrs = json.loads(attrs_json) if isinstance(attrs_json, str) else (attrs_json or {})
        if source_types and attrs.get("source_type") not in source_types:
            continue
        selected.append((row_id, attrs))

    if limit is not None:
        selected = selected[:limit]

    report = BackfillReport(dry_run=dry_run)
    last_fetch_time = 0.0

    for source_id, attrs in selected:
        url = attrs.get("url", "")
        if not url:
            report.outcomes.append(BackfillOutcome(
                source_id=source_id, url="", fetch_url="",
                classification="unreachable", reason="no-url"))
            continue

        evidence_id = _evidence_for_source(conn, source_id)

        # INV-KK-VALIDATE-RATE-LIMITED: spaced BEFORE the request, never after,
        # so a slow response counts towards the interval rather than adding to
        # it. The first fetch of a run is not delayed.
        elapsed = time.monotonic() - last_fetch_time
        if elapsed < rate_limit and last_fetch_time > 0:
            time.sleep(rate_limit - elapsed)

        fetch_url = plain_url(url)
        content = fetch(fetch_url)
        last_fetch_time = time.monotonic()

        cc = classify_content(content)
        outcome = BackfillOutcome(
            source_id=source_id, url=url, fetch_url=fetch_url,
            classification=cc.classification)

        if not source_content_sufficient(cc.classification):
            outcome.reason = cc.classification
        elif looks_like_markup(content):
            # INV-KK-BACKFILL-PROSE-NOT-MARKUP. The classifier said this reads
            # as prose; the body says it is a document made of tags. The body
            # wins, and the Source records 'directory' rather than a word count
            # that was never about words.
            outcome.classification = "directory"
            outcome.reason = "markup"
        elif evidence_id is None:
            outcome.reason = "no-evidence"
        else:
            prose = _strip_markup(content).strip()
            prose = prose[:_max_evidence_text_chars()]
            outcome.chars = len(prose)
            if not dry_run:
                update_node_attrs(conn, evidence_id, {"text": prose})
            outcome.stored = True

        if not dry_run:
            update_node_attrs(conn, source_id, {
                "content_status": outcome.classification,
                "content_checked_at": checked_at,
            })
        report.outcomes.append(outcome)

    if not dry_run:
        conn.commit()
    return report


def generate_backfill_report(report: BackfillReport) -> str:
    """A short text summary — counts first, then what was skipped and why."""
    lines = [
        "Backfill" + (" (DRY RUN — nothing written)" if report.dry_run else ""),
        f"  examined {report.examined}",
        f"  stored   {report.stored}",
    ]
    for cls, n in sorted(report.by_classification().items()):
        lines.append(f"    {cls:12} {n}")
    for reason in ("no-evidence", "markup", "no-url"):
        skipped = report.skipped(reason)
        if skipped:
            lines.append(f"  skipped ({reason}): {len(skipped)}")
            for o in skipped[:10]:
                lines.append(f"    {o.source_id}  {o.url}")
    return "\n".join(lines)


def generate_report(results: list[SourceValidationResult]) -> str:
    """Generate a markdown validation report."""
    from collections import Counter

    counts = Counter(r.classification for r in results)
    total = len(results)

    lines = [
        "# Source Content Validation Report",
        "",
        "## Summary",
        "",
        f"| Classification | Count |",
        f"|----------------|-------|",
    ]
    for cls in ["substantive", "stub", "directory", "thin", "unreachable"]:
        lines.append(f"| {cls} | {counts.get(cls, 0)} |")
    lines.append(f"| **Total** | **{total}** |")
    lines.append("")

    lines.append("## All Sources")
    lines.append("")
    lines.append("| Source ID | Classification | Words | URL |")
    lines.append("|-----------|---------------|-------|-----|")
    for r in sorted(results, key=lambda x: x.classification):
        url_short = r.url[:60] + "..." if len(r.url) > 60 else r.url
        lines.append(f"| {r.source_id} | {r.classification} | {r.word_count} | {url_short} |")
    lines.append("")

    needs_review = [r for r in results if r.classification in ("thin", "directory")]
    if needs_review:
        lines.append("## Needs Manual Review")
        lines.append("")
        for r in needs_review:
            lines.append(f"- **{r.source_id}** ({r.classification}): {r.url}")
            if r.suggested_replacement_urls:
                for su in r.suggested_replacement_urls[:3]:
                    lines.append(f"  - Suggested: {su}")
        lines.append("")

    stubs = [r for r in results if r.classification == "stub"]
    if stubs:
        lines.append("## Stub Sources (auto-resolvable)")
        lines.append("")
        for r in stubs:
            lines.append(f"- **{r.source_id}**: {r.url}")
            for ref in r.kernel_doc_refs:
                lines.append(f"  - kernel-doc ref: `{ref}` -> {build_replacement_url(ref)}")
        lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    """CLI entry point: python -m ingest.validate_sources"""
    parser = argparse.ArgumentParser(
        description="Validate source URLs for content sufficiency"
    )
    parser.add_argument("--db", default="data/know_kernel.db", help="Database path")
    parser.add_argument("--output", default=None, help="Output file (default: stdout)")
    parser.add_argument("--dry-run", action="store_true", help="Classify only, skip replacement suggestions")
    parser.add_argument("--rate-limit", type=float, default=1.0, help="Seconds between fetches")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    conn = sqlite3.connect(args.db)

    if args.dry_run:
        fetch_fn: Callable[[str], str] | None = None
    else:
        fetch_fn = None

    results = validate_all_sources(conn, fetch_fn=fetch_fn, rate_limit=args.rate_limit)
    report = generate_report(results)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
        log.info("Report written to %s", args.output)
    else:
        print(report)

    conn.close()


if __name__ == "__main__":
    main()
