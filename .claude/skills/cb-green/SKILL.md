---
name: cb-green
description: Contract-driven skill for code work (feature / change / refactor). Triage is handled by hook; Opus plans and implements against the pre-materialized surface.
---

# /cb-green — contract-driven workflow

CLAUDE.md inviolable rules #1--#4 apply. No mutation outside this skill.

## What the hook already did

Before you see this, the `cb-green-triage-dispatch` hook has:

1. Opened the gate (`silk gate-mark init cb-green`)
2. Opened the contract (`silk run begin --skill cb-green`)
3. Spawned a triage model (Haiku) to discover relevant DAG nodes
4. Submitted the triage stage (contract advanced from stage 0 to 1)
5. Assembled composite output with: original request, triage findings,
   and contract state

You have everything you need to start working.

## Authoring schema

The authoring schema is cached at `.combobul/cache/authoring-schema.json`
(regenerated every session start by the SessionStart hook). Read it
once when you need valid node kinds, required attributes, or edge
constraints:

```
Read .combobul/cache/authoring-schema.json
```

Do NOT re-query `ril schema --json` — use the cached file. If the
cache is missing, generate it:
`npm run ril -- schema --json > .combobul/cache/authoring-schema.json`

## Stage lifecycle

The contract progresses through 5 stages. The triage hook (stage 0)
has already fired before you see this.

| Stage | Name | What happens | Mutations allowed? |
|-------|------|-------------|-------------------|
| 0 | triage | Hook spawns Haiku, discovers DAG nodes | YES (stage < 2) |
| 1 | plan | You plan the work, write spec-author envelope | YES (stage < 2) |
| 2 | spec-author | You submit the envelope; silk sets P3 | NO until P3 set |
| 3 | impl-batch | Code changes + `ril apply-batch` | YES (P3 active) |
| 4 | verify | `spec:check` + finalize | YES (P3 active) |

## P3 gate

Stages 0-1 allow all mutations freely. At stage 2+, the
`skill-active-gate` hook blocks ALL mutations (Edit, Write, Bash,
`ril apply-batch`) until silk writes P3 evidence.

**P3 is set automatically by silk** when you submit a spec-author
envelope via `silk run submit-stage`. If the envelope's
`payload.mutations` array is non-empty → `P3_PASS`. If empty →
`P3_SKIPPED`.

**To get P3_PASS with actual mutations:**
1. During stage 1 (plan), write your spec-author envelope to
   `.combobul/tmp/spec-author-envelope.json` with the mutations you intend
   to apply.
2. Submit the plan stage.
3. Submit the spec-author envelope — silk reads `payload.mutations`,
   sets `P3_PASS`, and unlocks mutations for stage 3+.
4. Run `ril apply-batch` with the same mutations during stage 3.

**Spec-author envelope format:**
```json
{
  "templateId": "cb-green-spec-author-v1",
  "schemaVersion": "1.0.0",
  "stage": "spec-author",
  "payload": {
    "mutations": [
      {"type": "remove-node", "nodeId": "OLD-NODE-ID"},
      {"type": "add-node", "node": {"id": "NEW-ID", "kind": "annotation", ...}},
      {"type": "add-edge", "edge": {"kind": "contains", "from": "MOD", "to": "NEW-ID"}}
    ]
  }
}
```

If no DAG changes are needed (documentation/infra-only work), submit
the template directly (`spec-author.request.json`) — silk sets
`P3_SKIPPED` and mutations are allowed via the skipped path.

## Workflow

### 1. Plan (stage 1)

Read the triage findings and spec surface from the hook output.
Plan the work citing specific node IDs from the surface. Use
`npm run ril -- query-multi` to batch any additional reads.

If DAG mutations are needed, write the spec-author envelope to
`.combobul/tmp/spec-author-envelope.json` during this stage (writes are
allowed at stage < 2).

### 2. Spec mutations (stage 2)

Submit the spec-author envelope:
```
npm run silk -- run submit-stage --phases .combobul/tmp/spec-author-envelope.json --run-id <ID>
```

Silk sets P3_PASS automatically. Then run `ril apply-batch` with
the mutations during stage 3.

Use the cached schema (`.combobul/cache/authoring-schema.json`) for
valid attributes, required edges, and cardinality constraints.

### 3. Implement (stage 3)

Apply the DAG mutations via `ril apply-batch`. Write code that
satisfies the spec nodes.

### 4. Verify (stage 4)

Run `npm run spec:check` before committing. One logical change per
commit.

### 5. Finalize

```
npm run silk -- run finalize
```

Report silk's `finalStatus` — never substitute your own claim.

## Authoring rules

The triage hook output includes an `## Authoring rules` section with
mutation formats, required attributes per kind, the apply-batch piping
pattern, and invariant extra rules. Read it — do not re-query
`ril template` or `ril schema`.
