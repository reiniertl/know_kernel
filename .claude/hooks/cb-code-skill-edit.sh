#!/usr/bin/env bash
# CS-072 Phase 3: PostToolUse hook — annotate when SKILL.md for /cb-code is edited.
# Reminds the author that SKILL.md is spec-governed by SUB-SILK (previously SUB-LLM-PROTOCOL)
# and must stay in sync with the DAG.
# Never blocks (exits 0 always) per CS-072 D2 (annotate, don't block).

ARGS="$ARGUMENTS"

if echo "$ARGS" | grep -qE "\.claude/skills/cb-code/SKILL\.md"; then
  cat >&2 <<'EOF'
CB-CODE-SKILL-EDITED: SKILL.md is the implementation artifact for
10 algorithm nodes (CB-CODE-TRIAGE..CB-CODE-REPORT) and 4 coupling
invariants in SUB-SILK (previously SUB-LLM-PROTOCOL).

Recommended checks:
  1. npm run spec:check          # L1 + L3 validate
  2. Review: output format section matches CbCodeReport interface schema
  3. Review: hard rules still enforce all 4 coupling invariants

See docs/case-studies/CS-072-llm-protocol-layer.md for context.
EOF
fi

exit 0
