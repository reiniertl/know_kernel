"""Paper impact scoring workflow — creates HumanReview nodes (ALG-KK-REVIEW-PAPER)."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date

from graph.engine import add_node, add_edge
from graph.rules import validate_node


VALID_VERDICTS = {"accept", "reject", "skip"}
VALID_SCORES = {1, 2, 3, 4, 5}


@dataclass
class PaperReviewResult:
    review_id: str
    source_id: str
    reviewer: str
    score: int
    verdict: str
    rationale: str


def review_paper(
    conn: sqlite3.Connection,
    source_id: str,
    reviewer: str,
    score: int,
    verdict: str,
    rationale: str,
) -> PaperReviewResult:
    """Review a Source node: create HumanReview + reviewed-by edge.

    Raises ValueError if score is not 1-5, verdict is not in the allowed set,
    rationale is empty, source_id does not exist, or a review by the same
    reviewer already exists (INV-KK-REVIEW-SINGLE-PER-REVIEWER).
    """
    if score not in VALID_SCORES:
        raise ValueError(
            f"Score must be 1-5, got {score} (INV-KK-REVIEW-SCORE-RANGE)"
        )

    if verdict not in VALID_VERDICTS:
        raise ValueError(
            f"Invalid verdict '{verdict}'. "
            f"Must be one of: {', '.join(sorted(VALID_VERDICTS))} "
            "(INV-KK-REVIEW-VERDICT-ENUM)"
        )

    if not rationale or not rationale.strip():
        raise ValueError(
            "Rationale must be non-empty (INV-KK-REVIEW-RATIONALE-REQUIRED)"
        )

    source = conn.execute(
        "SELECT id, kind FROM nodes WHERE id = ? AND kind = 'Source'",
        (source_id,),
    ).fetchone()
    if source is None:
        raise ValueError(
            f"Source node '{source_id}' does not exist "
            "(INV-KK-REVIEW-SOURCE-EXISTS)"
        )

    existing = conn.execute(
        "SELECT 1 FROM edges e "
        "JOIN nodes n ON e.target_id = n.id "
        "WHERE e.kind = 'reviewed-by' "
        "AND e.source_id = ? "
        "AND n.kind = 'HumanReview' "
        "AND json_extract(n.attrs, '$.reviewer') = ? "
        "LIMIT 1",
        (source_id, reviewer),
    ).fetchone()
    if existing is not None:
        raise ValueError(
            f"Source '{source_id}' already reviewed by '{reviewer}' "
            "(INV-KK-REVIEW-SINGLE-PER-REVIEWER)"
        )

    review_id = f"hrev-{uuid.uuid4().hex[:12]}"

    add_node(conn, review_id, "HumanReview", {
        "reviewer": reviewer,
        "score": score,
        "verdict": verdict,
        "rationale": rationale.strip(),
        "review_date": date.today().isoformat(),
        "artifact_class": "human-review",
    })
    add_edge(conn, "reviewed-by", source_id, review_id)

    violations = validate_node(conn, review_id, "HumanReview")
    if violations:
        raise RuntimeError(
            f"HumanReview node {review_id} failed validation: "
            + "; ".join(v.message for v in violations)
        )

    return PaperReviewResult(
        review_id=review_id,
        source_id=source_id,
        reviewer=reviewer,
        score=score,
        verdict=verdict,
        rationale=rationale.strip(),
    )
