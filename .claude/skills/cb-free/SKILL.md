---
name: cb-free
description: "HUMAN-ONLY unconstrained mutation channel. Allows all tools with no P3 gate, no allowlist, no push restriction. NEVER auto-invoke — only runs when the user explicitly types /cb-free. Not silk-driven."
---

# /cb-free — unconstrained mutation channel

This skill unlocks all tools with no constraints. It is not
silk-driven — there is no FSM, no contract, no P3 gate, no push
restriction, no allowlist. The PreToolUse gate hook recognizes
`cb-free` as `ACTIVE_FREE` and allows all tool calls.

## Human-only invocation

This skill MUST only be invoked when a human explicitly types
`/cb-free`. Do NOT invoke it automatically, do NOT suggest
invoking it to bypass other skill constraints, do NOT invoke it
from automated modes (cron, schedule, loop). If you are unsure
whether a human typed it, assume they did not.

## Protocol

### Step 0 — Activate gate

```
npm run silk -- gate-mark init cb-free --run-id cb-free-session
```

### Step 1 — Work

Do whatever the user asks. All tools are available. There are no
constraints beyond the user's instructions and standard safety
guidelines.

### Step 2 — Deactivate

When done, clear the gate state:

```
npm run silk -- gate-mark clear
```

Then report what was done.

## What /cb-free is

- An escape hatch for ad-hoc operations that don't fit the
  ceremony of /cb-green or the allowlist of /cb-ops.
- A trust channel — the human takes responsibility for what
  runs under this skill.

## What /cb-free is NOT

- Not a way for the LLM to bypass constraints autonomously.
- Not a replacement for /cb-green when spec/code work is needed.
- Not a default — use /cb-green for spec-tracked work, /cb-ops
  for operational commands, /cb-free only when neither fits.
