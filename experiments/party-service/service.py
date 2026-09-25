"""Party service skeleton (ROADMAP F3 + F4, dev only): one party per appliance, server-issued device
identity, presence distinct from page load, host + succession, grace timers, versioned state, an
enforced end. The RULES are not re-implemented: the reference model in ../party-model (53 tests,
300-seed fuzz) is the engine, driven through HTTP. This module adds only what the model leaves out:
credentials in cookies, transport (HTTP commands + Server-Sent Events), serialisation, per-viewer
views, and a background timer.

Routes (all under /party/; every other path belongs to games — see front.py):
  GET  /party/             Party Home page (index.html)
  GET  /party/state        this viewer's view (observer until joined). Issues a device cookie.
  GET  /party/events       Server-Sent Events: the view again on every change (+ keepalives).
                           Re-attaches an EXISTING presence (a reload/wake) but never creates one.
  POST /party/join         {persona?}         explicit Join: the ONLY way a presence is created
  POST /party/leave | /party/rename {name}
  POST /party/host/transfer {to, if_version?} | /party/host/select {game, if_version?}
  POST /party/host/end-game | /party/host/end-party | /party/host/cancel-launch
  POST /party/dev/forget-me                 revoke this browser's own device token (reset one phone)
  POST /party/dev/reset-party               end the party for everyone — only with --dev-commands
Every POST must carry an allowed Origin; every request an allowed Host (DNS-rebinding guard).
"""
import json
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'party-model'))
from party_model import Appliance, Refused  # noqa: E402

import identity  # noqa: E402
import seat_ticket  # noqa: E402

JOIN_BIND_S = 15.0        # a Join's connection must be claimed by an event stream within this
KEEPALIVE_S = 10.0        # SSE comment interval: also how fast a vanished phone is noticed
MAX_BODY = 4096
MESSAGES = 10

DEFAULT_CATALOG = [
    # Used only without a games upstream (tests, a laptop demo). With one, front.py builds the
    # catalog from manifest v0 entries derived from the games server's /api/games
    # (../manifests). `href` is where followers go on the same origin; always_on = no launch step.
    {'id': 'bluff', 'name': 'BLUFF', 'max_players': 6, 'late_join': 'spectator_only',
     'launch': 'always_on', 'href': '/games/bluff/'},
    {'id': 'hub', 'name': 'LAN Games hub', 'max_players': 12, 'late_join': 'supported',
     'launch': 'always_on', 'href': '/'},
]


class Stream:
    """One open event stream (one tab). conn is the model's connection id when it belongs to a
    presence; None for an observer."""

    def __init__(self, token, party_id, conn):
        self.token, self.party_id, self.conn = token, party_id, conn


class PartyService:
    def __init__(self, store, clock=time.monotonic, catalog=None, succession='earliest_joined',
                 runtimes=()):
        self.store = store
        self.runtimes = list(runtimes)        # launchers for 'service' games (runtimes.py)
        self.seat_keys = {}                   # game id -> this launch's seat-ticket key (F5 v1)
        self.clock = clock
        self.app = Appliance(clock, succession=succession)
        self.app.devices = store.by_hash      # one table: the model resolves tokens through it
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.catalog = {g['id']: g for g in (catalog or DEFAULT_CATALOG)}
        self.pending = {}                     # token -> (party_id, conn, deadline): Join awaiting a stream

    # ---- identity -----------------------------------------------------------------------------
    def identify(self, cookie_value):
        """(token, set_cookie_header_or_None). Unknown/forged/revoked values get a NEW token."""
        with self.lock:
            if self.store.resolve(cookie_value):
                return cookie_value, None
            token, _ = self.store.issue()
            return token, identity.set_cookie(token)

    # ---- views (the per-viewer boundary: tokens and device ids never leave the server) --------
    def _marker(self):
        return (self.app.party.id, self.app.party.version)

    def _member(self, token):
        party = self.app.party
        device_id = self.store.resolve(token)
        p = party._by_device(device_id) if device_id else None
        return p if p is not None and not p.left and party.state != 'ended' else None

    def view(self, token):
        with self.lock:
            before = self._marker()
            try:
                return self._view(token)
            finally:                                  # describing the state applies due timers:
                if self._marker() != before:          # wake every stream, or they miss the change
                    self.changed.notify_all()

    def _view(self, token):
        with self.lock:
            party = self.app.party
            p = self._member(token)
            if p is None:
                seen = party.observe(token)
                return {'party': self._party_part(party), 'me': None,
                        'host': seen['host'], 'players': seen['players']}
            party.tick()                          # apply due timers before describing the state
            now = self.clock()
            seat = party.game.seats.get(p.id) if party.game else None
            return {
                'party': self._party_part(party),
                'me': {'presence_id': p.id, 'persona': p.persona, 'is_host': p.id == party.host_id,
                       'seat_slot': seat.slot if seat else None,
                       # only this phone's own view carries its ticket; the game trusts nothing else
                       'seat_ticket': seat_ticket.mint(self.seat_keys[party.game.manifest['id']],
                                                       party.game.manifest['id'], seat.slot)
                       if seat and party.game.manifest['id'] in self.seat_keys else None,
                       'spectator': party.state == 'in_game' and seat is None},
                'members': [{'presence_id': o.id, 'persona': o.persona, 'kind': o.kind,
                             'is_host': o.id == party.host_id, 'state': o.state(now)}
                            for o in party.presences.values() if not o.left],
                'catalog': [{'id': g['id'], 'name': g['name'], 'max_players': g['max_players']}
                            for g in self.catalog.values()],
                'messages': [d['text'] for _, kind, d, _ in party.events
                             if kind == 'system_message'][-MESSAGES:],
            }

    def _party_part(self, party):
        target = party.nav_target
        launch = party.launch['manifest'] if party.state == 'launching' and party.launch else None
        return {'id': party.id, 'state': party.state, 'version': party.version,
                'launching': {'id': launch['id'], 'name': launch['name']} if launch else None,
                'nav': {'seq': party.nav_seq, 'target': target,
                        'href': self.catalog.get(target, {}).get('href')}}

    # ---- commands -------------------------------------------------------------------------------
    def command(self, token, name, body):
        """Apply one command serially (PARTY-LIFECYCLE R1). Raises Refused for rule violations."""
        with self.lock:
            before = self._marker()
            try:
                self._apply(token, name, body)
                self._reconcile()
            finally:
                if self._marker() != before:
                    self.changed.notify_all()
            return self.view(token)

    def _apply(self, token, name, body):
        party = self.app.party
        host_cmd = name.startswith('host/')
        if host_cmd and 'if_version' in body and body['if_version'] != party.version:
            raise Refused('stale request: the party changed')
        if name == 'join':
            persona = body.get('persona')
            p = self.app.connect(token, kind='player',       # may start a NEW party if it ended
                                 persona=str(persona) if persona else None)
            self.pending[token] = (self.app.party.id, p.conns[-1], self.clock() + JOIN_BIND_S)
        elif name == 'leave':
            party.leave(token)
        elif name == 'rename':
            party.rename(token, str(body.get('name', '')))
        elif name == 'host/transfer':
            party.transfer_host(token, str(body.get('to', '')))
        elif name == 'host/select':
            game = self.catalog.get(str(body.get('game', '')))
            if game is None:
                raise Refused('no such game')
            if game.get('launch') == 'service' and self._runtime_for(game) is None:
                raise Refused(f"{game['name']} has no launcher on this appliance")
            launch_id = party.select_game(token, dict(game))
            if game.get('launch') == 'service':
                self._launch(launch_id, game)
        elif name == 'host/cancel-launch':
            party.cancel_launch(token)
            self._reconcile()
        elif name == 'host/end-game':
            ending = party.game.manifest.get('name') if party.game else None
            party.end_game(token)
            if ending:
                party._system(f'{ending} ended. Everyone is back at Party Home.')
        elif name == 'host/end-party':
            party.end_party(token)
        else:
            raise KeyError(name)

    # ---- service games: launch, readiness, stop (runtimes.py does the processes) ---------------
    def _runtime_for(self, game):
        return next((r for r in self.runtimes if r.handles(game)), None)

    def _launch(self, launch_id, game):
        rt = self._runtime_for(game)
        party_id = self.app.party.id
        key = self.seat_keys[game['id']] = seat_ticket.new_key()   # fresh per launch

        def report(ok, reason=None):
            with self.lock:
                before = self._marker()
                party = self.app.party
                current = (party.id == party_id and party.state == 'launching' and party.launch
                           and party.launch['id'] == launch_id)
                if current and ok:
                    party.game_ready(launch_id)
                    party._system(f"{game['name']} started.")
                elif current:
                    party.game_failed(launch_id, reason)
                elif ok:                              # cancelled or superseded while it started
                    threading.Thread(target=rt.stop, args=(game['id'],), daemon=True).start()
                if self._marker() != before:
                    self.changed.notify_all()

        def run():                                # never under the party lock: stops can take 15 s
            for other in self.runtimes:           # one emulator at a time
                if other is not rt:
                    other.stop()
            rt.start(game, on_ready=lambda: report(True), on_fail=lambda why: report(False, why),
                     env={'AVRANA_SEAT_KEY': key, 'AVRANA_SEAT_GAME': game['id']})

        threading.Thread(target=run, daemon=True).start()

    def _reconcile(self):
        """Runtimes follow the party: stop what the party no longer wants; report crashes."""
        party = self.app.party
        want = None
        if party.state == 'in_game' and party.game:
            want = party.game.manifest['id']
        elif party.state == 'launching' and party.launch:
            want = party.launch['manifest']['id']
        for rt in self.runtimes:
            if rt.crashed(want) and party.state == 'in_game':
                name = party.game.manifest.get('name', want)
                party._system(f'{name} stopped unexpectedly. Everyone is back at Party Home.')
                party.game_crashed()              # back home, seating kept; retry is the host's call
                continue
            game_id, _ = rt.running()
            if game_id is not None and game_id != want:
                threading.Thread(target=rt.stop, args=(game_id,), daemon=True).start()

    def set_catalog(self, entries):
        """Replace the selectable games (e.g. once the games server's registry is reachable)."""
        with self.lock:
            self.catalog = {g['id']: g for g in entries}
            self.changed.notify_all()

    def reset_party(self):
        """Dev/test only (front.py --dev-commands): end the current party for everyone."""
        with self.lock:
            if self.app.party.state != 'ended':
                self.app.party._end_party('dev reset')
            self.pending.clear()
            self.changed.notify_all()

    def forget(self, token):
        """Dev: revoke this browser's token (its presence, if any, is left as-is and times out)."""
        with self.lock:
            return self.store.revoke(token)

    # ---- event streams ----------------------------------------------------------------------------
    def open_stream(self, token):
        """A tab opened /party/events. Re-attaches an existing presence (reload, wake) — never
        creates one: GET never mutates membership, and a captive-portal WebView can't join."""
        with self.lock:
            party = self.app.party
            p = self._member(token)
            if p is None:
                return Stream(token, party.id, None)
            pend = self.pending.pop(token, None)
            if pend and pend[0] == party.id and pend[1] in p.conns:
                conn = pend[1]                     # the Join's own connection: nothing changes
            else:
                before = self._marker()
                p = party.connect(token)           # another tab / a reconnect: same presence
                conn = p.conns[-1]
                if self._marker() != before:
                    self.changed.notify_all()
            return Stream(token, party.id, conn)

    def close_stream(self, stream):
        with self.lock:
            self._drop(stream.token, stream.party_id, stream.conn)

    def _drop(self, token, party_id, conn):
        party = self.app.party
        if conn is None or party.id != party_id or party.state == 'ended':
            return
        p = self._member(token)
        if p is not None and conn in p.conns:      # never let the model pick "the newest" instead
            before = self._marker()
            party.drop(token, conn)
            if self._marker() != before:
                self.changed.notify_all()

    def wait(self, marker, timeout):
        """Block until the party changes from `marker` or timeout; returns the current marker."""
        with self.lock:
            self.changed.wait_for(lambda: self._marker() != marker, timeout=timeout)
            return self._marker()

    # ---- time ----------------------------------------------------------------------------------------
    def tick(self):
        with self.lock:
            before = self._marker()
            now = self.clock()
            for token, (party_id, conn, deadline) in list(self.pending.items()):
                if now >= deadline:                # a Join whose page never opened its stream
                    del self.pending[token]
                    self._drop(token, party_id, conn)
            self.app.tick()
            self._reconcile()
            if self._marker() != before:
                self.changed.notify_all()

    def run_timer(self, interval=1.0, stop=None):
        stop = stop or threading.Event()
        while not stop.wait(interval):
            self.tick()


# ---- HTTP adapter ------------------------------------------------------------------------------------
class Config:
    def __init__(self, hosts, cookie=identity.DEV_COOKIE, dev_commands=False):
        self.hosts = set(hosts)                                  # e.g. {'10.42.0.1:8190'}
        self.origins = {f'http://{h}' for h in self.hosts}
        self.cookie = cookie
        self.dev_commands = dev_commands                         # reset-party: tests only, never a playtest


def _send(h, status, obj=None, cookie=None, ctype='application/json', body=None):
    data = body if body is not None else json.dumps(obj).encode()
    h.send_response(status)
    h.send_header('Content-Type', ctype)
    h.send_header('Cache-Control', 'no-store')
    h.send_header('X-Content-Type-Options', 'nosniff')
    h.send_header('Referrer-Policy', 'no-referrer')
    if cookie:
        h.send_header('Set-Cookie', cookie)
    h.send_header('Content-Length', str(len(data)))
    h.end_headers()
    h.wfile.write(data)


def handle(h, service, cfg):
    """Serve one /party/ request on BaseHTTPRequestHandler `h`."""
    if h.headers.get('Host', '') not in cfg.hosts:
        return _send(h, 421, {'error': 'unknown host'})
    path = h.path.split('?', 1)[0]
    token, new_cookie = service.identify(identity.read_cookie(h.headers.get('Cookie'), cfg.cookie))
    if new_cookie and cfg.cookie != identity.DEV_COOKIE:
        new_cookie = new_cookie.replace(identity.DEV_COOKIE + '=', cfg.cookie + '=', 1)
    if h.command == 'GET':
        if path in ('/party', '/party/'):
            with open(os.path.join(HERE, 'index.html'), 'rb') as f:
                return _send(h, 200, cookie=new_cookie, ctype='text/html; charset=utf-8', body=f.read())
        if path == '/party/state':
            return _send(h, 200, service.view(token), cookie=new_cookie)
        if path == '/party/events':
            return _stream(h, service, token, new_cookie)
        return _send(h, 404, {'error': 'not found'})
    if h.command != 'POST':
        return _send(h, 405, {'error': 'method not allowed'})
    if h.headers.get('Origin') not in cfg.origins:
        return _send(h, 403, {'error': 'bad origin'})       # CSRF: POSTs only from our own pages
    try:
        n = int(h.headers.get('Content-Length') or 0)
        if not 0 <= n <= MAX_BODY:
            raise ValueError
        body = json.loads(h.rfile.read(n) or b'{}')
        if not isinstance(body, dict):
            raise ValueError
    except (ValueError, RecursionError):
        return _send(h, 400, {'error': 'bad request'})
    name = path[len('/party/'):]
    if name == 'dev/forget-me':                                  # self only: harmless, always on
        service.forget(token)
        return _send(h, 200, {'forgotten': True}, cookie=identity.clear_cookie(cfg.cookie))
    if name == 'dev/reset-party':
        if not cfg.dev_commands:
            return _send(h, 404, {'error': 'no such command'})
        service.reset_party()
        return _send(h, 200, {'reset': True})
    try:
        return _send(h, 200, service.command(token, name, body), cookie=new_cookie)
    except Refused as e:
        return _send(h, 409, {'error': str(e)}, cookie=new_cookie)
    except KeyError:
        return _send(h, 404, {'error': 'no such command'}, cookie=new_cookie)


def _stream(h, service, token, new_cookie):
    h.send_response(200)
    h.send_header('Content-Type', 'text/event-stream')
    h.send_header('Cache-Control', 'no-store')
    h.send_header('X-Accel-Buffering', 'no')                    # if nginx ever fronts it
    if new_cookie:
        h.send_header('Set-Cookie', new_cookie)
    h.end_headers()
    stream = service.open_stream(token)
    marker = None
    try:
        h.wfile.write(b'retry: 2000\n\n')
        while True:
            current = service.wait(marker, KEEPALIVE_S)
            if current != marker:
                marker = current
                data = json.dumps(service.view(token))
                h.wfile.write(f'event: state\ndata: {data}\n\n'.encode())
            else:
                h.wfile.write(b': keepalive\n\n')
            h.wfile.flush()
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
        pass
    finally:
        service.close_stream(stream)
