"""Party Core v0 rules (avrana.party.core) with an injected clock. No network, no threads."""
import random
import unittest

from avrana.party import core
from avrana.party.core import Refused

BLUFF = {'id': 'bluff', 'max_players': 3, 'late_join': 'spectator_only'}
BOMBER = {'id': 'bomber', 'max_players': 4, 'late_join': 'spectator_only'}
PREGAME = {'id': 'bluff', 'min_players': 2, 'max_players': 3, 'late_join': 'spectator_only',
           'pregame': True}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


def play(pc, clock, seconds, *devices, step=20.0):
    """`seconds` pass while the named devices' game pages follow the party: the bridge's long poll
    reaches Party Core about every 20 s (web/party/lib/bridge.js), and each poll is a heartbeat."""
    end = clock.t + seconds
    while clock.t < end:
        clock.advance(min(step, end - clock.t))
        for d in devices:
            pc.touch(d)


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
        self.assertIs(pc.reconnect('device-a', 'Ana'), a)

    def test_duplicate_names_are_numbered_and_names_never_authorize(self):
        pc, _ = make()
        pc.join('device-a', 'Ana')
        b = pc.join('device-b', 'Ana')
        self.assertEqual(b.name, 'Ana 2')
        with self.assertRaises(Refused):
            pc.launch('device-b', 'bluff', pc.party.version)     # same name, not the host

    def test_a_name_that_only_looks_like_another_is_numbered(self):
        """AVR-140: a blank letter or a look-alike alphabet must not make a second "Ana" the duplicate rule
        misses."""
        for second in ('Ana\u3164', 'Ana\uffa0', 'Ana\u2800', 'Ana\u034f', '\u3164Ana'):
            with self.subTest(second=ascii(second)):
                pc, _ = make()
                pc.join('device-a', 'Ana')
                b = pc.join('device-b', second)
                self.assertNotEqual(core._name_key(b.name), core._name_key('Ana'))
                self.assertTrue(b.name.endswith(' 2'), ascii(b.name))
        pc, _ = make()
        pc.join('device-a', 'Apa')
        self.assertEqual(pc.join('device-b', '\u0410\u0440\u0430').name, '\u0410\u0440\u0430 2')   # Cyrillic "Ара"
        self.assertEqual(pc.join('device-c', '\u0391\u03a1\u0391').name, '\u0391\u03a1\u0391 3')   # Greek "ΑΡΑ"

    def test_look_alike_folding_only_compares_it_never_rewrites_a_name(self):
        for name in ('\u0410\u0440\u0430', 'Ελένη', 'Анна', 'Zoë', '李雷'):
            with self.subTest(name=ascii(name)):
                self.assertEqual(core.clean_name(name), name)

    def test_bad_names_refused(self):
        pc, _ = make()
        for bad in ('', ' ', 'x' * 17, 'Admin', 'Hostess', 'Sуstem', None, 7, '‮​',
                    '\u3164', '\u1160\u115f', '\uffa0', '\u2800',      # names that draw as nothing (AVR-140)
                    'Ноѕт', 'НОЅТ', 'АDMIN'):                          # reserved words in look-alike letters
            with self.subTest(bad=bad):
                with self.assertRaises(Refused):
                    pc.join('device-z', bad)
        self.assertEqual(pc.party.members, {})

    def test_every_phone_sees_the_party_games_only_the_host_may_start_them(self):
        """AVR-127: followers (and a phone that has not joined yet) need to know which titles are
        party games, so Party Home never offers them as a solo launch; authority stays with
        me.host, which every host action re-checks."""
        pc, _ = make()
        pc.join('device-a', 'Ana')
        pc.join('device-b', 'Ben')
        for device in ('device-a', 'device-b', None, 'device-zzz'):
            self.assertEqual(pc.view(device)['games'], ['bluff'])
        self.assertFalse(pc.view('device-b')['me']['host'])
        with self.assertRaises(Refused) as e:
            pc.launch('device-b', 'bluff', pc.party.version)
        self.assertEqual(e.exception.code, 'not_host')

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
        long the game runs without a Party Home request: the game page's own follow (the bridge)
        is enough. Only a table whose every page went silent is abandoned (AVR-475, below). The
        host role is the exception (ADR 0006 amendment): Ana's own page is silent, so it passes to
        Ben, and Ana keeps her seat and her membership."""
        pc, clock = make()
        a = pc.join('device-a', 'Ana')
        b = pc.join('device-b', 'Ben')
        s = pc.launch('device-a', 'bluff', pc.party.version)
        pc.launch_accepted(s.id)
        play(pc, clock, 3600, 'device-b')                   # an hour in the game; only Ben's page follows
        pc.tick()
        self.assertEqual(pc.presence(a), 'playing')
        self.assertEqual(pc.presence(b), 'playing')
        self.assertEqual(pc.party.host_id, b.id)
        self.assertIn(a.id, pc.party.members)
        self.assertFalse(pc.party.ended)

    def test_a_table_coming_home_is_not_instantly_away(self):
        pc, clock = make()
        a = pc.join('device-a', 'Ana')
        s = pc.launch('device-a', 'bluff', pc.party.version)
        pc.launch_accepted(s.id)
        play(pc, clock, 600, 'device-a')
        clock.advance(core.LIVE_WINDOW + 5)                  # her page went quiet: away, until ...
        self.assertEqual(pc.presence(a), 'playing')
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

    def test_host_in_the_game_keeps_the_role_while_their_page_is_open(self):
        pc, clock = make()
        a = pc.join('device-a', 'Ana')
        pc.join('device-b', 'Ben')
        s = pc.launch('device-a', 'bluff', pc.party.version)
        pc.launch_accepted(s.id)
        play(pc, clock, 10 * (core.LIVE_WINDOW + core.HOST_GRACE), 'device-a', 'device-b')
        self.assertEqual(pc.party.host_id, a.id)

    def test_a_silent_host_in_the_game_hands_over_after_grace_and_the_round_goes_on(self):
        """The Host's phone dies mid-round while the others play on. A game that waits for its
        absent player (Checkers' mover, Best Guess's Guesser) never ends by itself, and the open
        pages keep the table from TABLE_ABANDON, so only a new Host can end it or take everyone
        home. Hosting passes on the same timers as outside a game; the seat and the round stay."""
        pc, clock = make()
        a = pc.join('device-a', 'Ana')
        b = pc.join('device-b', 'Ben')
        s = pc.launch('device-a', 'bluff', pc.party.version)
        pc.launch_accepted(s.id)
        roster = s.roster(pc.party.members)
        play(pc, clock, core.LIVE_WINDOW + core.HOST_GRACE - 5, 'device-b')    # Ana's page is silent
        pc.tick()
        self.assertEqual(pc.party.host_id, a.id)             # within grace: still Ana
        play(pc, clock, 10, 'device-b')
        pc.tick()
        self.assertEqual(pc.party.host_id, b.id)             # past grace: a player who is here
        self.assertEqual((s.state, s.roster(pc.party.members)), (core.ACTIVE, roster))
        self.assertEqual(pc.presence(a), 'playing')          # Ana keeps her seat
        pc.begin_end('device-b', pc.party.version)          # and Ben can end the round
        self.assertEqual(s.state, core.ENDING)
        pc.touch('device-a')                                 # Ana's phone comes back
        self.assertEqual(pc.party.host_id, b.id)             # a returning Host does not take it back

    def test_host_leaving_hands_over_at_once(self):
        pc, _ = make()
        pc.join('device-a', 'Ana')
        b = pc.join('device-b', 'Ben')
        pc.leave('device-a')
        self.assertEqual(pc.party.host_id, b.id)

    def test_host_leaving_mid_game_hands_over_to_a_player_and_the_game_goes_on(self):
        """AVR-127: players in the active game are present (playing), so they are successors; the
        game session is the party's, not the host's, and survives the handover untouched."""
        pc, _ = make()
        pc.join('device-a', 'Ana')
        b = pc.join('device-b', 'Ben')
        s = pc.launch('device-a', 'bluff', pc.party.version)
        pc.launch_accepted(s.id)
        roster = s.roster(pc.party.members)
        pc.leave('device-a')
        self.assertEqual(pc.party.host_id, b.id)             # at once, not vacant
        v = pc.view('device-b')
        self.assertEqual((v['state'], v['session']['id'], v['me']['host']), ('active', s.id, True))
        self.assertEqual(s.roster(pc.party.members), roster)  # the roster did not move
        pc.begin_end('device-b', pc.party.version)          # the new host has real authority
        self.assertEqual(s.state, core.ENDING)

    def test_an_away_host_outside_the_game_hands_over_to_a_player(self):
        pc, clock = make()
        a = pc.join('device-a', 'Ana')
        pc.join('device-b', 'Ben')
        c = pc.join('device-c', 'Cy')
        clock.advance(core.LIVE_WINDOW + 1)
        pc.touch('device-a')
        pc.touch('device-b')                                  # Cy is away at the launch
        s = pc.launch('device-a', 'bluff', pc.party.version)
        pc.launch_accepted(s.id)
        self.assertNotIn(c.id, s.participants)
        pc.touch('device-c')                                  # Cy is back on Party Home, not in the game
        pc.transfer_host('device-a', c.id, pc.party.version)
        # then Cy's phone goes quiet; Ana's and Ben's game pages follow the party (bridge heartbeats)
        play(pc, clock, core.LIVE_WINDOW + core.HOST_GRACE + 1, 'device-a', 'device-b')
        pc.tick()
        self.assertEqual(pc.party.host_id, a.id)             # Ana is playing and live: eligible
        self.assertEqual(s.state, core.ACTIVE)

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


class HostSilentInGame(unittest.TestCase):
    """ADR 0006 as amended (owner, 2026-10-22): Party Host authority follows the Host's own presence,
    in a game or not; the game seat and every in-game role stay where they are."""
    GRACE = core.LIVE_WINDOW + core.HOST_GRACE

    def table(self, *names):
        self.pc, self.clock = make()
        self.m = {n: self.pc.join(f'device-{n}', n) for n in names}
        self.s = self.pc.launch(f'device-{names[0]}', 'bluff', self.pc.party.version)
        self.pc.launch_accepted(self.s.id)
        self.roles = {mid: p.role for mid, p in self.s.participants.items()}
        return self.s

    def host(self):
        h = self.pc.party.host_id
        return self.pc.party.members[h].name if h else None

    def silent(self, seconds, *live):
        play(self.pc, self.clock, seconds, *(f'device-{n}' for n in live))
        self.pc.tick()

    def test_a_connected_host_keeps_the_role_however_long_the_round(self):
        self.table('Ana', 'Ben')
        self.silent(20 * self.GRACE, 'Ana', 'Ben')
        self.assertEqual(self.host(), 'Ana')

    def test_a_disconnected_host_is_succeeded_at_grace_not_before(self):
        self.table('Ana', 'Ben')
        self.silent(self.GRACE - 1, 'Ben')
        self.assertEqual(self.host(), 'Ana')
        self.silent(2, 'Ben')
        self.assertEqual(self.host(), 'Ben')

    def test_a_host_who_reconnects_before_grace_keeps_the_role_and_the_grace_starts_over(self):
        self.table('Ana', 'Ben')
        self.silent(self.GRACE - 5, 'Ben')
        self.pc.touch('device-Ana')                          # back in time
        self.silent(self.GRACE - 5, 'Ben')                   # quiet again, but not for a full grace
        self.assertEqual(self.host(), 'Ana')

    def test_a_host_who_returns_after_succession_plays_on_without_the_role(self):
        s = self.table('Ana', 'Ben')
        self.silent(self.GRACE + 1, 'Ben')
        self.pc.touch('device-Ana')
        self.silent(10 * self.GRACE, 'Ana', 'Ben')
        self.assertEqual(self.host(), 'Ben')
        self.assertEqual(self.pc.presence(self.m['Ana']), 'playing')
        self.assertEqual(self.pc.view('device-Ana')['session']['my_role'], 'player')
        with self.assertRaises(Refused):
            self.pc.begin_end('device-Ana', self.pc.party.version)
        self.assertEqual(s.state, core.ACTIVE)

    def test_a_seated_player_whose_phone_is_gone_is_never_chosen(self):
        """Cleo joined before Ben and holds a seat, but her phone went with Ana's: the role goes to
        Ben, whose page is here, not to a seat."""
        self.table('Ana', 'Cleo', 'Ben')
        self.silent(self.GRACE + 1, 'Ben')
        self.assertEqual(self.host(), 'Ben')

    def test_with_nobody_here_the_role_is_vacant_until_someone_is_and_the_round_waits(self):
        s = self.table('Ana', 'Ben')
        self.silent(self.GRACE + 1)                          # every phone is gone
        self.assertIsNone(self.pc.party.host_id)
        self.assertEqual(s.state, core.ACTIVE)               # nothing ended for it (TABLE_ABANDON may, later)
        self.pc.touch('device-Ben')
        self.assertEqual(self.host(), 'Ben')

    def test_the_new_host_ends_a_stalled_game_and_everyone_goes_home(self):
        s = self.table('Ana', 'Ben')
        self.silent(self.GRACE + 1, 'Ben')
        self.pc.begin_end('device-Ben', self.pc.party.version)
        self.assertEqual(self.pc.location()['at'], 'home')   # at once, while the game stops
        self.pc.end_confirmed(s.id, True)
        v = self.pc.view('device-Ben')
        self.assertEqual((s.state, s.outcome, v['location']['at']), (core.ENDED, 'ended_by_host', 'home'))
        self.assertIn(self.m['Ana'].id, self.pc.party.members)   # Ana is still a member

    def test_a_stalled_game_that_never_confirms_the_end_still_lets_the_party_go(self):
        s = self.table('Ana', 'Ben')
        self.silent(self.GRACE + 1, 'Ben')
        self.pc.begin_end('device-Ben', self.pc.party.version)
        self.silent(core.END_TIMEOUT + 1, 'Ben')             # the game's server never answers
        self.assertEqual((s.state, self.pc.location()['at']), (core.ENDED, 'home'))
        again = self.pc.launch('device-Ben', 'bluff', self.pc.party.version)
        self.assertIsNot(again, s)                           # and the new Host can start the next one

    def test_succession_touches_no_in_game_role(self):
        """Party authority only: no seat, role or turn moves with it (the game owns those)."""
        s = self.table('Ana', 'Ben', 'Cleo')
        roster = s.roster(self.pc.party.members)
        self.silent(self.GRACE + 1, 'Ben', 'Cleo')
        self.assertEqual(self.host(), 'Ben')
        self.assertEqual({mid: p.role for mid, p in s.participants.items()}, self.roles)
        self.assertEqual(s.roster(self.pc.party.members), roster)
        self.assertEqual(s.state, core.ACTIVE)



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
        play(self.pc, self.clock, 3000, 'device-a')
        _, p2 = self.pc.participant_for('device-b')
        self.assertIs(p1, p2)
        self.pc.leave('device-b')
        with self.assertRaises(Refused):
            self.pc.participant_for('device-b')                # left: no ticket
        self.pc.reconnect('device-b', 'Ben')
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
        self.assertIn('did not confirm', s.detail)                     # AVR-223: never silent
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


class Navigation(unittest.TestCase):
    """AVR-128: Party Core owns where everyone is. `nav` moves only on committed transitions;
    the host's switch ends the game that is on before the next session exists."""

    def setUp(self):
        self.pc, self.clock = make([BLUFF, BOMBER])
        self.pc.join('device-a', 'Ana')
        self.pc.join('device-b', 'Ben')

    def v(self):
        return self.pc.party.version

    def nav(self, device='device-b'):
        return self.pc.view(device)['nav']

    def start(self, game='bluff'):
        s = self.pc.launch('device-a', game, self.v())
        self.pc.launch_accepted(s.id)
        return s

    def switch(self, game, confirmed=True):
        old = self.pc.begin_switch('device-a', game, self.v())
        self.pc.end_confirmed(old.id, confirmed)
        return old, self.pc.launch_pending()

    def test_nav_moves_on_committed_start_and_host_end_only(self):
        self.assertEqual(self.nav(), {'seq': 0, 'to': 'home', 'game': None, 'session': None,
                                      'from': None})
        s = self.pc.launch('device-a', 'bluff', self.v())
        self.assertEqual(self.nav()['seq'], 0)                   # launching is intent, not a move
        self.pc.launch_accepted(s.id)
        self.assertEqual(self.nav(), {'seq': 1, 'to': 'game', 'game': 'bluff', 'session': s.id,
                                      'from': None})
        self.pc.begin_end('device-a', self.v())                  # the host's end: home at once
        self.assertEqual(self.nav(), {'seq': 2, 'to': 'home', 'game': None, 'session': None,
                                      'from': 'bluff'})
        self.pc.end_confirmed(s.id, True)
        self.assertEqual(self.nav()['seq'], 2)                   # one move, not two

    def test_a_game_ending_by_its_own_rules_leaves_everyone_on_its_end_screen(self):
        s = self.start()
        self.pc.game_reported_end(s.id, 'completed')
        self.assertEqual((self.pc.view('device-b')['state'], self.nav()['to'], self.nav()['seq']),
                         ('lobby', 'game', 1))
        s = self.pc.launch('device-a', 'bomber', self.v())       # a start that fails from here
        self.pc.launch_failed(s.id, 'down')                      # leaves them on the end screen
        self.assertEqual((self.nav()['to'], self.nav()['seq']), ('game', 1))
        nxt = self.start('bomber')                               # the host's next start moves them
        self.assertEqual((self.nav()['game'], self.nav()['session'], self.nav()['seq']),
                         ('bomber', nxt.id, 2))

    def test_failed_or_cancelled_starts_never_move_anyone(self):
        s = self.pc.launch('device-a', 'bluff', self.v())
        self.pc.launch_failed(s.id, 'down')
        s = self.pc.launch('device-a', 'bluff', self.v())
        self.pc.begin_end('device-a', self.v())
        self.clock.advance(core.LAUNCH_TIMEOUT + 1)
        self.assertEqual(self.nav()['seq'], 0)

    def test_host_switch_ends_the_old_game_first_then_everyone_goes_to_the_next(self):
        a = self.start()
        old = self.pc.begin_switch('device-a', 'bomber', self.v())
        self.assertIs(old, a)
        view = self.pc.view('device-b')
        self.assertEqual((view['state'], view['switching_to'], view['nav']['game']),
                         ('ending', 'bomber', 'bluff'))            # nobody moves yet
        with self.assertRaises(Refused) as e:                    # nothing starts in between
            self.pc.launch('device-a', 'bomber', self.v())
        self.assertEqual(e.exception.code, 'busy')
        with self.assertRaises(Refused):                         # no tickets for the old one
            self.pc.participant_for('device-b')
        self.pc.end_confirmed(a.id, True)
        self.assertEqual((a.state, a.outcome), (core.ENDED, 'ended_by_host'))
        self.assertEqual(self.nav()['game'], 'bluff')            # still no home detour
        b = self.pc.launch_pending()
        self.assertEqual((b.game_id, b.state, self.pc.party.pending), ('bomber', core.LAUNCHING, None))
        self.pc.launch_accepted(b.id)
        self.assertEqual((self.nav()['to'], self.nav()['game'], self.nav()['session'],
                          self.nav()['seq']), ('game', 'bomber', b.id, 2))
        self.assertEqual(self.pc.participant_for('device-b')[0], b)

    def test_switch_stops_when_the_old_game_did_not_confirm_its_end(self):
        self.start()
        old, nxt = self.switch('bomber', confirmed=False)
        self.assertIsNone(nxt)                                   # never on top of a live runtime
        view = self.pc.view('device-b')
        self.assertEqual((view['state'], view['switching_to'], view['nav']['to'],
                          view['nav']['from']), ('lobby', None, 'home', 'bluff'))
        self.assertIn('did not stop', view['session']['detail'])

    def test_switch_launch_failure_sends_everyone_home(self):
        self.start()
        _, b = self.switch('bomber')
        self.pc.launch_failed(b.id, 'down')
        self.assertEqual((self.nav()['to'], self.nav()['from']), ('home', 'bomber'))

    def test_a_switch_never_bounces_through_party_home(self):
        """AVR-223 (3): once the old game has stopped, `nav` goes straight to the next session
        while it launches; followers see `setup`, not a flash of Party Home."""
        self.start()
        old, b = self.switch('bomber')
        loc = self.pc.location()
        self.assertEqual((self.nav()['to'], self.nav()['session'], loc['at'], loc['game']),
                         ('game', b.id, 'setup', 'bomber'))
        seq = self.nav()['seq']
        self.pc.launch_accepted(b.id)
        self.assertEqual((self.nav()['seq'], self.pc.location()['at']), (seq, 'game'))  # one move

    def test_a_switch_whose_old_game_never_stops_says_why(self):
        """AVR-223 (4): the end timer, not only the link's reply, surfaces the dropped switch."""
        self.start()
        old = self.pc.begin_switch('device-a', 'bomber', self.v())
        self.clock.advance(core.END_TIMEOUT + 1)
        self.pc.tick()
        view = self.pc.view('device-b')
        self.assertEqual((old.state, old.outcome, view['switching_to'], view['nav']['to']),
                         (core.ENDED, 'ended_by_host', None, 'home'))
        self.assertIn('did not stop, so the next one did not start', view['session']['detail'])
        self.assertIsNone(self.pc.launch_pending())

    def test_host_cancelling_the_switched_launch_sends_everyone_home(self):
        self.start()
        _, b = self.switch('bomber')
        self.pc.begin_end('device-a', self.v())
        self.assertEqual((b.outcome, self.nav()['to']), ('launch_failed', 'home'))

    def test_switch_end_timeout_does_not_start_the_next_game(self):
        self.start()
        self.pc.begin_switch('device-a', 'bomber', self.v())
        self.clock.advance(core.END_TIMEOUT + 1)
        self.pc.tick()                                           # the end timed out
        self.assertIsNone(self.pc.launch_pending())
        self.assertEqual((self.pc._live_session(), self.nav()['to']), (None, 'home'))

    def test_only_the_host_navigates_the_party_and_only_from_the_current_version(self):
        self.start()
        v = self.v()
        for call in (lambda: self.pc.begin_switch('device-b', 'bomber', v),
                     lambda: self.pc.begin_end('device-b', v),
                     lambda: self.pc.launch('device-b', 'bomber', v)):
            with self.assertRaises(Refused) as e:
                call()
            self.assertEqual(e.exception.code, 'not_host')
        with self.assertRaises(Refused) as e:
            self.pc.begin_switch('device-x', 'bomber', v)
        self.assertEqual(e.exception.code, 'not_member')
        self.pc.join('device-c', 'Cy')                           # the party moved on
        with self.assertRaises(Refused) as e:
            self.pc.begin_switch('device-a', 'bomber', v)
        self.assertEqual(e.exception.code, 'stale')
        with self.assertRaises(Refused) as e:
            self.pc.begin_switch('device-a', 'nope', self.v())
        self.assertEqual(e.exception.code, 'unknown_game')
        self.assertEqual(self.pc.party.session.game_id, 'bluff')
        self.assertEqual(self.pc.party.session.state, core.ACTIVE)

    def test_switch_needs_a_game_on_and_only_one_switch_at_a_time(self):
        with self.assertRaises(Refused) as e:
            self.pc.begin_switch('device-a', 'bomber', self.v())
        self.assertEqual(e.exception.code, 'no_game')
        self.start()
        self.pc.begin_switch('device-a', 'bomber', self.v())
        with self.assertRaises(Refused) as e:
            self.pc.begin_switch('device-a', 'bluff', self.v())
        self.assertEqual(e.exception.code, 'busy')

    def test_leave_is_personal_and_never_moves_the_party(self):
        s = self.start()
        self.pc.leave('device-b')
        self.assertEqual((self.pc.party.session.state, self.nav('device-a')['session']),
                         (core.ACTIVE, s.id))

    def test_a_page_for_another_game_gets_no_ticket(self):
        self.start()
        with self.assertRaises(Refused) as e:
            self.pc.participant_for('device-b', 'bomber')
        self.assertEqual(e.exception.code, 'no_game')
        s, _ = self.pc.participant_for('device-b', 'bluff')
        self.assertEqual(s.game_id, 'bluff')

    def test_a_new_party_restarts_nav(self):
        self.start()
        self.pc.game_reported_end(self.pc.party.session.id, 'completed')
        self.clock.advance(core.LIVE_WINDOW + 1)
        self.pc.tick()                                           # nobody here: idle from now
        self.clock.advance(core.PARTY_IDLE + 1)
        view = self.pc.view(None)
        self.assertEqual(view['nav']['seq'], 0)                  # key navigation by (party, seq)


class Pregame(unittest.TestCase):
    """AVR-129: a pregame game opens in setup; members choose to play or watch; only the host
    starts, and only when everyone here has chosen and the minimum holds. Roles change only at
    the setup boundary."""

    def setUp(self):
        self.pc, self.clock = make([PREGAME, BOMBER])
        self.a = self.pc.join('device-a', 'Ana')
        self.b = self.pc.join('device-b', 'Ben')
        self.c = self.pc.join('device-c', 'Cy')

    def v(self):
        return self.pc.party.version

    def setup(self):
        return self.pc.launch('device-a', 'bluff', self.v())

    def refused(self, code, fn, *args):
        with self.assertRaises(Refused) as e:
            fn(*args)
        self.assertEqual(e.exception.code, code)

    def test_setup_is_a_committed_move_to_the_game_with_nothing_running(self):
        s = self.setup()
        self.assertEqual((s.state, s.participants), (core.SETUP, {}))
        view = self.pc.view('device-b')
        self.assertEqual((view['state'], view['nav']['to'], view['nav']['game'], view['nav']['session']),
                         ('setup', 'game', 'bluff', s.id))
        st = view['session']['setup']
        self.assertEqual((st['min'], st['max'], st['mine'], st['players']), (2, 3, None, 0))
        self.assertEqual(st['waiting'], [self.a.id, self.b.id, self.c.id])
        self.assertIn('Waiting for Ana, Ben, Cy', st['blocker'])

    def test_only_the_host_starts_and_only_when_everyone_has_chosen(self):
        s = self.setup()
        self.pc.choose('device-a', 'player')
        self.pc.choose('device-b', 'player')
        self.refused('not_host', self.pc.start_round, 'device-b', self.v())
        self.refused('unresolved', self.pc.start_round, 'device-a', self.v())   # Cy has not chosen
        self.pc.choose('device-c', 'spectator')
        self.refused('stale', self.pc.start_round, 'device-a', self.v() - 1)
        self.refused('not_member', self.pc.start_round, 'device-x', self.v())
        s = self.pc.start_round('device-a', self.v())
        self.assertEqual(s.state, core.LAUNCHING)
        roles = {mid: p.role for mid, p in s.participants.items()}
        self.assertEqual(roles, {self.a.id: 'player', self.b.id: 'player', self.c.id: 'spectator'})
        self.assertEqual([r['role'] for r in s.roster(self.pc.party.members)],
                         ['player', 'player', 'spectator'])     # spectators are never seated

    def test_minimum_and_maximum_players(self):
        self.setup()
        self.pc.choose('device-a', 'player')
        self.pc.choose('device-b', 'spectator')
        self.pc.choose('device-c', 'spectator')
        self.refused('player_count', self.pc.start_round, 'device-a', self.v())
        self.assertIn('2 players needed', self.pc.view('device-a')['session']['setup']['blocker'])
        self.pc.join('device-d', 'Dee')
        for d in ('device-b', 'device-c', 'device-d'):
            self.pc.choose(d, 'player')                          # 4 players; the maximum is 3
        self.refused('player_count', self.pc.start_round, 'device-a', self.v())
        self.pc.choose('device-d', 'spectator')
        self.assertIsNone(self.pc.view('device-a')['session']['setup']['blocker'])
        self.pc.start_round('device-a', self.v())

    def test_choices_can_change_during_setup_but_not_during_the_round(self):
        s = self.setup()
        self.pc.choose('device-b', 'spectator')
        self.pc.choose('device-b', 'player')                     # changed their mind: fine
        v = self.v()
        self.pc.choose('device-b', 'player')                     # the same choice: no new version
        self.assertEqual(self.v(), v)
        self.refused('bad_choice', self.pc.choose, 'device-b', 'host')
        for d in ('device-a', 'device-c'):
            self.pc.choose(d, 'player')
        self.pc.start_round('device-a', self.v())
        self.pc.launch_accepted(s.id)
        self.refused('round_on', self.pc.choose, 'device-b', 'spectator')
        self.assertEqual(s.participants[self.b.id].role, 'player')   # the live round is untouched

    def test_away_members_do_not_block_and_late_arrivals_watch_until_the_next_setup(self):
        s = self.setup()
        self.clock.advance(core.LIVE_WINDOW + 1)
        self.pc.touch('device-a')
        self.pc.touch('device-b')                               # Cy is away now
        self.pc.choose('device-a', 'player')
        self.pc.choose('device-b', 'player')
        self.assertEqual(self.pc.view('device-a')['session']['setup']['waiting'], [])
        self.pc.start_round('device-a', self.v())
        self.pc.launch_accepted(s.id)
        self.assertNotIn(self.c.id, s.participants)
        _, p = self.pc.participant_for('device-c', 'bluff')     # Cy comes back mid-round
        self.assertEqual(p.role, 'spectator')
        d = self.pc.join('device-d', 'Dee')                     # a new member mid-round
        self.assertEqual(s.participants[d.id].role, 'spectator')

    def test_a_member_joining_during_setup_must_choose_too(self):
        self.setup()
        for d in ('device-a', 'device-b', 'device-c'):
            self.pc.choose(d, 'player')
        self.pc.join('device-d', 'Dee')
        self.refused('unresolved', self.pc.start_round, 'device-a', self.v())
        self.pc.choose('device-d', 'spectator')
        self.pc.start_round('device-a', self.v())

    def test_tickets_wait_for_the_start_and_then_follow_the_choices(self):
        s = self.setup()
        self.refused('setup', self.pc.participant_for, 'device-b', 'bluff')
        self.refused('no_game', self.pc.participant_for, 'device-b')            # an older page
        self.refused('no_game', self.pc.participant_for, 'device-b', 'bomber')
        for d, c in (('device-a', 'player'), ('device-b', 'player'), ('device-c', 'spectator')):
            self.pc.choose(d, c)
        self.pc.start_round('device-a', self.v())
        self.refused('setup', self.pc.participant_for, 'device-c', 'bluff')     # still launching
        self.pc.launch_accepted(s.id)
        self.assertEqual(self.pc.participant_for('device-c', 'bluff')[1].role, 'spectator')
        self.assertEqual(self.pc.participant_for('device-b', 'bluff')[1].role, 'player')
        self.assertEqual(self.pc.view('device-b')['nav']['seq'], 1)  # active is no second move

    def test_host_end_during_setup_sends_everyone_home(self):
        s = self.setup()
        self.refused('not_host', self.pc.begin_end, 'device-b', self.v())
        self.pc.begin_end('device-a', self.v())
        view = self.pc.view('device-b')
        self.assertEqual((s.state, s.outcome, view['state'], view['nav']['to'], view['nav']['from']),
                         (core.ENDED, 'ended_by_host', 'lobby', 'home', 'bluff'))
        self.refused('no_game', self.pc.choose, 'device-b', 'player')

    def test_a_failed_launch_after_setup_sends_everyone_home(self):
        s = self.setup()
        for d in ('device-a', 'device-b', 'device-c'):
            self.pc.choose(d, 'player')
        self.pc.start_round('device-a', self.v())
        self.pc.launch_failed(s.id, 'down')
        self.assertEqual(self.pc.view('device-b')['nav']['to'], 'home')

    def test_switching_from_setup_or_into_setup(self):
        s = self.setup()
        old = self.pc.begin_switch('device-a', 'bomber', self.v())
        self.assertEqual((old.state, old.game_confirmed_end), (core.ENDED, True))
        nxt = self.pc.launch_pending()
        self.assertEqual((nxt.game_id, nxt.state), ('bomber', core.LAUNCHING))
        self.pc.launch_accepted(nxt.id)
        self.pc.begin_switch('device-a', 'bluff', self.v())
        self.pc.end_confirmed(nxt.id, True)
        again = self.pc.launch_pending()
        self.assertEqual((again.game_id, again.state, again.choices), ('bluff', core.SETUP, {}))
        self.assertEqual(self.pc.view('device-a')['nav']['session'], again.id)
        self.assertIsNot(again, s)                                # every round is set up afresh

    def test_non_pregame_games_launch_directly(self):
        s = self.pc.launch('device-a', 'bomber', self.v())
        self.assertEqual(s.state, core.LAUNCHING)
        self.refused('no_setup', self.pc.start_round, 'device-a', self.v())
        self.refused('round_on', self.pc.choose, 'device-b', 'player')


class ConsoleLocation(unittest.TestCase):
    """ADR 0011: one authoritative location for the whole party, moved only by the host."""

    def setUp(self):
        self.pc, self.clock = make([PREGAME, BOMBER])
        self.a = self.pc.join('device-a', 'Ana', 'gaze-07')
        self.b = self.pc.join('device-b', 'Ben')

    def v(self):
        return self.pc.party.version

    def at(self, device='device-b'):
        loc = self.pc.view(device)['location']
        return loc['at'], loc['game']

    def round(self):
        s = self.pc.launch('device-a', 'bluff', self.v())
        self.pc.choose('device-a', 'player')
        self.pc.choose('device-b', 'player')
        self.pc.start_round('device-a', self.v())
        self.pc.launch_accepted(s.id)
        return s

    def refused(self, code, fn, *args):
        with self.assertRaises(Refused) as e:
            fn(*args)
        self.assertEqual(e.exception.code, code)

    def test_home_setup_game_results_home(self):
        self.assertEqual(self.at(), ('home', None))
        s = self.pc.launch('device-a', 'bluff', self.v())
        self.assertEqual(self.at(), ('setup', 'bluff'))
        self.pc.choose('device-a', 'player')
        self.pc.choose('device-b', 'player')
        self.pc.start_round('device-a', self.v())
        self.assertEqual(self.at(), ('setup', 'bluff'))          # launching: still the setup scene
        self.pc.launch_accepted(s.id)
        self.assertEqual(self.at(), ('game', 'bluff'))
        self.pc.game_reported_end(s.id, 'completed')
        self.assertEqual(self.at(), ('results', 'bluff'))       # held until the host moves on
        self.refused('not_host', self.pc.go_home, 'device-b', self.v())
        got = self.pc.go_home('device-a', self.v())
        self.assertIs(got, s)
        self.assertEqual(self.at(), ('home', None))
        self.refused('not_results', self.pc.go_home, 'device-a', self.v())

    def test_play_again_from_results_is_a_fresh_setup(self):
        s = self.round()
        self.pc.game_reported_end(s.id, 'completed')
        self.assertEqual(self.at(), ('results', 'bluff'))
        self.refused('not_host', self.pc.launch, 'device-b', 'bluff', self.v())
        again = self.pc.launch('device-a', 'bluff', self.v())
        self.assertEqual((self.at(), again.choices), (('setup', 'bluff'), {}))

    def test_an_abandoned_round_has_no_results_to_hold_so_everyone_goes_home(self):
        """AVR-223 (1): a game (or a managed runtime) that gives up leaves no surface worth
        standing on; the party is home at once, and the outcome is still recorded."""
        s = self.round()
        self.pc.game_reported_end(s.id, 'abandoned')
        self.assertEqual(self.at(), ('home', None))
        v = self.pc.view('device-b')
        self.assertEqual((v['session']['outcome'], v['nav']['to'], v['nav']['from']),
                         ('abandoned', 'home', 'bluff'))
        self.refused('not_results', self.pc.go_home, 'device-a', self.v())

    def test_host_end_goes_home_and_a_direct_game_has_no_setup(self):
        first = self.round()
        self.pc.begin_end('device-a', self.v())
        self.assertEqual(self.at(), ('home', None))               # at once, while the game resets
        self.pc.end_confirmed(first.id, True)
        s = self.pc.launch('device-a', 'bomber', self.v())
        self.assertEqual(self.at(), ('home', None))               # launching directly: not yet moved
        self.pc.launch_accepted(s.id)
        self.assertEqual(self.at(), ('game', 'bomber'))

    def test_every_phone_sees_the_same_location(self):
        s = self.round()
        self.pc.join('device-c', 'Cy')                            # late: a spectator, same place
        locs = {d: self.pc.view(d)['location'] for d in ('device-a', 'device-b', 'device-c', None)}
        self.assertEqual({(l['at'], l['session']) for l in locs.values()}, {('game', s.id)})

    def test_avatars_are_bundled_gaze_ids_only(self):
        members = {m['name']: m['avatar'] for m in self.pc.view('device-a')['members']}
        self.assertEqual(members, {'Ana': 'gaze-07', 'Ben': None})
        self.pc.rename('device-b', 'Ben', 'gaze-12')
        for bad in ('../x', 'https://evil/x.svg', 'gaze-7', 12, 'gaze-12.svg'):
            self.pc.join('device-a', 'Ana', bad)
            self.assertIsNone(self.pc.party.members[self.a.id].avatar, bad)
        self.assertEqual(self.pc.party.members[self.b.id].avatar, 'gaze-12')


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


class TableAbandon(unittest.TestCase):
    """AVR-475 (PARTY-LIFECYCLE TABLE_ABANDON): a round whose every player's page went silent ends as
    `abandoned` TABLE_ABANDON after the last seat emptied (LIVE_WINDOW after that player's last
    request), and the party goes home; seen on the Pi when every browser of an OpenCE round closed."""

    def setUp(self):
        self.pc, self.clock = make()
        self.a = self.pc.join('device-a', 'Ana')
        self.b = self.pc.join('device-b', 'Ben')
        self.s = self.pc.launch('device-a', 'bluff', self.pc.party.version)
        self.pc.launch_accepted(self.s.id)
        self.start = self.clock.t

    def deadline(self, last_seen):
        return last_seen + core.LIVE_WINDOW + core.TABLE_ABANDON

    def test_every_page_silent_abandons_at_the_deadline_not_before(self):
        self.clock.t = self.deadline(self.start) - 1
        self.pc.tick()
        self.assertEqual(self.s.state, core.ACTIVE)
        self.assertEqual(self.pc.presence(self.a), 'playing')
        self.clock.advance(1)
        self.pc.tick()
        self.assertEqual((self.s.state, self.s.outcome), (core.ENDED, 'abandoned'))
        self.assertEqual(self.s.detail, 'Everyone left the game.')
        self.assertEqual(self.pc.location()['at'], 'home')
        self.assertEqual(self.pc.abandoned, [self.s])
        self.assertEqual(self.pc.presence(self.a), 'away')   # gone, not freshly "home"
        self.assertIsNone(self.s.reason)                     # the view's reason key is unchanged

    def test_counted_from_the_last_players_last_request(self):
        play(self.pc, self.clock, 200, 'device-b')           # Ben's page follows for a while
        last = self.clock.t
        self.clock.t = self.deadline(last) - 1
        self.pc.tick()
        self.assertEqual(self.s.state, core.ACTIVE)
        self.clock.advance(1)
        self.pc.tick()
        self.assertEqual(self.s.outcome, 'abandoned')

    def test_one_page_still_following_keeps_the_round_for_hours(self):
        play(self.pc, self.clock, 3 * 3600, 'device-a')
        self.assertEqual(self.s.state, core.ACTIVE)
        self.assertEqual(self.pc.abandoned, [])

    def test_a_player_back_before_the_deadline_keeps_it(self):
        self.clock.t = self.deadline(self.start) - 5
        self.pc.touch('device-b')
        self.clock.t = self.deadline(self.start) + 60
        self.pc.tick()
        self.assertEqual(self.s.state, core.ACTIVE)

    def test_a_watcher_alone_does_not_hold_a_table_with_no_players(self):
        self.pc.join('device-c', 'Cat')                      # joined after the start: watches
        play(self.pc, self.clock, core.LIVE_WINDOW + core.TABLE_ABANDON + 20, 'device-c')
        self.assertEqual(self.s.outcome, 'abandoned')

    def test_applied_at_the_next_request_and_a_newcomer_can_host_a_new_round(self):
        """The Pi run: every browser closed mid-round; the next arrival must be able to start again.
        No tick runs here: the deadline holds when the newcomer acts (R4)."""
        self.clock.t = self.deadline(self.start) + 1
        d = self.pc.join('device-d', 'Dee')
        self.assertEqual(self.s.outcome, 'abandoned')
        self.assertEqual(self.pc.party.host_id, d.id)        # Ana is long gone: the role moved
        s2 = self.pc.launch('device-d', 'bluff', self.pc.party.version)
        self.pc.launch_accepted(s2.id)
        self.assertEqual(self.pc.location()['at'], 'game')

    def test_only_an_active_round(self):
        pc, clock = make([PREGAME])
        pc.join('device-a', 'Ana')
        s = pc.launch('device-a', 'bluff', pc.party.version)      # setup
        clock.advance(core.LIVE_WINDOW + core.TABLE_ABANDON + 60)
        pc.tick()
        self.assertEqual(s.state, core.SETUP)
        self.assertEqual(pc.abandoned, [])

    def test_a_round_the_game_ended_first_is_not_abandoned_again(self):
        self.pc.game_reported_end(self.s.id, 'completed')
        self.clock.t = self.deadline(self.start) + 60
        self.pc.tick()
        self.assertEqual(self.s.outcome, 'completed')
        self.assertEqual(self.pc.abandoned, [])


class Fuzz(unittest.TestCase):
    """Random operation sequences (the model's fuzz, reduced). Invariants after every step:
    the host is a present-able member or vacant; at most one live session; the version never goes
    backwards within a party; a member's participant id in a session never changes."""

    def test_invariants(self):
        devices = [f'device-{i}' for i in range(5)]
        for seed in range(150):
            rng = random.Random(seed)
            pc, clock = make([PREGAME if seed % 2 else BLUFF, BOMBER])
            seen_pids = {}
            party_id, version, nav = pc.party.id, pc.party.version, 0
            for _ in range(120):
                d = rng.choice(devices)
                op = rng.randrange(14)
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
                    elif op == 11:
                        pc.choose(d, rng.choice(['player', 'spectator', 'player']))
                    elif op == 12:
                        s = pc.start_round(d, pc.party.version if rng.random() < .8 else 0)
                        if rng.random() < .8:
                            pc.launch_accepted(s.id)
                    elif op == 10:
                        old = pc.begin_switch(d, rng.choice(['bluff', 'bomber']),
                                              pc.party.version if rng.random() < .8 else 0)
                        if rng.random() < .8:
                            pc.end_confirmed(old.id, rng.random() < .8)
                            s = pc.launch_pending()
                            if s and rng.random() < .8:
                                pc.launch_accepted(s.id)
                    else:
                        pc.tick()
                except Refused:
                    pass
                party = pc.party
                if party.id != party_id:
                    party_id, version, nav = party.id, party.version, party.nav['seq']
                self.assertGreaterEqual(party.version, version, seed)
                self.assertGreaterEqual(party.nav['seq'], nav, seed)
                version, nav = party.version, party.nav['seq']
                if pc._live_session() is not None and pc._live_session().state == core.ACTIVE:
                    # nav never points anyone at a different game than the one on
                    self.assertEqual(party.nav['session'], pc._live_session().id, seed)
                if party.host_id is not None:
                    self.assertFalse(party.members[party.host_id].left, seed)
                live = pc._live_session()
                if live is not None:
                    self.assertIs(live, party.session)
                    self.assertIn(live.state, (core.SETUP, core.LAUNCHING, core.ACTIVE, core.ENDING))
                if live is not None and live.state == core.SETUP:
                    self.assertEqual(live.participants, {}, seed)       # nobody seated in setup
                if live is not None and live.pregame and live.state != core.SETUP:
                    players = [p for p in live.participants.values() if p.role == 'player']
                    self.assertLessEqual(len(players), live.max_players, seed)
                ids = [p.id for p in (party.session.participants.values() if party.session else [])]
                self.assertEqual(len(ids), len(set(ids)), seed)


class HostLobby(unittest.TestCase):
    """The Party's own way out of a game (begin_lobby): the host brings everyone back to Party
    Home from wherever the party is, and nothing is asked of the game's page. Found at the first
    playtest on a phone (2026-10-13): a game page that could not be used left the party on it."""

    def setUp(self):
        self.pc, self.clock = make([PREGAME, BOMBER])
        self.a = self.pc.join('device-a', 'Ana')
        self.b = self.pc.join('device-b', 'Ben')

    def v(self):
        return self.pc.party.version

    def at(self, device='device-b'):
        loc = self.pc.view(device)['location']
        return loc['at'], loc['game']

    def round(self, game='bomber'):
        s = self.pc.launch('device-a', game, self.v())
        if game == 'bluff':
            self.pc.choose('device-a', 'player')
            self.pc.choose('device-b', 'player')
            self.pc.start_round('device-a', self.v())
        self.pc.launch_accepted(s.id)
        return s

    def refused(self, code, fn, *args):
        with self.assertRaises(Refused) as e:
            fn(*args)
        self.assertEqual(e.exception.code, code)

    def test_a_game_that_crashed_and_never_answers_holds_nobody(self):
        s = self.round()
        self.assertEqual(self.pc.participant_for('device-b', 'bomber')[0], s)
        got, left = self.pc.begin_lobby('device-a', self.v())
        self.assertEqual((got, left, self.at(), self.at('device-a')),
                         (s, 'end', ('home', None), ('home', None)))    # at once, before the game is asked
        self.refused('no_game', self.pc.participant_for, 'device-b', 'bomber')   # no ticket to a round that is over
        self.refused('busy', self.pc.launch, 'device-a', 'bomber', self.v())     # nothing beside a game still ending
        self.clock.advance(core.END_TIMEOUT)
        self.pc.tick()                                                  # the game never confirmed
        view = self.pc.view('device-b')
        self.assertEqual((view['state'], view['session']['outcome'], s.game_confirmed_end),
                         ('lobby', 'ended_by_host', False))
        self.assertFalse(self.pc.end_confirmed(s.id, True))             # a late answer changes nothing
        self.refused('stale_session', self.pc.game_reported_end, s.id, 'completed')
        nxt = self.round()                                              # and the party plays on
        self.assertNotEqual(nxt.id, s.id)
        self.assertEqual((self.at(), self.pc.party.session), (('game', 'bomber'), nxt))

    def test_from_held_results_the_result_is_kept_and_no_ticket_is_needed(self):
        s = self.round()
        self.pc.game_reported_end(s.id, 'completed')
        self.refused('no_game', self.pc.participant_for, 'device-a', 'bomber')   # a reloaded page has no seat
        for _ in range(40):                                             # an hour: nothing moves by itself
            self.clock.advance(90)
            self.pc.touch('device-a')
            self.pc.touch('device-b')
            self.pc.tick()
        self.assertEqual(self.at(), ('results', 'bomber'))
        self.refused('not_host', self.pc.begin_lobby, 'device-b', self.v())
        self.assertEqual(self.at(), ('results', 'bomber'))
        got, left = self.pc.begin_lobby('device-a', self.v())
        self.assertEqual((got, left, self.at()), (s, 'release', ('home', None)))
        self.assertEqual((s.state, s.outcome), (core.ENDED, 'completed'))        # the round's own end stands
        self.refused('no_game', self.pc.begin_lobby, 'device-a', self.v())       # home already: nothing to leave
        self.refused('no_game', self.pc.participant_for, 'device-b', 'bomber')

    def test_only_the_host_now_and_only_on_the_view_they_saw(self):
        s = self.round()
        self.refused('not_host', self.pc.begin_lobby, 'device-b', self.v())
        self.refused('not_member', self.pc.begin_lobby, 'device-x', self.v())
        self.refused('stale', self.pc.begin_lobby, 'device-a', self.v() - 1)
        self.pc.transfer_host('device-a', self.b.id, self.v())           # Ana hands over
        self.refused('not_host', self.pc.begin_lobby, 'device-a', self.v())      # a former host is nobody special
        self.assertEqual((self.at(), s.state), (('game', 'bomber'), core.ACTIVE))
        self.pc.begin_lobby('device-b', self.v())
        self.assertEqual(self.at('device-a'), ('home', None))

    def test_a_host_who_left_cannot_bring_the_party_back_and_the_next_one_can(self):
        self.round()
        self.pc.game_reported_end(self.pc.party.session.id, 'completed')
        old = self.v()
        self.pc.leave('device-a')
        self.assertEqual(self.pc.party.host_id, self.b.id)
        for version in (old, self.v()):
            self.refused('not_member', self.pc.begin_lobby, 'device-a', version)
        self.assertEqual(self.at(), ('results', 'bomber'))
        self.pc.begin_lobby('device-b', self.v())
        self.assertEqual(self.at(), ('home', None))

    def test_a_round_being_set_up_or_starting_is_closed_here(self):
        s = self.pc.launch('device-a', 'bluff', self.v())                # setup
        self.assertEqual(self.pc.begin_lobby('device-a', self.v()), (s, None))
        self.assertEqual((self.at(), s.state), (('home', None), core.ENDED))
        s = self.pc.launch('device-a', 'bomber', self.v())               # launching: the game has not answered
        self.assertEqual(self.pc.begin_lobby('device-a', self.v()), (s, None))
        self.assertEqual((s.state, s.outcome), (core.ENDED, 'launch_failed'))
        self.assertFalse(self.pc.launch_accepted(s.id))                  # the runtime that comes up late is stopped

    def test_play_again_is_a_new_round_and_it_can_be_left_too(self):
        first = self.round()
        self.pc.game_reported_end(first.id, 'completed')
        again = self.round()                                            # Play again, from the results
        self.assertEqual((self.at(), again.id != first.id), (('game', 'bomber'), True))
        got, left = self.pc.begin_lobby('device-a', self.v())
        self.assertEqual((got, left, self.at()), (again, 'end', ('home', None)))
        self.pc.end_confirmed(again.id, True)
        self.assertEqual((self.pc.view('device-b')['state'], self.pc.party.session), ('lobby', again))
        third = self.round()
        self.assertEqual(self.pc.participant_for('device-b', 'bomber')[0], third)

    def test_a_switch_under_way_is_called_off(self):
        s = self.round()
        self.pc.begin_switch('device-a', 'bluff', self.v())
        self.assertEqual(self.at(), ('game', 'bomber'))                  # ending, the next game pending
        self.assertEqual(self.pc.begin_lobby('device-a', self.v()), (s, None))
        self.assertEqual((self.at(), self.pc.party.pending), (('home', None), None))
        self.pc.end_confirmed(s.id, True)                                # the switch's own end arrives
        self.assertIsNone(self.pc.launch_pending())                      # and opens nothing
        self.assertEqual((self.at(), self.pc.view('device-a')['state']), (('home', None), 'lobby'))



class QuitAndSpectate(unittest.TestCase):
    """AVR-132: the host gives up hosting and watches, at a boundary Party Core already has (a
    round being set up, a finished round's results); never under a running round."""

    def setUp(self):
        self.pc, self.clock = make([PREGAME, BOMBER])
        self.a = self.pc.join('device-a', 'Ana')
        self.b = self.pc.join('device-b', 'Ben')
        self.c = self.pc.join('device-c', 'Cy')

    def v(self):
        return self.pc.party.version

    def at(self):
        loc = self.pc.view('device-b')['location']
        return loc['at'], loc['game'], loc['session']

    def refused(self, code, fn, *args):
        with self.assertRaises(Refused) as e:
            fn(*args)
        self.assertEqual(e.exception.code, code)

    def host_device(self):
        return self.pc.party.members[self.pc.party.host_id].device_id

    def round(self):
        s = self.pc.launch(self.host_device(), 'bomber', self.v())       # starts directly, no setup
        self.pc.launch_accepted(s.id)
        return s

    def test_during_setup_the_host_watches_and_the_next_one_hosts_at_once(self):
        s = self.pc.launch('device-a', 'bluff', self.v())
        self.pc.choose('device-a', 'player')
        self.pc.choose('device-b', 'player')
        before = self.at()
        nxt = self.pc.quit_and_spectate('device-a', self.v())
        self.assertEqual((nxt, self.pc.party.host_id), (self.b, self.b.id))      # the earliest-joined who is here
        self.assertEqual(s.choices, {self.a.id: 'spectator', self.b.id: 'player'})   # Ben's choice untouched
        self.assertEqual((self.at(), s.state), (before, core.SETUP))             # nothing else moved
        view = self.pc.view('device-a')
        self.assertEqual((view['me']['host'], view['me']['name'], view['session']['setup']['mine']),
                         (False, 'Ana', 'spectator'))                            # still a member
        self.pc.choose('device-c', 'player')
        self.pc.start_round('device-b', self.v())                               # the new host starts
        self.assertEqual({m: p.role for m, p in s.participants.items()},
                         {self.b.id: 'player', self.c.id: 'player', self.a.id: 'spectator'})

    def test_at_results_the_former_host_watches_the_next_round_and_only_that_one(self):
        first = self.round()
        self.pc.game_reported_end(first.id, 'completed')
        before = self.at()
        self.pc.quit_and_spectate('device-a', self.v())
        self.assertEqual((self.at(), first.outcome, self.pc.party.host_id), (before, 'completed', self.b.id))
        self.assertTrue(self.pc.view('device-a')['me']['watch_next'])
        again = self.round()                                                    # Ben: Play again
        self.assertEqual((again.participants[self.a.id].role, again.participants[self.b.id].role),
                         ('spectator', 'player'))
        self.assertFalse(self.pc.view('device-a')['me']['watch_next'])
        self.pc.begin_end('device-b', self.v())
        self.pc.end_confirmed(again.id, True)
        third = self.round()                                                    # the round after: a player again
        self.assertEqual(third.participants[self.a.id].role, 'player')

    def test_at_results_before_a_set_up_game_the_watch_is_preset_and_still_their_own(self):
        first = self.round()
        self.pc.game_reported_end(first.id, 'completed')
        self.pc.quit_and_spectate('device-a', self.v())
        s = self.pc.launch('device-b', 'bluff', self.v())
        self.assertEqual(s.choices, {self.a.id: 'spectator'})
        self.assertFalse(self.a.watch_next)
        self.pc.choose('device-a', 'player')                                    # they may change their mind
        self.assertEqual(s.choices[self.a.id], 'player')

    def test_refused_mid_round_at_home_and_while_a_round_starts(self):
        self.refused('no_game', self.pc.quit_and_spectate, 'device-a', self.v())
        s = self.pc.launch('device-a', 'bomber', self.v())                      # launching: the roster is sent
        self.refused('round_on', self.pc.quit_and_spectate, 'device-a', self.v())
        self.pc.launch_accepted(s.id)
        self.refused('round_on', self.pc.quit_and_spectate, 'device-a', self.v())
        self.assertEqual((self.pc.party.host_id, s.participants[self.a.id].role), (self.a.id, 'player'))
        self.pc.begin_end('device-a', self.v())                                 # ending: the game has not stopped
        self.refused('round_on', self.pc.quit_and_spectate, 'device-a', self.v())
        self.pc.end_confirmed(s.id, True)
        self.refused('no_game', self.pc.quit_and_spectate, 'device-a', self.v())   # home: nothing to watch

    def test_only_the_host_on_the_view_they_saw_and_never_without_a_successor(self):
        s = self.pc.launch('device-a', 'bluff', self.v())
        self.refused('not_host', self.pc.quit_and_spectate, 'device-b', self.v())
        self.refused('stale', self.pc.quit_and_spectate, 'device-a', self.v() - 1)
        self.pc.leave('device-b')
        self.pc.leave('device-c')
        self.refused('no_successor', self.pc.quit_and_spectate, 'device-a', self.v())
        self.assertEqual((self.pc.party.host_id, s.choices), (self.a.id, {}))
        self.pc.reconnect('device-b', 'Ben')
        self.clock.advance(core.LIVE_WINDOW + 1)                                # Ben is away now
        self.pc.touch('device-a')
        self.refused('no_successor', self.pc.quit_and_spectate, 'device-a', self.v())

    def test_coming_back_never_restores_hosting_and_host_loss_is_still_its_own_rule(self):
        s = self.pc.launch('device-a', 'bluff', self.v())
        self.pc.quit_and_spectate('device-a', self.v())
        self.pc.join('device-a', 'Ana')                                         # a reload, a rejoin
        self.pc.touch('device-a')
        self.assertEqual(self.pc.party.host_id, self.b.id)
        self.pc.leave('device-a')
        self.pc.reconnect('device-a', 'Ana')                                    # left and came back
        self.assertEqual(self.pc.party.host_id, self.b.id)
        # the new host going quiet still passes hosting on by the timer, as before
        self.clock.advance(core.LIVE_WINDOW + core.HOST_GRACE + 1)
        self.pc.touch('device-a')
        self.pc.touch('device-c')
        self.pc.tick()
        self.assertEqual(self.pc.party.host_id, self.a.id)                      # earliest-joined who is here
        self.assertEqual(s.state, core.SETUP)

if __name__ == '__main__':
    unittest.main()


class DeclaredLifecycleBounds(unittest.TestCase):
    """AVR-260: a game's contract may state how long it needs to start and to stop. Party Core
    uses the value inside its own limits, the limit outside them, and today's constants when the
    contract says nothing."""

    def session(self, **declared):
        pc, clock = make([dict(BLUFF, **declared)])
        pc.join('device-a', 'Ana')
        pc.join('device-b', 'Ben')
        return pc, clock, pc.launch('device-a', 'bluff', pc.party.version)

    def test_no_declaration_behaves_exactly_as_before(self):
        _, _, s = self.session()
        self.assertEqual((s.launch_timeout, s.end_timeout), (core.LAUNCH_TIMEOUT, core.END_TIMEOUT))

    def test_a_declared_launch_bound_is_waited_for_and_no_longer(self):
        pc, clock, s = self.session(launch_timeout_s=120)
        clock.advance(core.LAUNCH_TIMEOUT + 1)
        pc.tick()
        self.assertEqual(s.state, core.LAUNCHING)              # the global 60 s no longer applies
        clock.advance(120 - core.LAUNCH_TIMEOUT)
        pc.tick()
        self.assertEqual(s.outcome, 'launch_failed')

    def test_a_declared_end_bound_is_waited_for(self):
        pc, clock, s = self.session(end_timeout_s=30)
        pc.launch_accepted(s.id)
        pc.begin_end('device-a', pc.party.version)
        clock.advance(core.END_TIMEOUT + 1)
        pc.tick()
        self.assertEqual(s.state, core.ENDING)
        clock.advance(30 - core.END_TIMEOUT)
        pc.tick()
        self.assertEqual((s.state, s.game_confirmed_end), (core.ENDED, False))

    def test_out_of_range_declarations_are_clamped_to_party_cores_limits(self):
        for declared, expected in (({'launch_timeout_s': 1}, (core.LAUNCH_BOUNDS[0], core.END_TIMEOUT)),
                                   ({'launch_timeout_s': 3600}, (core.LAUNCH_BOUNDS[1], core.END_TIMEOUT)),
                                   ({'end_timeout_s': 0.5}, (core.LAUNCH_TIMEOUT, core.END_BOUNDS[0])),
                                   ({'end_timeout_s': 999}, (core.LAUNCH_TIMEOUT, core.END_BOUNDS[1]))):
            with self.subTest(declared=declared):
                _, _, s = self.session(**declared)
                self.assertEqual((s.launch_timeout, s.end_timeout), expected)

    def test_the_end_limit_keeps_the_links_margin(self):
        from avrana.party import sessions
        self.assertGreater(core.END_BOUNDS[0], sessions.END_LINK_MARGIN)
