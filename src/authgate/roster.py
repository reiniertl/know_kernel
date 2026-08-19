"""Reviewer-roster mirroring — the gate's only touchpoint on master.db.

INV-KK-AUTH-ROSTER-MIRRORS-USERS: every active user has a Reviewer node named
by their username, so a logged-in person is always a valid review author and
INV-KK-REVIEW-REVIEWER-REGISTERED keeps holding without a manual roster step.

No other module under authgate/ may import from graph or ingest
(INV-KK-AUTH-STORE-SEPARATE keeps the two stores apart; this file is the one
deliberate, one-way exception and it writes only the roster entry).
"""

from __future__ import annotations

import sqlite3

from ingest.reviewer_registry import find_reviewer, register_reviewer


def ensure_roster_entry(master_conn: sqlite3.Connection, username: str) -> str:
    """Return the Reviewer node id for *username*, creating it if absent.

    Idempotent: an existing roster entry is reused, so re-running user creation
    never produces a duplicate. Matching is delegated to find_reviewer, which
    ignores case and surrounding whitespace (INV-KK-REVIEWER-NAME-UNIQUE).

    Does NOT commit — the caller owns the two-store commit ordering.
    """
    name = (username or "").strip()
    if not name:
        raise ValueError("Username must be non-empty to mirror onto the roster")

    existing = find_reviewer(master_conn, name)
    if existing is not None:
        return existing

    return register_reviewer(master_conn, name).reviewer_id
