"""Scenario and fuzz tests for the offline party model (stdlib only; no network, no Pi).
    python experiments/party-model/test_party_model.py
"""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from party_model import (HOST_GRACE, LAUNCH_TIMEOUT, PARTY_IDLE, SEAT_GRACE,  # noqa: E402
                         SEAT_RELEASE, TABLE_ABANDON, Appliance, Refused, _hash)

BLUFF = {'id': 'bluff', 'max_players': 6, 'late_join': 'spectator_only'}
TRIVIA = {'id': 'trivia', 'max_players': 8, 'late_join': 'supported'}
CARDS = {'id': 'cards', 'max_players': 6, 'late_join': 'next_round'}
BOMBER = {'id': 'ps1-bomberman', 'max_players': 4, 'late_join': 'supported',
          'launch': 'service', 'open_seat': True}
WORMS = {'id': 'ps1-worms', 'max_players': 1, 'late_join': 'spectator_only', 'launch': 'service'}
GAMES = [BLUFF, TRIVIA, CARDS, BOMBER, WORMS]


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


def setup(n, **kw):
    clock = Clock()
    app = Appliance(clock, **kw)
    tokens = [app.issue_device() for _ in range(n)]
    people = [app.connect(t) for t in tokens]
    return app, app.party, clock, tokens, people


def started(party, token, manifest):
    """Select a game and, for service games, report it ready."""
    launch = party.select_game(token, manifest)
    if party.state == 'launching':
        party.game_ready(launch)
    return party.game


def texts(party):
    return [d['text'] for _, kind, d, _ in party.events if kind == 'system_message']


class JoinAndIdentity(unittest.TestCase):
    def test_guests_numbered_first_is_host(self):
        for n in range(2, 9):
            _, party, _, _, people = setup(n)
            self.assertEqual([p.persona for p in people], [f'Player {i}' for i in range(1, n + 1)])
            self.assertEqual(party.host_id, people[0].id)

    def test_fabricated_token_gets_nothing(self):
        app, party, _, _, _ = setup(3)
        for call in (lambda: app.connect('made-up'), lambda: party.vote('made-up', 'r', 'x')):
            with self.assertRaises(Refused):
                call()

    def test_rename_is_display_only(self):
        _, party, _, tokens, people = setup(3)
        party.rename(tokens[2], 'Megan')
        self.assertEqual(people[2].persona, 'Megan')
        party.rename(tokens[1], people[0].persona)           # copying the host's name...
        self.assertEqual(people[1].persona, 'Player 1 2')     # ...is disambiguated
        with self.assertRaises(Refused):                      # ...and grants no host power
            party.transfer_host(tokens[1], people[1].id)

    def test_names_cannot_impersonate_system_or_each_other(self):
        _, party, _, tokens, people = setup(3)
        spoofs = ['SYSTEM', 'admin', '  Host ', '', 'SYSTEM:', 'System Message', 'Sуstem',
                  'SYS​TEM', 'ＳＹＳＴＥＭ', 'Avrana Party',
                  'x' * 17]
        for bad in spoofs:
            with self.assertRaises(Refused, msg=repr(bad)):
                party.rename(tokens[1], bad)
        party.rename(tokens[1], '‮METSYS')               # a bidi override is stripped...
        self.assertEqual(people[1].persona, 'METSYS')          # ...so it can't display as SYSTEM
        for good, shown in [('José', 'José'), ('Zoë  Q', 'Zoë Q'), ('たなか太郎', 'たなか太郎'),
                            ('megan', 'megan')]:
            party.rename(tokens[1], good)
            self.assertEqual(people[1].persona, shown)
        party.rename(tokens[2], 'Megan')
        self.assertEqual(people[2].persona, 'Megan 2')         # case-insensitive duplicate

    def test_ids_and_credentials_are_distinct(self):
        _, party, _, tokens, people = setup(2)
        game = started(party, tokens[0], BLUFF)
        values = set(tokens) | {p.id for p in people} | {p.device_id for p in people}
        values |= {s.id for s in game.seats.values()} | {s.game_key for s in game.seats.values()}
        values |= {party.id, game.id}
        self.assertEqual(len(values), 12)

    def test_screen_never_becomes_host_or_seat_or_voter(self):
        app, party, clock, _, _ = setup(0)
        tv = app.issue_device()
        app.connect(tv, kind='screen')
        self.assertIsNone(party.host_id)
        phone = app.issue_device()
        p = app.connect(phone)
        self.assertEqual(party.host_id, p.id)
        game = started(party, phone, BLUFF)
        self.assertEqual(list(game.seats), [p.id])
        party.open_vote(phone, 'r', spectators_vote=True)
        with self.assertRaises(Refused):
            party.vote(tv, 'r', 'x')


class Host(unittest.TestCase):
    def test_reconnect_within_grace_keeps_host(self):
        _, party, clock, tokens, people = setup(3)
        party.drop(tokens[0])
        clock.advance(HOST_GRACE - 1)
        party.tick()
        party.connect(tokens[0])
        clock.advance(HOST_GRACE)
        party.tick()
        self.assertEqual(party.host_id, people[0].id)

    def test_succession_and_no_takeback(self):
        _, party, clock, tokens, people = setup(4)
        party.drop(tokens[0])
        clock.advance(HOST_GRACE)
        party.tick()
        self.assertEqual(party.host_id, people[1].id)
        self.assertIn('Player 2 is now Host.', texts(party))
        party.connect(tokens[0])
        self.assertEqual(party.host_id, people[1].id)
        self.assertFalse(party.what_is_my_party_doing(tokens[0])['is_host'])

    def test_disconnected_host_cannot_act(self):
        _, party, _, tokens, _ = setup(2)
        party.drop(tokens[0])
        with self.assertRaises(Refused):
            party.select_game(tokens[0], BLUFF)

    def test_random_succession_picks_connected_player(self):
        _, party, clock, tokens, people = setup(6, succession='random', rng=random.Random(7))
        party.drop(tokens[0])
        party.drop(tokens[3])
        clock.advance(HOST_GRACE)
        party.tick()
        self.assertIn(party.host_id, {people[i].id for i in (1, 2, 4, 5)})

    def test_everyone_gone_then_first_back_is_host(self):
        _, party, clock, tokens, people = setup(3)
        for t in tokens:
            party.drop(t)
        clock.advance(HOST_GRACE)
        party.tick()
        self.assertIsNone(party.host_id)
        party.connect(tokens[2])
        self.assertEqual(party.host_id, people[2].id)

    def test_only_host_acts_and_transfer_rules(self):
        _, party, _, tokens, people = setup(3)
        with self.assertRaises(Refused):
            party.select_game(tokens[1], BLUFF)
        party.transfer_host(tokens[0], people[2].id)
        with self.assertRaises(Refused):
            party.transfer_host(tokens[0], people[0].id)
        party.drop(tokens[1])
        with self.assertRaises(Refused):
            party.transfer_host(tokens[2], people[1].id)     # target offline

    def test_host_leaves_immediate_succession_skipping_departed(self):
        _, party, _, tokens, people = setup(3)
        party.leave(tokens[1])                                # a former member who left
        party.leave(tokens[0])                                # host leaves explicitly
        self.assertEqual(party.host_id, people[2].id)         # not the departed Player 2

    def test_lone_host_leaves_vacant_then_spectator_screen_does_not_take_it(self):
        app, party, _, tokens, _ = setup(1)
        tv = app.issue_device()
        app.connect(tv, kind='screen')
        party.leave(tokens[0])
        self.assertIsNone(party.host_id)

    def test_stale_host_request_refused(self):
        _, party, _, tokens, _ = setup(2)
        seen = party.version
        party.rename(tokens[1], 'Nick')                       # something changed meanwhile
        with self.assertRaises(Refused):
            party.select_game(tokens[0], BLUFF, if_version=seen)


class Launch(unittest.TestCase):
    def test_service_game_navigates_only_when_ready(self):
        _, party, _, tokens, _ = setup(3)
        launch = party.select_game(tokens[0], BOMBER)
        self.assertEqual((party.state, party.nav_seq, party.nav_target), ('launching', 0, 'home'))
        late = party.appliance.issue_device()
        party.appliance.connect(late)                         # late join during launch = lobby
        self.assertTrue(party.game_ready(launch))
        self.assertEqual((party.state, party.nav_seq, party.nav_target), ('in_game', 1, 'ps1-bomberman'))
        self.assertIsNotNone(party.what_is_my_party_doing(late)['seat_slot'])

    def test_failed_launch_keeps_navigation(self):
        _, party, _, tokens, _ = setup(2)
        launch = party.select_game(tokens[0], BOMBER)
        self.assertTrue(party.game_failed(launch, 'power gate'))
        self.assertEqual((party.state, party.nav_seq), ('lobby', 0))
        self.assertIn('ps1-bomberman could not start (power gate).', texts(party))

    def test_stale_ready_ignored_and_double_select_refused(self):
        _, party, _, tokens, _ = setup(2)
        first = party.select_game(tokens[0], BOMBER)
        with self.assertRaises(Refused):
            party.select_game(tokens[0], WORMS)
        party.cancel_launch(tokens[0])
        second = party.select_game(tokens[0], WORMS)
        self.assertFalse(party.game_ready(first))             # the cancelled launch
        self.assertTrue(party.game_ready(second))
        self.assertEqual(party.nav_target, 'ps1-worms')

    def test_host_leaving_mid_launch_does_not_stop_it(self):
        _, party, _, tokens, people = setup(3)
        launch = party.select_game(tokens[0], BOMBER)
        party.leave(tokens[0])
        self.assertEqual(party.host_id, people[1].id)
        self.assertTrue(party.game_ready(launch))

    def test_launch_timeout(self):
        _, party, clock, tokens, _ = setup(2)
        party.select_game(tokens[0], BOMBER)
        clock.advance(LAUNCH_TIMEOUT)
        party.tick()
        self.assertEqual(party.state, 'lobby')


class Seats(unittest.TestCase):
    def test_transition_new_seats_same_seating(self):
        _, party, _, tokens, _ = setup(4)
        g1 = started(party, tokens[0], BLUFF)
        slots1 = {pid: s.slot for pid, s in g1.seats.items()}
        ids1 = {s.id for s in g1.seats.values()}
        party.end_game(tokens[0])
        self.assertEqual((party.state, party.nav_target), ('intermission', 'home'))
        g2 = started(party, tokens[0], BOMBER)
        self.assertEqual({pid: s.slot for pid, s in g2.seats.items()}, slots1)
        self.assertFalse(ids1 & {s.id for s in g2.seats.values()})

    def test_select_during_game_ends_the_old_session_first(self):
        _, party, _, tokens, _ = setup(3)
        started(party, tokens[0], BLUFF)
        started(party, tokens[0], TRIVIA)
        kinds = [(k, d.get('outcome')) for _, k, d, _ in party.events if k.startswith('session_')]
        self.assertEqual(kinds, [('session_started', None), ('session_ended', 'switched'),
                                 ('session_started', None)])
        self.assertEqual(len(party.last_seating), 3)

    def test_extra_players_spectate(self):
        _, party, _, tokens, _ = setup(6)
        game = started(party, tokens[0], BOMBER)
        self.assertEqual(len(game.seats), 4)
        self.assertTrue(party.what_is_my_party_doing(tokens[5])['spectator'])

    def test_disconnect_neutral_away_reclaim(self):
        _, party, clock, tokens, people = setup(3)
        game = started(party, tokens[0], BLUFF)
        seat = game.seats[people[1].id]
        party.drop(tokens[1])
        self.assertTrue(seat.neutral_input)
        clock.advance(SEAT_GRACE)
        party.tick()
        self.assertEqual(seat.state, 'away')
        party.connect(tokens[1])
        self.assertIs(game.seats[people[1].id], seat)
        self.assertEqual(seat.state, 'occupied')

    def test_phone_asleep_through_game_change_keeps_a_seat(self):
        _, party, _, tokens, people = setup(3)
        party.drop(tokens[2])                                  # asleep, still in grace
        game = started(party, tokens[0], BLUFF)
        seat = game.seats[people[2].id]
        self.assertEqual(seat.state, 'disconnected')           # dealt, neutral until back
        party.connect(tokens[2])
        state = party.what_is_my_party_doing(tokens[2])
        self.assertEqual((state['target'], state['seat_slot']), ('bluff', seat.slot))

    def test_two_tabs_newest_owns_input(self):
        _, party, _, tokens, people = setup(2)
        game = started(party, tokens[0], BLUFF)
        first = party.input_connection(people[1].id)
        party.connect(tokens[1])                               # second tab
        second = party.input_connection(people[1].id)
        self.assertNotEqual(first, second)
        party.drop(tokens[1], conn=second)
        self.assertEqual(party.input_connection(people[1].id), first)
        self.assertEqual(game.seats[people[1].id].state, 'occupied')
        self.assertEqual(len(party.presences), 2)

    def test_late_join_policies(self):
        _, party, _, tokens, _ = setup(2)
        started(party, tokens[0], BLUFF)
        late = party.appliance.issue_device()
        party.appliance.connect(late)
        self.assertTrue(party.what_is_my_party_doing(late)['spectator'])
        with self.assertRaises(Refused):
            party.promote_spectator(tokens[0], party._presence_for(late).id)
        started(party, tokens[0], TRIVIA)
        late2 = party.appliance.issue_device()
        party.appliance.connect(late2)
        self.assertFalse(party.what_is_my_party_doing(late2)['spectator'])

    def test_next_round_and_promotion(self):
        _, party, _, tokens, _ = setup(2)
        started(party, tokens[0], CARDS)
        a = party.appliance.issue_device()
        party.appliance.connect(a)
        self.assertTrue(party.what_is_my_party_doing(a)['spectator'])
        party.next_round(tokens[0])
        self.assertFalse(party.what_is_my_party_doing(a)['spectator'])

    def test_promoting_a_disconnected_spectator_gives_a_neutral_seat(self):
        _, party, clock, tokens, _ = setup(4)
        started(party, tokens[0], {'id': 'duo', 'max_players': 3, 'late_join': 'supported'})
        spectator = party._presence_for(tokens[3])             # 4th player didn't fit
        party.drop(tokens[3])
        party.remove_seat(tokens[0], party._presence_for(tokens[2]).id)
        self.assertEqual(party.promote_spectator(tokens[0], spectator.id), 'seated')
        seat = party.game.seats[spectator.id]
        self.assertEqual(seat.state, 'disconnected')
        clock.advance(SEAT_GRACE)
        party.tick()
        self.assertEqual(seat.state, 'away')

    def test_next_round_seats_a_disconnected_queued_player_neutral(self):
        _, party, _, tokens, _ = setup(2)
        started(party, tokens[0], CARDS)
        a = party.appliance.issue_device()
        pa = party.appliance.connect(a)
        party.drop(a)
        party.next_round(tokens[0])
        self.assertEqual(party.game.seats[pa.id].state, 'disconnected')

    def test_released_seat_refilled_owner_returns_as_spectator(self):
        _, party, _, tokens, people = setup(3)
        game = started(party, tokens[0], {'id': 'trio', 'max_players': 2, 'late_join': 'supported'})
        old_key = game.seats[people[1].id].game_key
        party.drop(tokens[1])
        party.remove_seat(tokens[0], people[1].id)
        party.promote_spectator(tokens[0], people[2].id)
        self.assertNotEqual(game.seats[people[2].id].game_key, old_key)
        party.connect(tokens[1])
        self.assertTrue(party.what_is_my_party_doing(tokens[1])['spectator'])

    def test_open_seat_game_releases_long_away_seats(self):
        _, party, clock, tokens, people = setup(3)
        game = started(party, tokens[0], BOMBER)
        party.drop(tokens[2])
        for step in (SEAT_GRACE, SEAT_RELEASE):
            clock.advance(step)
            party.tick()
        self.assertNotIn(people[2].id, game.seats)

    def test_empty_table_is_abandoned_with_seating_saved(self):
        _, party, clock, tokens, people = setup(1)
        started(party, tokens[0], BLUFF)
        party.drop(tokens[0])
        for _ in range(12):
            clock.advance(TABLE_ABANDON / 10)
            party.tick()
        self.assertEqual((party.state, party.last_seating), ('intermission', [people[0].id]))
        self.assertIn(('session_ended', 'abandoned'),
                      [(k, d.get('outcome')) for _, k, d, _ in party.events])

    def test_crash_returns_home_with_seating(self):
        _, party, _, tokens, _ = setup(2)
        started(party, tokens[0], BOMBER)
        party.game_crashed()
        self.assertEqual((party.state, len(party.last_seating)), ('intermission', 2))


class Voting(unittest.TestCase):
    def test_refresh_and_tabs_cannot_double_vote(self):
        _, party, _, tokens, _ = setup(3)
        party.open_vote(tokens[0], 'next', spectators_vote=True)
        party.vote(tokens[1], 'next', 'bomberman')
        party.drop(tokens[1])
        party.connect(tokens[1])
        party.connect(tokens[1])
        party.vote(tokens[1], 'next', 'worms')
        self.assertEqual(party.tally('next'), {'worms': 1})

    def test_eligibility_fixed_when_round_opens(self):
        _, party, _, tokens, _ = setup(2)
        party.open_vote(tokens[0], 'next')
        late = party.appliance.issue_device()
        party.appliance.connect(late)
        with self.assertRaises(Refused):
            party.vote(late, 'next', 'bluff')

    def test_spectators_excluded_by_default_early_completion(self):
        _, party, _, tokens, _ = setup(6)
        started(party, tokens[0], BOMBER)
        party.open_vote(tokens[0], 'rematch')
        with self.assertRaises(Refused):
            party.vote(tokens[5], 'rematch', 'yes')
        for t in tokens[:4]:
            self.assertFalse(party.vote_complete('rematch'))
            party.vote(t, 'rematch', 'yes')
        self.assertTrue(party.vote_complete('rematch'))

    def test_gone_voter_does_not_block_and_deadline_closes(self):
        _, party, clock, tokens, _ = setup(3)
        party.open_vote(tokens[0], 'next', seconds=30)
        party.vote(tokens[0], 'next', 'a')
        party.vote(tokens[1], 'next', 'a')
        party.drop(tokens[2])
        self.assertTrue(party.vote_complete('next'))            # early: all present voted
        party.open_vote(tokens[0], 'r2', seconds=30)
        with self.assertRaises(Refused):
            party.open_vote(tokens[0], 'r2')                    # reopening a live round
        clock.advance(30)
        party.tick()
        self.assertTrue(party.vote_complete('r2'))
        with self.assertRaises(Refused):
            party.vote(tokens[0], 'r2', 'late')


class Profiles(unittest.TestCase):
    def test_same_profile_on_two_devices(self):
        app, party, _, tokens, people = setup(2)
        profile = party.create_profile(tokens[1])
        game = started(party, tokens[0], BLUFF)
        seat = game.seats[people[1].id]
        old_key = seat.game_key
        new_phone = app.issue_device()
        with self.assertRaises(Refused):
            party.claim_profile(new_phone, profile)
        app.profiles[profile]['trusted'].add(app.devices[_hash(new_phone)])   # e.g. QR pairing
        moved = party.claim_profile(new_phone, profile)
        self.assertIs(moved, people[1])
        self.assertIs(game.seats[moved.id], seat)
        self.assertNotEqual(seat.game_key, old_key)             # the old phone's key is dead
        with self.assertRaises(Refused):
            party.what_is_my_party_doing(tokens[1])

    def test_claim_into_hostless_party_assigns_host(self):
        app, party, clock, tokens, people = setup(1)
        profile = party.create_profile(tokens[0])
        party.drop(tokens[0])
        clock.advance(HOST_GRACE)
        party.tick()
        self.assertIsNone(party.host_id)
        new_phone = app.issue_device()
        app.profiles[profile]['trusted'].add(app.devices[_hash(new_phone)])
        party.claim_profile(new_phone, profile)
        self.assertEqual(party.host_id, people[0].id)


class PartyEnd(unittest.TestCase):
    def test_ended_party_refuses_every_change(self):
        _, party, _, tokens, people = setup(3)
        with self.assertRaises(Refused):
            party.end_party(tokens[1])
        party.end_party(tokens[0])
        calls = [lambda: party.select_game(tokens[0], BLUFF), lambda: party.rename(tokens[1], 'x'),
                 lambda: party.open_vote(tokens[0], 'r'), lambda: party.transfer_host(tokens[0], people[1].id),
                 lambda: party.connect(tokens[1]), lambda: party.drop(tokens[1]),
                 lambda: party.leave(tokens[2]), lambda: party.claim_profile(tokens[1], 'p')]
        for call in calls:
            with self.assertRaises(Refused):
                call()

    def test_idle_party_ends_and_next_connect_starts_new_party(self):
        app, party, clock, tokens, people = setup(2)
        for t in tokens:
            party.drop(t)
        clock.advance(PARTY_IDLE)
        app.tick()
        self.assertEqual(party.state, 'ended')
        again = app.connect(tokens[0])
        self.assertIsNot(app.party, party)
        self.assertEqual(again.device_id, people[0].device_id)  # the device outlives the party
        self.assertEqual(app.party.host_id, again.id)

    def test_kick_and_leave(self):
        app, party, _, tokens, people = setup(3)
        party.kick(tokens[0], people[2].id)
        with self.assertRaises(Refused):
            app.connect(tokens[2])
        party.leave(tokens[1])
        back = app.connect(tokens[1])                            # leaving is not a ban
        self.assertIs(back, people[1])
        self.assertFalse(back.left)


class ApplyTime(unittest.TestCase):
    """Deadlines hold when an operation is APPLIED, even if no background tick ran (Jerry review)."""

    def test_deadlines_enforced_at_apply_time(self):
        app, party, clock, tokens, people = setup(3)
        party.open_vote(tokens[0], 'r', seconds=10)
        clock.advance(10)
        with self.assertRaises(Refused):                  # no tick: the vote is closed anyway
            party.vote(tokens[1], 'r', 'a')
        launch = party.select_game(tokens[0], BOMBER)
        clock.advance(LAUNCH_TIMEOUT)
        self.assertFalse(party.game_ready(launch))        # a late ready cannot resurrect it
        self.assertEqual(party.state, 'lobby')
        party.drop(tokens[0])
        clock.advance(HOST_GRACE)
        app.connect(tokens[0])                            # succession applies before the reconnect
        self.assertEqual(party.host_id, people[1].id)
        with self.assertRaises(Refused):
            party.select_game(tokens[0], BLUFF)

    def test_timer_changes_bump_version(self):
        _, party, clock, tokens, _ = setup(2)
        started(party, tokens[0], BLUFF)
        party.drop(tokens[1])
        before = party.version
        clock.advance(SEAT_GRACE)
        party.tick()                                      # seat disconnected -> away
        self.assertGreater(party.version, before)
        party.open_vote(tokens[0], 'r', seconds=10)
        before = party.version
        clock.advance(10)
        party.tick()                                      # vote closes at its deadline
        self.assertTrue(party.votes['r']['closed'])
        self.assertGreater(party.version, before)
        before = party.version
        party.tick()                                      # nothing due: no spurious bump
        self.assertEqual(party.version, before)

    def test_table_abandon_counts_from_when_the_last_seat_emptied(self):
        _, party, clock, tokens, _ = setup(2)
        started(party, tokens[0], BLUFF)
        for t in tokens:
            party.drop(t)
        for _ in range(int(TABLE_ABANDON // 30) - 1):     # ticks along the way must not reset it
            clock.advance(30)
            party.tick()
        self.assertEqual(party.state, 'in_game')
        clock.advance(TABLE_ABANDON - clock.t + 1000.0)   # exactly TABLE_ABANDON after the drops
        party.tick()
        self.assertEqual(party.state, 'intermission')
        self.assertEqual(party.events[-1][1], 'session_ended')
        self.assertEqual(party.events[-1][2]['outcome'], 'abandoned')

    def test_screen_only_party_idles(self):
        app, _, clock, _, _ = setup(0)
        tv = app.issue_device()
        app.connect(tv, kind='screen')                    # a TV alone does not keep a party alive
        clock.advance(PARTY_IDLE)
        app.tick()
        self.assertEqual(app.party.state, 'ended')

    def test_observe_does_not_create_presence(self):
        app, party, _, tokens, _ = setup(1)
        visitor = app.issue_device()
        before = (dict(party.presences), party.version)
        seen = party.observe(visitor)                     # captive-portal WebView / page open
        self.assertEqual(seen['players'], 1)
        self.assertEqual(seen['host'], 'Player 1')
        self.assertEqual((dict(party.presences), party.version), before)
        with self.assertRaises(Refused):
            party.observe('made-up')

    def test_nav_is_keyed_by_party_and_seq(self):
        """nav_seq restarts in a new party, so a phone must key navigation on (party_id, nav_seq)."""
        app, party, clock, tokens, _ = setup(2)
        started(party, tokens[0], BLUFF)
        old = (party.id, party.nav_seq)
        party.end_party(tokens[0])
        app.connect(tokens[0])
        started(app.party, tokens[0], BLUFF)
        new = (app.party.id, app.party.nav_seq)
        self.assertEqual(new[1], old[1])                  # the counter alone would look "already seen"
        self.assertNotEqual(new, old)


class ProfileOwnership(unittest.TestCase):
    def test_profile_single_live_presence(self):
        app, party, _, tokens, people = setup(3)
        profile = party.create_profile(tokens[1])
        party.leave(tokens[1])
        extra = app.issue_device()
        app.profiles[profile]['trusted'].add(app.devices[_hash(extra)])
        party.claim_profile(extra, profile)               # the profile moves on while phone 2 is gone
        back = app.connect(tokens[1])                     # A1: the old phone rejoins as a guest
        self.assertIsNone(back.profile_id)
        self.assertIn('profile_unlinked', [k for _, k, _, _ in party.events])
        live = [p for p in party.presences.values() if not p.left and p.profile_id == profile]
        self.assertEqual(len(live), 1)

    def test_presence_cannot_hold_two_profiles(self):
        app, party, _, tokens, _ = setup(1)
        first = party.create_profile(tokens[0])
        other_phone = app.issue_device()
        app.connect(other_phone)
        second = party.create_profile(other_phone)
        party.leave(other_phone)                          # `second` is free: only the A2 guard stops it
        app.profiles[second]['trusted'].add(app.devices[_hash(tokens[0])])
        with self.assertRaises(Refused):
            party.claim_profile(tokens[0], second)
        self.assertEqual(party._by_device(app.devices[_hash(tokens[0])]).profile_id, first)


class Fuzz(unittest.TestCase):
    """Random sequences of every operation; invariants after every step."""

    def check(self, party, after_tick, last):
        now = party.clock()
        self.assertGreaterEqual(party.nav_seq, last['nav'])
        self.assertGreaterEqual(party.version, last['ver'])
        last['nav'], last['ver'] = party.nav_seq, party.version
        devices = [p.device_id for p in party.presences.values()]
        self.assertEqual(len(devices), len(set(devices)))                 # one presence per device
        if party.host_id is not None:
            host = party.presences[party.host_id]
            self.assertTrue(host.eligible)                                  # never a TV or a leaver
            if after_tick and not host.connected:
                self.assertLess(now - host.disconnected_at, HOST_GRACE)
        elif party.state != 'ended':
            self.assertFalse([p for p in party.presences.values() if p.eligible and p.connected],
                             'connected player but no host')
        self.assertEqual(party.state == 'in_game', party.game is not None)
        self.assertEqual(party.nav_target, party.game.manifest['id'] if party.game else 'home')
        if party.game:
            seats = list(party.game.seats.values())
            self.assertEqual(len({s.slot for s in seats}), len(seats))
            self.assertLessEqual(len(seats), party.game.manifest['max_players'])
            self.assertEqual(len({s.id for s in seats}), len(seats))
            self.assertFalse(set(party.game.waiting) & set(party.game.seats))
            for s in seats:
                p = party.presences[s.presence_id]
                self.assertTrue(p.eligible)
                self.assertEqual(s.state == 'occupied', p.connected)        # occupied ⇔ connected
        for r in party.votes.values():
            self.assertLessEqual(set(r['ballots']), r['eligible'])
        profiles = [p.profile_id for p in party.presences.values() if p.profile_id and not p.left]
        self.assertEqual(len(profiles), len(set(profiles)))               # one live presence per profile

    def test_fuzz(self):
        steps = [5, 29, 30, 59, 60, 61, 300, PARTY_IDLE]
        for seed in range(300):
            rng = random.Random(seed)
            clock = Clock()
            app = Appliance(clock, succession=rng.choice(['earliest_joined', 'random']), rng=rng)
            tokens, last = [], {'nav': 0, 'ver': 0}
            for _ in range(150):
                party = app.party
                host = party.presences.get(party.host_id)
                host_tok = next((t for t in tokens if host and host.connected
                                 and app.devices[_hash(t)] == host.device_id), None)
                op, after_tick = rng.random(), False
                try:
                    if op < 0.10 or not tokens:
                        if len(tokens) < 8:
                            tokens.append(app.issue_device())
                            app.connect(tokens[-1], kind='screen' if rng.random() < 0.1 else 'player')
                    elif op < 0.25:
                        party.drop(rng.choice(tokens))
                    elif op < 0.40:
                        app.connect(rng.choice(tokens))
                    elif op < 0.50:
                        clock.advance(rng.choice(steps))
                        app.tick()
                        after_tick = True
                    elif op < 0.53:
                        party.leave(rng.choice(tokens))
                    elif op < 0.55:
                        tok = rng.choice(tokens)
                        prof = rng.choice(list(app.profiles) or ['x'])
                        if prof in app.profiles and rng.random() < 0.5:   # e.g. after QR pairing
                            app.profiles[prof]['trusted'].add(app.devices[_hash(tok)])
                        party.claim_profile(tok, prof)
                    elif op < 0.57:
                        party.create_profile(rng.choice(tokens))
                    elif party.launch and op < 0.62:
                        (party.game_ready if rng.random() < 0.7 else
                         lambda i: party.game_failed(i, 'x'))(party.launch['id'])
                    elif op < 0.64 and party.state == 'in_game':
                        party.game_crashed()
                    elif host_tok is None:
                        party.vote(rng.choice(tokens), 'r', rng.choice('abc'))
                    elif op < 0.72:
                        party.select_game(host_tok, rng.choice(GAMES))
                    elif op < 0.76:
                        party.end_game(host_tok)
                    elif op < 0.80:
                        party.transfer_host(host_tok, rng.choice(list(party.presences)))
                    elif op < 0.83:
                        party.promote_spectator(host_tok, rng.choice(list(party.presences)))
                    elif op < 0.85:
                        party.next_round(host_tok)
                    elif op < 0.87:
                        party.remove_seat(host_tok, rng.choice(list(party.presences)))
                    elif op < 0.88:
                        party.kick(host_tok, rng.choice(list(party.presences)))
                    elif op < 0.92:
                        party.open_vote(host_tok, 'r', seconds=rng.choice([10, 60]),
                                        spectators_vote=rng.random() < 0.5)
                    elif op < 0.995:
                        party.vote(rng.choice(tokens), 'r', rng.choice('abc'))
                    else:
                        party.end_party(host_tok)
                except Refused:
                    pass
                if app.party is not party:
                    last = {'nav': 0, 'ver': 0}
                self.check(app.party, after_tick, last)


if __name__ == '__main__':
    unittest.main(verbosity=1)
