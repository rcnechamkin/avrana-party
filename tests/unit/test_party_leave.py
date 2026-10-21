"""AVR-580: Leave Party is an intentional departure, Reconnect is the only way back.

Core rules run on a fake clock; the multi-client cases run over real HTTP (the same service the
phones use), with one cookie jar per "tab" or "phone". No browser, no Pi."""
import unittest

from avrana.party import core
from test_party_core import BLUFF, PREGAME, Clock, make, play
from test_party_service import ServiceCase


class LeaveIsIntentional(unittest.TestCase):
    def test_automatic_join_is_refused_after_leave_and_reconnect_is_the_way_back(self):
        pc, _ = make()
        a = pc.join('device-a', 'Ana')
        pc.join('device-b', 'Ben')
        pc.leave('device-a')
        for _ in range(3):                                   # a refresh, another tab, an app wake
            with self.assertRaises(core.Refused) as e:
                pc.join('device-a', 'Ana')
            self.assertEqual(e.exception.code, 'left_party')
        self.assertTrue(pc.view('device-a')['departed'])
        self.assertIsNone(pc.view('device-a')['me'])
        self.assertIs(pc.reconnect('device-a', 'Ana'), a)
        v = pc.view('device-a')
        self.assertFalse(v['departed'])
        self.assertEqual(v['me']['id'], a.id)

    def test_a_heartbeat_or_poll_never_brings_a_departed_device_back(self):
        pc, clock = make()
        pc.join('device-a', 'Ana')
        pc.join('device-b', 'Ben')
        pc.leave('device-b')
        for _ in range(5):
            clock.advance(10)
            self.assertIsNone(pc.touch('device-b'))
            pc.view('device-b')
        self.assertEqual([m['name'] for m in pc.view('device-a')['members']], ['Ana'])

    def test_leave_is_idempotent_and_needs_a_membership(self):
        pc, _ = make()
        with self.assertRaises(core.Refused) as e:
            pc.leave('device-x')                             # never joined
        self.assertEqual(e.exception.code, 'not_member')
        pc.join('device-a', 'Ana')
        pc.join('device-b', 'Ben')
        pc.leave('device-b')
        version = pc.party.version
        pc.leave('device-b')                                 # a retry, or the other tab
        self.assertEqual(pc.party.version, version)

    def test_a_departed_member_is_no_longer_connected_but_the_name_can_be_reused(self):
        pc, _ = make()
        pc.join('device-a', 'Ana')
        pc.join('device-b', 'Ben')
        pc.leave('device-b')
        self.assertEqual([m['name'] for m in pc.view('device-a')['members']], ['Ana'])
        self.assertEqual(pc.join('device-c', 'Ben').name, 'Ben')

    def test_leave_is_not_away_grace(self):
        pc, clock = make()
        pc.join('device-a', 'Ana')
        pc.join('device-b', 'Ben')
        clock.advance(core.LIVE_WINDOW + 1)                  # Ben only went quiet
        pc.touch('device-a')
        self.assertEqual(pc.view('device-a')['members'][1]['presence'], 'away')
        pc.touch('device-b')                                 # and comes back by himself
        self.assertEqual(pc.view('device-a')['members'][1]['presence'], 'here')
        pc.leave('device-b')                                 # leaving is the person's word
        clock.advance(1)
        pc.touch('device-b')
        self.assertTrue(pc.view('device-b')['departed'])

    def test_a_new_party_starts_without_the_opt_out(self):
        """The opt-out lives with the Party (memory-only). After a restart or idle end a device is
        simply unknown; the browser's own left marker is what keeps it out (see the web tests)."""
        pc, clock = make()
        pc.join('device-a', 'Ana')
        pc.leave('device-a')
        clock.advance(1)
        pc.tick()                                            # nobody here: the idle clock starts
        clock.advance(core.PARTY_IDLE + 1)
        pc.tick()                                            # ...and the Party ends
        self.assertIsNotNone(pc.join('device-a', 'Ana'))
        self.assertFalse(pc.view('device-a')['departed'])


class ReconnectDuringSetup(unittest.TestCase):
    def test_a_member_back_from_leave_chooses_again(self):
        pc, _ = make([PREGAME])
        pc.join('device-a', 'Ana')
        pc.join('device-b', 'Ben')
        s = pc.launch('device-a', 'bluff', pc.party.version)
        pc.choose('device-b', 'player')
        pc.leave('device-b')
        pc.reconnect('device-b', 'Ben')
        self.assertNotIn(pc._member_of('device-b').id, s.choices)
        self.assertEqual(pc.view('device-b')['session']['setup']['mine'], None)


class NonHostLeaveMovesNobody(unittest.TestCase):
    def table(self):
        pc, clock = make()
        pc.join('device-a', 'Ana')
        pc.join('device-b', 'Ben')
        pc.join('device-c', 'Cy')
        s = pc.launch('device-a', 'bluff', pc.party.version)
        pc.launch_accepted(s.id)
        return pc, clock, s

    def test_a_non_host_leave_changes_neither_the_session_nor_navigation_nor_the_host(self):
        pc, _, s = self.table()
        nav, host, loc = dict(pc.party.nav), pc.party.host_id, pc.location()
        pc.leave('device-b')
        self.assertEqual((pc.party.nav, pc.party.host_id, pc.location()), (nav, host, loc))
        self.assertEqual((pc.party.session, s.state), (s, core.ACTIVE))
        self.assertIn(pc._member_of('device-b').id, s.participants)     # the game owns the seat

    def test_a_departed_member_cannot_act_for_the_party_or_fetch_a_ticket(self):
        pc, _, _ = self.table()
        pc.leave('device-b')
        version = pc.party.version
        for call in (lambda: pc.begin_end('device-b', version), lambda: pc.go_home('device-b', version),
                     lambda: pc.begin_lobby('device-b', version), lambda: pc.transfer_host('device-b', 'x', version),
                     lambda: pc.quit_and_spectate('device-b', version), lambda: pc.participant_for('device-b'),
                     lambda: pc.choose('device-b', 'player'), lambda: pc.rename('device-b', 'Bob')):
            with self.assertRaises(core.Refused):
                call()
        self.assertEqual(pc.party.version, version)

    def test_reconnect_follows_the_current_location_not_a_stale_one(self):
        pc, _, s = self.table()
        pc.leave('device-b')
        pc.begin_end('device-a', pc.party.version)
        pc.end_confirmed(s.id, True)                         # the round ended while Ben was out
        pc.reconnect('device-b', 'Ben')
        v = pc.view('device-b')
        self.assertEqual((v['location']['at'], v['state']), ('home', 'lobby'))
        self.assertEqual(v['nav']['to'], 'home')


class HostLeave(unittest.TestCase):
    def test_leave_hands_hosting_to_the_next_member_here_and_the_old_host_keeps_nothing(self):
        pc, clock = make()
        a = pc.join('device-a', 'Ana')
        b = pc.join('device-b', 'Ben')
        pc.join('device-c', 'Cy')
        pc.leave('device-a')
        self.assertEqual(pc.party.host_id, b.id)             # earliest-joined who is here
        pc.reconnect('device-a', 'Ana')
        self.assertEqual(pc.party.host_id, b.id)             # coming back never restores the role
        version = pc.party.version
        with self.assertRaises(core.Refused) as e:
            pc.launch('device-a', 'bluff', version)          # no continued authority
        self.assertEqual(e.exception.code, 'not_host')

    def test_the_succession_skips_an_away_member_and_prefers_full_mode(self):
        pc, clock = make()
        pc.join('device-a', 'Ana')
        pc.join('device-b', 'Ben', mode=core.LIMITED)
        c = pc.join('device-c', 'Cy')
        clock.advance(core.LIVE_WINDOW + 1)
        pc.touch('device-a')
        pc.touch('device-b')
        pc.touch('device-c')
        pc.leave('device-a')
        self.assertEqual(pc.party.host_id, c.id)

    def test_host_leave_during_a_round_keeps_the_round_and_navigation(self):
        pc, _ = make()
        pc.join('device-a', 'Ana')
        b = pc.join('device-b', 'Ben')
        s = pc.launch('device-a', 'bluff', pc.party.version)
        pc.launch_accepted(s.id)
        nav = dict(pc.party.nav)
        pc.leave('device-a')
        self.assertEqual((pc.party.host_id, s.state, pc.party.nav), (b.id, core.ACTIVE, nav))
        self.assertEqual(pc.location()['at'], 'game')
        pc.begin_end('device-b', pc.party.version)           # the new Host is authoritative

    def test_the_leave_preview_names_the_consequence_before_confirmation(self):
        pc, clock = make()
        pc.join('device-a', 'Ana')
        pc.join('device-b', 'Ben')
        before = pc.party.version
        self.assertEqual(pc.view('device-a')['me']['leave'], {'host': True, 'successor': 'Ben', 'round': False})
        self.assertEqual(pc.view('device-b')['me']['leave'], {'host': False, 'successor': None, 'round': False})
        clock.advance(core.LIVE_WINDOW + 1)
        pc.touch('device-a')                                 # Ben is away: nobody could take over
        self.assertEqual(pc.view('device-a')['me']['leave'], {'host': True, 'successor': None, 'round': False})
        s = pc.launch('device-a', 'bluff', pc.party.version)
        pc.launch_accepted(s.id)
        self.assertTrue(pc.view('device-a')['me']['leave']['round'])
        self.assertGreater(pc.party.version, before)

    def test_no_eligible_successor_is_not_destructive(self):
        """OWNER DECISION (2026-10-18, keep vacant): the lone Host leaves mid-round. Nothing is
        ended and nothing is refused: the role is vacant, the round goes on, and the next member
        who arrives or is seen claims the role. TABLE_ABANDON (AVR-475) is the only clock."""
        pc, clock = make()
        a = pc.join('device-a', 'Ana')
        s = pc.launch('device-a', 'bluff', pc.party.version)
        pc.launch_accepted(s.id)
        nav = dict(pc.party.nav)
        pc.leave('device-a')
        self.assertIsNone(pc.party.host_id)
        self.assertEqual((s.state, pc.party.nav, pc.location()['at']), (core.ACTIVE, nav, 'game'))
        pc.join('device-b', 'Ben')
        self.assertEqual(pc.party.host_id, pc._member_of('device-b').id)    # claims the vacant role
        self.assertNotEqual(pc.party.host_id, a.id)

    def test_a_vacant_host_after_a_lone_leave_is_not_reclaimed_by_a_departed_device(self):
        pc, clock = make()
        pc.join('device-a', 'Ana')
        pc.leave('device-a')
        clock.advance(5)
        pc.touch('device-a')
        self.assertIsNone(pc.party.host_id)


class AbandonedRecoveryIsDistinct(unittest.TestCase):
    def test_everyone_leaving_a_round_still_ends_it_through_table_abandon(self):
        pc, clock = make()
        pc.join('device-a', 'Ana')
        pc.join('device-b', 'Ben')
        s = pc.launch('device-a', 'bluff', pc.party.version)
        pc.launch_accepted(s.id)
        play(pc, clock, 30, 'device-a', 'device-b')
        pc.leave('device-b')
        pc.leave('device-a')
        clock.advance(core.LIVE_WINDOW + core.TABLE_ABANDON + 1)
        pc.tick()
        self.assertEqual((s.state, s.outcome), (core.ENDED, 'abandoned'))
        self.assertEqual(pc.location()['at'], 'home')

    def test_a_silent_member_is_away_not_left_and_returns_without_reconnect(self):
        pc, clock = make()
        pc.join('device-a', 'Ana')
        pc.join('device-b', 'Ben')
        clock.advance(core.LIVE_WINDOW + 1)
        pc.touch('device-a')
        self.assertEqual(pc.view('device-a')['members'][1]['presence'], 'away')
        self.assertTrue(pc.join('device-b', 'Ben'))          # an automatic join still works


class QuitAndSpectateUnchanged(unittest.TestCase):
    def test_quit_and_spectate_keeps_membership_and_never_departs(self):
        pc, _ = make([PREGAME])
        a = pc.join('device-a', 'Ana')
        b = pc.join('device-b', 'Ben')
        pc.launch('device-a', 'bluff', pc.party.version)
        pc.quit_and_spectate('device-a', pc.party.version)
        v = pc.view('device-a')
        self.assertFalse(v['departed'])
        self.assertEqual((v['me']['id'], v['host']), (a.id, b.id))
        self.assertIsNotNone(pc.join('device-a', 'Ana'))     # still a member: automatic join is fine

    def test_quit_and_spectate_is_still_refused_mid_round(self):
        pc, _ = make()
        pc.join('device-a', 'Ana')
        pc.join('device-b', 'Ben')
        s = pc.launch('device-a', 'bluff', pc.party.version)
        pc.launch_accepted(s.id)
        with self.assertRaises(core.Refused) as e:
            pc.quit_and_spectate('device-a', pc.party.version)
        self.assertEqual(e.exception.code, 'round_on')


class OverHttp(ServiceCase):
    """Multi-client semantics: tabs of one phone share a cookie jar, phones do not."""

    def tab_of(self, phone):
        from test_party_service import Phone
        tab = Phone(self.port)
        tab.cookie, tab.cookie_name = phone.cookie, phone.cookie_name
        return tab

    def test_leave_in_one_tab_stops_every_other_tab_and_a_stale_page_from_rejoining(self):
        ana = self.phone()
        ana.post('join', {'name': 'Ana'})
        ben = self.phone()
        ben.post('join', {'name': 'Ben'})
        ben2 = self.tab_of(ben)
        status, v, _ = ben.post('leave')
        self.assertEqual((status, v['me'], v['departed']), (200, None, True))
        for tab in (ben, ben2):
            status, body, _ = tab.post('join', {'name': 'Ben'})          # the automatic path
            self.assertEqual((status, body['error']), (409, 'left_party'))
            self.assertTrue(tab.state()[1]['departed'])
        _, v, _ = ana.state()
        self.assertEqual([m['name'] for m in v['members']], ['Ana'])

    def test_a_second_leave_from_the_other_tab_is_harmless(self):
        ben = self.phone()
        ben.post('join', {'name': 'Ben'})
        ben2 = self.tab_of(ben)
        self.assertEqual(ben.post('leave')[0], 200)
        status, v, _ = ben2.post('leave')
        self.assertEqual((status, v['departed']), (200, True))

    def test_leave_needs_the_phones_own_cookie(self):
        stranger = self.phone()
        status, body, _ = stranger.post('leave')
        self.assertEqual((status, body['error']), (403, 'not_member'))
        ana = self.phone()
        ana.post('join', {'name': 'Ana'})
        forged = self.phone()
        forged.cookie, forged.cookie_name = 'f' * 64, ana.cookie_name
        self.assertEqual(forged.post('leave')[0], 403)
        self.assertEqual(ana.state()[1]['me']['name'], 'Ana')

    def test_reconnect_opts_back_in_and_the_view_follows_the_current_location(self):
        ana, ben = self.phone(), self.phone()
        ana.post('join', {'name': 'Ana'})
        ben.post('join', {'name': 'Ben'})
        _, v, _ = ana.state()
        ana.post('session/launch', {'game': 'bluff', 'if_version': v['version']})
        ben.post('leave')
        status, v, _ = ben.post('reconnect', {'name': 'Ben'})
        self.assertEqual((status, v['me']['name'], v['departed']), (200, 'Ben', False))
        self.assertEqual((v['location']['at'], v['state']), ('game', 'active'))
        self.assertFalse(v['me']['host'])

    def test_reconnect_without_a_name_is_refused_and_does_not_rejoin(self):
        ben = self.phone()
        ben.post('join', {'name': 'Ben'})
        ben.post('leave')
        status, body, _ = ben.post('reconnect', {})
        self.assertEqual((status, body['error']), (400, 'bad_name'))
        self.assertTrue(ben.state()[1]['departed'])

    def test_a_non_host_leave_moves_nobody_else_but_a_host_leave_hands_over(self):
        ana, ben, cy = self.phone(), self.phone(), self.phone()
        for p, n in ((ana, 'Ana'), (ben, 'Ben'), (cy, 'Cy')):
            p.post('join', {'name': n})
        _, v, _ = ana.state()
        ana.post('session/launch', {'game': 'bluff', 'if_version': v['version']})
        _, before, _ = cy.state()
        ben.post('leave')
        _, after, _ = cy.state()
        for key in ('nav', 'location', 'host', 'state'):
            self.assertEqual(after[key], before[key])
        status, v, _ = ana.post('leave')
        self.assertEqual(status, 200)
        _, v, _ = cy.state()
        self.assertTrue(v['me']['host'])
        self.assertEqual(v['state'], 'active')
        status, body, _ = ana.post('session/end', {'if_version': v['version']})
        self.assertEqual((status, body['error']), (403, 'not_member'))     # no leftover authority

    def test_chat_stays_closed_to_a_departed_device(self):
        ben = self.phone()
        _, v, _ = ben.post('join', {'name': 'Ben'})
        ben.post('leave')
        status, body, _ = ben.post('messages', {'party': v['party'], 'text': 'hi'})
        self.assertEqual(status, 403)


if __name__ == '__main__':
    unittest.main()
