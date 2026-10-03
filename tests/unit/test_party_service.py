"""Party Core v0 over real HTTP on 127.0.0.1 (avrana.party.service + identity)."""
import http.client
import io
import json
import os
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr

from avrana.party import identity, service

HOST = 'party.test'
ORIGIN = 'https://party.test'
BLUFF = {'bluff': {'id': 'bluff', 'max_players': 6, 'late_join': 'spectator_only'}}
TWO_GAMES = dict(BLUFF, bomber={'id': 'bomber', 'max_players': 4, 'late_join': 'spectator_only'})


class FakeLink:
    def __init__(self, ok=True):
        self.ok = ok
        self.launched = []
        self.ended = []

    def launch(self, session, roster):
        self.launched.append((session.id, roster))
        return self.ok, None if self.ok else 'Games server is down.'

    def end(self, session):
        self.ended.append(session.id)
        return True


class Phone:
    """A minimal browser: one cookie jar, JSON requests, our Host and Origin."""

    def __init__(self, port, origin=ORIGIN, host=HOST):
        self.port, self.origin, self.host = port, origin, host
        self.cookie = None
        self.last_set_cookie = None

    def req(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=40)
        h = {'Host': self.host}
        if self.cookie:
            h['Cookie'] = f'{identity.COOKIE}={self.cookie}'
        data = None
        if method == 'POST':
            data = json.dumps(body or {}).encode()
            h.update({'Origin': self.origin, 'Content-Type': 'application/json'})
        h.update(headers or {})
        conn.request(method, path, body=data, headers=h)
        r = conn.getresponse()
        raw = r.read()
        sc = r.getheader('Set-Cookie')
        self.last_set_cookie = sc
        if sc:
            self.cookie = sc.split(';')[0].split('=', 1)[1]
        conn.close()
        return r.status, (json.loads(raw) if raw else None), r

    def state(self, **q):
        qs = '&'.join(f'{k}={v}' for k, v in q.items())
        return self.req('GET', '/party/api/state' + (f'?{qs}' if qs else ''))

    def post(self, path, body=None, **kw):
        return self.req('POST', '/party/api/' + path, body, **kw)


class ServiceCase(unittest.TestCase):
    link_ok = True
    games = BLUFF

    def make_link(self):
        return FakeLink(self.link_ok)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = identity.DeviceStore(os.path.join(self.tmp.name, 'devices.json'))
        self.link = self.make_link()
        self.svc = service.PartyService(self.store, self.games, self.link)
        cfg = service.Config({HOST}, {ORIGIN}, secure_cookie=True)
        self.log = io.StringIO()
        self.server = service.make_server(self.svc, cfg, port=0)
        self.port = self.server.server_address[1]
        self._err = redirect_stderr(self.log)
        self._err.__enter__()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self._err.__exit__(None, None, None)
        self.tmp.cleanup()

    def phone(self, **kw):
        return Phone(self.port, **kw)


class Identity(ServiceCase):
    def test_looking_issues_no_cookie_and_joins_nobody(self):
        p = self.phone()
        status, view, _ = p.state()
        self.assertEqual(status, 200)
        self.assertIsNone(p.last_set_cookie)
        self.assertIsNone(view['me'])
        self.assertEqual(self.store.by_hash, {})

    def test_join_issues_a_production_cookie(self):
        p = self.phone()
        status, view, _ = p.post('join', {'name': 'Ana'})
        self.assertEqual(status, 200)
        attrs = [a.strip() for a in p.last_set_cookie.split(';')]
        self.assertEqual(attrs[0].split('=')[0], 'avrana_device')
        for want in ('Path=/party/', 'HttpOnly', 'Secure', 'SameSite=Lax'):
            self.assertIn(want, attrs)
        self.assertRegex(p.cookie, identity.TOKEN_RE)
        self.assertEqual(view['me']['name'], 'Ana')
        self.assertTrue(view['me']['host'])

    def test_the_token_never_appears_in_a_body_the_store_or_the_log(self):
        p = self.phone()
        _, view, _ = p.post('join', {'name': 'Ana'})
        _, view2, _ = p.state()
        text = json.dumps([view, view2]) + open(self.store.path, encoding='utf-8').read()
        text += self.log.getvalue()
        self.assertNotIn(p.cookie, text)
        self.assertNotIn('device-', json.dumps([view, view2]))
        self.assertEqual(os.stat(self.store.path).st_mode & 0o077 if os.name == 'posix' else 0, 0)

    def test_a_forged_or_unknown_cookie_never_becomes_an_identity(self):
        p = self.phone()
        p.cookie = 'A' * 43                                   # well-formed, never issued
        status, view, _ = p.state()
        self.assertIsNone(view['me'])
        status, _, _ = p.post('heartbeat')
        self.assertEqual(status, 403)
        status, view, _ = p.post('join', {'name': 'Mallory'})
        self.assertEqual(status, 200)
        self.assertNotEqual(p.cookie, 'A' * 43)               # a fresh server-issued token

    def test_the_same_cookie_is_the_same_member(self):
        p = self.phone()
        _, v1, _ = p.post('join', {'name': 'Ana'})
        _, v2, _ = p.post('join', {'name': 'Ana'})
        self.assertIsNone(p.last_set_cookie)
        self.assertEqual(v1['me']['id'], v2['me']['id'])
        self.assertEqual(len(v2['members']), 1)

    def test_identity_survives_a_service_restart(self):
        p = self.phone()
        p.post('join', {'name': 'Ana'})
        again = identity.DeviceStore(self.store.path)
        self.assertIsNotNone(again.resolve(p.cookie))


class Guards(ServiceCase):
    def test_unknown_host_is_refused(self):
        status, body, _ = self.phone(host='evil.example').state()
        self.assertEqual((status, body['error']), (421, 'unknown_host'))

    def test_post_needs_our_origin_json_and_a_small_body(self):
        p = self.phone(origin='https://evil.example')
        self.assertEqual(p.post('join', {'name': 'Ana'})[0], 403)
        p = self.phone()
        self.assertEqual(p.post('join', {'name': 'Ana'}, headers={'Content-Type': 'text/plain'})[0], 415)
        try:                        # refused unread: the OS may reset before the client reads 413
            self.assertEqual(p.post('join', {'name': 'x' * 9000})[0], 413)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass
        self.assertEqual(self.store.by_hash, {})

    def test_bad_names_mint_nothing(self):
        p = self.phone()
        status, body, _ = p.post('join', {'name': 'Admin'})
        self.assertEqual((status, body['error']), (400, 'bad_name'))
        self.assertIsNone(p.cookie)
        self.assertEqual(self.store.by_hash, {})

    def test_every_response_is_no_store(self):
        _, _, r = self.phone().state()
        self.assertEqual(r.getheader('Cache-Control'), 'no-store')

    def test_log_has_paths_only(self):
        p = self.phone()
        p.post('join', {'name': 'Ana'})
        p.state(since=1, wait=0)
        self.assertIn('/party/api/state', self.log.getvalue())
        self.assertNotIn('since=', self.log.getvalue())


class Flow(ServiceCase):
    def test_long_poll_wakes_on_change(self):
        a, b = self.phone(), self.phone()
        _, v, _ = a.post('join', {'name': 'Ana'})
        got = {}

        def poll():
            got['t0'] = time.monotonic()
            got['view'] = a.state(since=v['version'], wait=10)[1]
            got['t1'] = time.monotonic()
        t = threading.Thread(target=poll)
        t.start()
        time.sleep(0.3)
        b.post('join', {'name': 'Ben'})
        t.join(5)
        self.assertEqual([m['name'] for m in got['view']['members']], ['Ana', 'Ben'])
        self.assertLess(got['t1'] - got['t0'], 5)

    def test_launch_and_end_through_the_game_link(self):
        a, b = self.phone(), self.phone()
        _, v, _ = a.post('join', {'name': 'Ana'})
        _, v, _ = b.post('join', {'name': 'Ben'})
        status, body, _ = b.post('session/launch', {'game': 'bluff', 'if_version': v['version']})
        self.assertEqual((status, body['error']), (403, 'not_host'))
        _, v, _ = a.state()
        status, body, _ = a.post('session/launch', {'game': 'bluff', 'if_version': v['version'] - 1})
        self.assertEqual((status, body['error']), (409, 'stale'))
        status, v, _ = a.post('session/launch', {'game': 'bluff', 'if_version': v['version']})
        self.assertEqual((status, v['state'], v['session']['my_role']), (200, 'active', 'player'))
        sid, roster = self.link.launched[0]
        self.assertEqual([r['name'] for r in roster], ['Ana', 'Ben'])
        self.assertNotIn('member-', json.dumps(roster))
        _, bv, _ = b.state()
        self.assertEqual([m['presence'] for m in bv['members']], ['playing', 'playing'])
        status, v, _ = a.post('session/end', {'if_version': v['version']})
        self.assertEqual((status, v['state'], v['session']['outcome']), (200, 'lobby', 'ended_by_host'))
        self.assertEqual(self.link.ended, [sid])

    def test_leave_and_rename(self):
        a, b = self.phone(), self.phone()
        a.post('join', {'name': 'Ana'})
        b.post('join', {'name': 'Ben'})
        _, v, _ = b.post('rename', {'name': 'Benji'})
        self.assertEqual(v['me']['name'], 'Benji')
        _, v, _ = a.post('leave')
        self.assertIsNone(v['me'])
        _, v, _ = b.state()
        self.assertTrue(v['me']['host'])


class HostLaunch(ServiceCase):
    """AVR-20/AVR-127: the host's launch is the party's one transition; every member observes it
    through the long poll Party Home already uses, and it survives reconnects and succession."""

    def table(self, *names):
        phones = [self.phone() for _ in names]
        for p, n in zip(phones, names):
            p.post('join', {'name': n})
        return phones

    def poll_until(self, p, since, done, limit=10):
        """Long-poll like Party Home: every view seen until done(view)."""
        seen = []
        deadline = time.monotonic() + limit
        while time.monotonic() < deadline:
            _, v, _ = p.state(since=since, wait=5)
            seen.append(v)
            if done(v):
                return seen
            since = v['version']
        self.fail(f'never converged: {[x["state"] for x in seen]}')

    def test_one_host_launch_is_one_transition_every_member_observes(self):
        ana, ben, cy = self.table('Ana', 'Ben', 'Cy')
        _, v, _ = ana.state()
        self.assertEqual(v['games'], ['bluff'])
        _, bv, _ = ben.state()
        self.assertEqual((bv['games'], bv['me']['host']), (['bluff'], False))
        seen = {}

        def follow(name, p, since):
            seen[name] = self.poll_until(p, since, lambda x: x['state'] == 'active')
        followers = [threading.Thread(target=follow, args=(n, p, bv['version']))
                     for n, p in (('ben', ben), ('cy', cy))]
        for t in followers:
            t.start()
        time.sleep(0.3)
        _, v, _ = ana.state()
        status, v, _ = ana.post('session/launch', {'game': 'bluff', 'if_version': v['version']})
        self.assertEqual((status, v['state']), (200, 'active'))
        for t in followers:
            t.join(15)
        self.assertEqual(len(self.link.launched), 1)                  # one host action, one game
        sid = v['session']['id']
        for name in ('ben', 'cy'):
            sessions = {x['session']['id'] for x in seen[name] if x['session']}
            self.assertEqual(sessions, {sid}, name)                   # nobody saw another session
            self.assertEqual(seen[name][-1]['session']['my_role'], 'player')
            self.assertLessEqual(len(seen[name]), 3)                  # launching, active (+ presence)
        # the double tap and the late second launch are refused; still exactly one session
        status, body, _ = ana.post('session/launch', {'game': 'bluff', 'if_version': bv['version']})
        self.assertEqual((status, body['error']), (409, 'stale'))
        _, v, _ = ana.state()
        status, body, _ = ana.post('session/launch', {'game': 'bluff', 'if_version': v['version']})
        self.assertEqual((status, body['error']), (409, 'busy'))
        self.assertEqual(len(self.link.launched), 1)
        _, v, _ = cy.state()
        self.assertEqual([m['presence'] for m in v['members']], ['playing'] * 3)   # still members

    def test_a_member_who_is_not_host_can_neither_launch_nor_end(self):
        ana, ben = self.table('Ana', 'Ben')
        _, v, _ = ben.state()
        status, body, _ = ben.post('session/launch', {'game': 'bluff', 'if_version': v['version']})
        self.assertEqual((status, body['error']), (403, 'not_host'))
        stranger = self.phone()
        status, body, _ = stranger.post('session/launch', {'game': 'bluff', 'if_version': v['version']})
        self.assertEqual((status, body['error']), (403, 'not_member'))
        self.assertEqual(self.link.launched, [])
        _, v, _ = ana.state()
        _, v, _ = ana.post('session/launch', {'game': 'bluff', 'if_version': v['version']})
        status, body, _ = ben.post('session/end', {'if_version': v['version']})
        self.assertEqual((status, body['error']), (403, 'not_host'))
        self.assertEqual(ben.state()[1]['state'], 'active')

    def test_reconnecting_and_stale_clients_resolve_to_the_active_game(self):
        ana, ben = self.table('Ana', 'Ben')
        _, old, _ = ben.state()
        _, v, _ = ana.state()
        _, v, _ = ana.post('session/launch', {'game': 'bluff', 'if_version': v['version']})
        sid = v['session']['id']
        t0 = time.monotonic()
        _, stale, _ = ben.state(since=old['version'], wait=20)        # an old version: at once
        self.assertLess(time.monotonic() - t0, 2)
        self.assertEqual((stale['state'], stale['session']['id']), ('active', sid))
        _, fresh, _ = ben.state()                                     # a reload: no version at all
        self.assertEqual((fresh['state'], fresh['session']['id'], fresh['session']['my_role']),
                         ('active', sid, 'player'))
        late = self.phone()
        _, lv, _ = late.post('join', {'name': 'Cy'})                  # joins mid-game
        self.assertEqual((lv['state'], lv['session']['id'], lv['session']['my_role']),
                         ('active', sid, 'spectator'))

    def test_the_host_leaving_mid_game_hands_over_and_the_game_goes_on(self):
        ana, ben = self.table('Ana', 'Ben')
        _, v, _ = ana.state()
        _, v, _ = ana.post('session/launch', {'game': 'bluff', 'if_version': v['version']})
        sid = v['session']['id']
        _, gone, _ = ana.post('leave')
        self.assertIsNone(gone['me'])
        _, v, _ = ben.state()
        self.assertEqual((v['me']['host'], v['state'], v['session']['id'], v['session']['my_role']),
                         (True, 'active', sid, 'player'))
        _, v, _ = ben.post('session/end', {'if_version': v['version']})
        self.assertEqual((v['state'], v['session']['outcome']), ('lobby', 'ended_by_host'))
        self.assertEqual(self.link.ended, [sid])


class ProviderLink:
    """A game link that records every call in order, as one exclusive runtime would see it:
    `running` is the set of sessions the runtimes believe are on. `end_delay` stretches the time
    the old game takes to reset; `end_ok` is whether it confirms."""

    def __init__(self, end_delay=0.0, end_ok=True):
        self.calls, self.running, self.overlaps = [], set(), []
        self.end_delay, self.end_ok = end_delay, end_ok
        self.lock = threading.Lock()

    def launch(self, session, roster):
        with self.lock:
            if self.running:
                self.overlaps.append((set(self.running), session.id))
            self.running.add(session.id)
            self.calls.append(('launch', session.game_id, session.id))
        return True, None

    def end(self, session):
        time.sleep(self.end_delay)
        with self.lock:
            self.calls.append(('end', session.game_id, session.id))
            if self.end_ok:
                self.running.discard(session.id)
        return self.end_ok


class PartyNavigation(ServiceCase):
    """AVR-128 over real HTTP: one Party activity at a time, host-only navigation, and followers
    (Party Home or a game page, both long-polling /party/api/state) observing each committed move."""
    games = TWO_GAMES

    def make_link(self):
        return ProviderLink(end_delay=0.4)

    def table(self, *names):
        phones = [self.phone() for _ in names]
        for p, n in zip(phones, names):
            p.post('join', {'name': n})
        return phones

    def start(self, host, game='bluff'):
        _, v, _ = host.state()
        status, v, _ = host.post('session/launch', {'game': game, 'if_version': v['version']})
        self.assertEqual((status, v['state']), (200, 'active'))
        return v

    def watch(self, phone, since, done, seen, limit=15):
        def run():
            s = since
            deadline = time.monotonic() + limit
            while time.monotonic() < deadline:
                _, v, _ = phone.state(since=s, wait=5)
                seen.append(v)
                if done(v):
                    return
                s = v['version']
        t = threading.Thread(target=run)
        t.start()
        return t

    def test_host_switch_ends_the_old_runtime_before_the_next_starts_and_followers_move(self):
        ana, ben = self.table('Ana', 'Ben')
        first = self.start(ana)
        _, bv, _ = ben.state()
        self.assertEqual((bv['nav']['to'], bv['nav']['game']), ('game', 'bluff'))
        seen = []
        t = self.watch(ben, bv['version'], lambda v: v['nav']['game'] == 'bomber', seen)
        time.sleep(0.2)
        status, v, _ = ana.post('session/switch', {'game': 'bomber', 'if_version': first['version']})
        t.join(20)
        self.assertEqual((status, v['state'], v['session']['game'], v['nav']['game']),
                         (200, 'active', 'bomber', 'bomber'))
        self.assertEqual([c[:2] for c in self.link.calls],
                         [('launch', 'bluff'), ('end', 'bluff'), ('launch', 'bomber')])
        self.assertEqual(self.link.overlaps, [])                  # never two runtimes at once
        # the follower saw "switching" and then the next game, never a home detour
        self.assertIn('bomber', [x['switching_to'] for x in seen])
        self.assertNotIn('home', [x['nav']['to'] for x in seen])
        self.assertEqual(seen[-1]['nav']['seq'], bv['nav']['seq'] + 1)
        self.assertEqual(seen[-1]['session']['my_role'], 'player')

    def test_followers_already_in_a_game_go_home_on_the_host_end(self):
        ana, ben = self.table('Ana', 'Ben')
        v = self.start(ana)
        _, bv, _ = ben.state()
        seen = []
        t = self.watch(ben, bv['version'], lambda x: x['nav']['to'] == 'home', seen)
        time.sleep(0.2)
        status, v, _ = ana.post('session/end', {'if_version': v['version']})
        t.join(20)
        self.assertEqual((status, seen[-1]['nav']['to'], seen[-1]['nav']['from']),
                         (200, 'home', 'bluff'))

    def test_nobody_but_the_host_moves_the_party_and_leave_moves_only_you(self):
        ana, ben, cy = self.table('Ana', 'Ben', 'Cy')
        v = self.start(ana)
        _, bv, _ = ben.state()
        for path, body in (('session/switch', {'game': 'bomber'}), ('session/end', {}),
                           ('session/launch', {'game': 'bomber'})):
            status, r, _ = ben.post(path, dict(body, if_version=bv['version']))
            self.assertEqual((path, status, r['error']), (path, 403, 'not_host'))
        stranger = self.phone()
        status, r, _ = stranger.post('session/switch', {'game': 'bomber', 'if_version': bv['version']})
        self.assertEqual((status, r['error']), (403, 'not_member'))
        status, r, _ = ben.post('leave')
        self.assertEqual(status, 200)
        _, cv, _ = cy.state()
        self.assertEqual((cv['state'], cv['session']['game'], cv['nav']['seq']),
                         ('active', 'bluff', v['nav']['seq']))
        self.assertEqual([c[:2] for c in self.link.calls], [('launch', 'bluff')])

    def test_stale_and_concurrent_navigation_leave_exactly_one_activity(self):
        ana, ben = self.table('Ana', 'Ben')
        v = self.start(ana)
        tabs = [self.phone() for _ in range(6)]                   # six of the host's tabs
        for tab in tabs:
            tab.cookie = ana.cookie
        results = []

        def fire(tab, i):
            path = ('session/switch', 'session/launch')[i % 2]
            game = ('bomber', 'bluff')[i % 3 == 0]
            status, body, _ = tab.post(path, {'game': game, 'if_version': v['version']})
            results.append((path, status, body.get('error')))
        threads = [threading.Thread(target=fire, args=(t, i)) for i, t in enumerate(tabs)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(20)
        wins = [r for r in results if r[1] == 200]
        self.assertEqual(len(wins), 1, results)                   # one move wins
        self.assertTrue(all(r[2] in ('stale', 'busy') for r in results if r[1] != 200), results)
        self.assertEqual(self.link.overlaps, [])
        _, now, _ = ben.state()
        self.assertIn(now['state'], ('active', 'lobby'))
        live = [c for c in self.link.calls if c[0] == 'launch']
        ended = {c[2] for c in self.link.calls if c[0] == 'end'}
        self.assertLessEqual(len([c for c in live if c[2] not in ended]), 1)
        # an old tab still holding the first version is refused; the party does not move
        status, body, _ = ana.post('session/switch', {'game': 'bomber', 'if_version': v['version']})
        self.assertEqual((status, body['error']), (409, 'stale'))

    def test_launch_while_a_switch_is_ending_is_refused(self):
        ana, _ = self.table('Ana', 'Ben')
        v = self.start(ana)
        done = []
        t = threading.Thread(target=lambda: done.append(
            ana.post('session/switch', {'game': 'bomber', 'if_version': v['version']})))
        t.start()
        time.sleep(0.15)                                          # the old game is still resetting
        _, mid, _ = ana.state()
        self.assertEqual((mid['state'], mid['switching_to']), ('ending', 'bomber'))
        status, body, _ = ana.post('session/launch', {'game': 'bluff', 'if_version': mid['version']})
        self.assertEqual((status, body['error']), (409, 'busy'))
        t.join(20)
        self.assertEqual(done[0][1]['session']['game'], 'bomber')
        self.assertEqual(self.link.overlaps, [])


class UnconfirmedSwitch(PartyNavigation):
    def make_link(self):
        return ProviderLink(end_ok=False)

    def test_host_switch_ends_the_old_runtime_before_the_next_starts_and_followers_move(self):
        ana, ben = self.table('Ana', 'Ben')
        v = self.start(ana)
        status, v, _ = ana.post('session/switch', {'game': 'bomber', 'if_version': v['version']})
        self.assertEqual((status, v['state'], v['nav']['to'], v['switching_to']),
                         (200, 'lobby', 'home', None))
        self.assertIn('did not stop', v['session']['detail'])
        self.assertEqual([c[:2] for c in self.link.calls], [('launch', 'bluff'), ('end', 'bluff')])

    test_stale_and_concurrent_navigation_leave_exactly_one_activity = None
    test_launch_while_a_switch_is_ending_is_refused = None


class PregameHttp(ServiceCase):
    """AVR-129 over HTTP: setup, choices and the host's start, as Party Home and game pages see
    them through the long poll; the game link is used only once the round starts."""
    games = dict(TWO_GAMES, bluff={'id': 'bluff', 'min_players': 2, 'max_players': 6,
                                   'late_join': 'spectator_only', 'pregame': True})

    def test_followers_see_setup_then_the_round_and_the_link_waits_for_the_start(self):
        ana, ben = (self.phone(), self.phone())
        ana.post('join', {'name': 'Ana'})
        ben.post('join', {'name': 'Ben'})
        _, bv, _ = ben.state()
        seen = []

        def follow():
            since = bv['version']
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                _, v, _ = ben.state(since=since, wait=5)
                seen.append(v)
                if v['state'] == 'active':
                    return
                since = v['version']
        t = threading.Thread(target=follow)
        t.start()
        time.sleep(0.2)
        _, v, _ = ana.state()
        status, v, _ = ana.post('session/launch', {'game': 'bluff', 'if_version': v['version']})
        self.assertEqual((status, v['state'], self.link.launched), (200, 'setup', []))
        self.assertEqual(v['session']['setup']['waiting'], [m['id'] for m in v['members']])
        ana.post('session/choice', {'choice': 'player'})
        status, v, _ = ben.post('session/choice', {'choice': 'player'})
        self.assertEqual((status, v['session']['setup']['mine'], v['session']['setup']['blocker']),
                         (200, 'player', None))
        status, body, _ = ana.post('session/start', {'if_version': v['version'] - 1})
        self.assertEqual((status, body['error']), (409, 'stale'))
        _, v, _ = ana.state()
        status, v, _ = ana.post('session/start', {'if_version': v['version']})
        t.join(20)
        self.assertEqual((status, v['state'], len(self.link.launched)), (200, 'active', 1))
        states = [x['state'] for x in seen]
        self.assertEqual((states[0], states[-1]), ('setup', 'active'))
        self.assertEqual({x['nav']['session'] for x in seen}, {v['session']['id']})  # one move

    def test_switch_away_from_setup_never_calls_the_game(self):
        ana = self.phone()
        _, v, _ = ana.post('join', {'name': 'Ana'})
        _, v, _ = ana.post('session/launch', {'game': 'bluff', 'if_version': v['version']})
        status, v, _ = ana.post('session/switch', {'game': 'bomber', 'if_version': v['version']})
        self.assertEqual((status, v['state'], v['session']['game']), (200, 'active', 'bomber'))
        self.assertEqual(self.link.ended, [])
        self.assertEqual(len(self.link.launched), 1)


class SlowLink(FakeLink):
    """A launch that only returns once the test says so (the runtime is still coming up)."""

    def __init__(self):
        super().__init__(True)
        self.release = threading.Event()

    def launch(self, session, roster):
        self.release.wait(10)
        return super().launch(session, roster)


class LaunchRaces(ServiceCase):
    def make_link(self):
        return SlowLink()

    def test_a_launch_that_lands_after_the_host_cancelled_is_stopped(self):
        """AVR-223 (2): the party moved on while the launch was in flight; the runtime that then
        comes up is ended, never left running beside whatever starts next."""
        ana = self.phone()
        _, v, _ = ana.post('join', {'name': 'Ana'})
        t = threading.Thread(target=ana.post, args=('session/launch',
                             {'game': 'bluff', 'if_version': v['version']}), daemon=True)
        t.start()
        for _ in range(200):                                   # until the session is launching
            _, v, _ = self.phone().state()
            if v.get('session') and v['session']['state'] == 'launching':
                break
            time.sleep(0.02)
        sid = v['session']['id']
        host = self.phone()
        host.cookie = ana.cookie
        status, v, _ = host.post('session/end', {'if_version': v['version']})
        self.assertEqual((status, v['session']['outcome']), (200, 'launch_failed'))
        self.link.release.set()
        t.join(5)
        self.assertEqual(self.link.ended, [sid])
        self.assertEqual(self.phone().state()[1]['state'], 'lobby')


class FailingLaunch(ServiceCase):
    link_ok = False

    def test_a_failed_launch_says_why_and_returns_to_the_lobby(self):
        a = self.phone()
        _, v, _ = a.post('join', {'name': 'Ana'})
        _, v, _ = a.post('session/launch', {'game': 'bluff', 'if_version': v['version']})
        self.assertEqual((v['state'], v['session']['outcome'], v['session']['detail']),
                         ('lobby', 'launch_failed', 'Games server is down.'))
        # AVR-134: the failed launch is also ended at the game, so a runtime that came up late
        # (after the link gave up) or half-started is stopped before anything else can start
        self.assertEqual(self.link.ended, [v['session']['id']])


class Bounds(ServiceCase):
    """AVR-218: listen backlog and the cap on blocked long polls."""

    def test_listen_backlog_is_raised(self):
        self.assertEqual(self.server.request_queue_size, service.REQUEST_QUEUE_SIZE)
        self.assertGreater(service.REQUEST_QUEUE_SIZE, 5)
        self.assertTrue(self.server.daemon_threads)

    def test_extra_waiter_beyond_the_cap_returns_at_once(self):
        orig = service.MAX_WAITERS
        service.MAX_WAITERS = 1
        self.addCleanup(setattr, service, 'MAX_WAITERS', orig)
        _, v, _ = self.phone().state()
        since = v['version']
        first = threading.Thread(target=self.svc.view, args=(None, since, 5.0), daemon=True)
        first.start()
        deadline = time.monotonic() + 3
        while self.svc.waiters < 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.svc.waiters, 1)
        t0 = time.monotonic()
        view = self.svc.view(None, since, 5.0)       # saturated: degrades to a short poll
        self.assertLess(time.monotonic() - t0, 1.0)
        self.assertEqual(view['version'], since)
        self.assertEqual(self.svc.waiters, 1)
        self.svc.call('join', self.store.issue()[0] if hasattr(self.store, 'issue') else 'x', 'Ana', None)             if False else None
        with self.svc.lock:                           # release the first waiter
            self.svc.core.party.version += 1
            self.svc.changed.notify_all()
        first.join(3)
        self.assertEqual(self.svc.waiters, 0)

    def test_wait_zero_is_unchanged_when_saturated(self):
        orig = service.MAX_WAITERS
        service.MAX_WAITERS = 0
        self.addCleanup(setattr, service, 'MAX_WAITERS', orig)
        t0 = time.monotonic()
        self.svc.view(None, None, 0)
        self.svc.view(None, 1, 0)
        self.assertLess(time.monotonic() - t0, 1.0)


if __name__ == '__main__':
    unittest.main()
