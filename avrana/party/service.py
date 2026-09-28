"""Party Core v0 over HTTP: `/party/api/…` for phones (stdlib only).

    python3 -m avrana.party.service --config party.json          # binds 127.0.0.1 only

Phones reach it through nginx on the HTTPS server (a deployment step that is NOT done: it needs
an owner-approved `location /party/api/` on the 443 server). Routes:

    GET  /party/api/state[?since=V&wait=S]   the caller's view; long-polls up to S (<= 25) seconds
                                             for a version newer than V; a member's poll is also
                                             their heartbeat
    POST /party/api/join        {name}       explicit Join; the only request that issues a cookie
    POST /party/api/heartbeat   {}           "still here" from a page that is not Party Home
    POST /party/api/rename      {name}
    POST /party/api/leave       {}
    POST /party/api/host        {to, if_version}
    POST /party/api/session/launch {game, if_version}    host
    POST /party/api/session/end    {if_version}          host: end the game for everyone

Guards: an allowed Host header on every request (DNS rebinding); POSTs need an allowed Origin
(CSRF) and a JSON body of at most 8 KiB; every response is `Cache-Control: no-store`. The device
token lives only in the cookie; it is never logged and never in a body or URL. Game servers are
reached only through a GameLink (the session protocol), never with a device or member id.
"""
import argparse
import http.server
import json
import threading
import time
from urllib.parse import parse_qs, urlsplit

from avrana.party import core, identity

MAX_BODY = 8192
MAX_WAIT = 25.0


class NoGameLink:
    """A party with no game servers attached: every launch fails with a readable reason."""

    def launch(self, session, roster):
        return False, 'No game server is attached.'

    def end(self, session):
        return False


class PartyService:
    """Thread-safe wrapper: one lock around the core, a condition for long polls, and game-link
    calls made outside the lock (a slow game must not freeze the party)."""

    def __init__(self, store, games, link=None, clock=time.monotonic):
        self.store = store
        self.core = core.PartyCore(clock, games)
        self.link = link or NoGameLink()
        self.lock = threading.Lock()
        self.changed = threading.Condition(self.lock)

    def _notify(self):
        self.changed.notify_all()

    def call(self, fn, *args):
        with self.lock:
            before = self.core.party.version, self.core.party.id
            try:
                return getattr(self.core, fn)(*args)
            finally:
                if (self.core.party.version, self.core.party.id) != before:
                    self._notify()

    def view(self, device_id, since=None, wait=0.0):
        deadline = time.monotonic() + min(max(wait, 0.0), MAX_WAIT)
        with self.lock:
            if device_id:
                self._touch_locked(device_id)
            while since is not None and self.core.party.version == since:
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                self.changed.wait(left)
            return self.core.view(device_id)

    def _touch_locked(self, device_id):
        before = self.core.party.version
        self.core.touch(device_id)
        if self.core.party.version != before:
            self._notify()

    def launch(self, device_id, game_id, if_version):
        with self.lock:
            s = self.core.launch(device_id, game_id, if_version)
            roster = s.roster(self.core.party.members)
            self._notify()
        ok, detail = self.link.launch(s, roster)
        with self.lock:
            if ok:
                self.core.launch_accepted(s.id)
            else:
                self.core.launch_failed(s.id, detail or 'The game did not start.')
            self._notify()
        return s

    def end(self, device_id, if_version):
        with self.lock:
            s = self.core.begin_end(device_id, if_version)
            self._notify()
            if s.state == core.ENDED:            # a launch that was cancelled: nothing to reset
                return s
        confirmed = self.link.end(s)
        with self.lock:
            self.core.end_confirmed(s.id, confirmed)
            self._notify()
        return s

    def run_timer(self, stop, interval=1.0):
        while not stop.wait(interval):
            with self.lock:
                if self.core.tick():
                    self._notify()


class Config:
    def __init__(self, hosts, origins, secure_cookie=True):
        self.hosts = set(hosts)
        self.origins = set(origins)
        self.secure_cookie = secure_cookie


def _send(h, status, obj, cookie=None):
    data = json.dumps(obj).encode()
    h.send_response(status)
    h.send_header('Content-Type', 'application/json; charset=utf-8')
    h.send_header('Cache-Control', 'no-store')
    h.send_header('X-Content-Type-Options', 'nosniff')
    if cookie:
        h.send_header('Set-Cookie', cookie)
    h.send_header('Content-Length', str(len(data)))
    h.end_headers()
    h.wfile.write(data)


def _refused(h, e):
    status = {'not_member': 403, 'not_host': 403, 'stale': 409, 'busy': 409,
              'no_game': 409, 'stale_session': 409, 'unknown_game': 404}.get(e.code, 400)
    return _send(h, status, {'error': e.code, 'message': str(e)})


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = 'AvranaParty/0'
    service: PartyService = None
    cfg: Config = None
    extra_routes = {}                    # (method, path) -> fn(handler, device_id, body); protocol

    def log_request(self, code='-', size='-'):
        # Path only: never the query string, headers or body (tokens and tickets live there).
        self.log_message('%s %s %s', self.command, urlsplit(self.path).path, code)

    def _device(self):
        return self.service.store.resolve(identity.read_cookie(self.headers.get('Cookie')))

    def _guard(self):
        if self.headers.get('Host', '') not in self.cfg.hosts:
            _send(self, 421, {'error': 'unknown_host'})
            return False
        return True

    def do_GET(self):
        if not self._guard():
            return
        url = urlsplit(self.path)
        route = self.extra_routes.get(('GET', url.path))
        if route:
            return route(self, self._device(), None)
        if url.path != '/party/api/state':
            return _send(self, 404, {'error': 'not_found'})
        q = parse_qs(url.query)
        try:
            since = int(q['since'][0]) if 'since' in q else None
            wait = float(q['wait'][0]) if 'wait' in q else 0.0
        except ValueError:
            return _send(self, 400, {'error': 'bad_query'})
        return _send(self, 200, self.service.view(self._device(), since, wait))

    def do_POST(self):
        if not self._guard():
            return
        path = urlsplit(self.path).path
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            n = -1
        if not 0 <= n <= MAX_BODY:
            self.close_connection = True
            return _send(self, 413, {'error': 'body_size'})
        raw = self.rfile.read(n)             # read before refusing so the reply is not reset
        if self.headers.get('Origin') not in self.cfg.origins:
            return _send(self, 403, {'error': 'bad_origin'})
        if not (self.headers.get('Content-Type') or '').startswith('application/json'):
            return _send(self, 415, {'error': 'json_only'})
        try:
            body = json.loads(raw or b'{}')
        except ValueError:
            return _send(self, 400, {'error': 'bad_json'})
        if not isinstance(body, dict):
            return _send(self, 400, {'error': 'bad_json'})
        device = self._device()
        route = self.extra_routes.get(('POST', path))
        try:
            if route:
                return route(self, device, body)
            if path == '/party/api/join':
                return self._join(device, body)
            if device is None:
                return _send(self, 403, {'error': 'not_member', 'message': 'Join the party first.'})
            svc = self.service
            if path == '/party/api/heartbeat':
                with svc.lock:
                    svc._touch_locked(device)
            elif path == '/party/api/rename':
                svc.call('rename', device, body.get('name'))
            elif path == '/party/api/leave':
                svc.call('leave', device)
            elif path == '/party/api/host':
                svc.call('transfer_host', device, body.get('to'), body.get('if_version'))
            elif path == '/party/api/session/launch':
                svc.launch(device, body.get('game'), body.get('if_version'))
            elif path == '/party/api/session/end':
                svc.end(device, body.get('if_version'))
            else:
                return _send(self, 404, {'error': 'not_found'})
            return _send(self, 200, svc.view(device))
        except core.Refused as e:
            return _refused(self, e)

    def _join(self, device, body):
        cookie = None
        if device is None:
            core.clean_name(body.get('name'))              # refuse a bad name before minting
            token, device = self.service.store.issue()
            cookie = identity.set_cookie(token, self.cfg.secure_cookie)
        self.service.call('join', device, body.get('name'))
        return _send(self, 200, self.service.view(device), cookie)


def make_server(service, cfg, host='127.0.0.1', port=8190, extra_routes=None):
    handler = type('BoundHandler', (Handler,), {'service': service, 'cfg': cfg,
                                                'extra_routes': dict(extra_routes or {})})
    return http.server.ThreadingHTTPServer((host, port), handler)


def load_games(entries):
    """Game entries from config: {"bluff": {"max_players": 6, "late_join": "spectator_only"}}."""
    games = {}
    for game_id, e in entries.items():
        games[game_id] = {'id': game_id, 'max_players': int(e['max_players']),
                          'late_join': e.get('late_join', 'spectator_only')}
    return games


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--config', required=True, help='JSON: hosts, origins, devices, games')
    ap.add_argument('--port', type=int, default=8190)
    args = ap.parse_args(argv)
    with open(args.config, encoding='utf-8') as f:
        conf = json.load(f)
    store = identity.DeviceStore(conf.get('devices'))
    service = PartyService(store, load_games(conf.get('games', {})))
    cfg = Config(conf['hosts'], conf['origins'], conf.get('secure_cookie', True))
    server = make_server(service, cfg, port=args.port)
    stop = threading.Event()
    threading.Thread(target=service.run_timer, args=(stop,), daemon=True).start()
    try:
        server.serve_forever()
    finally:
        stop.set()


if __name__ == '__main__':
    main()
