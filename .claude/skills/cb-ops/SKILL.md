---
name: cb-ops
description: Operational-only skill for routine git / npm actions that don't shape spec or code. Menu-driven (proposes 2-4 context-aware options via AskUserQuestion); operator picks; the pick runs; reports. NOT silk-driven. NO PHASE_LOG, NO P3 ceremony, NO silk run validation. Permits a fixed allowlist (git push/fetch/pull/tag/stash, branch checkout, npm install/ci); denies DAG mutation, source-tree edits, arbitrary shell. Use this instead of /cb-green for "push these commits", "pull main", "npm install", etc.
---

# /cb-ops — operational mutation channel

> **Preferred model:** `claude-haiku-4-5-20251001` (Haiku 4.5). This skill is
> lightweight and menu-driven — switch to Haiku 4.5 before proceeding.
> Spec: ANN-SILK-CB-OPS-PREFERRED-MODEL.

You are the entry point for `/cb-ops`. This skill exists to handle
operational mutation that does not shape the spec or the code:
pushing already-reviewed commits, fetching, fast-forward pulls,
tagging, branch checkout, npm install / npm ci, and similar.

It is intentionally thin. There is no FSM, no PHASE_LOG, no
mandatory phases, no silk run validation, and no `silk drive ops`
CLI. The PreToolUse skill-active-gate hook recognises /cb-ops as
ACTIVE_OPS and enforces the allowlist mechanically.

## Inviolable rules (CB-OPS-INV-*)

- **CB-OPS-INV-OPERATIONAL-ONLY** — only commands matching the
  allowlist below run. Source-tree edits (Edit / Write /
  NotebookEdit) are denied. ril apply-batch / silk apply-batch /
  silk extract / silk rfc are denied. Arbitrary shell mutations
  (rm / mv / cp, redirection, sed -i, etc.) are denied.
- **CB-OPS-INV-MENU-FIRST** — propose options via
  `AskUserQuestion` before running anything. Don't execute on a
  bare action verb. The user's pick (or free-text "Other"
  answer) is what runs.
- **CLAUDE.md rule #1 (amended)** — /cb-ops is now one of the
  active-skill states permitted to mutate. The amendment is
  scoped: cb-ops authorises the allowlist below, nothing else.

## Operational allowlist

| Command family | Examples |
|---|---|
| `git push` | `git push origin <branch>`, `git push --tags` |
| `git fetch` | `git fetch`, `git fetch --all`, `git fetch <remote>` |
| `git pull --ff-only` | `git pull --ff-only origin <branch>` |
| `git tag` | `git tag <name>`, `git tag -a <name> -m <msg>`, `git push --tags` |
| `git stash` | `git stash push -m <msg>`, `git stash pop`, `git stash list` |
| `git checkout <branch>` | branch switching only — NEVER `git checkout -- <path>` (file restore is a destructive mutation outside cb-ops scope) |
| `git commit` | message-only commits (`-m <msg>`). Dangerous flags **denied**: `--amend` (rewrites history), `--no-verify` (bypasses pre-commit artifact-association hook), `--no-gpg-sign`, `--allow-empty`. The pre-commit hook (CS-080 R5) still runs and validates artifact-associations for newly-added source files. |
| `git add` | stage paths for the next commit (new, modified, or deleted files). Required to capture untracked paths since `git commit -a` only stages tracked-modified files. |
| `git rm` | remove tracked paths from the index (and optionally the working tree). Use for deletions that should land in the next commit. |
| `git mv` | rename / move tracked paths atomically (preserves git history). |
| `npm install` | lockfile-faithful install |
| `npm ci` | clean install from lockfile |
| `npm run ril -- rebuild` | Reconstruct spec.db from mutation log (after pull/checkout) |
| `npm run ril -- check-conflicts` | Detect semantic conflicts in mutation log (after merge) |

Anything else — including `git rebase`, `git reset`, `git merge`,
`git commit --amend`, `git commit --no-verify`,
`npm run <script>` (for scripts that mutate), file edits,
ril/silk mutating commands (apply-batch, propose, etc.) — is
**out of scope** for /cb-ops. Use the appropriate
/cb-green | /cb-fix skill or do read-only investigation
outside any skill.

## Protocol

### Step 0 — Activate gate

Run once before any other tool call:

```
npm run silk -- gate-mark init cb-ops --run-id cb-ops-session
```

### Step 1 — Gather context

Run read-only checks to understand the operational state:

```
git status --short
git log @{u}..HEAD --oneline      (unpushed commits)
git log HEAD..@{u} --oneline      (incoming commits)
git fetch --dry-run               (does the remote have updates?)
diff package-lock.json HEAD:package-lock.json  (lockfile drift)
```

### Step 2 — Propose options via AskUserQuestion

Synthesise 2-4 context-aware options grounded in what the context
shows. Default option order:

- (a) push unpushed commits — if `git log @{u}..HEAD` non-empty
- (b) fast-forward pull — if `git log HEAD..@{u}` non-empty
- (c) `ril rebuild` — if spec.db is stale or missing after pull/checkout
- (d) `git fetch` — always available
- (e) `npm ci` — if lockfile changed since last install
- (f) "Other (free-text operational command)" — fallback

If `<args>` is non-empty, treat it as a hint that biases the
ranking but still present the menu. Never execute on `<args>`
alone.

If nothing operational is pending, present a single "nothing to
do — close skill" option and emit FINAL_STATUS without running
anything.

### Step 3 — Run the picked command

Run the chosen Bash command. The PreToolUse hook will block any
out-of-allowlist invocation; if you see CB-OPS-ERR-OUT-OF-SCOPE,
the chosen command needs a different skill (/cb-green for
spec/code work, /cb-fix for bug work).

### Step 4 — Report

Emit a brief outcome:

```
COMMAND
<the exact command run>

OUTCOME
<2-3 lines summarising stdout / exit code>

FINAL_STATUS
<one of: SUCCESS | FAILED | NOTHING_TO_DO | OUT_OF_SCOPE>
```

That's the entire skill. No PHASE_LOG, no SPEC_CHANGESET, no
SILK_RUN_OUTPUT. Closing FINAL_STATUS terminates the skill; any
follow-up turn is again outside-skill (read-only) per the usual
state-machine.

## What /cb-ops is NOT

- Not a back-door for unaudited mutation. The hook enforces the
  allowlist; you cannot widen it from inside a skill turn.
- Not a replacement for /cb-green when the underlying action is
  actually a code/spec change disguised as an operational verb
  ("just install this new dep" is a code change → /cb-green).
- Not silk-validated. The skill ships without a `silk run ops`
  validator because there is no spec graph to validate against —
  the operation is its own outcome, captured in COMMAND/OUTCOME
  above.

## Spec traceability

This skill is governed by:

| Node | Role |
|---|---|
| `INV-NO-OFF-SKILL-MUTATION` | Amended in CS-OPS to add /cb-ops to the active-skill set |
| `CB-OPS-INV-OPERATIONAL-ONLY` | Allowlist + denial of DAG/source mutation |
| `CB-OPS-INV-MENU-FIRST` | Mandatory AskUserQuestion before execution |
| `CS-OPS-SKILL-INTRODUCTION` | Annotation anchoring this skill's introduction |

See the `/cb-green` invocation that introduced this skill for
rationale (commit message and CS-OPS-SKILL-INTRODUCTION
description).
