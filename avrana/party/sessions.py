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
    When the message carries a `result` (avrana.party.result, ADR 0015) the reply adds
    "result": "accepted", or "result": "refused" with a "reason". Either way the session ended.

The game URL and key come from the appliance's grant for that game (config), never from the game.
"""
import json
import logging
import urllib.error
import urllib.request

from avrana.party import core, protocol

log = logging.getLogger('avrana.party.sessions')

LAUNCH_PATH = '/avrana/session/v0/launch'
END_PATH = '/avrana/session/v0/end'
ENDED_ROUTE = '/internal/party-session/v0/ended'
TICKET_ROUTE = '/party/api/session/ticket'


class GameEndpoint:
    def __init__(self, game_id, url, key, timeout=None):
        self.game_id = game_id
        self.url = url.rstrip('/')
        self.key = key
        self.timeout = timeout          # s per request; None = the link's default. A game that
                                        # starts a heavy runtime on launch (the arcade) needs more


# The link waits for an `end` less long than Party Core does (core.END_TIMEOUT): a game that does
# not stop in time is then reported as unconfirmed (and a pending switch says why) instead of the
# party's timer closing the session first and dropping the switch silently (AVR-223).
END_LINK_TIMEOUT = core.END_TIMEOUT - 3.0


class HttpGameLink:
    """Implements service.PartyService's GameLink with protocol messages."""

    def __init__(self, endpoints, timeout=5.0):
        self.endpoints = dict(endpoints)          # game_id -> GameEndpoint
        self.timeout = timeout

    def _post(self, url, message, timeout=None):
        req = urllib.request.Request(url, data=json.dumps({'message': message}).encode(),
                                     headers={'Content-Type': 'application/json'}, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                body = json.loads(r.read() or b'{}')
                return r.status == 200 and body.get('ok') is True, body.get('message')
        except (urllib.error.URLError, OSError, ValueError) as e:
            return False, f'The game server did not answer ({type(e).__name__}).'

    def launch(self, session, roster):
        ep = self.endpoints.get(session.game_id)
        if ep is None:
            return False, 'That game has no server here.'
        msg = protocol.launch_message(ep.key, ep.game_id, session.id, roster)
        ok, detail = self._post(ep.url + LAUNCH_PATH, msg, ep.timeout)
        return ok, (None if ok else detail or 'The game refused to start.')

    def end(self, session):
        ep = self.endpoints.get(session.game_id)
        if ep is None:
            return False
        msg = protocol.end_message(ep.key, ep.game_id, session.id)
        return self._post(ep.url + END_PATH, msg, min(ep.timeout or self.timeout, END_LINK_TIMEOUT))[0]


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
                service._notify()
        except core.Refused as e:
            return _refused(h, e)
        ep = endpoints.get(s.game_id)
        if ep is None:
            return _send(h, 409, {'error': 'no_game', 'message': 'That game has no server here.'})
        tok = protocol.mint_ticket(ep.key, ep.game_id, s.id, p.id, p.role)
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

    return {('POST', TICKET_ROUTE): ticket}, {ENDED_ROUTE: ended}
