#!/usr/bin/env node
/*
 * CS-079 Stage 3 — PreToolUse mechanical gate.
 *
 * Denies mutating tool calls when no /cb-green | /cb-fix
 * skill is currently active. This is the mechanical backstop that
 * does not depend on the LLM reading any prompt.
 *
 * Contract (Claude Code PreToolUse hook):
 *   stdin  : JSON envelope { tool_name, tool_input, transcript_path, ... }
 *   exit 0 : allow tool call
 *   exit 2 : block tool call (stderr is shown to the LLM)
 *
 * Skill-active state derivation (CS-086 Stage I — contract + marker only):
 *   1. Contract first: read .combobul/runs/<runId>/contract.json
 *   2. Marker cache: read .combobul/cache/silk/<session>/gate-marker.json
 *   No transcript-JSONL scanning — silk-owned sources are authoritative.
 *
 * Trace: CS-078-INV-SILK-OWNS-SKILLS, CS-079, CS-086 Stage I.
 */

import fs from 'node:fs';
import path from 'node:path';

// INV-GATE-MARKER-GLOBAL: single project-global marker at fixed path.
const MARKER_PATH = path.join(process.cwd(), '.combobul', 'cache', 'silk', 'gate-marker.json');

const ALWAYS_MUTATING_TOOLS = new Set(['Edit', 'Write', 'NotebookEdit']);

// Conservative deny-list. Matches commands that mutate the working
// tree, repo state, package state, or DAG/silk state. Anything not
// matched falls through to allow.
const MUTATING_BASH_PATTERNS = [
  /\bgit\s+(commit|push|reset|rebase|merge|cherry-pick|revert|tag|branch|checkout|am|stash|gc|prune|filter-branch|update-ref|symbolic-ref|add)\b/,
  /\bnpm\s+run\s+ril\s+--\s+(apply-batch|propose|modify-node|remove-node|add-)/,
  /\bnpm\s+run\s+silk\s+--\s+(rfc|extract|apply-batch)/,
  /\b(rm|mv|cp|mkdir|rmdir|touch|chmod|chown)\s/,
  /(^|[\s|;&(])>(?!&)\s*\S/,
  /(^|[\s|;&(])>>\s*\S/,
  /\bsed\s+-i\b/,
  /\b(npm|pnpm|yarn)\s+(install|uninstall|ci|add|remove)\b/,
  /\b(pip|composer|winget|choco|brew|apt|apt-get|wsl\s+--install)\s+(install|uninstall|remove|add)\b/,
  /\bcat\s+>\s*\S/,
  /\btee\s+/,
];

const MUTATING_PS_PATTERNS = [
  /\b(Set-Content|Out-File|New-Item|Add-Content|Copy-Item|Move-Item|Remove-Item|Rename-Item)\b/i,
];

const MUTATING_NODE_PATTERNS = [
  /\bnode\s+-e\b.*\b(writeFileSync|writeSync|appendFileSync|renameSync|unlinkSync|mkdirSync|copyFileSync|rmSync)\b/,
];

function readStdin() {
  return new Promise((resolve, reject) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => { data += chunk; });
    process.stdin.on('end', () => resolve(data));
    process.stdin.on('error', reject);
  });
}

function isBashMutating(command) {
  if (typeof command !== 'string' || command.length === 0) return false;
  return MUTATING_BASH_PATTERNS.some((re) => re.test(command));
}

function isPsMutating(command) {
  if (typeof command !== 'string' || command.length === 0) return false;
  return MUTATING_PS_PATTERNS.some((re) => re.test(command));
}

function isNodeMutating(command) {
  if (typeof command !== 'string' || command.length === 0) return false;
  return MUTATING_NODE_PATTERNS.some((re) => re.test(command));
}

// INV-GATE-CONSULT-CONTRACT-FIRST: contract-first skill-state derivation.
// Reads .combobul/runs/<runId>/contract.json directly (same algorithm as
// deriveRunId in contract-store.ts) to avoid subprocess overhead.
const RUNS_DIR = '.combobul/runs';
const MUTATING_SKILLS = new Set(['cb-green', 'cb-fix']);

function skillToState(skill) {
  if (MUTATING_SKILLS.has(skill)) {
    return { state: 'ACTIVE_MUTATING', activeSkill: skill };
  }
  if (skill === 'cb-ops') {
    return { state: 'ACTIVE_OPS', activeSkill: skill };
  }
  if (skill === 'cb-free') {
    return { state: 'ACTIVE_FREE', activeSkill: skill };
  }
  return null;
}

// INV-CB-AUDIT-FORBIDDEN-EXPLICIT: read forbidden from the skill's
// stage templates. Data-driven replacement for the hardcoded
// READONLY_SKILLS set (CS-086 Stage J.2).
function readSkillForbidden(skill) {
  const templatesDir = path.join(process.cwd(), '.claude', 'skills', skill, 'templates');
  if (!fs.existsSync(templatesDir)) return null;
  let files;
  try {
    files = fs.readdirSync(templatesDir).filter(f => f.endsWith('.request.json'));
  } catch {
    return null;
  }
  if (files.length === 0) return null;
  try {
    const template = JSON.parse(fs.readFileSync(path.join(templatesDir, files[0]), 'utf8'));
    return Array.isArray(template.forbidden) ? template.forbidden : null;
  } catch {
    return null;
  }
}

function readContractFromRunId(runId) {
  const contractFile = path.join(process.cwd(), RUNS_DIR, runId, 'contract.json');
  if (!fs.existsSync(contractFile)) return null;
  let contract;
  try {
    contract = JSON.parse(fs.readFileSync(contractFile, 'utf8'));
  } catch {
    return null;
  }
  if (contract.status === 'closed') return null;
  const stage = typeof contract.currentStage === 'number' ? contract.currentStage : 0;
  const result = skillToState(contract.skill);
  if (result) return { ...result, currentStage: stage };
  const forbidden = readSkillForbidden(contract.skill);
  if (forbidden) {
    return { state: 'ACTIVE_FORBIDDEN', activeSkill: contract.skill, forbidden, currentStage: stage };
  }
  return null;
}

function readGlobalMarkerState() {
  if (!fs.existsSync(MARKER_PATH)) return null;
  let marker;
  try {
    marker = JSON.parse(fs.readFileSync(MARKER_PATH, 'utf8'));
  } catch {
    return null;
  }
  if (!marker.skill) return null;
  const result = skillToState(marker.skill);
  if (result) {
    if (marker.runId) {
      const contractResult = readContractFromRunId(marker.runId);
      if (contractResult) return contractResult;
      const contractFile = path.join(process.cwd(), RUNS_DIR, marker.runId, 'contract.json');
      if (fs.existsSync(contractFile)) return null;
    }
    return result;
  }
  const forbidden = readSkillForbidden(marker.skill);
  if (forbidden) {
    return { state: 'ACTIVE_FORBIDDEN', activeSkill: marker.skill, forbidden };
  }
  return null;
}

// CB-OPS-INV-OPERATIONAL-ONLY allowlist. Patterns matching one of
// these AND not matching any line in OPS_DENY_PATTERNS may run when
// skill-state = ACTIVE_OPS.
const OPS_ALLOW_PATTERNS = [
  /^\s*git\s+push(\s+|$)/,
  /^\s*git\s+fetch(\s+|$)/,
  /^\s*git\s+pull\s+--ff-only(\s+|$)/,
  /^\s*git\s+tag(\s+|$)/,
  /^\s*git\s+stash(\s+(push|pop|list|apply|drop|show)\b|\s*$)/,
  // git checkout <branch> — branch only, never `-- <path>` (path
  // restore is destructive and out of scope).
  /^\s*git\s+checkout\s+(?!--\s)[^\s-][^\s]*\s*$/,
  // git commit — message-only commits permitted; dangerous flags
  // (--amend, --no-verify, --no-gpg-sign, --allow-empty) are
  // subtracted by OPS_DENY_PATTERNS so commit-message discipline
  // and hook validation stay intact.
  /^\s*git\s+commit(\s+|$)/,
  // Staging primitives — needed by git commit to capture new,
  // deleted, and renamed paths. No deny-flags: git add -f only
  // affects ignored files (intentional act); git rm/mv have no
  // dangerous flag equivalents worth blocking at this layer.
  /^\s*git\s+add(\s+|$)/,
  /^\s*git\s+rm(\s+|$)/,
  /^\s*git\s+mv(\s+|$)/,
  /^\s*npm\s+install\s*$/,
  /^\s*npm\s+ci\s*$/,
  // RIL read-only operational commands — needed after pull/checkout
  // to reconstruct spec.db, create checkpoints, and detect conflicts.
  /^\s*npm\s+run\s+ril\s+--\s+rebuild(\s|$)/,
  /^\s*npm\s+run\s+ril\s+--\s+snapshot(\s|$)/,
  /^\s*npm\s+run\s+ril\s+--\s+check-conflicts(\s|$)/,
];

// Even within ACTIVE_OPS, these are always denied — they would
// constitute DAG mutation, silk apply, or arbitrary shell.
const OPS_DENY_PATTERNS = [
  /\bril\s+--\s+(apply-batch|propose|modify-node|remove-node|add-)/,
  /\bnpm\s+run\s+ril\s+--\s+(?!rebuild(\s|$)|snapshot(\s|$)|check-conflicts(\s|$))\S/,
  /\bsilk\s+--\s+(rfc|extract|apply-batch)/,
  /\bnpm\s+run\s+silk\s+--\s+(rfc|extract|apply-batch)/,
  // git commit deny-flags: rewriting history (--amend), bypassing
  // the pre-commit artifact-association hook (--no-verify),
  // bypassing GPG signing (--no-gpg-sign), or recording empty
  // commits (--allow-empty) all defeat the safeguards that make
  // commit-in-cb-ops safe.
  /\bgit\s+commit\b[^\n]*\s--(amend|no-verify|no-gpg-sign|allow-empty)\b/,
];

function isOpsAllowedBash(command) {
  if (typeof command !== 'string' || command.length === 0) return false;
  if (OPS_DENY_PATTERNS.some((re) => re.test(command))) return false;
  return OPS_ALLOW_PATTERNS.some((re) => re.test(command));
}

/**
 * CS-080 R8 — P3 evidence from marker cache only (CS-086 Stage I).
 * Reads .combobul/cache/silk/<session>/gate-marker.json. Marker written by
 * `silk gate-mark p3-pass` is visible to the gate within the same
 * turn — no transcript-flush dependency.
 */
const MIN_SKIPPED_RATIONALE = 80;

function hasP3Evidence() {
  if (!fs.existsSync(MARKER_PATH)) return false;
  let marker;
  try {
    marker = JSON.parse(fs.readFileSync(MARKER_PATH, 'utf8'));
  } catch {
    return false;
  }
  if (marker.kind === 'P3_PASS') return true;
  if (marker.kind === 'P3_SKIPPED') {
    const rationale = (marker.rationale ?? '').trim();
    return rationale.length >= MIN_SKIPPED_RATIONALE;
  }
  return false;
}

async function main() {
  let envelope;
  try {
    const raw = await readStdin();
    envelope = raw.trim().length > 0 ? JSON.parse(raw) : {};
  } catch {
    process.exit(0);
  }
  const toolName = envelope.tool_name || '';
  const toolInput = envelope.tool_input || {};

  let mutating = false;
  let why = '';
  if (ALWAYS_MUTATING_TOOLS.has(toolName)) {
    mutating = true;
    why = `${toolName} always mutates files`;
  } else if (toolName === 'Bash') {
    if (isBashMutating(toolInput.command) || isNodeMutating(toolInput.command)) {
      mutating = true;
      const cmd = String(toolInput.command).slice(0, 200);
      why = `Bash command matches mutating deny-list: ${cmd}`;
    }
  } else if (toolName === 'PowerShell') {
    if (isBashMutating(toolInput.command) || isPsMutating(toolInput.command) || isNodeMutating(toolInput.command)) {
      mutating = true;
      const cmd = String(toolInput.command).slice(0, 200);
      why = `PowerShell command matches mutating deny-list: ${cmd}`;
    }
  }

  if (!mutating) process.exit(0);

  // CS-086 Stage I: derive skill-state from silk-owned sources only.
  // Marker first (explicit gate-mark overrides stale contract state),
  // then contract (fallback for first tool call before any gate-mark).
  // Fix for run-id reuse: deriveRunId is deterministic per session, so
  // multiple contracts overwrite each other. The marker is the explicit
  // "I am now in skill X" signal that resolves the ambiguity.
  const derived = readGlobalMarkerState() ?? { state: 'INACTIVE', activeSkill: null };
  const { state, activeSkill } = derived;
  const forbidden = derived.forbidden ?? null;
  const currentStage = derived.currentStage ?? 0;

  // CB-OPS-INV-OPERATIONAL-ONLY: under /cb-ops, only the operational
  // Bash allowlist runs. Edit/Write/NotebookEdit always denied;
  // ril/silk-mutating Bash always denied; non-allowlisted Bash denied.
  if (state === 'ACTIVE_OPS') {
    const cmd = String(toolInput.command || '');
    if ((toolName === 'Bash' || toolName === 'PowerShell') && isOpsAllowedBash(cmd)) process.exit(0);
    const opsBanner = [
      '',
      '┌─ BLOCKED by CS-OPS (skill-active-gate, ACTIVE_OPS allowlist) ───',
      `│ Tool denied: ${toolName}`,
      `│ Reason:      ${why}`,
      `│ Skill state: ACTIVE_OPS (cb-ops)`,
      `│ Error code:  CB-OPS-ERR-OUT-OF-SCOPE`,
      '│',
      '│ Per CB-OPS-INV-OPERATIONAL-ONLY, /cb-ops permits only the',
      '│ operational allowlist:',
      '│   git push | git fetch | git pull --ff-only | git tag |',
      '│   git stash {push|pop|list|apply|drop|show} |',
      '│   git checkout <branch> | git commit (no --amend/--no-verify/',
      '│   --no-gpg-sign/--allow-empty) | git add | git rm | git mv |',
      '│   npm install | npm ci',
      '│ Source-tree edits (Edit/Write/NotebookEdit), DAG mutation',
      '│ (ril apply-batch), and silk-mutating commands are denied.',
      '│',
      '│ Action: if this command is operational, refine it to match',
      '│ the allowlist. If it is a code/spec change, exit /cb-ops and',
      '│ invoke /cb-green | /cb-fix instead.',
      '└─────────────────────────────────────────────────────────────────',
      '',
    ].join('\n');
    process.stderr.write(opsBanner);
    process.exit(2);
  }

  if (state === 'ACTIVE_FREE') process.exit(0);

  if (state === 'ACTIVE_MUTATING') {
    // CS-083: git push remains /cb-ops-only as the publish-decision
    // boundary, even within an ACTIVE_MUTATING skill. Commit/add/rm/mv
    // are in scope; push is not.
    if (toolName === 'Bash' && /^\s*git\s+push(\s+|$)/.test(String(toolInput.command || ''))) {
      const pushBanner = [
        '',
        '┌─ BLOCKED by CS-083 (skill-active-gate, push-publication rule) ──',
        `│ Tool denied: Bash (git push)`,
        `│ Skill state: ACTIVE_MUTATING (${activeSkill})`,
        `│ Error code:  CB-MUTATING-ERR-PUSH-OUT-OF-SCOPE`,
        '│',
        '│ Per CS-083, mutating skills (/cb-green, /cb-fix)',
        '│ permit git commit/add/rm/mv as the natural close of an',
        '│ authoring session — but git push remains /cb-ops-only.',
        '│ Push is the publish-decision boundary; making it explicit',
        '│ keeps "is this change correct?" separate from "should we',
        '│ ship it now?".',
        '│',
        '│ Action: emit FINAL_STATUS to close this skill, then invoke',
        '│ /cb-ops to push.',
        '└─────────────────────────────────────────────────────────────────',
        '',
      ].join('\n');
      process.stderr.write(pushBanner);
      process.exit(2);
    }
    // CS-088: stages 0-1 (triage, plan) skip P3 — they are classification/planning, not spec mutation.
    if (currentStage < 2) process.exit(0);
    // CS-080 R4 P3-evidence gate. At stages >= 2 (spec-author, impl-batch, verify),
    // require P3_MUTATE evidence before allowing a mutating tool.
    // CS-086 Stage I: marker cache only, no transcript-JSONL scan.
    if (hasP3Evidence()) process.exit(0);
    const p3Banner = [
      '',
      '┌─ BLOCKED by CS-080 R4 (skill-active-gate, P3-evidence rule) ────',
      `│ Tool denied: ${toolName}`,
      `│ Reason:      ${why}`,
      `│ Skill state: ACTIVE_MUTATING (${activeSkill})`,
      `│ Error code:  CB-GREEN-ERR-MUTATION-WITHOUT-P3`,
      '│',
      '│ Per INV-MUTATION-REQUIRES-P3-EVIDENCE, the gate requires P3',
      '│ evidence before any mutating tool fires at stage >= 2.',
      '│ P3 evidence is set mechanically by silk when submit-stage',
      '│ accepts a spec-author envelope (CS-088).',
      '│',
      '│ If you see this error, submit the spec-author stage first.',
      '│ Silk will set P3_PASS (if mutations non-empty) or P3_SKIPPED',
      '│ (if mutations empty) automatically.',
      '└─────────────────────────────────────────────────────────────────',
      '',
    ].join('\n');
    process.stderr.write(p3Banner);
    process.exit(2);
  }

  // INV-CB-AUDIT-FORBIDDEN-EXPLICIT: contract-driven forbidden field.
  // Replaces the hardcoded READONLY_SKILLS set (CS-086 Stage J.2).
  if (state === 'ACTIVE_FORBIDDEN' && forbidden) {
    const forbiddenBanner = [
      '',
      '┌─ BLOCKED by contract forbidden field (skill-active-gate) ──────',
      `│ Tool denied: ${toolName}`,
      `│ Reason:      ${why}`,
      `│ Skill state: ACTIVE_FORBIDDEN (${activeSkill})`,
      `│ Forbidden:   [${forbidden.join(', ')}]`,
      '│',
      `│ Per INV-CB-AUDIT-FORBIDDEN-EXPLICIT, every ${activeSkill} stage`,
      '│ template carries an explicit forbidden tool set. The denied',
      '│ tool matches a forbidden category.',
      '│',
      '│ Action: this skill is read-only by contract. If you need to',
      '│ mutate, exit this skill and invoke /cb-green | /cb-fix.',
      '└─────────────────────────────────────────────────────────────────',
      '',
    ].join('\n');
    process.stderr.write(forbiddenBanner);
    process.exit(2);
  }

  const banner = [
    '',
    '┌─ BLOCKED by CS-079 Stage 3 (skill-active-gate) ─────────────────',
    `│ Tool denied: ${toolName}`,
    `│ Reason:      ${why}`,
    `│ Skill state: ${state}${activeSkill ? ` (${activeSkill})` : ''}`,
    '│',
    '│ Per CLAUDE.md inviolable rule #1, file mutation, git mutating',
    '│ commands, ril apply-batch, install/uninstall, and silk mutating',
    '│ commands require an active /cb-green | /cb-fix',
    '│ invocation. /cb-audit is read-only and does not authorise',
    '│ mutation.',
    '│',
    '│ Action: ask the user to invoke /cb-green (or /cb-fix)',
    '│ for this change. Do NOT retry the same tool call.',
    '└─────────────────────────────────────────────────────────────────',
    '',
  ].join('\n');
  process.stderr.write(banner);
  process.exit(2);
}

main().catch((err) => {
  // Fail open on internal hook errors — the LLM-side rule + the
  // reminder hook are still active. Log to stderr but do not block.
  process.stderr.write(`[skill-active-gate hook error: ${err?.message || err}]\n`);
  process.exit(0);
});
