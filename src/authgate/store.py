"""Credential, session, and remember-token storage — MOD-KK-AUTH.

Stdlib only: hashlib, hmac, secrets, sqlite3, datetime. No passlib, no
itsdangerous — server-side sessions need neither.

Enforces:
  INV-KK-AUTH-NO-PLAINTEXT-PASSWORD  passwords are stored only as pbkdf2 hashes
  INV-KK-AUTH-SESSION-TTL            expired sessions never resolve
  INV-KK-AUTH-REMEMBER-ROTATES       a consumed remember token is replaced atomically
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from authgate.schema import PBKDF2_ROUNDS, REMEMBER_TTL, SESSION_TTL


class LastAdminError(Exception):
    """Raised when deactivating a user would leave no active admin."""


@dataclass(frozen=True)
class UserRecord:
    username: str
    role: str
    active: bool
    created_at: str


# --- helpers ----------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def _parse(stamp: str) -> datetime:
    parsed = datetime.fromisoformat(stamp)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _canonical(username: str) -> str:
    """Usernames are stored and looked up lowercase-trimmed."""
    return (username or "").strip().lower()


def _row_to_user(row: sqlite3.Row) -> UserRecord:
    return UserRecord(
        username=row["username"],
        role=row["role"],
        active=bool(row["active"]),
        created_at=row["created_at"],
    )


def _token_hash(token: str) -> str:
    """Remember tokens are stored hashed so a leaked DB cannot be replayed."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# --- passwords (ALG-KK-AUTH-VERIFY-CREDENTIAL) ------------------------------


def hash_password(
    password: str, salt: str | None = None, iterations: int = PBKDF2_ROUNDS
) -> tuple[str, str, int]:
    """Return (hash_hex, salt_hex, iterations). A fresh salt unless one is given."""
    salt_hex = salt if salt is not None else secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), iterations
    )
    return digest.hex(), salt_hex, iterations


def verify_password(
    stored_hash: str, salt: str, iterations: int, candidate: str
) -> bool:
    """Constant-time comparison of a candidate password against a stored hash."""
    candidate_hash, _, _ = hash_password(candidate, salt, iterations)
    return hmac.compare_digest(stored_hash, candidate_hash)


# --- users ------------------------------------------------------------------


def create_user(
    auth_conn: sqlite3.Connection,
    username: str,
    password: str,
    role: str = "user",
) -> UserRecord:
    """Add a user. Raises ValueError on an empty name, bad role, or duplicate."""
    name = _canonical(username)
    if not name:
        raise ValueError("Username must be non-empty")
    if role not in ("admin", "user"):
        raise ValueError(f"Role must be 'admin' or 'user', got {role!r}")
    if get_user(auth_conn, name) is not None:
        raise ValueError(f"User '{name}' already exists")

    password_hash, salt, iterations = hash_password(password)
    created_at = _iso(_now())
    auth_conn.execute(
        "INSERT INTO users (username, password_hash, salt, iterations, role, "
        "active, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
        (name, password_hash, salt, iterations, role, created_at),
    )
    return UserRecord(username=name, role=role, active=True, created_at=created_at)


def get_user(auth_conn: sqlite3.Connection, username: str) -> UserRecord | None:
    row = auth_conn.execute(
        "SELECT username, role, active, created_at FROM users WHERE username = ?",
        (_canonical(username),),
    ).fetchone()
    return _row_to_user(row) if row is not None else None


def list_users(auth_conn: sqlite3.Connection) -> list[UserRecord]:
    rows = auth_conn.execute(
        "SELECT username, role, active, created_at FROM users ORDER BY username"
    ).fetchall()
    return [_row_to_user(row) for row in rows]


def set_password(auth_conn: sqlite3.Connection, username: str, password: str) -> None:
    """Replace a user's stored hash. Existing sessions are left alone."""
    name = _canonical(username)
    if get_user(auth_conn, name) is None:
        raise ValueError(f"User '{name}' does not exist")
    password_hash, salt, iterations = hash_password(password)
    auth_conn.execute(
        "UPDATE users SET password_hash = ?, salt = ?, iterations = ? "
        "WHERE username = ?",
        (password_hash, salt, iterations, name),
    )


def deactivate_user(auth_conn: sqlite3.Connection, username: str) -> None:
    """Mark a user inactive and drop their sessions and remember tokens.

    Users are deactivated, never deleted: a deleted user whose reviews still
    reference their roster entry would leave dangling attribution.
    """
    name = _canonical(username)
    user = get_user(auth_conn, name)
    if user is None:
        raise ValueError(f"User '{name}' does not exist")

    if user.role == "admin" and user.active:
        remaining = auth_conn.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1 "
            "AND username != ?",
            (name,),
        ).fetchone()[0]
        if remaining == 0:
            raise LastAdminError(
                f"Cannot deactivate '{name}': it is the last active admin"
            )

    auth_conn.execute("UPDATE users SET active = 0 WHERE username = ?", (name,))
    auth_conn.execute("DELETE FROM sessions WHERE username = ?", (name,))
    auth_conn.execute("DELETE FROM remember_tokens WHERE username = ?", (name,))


def authenticate(
    auth_conn: sqlite3.Connection, username: str, password: str
) -> UserRecord | None:
    """ALG-KK-AUTH-VERIFY-CREDENTIAL.

    Returns the user iff they exist, are active, and the password matches.
    A missing user and a wrong password are indistinguishable to the caller.
    """
    row = auth_conn.execute(
        "SELECT username, password_hash, salt, iterations, role, active, "
        "created_at FROM users WHERE username = ?",
        (_canonical(username),),
    ).fetchone()
    if row is None or not row["active"]:
        return None
    if not verify_password(
        row["password_hash"], row["salt"], row["iterations"], password
    ):
        return None
    return _row_to_user(row)


# --- sessions ---------------------------------------------------------------


def create_session(auth_conn: sqlite3.Connection, username: str) -> tuple[str, str]:
    """Mint a session. Returns (token, expires_at)."""
    name = _canonical(username)
    if get_user(auth_conn, name) is None:
        raise ValueError(f"User '{name}' does not exist")
    token = secrets.token_urlsafe(32)
    now = _now()
    expires_at = _iso(now + SESSION_TTL)
    auth_conn.execute(
        "INSERT INTO sessions (token, username, created_at, expires_at) "
        "VALUES (?, ?, ?, ?)",
        (token, name, _iso(now), expires_at),
    )
    return token, expires_at


def resolve_session(auth_conn: sqlite3.Connection, token: str) -> UserRecord | None:
    """Resolve a session token to its user, or None (INV-KK-AUTH-SESSION-TTL).

    An expired session resolves to nobody and its row is deleted on the attempt.
    """
    if not token:
        return None
    row = auth_conn.execute(
        "SELECT s.expires_at, u.username, u.role, u.active, u.created_at "
        "FROM sessions s JOIN users u ON u.username = s.username "
        "WHERE s.token = ?",
        (token,),
    ).fetchone()
    if row is None:
        return None
    if _parse(row["expires_at"]) <= _now():
        auth_conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        return None
    if not row["active"]:
        return None
    return _row_to_user(row)


def slide_session(auth_conn: sqlite3.Connection, token: str) -> None:
    """ALG-KK-AUTH-SESSION-SLIDE — push expires_at to now + SESSION_TTL."""
    auth_conn.execute(
        "UPDATE sessions SET expires_at = ? WHERE token = ?",
        (_iso(_now() + SESSION_TTL), token),
    )


def delete_session(auth_conn: sqlite3.Connection, token: str) -> None:
    auth_conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


# --- remember tokens --------------------------------------------------------


def create_remember(auth_conn: sqlite3.Connection, username: str) -> str:
    """Mint a remember-me token. Returns the RAW value; only its hash is stored."""
    name = _canonical(username)
    if get_user(auth_conn, name) is None:
        raise ValueError(f"User '{name}' does not exist")
    token = secrets.token_urlsafe(32)
    now = _now()
    auth_conn.execute(
        "INSERT INTO remember_tokens (token_hash, username, created_at, expires_at) "
        "VALUES (?, ?, ?, ?)",
        (_token_hash(token), name, _iso(now), _iso(now + REMEMBER_TTL)),
    )
    return token


def consume_remember(
    auth_conn: sqlite3.Connection, token: str
) -> tuple[UserRecord, str] | None:
    """Spend a remember-me token and issue its replacement.

    INV-KK-AUTH-REMEMBER-ROTATES: the delete and the insert happen in one
    transaction, so the old token can never be accepted twice.
    """
    if not token:
        return None
    old_hash = _token_hash(token)
    row = auth_conn.execute(
        "SELECT r.expires_at, u.username, u.role, u.active, u.created_at "
        "FROM remember_tokens r JOIN users u ON u.username = r.username "
        "WHERE r.token_hash = ?",
        (old_hash,),
    ).fetchone()
    if row is None:
        return None
    if _parse(row["expires_at"]) <= _now() or not row["active"]:
        auth_conn.execute(
            "DELETE FROM remember_tokens WHERE token_hash = ?", (old_hash,)
        )
        return None

    new_token = secrets.token_urlsafe(32)
    now = _now()
    with auth_conn:  # one transaction: rotation is atomic
        auth_conn.execute(
            "DELETE FROM remember_tokens WHERE token_hash = ?", (old_hash,)
        )
        auth_conn.execute(
            "INSERT INTO remember_tokens (token_hash, username, created_at, "
            "expires_at) VALUES (?, ?, ?, ?)",
            (
                _token_hash(new_token),
                row["username"],
                _iso(now),
                _iso(now + REMEMBER_TTL),
            ),
        )
    return _row_to_user(row), new_token


def delete_remember(auth_conn: sqlite3.Connection, token: str) -> None:
    auth_conn.execute(
        "DELETE FROM remember_tokens WHERE token_hash = ?", (_token_hash(token),)
    )


# --- maintenance ------------------------------------------------------------


def purge_expired(auth_conn: sqlite3.Connection) -> int:
    """Delete every expired session and remember token. Returns the row count."""
    now = _iso(_now())
    sessions = auth_conn.execute(
        "DELETE FROM sessions WHERE expires_at <= ?", (now,)
    ).rowcount
    remembers = auth_conn.execute(
        "DELETE FROM remember_tokens WHERE expires_at <= ?", (now,)
    ).rowcount
    return sessions + remembers
