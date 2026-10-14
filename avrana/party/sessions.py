"""The party's side of the session protocol (avrana.party.protocol, ADR 0006) over HTTP.

Party -> game (server to server, loopback, signed with that game's key):
    POST {game_url}/avrana/session/v0/launch   {"message": <launch>}   -> 200 {"ok": true}
    POST {game_url}/avrana/session/v0/end      {"message": <end>}      -> 200 {"ok": true}

Browser -> party (cookie-authenticated, Origin-checked, never in a URL):
    POST /party/api/session/ticket   {[game]} -> {"protocol", "game", "session", "role", "ticket",
                                                  "expires_in"}
    A page that names its game gets 409 no_game while the party plays another one (AVR-128).
    The bridge frame (ADR 0013) adds "origin": the origin of the game page it is serving, as the
    browser reported it. It must then name the game, and that origin must be registered for that
    game (service.Config.game_origins), or the answer is 403 bad_game_origin.
    The game page sends the ticket as its first WebSocket message: {"t": "hello", "ticket": …}.

Game -> party (server to server, loopback and unproxied only, signed):
    POST /internal/party-session/v0/ended   {"message": <ended>}   -> 200 {"ok": true}
    POST /internal/party-session/v0/host    {"message": <host>}    -> 200 {"ok": true, "answer": <host_is>}
    When the message carries a `result` (avrana.party.result, ADR 0015) the reply adds
    "result": "accepted", or "result": "refused" with a "reason". Either way the session ended.

The game URL and key come from the appliance's grant for that game (config), never from the game.

A native game is reached over its own Unix socket instead of loopback TCP (ADR 0016 §4,
AVR-258): the same two POSTs, the same paths under /games/<id>, the same signed messages. Only
the address changes. A game reports `ended` to the party's internal Unix socket
(service.make_internal_server), which serves the same route.

Every call to a game is bounded in size and in time (AVR-336, AVR-33): see `_exchange`.
"""
import http.client
import json
import logging
import socket
import time
from urllib.parse import urlsplit

from avrana.party import core, protocol

log = logging.getLogger('avrana.party.sessions')

LAUNCH_PATH = '/avrana/session/v0/launch'
END_PATH = '/avrana/session/v0/end'
ENDED_ROUTE = '/internal/party-session/v0/ended'
HOST_ROUTE = '/internal/party-session/v0/host'
TICKET_ROUTE = '/party/api/session/ticket'


def unix_base(game_id):
    """The URL a game on a Unix socket is addressed by: only its path matters, and it is the path
    the front door will route to the same socket (/games/<id>/…), so a game sees one layout."""
    return f'http://localhost/games/{game_id}'


class DeadlineSocket(socket.socket):
    """A socket whose every wait is cut to what is left of ONE deadline (a time on the monotonic
    clock). The stdlib's timeout is per call, so a peer that sends a byte just inside it, again and
    again, would hold the reader for ever; here each send and receive is given only the remaining
    budget, and once it is spent they raise TimeoutError. Set `deadline` before use."""
    deadline = None

    def _budget(self):
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError('deadline')
        self.settimeout(left)

    def recv(self, *args, **kw):
        self._budget()
        return super().recv(*args, **kw)

    def recv_into(self, *args, **kw):
        self._budget()
        return super().recv_into(*args, **kw)

    def send(self, *args, **kw):
        self._budget()
        return super().send(*args, **kw)

    def sendall(self, *args, **kw):
        self._budget()
        return super().sendall(*args, **kw)

    def connect(self, address):
        self._budget()
        return super().connect(address)


class BoundedConnection(http.client.HTTPConnection):
    """HTTP over a socket that obeys `deadline` (see DeadlineSocket): loopback TCP, or, with
    `unix_path`, a Unix stream socket: the same requests, a different address.

    Name resolution (getaddrinfo) is outside the deadline. That is acceptable because a game is
    only ever addressed by a loopback IP literal or a Unix socket path from the appliance's own
    grant (never a name a game or phone supplies), so resolution does not touch the network or
    a resolver; connect, send and receive, which can block, are all inside it."""

    def __init__(self, host, port, timeout, unix_path=None):
        super().__init__(host, port, timeout=timeout)
        self.unix_path = unix_path
        self.deadline = time.monotonic() + timeout

    def connect(self):
        if self.unix_path:
            sock = DeadlineSocket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.deadline = self.deadline
            try:
                sock.connect(self.unix_path)
            except BaseException:
                sock.close()
                raise
            self.sock = sock
            return
        last = OSError('no address')
        for family, kind, proto, _, address in socket.getaddrinfo(self.host, self.port, 0, socket.SOCK_STREAM):
            sock = DeadlineSocket(family, kind, proto)
            sock.deadline = self.deadline
            try:
                sock.connect(address)
            except OSError as e:
                sock.close()
                last = e
                continue
            self.sock = sock
            return
        raise last


class UnixHTTPConnection(BoundedConnection):
    """HTTP over a Unix stream socket (a native game, ADR 0016 §4)."""

    def __init__(self, path, timeout):
        super().__init__('localhost', None, timeout, unix_path=path)


MAX_REPLY_BYTES = 64 * 1024     # a launch/end answer is one small JSON object; more is a misbehaving game


class ReplyRefused(OSError):
    """A game's answer was too large or too slow. Party Core stops reading it (AVR-336)."""


def read_reply(response, seconds):
    """The body of a game server's answer, read in pieces and refused past MAX_REPLY_BYTES or once
    `seconds` have passed since the body began. This is the second line of defence: the first is
    the whole-call deadline in `_exchange`, which cuts the socket whatever stage the game is at.
    The socket timeout alone bounds each wait, not the whole answer: a game that drips bytes would
    otherwise hold a Party Core request thread, and one that streams without end would fill its
    memory. The game is third-party code at the community tier."""
    deadline = time.monotonic() + seconds
    out = bytearray()
    while True:
        chunk = getattr(response, 'read1', response.read)(4096)   # read(n) would wait to fill n bytes: a drip never returns
        if not chunk:
            return bytes(out)
        out += chunk
        if len(out) > MAX_REPLY_BYTES:
            raise ReplyRefused('answer too large')
        if time.monotonic() > deadline:
            raise ReplyRefused('answer too slow')


class Reply:
    """What one POST to a game came to. `answered` is False when no usable HTTP answer arrived
    (nothing listening, a cut-off, a malformed or oversized reply)."""
    __slots__ = ('answered', 'status', 'body', 'detail')

    def __init__(self, answered, status=None, body=None, detail=None):
        self.answered, self.status, self.body, self.detail = answered, status, body or {}, detail

    @property
    def ok(self):
        return self.answered and self.status == 200 and self.body.get('ok') is True

    @property
    def message(self):
        """The game's own words for a refusal, or None."""
        text = self.body.get('message')
        return text if self.answered and isinstance(text, str) else None

def _exchange(conn, path, data, seconds, headers):
    """One POST with ONE deadline: `seconds` on the monotonic clock from before the connection is
    made. Every wait on the socket, the headers' as much as the body's, is cut to what is left
    of it (DeadlineSocket), so a game that drips its headers, drips its body, or stalls after its
    headers frees the caller within `seconds` (plus scheduling) whatever its interval. The size of
    the answer is bounded by read_reply. Never raises; returns a Reply."""
    conn.deadline = time.monotonic() + seconds
    try:
        conn.request('POST', path, body=data, headers=headers)
        response = conn.getresponse()
        body = json.loads(read_reply(response, seconds) or b'{}')
        if not isinstance(body, dict):
            return Reply(False, detail='The game server did not answer (ValueError).')
        return Reply(True, response.status, body)
    except (http.client.HTTPException, OSError, ValueError) as e:
        return Reply(False, detail=f'The game server did not answer ({type(e).__name__}).')
    finally:
        conn.close()


class GameEndpoint:
    def __init__(self, game_id, url, key, timeout=None, socket_path=None):
        self.game_id = game_id
        self.url = url.rstrip('/')
        self.key = key
        self.timeout = timeout          # s per request; None = the link's default. A game that
                                        # starts a heavy runtime on launch (the arcade) needs more
        self.socket_path = socket_path  # a native game's Unix socket; None = loopback TCP at `url`


# The link waits for an `end` less long than Party Core does (core.END_TIMEOUT): a game that does
# not stop in time is then reported as unconfirmed (and a pending switch says why) instead of the
# party's timer closing the session first and dropping the switch silently (AVR-223).
END_LINK_TIMEOUT = core.END_TIMEOUT - 3.0


class HttpGameLink:
    """Implements service.PartyService's GameLink with protocol messages. Every call has one
    deadline (`_exchange`) and a bounded reply; the service makes none of them under its lock."""

    def __init__(self, endpoints, timeout=5.0, share=False):
        # game_id -> GameEndpoint. With share=True the caller's own dict is used, so a registry
        # reload (avrana.party.registry.apply) changes the link and the session routes together.
        self.endpoints = endpoints if share else dict(endpoints)
        self.timeout = timeout

    def _post(self, url, message, timeout=None, socket_path=None):
        """POST {"message": …} to `url`: loopback TCP at its address, or, with `socket_path`, that
        Unix socket (same path under /games/<id>, same message). Returns a Reply."""
        data = json.dumps({'message': message}).encode()
        headers = {'Content-Type': 'application/json'}
        seconds = timeout or self.timeout
        u = urlsplit(url)
        if socket_path:
            if not hasattr(socket, 'AF_UNIX'):
                return Reply(False, detail='This system has no Unix sockets.')
            return _exchange(UnixHTTPConnection(socket_path, seconds), u.path, data, seconds,
                             dict(headers, Host='localhost'))
        try:
            conn = BoundedConnection(u.hostname, u.port or 80, seconds)
        except (ValueError, TypeError):
            return Reply(False, detail='The game server did not answer (bad address).')
        return _exchange(conn, u.path, data, seconds, headers)

    def launch(self, session, roster):
        ep = self.endpoints.get(session.game_id)
        if ep is None:
            return False, 'That game has no server here.'
        msg = protocol.launch_message(ep.key, ep.game_id, session.id, roster)
        r = self._post(ep.url + LAUNCH_PATH, msg, ep.timeout, ep.socket_path)
        return r.ok, (None if r.ok else r.message or r.detail or 'The game refused to start.')

    def end(self, session):
        ep = self.endpoints.get(session.game_id)
        if ep is None:
            return False
        msg = protocol.end_message(ep.key, ep.game_id, session.id)
        return self._post(ep.url + END_PATH, msg, min(ep.timeout or self.timeout, END_LINK_TIMEOUT),
                          ep.socket_path).ok

    def reachable(self, session, seconds=None):
        """Whether a connection to the session's game is accepted: True or False, or None when
        this system cannot tell (no Unix sockets). A connection only; no message is sent, so this
        adds nothing to the session protocol (AVR-33, used only with session_recovery.close_lost_game).

        The wait is the game's own link timeout (the grant's `timeout`, else the link's 5 s), the
        time a launch is given: a connection to a loopback or Unix socket is refused at once when
        nothing listens, so a wait only happens when the game's accept queue is full, and a Pi
        loaded by the arcade must not turn a slow accept into a "miss".

        Side effect: for a socket-activated native game (deploy/games/avrana-game@.socket) systemd
        accepts the connection while the process is down and STARTS the unit, exactly as the phone's
        own connection would. That process holds no session, so it answers and refuses the tickets:
        the session is not closed. The check therefore finds a game whose socket is gone (for
        instance after systemd's start limit stopped it), or a TCP game that is down; it does not
        find one that restarted."""
        ep = self.endpoints.get(session.game_id)
        if ep is None:
            return False
        seconds = seconds or ep.timeout or self.timeout
        sock = None
        try:
            if ep.socket_path:
                if not hasattr(socket, 'AF_UNIX'):
                    return None
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(seconds)
                sock.connect(ep.socket_path)
            else:
                u = urlsplit(ep.url)
                sock = socket.create_connection((u.hostname, u.port or 80), timeout=seconds)
        except (OSError, ValueError, TypeError):
            return False
        finally:
            if sock is not None:
                sock.close()                 # on the failed-connect path too
        return True


def routes(service, endpoints):
    """(extra_routes, internal_routes) for service.make_server."""
    from avrana.party.service import _refused, _send
    guard = protocol.ReplayGuard()

    def ticket(h, device, body):
        if device is None:
            return _send(h, 403, {'error': 'not_member', 'message': 'Join the party first.'})
        game = body.get('game') if isinstance(body.get('game'), str) else None
        if 'origin' in body and not (game and isinstance(body['origin'], str)
                                     and h.cfg.game_allowed(body['origin'], game)):
            return _send(h, 403, {'error': 'bad_game_origin',
                                  'message': 'That page may not ask for a ticket to this game.'})
        try:
            with service.lock:
                s, p = service.core.participant_for(device, game)
                # the host, as Party Core has it at this moment (succession included). A game
                # that acts on it asks again, server to server, at the action (HOST_ROUTE)
                host = p.member_id == service.core.party.host_id
                service._notify()
        except core.Refused as e:
            return _refused(h, e)
        ep = endpoints.get(s.game_id)
        if ep is None:
            return _send(h, 409, {'error': 'no_game', 'message': 'That game has no server here.'})
        if not service.game_up(s):                  # AVR-33: the game is gone; the session just closed
            return _send(h, 409, {'error': 'no_game', 'message': 'The game stopped.'})
        tok = protocol.mint_ticket(ep.key, ep.game_id, s.id, p.id, p.role, host=host)
        return _send(h, 200, {'protocol': protocol.VERSION, 'game': s.game_id, 'session': s.id,
                              'role': p.role, 'ticket': tok, 'expires_in': protocol.TICKET_TTL})

    def ended(h, body):
        with service.lock:
            s = service.core.party.session
            game_id = s.game_id if s is not None else None
        ep = endpoints.get(game_id)
        if ep is None:
            return _send(h, 409, {'error': 'stale_session', 'message': 'No game session.'})
        try:
            p = protocol.open_message(ep.key, body.get('message'), 'ended', 'party', guard)
            if p['iss'] != ep.game_id:
                raise protocol.Invalid('issuer')
        except protocol.Invalid as e:
            return _send(h, 403, {'error': 'bad_message', 'reason': str(e)})
        try:
            s = service.game_reported_end(p['sid'], p['outcome'], p.get('result'))
        except core.Refused as e:
            return _refused(h, e)
        reply = {'ok': True}
        if 'result' in p:                         # the end counted; say what became of the result
            if s.result is not None:
                reply['result'] = 'accepted'
            else:
                reply.update(result='refused', reason=s.result_refused)
                log.warning('game %s session %s: result refused (%s)', ep.game_id, p['sid'],
                            s.result_refused)
        return _send(h, 200, reply)

    def host(h, body):
        """A game asks whether one participant of its running session is the Party Host now.
        Party Core answers under its lock, timers run first, so a transfer, a succession and an
        ended session are all already in the answer. The answer is signed and repeats the
        question's nonce; who the host is otherwise is not said."""
        with service.lock:
            s = service.core.party.session
            game_id = s.game_id if s is not None else None
        ep = endpoints.get(game_id)
        if ep is None:
            return _send(h, 409, {'error': 'stale_session', 'message': 'No game session.'})
        try:
            with service.lock:                    # the replay guard is shared between threads
                q = protocol.open_message(ep.key, body.get('message'), 'host', 'party', guard)
            if q['iss'] != ep.game_id:
                raise protocol.Invalid('issuer')
        except protocol.Invalid as e:
            return _send(h, 403, {'error': 'bad_message', 'reason': str(e)})
        with service.lock:
            is_host = service.core.is_host(q['sid'], q['pid'])
        if is_host is None:
            return _send(h, 409, {'error': 'stale_session', 'message': 'No game session.'})
        return _send(h, 200, {'ok': True, 'answer': protocol.host_answer(ep.key, q, is_host)})

    return {('POST', TICKET_ROUTE): ticket}, {ENDED_ROUTE: ended, HOST_ROUTE: host}
