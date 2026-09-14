# cb-audit Cheat Sheet

Quick reference for running a read-only spec audit.

## Full lifecycle (copy-paste ready)

```bash
# 1. Open contract
npm run silk -- run begin --skill cb-audit --phases ".claude/skills/cb-audit/templates/ap0-triage.request.json"

# 2. Check state
npm run silk -- run state --compact

# 3. Submit all 6 stages inline (replace payloads with real data)
npm run silk -- run submit-stage --request '{"templateId":"cb-audit-ap0-triage-v1","schemaVersion":"1.0.0","stage":"ap0-triage","payload":{"scope":"SCOPE_INVARIANT","rationale":"..."}}'

npm run silk -- run submit-stage --request '{"templateId":"cb-audit-ap1-inventory-v1","schemaVersion":"1.0.0","stage":"ap1-inventory","payload":{"nodeCountByKind":{},"modules":[],"summary":"..."}}'

npm run silk -- run submit-stage --request '{"templateId":"cb-audit-ap2-analyze-v1","schemaVersion":"1.0.0","stage":"ap2-analyze","payload":{"findings":[]}}'

npm run silk -- run submit-stage --request '{"templateId":"cb-audit-ap3-classify-v1","schemaVersion":"1.0.0","stage":"ap3-classify","payload":{"classified":[]}}'

npm run silk -- run submit-stage --request '{"templateId":"cb-audit-ap4-recommend-v1","schemaVersion":"1.0.0","stage":"ap4-recommend","payload":{"recommendations":[]}}'

npm run silk -- run submit-stage --request '{"templateId":"cb-audit-ap5-report-v1","schemaVersion":"1.0.0","stage":"ap5-report","payload":{"verdict":"PASS","summary":"..."}}'

# 4. Finalize
npm run silk -- run finalize
```

## Key rules

- **ALL submissions use `--request` (inline JSON), NEVER `--phases` (file)**
  The gate blocks all file writes during cb-audit.

- **Do the actual audit work BETWEEN submissions**
  Query the DAG, run spec:check, analyze findings, then encode
  results in the stage payload.

- **Stage order is fixed**: ap0 -> ap1 -> ap2 -> ap3 -> ap4 -> ap5

## Scope enum (AP0)

| Value | When |
|---|---|
| SCOPE_MODULE | Audit scoped to one module |
| SCOPE_INVARIANT | Audit scoped to invariants/predicates |
| SCOPE_INTERFACE | Audit scoped to interfaces |
| SCOPE_SYSTEM_WIDE | Cross-cutting audit |
| REJECT | Request is not auditable |

## Read-only tools available

| Tool | Example |
|---|---|
| ril query-multi | `npm run ril -- query-multi '[...]' --json` |
| ril query node-info | `npm run ril -- query node-info ID1 ID2 --json` |
| ril query impact-analysis | `npm run ril -- query impact-analysis ID1 --json` |
| spec:check | `npm run spec:check` |
| spec:validate | `npm run spec:validate` |
| spec:semantic-validate | `npm run spec:semantic-validate` |
| git log/diff/status | Read-only git commands |
| Read/Grep/Glob | File inspection tools |

## What NOT to do

- Write files (Edit, Write, Bash with >, mktemp, tee, etc.)
- Use PowerShell with Set-Content, Out-File, New-Item
- Use `--phases` for submit-stage (requires a file)
- Reuse stale envelope files from .combobul/tmp/ (wrong payload)
- Run node -e with writeFileSync
