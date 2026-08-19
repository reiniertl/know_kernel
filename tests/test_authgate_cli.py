"""Tests for user-creation CLIs and roster mirroring — MOD-KK-AUTH.

INV-KK-AUTH-ROSTER-MIRRORS-USERS: creating a user creates its Reviewer node.
INV-KK-AUTH-NO-PLAINTEXT-PASSWORD: the password never reaches argv or output.
ALG-KK-AUTH-USER-CREATE: the two-store write is both-or-neither.
"""

from __future__ import annotations

import sqlite3

import pytest

from authgate.cli import create_user_with_roster, passwd, useradd, userlist
from authgate.roster import ensure_roster_entry
from authgate.schema import init_auth_db
from authgate.store import authenticate, get_user
from graph.schema import init_db
from ingest.reviewer_registry import list_reviewers, register_reviewer


@pytest.fixture
def stores(tmp_path):
    """A fresh auth.db and master.db pair, plus their paths."""
    auth_path = tmp_path / "auth.db"
    master_path = tmp_path / "master.db"
    auth_conn = init_auth_db(auth_path)
    master_conn = init_db(master_path)
    master_conn.commit()
    yield {
        "auth": auth_conn,
        "master": master_conn,
        "auth_path": str(auth_path),
        "master_path": str(master_path),
    }
    auth_conn.close()
    master_conn.close()


def _feed_password(monkeypatch, *values: str) -> None:
    """Answer successive getpass prompts with *values*."""
    answers = list(values)
    monkeypatch.setattr(
        "authgate.cli.getpass.getpass", lambda *a, **k: answers.pop(0)
    )


# --- roster mirroring -------------------------------------------------------


def test_ensure_roster_entry_creates_the_reviewer_node(stores):
    reviewer_id = ensure_roster_entry(stores["master"], "reinier")

    assert reviewer_id.startswith("rvr-")
    assert [r.name for r in list_reviewers(stores["master"])] == ["reinier"]


def test_ensure_roster_entry_is_idempotent(stores):
    first = ensure_roster_entry(stores["master"], "reinier")
    second = ensure_roster_entry(stores["master"], "reinier")

    assert first == second
    assert len(list_reviewers(stores["master"])) == 1


def test_ensure_roster_entry_reuses_a_pre_existing_entry(stores):
    existing = register_reviewer(stores["master"], "reinier")

    assert ensure_roster_entry(stores["master"], "reinier") == existing.reviewer_id
    assert len(list_reviewers(stores["master"])) == 1


def test_ensure_roster_entry_rejects_an_empty_name(stores):
    with pytest.raises(ValueError, match="non-empty"):
        ensure_roster_entry(stores["master"], "   ")


# --- ALG-KK-AUTH-USER-CREATE ------------------------------------------------


def test_create_user_with_roster_writes_both_stores(stores):
    create_user_with_roster(stores["auth"], stores["master"], "reinier", "pw")

    assert get_user(stores["auth"], "reinier") is not None
    assert [r.name for r in list_reviewers(stores["master"])] == ["reinier"]


def test_create_user_with_roster_rolls_back_when_the_roster_write_fails(
    stores, monkeypatch
):
    """Fail-loud: a roster failure must leave no user row behind."""
    monkeypatch.setattr(
        "authgate.cli.ensure_roster_entry",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("roster exploded")),
    )

    with pytest.raises(RuntimeError, match="roster exploded"):
        create_user_with_roster(stores["auth"], stores["master"], "reinier", "pw")

    assert get_user(stores["auth"], "reinier") is None
    assert list_reviewers(stores["master"]) == []


def test_duplicate_user_leaves_a_single_roster_entry(stores):
    create_user_with_roster(stores["auth"], stores["master"], "reinier", "pw")

    with pytest.raises(ValueError, match="already exists"):
        create_user_with_roster(stores["auth"], stores["master"], "reinier", "other")

    assert len(list_reviewers(stores["master"])) == 1


# --- kk-useradd -------------------------------------------------------------


def test_useradd_creates_user_and_roster_entry(stores, monkeypatch, capsys):
    _feed_password(monkeypatch, "pw", "pw")

    code = useradd(
        [
            "reinier",
            "--db",
            stores["master_path"],
            "--auth-db",
            stores["auth_path"],
        ]
    )

    assert code == 0
    auth_conn = init_auth_db(stores["auth_path"])
    master_conn = sqlite3.connect(stores["master_path"])
    try:
        assert authenticate(auth_conn, "reinier", "pw") is not None
        assert [r.name for r in list_reviewers(master_conn)] == ["reinier"]
    finally:
        auth_conn.close()
        master_conn.close()


def test_useradd_admin_flag_sets_the_admin_role(stores, monkeypatch):
    _feed_password(monkeypatch, "pw", "pw")

    useradd(
        ["boss", "--admin", "--db", stores["master_path"], "--auth-db", stores["auth_path"]]
    )

    auth_conn = init_auth_db(stores["auth_path"])
    try:
        assert get_user(auth_conn, "boss").role == "admin"
    finally:
        auth_conn.close()


def test_useradd_without_the_flag_creates_a_plain_user(stores, monkeypatch):
    _feed_password(monkeypatch, "pw", "pw")

    useradd(["reinier", "--db", stores["master_path"], "--auth-db", stores["auth_path"]])

    auth_conn = init_auth_db(stores["auth_path"])
    try:
        assert get_user(auth_conn, "reinier").role == "user"
    finally:
        auth_conn.close()


def test_useradd_on_a_duplicate_exits_non_zero_and_adds_no_second_entry(
    stores, monkeypatch
):
    _feed_password(monkeypatch, "pw", "pw", "pw2", "pw2")
    argv = ["reinier", "--db", stores["master_path"], "--auth-db", stores["auth_path"]]

    assert useradd(argv) == 0
    assert useradd(argv) == 1

    master_conn = sqlite3.connect(stores["master_path"])
    try:
        assert len(list_reviewers(master_conn)) == 1
    finally:
        master_conn.close()


def test_useradd_rejects_mismatched_passwords(stores, monkeypatch):
    _feed_password(monkeypatch, "pw", "different")

    code = useradd(
        ["reinier", "--db", stores["master_path"], "--auth-db", stores["auth_path"]]
    )

    assert code == 2
    auth_conn = init_auth_db(stores["auth_path"])
    try:
        assert get_user(auth_conn, "reinier") is None
    finally:
        auth_conn.close()


def test_useradd_rejects_an_empty_password(stores, monkeypatch):
    _feed_password(monkeypatch, "", "")

    assert (
        useradd(
            ["reinier", "--db", stores["master_path"], "--auth-db", stores["auth_path"]]
        )
        == 2
    )


def test_useradd_reports_a_missing_master_db(tmp_path, stores, monkeypatch):
    code = useradd(
        [
            "reinier",
            "--db",
            str(tmp_path / "nope.db"),
            "--auth-db",
            stores["auth_path"],
        ]
    )

    assert code == 2


def test_password_never_appears_in_argv_or_output(stores, monkeypatch, capsys):
    """INV-KK-AUTH-NO-PLAINTEXT-PASSWORD at the CLI boundary."""
    secret = "sup3r-s3cret-value"
    _feed_password(monkeypatch, secret, secret)
    argv = ["reinier", "--db", stores["master_path"], "--auth-db", stores["auth_path"]]

    useradd(argv)

    assert secret not in " ".join(argv)
    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err

    auth_conn = init_auth_db(stores["auth_path"])
    try:
        row = auth_conn.execute(
            "SELECT password_hash, salt FROM users WHERE username = 'reinier'"
        ).fetchone()
    finally:
        auth_conn.close()
    assert secret not in row["password_hash"]
    assert secret not in row["salt"]


# --- kk-userlist and kk-passwd ----------------------------------------------


def test_userlist_reports_no_users_on_an_empty_store(stores, capsys):
    assert userlist(["--auth-db", stores["auth_path"]]) == 0
    assert "No users registered." in capsys.readouterr().out


def test_userlist_lists_username_role_and_state(stores, monkeypatch, capsys):
    _feed_password(monkeypatch, "pw", "pw")
    useradd(
        ["boss", "--admin", "--db", stores["master_path"], "--auth-db", stores["auth_path"]]
    )
    capsys.readouterr()

    userlist(["--auth-db", stores["auth_path"]])

    out = capsys.readouterr().out
    assert "boss" in out
    assert "admin" in out
    assert "active" in out


def test_passwd_changes_the_password(stores, monkeypatch):
    _feed_password(monkeypatch, "old-pw", "old-pw", "new-pw", "new-pw")
    useradd(["reinier", "--db", stores["master_path"], "--auth-db", stores["auth_path"]])

    assert passwd(["reinier", "--auth-db", stores["auth_path"]]) == 0

    auth_conn = init_auth_db(stores["auth_path"])
    try:
        assert authenticate(auth_conn, "reinier", "old-pw") is None
        assert authenticate(auth_conn, "reinier", "new-pw") is not None
    finally:
        auth_conn.close()


def test_passwd_on_an_unknown_user_exits_non_zero(stores, monkeypatch):
    _feed_password(monkeypatch, "pw", "pw")

    assert passwd(["nobody", "--auth-db", stores["auth_path"]]) == 1
