#!/usr/bin/env python3
"""A tiny client of Party Core's public HTTP API and an INSTALLED PACKAGE's Unix socket (AVR-39 proof).

Part of experiments/native-game/package-proof.sh; Linux, run as root, stdlib only. It plays the
roles of the phones and the host for the experimental Hello Party package (Games repository, the
game id `hello`), without a browser. It reuses the small HTTP helpers of driver.py (the AVR-236
stand-in driver), which is not edited, and talks to the game only through its documented routes
under /games/hello. Nothing about the game is known to the Party code under test: this file and the
proof script are the only places the id appears.

    package-driver.py                  two players and a late watcher; launch; tickets; redeems; each
                                       seat sees only its own secret word; strangers refused; each
                                       player says hello over the game's HTTP API; a reload returns
                                       the same seat; the game ends by itself and Party Core accepts
                                       the signed `ended` and shows the result; the host returns home
    package-driver.py --end [--during-live CMD ...]
                                       a second session the Host ends from Party. With --during-live
                                       the command (the rest of the line) runs while the session is
                                       live and MUST exit 1 with a refusal ("session running")
    package-driver.py --offered        Party Core offers the game (/party/api/state)
    package-driver.py --absent         Party Core no longer offers the game

Exit 0 on success; on failure exit 1 with one line `driver: FAIL <step>: <what was received>`. Lines
`driver: observe ...` are facts for the proof's log. No ticket, token, secret word or cookie value is
ever printed: only HTTP statuses, error codes the services send, and counts.
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))     # the AVR-236 helpers, unchanged
from driver import Fail, Phone, UnixConnection, exchange, leave_all, poll, short, want   # noqa: E402

GAME = 'hello'
GAME_BASE = '/games/hello'


def gpost(args, path, body, headers=None):
    conn = UnixConnection(args.game_socket, 30)
    return exchange(conn, 'POST', GAME_BASE + path, body, dict({'Host': 'localhost'}, **(headers or {})))


def observe(text):
    print(f'driver: observe {text}')


def wait_offered(watcher):
    poll('Party Core offers the game (from the installed package\'s contract)',
         lambda: (GAME in watcher.state().get('games', []), f'games {watcher.state().get("games")}'))


def seat_up(args):
    ana, ben = Phone(args, 'Ana'), Phone(args, 'Ben')
    for p in (ana, ben):
        status, v = p.post('join', {'name': p.name})
        want(f'join {p.name}', status == 200 and isinstance(v, dict) and v.get('me'), f'HTTP {status} {short(v)}')
    out = ana.host_post('session/launch', {'game': GAME}, 'launch')
    s = out.get('session') or {}
    want('launch', out.get('state') == 'active' and s.get('game') == GAME,
         f'state {out.get("state")!r}, session {s.get("state")!r} {s.get("detail")!r}')
    return ana, ben


def ticket_and_redeem(args, p, role='player'):
    status, t = p.post('session/ticket', {'game': GAME})
    want(f'ticket {p.name}', status == 200 and isinstance(t, dict) and t.get('role') == role,
         f'HTTP {status} {short(t)}')
    p.ticket = t['ticket']
    status, out, _ = gpost(args, '/api/redeem', {'ticket': p.ticket})
    want(f'redeem {p.name}', status == 200 and isinstance(out, dict) and out.get('ok') is True and out.get('role') == role,
         f'HTTP {status} {short(out)}')
    return out


def redeem_players(args, ana, ben):
    for p in (ana, ben):
        out = ticket_and_redeem(args, p)
        p.token, p.view = out['token'], out['view']
    want('the two players hold the two first seats', {ana.view.get('seat'), ben.view.get('seat')} == {0, 1},
         f'seats {ana.view.get("seat")!r} {ben.view.get("seat")!r}')
    secrets_ = [p.view['you']['secret'] for p in (ana, ben)]
    want('each seat is dealt its own secret word', all(isinstance(s, str) and s for s in secrets_) and secrets_[0] != secrets_[1],
         'the two secret words are missing or equal')
    for p, other in ((ana, ben), (ben, ana)):
        blob = json.dumps(p.view)
        want(f'{p.name}\'s view holds nothing of {other.name}\'s secret, ticket or token',
             other.view['you']['secret'] not in blob and other.ticket not in blob and other.token not in blob,
             'the view leaks the other seat')
    want('the two players have distinct game tokens', ana.token != ben.token, 'identical tokens')
    status, out, _ = gpost(args, '/api/redeem', {'ticket': ana.ticket})
    want('a ticket is single use', status == 403, f'a second redeem answered HTTP {status}')
    observe(f'seats: Ana {ana.view["seat"]}, Ben {ben.view["seat"]}; each holds a secret word of its own '
            f'(not shown); the shared board has {len(ana.view["board"])} greetings')


def strangers(args, ana, ben):
    zed = Phone(args, 'Zed')
    status, out = zed.post('session/ticket', {'game': GAME})
    want('an unseated device gets no ticket', status == 403, f'HTTP {status} {short(out)}')
    status, out, _ = gpost(args, '/api/redeem', {'ticket': 'x' * 120})
    want('a made-up ticket is refused at the game', status == 403, f'HTTP {status} {short(out)}')
    status, out, _ = gpost(args, '/api/poll', {'token': 'x' * 60, 'since': 0})
    want('a made-up game token reads nothing', status == 403, f'HTTP {status} {short(out)}')
    cy = Phone(args, 'Cy')
    status, v = cy.post('join', {'name': 'Cy'})
    want('join Cy', status == 200, f'HTTP {status} {short(v)}')
    out = ticket_and_redeem(args, cy, role='spectator')
    cy.token, cy.view = out['token'], out['view']
    blob = json.dumps(cy.view)
    want('a late member watches: no seat, no card, and no player\'s secret',
         cy.view['seat'] is None and cy.view['you'] is None
         and ana.view['you']['secret'] not in blob and ben.view['you']['secret'] not in blob,
         f'seat {cy.view["seat"]!r}')
    status, out, _ = gpost(args, '/api/greet', {'token': cy.token, 'text': 'hi'})
    want('a watcher cannot say hello', status == 403, f'HTTP {status} {short(out)}')
    return cy


def reconnect(args, p):
    before = p.view
    out = ticket_and_redeem(args, p)
    view = out['view']
    want(f'{p.name} reconnects to the same game token', out['token'] == p.token, 'a different token')
    want(f'{p.name} reconnects to the same seat, secret and board',
         view['seat'] == before['seat'] and view['you'] == before['you'] and view['board'] == before['board'],
         'the seat, card or board changed')
    observe(f'reconnect: {p.name} redeemed a fresh ticket and got the same seat, token, secret word and board')


def say_hello(args, p, text):
    status, out, _ = gpost(args, '/api/greet', {'token': p.token, 'text': text})
    want(f'{p.name} says hello', status == 200 and out.get('ok') is True, f'HTTP {status} {short(out)}')
    p.view = out['view']


def run_full(args):
    wait_offered(Phone(args, 'Watcher'))
    ana, ben = seat_up(args)
    redeem_players(args, ana, ben)
    cy = strangers(args, ana, ben)
    say_hello(args, ana, 'hello from Ana')
    status, seen, _ = gpost(args, '/api/poll', {'token': ben.token, 'since': ben.view['v']})
    want('Ben sees Ana\'s hello on the shared board', status == 200 and [e['text'] for e in seen['view']['board']] == ['hello from Ana'],
         f'HTTP {status}')
    ben.view = seen['view']
    status, out, _ = gpost(args, '/api/greet', {'token': ana.token, 'text': 'again'})
    want('a second hello from one seat is refused', status == 409 and short(out).startswith('already'), f'HTTP {status} {short(out)}')
    reconnect(args, ana)
    say_hello(args, ben, 'hello from Ben')
    want('after the last greeting the game is over', ben.view['over'] is True and ben.view['result'] == {'greetings': 2},
         f'over {ben.view["over"]!r}, result {ben.view["result"]!r}')
    status, out, _ = gpost(args, '/api/poll', {'token': cy.token, 'since': 0})
    want('the watcher reads the finished board', status == 200 and out['view']['over'] is True, f'HTTP {status}')

    def ended():
        s = ben.state().get('session') or {}
        return (s.get('state') == 'ended' and s.get('outcome') == 'completed',
                f'session {s.get("state")!r} outcome {s.get("outcome")!r}')
    poll('Party Core accepts the signed `ended` and shows the round ended completed', ended)
    summary = ben.state()['session'].get('result_summary')
    want('Party Core shows the party the accepted result (result_summary)',
         isinstance(summary, dict) and summary.get('game') == GAME and summary.get('mode') == 'cooperative', f'summary {summary!r}')
    got = {e['name']: e['standing'] for e in summary['players']}
    want('both players are shown as having won', got == {'Ana': 'won', 'Ben': 'won'}, f'got {got}')
    observe(f'party result_summary: game {summary["game"]}, mode {summary["mode"]}, standings {got}')
    ana.host_post('home', {}, 'host returns home')
    want('the party is home again', (ben.state().get('location') or {}).get('at') == 'home', 'not home')
    leave_all([cy, ben, ana])
    print('driver: ok (a complete session: launch, redeem, private words, hello over the HTTP API, reconnect, result accepted, home)')


def run_end(args):
    wait_offered(Phone(args, 'Watcher'))
    ana, ben = seat_up(args)
    redeem_players(args, ana, ben)
    if args.during_live:
        done = subprocess.run(args.during_live, cwd=args.cwd, capture_output=True, text=True, timeout=60)
        text = done.stdout + done.stderr
        want('removing the package while it has a session is refused', done.returncode == 1 and 'session running' in text,
             f'exit {done.returncode}, said: {text.strip()[:160]}')
        observe('remove during a live session: refused (exit 1) and said "session running"')
        status, out, _ = gpost(args, '/api/poll', {'token': ana.token, 'since': 0})
        want('and the live session is untouched by the attempt', status == 200, f'HTTP {status}')
    ana.host_post('session/end', {}, 'host ends the game')

    def ended():
        s = ben.state().get('session') or {}
        return (s.get('state') == 'ended' and s.get('outcome') == 'ended_by_host',
                f'session {s.get("state")!r} outcome {s.get("outcome")!r}')
    poll('Party Core shows the round ended by the host', ended)
    for p in (ana, ben):
        status, out, _ = gpost(args, '/api/poll', {'token': p.token, 'since': 0})
        want(f'{p.name}\'s game token reads nothing: the game holds no session', status == 403, f'HTTP {status} {short(out)}')
        status, out = p.post('session/ticket', {'game': GAME})
        want(f'{p.name} gets no new ticket: the session is over', status != 200, f'HTTP {status}')
    leave_all([ben, ana])
    print('driver: ok (the Host ended the game from Party: over for both phones)')


def run_offered(args):
    watcher = Phone(args, 'Watcher')
    wait_offered(watcher)
    print('driver: ok (the game is offered)')


def run_absent(args):
    watcher = Phone(args, 'Watcher')
    poll('Party Core stops offering the game', lambda: (GAME not in watcher.state().get('games', []), 'still offered'),
         timeout=20)
    print('driver: ok (the game is not offered)')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--end', action='store_true', help='a session the Host ends from Party')
    mode.add_argument('--offered', action='store_true', help='check Party Core offers the game')
    mode.add_argument('--absent', action='store_true', help='check Party Core does not offer the game')
    ap.add_argument('--party-host', default='127.0.0.1')
    ap.add_argument('--party-port', type=int, default=8191)
    ap.add_argument('--game-socket', default='/run/avrana-games/hello.sock')
    ap.add_argument('--cwd', default=None, help='where --during-live runs')
    ap.add_argument('--during-live', nargs=argparse.REMAINDER, default=None,
                    help='with --end: a command to run (and expect refused) while the session is live; last option')
    args = ap.parse_args(argv)
    try:
        (run_absent if args.absent else run_offered if args.offered else run_end if args.end else run_full)(args)
        return 0
    except Fail as e:
        print(f'driver: FAIL {e}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
