"""Source content classification and validation for provenance grounding.

Spec: ALG-KK-CLASSIFY-SOURCE-CONTENT, ALG-KK-EXTRACT-KERNEL-DOC-REFS,
      INV-KK-SOURCE-CONTENT-SUFFICIENT, ALG-KK-VALIDATE-SOURCE-CONTENT,
      ALG-KK-RESOLVE-DIRECTORY-SOURCE, INV-KK-VALIDATE-RATE-LIMITED
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

log = logging.getLogger(__name__)


GIT_KERNEL_ORG_BLOB = (
    "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/{path}"
)

_KERNEL_DOC_RE = re.compile(r"\.\.\s+kernel-doc::\s+(\S+)")

_DIRECTORY_MARKERS = [
    '<table class="list">',
    "drwxr-xr-x",
    '<td class="ls-mode">',
]

_RST_DIRECTIVE_RE = re.compile(r"^\.\.\s+\S+::", re.MULTILINE)
_RST_ROLE_RE = re.compile(r":\w+:`[^`]*`")
_CODE_BLOCK_RE = re.compile(
    r"(?s)\.\.\s+code-block::\s*\w*\n(?:[ \t]+[^\n]*\n?)+", re.MULTILINE
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

    if any(marker in text for marker in _DIRECTORY_MARKERS):
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
