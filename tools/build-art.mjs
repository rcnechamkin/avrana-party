#!/usr/bin/env node
// Prepare the curated library artwork: contracts/artwork.json names icons from the vendored,
// unmodified Kenney originals in assets/vendor/kenney-board-game-icons/; each is written to
// web/party/art/<name>.svg with a viewBox and currentColor fill (so a tile can tint it) and
// nothing else changed.
//
//   npm run build:art            (part of npm run build:ui)
//   node tools/build-art.mjs --check
//
// Development-time only; the output is committed, precached and served locally.
import { mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const vendor = path.join(root, 'assets', 'vendor', 'kenney-board-game-icons');
const outDir = path.join(root, 'web', 'party', 'art');
const NAME = /^[A-Za-z0-9_]{1,40}$/;

/** Kenney's vector icons are single-colour paths on a 64 x 64 canvas centred on 0,0. */
export function prepare(svg) {
  const paths = [...svg.matchAll(/<path\b[^>]*\sd="([^"]+)"[^>]*\/?>/g)].map((m) => m[1]);
  if (!paths.length) throw new Error('no paths');
  return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="-32 -32 64 64" fill="currentColor">'
    + paths.map((d) => `<path d="${d}"/>`).join('') + '</svg>\n';
}

export function wanted() {
  const doc = JSON.parse(readFileSync(path.join(root, 'contracts', 'artwork.json'), 'utf8'));
  const names = [...new Set(Object.values(doc.games))].sort();
  for (const name of names) if (!NAME.test(name)) throw new Error(`bad artwork name ${name}`);
  return new Map(names.map((name) => [name + '.svg', prepare(readFileSync(path.join(vendor, name + '.svg'), 'utf8'))]));
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  const files = wanted();
  if (process.argv.includes('--check')) {
    let present = [];
    try { present = readdirSync(outDir); } catch { /* missing counts as stale */ }
    const stale = [...files].filter(([f, svg]) => {
      try { return readFileSync(path.join(outDir, f), 'utf8') !== svg; } catch { return true; }
    }).map(([f]) => f).concat(present.filter((f) => !files.has(f)));
    if (stale.length) {
      console.error(`web/party/art is stale (${stale.join(', ')}): run npm run build:art and commit it`);
      process.exit(1);
    }
    console.log('art is current');
  } else {
    rmSync(outDir, { recursive: true, force: true });
    mkdirSync(outDir, { recursive: true });
    for (const [f, svg] of files) writeFileSync(path.join(outDir, f), svg);
    console.log(`art: ${files.size} icons, ${[...files.values()].reduce((n, s) => n + s.length, 0)} bytes`);
  }
}
