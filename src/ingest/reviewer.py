"""Source review workflow â€” creates Advisory nodes (ALG-KK-REVIEW-SOURCE)."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass

from graph.engine import add_edge, add_node
from graph.rules import validate_node
from ingest.scanner import ContaminationLevel


VALID_LEVELS = {level.value for level in ContaminationLevel}


@dataclass
class ReviewResult:
    advisory_id: str
    source_id: str
    assessment_text: str
    contamination_confirmed: str


def review_source(
    conn: sqlite3.Connection,
    source_id: str,
    assessment_text: str,
    confirmed_level: str,
) -> ReviewResult:
    """Review a Source node: create Advisory + assessed-by edge.

    Raises ValueError if source_id does not exist, if assessment_text is empty,
    if confirmed_level is not a valid ContaminationLevel, or if an assessed-by
    edge already exists (INV-KK-ADVISORY-SINGLE-PER-SOURCE).
    """
    if not assessment_text or not assessment_text.strip():
        raise ValueError("Assessment text must be non-empty (INV-KK-ADVISORY-REQUIRES-ASSESSMENT)")

    if confirmed_level not in VALID_LEVELS:
        raise ValueError(
            f"Invalid contamination level '{confirmed_level}'. "
            f"Must be one of: {', '.join(sorted(VALID_LEVELS))}"
        )

    source = conn.execute(
        "SELECT id, kind FROM nodes WHERE id = ? AND kind = 'Source'",
        (source_id,),
    ).fetchone()
    if source is None:
        raise ValueError(f"Source node '{source_id}' does not exist")

    existing = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'assessed-by' AND source_id = ? LIMIT 1",
        (source_id,),
    ).fetchone()
    if existing is not None:
        raise ValueError(
            f"Source '{source_id}' already has an assessed-by edge "
            "(INV-KK-ADVISORY-SINGLE-PER-SOURCE)"
        )

    advisory_id = f"adv-{uuid.uuid4().hex[:12]}"

    add_node(conn, advisory_id, "Advisory", {
        "assessment": assessment_text.strip(),
    })
    add_edge(conn, "assessed-by", source_id, advisory_id)

    violations = validate_node(conn, advisory_id, "Advisory")
    if violations:
        raise RuntimeError(
            f"Advisory node {advisory_id} failed validation: "
            + "; ".join(v.message for v in violations)
        )

    return ReviewResult(
        advisory_id=advisory_id,
        source_id=source_id,
        assessment_text=assessment_text.strip(),
        contamination_confirmed=confirmed_level,
    )
