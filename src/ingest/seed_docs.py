"""Seed Sources and Evidence from canonical-documentation subtrees.

ALG-KK-SEED-DOC-SUBTREE. THE HARVEST RAN OUT OF DOCUMENTS AND THIS REFILLS IT.
Measured 2026-09-28: all 18 kernel-doc Evidence nodes carrying prose are
harvested, and the other 25 are 17 directories, 7 dead URLs and 1 stub. Growing
the vocabulary needs more documents, not another pass over the same ones.

IT REUSES BOTH HALVES RATHER THAN GROWING A THIRD. The fetch is
validate_sources._default_fetch under INV-KK-VALIDATE-RATE-LIMITED; the write is
pipeline.ingest_document under ALG-KK-INGEST-PIPELINE. This module is the join
between them and owns no fetching and no node-writing of its own, except the
licence Advisory that ingest_document deliberately does not write.

Spec: ALG-KK-SEED-DOC-SUBTREE, INV-KK-SEED-PATH-DEFINITIONAL,
      IFC-KK-DOC-DEFINED-PROVENANCE (which paths define),
      INV-KK-INGEST-SOURCE-HAS-ADVISORY (this path conforms).
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from graph.engine import add_edge, add_node
from graph.rules import DOC_PATH_PREFIXES, path_is_definitional
from ingest.pipeline import ingest_document
from ingest.validate_sources import (
    _default_fetch,
    classify_content,
    plain_url,
    source_content_sufficient,
)

log = logging.getLogger(__name__)

#: The licence assessment every kernel-doc Source carries. Verbatim from the 43
#: that already exist — the same licence and the same claim, so a second wording
#: for one fact would make the corpus harder to audit rather than easier.
KERNEL_DOC_ASSESSMENT = (
    "GPL-2.0 kernel documentation, abstraction-safe after transformation"
)
KERNEL_DOC_LICENSE = "GPL-2.0"
KERNEL_DOC_SOURCE_TYPE = "kernel-doc"

_RST_LINK_RE = re.compile(r">([^<]+\.rst)</a>")

#: Every anchor in a cgit /plain/ listing, as (href, visible name).
#:
#: THE HREF IS WHAT SEPARATES A DIRECTORY FROM A FILE, AND THE VISIBLE NAME IS
#: NOT. Measured against the live listing of Documentation/filesystems/ on
#: 2026-09-29: the subdirectories ext4, xfs, nfs, fuse, caching, gfs2, iomap,
#: smb and spufs render WITHOUT a trailing slash, exactly like the files
#: path-lookup.txt and propagate_umount.txt beside them. Only their HREF
#: carries one:
#:
#:     <a href='.../filesystems/9p.rst'>9p.rst</a>      <- a file
#:     <a href='.../filesystems/ext4/'>ext4</a>         <- a directory
#:
#: Guessing from the name — "it has no extension, so it is a directory" —
#: would classify path-lookup.txt correctly by accident and break on the first
#: extensionless file the kernel adds.
_ENTRY_RE = re.compile(r"<a href='([^']*)'>([^<]+)</a>")

#: The parent link, which is the one entry whose NAME does carry a slash.
_PARENT_NAME = "../"

#: How deep list_subtree will walk. Documentation/ is three levels at its
#: deepest (userspace-api/media/v4l/), and an unbounded walk over a listing
#: service is how a seeding run becomes a crawl.
MAX_SUBTREE_DEPTH = 3


@dataclass
class SeedOutcome:
    url: str
    seeded: bool = False
    source_id: str = ""
    reason: str = ""
    chars: int = 0


@dataclass
class SeedReport:
    outcomes: list[SeedOutcome] = field(default_factory=list)
    dry_run: bool = False

    @property
    def seeded(self) -> int:
        return sum(1 for o in self.outcomes if o.seeded)

    def by_reason(self) -> dict[str, int]:
        from collections import Counter
        return dict(Counter(o.reason for o in self.outcomes if o.reason))


def list_subtree(
    subtree_url: str,
    fetch_fn: Callable[[str], str] | None = None,
    max_depth: int = MAX_SUBTREE_DEPTH,
) -> list[str]:
    """Every .rst document in a subtree AND ITS SUBDIRECTORIES, as /tree/ urls.

    The listing is fetched from the /plain/ form, which returns a bare <ul> of
    links; the /tree/ form returns a full cgit page. The urls returned are the
    /tree/ form, because that is the human-readable address a reader opens and
    the one ALG-KK-BACKFILL-SOURCE-PROSE decided to keep as canonical.

    IT DID NOT RECURSE UNTIL 2026-09-29, AND IT REPORTED SUCCESS ANYWAY. The
    old body applied one regex to one directory's listing, so it returned the
    .rst files at that level and nothing beneath. Documentation/filesystems/
    keeps its substantial per-filesystem documentation in SUBDIRECTORIES, so
    the 2026-09-29 seeding run offered the seeder 78 flat files and never saw
    the other 70 — ext4/ 27, nfs/ 12, fuse/ 6, caching/ 5, xfs/ 5, smb/ 4,
    spufs/ 4, iomap/ 4, gfs2/ 3. The run was justified by "seeding
    filesystems/ is how XFS Filesystem stops being evidence-free"; XFS
    Filesystem's five documents were in xfs/ and it ended the run exactly as
    evidence-free as it began.

    THE WALK IS BOUNDED AND ORDERED. max_depth stops an unbounded crawl of a
    listing service; the result is sorted so a dry run and the seed that
    follows it agree on order, which is the contract ALG-KK-SEED-DOC-SUBTREE
    offers and the reason its 2026-09-28 counts held exactly.

    A SUBDIRECTORY THAT CANNOT BE LISTED IS SKIPPED, NOT FATAL — one
    unreachable subdirectory must not cost the documents found beside it. THE
    TOP LEVEL IS NOT COVERED BY THAT, AND THE ASYMMETRY IS DELIBERATE: a
    subtree whose own listing fails RAISES. Swallowing it would return an empty
    list and report success, which is the failure this function is being
    repaired for, and it would be the second time.
    """
    fetch = fetch_fn or _default_fetch
    found: list[str] = []
    seen: set[str] = set()

    def walk(url: str, depth: int) -> None:
        base = url.rstrip("/")
        if base in seen:
            return
        seen.add(base)
        # The url is fetched AS GIVEN, trailing slash and all. Normalising it
        # here would fetch a different address than the caller named.
        try:
            html = fetch(plain_url(url)) or ""
        except Exception:
            if depth == 0:
                raise
            return
        subdirs: list[str] = []
        for href, name in _ENTRY_RE.findall(html):
            if name == _PARENT_NAME:
                continue
            if href.endswith("/"):
                subdirs.append(name.rstrip("/"))
            elif name.endswith(".rst"):
                found.append(f"{base}/{name}")
        if depth < max_depth:
            for sub in sorted(set(subdirs)):
                walk(f"{base}/{sub}", depth + 1)

    walk(subtree_url, 0)
    return sorted(set(found))


def existing_source_urls(conn: sqlite3.Connection) -> set[str]:
    """Every url already registered, so a re-run adds only what is missing."""
    return {
        r[0] for r in conn.execute(
            "SELECT json_extract(attrs, '$.url') FROM nodes WHERE kind = 'Source'"
        ).fetchall() if r[0]
    }


def _write_advisory(conn: sqlite3.Connection, source_id: str) -> str:
    """The licence Advisory ingest_document deliberately does not write.

    INV-KK-INGEST-SOURCE-HAS-ADVISORY is violated 3,531 times of 3,574 because
    the ingest path creates none. All 43 existing kernel-doc Sources conform;
    writing the same Advisory here means seeding 129 more documents does not
    grow that number by 129. The 3,531 legacy Sources are not touched — what
    assessment a paper deserves is a larger decision made elsewhere.
    """
    advisory_id = f"adv-{uuid.uuid4().hex[:12]}"
    add_node(conn, advisory_id, "Advisory", {
        "assessment": KERNEL_DOC_ASSESSMENT,
        "contamination_confirmed": False,
    })
    add_edge(conn, "assessed-by", source_id, advisory_id)
    return advisory_id


def seed_subtree(
    conn: sqlite3.Connection,
    subtree_url: str,
    fetch_fn: Callable[[str], str] | None = None,
    rate_limit: float = 1.0,
    limit: int | None = None,
    dry_run: bool = False,
) -> SeedReport:
    """Seed one documentation subtree.

    A path outside DOC_PATH_PREFIXES is refused BEFORE any fetch
    (INV-KK-SEED-PATH-DEFINITIONAL) — the rule exists to stop a bad source
    entering, so checking it after paying for the document would be theatre.

    --limit applies after selection and after the already-seeded filter, so a
    bound of ten means ten documents actually fetched, matching
    ALG-KK-EXTRACT-CLI rather than inventing a third convention.
    """
    fetch = fetch_fn or _default_fetch
    report = SeedReport(dry_run=dry_run)

    if not path_is_definitional(subtree_url):
        report.outcomes.append(SeedOutcome(
            url=subtree_url, reason="refused-path"))
        return report

    urls = list_subtree(subtree_url, fetch_fn=fetch)
    known = existing_source_urls(conn)

    pending: list[str] = []
    for url in urls:
        if not path_is_definitional(url):
            report.outcomes.append(SeedOutcome(url=url, reason="refused-path"))
        elif url in known:
            report.outcomes.append(SeedOutcome(url=url, reason="already-seeded"))
        else:
            pending.append(url)

    if limit is not None:
        pending = pending[:limit]

    last_fetch = 0.0
    for url in pending:
        # INV-KK-VALIDATE-RATE-LIMITED, spaced before the request and never
        # after it, so a slow response counts towards the interval.
        elapsed = time.monotonic() - last_fetch
        if elapsed < rate_limit and last_fetch > 0:
            time.sleep(rate_limit - elapsed)
        body = fetch(plain_url(url))
        last_fetch = time.monotonic()

        # INV-KK-SOURCE-CONTENT-SUFFICIENT, checked HERE and not left to
        # ingest_document. That gate raises on 'stub' and 'directory' but NOT
        # on 'unreachable', so a toctree index.rst — which is what every
        # subtree's index is — would be seeded as a Source with no usable
        # text. That is precisely the state ALG-KK-BACKFILL-SOURCE-PROSE was
        # written to repair on 43 existing Sources; seeding 129 more of them
        # would be repeating the defect knowingly.
        classification = classify_content(body).classification
        if not source_content_sufficient(classification):
            report.outcomes.append(SeedOutcome(url=url, reason=classification))
            continue
        if dry_run:
            report.outcomes.append(SeedOutcome(
                url=url, reason="dry-run", chars=len(body)))
            continue

        # ingest_document takes a file_path, not a URL. Writing a temp file is
        # what lets this reuse the one ingest path instead of growing a second.
        handle, tmp = tempfile.mkstemp(suffix=".rst")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as fh:
                fh.write(body)
            result = ingest_document(conn, tmp, url, KERNEL_DOC_SOURCE_TYPE)
        except ValueError as exc:
            # The stub and directory gate already in ingest_document
            # (INV-KK-INGEST-REJECTS-STUB, INV-KK-INGEST-REJECTS-DIRECTORY).
            # Each subtree carries an index.rst that is a table of contents and
            # is refused here. That is the gate working, and it is COUNTED —
            # a seed that silently skipped them would look identical to a
            # subtree that had none.
            reason = "refused-stub" if "stub" in str(exc) else (
                "refused-directory" if "directory" in str(exc) else "refused")
            report.outcomes.append(SeedOutcome(url=url, reason=reason))
            continue
        finally:
            os.unlink(tmp)

        _write_advisory(conn, result.source_id)
        report.outcomes.append(SeedOutcome(
            url=url, seeded=True, source_id=result.source_id,
            chars=result.text_length))

    if not dry_run:
        conn.commit()
    return report


def format_seed_report(report: SeedReport) -> str:
    head = "Seed" + (" (DRY RUN — nothing written)" if report.dry_run else "")
    lines = [head, f"  seeded    {report.seeded}"]
    for reason, n in sorted(report.by_reason().items()):
        lines.append(f"    {reason:18} {n}")
    return "\n".join(lines)
