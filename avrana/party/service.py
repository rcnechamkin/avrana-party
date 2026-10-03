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
    POST /party/api/session/switch {game, if_version}    host: end the game that is on, then
                                                         launch this one (AVR-128)
    POST /party/api/session/choice {choice}              a member, during setup: 'player' or
                                                         'spectator' for this round (AVR-129)
    POST /party/api/session/start  {if_version}          host: start the round set up (AVR-129)
    POST /party/api/home           {if_version}          host: from a round's results back to
                                                         Party Home, for everyone (ADR 0011)
    join and rename also take {avatar}: a bundled Gaze avatar id, shown to the party

Session protocol routes (ticket, the game's `ended` report) are attached by avrana.party.sessions
(ADR 0006).

Guards: an allowed Host header on every request (DNS rebinding); POSTs need an allowed Origin
(CSRF) and a JSON body of at most 8 KiB; every response is `Cache-Control: no-store`. The device
token lives only in the cookie; it is never logged and never in a body or URL. Game servers are
reached only through a GameLink (the session protocol), never with a device or member id.
Bounds (AVR-218): at most MAX_WAITERS long polls block at once (extra ones get the current view
at once, a short poll), and the listen backlog is REQUEST_QUEUE_SIZE so phone wake storms queue.
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
MAX_WAITERS = 64            # AVR-218: concurrent blocked long polls; beyond it a poll returns at once
REQUEST_QUEUE_SIZE = 128    # AVR-218: listen backlog (socketserver default 5 drops reconnect storms)


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
        self.waiters = 0

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
            if since is not None and self.core.party.version == since and wait > 0 \
                    and self.waiters < MAX_WAITERS:
                self.waiters += 1
                try:
                    while self.core.party.version == since:
                        left = deadline - time.monotonic()
                        if left <= 0:
                            break
                        self.changed.wait(left)
                finally:
                    self.waiters -= 1
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
        if s.state == core.SETUP:               # pregame (AVR-129): the host's start launches it
            return s
        return self._start(s, roster)

    def go_home(self, device_id, if_version):
        """Host: results -> Party Home (ADR 0011). The game held its results screen for the
        party; it is released (the session protocol's end, acknowledged for a finished session)."""
        with self.lock:
            s = self.core.go_home(device_id, if_version)
            self._notify()
        self.link.end(s)
        return s

    def start_round(self, device_id, if_version):
        """The host starts a round that was set up (AVR-129): the members' choices become the
        roster, then the game is launched exactly as a direct launch would be."""
        with self.lock:
            s = self.core.start_round(device_id, if_version)
            roster = s.roster(self.core.party.members)
            self._notify()
        return self._start(s, roster)

    def switch(self, device_id, game_id, if_version):
        """End the game that is on, then launch the next one: the old game's server has reset
        (or timed out, and then nothing new starts) before the next session exists, so two party
        games never run at once. Nothing can start in between: the old session stays live
        (ending) until the same locked step that opens the next one."""
        with self.lock:
            old = self.core.begin_switch(device_id, game_id, if_version)
            self._notify()
        # a round still in setup never reached the game: nothing there to end
        confirmed = True if old.state == core.ENDED else self.link.end(old)
        with self.lock:
            self.core.end_confirmed(old.id, confirmed)
            s = self.core.launch_pending()
            roster = s.roster(self.core.party.members) if s else None
            self._notify()
        if s is None or s.state == core.SETUP:
            return s or old
        return self._start(s, roster)

    def _start(self, s, roster):
        ok, detail = self.link.launch(s, roster)
        if not ok:
            # Roll back at the game too (AVR-134): a runtime that came up after the link gave up
            # waiting, or half-started, is stopped before the party says the launch failed, so a
            # failed start never leaves a heavy runtime running beside the next one.
            self.link.end(s)
        with self.lock:
            if ok:
                accepted = self.core.launch_accepted(s.id)
            else:
                accepted = True
                self.core.launch_failed(s.id, detail or 'The game did not start.')
            self._notify()
        if ok and not accepted:
            # AVR-223: the party moved on while the launch was in flight (the host cancelled it,
            # or LAUNCH_TIMEOUT passed): the runtime that just came up would be orphaned. Stop it.
            self.link.end(s)
        return s

    def game_reported_end(self, session_id, outcome):
        """The game's own `ended` (via the session protocol). A completed round is held on the
        game's results screen until the host moves on (ADR 0011); an abandoned one has nothing to
        hold, so the party goes home and the game is released at once (AVR-223)."""
        with self.lock:
            s = self.core.game_reported_end(session_id, outcome)
            self._notify()
        if s.outcome == 'abandoned':
            self.link.end(s)
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
              'no_game': 409, 'stale_session': 409, 'unknown_game': 404,
              'setup': 409, 'round_on': 409, 'no_setup': 409, 'unresolved': 409,
              'player_count': 409, 'not_results': 409}.get(e.code, 400)
    return _send(h, status, {'error': e.code, 'message': str(e)})


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = 'AvranaParty/0'
    service: PartyService = None
    cfg: Config = None
    extra_routes = {}                    # (method, path) -> fn(handler, device_id, body); protocol
    internal_routes = {}                 # path -> fn(handler, body); loopback, unproxied only

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
        path = urlsplit(self.path).path
        if path.startswith('/internal/'):
            return self._internal(path)
        if not self._guard():
            return
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
                svc.call('rename', device, body.get('name'), body.get('avatar'))
            elif path == '/party/api/leave':
                svc.call('leave', device)
            elif path == '/party/api/host':
                svc.call('transfer_host', device, body.get('to'), body.get('if_version'))
            elif path == '/party/api/session/launch':
                svc.launch(device, body.get('game'), body.get('if_version'))
            elif path == '/party/api/session/end':
                svc.end(device, body.get('if_version'))
            elif path == '/party/api/session/switch':
                svc.switch(device, body.get('game'), body.get('if_version'))
            elif path == '/party/api/session/choice':
                svc.call('choose', device, body.get('choice'))
            elif path == '/party/api/home':
                svc.go_home(device, body.get('if_version'))
            elif path == '/party/api/session/start':
                svc.start_round(device, body.get('if_version'))
            else:
                return _send(self, 404, {'error': 'not_found'})
            return _send(self, 200, svc.view(device))
        except core.Refused as e:
            return _refused(self, e)

    def _internal(self, path):
        """Server-to-server routes (the session protocol's game -> party messages). Only from this
        machine and never through the reverse proxy: nginx adds X-Forwarded-For/X-Real-IP, and it
        forwards only /party/api/. The message itself is signed; this is defence in depth."""
        route = self.internal_routes.get(path)
        proxied = any(self.headers.get(h) for h in ('X-Forwarded-For', 'X-Real-IP', 'Forwarded'))
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            n = -1
        if not 0 <= n <= MAX_BODY:
            self.close_connection = True
            return _send(self, 413, {'error': 'body_size'})
        raw = self.rfile.read(n)             # read before refusing so the reply is not reset
        if route is None or proxied or self.client_address[0] not in ('127.0.0.1', '::1'):
            return _send(self, 404, {'error': 'not_found'})
        try:
            body = json.loads(raw or b'{}')
        except ValueError:
            return _send(self, 400, {'error': 'bad_json'})
        if not isinstance(body, dict):
            return _send(self, 400, {'error': 'bad_json'})
        return route(self, body)

    def _join(self, device, body):
        cookie = None
        if device is None and identity.ambiguous(self.headers.get('Cookie')):
            # Two device cookies: one of them was planted (identity.read_cookie). Minting a third
            # would not help, since the planted one would still shadow it, so say so instead.
            return _send(self, 409, {'error': 'ambiguous_identity', 'message':
                                     "This phone sent two Party identities. Clear this site's "
                                     'data in the browser, then open Party again.'})
        if device is None:
            core.clean_name(body.get('name'))              # refuse a bad name before minting
            token, device = self.service.store.issue()
            cookie = identity.set_cookie(token, self.cfg.secure_cookie)
        self.service.call('join', device, body.get('name'), body.get('avatar'))
        return _send(self, 200, self.service.view(device), cookie)


def make_server(service, cfg, host='127.0.0.1', port=8190, extra_routes=None, internal_routes=None):
    server_cls = type('PartyServer', (http.server.ThreadingHTTPServer,),
                      {'request_queue_size': REQUEST_QUEUE_SIZE, 'daemon_threads': True})
    handler = type('BoundHandler', (Handler,), {'service': service, 'cfg': cfg,
                                                'extra_routes': dict(extra_routes or {}),
                                                'internal_routes': dict(internal_routes or {})})
    return server_cls((host, port), handler)


def load_games(entries):
    """Game entries from config: {"bluff": {"max_players": 6, "late_join": "spectator_only"}}."""
    games = {}
    for game_id, e in entries.items():
        games[game_id] = {'id': game_id, 'max_players': int(e['max_players']),
                          'late_join': e.get('late_join', 'spectator_only'),
                          'min_players': int(e.get('min_players', 1)),
                          'pregame': bool(e.get('pregame', False))}
    return games


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--config', required=True, help='JSON: hosts, origins, devices, games')
    ap.add_argument('--port', type=int, default=8190)
    args = ap.parse_args(argv)
    with open(args.config, encoding='utf-8') as f:
        conf = json.load(f)
    from avrana.party import protocol, sessions         # the session protocol (ADR 0006)
    store = identity.DeviceStore(conf.get('devices'))
    entries = conf.get('games', {})
    endpoints = {g: sessions.GameEndpoint(g, e['url'], protocol.read_key(e['key_file']),
                                          e.get('timeout'))
                 for g, e in entries.items() if e.get('url') and e.get('key_file')}
    service = PartyService(store, load_games(entries), sessions.HttpGameLink(endpoints))
    cfg = Config(conf['hosts'], conf['origins'], conf.get('secure_cookie', True))
    extra, internal = sessions.routes(service, endpoints)
    server = make_server(service, cfg, port=args.port, extra_routes=extra, internal_routes=internal)
    stop = threading.Event()
    threading.Thread(target=service.run_timer, args=(stop,), daemon=True).start()
    try:
        server.serve_forever()
    finally:
        stop.set()


if __name__ == '__main__':
    main()
