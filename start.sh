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
export PYTHONPATH="$SCRIPT_DIR/src"

echo "Starting know_kernel web server..."
echo "  Database: $DB"
echo "  URL:      http://localhost:8000"
echo ""

python -m uvicorn web.app:app --host 127.0.0.1 --port 8000 --reload
