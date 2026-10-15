// EXPERIMENTAL (AVR-469): device requirements in the Game Contract, checked before Play.
//
// A presentation may declare `requires.device_caps` (avrana/contracts/game.py): measured needs
// ({ memory_mb, shared_memory, webgl2_offscreen: 'worker'|'main', opfs, storage_mb }). Before a phone
// is offered Play for such a game, this module tries each one for real and the setup panel keeps the
// EXISTING Play/Watch choice: a phone that fails a check is shown Watch, with Play disabled and the
// failing check named in plain words. A game that declares nothing is never touched.
//
// What a check can and cannot prove, honestly:
//  - Results are 'pass', 'fail', 'unknown' or 'launch'. A probe that throws or times out is
//    'unknown', never a pass; 'unknown' does not block Play but is shown.
//  - Party Home is NOT cross-origin isolated, so `shared_memory` (SharedArrayBuffer / shared
//    WebAssembly.Memory) cannot be proven here. It is 'launch': neither a pass nor a fail, "checked
//    by the game at launch". The game page's own preflight stays the final check for everything.
//  - Memory, OPFS and storage are measured on Party's origin, standing in for the game's origin
//    (a phone's memory limits are per browser, but a separate origin has its own storage usage).
//  - Memory is a non-shared WebAssembly.Memory of the declared size, released at once. That only
//    RESERVES address space (its pages are never touched): a refusal is real evidence that the phone
//    cannot, a success only that a reservation of that size is possible now, not that the RAM is there.
//  - Every check has a time limit (`timeoutMs`), and the checker one more over the whole probe
//    (`totalMs`): a check that never settles is 'unknown', so it can never hold Play back.
// Pure of the page except through `env` (default globalThis), so tests inject fakes.

const PAGE = 65536;
const WORKER_URL = new URL('./device-probe-worker.js', import.meta.url).href;

export const KEYS = Object.freeze(['memory_mb', 'shared_memory', 'webgl2_offscreen', 'opfs', 'storage_mb']);

const message = (error) => (error && error.message ? error.message : String(error));
const result = (status, detail) => ({ status, detail });
const asked = (requires, key) => requires && requires[key] !== undefined && requires[key] !== false;

/** The measured needs of the presentation this phone would be given as a player, or null.
 * `chosen`: the presentation id evaluateSeat picked (so the numbers belong to what will be shown). */
export function deviceRequirements(game, chosen) {
  const list = (game && game.presentations) || [];
  const p = list.find((x) => x.id === chosen) || list.find((x) => x.available && x.roles.includes('player'));
  const caps = p && p.requires && p.requires.device_caps;
  if (!caps || typeof caps !== 'object') return null;
  const wanted = Object.fromEntries(KEYS.filter((k) => asked(caps, k)).map((k) => [k, caps[k]]));
  return Object.keys(wanted).length ? wanted : null;
}

async function memory(requires, env) {
  try {
    if (typeof env.WebAssembly !== 'object') return result('fail', 'no WebAssembly');
    const pages = Math.ceil(requires.memory_mb * 1024 * 1024 / PAGE);
    let mem = new env.WebAssembly.Memory({ initial: pages, maximum: pages });
    const ok = mem.buffer.byteLength === pages * PAGE;
    mem = null;                                  // let go at once; the browser frees it when it collects
    return ok ? result('pass', `${requires.memory_mb} MB reserved`) : result('fail', 'allocation came back short');
  } catch (error) {
    // A refused reservation is a RangeError; anything else says nothing about this phone.
    return error instanceof RangeError ? result('fail', `refused: ${message(error)}`) : result('unknown', message(error));
  }
}

function workerWebGL2(env, timeoutMs) {
  return new Promise((resolve) => {
    let worker = null;
    const done = (r) => { clearTimeout(timer); if (worker) worker.terminate(); resolve(r); };
    const timer = setTimeout(() => done(result('unknown', 'the Worker did not answer')), timeoutMs);
    try {
      worker = new env.Worker(env.workerUrl || WORKER_URL);
      worker.onmessage = (e) => done(e.data && e.data.ok ? result('pass', String(e.data.detail)) : result('fail', String(e.data && e.data.detail)));
      worker.onerror = () => done(result('unknown', 'the probe Worker could not start'));
    } catch (error) {
      done(result('unknown', message(error)));
    }
  });
}

async function webgl2(requires, env, timeoutMs) {
  try {
    if (requires.webgl2_offscreen === 'worker') {
      if (typeof env.Worker !== 'function') return result('fail', 'no Workers');
      return await workerWebGL2(env, timeoutMs);
    }
    if (typeof env.OffscreenCanvas !== 'function') return result('fail', 'no OffscreenCanvas');
    const gl = new env.OffscreenCanvas(16, 16).getContext('webgl2');
    const lose = gl && gl.getExtension && gl.getExtension('WEBGL_lose_context');
    if (lose) lose.loseContext();
    return gl ? result('pass', 'WebGL 2 on an OffscreenCanvas') : result('fail', 'no WebGL 2 on an OffscreenCanvas');
  } catch (error) {
    return result('unknown', message(error));
  }
}

async function opfs(env) {
  try {
    const store = env.navigator && env.navigator.storage;
    if (!store || typeof store.getDirectory !== 'function') return result('fail', 'no Origin Private File System');
    await store.getDirectory();
    return result('pass', 'Origin Private File System available');
  } catch (error) {
    return result('unknown', message(error));   // private browsing and policy refusals throw; that is not a measurement
  }
}

async function storage(requires, env) {
  try {
    const store = env.navigator && env.navigator.storage;
    if (!store || typeof store.estimate !== 'function') return result('unknown', 'the browser does not report its storage');
    const { quota, usage = 0 } = await store.estimate();
    if (!Number.isFinite(quota)) return result('unknown', 'the browser did not report a quota');
    const free = Math.floor((quota - usage) / (1024 * 1024));
    return free >= requires.storage_mb ? result('pass', `${free} MB free`) : result('fail', `${free} MB free, ${requires.storage_mb} MB needed`);
  } catch (error) {
    return result('unknown', message(error));
  }
}

// `promise`, or 'unknown' when it has not settled within `ms`
function within(promise, ms, env) {
  let timer;
  const late = new Promise((resolve) => { timer = env.setTimeout(() => resolve(result('unknown', 'the check did not finish in time')), ms); });
  return Promise.race([promise, late]).finally(() => env.clearTimeout(timer));
}

/** Try each declared need. Never throws; every key asked for gets an answer, each within `timeoutMs`. */
export async function probeDevice(requires, env = globalThis, { timeoutMs = 4000 } = {}) {
  const out = {};
  const timed = (check) => within(check, timeoutMs, env.setTimeout ? env : globalThis);
  if (asked(requires, 'shared_memory')) out.shared_memory = result('launch', 'needs a cross-origin isolated page, which the game has and Party Home does not');
  if (asked(requires, 'memory_mb')) out.memory_mb = await timed(memory(requires, env));
  if (asked(requires, 'webgl2_offscreen')) out.webgl2_offscreen = await timed(webgl2(requires, env, timeoutMs));
  if (asked(requires, 'opfs')) out.opfs = await timed(opfs(env));
  if (asked(requires, 'storage_mb')) out.storage_mb = await timed(storage(requires, env));
  return out;
}

// Plain words for a guest: what is wrong, not how it is measured.
const FAIL = {
  memory_mb: (r) => `This phone cannot spare enough memory for this game (about ${r.memory_mb} MB).`,
  webgl2_offscreen: () => 'This phone’s browser cannot draw this game’s graphics the way it needs to.',
  opfs: () => 'This phone’s browser cannot keep this game’s files.',
  storage_mb: (r) => `This phone does not have enough free storage for this game (about ${r.storage_mb} MB).`,
};
const NAME = {
  memory_mb: 'memory', shared_memory: 'shared memory', webgl2_offscreen: 'graphics',
  opfs: 'file storage', storage_mb: 'free storage',
};

/** The decision: { play, why, checks }. `why` is '' when every check passed. */
export function decide(requires, results) {
  const checks = KEYS.filter((k) => asked(requires, k)).map((key) => {
    const r = results && results[key];
    const status = r && ['pass', 'fail', 'launch'].includes(r.status) ? r.status : 'unknown';   // anything else is not a pass
    return { key, status, detail: (r && r.detail) || '' };
  });
  const failed = checks.filter((c) => c.status === 'fail');
  if (failed.length) return { play: false, checks, why: `${FAIL[failed[0].key](requires)} You can watch this one.` };
  const open = checks.filter((c) => c.status === 'unknown').map((c) => NAME[c.key]);
  const later = checks.filter((c) => c.status === 'launch').map((c) => NAME[c.key]);
  let why = '';
  if (open.length) why = `Could not check this phone’s ${open.join(' and ')}. The game checks again when it starts.`;
  else if (later.length) why = `The game checks this phone’s ${later.join(' and ')} when it starts.`;
  return { play: true, checks, why };
}

/** One checker per page: each distinct set of needs is probed once and the answer kept. */
export function createDeviceChecker({ env = globalThis, probe = probeDevice, totalMs = 12000 } = {}) {
  const done = new Map();
  const pending = new Map();
  const keyOf = (requires) => JSON.stringify(KEYS.map((k) => requires[k] ?? null));
  return {
    /** The kept decision, or null while it is still being found out. */
    peek: (requires) => done.get(keyOf(requires)) || null,
    check(requires) {
      const key = keyOf(requires);
      if (done.has(key)) return Promise.resolve(done.get(key));
      if (!pending.has(key)) {
        // a probe that falls over, or outlives `totalMs`, proves nothing: every check it did not answer is unknown
        let timer;
        const late = new Promise((resolve) => { timer = setTimeout(() => resolve({}), totalMs); });
        pending.set(key, Promise.race([Promise.resolve().then(() => probe(requires, env)), late])
          .catch(() => ({}))
          .finally(() => clearTimeout(timer))
          .then((results) => {
            const decision = decide(requires, results);
            done.set(key, decision);
            pending.delete(key);
            return decision;
          }));
      }
      return pending.get(key);
    },
  };
}
