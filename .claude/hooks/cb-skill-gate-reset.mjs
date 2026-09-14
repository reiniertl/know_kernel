/**
 * INV-GATE-MARKER-CLEARED-ON-SKILL-ENTRY
 *
 * UserPromptSubmit hook that clears stale gate markers and writes a
 * fresh one with the detected skill name before any /cb-* skill
 * begins. Runs before cb-green-triage-dispatch.mjs.
 * Never blocks (exit 0 always).
 */

import { unlinkSync, writeFileSync, mkdirSync, renameSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';

const userMessage = process.env.USER_PROMPT ?? '';
const match = userMessage.match(/^\/cb-(green|fix|brown|audit|ops|free)\b/);

if (match) {
  const skill = `cb-${match[1]}`;
  const markerPath = join(process.cwd(), '.combobul', 'cache', 'silk', 'gate-marker.json');

  if (existsSync(markerPath)) {
    try {
      unlinkSync(markerPath);
    } catch { /* best-effort */ }
  }

  try {
    mkdirSync(dirname(markerPath), { recursive: true });
    const marker = JSON.stringify({
      skill,
      kind: 'NONE',
      runId: '',
      setAt: new Date().toISOString(),
    }, null, 2);
    const tmp = `${markerPath}.tmp.${process.pid}`;
    writeFileSync(tmp, marker, 'utf8');
    renameSync(tmp, markerPath);
  } catch { /* best-effort — silk gate-mark init will overwrite later */ }
}
