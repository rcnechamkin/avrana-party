"""Limited Mode in Party Core (ADR 0012, AVR-225): the same party over plain HTTP, with its own
credential, on its own loopback listener. Real HTTP on 127.0.0.1; no nginx, no browser."""
import http.client
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from avrana.party import core, identity, service

FULL_HOST, FULL_ORIGIN = 'party.test', 'https://party.test'
LIMITED_HOST, LIMITED_ORIGIN = '10.42.0.1', 'http://10.42.0.1'
BLUFF = {'bluff': {'id': 'bluff', 'max_players': 6, 'late_join': 'spectator_only'}}
EXAMPLE = Path(__file__).resolve().parents[2] / 'deploy' / 'party-core' / 'party-core.example.json'


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


class Link:
    def launch(self, session, roster):
        return True, None

    def end(self, session):
        return True


class Phone:
    """One cookie jar on one origin. A browser never sends a cookie to another origin, and never
    sends a `Secure` cookie over plain HTTP; `carry` hands a jar across for the tests that ask
    what the server does if one arrives anyway."""

    def __init__(self, port, host, origin):
        self.port, self.host, self.origin = port, host, origin
        self.jar = {}
        self.set_cookie = None

    def req(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20)
        h = {'Host': self.host}
        if self.jar:
            h['Cookie'] = '; '.join(f'{k}={v}' for k, v in self.jar.items())
        data = None
        if method == 'POST':
            data = json.dumps(body or {}).encode()
            h.update({'Origin': self.origin, 'Content-Type': 'application/json'})
        h.update(headers or {})
        conn.request(method, path, body=data, headers=h)
        r = conn.getresponse()
        raw = r.read()
        self.set_cookie = r.getheader('Set-Cookie')
        if self.set_cookie:
            name, value = self.set_cookie.split(';')[0].split('=', 1)
            self.jar[name] = value
        conn.close()
        return r.status, (json.loads(raw) if raw else None)

    def state(self):
        return self.req('GET', '/party/api/state')

    def post(self, path, body=None, **kw):
        return self.req('POST', '/party/api/' + path, body, **kw)


class TwoListeners(unittest.TestCase):
    """One PartyService behind a Full listener and a Limited listener, as main() builds them."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = identity.DeviceStore(os.path.join(self.tmp.name, 'devices.json'))
        self.clock = Clock()
        self.limited_store = identity.LimitedStore(self.clock)
        self.svc = service.PartyService(self.store, BLUFF, Link(), limited=self.limited_store)
        full = service.Config({FULL_HOST}, {FULL_ORIGIN})
        limited = service.limited_config({'hosts': [LIMITED_HOST], 'origins': [LIMITED_ORIGIN]}, full)
        hit = []
        internal = {'/internal/party-session/v0/ended': lambda h, body: hit.append(body) or service._send(h, 200, {'ok': True})}
        self.internal_hits = hit
        self.servers = [service.make_server(self.svc, full, port=0, internal_routes=internal),
                        service.make_server(self.svc, limited, port=0)]
        self._err = redirect_stderr(io.StringIO())
        self._err.__enter__()
        for s in self.servers:
            threading.Thread(target=s.serve_forever, daemon=True).start()

    def tearDown(self):
        for s in self.servers:
            s.shutdown()
            s.server_close()
        self._err.__exit__(None, None, None)
        self.tmp.cleanup()

    def full(self):
        return Phone(self.servers[0].server_address[1], FULL_HOST, FULL_ORIGIN)

    def limited(self):
        return Phone(self.servers[1].server_address[1], LIMITED_HOST, LIMITED_ORIGIN)

    def test_a_limited_join_gets_its_own_short_lived_cookie_and_never_the_device_cookie(self):
        p = self.limited()
        status, view = p.state()
        self.assertEqual((status, view['mode'], view['me']), (200, 'limited', None))
        self.assertIsNone(p.set_cookie)                       # looking issues nothing here either
        status, view = p.post('join', {'name': 'Lena'})
        self.assertEqual(status, 200)
        attrs = [a.strip() for a in p.set_cookie.split(';')]
        self.assertEqual(attrs[0].split('=')[0], 'avrana_limited')
        self.assertIn('HttpOnly', attrs)
        self.assertIn('SameSite=Lax', attrs)
        self.assertIn('Path=/party/', attrs)
        self.assertIn(f'Max-Age={12 * 3600}', attrs)
        self.assertNotIn('Secure', attrs)
        self.assertNotIn('avrana_device', p.set_cookie)
        self.assertEqual((view['mode'], view['me']['mode'], view['me']['host']), ('limited', 'limited', True))
        self.assertEqual(self.store.by_hash, {})              # nothing persistent was minted
        self.assertFalse(os.path.exists(self.store.path))
        self.assertEqual(p.state()[1]['me']['name'], 'Lena')  # and the cookie is who she is

    def test_one_party_two_modes_and_each_member_shows_its_mode(self):
        ana, lena = self.full(), self.limited()
        ana.post('join', {'name': 'Ana'})
        lena.post('join', {'name': 'Lena'})
        status, view = ana.state()
        self.assertEqual(view['mode'], 'full')
        self.assertEqual({m['name']: m['mode'] for m in view['members']}, {'Ana': 'full', 'Lena': 'limited'})
        self.assertEqual(lena.state()[1]['party'], view['party'])

    def test_each_listener_resolves_only_its_own_credential(self):
        ana, lena = self.full(), self.limited()
        ana.post('join', {'name': 'Ana'})
        lena.post('join', {'name': 'Lena'})
        device_token = ana.jar[identity.HOST_COOKIE]
        limited_token = lena.jar[identity.LIMITED_COOKIE]
        # A device token on the Limited listener, under either name, is nobody.
        for name in (identity.HOST_COOKIE, identity.COOKIE, identity.LIMITED_COOKIE):
            stray = self.limited()
            stray.jar = {name: device_token}
            self.assertIsNone(stray.state()[1]['me'], name)
        # A Limited token on the Full listener, under any name, is nobody.
        for name in (identity.HOST_COOKIE, identity.COOKIE, identity.LIMITED_COOKIE):
            stray = self.full()
            stray.jar = {name: limited_token}
            self.assertIsNone(stray.state()[1]['me'], name)
        # And joining there mints that listener's own credential: a new device, a new member.
        switched = self.full()
        switched.jar = {identity.LIMITED_COOKIE: limited_token}
        status, view = switched.post('join', {'name': 'Lena'})
        self.assertEqual(status, 200)
        self.assertTrue(switched.set_cookie.startswith(identity.HOST_COOKIE + '='))
        self.assertEqual(sorted(m['name'] for m in view['members']), ['Ana', 'Lena', 'Lena 2'])

    def test_a_limited_member_has_host_authority(self):
        lena = self.limited()
        _, view = lena.post('join', {'name': 'Lena'})
        status, view = lena.post('session/launch', {'game': 'bluff', 'if_version': view['version']})
        self.assertEqual((status, view['state']), (200, 'active'))
        status, view = lena.post('session/end', {'if_version': view['version']})
        self.assertEqual((status, view['state']), (200, 'lobby'))

    def test_the_limited_credential_expires_and_dies_with_the_store(self):
        lena = self.limited()
        lena.post('join', {'name': 'Lena'})
        self.clock.advance(identity.LIMITED_MAX_AGE - 1)
        self.assertIsNotNone(lena.state()[1]['me'])
        self.clock.advance(2)
        self.assertIsNone(lena.state()[1]['me'])
        self.assertEqual(lena.post('heartbeat')[0], 403)
        self.assertEqual(self.limited_store.by_hash, {})

    def test_limited_guards_host_origin_and_a_planted_second_cookie(self):
        p = self.limited()
        p.host = FULL_HOST
        self.assertEqual(p.state()[0], 421)                    # the Full name is not served here
        p = self.limited()
        p.origin = FULL_ORIGIN
        self.assertEqual(p.post('join', {'name': 'Mallory'}), (403, {'error': 'bad_origin'}))
        p = self.limited()
        status, body = p.post('join', {'name': 'Twice'},
                              headers={'Cookie': 'avrana_limited=a; avrana_limited=b'})
        self.assertEqual((status, body['error']), (409, 'ambiguous_identity'))

    def test_over_plain_http_no_browser_sends_sec_fetch_site_and_the_origin_check_is_what_refuses(self):
        """Browsers send Sec-Fetch-Site only to trustworthy origins, so the Limited listener never
        sees it. These are the requests another page on the Wi-Fi can really make there."""
        host = self.limited()
        host.post('join', {'name': 'Lena'})
        # a POST from another origin, cookie attached (same site), no Sec-Fetch-Site: refused
        for origin in ('http://10.42.0.1:8096', 'http://evil.test', 'https://10.42.0.1', 'null'):
            status, body = host.req('POST', '/party/api/leave', {}, headers={'Origin': origin})
            self.assertEqual((status, body), (403, {'error': 'bad_origin'}), origin)
        # and one with no Origin at all
        conn = http.client.HTTPConnection('127.0.0.1', host.port, timeout=10)
        conn.request('POST', '/party/api/leave', body=b'{}', headers={
            'Host': LIMITED_HOST, 'Content-Type': 'application/json',
            'Cookie': '; '.join(f'{k}={v}' for k, v in host.jar.items())})
        self.assertEqual(conn.getresponse().status, 403)
        conn.close()
        self.assertEqual([m['name'] for m in host.state()[1]['members']], ['Lena'])   # still a member
        # a GET from another origin is answered, changes nothing, and is unreadable there: no
        # response from this listener carries a CORS header
        for path in ('/party/api/state', service.BRIDGE_ROUTE, '/party/api/nope'):
            conn = http.client.HTTPConnection('127.0.0.1', host.port, timeout=10)
            conn.request('GET', path, headers={'Host': LIMITED_HOST, 'Origin': 'http://evil.test'})
            res = conn.getresponse()
            res.read()
            self.assertEqual([k for k, _ in res.getheaders() if k.lower().startswith('access-control-')], [], path)
            conn.close()
        # the header still refuses when it is present (a tool, or localhost in development)
        self.assertEqual(host.req('GET', '/party/api/state', headers={'Sec-Fetch-Site': 'same-site'})[0], 403)

    def test_the_limited_listener_serves_no_game_report_and_no_bridge_origin(self):
        p = self.limited()
        conn = http.client.HTTPConnection('127.0.0.1', p.port, timeout=10)
        conn.request('POST', '/internal/party-session/v0/ended', body=b'{}',
                     headers={'Host': LIMITED_HOST, 'Content-Type': 'application/json'})
        self.assertEqual(conn.getresponse().status, 404)
        conn.close()
        self.assertEqual(self.internal_hits, [])
        status, bridge = p.req('GET', service.BRIDGE_ROUTE)
        self.assertEqual((status, bridge['origins']), (200, {}))


class LimitedConfig(unittest.TestCase):
    def setUp(self):
        self.full = service.Config({FULL_HOST}, {FULL_ORIGIN})

    def test_absent_means_no_limited_listener_and_production_does_not_set_it(self):
        self.assertIsNone(service.limited_config(None, self.full))
        self.assertNotIn('limited', json.loads(EXAMPLE.read_text(encoding='utf-8')))

    def test_only_plain_http_origins_and_never_one_shared_with_full_mode(self):
        cfg = service.limited_config({'hosts': [LIMITED_HOST], 'origins': [LIMITED_ORIGIN]}, self.full)
        self.assertEqual((cfg.mode, cfg.secure_cookie, cfg.game_origins), ('limited', False, {}))
        for bad in ({'hosts': [LIMITED_HOST], 'origins': ['https://10.42.0.1']},
                    {'hosts': [LIMITED_HOST], 'origins': []},
                    {'hosts': [], 'origins': [LIMITED_ORIGIN]},
                    {'origins': [LIMITED_ORIGIN]}, []):
            with self.assertRaises(ValueError, msg=bad):
                service.limited_config(bad, self.full)
        dev = service.Config({'127.0.0.1:1'}, {'http://127.0.0.1:1'}, secure_cookie=False)
        with self.assertRaises(ValueError):
            service.limited_config({'hosts': ['127.0.0.1:1'], 'origins': ['http://127.0.0.1:1']}, dev)
        with self.assertRaises(ValueError):
            service.Config({LIMITED_HOST}, {LIMITED_ORIGIN}, mode='limited',
                           game_origins={'http://games.test': '*'})
        with self.assertRaises(ValueError):
            service.Config({LIMITED_HOST}, {LIMITED_ORIGIN}, mode='half')


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class MainWiring(unittest.TestCase):
    """service.main() itself, as a process: which listeners a config starts."""

    def run_main(self, limited):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        port = free_port()
        conf = {'hosts': [f'127.0.0.1:{port}'], 'origins': [f'http://127.0.0.1:{port}'], 'secure_cookie': False,
                'devices': os.path.join(tmp.name, 'devices.json'), 'games': {}}
        if limited is not None:
            conf['limited'] = limited
        path = os.path.join(tmp.name, 'party-core.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(conf, f)
        env = {k: v for k, v in os.environ.items() if not k.startswith('LISTEN_')}
        proc = subprocess.Popen([sys.executable, '-m', 'avrana.party.service', '--config', path, '--port', str(port)],
                                cwd=str(Path(__file__).resolve().parents[2]), env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

        def stop():
            proc.kill()
            proc.wait(10)
            proc.stderr.close()
        self.addCleanup(stop)
        return proc, port

    def answer(self, proc, port, host, path='/party/api/state', method='GET', origin=None):
        deadline = time.monotonic() + 20
        while True:
            try:
                conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
                headers = {'Host': host}
                body = None
                if method == 'POST':
                    body = b'{}'
                    headers.update({'Origin': origin, 'Content-Type': 'application/json'})
                conn.request(method, path, body=body, headers=headers)
                res = conn.getresponse()
                raw = res.read()
                conn.close()
                return res.status, (json.loads(raw) if raw else None), res.getheader('Set-Cookie')
            except OSError:
                if proc.poll() is not None or time.monotonic() > deadline:
                    raise
                time.sleep(0.1)

    def refused(self, port):
        try:
            socket.create_connection(('127.0.0.1', port), timeout=2).close()
        except OSError:
            return True
        return False

    def test_a_limited_object_starts_a_second_listener_that_is_limited_mode_and_only_that(self):
        lport = free_port()
        host, origin = f'127.0.0.1:{lport}', f'http://127.0.0.1:{lport}'
        proc, port = self.run_main({'hosts': [host], 'origins': [origin], 'port': lport})
        full_host = f'127.0.0.1:{port}'
        self.assertEqual(self.answer(proc, port, full_host)[1]['mode'], 'full')
        status, view, _ = self.answer(proc, lport, host)
        self.assertEqual((status, view['mode']), (200, 'limited'))
        # each listener answers only for its own name
        self.assertEqual(self.answer(proc, lport, full_host)[0], 421)
        self.assertEqual(self.answer(proc, port, host)[0], 421)
        # the Limited listener issues the Limited credential, and it is one party
        status, view, cookie = self.answer(proc, lport, host, '/party/api/join', 'POST', origin)
        self.assertEqual(status, 400, view)                              # no name: refused before minting
        self.assertIsNone(cookie)
        conn = http.client.HTTPConnection('127.0.0.1', lport, timeout=5)
        conn.request('POST', '/party/api/join', body=json.dumps({'name': 'Lena'}).encode(),
                     headers={'Host': host, 'Origin': origin, 'Content-Type': 'application/json'})
        res = conn.getresponse()
        joined = json.loads(res.read())
        cookie = res.getheader('Set-Cookie')
        conn.close()
        self.assertTrue(cookie.startswith(identity.LIMITED_COOKIE + '='), cookie)
        self.assertNotIn('Secure', cookie)
        self.assertEqual([(m['name'], m['mode']) for m in joined['members']], [('Lena', 'limited')])
        self.assertEqual([(m['name'], m['mode']) for m in self.answer(proc, port, full_host)[1]['members']],
                         [('Lena', 'limited')])
        # the routes main() attaches to both: the status route answers here too; the game -> party
        # report is not served on the Limited listener
        self.assertEqual(self.answer(proc, lport, host, '/party/api/status')[0],
                         self.answer(proc, port, full_host, '/party/api/status')[0])
        conn = http.client.HTTPConnection('127.0.0.1', lport, timeout=5)
        conn.request('POST', '/internal/party-session/v0/ended', body=b'{}',
                     headers={'Host': host, 'Content-Type': 'application/json'})
        self.assertEqual(conn.getresponse().status, 404)
        conn.close()
        self.assertIsNone(proc.poll())

    def test_without_a_limited_object_main_starts_no_second_listener(self):
        proc, port = self.run_main(None)
        self.assertEqual(self.answer(proc, port, f'127.0.0.1:{port}')[1]['mode'], 'full')
        self.assertTrue(self.refused(service.LIMITED_PORT) or self.not_ours(service.LIMITED_PORT))
        self.assertIsNone(proc.poll())

    def not_ours(self, port):
        """Something else on this machine holds the default port: it is not this Party Core if it
        does not answer as one."""
        try:
            conn = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
            conn.request('GET', '/party/api/state', headers={'Host': '10.42.0.1'})
            res = conn.getresponse()
            raw = res.read()
            conn.close()
            return not (res.status == 200 and json.loads(raw).get('mode') == 'limited')
        except (OSError, ValueError, http.client.HTTPException):
            return True

    def test_a_bad_limited_object_stops_main_before_it_listens_anywhere(self):
        for bad in ({'hosts': ['10.42.0.1'], 'origins': ['https://10.42.0.1']},
                    {'hosts': ['10.42.0.1'], 'origins': ['http://10.42.0.1'], 'port': 'eighty'},
                    {'hosts': ['10.42.0.1']}, 'yes'):
            proc, port = self.run_main(bad)
            self.assertNotEqual(proc.wait(20), 0, bad)
            self.assertIn('party-core config:', proc.stderr.read().decode(), bad)
            self.assertTrue(self.refused(port), bad)

    def test_an_origin_shared_with_full_mode_is_refused_and_a_shared_host_name_is_not(self):
        full = service.Config({'party.avrana.net'}, {'https://party.avrana.net'})
        cfg = service.limited_config({'hosts': ['party.avrana.net', '10.42.0.1'],
                                      'origins': ['http://party.avrana.net', 'http://10.42.0.1']}, full)
        self.assertEqual((cfg.mode, 'party.avrana.net' in cfg.hosts), ('limited', True))
        plain = service.Config({'party.test'}, {'http://party.test'}, secure_cookie=False)
        with self.assertRaises(ValueError):
            service.limited_config({'hosts': ['other.test'], 'origins': ['http://party.test']}, plain)


class Store(unittest.TestCase):
    def test_tokens_are_minted_here_hashed_and_separate_from_the_device_store(self):
        clock = Clock()
        store = identity.LimitedStore(clock)
        token, device = store.issue()
        self.assertRegex(token, identity.TOKEN_RE)
        self.assertEqual(store.resolve(token), device)
        self.assertNotIn(token, json.dumps(list(store.by_hash)))
        for bad in (None, '', 'x' * 43, token + 'x', 7):
            self.assertIsNone(store.resolve(bad))
        self.assertIsNone(identity.DeviceStore(None).resolve(token))

    def test_expired_tokens_are_forgotten_on_the_next_issue(self):
        clock = Clock()
        store = identity.LimitedStore(clock, lifetime=10)
        old, _ = store.issue()
        clock.advance(11)
        new, device = store.issue()
        self.assertEqual(len(store.by_hash), 1)
        self.assertIsNone(store.resolve(old))
        self.assertEqual(store.resolve(new), device)


def party():
    clock = Clock()
    return core.PartyCore(clock, BLUFF), clock


class Succession(unittest.TestCase):
    """ADR 0012 D4: mixed parties are allowed; succession prefers Full Mode; a host who is here
    is never displaced."""

    def test_succession_prefers_a_full_mode_member_who_is_here(self):
        pc, clock = party()
        pc.join('device-a', 'Ana')
        pc.join('device-l', 'Lena', mode='limited')            # joined before Fay
        fay = pc.join('device-f', 'Fay')
        pc.leave('device-a')
        self.assertEqual(pc.party.host_id, fay.id)

    def test_with_nobody_in_full_mode_a_limited_member_takes_over(self):
        pc, clock = party()
        pc.join('device-a', 'Ana')
        lena = pc.join('device-l', 'Lena', mode='limited')
        pc.join('device-m', 'Moe', mode='limited')
        pc.leave('device-a')
        self.assertEqual(pc.party.host_id, lena.id)

    def test_a_full_member_who_is_away_is_not_preferred_over_a_limited_one_who_is_here(self):
        pc, clock = party()
        pc.join('device-a', 'Ana')
        pc.join('device-f', 'Fay')
        lena = pc.join('device-l', 'Lena', mode='limited')
        clock.advance(core.LIVE_WINDOW + 1)
        pc.touch('device-a')
        pc.touch('device-l')                                   # Fay stopped polling
        pc.leave('device-a')
        self.assertEqual(pc.party.host_id, lena.id)

    def test_a_limited_host_who_is_here_is_never_displaced_by_a_full_member(self):
        pc, clock = party()
        lena = pc.join('device-l', 'Lena', mode='limited')
        pc.join('device-f', 'Fay')
        for _ in range(10):
            clock.advance(20)
            pc.touch('device-l')
            pc.touch('device-f')
            pc.tick()
        self.assertEqual(pc.party.host_id, lena.id)
        self.assertEqual(pc.view('device-f')['host'], lena.id)

    def test_mode_is_set_at_join_kept_and_shown(self):
        pc, clock = party()
        pc.join('device-l', 'Lena', mode='limited')
        pc.join('device-l', 'Lena', mode='full')               # the same device cannot change it
        view = pc.view('device-l')
        self.assertEqual((view['me']['mode'], view['members'][0]['mode']), ('limited', 'limited'))
        with self.assertRaises(ValueError):
            pc.join('device-x', 'Xi', mode='secure')


if __name__ == '__main__':
    unittest.main()
