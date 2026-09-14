#!/usr/bin/env bash
# CS-072b Phase 3: PostToolUse hook — annotate when a file under tests/
# is edited, reminding that FP1_REPRODUCE requires the new test to
# FAIL before fixing.
# Never blocks (exits 0 always).

ARGS="$ARGUMENTS"

if echo "$ARGS" | grep -qE "tests/.*\.test\.ts"; then
  cat >&2 <<'EOF'
CB-FIX-REPRODUCTION-REMINDER: A test file was edited.

If this is a /cb-fix session reproduction test (FP1_REPRODUCE):
  Per CB-FIX-INV-REPRODUCE-BEFORE-FIX, the new test MUST fail
  before you implement the fix. Run `npm test` and confirm:
    - the new test FAILS (that is what reproduces the bug)
    - no other tests regress

Per CB-FIX-INV-REPRODUCE-PASSES-AFTER-FIX, after the fix (FP9):
  - the same reproduction test must now PASS
  - no other tests regress

If this edit is unrelated to /cb-fix, disregard.
EOF
fi

exit 0
