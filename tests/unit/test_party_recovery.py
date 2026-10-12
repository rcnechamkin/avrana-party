"""Party recovery and robustness (AVR-33): host actions as presence, a switch whose next game
fails, a host who disappears mid-switch, the device store after a bad power cut, and the clock.
T1: Party Core with an injected clock, PartyService with a scripted link, no sockets."""
import logging
import os
import tempfile
import time
import unittest

from avrana.party import core, identity, protocol, service

BLUFF = {'id': 'bluff', 'max_players': 3, 'late_join': 'spectator_only'}
BOMBER = {'id': 'bomber', 'max_players': 4, 'late_join': 'spectator_only'}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


def make():
    clock = Clock()
    return core.PartyCore(clock, {g['id']: g for g in (BLUFF, BOMBER)}), clock


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


if __name__ == '__main__':
    unittest.main()
