"""Reconcile a Source title against the document its identifier resolves to
(ALG-KK-SOURCE-TITLE-RECONCILE, INV-KK-SOURCE-TITLE-MATCHES-IDENTITY).

WHY THE TITLE AND NOT ANYTHING ELSE. Measured 2026-09-18: on every affected
record examined, the url, the identifier, the Evidence text, the abstract fetched
independently from OpenAlex, and the generated summary all agree with each other,
and the title is the single field that does not. src-arxiv-00013612 is titled
"AgenTEE: Confidential LLM Agent Execution on Edge Devices" while its identifier,
abstract and summary all describe a commit-open SAE-feature-trace protocol.
Trusting the title and rewriting the rest would discard four corroborating fields
in favour of the one shown to be wrong.

A random sample of 200 papers with a resolvable identifier, 187 of which OpenAlex
answered for, showed 16.0% mismatched. One contiguous 120-row window ran at 42%,
so the damage is clustered rather than uniform. Only 8 of 49 mismatches in that
window were explained by an off-by-one against insertion order; 41 matched
nothing at any offset from -3 to +3. Re-pairing neighbours would have repaired a
minority and mangled the rest.

WHAT THIS DOES NOT DO. It does not touch summaries. Each summary was derived from
the abstract or Evidence of the document its identifier names and describes that
document correctly; an earlier diagnosis that they described the wrong paper was
mistaken. Reconciling the title makes the record coherent and leaves the summary
right.

THE COMPARISON IS BLUNT ON PURPOSE. Jaccard over lowercased word tokens of length
3 or more. A sharper measure invites tuning until the number looks acceptable.
This one is reported with the count of what it changed, and every replacement
keeps the old value in title_before_reconcile so the decision stays auditable.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from ingest.abstract_fetcher import (
    OPENALEX_API,
    OPENALEX_CONTAINER_TYPE,
    USER_AGENT,
    Fetch,
    Identifier,
    RouteTransportError,
    _urllib_fetch,
    resolve_identifier,
)

PAPER_SOURCE_TYPES = ("preprint", "conference-paper", "conference-proceedings")

# Below this the two titles are judged to name different works. Chosen against
# the measured distribution, where genuine matches clustered well above it and
# mismatches sat at or near zero overlap.
TITLE_MATCH_FLOOR = 0.35

CALL_INTERVAL_SECONDS = 0.05

_VERSION_SUFFIX_RE = re.compile(r"v\d+$")
_WORD_RE = re.compile(r"[a-z0-9]+")


def title_tokens(text: str | None) -> set[str]:
    """Lowercased word tokens of length 3 or more."""
    return {w for w in _WORD_RE.findall((text or "").lower()) if len(w) > 2}


def titles_agree(stored: str | None, authoritative: str | None) -> bool:
    """Whether two titles name the same work, by blunt token overlap."""
    a, b = title_tokens(stored), title_tokens(authoritative)
    if not a or not b:
        return False
    return len(a & b) / len(a | b) >= TITLE_MATCH_FLOOR


def authoritative_title(identifier: Identifier, fetch: Fetch) -> str | None:
    """The title OpenAlex holds for this identifier, or None.

    None covers three distinct cases the caller does not need to tell apart,
    because all three mean the same thing here: do not touch this record. No
    record; a record with no title; a record that is a proceedings CONTAINER,
    whose title is the volume's rather than the paper's.
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
    except Exception as exc:
        raise RouteTransportError("openalex", exc) from exc
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if data.get("type") == OPENALEX_CONTAINER_TYPE:
        return None
    return data.get("title") or None


@dataclass
class ReconcileReport:
    considered: int = 0
    reconciled: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    changes: list[dict] = field(default_factory=list)

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    def as_dict(self) -> dict:
        return {
            "considered": self.considered,
            "reconciled": self.reconciled,
            "skipped": self.skipped,
            "changes": self.changes,
        }


def reconcile_title(
    conn: sqlite3.Connection,
    source_id: str,
    fetch: Fetch = _urllib_fetch,
    dry_run: bool = False,
) -> tuple[str, dict | None]:
    """Reconcile one Source. Returns (outcome, change or None).

    Outcomes: reconciled, agrees, authority-less-specific, no-identifier,
    no-authority, transport-error.
    The title is the only field written; title_before_reconcile preserves what
    was there.
    """
    row = conn.execute("SELECT attrs FROM nodes WHERE id = ?", (source_id,)).fetchone()
    if row is None:
        raise ValueError(f"Source node '{source_id}' does not exist")
    attrs = json.loads(row[0]) if isinstance(row[0], str) else (row[0] or {})

    identifier = resolve_identifier(attrs.get("url"))
    if identifier is None:
        return "no-identifier", None
    try:
        real = authoritative_title(identifier, fetch)
    except RouteTransportError:
        return "transport-error", None
    if not real:
        return "no-authority", None

    # The authority answered, so this record HAS been checked whatever the
    # comparison concludes. Stamping only the records we change would leave the
    # ones that were already correct indistinguishable from the ones nobody ever
    # looked at — which is exactly the hole the first corpus run left, and what
    # the title_verified dimension of IFC-KK-PAPER-COMPLETENESS needs closed.
    def _stamp(a: dict) -> None:
        a["title_reconciled_at"] = date.today().isoformat()

    stored = attrs.get("title") or ""
    if titles_agree(stored, real):
        if not dry_run:
            _stamp(attrs)
            conn.execute("UPDATE nodes SET attrs = ? WHERE id = ?",
                         (json.dumps(attrs), source_id))
        return "agrees", None

    # The authority is sometimes LESS specific than what we hold. Several ACM
    # records store only the short name before the colon — "PathFS" for "PathFS:
    # A File System for the Hierarchical Edge" — and the blunt comparison judges
    # those different. Replacing the fuller title with the stub would lose real
    # information to fix nothing, so a new title whose words are wholly contained
    # in the old one is refused. Found on 2026-09-18 by reading what the first
    # corpus run had actually written: 4 of 520 records were damaged this way.
    if title_tokens(real) and title_tokens(real) <= title_tokens(stored):
        # Still checked: the authority answered and we kept our fuller title.
        if not dry_run:
            _stamp(attrs)
            conn.execute("UPDATE nodes SET attrs = ? WHERE id = ?",
                         (json.dumps(attrs), source_id))
        return "authority-less-specific", None

    change = {
        "source_id": source_id,
        "identifier": f"{identifier.kind}:{identifier.value}",
        "was": stored,
        "now": real,
    }
    if not dry_run:
        attrs["title_before_reconcile"] = stored
        attrs["title"] = real
        _stamp(attrs)
        conn.execute("UPDATE nodes SET attrs = ? WHERE id = ?", (json.dumps(attrs), source_id))
    return "reconciled", change


def run_batch(
    conn: sqlite3.Connection,
    fetch: Fetch = _urllib_fetch,
    dry_run: bool = False,
    limit: int | None = None,
    pause: float = CALL_INTERVAL_SECONDS,
    progress=None,
) -> ReconcileReport:
    report = ReconcileReport()
    placeholders = ", ".join("?" for _ in PAPER_SOURCE_TYPES)
    sql = (
        f"SELECT id FROM nodes WHERE kind = 'Source' "
        f"AND json_extract(attrs, '$.source_type') IN ({placeholders}) ORDER BY id"
    )
    params: list = list(PAPER_SOURCE_TYPES)
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    for (source_id,) in conn.execute(sql, params).fetchall():
        report.considered += 1
        outcome, change = reconcile_title(conn, source_id, fetch=fetch, dry_run=dry_run)
        if outcome == "reconciled":
            report.reconciled += 1
            report.changes.append(change)
        elif outcome != "agrees":
            report.skip(outcome)
        if not dry_run and outcome in ("reconciled", "agrees", "authority-less-specific"):
            # Commit per row: an interrupted run keeps every check it has made.
            conn.commit()
        if progress:
            progress(f"{source_id} {outcome}")
        if pause:
            time.sleep(pause)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kk-reconcile-titles",
        description=__doc__.split("\n")[0],
    )
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    conn = sqlite3.connect(str(args.db))
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        report = run_batch(
            conn, dry_run=args.dry_run, limit=args.limit,
            progress=None if args.quiet else lambda m: print(m, file=sys.stderr),
        )
        if not args.dry_run:
            conn.commit()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()

    print(f"[{'DRY RUN' if args.dry_run else 'APPLIED'}]")
    print(json.dumps(report.as_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
