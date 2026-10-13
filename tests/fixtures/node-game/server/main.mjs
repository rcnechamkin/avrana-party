// The process of the Node fixture game (AVR-68), as the appliance runs it and in no other way:
//
//   <pinned node> server/main.mjs        working directory = the staged package root
//
// What systemd hands it (deploy/games/avrana-game@.service): the listening Unix socket as file
// descriptor 3 (LISTEN_PID, LISTEN_FDS=1), its key as <id>.key in $AVRANA_PARTY_KEYS, Party Core's
// internal socket in $AVRANA_PARTY_SOCKET, the Party's browser origin in $AVRANA_PARTY_ORIGIN. It
// opens no IP socket and resolves no name. It stops itself when idle, and on SIGTERM.
import { readFileSync } from 'node:fs';
import http from 'node:http';
import { getHeapStatistics } from 'node:v8';

import { BASE, ENDED_ROUTE, GAME, createApp } from './game.mjs';

const log = (level, text) => process.stderr.write(`${GAME} ${level} ${text}\n`);

function fail(text) {
  log('ERROR', text);
  process.exit(2);
}

// Executable memory under the unit's sandbox: WebAssembly has no interpreter in V8, so compiling
// and calling a function proves the JIT can map code. Under --jitless there is no WebAssembly.
function jitProbe() {
  if (typeof WebAssembly === 'undefined') return 'no-webassembly';
  // (module (func (export "f") (result i32) i32.const 42))
  const bytes = Uint8Array.of(0, 97, 115, 109, 1, 0, 0, 0, 1, 5, 1, 96, 0, 1, 127, 3, 2, 1, 0, 7, 5, 1, 1, 102, 0, 0,
    10, 6, 1, 4, 0, 65, 42, 11);
  return new WebAssembly.Instance(new WebAssembly.Module(bytes)).exports.f() === 42 ? 'ok' : 'wrong';
}

const env = process.env;
if (env.LISTEN_PID !== String(process.pid) || env.LISTEN_FDS !== '1') fail('expected one inherited socket on fd 3 (LISTEN_FDS=1, LISTEN_PID)');
if (!env.AVRANA_PARTY_KEYS || !env.AVRANA_PARTY_SOCKET) fail('AVRANA_PARTY_KEYS and AVRANA_PARTY_SOCKET are required');
let key;
try {
  const text = readFileSync(`${env.AVRANA_PARTY_KEYS}/${GAME}.key`, 'ascii').trim();
  if (!/^[0-9a-f]{64}$/.test(text)) throw new Error('not a key');
  key = Buffer.from(text, 'hex');
} catch {
  fail('the party key is missing or unusable'); // never the key, never its path content
}
const origin = /^https?:\/\/[A-Za-z0-9][A-Za-z0-9.-]{0,252}(:[0-9]{1,5})?$/.test(env.AVRANA_PARTY_ORIGIN || '') ? env.AVRANA_PARTY_ORIGIN : null;

/** POST one signed `ended` to Party Core's internal Unix socket. */
function report(message) {
  return new Promise((resolve) => {
    const body = Buffer.from(JSON.stringify({ message }));
    const req = http.request({ socketPath: env.AVRANA_PARTY_SOCKET, path: ENDED_ROUTE, method: 'POST', timeout: 3000,
      headers: { 'Content-Type': 'application/json', 'Content-Length': body.length, Host: 'localhost' } }, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => {
        let verdict = null;
        try {
          const answer = JSON.parse(Buffer.concat(chunks).toString('utf8'));
          if (answer && typeof answer.result === 'string') verdict = answer.result;
        } catch { /* not JSON: no verdict */ }
        resolve({ status: res.statusCode, verdict });
      });
    });
    req.on('timeout', () => req.destroy(new Error('timeout')));
    req.on('error', (e) => {
      log('WARNING', `could not report to the party (${e.code || e.message})`);
      resolve({ status: null, verdict: null });
    });
    req.end(body);
  });
}

const app = createApp({ key, report, origin, page: readFileSync(new URL('../web/index.html', import.meta.url)), log });
const server = http.createServer(app.listener);
server.requestTimeout = 40000; // longer than a poll
server.on('error', (e) => fail(`the inherited socket is unusable (${e.code || e.message})`));

function stop() {
  app.close();
  server.close(() => process.exit(0));
  server.closeAllConnections();
}
process.on('SIGTERM', stop);
setInterval(() => { if (app.claimIdleStop()) stop(); }, 1000).unref();

server.listen({ fd: 3 }, () => {
  const heapMb = Math.round(getHeapStatistics().heap_size_limit / 1048576);
  log('INFO', `serving ${BASE}/ on the inherited socket: node ${process.version} ${process.arch}, `
    + `jit ${jitProbe()}, heap limit ${heapMb} MiB, execArgv [${process.execArgv.join(' ')}]`);
});
