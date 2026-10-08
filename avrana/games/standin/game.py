"""The stand-in native game (AVR-236). TEST ONLY: contracts/games/standin.json says so and no
product appliance profile grants it.

The smallest process that behaves as ADR 0016 sections 4 and 5 say a native game does, run as

    python3 -m avrana.games.standin

and handed, by the socket unit and the service unit, only this (the field-test runtime convention):
  * its listening socket as file descriptor 3 (LISTEN_FDS=1, LISTEN_PID): an AF_UNIX stream socket
    that nginx (pages, with proxy headers) and Party Core (control, without) both connect to;
  * $AVRANA_PARTY_KEYS: a directory holding `<game id>.key`;
  * $AVRANA_PARTY_SOCKET: Party Core's internal Unix socket, where it reports `ended`;
  * $AVRANA_PARTY_ORIGIN: the Party's browser origin (set per appliance by provision-game from
    Party Core's own configuration), which a game page hands to the bridge shim (ADR 0013);
  * $STATE_DIRECTORY: unused here.
It has no IP networking at all (RestrictAddressFamilies=AF_UNIX): nothing in this module opens an
IP socket or resolves a name. The session logic is the reference protocol.GameSide, unmodified.

Routes (every path is under /games/standin, which is where the front door and Party Core put it):

    POST /games/standin/avrana/session/v0/launch   {"message"}  party -> game, signed, never proxied
    POST /games/standin/avrana/session/v0/end      {"message"}  party -> game, signed, never proxied
    GET  /games/standin/                           a static page
    POST /games/standin/api/redeem   {"ticket"}    -> {"ok", "token", "view"}: single use; the
                                                      caller's own private view only
    POST /games/standin/api/finish   {"token"}     -> {"ok"}: the redeemed player wins; the game
                                                      reports a signed `ended` with a result
    GET  /games/standin/api/party                  -> {"partyOrigin"}: the origin the game was
                                                      handed, or null (what a real page's server tells it)

The stand-in stays resident once started: ADR 0016 section 4's "stops itself when idle" is NOT
implemented here (it is deferred to AVR-238, with the resource ceilings), so a stopped game is
one the host or `provision-game --rotate` stopped.

The credential a redeemed participant holds is protocol.game_token (stable per session and
participant, unforgeable without the key). Nothing here logs a key, a ticket or a token.
"""
import hmac
import http.client
import http.server
import json
import logging
import os
import re
import socket
import socketserver
import sys
import threading

from avrana.party import protocol, result, service, sessions

GAME = 'standin'
BUILD = 'standin-1'
BASE = f'/games/{GAME}'
LAUNCH = BASE + sessions.LAUNCH_PATH
END = BASE + sessions.END_PATH
PAGE = BASE + '/'
REDEEM = BASE + '/api/redeem'
FINISH = BASE + '/api/finish'
PARTY = BASE + '/api/party'
BARE_ORIGIN = re.compile(r'https?://[A-Za-z0-9][A-Za-z0-9.-]{0,252}(:[0-9]{1,5})?')
PROXY_HEADERS = ('x-forwarded-for', 'x-real-ip', 'forwarded')
MAX_BODY = 16384                # a signed launch for a few players fits many times over
REQUEST_TIMEOUT = 10            # s: a stalled client never holds a thread for long
REPORT_TIMEOUT = 5              # s for the `ended` POST to the party

log = logging.getLogger('avrana.games.standin')

HTML = (b'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" '
        b'content="width=device-width,initial-scale=1"><title>Stand-in</title>'
        b'<h1>Stand-in game</h1><p>A test game. It has no screen of its own.</p></html>')
SECURITY = {'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store',
            'Content-Security-Policy': "default-src 'none'"}


class Bad(Exception):
    """A request that is not acceptable JSON of the expected shape."""


def strict_json(raw, keys):
    """The body as a dict with exactly the keys in `keys`, each a string. No duplicate keys, no
    NaN or Infinity, nothing but one object."""
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise Bad('duplicate key')
            out[k] = v
        return out

    def no_constant(name):
        raise Bad('bad number')
    try:
        body = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=no_constant)
    except (ValueError, RecursionError):
        raise Bad('bad json')
    if not isinstance(body, dict) or set(body) != set(keys) \
            or not all(isinstance(body[k], str) for k in keys):
        raise Bad('bad shape')
    return body


def _json(status, body):
    return status, 'application/json', json.dumps(body, sort_keys=True).encode()


class Standin:
    """The game's logic, with no sockets in it: `handle` maps one request to one answer, `report`
    (an injected callable: message -> (HTTP status or None, the party's verdict on the result:
    "accepted", "refused" or None)) is how `ended` reaches the party."""

    def __init__(self, side, report, party_origin=None):
        self.side = side                  # protocol.GameSide for GAME
        self.report = report
        self.party_origin = party_origin  # the Party's browser origin, as handed to this process, or None
        self.lock = threading.Lock()
        self.redeemed = {}                # game token -> (participant, role), current session only

    def handle(self, method, path, headers, raw):
        """(status, content type, body bytes). `headers` has lower-case names."""
        if path.startswith(BASE + '/avrana/'):
            # Control traffic: only Party Core sends it, and Party sends no proxy header; nginx
            # always adds one and also refuses this prefix itself. Anything else is not here.
            if any(headers.get(h) for h in PROXY_HEADERS) or path not in (LAUNCH, END) \
                    or method != 'POST':
                return _json(404, {'ok': False, 'error': 'not_found'})
            return self._control(path, raw)
        if path == PAGE and method == 'GET':
            return 200, 'text/html; charset=utf-8', HTML
        if path == PARTY and method == 'GET':
            return _json(200, {'partyOrigin': self.party_origin})
        if path in (REDEEM, FINISH):
            if method != 'POST':
                return _json(405, {'ok': False, 'error': 'method'})
            return self._redeem(raw) if path == REDEEM else self._finish(raw)
        return _json(404, {'ok': False, 'error': 'not_found'})

    def _control(self, path, raw):
        try:
            message = strict_json(raw, ('message',))['message']
        except Bad:
            return _json(400, {'ok': False, 'error': 'bad_json'})
        with self.lock:
            try:
                if path == LAUNCH:
                    roster = self.side.on_launch(message)
                    self.redeemed.clear()
                    log.info('launched (%d on the roster)', len(roster))
                else:
                    self.side.on_end(message)
                    self.redeemed.clear()
                    log.info('ended by the party')
            except protocol.Invalid as e:
                log.warning('control message refused (%s)', e)
                return _json(403, {'ok': False, 'message': 'Refused.', 'reason': str(e)})
        return _json(200, {'ok': True})

    def _redeem(self, raw):
        try:
            ticket = strict_json(raw, ('ticket',))['ticket']
        except Bad:
            return _json(400, {'ok': False, 'error': 'bad_json'})
        with self.lock:
            try:
                who = self.side.present(ticket)
            except protocol.Invalid as e:
                log.warning('ticket refused (%s)', e)
                return _json(403, {'ok': False, 'message': 'Refused.'})
            self.redeemed[who['token']] = (who['participant'], who['role'])
            me = next((r for r in self.side.roster if r['participant'] == who['participant']), None)
            players = sum(1 for r in self.side.roster if r['role'] == 'player')
            log.info('ticket redeemed (%s)', who['role'])
        # Only the caller's own view: their name, and how many play. Nobody else's.
        return _json(200, {'ok': True, 'token': who['token'], 'role': who['role'],
                           'view': {'you': me['name'] if me else None, 'players': players}})

    def _finish(self, raw):
        try:
            token = strict_json(raw, ('token',))['token']
        except Bad:
            return _json(400, {'ok': False, 'error': 'bad_json'})
        with self.lock:
            seat = next((s for t, s in self.redeemed.items() if hmac.compare_digest(t, token)), None)
            if seat is None or self.side.sid is None:
                return _json(403, {'ok': False, 'message': 'Redeem a ticket first.'})
            participant, role = seat
            if role != 'player':
                return _json(403, {'ok': False, 'message': 'Only a player can finish.'})
            players = [r['participant'] for r in self.side.roster if r['role'] == 'player']
            made = result.build(
                GAME, BUILD, 'competitive',
                [{'participant': p, 'standing': 'won' if p == participant else 'lost'} for p in players],
                players, data_schema='standin.result/v1', data={'rounds': 1})
            message = self.side.ended('completed', result=made)     # the session stops admitting here
            self.redeemed.clear()
        # The session was stopped (above) before the report, on purpose: nothing more is admitted
        # while the party is asked. If the report then fails, the party's session is still there and
        # this game no longer knows it; the host ends it from Party Home (or Party Core's own end
        # timer does). A retry would need the same signed message, which this game does not keep.
        status, verdict = self.report(message)         # off the lock: it waits on the party
        verdict = verdict if verdict in ('accepted', 'refused') else 'unknown'
        log.info('finished; the party answered %s (result %s)', status, verdict)    # the verdict word only
        if status != 200 or verdict != 'accepted':
            return _json(502, {'ok': False, 'message': 'The party did not accept the result.'})
        return _json(200, {'ok': True})


def report_to(party_socket):
    """A `report` that POSTs one signed `ended` to Party Core's internal Unix socket and returns
    (HTTP status, the "result" word of the reply: "accepted" or "refused"); (None, None) when the
    party cannot be reached."""
    def report(message):
        conn = sessions.UnixHTTPConnection(party_socket, REPORT_TIMEOUT)
        try:
            conn.request('POST', sessions.ENDED_ROUTE, body=json.dumps({'message': message}).encode(),
                         headers={'Content-Type': 'application/json', 'Host': 'localhost'})
            r = conn.getresponse()
            raw = r.read(MAX_BODY)
            try:                                        # the party says whether the result was accepted
                reply = json.loads(raw.decode('utf-8'))
            except ValueError:
                reply = None
            verdict = reply.get('result') if isinstance(reply, dict) else None
            return r.status, verdict if isinstance(verdict, str) else None
        except (OSError, ValueError, http.client.HTTPException) as e:
            log.warning('could not report to the party (%s)', type(e).__name__)     # the kind of failure only
            return None, None
        finally:
            conn.close()
    return report


def make_handler(app):
    class Handler(http.server.BaseHTTPRequestHandler):
        timeout = REQUEST_TIMEOUT

        def log_message(self, *args):
            pass                                        # the game logs its own events, never URLs

        def address_string(self):
            return 'unix'

        def _answer(self, status, ctype, body):
            self.send_response(status)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            for k, v in SECURITY.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _serve(self, with_body):
            raw = b''
            if with_body:
                try:
                    n = int(self.headers.get('Content-Length') or -1)
                except ValueError:
                    n = -1
                if not 0 <= n <= MAX_BODY:
                    self.close_connection = True
                    return self._answer(*_json(413, {'ok': False, 'error': 'body_size'}))
                raw = self.rfile.read(n)                # read before answering, so no reset
                if not (self.headers.get('Content-Type') or '').startswith('application/json'):
                    return self._answer(*_json(415, {'ok': False, 'error': 'json_only'}))
            headers = {k.lower(): v for k, v in self.headers.items()}
            path = self.path.split('?', 1)[0]
            self._answer(*app.handle(self.command, path, headers, raw))

        def do_GET(self):
            self._serve(False)

        def do_POST(self):
            self._serve(True)

    return Handler


def make_server(fd, app):
    """A server on the already listening Unix socket `fd` (inherited, never bound here)."""
    if not hasattr(socketserver, 'UnixStreamServer'):
        raise SystemExit('standin game: this system has no Unix sockets')
    server_cls = type('StandinServer', (socketserver.ThreadingMixIn, socketserver.UnixStreamServer),
                      {'daemon_threads': True})
    server = server_cls(None, make_handler(app), bind_and_activate=False)
    server.socket.close()
    server.socket = socket.socket(fileno=fd)
    if server.socket.family != socket.AF_UNIX:
        raise SystemExit('standin game: the inherited socket is not a Unix socket')
    return server


def main(environ=os.environ):
    logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                        format='%(name)s %(levelname)s %(message)s')
    if service.listen_fds(environ) != [3]:
        log.error('expected one inherited socket on fd 3 (LISTEN_FDS=1, LISTEN_PID)')
        return 2
    keys, party_socket = environ.get('AVRANA_PARTY_KEYS'), environ.get('AVRANA_PARTY_SOCKET')
    if not keys or not party_socket:
        log.error('AVRANA_PARTY_KEYS and AVRANA_PARTY_SOCKET are required')
        return 2
    try:
        key = protocol.read_key(os.path.join(keys, f'{GAME}.key'))
    except (OSError, ValueError):
        log.error('the party key is missing or unusable')      # never the key or the file content
        return 2
    origin = environ.get('AVRANA_PARTY_ORIGIN')
    origin = origin if origin and BARE_ORIGIN.fullmatch(origin) else None     # an origin and nothing else
    make_server(3, Standin(protocol.GameSide(key, GAME), report_to(party_socket), origin)).serve_forever()
    return 0
