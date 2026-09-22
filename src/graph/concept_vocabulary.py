"""The curated Concept vocabulary: matching against it, and what misses it.

INV-KK-CONCEPT-ADMISSION says a Concept is an established class and that
"Papers are linked to a curated vocabulary rather than minting a concept each".
This module is how a path links rather than mints.

THE MATCHER IS NOT NEW. Its three tiers — exact on the normalised name, then
prefix in either direction, then Levenshtein within a small distance — are the
ones src/ingest/claim_extractor.py has used on the discourse path since it was
written. It moved here on 2026-09-22 so the paper extractor could share it
instead of growing a second implementation; claim_extractor re-exports every
name below, so its callers and tests import exactly what they imported before.

EXACT MATCHING ALONE DOES NOT WORK, MEASURED. A matcher added to extractor.py
on 2026-09-21 required an exact normalised hit and matched 0 of 114 candidates
across two batches. Two things were wrong and only one of them was the matcher:
the model had never been SHOWN the vocabulary, so it proposed "uSTM" and
"BR-WFD Algorithm", which no amount of fuzziness rescues. Showing it the names
is build_vocabulary_context; matching loosely is what makes the showing survive
paraphrase.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

#: Levenshtein tolerance. Two edits catches plurals, a dropped hyphen and a
#: British/American spelling; it does not catch a different concept.
DEFAULT_MAX_DISTANCE = 2


def normalise_concept_name(name: str) -> str:
    """The key a concept name is matched on.

    casefold rather than lower: the corpus carries names taken from paper
    titles and the difference matters for the few that are not plain ASCII.
    """
    return " ".join(str(name or "").split()).casefold()


def levenshtein_distance(s: str, t: str) -> int:
    """Edit distance between two strings."""
    if len(s) < len(t):
        return levenshtein_distance(t, s)
    if not t:
        return len(s)
    prev = list(range(len(t) + 1))
    for i, sc in enumerate(s):
        curr = [i + 1]
        for j, tc in enumerate(t):
            cost = 0 if sc == tc else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]


def resolve_concept_names(conn: sqlite3.Connection) -> dict[str, str]:
    """normalised concept name -> node id, for every Concept in the graph."""
    rows = conn.execute(
        "SELECT id, json_extract(attrs, '$.name') FROM nodes WHERE kind = 'Concept'"
    ).fetchall()
    return {normalise_concept_name(r[1]): r[0] for r in rows if r[1]}


def fuzzy_match_concept(
    query: str, name_to_id: dict[str, str],
    max_distance: int = DEFAULT_MAX_DISTANCE,
) -> str | None:
    """Three-tier match: exact, prefix either way, then Levenshtein.

    Returns the concept node id, or None when nothing is close enough. None is
    a normal outcome and means "this is a candidate", not "this failed".
    """
    q = normalise_concept_name(query)
    if not q:
        return None
    if q in name_to_id:
        return name_to_id[q]
    for name, cid in name_to_id.items():
        if name.startswith(q) or q.startswith(name):
            return cid
    best_id, best = None, max_distance + 1
    for name, cid in name_to_id.items():
        d = levenshtein_distance(q, name)
        if d <= max_distance and d < best:
            best, best_id = d, cid
    return best_id


def build_vocabulary_context(conn: sqlite3.Connection) -> str:
    """The vocabulary, for the prompt.

    The half that was missing on 2026-09-21: a model asked to name concepts
    without being told which ones exist will name the paper's own artifact,
    and then no matcher can help. Mirrors
    claim_extractor.build_claim_extraction_context, which has always done this.
    """
    rows = conn.execute(
        "SELECT json_extract(attrs, '$.name') FROM nodes WHERE kind = 'Concept'"
    ).fetchall()
    names = sorted({r[0] for r in rows if r[0]})
    if not names:
        return "No known kernel concepts yet."
    return (
        "KNOWN KERNEL CONCEPTS — choose concept names from this list wherever "
        "the document is about one of them. Do NOT invent a name for this "
        "paper's own system, tool or algorithm; those are recorded elsewhere. "
        "If the document is about something genuinely absent from this list, "
        "name it as a general class rather than as a product.\n" + ", ".join(names)
    )


# --- the candidate queue (IFC-KK-CONCEPT-CANDIDATE) -------------------------


@dataclass
class Candidate:
    """A name the extractor proposed and the vocabulary did not contain."""
    normalised: str
    name: str
    sources: int
    evidence_ids: list[str]


def record_candidate(
    conn: sqlite3.Connection, name: str, evidence_id: str, proposed_at: str
) -> bool:
    """Queue an unmatched name against the Evidence that proposed it.

    One row per (name, Evidence) PAIR, which is what makes the distinct-Source
    count below possible — and that count is the same weight test
    INV-KK-CONCEPT-ADMISSION applies to an admitted Concept, asked before the
    node exists rather than after. Returns False when this pair is already
    queued, so a re-run does not inflate the evidence for a candidate.
    """
    key = normalise_concept_name(name)
    if not key or not evidence_id:
        return False
    cur = conn.execute(
        "INSERT OR IGNORE INTO concept_candidates "
        "(normalised, name, evidence_id, proposed_at) VALUES (?, ?, ?, ?)",
        (key, name.strip(), evidence_id, proposed_at))
    return cur.rowcount > 0


def candidate_ranking(conn: sqlite3.Connection, limit: int = 50) -> list[Candidate]:
    """Queued names, most independently-proposed first.

    A name two distinct Sources reached for on their own is worth a human
    minute. A name one paper invented for its own artifact is not, and sorts
    to the bottom where it can be ignored rather than deleted.
    """
    rows = conn.execute(
        "SELECT c.normalised, MIN(c.name), "
        "       COUNT(DISTINCT COALESCE(s.target_id, c.evidence_id)), "
        "       GROUP_CONCAT(DISTINCT c.evidence_id) "
        "FROM concept_candidates c "
        "LEFT JOIN edges s ON s.source_id = c.evidence_id "
        "                 AND s.kind = 'sourced-from' "
        "GROUP BY c.normalised ORDER BY 3 DESC, 1 LIMIT ?", (limit,)
    ).fetchall()
    return [Candidate(normalised=r[0], name=r[1], sources=r[2],
                      evidence_ids=(r[3] or "").split(",")) for r in rows]


__all__ = [
    "Candidate", "DEFAULT_MAX_DISTANCE", "build_vocabulary_context",
    "candidate_ranking", "fuzzy_match_concept", "levenshtein_distance",
    "normalise_concept_name", "record_candidate", "resolve_concept_names",
]
