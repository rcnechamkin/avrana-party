"""Tests for the dev party service + front door (stdlib only; binds 127.0.0.1 on free ports).
    python experiments/party-service/test_party_service.py
The lifecycle RULES are the reference model's (../party-model, 52 tests); these tests check that
the service carries them over HTTP without breaking the identity and security invariants.
"""
import http.client
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import front  # noqa: E402
import identity  # noqa: E402
import service  # noqa: E402
from party_model import HOST_GRACE, PARTY_IDLE  # noqa: E402  (path set by service)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


class Identity(unittest.TestCase):
    def test_tokens_are_server_issued_high_entropy_and_only_hashed_at_rest(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'devices.json')
            store = identity.DeviceStore(path)
            tokens = [store.issue()[0] for _ in range(50)]
            self.assertEqual(len(set(tokens)), 50)
            self.assertTrue(all(identity.TOKEN_RE.match(t) for t in tokens))    # 256-bit urlsafe
            with open(path, encoding='utf-8') as f:
                raw = f.read()
            self.assertFalse(any(t in raw for t in tokens))                   # hashes only
            again = identity.DeviceStore(path)                                # survives a restart
            self.assertEqual(again.resolve(tokens[0]), store.resolve(tokens[0]))
            if os.name == 'posix':
                self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_forged_malformed_and_revoked_tokens_resolve_to_nothing(self):
        store = identity.DeviceStore()
        token, device = store.issue()
        self.assertEqual(store.resolve(token), device)
        for bad in (None, '', 'x' * 43, token + 'a', token[:-1], '../../etc', 'a b'):
            self.assertIsNone(store.resolve(bad))
        store.revoke(token)
        self.assertIsNone(store.resolve(token))

    def test_cookie_attributes(self):
        c = identity.set_cookie('T' * 43)
        for attr in ('HttpOnly', 'SameSite=Lax', 'Path=/party/', 'Max-Age='):
            self.assertIn(attr, c)
        self.assertNotIn('Secure', c)                  # plain-HTTP LAN: Secure would never be sent
        self.assertTrue(c.startswith('avrana_dev_device='))
        self.assertEqual(identity.read_cookie('a=1; avrana_dev_device=XYZ; b=2'), 'XYZ')
        self.assertIsNone(identity.read_cookie('avrana_device=XYZ'))


class Harness(unittest.TestCase):
    """A real front door on a free port, an injected clock, and no background timer (tests tick)."""

    upstream = None

    def setUp(self):
        service.KEEPALIVE_S = 0.3                    # notice closed streams quickly in tests
        self.clock = Clock()
        self.party = service.PartyService(identity.DeviceStore(), clock=self.clock)
        self.srv = front.FrontServer(('127.0.0.1', 0), self.party, service.Config(['placeholder']),
                                     self.upstream)
        self.port = self.srv.server_address[1]
        self.host = f'127.0.0.1:{self.port}'
        self.srv.cfg = service.Config([self.host])
        self.origin = f'http://{self.host}'
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def req(self, method, path, body=None, cookie=None, origin='default', host=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        headers = {'Host': host or self.host}
        if cookie:
            headers['Cookie'] = f'avrana_dev_device={cookie}'
        if method == 'POST':
            headers['Content-Type'] = 'application/json'
            if origin == 'default':
                headers['Origin'] = self.origin
            elif origin:
                headers['Origin'] = origin
        c.request(method, path, body=json.dumps(body or {}) if method == 'POST' else None, headers=headers)
        r = c.getresponse()
        raw = r.read()
        c.close()
        set_cookie = r.getheader('Set-Cookie')
        token = identity.read_cookie(set_cookie.split(';')[0]) if set_cookie else None
        return r.status, (json.loads(raw) if raw and r.getheader('Content-Type', '').startswith('application/json') else raw), token, raw

    def device(self):
        """A browser's first visit: GET the state, keep the cookie the server issued."""
        status, view, token, _ = self.req('GET', '/party/state')
        self.assertEqual(status, 200)
        self.assertIsNotNone(token)
        return token

    def join(self, token, persona=None):
        status, view, _, _ = self.req('POST', '/party/join', {'persona': persona} if persona else {}, cookie=token)
        self.assertEqual(status, 200, view)
        return view


class PartyOverHttp(Harness):
    def test_first_visit_observes_and_join_is_explicit(self):
        token = self.device()
        _, view, _, _ = self.req('GET', '/party/state', cookie=token)
        self.assertIsNone(view['me'])
        self.assertEqual(self.party.app.party.presences, {})       # page load is not presence
        me = self.join(token)['me']
        self.assertEqual((me['persona'], me['is_host']), ('Player 1', True))
        other = self.device()
        self.assertEqual(self.join(other, 'Megan')['me']['persona'], 'Megan')

    def test_event_stream_never_creates_a_presence(self):
        token = self.device()
        s = socket.create_connection(('127.0.0.1', self.port), timeout=5)
        s.sendall(f'GET /party/events HTTP/1.1\r\nHost: {self.host}\r\nCookie: avrana_dev_device={token}\r\n\r\n'.encode())
        data = b''
        while b'event: state' not in data:
            data += s.recv(4096)
        s.close()
        self.assertEqual(self.party.app.party.presences, {})
        self.assertIn(b'"me": null', data)

    def test_forged_cookie_gets_a_fresh_identity_not_the_forged_one(self):
        forged = 'A' * 43
        status, view, issued, _ = self.req('GET', '/party/state', cookie=forged)
        self.assertEqual(status, 200)
        self.assertIsNotNone(issued)
        self.assertNotEqual(issued, forged)
        self.assertIsNone(self.party.store.resolve(forged))

    def test_security_boundaries(self):
        token = self.device()
        self.assertEqual(self.req('POST', '/party/join', cookie=token, origin=None)[0], 403)
        self.assertEqual(self.req('POST', '/party/join', cookie=token, origin='http://evil.example')[0], 403)
        self.assertEqual(self.req('GET', '/party/state', cookie=token, host='evil.example')[0], 421)  # rebinding
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        c.putrequest('POST', '/party/join', skip_host=True)
        for k, v in (('Host', self.host), ('Origin', self.origin), ('Content-Length', '-1')):
            c.putheader(k, v)
        c.endheaders()
        self.assertEqual(c.getresponse().status, 400)
        c.close()
        _, _, _, raw = self.req('POST', '/party/join', cookie=token)
        self.assertNotIn(token.encode(), raw)                       # the token never enters a body
        self.assertNotIn(b'device-', raw)                           # nor does the device id

    def test_host_actions_need_the_host_and_a_fresh_version(self):
        a, b = self.device(), self.device()
        self.join(a)
        view = self.join(b)
        self.assertEqual(self.req('POST', '/party/host/select', {'game': 'bluff'}, cookie=b)[0], 409)
        stale = view['party']['version'] - 1
        self.assertEqual(self.req('POST', '/party/host/select', {'game': 'bluff', 'if_version': stale}, cookie=a)[0], 409)
        status, v, _, _ = self.req('POST', '/party/host/select', {'game': 'bluff'}, cookie=a)
        self.assertEqual(status, 200)
        self.assertEqual((v['party']['state'], v['party']['nav']['href']), ('in_game', '/games/bluff/'))
        self.assertEqual(v['me']['seat_slot'], 1)
        self.assertEqual(self.req('POST', '/party/host/select', {'game': 'nope'}, cookie=a)[0], 409)

    def test_rename_is_display_only(self):
        a, b = self.device(), self.device()
        self.join(a)
        self.join(b)
        _, v, _, _ = self.req('POST', '/party/rename', {'name': 'Player 1'}, cookie=b)
        self.assertEqual(v['me']['persona'], 'Player 1 2')         # disambiguated, still not host
        self.assertFalse(v['me']['is_host'])
        self.assertEqual(self.req('POST', '/party/rename', {'name': 'SYSTEM'}, cookie=b)[0], 409)

    def test_unclaimed_join_times_out_then_host_succession(self):
        a, b = self.device(), self.device()
        self.join(a)                                    # a never opens its event stream
        self.join(b)
        self.party.open_stream(b)                       # b's page is open
        self.clock.advance(service.JOIN_BIND_S)
        self.party.tick()                               # a's Join connection is dropped
        members = {m['persona']: m for m in self.req('GET', '/party/state', cookie=b)[1]['members']}
        self.assertEqual(members['Player 1']['state'], 'reconnecting')
        self.clock.advance(HOST_GRACE)
        self.party.tick()
        self.assertTrue(self.req('GET', '/party/state', cookie=b)[1]['me']['is_host'])

    def test_timer_change_seen_by_a_view_still_wakes_other_streams(self):
        a, b = self.device(), self.device()
        self.join(a)
        self.join(b)
        sa, sb = self.party.open_stream(a), self.party.open_stream(b)
        self.party.close_stream(sa)                     # host's phone sleeps
        marker = self.party.wait(None, 0)
        self.clock.advance(HOST_GRACE)
        woke = []

        def waiter():
            t0 = time.monotonic()
            m = self.party.wait(marker, 3)
            woke.append((m, time.monotonic() - t0))
        t = threading.Thread(target=waiter)
        t.start()
        time.sleep(0.2)
        self.req('GET', '/party/state', cookie=b)       # this view applies the succession timer
        t.join(4)
        self.assertNotEqual(woke[0][0], marker)
        self.assertLess(woke[0][1], 1.5)                # woken by the change, not by the timeout

    def test_stream_close_drops_and_reopen_reclaims_the_same_presence(self):
        a = self.device()
        pid = self.join(a)['me']['presence_id']
        stream = self.party.open_stream(a)              # binds the Join's connection
        self.party.close_stream(stream)
        self.assertEqual(self.req('GET', '/party/state', cookie=a)[1]['members'][0]['state'], 'reconnecting')
        self.party.open_stream(a)                       # reload / wake
        me = self.req('GET', '/party/state', cookie=a)[1]
        self.assertEqual((me['me']['presence_id'], me['members'][0]['state']), (pid, 'connected'))
        self.assertTrue(me['me']['is_host'])

    def test_ended_party_refuses_host_actions_and_next_join_starts_a_new_party(self):
        a, b = self.device(), self.device()
        first = self.join(a)['party']['id']
        self.join(b)
        self.assertEqual(self.req('POST', '/party/host/end-party', cookie=b)[0], 409)   # not host
        self.assertEqual(self.req('POST', '/party/host/end-party', cookie=a)[0], 200)
        self.assertEqual(self.req('POST', '/party/host/select', {'game': 'bluff'}, cookie=a)[0], 409)
        self.assertIsNone(self.req('GET', '/party/state', cookie=b)[1]['me'])          # ended: observer
        v = self.join(b)
        self.assertNotEqual(v['party']['id'], first)
        self.assertTrue(v['me']['is_host'])              # b joined first this time

    def test_idle_party_ends_with_nobody_connected(self):
        a = self.device()
        stream = self.party.open_stream(a) if self.join(a) else None
        self.party.close_stream(stream)
        self.clock.advance(PARTY_IDLE)
        self.party.tick()
        self.assertEqual(self.party.app.party.state, 'ended')

    def test_leave_then_rejoin_is_the_same_presence(self):
        a = self.device()
        pid = self.join(a)['me']['presence_id']
        self.assertIsNone(self.req('POST', '/party/leave', cookie=a)[1]['me'])
        self.assertEqual(self.join(a)['me']['presence_id'], pid)

    def test_dev_forget_me_revokes_the_token(self):
        a = self.device()
        status, _, _, _ = self.req('POST', '/party/dev/forget-me', cookie=a)
        self.assertEqual(status, 200)
        self.assertIsNone(self.party.store.resolve(a))

    def test_reset_party_is_off_unless_enabled(self):
        a = self.device()
        self.join(a)
        self.assertEqual(self.req('POST', '/party/dev/reset-party', cookie=a)[0], 404)
        self.srv.cfg.dev_commands = True
        self.assertEqual(self.req('POST', '/party/dev/reset-party', cookie=a)[0], 200)
        self.assertEqual(self.party.app.party.state, 'ended')

    def test_party_page_is_self_contained(self):
        status, _, _, raw = self.req('GET', '/party/')
        self.assertEqual(status, 200)
        self.assertNotRegex(raw.decode(), r'(src|href)\s*=\s*["\']?(https?:)?//')   # offline-first


# ---- front door: cookie stripping and the WebSocket tunnel ------------------------------------------
class Recorder(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        Recorder.seen.append(dict(self.headers))
        body = b'game page'
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def ws_echo_upstream():
    """A fake game server: answers an upgrade with 101, then echoes bytes. Records the request."""
    lst = socket.socket()
    lst.bind(('127.0.0.1', 0))
    lst.listen(1)
    seen = {}

    def run():
        conn, _ = lst.accept()
        req = b''
        while b'\r\n\r\n' not in req:
            req += conn.recv(4096)
        seen['request'] = req.decode('latin-1')
        conn.sendall(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n')
        data = conn.recv(4096)
        conn.sendall(data)
        conn.close()
        lst.close()

    threading.Thread(target=run, daemon=True).start()
    return lst.getsockname(), seen


class ApiGames(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        with open(os.path.join(os.path.dirname(HERE), 'manifests', 'fixtures', 'api-games.sample.json'), 'rb') as f:
            body = f.read()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class FrontDoor(Harness):
    def test_catalog_is_derived_from_the_upstream_registry(self):
        up = ThreadingHTTPServer(('127.0.0.1', 0), ApiGames)
        threading.Thread(target=up.serve_forever, daemon=True).start()
        try:
            catalog, problems = front.lan_catalog(up.server_address)
        finally:
            up.shutdown()
            up.server_close()
        ids = {c['id'] for c in catalog}
        self.assertTrue({'bluff', 'wordrush', 'blitz', 'wordclash'} <= ids)
        self.assertNotIn('_template', ids)
        self.assertEqual(problems, ['mystery: no min_p/max_p in the registry'])
        self.party.catalog = {c['id']: c for c in catalog}
        a = self.device()
        self.join(a)
        _, v, _, _ = self.req('POST', '/party/host/select', {'game': 'wordrush'}, cookie=a)
        self.assertEqual(v['party']['nav']['href'], '/games/wordrush/')
        self.assertEqual(front.lan_catalog(('127.0.0.1', 9))[0], [])      # unreachable: empty, not a crash

    def test_catalog_retries_until_the_games_server_is_up(self):
        up = ThreadingHTTPServer(('127.0.0.1', 0), ApiGames)
        addr = up.server_address
        up.server_close()                                  # not listening yet
        tries = []

        def sleep(_):                                       # the games server comes up on retry 3
            tries.append(1)
            if len(tries) == 2:
                later = ThreadingHTTPServer(addr, ApiGames)
                threading.Thread(target=later.serve_forever, daemon=True).start()
                self.addCleanup(later.server_close)
                self.addCleanup(later.shutdown)
        self.assertTrue(front.load_catalog(self.party, addr, attempts=5, sleep=sleep))
        self.assertIn('wordrush', self.party.catalog)
        self.assertEqual(len(tries), 2)
        self.assertFalse(front.load_catalog(self.party, ('127.0.0.1', 9), attempts=2, sleep=lambda _: None))

    def test_game_paths_are_proxied_without_cookies(self):
        up = ThreadingHTTPServer(('127.0.0.1', 0), Recorder)
        threading.Thread(target=up.serve_forever, daemon=True).start()
        self.srv.upstream = up.server_address
        token = self.device()
        status, _, _, raw = self.req('GET', '/games/bluff/', cookie=token)
        up.shutdown()
        up.server_close()
        self.assertEqual((status, raw), (200, b'game page'))
        headers = {k.lower(): v for k, v in Recorder.seen[-1].items()}
        self.assertNotIn('cookie', headers)                          # device token never reaches games
        self.assertEqual(headers['host'], self.host)

    def test_websocket_upgrade_is_tunnelled_without_cookies(self):
        addr, seen = ws_echo_upstream()
        self.srv.upstream = addr
        s = socket.create_connection(('127.0.0.1', self.port), timeout=5)
        s.sendall((f'GET /chat/ws HTTP/1.1\r\nHost: {self.host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                   'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n'
                   'Cookie: avrana_dev_device=SECRET\r\n\r\n').encode())
        head = b''
        while b'\r\n\r\n' not in head:
            head += s.recv(4096)
        self.assertIn(b' 101 ', head.split(b'\r\n')[0])
        s.sendall(b'frame-bytes')
        self.assertEqual(s.recv(4096), b'frame-bytes')
        s.close()
        self.assertNotIn('SECRET', seen['request'])
        self.assertIn('Upgrade: websocket', seen['request'])

    def test_unknown_host_is_refused_on_game_paths_too(self):
        self.srv.upstream = ('127.0.0.1', 9)
        self.assertEqual(self.req('GET', '/games/bluff/', host='evil.example')[0], 421)


if __name__ == '__main__':
    unittest.main(verbosity=1)
