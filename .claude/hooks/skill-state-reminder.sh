#!/usr/bin/env bash
# UserPromptSubmit hook — contract state injection.
#
# Reads runId from marker cache (gate-marker.json) FIRST.
# Falls back to transcript-based deriveRunId() if no marker.
#
# Trace: ALG-USER-PROMPT-SUBMIT-REMINDER,
#        INV-COMPACT-VIEW-PRESERVES-RULE-LOCALITY,
#        INV-PHASE-REMINDER-IS-HOOK-PUSHED.

cat >/dev/null

# Priority 1: marker cache → extract runId → silk run state
if [ -n "$TRANSCRIPT_PATH" ]; then
  SESSION_ID=$(basename "$TRANSCRIPT_PATH" .jsonl)
  MARKER_FILE="$PWD/.combobul/cache/silk/$SESSION_ID/gate-marker.json"
  if [ -f "$MARKER_FILE" ]; then
    MARKER_RUN_ID=$(node -e "try{const m=JSON.parse(require('fs').readFileSync('$MARKER_FILE','utf8'));if(m.runId)process.stdout.write(m.runId)}catch{}" 2>/dev/null)
    if [ -n "$MARKER_RUN_ID" ]; then
      COMPACT=$(npm run --silent silk -- run state --run-id "$MARKER_RUN_ID" --compact 2>/dev/null)
      if [ -n "$COMPACT" ]; then
        printf '%s\n' "$COMPACT"
        exit 0
      fi
    fi
  fi
fi

# Priority 2: transcript-based deriveRunId (temporary fallback)
COMPACT=$(npm run --silent silk -- run state --compact 2>/dev/null)
if [ -n "$COMPACT" ]; then
  printf '%s\n' "$COMPACT"
  exit 0
fi

# Priority 3: phase reminder
PHASE_REMINDER=$(npm run --silent silk -- drive auto --reminder 2>/dev/null)
if [ -n "$PHASE_REMINDER" ]; then
  printf '%s\n' "$PHASE_REMINDER"
fi

exit 0
