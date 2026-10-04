"""Tier 1: provider boundaries and the arcade's adapters, without evdev, RetroArch or GStreamer.

The uinput adapter is checked against the arcade's original Pad logic (copied below as an oracle)
so the extraction provably writes the same events in the same order.
"""
import random
import subprocess
import sys
import time
import types
import unittest

from avrana.providers.base import InputProvider, PresentationProvider, ProviderInfo, RuntimeProvider, VirtualController
from avrana.providers.controller import ControllerLayout
from avrana.providers.retroarch import RetroArchRuntime
from avrana.providers.uinput_gamepad import UInputGamepadProvider

ARCADE = ControllerLayout(buttons=('fire', 'magic', 'coin', 'start'), directions='dpad')


def fake_evdev(log):
    E = types.SimpleNamespace(EV_KEY=1, EV_ABS=3, ABS_X=0, ABS_Y=1, BTN_SOUTH=304, BTN_EAST=305,
                              BTN_SELECT=314, BTN_START=315)

    class UInput:
        def __init__(self, caps, name, vendor, product):
            log.append(('create', caps, name, vendor, product))

        def write(self, etype, code, value):
            log.append(('write', etype, code, value))

        def syn(self):
            log.append(('syn',))

        def close(self):
            log.append(('close',))

    return types.SimpleNamespace(ecodes=E, UInput=UInput, AbsInfo=lambda *a: ('absinfo',) + a)


class OriginalPad:
    """arcade/stream.py Pad before the extraction (d092ffd), with the device injected."""
    def __init__(self, evdev, slot, log):
        E = evdev.ecodes
        self.E = E
        self.BUTTONS = {'fire': E.BTN_SOUTH, 'magic': E.BTN_EAST, 'coin': E.BTN_SELECT, 'start': E.BTN_START}
        self.ALLOWED = set(self.BUTTONS) | {'up', 'down', 'left', 'right'}
        self.device = evdev.UInput({E.EV_KEY: list(self.BUTTONS.values()), E.EV_ABS: [
            (E.ABS_X, evdev.AbsInfo(0, -32768, 32767, 0, 0, 0)),
            (E.ABS_Y, evdev.AbsInfo(0, -32768, 32767, 0, 0, 0))]},
            name=f'Avrana Player {slot + 1}', vendor=0x1209, product=0xA001 + slot)
        self.state = set()

    def update(self, values):
        E = self.E
        if not isinstance(values, list) or len(values) > 8 or any(
                not isinstance(x, str) or x not in self.ALLOWED for x in values):
            raise ValueError('Invalid controller state')
        new = set(values)
        for name, code in self.BUTTONS.items():
            if (name in new) != (name in self.state):
                self.device.write(E.EV_KEY, code, int(name in new))
        for axis, neg, pos in [(E.ABS_X, 'left', 'right'), (E.ABS_Y, 'up', 'down')]:
            value = int(pos in new) - int(neg in new)
            self.device.write(E.EV_ABS, axis, -32768 if value < 0 else 32767 if value else 0)
        self.device.syn()
        self.state = new


class UInputAdapter(unittest.TestCase):
    def test_identical_to_the_original_pad(self):
        rng = random.Random(3)
        names = sorted(ARCADE.names)
        for slot in (0, 1):
            old_log, new_log = [], []
            old = OriginalPad(fake_evdev(old_log), slot, old_log)
            new = UInputGamepadProvider(evdev=fake_evdev(new_log)).open(slot, ARCADE)
            self.assertEqual(old_log, new_log)  # same device: capabilities, name, vendor, product
            snapshots = [[], ['fire'], ['up', 'left', 'fire'], ['down', 'up'], ['coin', 'start', 'magic']]
            snapshots += [rng.sample(names, rng.randint(0, len(names))) for _ in range(200)]
            for snap in snapshots:
                old.update(list(snap))
                new.update(list(snap))
            self.assertEqual(old_log, new_log)
            self.assertEqual(set(old.state), set(new.state))

    def test_invalid_snapshots_are_refused_like_before(self):
        pad = UInputGamepadProvider(evdev=fake_evdev([])).open(0, ARCADE)
        for bad in (None, 'fire', ['fire'] * 9, ['jump'], [1], {'fire': 1}):
            with self.assertRaisesRegex(ValueError, 'Invalid controller state'):
                pad.set_state(bad)

    def test_neutralize_close_and_protocols(self):
        log = []
        pad = UInputGamepadProvider(evdev=fake_evdev(log)).open(1, ARCADE)
        pad.set_state(['fire', 'left'])
        pad.neutralize()
        self.assertEqual(pad.state, frozenset())
        pad.close()
        self.assertEqual(log[-1], ('close',))
        self.assertIsInstance(pad, VirtualController)
        self.assertIsInstance(UInputGamepadProvider(), InputProvider)
        self.assertEqual(UInputGamepadProvider.info.isolation, 'global')

    def test_evdev_is_imported_lazily(self):
        UInputGamepadProvider()  # no evdev on this machine: constructing must not import it
        self.assertNotIn('evdev', sys.modules)

    def test_unmapped_button(self):
        with self.assertRaises(ValueError):
            UInputGamepadProvider(evdev=fake_evdev([])).open(0, ControllerLayout(buttons=('jump',)))


class Layouts(unittest.TestCase):
    def test_from_contract(self):
        layout = ControllerLayout.from_contract({'model': 'controller_slots', 'slots': 2, 'buttons': ['a', 'b']})
        self.assertEqual(layout.names, frozenset({'a', 'b', 'up', 'down', 'left', 'right'}))
        with self.assertRaises(ValueError):
            ControllerLayout.from_contract({'model': 'browser_native'})
        with self.assertRaises(ValueError):
            ControllerLayout(buttons=('up',))
        self.assertEqual(ControllerLayout(buttons=('a',), directions='none').names, frozenset({'a'}))


class RetroArch(unittest.TestCase):
    def test_command_is_unchanged_and_never_opens_the_network_port(self):
        rt = RetroArchRuntime(config='/r/retroarch.cfg', core='/r/cores/mame2010_libretro.so',
                              content='/srv/avrana/roms/arcade/gaunt2.zip')
        self.assertEqual(rt.command(), ['retroarch', '-v', '-c', '/r/retroarch.cfg', '-L',
                                        '/r/cores/mame2010_libretro.so', '/srv/avrana/roms/arcade/gaunt2.zip'])
        self.assertFalse(any('command' in part or 'host' in part for part in rt.command()))
        self.assertIsInstance(rt, RuntimeProvider)

    def test_lifecycle_with_a_real_process(self):
        rt = RetroArchRuntime(config='c', core='k', content='x', executable=sys.executable, verbose=False,
                              popen=lambda cmd, **kw: subprocess.Popen(
                                  [sys.executable, '-c', 'import time; time.sleep(30)'], **kw))
        self.assertFalse(rt.running())
        rt.stop()  # idempotent before start
        rt.start(stdout=subprocess.DEVNULL)
        self.assertTrue(rt.running())
        with self.assertRaises(RuntimeError):
            rt.start()
        self.assertTrue(rt.status()['running'])
        rt.stop(timeout=5)
        self.assertFalse(rt.running())
        self.assertIsNotNone(rt.status()['exitCode'])

    def test_stop_kills_a_process_that_ignores_terminate(self):
        script = 'import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print("ok", flush=True); time.sleep(30)'
        rt = RetroArchRuntime(config='c', core='k', content='x',
                              popen=lambda cmd, **kw: subprocess.Popen([sys.executable, '-c', script], **kw))
        proc = rt.start(stdout=subprocess.PIPE, stderr=None)
        proc.stdout.readline()  # the handler is installed
        started = time.monotonic()
        rt.stop(timeout=0.5)
        self.assertFalse(rt.running())
        self.assertLess(time.monotonic() - started, 5)
        proc.stdout.close()


class Info(unittest.TestCase):
    def test_provider_info_validates(self):
        with self.assertRaises(ValueError):
            ProviderInfo('x', 'magic', ('a.b',), 'x')
        with self.assertRaises(ValueError):
            ProviderInfo('x', 'input', (), 'x')
        with self.assertRaises(ValueError):
            ProviderInfo('x', 'input', ('a.b',), 'x', isolation='sometimes')
        self.assertNotIn('isolation', ProviderInfo('x', 'runtime', ('a.b',), 'x').describe())

    def test_presentation_protocol_shape(self):
        class Fake:
            info = ProviderInfo('p', 'presentation', ('presentation.shared_stream',), 'fake')

            def request_keyframe(self, reason):
                pass

            def status(self):
                return {}
        self.assertIsInstance(Fake(), PresentationProvider)


class RetroArchConfig(unittest.TestCase):
    '''The arcade runs from a read-only release as a user with no home (ADR 0016): the config
    RetroArch gets must send everything it writes to the service's runtime directory.'''

    def test_the_committed_config_names_no_path_and_the_written_one_only_the_runtime_directory(self):
        import tempfile
        from pathlib import Path
        from avrana import REPO_ROOT
        from avrana.providers import retroarch
        committed = (REPO_ROOT / 'arcade/retroarch.cfg').read_text(encoding='utf-8')
        self.assertNotRegex(committed, r'/home/|_directory\s*=|core_options_path')
        with tempfile.TemporaryDirectory() as d:
            runtime = Path(d) / 'state'
            out = retroarch.write_config(REPO_ROOT / 'arcade/retroarch.cfg', REPO_ROOT / 'arcade/core-options.cfg', runtime)
            text = out.read_text(encoding='utf-8')
            self.assertEqual(out, runtime / 'retroarch.cfg')
            self.assertTrue(text.startswith(committed))
            values = dict(line.split(' = ', 1) for line in text[len(committed):].splitlines() if line)
            self.assertEqual(sorted(values), ['core_options_path', 'savefile_directory', 'savestate_directory',
                                              'screenshot_directory', 'system_directory'])
            for value in values.values():
                self.assertTrue(Path(value.strip('"')).is_relative_to(runtime), value)
            for name in ('system', 'saves', 'screenshots'):
                self.assertTrue((runtime / name).is_dir())
            self.assertEqual((runtime / 'core-options.cfg').read_bytes(),
                             (REPO_ROOT / 'arcade/core-options.cfg').read_bytes())
            # a second start keeps saves and takes the committed core options again
            (runtime / 'saves/nvram').write_text('kept')
            (runtime / 'core-options.cfg').write_text('rewritten by RetroArch')
            retroarch.write_config(REPO_ROOT / 'arcade/retroarch.cfg', REPO_ROOT / 'arcade/core-options.cfg', runtime)
            self.assertEqual((runtime / 'saves/nvram').read_text(), 'kept')
            self.assertEqual(out.read_text(encoding='utf-8'), text)
            self.assertNotEqual((runtime / 'core-options.cfg').read_text(), 'rewritten by RetroArch')

    def test_prepare_runs_before_each_start_and_supplies_the_config(self):
        from avrana.providers.retroarch import RetroArchRuntime
        seen = []

        class Proc:
            def poll(self):
                return 0
        r = RetroArchRuntime(config='unused', core='k', content='x', prepare=lambda: 'written.cfg',
                             popen=lambda cmd, **kw: seen.append(cmd) or Proc())
        r.start()
        self.assertEqual(seen[0][seen[0].index('-c') + 1], 'written.cfg')


if __name__ == '__main__':
    unittest.main()
