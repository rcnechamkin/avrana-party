"""A runtime that runs only while the Party says so (AVR-134, ADR 0009).

The game side of the session protocol (ADR 0006) for a heavyweight provider: the arcade's
RetroArch + capture/encode. Party Core's signed `launch` starts the runtime and its signed `end`
stops it, one request at a time, so the one-Party-activity rule (ADR 0008) also bounds CPU,
the hardware encoder and power: Gauntlet II never runs beside BLUFF or another Party game.

    managed = ManagedRuntime(side, start, stop, report=post)   # side: protocol.GameSide
    status, body = await managed.launch(message)               # 200 {"ok": true} once running
    status, body = await managed.end(message)                  # 200 {"ok": true} once stopped
    await managed.abandon()                                     # a fatal failure: tell the party

Rules (each has a test in tests/unit/test_party_managed.py):
  * One at a time: launch, end and abandon hold one lock, so a stop never overlaps a start.
  * A launch while an older session still runs stops that run first (the party never does this;
    a lost `end` would), so there is never more than one run.
  * A start that fails or takes longer than START_TIMEOUT is stopped again (a partial start never
    lingers) and answered 200 {"ok": false, "message"}: the party shows why and starts nothing.
  * `end` for the running session stops it. `end` for another session while nothing runs is
    answered ok (idempotent: after a restart or a failed start the runtime is already stopped, and
    the party's switch must be able to go on). `end` for another session while a newer one runs
    is refused (409): a late message never stops the party's current game.
  * A stop that fails is answered {"ok": false}: the party then does not start the next game.
  * Messages are verified (signature, audience, expiry, replay) before anything happens; a forged,
    replayed or expired one is refused (403) and changes nothing.

The HTTP side (`handle`) accepts only loopback requests without proxy headers; the arcade serves
it on its own 127.0.0.1 port that nginx never forwards.
"""
import asyncio
import ipaddress
import json
import logging
import os
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from avrana.party import protocol

IDLE, STARTING, RUNNING, STOPPING = 'idle', 'starting', 'running', 'stopping'
START_TIMEOUT = 15.0            # s for the runtime to come up (the party's link waits longer)
REPORT_TIMEOUT = 3.0            # s for one `ended` POST while the process is going down
MAX_BODY = 8192
PROXY_HEADERS = ('x-forwarded-for', 'x-real-ip', 'forwarded')
LOOPBACK = ('127.0.0.1', '::1')
KEYS_ENV = 'AVRANA_PARTY_KEYS'
PARTY_URL_ENV = 'AVRANA_PARTY_URL'
ENDED_PATH = '/internal/party-session/v0/ended'
LAUNCH_PATH = '/avrana/session/v0/launch'
END_PATH = '/avrana/session/v0/end'

log = logging.getLogger('avrana.party.managed')


class ManagedRuntime:
    def __init__(self, side, start, stop, *, report=None, start_timeout=START_TIMEOUT):
        self.side = side                 # protocol.GameSide: key, game id, current sid, replays
        self._start, self._stop = start, stop           # async callables
        self.report = report             # async callable(message) -> bool, or None
        self.start_timeout = start_timeout
        self.state = IDLE
        self.lock = asyncio.Lock()

    @property
    def session(self):
        return self.side.sid

    async def _halt(self):
        """Stop whatever runs. True when the runtime is stopped."""
        self.state = STOPPING
        try:
            await self._stop()
        except Exception:
            log.exception('[%s] stopping the runtime failed', self.side.game)
            self.state = RUNNING         # assume the worst: it may still be running
            return False
        self.state = IDLE
        return True

    async def launch(self, message):
        async with self.lock:
            running = self.state != IDLE
            try:
                roster = self.side.on_launch(message)       # verifies; the new sid replaces
            except protocol.Invalid as e:
                return 403, {'ok': False, 'message': 'Refused.', 'reason': str(e)}
            if running and not await self._halt():
                self.side.sid, self.side.roster = None, []
                return 200, {'ok': False, 'message': 'The last run did not stop.'}
            self.state = STARTING
            try:
                await asyncio.wait_for(self._start(), self.start_timeout)
            except Exception as e:
                log.error('[%s] start failed: %s', self.side.game, str(e) or type(e).__name__)
                self.side.sid, self.side.roster = None, []
                await self._halt()
                why = 'it took too long' if isinstance(e, asyncio.TimeoutError) else str(e)
                return 200, {'ok': False, 'message': f'The game did not start ({why}).'}
            self.state = RUNNING
            log.info('[%s] party session started (%d on the roster)', self.side.game, len(roster))
            return 200, {'ok': True}

    async def end(self, message):
        async with self.lock:
            try:
                p = protocol.open_message(self.side.key, message, 'end', self.side.game,
                                          self.side.guard)
            except protocol.Invalid as e:
                return 403, {'ok': False, 'message': 'Refused.', 'reason': str(e)}
            if p['sid'] != self.side.sid and self.state != IDLE:
                return 409, {'ok': False, 'message': 'Another session is running.',
                             'reason': 'session'}
            self.side.sid, self.side.roster = None, []
            if self.state != IDLE and not await self._halt():
                return 200, {'ok': False, 'message': 'The game did not stop.'}
            log.info('[%s] party session ended; runtime stopped', self.side.game)
            return 200, {'ok': True}

    async def abandon(self):
        """The runtime failed for good (the process is about to exit): stop admitting the session
        and tell the party once, bounded, so it does not show a game that is gone."""
        if self.side.sid is None or self.report is None:
            return False
        message = self.side.ended('abandoned')
        try:
            return bool(await asyncio.wait_for(self.report(message), REPORT_TIMEOUT + 1))
        except Exception:
            log.warning('[%s] could not tell the party the session was abandoned', self.side.game)
            return False


async def handle(managed, action, remote, headers, raw):
    """(status, body) for one control request: `action` is 'launch' or 'end'."""
    lower = {k.lower(): v for k, v in headers.items()}
    if remote not in LOOPBACK or any(lower.get(h) for h in PROXY_HEADERS):
        return 404, {'error': 'not_found'}
    if len(raw) > MAX_BODY:
        return 413, {'error': 'body_size'}
    try:
        body = json.loads(raw or b'{}')
    except ValueError:
        return 400, {'error': 'bad_json'}
    if not isinstance(body, dict):
        return 400, {'error': 'bad_json'}
    fn = managed.launch if action == 'launch' else managed.end
    return await fn(body.get('message'))


def party_url(value):
    """The party's base URL, only as a loopback http origin (its internal routes answer nothing
    else); None otherwise."""
    if not value:
        return None
    try:
        u = urlsplit(value.strip())
        host, port = u.hostname, u.port
        ok = (u.scheme == 'http' and host is not None and ipaddress.ip_address(host).is_loopback
              and port is not None and not u.username and not u.password
              and u.path in ('', '/') and not u.query and not u.fragment)
    except ValueError:
        ok = False
    return f'http://{host}:{port}' if ok else None


def configure(env, game):
    """(GameSide, party_url) when both halves are configured ($AVRANA_PARTY_KEYS holds
    <game>.key and $AVRANA_PARTY_URL is a loopback origin), else None: the runtime then runs
    always-on, as before AVR-134. The key is never logged."""
    keys, url = env.get(KEYS_ENV), party_url(env.get(PARTY_URL_ENV))
    if not keys:
        return None
    path = os.path.join(keys, f'{game}.key')
    if not os.path.exists(path):
        return None
    try:
        key = protocol.read_key(path)
    except (OSError, ValueError):
        log.error('[%s] party session key %s is unusable; running always-on', game, path)
        return None
    if url is None:
        log.error('[%s] %s is missing or not a loopback origin; running always-on',
                  game, PARTY_URL_ENV)
        return None
    return protocol.GameSide(key, game), url


def post_ended(base_url, message, timeout=REPORT_TIMEOUT):
    """One POST of an `ended` report; the HTTP status, or None. Blocking: run it off the loop."""
    req = urllib.request.Request(base_url + ENDED_PATH, method='POST',
                                 data=json.dumps({'message': message}).encode(),
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read()
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, OSError, ValueError):
        return None
