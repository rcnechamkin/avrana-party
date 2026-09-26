// Capability Engine v0, browser side: observe what this browser can do. Never sniff the user agent.
//
// Report schema 'avrana.capabilities/v0':
//   { schema, probeVersion, probedAt, depth: 'quick'|'deep',
//     context: { secureContext, displayMode, visibility, online, viewport, orientation, pointer, prefs },
//     caps: { <name>: { status: 'yes'|'no'|'partial'|'unknown', via: 'presence'|'functional'|'permission', note? } } }
//
// Names are the device capabilities in contracts/capabilities.v0.json (a test keeps them equal).
// 'unknown' means "not observed", never "no". Nothing here prompts the user: camera and microphone
// are read from the Permissions API only, persist() is never called, and a wake lock is only
// requested by keep-awake.js inside a tap. Every probe is wrapped, so a throwing API becomes
// 'unknown' instead of breaking the page.

export const SCHEMA = 'avrana.capabilities/v0';
export const PROBE_VERSION = 1;

export const DEVICE_CAPABILITIES = Object.freeze([
  'secure_context', 'service_worker', 'cache_storage', 'websocket', 'webrtc', 'webrtc.data_channel',
  'video.h264', 'web_audio', 'gamepad', 'wake_lock', 'web_crypto', 'storage.local',
  'storage.indexeddb', 'storage.persistent', 'webgl', 'webgl2', 'webgpu', 'fullscreen', 'vibration',
  'media_devices', 'microphone', 'camera', 'touch',
]);

const cap = (status, via, note) => (note ? { status, via, note } : { status, via });
const yn = (ok, via = 'presence') => cap(ok ? 'yes' : 'no', via);
const isFn = (v) => typeof v === 'function';

function guard(fn) {
  try {
    return fn();
  } catch (err) {
    return cap('unknown', 'presence', `probe failed: ${err && err.name ? err.name : 'error'}`);
  }
}

async function guardAsync(fn, via) {
  try {
    return await fn();
  } catch (err) {
    return cap('unknown', via, `probe failed: ${err && err.name ? err.name : 'error'}`);
  }
}

function withTimeout(promise, ms) {
  let timer;
  return Promise.race([
    promise,
    new Promise((resolve) => { timer = setTimeout(() => resolve(TIMEOUT), ms); }),
  ]).finally(() => clearTimeout(timer));
}
const TIMEOUT = Symbol('timeout');

function glContext(env, kind) {
  const doc = env.document;
  if (!doc || !isFn(doc.createElement)) return cap('unknown', 'functional', 'no document');
  const canvas = doc.createElement('canvas');
  const gl = canvas && isFn(canvas.getContext) ? canvas.getContext(kind) : null;
  if (gl && isFn(gl.getExtension)) {
    const lose = gl.getExtension('WEBGL_lose_context');
    if (lose && isFn(lose.loseContext)) lose.loseContext();
  }
  return yn(Boolean(gl), 'functional');
}

/** Synchronous probes: cheap, no prompts, no hardware wake-up. */
export function probeSync(env = globalThis) {
  const nav = env.navigator || {};
  const doc = env.document || {};
  const caps = {};
  caps.secure_context = guard(() => (env.isSecureContext === true ? yn(true)
    : env.isSecureContext === false ? yn(false) : cap('unknown', 'presence')));
  caps.service_worker = guard(() => yn('serviceWorker' in nav && Boolean(nav.serviceWorker)));
  caps.cache_storage = guard(() => yn(typeof env.caches === 'object' && env.caches !== null));
  caps.websocket = guard(() => yn(isFn(env.WebSocket)));
  caps.webrtc = guard(() => yn(isFn(env.RTCPeerConnection)));
  caps['webrtc.data_channel'] = guard(() => yn(isFn(env.RTCPeerConnection)
    && isFn(env.RTCPeerConnection.prototype && env.RTCPeerConnection.prototype.createDataChannel)));
  caps['video.h264'] = guard(() => {
    const recv = env.RTCRtpReceiver;
    if (!recv || !isFn(recv.getCapabilities)) return cap(isFn(env.RTCPeerConnection) ? 'unknown' : 'no', 'presence');
    const video = recv.getCapabilities('video');
    const codecs = (video && video.codecs) || [];
    return yn(codecs.some((c) => /^video\/h264$/i.test(c.mimeType || '')), 'functional');
  });
  caps.web_audio = guard(() => yn(isFn(env.AudioContext) || isFn(env.webkitAudioContext)));
  caps.gamepad = guard(() => {
    if (!isFn(nav.getGamepads)) return yn(false);
    let connected = 0;
    try { connected = Array.from(nav.getGamepads() || []).filter(Boolean).length; } catch { /* policy */ }
    return cap('yes', 'presence', connected ? `${connected} connected` : 'none connected');
  });
  caps.wake_lock = guard(() => yn(Boolean(nav.wakeLock) && isFn(nav.wakeLock.request)));
  caps.web_crypto = guard(() => yn(Boolean(env.crypto && typeof env.crypto.subtle === 'object' && env.crypto.subtle)));
  caps['storage.local'] = guard(() => {
    const ls = env.localStorage;
    if (!ls) return yn(false, 'functional');
    try {
      ls.setItem('avrana.probe', '1');
      const ok = ls.getItem('avrana.probe') === '1';
      ls.removeItem('avrana.probe');
      return yn(ok, 'functional');
    } catch (err) {
      return cap('no', 'functional', `blocked: ${err && err.name ? err.name : 'error'}`);
    }
  });
  caps['storage.indexeddb'] = guard(() => yn(typeof env.indexedDB === 'object' && env.indexedDB !== null));
  caps['storage.persistent'] = guard(() => (nav.storage && isFn(nav.storage.persisted)
    ? cap('unknown', 'presence', 'not checked yet') : yn(false)));
  caps.webgl = guard(() => glContext(env, 'webgl'));
  caps.webgl2 = guard(() => glContext(env, 'webgl2'));
  caps.webgpu = guard(() => (nav.gpu && isFn(nav.gpu.requestAdapter)
    ? cap('unknown', 'presence', 'adapter not requested') : yn(false)));
  caps.fullscreen = guard(() => yn(doc.fullscreenEnabled === true || doc.webkitFullscreenEnabled === true));
  caps.vibration = guard(() => yn(isFn(nav.vibrate)));
  caps.media_devices = guard(() => yn(Boolean(nav.mediaDevices) && isFn(nav.mediaDevices.getUserMedia)));
  caps.microphone = cap('unknown', 'permission', 'not checked yet');
  caps.camera = cap('unknown', 'permission', 'not checked yet');
  caps.touch = guard(() => (typeof nav.maxTouchPoints === 'number' ? yn(nav.maxTouchPoints > 0)
    : cap('unknown', 'presence')));
  return caps;
}

function media(env, query) {
  try {
    return isFn(env.matchMedia) ? Boolean(env.matchMedia(query).matches) : null;
  } catch {
    return null;
  }
}

/** Facts about this page right now (not capabilities; used for presentation choices). */
export function probeContext(env = globalThis) {
  const nav = env.navigator || {};
  const w = Number(env.innerWidth) || 0;
  const h = Number(env.innerHeight) || 0;
  const standalone = media(env, '(display-mode: standalone), (display-mode: fullscreen)') || nav.standalone === true;
  const coarse = media(env, '(pointer: coarse)');
  const fine = media(env, '(pointer: fine)');
  return {
    secureContext: env.isSecureContext === true,
    displayMode: standalone ? 'standalone' : 'browser',
    visibility: (env.document && env.document.visibilityState) || 'unknown',
    online: typeof nav.onLine === 'boolean' ? nav.onLine : null,
    viewport: { w, h, dpr: Number(env.devicePixelRatio) || 1 },
    orientation: w && h ? (w >= h ? 'landscape' : 'portrait') : 'unknown',
    pointer: coarse ? 'coarse' : fine ? 'fine' : coarse === false && fine === false ? 'none' : 'unknown',
    prefs: {
      reducedMotion: media(env, '(prefers-reduced-motion: reduce)'),
      colorScheme: media(env, '(prefers-color-scheme: light)') ? 'light' : 'dark',
      contrastMore: media(env, '(prefers-contrast: more)'),
    },
  };
}

async function permission(env, name) {
  const perms = env.navigator && env.navigator.permissions;
  if (!perms || !isFn(perms.query)) return cap('unknown', 'permission', 'Permissions API missing');
  return guardAsync(async () => {
    const state = (await perms.query({ name })).state;
    if (state === 'granted') return cap('yes', 'permission');
    if (state === 'denied') return cap('no', 'permission');
    return cap('unknown', 'permission', 'would ask');
  }, 'permission');
}

async function persisted(env) {
  const storage = env.navigator && env.navigator.storage;
  if (!storage || !isFn(storage.persisted)) return cap('no', 'presence');
  return guardAsync(async () => yn(Boolean(await storage.persisted()), 'functional'), 'functional');
}

async function webgpu(env) {
  const gpu = env.navigator && env.navigator.gpu;
  if (!gpu || !isFn(gpu.requestAdapter)) return cap('no', 'presence');
  return guardAsync(async () => {
    const adapter = await withTimeout(gpu.requestAdapter(), 1500);
    if (adapter === TIMEOUT) return cap('unknown', 'functional', 'no answer in 1.5 s');
    return adapter ? cap('yes', 'functional') : cap('no', 'functional', 'no adapter');
  }, 'functional');
}

// A loopback between two local peer connections. A failure is 'unknown', never 'no': WebKit
// hides host candidates from pages without capture permission, so a real connection to the Pi
// can work where a same-page loopback cannot.
async function dataChannelLoopback(env) {
  const PC = env.RTCPeerConnection;
  if (!isFn(PC)) return cap('no', 'presence');
  const a = new PC({ iceServers: [] });
  const b = new PC({ iceServers: [] });
  try {
    a.onicecandidate = (e) => e.candidate && b.addIceCandidate(e.candidate).catch(() => {});
    b.onicecandidate = (e) => e.candidate && a.addIceCandidate(e.candidate).catch(() => {});
    const opened = new Promise((resolve) => {
      b.ondatachannel = (e) => { e.channel.onmessage = (m) => resolve(m.data === 'avrana'); };
    });
    const channel = a.createDataChannel('probe');
    channel.onopen = () => channel.send('avrana');
    await a.setLocalDescription(await a.createOffer());
    await b.setRemoteDescription(a.localDescription);
    await b.setLocalDescription(await b.createAnswer());
    await a.setRemoteDescription(b.localDescription);
    const result = await withTimeout(opened, 3000);
    if (result === true) return cap('yes', 'functional', 'local loopback');
    return cap('unknown', 'functional', 'local loopback did not open (the Pi may still work)');
  } catch (err) {
    return cap('unknown', 'functional', `loopback failed: ${err && err.name ? err.name : 'error'}`);
  } finally {
    a.close();
    b.close();
  }
}

/**
 * Probe this browser. quick: sync probes + permission/persistence reads (no prompts, no GPU).
 * deep: also WebGPU adapter and a DataChannel loopback (diagnostics page, on request).
 */
export async function probeCapabilities(env = globalThis, { deep = false, now = () => new Date() } = {}) {
  const caps = probeSync(env);
  const [mic, camera, persist] = await Promise.all([
    permission(env, 'microphone'), permission(env, 'camera'), persisted(env),
  ]);
  caps.microphone = mic;
  caps.camera = camera;
  caps['storage.persistent'] = persist;
  if (deep) {
    caps.webgpu = await webgpu(env);
    if (caps['webrtc.data_channel'].status === 'yes') caps['webrtc.data_channel'] = await dataChannelLoopback(env);
  }
  return {
    schema: SCHEMA,
    probeVersion: PROBE_VERSION,
    probedAt: now().toISOString(),
    depth: deep ? 'deep' : 'quick',
    context: probeContext(env),
    caps,
  };
}

/** name -> status, the shape evaluate.js takes. */
export function statuses(report) {
  const out = {};
  for (const [name, entry] of Object.entries(report.caps || {})) out[name] = entry.status;
  return out;
}
