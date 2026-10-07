"""Tier 1: the PS1 input provider, its key banks and the check of the owner's content
(avrana/providers/ps1.py).

The XTest provider runs against a fake X11 with a fake clock, so press, hold and release timing is
exact. The banks are checked against ps1/mode-xvfb.cfg, the file RetroArch reads. The content check
runs on temporary directories holding a few synthetic bytes: no X server, no emulator, and no ROM,
BIOS or core anywhere. The X11, XTestPad and BANKS code was recovered from the donor branch
(experiment/ps1-title-profiles, 4b8fa60), which had no tests for it.
"""
import asyncio
import contextlib
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from avrana import REPO_ROOT
from avrana.providers import ps1
from avrana.providers.base import InputProvider, VirtualController
from avrana.providers.controller import ControllerLayout

# The seats' layouts exactly as the Game Contracts declare them.
BOMBERMAN = ControllerLayout.from_contract(
    json.loads((REPO_ROOT / 'contracts/games/ps1-bomberman.json').read_text(encoding='utf-8'))['input'])
WORMS = ControllerLayout.from_contract(
    json.loads((REPO_ROOT / 'contracts/games/ps1-worms.json').read_text(encoding='utf-8'))['input'])
FULL = ControllerLayout(buttons=ps1.BUTTONS[4:], directions='dpad')       # all fourteen names

# The donor's BANKS (stream_ps1.py at 4b8fa60), copied here so that editing the module's banks fails a test.
DONOR_BANKS = (
    ('Up', 'Down', 'Left', 'Right', 'z', 'x', 'a', 's', 'q', 'w', 'e', 'r', 'Return', 'Shift_R'),
    ('t', 'g', 'f', 'h', 'v', 'b', 'n', 'm', 'y', 'u', 'i', 'o', '1', '2'),
    ('KP_8', 'KP_5', 'KP_4', 'KP_6', 'KP_1', 'KP_2', 'KP_7', 'KP_9', 'KP_0', 'KP_Decimal',
     'KP_Divide', 'KP_Multiply', 'KP_Enter', 'KP_Add'),
    ('F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7', 'F8', 'F11', 'F12', 'Prior', 'Next', 'F9', 'F10'),
)
# X keysym -> the name RetroArch's keyboard driver gives the same key in a config file.
RETROARCH_KEY = {
    'Up': 'up', 'Down': 'down', 'Left': 'left', 'Right': 'right', 'Return': 'enter', 'Shift_R': 'rshift',
    '1': 'num1', '2': 'num2', 'Prior': 'pageup', 'Next': 'pagedown',
    'KP_0': 'keypad0', 'KP_1': 'keypad1', 'KP_2': 'keypad2', 'KP_4': 'keypad4', 'KP_5': 'keypad5',
    'KP_6': 'keypad6', 'KP_7': 'keypad7', 'KP_8': 'keypad8', 'KP_9': 'keypad9', 'KP_Decimal': 'kp_period',
    'KP_Divide': 'divide', 'KP_Multiply': 'multiply', 'KP_Enter': 'kp_enter', 'KP_Add': 'add',
}
# PS1 button -> the RetroPad control the mode config binds (its comment: "RetroPad -> PS1: b=Cross
# a=Circle y=Square x=Triangle").
RETROPAD = {'up': 'up', 'down': 'down', 'left': 'left', 'right': 'right', 'cross': 'b', 'circle': 'a',
            'square': 'y', 'triangle': 'x', 'l1': 'l', 'r1': 'r', 'l2': 'l2', 'r2': 'r2', 'start': 'start',
            'select': 'select'}


def retroarch_key(keysym):
    return RETROARCH_KEY.get(keysym, keysym.lower())


def link_directory(target, link):
    """Make `link` lead to the directory `target`: a symbolic link, or on Windows a junction, which
    needs no privilege. Skips the test on a host that can make neither."""
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except (OSError, NotImplementedError):
        pass
    if os.name == 'nt':
        made = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)], capture_output=True)
        if made.returncode == 0:
            return
    raise unittest.SkipTest('this host can create neither a symbolic link nor a junction')


class FakeX11:
    """The surface of ps1.X11, recording every call."""

    def __init__(self, missing=()):
        self.missing, self.codes, self.names, self.log, self.closed = set(missing), {}, {}, [], False
        self.held = set()            # the keys the X server holds down; clearing the log does not release them
        self.fail_on = None          # a keysym whose release raises, like a connection that has gone

    def keycode(self, name):
        if name in self.missing:
            raise RuntimeError(f'no keycode for {name}')
        code = self.codes.setdefault(name, 10 + len(self.codes))
        self.names[code] = name
        return code

    def key(self, code, down):
        if self.names[code] == self.fail_on:
            raise RuntimeError('X connection lost')
        (self.held.add if down else self.held.discard)(self.names[code])
        self.log.append(('key', self.names[code], bool(down)))

    def flush(self):
        self.log.append(('flush',))

    def close(self):
        self.closed = True

    def keys(self):
        """[(keysym, down)] for every key event so far."""
        return [(entry[1], entry[2]) for entry in self.log if entry[0] == 'key']

    def down_now(self):
        return set(self.held)


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeLoop:
    """call_later on the fake clock; run() moves time forward and fires what falls due, in order."""

    class Timer:
        def __init__(self, when, callback):
            self.when, self.callback, self.cancelled = when, callback, False

        def cancel(self):
            self.cancelled = True

    def __init__(self, clock):
        self.clock, self.timers = clock, []

    def call_later(self, delay, callback):
        timer = self.Timer(self.clock.now + delay, callback)
        self.timers.append(timer)
        return timer

    def pending(self):
        return [t for t in self.timers if not t.cancelled]

    def run(self, seconds):
        end = self.clock.now + seconds
        while True:
            due = [t for t in self.pending() if t.when <= end]
            if not due:
                break
            timer = min(due, key=lambda t: t.when)
            self.timers.remove(timer)
            self.clock.now = max(self.clock.now, timer.when)
            timer.callback()
        self.clock.now = end


class KeyBanks(unittest.TestCase):
    def test_the_banks_are_the_donors(self):
        self.assertEqual(ps1.BANKS, DONOR_BANKS)
        self.assertEqual(len(ps1.BANKS), 4)
        self.assertEqual(ps1.MAX_SLOTS, 4)
        self.assertTrue(all(len(bank) == len(ps1.BUTTONS) == 14 for bank in ps1.BANKS))
        self.assertEqual(ps1.BUTTONS, ('up', 'down', 'left', 'right', 'cross', 'circle', 'square', 'triangle',
                                       'l1', 'r1', 'l2', 'r2', 'start', 'select'))
        self.assertEqual(ps1.MIN_HOLD, 0.040)

    def test_every_bank_key_is_bound_in_mode_xvfb_to_the_same_player_and_button(self):
        """RetroArch reads these bindings: a key that is not bound, or bound to another button, is a
        controller that does not work (or drives somebody else's)."""
        cfg = dict(re.findall(r'^\s*(input_player[0-9]_[a-z0-9]+)\s*=\s*"([^"]*)"',
                              (ps1.PS1_DIR / 'mode-xvfb.cfg').read_text(encoding='utf-8'), re.M))
        for slot, bank in enumerate(ps1.BANKS):
            for button, keysym in zip(ps1.BUTTONS, bank):
                with self.subTest(slot=slot + 1, button=button, key=keysym):
                    self.assertEqual(cfg[f'input_player{slot + 1}_{RETROPAD[button]}'], retroarch_key(keysym))

    def test_no_two_seats_share_a_key_and_none_is_a_hotkey_enable_or_lock(self):
        keys = [key for bank in ps1.BANKS for key in bank]
        self.assertEqual(len(keys), len(set(keys)), 'a shared key would drive two players')
        bound = [retroarch_key(key) for key in keys]
        self.assertEqual(len(bound), len(set(bound)))
        for forbidden in ('Scroll_Lock', 'Num_Lock', 'Caps_Lock', 'Shift_L', 'Control_L', 'Control_R', 'Alt_L',
                          'Escape'):
            self.assertNotIn(forbidden, keys)

    def test_mode_xvfb_binds_five_retroarch_users_and_only_four_have_banks(self):
        text = (ps1.PS1_DIR / 'mode-xvfb.cfg').read_text(encoding='utf-8')
        self.assertEqual(sorted({int(n) for n in re.findall(r'input_player([0-9]+)_', text)}), [1, 2, 3, 4, 5])
        self.assertEqual(ps1.MAX_USERS, 5)
        self.assertEqual(ps1.MAX_SLOTS, 4)          # user 5 (a multitap's fourth pad) has keys but no seat


class ControllerBehaviour(unittest.TestCase):
    def setUp(self):
        self.x11, self.clock = FakeX11(), Clock()
        self.loop = FakeLoop(self.clock)
        self.provider = ps1.XTestKeysProvider(':99', connect=lambda display, authority: self.x11, loop=self.loop,
                                              clock=self.clock, sleep=self.clock.advance)

    def seat(self, slot=0, layout=BOMBERMAN):
        return self.provider.open(slot, layout)

    def test_opening_a_seat_releases_its_whole_bank_and_presses_nothing(self):
        self.seat(1)
        self.assertEqual(self.x11.keys(), [(key, False) for key in ps1.BANKS[1]])
        self.assertEqual(self.x11.log[-1], ('flush',))
        self.assertEqual(self.x11.down_now(), set())

    def test_a_snapshot_presses_its_own_seats_keys_and_nobody_elses(self):
        first, second = self.seat(0), self.seat(1)
        self.x11.log.clear()
        second.set_state(['left', 'cross'])
        self.assertEqual(self.x11.keys(), [('f', True), ('v', True)])    # seat 2's left and cross, in pad order
        self.assertEqual(self.x11.log[-1], ('flush',))
        self.assertEqual(second.state, frozenset({'left', 'cross'}))
        self.assertEqual(first.state, frozenset())
        self.assertTrue(self.x11.down_now().isdisjoint(ps1.BANKS[0]))

    def test_every_button_of_every_seat_presses_its_own_bank_key(self):
        for slot in range(4):
            pad = self.seat(slot, FULL)
            for button, key in zip(ps1.BUTTONS, ps1.BANKS[slot]):
                with self.subTest(slot=slot, button=button):
                    self.x11.log.clear()
                    pad.set_state([button])
                    self.assertEqual(self.x11.keys(), [(key, True)])
                    self.clock.advance(0.05)
                    pad.set_state([])
                    self.assertEqual(self.x11.down_now(), set())
            pad.close()

    def test_a_snapshot_is_the_whole_truth_so_dropping_a_name_releases_its_key(self):
        pad = self.seat()
        pad.set_state(['up', 'cross'])
        self.clock.advance(0.05)
        self.x11.log.clear()
        pad.set_state(['up'])
        self.assertEqual(self.x11.keys(), [('z', False)])
        pad.set_state(['up'])                       # nothing changed: nothing is sent
        self.assertEqual(self.x11.keys(), [('z', False)])
        self.assertEqual(self.x11.down_now(), {'Up'})

    def test_a_key_released_after_the_minimum_hold_goes_up_at_once(self):
        pad = self.seat()
        pad.set_state(['cross'])
        self.clock.advance(ps1.MIN_HOLD)
        self.x11.log.clear()
        pad.set_state([])
        self.assertEqual(self.x11.keys(), [('z', False)])
        self.assertEqual(self.loop.pending(), [])

    def test_a_tap_shorter_than_the_minimum_hold_is_held_for_it(self):
        pad = self.seat()
        pad.set_state(['cross'])
        self.clock.advance(0.010)
        self.x11.log.clear()
        pad.set_state([])                            # the phone let go after 10 ms
        self.assertEqual(self.x11.keys(), [])        # the key stays down
        self.assertEqual(pad.state, frozenset())     # while the seat already says it holds nothing
        (timer,) = self.loop.pending()
        self.assertAlmostEqual(timer.when - self.clock.now, 0.030, places=9)
        self.loop.run(0.029)                         # 39 ms after the press
        self.assertEqual(self.x11.down_now(), {'z'})
        self.loop.run(0.002)                         # 41 ms
        self.assertEqual(self.x11.keys(), [('z', False)])
        self.assertEqual(self.loop.pending(), [])

    def test_a_press_while_the_release_waits_keeps_the_key_down(self):
        pad = self.seat()
        pad.set_state(['cross'])
        self.clock.advance(0.010)
        pad.set_state([])
        self.clock.advance(0.010)
        self.x11.log.clear()
        pad.set_state(['cross'])                     # held again before the first tap's 40 ms were up
        self.loop.run(0.100)
        self.assertEqual(self.x11.keys(), [])        # never released, and not pressed a second time
        self.assertEqual(self.x11.down_now(), {'z'})

    def test_two_keys_each_wait_out_their_own_hold(self):
        pad = self.seat()
        pad.set_state(['cross'])
        self.clock.advance(0.020)
        pad.set_state(['cross', 'circle'])
        self.clock.advance(0.005)
        self.x11.log.clear()
        pad.set_state([])                            # cross has 15 ms to go, circle 35 ms
        self.assertEqual(self.x11.keys(), [])
        self.loop.run(0.016)
        self.assertEqual(self.x11.keys(), [('z', False)])
        self.loop.run(0.010)
        self.assertEqual(self.x11.keys(), [('z', False)])
        self.loop.run(0.020)
        self.assertEqual(self.x11.keys(), [('z', False), ('x', False)])
        self.assertEqual(self.loop.pending(), [])

    def test_without_an_event_loop_the_caller_waits_out_the_hold_and_no_longer(self):
        provider = ps1.XTestKeysProvider(':99', connect=lambda display, authority: self.x11, clock=self.clock,
                                         sleep=self.clock.advance)
        pad = provider.open(0, BOMBERMAN)
        pad.set_state(['cross'])
        pressed_at = self.clock.now
        self.clock.advance(0.010)
        pad.set_state([])
        self.assertEqual(self.x11.down_now(), set())
        held = self.clock.now - pressed_at
        self.assertGreaterEqual(held, ps1.MIN_HOLD - 1e-9)
        self.assertLess(held, ps1.MIN_HOLD + 0.001)

    def test_neutralize_releases_everything_at_once_even_inside_the_hold(self):
        pad = self.seat()
        pad.set_state(['up', 'left', 'cross', 'start'])
        self.clock.advance(0.010)
        pad.set_state(['up'])                        # three releases are waiting
        (timer,) = self.loop.pending()
        self.x11.log.clear()
        self.clock.advance(5)
        pad.neutralize()
        self.assertEqual(self.x11.keys(), [(key, False) for key in ps1.BANKS[0]])
        self.assertEqual(self.x11.down_now(), set())
        self.assertEqual(pad.state, frozenset())
        self.assertEqual(pad.updated, self.clock.now)
        self.assertTrue(timer.cancelled)
        self.assertEqual(self.loop.pending(), [])
        pad.set_state(['cross'])                     # and the seat works again afterwards
        self.assertEqual(self.x11.down_now(), {'z'})

    def test_neutralize_releases_keys_a_crashed_process_left_down(self):
        pad = self.seat()
        pad.neutralize()
        self.assertEqual(self.x11.keys()[-14:], [(key, False) for key in ps1.BANKS[0]])
        self.assertEqual(self.x11.down_now(), set())

    def test_close_releases_everything_and_refuses_further_snapshots(self):
        pad = self.seat()
        pad.set_state(['cross'])
        self.x11.log.clear()
        pad.close()
        self.assertEqual(self.x11.keys(), [(key, False) for key in ps1.BANKS[0]])
        with self.assertRaises(RuntimeError):
            pad.set_state(['cross'])
        pad.close()                                  # idempotent
        pad.neutralize()                             # harmless
        self.assertEqual(len(self.x11.keys()), 14)
        self.assertFalse(self.x11.closed)            # the shared connection belongs to the provider
        self.seat().set_state(['cross'])             # the slot can be opened again

    def test_a_slot_cannot_be_opened_twice_at_once(self):
        self.seat(2)
        with self.assertRaisesRegex(ValueError, 'already open'):
            self.seat(2)
        self.seat(3)

    def test_invalid_snapshots_are_refused_like_the_arcades_and_change_nothing(self):
        pad = self.seat()
        pad.set_state(['cross'])
        self.x11.log.clear()
        for bad in (None, 'cross', ['cross'] * 20, ['jump'], [1], {'cross': 1}, ['l1']):   # l1: not in this layout
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, 'Invalid controller state'):
                pad.set_state(bad)
        self.assertEqual(self.x11.keys(), [])
        self.assertEqual(pad.state, frozenset({'cross'}))

    def test_a_layout_with_only_the_d_pad_is_enough(self):
        """The Worms contract (hotseat) declares no buttons, so its layout is the d-pad alone."""
        for layout in (WORMS, ControllerLayout(buttons=())):
            with self.subTest(layout=layout):
                pad = self.seat(0, layout)
                pad.set_state(['left', 'down'])
                self.assertEqual(self.x11.down_now(), {'Down', 'Left'})
                with self.assertRaises(ValueError):
                    pad.set_state(['cross'])
                pad.close()

    def test_a_layout_needs_a_key_for_every_name(self):
        with self.assertRaisesRegex(ValueError, 'no XTest key'):
            self.seat(0, ControllerLayout(buttons=('fire', 'magic')))
        with self.assertRaises(ValueError):
            self.seat(0, ControllerLayout(buttons=('cross', 'jump')))
        self.assertEqual(self.x11.log, [])           # refused before anything was pressed or connected

    def test_slots_are_zero_to_three(self):
        for bad in (-1, 4, 99, True, '0', None, 1.0):
            with self.subTest(slot=bad), self.assertRaises(ValueError):
                self.seat(bad)

    def test_a_missing_keysym_fails_the_open_not_a_later_press(self):
        provider = ps1.XTestKeysProvider(':99', connect=lambda display, authority: FakeX11(missing={'KP_Add'}))
        provider.open(0, BOMBERMAN)
        with self.assertRaisesRegex(RuntimeError, 'no keycode for KP_Add'):
            provider.open(2, BOMBERMAN)

    def test_the_arcades_stale_input_policy_and_cleanup_work_on_it(self):
        """arcade/stream.py: `if pad.state and time.monotonic() - pad.updated > 0.3: pad.update([])`,
        and its cleanup closes `pad.device`."""
        pad = self.seat()
        self.clock.advance(10)                       # the seat has been open a while before the phone speaks
        pad.update(['up'])
        self.assertEqual(pad.updated, self.clock.now)
        self.clock.advance(0.25)
        self.assertFalse(pad.state and self.clock() - pad.updated > 0.3)
        self.clock.advance(0.1)
        self.assertTrue(pad.state and self.clock() - pad.updated > 0.3)
        pad.update([])
        self.assertEqual(self.x11.down_now(), set())
        pad.update(['right'])
        self.assertIs(pad.device, pad)
        pad.device.close()
        self.assertEqual(self.x11.down_now(), set())
        with self.assertRaises(RuntimeError):
            pad.update(['right'])


class ProviderBehaviour(unittest.TestCase):
    def test_it_is_an_input_provider_and_its_controllers_are_virtual_controllers(self):
        x11 = FakeX11()
        provider = ps1.XTestKeysProvider(':0', connect=lambda display, authority: x11)
        self.assertIsInstance(provider, InputProvider)
        self.assertIsInstance(provider.open(0, BOMBERMAN), VirtualController)
        info = ps1.XTestKeysProvider.info
        self.assertEqual((info.id, info.kind, info.isolation), ('xtest-keys', 'input', 'private'))
        self.assertEqual(info.describe(), {'id': 'xtest-keys', 'kind': 'input', 'offers': ['input.virtual_gamepad'],
                                           'isolation': 'private'})

    def test_it_takes_the_layouts_of_both_titles(self):
        for layout in (BOMBERMAN, WORMS):
            provider = ps1.XTestKeysProvider(':0', connect=lambda display, authority: FakeX11())
            provider.open(0, layout)
            provider.close()

    def test_it_agrees_with_what_the_appliance_profile_already_declares_for_it(self):
        """The profile lists xtest-keys as an experiment with no adapter; naming the adapter is a
        follow-up's contract change. What it declares must already be true of this class."""
        profile = json.loads((REPO_ROOT / 'contracts/appliances/avrana-pi4.json').read_text(encoding='utf-8'))
        declared = next(p for p in profile['providers'] if p['id'] == 'xtest-keys')
        info = ps1.XTestKeysProvider.info
        self.assertEqual((info.id, info.kind, sorted(info.offers)),
                         (declared['id'], declared['kind'], sorted(declared['offers'])))
        self.assertIn(f'isolation: {info.isolation}', declared['implementation'])

    def test_the_display_must_be_a_local_one(self):
        for good in (':0', ':99', ':99.0', ':1001'):
            ps1.XTestKeysProvider(good)
        for bad in ('', 'host:0', 'tcp/host:6000', ':99;rm', ':', ':x', ':99\n', '10.0.0.1:0', None, 99):
            with self.subTest(display=bad), self.assertRaisesRegex(ValueError, 'local X display'):
                ps1.XTestKeysProvider(bad)

    def test_it_connects_once_at_the_first_open_and_shares_the_connection(self):
        made = []

        def connect(display, authority):
            made.append((display, authority))
            return FakeX11()
        provider = ps1.XTestKeysProvider(':77', '/run/cookie', connect=connect)
        self.assertEqual(made, [])                                       # constructing connects to nothing
        with self.assertRaises(ValueError):
            provider.open(9, BOMBERMAN)
        self.assertEqual(made, [])                                       # neither does a refused open
        a, b = provider.open(0, BOMBERMAN), provider.open(1, BOMBERMAN)
        self.assertEqual(made, [(':77', '/run/cookie')])
        self.assertIs(a._x11, b._x11)

    def test_close_releases_every_seat_then_closes_the_connection_and_can_repeat(self):
        connections = []

        def connect(display, authority):
            connections.append(FakeX11())
            return connections[-1]
        provider = ps1.XTestKeysProvider(':5', connect=connect, sleep=lambda seconds: None)
        a, b = provider.open(0, BOMBERMAN), provider.open(3, BOMBERMAN)
        a.set_state(['up'])
        b.set_state(['cross'])
        x11 = connections[0]
        x11.log.clear()
        provider.close()
        self.assertEqual(x11.down_now(), set())
        self.assertEqual(len(x11.keys()), 28)
        self.assertTrue(x11.closed)
        provider.close()
        for pad in (a, b):
            with self.assertRaises(RuntimeError):
                pad.set_state(['up'])
        provider.open(0, BOMBERMAN)                                      # a fresh connection
        self.assertEqual(len(connections), 2)

    def test_a_seat_that_cannot_release_does_not_stop_the_others_or_the_connection_closing(self):
        x11 = FakeX11()
        provider = ps1.XTestKeysProvider(':5', connect=lambda display, authority: x11, sleep=lambda seconds: None)
        first, second = provider.open(0, BOMBERMAN), provider.open(1, BOMBERMAN)
        second.set_state(['cross'])
        x11.fail_on = 'Up'                                               # seat 1's first key fails to release
        with self.assertRaisesRegex(RuntimeError, 'X connection lost'):
            provider.close()
        self.assertNotIn('v', x11.down_now())                            # seat 2's cross went up all the same
        self.assertTrue(x11.closed)
        with self.assertRaises(RuntimeError):
            first.set_state(['up'])

    def test_x11_is_not_loaded_until_a_controller_is_opened(self):
        with mock.patch('ctypes.CDLL', side_effect=AssertionError('libX11 was loaded too early')):
            provider = ps1.XTestKeysProvider(':99')
            self.assertIsInstance(provider, InputProvider)
        with mock.patch('ctypes.CDLL', side_effect=OSError('libX11.so.6: cannot open shared object file')):
            with self.assertRaisesRegex(RuntimeError, 'libX11.so.6 and libXtst.so.6'):
                provider.open(0, BOMBERMAN)
        self.assertIsNone(provider._x11)

    def test_the_module_imports_and_describes_itself_without_x(self):
        code = 'import avrana.providers.ps1 as ps1; print(ps1.INFO.isolation, len(ps1.BANKS))'
        done = subprocess.run([sys.executable, '-c', code], cwd=REPO_ROOT, capture_output=True, text=True)
        self.assertEqual((done.returncode, done.stdout.strip()), (0, 'private 4'), done.stderr)


class FakeLib:
    """libX11 or libXtst: every function records its call and answers from `answers`; functions take
    attributes the way ctypes ones do (restype, argtypes)."""

    def __init__(self, calls, answers):
        self._calls, self._answers, self._functions = calls, answers, {}

    def __getattr__(self, name):
        if name not in self._functions:
            def function(*args, _name=name):
                self._calls.append((_name,) + args)
                return self._answers.get(_name, lambda *a: None)(*args)
            self._functions[name] = function
        return self._functions[name]


class X11Wrapper(unittest.TestCase):
    """ps1.X11 against fake libraries: the ctypes wiring, with no X server."""

    def setUp(self):
        self.calls, self.seen_authority = [], []
        self.answers = {'XOpenDisplay': self.open_display, 'XStringToKeysym': lambda name: 0xFF0D,
                        'XKeysymToKeycode': lambda dpy, keysym: 36}
        self.libs = {'libX11.so.6': FakeLib(self.calls, self.answers),
                     'libXtst.so.6': FakeLib(self.calls, self.answers)}
        self.display_opens = True

    def open_display(self, name):
        self.seen_authority.append(os.environ.get('XAUTHORITY'))
        return 0xBEEF if self.display_opens else None

    def cdll(self, name):
        if name not in self.libs:
            raise OSError(f'{name}: cannot open shared object file')
        return self.libs[name]

    def x11(self, display=':99', authority=None):
        return ps1.X11(display, authority, cdll=self.cdll)

    def test_it_opens_the_display_and_talks_xtest(self):
        x11 = self.x11(':42')
        self.assertEqual(self.calls, [('XOpenDisplay', b':42')])
        self.assertEqual(x11.keycode('Return'), 36)
        self.assertEqual(self.calls[1:], [('XStringToKeysym', b'Return'), ('XKeysymToKeycode', 0xBEEF, 0xFF0D)])
        self.calls.clear()
        x11.key(36, True)
        x11.key(36, False)
        x11.flush()
        self.assertEqual(self.calls, [('XTestFakeKeyEvent', 0xBEEF, 36, 1, 0), ('XTestFakeKeyEvent', 0xBEEF, 36, 0, 0),
                                      ('XFlush', 0xBEEF)])

    def test_the_foreign_function_signatures_are_declared(self):
        import ctypes
        self.x11()
        x, tst = self.libs['libX11.so.6'], self.libs['libXtst.so.6']
        self.assertIs(x.XOpenDisplay.restype, ctypes.c_void_p)
        self.assertEqual(x.XOpenDisplay.argtypes, [ctypes.c_char_p])
        self.assertIs(x.XKeysymToKeycode.restype, ctypes.c_ubyte)
        self.assertEqual(tst.XTestFakeKeyEvent.argtypes,
                         [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong])

    def test_an_unknown_keysym_is_an_error(self):
        x11 = self.x11()
        self.answers['XStringToKeysym'] = lambda name: 0
        self.answers['XKeysymToKeycode'] = lambda dpy, keysym: 0
        with self.assertRaisesRegex(RuntimeError, 'no keycode for Nope'):
            x11.keycode('Nope')

    def test_a_display_that_will_not_open_is_an_error_naming_it(self):
        self.display_opens = False
        with self.assertRaisesRegex(RuntimeError, 'cannot open PS1 display :99'):
            self.x11()

    def test_missing_libraries_are_an_error_that_names_them(self):
        del self.libs['libXtst.so.6']
        with self.assertRaisesRegex(RuntimeError, 'libX11.so.6 and libXtst.so.6'):
            self.x11()

    def test_the_cookie_file_is_in_the_environment_only_while_the_display_opens(self):
        with mock.patch.dict(os.environ, {'XAUTHORITY': 'before'}):
            self.x11(authority='/run/ps1/cookie')
            self.assertEqual(os.environ['XAUTHORITY'], 'before')
        with mock.patch.dict(os.environ, clear=False):
            os.environ.pop('XAUTHORITY', None)
            self.x11(authority='/run/ps1/cookie')
            self.assertNotIn('XAUTHORITY', os.environ)
        self.assertEqual(self.seen_authority, ['/run/ps1/cookie', '/run/ps1/cookie'])

    def test_a_closed_connection_refuses_to_press_instead_of_crashing_the_process(self):
        x11 = self.x11()
        x11.close()
        self.assertIn(('XCloseDisplay', 0xBEEF), self.calls)
        for call in (lambda: x11.key(36, True), x11.flush, lambda: x11.keycode('Return')):
            with self.assertRaisesRegex(RuntimeError, 'closed'):
                call()
        before = len(self.calls)
        x11.close()
        self.assertEqual(len(self.calls), before)

    def test_the_provider_uses_it_by_default(self):
        provider = ps1.XTestKeysProvider(':42', '/run/ps1/cookie')
        with mock.patch('ctypes.CDLL', side_effect=self.cdll):
            pad = provider.open(0, BOMBERMAN)
            pad.set_state(['cross'])
        self.assertIn(('XTestFakeKeyEvent', 0xBEEF, 36, 1, 0), self.calls)


class RunningEventLoop(unittest.IsolatedAsyncioTestCase):
    async def test_a_short_tap_is_finished_by_the_running_loop(self):
        x11, clock = FakeX11(), Clock()
        provider = ps1.XTestKeysProvider(':99', connect=lambda display, authority: x11, clock=clock)
        pad = provider.open(0, BOMBERMAN)               # no loop passed: the running one is found
        pad.set_state(['cross'])
        clock.advance(0.010)
        pad.set_state([])
        self.assertEqual(x11.down_now(), {'z'})         # still held: the release is the loop's job now
        clock.advance(1)                                # the controller's clock has moved on; the timer is real
        for _ in range(100):
            if not x11.down_now():
                break
            await asyncio.sleep(0.02)
        self.assertEqual(x11.down_now(), set())


# --- the owner's content ----------------------------------------------------------------------

CORE_BYTES = b'synthetic core, not libretro'


class ContentFixture(unittest.TestCase):
    """A content root with a few synthetic bytes where a disc and a BIOS would be."""

    def setUp(self):
        self.build()

    def build(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name)
        self.root = self.tmp / 'content'
        self.root.mkdir()
        self.profile = ps1.load('bomberman')
        self.cue = ps1.cue_path(self.profile, self.root)
        self.folder = self.cue.parent
        self.bin = self.folder / (self.cue.stem + '.bin')
        self.folder.mkdir(parents=True)
        self.cue.write_text(f'FILE "{self.bin.name}" BINARY\r\n  TRACK 01 MODE2/2352\r\n    INDEX 01 00:00:00\r\n',
                            encoding='utf-8', newline='')
        self.bin.write_bytes(b'not a disc')
        self.bios = self.root / ps1.BIOS_NAME
        self.bios.write_bytes(b'\0' * ps1.BIOS_SIZE)
        self.core = self.tmp / 'pcsx_rearmed_libretro.so'
        self.core.write_bytes(CORE_BYTES)
        self.pin = {'core': 'pcsx_rearmed_libretro.so', 'so_sha256': hashlib.sha256(CORE_BYTES).hexdigest()}

    def check(self, **kw):
        kw.setdefault('root', self.root)
        kw.setdefault('core_path', self.core)
        kw.setdefault('pin', self.pin)
        kw.setdefault('environ', {})
        return ps1.check_content(self.profile, **kw)

    def codes(self, report):
        return [c.code for c in report.checks]

    def failing(self, report):
        return [(c.name, c.code) for c in report.failures]


class ContentCheck(ContentFixture):
    def test_all_good(self):
        report = self.check()
        self.assertTrue(report.ok)
        self.assertEqual(report.failures, ())
        self.assertEqual([c.name for c in report.checks], ['content_root', 'cue', 'bin', 'bios', 'core'])
        self.assertEqual(set(self.codes(report)), {'ok'})
        self.assertEqual(report.title, 'bomberman')

    def test_the_report_is_json_safe_and_names_no_absolute_path(self):
        text = json.dumps(self.check().to_dict())
        self.assertIn(self.profile['cue'].split('/')[-1], text)
        for private in (str(self.tmp), str(self.root), self.tmp.name):
            self.assertNotIn(private, text)
            self.assertNotIn(private.replace('\\', '/'), text)
        broken = self.check(core_path=self.tmp / 'missing.so')
        self.assertNotIn(self.tmp.name, json.dumps(broken.to_dict()))

    def test_missing_cue(self):
        self.cue.unlink()
        report = self.check()
        self.assertEqual(self.failing(report), [('cue', 'cue_missing')])
        self.assertEqual([c.name for c in report.checks], ['content_root', 'cue', 'bios', 'core'])   # the rest ran
        self.assertIn('cue sheet', report.failures[0].detail)

    def test_missing_bin(self):
        self.bin.unlink()
        report = self.check()
        self.assertEqual(self.failing(report), [('bin', 'bin_missing')])
        self.assertIn(self.bin.name, report.failures[0].detail)

    def test_every_bin_the_cue_names_must_be_there(self):
        (self.folder / 'Track 02.bin').write_bytes(b'x')
        self.cue.write_text(f'FILE "{self.bin.name}" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n'
                            'FILE "Track 02.bin" BINARY\n  TRACK 02 AUDIO\n    INDEX 01 00:00:00\n'
                            'file "Track 03.bin" binary\n  TRACK 03 AUDIO\n    INDEX 01 00:00:00\n'
                            f'FILE "{self.bin.name}" BINARY\n', encoding='utf-8')         # a repeated name counts once
        report = self.check()
        bins = [c for c in report.checks if c.name == 'bin']
        self.assertEqual([(c.ok, c.code) for c in bins], [(True, 'ok'), (True, 'ok'), (False, 'bin_missing')])
        self.assertIn('Track 03.bin', bins[2].detail)

    def test_unquoted_names_and_a_byte_order_mark_are_read(self):
        (self.folder / 'game.bin').write_bytes(b'x')
        self.cue.write_bytes(b'\xef\xbb\xbfFILE game.bin BINARY\r\n')
        self.assertEqual(self.failing(self.check()), [])

    def test_bios_of_the_wrong_size(self):
        for size in (0, 1024, ps1.BIOS_SIZE - 1, ps1.BIOS_SIZE + 1):
            with self.subTest(size=size):
                self.bios.write_bytes(b'\0' * size)
                report = self.check()
                self.assertEqual(self.failing(report), [('bios', 'bios_wrong_size')])
                self.assertIn(f'{size} bytes', report.failures[0].detail)
                self.assertIn('524288', report.failures[0].detail)
        self.assertEqual(ps1.BIOS_SIZE, 524288)

    def test_bios_missing_or_named_in_another_case(self):
        self.bios.rename(self.root / 'scph1001.bin')
        self.assertEqual(self.failing(self.check()), [])           # case does not matter
        (self.root / 'scph1001.bin').unlink()
        self.assertEqual(self.failing(self.check()), [('bios', 'bios_missing')])
        (self.root / ps1.BIOS_NAME).mkdir()                        # a folder is not an image
        self.assertEqual(self.failing(self.check()), [('bios', 'bios_missing')])

    def test_core_hash_mismatch(self):
        self.core.write_bytes(CORE_BYTES + b'!')
        report = self.check()
        self.assertEqual(self.failing(report), [('core', 'core_hash_mismatch')])
        detail = report.failures[0].detail
        self.assertIn(hashlib.sha256(CORE_BYTES + b'!').hexdigest()[:16], detail)
        self.assertIn(self.pin['so_sha256'][:16], detail)

    def test_core_missing_and_unset(self):
        self.assertEqual(self.failing(self.check(core_path=self.tmp / 'nope.so')), [('core', 'core_missing')])
        self.assertEqual(self.failing(self.check(core_path=self.tmp)), [('core', 'core_missing')])    # a folder
        self.assertEqual(self.failing(self.check(core_path=None)), [('core', 'core_unset')])
        self.assertEqual(self.failing(self.check(core_path='')), [('core', 'core_unset')])

    def test_an_unusable_pin_is_its_own_failure(self):
        for pin in ({}, {'so_sha256': 'ABC'}, {'so_sha256': 'A' * 64}, {'so_sha256': 7}, {'so_sha256': None}, [], 'x'):
            with self.subTest(pin=pin):
                self.assertEqual(self.failing(self.check(pin=pin)), [('core', 'core_pin_invalid')])
        unreadable = ps1.ProfileError('the core pin x.json cannot be read')
        with mock.patch.object(ps1, 'load_core_pin', side_effect=unreadable):
            self.assertEqual(self.failing(self.check(pin=None)), [('core', 'core_pin_invalid')])

    def test_the_content_root_comes_from_the_argument_or_the_environment_never_from_a_default(self):
        env = {ps1.ENV_CONTENT: str(self.root), ps1.ENV_CORE: str(self.core)}
        self.assertTrue(ps1.check_content(self.profile, pin=self.pin, environ=env).ok)
        other = self.tmp / 'other'                                   # an argument beats the environment
        other.mkdir()
        self.assertEqual(self.failing(ps1.check_content(self.profile, other, pin=self.pin, environ=env)),
                         [('cue', 'cue_missing'), ('bios', 'bios_missing')])
        report = ps1.check_content(self.profile, pin=self.pin, environ={})          # nothing given: no guessing
        self.assertEqual(self.failing(report), [('content_root', 'content_root_unset'), ('core', 'core_unset')])
        self.assertIn(ps1.ENV_CONTENT, report.failures[0].detail)
        self.assertIn(ps1.ENV_CORE, report.failures[1].detail)
        empty = ps1.check_content(self.profile, '', pin=self.pin, environ={ps1.ENV_CONTENT: ''})
        self.assertEqual(empty.failures[0].code, 'content_root_unset')
        with mock.patch.dict(os.environ, env):                       # the process environment is the default
            self.assertTrue(ps1.check_content(self.profile, pin=self.pin).ok)

    def test_a_content_root_that_is_not_a_folder(self):
        for root in (self.tmp / 'absent', self.bios):
            with self.subTest(root=root):
                report = self.check(root=root)
                self.assertEqual(self.failing(report), [('content_root', 'content_root_missing')])
                self.assertEqual([c.name for c in report.checks], ['content_root', 'core'])   # the core is separate

    def test_a_cue_that_cannot_be_read_as_a_cue_sheet(self):
        self.cue.write_bytes(b'FILE "\xff\xfe.bin" BINARY\n')
        self.assertEqual(self.failing(self.check()), [('cue', 'cue_invalid')])
        self.assertIn('UTF-8', self.check().failures[0].detail)
        self.cue.write_bytes(b'x' * (ps1.MAX_CUE_BYTES + 1))
        self.assertEqual(self.failing(self.check()), [('cue', 'cue_invalid')])
        self.assertIn('1 MiB', self.check().failures[0].detail)
        self.cue.write_text(''.join(f'FILE "t{n}.bin" BINARY\n' for n in range(ps1.MAX_CUE_FILES + 1)),
                            encoding='utf-8')
        self.assertEqual(self.failing(self.check()), [('cue', 'cue_invalid')])
        self.assertIn(f'more than {ps1.MAX_CUE_FILES} files', self.check().failures[0].detail)
        self.cue.write_text('REM nothing here\nTITLE "x"\n', encoding='utf-8')
        self.assertEqual(self.failing(self.check()), [('cue', 'cue_no_files')])
        self.cue.unlink()
        self.cue.mkdir()                                             # a folder where the cue sheet belongs
        self.assertEqual(self.failing(self.check()), [('cue', 'cue_missing')])

    def test_a_cue_may_not_point_outside_its_folder(self):
        (self.root / 'outside.bin').write_bytes(b'x')                # it exists, and it still is refused
        for name in ('../../outside.bin', '..\\..\\outside.bin', '/etc/hostname', '\\\\host\\share\\x.bin',
                     'C:\\x.bin', '', 'a/../../../outside.bin'):
            with self.subTest(name=name):
                self.cue.write_text(f'FILE "{name}" BINARY\n', encoding='utf-8')
                self.assertEqual(self.failing(self.check()), [('bin', 'bin_unsafe')])
        sub = self.folder / 'Disc 1'
        sub.mkdir()
        (sub / 'track.bin').write_bytes(b'x')
        self.cue.write_text('FILE "Disc 1/track.bin" BINARY\n', encoding='utf-8')               # a subfolder is fine
        self.assertEqual(self.failing(self.check()), [])
        self.assertEqual([c.subject for c in self.check().checks if c.name == 'bin'],
                         [self.profile['cue'].rsplit('/', 1)[0] + '/Disc 1/track.bin'])

    def test_a_long_name_in_a_cue_sheet_is_cut_in_the_report(self):
        self.cue.write_text('FILE "' + '../' * 100 + '" BINARY\n', encoding='utf-8')
        report = self.check()
        self.assertEqual(self.failing(report), [('bin', 'bin_unsafe')])
        self.assertLess(len(report.failures[0].subject), 100)
        self.assertLess(len(report.failures[0].detail), 200)

    def test_a_cue_path_that_leads_out_of_the_root_is_refused(self):
        with mock.patch.object(ps1, 'cue_path', side_effect=ps1.ContentPathError('cue escapes the content root')):
            self.assertEqual(self.failing(self.check()), [('cue', 'cue_outside_root')])

    def test_a_cue_path_that_loops_through_links_is_a_failure_not_a_crash(self):
        with mock.patch.object(Path, 'resolve', side_effect=RuntimeError('Symlink loop from x')):
            self.assertEqual(self.failing(self.check()), [('cue', 'cue_outside_root')])

    def test_a_linked_disc_folder_that_leaves_the_root_is_refused(self):
        away = self.tmp / 'elsewhere'
        away.mkdir()
        top = self.root / self.profile['cue'].split('/')[0]
        for child in top.iterdir():
            child.rename(away / child.name)
        top.rmdir()
        link_directory(away, top)
        self.assertEqual(self.failing(self.check()), [('cue', 'cue_outside_root')])

    def test_only_the_cue_sheet_and_the_core_are_ever_opened(self):
        """A content check may not read game data: the disc image and the BIOS are only looked at."""
        opened, real_open = [], open

        def spy(file, *args, **kwargs):
            opened.append(Path(os.fspath(file)))
            return real_open(file, *args, **kwargs)
        with mock.patch('builtins.open', spy):
            report = self.check()
        self.assertTrue(report.ok)
        self.assertEqual(sorted(opened), sorted([self.cue, self.core]))

    def test_a_file_the_user_may_not_look_at_is_a_failure_not_a_crash(self):
        denied = PermissionError(13, 'Permission denied')
        with mock.patch.object(ps1, '_is_file', side_effect=denied):
            report = self.check()
        self.assertEqual(self.failing(report), [('cue', 'unreadable'), ('bios', 'unreadable'), ('core', 'unreadable')])
        self.assertIn('Permission denied', report.failures[0].detail)
        self.assertIn('read access', report.failures[0].detail)
        with mock.patch.object(ps1, '_is_dir', side_effect=denied):
            self.assertEqual(self.failing(self.check()), [('content_root', 'unreadable')])
        with mock.patch.object(ps1, 'file_sha256', side_effect=PermissionError('denied')):
            self.assertEqual(self.failing(self.check()), [('core', 'unreadable')])
        with mock.patch.object(ps1.os, 'listdir', side_effect=denied):       # the BIOS lookup lists the root
            self.assertEqual(self.failing(self.check()), [('bios', 'unreadable')])

    def test_the_file_probes_say_not_there_only_for_not_there(self):
        """Path.is_file() answers False for a folder the user may not enter from Python 3.13 on, which would
        read as "the cue sheet is not there"; these let the permission error through to be reported."""
        self.assertTrue(ps1._is_file(self.bios))
        self.assertFalse(ps1._is_file(self.folder))                  # a folder is not a file
        self.assertFalse(ps1._is_file(self.root / 'absent.bin'))
        self.assertFalse(ps1._is_file(self.bios / 'inside-a-file'))
        self.assertTrue(ps1._is_dir(self.folder))
        self.assertFalse(ps1._is_dir(self.bios))
        self.assertFalse(ps1._is_dir(self.root / 'absent'))
        for probe in (ps1._is_file, ps1._is_dir):
            with mock.patch.object(ps1.os, 'stat', side_effect=PermissionError(13, 'Permission denied')):
                with self.assertRaises(PermissionError):
                    probe(self.bios)

    def test_every_failure_is_distinct_documented_and_exercised(self):
        """Fifteen ways to be wrong, fifteen different codes, each with its own sentence."""
        denied = mock.patch.object(ps1, 'file_sha256', side_effect=PermissionError(13, 'Permission denied'))
        outside = mock.patch.object(ps1, 'cue_path', side_effect=ps1.ContentPathError('cue escapes the root'))
        scenarios = [
            ('content_root_unset', lambda: self.check(root=None)),
            ('content_root_missing', lambda: self.check(root=self.tmp / 'absent')),
            ('unreadable', lambda: self.with_patch(denied)),
            ('cue_outside_root', lambda: self.with_patch(outside)),
            ('cue_missing', lambda: (self.cue.unlink(), self.check())[1]),
            ('cue_invalid', lambda: (self.cue.write_bytes(b'\xff'), self.check())[1]),
            ('cue_no_files', lambda: (self.cue.write_text('REM\n'), self.check())[1]),
            ('bin_unsafe', lambda: (self.cue.write_text('FILE "../x.bin" BINARY\n'), self.check())[1]),
            ('bin_missing', lambda: (self.bin.unlink(), self.check())[1]),
            ('bios_missing', lambda: (self.bios.unlink(), self.check())[1]),
            ('bios_wrong_size', lambda: (self.bios.write_bytes(b'0'), self.check())[1]),
            ('core_unset', lambda: self.check(core_path=None)),
            ('core_missing', lambda: (self.core.unlink(), self.check())[1]),
            ('core_pin_invalid', lambda: self.check(pin={})),
            ('core_hash_mismatch', lambda: (self.core.write_bytes(b'other'), self.check())[1]),
        ]
        sentences = {}
        for code, run in scenarios:
            with self.subTest(code=code):
                self.build()                                         # a fresh, good content root each time
                report = run()
                self.assertEqual([c.code for c in report.failures], [code])
                self.assertFalse(report.ok)
                sentences[code] = report.failures[0].detail
        self.assertEqual(set(sentences), set(ps1.FAILURES))
        self.assertEqual(len(set(sentences.values())), len(sentences), 'every failure has its own sentence')
        self.assertTrue(all(len(sentence) > 20 for sentence in sentences.values()))

    def with_patch(self, patcher):
        with patcher:
            return self.check()

    def test_a_check_cannot_contradict_itself(self):
        ps1.Check('cue', 'x', True, 'ok', 'fine')
        ps1.Check('cue', 'x', False, 'cue_missing', 'gone')
        for ok, code in ((True, 'cue_missing'), (False, 'ok'), (False, 'made_up'), (True, 'made_up')):
            with self.subTest(ok=ok, code=code), self.assertRaisesRegex(ValueError, 'inconsistent check'):
                ps1.Check('cue', 'x', ok, code, 'x')

    def test_a_profile_that_is_not_valid_is_the_only_thing_that_raises(self):
        with self.assertRaises(ps1.MultitapError):                   # even with nothing configured to look at
            ps1.check_content(dict(self.profile, multitap='port 1'), environ={}, pin=self.pin)
        with self.assertRaises(ps1.ProfileError):
            ps1.check_content(None, self.root, self.core, environ={}, pin=self.pin)

    def test_the_content_check_has_no_hard_coded_location(self):
        code = (REPO_ROOT / 'avrana/providers/ps1.py').read_text(encoding='utf-8')
        self.assertNotRegex(code, r'/home/|~/|\bPath\.home|expanduser|/srv/|/mnt/|/media/|/Users/')
        self.assertEqual((ps1.ENV_CONTENT, ps1.ENV_CORE), ('AVRANA_PS1_CONTENT', 'AVRANA_PS1_CORE'))

    def test_the_shipped_core_pin_is_a_usable_pin(self):
        pin = ps1.load_core_pin()
        self.assertEqual(pin['core'], 'pcsx_rearmed_libretro.so')
        self.assertRegex(pin['so_sha256'], r'^[0-9a-f]{64}$')
        with tempfile.TemporaryDirectory() as folder:
            for text in ('{}', '[1]', '{"so_sha256": "x"}',
                         '{"so_sha256": "' + 'a' * 64 + '", "so_sha256": "' + 'b' * 64 + '"}', 'not json'):
                path = Path(folder) / 'pin.json'
                path.write_text(text, encoding='utf-8')
                with self.subTest(text=text), self.assertRaises(ps1.ProfileError):
                    ps1.load_core_pin(path)
            with self.assertRaises(ps1.ProfileError):
                ps1.load_core_pin(Path(folder) / 'absent.json')

    def test_the_pin_is_what_decides_not_the_core_file_name(self):
        """A file called pcsx_rearmed_libretro.so with other bytes is not the pinned build."""
        shipped = ps1.load_core_pin()['so_sha256']
        self.assertNotEqual(hashlib.sha256(CORE_BYTES).hexdigest(), shipped)
        report = self.check(pin=None)
        self.assertEqual(self.failing(report), [('core', 'core_hash_mismatch')])
        self.assertIn(shipped[:16], report.failures[0].detail)


class CommandLine(ContentFixture):
    def run_main(self, *argv, environ=None):
        out, err = io.StringIO(), io.StringIO()
        code = ps1.main(list(argv), environ={} if environ is None else environ, stdout=out, stderr=err)
        return code, out.getvalue(), err.getvalue()

    def test_a_ready_title_exits_zero(self):
        with mock.patch.object(ps1, 'load_core_pin', return_value=self.pin):
            code, out, err = self.run_main('check', 'bomberman', '--content', str(self.root), '--core', str(self.core))
        self.assertEqual((code, err), (0, ''))
        self.assertIn('PS1 content check: bomberman (SLUS-01189)', out)
        self.assertIn('all 5 checks passed', out)
        self.assertNotIn('FAIL', out)

    def test_the_environment_names_work_on_the_command_line_too(self):
        env = {ps1.ENV_CONTENT: str(self.root), ps1.ENV_CORE: str(self.core)}
        with mock.patch.object(ps1, 'load_core_pin', return_value=self.pin):
            self.assertEqual(self.run_main('check', 'worms', environ=env)[0], 1)    # Worms' disc is not there
            self.assertEqual(self.run_main('check', 'bomberman', environ=env)[0], 0)

    def test_a_problem_exits_one_and_says_which(self):
        self.bios.write_bytes(b'short')
        code, out, err = self.run_main('check', 'bomberman', '--content', str(self.root), '--core', str(self.core))
        self.assertEqual(code, 1)
        self.assertIn('FAIL  bios', out)
        self.assertIn('[bios_wrong_size]', out)
        self.assertIn('[core_hash_mismatch]', out)               # the shipped pin is not the synthetic core
        self.assertIn('2 of 5 checks failed', out)
        self.assertNotIn(self.tmp.name, out + err)               # no absolute path of the owner's machine

    def test_nothing_configured_says_what_to_set(self):
        code, out, _ = self.run_main('check', 'bomberman')
        self.assertEqual(code, 1)
        self.assertIn(ps1.ENV_CONTENT, out)
        self.assertIn(ps1.ENV_CORE, out)

    def test_an_unknown_title_is_refused(self):
        code, out, err = self.run_main('check', 'nope')
        self.assertEqual((code, out), (1, ''))
        self.assertIn('ps1: unknown title', err)
        self.assertEqual(self.run_main('check', '../x')[0], 1)

    def test_usage_errors_exit_two(self):
        for argv in ([], ['check'], ['launch', 'bomberman']):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    ps1.main(argv, environ={})
            self.assertEqual(caught.exception.code, 2)

    def test_it_runs_as_a_module(self):
        done = subprocess.run([sys.executable, '-m', 'avrana.providers.ps1', 'check', 'bomberman'], cwd=REPO_ROOT,
                              env={k: v for k, v in os.environ.items() if not k.startswith('AVRANA_PS1_')},
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 1)
        self.assertIn('content_root_unset', done.stdout)
        self.assertEqual(done.stderr, '')


if __name__ == '__main__':
    unittest.main()
