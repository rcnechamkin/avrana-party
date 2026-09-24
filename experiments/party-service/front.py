#!/usr/bin/env python3
"""Dev-only single front door (ROADMAP F2a): ONE origin for the party service and the games.

    python front.py --port 8190 --upstream 127.0.0.1:8196 --host 10.42.0.1:8190 --host 127.0.0.1:8190

  /party/…  → the party service (service.py), in this process
  anything else → the games server (`--upstream`, e.g. the Avrana Party Games fork on 8196),
               HTTP proxied and WebSocket upgrades tunnelled, with the Cookie header STRIPPED so
               game servers never see the device token (ADR 0003 §2.4)

It never touches live nginx or production ports: it is a dev process on its own port that phones
open instead of juggling :80 / :8196 / :8198. Stdlib only. Not hardened for the internet: it
serves a WPA2 party LAN, answers only allowlisted Host headers, and is meant for development.
"""
import argparse
import http.client
import os
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import identity  # noqa: E402
import service  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'manifests'))
import manifest  # noqa: E402

HOP = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization', 'te', 'trailers',
       'transfer-encoding', 'upgrade', 'cookie', 'host', 'content-length'}
MAX_UPLOAD = 16 * 1024 * 1024


def is_party(path):
    return path == '/party' or path.startswith('/party/')


class Front(BaseHTTPRequestHandler):
    server_version = 'avrana-dev-front'
    timeout = 30

    def log_message(self, fmt, *args):             # no URLs or headers in logs (ADR 0003 §2.4)
        pass

    def _route(self):
        if is_party(self.path):
            return service.handle(self, self.server.party, self.server.cfg)
        if self.headers.get('Host', '') not in self.server.cfg.hosts:
            return service._send(self, 421, {'error': 'unknown host'})
        if not self.server.upstream:
            return service._send(self, 404, {'error': 'no games upstream configured'})
        if self.headers.get('Upgrade', '').lower() == 'websocket':
            return self._tunnel()
        return self._proxy()

    do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = do_PATCH = do_OPTIONS = _route

    def _upstream_headers(self):
        out = [(k, v) for k, v in self.headers.items() if k.lower() not in HOP]
        out.append(('Host', self.headers.get('Host', '')))   # games see the public host, as behind nginx
        out.append(('X-Forwarded-For', self.client_address[0]))
        return out

    def _proxy(self):
        host, port = self.server.upstream
        n = int(self.headers.get('Content-Length') or 0)
        if not 0 <= n <= MAX_UPLOAD:
            return service._send(self, 413, {'error': 'too large'})
        body = self.rfile.read(n) if n else None
        try:
            up = http.client.HTTPConnection(host, port, timeout=30)
            up.putrequest(self.command, self.path, skip_host=True, skip_accept_encoding=True)
            for k, v in self._upstream_headers():
                up.putheader(k, v)
            if body is not None:
                up.putheader('Content-Length', str(len(body)))
            up.endheaders(body)
            resp = up.getresponse()
        except OSError:
            return service._send(self, 502, {'error': 'games server unreachable'})
        self.send_response(resp.status, resp.reason)
        for k, v in resp.getheaders():
            if k.lower() not in HOP:
                self.send_header(k, v)
        self.send_header('Connection', 'close')        # HTTP/1.0 framing: body ends at close
        self.end_headers()
        if self.command != 'HEAD':
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
        up.close()

    def _tunnel(self):
        """Replay the upgrade request (minus cookies) upstream, then pipe bytes both ways."""
        host, port = self.server.upstream
        try:
            up = socket.create_connection((host, port), timeout=10)
        except OSError:
            return service._send(self, 502, {'error': 'games server unreachable'})
        lines = [f'{self.command} {self.path} HTTP/1.1']
        for k, v in self.headers.items():
            if k.lower() not in ('cookie', 'host'):
                lines.append(f'{k}: {v}')
        lines.append(f"Host: {self.headers.get('Host', '')}")
        up.sendall(('\r\n'.join(lines) + '\r\n\r\n').encode('latin-1'))
        client = self.connection
        client.settimeout(None)
        up.settimeout(None)

        def pipe(src, dst):
            try:
                while True:
                    data = src.recv(65536)
                    if not data:
                        break
                    dst.sendall(data)
            except OSError:
                pass
            finally:
                for s in (src, dst):
                    try:
                        s.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass

        t = threading.Thread(target=pipe, args=(up, client), daemon=True)
        t.start()
        pipe(client, up)
        t.join(timeout=5)
        up.close()
        self.close_connection = True


def lan_catalog(upstream):
    """Catalog entries for the games the upstream server actually serves, derived from its own
    GET /api/games (manifest v0: never hand-written). Returns (entries, problems)."""
    host, port = upstream
    c = http.client.HTTPConnection(host, port, timeout=5)
    try:
        c.request('GET', '/api/games', headers={'Host': f'{host}:{port}'})
        r = c.getresponse()
        if r.status != 200:
            return [], [f'/api/games answered {r.status}']
        api = manifest.parse(r.read().decode())
    except (OSError, manifest.ManifestError) as e:
        return [], [f'/api/games unreachable: {e}']
    finally:
        c.close()
    ms, problems = manifest.derive_lan(api, manifest.load_overlay())
    return manifest.catalog(ms), problems


class FrontServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, party, cfg, upstream=None):
        super().__init__(addr, Front)
        self.party, self.cfg, self.upstream = party, cfg, upstream


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--bind', default='0.0.0.0')
    ap.add_argument('--port', type=int, default=8190)
    ap.add_argument('--host', action='append', default=[],
                    help='allowed Host header, e.g. 10.42.0.1:8190 (repeatable); default: 127.0.0.1:PORT, localhost:PORT')
    ap.add_argument('--upstream', help='games server host:port, e.g. 127.0.0.1:8196')
    ap.add_argument('--devices', default=os.path.join(HERE, 'dev-data', 'devices.json'),
                    help='device-token hash store (JSON, 0600); "" = memory only')
    ap.add_argument('--reset-devices', action='store_true', help='forget every device, then start')
    ap.add_argument('--dev-commands', action='store_true',
                    help='enable POST /party/dev/reset-party (automated tests only; never for a playtest)')
    args = ap.parse_args()
    hosts = args.host or [f'127.0.0.1:{args.port}', f'localhost:{args.port}']
    path = args.devices or None
    if path:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    store = identity.DeviceStore(path)
    if args.reset_devices:
        store.reset()
    upstream, catalog = None, None
    if args.upstream:
        h, _, p = args.upstream.rpartition(':')
        upstream = (h, int(p))
        catalog, problems = lan_catalog(upstream)
        for line in problems:
            print('manifest:', line)
        print(f'catalog: {len(catalog)} games from the upstream registry')
    party = service.PartyService(store, catalog=catalog or None)
    threading.Thread(target=party.run_timer, daemon=True).start()
    srv = FrontServer((args.bind, args.port), party, service.Config(hosts, dev_commands=args.dev_commands), upstream)
    print(f'dev front on :{args.port} for {", ".join(hosts)}; games upstream: {args.upstream or "none"}')
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
