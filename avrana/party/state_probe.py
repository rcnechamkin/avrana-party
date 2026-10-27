"""PROTOTYPE (AVR-673 phase 1): ask a running game whether it still holds the session.

The lost-game check (sessions.HttpGameLink.reachable) is a TCP connect: it sees a dead process,
not one that accepts connections and never answers (a hung event loop), nor a restarted game that
holds no session. This asks the game itself, with a signed question it answers from its session
state. The design is the recommendation in docs/design/proposals/2026-10-21-wedged-game-health.md
§4-§5:

* Opt-in: only a game whose contract sets extensions["net.avrana.party"].state = true is asked.
  Every other game keeps today's behaviour exactly.
* POST {game}/avrana/session/v0/state with a sealed `state` message (party -> game, nonce); the
  game answers {"message": sealed `state_is` {sid, nonce, holds}} (game -> party).
* Phase 1 only RAISES A FLAG in Party state (the session's `game_answering`, false): the Host, or
  anyone while the role is vacant, can be offered End. No round is ever closed by this.

The message types live here, not in protocol.py, so the vendored protocol (and its digest in the
Games repository) does not move while this is a prototype. Nothing ships it to a game yet: no
contract declares `state`, and the kits do not answer it.
"""
import secrets

from avrana.party import protocol

STATE_PATH = '/avrana/session/v0/state'

# Outcomes of one question, as Party Core counts them (core.PartyCore.state_answer).
HOLDS, NOT_HOLDS, SILENT, IGNORED = 'holds', 'not_holds', 'silent', 'ignored'


def question(key, game, sid, now=None):
    """Party -> game: do you hold session `sid`?"""
    payload = protocol._base('state', 'party', game, sid, now, protocol.MESSAGE_TTL)
    payload['nonce'] = secrets.token_hex(12)
    return protocol.seal(key, payload)


def answer(key, asked, holds, now=None):
    """Game -> party: the answer to one opened `state` question (its payload). For the kits, and
    for tests that stand in for a game."""
    if type(holds) is not bool:
        raise ValueError('bad state answer')
    payload = protocol._base('state_is', asked['aud'], 'party', asked['sid'], now, protocol.MESSAGE_TTL)
    payload.update({'nonce': asked['nonce'], 'holds': holds})
    return protocol.seal(key, payload)


def open_question(key, token, game, now=None):
    """Game side: the payload of a `state` question addressed to `game`, or raises Invalid."""
    p = protocol.unseal(key, token, 'state', game, now)
    if p.get('iss') != 'party' or not isinstance(p.get('nonce'), str):
        raise protocol.Invalid('issuer')
    return p


def read_answer(key, token, game, asked, now=None):
    """Party side: True or False from an authentic answer to exactly this question, else Invalid."""
    p = protocol.unseal(key, token, 'state_is', 'party', now)
    if p.get('iss') != game or p.get('sid') != asked['sid'] or p.get('nonce') != asked['nonce'] \
            or type(p.get('holds')) is not bool:
        raise protocol.Invalid('answer')
    return p['holds']


def ask(link, session, now=None):
    """One question to the session's game over the link's transport: HOLDS, NOT_HOLDS, SILENT (no
    usable answer in time) or IGNORED (an answer that proves nothing either way: a 404/405 from a
    game that declared the probe, a bad signature, a reply to another question). Never raises."""
    ep = getattr(link, 'endpoints', {}).get(session.game_id)
    if ep is None:
        return IGNORED
    token = question(ep.key, ep.game_id, session.id, now)
    asked = protocol.unseal(ep.key, token, 'state', ep.game_id, now)
    reply = link._post(ep.url + STATE_PATH, token, ep.timeout, ep.socket_path)
    if not reply.answered:
        return SILENT
    if reply.status != 200:
        return IGNORED
    try:
        return HOLDS if read_answer(ep.key, reply.body.get('message'), ep.game_id, asked, now) else NOT_HOLDS
    except protocol.Invalid:
        return IGNORED
