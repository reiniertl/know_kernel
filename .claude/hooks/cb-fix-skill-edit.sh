#!/usr/bin/env bash
# CS-072b Phase 3: PostToolUse hook for /cb-fix SKILL.md edits.
# Never blocks (exits 0 always).

ARGS="$ARGUMENTS"

if echo "$ARGS" | grep -qE "\.claude/skills/cb-fix/SKILL\.md"; then
  cat >&2 <<'EOF'
CB-FIX-SKILL-EDITED: SKILL.md implements 5 cb-fix algorithms
(CB-FIX-TRIAGE/REPRODUCE/DIAGNOSE/ROOT-CAUSE/REPORT) + inherits 7
cb-code algorithms through shared `enables` edges in cb-fix-fsm.

Recommended checks:
  1. npm run spec:check          # L1 + L3 validate
  2. CbFixReport still extends CbCodeReport (inherits 9 cb-code fields)
  3. Reproduction-test invariants still enforced in prompt body:
     - CB-FIX-INV-REPRODUCE-BEFORE-FIX
     - CB-FIX-INV-REPRODUCE-PASSES-AFTER-FIX
     - CB-FIX-INV-ROOT-CAUSE-CLASSIFIED

See docs/case-studies/CS-072-llm-protocol-layer.md.
EOF
fi

exit 0
