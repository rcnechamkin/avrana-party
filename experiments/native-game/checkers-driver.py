#!/usr/bin/env python3
"""A tiny client of Party Core's public HTTP API and the Checkers game's Unix socket (AVR-238 proof).

Part of experiments/native-game/checkers-proof.sh; Linux, run as root, stdlib only. It plays the
roles of two players' phones, a late watcher and the host, so a real Party Core and the real
socket-activated Checkers (Games repository, `python3 -m checkers`) can be exercised without a
browser. It reuses the small HTTP helpers of driver.py (the AVR-236 stand-in driver), which is not
edited, and talks to the game only through its documented routes under /games/checkers.

    checkers-driver.py            two phones join, the host launches `checkers`, tickets, redeems,
                                  strangers refused, a COMPLETE game is played with legal moves taken
                                  from each seat's own view until the rules end it, a mid-game
                                  reconnect returns the same seat, Party Core accepts the signed
                                  `ended` and shows the result to the party, the host returns home
    checkers-driver.py --end      a second session: two phones, one move, then the Host ends the game
                                  from Party (POST /party/api/session/end); the session is over for
                                  both phones and the game refuses their tokens
    checkers-driver.py --absent   the game is no longer offered by Party Core (after --remove)

Exit 0 on success; on failure exit 1 with one line `driver: FAIL <step>: <what was received>`.
Lines `driver: observe ...` are facts for the proof's log. No ticket, token or cookie value is ever
printed: only HTTP statuses, error codes the services themselves send, and board facts.
"""
import argparse
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))     # the AVR-236 helpers, unchanged
from driver import Fail, Phone, UnixConnection, exchange, leave_all, poll, short, want   # noqa: E402

GAME = 'checkers'
GAME_BASE = '/games/checkers'
MAX_PLIES = 600                       # the 80-half-move rule ends any game long before this
SEED = 238


def gpost(args, path, body, headers=None):
    conn = UnixConnection(args.game_socket, 30)
    return exchange(conn, 'POST', GAME_BASE + path, body, dict({'Host': 'localhost'}, **(headers or {})))


def observe(text):
    print(f'driver: observe {text}')


def wait_offered(watcher):
    poll('Party Core offers the game (from its contract)', lambda: (GAME in watcher.state().get('games', []),
                                                                  f'games {watcher.state().get("games")}'))


def seat_up(args):
    """Two players join and the host (the first) launches; returns (ana, ben)."""
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
    """Party Core hands this phone a ticket; the game redeems it. Returns the game's answer."""
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
        p.seat = p.view.get('seat')
    want('the two players hold the two sides', {ana.seat, ben.seat} == {'w', 'b'}, f'seats {ana.seat!r} {ben.seat!r}')
    want('the two players have distinct game tokens', ana.token != ben.token, 'identical tokens')
    for p, other in ((ana, ben), (ben, ana)):
        blob = repr(p.view)
        want(f'{p.name}\'s view carries nothing of {other.name}\'s ticket or token',
             other.ticket not in blob and other.token not in blob, 'the view leaks the other seat')
    first = ana if ana.seat == 'w' else ben
    second = ben if first is ana else ana
    want('only the side to move has controls: white has legal moves, black has none',
         first.view['turn'] == 'w' and first.view['moves'] and second.view['moves'] == [],
         f'turn {first.view["turn"]!r}, white moves {len(first.view["moves"])}, black moves {len(second.view["moves"])}')
    observe(f'seats: {first.name} plays white and moves first, {second.name} plays black; '
            f'white has {len(first.view["moves"])} legal moves, black {len(second.view["moves"])}')
    status, out, _ = gpost(args, '/api/redeem', {'ticket': ana.ticket})
    want('a ticket is single use', status == 403, f'a second redeem answered HTTP {status}')


def strangers(args, ana):
    """A device that never joined, forged tickets, and a late member (a spectator)."""
    zed = Phone(args, 'Zed')
    status, out = zed.post('session/ticket', {'game': GAME})
    want('an unseated device gets no ticket', status == 403, f'HTTP {status} {short(out)}')
    status, out, _ = gpost(args, '/api/redeem', {'ticket': 'x' * 120})
    want('a made-up ticket is refused at the game', status == 403, f'HTTP {status} {short(out)}')
    status, out, _ = gpost(args, '/api/redeem', {'ticket': ana.ticket + 'x'})
    want('an altered ticket is refused at the game', status == 403, f'HTTP {status} {short(out)}')
    status, out, _ = gpost(args, '/api/poll', {'token': 'x' * 60, 'since': 0})
    want('a made-up game token reads no board', status == 403, f'HTTP {status} {short(out)}')
    cy = Phone(args, 'Cy')
    status, v = cy.post('join', {'name': 'Cy'})
    want('join Cy', status == 200, f'HTTP {status} {short(v)}')
    out = ticket_and_redeem(args, cy, role='spectator')
    cy.token, cy.view = out['token'], out['view']
    want('a late member watches: no side, no controls',
         cy.view['seat'] is None and cy.view['moves'] == [], f'seat {cy.view["seat"]!r}, moves {len(cy.view["moves"])}')
    status, out, _ = gpost(args, '/api/move', {'token': cy.token, 'v': cy.view['v'], 'move': [0, 1]})
    want('a spectator cannot move', status == 403, f'HTTP {status} {short(out)}')
    status, out, _ = gpost(args, '/api/resign', {'token': cy.token})
    want('a spectator cannot resign', status == 403, f'HTTP {status} {short(out)}')
    return cy


def refusals_on_first_move(args, mover, other):
    """Before any move: the side to wait, a stale view and an illegal path each change nothing."""
    status, out, _ = gpost(args, '/api/move', {'token': other.token, 'v': other.view['v'], 'move': [0, 1]})
    want('the side not to move is refused (not_your_turn)', status == 409 and short(out).startswith('not_your_turn'),
         f'HTTP {status} {short(out)}')
    status, out, _ = gpost(args, '/api/move', {'token': mover.token, 'v': mover.view['v'] - 1, 'move': mover.view['moves'][0]})
    want('a move against a stale view is refused', status == 409 and short(out).startswith('stale'), f'HTTP {status} {short(out)}')
    status, out, _ = gpost(args, '/api/move', {'token': mover.token, 'v': mover.view['v'], 'move': [0, 1]})
    want('an illegal path is refused', status == 409 and short(out).startswith('illegal'), f'HTTP {status} {short(out)}')
    status, out, _ = gpost(args, '/api/poll', {'token': mover.token, 'since': 0})
    want('and none of that changed the board', status == 200 and out['view']['v'] == mover.view['v']
         and out['view']['board'] == mover.view['board'], f'HTTP {status}')


def reconnect(args, p):
    """The phone reloads mid-game: Party Core hands it a fresh ticket and the game gives the same
    seat, the same token and the board as it is now."""
    before = p.view
    out = ticket_and_redeem(args, p)
    view = out['view']
    want(f'{p.name} reconnects to the same game token', out['token'] == p.token, 'a different token')
    want(f'{p.name} reconnects to the same seat', view['seat'] == p.seat, f'seat {view["seat"]!r}')
    want(f'{p.name} reconnects to the current board', view['v'] == before['v'] and view['board'] == before['board']
         and view['turn'] == before['turn'], f'v {view["v"]} (was {before["v"]})')
    want(f'{p.name} still sees only its own controls', bool(view['moves']) == bool(before['moves']), 'controls changed')
    observe(f'reconnect: {p.name} redeemed a fresh ticket at v {view["v"]} and got the same seat, token and board')


def play(args, ana, ben):
    """Both seats play legal moves, always taken from the mover's own view, until the rules end it."""
    rng = random.Random(SEED)
    by_seat = {p.seat: p for p in (ana, ben)}
    plies, reconnected = 0, False
    refusals_on_first_move(args, by_seat['w'], by_seat['b'])
    while True:
        turn = by_seat['w'].view['turn']
        if turn is None:
            break
        mover, other = by_seat[turn], by_seat['b' if turn == 'w' else 'w']
        want(f'ply {plies + 1}: the mover has legal moves and the other seat has none',
             mover.view['moves'] and other.view['moves'] == [],
             f'mover {len(mover.view["moves"])}, other {len(other.view["moves"])}')
        path = rng.choice(mover.view['moves'])
        status, out, _ = gpost(args, '/api/move', {'token': mover.token, 'v': mover.view['v'], 'move': path})
        want(f'ply {plies + 1}: a legal move is accepted', status == 200 and out.get('ok') is True,
             f'HTTP {status} {short(out)}')
        mover.view = out['view']
        status, seen, _ = gpost(args, '/api/poll', {'token': other.token, 'since': other.view['v']})
        want(f'ply {plies + 1}: the other seat sees the move', status == 200 and seen.get('ok') is True,
             f'HTTP {status} {short(seen)}')
        other.view = seen['view']
        want(f'ply {plies + 1}: both seats see the same board and version',
             other.view['v'] == mover.view['v'] and other.view['board'] == mover.view['board'],
             f'v {mover.view["v"]} / {other.view["v"]}')
        plies += 1
        if plies == 6 and not reconnected:
            reconnect(args, other)
            reconnected = True
        want('the game ends by its own rules before the safety cap', plies < MAX_PLIES, f'{plies} plies and still running')
    want('the game was reconnected mid-way', reconnected, 'the game ended before ply 6')
    return plies


def finish(args, ana, ben, cy, plies):
    by_seat = {p.seat: p for p in (ana, ben)}
    for p in (ana, ben, cy):                                       # each reads the final board
        status, out, _ = gpost(args, '/api/poll', {'token': p.token, 'since': 0})
        want(f'{p.name} reads the final board', status == 200 and out['view']['result'] is not None,
             f'HTTP {status} {short(out)}')
        p.view = out['view']
    res = ana.view['result']
    want('all three see the same ending', ben.view['result'] == res == cy.view['result'], 'the results differ')
    want('the game ended naturally, not by resignation', res['ending'] in ('captured', 'blocked', 'drawn'),
         f'ending {res["ending"]!r}')
    want('the game ended with no side to move', ana.view['turn'] is None and ben.view['moves'] == [], 'still has a turn')
    status, out, _ = gpost(args, '/api/move', {'token': by_seat['w'].token, 'v': by_seat['w'].view['v'], 'move': [0, 1]})
    want('no move is accepted after the end', status == 409 and short(out).startswith('over'), f'HTTP {status} {short(out)}')
    winner = res['winner']
    observe(f'game over after {res["plies"]} plies ({plies} played by this driver): ending {res["ending"]}, '
            f'winner {winner or "none (draw)"}; white is {by_seat["w"].name}, black is {by_seat["b"].name}')

    def ended():
        s = ben.state().get('session') or {}
        return (s.get('state') == 'ended' and s.get('outcome') == 'completed',
                f'session {s.get("state")!r} outcome {s.get("outcome")!r}')
    poll('Party Core shows the round ended completed', ended)
    s = ben.state()['session']
    summary = s.get('result_summary')
    want('Party Core shows the party the accepted result (result_summary)',
         isinstance(summary, dict) and summary.get('game') == GAME and summary.get('mode') == 'competitive', f'summary {summary!r}')
    want_standing = {p.name: ('draw' if winner is None else 'won' if p.seat == winner else 'lost') for p in (ana, ben)}
    got = {e['name']: e['standing'] for e in summary['players']}
    want('the party shows the standings the game reported', got == want_standing, f'got {got}, wanted {want_standing}')
    observe(f'party result_summary: game {summary["game"]}, mode {summary["mode"]}, standings {got}')
    want('the party is on the results screen', (ben.state().get('location') or {}).get('at') == 'results',
         f'location {(ben.state().get("location") or {}).get("at")!r}')
    ana.host_post('home', {}, 'host returns home')
    want('the party is home again', (ben.state().get('location') or {}).get('at') == 'home',
         f'location {(ben.state().get("location") or {}).get("at")!r}')


def run_full(args):
    wait_offered(Phone(args, 'Watcher'))
    ana, ben = seat_up(args)
    redeem_players(args, ana, ben)
    cy = strangers(args, ana)
    plies = play(args, ana, ben)
    finish(args, ana, ben, cy, plies)
    leave_all([cy, ben, ana])
    print('driver: ok (a complete game: launch, redeem, reconnect, played to its end, result accepted, home)')


def run_end(args):
    wait_offered(Phone(args, 'Watcher'))
    ana, ben = seat_up(args)
    redeem_players(args, ana, ben)
    by_seat = {p.seat: p for p in (ana, ben)}
    white = by_seat['w']
    status, out, _ = gpost(args, '/api/move', {'token': white.token, 'v': white.view['v'], 'move': white.view['moves'][0]})
    want('a move is made in the second session', status == 200, f'HTTP {status} {short(out)}')
    ana.host_post('session/end', {}, 'host ends the game')

    def ended():
        s = ben.state().get('session') or {}
        return (s.get('state') == 'ended' and s.get('outcome') == 'ended_by_host',
                f'session {s.get("state")!r} outcome {s.get("outcome")!r}')
    poll('Party Core shows the round ended by the host', ended)
    want('the party is home', (ben.state().get('location') or {}).get('at') == 'home', 'not home')
    want('the host\'s own phone agrees', (ana.state().get('session') or {}).get('state') == 'ended', 'not ended')
    for p in (ana, ben):
        status, out, _ = gpost(args, '/api/poll', {'token': p.token, 'since': 0})
        want(f'{p.name}\'s game token reads nothing: the game holds no session', status == 403, f'HTTP {status} {short(out)}')
        status, out, _ = gpost(args, '/api/move', {'token': p.token, 'v': 1, 'move': [0, 1]})
        want(f'{p.name}\'s game token moves nothing', status == 403, f'HTTP {status} {short(out)}')
        status, out = p.post('session/ticket', {'game': GAME})
        want(f'{p.name} gets no new ticket: the session is over', status != 200, f'HTTP {status}')
    status, out, _ = gpost(args, '/api/redeem', {'ticket': ana.ticket})
    want('and the old ticket buys nothing', status == 403, f'HTTP {status}')
    leave_all([ben, ana])
    print('driver: ok (the Host ended the game from Party: over for both phones, the game refuses their tokens)')


def run_absent(args):
    watcher = Phone(args, 'Watcher')
    poll('Party Core stops offering the game', lambda: (GAME not in watcher.state().get('games', []), 'still offered'),
         timeout=20)
    print('driver: ok (the game is no longer offered)')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--end', action='store_true', help='a session the Host ends from Party')
    mode.add_argument('--absent', action='store_true', help='check Party Core no longer offers the game')
    ap.add_argument('--party-host', default='127.0.0.1')
    ap.add_argument('--party-port', type=int, default=8191)
    ap.add_argument('--game-socket', default='/run/avrana-games/checkers.sock')
    args = ap.parse_args(argv)
    try:
        (run_absent if args.absent else run_end if args.end else run_full)(args)
        return 0
    except Fail as e:
        print(f'driver: FAIL {e}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
