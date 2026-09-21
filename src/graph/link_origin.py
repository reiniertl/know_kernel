"""Attributing a provenance edge to the mechanism that wrote it.

The edges table records no creation time and no writer, so the only evidence
about where an extracted-from edge came from is the SHAPE OF THE ID AT ITS
SOURCE END. That turns out to be strong evidence here: every node-minting site
in this codebase writes ``f"<prefix>-{uuid.uuid4().hex[:12]}"``, and the
prefixes do not overlap between writers.

    src/ingest/extractor.py     concept- kinv- fm- proto- profile- compat-
    src/ingest/claim_extractor  prob- obs- prop- bench- rej- disc-

The assumption this rests on is that no EARLIER revision minted a different
shape. Each prefix was traced with ``git log -S`` over src/ and nothing
contradicts it, but a slug-minting revision older than the searched history
would break the classification. ANN-KK-UNLINKED-PROVENANCE-CENSUS states that
assumption so it can be falsified rather than quietly relied on.

Nothing here dates an edge. Per INV-KK-EXTRACT-EVIDENCE-RECORDED the markers
carry no checked_at: knowing which program wrote an edge is not knowing when,
and a date invented per group would drag these edges inside that invariant's
scope on a fiction.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field

from graph.rules import (
    CLAIM_EXTRACT_UNVERIFIED_BASIS,
    EXTRACTOR_PREVERDICT_BASIS,
    LEGACY_UNVERIFIED_BASIS,
    MECHANISM_UNATTRIBUTED_BASIS,
    OUT_OF_SCOPE_BASES,
)

#: uuid.uuid4().hex[:12] — the suffix every writer in this codebase produces.
_MINTED_SUFFIX = re.compile(r"^[0-9a-f]{12}$")

#: src/ingest/claim_extractor.py, at :398, :421, :441, :467, :488 and :509.
CLAIM_EXTRACT_PREFIXES = ("prob", "obs", "prop", "bench", "rej", "disc")

#: src/ingest/extractor.py, at :448, :497, :561, :617, :686 and :771.
#:
#: "concept" is DELIBERATELY ABSENT. store_rich_concept does mint concept- ids,
#: but every concept- provenance edge in this corpus was written by the
#: title-regex linker and already carries LEGACY_UNVERIFIED_BASIS. An UNMARKED
#: concept- edge would therefore be ambiguous between that linker and the
#: extractor's pre-verdict era, and "unattributed" is the honest answer for an
#: ambiguous case. Adding it here would assert the extractor wrote something
#: the evidence does not place.
EXTRACTOR_PREFIXES = ("kinv", "fm", "proto", "profile", "compat", "analysis")

#: What each marker says, stored on the edge so a reader of the graph alone can
#: tell why it has no verdict.
MECHANISM_NOTES = {
    CLAIM_EXTRACT_UNVERIFIED_BASIS: (
        "src/ingest/claim_extractor.py (ALG-KK-CLAIM-EXTRACT), identified by a "
        "uuid4 hex12 id under a prefix only that module mints. It is a live, "
        "sanctioned writer whose six writers pass no attrs; see "
        "INV-KK-CLAIM-EXTRACT-EVIDENCE-BARE. Not dated: the edges table "
        "records no creation time."),
    EXTRACTOR_PREVERDICT_BASIS: (
        "src/ingest/extractor.py before build_evidence_attrs existed "
        "(2026-09-21), identified by a uuid4 hex12 id under a prefix only that "
        "module mints. Same mechanism as today, earlier revision. Not dated: "
        "the edges table records no creation time."),
    MECHANISM_UNATTRIBUTED_BASIS: (
        "unknown. The source id matches no minting form in this codebase — "
        "either a hand-written slug no writer produces, or a hex12 id under a "
        "prefix whose minting form appears nowhere in src/ history. Nobody "
        "recorded what wrote this edge and it is not recoverable."),
}


def classify_link_origin(source_id: str) -> str:
    """Which marker basis the id at an edge's source end warrants.

    Pure function of the id. It never returns a value in VALID_EVIDENCE_BASES:
    every answer means "out of scope, and here is what is known".
    """
    prefix, _, suffix = source_id.partition("-")
    if not _MINTED_SUFFIX.match(suffix):
        return MECHANISM_UNATTRIBUTED_BASIS
    if prefix in CLAIM_EXTRACT_PREFIXES:
        return CLAIM_EXTRACT_UNVERIFIED_BASIS
    if prefix in EXTRACTOR_PREFIXES:
        return EXTRACTOR_PREVERDICT_BASIS
    return MECHANISM_UNATTRIBUTED_BASIS


def build_origin_marker(source_id: str) -> dict[str, object]:
    """The attrs to write onto one unmarked provenance edge.

    Mirrors the shape the 2,022 legacy edges carry — basis, grounded,
    mechanism, superseded — so the whole marked population reads the same way.
    superseded is False and stays False until a re-derivation replaces the
    edge; it is the slot that makes replacing-versus-superseding a later
    decision rather than a schema change.
    """
    basis = classify_link_origin(source_id)
    return {
        "basis": basis,
        "grounded": False,
        "mechanism": MECHANISM_NOTES[basis],
        "superseded": False,
    }


@dataclass
class MarkingResult:
    """What a marking pass did. examined counts every extracted-from edge."""
    examined: int = 0
    already_marked: int = 0
    in_scope_skipped: int = 0
    marked: int = 0
    by_basis: dict[str, int] = field(default_factory=dict)


def mark_unmarked_provenance_edges(
    conn: sqlite3.Connection, *, dry_run: bool = False
) -> MarkingResult:
    """Attach an origin marker to every provenance edge that has no basis.

    Three populations are left alone, each for its own reason:

    * edges already carrying one of OUT_OF_SCOPE_BASES — re-marking would
      overwrite the 2,022 legacy markers with a weaker guess;
    * edges carrying a checked_at — those are IN SCOPE and marking them would
      be exactly the "make the rule pass by relabelling" move rule 2 forbids;
    * edges whose attrs will not parse — they are already violations and the
      sweep reports them as such.
    """
    result = MarkingResult()
    rows = conn.execute(
        "SELECT source_id, target_id, attrs FROM edges "
        "WHERE kind = 'extracted-from'"
    ).fetchall()

    for source_id, target_id, raw in rows:
        result.examined += 1
        try:
            attrs = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except json.JSONDecodeError:
            continue
        if not isinstance(attrs, dict):
            continue
        if attrs.get("basis") in OUT_OF_SCOPE_BASES:
            result.already_marked += 1
            continue
        if attrs.get("basis") is not None or attrs.get("checked_at"):
            result.in_scope_skipped += 1
            continue

        marker = build_origin_marker(source_id)
        merged = {**attrs, **marker}
        result.marked += 1
        result.by_basis[marker["basis"]] = result.by_basis.get(
            marker["basis"], 0) + 1
        if not dry_run:
            conn.execute(
                "UPDATE edges SET attrs = ? WHERE kind = 'extracted-from' "
                "AND source_id = ? AND target_id = ?",
                (json.dumps(merged), source_id, target_id))
    return result


__all__ = [
    "CLAIM_EXTRACT_PREFIXES", "EXTRACTOR_PREFIXES", "MECHANISM_NOTES",
    "MarkingResult", "build_origin_marker", "classify_link_origin",
    "mark_unmarked_provenance_edges",
]
