// TEST ONLY, never part of the package (the recipe does not include it): runs the fixture's app on
// loopback TCP so that tests/unit/test_node_game_runtime.py can play the Party against it on any
// OS. The appliance never runs a game this way: there it gets a Unix socket on fd 3 (server/main.mjs).
//
//   node dev-harness.mjs <unpacked package root> <key, 64 hex> <port of the test's stand-in Party>
import http from 'node:http';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const [root, keyHex, partyPort] = process.argv.slice(2);
const { ENDED_ROUTE, createApp } = await import(pathToFileURL(path.join(root, 'server', 'game.mjs')).href);

function report(message) {
  return new Promise((resolve) => {
    const body = Buffer.from(JSON.stringify({ message }));
    const req = http.request({ host: '127.0.0.1', port: Number(partyPort), path: ENDED_ROUTE, method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': body.length } }, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => {
        let verdict = null;
        try {
          verdict = JSON.parse(Buffer.concat(chunks).toString('utf8')).result ?? null;
        } catch { /* no verdict */ }
        resolve({ status: res.statusCode, verdict });
      });
    });
    req.on('error', () => resolve({ status: null, verdict: null }));
    req.end(body);
  });
}

const app = createApp({ key: Buffer.from(keyHex, 'hex'), report, origin: null,
  page: readFileSync(path.join(root, 'web', 'index.html')), log: (level, text) => process.stderr.write(`${level} ${text}\n`) });
const server = http.createServer(app.listener);
server.listen(0, '127.0.0.1', () => process.stdout.write(`listening ${server.address().port}\n`));
process.stdin.on('end', () => process.exit(0)); // the test closes stdin to stop it
process.stdin.resume();
