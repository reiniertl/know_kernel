"""Tests for the authentication store — MOD-KK-AUTH.

INV-KK-AUTH-NO-PLAINTEXT-PASSWORD: only pbkdf2 hashes are persisted.
INV-KK-AUTH-STORE-SEPARATE: auth.db and master.db share no tables.
INV-KK-AUTH-SESSION-TTL: an expired session never resolves.
INV-KK-AUTH-REMEMBER-ROTATES: a consumed remember token cannot be replayed.

Expiry is simulated by writing expires_at directly to a past timestamp —
never by sleeping.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from authgate.schema import AUTH_SCHEMA_SQL, init_auth_db
from authgate.store import (
    LastAdminError,
    authenticate,
    consume_remember,
    create_remember,
    create_session,
    create_user,
    deactivate_user,
    delete_remember,
    delete_session,
    get_user,
    hash_password,
    list_users,
    purge_expired,
    resolve_session,
    set_password,
    slide_session,
    verify_password,
)


PAST = "2000-01-01T00:00:00+00:00"


@pytest.fixture
def auth(tmp_path) -> sqlite3.Connection:
    conn = init_auth_db(tmp_path / "auth.db")
    yield conn
    conn.close()


def _expire_session(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("UPDATE sessions SET expires_at = ? WHERE token = ?", (PAST, token))


def _expire_all_remembers(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE remember_tokens SET expires_at = ?", (PAST,))


# --- users ------------------------------------------------------------------


def test_create_user_writes_and_get_user_reads_back(auth):
    created = create_user(auth, "reinier", "pw")
    fetched = get_user(auth, "reinier")
    assert fetched is not None
    assert fetched.username == "reinier"
    assert fetched.role == "user"
    assert fetched.active is True
    assert created.created_at == fetched.created_at


def test_duplicate_username_raises(auth):
    create_user(auth, "reinier", "pw")
    with pytest.raises(ValueError, match="already exists"):
        create_user(auth, "reinier", "other-pw")


def test_duplicate_username_is_case_insensitive(auth):
    create_user(auth, "reinier", "pw")
    with pytest.raises(ValueError, match="already exists"):
        create_user(auth, "REINIER", "other-pw")


def test_empty_username_raises(auth):
    with pytest.raises(ValueError, match="non-empty"):
        create_user(auth, "   ", "pw")


def test_authenticate_succeeds_with_the_right_password(auth):
    create_user(auth, "reinier", "correct-horse")
    user = authenticate(auth, "reinier", "correct-horse")
    assert user is not None
    assert user.username == "reinier"


def test_authenticate_fails_with_the_wrong_password(auth):
    create_user(auth, "reinier", "correct-horse")
    assert authenticate(auth, "reinier", "wrong-horse") is None


def test_authenticate_on_a_missing_user_is_indistinguishable(auth):
    """A missing user and a wrong password both return None."""
    create_user(auth, "reinier", "pw")
    assert authenticate(auth, "nobody", "pw") is None
    assert authenticate(auth, "reinier", "nope") is None


def test_stored_hash_is_not_the_password(auth):
    create_user(auth, "reinier", "s3cret")
    row = auth.execute(
        "SELECT password_hash, salt FROM users WHERE username = 'reinier'"
    ).fetchone()
    assert row["password_hash"] != "s3cret"
    assert "s3cret" not in row["password_hash"]
    assert "s3cret" not in row["salt"]


def test_same_password_yields_different_hashes(auth):
    create_user(auth, "alice", "same-pw")
    create_user(auth, "bob", "same-pw")
    rows = auth.execute(
        "SELECT username, password_hash, salt FROM users ORDER BY username"
    ).fetchall()
    assert rows[0]["salt"] != rows[1]["salt"]
    assert rows[0]["password_hash"] != rows[1]["password_hash"]


def test_verify_password_round_trips(auth):
    digest, salt, iterations = hash_password("hunter2")
    assert verify_password(digest, salt, iterations, "hunter2") is True
    assert verify_password(digest, salt, iterations, "hunter3") is False


def test_deactivated_user_cannot_authenticate(auth):
    create_user(auth, "boss", "pw", role="admin")
    create_user(auth, "reinier", "pw")
    deactivate_user(auth, "reinier")
    assert authenticate(auth, "reinier", "pw") is None


def test_lookup_is_case_insensitive_and_trimmed(auth):
    create_user(auth, "  Reinier  ", "pw")
    assert get_user(auth, "reinier") is not None
    assert get_user(auth, "REINIER") is not None
    assert authenticate(auth, " ReInIeR ", "pw") is not None


def test_set_password_invalidates_the_old_one(auth):
    create_user(auth, "reinier", "old-pw")
    set_password(auth, "reinier", "new-pw")
    assert authenticate(auth, "reinier", "old-pw") is None
    assert authenticate(auth, "reinier", "new-pw") is not None


def test_deactivate_refuses_on_the_last_active_admin(auth):
    create_user(auth, "boss", "pw", role="admin")
    with pytest.raises(LastAdminError):
        deactivate_user(auth, "boss")
    assert get_user(auth, "boss").active is True


def test_deactivate_allows_an_admin_when_another_remains(auth):
    create_user(auth, "boss", "pw", role="admin")
    create_user(auth, "second", "pw", role="admin")
    deactivate_user(auth, "boss")
    assert get_user(auth, "boss").active is False


def test_list_users_returns_all_sorted(auth):
    create_user(auth, "zed", "pw")
    create_user(auth, "alice", "pw", role="admin")
    assert [u.username for u in list_users(auth)] == ["alice", "zed"]


# --- sessions ---------------------------------------------------------------


def test_fresh_session_resolves(auth):
    create_user(auth, "reinier", "pw")
    token, _ = create_session(auth, "reinier")
    user = resolve_session(auth, token)
    assert user is not None
    assert user.username == "reinier"


def test_expired_session_does_not_resolve_and_its_row_is_gone(auth):
    create_user(auth, "reinier", "pw")
    token, _ = create_session(auth, "reinier")
    _expire_session(auth, token)

    assert resolve_session(auth, token) is None
    remaining = auth.execute(
        "SELECT COUNT(*) FROM sessions WHERE token = ?", (token,)
    ).fetchone()[0]
    assert remaining == 0


def test_slide_session_pushes_expiry_forward(auth):
    create_user(auth, "reinier", "pw")
    token, original = create_session(auth, "reinier")
    auth.execute(
        "UPDATE sessions SET expires_at = ? WHERE token = ?",
        ((datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(), token),
    )

    slide_session(auth, token)

    slid = auth.execute(
        "SELECT expires_at FROM sessions WHERE token = ?", (token,)
    ).fetchone()["expires_at"]
    assert datetime.fromisoformat(slid) > datetime.now(timezone.utc) + timedelta(
        hours=23
    )
    assert datetime.fromisoformat(slid) <= datetime.fromisoformat(original) + timedelta(
        minutes=5
    )


def test_delete_session_revokes_immediately(auth):
    create_user(auth, "reinier", "pw")
    token, _ = create_session(auth, "reinier")
    delete_session(auth, token)
    assert resolve_session(auth, token) is None


def test_session_of_a_deactivated_user_does_not_resolve(auth):
    create_user(auth, "boss", "pw", role="admin")
    create_user(auth, "reinier", "pw")
    token, _ = create_session(auth, "reinier")
    deactivate_user(auth, "reinier")
    assert resolve_session(auth, token) is None


def test_unknown_token_resolves_to_none(auth):
    assert resolve_session(auth, "not-a-token") is None
    assert resolve_session(auth, "") is None


# --- remember tokens --------------------------------------------------------


def test_consume_remember_returns_the_user_and_a_new_token(auth):
    create_user(auth, "reinier", "pw")
    token = create_remember(auth, "reinier")

    result = consume_remember(auth, token)

    assert result is not None
    user, new_token = result
    assert user.username == "reinier"
    assert new_token != token


def test_consumed_token_cannot_be_replayed(auth):
    create_user(auth, "reinier", "pw")
    token = create_remember(auth, "reinier")
    consume_remember(auth, token)

    assert consume_remember(auth, token) is None


def test_rotated_token_still_works_once(auth):
    create_user(auth, "reinier", "pw")
    token = create_remember(auth, "reinier")
    _, new_token = consume_remember(auth, token)

    result = consume_remember(auth, new_token)

    assert result is not None
    assert result[0].username == "reinier"


def test_raw_remember_token_is_never_stored(auth):
    create_user(auth, "reinier", "pw")
    token = create_remember(auth, "reinier")
    stored = auth.execute("SELECT token_hash FROM remember_tokens").fetchone()[0]
    assert stored != token


def test_expired_remember_token_does_not_resolve(auth):
    create_user(auth, "reinier", "pw")
    token = create_remember(auth, "reinier")
    _expire_all_remembers(auth)

    assert consume_remember(auth, token) is None


def test_remember_token_of_a_deactivated_user_does_not_resolve(auth):
    create_user(auth, "boss", "pw", role="admin")
    create_user(auth, "reinier", "pw")
    token = create_remember(auth, "reinier")
    deactivate_user(auth, "reinier")

    assert consume_remember(auth, token) is None


def test_delete_remember_revokes(auth):
    create_user(auth, "reinier", "pw")
    token = create_remember(auth, "reinier")
    delete_remember(auth, token)
    assert consume_remember(auth, token) is None


# --- maintenance ------------------------------------------------------------


def test_purge_expired_removes_only_expired_rows(auth):
    create_user(auth, "reinier", "pw")
    stale_token, _ = create_session(auth, "reinier")
    fresh_token, _ = create_session(auth, "reinier")
    _expire_session(auth, stale_token)
    create_remember(auth, "reinier")

    removed = purge_expired(auth)

    assert removed == 1
    assert resolve_session(auth, fresh_token) is not None
    assert auth.execute("SELECT COUNT(*) FROM remember_tokens").fetchone()[0] == 1


# --- INV-KK-AUTH-STORE-SEPARATE ---------------------------------------------


def test_auth_schema_declares_no_graph_table():
    assert "nodes" not in AUTH_SCHEMA_SQL.replace("idx_sessions_username", "")
    assert "CREATE TABLE IF NOT EXISTS edges" not in AUTH_SCHEMA_SQL


def test_auth_db_and_master_db_share_no_tables(tmp_path):
    """The two stores are disjoint by construction (INV-KK-AUTH-STORE-SEPARATE)."""
    from graph.schema import init_db

    auth_conn = init_auth_db(tmp_path / "auth.db")
    master_conn = init_db(tmp_path / "master.db")
    try:
        auth_tables = {
            r[0]
            for r in auth_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        }
        master_tables = {
            r[0]
            for r in master_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        }
    finally:
        auth_conn.close()
        master_conn.close()

    assert auth_tables == {"users", "sessions", "remember_tokens"}
    assert master_tables == {"nodes", "edges"}
    assert auth_tables & master_tables == set()
