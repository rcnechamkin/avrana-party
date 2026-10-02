#!/usr/bin/env node
// Select the conventional Python executable without changing existing repository scripts.
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const python = process.platform === 'win32' ? 'python' : 'python3';
const result = spawnSync(python, [fileURLToPath(new URL('./repo-check.py', import.meta.url)),
  '--generated', ...process.argv.slice(2)], { stdio: 'inherit' });
if (result.error) console.error(`Could not start ${python}; see docs/TESTING.md`);
process.exit(result.status ?? 1);
