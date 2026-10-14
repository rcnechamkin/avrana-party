// AVR-425: npm run check:ui fails when a copy of the ground colour outside the stylesheet drifts.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { GROUND_COPIES, groundColourDrift } from '../../tools/check-ui.mjs';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const real = (rel) => readFileSync(path.join(root, rel), 'utf8');

test('the committed copies agree with --color-base-100', () => {
  assert.deepEqual(groundColourDrift(real), []);
});

for (const file of GROUND_COPIES) {
  test(`a planted wrong colour in ${file} is caught`, () => {
    const planted = (rel) => (rel === file ? real(rel).replaceAll('#0d0d0f', '#0d0d10') : real(rel));
    const found = groundColourDrift(planted);
    assert.ok(found.length >= 1 && found.every((m) => m.startsWith(`${file}:`)), found.join('\n'));
  });
}

test('a missing theme-color is caught', () => {
  const file = 'web/party/doorway/index.html';
  const planted = (rel) => (rel === file ? real(rel).replace(/<meta\s+name="theme-color"[^>]*>/, '') : real(rel));
  assert.match(groundColourDrift(planted).join('\n'), /doorway\/index\.html: theme-color is missing/);
});

test('a changed ground colour with stale copies is caught everywhere', () => {
  const planted = (rel) => (rel === 'web/src/party.css' ? real(rel).replace('--color-base-100: #0d0d0f', '--color-base-100: #101012') : real(rel));
  assert.equal(groundColourDrift(planted).length, 5);
});
