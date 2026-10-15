// Tier 1 (node --test): EXPERIMENTAL (AVR-469) device requirements, decided before Play.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createDeviceChecker, decide, deviceRequirements, probeDevice } from '../../web/party/lib/device-check.js';

const JARGON = /\b(seat|session|runtime|server|websocket|presence|manifest|launch(ing)?|backend|token|slot|capabilit(y|ies)|provider|webrtc|h\.?264|codec)\b/i;
const MB = 1024 * 1024;

const game = (caps, extra = {}) => ({
  presentations: [{ id: 'phone', available: true, roles: ['player', 'spectator'], requires: { device: [], ...(caps ? { device_caps: caps } : {}) }, ...extra }],
});

test('a game that declares nothing has no requirements, and false means not required', () => {
  assert.equal(deviceRequirements(game(null), 'phone'), null);
  assert.equal(deviceRequirements({ presentations: [] }, 'phone'), null);
  assert.equal(deviceRequirements(game({ opfs: false }), 'phone'), null);
  assert.deepEqual(deviceRequirements(game({ memory_mb: 384, opfs: true }), 'phone'), { memory_mb: 384, opfs: true });
});

test('requirements come from the presentation the phone is given', () => {
  const g = { presentations: [
    { id: 'a', available: true, roles: ['player'], requires: { device: [], device_caps: { memory_mb: 900 } } },
    { id: 'b', available: true, roles: ['player'], requires: { device: [], device_caps: { memory_mb: 100 } } },
  ] };
  assert.deepEqual(deviceRequirements(g, 'b'), { memory_mb: 100 });
  assert.deepEqual(deviceRequirements(g, undefined), { memory_mb: 900 });
});

const cases = [
  ['every check passes', { memory_mb: { status: 'pass' }, opfs: { status: 'pass' } }, true, ''],
  ['a failing check blocks Play and names itself', { memory_mb: { status: 'pass' }, storage_mb: { status: 'fail' } }, false, 'free storage|storage for this game'],
  ['unknown does not block, and is shown', { memory_mb: { status: 'unknown' }, opfs: { status: 'pass' } }, true, 'Could not check'],
  ['a missing answer is unknown, never a pass', {}, true, 'Could not check'],
  ['a strange status is unknown, never a pass', { memory_mb: { status: 'ok' } }, true, 'Could not check'],
  ['one failure outweighs unknowns', { memory_mb: { status: 'unknown' }, storage_mb: { status: 'fail' } }, false, 'storage'],
];
for (const [name, results, play, words] of cases) {
  test(`decide: ${name}`, () => {
    const requires = { memory_mb: 384, opfs: true, storage_mb: 2000 };
    const asked = Object.fromEntries(Object.keys(results).map((k) => [k, requires[k]]));
    const d = decide(Object.keys(asked).length ? asked : { memory_mb: 384 }, results);
    assert.equal(d.play, play);
    if (words) assert.match(d.why, new RegExp(words)); else assert.equal(d.why, '');
    if (!play) assert.match(d.why, /watch/i);
    assert.doesNotMatch(d.why, JARGON);
  });
}

test('shared_memory is "checked by the game", not a pass and not a fail', () => {
  const d = decide({ shared_memory: true, memory_mb: 100 }, { shared_memory: { status: 'launch' }, memory_mb: { status: 'pass' } });
  assert.equal(d.play, true);
  assert.match(d.why, /shared memory/);
  assert.match(d.why, /when it starts/);
  assert.equal(d.checks.find((c) => c.key === 'shared_memory').status, 'launch');
});

test('probe: shared_memory is never proven on Party Home, even when the page claims isolation', async () => {
  const r = await probeDevice({ shared_memory: true }, { crossOriginIsolated: true, SharedArrayBuffer });
  assert.equal(r.shared_memory.status, 'launch');
});

const fakeMemory = (limitPages) => ({
  Memory: class { constructor({ initial }) { if (initial > limitPages) throw new RangeError('could not allocate memory'); this.buffer = { byteLength: initial * 65536 }; } },
});

test('probe: memory is a real allocation; refusal fails, other errors are unknown', async () => {
  assert.equal((await probeDevice({ memory_mb: 100 }, { WebAssembly: fakeMemory(2000) })).memory_mb.status, 'pass');
  assert.equal((await probeDevice({ memory_mb: 100 }, { WebAssembly: fakeMemory(10) })).memory_mb.status, 'fail');
  const odd = { Memory: class { constructor() { throw new TypeError('weird'); } } };
  assert.equal((await probeDevice({ memory_mb: 100 }, { WebAssembly: odd })).memory_mb.status, 'unknown');
  assert.equal((await probeDevice({ memory_mb: 100 }, {})).memory_mb.status, 'fail');
});

test('probe: storage compares free space; a missing or throwing estimate is unknown', async () => {
  const nav = (estimate) => ({ navigator: { storage: { estimate } } });
  assert.equal((await probeDevice({ storage_mb: 500 }, nav(async () => ({ quota: 1000 * MB, usage: 100 * MB })))).storage_mb.status, 'pass');
  assert.equal((await probeDevice({ storage_mb: 500 }, nav(async () => ({ quota: 1000 * MB, usage: 700 * MB })))).storage_mb.status, 'fail');
  assert.equal((await probeDevice({ storage_mb: 500 }, nav(async () => { throw new Error('no'); }))).storage_mb.status, 'unknown');
  assert.equal((await probeDevice({ storage_mb: 500 }, { navigator: { storage: {} } })).storage_mb.status, 'unknown');
  assert.equal((await probeDevice({ storage_mb: 500 }, nav(async () => ({})))).storage_mb.status, 'unknown');
});

test('probe: OPFS present passes, absent fails, a throw is unknown', async () => {
  assert.equal((await probeDevice({ opfs: true }, { navigator: { storage: { getDirectory: async () => ({}) } } })).opfs.status, 'pass');
  assert.equal((await probeDevice({ opfs: true }, { navigator: { storage: {} } })).opfs.status, 'fail');
  assert.equal((await probeDevice({ opfs: true }, { navigator: { storage: { getDirectory: async () => { throw new Error('private'); } } } })).opfs.status, 'unknown');
});

test('probe: WebGL 2 on the main thread and in a Worker', async () => {
  const canvas = (gl) => class { getContext() { return gl; } };
  assert.equal((await probeDevice({ webgl2_offscreen: 'main' }, { OffscreenCanvas: canvas({}) })).webgl2_offscreen.status, 'pass');
  assert.equal((await probeDevice({ webgl2_offscreen: 'main' }, { OffscreenCanvas: canvas(null) })).webgl2_offscreen.status, 'fail');
  assert.equal((await probeDevice({ webgl2_offscreen: 'main' }, {})).webgl2_offscreen.status, 'fail');
  const worker = (behave) => class { constructor() { setTimeout(() => behave(this), 0); } terminate() { this.ended = true; } };
  const say = (data) => (w) => w.onmessage({ data });
  assert.equal((await probeDevice({ webgl2_offscreen: 'worker' }, { Worker: worker(say({ ok: true, detail: 'x' })) })).webgl2_offscreen.status, 'pass');
  assert.equal((await probeDevice({ webgl2_offscreen: 'worker' }, { Worker: worker(say({ ok: false, detail: 'no' })) })).webgl2_offscreen.status, 'fail');
  assert.equal((await probeDevice({ webgl2_offscreen: 'worker' }, { Worker: worker((w) => w.onerror({})) })).webgl2_offscreen.status, 'unknown');
  assert.equal((await probeDevice({ webgl2_offscreen: 'worker' }, { Worker: worker(() => {}) }, { timeoutMs: 20 })).webgl2_offscreen.status, 'unknown');
  assert.equal((await probeDevice({ webgl2_offscreen: 'worker' }, { Worker: class { constructor() { throw new Error('blocked'); } } })).webgl2_offscreen.status, 'unknown');
});

test('the checker probes once per set of needs, keeps the answer, and a crashing probe is unknown', async () => {
  let calls = 0;
  const checker = createDeviceChecker({ probe: async () => { calls += 1; return { storage_mb: { status: 'fail' } }; } });
  const req = { storage_mb: 99999 };
  assert.equal(checker.peek(req), null);
  const [a, b] = await Promise.all([checker.check(req), checker.check(req)]);
  assert.equal(a.play, false);
  assert.equal(b, a);
  assert.equal(checker.peek(req), a);
  await checker.check(req);
  assert.equal(calls, 1);
  const crashing = createDeviceChecker({ probe: async () => { throw new Error('boom'); } });
  const d = await crashing.check({ memory_mb: 5 });
  assert.equal(d.play, true);
  assert.equal(d.checks[0].status, 'unknown');
});

test('a check that never settles is unknown within its limit, and cannot hold Play', async () => {
  const never = new Promise(() => {});
  const stuck = { navigator: { storage: { getDirectory: () => never, estimate: () => never } } };
  const r = await probeDevice({ opfs: true, storage_mb: 10 }, stuck, { timeoutMs: 20 });
  assert.equal(r.opfs.status, 'unknown');
  assert.equal(r.storage_mb.status, 'unknown');
  const hung = createDeviceChecker({ probe: () => never, totalMs: 20 });
  const d = await hung.check({ opfs: true });
  assert.equal(d.play, true);
  assert.equal(d.checks[0].status, 'unknown');
});

test('a memory pass says reserved, not allocated', async () => {
  const fake = { Memory: class { constructor({ initial }) { this.buffer = { byteLength: initial * 65536 }; } } };
  assert.match((await probeDevice({ memory_mb: 10 }, { WebAssembly: fake })).memory_mb.detail, /reserved/);
});
