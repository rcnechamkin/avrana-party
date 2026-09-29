"""AVR-134: a heavyweight runtime (the arcade) runs only while the Party says so.

Unit rules of avrana.party.managed.ManagedRuntime (ordering, failures, stale and forged
requests, abandon), its HTTP guard, its configuration, and one cross-component run: real Party
Core + the real HTTP game link + a reference BLUFF server + a managed "arcade" served over HTTP,
recording one timeline of runtime starts and stops. Stand-ins replace RetroArch and GStreamer
(tests/unit/test_arcade_stream.py covers arcade/stream.py itself); the Pi is Tier 3.
"""
import asyncio
import http.server
import json
import os
import tempfile
import threading
import time
import unittest

from avrana.party import managed, protocol, service, sessions
from avrana.party.managed import IDLE, RUNNING

from test_party_service import HOST, ORIGIN, Phone, ServiceCase
from test_party_session_flow import KEY as BLUFF_KEY, ReferenceGame

GAME = 'arcade-gauntlet2'
KEY = protocol.new_key()
SID = 'session-' + 'a' * 32
SID2 = 'session-' + 'b' * 32
ROSTER = [{'participant': 'participant-' + '1' * 32, 'name': 'Ana', 'role': 'player'}]


class Runtime:
    """A stand-in heavy runtime: records starts/stops and how many runs overlap."""

    def __init__(self, timeline=None, start_delay=0.0, fail_start=False, fail_stop=False):
        self.timeline = timeline if timeline is not None else []
        self.start_delay, self.fail_start, self.fail_stop = start_delay, fail_start, fail_stop
        self.running = 0
        self.max_running = 0

    async def start(self):
        self.timeline.append(('arcade', 'start'))
        await asyncio.sleep(self.start_delay)
        if self.fail_start:
            raise RuntimeError('no encoder')
        self.running += 1
        self.max_running = max(self.max_running, self.running)
        self.timeline.append(('arcade', 'running'))

    async def stop(self):
        if self.fail_stop:
            raise RuntimeError('stuck')
        self.running = 0
        self.timeline.append(('arcade', 'stopped'))


def launch(sid=SID, key=KEY, game=GAME, now=None):
    return protocol.launch_message(key, game, sid, ROSTER, now)


def end(sid=SID, key=KEY, now=None):
    return protocol.end_message(key, GAME, sid, now)


def make(**kw):
    rt = Runtime(**{k: v for k, v in kw.items() if k != 'report' and k != 'start_timeout'})
    m = managed.ManagedRuntime(protocol.GameSide(KEY, GAME), rt.start, rt.stop,
                               report=kw.get('report'), start_timeout=kw.get('start_timeout', 5))
    return m, rt


def run(coro):
    return asyncio.run(coro)


class Lifecycle(unittest.TestCase):
    def test_launch_starts_and_end_stops(self):
        async def go():
            m, rt = make()
            self.assertEqual((m.state, rt.running), (IDLE, 0))
            self.assertEqual(await m.launch(launch()), (200, {'ok': True}))
            self.assertEqual((m.state, m.session, rt.running), (RUNNING, SID, 1))
            self.assertEqual(await m.end(end()), (200, {'ok': True}))
            self.assertEqual((m.state, m.session, rt.running), (IDLE, None, 0))
            self.assertEqual(rt.timeline, [('arcade', 'start'), ('arcade', 'running'), ('arcade', 'stopped')])
        run(go())

    def test_forged_replayed_expired_or_misaddressed_messages_change_nothing(self):
        async def go():
            m, rt = make()
            msg = launch()
            for bad in (launch(key=protocol.new_key()), launch(game='bluff'),
                        launch(now=time.time() - 3600), None, 'aps0.x.y'):
                status, body = await m.launch(bad)
                self.assertEqual((status, body['ok']), (403, False))
            self.assertEqual((rt.timeline, m.state), ([], IDLE))
            await m.launch(msg)
            status, _ = await m.launch(msg)                      # a replay of the same launch
            self.assertEqual(status, 403)
            e = end()
            await m.end(e)
            self.assertEqual((await m.end(e))[0], 403)          # and of the same end
            self.assertEqual(rt.timeline.count(('arcade', 'start')), 1)
        run(go())

    def test_a_failed_start_is_stopped_again_and_reported(self):
        async def go():
            m, rt = make(fail_start=True)
            status, body = await m.launch(launch())
            self.assertEqual((status, body['ok']), (200, False))
            self.assertIn('no encoder', body['message'])
            self.assertEqual((m.state, m.session), (IDLE, None))
            self.assertEqual(rt.timeline[-1], ('arcade', 'stopped'))   # the partial start is undone
        run(go())

    def test_a_slow_start_times_out_and_is_stopped(self):
        async def go():
            m, rt = make(start_delay=1.0, start_timeout=0.2)
            status, body = await m.launch(launch())
            self.assertEqual((status, body['ok'], m.state), (200, False, IDLE))
            self.assertIn('too long', body['message'])
            self.assertEqual(rt.timeline, [('arcade', 'start'), ('arcade', 'stopped')])
        run(go())

    def test_a_launch_over_a_lost_end_stops_the_old_run_first(self):
        async def go():
            m, rt = make()
            await m.launch(launch(SID))
            self.assertEqual(await m.launch(launch(SID2)), (200, {'ok': True}))
            self.assertEqual(rt.max_running, 1)                 # never two runs
            self.assertEqual(rt.timeline, [('arcade', 'start'), ('arcade', 'running'), ('arcade', 'stopped'),
                                           ('arcade', 'start'), ('arcade', 'running')])
            self.assertEqual(m.session, SID2)
        run(go())

    def test_an_end_during_a_start_waits_for_it_then_stops(self):
        async def go():
            m, rt = make(start_delay=0.3)
            t = asyncio.create_task(m.launch(launch()))
            await asyncio.sleep(0.05)
            self.assertEqual(m.state, 'starting')
            status, body = await m.end(end())                    # queued behind the start
            self.assertEqual((await t)[1]['ok'], True)
            self.assertEqual((status, body['ok'], m.state), (200, True, IDLE))
            self.assertEqual(rt.timeline, [('arcade', 'start'), ('arcade', 'running'), ('arcade', 'stopped')])
        run(go())

    def test_stale_ends(self):
        async def go():
            m, rt = make()
            # nothing runs (a restart, a failed start): an end for any session is answered ok,
            # so the party's switch can go on
            self.assertEqual(await m.end(end(SID)), (200, {'ok': True}))
            await m.launch(launch(SID2))
            status, body = await m.end(end(SID))               # a late end for an older session
            self.assertEqual((status, body['reason']), (409, 'session'))
            self.assertEqual((m.state, m.session, rt.running), (RUNNING, SID2, 1))
        run(go())

    def test_a_stop_that_fails_is_not_confirmed(self):
        async def go():
            m, rt = make(fail_stop=True)
            await m.launch(launch())
            status, body = await m.end(end())
            self.assertEqual((status, body['ok'], m.state), (200, False, RUNNING))
        run(go())

    def test_abandon_tells_the_party_once_with_a_report_it_accepts(self):
        sent = []

        async def report(message):
            sent.append(message)
            return True

        async def go():
            m, _ = make(report=report)
            self.assertFalse(await m.abandon())                 # idle: nothing to report
            await m.launch(launch())
            self.assertTrue(await m.abandon())
            self.assertIsNone(m.session)
            self.assertFalse(await m.abandon())
        run(go())
        self.assertEqual(len(sent), 1)
        p = protocol.open_message(KEY, sent[0], 'ended', 'party', protocol.ReplayGuard())
        self.assertEqual((p['iss'], p['sid'], p['outcome']), (GAME, SID, 'abandoned'))

    def test_abandon_with_an_unreachable_party_does_not_hang(self):
        async def report(message):
            await asyncio.sleep(60)

        async def go():
            m, _ = make(report=report)
            await m.launch(launch())
            t0 = time.monotonic()
            self.assertFalse(await m.abandon())
            self.assertLess(time.monotonic() - t0, managed.REPORT_TIMEOUT + 2)
        run(go())


class HttpGuard(unittest.TestCase):
    def test_only_local_unproxied_json_reaches_the_runtime(self):
        async def go():
            m, rt = make()
            body = json.dumps({'message': launch()}).encode()
            for remote, headers, raw, want in (
                    ('10.42.0.23', {}, body, 404),                      # a phone
                    ('127.0.0.1', {'X-Forwarded-For': '10.42.0.23'}, body, 404),   # via a proxy
                    ('127.0.0.1', {'x-real-ip': '10.42.0.23'}, body, 404),
                    ('127.0.0.1', {}, b'x' * (managed.MAX_BODY + 1), 413),
                    ('127.0.0.1', {}, b'{', 400),
                    ('127.0.0.1', {}, b'[]', 400)):
                status, _ = await managed.handle(m, 'launch', remote, headers, raw)
                self.assertEqual(status, want, (remote, headers))
            self.assertEqual(rt.timeline, [])
            self.assertEqual((await managed.handle(m, 'launch', '127.0.0.1', {}, body))[0], 200)
            self.assertEqual(rt.running, 1)
        run(go())


class Configure(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def key(self, text=None):
        path = os.path.join(self.dir, f'{GAME}.key')
        with open(path, 'w') as f:
            f.write(text if text is not None else KEY.hex() + '\n')
        os.chmod(path, 0o600)                   # read_key refuses group/other-readable keys (POSIX)

    def test_both_halves_or_always_on(self):
        url = 'http://127.0.0.1:8191'
        self.assertIsNone(managed.configure({}, GAME))
        self.assertIsNone(managed.configure({'AVRANA_PARTY_KEYS': self.dir, 'AVRANA_PARTY_URL': url}, GAME))
        self.key()
        self.assertIsNone(managed.configure({'AVRANA_PARTY_KEYS': self.dir}, GAME))
        for bad in ('http://10.42.0.1:8191', 'https://127.0.0.1:8191', 'http://127.0.0.1',
                    'http://127.0.0.1:8191/party', 'http://u:p@127.0.0.1:8191'):
            self.assertIsNone(managed.configure({'AVRANA_PARTY_KEYS': self.dir, 'AVRANA_PARTY_URL': bad}, GAME), bad)
        side, got = managed.configure({'AVRANA_PARTY_KEYS': self.dir, 'AVRANA_PARTY_URL': url + '/'}, GAME)
        self.assertEqual((side.game, side.key, got), (GAME, KEY, url))

    def test_an_unusable_key_runs_always_on(self):
        self.key('not hex')
        self.assertIsNone(managed.configure({'AVRANA_PARTY_KEYS': self.dir,
                                             'AVRANA_PARTY_URL': 'http://127.0.0.1:8191'}, GAME))


# ---- cross-component: Party Core switches between BLUFF and a managed arcade -------------------
class ArcadeServer:
    """The managed runtime behind a real HTTP server on 127.0.0.1 (the arcade's control port)."""

    def __init__(self, timeline, **kw):
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.runtime = Runtime(timeline, **{k: v for k, v in kw.items() if k != 'start_timeout'})

        async def build():
            return managed.ManagedRuntime(protocol.GameSide(KEY, GAME), self.runtime.start,
                                          self.runtime.stop, start_timeout=kw.get('start_timeout', 5))
        self.managed = asyncio.run_coroutine_threadsafe(build(), self.loop).result()
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get('Content-Length') or 0))
                action = {managed.LAUNCH_PATH: 'launch', managed.END_PATH: 'end'}.get(self.path)
                fut = asyncio.run_coroutine_threadsafe(
                    managed.handle(outer.managed, action, self.client_address[0], dict(self.headers), raw),
                    outer.loop)
                status, body = fut.result(30)
                data = json.dumps(body).encode()
                try:
                    self.send_response(status)
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass                        # the party gave up waiting (a timed-out launch)

        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.loop.call_soon_threadsafe(self.loop.stop)


class RecordingGame(ReferenceGame):
    """The reference BLUFF server, also writing its launches and ends into the shared timeline."""

    def __init__(self, party_port, timeline):
        super().__init__(party_port)
        side, self.timeline = self.side, timeline
        on_launch, on_end = side.on_launch, side.on_end

        def launch(msg, now=None):
            r = on_launch(msg, now)
            timeline.append(('bluff', 'running'))
            return r

        def ended(msg, now=None):
            r = on_end(msg, now)
            timeline.append(('bluff', 'stopped'))
            return r
        side.on_launch, side.on_end = launch, ended


class PartyAndArcade(ServiceCase):
    games = {'bluff': {'id': 'bluff', 'max_players': 6, 'late_join': 'spectator_only'},
             GAME: {'id': GAME, 'max_players': 2, 'late_join': 'supported'}}
    arcade_kw = {}
    link_timeout = 5

    def setUp(self):
        super().setUp()
        self.server.shutdown()
        self.server.server_close()
        self.timeline = []
        self.bluff = RecordingGame(0, self.timeline)
        self.arcade = ArcadeServer(self.timeline, **self.arcade_kw)
        endpoints = {'bluff': sessions.GameEndpoint('bluff', self.bluff.url, BLUFF_KEY),
                     GAME: sessions.GameEndpoint(GAME, self.arcade.url, KEY, self.link_timeout)}
        self.svc.link = sessions.HttpGameLink(endpoints, timeout=5)
        extra, internal = sessions.routes(self.svc, endpoints)
        cfg = service.Config({HOST}, {ORIGIN}, secure_cookie=True)
        self.server = service.make_server(self.svc, cfg, port=0, extra_routes=extra, internal_routes=internal)
        self.port = self.server.server_address[1]
        self.bluff.party_port = self.port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.ana, self.ben = self.phone(), self.phone()
        self.ana.post('join', {'name': 'Ana'})
        self.ben.post('join', {'name': 'Ben'})

    def tearDown(self):
        self.arcade.stop()
        self.bluff.stop()
        super().tearDown()

    def host(self, path, **body):
        _, v, _ = self.ana.state()
        return self.ana.post(path, dict(body, if_version=v['version']))

    def assert_never_two(self):
        """Replay the timeline: at no point do BLUFF and the arcade both run."""
        on = set()
        for who, what in self.timeline:
            if what == 'running':
                on.add(who)
            elif what == 'stopped':
                on.discard(who)
            self.assertLessEqual(len(on), 1, self.timeline)

    def test_switching_between_bluff_and_gauntlet_never_overlaps(self):
        status, v, _ = self.host('session/launch', game='bluff')
        self.assertEqual((status, v['state']), (200, 'active'))
        status, v, _ = self.host('session/switch', game=GAME)
        self.assertEqual((status, v['state'], v['session']['game'], v['nav']['game']), (200, 'active', GAME, GAME))
        self.assertEqual(self.arcade.managed.state, RUNNING)
        status, v, _ = self.host('session/switch', game='bluff')
        self.assertEqual((status, v['session']['game']), (200, 'bluff'))
        self.assertEqual((self.arcade.managed.state, self.arcade.runtime.running), (IDLE, 0))
        status, v, _ = self.host('session/end')
        self.assertEqual(v['state'], 'lobby')
        self.assertEqual(self.timeline, [
            ('bluff', 'running'), ('bluff', 'stopped'),
            ('arcade', 'start'), ('arcade', 'running'), ('arcade', 'stopped'),
            ('bluff', 'running'), ('bluff', 'stopped')])
        self.assert_never_two()

    def test_host_end_stops_the_arcade_and_non_hosts_cannot_start_it(self):
        _, bv, _ = self.ben.state()
        status, body, _ = self.ben.post('session/launch', {'game': GAME, 'if_version': bv['version']})
        self.assertEqual((status, body['error']), (403, 'not_host'))
        self.assertEqual(self.timeline, [])
        self.host('session/launch', game=GAME)
        self.assertEqual(self.arcade.runtime.running, 1)
        status, v, _ = self.host('session/end')
        self.assertEqual((status, v['state'], v['nav']['to']), (200, 'lobby', 'home'))
        self.assertEqual((self.arcade.managed.state, self.arcade.runtime.running), (IDLE, 0))

    def test_a_restarted_arcade_lets_the_switch_go_on(self):
        """The arcade process restarted mid-session (it comes back idle and has forgotten the
        session): the party's end is still confirmed, so the host can switch to BLUFF."""
        self.host('session/launch', game=GAME)
        self.arcade.managed.side.sid = None                     # what a restart looks like
        asyncio.run_coroutine_threadsafe(self.arcade.managed._halt(), self.arcade.loop).result()
        status, v, _ = self.host('session/switch', game='bluff')
        self.assertEqual((status, v['state'], v['session']['game']), (200, 'active', 'bluff'))
        self.assert_never_two()

    def test_an_abandoned_arcade_returns_the_party_to_the_lobby(self):
        self.arcade.managed.report = lambda m: asyncio.to_thread(
            managed.post_ended, f'http://127.0.0.1:{self.port}', m)
        self.host('session/launch', game=GAME)
        ok = asyncio.run_coroutine_threadsafe(self.arcade.managed.abandon(), self.arcade.loop).result(10)
        self.assertTrue(ok)
        _, v, _ = self.ben.state()
        self.assertEqual((v['state'], v['session']['outcome']), ('lobby', 'abandoned'))


class ArcadeFailsToStart(PartyAndArcade):
    arcade_kw = {'fail_start': True}

    def test_switching_between_bluff_and_gauntlet_never_overlaps(self):
        self.host('session/launch', game='bluff')
        status, v, _ = self.host('session/switch', game=GAME)
        self.assertEqual((status, v['state'], v['session']['outcome'], v['nav']['to']),
                         (200, 'lobby', 'launch_failed', 'home'))
        self.assertIn('no encoder', v['session']['detail'])
        self.assertEqual((self.arcade.managed.state, self.arcade.runtime.running), (IDLE, 0))
        self.assert_never_two()

    test_host_end_stops_the_arcade_and_non_hosts_cannot_start_it = None
    test_a_restarted_arcade_lets_the_switch_go_on = None
    test_an_abandoned_arcade_returns_the_party_to_the_lobby = None


class ArcadeTooSlowForTheLink(PartyAndArcade):
    """The link gives up before the arcade is up: the party says the launch failed and sends
    `end`, which the arcade applies right after its start completes, so nothing is left running."""
    arcade_kw = {'start_delay': 1.5, 'start_timeout': 10}
    link_timeout = 0.5

    def test_switching_between_bluff_and_gauntlet_never_overlaps(self):
        status, v, _ = self.host('session/launch', game=GAME)
        self.assertEqual((v['state'], v['session']['outcome']), ('lobby', 'launch_failed'))
        deadline = time.monotonic() + 10
        while self.timeline[-1:] != [('arcade', 'stopped')]:
            self.assertLess(time.monotonic(), deadline, self.timeline)
            time.sleep(0.05)
        self.assertEqual(self.arcade.runtime.running, 0)
        self.assertEqual(self.arcade.managed.state, IDLE)

    test_host_end_stops_the_arcade_and_non_hosts_cannot_start_it = None
    test_a_restarted_arcade_lets_the_switch_go_on = None
    test_an_abandoned_arcade_returns_the_party_to_the_lobby = None


if __name__ == '__main__':
    unittest.main()
