// A loopback-only HTTP proxy that resolves *.cp.test to 127.0.0.1, for browsers without
// --host-resolver-rules (Playwright WebKit). Plain HTTP requests and CONNECT tunnels (WebSockets).
import http from 'node:http';
import net from 'node:net';

const debug = (...a) => { if (process.env.CP_PROXY_DEBUG) console.log('[proxy]', ...a); };
const ok = (host) => /^(party|games)\.cp\.test$/.test(host);

export function startProxy(port) {
  const server = http.createServer((req, res) => {
    let target;
    try { target = new URL(req.url); } catch { res.writeHead(400); res.end(); return; }
    if (!ok(target.hostname)) { res.writeHead(403); res.end(); return; }
    const up = http.request({ host: '127.0.0.1', port: target.port || 80, method: req.method, path: target.pathname + target.search, headers: req.headers }, (r) => {
      res.writeHead(r.statusCode, r.headers); r.pipe(res);
    });
    up.on('error', () => { res.writeHead(502); res.end(); });
    req.pipe(up);
  });
  server.on('connect', (req, sock, head) => {
    debug('CONNECT', req.url);
    const [host, p] = req.url.split(':');
    if (!ok(host)) { sock.end('HTTP/1.1 403 Forbidden\r\n\r\n'); return; }
    const up = net.connect(Number(p) || 80, '127.0.0.1', () => { sock.write('HTTP/1.1 200 Connection Established\r\n\r\n'); up.write(head); up.pipe(sock); sock.pipe(up); });
    up.on('error', () => sock.destroy()); sock.on('error', () => up.destroy());
  });
  server.on('upgrade', (req, sock, head) => {
    debug('UPGRADE', req.url, req.headers.host);   // a proxied ws:// sent as an absolute-URI GET with Upgrade
    let target; try { target = new URL(req.url, `http://${req.headers.host}`); } catch { sock.destroy(); return; }   // WebKit sends origin-form + Host
    if (!ok(target.hostname)) { sock.destroy(); return; }
    const up = net.connect(Number(target.port) || 80, '127.0.0.1', () => {
      const lines = [`${req.method} ${target.pathname}${target.search} HTTP/1.1`];
      for (let i = 0; i < req.rawHeaders.length; i += 2) lines.push(`${req.rawHeaders[i]}: ${req.rawHeaders[i + 1]}`);
      up.write(lines.join('\r\n') + '\r\n\r\n'); up.write(head); up.pipe(sock); sock.pipe(up);
    });
    up.on('error', () => sock.destroy()); sock.on('error', () => up.destroy());
  });
  server.listen(port, '127.0.0.1');
  return server;
}
