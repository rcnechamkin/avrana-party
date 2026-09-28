#!/usr/bin/env node
// Generate the Avrana player avatars: 32 DiceBear "Gaze" SVGs with the official "Night Shift"
// preset, written to web/party/avatars/gaze-NN.svg.
//
//   npm run build:avatars            (part of npm run build:ui)
//   node tools/build-avatars.mjs --check
//
// Development-time only: the Pi and phones never run DiceBear and never call its HTTP API; the
// generated files are committed, precached and served locally. docs/UI-DESIGN-SYSTEM.md, "Player
// avatars", explains the choice and how to reproduce it.
//
// Reproducibility: the preset, seed prefix, count and selection rule below fully determine the set
// for a given @dicebear/core + @dicebear/styles version (both pinned in package-lock.json).
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Avatar, Style } from '@dicebear/core';
import definition from '@dicebear/styles/gaze.json' with { type: 'json' };

// DiceBear Gaze preset "Night Shift" ("For dark interfaces"), verbatim from
// https://www.dicebear.com/styles/gaze/presets (2026-09-27): only the ground is set; every other
// option keeps varying with the seed.
export const PRESET = Object.freeze({ backgroundColor: ['16161a'] });
export const COUNT = 32;
const SEED_PREFIX = 'avrana-gaze-';
// A curated roster, chosen deterministically: walk seeds 1, 2, 3, ... and keep a candidate only if
// it adds a new shape + body colour pair without over-using a shape, colour or eye style.
const LIMITS = { shape: 3, color: 6, eyes: 4 };

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const outDir = path.join(root, 'web', 'party', 'avatars');
export const avatarId = (i) => `gaze-${String(i + 1).padStart(2, '0')}`;

export function roster() {
  const style = new Style(definition);
  const pairs = new Set();
  const used = { shape: new Map(), color: new Map(), eyes: new Map() };
  const picked = [];
  for (let n = 1; picked.length < COUNT; n++) {
    if (n > 5000) throw new Error('could not find enough distinct avatars');
    const seed = SEED_PREFIX + n;
    const avatar = new Avatar(style, { seed, ...PRESET });
    const o = avatar.toJSON().options;
    const look = { shape: o.shapeVariant, color: o.bodyColor[0], eyes: o.eyesVariant };
    const pair = look.shape + '|' + look.color;
    if (pairs.has(pair) || Object.entries(LIMITS).some(([k, max]) => (used[k].get(look[k]) || 0) >= max)) continue;
    pairs.add(pair);
    for (const k of Object.keys(LIMITS)) used[k].set(look[k], (used[k].get(look[k]) || 0) + 1);
    picked.push({ id: avatarId(picked.length), seed, look, svg: avatar.toString() + '\n' });
  }
  return picked;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  const set = roster();
  if (process.argv.includes('--check')) {
    const stale = set.filter(({ id, svg }) => {
      try { return readFileSync(path.join(outDir, id + '.svg'), 'utf8') !== svg; } catch { return true; }
    });
    const extra = readdirSync(outDir).filter((f) => !set.some(({ id }) => f === id + '.svg'));
    if (stale.length || extra.length) {
      console.error(`web/party/avatars is stale (${[...stale.map((s) => s.id), ...extra].join(', ')}): run npm run build:avatars and commit it`);
      process.exit(1);
    }
    console.log('avatars are current');
  } else {
    mkdirSync(outDir, { recursive: true });
    for (const { id, svg } of set) writeFileSync(path.join(outDir, id + '.svg'), svg);
    const bytes = set.reduce((sum, { svg }) => sum + svg.length, 0);
    console.log(`avatars: ${set.length} Gaze (Night Shift), ${bytes} bytes`);
    for (const { id, seed, look } of set) console.log(`  ${id}  ${seed.padEnd(18)} ${look.shape} ${look.color} ${look.eyes}`);
  }
}
