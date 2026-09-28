#!/usr/bin/env node
// Fail when committed generated UI assets no longer match their sources (npm run check:ui; CI).
//
//   web/src/party.css      -> web/party/styles.css   (Tailwind CSS 4 + daisyUI 5)
//   tools/build-icons.mjs  -> web/party/lib/icons.js (Lucide subset)
//   tools/build-avatars.mjs -> web/party/avatars/gaze-NN.svg (DiceBear Gaze, Night Shift)
//
// Nothing in the working tree is written: the CSS is compiled into a temporary file and compared
// byte for byte, and the icon generator runs in its --check mode.
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
let failed = false;

for (const tool of ['build-icons.mjs', 'build-avatars.mjs']) {
  try {
    execFileSync(process.execPath, [path.join(root, 'tools', tool), '--check'], { stdio: 'inherit' });
  } catch {
    failed = true;
  }
}

const tmp = mkdtempSync(path.join(tmpdir(), 'avrana-ui-'));
try {
  const out = path.join(tmp, 'styles.css');
  const cli = path.join(root, 'node_modules', '@tailwindcss', 'cli', 'dist', 'index.mjs');
  execFileSync(process.execPath, [cli, '-i', path.join(root, 'web', 'src', 'party.css'), '-o', out, '--minify'],
    { cwd: root, stdio: 'pipe' });
  const committed = readFileSync(path.join(root, 'web', 'party', 'styles.css'), 'utf8');
  if (readFileSync(out, 'utf8') !== committed) {
    console.error('web/party/styles.css is stale: run npm run build:css and commit it');
    failed = true;
  } else {
    console.log('styles.css is current');
  }
} finally {
  rmSync(tmp, { recursive: true, force: true });
}

process.exit(failed ? 1 : 0);
