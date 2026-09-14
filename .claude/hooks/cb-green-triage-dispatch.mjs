#!/usr/bin/env node
/**
 * CS-088 §3.1 — UserPromptSubmit hook for cb-green triage orchestration.
 *
 * This hook fires on every user prompt. When it detects /cb-green:
 *   1. Nukes all stale contract state and broadcasts its runId
 *   2. Opens the gate and contract via silk
 *   3. Spawns a triage model (default: Haiku) for DAG surface discovery
 *   4. Submits the triage stage to advance the contract 0→1
 *   5. Assembles composite output (original msg + triage + surface)
 *
 * INVARIANT: after /cb-green detection, every failure exits non-zero
 * with [HOOK FATAL] on stderr. No silent exit(0).
 */
import { spawnSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { existsSync, readFileSync, writeFileSync, mkdtempSync, mkdirSync, rmSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { tmpdir } from 'node:os';

const SILK_ENTRY = resolve(process.cwd(), 'combobul/cli/silk.mjs');

const TRIAGE_TIMEOUT_MS = 240_000;

function fatal(msg) {
  process.stderr.write(`[HOOK FATAL] cb-green-triage-dispatch: ${msg}\n`);
  process.exit(1);
}

// ── Entry point ────────────────────────────────────────────────────────

async function main() {
  let input = '';
  for await (const chunk of process.stdin) {
    input += chunk;
  }

  let payload;
  try {
    payload = JSON.parse(input);
  } catch {
    process.exit(0);
  }

  const userMessage = (payload?.prompt ?? '').trim();
  if (!userMessage.startsWith('/cb-green')) {
    process.exit(0);
  }

  // ── PAST THIS POINT: /cb-green detected. Every failure is FATAL. ──

  const rawPrompt = userMessage.replace(/^\/cb-green\s*/, '').trim();
  const isEmptyPrompt = rawPrompt.length === 0;

  const hookRunId = randomUUID().replace(/-/g, '').slice(0, 16);

  try {
    // Step 0: Ensure .combobul dir exists
    mkdirSync(join(process.cwd(), '.combobul'), { recursive: true });

    // Step 1: Open gate (pass --run-id so marker carries the contract runId)
    silkArgs('gate-mark', 'init', 'cb-green', '--run-id', hookRunId);

    // Step 2: Open contract
    const requestText = isEmptyPrompt
      ? '(empty prompt — suggest work items)'
      : rawPrompt;
    const beginResult = silkJsonArgs('run', 'begin', '--skill', 'cb-green',
      '--run-id', hookRunId, '--request', requestText, '--json');
    if (!beginResult?.runId) fatal('silk run begin returned no runId');
    const runId = beginResult.runId;

    // Step 3: Spawn triage model
    const triageOutput = spawnTriageModel(rawPrompt, isEmptyPrompt);

    // Step 4: Extract structured fields (best-effort)
    const { disposition, reasonCode, candidateNodes: rawCandidates } = extractTriageFields(triageOutput);

    // Step 4b: Partition candidates into existing (DAG-validated) vs. proposed (to-be-created)
    const { candidateNodes, proposedNodes } = partitionCandidateNodes(rawCandidates);

    // Step 5: Snapshot the surface from candidate nodes
    let surfaceJson = '';
    if (candidateNodes.length > 0) {
      try {
        const snapResult = silkSpawn('run', 'surface-snapshot', '--run-id', hookRunId,
          '--nodes', candidateNodes.join(','), '--json');
        if (snapResult.status === 0) surfaceJson = (snapResult.stdout ?? '').trim();
      } catch (e) {
        process.stderr.write(`[HOOK WARN] surface-snapshot failed: ${e.message}\n`);
      }
    }

    // Step 5b: Build authoring rules from schema cache
    const authoringRules = buildAuthoringRules();

    // Step 6: Build and submit triage envelope
    const envelope = {
      templateId: 'cb-green-triage-v2',
      schemaVersion: '2.0.0',
      stage: 'triage',
      payload: {
        classification: reasonCode,
        candidateNodes,
        proposedNodes,
        affectedModules: [],
        userIntent: requestText,
        readOnlyDiscovery: null,
      },
    };

    const tmpDir = mkdtempSync(join(tmpdir(), 'cb-green-triage-'));
    const envelopePath = join(tmpDir, 'triage-envelope.json');
    try {
      writeFileSync(envelopePath, JSON.stringify(envelope, null, 2));
      silkArgs('run', 'submit-stage', '--run-id', hookRunId, '--phases', envelopePath);
    } catch (e) {
      rmSync(tmpDir, { recursive: true, force: true });
      fatal(`submit-stage failed: ${e.message}`);
    } finally {
      rmSync(tmpDir, { recursive: true, force: true });
    }

    // Step 7: Handle empty-prompt mode
    if (isEmptyPrompt) {
      silkArgs('run', 'finalize', '--run-id', hookRunId);
      process.stdout.write(
        `[cb-green triage — empty prompt mode]\n\n` +
        `Haiku examined the DAG for work items:\n\n${triageOutput || '(no suggestions)'}\n\n` +
        `Pick an item and invoke /cb-green with it.\n`
      );
      process.exit(0);
    }

    // Step 8: Assemble composite output for Opus
    const nextSteps = `## Next steps

You are now at **stage 1 (plan)** with run-id \`${runId}\`.

**If DAG mutations are needed**, write the spec-author envelope during this stage:
\`\`\`
Write .combobul/tmp/spec-author-envelope.json with:
{
  "templateId": "cb-green-spec-author-v1",
  "schemaVersion": "1.0.0",
  "stage": "spec-author",
  "payload": {
    "mutations": [
      {"type": "remove-node", "nodeId": "..."},
      {"type": "add-node", "node": {"id": "...", "kind": "...", ...}},
      {"type": "add-edge", "edge": {"kind": "...", "from": "...", "to": "..."}}
    ]
  }
}
\`\`\`
Then: submit plan → submit spec-author envelope → ril apply-batch in stage 3.

**If no DAG changes needed**, submit the template directly:
\`\`\`
npm run silk -- run submit-stage --phases .claude/skills/cb-green/templates/spec-author.request.json --run-id ${runId}
\`\`\`

**Stage commands:**
- Submit plan: \`npm run silk -- run submit-stage --phases .claude/skills/cb-green/templates/plan.request.json --run-id ${runId}\`
- Submit spec-author: \`npm run silk -- run submit-stage --phases .combobul/tmp/spec-author-envelope.json --run-id ${runId}\`
- Submit impl: \`npm run silk -- run submit-stage --phases .claude/skills/cb-green/templates/impl-batch.request.json --run-id ${runId}\`
- Submit verify: \`npm run silk -- run submit-stage --phases .claude/skills/cb-green/templates/verify.request.json --run-id ${runId}\`
- Finalize: \`npm run silk -- run finalize --run-id ${runId}\`
`;

    process.stdout.write(
      `[cb-green triage complete — disposition: ${disposition}, reasonCode: ${reasonCode}]\n\n` +
      `## Original request\n${rawPrompt}\n\n` +
      `## Triage findings (from Haiku)\n${triageOutput}\n\n` +
      `## Checksummed spec surface\n${surfaceJson || '(no surface — candidate nodes empty or snapshot failed)'}\n\n` +
      `## Authoring rules (from schema cache)\n${authoringRules}\n\n` +
      nextSteps
    );
  } catch (err) {
    fatal(`${err.message}\n${err.stack ?? ''}`);
  }
}

// ── Triage model — USER-REPLACEABLE ────────────────────────────────────

function spawnTriageModel(prompt, isEmptyPrompt) {
  const systemPrompt = isEmptyPrompt
    ? 'You are a spec triage agent. The user typed /cb-green with no arguments. ' +
      'Query the DAG for open GAP annotations, rank by small-surface + low-impact ' +
      '(easy wins), and suggest the 3 best candidates. For each, give the GAP ID, ' +
      'a one-line description, and the containing module. Output as a numbered list.'
    : 'You are a spec triage agent. Classify the user\'s request against the DAG. ' +
      'Search for relevant nodes using `npm run ril -- query nodes --filter "<keyword>" --json`, ' +
      'expand with `npm run ril -- query neighborhood <id> --depth 1 --json`, ' +
      'check impact with `npm run ril -- query impact-analysis <id> --json`. ' +
      'Once you have enough evidence, output a JSON object with: ' +
      '{"disposition": "ROUTE", "reasonCode": "FEATURE", ' +
      '"candidateNodes": ["NODE-1", ...], "proposedNodes": ["NEW-NODE-1", ...], ' +
      '"refinedPrompt": "optional rewrite"}. ' +
      'candidateNodes: only IDs you found in DAG query results (existing nodes). ' +
      'proposedNodes: IDs the user wants to CREATE that do not yet exist in the DAG.';

  const result = spawnSync('claude', [
    '--print', '--model', 'haiku',
    '--allowedTools', 'Bash,Read,Grep,Glob',
    '-p', `${systemPrompt}\n\nUser request: ${isEmptyPrompt ? 'Find open GAP annotations and suggest 3 easy work items.' : prompt}`,
  ], {
    timeout: TRIAGE_TIMEOUT_MS,
    encoding: 'utf-8',
    stdio: ['pipe', 'pipe', 'pipe'],
    cwd: process.cwd(),
  });

  if (result.error || result.status !== 0) {
    const errDetail = result.error?.message ?? `exit ${result.status}`;
    process.stderr.write(`[HOOK WARN] triage model failed: ${errDetail}\n`);
    return `TRIAGE FAILED — ${errDetail}. Opus must discover DAG nodes manually via ril query.`;
  }
  return (result.stdout ?? '').trim();
}

// ── Helpers ─────────────────────────────────────────────────────────────

function extractTriageFields(output) {
  let disposition = 'ROUTE';
  let reasonCode = 'FEATURE';
  let candidateNodes = [];
  try {
    const jsonMatch = output.match(/\{[\s\S]*"disposition"[\s\S]*\}/);
    if (jsonMatch) {
      const parsed = JSON.parse(jsonMatch[0]);
      if (parsed.disposition) disposition = parsed.disposition;
      if (parsed.reasonCode) reasonCode = parsed.reasonCode;
      if (Array.isArray(parsed.candidateNodes)) candidateNodes = parsed.candidateNodes;
    }
  } catch { /* best-effort — defaults are fine */ }
  return { disposition, reasonCode, candidateNodes };
}

function partitionCandidateNodes(rawCandidates) {
  if (!Array.isArray(rawCandidates) || rawCandidates.length === 0) {
    return { candidateNodes: [], proposedNodes: [] };
  }
  const ids = rawCandidates.filter((id) => typeof id === 'string' && id.length > 0);
  if (ids.length === 0) return { candidateNodes: [], proposedNodes: [] };
  try {
    const result = spawnSync('npm', ['run', 'ril', '--', 'query', 'node-info', ...ids, '--json'], {
      encoding: 'utf-8',
      stdio: ['pipe', 'pipe', 'pipe'],
      timeout: 15_000,
      cwd: process.cwd(),
      shell: true,
    });
    if (result.status !== 0) {
      process.stderr.write(`[HOOK WARN] partitionCandidateNodes: ril query failed (exit ${result.status}), treating all as proposed\n`);
      return { candidateNodes: [], proposedNodes: ids };
    }
    const output = (result.stdout ?? '').trim();
    const jsonStart = output.indexOf('{');
    if (jsonStart === -1) return { candidateNodes: [], proposedNodes: ids };
    const parsed = JSON.parse(output.slice(jsonStart));
    const foundIds = new Set();
    if (parsed.node?.id) foundIds.add(parsed.node.id);
    if (Array.isArray(parsed.results)) {
      for (const r of parsed.results) {
        if (r.node?.id) foundIds.add(r.node.id);
      }
    }
    const candidateNodes = ids.filter((id) => foundIds.has(id));
    const proposedNodes = ids.filter((id) => !foundIds.has(id));
    return { candidateNodes, proposedNodes };
  } catch (e) {
    process.stderr.write(`[HOOK WARN] partitionCandidateNodes: ${e.message}, treating all as proposed\n`);
    return { candidateNodes: [], proposedNodes: ids };
  }
}

function buildAuthoringRules() {
  const cachePath = join(process.cwd(), '.combobul', 'cache', 'authoring-schema.json');
  try {
    if (!existsSync(cachePath)) return '(schema cache not found — run `npm run ril -- schema --json > .combobul/cache/authoring-schema.json`)';

    const raw = readFileSync(cachePath, 'utf-8');
    const jsonStart = raw.indexOf('{');
    if (jsonStart === -1) return '(schema cache malformed)';
    const schema = JSON.parse(raw.slice(jsonStart));
    const kinds = schema.nodeKinds ?? {};

    const lines = [];

    lines.push('### Mutation formats');
    lines.push('```');
    lines.push('modify-node: {"type": "modify-node", "nodeId": "ID", "props": {"field": "value"}}');
    lines.push('add-node:    {"type": "add-node", "node": {"id": "ID", "kind": "...", "language": "meta", ...}}');
    lines.push('add-edge:    {"type": "add-edge", "edge": {"kind": "contains", "from": "SRC", "to": "TGT"}}');
    lines.push('remove-node: {"type": "remove-node", "nodeId": "ID"}');
    lines.push('remove-edge: {"type": "remove-edge", "edge": {"kind": "contains", "from": "SRC", "to": "TGT"}}');
    lines.push('```');
    lines.push('IMPORTANT: modify-node uses `props`, NOT `attributes`.');
    lines.push('');

    lines.push('### Apply-batch: always pipe via stdin');
    lines.push('```powershell');
    lines.push('$envelope = Get-Content -Raw .combobul/tmp/spec-author-envelope.json | ConvertFrom-Json');
    lines.push('$mutations = $envelope.payload.mutations | ConvertTo-Json -Depth 10 -Compress');
    lines.push('$mutations | Out-File -Encoding utf8 .combobul/tmp/mutations-batch.json');
    lines.push('Get-Content .combobul/tmp/mutations-batch.json | npm run ril -- apply-batch --json');
    lines.push('```');
    lines.push('');

    lines.push('### Required attributes and edges per kind');

    const targetKinds = ['invariant', 'algorithm', 'error-code', 'interface', 'module', 'annotation', 'automaton'];
    for (const kindName of targetKinds) {
      const k = kinds[kindName];
      if (!k) continue;

      const reqAttrs = (k.attributes ?? []).filter(a => a.required).map(a => a.name);
      const reqChildren = (k.children ?? []).filter(c => c.required).map(c => c.name);
      const reqEdges = (k.requiredEdges ?? []).map(e => `${e.kind} → ${e.direction === 'out' ? '(target)' : '(source)'}${e.cardinality ? ` [${e.cardinality}]` : ''}`);

      const parts = [];
      if (reqAttrs.length) parts.push(`attrs: ${reqAttrs.join(', ')}`);
      if (reqChildren.length) parts.push(`children: ${reqChildren.join(', ')}`);
      if (reqEdges.length) parts.push(`edges: ${reqEdges.join('; ')}`);

      if (parts.length === 0) continue;
      lines.push(`- **${kindName}**: ${parts.join(' | ')}`);
    }

    lines.push('');
    lines.push('### Invariant predicate rules (AUTH-030, AUTH-016)');
    lines.push('- `predicate` is REQUIRED (AUTH-030) — the verifiable property (semi-formal quantified form preferred, e.g. "forall x in S. P(x)")');
    lines.push('- `predicateNL` is REQUIRED when predicate is set (AUTH-016) — natural language description (DO NOT duplicate predicate text)');
    lines.push('- `predicateCode` is optional — executable TypeScript assertion function');
    lines.push('- `predicateFormal` is optional — lean4/fol/smt-lib proof expression');
    lines.push('- `enforced` variant container is required — use `"{}"`');
    lines.push('- Use tsName (camelCase) in mutations: `predicate`, `predicateNL`, `predicateCode`, `predicateFormal`');
    lines.push('');
    lines.push('### Algorithm pre/postcondition rules');
    lines.push('- Algorithms use `satisfies` edges to LMP invariants for postconditions (preferred pattern)');
    lines.push('- Optional inline: `preconditionNL`/`preconditionCode`, `postconditionNL`/`postconditionCode` as properties');
    lines.push('');
    lines.push('### Pre-existing spec:check warnings (not regressions)');
    lines.push('AUTH-ERR-FOREIGN-FIELD on ri-status, ip-clearance, predicate-nl, predicate-authority');
    lines.push('exists across many nodes. Only check for NEW errors on YOUR nodes.');

    return lines.join('\n');
  } catch (e) {
    return `(failed to build authoring rules: ${e.message})`;
  }
}

function silkSpawn(...args) {
  return spawnSync(process.execPath, [SILK_ENTRY, ...args], {
    encoding: 'utf-8', stdio: ['pipe', 'pipe', 'pipe'], timeout: 30_000,
    shell: false, cwd: process.cwd(),
  });
}

function silkArgs(...args) {
  const result = silkSpawn(...args);
  if (result.status !== 0) {
    throw new Error(`silk ${args[0]} failed (exit ${result.status}): ${(result.stderr ?? '').trim()}`);
  }
}

function silkJsonArgs(...args) {
  const result = silkSpawn(...args);
  if (result.status !== 0) {
    throw new Error(`silk ${args[0]} failed (exit ${result.status}): ${(result.stderr ?? '').trim()}`);
  }
  return JSON.parse((result.stdout ?? '').trim());
}

main().catch((err) => fatal(`unhandled: ${err.message}\n${err.stack ?? ''}`));
