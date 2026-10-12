"""Party recovery and robustness (AVR-33): host actions as presence, a switch whose next game
fails, a host who disappears mid-switch, the device store after a bad power cut, and the clock.
T1: Party Core with an injected clock, PartyService with a scripted link, no sockets."""
import http.server
import json
import logging
import os
import socket
import tempfile
import threading
import time
import unittest

from avrana.party import core, identity, protocol, record, service, sessions
from avrana.party.protocol import Invalid

from test_party_service import GAME_ORIGINS, HOST, ORIGIN, ServiceCase

BLUFF = {'id': 'bluff', 'max_players': 3, 'late_join': 'spectator_only'}
BOMBER = {'id': 'bomber', 'max_players': 4, 'late_join': 'spectator_only'}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


def make(close_lost_game=False):
    clock = Clock()
    return core.PartyCore(clock, {g['id']: g for g in (BLUFF, BOMBER)}, close_lost_game=close_lost_game), clock


class HostActionIsPresence(unittest.TestCase):
    """core.py promises that any authenticated party request makes a member `here`. A host who
    acts while their phone had gone quiet (inside the host grace) must be in the roster they
    start, not a spectator of their own game."""

    def test_a_host_who_starts_a_game_after_a_quiet_spell_plays_it(self):
        pc, clock = make()
        ana = pc.join('device-a', 'Ana')
        pc.join('device-b', 'Ben')
        clock.advance(core.LIVE_WINDOW + 5)                  # Ana's phone was asleep: 'away'
        pc.touch('device-b')
        self.assertEqual(pc.presence(ana), 'away')
        self.assertEqual(pc.party.host_id, ana.id)           # still inside the host grace
        s = pc.launch('device-a', 'bluff', pc.party.version)
        self.assertEqual(s.participants[ana.id].role, 'player')

    def test_the_host_handing_over_after_a_quiet_spell_is_seen_to_be_here(self):
        pc, clock = make()
        ana = pc.join('device-a', 'Ana')
        ben = pc.join('device-b', 'Ben')
        clock.advance(core.LIVE_WINDOW + 5)
        pc.touch('device-b')
        pc.transfer_host('device-a', ben.id, pc.party.version)
        self.assertEqual(pc.presence(ana), 'here')


class SwitchRecovery(unittest.TestCase):
    """The host's switch ends the old game, then launches the next. Whatever goes wrong, every
    phone must end up somewhere it can recover from without the host doing anything."""

    def setUp(self):
        self.clock = Clock()
        self.launch_ok, self.end_ok = True, True
        self.calls = []
        outer = self

        class Link:
            def launch(self, session, roster):
                outer.calls.append(('launch', session.game_id, session.id))
                return outer.launch_ok, None if outer.launch_ok else 'The game said no.'

            def end(self, session):
                outer.calls.append(('end', session.game_id, session.id))
                return outer.end_ok

        self.svc = service.PartyService(identity.DeviceStore(None),
                                        {g['id']: g for g in (BLUFF, BOMBER)}, Link(),
                                        clock=self.clock)
        self.ana = self.svc.core.join('device-a', 'Ana')
        self.ben = self.svc.core.join('device-b', 'Ben')

    def v(self):
        return self.svc.core.party.version

    def test_a_switch_whose_next_launch_fails_sends_everyone_home_and_stops_that_game(self):
        first = self.svc.launch('device-a', 'bluff', self.v())
        self.launch_ok = False
        nxt = self.svc.switch('device-a', 'bomber', self.v())
        view = self.svc.view('device-b')
        self.assertEqual((view['state'], view['nav']['to'], view['location']['at']), ('lobby', 'home', 'home'))
        self.assertEqual((view['session']['outcome'], view['session']['detail']),
                         ('launch_failed', 'The game said no.'))
        self.assertEqual([c[:2] for c in self.calls],
                         [('launch', 'bluff'), ('end', 'bluff'), ('launch', 'bomber'), ('end', 'bomber')])
        self.assertEqual(self.calls[-1][2], nxt.id)                  # the failed start was rolled back
        self.assertIsNone(self.svc.core.party.pending)
        # the host is not needed to recover: a fresh start works at once
        self.launch_ok = True
        self.svc.launch('device-a', 'bluff', self.v())
        self.assertEqual(self.svc.view('device-b')['state'], 'active')
        self.assertNotEqual(first.id, self.svc.core.party.session.id)

    def test_a_switch_whose_old_game_will_not_stop_starts_nothing_and_says_so(self):
        self.svc.launch('device-a', 'bluff', self.v())
        self.end_ok = False
        self.svc.switch('device-a', 'bomber', self.v())
        view = self.svc.view('device-b')
        self.assertEqual((view['state'], view['nav']['to'], view['switching_to']), ('lobby', 'home', None))
        self.assertIn('did not stop', view['session']['detail'])
        self.assertEqual([c[:2] for c in self.calls], [('launch', 'bluff'), ('end', 'bluff')])


class HostGoneMidGame(unittest.TestCase):
    def test_a_host_who_vanishes_in_a_game_hands_the_results_screen_to_someone_who_can_move_on(self):
        pc, clock = make()
        ana = pc.join('device-a', 'Ana')
        ben = pc.join('device-b', 'Ben')
        s = pc.launch('device-a', 'bluff', pc.party.version)
        pc.launch_accepted(s.id)
        pc.begin_switch('device-a', 'bomber', pc.party.version)
        pc.end_confirmed(s.id, True)
        nxt = pc.launch_pending()
        pc.launch_accepted(nxt.id)
        clock.advance(core.LIVE_WINDOW + core.HOST_GRACE)       # Ana's phone never comes back
        pc.touch('device-b')
        pc.tick()
        self.assertEqual(pc.party.host_id, ana.id)              # in the game: the role stays (design)
        pc.game_reported_end(nxt.id, 'completed')
        clock.advance(core.LIVE_WINDOW + core.HOST_GRACE)       # the results screen is up
        pc.touch('device-b')
        pc.tick()
        self.assertEqual(pc.party.host_id, ben.id)
        self.assertEqual(pc.location()['at'], 'results')
        pc.go_home('device-b', pc.party.version)                # a host who can move everyone on
        self.assertEqual(pc.location()['at'], 'home')

    def test_a_lone_member_who_leaves_mid_game_and_returns_has_their_seat_and_the_host_role(self):
        pc, clock = make()
        solo = pc.join('device-a', 'Ana')
        s = pc.launch('device-a', 'bluff', pc.party.version)
        pc.launch_accepted(s.id)
        pid = s.participants[solo.id].id
        pc.leave('device-a')
        self.assertIsNone(pc.party.host_id)
        clock.advance(core.LIVE_WINDOW * 4)
        pc.tick()
        pc.join('device-a', 'Ana')
        self.assertEqual(pc.party.host_id, solo.id)
        _, p = pc.participant_for('device-a', 'bluff')
        self.assertEqual((p.id, p.role), (pid, 'player'))


class DeviceStoreAfterPowerLoss(unittest.TestCase):
    """The appliance loses power without warning. A device file cut short must not keep the
    party service from starting (it would crash-loop with nothing to show): phones are simply
    issued new identities, and the bad file is kept aside."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, 'devices.json')

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_truncated_or_garbled_file_does_not_stop_the_party(self):
        for bad in ('', '{"3f', 'not json', '[1, 2]', '{"x": "y"}'):
            with self.subTest(bad=bad):
                with open(self.path, 'w', encoding='utf-8') as f:
                    f.write(bad)
                with self.assertLogs('avrana.party.identity', level=logging.WARNING):
                    store = identity.DeviceStore(self.path)
                self.assertEqual(store.by_hash, {})
                token, device = store.issue()
                self.assertEqual(identity.DeviceStore(self.path).resolve(token), device)
                aside = [n for n in os.listdir(self.tmp.name) if n.startswith('devices.json.')]
                self.assertTrue(aside, 'the bad file was thrown away instead of kept')
                for n in aside:
                    os.unlink(os.path.join(self.tmp.name, n))

    def test_a_store_that_cannot_be_written_still_lets_a_phone_join(self):
        store = identity.DeviceStore(os.path.join(self.tmp.name, 'gone', 'devices.json'))
        with self.assertLogs('avrana.party.identity', level=logging.WARNING):
            token, device = store.issue()
        self.assertEqual(store.resolve(token), device)       # good for this run, not after a restart


class DeviceStoreDurability(unittest.TestCase):
    """The file is on disk before it takes the real name (a power cut leaves old or new, never empty)."""

    def test_fsync_of_the_temp_file_comes_before_the_replace_and_a_failing_dir_sync_is_harmless(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            store = identity.DeviceStore(os.path.join(tmp, 'devices.json'))
            events = []
            real_fsync, real_replace = os.fsync, os.replace

            def fsync(fd):
                events.append('fsync')
                real_fsync(fd)
                if events.count('fsync') > 1:
                    raise OSError('no directory sync here')

            def replace(a, b):
                events.append('replace')
                real_replace(a, b)

            with mock.patch.object(os, 'fsync', fsync), mock.patch.object(os, 'replace', replace):
                token, device = store.issue()
            self.assertEqual(events[:2], ['fsync', 'replace'])
            self.assertEqual(identity.DeviceStore(store.path).resolve(token), device)


class WallClockSteps(unittest.TestCase):
    """The appliance has no RTC: NTP can step the wall clock once the internet appears."""

    def test_party_timers_run_on_the_monotonic_clock(self):
        svc = service.PartyService(identity.DeviceStore(None), {'bluff': BLUFF})
        self.assertIs(svc.core.clock, time.monotonic)
        self.assertIs(identity.LimitedStore().clock, time.monotonic)

    def test_a_ticket_caught_by_a_backward_step_is_refused_as_clock_and_a_fresh_one_works(self):
        key, sid = protocol.new_key(), 'session-' + 'a' * 32
        pid, T = 'participant-' + 'c' * 32, 2_000_000_000
        side = protocol.GameSide(key, 'bluff')
        side.on_launch(protocol.launch_message(key, 'bluff', sid, [], now=T), now=T)
        old = protocol.mint_ticket(key, 'bluff', sid, pid, 'player', now=T)
        stepped_back = T - 3600
        with self.assertRaises(protocol.Invalid) as e:
            side.admit(old, now=stepped_back)
        self.assertEqual(str(e.exception), 'clock')
        fresh = protocol.mint_ticket(key, 'bluff', sid, pid, 'player', now=stepped_back)
        side.admit(fresh, now=stepped_back)
        with self.assertRaises(protocol.Invalid) as e:           # still single-use after the step
            side.admit(fresh, now=stepped_back + 1)
        self.assertEqual(str(e.exception), 'replay')

    def test_a_forward_step_expires_tickets_and_a_fresh_one_works(self):
        key, sid = protocol.new_key(), 'session-' + 'a' * 32
        pid, T = 'participant-' + 'c' * 32, 2_000_000_000
        side = protocol.GameSide(key, 'bluff')
        side.on_launch(protocol.launch_message(key, 'bluff', sid, [], now=T), now=T)
        old = protocol.mint_ticket(key, 'bluff', sid, pid, 'player', now=T)
        with self.assertRaises(protocol.Invalid) as e:
            side.admit(old, now=T + 86400)
        self.assertEqual(str(e.exception), 'expired')
        side.admit(protocol.mint_ticket(key, 'bluff', sid, pid, 'player', now=T + 86400), now=T + 86400)


class GameLostRules(unittest.TestCase):
    """Party Core, pure, injected clock: when an active session's game stops answering, and what it
    becomes. Only with the `close_lost_game` switch on."""

    def active(self, close=True):
        pc, clock = make(close)
        for i, name in enumerate(('Ana', 'Ben', 'Cat', 'Dan')):
            pc.join(f'device-{i}', name)
        s = pc.launch('device-0', 'bluff', pc.party.version)
        pc.launch_accepted(s.id)
        return pc, clock, s

    def test_three_misses_inside_the_window_close_the_session(self):
        pc, clock, s = self.active()
        self.assertFalse(pc.game_unreachable(s.id))
        clock.advance(4)
        self.assertFalse(pc.game_unreachable(s.id))
        clock.advance(5)
        self.assertTrue(pc.game_unreachable(s.id))                 # t = 0, 4, 9: all within 10 s
        self.assertEqual((s.state, s.outcome, s.reason, s.detail), ('ended', 'abandoned', 'game_lost', 'The game stopped.'))
        self.assertEqual(pc.location()['at'], 'home')
        self.assertEqual(pc.party.nav['to'], 'home')

    def test_misses_that_are_far_apart_expire_and_never_add_up(self):
        pc, clock, s = self.active()
        self.assertFalse(pc.game_unreachable(s.id))                # t = 0
        clock.advance(60)
        self.assertFalse(pc.game_unreachable(s.id))                # t = 60: the first has expired
        clock.advance(2)
        self.assertFalse(pc.game_unreachable(s.id))                # t = 62: two inside the window, not three
        self.assertEqual(s.state, 'active')
        clock.advance(2)
        self.assertTrue(pc.game_unreachable(s.id))                 # t = 64: 60, 62, 64

    def test_an_answer_clears_the_misses(self):
        pc, clock, s = self.active()
        pc.game_unreachable(s.id)
        clock.advance(2)
        pc.game_unreachable(s.id)
        pc.game_reachable(s.id)
        clock.advance(2)
        self.assertFalse(pc.game_unreachable(s.id))
        clock.advance(2)
        self.assertFalse(pc.game_unreachable(s.id))
        self.assertEqual(s.state, 'active')

    def test_only_the_active_session_can_be_lost(self):
        pc, clock, s = self.active()
        self.assertFalse(pc.game_lost('session-' + 'f' * 32))
        pc.game_reported_end(s.id, 'completed')               # results held: the game is not "lost"
        self.assertFalse(pc.game_lost(s.id))
        self.assertEqual((s.outcome, s.reason), ('completed', None))

    def test_the_reason_reaches_every_phone_and_nav_goes_home_for_all(self):
        pc, clock, s = self.active()
        pc.game_lost(s.id)
        for i in range(4):
            v = pc.view(f'device-{i}')
            self.assertEqual((v['state'], v['location']['at'], v['nav']['to'], v['session']['outcome'],
                              v['session']['reason']), ('lobby', 'home', 'home', 'abandoned', 'game_lost'))
            self.assertEqual(v['nav']['from'], 'bluff')
        pc.launch('device-0', 'bluff', pc.party.version)         # and the host can simply start again

    def test_checks_that_waited_out_a_slow_connect_are_stamped_at_their_start_and_fit_a_wider_window(self):
        pc, clock, s = self.active()
        base = clock()
        # three checks of 5 s each, back to back, start at 0, 5 and 10
        self.assertFalse(pc.game_unreachable(s.id, at=base, window=17.0))
        self.assertFalse(pc.game_unreachable(s.id, at=base + 5, window=17.0))
        self.assertTrue(pc.game_unreachable(s.id, at=base + 10, window=17.0))
        pc, clock, s = self.active()
        for t in (0, 5):
            pc.game_unreachable(s.id, at=base + t)
        self.assertFalse(pc.game_unreachable(s.id, at=base + 10),
                         'with the plain 10 s window such checks could never add up')

    def test_with_the_switch_off_nothing_is_counted_closed_or_shown(self):
        pc, clock, s = self.active(close=False)
        for _ in range(10):
            self.assertFalse(pc.game_unreachable(s.id))
            clock.advance(1)
        self.assertEqual((s.state, s.reason), ('active', None))
        self.assertNotIn('reason', pc.view('device-1')['session'])     # not a key of the public view at all
        pc2, _, s2 = self.active()
        self.assertIn('reason', pc2.view('device-1')['session'])
        self.assertIsNone(pc2.view('device-1')['session']['reason'])


class SessionRecordFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, 'active-session.json')
        self.rec = record.SessionRecord(self.path)
        self.a, self.b = 'session-' + 'a' * 32, 'session-' + 'b' * 32

    def tearDown(self):
        self.tmp.cleanup()

    def test_what_was_written_is_read_back_and_clear_removes_it(self):
        self.assertEqual(self.rec.read(), [])
        self.rec.write(self.a, 'bluff')
        self.assertEqual(self.rec.read(), [(self.a, 'bluff')])
        self.assertEqual(os.listdir(self.tmp.name), ['active-session.json'])    # no temporary file left
        self.rec.clear(self.a)
        self.assertEqual(self.rec.read(), [])
        self.assertEqual(os.listdir(self.tmp.name), [])
        self.rec.clear(self.a)                                                   # and clearing twice is fine

    def test_a_new_session_never_replaces_an_entry_that_has_not_been_processed(self):
        self.rec.write(self.a, 'bluff')
        self.rec.write(self.b, 'checkers')
        self.assertEqual(self.rec.read(), [(self.a, 'bluff'), (self.b, 'checkers')])
        self.rec.clear(self.a)                                  # a late confirmation of the older one
        self.assertEqual(self.rec.read(), [(self.b, 'checkers')])
        self.rec.clear(self.b)
        self.assertEqual(self.rec.read(), [])

    def test_only_the_newest_few_are_kept(self):
        for i in range(record.MAX_KEPT + 3):
            self.rec.write('session-' + str(i) * 32, 'bluff')
        self.assertEqual(len(self.rec.read()), record.MAX_KEPT)
        self.assertEqual(self.rec.read()[-1][0], 'session-' + str(record.MAX_KEPT + 2) * 32)

    def test_a_write_and_a_clear_racing_each_other_never_lose_an_entry(self):
        """clear(a) has read [a] and is about to save [] when write(b) comes in. Without one lock
        around the read-modify-write, write(b) saves [a, b] and clear then saves [] over it."""
        self.rec.write(self.a, 'bluff')
        in_save, release, calls = threading.Event(), threading.Event(), []
        real = self.rec._save

        def save(entries):
            calls.append(entries)
            if len(calls) == 1:                    # the clear: hold it between its read and its save
                in_save.set()
                release.wait(5)
            real(entries)
        self.rec._save = save
        clearing = threading.Thread(target=self.rec.clear, args=(self.a,))
        writing = threading.Thread(target=self.rec.write, args=(self.b, 'bluff'))
        clearing.start()
        self.assertTrue(in_save.wait(5))
        writing.start()
        writing.join(0.3)                          # with the lock it waits here; without, it finishes
        release.set()
        clearing.join(5)
        writing.join(5)
        self.assertEqual(self.rec.read(), [(self.b, 'bluff')])

    def test_a_file_that_is_not_ours_is_set_aside_and_the_record_starts_empty(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write('{"sess')
        with self.assertLogs('avrana.party.record', level=logging.WARNING):
            self.assertEqual(self.rec.read(), [])
        names = os.listdir(self.tmp.name)
        self.assertEqual([n for n in names if '.bad-' in n], [n for n in names])
        self.assertEqual(len(names), 1)
        self.rec.write(self.a, 'bluff')                   # and the next write is a clean file
        self.assertEqual(self.rec.read(), [(self.a, 'bluff')])

    def test_a_cut_short_or_foreign_file_is_ignored_not_fatal(self):
        for bad in ('', '{"sess', 'not json', '[1]', '{"schema": "x"}',
                    '{"schema": "%s", "sessions": [{"session": 1, "game": "g"}]}' % record.SCHEMA,
                    '{"schema": "%s", "sessions": "x"}' % record.SCHEMA, '[' * 100000):
            with self.subTest(bad=bad[:20]):
                with open(self.path, 'w', encoding='utf-8') as f:
                    f.write(bad)
                with self.assertLogs('avrana.party.record', level=logging.WARNING):
                    self.assertEqual(self.rec.read(), [])

    def test_a_record_that_cannot_be_written_is_not_fatal(self):
        gone = record.SessionRecord(os.path.join(self.tmp.name, 'missing', 'active-session.json'))
        with self.assertLogs('avrana.party.record', level=logging.WARNING):
            gone.write(self.a, 'bluff')
        self.assertEqual(gone.read(), [])

    def test_the_file_is_owner_only_and_on_disk_before_it_takes_its_name(self):
        from unittest import mock
        events = []
        real_fsync, real_replace = os.fsync, os.replace
        with mock.patch.object(os, 'fsync', lambda fd: (events.append('fsync'), real_fsync(fd))[1]), \
                mock.patch.object(os, 'replace', lambda a, b: (events.append('replace'), real_replace(a, b))[1]):
            self.rec.write(self.a, 'bluff')
        self.assertEqual(events[:2], ['fsync', 'replace'])
        if os.name == 'posix':
            self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    def test_the_path_comes_from_the_config_or_sits_beside_the_device_file_or_is_switched_off(self):
        self.assertEqual(service.session_record_path({'session_record': '/x/a.json', 'devices': '/d/devices.json'}),
                         '/x/a.json')
        self.assertEqual(service.session_record_path({'devices': os.path.join('d', 'devices.json')}),
                         os.path.join('d', 'active-session.json'))
        self.assertIsNone(service.session_record_path({}))
        for off in ('', False, None):                     # named but empty: no record, no fallback
            self.assertIsNone(service.session_record_path({'session_record': off, 'devices': '/d/devices.json'}))


class SlowAccept(unittest.TestCase):
    """A game whose accept queue is full: each check waits out the whole connect timeout and misses.
    Injected clock, no sleeping."""

    def test_three_slow_misses_still_close_the_session(self):
        clock = Clock()

        class Link:
            timeout = 5.0
            endpoints = {}

            def reachable(self, session):
                clock.advance(5.0)                  # the connect timed out
                return False

            def launch(self, session, roster):
                return True, None

            def end(self, session):
                return True
        svc = service.PartyService(identity.DeviceStore(None), {'bluff': BLUFF}, Link(), clock=clock,
                                   close_lost_game=True)
        svc.core.join('device-a', 'Ana')
        s = svc.core.launch('device-a', 'bluff', svc.core.party.version)
        svc.core.launch_accepted(s.id)
        self.assertTrue(svc.game_up(s))              # started at 0, stamped 0
        self.assertTrue(svc.game_up(s))              # started at 5
        self.assertFalse(svc.game_up(s))             # started at 10: three inside 3 x 5 s + slack
        self.assertEqual((s.state, s.reason), ('ended', 'game_lost'))
        for thread in threading.enumerate():
            if thread.name == service.RELEASE_THREAD:
                thread.join(5)


class RecoveryConfig(unittest.TestCase):
    def test_defaults_change_nothing_but_the_not_held_reading(self):
        self.assertEqual(service.recovery_config({}), {'end_orphan_on_start': False, 'close_lost_game': False,
                                                       'end_not_held_is_ended': True})
        self.assertEqual(service.recovery_config({'session_recovery': {'close_lost_game': True}})['close_lost_game'], True)

    def test_a_typo_or_a_non_boolean_is_refused_at_startup(self):
        for bad in ({'close_lost': True}, {'close_lost_game': 'yes'}, {'end_orphan_on_start': 1}, [], 'on'):
            with self.subTest(bad=bad):
                with self.assertRaises(SystemExit):
                    service.recovery_config({'session_recovery': bad})

    def test_the_example_config_spells_every_switch_out_with_its_default(self):
        import json as _json
        example = _json.load(open(os.path.join(os.path.dirname(__file__), '..', '..', 'deploy', 'party-core',
                                               'party-core.example.json'), encoding='utf-8'))
        self.assertEqual(example['session_recovery'], service.RECOVERY_DEFAULTS)
        self.assertEqual(service.recovery_config(example), service.RECOVERY_DEFAULTS)


class ScriptedLink:
    """A link that answers `end` from a script, and says what it was asked."""

    def __init__(self, *outcomes):
        self.outcomes, self.asked = list(outcomes), []

    def end_outcome(self, session):
        self.asked.append((session.game_id, session.id))
        return self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]

    def end(self, session):
        return self.end_outcome(session) in ('ended', 'not_held')

    def launch(self, session, roster):
        return True, None


class RecoverOrphan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rec = record.SessionRecord(os.path.join(self.tmp.name, 'active-session.json'))
        self.rec.write('session-' + 'a' * 32, 'bluff')

    def tearDown(self):
        self.tmp.cleanup()

    def svc(self, link, on=True):
        return service.PartyService(identity.DeviceStore(None), {'bluff': BLUFF}, link, record=self.rec,
                                    end_orphan_on_start=on)

    def test_a_restarted_party_ends_the_session_it_forgot_and_drops_the_record(self):
        link = ScriptedLink('ended')
        self.assertEqual(self.svc(link).recover_orphan(sleep=lambda s: None), ['ended'])
        self.assertEqual(link.asked, [('bluff', 'session-' + 'a' * 32)])
        self.assertEqual(self.rec.read(), [])

    def test_a_game_that_holds_nothing_or_refuses_is_done_with_too(self):
        for outcome in ('not_held', 'refused'):
            with self.subTest(outcome=outcome):
                self.rec.write('session-' + 'a' * 32, 'bluff')
                self.assertEqual(self.svc(ScriptedLink(outcome)).recover_orphan(sleep=lambda s: None), [outcome])
                self.assertEqual(self.rec.read(), [])

    def test_a_game_that_is_not_up_yet_is_tried_again_then_given_up_on(self):
        link, waited = ScriptedLink('unreachable', 'unreachable', 'ended'), []
        self.assertEqual(self.svc(link).recover_orphan(attempts=5, delay=2.0, sleep=waited.append), ['ended'])
        self.assertEqual((len(link.asked), waited), (3, [2.0, 2.0]))
        self.rec.write('session-' + 'a' * 32, 'bluff')
        link, waited = ScriptedLink('unreachable'), []
        self.assertEqual(self.svc(link).recover_orphan(attempts=4, delay=1.0, sleep=waited.append), ['unreachable'])
        self.assertEqual((len(link.asked), len(waited)), (4, 3))
        self.assertEqual(self.rec.read(), [])                       # it does not retry for ever, run after run

    def test_nothing_happens_without_a_record(self):
        self.rec.clear('session-' + 'a' * 32)
        link = ScriptedLink('ended')
        self.assertIsNone(self.svc(link).recover_orphan())
        self.assertIsNone(service.PartyService(identity.DeviceStore(None), {'bluff': BLUFF}, link).recover_orphan())
        self.assertEqual(link.asked, [])

    def test_a_session_this_run_started_is_never_ended_as_an_orphan(self):
        link = ScriptedLink('ended')
        svc = self.svc(link)
        svc.core.join('device-a', 'Ana')
        s = svc.core.launch('device-a', 'bluff', svc.core.party.version)
        self.rec.write(s.id, 'bluff')
        self.rec.clear('session-' + 'a' * 32)
        self.assertIsNone(svc.recover_orphan())
        self.assertEqual(link.asked, [])

    def test_with_the_switch_off_nothing_is_recorded_and_nothing_is_ended(self):
        link = ScriptedLink('ended')
        svc = self.svc(link, on=False)
        self.assertIsNone(svc.record)
        self.assertIsNone(svc.recover_orphan())
        self.assertEqual(link.asked, [])
        self.assertEqual(self.rec.read(), [('session-' + 'a' * 32, 'bluff')])   # and the file is untouched

    def test_a_launch_racing_the_recovery_does_not_hide_the_orphan(self):
        link = ScriptedLink('ended')
        svc = self.svc(link)
        svc.core.join('device-a', 'Ana')
        s = svc.core.launch('device-a', 'bluff', svc.core.party.version)
        svc._remember(s)                                         # the new launch writes its own entry
        self.assertEqual([e[0] for e in self.rec.read()], ['session-' + 'a' * 32, s.id])
        self.assertEqual(svc.recover_orphan(sleep=lambda x: None), ['ended'])
        self.assertEqual(link.asked, [('bluff', 'session-' + 'a' * 32)])    # the orphan was ended, not the new one
        self.assertEqual(self.rec.read(), [(s.id, 'bluff')])               # and the new session's entry stays


# ---- the five scenarios, end to end (AVR-33) ------------------------------------------------------
KEY = protocol.new_key()


class RestartableGame:
    """A game server on a real loopback socket, with the reference GameSide behind it (the shape
    every Games server and the stand-in have), that can crash and come back with or without the
    session it held. `shape` is how it words a refusal: 'reason' ({"reason": "session"}, GameSide
    games and the managed runtime) or 'error' ({"error": "bad_message:session"}, the Games server)."""

    def __init__(self, shape='reason'):
        self.side = protocol.GameSide(KEY, 'bluff')
        self.shape = shape
        self.port, self.server = None, None
        self.start()

    def start(self):
        game = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                try:
                    if self.path == sessions.LAUNCH_PATH:
                        game.side.on_launch(body['message'])
                    elif self.path == sessions.END_PATH:
                        game.side.on_end(body['message'])
                    else:
                        raise Invalid('route')
                    out, status = {'ok': True}, 200
                except Invalid as e:
                    out = ({'ok': False, 'error': f'bad_message:{e}'} if game.shape == 'error'
                           else {'ok': False, 'message': f'Refused: {e}'} if game.shape == 'prose'
                           else {'ok': False, 'message': 'Refused.', 'reason': str(e)})
                    status = 403
                data = json.dumps(out).encode()
                self.send_response(status)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', self.port or 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, args=(0.02,), daemon=True).start()   # quick to stop

    @property
    def url(self):
        return f'http://127.0.0.1:{self.port}'

    def stop(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None

    def restart(self, keep_session=False):
        """The process dies and a new one answers on the same address (a crash and systemd's
        Restart=, or socket activation). A new process holds no session."""
        self.stop()
        if not keep_session:
            self.side = protocol.GameSide(KEY, 'bluff')
        self.start()

    def hello(self, ticket):
        return self.side.admit(ticket)


class ScenarioRig(ServiceCase):
    """T2: real HTTP between phones, Party Core and a game server, all on loopback in one process
    (the game is a thread, so a crash is a stopped listener). Unix-socket variants of the link run on
    the Linux runner (test_game_link_bounds). Four phones: Ana (host), Ben, Cat, Dan."""
    game_shape = 'reason'
    recovery = {'end_orphan_on_start': True, 'close_lost_game': True}     # the switches under test

    def setUp(self):
        super().setUp()
        self.game = RestartableGame(self.game_shape)
        self.addCleanup(self.game.stop)
        self.endpoints = {'bluff': sessions.GameEndpoint('bluff', self.game.url, KEY)}
        self.svc.link = sessions.HttpGameLink(self.endpoints, timeout=3)
        self.clock = Clock()
        self.clock.t = time.monotonic()
        self.svc.core.clock = self.clock
        self.svc.core.close_lost_game = self.recovery['close_lost_game']
        self.record_path = os.path.join(self.tmp.name, 'active-session.json')
        self.svc.record = record.SessionRecord(self.record_path) if self.recovery['end_orphan_on_start'] else None
        extra, internal = sessions.routes(self.svc, self.endpoints)       # the protocol routes, on the server
        handler = self.server.RequestHandlerClass                          # ServiceCase already runs
        handler.extra_routes.update(extra)
        handler.internal_routes.update(internal)
        self.phones = {name: self.phone() for name in ('Ana', 'Ben', 'Cat', 'Dan')}
        for name, phone in self.phones.items():
            phone.post('join', {'name': name})

    def tearDown(self):
        for t in threading.enumerate():                  # the best-effort `end` after a lost game
            if t.name == service.RELEASE_THREAD:
                t.join(timeout=10)
        super().tearDown()

    # ---- what a phone sees -------------------------------------------------------------------------
    def seen(self, name):
        """(party state, location, nav, session state, outcome, reason) as /party/api/state says."""
        status, v, _ = self.phones[name].state()
        self.assertEqual(status, 200)
        s = v['session'] or {}
        return (v['state'], v['location']['at'], v['nav']['to'], s.get('state'), s.get('outcome'), s.get('reason'))

    def everyone_sees(self, expected):
        for name in self.phones:
            self.assertEqual(self.seen(name), expected, name)

    def launch(self):
        _, v, _ = self.phones['Ana'].state()
        status, v, _ = self.phones['Ana'].post('session/launch', {'game': 'bluff', 'if_version': v['version']})
        self.assertEqual((status, v['state']), (200, 'active'), v)
        return v['session']['id']

    def ticket(self, name):
        return self.phones[name].post('session/ticket', {'game': 'bluff'})

    def host_ends(self):
        _, v, _ = self.phones['Ana'].state()
        return self.phones['Ana'].post('session/end', {'if_version': v['version']})

    def nothing_is_held(self):
        """No request thread is parked on a game and the service lock is free."""
        self.assertTrue(self.svc.lock.acquire(timeout=1.0), 'the service lock is held')
        self.svc.lock.release()
        self.assertEqual(self.svc.waiters, 0)

    def restart_party(self):
        """Party Core restarts: devices persist (cookies), the party and its session do not."""
        self.svc.core = core.PartyCore(self.clock, self.svc.core.games, close_lost_game=self.recovery['close_lost_game'])
        self.svc._probed = None

    ACTIVE = ('active', 'game', 'game', 'active', None, None)
    HOME = ('lobby', 'home', 'home')


class Scenarios(ScenarioRig):

    # ---- 1. Games (or a native game process) restarts while the session is ACTIVE ---------------------
    def test_1_a_restarted_game_leaves_a_party_that_still_says_active_until_the_host_ends_it(self):
        """TODAY and after this change: Party Core cannot tell (the v0 contract has no way to ask a
        game what it holds). Every phone is still sent to the game and the game refuses it. The
        host's End recovers it, and now confirms instead of timing out."""
        sid = self.launch()
        self.game.restart()                                   # lost current_sid
        self.everyone_sees(self.ACTIVE)
        for name in ('Ben', 'Cat', 'Dan'):
            status, body, _ = self.ticket(name)
            self.assertEqual(status, 200, 'Party Core still issues the ticket')
            with self.assertRaises(Invalid) as refused:
                self.game.hello(body['ticket'])
            self.assertEqual(str(refused.exception), 'session', 'and the game refuses it: the bounce')
        # the reachability check sees a game that answers, so it does not close the session
        for _ in range(4):
            self.clock.advance(5)
            self.ticket('Ben')
        self.assertEqual(self.seen('Ben'), self.ACTIVE)
        status, v, _ = self.host_ends()
        self.assertEqual(status, 200)
        self.everyone_sees(self.HOME + ('ended', 'ended_by_host', None))
        self.assertIs(self.svc.core.party.session.game_confirmed_end, True,
                      'a game that says it holds no such session has nothing left to stop')
        self.assertEqual(record.SessionRecord(self.record_path).read(), [])
        self.assertEqual(self.ticket('Ben')[0], 409)
        self.nothing_is_held()
        self.assertNotEqual(sid, None)

    def test_1_after_a_games_restart_the_host_can_still_switch_games(self):
        """Regression: End and a switch both ask the game to end the old session. A restarted game
        answers "no such session"; that used to read as "did not stop", and a switch then refused
        to start anything."""
        for shape in ('reason', 'error'):                    # both refusal wordings in use today
            with self.subTest(shape=shape):
                self.game.shape = shape
                old = self.launch()
                self.game.restart()
                _, v, _ = self.phones['Ana'].state()
                status, v, _ = self.phones['Ana'].post('session/switch', {'game': 'bluff', 'if_version': v['version']})
                self.assertEqual((status, v['state']), (200, 'active'), v)
                new = v['session']['id']
                self.assertNotEqual(new, old)
                self.assertEqual(self.game.side.sid, new)
                self.assertTrue(self.svc.core.party.session.state == 'active')
                self.host_ends()

    # ---- 2. Party Core restarts while the game is still running ---------------------------------------
    def test_2_a_restarted_party_ends_the_session_it_forgot_and_phones_rejoin_a_clean_party(self):
        """TODAY: the game keeps the old session until some host launches again. AFTER: the durable
        record lets the restarted Party Core send that game the signed `end`; the game (and for the
        arcade/PS1 their runtime) stops. In-memory party state is still lost: members, host and
        roster are not restored; phones rejoin with their device cookie, and the first to rejoin is
        the host."""
        old = self.launch()
        self.assertEqual(record.SessionRecord(self.record_path).read(), [(old, 'bluff')])
        _, held, _ = self.ticket('Ben')
        self.restart_party()
        self.assertEqual(self.game.side.sid, old, 'the game still holds it, nobody manages it')
        started = time.monotonic()
        self.assertEqual(self.svc.recover_orphan(sleep=lambda s: None), ['ended'])
        self.assertLess(time.monotonic() - started, 3)
        self.assertIsNone(self.game.side.sid, 'the game is clean')
        with self.assertRaises(Invalid):
            self.game.hello(held['ticket'])                   # an old ticket is dead
        self.assertEqual(record.SessionRecord(self.record_path).read(), [])
        # what a phone sees: not a member any more (the party is new), nothing running
        for name in self.phones:
            _, v, _ = self.phones[name].state()
            self.assertEqual((v['me'], v['state'], v['location']['at'], v['session']), (None, 'lobby', 'home', None))
        status, body, _ = self.ticket('Ben')
        self.assertEqual((status, body['error']), (403, 'not_member'))
        for name in ('Cat', 'Dan', 'Ben', 'Ana'):             # Cat is first: the old host is not restored
            self.phones[name].post('join', {'name': name})
        _, v, _ = self.phones['Ana'].state()
        self.assertEqual((v['me']['host'], [m['name'] for m in v['members'] if m['host']]), (False, ['Cat']))
        self.assertEqual(self.phones['Ana'].post('session/end', {'if_version': v['version']})[0], 403)
        self.everyone_sees(self.HOME + (None, None, None))
        self.assertEqual(self.ticket('Ben')[0], 409)          # no game on
        self.nothing_is_held()

    def test_2_a_recovery_end_never_stops_a_newer_session(self):
        old = self.launch()
        self.restart_party()
        for name in self.phones:
            self.phones[name].post('join', {'name': name})
        new = self.launch()                                   # the launch replaces the old session
        self.assertEqual(self.game.side.sid, new)
        record.SessionRecord(self.record_path).write(old, 'bluff')    # a stale entry, as a race leaves it
        self.assertEqual(self.svc.recover_orphan(sleep=lambda s: None), ['not_held'])
        self.assertEqual(self.game.side.sid, new, 'the game still holds the newer session')
        self.assertEqual(self.seen('Dan'), self.ACTIVE)

    def test_2_with_the_game_down_at_restart_the_party_gives_up_after_its_tries(self):
        self.launch()
        self.restart_party()
        self.game.stop()
        waited = []
        self.assertEqual(self.svc.recover_orphan(attempts=3, delay=1.0, sleep=waited.append), ['unreachable'])
        self.assertEqual(waited, [1.0, 1.0])
        self.assertEqual(record.SessionRecord(self.record_path).read(), [])
        self.game.start()                                     # whatever it holds, the next launch replaces

    # ---- 3. A native game process crashes mid-session ------------------------------------------------
    def test_3_a_game_that_stays_down_closes_the_session_for_everyone_after_a_few_misses(self):
        """AUTOMATIC: a ticket request is the trigger; three misses inside ten seconds close it as
        `abandoned` / `game_lost` and send every phone home."""
        self.launch()
        self.game.stop()
        self.assertEqual(self.ticket('Ben')[0], 200)          # miss 1: nothing yet (a restart takes a moment)
        self.clock.advance(4)
        self.assertEqual(self.ticket('Cat')[0], 200)          # miss 2
        self.everyone_sees(self.ACTIVE)
        self.clock.advance(4)
        started = time.monotonic()
        status, body, _ = self.ticket('Dan')                  # miss 3, eight seconds after the first: inside the window
        self.assertEqual((status, body['error'], body['message']), (409, 'no_game', 'The game stopped.'))
        self.assertLess(time.monotonic() - started, 3, 'the request was not held on the dead game')
        self.everyone_sees(self.HOME + ('ended', 'abandoned', 'game_lost'))
        _, v, _ = self.phones['Cat'].state()
        self.assertEqual((v['session']['detail'], v['nav']['from']), ('The game stopped.', 'bluff'))
        self.assertEqual(self.ticket('Ben')[0], 409)
        self.assertEqual(self.host_ends()[0], 409)            # nothing left to end
        self.nothing_is_held()
        self.game.start()                                     # the host starts again, no restart needed
        self.assertEqual(self.launch(), self.svc.core.party.session.id)

    def test_3_a_game_that_blinks_does_not_lose_a_healthy_session(self):
        self.launch()
        for _ in range(3):                                    # down for two checks, up for the next, again
            self.game.stop()
            self.ticket('Ben')
            self.clock.advance(5)
            self.ticket('Cat')
            self.clock.advance(6)
            self.game.start()
            self.assertEqual(self.ticket('Dan')[0], 200)
            self.clock.advance(5)
        self.assertEqual(self.seen('Ben'), self.ACTIVE)

    def test_3_a_crowd_of_phones_costs_one_check_not_one_each(self):
        self.launch()
        checks = []
        real = self.svc.link.reachable
        self.svc.link.reachable = lambda s, *a: (checks.append(1), real(s, *a))[1]
        for name in ('Ben', 'Cat', 'Dan', 'Ben', 'Cat', 'Dan'):
            self.assertEqual(self.ticket(name)[0], 200)
        self.assertEqual(len(checks), 1)
        self.clock.advance(sessions_probe_every())
        self.ticket('Ben')
        self.assertEqual(len(checks), 2)

    def test_3_a_game_that_systemd_starts_again_is_scenario_1(self):
        """Socket activation (deploy/games/avrana-game@.socket) accepts the connection while the
        process is down and starts it with no session: reachable, so Party cannot tell."""
        self.launch()
        self.game.restart()
        for _ in range(6):
            self.clock.advance(5)
            self.assertEqual(self.ticket('Ben')[0], 200)
        self.assertEqual(self.seen('Ben'), self.ACTIVE)

    # ---- 4. The host reconnects after a service interruption ----------------------------------------
    def test_4_the_host_returns_after_the_games_service_blinked_and_nothing_is_lost(self):
        self.launch()
        self.game.stop()
        self.ticket('Ben')                                    # a follower's request finds it down
        self.clock.advance(5)
        self.game.start()                                     # the same process answering again (a network blip)
        status, body, _ = self.ticket('Ana')
        self.assertEqual(status, 200)
        self.game.hello(body['ticket'])                       # the host is admitted
        self.assertEqual(self.seen('Ana'), self.ACTIVE)
        self.assertTrue(self.phones['Ana'].state()[1]['me']['host'])

    def test_4_the_host_returns_after_party_core_restarted_and_is_a_member_not_the_host(self):
        self.launch()
        self.restart_party()
        self.svc.recover_orphan(sleep=lambda s: None)
        status, v, _ = self.phones['Ana'].state()
        self.assertEqual((status, v['me'], v['host']), (200, None, None))    # no member, and nobody is host
        self.phones['Ana'].post('join', {'name': 'Ana'})      # a phone with a profile does this on its own
        _, v, _ = self.phones['Ana'].state()
        self.assertTrue(v['me']['host'], 'rejoining first, Ana is host again')
        self.phones['Ben'].post('join', {'name': 'Ben'})
        self.assertFalse(self.phones['Ben'].state()[1]['me']['host'])
        self.assertEqual(self.seen('Ana'), self.HOME + (None, None, None))

    # ---- 5. Followers try to reconnect to a session that is dead --------------------------------------
    def test_5_followers_of_a_session_the_host_ended_get_no_ticket_and_see_home(self):
        self.launch()
        self.host_ends()
        for name in ('Ben', 'Cat', 'Dan'):
            status, body, _ = self.ticket(name)
            self.assertEqual((status, body['error']), (409, 'no_game'), name)
        self.everyone_sees(self.HOME + ('ended', 'ended_by_host', None))

    def test_5_followers_of_a_session_whose_game_is_gone_are_sent_home_not_back_and_forth(self):
        self.launch()
        self.game.stop()
        for name in ('Ben', 'Cat', 'Dan', 'Ben', 'Cat'):      # their pages keep reconnecting
            self.ticket(name)
            self.clock.advance(4)
        self.everyone_sees(self.HOME + ('ended', 'abandoned', 'game_lost'))
        for name in ('Ben', 'Cat', 'Dan'):
            status, body, _ = self.ticket(name)
            self.assertEqual((status, body['error']), (409, 'no_game'), name)
        self.nothing_is_held()

    def test_5_followers_of_a_session_a_restarted_party_forgot_are_not_members_until_they_rejoin(self):
        self.launch()
        self.restart_party()
        self.svc.recover_orphan(sleep=lambda s: None)
        for name in ('Ben', 'Cat', 'Dan'):
            status, body, _ = self.ticket(name)
            self.assertEqual((status, body['error']), (403, 'not_member'), name)
            self.phones[name].post('join', {'name': name})
            status, body, _ = self.ticket(name)
            self.assertEqual((status, body['error']), (409, 'no_game'), name)


def sessions_probe_every():
    return service.PROBE_EVERY + 0.5


class RefusalWording(ScenarioRig):
    """A restarted Games server (BLUFF, EXPO) words its refusal differently from a GameSide game; the
    host's End is confirmed by either, and by neither when the not-held reading is switched off."""

    def end_after_restart(self):
        self.launch()
        self.game.restart()
        self.host_ends()
        return self.svc.core.party.session.game_confirmed_end

    def test_both_wordings_confirm_the_hosts_end(self):
        for shape in ('reason', 'error'):
            with self.subTest(shape=shape):
                self.game.shape = shape
                self.assertIs(self.end_after_restart(), True)

    def test_a_different_wording_is_not_read_as_not_held(self):
        self.game.shape = 'prose'
        self.assertIs(self.end_after_restart(), False)

    def test_with_end_not_held_is_ended_off_the_old_behaviour_returns(self):
        self.svc.link.end_not_held_is_ended = False
        self.assertIs(self.end_after_restart(), False)


class SwitchesOff(ScenarioRig):
    """Both recovery switches at their defaults: the paths they guard behave as without them."""
    recovery = {'end_orphan_on_start': False, 'close_lost_game': False}

    def test_no_record_is_written_and_a_restarted_party_ends_nothing(self):
        old = self.launch()
        self.assertFalse(os.path.exists(self.record_path))
        self.restart_party()
        self.assertIsNone(self.svc.recover_orphan(sleep=lambda s: None))
        self.assertEqual(self.game.side.sid, old)                    # the game keeps it, as before

    def test_a_game_that_stays_down_never_closes_the_session_and_is_never_probed(self):
        self.launch()
        self.game.stop()
        probes = []
        self.svc.link.reachable = lambda *a: probes.append(a)
        for _ in range(8):
            self.assertEqual(self.ticket('Ben')[0], 200)             # a ticket is issued, as before
            self.clock.advance(5)
        self.assertEqual(probes, [])
        self.assertEqual(self.seen('Ben'), self.ACTIVE)
        self.assertNotIn('reason', self.phones['Ben'].state()[1]['session'])
        self.assertNotIn('reason', self.phones['Ben'].state()[1]['session'])


class ProbeTimeout(unittest.TestCase):
    """The connection check waits as long as a launch would, so a loaded Pi's slow accept is not a miss."""

    def link(self, **kw):
        ep = sessions.GameEndpoint('bluff', 'http://127.0.0.1:9', KEY, **kw)
        return sessions.HttpGameLink({'bluff': ep}, timeout=5.0)

    def test_it_waits_the_launch_timeout_not_one_second(self):
        from unittest import mock
        seen = []

        class Sock:
            def close(self):
                seen.append('closed')

        def connect(addr, timeout=None):
            seen.append(timeout)
            return Sock()
        s = type('S', (), {'game_id': 'bluff'})()
        with mock.patch.object(sessions.socket, 'create_connection', connect):
            self.assertTrue(self.link().reachable(s))
            self.assertTrue(self.link(timeout=25).reachable(s))
        self.assertEqual(seen, [5.0, 'closed', 25, 'closed'])        # the link's, then the grant's own

    def test_a_refused_or_timed_out_connection_is_a_miss_and_leaves_no_socket_open(self):
        from unittest import mock
        s = type('S', (), {'game_id': 'bluff'})()
        for exc in (ConnectionRefusedError(), TimeoutError()):
            with mock.patch.object(sessions.socket, 'create_connection', side_effect=exc):
                self.assertFalse(self.link().reachable(s))

    @unittest.skipUnless(hasattr(socket, 'AF_UNIX'), 'Unix sockets only (the Linux runner)')
    def test_the_unix_failed_connect_closes_its_socket(self):
        from unittest import mock
        made = []
        real = socket.socket

        def tracking(*a, **k):
            sock = real(*a, **k)
            made.append(sock)
            return sock
        s = type('S', (), {'game_id': 'bluff'})()
        link = sessions.HttpGameLink({'bluff': sessions.GameEndpoint(
            'bluff', 'http://localhost/games/bluff', KEY, socket_path='/nonexistent/g.sock')})
        with mock.patch.object(sessions.socket, 'socket', tracking):
            self.assertFalse(link.reachable(s))
        self.assertTrue(made and all(m.fileno() == -1 for m in made))


if __name__ == '__main__':
    unittest.main()
