// Tier 1 (node --test): the browser capability probe against fake browser environments.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DEVICE_CAPABILITIES, SCHEMA, probeCapabilities, probeContext, probeSync, statuses }
  from '../../web/party/lib/capabilities.js';

const vocabulary = JSON.parse(readFileSync(new URL('../../contracts/capabilities.v0.json', import.meta.url)));

function canvasDoc(kinds) {
  return {
    visibilityState: 'visible',
    fullscreenEnabled: false,
    createElement: () => ({ getContext: (k) => (kinds.includes(k) ? { getExtension: () => ({ loseContext() {} }) } : null) }),
  };
}

// A modern phone on https://party.avrana.net (every API present).
function phone(over = {}) {
  const store = new Map();
  class PC {}
  PC.prototype.createDataChannel = () => {};
  return {
    isSecureContext: true,
    navigator: {
      serviceWorker: {}, wakeLock: { request: async () => ({}) }, getGamepads: () => [null, { id: 'pad' }],
      vibrate: () => true, mediaDevices: { getUserMedia: () => {} }, maxTouchPoints: 5, onLine: true,
      storage: { persisted: async () => false },
      permissions: { query: async ({ name }) => ({ state: name === 'camera' ? 'denied' : 'prompt' }) },
      gpu: { requestAdapter: async () => ({}) },
    },
    document: canvasDoc(['webgl', 'webgl2']),
    caches: {}, WebSocket: function WebSocket() {}, RTCPeerConnection: PC,
    RTCRtpReceiver: { getCapabilities: () => ({ codecs: [{ mimeType: 'video/VP8' }, { mimeType: 'video/H264' }] }) },
    AudioContext: function AudioContext() {}, crypto: { subtle: {} }, indexedDB: {},
    localStorage: { setItem: (k, v) => store.set(k, v), getItem: (k) => store.get(k) ?? null, removeItem: (k) => store.delete(k) },
    matchMedia: (q) => ({ matches: q.includes('coarse') || q.includes('dark') }),
    innerWidth: 390, innerHeight: 844, devicePixelRatio: 3,
    ...over,
  };
}

test('probe names are exactly the vocabulary', () => {
  assert.deepEqual([...DEVICE_CAPABILITIES].sort(), Object.keys(vocabulary.device).sort());
  assert.deepEqual(Object.keys(probeSync(phone())).sort(), Object.keys(vocabulary.device).sort());
});

test('a capable phone', async () => {
  const report = await probeCapabilities(phone(), { now: () => new Date('2026-09-26T00:00:00Z') });
  assert.equal(report.schema, SCHEMA);
  assert.equal(report.probedAt, '2026-09-26T00:00:00.000Z');
  assert.equal(report.depth, 'quick');
  const s = statuses(report);
  for (const name of ['secure_context', 'service_worker', 'websocket', 'webrtc', 'webrtc.data_channel', 'video.h264',
    'wake_lock', 'web_crypto', 'gamepad', 'storage.local', 'webgl', 'webgl2', 'touch', 'vibration']) {
    assert.equal(s[name], 'yes', name);
  }
  assert.equal(report.caps.gamepad.note, '1 connected');
  assert.equal(s.camera, 'no');                     // denied
  assert.equal(s.microphone, 'unknown');            // 'prompt' is never asked
  assert.equal(s['storage.persistent'], 'no');
  assert.equal(s.webgpu, 'unknown');                // adapter only requested in deep mode
  assert.equal(report.caps.webgpu.via, 'presence');
  assert.equal(report.context.orientation, 'portrait');
  assert.equal(report.context.pointer, 'coarse');
});

test('deep probe asks for a WebGPU adapter', async () => {
  const report = await probeCapabilities(phone({ RTCPeerConnection: undefined }), { deep: true });
  assert.equal(report.depth, 'deep');
  assert.equal(report.caps.webgpu.status, 'yes');
  assert.equal(report.caps.webgpu.via, 'functional');
});

test('plain HTTP: secure-only APIs are absent, not errors', async () => {
  const env = phone({ isSecureContext: false, caches: undefined, crypto: {} });
  delete env.navigator.serviceWorker;
  delete env.navigator.wakeLock;
  const s = statuses(await probeCapabilities(env));
  assert.equal(s.secure_context, 'no');
  assert.equal(s.service_worker, 'no');
  assert.equal(s.cache_storage, 'no');
  assert.equal(s.wake_lock, 'no');
  assert.equal(s.web_crypto, 'no');
});

test('an iPhone-like browser: no vibration, no element fullscreen, no H.264 list yet', () => {
  const env = phone({ RTCRtpReceiver: undefined });
  delete env.navigator.vibrate;
  const caps = probeSync(env);
  assert.equal(caps.vibration.status, 'no');
  assert.equal(caps.fullscreen.status, 'no');
  assert.equal(caps['video.h264'].status, 'unknown');   // RTCPeerConnection exists: not observed, not "no"
});

test('throwing APIs become unknown and never break the probe', async () => {
  const env = phone({
    RTCRtpReceiver: { getCapabilities: () => { throw new TypeError('boom'); } },
    localStorage: { setItem: () => { throw Object.assign(new Error('full'), { name: 'QuotaExceededError' }); } },
  });
  env.navigator.permissions = { query: async () => { throw new TypeError('unsupported name'); } };
  env.navigator.getGamepads = () => { throw new Error('policy'); };
  const report = await probeCapabilities(env);
  assert.equal(report.caps['video.h264'].status, 'unknown');
  assert.match(report.caps['video.h264'].note, /TypeError/);
  assert.equal(report.caps['storage.local'].status, 'no');
  assert.match(report.caps['storage.local'].note, /QuotaExceededError/);
  assert.equal(report.caps.microphone.status, 'unknown');
  assert.equal(report.caps.gamepad.status, 'yes');
});

test('an empty environment still yields a complete report', async () => {
  const report = await probeCapabilities({});
  assert.equal(Object.keys(report.caps).length, DEVICE_CAPABILITIES.length);
  for (const entry of Object.values(report.caps)) assert.ok(['yes', 'no', 'unknown', 'partial'].includes(entry.status));
  assert.deepEqual(probeContext({}).viewport, { w: 0, h: 0, dpr: 1 });
});

test('the report never contains a user-agent string', async () => {
  const env = phone();
  env.navigator.userAgent = 'Mozilla/5.0 (iPhone) SECRET-UA';
  const text = JSON.stringify(await probeCapabilities(env));
  assert.ok(!text.includes('SECRET-UA'));
});
