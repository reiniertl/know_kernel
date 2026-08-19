"""Auth database schema and tuning constants — MOD-KK-AUTH.

auth.db is a SEPARATE SQLite file from the knowledge graph's master.db
(INV-KK-AUTH-STORE-SEPARATE). Nothing here names a graph table, and
graph.schema.SCHEMA_SQL names nothing here.

Sessions are server-side: the cookie carries an opaque token and the row
holds the expiry, so logout genuinely revokes and no signing secret exists.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import timedelta
from pathlib import Path

# --- tuning constants (single definition site) ------------------------------

SESSION_TTL = timedelta(hours=24)
REMEMBER_TTL = timedelta(days=30)
PBKDF2_ROUNDS = 240_000

SESSION_COOKIE = "kk_session"
REMEMBER_COOKIE = "kk_remember"

# --- schema -----------------------------------------------------------------

AUTH_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS users (
    username      TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    salt          TEXT NOT NULL,
    iterations    INTEGER NOT NULL DEFAULT 240000,
    role          TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin','user')),
    active        INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    username   TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS remember_tokens (
    token_hash TEXT PRIMARY KEY,
    username   TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_username ON sessions(username);
CREATE INDEX IF NOT EXISTS idx_remember_username ON remember_tokens(username);
"""


def init_auth_db(
    path: Path | str, check_same_thread: bool = True
) -> sqlite3.Connection:
    """Open (or create) auth.db and apply the schema.

    Mirrors graph.schema.init_db: WAL, foreign keys on, idempotent
    CREATE TABLE IF NOT EXISTS so an existing file migrates on open.

    The server passes check_same_thread=False because FastAPI runs sync
    handlers on a threadpool; the CLIs keep the safer default.
    """
    conn = sqlite3.connect(str(path), check_same_thread=check_same_thread)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(AUTH_SCHEMA_SQL)
    return conn


def auth_db_path() -> str:
    """Path to auth.db — KNOW_KERNEL_AUTH_DB, else data/auth.db."""
    env = os.environ.get("KNOW_KERNEL_AUTH_DB")
    if env:
        return env
    return str(Path(__file__).resolve().parents[2] / "data" / "auth.db")
