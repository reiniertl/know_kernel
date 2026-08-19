"""Command line user administration — ALG-KK-AUTH-CLI-USERADD.

    kk-useradd [--admin] [--db PATH] [--auth-db PATH] <username>
    kk-userlist [--auth-db PATH]
    kk-passwd [--auth-db PATH] <username>

Passwords are read from the terminal with getpass and confirmed twice. They are
never accepted as an argv argument and never echoed
(INV-KK-AUTH-NO-PLAINTEXT-PASSWORD).

Creating a user writes to two stores that cannot share a transaction. The order
is fixed — user row, roster entry, commit auth.db, commit master.db — and any
failure rolls both back and exits non-zero. A half-applied state is never left
silently (ALG-KK-AUTH-USER-CREATE).
"""

from __future__ import annotations

import argparse
import getpass
import sqlite3
import sys
from pathlib import Path

from authgate.roster import ensure_roster_entry
from authgate.schema import auth_db_path, init_auth_db
from authgate.store import create_user, list_users, set_password


def _default_master_db() -> str:
    import os

    env = os.environ.get("KNOW_KERNEL_DB")
    if env:
        return env
    return str(Path(__file__).resolve().parents[2] / "data" / "master.db")


def _prompt_password(prompt: str = "Password: ") -> str:
    """Read a password twice and confirm the two match."""
    first = getpass.getpass(prompt)
    if not first:
        raise ValueError("Password must be non-empty")
    second = getpass.getpass("Repeat password: ")
    if first != second:
        raise ValueError("Passwords do not match")
    return first


def create_user_with_roster(
    auth_conn: sqlite3.Connection,
    master_conn: sqlite3.Connection,
    username: str,
    password: str,
    role: str = "user",
) -> str:
    """ALG-KK-AUTH-USER-CREATE — user row plus roster entry, both or neither.

    Returns the Reviewer node id. Rolls both stores back and re-raises if
    either half fails.
    """
    try:
        record = create_user(auth_conn, username, password, role=role)
        reviewer_id = ensure_roster_entry(master_conn, record.username)
        auth_conn.commit()
        master_conn.commit()
    except Exception:
        auth_conn.rollback()
        master_conn.rollback()
        raise
    return reviewer_id


def useradd(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kk-useradd",
        description="Create a login user and mirror it onto the reviewer roster.",
    )
    parser.add_argument("username", help="Login name (also the roster name)")
    parser.add_argument(
        "--admin", action="store_true", help="Create the user with the admin role"
    )
    parser.add_argument(
        "--db", default=None, help="Path to master.db (default: KNOW_KERNEL_DB)"
    )
    parser.add_argument(
        "--auth-db", default=None, help="Path to auth.db (default: KNOW_KERNEL_AUTH_DB)"
    )
    args = parser.parse_args(argv)

    master_path = Path(args.db or _default_master_db())
    if not master_path.exists():
        print(f"Error: master DB not found: {master_path}", file=sys.stderr)
        return 2

    try:
        password = _prompt_password()
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    auth_conn = init_auth_db(args.auth_db or auth_db_path())
    master_conn = sqlite3.connect(str(master_path))
    master_conn.execute("PRAGMA foreign_keys=ON")
    role = "admin" if args.admin else "user"
    try:
        create_user_with_roster(
            auth_conn, master_conn, args.username, password, role=role
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        auth_conn.close()
        master_conn.close()

    print(f"Created {args.username.strip().lower()} ({role})")
    return 0


def userlist(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kk-userlist", description="List login users."
    )
    parser.add_argument("--auth-db", default=None, help="Path to auth.db")
    args = parser.parse_args(argv)

    auth_conn = init_auth_db(args.auth_db or auth_db_path())
    try:
        users = list_users(auth_conn)
    finally:
        auth_conn.close()

    if not users:
        print("No users registered.")
        return 0
    for user in users:
        state = "active" if user.active else "inactive"
        print(f"{user.username}\t{user.role}\t{state}\t{user.created_at}")
    return 0


def passwd(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kk-passwd", description="Change a user's password."
    )
    parser.add_argument("username", help="Login name")
    parser.add_argument("--auth-db", default=None, help="Path to auth.db")
    args = parser.parse_args(argv)

    try:
        password = _prompt_password("New password: ")
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    auth_conn = init_auth_db(args.auth_db or auth_db_path())
    try:
        set_password(auth_conn, args.username, password)
        auth_conn.commit()
    except ValueError as exc:
        auth_conn.rollback()
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        auth_conn.close()

    print(f"Password updated for {args.username.strip().lower()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """python -m authgate.cli <useradd|userlist|passwd> [args]"""
    args = list(sys.argv[1:] if argv is None else argv)
    commands = {"useradd": useradd, "userlist": userlist, "passwd": passwd}
    if not args or args[0] not in commands:
        print(f"Usage: authgate.cli {{{'|'.join(commands)}}} [args]", file=sys.stderr)
        return 2
    return commands[args[0]](args[1:])


if __name__ == "__main__":
    sys.exit(main())
