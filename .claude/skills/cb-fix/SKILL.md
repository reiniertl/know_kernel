---
name: cb-fix
description: Contract-driven skill for bug-targeted work. Silk owns the FSM; the LLM follows contract stages via silk run begin/state/submit-stage/finalize.
---

# /cb-fix — contract-driven workflow

CLAUDE.md inviolable rules #1--#4 apply. No mutation outside this skill.

## Protocol

1. Open a contract:
   `npm run silk -- run begin --skill cb-fix --request "<bug description>" --json`
2. Submit triage envelope manually (triage hook is cb-green only):
   Fill `templates/fp0-triage.request.json`, write to file, submit via
   `npm run silk -- run submit-stage --phases <envelope.json>`
3. `npm run silk -- run state --compact` — read current stage + rules.
4. Continue the card exchange: load the stage template, do the work,
   write an envelope, submit via `npm run silk -- run submit-stage`.
5. Repeat (3–4) for each stage until all complete.
6. `npm run silk -- run finalize` — close the contract; use its verdict.

## Stage templates (.claude/skills/cb-fix/templates/)

| Stage | Template | Phase |
|---|---|---|
| fp0-triage | fp0-triage.request.json | FP0_TRIAGE |
| fp1-reproduce | fp1-reproduce.request.json | FP1_REPRODUCE |
| fp2-diagnose | fp2-diagnose.request.json | FP2_DIAGNOSE |
| fp3-root-cause | fp3-root-cause.request.json | FP3_ROOT_CAUSE |
| fp4-read | fp4-read.request.json | FP4_READ |
| fp5-map | fp5-map.request.json | FP5_MAP |
| fp6-mutate | fp6-mutate.request.json | FP6_MUTATE |
| fp7-validate | fp7-validate.request.json | FP7_VALIDATE |
| fp8-plan-impl | fp8-plan-impl.request.json | FP8_PLAN_IMPL |
| fp9-implement | fp9-implement.request.json | FP9_IMPLEMENT |
| fp10-verify | fp10-verify.request.json | FP10_VERIFY |
| fp11-report | fp11-report.request.json | FP11_REPORT |

## Efficient spec queries

When querying multiple nodes during read-only discovery (fp4-read,
fp5-map), use `ril query-multi` to batch reads in one subprocess:

```
npm run ril -- query-multi '[{"cmd":"node-info","args":["ID-1","ID-2"]}]' --json
```

See CLAUDE.md "Efficient query patterns" for details.

Report silk's `finalStatus` — never substitute your own claim.
