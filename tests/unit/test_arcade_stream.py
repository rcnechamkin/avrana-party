"""Tier 1/2: arcade/stream.py wiring after the provider extraction, with GStreamer and aiohttp stubbed.

It cannot prove streaming works (that needs the Pi's encoder, a phone and the owner); it proves
the module imports without python-evdev, that its controller layout agrees with the Game
Contract and the phone page, and that startup/stats/cleanup drive the runtime and input
providers (a stand-in process instead of RetroArch, a fake uinput).
"""
import asyncio
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock
from pathlib import Path

from avrana import CONTRACTS_DIR, REPO_ROOT
from avrana.contracts import game, vocabulary
from avrana.providers.retroarch import RetroArchRuntime
from avrana.providers.uinput_gamepad import UInputGamepadProvider

from test_providers import fake_evdev


class _Enum(types.SimpleNamespace):
    pass


def stub_modules():
    gst = types.SimpleNamespace(
        init=lambda *_: None,
        State=_Enum(PLAYING='PLAYING', NULL='NULL'),
        StateChangeReturn=_Enum(FAILURE='FAILURE', SUCCESS='SUCCESS'),
        MessageType=_Enum(ERROR='ERROR'),
        CLOCK_TIME_NONE=-1,
        parse_launch=None,  # set per test
    )
    repository = types.SimpleNamespace(Gst=gst, GstVideo=types.SimpleNamespace(), GstWebRTC=types.SimpleNamespace(),
                                       GstSdp=types.SimpleNamespace())
    gi = types.ModuleType('gi')
    gi.require_version = lambda *_: None
    gi.repository = repository
    class HTTPError(Exception):
        def __init__(self, text=''):
            super().__init__(text)
            self.text = text
    web = types.SimpleNamespace(json_response=lambda data, status=200: data,
                                HTTPForbidden=type('HTTPForbidden', (HTTPError,), {}),
                                HTTPServiceUnavailable=type('HTTPServiceUnavailable', (HTTPError,), {}),
                                HTTPConflict=type('HTTPConflict', (HTTPError,), {}))
    aiohttp = types.ModuleType('aiohttp')
    aiohttp.web = web
    return {'gi': gi, 'gi.repository': repository, 'aiohttp': aiohttp}, gst


def load_stream():
    modules, gst = stub_modules()
    saved = {name: sys.modules.get(name) for name in modules}
    sys.modules.update(modules)
    try:
        spec = importlib.util.spec_from_file_location('arcade_stream_under_test', REPO_ROOT / 'arcade' / 'stream.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for name, old in saved.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old
    return module, gst


class FakePipeline:
    def __init__(self):
        self.states = []

    def get_by_name(self, name):
        return types.SimpleNamespace(connect=lambda *a: None)

    def set_state(self, state):
        self.states.append(state)
        return 'SUCCESS'

    def get_bus(self):
        return types.SimpleNamespace(pop_filtered=lambda *_: None)


class ArcadeStream(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stream, cls.gst = load_stream()
        cls.contract = game.load(CONTRACTS_DIR / 'games' / 'arcade-gauntlet2.json', vocabulary.load())

    def test_imports_without_evdev(self):
        self.assertNotIn('evdev', sys.modules)

    def test_layout_matches_contract_and_page(self):
        inp = self.contract['input']
        self.assertEqual(self.stream.LAYOUT.buttons, tuple(inp['buttons']))
        self.assertEqual(self.stream.LAYOUT.directions, inp['directions'])
        self.assertEqual(self.stream.MAX_PLAYERS, inp['slots'])
        page = (REPO_ROOT / 'arcade' / 'index.html').read_text(encoding='utf-8')
        self.assertEqual(set(re.findall(r'data-key="([a-z]+)"', page)), set(self.stream.LAYOUT.names))

    def test_presentation_provider_shape(self):
        s = self.stream.Stream()
        self.assertEqual(s.info.offers, ('presentation.shared_stream',))
        self.assertEqual(s.status(), {'id': 'shared-webrtc', 'kind': 'presentation',
                                      'offers': ['presentation.shared_stream'], 'viewers': 0, 'encoders': 1})
        self.assertEqual(s.runtime.command()[-1], '/srv/avrana/roms/arcade/gaunt2.zip')
        self.assertTrue(s.runtime.core.as_posix().endswith('arcade/cores/mame2010_libretro.so'))

    def test_startup_stats_cleanup_drive_the_providers(self):
        log = []
        s = self.stream.Stream()
        s.input = UInputGamepadProvider(evdev=fake_evdev(log))
        s.runtime = RetroArchRuntime(config='c', core='k', content='x', popen=lambda cmd, **kw: subprocess.Popen(
            [sys.executable, '-c', 'import time; time.sleep(30)'], **kw))
        pipeline = FakePipeline()
        self.gst.parse_launch = lambda description: pipeline
        with tempfile.TemporaryDirectory() as tmp:
            self.stream.EMULATOR_LOG = Path(tmp) / 'emulator.log'
            os.environ.setdefault('PULSE_SERVER', 'unix:/nonexistent')

            async def run():
                await s.startup(None)
                stats = await s.stats(None)
                await s.cleanup(None)
                return stats
            stats = asyncio.run(run())
        self.assertTrue(stats['emulator_running'])
        self.assertEqual(stats['max_players'], 2)
        self.assertEqual(stats['video_encoders'], 1)
        self.assertEqual(stats['providers']['runtime']['id'], 'retroarch')
        self.assertTrue(stats['providers']['runtime']['running'])
        self.assertEqual(stats['providers']['input']['isolation'], 'global')
        self.assertEqual(stats['providers']['input']['controllers'], 2)
        self.assertEqual(stats['providers']['presentation']['viewers'], 0)
        self.assertEqual([entry[2] for entry in log if entry[0] == 'create'], ['Avrana Player 1', 'Avrana Player 2'])
        self.assertEqual(sum(1 for entry in log if entry[0] == 'close'), 2)
        self.assertFalse(s.runtime.running())
        self.assertEqual(pipeline.states, ['PLAYING', 'NULL'])


class ManagedArcade(unittest.TestCase):
    """AVR-134: with a Party session key the arcade starts idle; the Party's signed launch starts
    RetroArch and the encode, its end stops them, and the page, controllers and /stats stay up."""

    @classmethod
    def setUpClass(cls):
        cls.stream, cls.gst = load_stream()

    def setUp(self):
        from avrana.party import protocol
        self.protocol = protocol
        self.key = protocol.new_key()
        self.tmp = tempfile.TemporaryDirectory()
        path = os.path.join(self.tmp.name, 'arcade-gauntlet2.key')
        with open(path, 'w') as f:
            f.write(self.key.hex() + '\n')
        os.chmod(path, 0o600)                   # read_key refuses group/other-readable keys (POSIX)
        self.env = mock.patch.dict(os.environ, {'AVRANA_PARTY_KEYS': self.tmp.name,
                                                'AVRANA_PARTY_URL': 'http://127.0.0.1:8191',
                                                'PULSE_SERVER': 'unix:/nonexistent'})
        self.env.start()
        self.stream.EMULATOR_LOG = Path(self.tmp.name) / 'emulator.log'

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def make(self, log):
        s = self.stream.Stream()
        s.input = UInputGamepadProvider(evdev=fake_evdev(log))
        s.runtime = RetroArchRuntime(config='c', core='k', content='x', popen=lambda cmd, **kw: subprocess.Popen(
            [sys.executable, '-c', 'import time; time.sleep(30)'], **kw))
        self.pipelines = []

        def parse(description):
            self.pipelines.append(FakePipeline())
            return self.pipelines[-1]
        self.gst.parse_launch = parse
        s.controls = 0

        async def no_socket():          # the real one binds 127.0.0.1:8098 through aiohttp
            s.controls += 1
        s.start_control = no_socket
        return s

    def message(self, typ, sid):
        roster = [{'participant': 'participant-' + '1' * 32, 'name': 'Ana', 'role': 'player'}]
        if typ == 'launch':
            return self.protocol.launch_message(self.key, 'arcade-gauntlet2', sid, roster)
        return self.protocol.end_message(self.key, 'arcade-gauntlet2', sid)

    def request(self):
        return types.SimpleNamespace(headers={'Origin': 'https://party.avrana.net'}, host='party.avrana.net')

    def test_idle_until_launched_then_stopped_by_end_and_restartable(self):
        log = []
        s = self.make(log)
        sid1, sid2 = 'session-' + 'a' * 32, 'session-' + 'b' * 32

        async def run():
            await s.startup(None)
            idle = await s.stats(None)
            with self.assertRaises(self.stream.web.HTTPServiceUnavailable) as refused:
                await s.websocket(self.request())       # a phone before the host starts it
            first = await s.managed.launch(self.message('launch', sid1))
            running = await s.stats(None)
            ticket = self.protocol.mint_ticket(self.key, s.managed.side.game, sid1,
                                               'participant-' + '1' * 32, 'player')
            s.party_seats.claim(s.managed.side, ticket, object())
            stopped = await s.managed.end(self.message('end', sid1))
            self.assertEqual(s.party_seats.seats, {})
            after = await s.stats(None)
            again = await s.managed.launch(self.message('launch', sid2))
            await s.cleanup(None)
            return idle, refused.exception.text, first, running, stopped, after, again
        idle, refused, first, running, stopped, after, again = asyncio.run(run())
        self.assertEqual(s.controls, 1)
        self.assertEqual((idle['state'], idle['party_managed'], idle['emulator_running']), ('idle', True, False))
        self.assertEqual(len(self.pipelines), 2)          # one encode per run, none while idle
        self.assertIn('Party Host', refused)
        self.assertEqual(first, (200, {'ok': True}))
        self.assertEqual((running['state'], running['emulator_running']), ('running', True))
        self.assertEqual(stopped, (200, {'ok': True}))
        self.assertEqual((after['state'], after['emulator_running']), ('idle', False))
        self.assertEqual(self.pipelines[0].states, ['PLAYING', 'NULL'])
        self.assertEqual(again, (200, {'ok': True}))
        self.assertEqual(self.pipelines[1].states, ['PLAYING', 'NULL'])  # cleanup stopped run 2
        self.assertFalse(s.runtime.running())
        # the controllers stayed open across runs and were released once, at the end
        self.assertEqual(sum(1 for e in log if e[0] == 'create'), 2)
        self.assertEqual(sum(1 for e in log if e[0] == 'close'), 2)

    def test_newer_launch_clears_reservations_even_without_old_end(self):
        s = self.make([])
        async def run():
            await s.startup(None)
            sid1, sid2 = 'session-' + 'a' * 32, 'session-' + 'b' * 32
            await s.managed.launch(self.message('launch', sid1))
            old = self.protocol.mint_ticket(self.key, s.managed.side.game, sid1,
                                           'participant-' + '1' * 32, 'player')
            s.party_seats.claim(s.managed.side, old, object())
            await s.managed.launch(self.message('launch', sid2))
            self.assertEqual(s.party_seats.seats, {})
            with self.assertRaises(self.protocol.Invalid):
                s.party_seats.claim(s.managed.side, old, object())
            await s.cleanup(None)
        asyncio.run(run())

    def test_without_the_key_the_arcade_runs_always_on(self):
        log = []
        with mock.patch.dict(os.environ, {'AVRANA_PARTY_KEYS': ''}):
            s = self.make(log)

            async def run():
                await s.startup(None)
                stats = await s.stats(None)
                await s.cleanup(None)
                return stats
            stats = asyncio.run(run())
        self.assertIsNone(s.managed)
        self.assertEqual(s.controls, 0)                  # no control port either
        self.assertEqual((stats['state'], stats['party_managed'], stats['emulator_running']),
                         ('running', False, True))

    def test_a_fatal_failure_during_a_party_session_reports_abandoned_before_exiting(self):
        log = []
        s = self.make(log)
        s.exits = 0
        s.request_exit = lambda: setattr(s, 'exits', s.exits + 1)
        reports = []

        async def report(message):
            reports.append(message)
            return True

        async def run():
            await s.startup(None)
            s.managed.report = report
            await s.managed.launch(self.message('launch', 'session-' + 'c' * 32))
            s.runtime.process.kill()                      # the emulator dies mid-game
            await asyncio.wait_for(s.monitor, 5)
            await s.cleanup(None)
        asyncio.run(run())
        self.assertEqual((s.error, s.exits, len(reports)), ('Emulator exited', 1, 1))
        p = self.protocol.open_message(self.key, reports[0], 'ended', 'party', self.protocol.ReplayGuard())
        self.assertEqual(p['outcome'], 'abandoned')


# 'ip -o addr show' output as the Pi prints it (the literal backslash ends each record).
IP_NOW = r"""1: lo    inet 127.0.0.1/8 scope host lo\       valid_lft forever preferred_lft forever
2: eth0    inet 10.0.0.142/24 brd 10.0.0.255 scope global dynamic noprefixroute eth0\       valid_lft 86000sec
3: wlan0    inet 10.42.0.1/24 brd 10.42.0.255 scope global noprefixroute wlan0\       valid_lft forever
3: wlan0    inet6 fe80::9afe:54ff:fe34:e550/64 scope link noprefixroute \       valid_lft forever
"""
IP_OLD = r"""2: wlan0    inet 10.0.0.143/24 brd 10.0.0.255 scope global wlan0\       valid_lft 86000sec
4: wlan1    inet 10.42.0.1/24 brd 10.42.0.255 scope global wlan1\       valid_lft forever
"""


class PartySeatReservations(unittest.TestCase):
    """AVR-130: real protocol admission, deterministic monotonic grace clock."""
    def setUp(self):
        from avrana.party import protocol
        self.protocol = protocol
        self.module, _ = load_stream()
        self.side = protocol.GameSide(protocol.new_key(), 'arcade-gauntlet2')
        self.side.on_launch(protocol.launch_message(self.side.key, self.side.game,
                                                   'session-' + 'a' * 32, []))
        self.now = 100
        self.seats = self.module.PartySeats(clock=lambda: self.now)

    def ticket(self, who=1, role='player', **kw):
        # Tickets are single-use (AVR-52) and iat has one-second resolution: give each minted
        # ticket a distinct (past) iat so repeated claims by one participant are distinct tickets.
        self._minted = getattr(self, '_minted', 0) + 1
        kw.setdefault('now', int(time.time()) - self._minted)
        return self.protocol.mint_ticket(self.side.key, kw.pop('game', self.side.game),
                                        kw.pop('sid', self.side.sid),
                                        'participant-' + str(who) * 32, role, **kw)

    def claim(self, who=1, ws=None):
        return self.seats.claim(self.side, self.ticket(who), ws or object())

    def test_first_player_and_same_participant_reconnect(self):
        ws = object()
        self.assertEqual(self.claim(ws=ws), (0, None))
        self.assertTrue(self.seats.disconnect(0, ws))
        self.assertEqual(self.claim(), (0, None))

    def test_reverse_reconnect_does_not_swap_slots(self):
        a, b = object(), object()
        self.assertEqual(self.claim(1, a)[0], 0)
        self.assertEqual(self.claim(2, b)[0], 1)
        self.seats.disconnect(0, a)
        self.seats.disconnect(1, b)
        self.assertEqual(self.claim(2)[0], 1)
        self.assertEqual(self.claim(1)[0], 0)

    def test_grace_blocks_other_participant_and_expires_at_deadline(self):
        a = object()
        self.claim(1, a)
        self.claim(2)
        self.seats.disconnect(0, a)
        self.now += 59.999
        with self.assertRaisesRegex(self.protocol.Invalid, 'full'):
            self.claim(3)
        self.now = 160
        self.assertEqual(self.claim(3)[0], 0)

    def test_leave_releases_immediately(self):
        a = object()
        self.claim(1, a)
        self.seats.disconnect(0, a, leave=True)
        self.assertEqual(self.claim(2)[0], 0)

    def test_duplicate_uses_same_slot_and_old_socket_cannot_input_or_release(self):
        a, b = object(), object()
        self.claim(1, a)
        self.assertEqual(self.claim(1, b), (0, a))
        self.assertEqual(len(self.seats.seats), 1)
        self.assertFalse(self.seats.owns(self.side, 0, a))
        self.assertTrue(self.seats.owns(self.side, 0, b))
        self.assertFalse(self.seats.disconnect(0, a, leave=True))
        self.assertFalse(self.seats.disconnect(0, a))
        self.assertTrue(self.seats.owns(self.side, 0, b))

    def test_stale_ticket_and_new_launch(self):
        old = self.ticket()
        a = object()
        self.claim(1, a)
        self.side.on_launch(self.protocol.launch_message(self.side.key, self.side.game,
                                                       'session-' + 'b' * 32, []))
        self.assertFalse(self.seats.owns(self.side, 0, a))
        with self.assertRaisesRegex(self.protocol.Invalid, 'session'):
            self.seats.claim(self.side, old, object())
        self.assertEqual(self.claim(2)[0], 0)
        self.assertEqual(len(self.seats.seats), 1)

    def test_invalid_tickets_never_allocate(self):
        for ticket in (None, 'bad', self.ticket(game='bluff'), self.ticket(now=0),
                       self.ticket()[:-3] + 'xxx'):
            with self.subTest(ticket=ticket), self.assertRaises(self.protocol.Invalid):
                self.seats.claim(self.side, ticket, object())
        self.assertEqual(self.seats.seats, {})

    def test_spectator_cannot_acquire_input(self):
        ws = object()
        with self.assertRaisesRegex(self.protocol.Invalid, 'spectator'):
            self.seats.claim(self.side, self.ticket(role='spectator'), ws)
        self.assertEqual(self.seats.seats, {})
        self.assertFalse(self.seats.owns(self.side, 0, ws))

    def test_end_invalidates_input_and_tickets(self):
        a = object()
        old = self.ticket()
        self.claim(1, a)
        self.side.on_end(self.protocol.end_message(self.side.key, self.side.game, self.side.sid))
        self.assertFalse(self.seats.owns(self.side, 0, a))
        with self.assertRaises(self.protocol.Invalid):
            self.seats.claim(self.side, old, object())


class ArcadeSocketSeats(unittest.TestCase):
    """Exercise the actual websocket route with fake media, not just the reservation table."""
    def setUp(self):
        PartySeatReservations.setUp(self)
        import json
        module = self.module
        self.s = module.Stream()
        self.s.party_seats = self.seats
        self.s.pipeline = mock.MagicMock()
        self.s.pads = [mock.Mock(), mock.Mock()]
        self.s.request_keyframe = mock.Mock()
        self.s.managed = types.SimpleNamespace(side=self.side, state='running')
        module.Gst = mock.MagicMock()
        module.Gst.CLOCK_TIME_NONE = -1
        module.Gst.PadLinkReturn.OK = module.Gst.parse_bin_from_description.return_value.get_static_pad.return_value.link.return_value
        module.GstWebRTC = mock.MagicMock()
        module.GstSdp = mock.MagicMock()
        module.GstSdp.SDPMessage.new.return_value = (None, mock.Mock())
        module.GstSdp.sdp_message_parse_buffer.return_value = module.GstSdp.SDPResult.OK
        offer = types.SimpleNamespace(sdp=types.SimpleNamespace(as_text=lambda: 'fake'))
        offer.copy = lambda: offer
        self.s.promise = mock.AsyncMock(return_value=types.SimpleNamespace(get_value=lambda _: offer))
        self.s.peer_stats = mock.AsyncMock()
        module.web.WSMsgType = types.SimpleNamespace(TEXT='text')
        self.sockets = []
        sockets = self.sockets

        class Socket:
            def __init__(inner, **kw):
                inner.closed = False
                inner.sent = []
                inner.stopped = asyncio.Event()
                sockets.append(inner)
            async def prepare(inner, request):
                inner.request = request
            async def receive_json(inner, timeout):
                return inner.request.hello
            async def send_json(inner, body):
                inner.sent.append(body)
            async def close(inner, **kw):
                inner.closed = True
                inner.stopped.set()
            def __aiter__(inner):
                async def messages():
                    for body in inner.request.messages:
                        if inner.request.pause is not None and body.get('type') == 'input':
                            inner.request.pause.set()
                            await inner.stopped.wait()
                        yield types.SimpleNamespace(type='text', data=json.dumps(body))
                return messages()
        module.web.WebSocketResponse = Socket

    ticket = PartySeatReservations.ticket

    async def connect(self, ticket, messages=(), pause=None):
        self.s.loop = asyncio.get_running_loop()
        request = types.SimpleNamespace(headers={'Origin': 'https://party.test'}, host='party.test',
                                        remote='127.0.0.1', query={},
                                        hello={'type': 'hello', 'ticket': ticket}, messages=messages, pause=pause)
        return await self.s.websocket(request)

    def test_socket_admission_input_disconnect_and_leave(self):
        async def run():
            ws = await self.connect(self.ticket(), [{'type': 'answer', 'sdp': 'fake'},
                                                    {'type': 'input', 'buttons': ['fire']}])
            self.assertIn({'type': 'player', 'slot': 1}, ws.sent)
            self.s.pads[0].update.assert_any_call(['fire'])
            self.assertEqual(len(self.seats.seats), 1)
            ws = await self.connect(self.ticket(), [{'type': 'leave'}])
            self.assertIn({'type': 'player', 'slot': 1}, ws.sent)
            self.assertEqual(self.seats.seats, {})
        asyncio.run(run())

    def test_socket_refuses_unticketed_and_spectator_without_media_or_input(self):
        async def run():
            for ticket in (None, 'bad', self.ticket(role='spectator'), self.ticket(game='bluff'),
                           self.ticket(now=0)):
                ws = await self.connect(ticket, [{'type': 'input', 'buttons': ['fire']}])
                self.assertEqual(ws.sent[0]['type'], 'error')
                self.assertTrue(ws.closed)
            self.s.pads[0].update.assert_not_called()
            self.module.Gst.ElementFactory.make.assert_not_called()
        asyncio.run(run())

    def test_standalone_disconnect_reuses_first_free_slot(self):
        self.s.managed = None
        async def run():
            for _ in range(2):
                ws = await self.connect(None)
                self.assertIn({'type': 'player', 'slot': 1}, ws.sent)
                self.assertEqual(self.s.reserved, set())
            self.s.reserved.add(0)
            ws = await self.connect(None)
            self.assertIn({'type': 'player', 'slot': 2}, ws.sent)
        asyncio.run(run())

    def test_duplicate_route_closes_old_socket_and_rejects_its_queued_input(self):
        async def run():
            paused = asyncio.Event()
            first = asyncio.create_task(self.connect(self.ticket(), [
                {'type': 'answer', 'sdp': 'fake'}, {'type': 'input', 'buttons': ['magic']}], paused))
            await asyncio.wait_for(paused.wait(), 2)
            newest = await self.connect(self.ticket(), [
                {'type': 'answer', 'sdp': 'fake'}, {'type': 'input', 'buttons': ['fire']}])
            old = await asyncio.wait_for(first, 2)
            self.assertIn({'type': 'error', 'reason': 'replaced'}, old.sent)
            self.assertTrue(old.closed)
            self.assertIn({'type': 'player', 'slot': 1}, newest.sent)
            self.assertEqual(len(self.seats.seats), 1)
            self.s.pads[0].update.assert_any_call(['fire'])
            self.assertNotIn(mock.call(['magic']), self.s.pads[0].update.call_args_list)
            self.s.pads[1].update.assert_not_called()
        asyncio.run(run())

    def test_media_setup_failure_disconnects_binding_and_allows_grace_expiry(self):
        self.module.Gst.ElementFactory.make.side_effect = RuntimeError('no transport')
        async def run():
            with self.assertLogs('avrana-arcade', level='ERROR'):
                ws = await self.connect(self.ticket())
            self.assertTrue(ws.closed)
            self.assertIsNone(next(iter(self.seats.seats.values()))['ws'])
            self.now += self.module.SEAT_GRACE_S
            self.assertEqual(self.seats.claim(self.side, self.ticket(2), object())[0], 0)
        asyncio.run(run())


class ApAddresses(unittest.TestCase):
    """/stats labels a peer's path 'avrana' when its address is on the party AP. The AP is found by
    the party address (10.42.0.1), not an interface name: wlan1 (USB adapter) before 2026-09-24,
    the internal wlan0 since."""

    @classmethod
    def setUpClass(cls):
        cls.stream, _ = load_stream()

    def addresses(self, ip_output):
        fake = types.SimpleNamespace(run=lambda *a, **k: types.SimpleNamespace(stdout=ip_output))
        with mock.patch.object(self.stream, 'subprocess', fake):
            return self.stream.ap_addresses()

    def test_internal_radio_as_ap(self):
        self.assertEqual(self.addresses(IP_NOW), {'10.42.0.1', 'fe80::9afe:54ff:fe34:e550'})

    def test_old_usb_adapter_as_ap(self):
        self.assertEqual(self.addresses(IP_OLD), {'10.42.0.1'})

    def test_no_party_ap(self):
        self.assertEqual(self.addresses('2: eth0    inet 10.0.0.142/24 scope global eth0\n'), set())

    def test_ip_failure_is_empty(self):
        def boom(*a, **k):
            raise FileNotFoundError('ip')
        with mock.patch.object(self.stream, 'subprocess', types.SimpleNamespace(run=boom)):
            self.assertEqual(self.stream.ap_addresses(), set())


class ClientStatsLog(unittest.TestCase):
    """runtime/client-stats.jsonl is bounded (AVR-30): past its cap it rotates to .1, so the
    newest phone stats are kept and the pair never exceeds about twice the cap."""

    def setUp(self):
        self.module, _ = load_stream()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: [p.unlink() for p in self.tmp.iterdir()] and None)
        self.module.CLIENT_LOG = self.tmp / 'client-stats.jsonl'
        self.module.CLIENT_LOG_MAX = 400
        self.stream = self.module.Stream.__new__(self.module.Stream)
        self.peer = {'addr': '10.42.0.23', 'server': {'path': 'wlan'}}

    def test_rotates_past_the_cap_and_keeps_writing(self):
        for i in range(40):
            self.stream.log_client(self.peer, {'n': i})
        log, old = self.module.CLIENT_LOG, self.module.CLIENT_LOG.with_suffix('.jsonl.1')
        self.assertTrue(old.exists())
        self.assertLessEqual(log.stat().st_size, 400 + 200)
        self.assertLessEqual(old.stat().st_size, 400 + 200)
        newest = log.read_text(encoding='utf-8').splitlines()[-1]
        self.assertIn('"n": 39', newest)                 # the newest record is never dropped
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()),
                         ['client-stats.jsonl', 'client-stats.jsonl.1'])


if __name__ == '__main__':
    unittest.main()
