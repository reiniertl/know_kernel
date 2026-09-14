---
name: cb-audit
description: Contract-driven skill for read-only analysis and issue collection. Silk owns the FSM; the LLM follows contract stages via silk run begin/state/submit-stage/finalize. Every stage carries forbidden=[edit,write,mutating-bash,mutating-ril,mutating-silk].
---

# /cb-audit — contract-driven workflow

CLAUDE.md inviolable rules #1--#4 apply. cb-audit is READ-ONLY by design.

## Protocol

1. `npm run silk -- run begin --skill cb-audit --phases <request-file>` — open a contract.
3. `npm run silk -- run state --compact` — read current stage + rules.
4. Do the stage work (read-only queries, analysis, reasoning).
5. Submit the stage envelope inline (no file write needed):
   `npm run silk -- run submit-stage --request '<envelope-json>'`
6. Repeat (3–5) for each stage until all complete.
7. `npm run silk -- run finalize` — close the contract; use its verdict.

## Stage submission — inline envelopes

cb-audit's forbidden set blocks all file writes (Edit, Write,
mutating Bash). Use `--request` to pass the envelope JSON inline
instead of `--phases <file>`:

```bash
npm run silk -- run submit-stage --request '{"templateId":"cb-audit-ap0-triage-v1","schemaVersion":"1.0.0","stage":"ap0-triage","payload":{"scope":"SCOPE_INVARIANT","rationale":"..."}}'
```

The `--request` flag accepts inline JSON and does not touch the
filesystem. This is the ONLY way to submit envelopes during
cb-audit — do NOT attempt to write temp files.

## Stage templates (.claude/skills/cb-audit/templates/)

| Stage | Template | Phase |
|---|---|---|
| ap0-triage | ap0-triage.request.json | AP0_TRIAGE |
| ap1-inventory | ap1-inventory.request.json | AP1_INVENTORY |
| ap2-analyze | ap2-analyze.request.json | AP2_ANALYZE |
| ap3-classify | ap3-classify.request.json | AP3_CLASSIFY |
| ap4-recommend | ap4-recommend.request.json | AP4_RECOMMEND |
| ap5-report | ap5-report.request.json | AP5_REPORT |

### Minimal envelope shapes per stage

```
AP0: {"templateId":"cb-audit-ap0-triage-v1","schemaVersion":"1.0.0","stage":"ap0-triage","payload":{"scope":"<SCOPE_ENUM>","rationale":"..."}}

AP1: {"templateId":"cb-audit-ap1-inventory-v1","schemaVersion":"1.0.0","stage":"ap1-inventory","payload":{"nodeCountByKind":{},"modules":[],"summary":"..."}}

AP2: {"templateId":"cb-audit-ap2-analyze-v1","schemaVersion":"1.0.0","stage":"ap2-analyze","payload":{"findings":[]}}

AP3: {"templateId":"cb-audit-ap3-classify-v1","schemaVersion":"1.0.0","stage":"ap3-classify","payload":{"classified":[]}}

AP4: {"templateId":"cb-audit-ap4-recommend-v1","schemaVersion":"1.0.0","stage":"ap4-recommend","payload":{"recommendations":[]}}

AP5: {"templateId":"cb-audit-ap5-report-v1","schemaVersion":"1.0.0","stage":"ap5-report","payload":{"verdict":"PASS|FAIL","summary":"..."}}
```

## Efficient spec queries

Batch all read-only DAG queries via `ril query-multi` to avoid
repeated subprocess spawns:

```
npm run ril -- query-multi '[{"cmd":"node-info","args":["ID-1","ID-2"]},{"cmd":"impact-analysis","args":["ID-3"]}]' --json
```

See CLAUDE.md "Efficient query patterns" for details.

## Common pitfalls

1. **Do not write temp files.** The skill-active-gate hook blocks
   ALL writes — including mktemp, cat >, node -e writeFileSync,
   PowerShell Set-Content, etc. Use `--request` for inline submission.

2. **Do not use PowerShell** for anything that creates files. The
   gate matches Set-Content, Out-File, New-Item patterns.

3. **Reusing stale envelope files is fragile.** Prior audit envelopes
   (.combobul/tmp/cb-audit-ap*.json) contain payload from previous runs. The
   templateId + schemaVersion will match, but the payload is wrong.
   Use `--request` with fresh payload instead.

Report silk's `finalStatus` — never substitute your own claim.
