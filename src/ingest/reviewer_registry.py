"""Reviewer roster — creates Reviewer nodes (ALG-KK-REVIEWER-REGISTER).

Distinct from `ingest.reviewer`, which reviews Sources for contamination and
produces Advisory nodes. This module owns the roster of people who may submit
human reviews.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass

from graph.engine import add_node
from graph.rules import validate_node


@dataclass
class ReviewerResult:
    reviewer_id: str
    name: str


def find_reviewer(conn: sqlite3.Connection, name: str) -> str | None:
    """Return the id of the roster entry matching `name`, or None.

    Matching ignores case and surrounding whitespace
    (INV-KK-REVIEWER-NAME-UNIQUE).
    """
    row = conn.execute(
        "SELECT id FROM nodes WHERE kind = 'Reviewer' "
        "AND lower(trim(json_extract(attrs, '$.name'))) = ? "
        "LIMIT 1",
        (name.strip().lower(),),
    ).fetchone()
    return row[0] if row else None


def register_reviewer(conn: sqlite3.Connection, name: str) -> ReviewerResult:
    """Add a name to the reviewer roster (ALG-KK-REVIEWER-REGISTER).

    Raises ValueError if the name is empty after stripping or already on the
    roster under any capitalisation (INV-KK-REVIEWER-NAME-UNIQUE).
    """
    cleaned = name.strip() if name else ""
    if not cleaned:
        raise ValueError(
            "Reviewer name must be non-empty (INV-KK-REVIEWER-NAME-UNIQUE)"
        )

    if find_reviewer(conn, cleaned) is not None:
        raise ValueError(
            f"Reviewer '{cleaned}' is already registered "
            "(INV-KK-REVIEWER-NAME-UNIQUE)"
        )

    reviewer_id = f"rvr-{uuid.uuid4().hex[:12]}"

    add_node(conn, reviewer_id, "Reviewer", {"name": cleaned})

    violations = validate_node(conn, reviewer_id, "Reviewer")
    if violations:
        raise RuntimeError(
            f"Reviewer node {reviewer_id} failed validation: "
            + "; ".join(v.message for v in violations)
        )

    return ReviewerResult(reviewer_id=reviewer_id, name=cleaned)


def list_reviewers(conn: sqlite3.Connection) -> list[ReviewerResult]:
    """Return the roster in stable name order (ALG-KK-REVIEWER-LIST)."""
    rows = conn.execute(
        "SELECT id, json_extract(attrs, '$.name') FROM nodes "
        "WHERE kind = 'Reviewer' "
        "ORDER BY lower(json_extract(attrs, '$.name')), id"
    ).fetchall()
    return [ReviewerResult(reviewer_id=r[0], name=r[1] or "") for r in rows]
