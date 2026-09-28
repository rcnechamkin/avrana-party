"""Party Core v0 rules (avrana.party.core) with an injected clock. No network, no threads."""
import random
import unittest

from avrana.party import core
from avrana.party.core import Refused

BLUFF = {'id': 'bluff', 'max_players': 3, 'late_join': 'spectator_only'}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


def make(games=None):
    clock = Clock()
    return core.PartyCore(clock, {g['id']: g for g in (games or [BLUFF])}), clock


class Membership(unittest.TestCase):
    def test_looking_never_joins(self):
        pc, _ = make()
        view = pc.view('device-a')
        self.assertIsNone(view['me'])
        self.assertIsNone(pc.touch('device-a'))
        self.assertEqual(pc.party.members, {})

    def test_explicit_join_first_member_is_host(self):
        pc, _ = make()
        a = pc.join('device-a', 'Ana')
        b = pc.join('device-b', 'Ben')
        self.assertEqual(pc.party.host_id, a.id)
        self.assertEqual([m['name'] for m in pc.view('device-b')['members']], ['Ana', 'Ben'])
        self.assertFalse(pc.view('device-b')['me']['host'])
        self.assertNotEqual(a.id, b.id)

    def test_join_is_idempotent_per_device(self):
        pc, _ = make()
        a1 = pc.join('device-a', 'Ana')
        a2 = pc.join('device-a', 'Ana')
        self.assertIs(a1, a2)
        self.assertEqual(len(pc.party.members), 1)

    def test_leave_then_rejoin_is_the_same_member(self):
        pc, _ = make()
        a = pc.join('device-a', 'Ana')
        pc.leave('device-a')
        self.assertEqual(pc.view('device-a')['members'], [])
        self.assertIs(pc.join('device-a', 'Ana'), a)

    def test_duplicate_names_are_numbered_and_names_never_authorize(self):
        pc, _ = make()
        pc.join('device-a', 'Ana')
        b = pc.join('device-b', 'Ana')
        self.assertEqual(b.name, 'Ana 2')
        with self.assertRaises(Refused):
            pc.launch('device-b', 'bluff', pc.party.version)     # same name, not the host

    def test_bad_names_refused(self):
        pc, _ = make()
        for bad in ('', ' ', 'x' * 17, 'Admin', 'Hostess', 'Sуstem', None, 7, '‮​'):
            with self.subTest(bad=bad):
                with self.assertRaises(Refused):
                    pc.join('device-z', bad)
        self.assertEqual(pc.party.members, {})

    def test_view_hides_device_ids(self):
        pc, _ = make()
        pc.join('device-a', 'Ana')
        self.assertNotIn('device-a', repr(pc.view('device-a')))
        self.assertNotIn('device-a', repr(pc.view(None)))


class Presence(unittest.TestCase):
    def test_here_then_away_on_silence_but_still_a_member(self):
        pc, clock = make()
        a = pc.join('device-a', 'Ana')
        self.assertEqual(pc.presence(a), 'here')
        clock.advance(core.LIVE_WINDOW + 1)
        self.assertEqual(pc.presence(a), 'away')
        self.assertIn(a.id, pc.party.members)
        pc.touch('device-a')
        self.assertEqual(pc.presence(a), 'here')

    def test_time_alone_changing_presence_moves_the_version(self):
        pc, clock = make()
        pc.join('device-a', 'Ana')
        v = pc.party.version
        clock.advance(core.LIVE_WINDOW + 1)
        self.assertTrue(pc.tick())
        self.assertGreater(pc.party.version, v)
        self.assertFalse(pc.tick())                          # nothing new: no churn

    def test_entering_a_game_is_not_leaving_the_party(self):
        """The experiment's defect: Party Home's stream closed when a phone opened the game, so
        the party saw it disappear. Here a player in the active session stays 'playing' however
        long the game runs without a Party Home request."""
        pc, clock = make()
        a = pc.join('device-a', 'Ana')
        b = pc.join('device-b', 'Ben')
        s = pc.launch('device-a', 'bluff', pc.party.version)
        pc.launch_accepted(s.id)
        clock.advance(3600)                                  # an hour in the game, no party requests
        pc.tick()
        self.assertEqual(pc.presence(a), 'playing')
        self.assertEqual(pc.presence(b), 'playing')
        self.assertEqual(pc.party.host_id, a.id)
        self.assertIn(a.id, pc.party.members)
        self.assertFalse(pc.party.ended)

    def test_a_table_coming_home_is_not_instantly_away(self):
        pc, clock = make()
        a = pc.join('device-a', 'Ana')
        s = pc.launch('device-a', 'bluff', pc.party.version)
        pc.launch_accepted(s.id)
        clock.advance(600)
        pc.game_reported_end(s.id, 'completed')
        self.assertEqual(pc.presence(a), 'here')             # released now; the walk home is short
        clock.advance(core.LIVE_WINDOW + 1)
        self.assertEqual(pc.presence(a), 'away')


class Host(unittest.TestCase):
    def test_succession_after_grace_to_earliest_joined_who_is_here(self):
        pc, clock = make()
        a = pc.join('device-a', 'Ana')
        pc.join('device-b', 'Ben')
        c = pc.join('device-c', 'Cy')
        clock.advance(core.LIVE_WINDOW + core.HOST_GRACE - 1)
        pc.touch('device-c')                                  # only Cy keeps polling
        pc.tick()
        self.assertEqual(pc.party.host_id, a.id)             # still within grace
        clock.advance(2)
        pc.touch('device-c')
        self.assertEqual(pc.party.host_id, c.id)             # Ben is away too: Cy

    def test_old_host_returning_does_not_take_it_back(self):
        pc, clock = make()
        pc.join('device-a', 'Ana')
        b = pc.join('device-b', 'Ben')
        clock.advance(core.LIVE_WINDOW + core.HOST_GRACE + 1)
        pc.touch('device-b')
        self.assertEqual(pc.party.host_id, b.id)
        pc.touch('device-a')
        self.assertEqual(pc.party.host_id, b.id)

    def test_vacant_then_first_member_back_is_host(self):
        pc, clock = make()
        pc.join('device-a', 'Ana')
        b = pc.join('device-b', 'Ben')
        clock.advance(core.LIVE_WINDOW + core.HOST_GRACE + 1)
        pc.tick()
        self.assertIsNone(pc.party.host_id)                  # nobody here: vacant
        pc.touch('device-b')
        self.assertEqual(pc.party.host_id, b.id)

    def test_host_in_the_game_keeps_the_role(self):
        pc, clock = make()
        a = pc.join('device-a', 'Ana')
        pc.join('device-b', 'Ben')
        s = pc.launch('device-a', 'bluff', pc.party.version)
        pc.launch_accepted(s.id)
        clock.advance(10 * (core.LIVE_WINDOW + core.HOST_GRACE))
        pc.touch('device-b')
        self.assertEqual(pc.party.host_id, a.id)

    def test_host_leaving_hands_over_at_once(self):
        pc, _ = make()
        pc.join('device-a', 'Ana')
        b = pc.join('device-b', 'Ben')
        pc.leave('device-a')
        self.assertEqual(pc.party.host_id, b.id)

    def test_transfer_needs_fresh_version_and_a_present_target(self):
        pc, clock = make()
        pc.join('device-a', 'Ana')
        b = pc.join('device-b', 'Ben')
        stale = pc.party.version - 1
        with self.assertRaises(Refused) as e:
            pc.transfer_host('device-a', b.id, stale)
        self.assertEqual(e.exception.code, 'stale')
        with self.assertRaises(Refused):
            pc.transfer_host('device-b', b.id, pc.party.version)   # not the host
        clock.advance(core.LIVE_WINDOW + 1)
        pc.touch('device-a')
        with self.assertRaises(Refused) as e:
            pc.transfer_host('device-a', b.id, pc.party.version)   # Ben is away
        self.assertEqual(e.exception.code, 'bad_target')
        pc.touch('device-b')
        pc.transfer_host('device-a', b.id, pc.party.version)
        self.assertEqual(pc.party.host_id, b.id)


class Session(unittest.TestCase):
    def setUp(self):
        self.pc, self.clock = make()
        self.a = self.pc.join('device-a', 'Ana')
        self.b = self.pc.join('device-b', 'Ben')

    def launch(self):
        s = self.pc.launch('device-a', 'bluff', self.pc.party.version)
        self.pc.launch_accepted(s.id)
        return s

    def test_roster_players_up_to_max_then_spectators_away_members_left_out(self):
        pc, clock = make()
        for d, n in (('device-a', 'Ana'), ('device-b', 'Ben'), ('device-c', 'Cy'),
                     ('device-d', 'Di'), ('device-e', 'Ed')):
            pc.join(d, n)
        clock.advance(core.LIVE_WINDOW + 1)
        for d in ('device-a', 'device-b', 'device-c', 'device-d'):
            pc.touch(d)                                        # Ed is away
        s = pc.launch('device-a', 'bluff', pc.party.version)
        roster = s.roster(pc.party.members)
        self.assertEqual([(r['name'], r['role']) for r in roster],
                         [('Ana', 'player'), ('Ben', 'player'), ('Cy', 'player'), ('Di', 'spectator')])
        self.assertEqual(set(roster[0]), {'participant', 'name', 'role'})   # nothing else leaves
        self.assertNotIn('device', repr(roster))
        self.assertNotIn('member-', repr(roster))

    def test_launch_is_host_only_versioned_and_one_at_a_time(self):
        with self.assertRaises(Refused):
            self.pc.launch('device-b', 'bluff', self.pc.party.version)
        with self.assertRaises(Refused) as e:
            self.pc.launch('device-a', 'bluff', self.pc.party.version - 1)
        self.assertEqual(e.exception.code, 'stale')
        with self.assertRaises(Refused) as e:
            self.pc.launch('device-a', 'chess', self.pc.party.version)
        self.assertEqual(e.exception.code, 'unknown_game')
        self.launch()
        with self.assertRaises(Refused) as e:
            self.pc.launch('device-a', 'bluff', self.pc.party.version)
        self.assertEqual(e.exception.code, 'busy')
        self.assertEqual(self.pc.view('device-a')['state'], 'active')

    def test_launch_failure_and_timeout_return_to_lobby(self):
        s = self.pc.launch('device-a', 'bluff', self.pc.party.version)
        self.assertEqual(self.pc.view('device-a')['state'], 'launching')
        self.assertTrue(self.pc.launch_failed(s.id, 'Games server is down.'))
        v = self.pc.view('device-a')
        self.assertEqual((v['state'], v['session']['outcome']), ('lobby', 'launch_failed'))
        s2 = self.pc.launch('device-a', 'bluff', self.pc.party.version)
        self.clock.advance(core.LAUNCH_TIMEOUT)
        self.pc.tick()
        self.assertEqual(s2.outcome, 'launch_failed')
        self.assertFalse(self.pc.launch_accepted(s2.id))        # a late accept cannot revive it

    def test_participant_ids_are_stable_across_reconnects_and_unique_per_session(self):
        s = self.launch()
        _, p1 = self.pc.participant_for('device-b')
        self.clock.advance(3000)
        _, p2 = self.pc.participant_for('device-b')
        self.assertIs(p1, p2)
        self.pc.leave('device-b')
        with self.assertRaises(Refused):
            self.pc.participant_for('device-b')                # left: no ticket
        self.pc.join('device-b', 'Ben')
        _, p3 = self.pc.participant_for('device-b')
        self.assertEqual(p3.id, p1.id)                         # back: the same game identity
        self.pc.game_reported_end(s.id, 'completed')
        s2 = self.launch()
        _, p4 = self.pc.participant_for('device-b')
        self.assertNotEqual(p4.id, p1.id)                      # a new session: unlinkable id
        self.assertNotEqual(s2.id, s.id)

    def test_late_member_is_admitted_as_spectator(self):
        self.launch()
        self.pc.join('device-c', 'Cy')
        _, p = self.pc.participant_for('device-c')
        self.assertEqual(p.role, 'spectator')
        self.assertEqual(self.pc.view('device-c')['session']['my_role'], 'spectator')

    def test_no_participant_outside_an_active_session(self):
        with self.assertRaises(Refused):
            self.pc.participant_for('device-a')
        self.pc.launch('device-a', 'bluff', self.pc.party.version)   # still launching
        with self.assertRaises(Refused):
            self.pc.participant_for('device-a')
        with self.assertRaises(Refused):
            self.pc.participant_for('device-zzz')                    # not a member

    def test_game_reports_completed_or_abandoned(self):
        for outcome in ('completed', 'abandoned'):
            with self.subTest(outcome=outcome):
                s = self.launch()
                self.pc.game_reported_end(s.id, outcome)
                v = self.pc.view('device-a')
                self.assertEqual((v['state'], v['session']['outcome']), ('lobby', outcome))

    def test_stale_or_bogus_reports_are_refused_and_never_resurrect(self):
        s1 = self.launch()
        self.pc.game_reported_end(s1.id, 'completed')
        s2 = self.launch()
        for sid, outcome in ((s1.id, 'completed'), ('session-nope', 'abandoned'), (s2.id, 'won')):
            with self.subTest(sid=sid, outcome=outcome):
                with self.assertRaises(Refused):
                    self.pc.game_reported_end(sid, outcome)
        self.assertEqual(s2.state, core.ACTIVE)
        self.assertEqual(s1.outcome, 'completed')
        self.assertFalse(self.pc.launch_accepted(s1.id))

    def test_end_for_everyone(self):
        s = self.launch()
        with self.assertRaises(Refused):
            self.pc.begin_end('device-b', self.pc.party.version)      # not host
        self.pc.begin_end('device-a', self.pc.party.version)
        self.assertEqual(s.state, core.ENDING)
        with self.assertRaises(Refused):
            self.pc.participant_for('device-b')                        # tickets stop at once
        self.assertTrue(self.pc.end_confirmed(s.id, True))
        self.assertEqual((s.state, s.outcome, s.game_confirmed_end), (core.ENDED, 'ended_by_host', True))
        self.assertEqual(self.pc.view('device-a')['state'], 'lobby')
        with self.assertRaises(Refused):
            self.pc.game_reported_end(s.id, 'completed')               # too late to matter

    def test_end_unconfirmed_times_out_but_the_party_moves_on(self):
        s = self.launch()
        self.pc.begin_end('device-a', self.pc.party.version)
        self.clock.advance(core.END_TIMEOUT)
        self.pc.tick()
        self.assertEqual((s.state, s.game_confirmed_end), (core.ENDED, False))
        self.launch()                                                  # a new game can start

    def test_game_report_during_ending_counts_as_confirmation(self):
        s = self.launch()
        self.pc.begin_end('device-a', self.pc.party.version)
        self.pc.game_reported_end(s.id, 'abandoned')
        self.assertEqual((s.outcome, s.game_confirmed_end), ('ended_by_host', True))

    def test_cancel_while_launching(self):
        s = self.pc.launch('device-a', 'bluff', self.pc.party.version)
        self.pc.begin_end('device-a', self.pc.party.version)
        self.assertEqual((s.state, s.outcome), (core.ENDED, 'launch_failed'))


class Idle(unittest.TestCase):
    def test_idle_party_ends_and_the_next_visit_starts_a_new_one(self):
        pc, clock = make()
        pc.join('device-a', 'Ana')
        first = pc.party.id
        clock.advance(core.PARTY_IDLE + core.LIVE_WINDOW + 1)
        pc.tick()
        clock.advance(1)
        view = pc.view('device-a')
        self.assertNotEqual(view['party'], first)
        self.assertEqual(view['members'], [])

    def test_a_running_game_keeps_the_party_alive(self):
        pc, clock = make()
        pc.join('device-a', 'Ana')
        s = pc.launch('device-a', 'bluff', pc.party.version)
        pc.launch_accepted(s.id)
        first = pc.party.id
        clock.advance(core.PARTY_IDLE * 2)
        pc.tick()
        self.assertEqual(pc.view(None)['party'], first)


class Fuzz(unittest.TestCase):
    """Random operation sequences (the model's fuzz, reduced). Invariants after every step:
    the host is a present-able member or vacant; at most one live session; the version never goes
    backwards within a party; a member's participant id in a session never changes."""

    def test_invariants(self):
        devices = [f'device-{i}' for i in range(5)]
        for seed in range(150):
            rng = random.Random(seed)
            pc, clock = make()
            seen_pids = {}
            party_id, version = pc.party.id, pc.party.version
            for _ in range(120):
                d = rng.choice(devices)
                op = rng.randrange(11)
                try:
                    if op == 0:
                        pc.join(d, rng.choice(['Ana', 'Ben', 'Cy']))
                    elif op == 1:
                        pc.touch(d)
                    elif op == 2:
                        pc.leave(d)
                    elif op == 3:
                        s = pc.launch(d, 'bluff', pc.party.version if rng.random() < .8 else 0)
                        if rng.random() < .8:
                            pc.launch_accepted(s.id)
                    elif op == 4:
                        s = pc.party.session
                        if s:
                            pc.game_reported_end(s.id if rng.random() < .8 else 'session-x',
                                                 rng.choice(['completed', 'abandoned']))
                    elif op == 5:
                        s = pc.begin_end(d, pc.party.version)
                        if rng.random() < .7:
                            pc.end_confirmed(s.id, rng.random() < .5)
                    elif op == 6:
                        s, p = pc.participant_for(d)
                        key = (s.id, pc._member_of(d).id)
                        self.assertEqual(seen_pids.setdefault(key, p.id), p.id)
                    elif op == 7:
                        others = [m.id for m in pc.party.members.values()]
                        if others:
                            pc.transfer_host(d, rng.choice(others), pc.party.version)
                    elif op == 8:
                        clock.advance(rng.choice([1, 20, 50, 80, 400]))
                    else:
                        pc.tick()
                except Refused:
                    pass
                party = pc.party
                if party.id != party_id:
                    party_id, version = party.id, party.version
                self.assertGreaterEqual(party.version, version, seed)
                version = party.version
                if party.host_id is not None:
                    self.assertFalse(party.members[party.host_id].left, seed)
                live = pc._live_session()
                if live is not None:
                    self.assertIs(live, party.session)
                    self.assertIn(live.state, (core.LAUNCHING, core.ACTIVE, core.ENDING))
                ids = [p.id for p in (party.session.participants.values() if party.session else [])]
                self.assertEqual(len(ids), len(set(ids)), seed)


if __name__ == '__main__':
    unittest.main()
