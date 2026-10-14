#!/usr/bin/env node
// Fail when committed generated UI assets no longer match their sources (npm run check:ui; CI).
//
//   web/src/party.css      -> web/party/styles.css   (Tailwind CSS 4 + daisyUI 5)
//   tools/build-icons.mjs  -> web/party/lib/icons.js (Lucide subset)
//   tools/build-avatars.mjs -> web/party/avatars/gaze-NN.svg (DiceBear Gaze, Night Shift)
//   tools/build-art.mjs    -> web/party/art/*.svg (curated Kenney library artwork)
//
// Nothing in the working tree is written: the CSS is compiled into a temporary file and compared
// byte for byte, and the icon generator runs in its --check mode.
//
// It also fails when a copy of the ground colour outside the stylesheet (a page's theme-color, the
// web manifest's colours) differs from --color-base-100 in web/src/party.css (AVR-425).
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');

/** Files outside the stylesheet that repeat the ground colour, relative to the repository root. */
export const GROUND_COPIES = ['web/party/index.html', 'web/party/diag/index.html', 'web/party/doorway/index.html',
  'web/party/manifest.json'];

/** Every copy of the ground colour that differs from --color-base-100, as messages (empty: all agree).
 * `read(relativePath)` returns a file's text. */
export function groundColourDrift(read) {
  const m = /--color-base-100:\s*(#[0-9a-fA-F]{3,8})\s*;/.exec(read('web/src/party.css'));
  if (!m) return ['web/src/party.css: no --color-base-100'];
  const ground = m[1].toLowerCase();
  const found = [];
  for (const file of GROUND_COPIES) {
    const text = read(file);
    const copies = [];
    if (file.endsWith('.json')) {
      const doc = JSON.parse(text);
      for (const key of ['background_color', 'theme_color']) copies.push([key, doc[key]]);
    } else {
      const meta = /<meta\s+name="theme-color"\s+content="([^"]*)"/.exec(text);
      copies.push(['theme-color', meta ? meta[1] : undefined]);
    }
    for (const [what, value] of copies) {
      if (typeof value !== 'string' || value.toLowerCase() !== ground) {
        found.push(`${file}: ${what} is ${value === undefined ? 'missing' : value}, not --color-base-100 ${ground}`);
      }
    }
  }
  return found;
}

function main() {
  let failed = false;

  const drift = groundColourDrift((rel) => readFileSync(path.join(root, rel), 'utf8'));
  for (const line of drift) console.error(line);
  if (drift.length) failed = true;
  else console.log('ground colour copies match --color-base-100');

  for (const tool of ['build-icons.mjs', 'build-avatars.mjs', 'build-art.mjs']) {
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
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) main();
