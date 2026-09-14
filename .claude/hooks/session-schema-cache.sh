#!/usr/bin/env bash
# SessionStart hook: generate authoring schema cache from ril.
# Single canonical source: src/graph/auth-template.ts via `ril schema --json`.
# Overwrites on every session start so the cache is never stale within a session.
# The agent reads .combobul/cache/authoring-schema.json instead of querying ril.

set -e
CACHE_DIR=".combobul/cache"
mkdir -p "$CACHE_DIR"
npm run ril -- schema --json > "$CACHE_DIR/authoring-schema.json" 2>/dev/null
