"""Paper impact scoring workflow — creates HumanReview nodes (ALG-KK-REVIEW-PAPER)."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date

from graph.engine import add_node, add_edge
from graph.rules import validate_node
from ingest.reviewer_registry import find_reviewer


VALID_VERDICTS = {"accept", "reject"}
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

    if find_reviewer(conn, reviewer) is None:
        raise ValueError(
            f"Reviewer '{reviewer}' is not registered "
            "(INV-KK-REVIEW-REVIEWER-REGISTERED)"
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


def edit_review(
    conn: sqlite3.Connection,
    review_id: str,
    score: int,
    verdict: str,
    rationale: str,
) -> PaperReviewResult:
    """Edit an existing HumanReview node (ALG-KK-REVIEW-EDIT).

    Reviewer is immutable (INV-KK-REVIEW-EDIT-IMMUTABLE-REVIEWER).
    """
    from graph.engine import get_node, update_node_attrs

    node = get_node(conn, review_id)
    if node is None or node["kind"] != "HumanReview":
        raise ValueError(
            f"HumanReview node '{review_id}' does not exist"
        )

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

    # The reviewer is immutable (INV-KK-REVIEW-EDIT-IMMUTABLE-REVIEWER), so the
    # roster is checked against the name already on the node.
    existing_reviewer = node["attrs"].get("reviewer", "")
    if find_reviewer(conn, existing_reviewer) is None:
        raise ValueError(
            f"Reviewer '{existing_reviewer}' is not registered "
            "(INV-KK-REVIEW-REVIEWER-REGISTERED)"
        )

    update_node_attrs(conn, review_id, {
        "score": score,
        "verdict": verdict,
        "rationale": rationale.strip(),
        "review_date": date.today().isoformat(),
    })

    violations = validate_node(conn, review_id, "HumanReview")
    if violations:
        raise RuntimeError(
            f"HumanReview node {review_id} failed validation: "
            + "; ".join(v.message for v in violations)
        )

    source_row = conn.execute(
        "SELECT e.source_id FROM edges e "
        "WHERE e.kind = 'reviewed-by' AND e.target_id = ?",
        (review_id,),
    ).fetchone()
    source_id = source_row[0] if source_row else ""

    return PaperReviewResult(
        review_id=review_id,
        source_id=source_id,
        reviewer=node["attrs"].get("reviewer", ""),
        score=score,
        verdict=verdict,
        rationale=rationale.strip(),
    )


@dataclass
class ReviewDeleteResult:
    review_id: str
    source_id: str


def delete_review(conn: sqlite3.Connection, review_id: str) -> ReviewDeleteResult:
    """Remove a HumanReview and its reviewed-by edge (ALG-KK-REVIEW-DELETE).

    Deliberately scoped rather than delegating to graph.engine.delete_node.
    delete_node revalidates the source node of every incoming edge, so removing
    a review revalidates the reviewing Source against its must-have-an-Advisory
    rule and rolls back on the great majority of real Sources. Nothing in
    RULES_BY_KIND depends on a HumanReview existing, and reviewed-by is the only
    edge that reaches one, so dropping the node together with that edge is
    complete and leaves no orphans.

    Raises ValueError if review_id names no node or names one of another kind.
    """
    from graph.engine import get_node

    node = get_node(conn, review_id)
    if node is None or node["kind"] != "HumanReview":
        raise ValueError(
            f"HumanReview node '{review_id}' does not exist"
        )

    source_row = conn.execute(
        "SELECT source_id FROM edges "
        "WHERE kind = 'reviewed-by' AND target_id = ?",
        (review_id,),
    ).fetchone()
    source_id = source_row[0] if source_row else ""

    conn.execute("SAVEPOINT delete_review")
    try:
        conn.execute(
            "DELETE FROM edges WHERE kind = 'reviewed-by' AND target_id = ?",
            (review_id,),
        )
        conn.execute("DELETE FROM nodes WHERE id = ?", (review_id,))
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT delete_review")
        conn.execute("RELEASE SAVEPOINT delete_review")
        raise
    conn.execute("RELEASE SAVEPOINT delete_review")

    return ReviewDeleteResult(review_id=review_id, source_id=source_id)
