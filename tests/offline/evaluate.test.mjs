// Tier 1 (node --test): browser seat evaluation against the vectors shared with Python.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { evaluateSeat, explain } from '../../web/party/lib/evaluate.js';

const vectors = JSON.parse(readFileSync(new URL('../../contracts/vectors/evaluate.v0.json', import.meta.url)));
const catalog = JSON.parse(readFileSync(new URL('../../web/party/catalog.json', import.meta.url)));
// Party Home's banned words (experiments/party-service/party.spec.ts) plus engine terms.
const JARGON = /\b(seat|session|runtime|server|websocket|presence|manifest|launch(ing)?|backend|token|slot|capabilit(y|ies)|provider|webrtc|h\.?264|codec)\b/i;

for (const c of vectors.cases) {
  test(`vector: ${c.name}`, () => {
    assert.deepEqual(evaluateSeat(vectors.games[c.game], c.caps, c.role), c.expect);
  });
}

test('role must be player or spectator', () => {
  assert.throws(() => evaluateSeat(vectors.games.table, {}, 'host'));
});

test('guest explanations never use machinery words and are empty when ready', () => {
  const labels = catalog.labels;
  for (const c of vectors.cases) {
    const result = evaluateSeat(vectors.games[c.game], c.caps, c.role);
    const text = explain(result, labels);
    if (result.outcome === 'ready') assert.equal(text, '');
    else assert.ok(text.length > 0, c.name);
    assert.doesNotMatch(text, JARGON, c.name);
  }
});

test('the real catalog: every game evaluates for every role without throwing', () => {
  const caps = { websocket: 'yes', webrtc: 'yes', 'video.h264': 'yes' };
  for (const game of catalog.games) {
    for (const role of ['player', 'spectator']) {
      const r = evaluateSeat(game, caps, role);
      assert.ok(['ready', 'limited', 'watch', 'unavailable'].includes(r.outcome), game.id);
    }
  }
});
