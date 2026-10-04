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
    GET  /party/api/status                   what is running: avrana.ops.status (no secrets)
    join and rename also take {avatar}: a bundled Gaze avatar id, shown to the party

Session protocol routes (ticket, the game's `ended` report) are attached by avrana.party.sessions
(ADR 0006).

Limited Mode (ADR 0012, AVR-225): the same party, reached over plain HTTP when trusted HTTPS is
unavailable. It is a second loopback listener (`limited` in the config; production does not set
it), so the mode is a property of the socket a request arrived on and no header can claim it.
That listener issues and accepts only the `avrana_limited` credential (identity.LimitedStore),
serves no game -> party route and no bridge origin, and says `"mode": "limited"` in every view.

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
import os
import signal
import socket
import socketserver
import stat
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

    def __init__(self, store, games, link=None, clock=time.monotonic, limited=None):
        self.store = store
        self.limited = limited or identity.LimitedStore()     # Limited Mode credentials (memory)
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

    def game_reported_end(self, session_id, outcome, result=None):
        """The game's own `ended` (via the session protocol). A completed round is held on the
        game's results screen until the host moves on (ADR 0011); an abandoned one has nothing to
        hold, so the party goes home and the game is released at once (AVR-223). `result` is the
        structured result the report carried, if any (ADR 0015)."""
        with self.lock:
            s = self.core.game_reported_end(session_id, outcome, result)
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


BRIDGE_ROUTE = '/party/api/bridge'
BRIDGE_SCHEMA = 'avrana.party-bridge/v1'
SAME_ORIGIN_FETCH = ('same-origin', 'none')      # Sec-Fetch-Site values the Party API answers


class Config:
    def __init__(self, hosts, origins, secure_cookie=True, game_origins=None, mode=core.FULL):
        self.hosts = set(hosts)
        self.origins = set(origins)
        self.secure_cookie = secure_cookie
        if mode not in core.MODES:
            raise ValueError(f'unknown mode {mode!r}')
        self.mode = mode
        if mode == core.LIMITED:
            # Limited Mode is the plain-HTTP fallback and nothing else: an https origin here
            # would hand a trusted origin the weak credential. First-party games stay
            # same-origin in Limited Mode (ADR 0012 D5), so there is no game origin either.
            if not all(isinstance(o, str) and o.startswith('http://') for o in self.origins):
                raise ValueError('a Limited Mode origin must be http://')
            if game_origins:
                raise ValueError('Limited Mode has no game origins')
            self.secure_cookie = False
        # ADR 0013: the browser origins game pages are served from, each with the games it may
        # host ('*' or a list of ids). They are never POST origins: a game page reaches the
        # Party only through the bridge frame, which runs on a Party origin.
        self.game_origins = dict(game_origins or {})
        clash = self.origins & set(self.game_origins)
        if clash:
            raise ValueError(f'a game origin may not also be a Party origin: {sorted(clash)}')

    def game_allowed(self, origin, game):
        games = self.game_origins.get(origin)
        return games == '*' or (isinstance(games, (list, tuple)) and game in games)


def _send(h, status, obj, cookie=None):
    data = json.dumps(obj).encode()
    h.send_response(status)
    h.send_header('Content-Type', 'application/json; charset=utf-8')
    h.send_header('Cache-Control', 'no-store')
    h.send_header('X-Content-Type-Options', 'nosniff')
    cookie = cookie or getattr(h, 'upgrade_cookie', None)
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
        if self.cfg.mode == core.LIMITED:
            # Only the Limited credential, only from the Limited store: a device cookie that
            # reached this listener (it cannot, being Secure) would mean nothing here.
            self.upgrade_cookie = None
            return self.service.limited.resolve(
                identity.read_cookie(self.headers.get('Cookie'), identity.LIMITED_COOKIE))
        token, source = identity.presented(self.headers.get('Cookie'))
        device = self.service.store.resolve(token)
        # One release of dual read (ADR 0013 D3): a phone that still presents only the earlier
        # cookie keeps its member and is handed the `__Host-` cookie with the same token.
        self.upgrade_cookie = (identity.set_cookie(token, True)
                               if device and source == 'legacy' and self.cfg.secure_cookie else None)
        return device

    def _guard(self):
        self.upgrade_cookie = None
        if self.headers.get('Host', '') not in self.cfg.hosts:
            _send(self, 421, {'error': 'unknown_host'})
            return False
        # A browser says where a request comes from. A page on another origin, a sibling host
        # name included, gets nothing from the Party API even though the browser would attach
        # the cookie to its request (same site). Requests without the header (older browsers,
        # tools) fall through to the Origin allow-list and the absence of CORS.
        site = self.headers.get('Sec-Fetch-Site')
        if site is not None and site not in SAME_ORIGIN_FETCH:
            _send(self, 403, {'error': 'cross_origin'})
            return False
        return True

    def do_GET(self):
        if not self._guard():
            return
        url = urlsplit(self.path)
        route = self.extra_routes.get(('GET', url.path))
        if route:
            return route(self, self._device(), None)
        if url.path == BRIDGE_ROUTE:           # which game origins the bridge frame may serve
            return _send(self, 200, {'schema': BRIDGE_SCHEMA, 'origins': self.cfg.game_origins})
        if url.path != '/party/api/state':
            return _send(self, 404, {'error': 'not_found'})
        q = parse_qs(url.query)
        try:
            since = int(q['since'][0]) if 'since' in q else None
            wait = float(q['wait'][0]) if 'wait' in q else 0.0
        except ValueError:
            return _send(self, 400, {'error': 'bad_query'})
        return _send(self, 200, self._view(self._device(), since, wait))

    def _view(self, device, since=None, wait=0.0):
        """The caller's view, with the mode of the connection it came in on: a phone learns that
        it is in Limited Mode from the party, even before it is a member."""
        return dict(self.service.view(device, since, wait), mode=self.cfg.mode)

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
            return _send(self, 200, self._view(device))
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
        if route is None or proxied or not self._local_peer():
            return _send(self, 404, {'error': 'not_found'})
        try:
            body = json.loads(raw or b'{}')
        except ValueError:
            return _send(self, 400, {'error': 'bad_json'})
        if not isinstance(body, dict):
            return _send(self, 400, {'error': 'bad_json'})
        return route(self, body)

    def _local_peer(self):
        return self.client_address[0] in ('127.0.0.1', '::1')

    def _join(self, device, body):
        cookie = None
        limited = self.cfg.mode == core.LIMITED
        if device is None and identity.ambiguous(self.headers.get('Cookie'),
                                                 identity.LIMITED_COOKIE if limited else None):
            # Two device cookies: one of them was planted (identity.read_cookie). Minting a third
            # would not help, since the planted one would still shadow it, so say so instead.
            return _send(self, 409, {'error': 'ambiguous_identity', 'message':
                                     "This phone sent two Party identities. Clear this site's "
                                     'data in the browser, then open Party again.'})
        if device is None:
            core.clean_name(body.get('name'))              # refuse a bad name before minting
            if limited:
                token, device = self.service.limited.issue()
                cookie = identity.set_limited_cookie(token)
            else:
                token, device = self.service.store.issue()
                cookie = identity.set_cookie(token, self.cfg.secure_cookie)
        self.service.call('join', device, body.get('name'), body.get('avatar'), self.cfg.mode)
        return _send(self, 200, self._view(device), cookie)


def make_server(service, cfg, host='127.0.0.1', port=8190, extra_routes=None, internal_routes=None):
    server_cls = type('PartyServer', (http.server.ThreadingHTTPServer,),
                      {'request_queue_size': REQUEST_QUEUE_SIZE, 'daemon_threads': True})
    handler = type('BoundHandler', (Handler,), {'service': service, 'cfg': cfg,
                                                'extra_routes': dict(extra_routes or {}),
                                                'internal_routes': dict(internal_routes or {})})
    return server_cls((host, port), handler)


LIMITED_PORT = 8192


def limited_config(conf, full):
    """The Limited Mode listener's Config from party-core.json's `limited` object, or None when
    the appliance has none (production today). {"hosts": [...], "origins": ["http://..."],
    "port": 8192}. A name or origin shared with Full Mode is refused: the two modes are two
    origins with two credentials, and one listener must never answer for the other."""
    if conf is None:
        return None
    if not isinstance(conf, dict) or not conf.get('hosts') or not conf.get('origins'):
        raise ValueError('limited: needs "hosts" and "origins"')
    cfg = Config(conf['hosts'], conf['origins'], mode=core.LIMITED)
    if cfg.origins & full.origins:
        raise ValueError('limited: an origin may not serve both modes')
    return cfg


class InternalHandler(Handler):
    """The party's internal Unix socket (ADR 0016 §4): game -> party messages only. Who may
    connect is decided by the socket's ownership and mode, not by an address; what is said is
    still verified by signature, issuer and session exactly as on loopback. Nothing else is
    served here: no API, no cookie, no GET."""

    def address_string(self):
        return 'unix'

    def _local_peer(self):
        return True

    def do_GET(self):
        return _send(self, 404, {'error': 'not_found'})

    def do_POST(self):
        # Always through _internal: it reads the body before it refuses, so a caller still
        # sending one gets the 404 and not a reset. A path it has no route for is not found.
        return self._internal(urlsplit(self.path).path)


def listen_fds(environ=os.environ, pid=None):
    """The sockets systemd passed to this process (sd_listen_fds): file descriptors 3, 4, … when
    LISTEN_PID is this process and LISTEN_FDS says how many. [] otherwise."""
    try:
        if int(environ.get('LISTEN_PID', '-1')) != (os.getpid() if pid is None else pid):
            return []
        return list(range(3, 3 + int(environ.get('LISTEN_FDS', '0'))))
    except ValueError:
        return []


def make_internal_server(service, internal_routes, path=None, fd=None):
    """The internal Unix-socket listener. With `fd`, an already listening socket inherited from
    the service's systemd socket unit, which is how production gets a socket owned
    avrana-party:avrana-games 0660. With `path`, a socket this process creates (tests and the dev
    server): mode 0660, owned by the caller, replacing a stale socket file of the same name."""
    if not hasattr(socketserver, 'UnixStreamServer'):
        raise OSError('this system has no Unix sockets')
    server_cls = type('PartyInternalServer', (socketserver.ThreadingMixIn, socketserver.UnixStreamServer),
                      {'daemon_threads': True, 'request_queue_size': REQUEST_QUEUE_SIZE})
    handler = type('BoundInternalHandler', (InternalHandler,),
                   {'service': service, 'cfg': Config(set(), set()), 'extra_routes': {},
                    'internal_routes': dict(internal_routes or {})})
    if fd is not None:
        server = server_cls(None, handler, bind_and_activate=False)
        server.socket.close()
        server.socket = socket.socket(fileno=fd)
        if server.socket.family != socket.AF_UNIX:
            raise OSError('the inherited socket is not a Unix socket')
        server.server_address = server.socket.getsockname()
        return server
    if os.path.exists(path):
        if not stat.S_ISSOCK(os.stat(path).st_mode):
            raise OSError(f'{path} exists and is not a socket')
        os.unlink(path)
    old = os.umask(0o117)                            # created 0660: never open to others
    try:
        server = server_cls(path, handler)
    finally:
        os.umask(old)
    os.chmod(path, 0o660)
    return server


def load_games(entries):
    """Games from explicit entries: {"bluff": {"max_players": 6, "late_join": "spectator_only"}}.
    For tests and harnesses that state a game by hand. The service itself does not use it: main()
    derives these facts from the Game Contracts (avrana.contracts.party_config, AVR-229), so the
    deployed config never carries a second copy of them."""
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
    from avrana.party import registry, sessions         # the session protocol (ADR 0006)
    store = identity.DeviceStore(conf.get('devices'))
    # Per-game facts come from the contracts; where each game is comes from this config and the
    # registry directory (avrana.party.registry). One dict of endpoints is shared by the game
    # link and the session routes, so a reload changes both at once.
    try:
        games, endpoints = registry.build(conf.get('games', {}), conf.get('registry'))
    except registry.RegistryError as e:
        raise SystemExit('party-core config: ' + '; '.join(e.problems))
    service = PartyService(store, games, sessions.HttpGameLink(endpoints, share=True))
    cfg = Config(conf['hosts'], conf['origins'], conf.get('secure_cookie', True),
                 conf.get('game_origins'))
    extra, internal = sessions.routes(service, endpoints)
    from avrana.ops import status                        # GET /party/api/status (avrana.status/v0)
    extra.update(status.route(service, status.load_config(conf)))
    server = make_server(service, cfg, port=args.port, extra_routes=extra, internal_routes=internal)
    try:
        limited = limited_config(conf.get('limited'), cfg)
    except ValueError as e:
        raise SystemExit(f'party-core config: {e}')
    if limited is not None:                    # the same party over plain HTTP (ADR 0012)
        limited_server = make_server(service, limited, extra_routes=extra,
                                     port=int(conf['limited'].get('port', LIMITED_PORT)))
        threading.Thread(target=limited_server.serve_forever, daemon=True).start()
    stop = threading.Event()
    threading.Thread(target=service.run_timer, args=(stop,), daemon=True).start()
    # Native games report on a Unix socket: inherited from the systemd socket unit in production,
    # created here when the config names a path (ADR 0016 §4, AVR-258). The loopback route above
    # stays for the arcade and the LAN Games fork.
    inherited = listen_fds()
    internal_server = None
    if inherited or conf.get('internal_socket'):
        internal_server = make_internal_server(service, internal, conf.get('internal_socket'),
                                               inherited[0] if inherited else None)
        threading.Thread(target=internal_server.serve_forever, daemon=True).start()
    if hasattr(signal, 'SIGHUP'):                # `systemctl reload`: pick up new games, no restart
        def on_hup(signum, frame):
            threading.Thread(target=registry.reload, args=(service, endpoints, args.config),
                             daemon=True).start()
        signal.signal(signal.SIGHUP, on_hup)
    try:
        server.serve_forever()
    finally:
        stop.set()
        if internal_server is not None:
            internal_server.shutdown()


if __name__ == '__main__':
    main()
