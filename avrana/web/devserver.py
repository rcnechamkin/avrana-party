"""A simulated Party origin for local development and Tier 2 tests (never on the Pi).

    python3 -m avrana.web.devserver --port 8180 [--test-controls]
    open http://127.0.0.1:8180/party/        (127.0.0.1 is a secure context, like the real origin)

It mirrors the nginx 443 site closely enough for the browser tests: the shell under /party/ with
the same headers (no-cache, CSP, nosniff), /party/api/origin.json, the arcade page at /arcade/
with a fake /arcade/stats, and a stub games hub at /. With --test-controls, POST
/__test__/arcade/<up|down|full|hang> switches the fake arcade. Binds 127.0.0.1 only.
"""
import argparse
import json
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from avrana import REPO_ROOT, WEB_DIR

# Keep in step with the /party/ location in avrana-party.nginx (tests/unit/test_nginx_site.py
# compares them).
SHELL_HEADERS = {
    'Cache-Control': 'no-cache',
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'same-origin',
    'Content-Security-Policy': ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                                "connect-src 'self'; worker-src 'self'; manifest-src 'self'; object-src 'none'; "
                                "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"),
}
TYPES = {'.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
         '.json': 'application/json', '.svg': 'image/svg+xml', '.html': 'text/html; charset=utf-8'}
HUB = b'<!doctype html><meta charset="utf-8"><title>LAN GAMES (stub)</title><h1 class="hub-logo">LAN GAMES stub</h1>'


class Arcade:
    def __init__(self):
        self.lock = threading.Lock()
        self.mode = 'up'

    def stats(self):
        with self.lock:
            mode = self.mode
        if mode == 'down':
            return None
        if mode == 'hang':
            return 'hang'
        players = 2 if mode == 'full' else 1
        return {'players': players, 'max_players': 2, 'video_encoders': 1, 'error': None, 'emulator_running': True,
                'providers': {'runtime': {'id': 'retroarch', 'running': True}}}


class Handler(BaseHTTPRequestHandler):
    server_version = 'avrana-devserver'

    def log_message(self, fmt, *args):  # quiet: tests read results, not logs
        return

    def _send(self, status, body, ctype='text/plain; charset=utf-8', headers=None):
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def _file(self, root, rel, headers):
        root = Path(root).resolve()
        target = (root / rel).resolve()
        if root != target and root not in target.parents:
            return self._send(404, b'not found')
        if target.is_dir():
            target = target / 'index.html'
        if not target.is_file():
            return self._send(404, b'not found', headers=headers)
        ctype = TYPES.get(target.suffix) or mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
        return self._send(200, target.read_bytes(), ctype, headers)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urlsplit(self.path).path
        cfg = self.server.cfg
        if path == '/party':
            return self._send(301, b'', headers={'Location': '/party/'})
        if path == '/party/api/origin.json':
            body = json.dumps({'schema': 'avrana.origin/v0', 'scheme': 'http', 'serverAddr': '127.0.0.1',
                               'tls': '', 'http': self.request_version}).encode()
            return self._send(200, body, 'application/json', {'Cache-Control': 'no-store'})
        if path.startswith('/party/'):
            return self._file(cfg['web'], path[len('/party/'):], SHELL_HEADERS)
        if path == '/arcade/stats':
            stats = cfg['arcade'].stats()
            if stats == 'hang':  # a stuck upstream: answer long after any client timeout
                threading.Event().wait(10)
                stats = None
            if stats is None:
                return self._send(502, b'<html><body>502 Bad Gateway</body></html>', 'text/html')
            return self._send(200, json.dumps(stats).encode(), 'application/json', {'Cache-Control': 'no-store'})
        if path == '/arcade/':
            return self._file(REPO_ROOT / 'arcade', 'index.html', {'Cache-Control': 'no-store'})
        if path == '/':
            return self._send(200, HUB, 'text/html; charset=utf-8')
        return self._send(404, b'not found')

    def do_POST(self):
        path = urlsplit(self.path).path
        cfg = self.server.cfg
        if cfg['test_controls'] and path.startswith('/__test__/arcade/'):
            mode = path.rsplit('/', 1)[1]
            if mode in ('up', 'down', 'full', 'hang'):
                with cfg['arcade'].lock:
                    cfg['arcade'].mode = mode
                return self._send(204, b'')
        return self._send(404, b'not found')


def make_server(port=0, web=WEB_DIR, test_controls=False):
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    server.cfg = {'web': Path(web), 'arcade': Arcade(), 'test_controls': test_controls}
    return server


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--port', type=int, default=8180)
    ap.add_argument('--web', default=str(WEB_DIR), help='shell directory (a built copy also works)')
    ap.add_argument('--test-controls', action='store_true')
    args = ap.parse_args(argv)
    server = make_server(args.port, args.web, args.test_controls)
    print(f'Avrana dev server: http://127.0.0.1:{server.server_address[1]}/party/', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
