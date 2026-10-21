"""AVR-580 guest exit (Party PR #184): a guest on a game page of another origin asks to leave; the
confirmation is on Party Home. The request only asks: it never changes membership, seats, roles or
the party's location, and it is never the Host's way round succession.

Core rules run on a fake clock; the request boundary runs over real HTTP. No browser, no Pi."""
import unittest

from avrana.party import core
from test_party_core import make
from test_party_service import GAMES_ORIGIN, ServiceCase


def table():
    """Ana hosts a round of BLUFF; Ben and Cy play."""
    pc, clock = make()
    for d, n in (('device-a', 'Ana'), ('device-b', 'Ben'), ('device-c', 'Cy')):
        pc.join(d, n)
    s = pc.launch('device-a', 'bluff', pc.party.version)
    pc.launch_accepted(s.id)
    return pc, clock, s


def exit_of(pc, device):
    return pc.view(device)['me']['exit']


class RequestOnlyAsks(unittest.TestCase):
    def test_a_guest_request_changes_nothing_but_their_own_view(self):
        pc, _, s = table()
        nav, host, loc = dict(pc.party.nav), pc.party.host_id, pc.location()
        seat = s.participants[pc._member_of('device-b').id]
        pc.request_exit('device-b')
        self.assertEqual((pc.party.nav, pc.party.host_id, pc.location()), (nav, host, loc))
        self.assertIs(s.participants[pc._member_of('device-b').id], seat)
        self.assertEqual(s.state, core.ACTIVE)
        self.assertFalse(pc._member_of('device-b').left)
        ex = exit_of(pc, 'device-b')
        self.assertTrue(ex['live'] and ex['id'].startswith('exit'))
        for other in ('device-a', 'device-c'):                       # never shown to anyone else
            v = pc.view(other)
            self.assertIsNone(v['me']['exit'])
            self.assertNotIn('exit', str(v['members']))

    def test_the_host_is_refused_and_keeps_succession_on_party_home(self):
        pc, _, _ = table()
        version = pc.party.version
        with self.assertRaises(core.Refused) as e:
            pc.request_exit('device-a')
        self.assertEqual(e.exception.code, 'host_uses_party_home')
        self.assertEqual(pc.party.version, version)
        self.assertIsNone(exit_of(pc, 'device-a'))

    def test_refused_outside_a_round_for_strangers_and_for_a_device_that_left(self):
        pc, _ = make()
        pc.join('device-a', 'Ana')
        pc.join('device-b', 'Ben')
        with self.assertRaises(core.Refused) as e:
            pc.request_exit('device-b')                               # at home: Leave is on Party Home
        self.assertEqual(e.exception.code, 'not_in_round')
        with self.assertRaises(core.Refused) as e:
            pc.request_exit('device-x')
        self.assertEqual(e.exception.code, 'not_member')
        pc, _, _ = table()
        pc.leave('device-b')
        with self.assertRaises(core.Refused) as e:
            pc.request_exit('device-b')
        self.assertEqual(e.exception.code, 'left_party')

    def test_results_count_as_the_round(self):
        pc, _, s = table()
        pc.game_reported_end(s.id, 'completed')
        self.assertEqual(pc.location()['at'], 'results')
        pc.request_exit('device-b')
        self.assertTrue(exit_of(pc, 'device-b')['live'])


class ExpiryAndRepeats(unittest.TestCase):
    def test_expiry_stops_moving_pages_but_keeps_the_request_open_for_the_sheet(self):
        pc, clock, _ = table()
        pc.request_exit('device-b')
        first = exit_of(pc, 'device-b')['id']
        clock.advance(core.EXIT_INTENT + 1)
        ex = exit_of(pc, 'device-b')
        self.assertEqual((ex['id'], ex['live']), (first, False))     # stale: moves nothing, still answerable

    def test_a_repeat_keeps_the_same_request_and_renews_it(self):
        pc, clock, _ = table()
        pc.request_exit('device-b')
        first = exit_of(pc, 'device-b')['id']
        clock.advance(core.EXIT_INTENT - 1)
        pc.request_exit('device-b')                                   # a double tap, or a second game tab
        clock.advance(10)
        ex = exit_of(pc, 'device-b')
        self.assertEqual((ex['id'], ex['live']), (first, True))

    def test_stay_closes_it_and_is_idempotent(self):
        pc, _, _ = table()
        pc.stay('device-b')                                           # nothing open: nothing changes
        pc.request_exit('device-b')
        pc.stay('device-b')
        self.assertIsNone(exit_of(pc, 'device-b'))
        version = pc.party.version
        pc.stay('device-b')
        self.assertEqual(pc.party.version, version)
        self.assertFalse(pc._member_of('device-b').left)

    def test_after_stay_a_new_request_is_a_new_one(self):
        pc, _, _ = table()
        pc.request_exit('device-b')
        first = exit_of(pc, 'device-b')['id']
        pc.stay('device-b')
        pc.request_exit('device-b')
        self.assertNotEqual(exit_of(pc, 'device-b')['id'], first)

    def test_leave_and_reconnect_close_it(self):
        pc, _, _ = table()
        pc.request_exit('device-b')
        pc.leave('device-b')
        self.assertTrue(pc.view('device-b')['departed'])
        pc.reconnect('device-b', 'Ben')
        self.assertIsNone(exit_of(pc, 'device-b'))


class NoWayRoundSuccession(unittest.TestCase):
    def test_a_guest_who_becomes_host_while_asked_sees_the_hosts_consequence(self):
        pc, _, _ = table()
        pc.request_exit('device-b')
        pc.leave('device-a')                                          # Ben is next: he hosts now
        me = pc.view('device-b')['me']
        self.assertTrue(me['host'])
        self.assertTrue(me['leave']['host'])                          # Party Home's sheet names the successor
        self.assertEqual(me['leave']['successor'], 'Cy')
        with self.assertRaises(core.Refused):
            pc.request_exit('device-b')                               # and asks no more from a game page


class OverHttp(ServiceCase):
    def round(self):
        ana, ben, cy = self.phone(), self.phone(), self.phone()
        for p, n in ((ana, 'Ana'), (ben, 'Ben'), (cy, 'Cy')):
            p.post('join', {'name': n})
        _, v, _ = ana.state()
        ana.post('session/launch', {'game': 'bluff', 'if_version': v['version']})
        return ana, ben, cy

    def test_a_guest_asks_and_stays_with_their_own_cookie(self):
        ana, ben, cy = self.round()
        status, v, _ = ben.post('leave/request')
        self.assertEqual(status, 200)
        self.assertTrue(v['me']['exit']['live'])
        self.assertIsNone(cy.state()[1]['me']['exit'])
        status, v, _ = ben.post('leave/stay')
        self.assertEqual((status, v['me']['exit']), (200, None))

    def test_the_host_is_refused_over_http(self):
        ana, _, _ = self.round()
        status, body, _ = ana.post('leave/request')
        self.assertEqual((status, body['error']), (403, 'host_uses_party_home'))

    def test_no_cookie_a_forged_cookie_a_game_origin_or_another_origin_is_refused(self):
        ana, ben, _ = self.round()
        stranger = self.phone()
        self.assertEqual(stranger.post('leave/request')[1]['error'], 'not_member')
        forged = self.phone()
        forged.cookie, forged.cookie_name = 'f' * 64, ben.cookie_name
        self.assertEqual(forged.post('leave/request')[0], 403)
        for origin in (GAMES_ORIGIN, 'https://evil.example', 'null'):
            page = self.phone(origin=origin)                          # a game page, or anyone, with Ben's cookie
            page.cookie, page.cookie_name = ben.cookie, ben.cookie_name
            status, body, _ = page.post('leave/request')
            self.assertEqual((status, body['error']), (403, 'bad_origin'))
            self.assertEqual(page.post('leave/stay')[0], 403)
        page = self.phone()
        page.cookie, page.cookie_name = ben.cookie, ben.cookie_name
        status, body, _ = page.req('POST', '/party/api/leave/request', {}, headers={'Sec-Fetch-Site': 'same-site'})
        self.assertEqual((status, body['error']), (403, 'cross_origin'))   # a sibling host name, same site
        self.assertIsNone(ben.state()[1]['me']['exit'])

    def test_a_get_never_asks(self):
        _, ben, _ = self.round()
        status, _, _ = ben.req('GET', '/party/api/leave/request')
        self.assertNotEqual(status, 200)
        self.assertIsNone(ben.state()[1]['me']['exit'])

    def test_a_second_tab_shares_the_request_and_a_stay_in_either_closes_it(self):
        from test_party_service import Phone
        _, ben, _ = self.round()
        ben2 = Phone(self.port)
        ben2.cookie, ben2.cookie_name = ben.cookie, ben.cookie_name
        _, v, _ = ben.post('leave/request')
        self.assertEqual(ben2.state()[1]['me']['exit']['id'], v['me']['exit']['id'])
        ben2.post('leave/stay')
        self.assertIsNone(ben.state()[1]['me']['exit'])


if __name__ == '__main__':
    unittest.main()
