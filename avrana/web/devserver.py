"""A simulated Party origin for local development and Tier 2 tests (never on the Pi).

    python3 -m avrana.web.devserver --port 8180 [--test-controls]
    open http://127.0.0.1:8180/party/        (127.0.0.1 is a secure context, like the real origin)

It mirrors the nginx 443 site closely enough for the browser tests: the shell under /party/ with
the same headers (no-cache, CSP, nosniff), /party/api/origin.json, the arcade page at /arcade/
with a fake /arcade/stats, and a stub games hub at /. With --test-controls, POST
/__test__/arcade/<up|down|full|hang> switches the fake arcade. Binds 127.0.0.1 only.

With --party, a REAL Party Core (avrana.party.service) runs beside it on an ephemeral loopback
port and /party/api/ is forwarded to it, as nginx does on the appliance: Join, host, launch,
switch, end and /party/api/status all work, with a game link that accepts every launch and stub
game pages under /games/<slug>/. POST /__test__/party/reset starts a fresh party (test controls).
Nothing here deploys; the party is memory-only and dies with the process.
"""
import argparse
import http.client
import json
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from avrana import REPO_ROOT, WEB_DIR

# The games the simulated party offers (deploy/party-core/party-core.example.json's shape).
PARTY_GAMES = {'bluff': {'max_players': 6, 'min_players': 2, 'pregame': True, 'late_join': 'spectator_only'},
               'arcade-gauntlet2': {'max_players': 2, 'late_join': 'supported'},
               'lan-chess': {'max_players': 2, 'late_join': 'spectator_only'}}
FORWARD = ('host', 'cookie', 'origin', 'content-type', 'content-length', 'sec-fetch-site')
# A second pair of host names for the same server, so a browser test can put a game page on
# another origin of the same site (ADR 0013). Chromium is told to resolve them to 127.0.0.1.
PARTY_HOST, GAMES_HOST = 'party.avrana.test', 'games.avrana.test'
BRIDGE_GAME = (b'<!doctype html><meta charset="utf-8"><title>bridge test game</title><h1>stub game on the game origin</h1>'
               b'<script type="module">import { connectParty } from "/party/bridge/shim.js";'
               b'const q = new URLSearchParams(location.search);'
               b'window.partyViews = [];'
               b'window.party = connectParty({ partyOrigin: q.get("party"), game: q.get("game") });'
               b'window.party.onChange((v) => window.partyViews.push(v));'
               b'</script>')
RETURN = ('content-type', 'cache-control', 'set-cookie', 'x-content-type-options')
GAME_STUB = (b'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
             b'<title>%s (stub game)</title><h1 data-game="%s">%s stub</h1>'
             b'<nav id="nav"><a href="/party/">Back to Party</a></nav>'
             # The real in-game follower (what /shared/avrana-integration.js runs in Games): the
             # Party moves this page like any game page. `here` is the Party Core game id.
             b'<script type="module">import { startPartyFollow } from "/party/lib/party-follow.js";'
             b'const slug = location.pathname.split("/")[2];'
             b'startPartyFollow({ here: slug === "bluff" ? slug : "lan-" + slug, container: document.getElementById("nav") });'
             b'</script>')


class AcceptingLink:
    """A game link for the simulated party: every launch and end succeeds, nothing runs."""

    def __init__(self):
        self.launched, self.ended = [], []

    def launch(self, session, roster):
        self.launched.append((session.game_id, [p['name'] for p in roster]))
        return True, None

    def end(self, session):
        self.ended.append(session.id)
        return True


class SimulatedParty:
    """A real Party Core on 127.0.0.1:<ephemeral>; the dev server forwards /party/api/ to it."""

    def __init__(self, public_port):
        from avrana.ops import status
        from avrana.party import identity, service
        self.service_module = service
        from avrana.party import protocol, sessions
        hosts = {f'127.0.0.1:{public_port}', f'{PARTY_HOST}:{public_port}'}
        self.svc = service.PartyService(identity.DeviceStore(None), service.load_games(PARTY_GAMES),
                                        AcceptingLink())
        self.game_origin = f'http://{GAMES_HOST}:{public_port}'
        self.party_origin = f'http://{PARTY_HOST}:{public_port}'
        cfg = service.Config(hosts, {f'http://{h}' for h in hosts}, secure_cookie=False,
                             game_origins={self.game_origin: '*'})
        # The ticket route, so a page can be handed a real ticket; the link still accepts all.
        endpoints = {g: sessions.GameEndpoint(g, f'http://127.0.0.1:{public_port}/games/{g}', protocol.new_key())
                     for g in PARTY_GAMES}
        ticket_routes, _ = sessions.routes(self.svc, endpoints)
        probes = DevProbes()
        routes = status.route(self.svc, {'manifest': str(REPO_ROOT / 'nonexistent-deployment.json'),
                                         'party_checkout': str(REPO_ROOT), 'games_checkout': '',
                                         'web_root': '', 'certificate': '', 'units': [],
                                         'games_url': f'http://127.0.0.1:{public_port}',
                                         'arcade_url': f'http://127.0.0.1:{public_port}/arcade'}, probes, ttl=0)
        routes.update(ticket_routes)
        self.server = service.make_server(self.svc, cfg, port=0, extra_routes=routes)
        self.port = self.server.server_address[1]
        self.stop = threading.Event()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        threading.Thread(target=self.svc.run_timer, args=(self.stop,), daemon=True).start()

    def reset(self):
        import time
        from avrana.party import core
        with self.svc.lock:
            self.svc.core = core.PartyCore(time.monotonic, self.service_module.load_games(PARTY_GAMES))
            self.svc._notify()

    def forward(self, method, target, headers, body, client):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=35)
        h = {k: v for k, v in headers.items() if k.lower() in FORWARD}
        h['X-Forwarded-For'] = h['X-Real-IP'] = client
        try:
            conn.request(method, target, body=body or None, headers=h)
            r = conn.getresponse()
            return r.status, [(k, v) for k, v in r.getheaders() if k.lower() in RETURN], r.read()
        finally:
            conn.close()

    def close(self):
        self.stop.set()
        self.server.shutdown()
        self.server.server_close()


class DevProbes:
    """Status probes for the simulated appliance: this checkout, no manifest, no systemd."""

    def checkout(self, path):
        from avrana.ops import manifest
        try:
            return manifest.observe_checkout(path) if path else None
        except manifest.ManifestError:
            return None

    def web_release(self, root):
        try:
            v = json.loads((WEB_DIR / 'version.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None
        return {'path': str(WEB_DIR), 'build': v.get('build'), 'commit': v.get('commit')}

    def unit_state(self, unit):
        return 'unavailable'

    def certificate_not_after(self, path):
        return None

    def get_json(self, url):
        from avrana.ops import status
        return status.Probes(timeout=2.0).get_json(url)

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
        if path.startswith('/party/api/') and cfg['party'] is not None:
            return self._party()
        if path == '/hotspot-detect.html':
            return self._send(200, b'Success', 'text/html')
        if path.startswith('/games/') and cfg['party'] is not None:
            slug = path.split('/')[2].encode('ascii', 'replace')
            return self._send(200, GAME_STUB % (slug, slug, slug), 'text/html; charset=utf-8', {'Cache-Control': 'no-store'})
        if path == '/party/bridge.html' and cfg['party'] is not None:
            # The one Party page a game origin may frame (ADR 0013); everything else stays 'none'.
            csp = SHELL_HEADERS['Content-Security-Policy'].replace(
                "frame-ancestors 'none'", 'frame-ancestors ' + cfg['party'].game_origin)
            return self._file(cfg['web'], 'bridge.html', dict(SHELL_HEADERS, **{'Content-Security-Policy': csp}))
        if cfg['test_controls'] and path == '/__test__/bridge-game.html':
            return self._send(200, BRIDGE_GAME, 'text/html; charset=utf-8', {'Cache-Control': 'no-store'})
        if path.startswith('/party/'):
            return self._file(cfg['web'], path[len('/party/'):], SHELL_HEADERS)
        if path == '/api/games':
            # Simulated availability only. Never contacts the Pi or starts donor games/chat.
            snapshot = json.loads((REPO_ROOT / 'contracts/catalogs/lan-games.json').read_text(encoding='utf-8'))
            rows = [dict(row, live={'players': 0, 'phase': 'lobby'}, hidden=False)
                    for row in snapshot['games']]
            return self._send(200, json.dumps({'games': rows, 'external': [], 'avranaIntegration': 'avrana.lan-launch/v1'}).encode(),
                              'application/json', {'Cache-Control': 'no-store'})
        if path == '/arcade/stats':
            stats = cfg['arcade'].stats()
            if stats == 'hang':  # a stuck upstream: answer long after any client timeout
                threading.Event().wait(10)
                stats = None
            if stats is None:
                return self._send(502, b'<html><body>502 Bad Gateway</body></html>', 'text/html')
            if cfg['party'] is not None and self.headers.get('Host', '').startswith(GAMES_HOST + ':'):
                # On the game origin the arcade names the Party's origin (arcade/stream.py
                # AVRANA_PARTY_ORIGIN) and the Party starts and admits: the page asks for a ticket.
                stats = dict(stats, party_origin=cfg['party'].party_origin, party_managed=True, state='running')
            return self._send(200, json.dumps(stats).encode(), 'application/json', {'Cache-Control': 'no-store'})
        if path in ('/arcade/party-bridge.js', '/arcade/keep-awake.js'):   # as arcade/stream.py PAGE_MODULES
            source = 'bridge/shim.js' if path.endswith('party-bridge.js') else 'lib/keep-awake.js'
            return self._file(cfg['web'], source, {'Cache-Control': 'no-cache'})
        if path == '/arcade/':
            return self._file(REPO_ROOT / 'arcade', 'index.html', {'Cache-Control': 'no-store'})
        if path == '/':
            return self._send(200, HUB, 'text/html; charset=utf-8')
        return self._send(404, b'not found')

    def _party(self):
        """Forward one request to the simulated Party Core, the way nginx forwards /party/api/."""
        party = self.server.cfg['party']
        n = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(n) if n else b''
        status, headers, data = party.forward(self.command, self.path, dict(self.headers.items()),
                                              body, self.client_address[0])
        try:
            self.send_response(status)
            for k, v in headers:
                self.send_header(k, v)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(data)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass                                  # a page left mid long-poll: normal, not an error

    def do_POST(self):
        path = urlsplit(self.path).path
        cfg = self.server.cfg
        if path.startswith('/party/api/') and cfg['party'] is not None:
            return self._party()
        if cfg['test_controls'] and path == '/__test__/party/reset' and cfg['party'] is not None:
            cfg['party'].reset()
            return self._send(204, b'')
        if cfg['test_controls'] and path.startswith('/__test__/arcade/'):
            mode = path.rsplit('/', 1)[1]
            if mode in ('up', 'down', 'full', 'hang'):
                with cfg['arcade'].lock:
                    cfg['arcade'].mode = mode
                return self._send(204, b'')
        return self._send(404, b'not found')


class _DevServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        # A phone that navigates away mid long-poll aborts its connection: expected, not an error.
        import sys
        if isinstance(sys.exc_info()[1], (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)

    # A fresh page's service worker fetches every shell file at once (~90 with the avatars and
    # library art). The socketserver default backlog of 5 makes Windows refuse the overflow
    # (ECONNREFUSED); nginx on the Pi has no such limit.
    request_queue_size = 128


def make_server(port=0, web=WEB_DIR, test_controls=False, party=False):
    server = _DevServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    server.cfg = {'web': Path(web), 'arcade': Arcade(), 'test_controls': test_controls,
                  'party': SimulatedParty(server.server_address[1]) if party else None}
    return server


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--port', type=int, default=8180)
    ap.add_argument('--web', default=str(WEB_DIR), help='shell directory (a built copy also works)')
    ap.add_argument('--test-controls', action='store_true')
    ap.add_argument('--party', action='store_true', help='run a real Party Core behind /party/api/')
    args = ap.parse_args(argv)
    server = make_server(args.port, args.web, args.test_controls, args.party)
    print(f'Avrana dev server: http://127.0.0.1:{server.server_address[1]}/party/', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if server.cfg['party'] is not None:
            server.cfg['party'].close()
        server.server_close()


if __name__ == '__main__':
    main()
