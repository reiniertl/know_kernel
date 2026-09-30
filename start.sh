#!/usr/bin/env bash
# Start the know_kernel web server with the PoC demo database.
# Usage: ./start.sh [DB_PATH]
#   DB_PATH defaults to data/master.db

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

DB="${1:-$SCRIPT_DIR/data/master.db}"

# Resolve to absolute path
DB="$(cd "$(dirname "$DB")" && pwd)/$(basename "$DB")"

if [ ! -f "$DB" ]; then
    echo "ERROR: database not found: $DB"
    echo ""
    echo "Available databases:"
    ls "$SCRIPT_DIR"/data/*.db 2>/dev/null || echo "  (none)"
    exit 1
fi

export KNOW_KERNEL_DB="$DB"
export KNOW_KERNEL_AUTH_DB="${KNOW_KERNEL_AUTH_DB:-$SCRIPT_DIR/data/auth.db}"
export PYTHONPATH="$SCRIPT_DIR/src"

echo "Starting know_kernel web server..."
echo "  Database: $DB"
echo "  Auth DB:  $KNOW_KERNEL_AUTH_DB"
echo "  URL:      http://localhost:8000"
echo ""

# THE REPOSITORY'S OWN INTERPRETER, NEVER whatever `python` means on the PATH
# (ALG-KK-OPS-START-SERVER). This line used to read `python -m uvicorn`, which
# resolved to /usr/bin/python and failed with "No module named uvicorn" on a
# machine where nothing was missing — the venv holds uvicorn and fastapi, and
# the app imports cleanly there. That message names a DEPENDENCY when the
# INTERPRETER is wrong, and it sends a reader to pip install: run outside the
# venv that installs uvicorn into the system Python, makes the symptom vanish,
# and leaves this script still wrong. A failure that misdirects the repair is
# worse than a louder one.
PY="$SCRIPT_DIR/venv/bin/python"

if [ ! -x "$PY" ]; then
    echo "ERROR: the project virtualenv is missing or not executable:"
    echo "  $PY"
    echo ""
    echo "This is NOT a missing dependency. Create the venv and install into it:"
    echo "  python3 -m venv \"$SCRIPT_DIR/venv\""
    echo "  \"$PY\" -m pip install -e \"$SCRIPT_DIR\""
    exit 1
fi

# NO MODULE LIST HERE, DELIBERATELY. A hand-written check drifts and then
# reports confidently while drifting: while diagnosing the bug above, a guess at
# itsdangerous, passlib and bcrypt reported all three missing and all three are
# unused — src/authgate and src/web import only stdlib plus fastapi, with
# password hashing and sessions on hashlib, hmac and secrets. Python's own
# ImportError is current by construction; this script's job is to make sure the
# right Python raises it.

# authgate.app:app, never web.app:app — INV-KK-AUTH-GATE-COVERS-MOUNT:
# "Nothing served by the mounted app is reachable anonymously." ALG-KK-AUTH-GATE
# puts the single middleware on the PARENT gate app, registered before the Mount
# of the know_kernel app at /, so serving web.app directly bypasses
# authentication entirely rather than partially.
#
# (An edit on 2026-09-30 briefly claimed this citation was wrong, on the ground
# that the invariant "has no predicate". It has one. That was concluded from
# `ril query node`, whose payload omits predicate fields — a negative asserted
# from a tool that cannot establish one, against CLAUDE.md's explicit "prefer
# node-info over node". The original citation was correct and is restored.)
# --reload is safe: sessions live in auth.db, not in an in-process secret.
exec "$PY" -m uvicorn authgate.app:app --host 127.0.0.1 --port 8000 --reload
