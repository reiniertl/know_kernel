#!/usr/bin/env bash
# CS-072 Phase 3: PostToolUse hook after Bash — annotate when bash commands
# run `spec:check` or `npm test` and fail, reminding that
# CB-CODE-INV-VERIFIED-BEFORE-SUCCESS forbids claiming SUCCESS
# unless these pass.
# Never blocks (exits 0 always).

ARGS="$ARGUMENTS"

# Detect if a verification command was just run
if echo "$ARGS" | grep -qE "npm run spec:check|npm test|npm run spec:conformance"; then
  cat >&2 <<'EOF'
CB-CODE-VERIFY-REMINDER: A verification tool ran.

Per CB-CODE-INV-VERIFIED-BEFORE-SUCCESS (in SUB-SILK (previously SUB-LLM-PROTOCOL)):
  If you emit FINAL_STATUS = SUCCESS in a /cb-code session,
  PHASE_LOG must contain P7_VERIFY with result PASS.

If any tool reported errors, set FINAL_STATUS = BLOCKED_BY_VERIFICATION.
Do not claim SUCCESS.
EOF
fi

exit 0
