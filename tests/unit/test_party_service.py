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

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = identity.DeviceStore(os.path.join(self.tmp.name, 'devices.json'))
        self.link = FakeLink(self.link_ok)
        self.svc = service.PartyService(self.store, BLUFF, self.link)
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


class FailingLaunch(ServiceCase):
    link_ok = False

    def test_a_failed_launch_says_why_and_returns_to_the_lobby(self):
        a = self.phone()
        _, v, _ = a.post('join', {'name': 'Ana'})
        _, v, _ = a.post('session/launch', {'game': 'bluff', 'if_version': v['version']})
        self.assertEqual((v['state'], v['session']['outcome'], v['session']['detail']),
                         ('lobby', 'launch_failed', 'Games server is down.'))


if __name__ == '__main__':
    unittest.main()
