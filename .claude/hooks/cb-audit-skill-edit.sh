#!/usr/bin/env bash
# CS-072c Phase 3: PostToolUse hook for /cb-audit SKILL.md edits.
# Never blocks (exits 0 always).

ARGS="$ARGUMENTS"

if echo "$ARGS" | grep -qE "\.claude/skills/cb-audit/SKILL\.md"; then
  cat >&2 <<'EOF'
CB-AUDIT-SKILL-EDITED: SKILL.md implements 6 cb-audit algorithms
and enforces the read-only invariant (CB-AUDIT-INV-NO-MUTATION).

Critical review points:
  1. Hard rules still forbid mutation (no ril apply-batch, no Edit/Write)
  2. AP3_CLASSIFY still maps tool outputs to CB-AUDIT-FINDING-KIND-ENUM
  3. Finding schema still requires nodeId / kind / severity / message
  4. finalStatus = BLOCKED path preserved for tool failures
  5. npm run spec:check / spec:conformance still invoked at AP2_ANALYZE

See docs/case-studies/CS-072-llm-protocol-layer.md.
EOF
fi

exit 0
