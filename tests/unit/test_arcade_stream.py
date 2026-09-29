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
    web = types.SimpleNamespace(json_response=lambda data: data)
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
        self.assertTrue(str(s.runtime.core).endswith('arcade/cores/mame2010_libretro.so'))

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


# 'ip -o addr show' output as the Pi prints it (the literal backslash ends each record).
IP_NOW = r"""1: lo    inet 127.0.0.1/8 scope host lo\       valid_lft forever preferred_lft forever
2: eth0    inet 10.0.0.142/24 brd 10.0.0.255 scope global dynamic noprefixroute eth0\       valid_lft 86000sec
3: wlan0    inet 10.42.0.1/24 brd 10.42.0.255 scope global noprefixroute wlan0\       valid_lft forever
3: wlan0    inet6 fe80::9afe:54ff:fe34:e550/64 scope link noprefixroute \       valid_lft forever
"""
IP_OLD = r"""2: wlan0    inet 10.0.0.143/24 brd 10.0.0.255 scope global wlan0\       valid_lft 86000sec
4: wlan1    inet 10.42.0.1/24 brd 10.42.0.255 scope global wlan1\       valid_lft forever
"""


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
