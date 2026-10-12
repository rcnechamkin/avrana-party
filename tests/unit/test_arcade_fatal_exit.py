"""Tier 1/2: a fatal emulator or pipeline failure ends the arcade process non-zero (so systemd's
Restart=on-failure can bring it back), after cleanup; ordinary client churn never does.

GStreamer, aiohttp and python-evdev are stubbed and a stand-in process plays RetroArch, so this
proves the process lifecycle, not streaming on the Pi, and not systemd itself.
"""
import asyncio
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import types
import unittest
from unittest import mock
from pathlib import Path

from avrana import REPO_ROOT
from avrana.providers.retroarch import RetroArchRuntime
from avrana.providers.uinput_gamepad import UInputGamepadProvider

from test_arcade_stream import FakePipeline, load_stream
from test_providers import fake_evdev


class FakeSocket:
    def __init__(self):
        self.closed_with = None

    async def close(self, code=None, message=None):
        if self.closed_with is None:  # cleanup() closes again later; keep the first code
            self.closed_with = code


class ErrorBus:
    def __init__(self):
        self.error = None

    def pop_filtered(self, _):
        if self.error is None:
            return None
        err, self.error = self.error, None
        return types.SimpleNamespace(parse_error=lambda: (err, 'debug'))


def sleeper(seconds):
    return lambda cmd, **kw: subprocess.Popen([sys.executable, '-c', f'import time; time.sleep({seconds})'], **kw)


class WatchLoop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stream, cls.gst = load_stream()

    def make(self, log, runtime_seconds=30):
        s = self.stream.Stream()
        s.input = UInputGamepadProvider(evdev=fake_evdev(log))
        s.runtime = RetroArchRuntime(config='c', core='k', content='x', popen=sleeper(runtime_seconds))
        s.exits = 0
        s.request_exit = lambda: setattr(s, 'exits', s.exits + 1)
        self.pipeline = FakePipeline()
        self.bus = ErrorBus()
        self.pipeline.get_bus = lambda: self.bus
        self.gst.parse_launch = lambda description: self.pipeline
        return s

    def run_case(self, s, during):
        with tempfile.TemporaryDirectory() as tmp:
            self.stream.EMULATOR_LOG = Path(tmp) / 'emulator.log'
            os.environ.setdefault('PULSE_SERVER', 'unix:/nonexistent')

            async def run():
                await s.startup(None)
                result = await during(s)
                await s.cleanup(None)
                return result
            return asyncio.run(run())

    def test_emulator_death_is_fatal_and_cleans_up(self):
        log = []
        s = self.make(log)
        peer = FakeSocket()

        async def during(s):
            s.peers[peer] = {}
            s.runtime.process.kill()
            await asyncio.wait_for(s.monitor, 5)
        self.run_case(s, during)
        self.assertEqual(s.error, 'Emulator exited')
        self.assertTrue(s.fatal)
        self.assertEqual(s.exits, 1)
        self.assertEqual(peer.closed_with, 1011)
        self.assertEqual(sum(1 for e in log if e[0] == 'close'), self.stream.MAX_PLAYERS)   # every pad released
        self.assertEqual(self.pipeline.states[-1], 'NULL')

    def test_pipeline_error_is_fatal_and_stops_the_emulator(self):
        log = []
        s = self.make(log)

        async def during(s):
            self.bus.error = 'Could not encode'
            await asyncio.wait_for(s.monitor, 5)
        self.run_case(s, during)
        self.assertEqual(s.error, 'Could not encode')
        self.assertTrue(s.fatal)
        self.assertEqual(s.exits, 1)
        self.assertFalse(s.runtime.running())
        self.assertEqual(sum(1 for e in log if e[0] == 'close'), self.stream.MAX_PLAYERS)

    def test_silent_video_stall_is_fatal(self):
        """2026-09-28: the encoder stopped returning frames with no bus ERROR; the process stayed
        'active', /stats had error null, and every phone failed. Silence must end the process."""
        log = []
        s = self.make(log)
        peer = FakeSocket()

        async def during(s):
            s.peers[peer] = {}
            s.last_sample['video'] = time.monotonic()   # video flowed once, then stopped
            await asyncio.wait_for(s.monitor, 5)
        with mock.patch.object(self.stream, 'VIDEO_STALL_S', 0.3):
            self.run_case(s, during)
        self.assertEqual(s.error, 'Video capture stalled')
        self.assertTrue(s.fatal)
        self.assertEqual(s.exits, 1)
        self.assertEqual(peer.closed_with, 1011)
        self.assertFalse(s.runtime.running())
        self.assertEqual(sum(1 for e in log if e[0] == 'close'), self.stream.MAX_PLAYERS)

    def test_video_that_never_starts_is_fatal(self):
        s = self.make([])

        async def during(s):
            await asyncio.wait_for(s.monitor, 5)
        with mock.patch.object(self.stream, 'VIDEO_STALL_S', 0.3):
            self.run_case(s, during)
        self.assertEqual(s.error, 'Video capture stalled')
        self.assertEqual(s.exits, 1)

    def test_flowing_video_is_not_fatal(self):
        s = self.make([])

        async def during(s):
            for _ in range(10):   # one frame every 0.1 s for a second: well past the stall limit
                s.last_sample['video'] = time.monotonic()
                await asyncio.sleep(0.1)
            stats = await s.stats(None)
            return s.monitor.done(), stats
        with mock.patch.object(self.stream, 'VIDEO_STALL_S', 0.3):
            done, stats = self.run_case(s, during)
        self.assertFalse(done)
        self.assertFalse(s.fatal)
        self.assertIsNone(stats['error'])
        self.assertLess(stats['sample_age_s']['video'], 0.3)

    def test_client_churn_is_not_fatal(self):
        s = self.make([])

        async def during(s):
            for _ in range(3):   # phones joining, dropping and reconnecting
                peer = FakeSocket()
                s.peers[peer] = {}
                await asyncio.sleep(0.15)
                s.peers.pop(peer)
            await asyncio.sleep(0.3)
            return s.monitor.done()
        self.assertFalse(self.run_case(s, during))   # the watcher is still running
        self.assertFalse(s.fatal)
        self.assertEqual(s.exits, 0)
        self.assertIsNone(s.error)


# Minimal stand-ins so arcade/stream.py can run as __main__ in a child process.
STUBS = {
    'gi/__init__.py': """
        import types, os
        def require_version(*a): pass
        """,
    'gi/repository.py': """
        import os, types
        class _E(types.SimpleNamespace): pass
        class _Bus:
            def pop_filtered(self, *a): return None
        class _Pipe:
            def get_by_name(self, n): return types.SimpleNamespace(connect=lambda *a: None)
            def set_state(self, s):
                with open(os.environ['AVRANA_TEST_LOG'], 'a') as f: f.write('pipeline %s\\n' % s)
                return 'SUCCESS'
            def get_bus(self): return _Bus()
        Gst = types.SimpleNamespace(init=lambda *a: None, State=_E(PLAYING='PLAYING', NULL='NULL'),
            StateChangeReturn=_E(FAILURE='FAILURE'), MessageType=_E(ERROR='ERROR'), CLOCK_TIME_NONE=-1,
            parse_launch=lambda d: _Pipe())
        GstVideo = GstWebRTC = GstSdp = types.SimpleNamespace()
        """,
    'aiohttp/__init__.py': """
        import asyncio, signal, types
        class Application:
            def __init__(self, **kw):
                self.router = types.SimpleNamespace(add_get=lambda *a: None)
                self.on_startup, self.on_cleanup = [], []
        def run_app(app, **kw):
            # aiohttp's contract: SIGTERM/SIGINT end the app gracefully, running on_cleanup.
            async def main():
                stop = asyncio.Event()
                loop = asyncio.get_running_loop()
                for sig in (signal.SIGTERM, signal.SIGINT):
                    loop.add_signal_handler(sig, stop.set)
                for f in app.on_startup: await f(app)
                await stop.wait()
                for f in app.on_cleanup: await f(app)
            asyncio.run(main())
        web = types.SimpleNamespace(Application=Application, run_app=run_app, FileResponse=None,
                                    json_response=lambda d: d)
        """,
    'evdev/__init__.py': """
        import os, types
        ecodes = types.SimpleNamespace(EV_KEY=1, EV_ABS=3, ABS_X=0, ABS_Y=1, BTN_SOUTH=304, BTN_EAST=305,
                                       BTN_SELECT=314, BTN_START=315)
        def AbsInfo(*a): return a
        class UInput:
            def __init__(self, *a, **k): pass
            def write(self, *a): pass
            def syn(self): pass
            def close(self):
                with open(os.environ['AVRANA_TEST_LOG'], 'a') as f: f.write('pad closed\\n')
        """,
    # A stand-in RetroArch: runs for AVRANA_TEST_EMULATOR_SECONDS, then dies with an error.
    'bin/retroarch': """
        #!/bin/sh
        sleep "${AVRANA_TEST_EMULATOR_SECONDS:-30}"
        exit 3
        """,
}


class ProcessLifecycle(unittest.TestCase):
    """Runs the real arcade/stream.py entry point as a child process."""

    @classmethod
    def setUpClass(cls):
        cls.stream, _ = load_stream()       # only for MAX_PLAYERS: the child process is the real file

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for rel, text in STUBS.items():
            path = self.tmp / 'stubs' / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(text).lstrip())
        (self.tmp / 'stubs' / 'bin' / 'retroarch').chmod(0o755)
        # A private copy, so runtime/ logs never land in the repository checkout.
        (self.tmp / 'arcade' / 'runtime').mkdir(parents=True)
        for name in ('stream.py', 'retroarch.cfg', 'core-options.cfg'):     # what a start reads from its own directory
            shutil.copy(REPO_ROOT / 'arcade' / name, self.tmp / 'arcade' / name)
        self.log = self.tmp / 'events.log'
        self.log.touch()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def start(self, emulator_seconds):
        env = dict(os.environ, PYTHONPATH=f'{self.tmp / "stubs"}{os.pathsep}{REPO_ROOT}',
                   PATH=f'{self.tmp / "stubs" / "bin"}{os.pathsep}{os.environ["PATH"]}',
                   PULSE_SERVER='unix:/nonexistent', AVRANA_TEST_LOG=str(self.log),
                   AVRANA_TEST_EMULATOR_SECONDS=str(emulator_seconds), PYTHONDONTWRITEBYTECODE='1')
        return subprocess.Popen([sys.executable, str(self.tmp / 'arcade' / 'stream.py')], env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)

    def test_emulator_crash_exits_non_zero_after_cleanup(self):
        proc = self.start(emulator_seconds=3)   # startup waits 2.5 s, then the emulator dies
        try:
            code = proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            self.fail('the arcade kept running after its emulator died (systemd would never restart it)')
        finally:
            proc.stderr.close()
        self.assertEqual(code, 1)
        events = self.log.read_text().splitlines()
        self.assertEqual(events.count('pad closed'), self.stream.MAX_PLAYERS)
        self.assertEqual(events.count('pipeline NULL'), 1)

    def test_a_normal_stop_still_exits_zero(self):
        proc = self.start(emulator_seconds=60)
        try:
            deadline = time.monotonic() + 15
            while 'pipeline PLAYING' not in self.log.read_text():
                self.assertLess(time.monotonic(), deadline, 'the arcade never started')
                self.assertIsNone(proc.poll(), 'the arcade exited during startup')
                time.sleep(0.1)
            proc.send_signal(signal.SIGTERM)   # what `systemctl stop` sends
            code = proc.wait(timeout=20)
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.stderr.close()
        self.assertEqual(code, 0)   # not a failure: no restart after a deliberate stop
        self.assertEqual(self.log.read_text().splitlines().count('pad closed'), self.stream.MAX_PLAYERS)


if __name__ == '__main__':
    unittest.main()
