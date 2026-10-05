#!/usr/bin/env node
// Installs the third-party design skills for Claude Code into this checkout's .claude/
// (project scope, gitignored). The Avrana skill itself is tracked; see docs/agents/design-skills.md.
// Usage: node tools/install-design-skills.mjs [--dry-run]
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const dryRun = process.argv.includes('--dry-run');

// --no-hooks: no detector hook is written to .claude/settings.local.json.
// The UIZZE source offers exactly ui-design, anti-ui-slop and ui-radar; its paid MCP is not connected.
const steps = [
  ['impeccable@4.1.0', 'install', '-y', '--providers=claude', '--scope=project', '--no-hooks'],
  ['skills', 'add', 'https://uizze.com', '--skill', '*', '-a', 'claude-code', '-y'],
  ['skills', 'add', 'vercel-labs/agent-skills', '--skill', 'web-design-guidelines', '-a', 'claude-code', '-y'],
  ['skills', 'add', 'anthropics/skills', '--skill', 'frontend-design', '-a', 'claude-code', '-y'],
];
const expected = ['impeccable', 'ui-design', 'anti-ui-slop', 'ui-radar', 'web-design-guidelines',
  'frontend-design', 'avrana-ux-ui'];

const quote = (arg) => (/[*\s]/.test(arg) ? `"${arg}"` : arg);
for (const step of steps) {
  const command = ['npx', '-y', ...step.map(quote)].join(' ');
  console.log(`> ${command}`);
  if (dryRun) continue;
  const result = spawnSync(command, {
    cwd: root, stdio: 'inherit', shell: true,
    env: { ...process.env, DISABLE_TELEMETRY: '1', DO_NOT_TRACK: '1' },
  });
  if (result.status !== 0) {
    console.error(`design skills: step failed (${result.status ?? result.error})`);
    process.exit(1);
  }
}

const missing = expected.filter((name) => !existsSync(join(root, '.claude', 'skills', name, 'SKILL.md')));
if (missing.length && !dryRun) {
  console.error(`design skills: missing ${missing.join(', ')}`);
  process.exit(1);
}
console.log(dryRun ? 'design skills: dry run only' : `design skills: OK (${expected.join(', ')})`);
