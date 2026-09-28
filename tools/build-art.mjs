#!/usr/bin/env node
// Prepare the library artwork named in contracts/artwork.json into web/party/art/:
//
//   lan:<slug>     -> art/lan-<slug>.svg      the title's own GameArt scene, exported by the games
//                                             repository (ops/export_game_art.mjs) into
//                                             assets/vendor/lan-games-art/; copied verbatim
//   kenney:<icon>  -> art/kenney-<icon>.svg   a vendored, unmodified Kenney Board Game Icon (CC0),
//                                             given a viewBox and an Avrana lavender fill
//
//   npm run build:art            (part of npm run build:ui)
//   node tools/build-art.mjs --check
//
// Development-time only; the output is committed, precached and served locally.
import { mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const vendor = path.join(root, 'assets', 'vendor');
const outDir = path.join(root, 'web', 'party', 'art');
const REF = /^(lan|kenney):([A-Za-z0-9_]{1,40})$/;
const KENNEY_FILL = '#cdbff2';   // Avrana lavender on the tile; Kenney art is single-colour

/** Kenney's vector icons are single-colour paths on a 64 x 64 canvas centred on 0,0. */
export function prepareKenney(svg) {
  const paths = [...svg.matchAll(/<path\b[^>]*\sd="([^"]+)"[^>]*\/?>/g)].map((m) => m[1]);
  if (!paths.length) throw new Error('no paths');
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="-40 -40 80 80" fill="${KENNEY_FILL}">`
    + paths.map((d) => `<path d="${d}"/>`).join('') + '</svg>\n';
}

export function outputName(ref) {
  const [, source, name] = REF.exec(ref) || [];
  if (!source) throw new Error(`bad artwork reference ${ref}`);
  return `${source}-${name}.svg`;
}

export function wanted() {
  const doc = JSON.parse(readFileSync(path.join(root, 'contracts', 'artwork.json'), 'utf8'));
  const files = new Map();
  for (const ref of new Set(Object.values(doc.games))) {
    const [, source, name] = REF.exec(ref) || [];
    if (!source) throw new Error(`bad artwork reference ${ref}`);
    const svg = source === 'lan'
      ? readFileSync(path.join(vendor, 'lan-games-art', name + '.svg'), 'utf8')
      : prepareKenney(readFileSync(path.join(vendor, 'kenney-board-game-icons', name + '.svg'), 'utf8'));
    files.set(outputName(ref), svg);
  }
  return new Map([...files].sort());
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
    console.log(`art: ${files.size} files, ${[...files.values()].reduce((n, s) => n + s.length, 0)} bytes`);
  }
}
