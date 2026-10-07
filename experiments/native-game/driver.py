#!/usr/bin/env python3
"""A tiny client of Party Core's public HTTP API and one native game's Unix socket (AVR-236 proof).

Part of experiments/native-game/proof.sh; Linux, run as root, stdlib only. It plays the roles a
room full of phones and the host's shell play, so a real Party Core and a real socket-activated
game can be exercised without a browser:

    driver.py             two phones join, the host launches `standin`, both get tickets and redeem
                          them at the game, strangers are refused, a player finishes, Party Core
                          shows the round ended `completed`, the host returns home, everyone leaves
    driver.py --hold      the same up to the redeems, then stop: the session stays live and what is
                          needed to resume is written to --state (0600)
    driver.py --end       the held session's host ends the game from Party Home (the shell's "end
                          game": POST /party/api/session/end), the end is verified, everyone leaves
    driver.py --absent    the game is no longer offered by Party Core (after provision-game --remove)

Exit 0 on success; on failure exit 1 with one line `driver: FAIL <step>: <what was received>`.
No ticket, token or cookie value is ever printed: only HTTP statuses and the error codes the
services themselves send.

The one thing it cannot see is the result Party Core keeps for the finished round: no public
route exposes it. The proof script reads the journal for that.
"""
import argparse
import http.client
import json
import os
import socket
import sys
import time

HOST = 'party.ci.test'                    # a name only the proof's party-core.json knows
ORIGIN = 'http://party.ci.test'
GAME = 'standin'
GAME_BASE = '/games/standin'
POLL_S = 0.3


class Fail(Exception):
    pass


def short(body):
    """What a service said about a refusal: its error code and message only, never the body."""
    if isinstance(body, dict):
        return ' '.join(str(body[k])[:80] for k in ('error', 'message', 'reason') if k in body) or 'no error code'
    return 'not a JSON object'


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, path, timeout):
        super().__init__('localhost', timeout=timeout)
        self.unix_path = path

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect(self.unix_path)
        self.sock = s


def exchange(conn, method, path, body, headers):
    data = json.dumps(body).encode() if method == 'POST' else None
    h = dict(headers)
    if data is not None:
        h['Content-Type'] = 'application/json'
    try:
        conn.request(method, path, body=data, headers=h)
        r = conn.getresponse()
        raw = r.read()
    except (OSError, http.client.HTTPException) as e:
        raise Fail(f'{method} {path}: {type(e).__name__}')
    finally:
        conn.close()
    try:
        parsed = json.loads(raw) if raw and r.getheader('Content-Type', '').startswith('application/json') else None
    except ValueError:
        parsed = None
    return r.status, parsed, r


class Phone:
    """One browser: a cookie jar, our Host and Origin, JSON requests to Party Core."""

    def __init__(self, args, name):
        self.args, self.name = args, name
        self.cookie_name = self.cookie = None
        self.ticket = self.token = None

    def req(self, method, path, body=None):
        h = {'Host': HOST}
        if self.cookie:
            h['Cookie'] = f'{self.cookie_name}={self.cookie}'
        if method == 'POST':
            h['Origin'] = ORIGIN
        conn = http.client.HTTPConnection(self.args.party_host, self.args.party_port, timeout=30)
        status, parsed, r = exchange(conn, method, path, body if body is not None else {}, h)
        sc = r.getheader('Set-Cookie')
        if sc:
            self.cookie_name, self.cookie = sc.split(';')[0].split('=', 1)
        return status, parsed

    def state(self):
        status, v = self.req('GET', '/party/api/state')
        if status != 200 or not isinstance(v, dict):
            raise Fail(f'state ({self.name}): HTTP {status}')
        return v

    def post(self, route, body=None):
        return self.req('POST', '/party/api/' + route, body)

    def host_post(self, route, body, step):
        """A host action: needs the current version, so ask for it and retry once if it moved."""
        for attempt in (1, 2):
            v = self.state()
            status, out = self.post(route, dict(body, if_version=v['version']))
            if status != 409 or not isinstance(out, dict) or out.get('error') != 'stale':
                break
        if status != 200:
            raise Fail(f'{step}: HTTP {status} {short(out)}')
        return out


def game_post(args, path, body, headers=None):
    conn = UnixConnection(args.game_socket, 30)
    return exchange(conn, 'POST', GAME_BASE + path, body, dict({'Host': 'localhost'}, **(headers or {})))


def poll(what, fn, timeout=15.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = fn()
        if last[0]:
            return last[1]
        time.sleep(POLL_S)
    raise Fail(f'{what}: not reached within {timeout:.0f}s ({last[1] if last else "no answer"})')


def want(step, condition, got):
    if not condition:
        raise Fail(f'{step}: {got}')


def wait_offered(args, phone):
    poll('Party Core offers the game', lambda: (GAME in phone.state().get('games', []),
                                                 f'games {phone.state().get("games")}'))


def seat(args):
    """Two players who join, and the host launches; returns (ana, ben)."""
    ana, ben = Phone(args, 'Ana'), Phone(args, 'Ben')
    for p in (ana, ben):
        status, v = p.post('join', {'name': p.name})
        want(f'join {p.name}', status == 200 and isinstance(v, dict) and v.get('me'), f'HTTP {status} {short(v)}')
    out = ana.host_post('session/launch', {'game': GAME}, 'launch')
    s = out.get('session') or {}
    want('launch', out.get('state') == 'active' and s.get('game') == GAME,
         f'state {out.get("state")!r}, session {s.get("state")!r} {s.get("detail")!r}')
    return ana, ben


def redeem_all(args, ana, ben):
    for p in (ana, ben):
        status, t = p.post('session/ticket', {'game': GAME})
        want(f'ticket {p.name}', status == 200 and isinstance(t, dict) and t.get('role') == 'player',
             f'HTTP {status} {short(t)}')
        p.ticket = t['ticket']
    seen = {}
    for p, other in ((ana, ben), (ben, ana)):
        status, out, _ = game_post(args, '/api/redeem', {'ticket': p.ticket})
        want(f'redeem {p.name}', status == 200 and isinstance(out, dict) and out.get('ok') is True,
             f'HTTP {status} {short(out)}')
        view = out.get('view') or {}
        want(f'redeem {p.name}: the view names only the caller',
             view.get('you') == p.name and other.name not in json.dumps(out) and other.ticket not in json.dumps(out),
             'the view does not name exactly the caller')
        want(f'redeem {p.name}: role', out.get('role') == 'player' and view.get('players') == 2,
             f'role {out.get("role")!r}, players {view.get("players")!r}')
        p.token = out['token']
        seen[p.name] = out
    want('the two players have distinct game tokens', ana.token != ben.token, 'identical tokens')
    status, out, _ = game_post(args, '/api/redeem', {'ticket': ana.ticket})
    want('a ticket is single use', status == 403, f'a second redeem answered HTTP {status}')


def strangers(args, ana):
    """A device that never joined, and a late member: neither is seated as a player."""
    stranger = Phone(args, 'Zed')
    status, out = stranger.post('session/ticket', {'game': GAME})
    want('an unseated device gets no ticket', status == 403, f'HTTP {status} {short(out)}')
    status, out, _ = game_post(args, '/api/redeem', {'ticket': 'x' * 120})
    want('a made-up ticket is refused at the game', status == 403, f'HTTP {status} {short(out)}')
    status, out, _ = game_post(args, '/api/redeem', {'ticket': ana.ticket + 'x'})
    want('an altered ticket is refused at the game', status == 403, f'HTTP {status} {short(out)}')
    cy = Phone(args, 'Cy')
    status, v = cy.post('join', {'name': 'Cy'})
    want('join Cy', status == 200, f'HTTP {status} {short(v)}')
    status, t = cy.post('session/ticket', {'game': GAME})
    want('a late member is seated as a spectator',
         status == 200 and isinstance(t, dict) and t.get('role') == 'spectator', f'HTTP {status} {short(t)}')
    status, out, _ = game_post(args, '/api/redeem', {'ticket': t['ticket']})
    want('the spectator redeems', status == 200 and out.get('role') == 'spectator', f'HTTP {status} {short(out)}')
    status, out, _ = game_post(args, '/api/finish', {'token': out['token']})
    want('a spectator cannot finish the round', status == 403, f'HTTP {status} {short(out)}')
    return cy


def page_side(args):
    """Control is not reachable from the page side: a request carrying a proxy header (which is
    what nginx always adds) never reaches the session routes, and the page itself is served."""
    status, out, _ = game_post(args, '/avrana/session/v0/launch', {'message': 'x'},
                               {'X-Forwarded-For': '10.0.0.9'})
    want('control through the front door is not found', status == 404, f'HTTP {status} {short(out)}')
    conn = UnixConnection(args.game_socket, 30)
    try:
        conn.request('GET', GAME_BASE + '/', headers={'Host': 'localhost'})
        r = conn.getresponse()
        r.read()
    except (OSError, http.client.HTTPException) as e:
        raise Fail(f'game page: {type(e).__name__}')
    finally:
        conn.close()
    want('the game page is served', r.status == 200, f'HTTP {r.status}')


def leave_all(phones):
    for p in phones:                                  # the host is last, so nobody inherits a stale party
        if p.cookie:
            p.post('leave')


def finish_round(args, ana, ben, cy):
    status, out, _ = game_post(args, '/api/finish', {'token': ana.token})
    want('the player finishes', status == 200 and isinstance(out, dict) and out.get('ok') is True,
         f'HTTP {status} {short(out)}')
    status, out, _ = game_post(args, '/api/finish', {'token': ana.token})
    want('a round finishes once', status == 403, f'a second finish answered HTTP {status}')

    def ended():
        v = ben.state()
        s = v.get('session') or {}
        return (s.get('state') == 'ended' and s.get('outcome') == 'completed',
                f'session {s.get("state")!r} outcome {s.get("outcome")!r}')
    poll('Party Core shows the round ended completed', ended)
    v = ben.state()
    want('the party is on the results screen', (v.get('location') or {}).get('at') == 'results',
         f'location {(v.get("location") or {}).get("at")!r}')
    ana.host_post('home', {}, 'host returns home')
    v = ben.state()
    want('the party is home again', (v.get('location') or {}).get('at') == 'home',
         f'location {(v.get("location") or {}).get("at")!r}')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--hold', action='store_true', help='stop with the session live; write --state')
    mode.add_argument('--end', action='store_true', help='the held session\'s host ends it from Party Home')
    mode.add_argument('--absent', action='store_true', help='check Party Core no longer offers the game')
    ap.add_argument('--state', default='/run/avrana-native-game-proof/driver.json')
    ap.add_argument('--party-host', default='127.0.0.1')
    ap.add_argument('--party-port', type=int, default=8191)
    ap.add_argument('--game-socket', default='/run/avrana-games/standin.sock')
    args = ap.parse_args(argv)
    try:
        if args.absent:
            watcher = Phone(args, 'Watcher')
            poll('Party Core stops offering the game', lambda: (GAME not in watcher.state().get('games', []),
                                                                 'still offered'), timeout=20)
            print('driver: ok (the game is no longer offered)')
            return 0
        if args.end:
            return end_held(args)
        wait_offered(args, Phone(args, 'Watcher'))
        ana, ben = seat(args)
        redeem_all(args, ana, ben)
        page_side(args)
        cy = strangers(args, ana)
        if args.hold:
            doc = {'phones': [{'name': p.name, 'cookie_name': p.cookie_name, 'cookie': p.cookie}
                              for p in (ana, ben, cy)]}
            os.makedirs(os.path.dirname(args.state), mode=0o700, exist_ok=True)
            fd = os.open(args.state, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(doc, f)
            print('driver: ok (session held live)')
            return 0
        finish_round(args, ana, ben, cy)
        leave_all([cy, ben, ana])
        print('driver: ok (full session: launch, redeem, finish, results, home)')
        return 0
    except Fail as e:
        print(f'driver: FAIL {e}', file=sys.stderr)
        return 1


def end_held(args):
    try:
        with open(args.state, encoding='utf-8') as f:
            doc = json.load(f)
    except (OSError, ValueError) as e:
        raise Fail(f'resume: cannot read the state file ({type(e).__name__})')
    phones = []
    for entry in doc['phones']:
        p = Phone(args, entry['name'])
        p.cookie_name, p.cookie = entry['cookie_name'], entry['cookie']
        phones.append(p)
    ana, ben, cy = phones
    v = ana.state()
    want('resume', (v.get('session') or {}).get('state') == 'active', f'session {(v.get("session") or {}).get("state")!r}')
    ana.host_post('session/end', {}, 'host ends the game')

    def ended():
        s = ben.state().get('session') or {}
        return (s.get('state') == 'ended' and s.get('outcome') == 'ended_by_host',
                f'session {s.get("state")!r} outcome {s.get("outcome")!r}')
    poll('Party Core shows the round ended by the host', ended)
    want('the party is home', (ben.state().get('location') or {}).get('at') == 'home', 'not home')
    leave_all([cy, ben, ana])
    os.unlink(args.state)
    print('driver: ok (held session ended by the host)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
