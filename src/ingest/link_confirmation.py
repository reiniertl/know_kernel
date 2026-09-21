"""Human confirmation of a paper link (INV-KK-LINK-CONFIRMATION-STATE).

INV-KK-EXTRACT-EVIDENCE-RECORDED made a link CHECKABLE — the grounding verdict
and a fingerprint of the document sit on the edge, so anyone can be shown what
the claim rests on. It did not make the link CHECKED. A model can produce prose
whose bigrams all appear in the paper and still describe something the paper
does not support, and no computation closes that gap.

ABSENCE IS THE THIRD STATE. The stored vocabulary is exactly 'confirmed' or
'rejected'; an edge with no confirmation key has not been looked at. Writing
'unreviewed' onto all 3,169 existing edges would have been a migration whose
only effect is to assert ignorance, and it would mean a new edge is unreviewed
only if somebody remembers to say so. This way it is unreviewed by construction.

NOTHING HERE GATES. Per INV-KK-COMPLETENESS-ADVISORY an unconfirmed link is
still returned by every query, rendered on every page and counted in
links_concept. The specific risk this module invites is hiding unconfirmed
links, which would make the corpus look verified rather than make it verified.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date

#: The only two values that are ever stored. Absence means unreviewed.
CONFIRMATION_STATES = ("confirmed", "rejected")

#: The keys this module owns. INV-KK-EXTRACT-EVIDENCE-RECORDED permits exactly
#: these four as additions to its required set, and no others.
CONFIRMATION_KEYS = (
    "confirmation", "confirmed_by", "confirmed_at", "confirmation_note",
)


@dataclass(frozen=True)
class ConfirmationResult:
    concept_id: str
    evidence_id: str
    confirmation: str
    confirmed_by: str
    confirmed_at: str
    note: str = ""


def _edge_row(conn: sqlite3.Connection, concept_id: str, evidence_id: str):
    return conn.execute(
        "SELECT id, attrs FROM edges WHERE kind = 'extracted-from' "
        "AND source_id = ? AND target_id = ?",
        (concept_id, evidence_id),
    ).fetchone()


def get_confirmation(
    conn: sqlite3.Connection, concept_id: str, evidence_id: str
) -> str | None:
    """The stored state, or None for a link nobody has looked at."""
    row = _edge_row(conn, concept_id, evidence_id)
    if row is None:
        return None
    return (json.loads(row[1]) if isinstance(row[1], str) else (row[1] or {})).get(
        "confirmation")


def set_confirmation(
    conn: sqlite3.Connection,
    concept_id: str,
    evidence_id: str,
    confirmation: str,
    reviewer_id: str,
    note: str = "",
    confirmed_at: str | None = None,
) -> ConfirmationResult:
    """Record that a named person confirmed or rejected this link.

    A confirmation with no reviewer is an anonymous assertion and is refused —
    the whole value of the state is that somebody put their name to it.
    """
    if confirmation not in CONFIRMATION_STATES:
        raise ValueError(
            f"Invalid confirmation '{confirmation}'; "
            f"expected one of {CONFIRMATION_STATES} "
            f"(INV-KK-LINK-CONFIRMATION-STATE)")

    reviewer_id = (reviewer_id or "").strip()
    if not reviewer_id:
        raise ValueError("confirmation requires a reviewer "
                         "(INV-KK-LINK-CONFIRMATION-STATE)")
    reviewer = conn.execute(
        "SELECT 1 FROM nodes WHERE id = ? AND kind = 'Reviewer'", (reviewer_id,)
    ).fetchone()
    if reviewer is None:
        raise ValueError(f"Reviewer '{reviewer_id}' does not exist")

    row = _edge_row(conn, concept_id, evidence_id)
    if row is None:
        raise ValueError(
            f"No extracted-from edge from '{concept_id}' to '{evidence_id}'")

    edge_id, raw = row
    attrs = json.loads(raw) if isinstance(raw, str) else (raw or {})
    stamp = confirmed_at or date.today().isoformat()
    attrs.update({
        "confirmation": confirmation,
        "confirmed_by": reviewer_id,
        "confirmed_at": stamp,
    })
    # An empty note is stored as no note rather than as an empty string, so the
    # permitted-key set stays as small as the record actually needs.
    if note.strip():
        attrs["confirmation_note"] = note.strip()
    else:
        attrs.pop("confirmation_note", None)

    conn.execute("UPDATE edges SET attrs = ? WHERE id = ?",
                 (json.dumps(attrs, sort_keys=True), edge_id))
    return ConfirmationResult(concept_id, evidence_id, confirmation,
                              reviewer_id, stamp, note.strip())


def clear_confirmation(
    conn: sqlite3.Connection, concept_id: str, evidence_id: str
) -> bool:
    """Return the link to unreviewed. A reviewer must be able to undo a mistake
    without the only remedy being to assert the opposite."""
    row = _edge_row(conn, concept_id, evidence_id)
    if row is None:
        return False
    edge_id, raw = row
    attrs = json.loads(raw) if isinstance(raw, str) else (raw or {})
    if not any(k in attrs for k in CONFIRMATION_KEYS):
        return False
    for k in CONFIRMATION_KEYS:
        attrs.pop(k, None)
    conn.execute("UPDATE edges SET attrs = ? WHERE id = ?",
                 (json.dumps(attrs, sort_keys=True), edge_id))
    return True


def count_confirmations(conn: sqlite3.Connection) -> dict[str, int]:
    """Totals over every extracted-from edge. Counts of review ACTIVITY, never
    of correctness: a confirmed link is one a person said they believed."""
    total = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind = 'extracted-from'").fetchone()[0]
    by_state = dict(conn.execute(
        "SELECT json_extract(attrs, '$.confirmation'), COUNT(*) FROM edges "
        "WHERE kind = 'extracted-from' "
        "AND json_extract(attrs, '$.confirmation') IS NOT NULL GROUP BY 1"
    ).fetchall())
    return {
        "total": total,
        "confirmed": by_state.get("confirmed", 0),
        "rejected": by_state.get("rejected", 0),
        "unreviewed": total - sum(by_state.values()),
    }
