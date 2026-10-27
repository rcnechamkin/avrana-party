"""PROPOSAL home_in_round (AVR-703, Concept K K2): Party Home during a round, off unless the
appliance's party-core.json switches it on. With it off, nothing changes, not even the view."""
import unittest

from avrana.contracts import party_config
from avrana.party import core
from avrana.party.core import Refused
from test_party_core import BLUFF


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


def party(proposals=('home_in_round',)):
    pc = core.PartyCore(Clock(), {'bluff': BLUFF}, proposals=proposals)
    pc.join('device-a', 'Ana')
    pc.join('device-b', 'Ben')
    s = pc.launch('device-a', 'bluff', pc.party.version)
    pc.launch_accepted(s.id)
    return pc, s


class HomeInRound(unittest.TestCase):
    def test_off_by_default_refused_and_the_view_is_as_before(self):
        pc, _ = party(proposals=())
        with self.assertRaises(Refused) as e:
            pc.visit_home('device-b')
        self.assertEqual(e.exception.code, 'not_offered')
        v = pc.view('device-b')
        self.assertNotIn('proposals', v)
        self.assertNotIn('home_visit', v['me'])

    def test_a_visit_moves_only_this_device_and_never_the_round(self):
        pc, s = party()
        self.assertEqual(pc.view('device-b')['proposals'], ['home_in_round'])
        before = pc.party.version
        pc.visit_home('device-b')
        self.assertGreater(pc.party.version, before)            # wakes this device's pages
        self.assertTrue(pc.view('device-b')['me']['home_visit'])
        self.assertFalse(pc.view('device-a')['me']['home_visit'])
        self.assertEqual((s.state, pc.location()['at']), (core.ACTIVE, 'game'))   # the round goes on
        version = pc.party.version
        pc.visit_home('device-b')                               # a repeat changes nothing
        self.assertEqual(pc.party.version, version)
        pc.back_to_game('device-b')
        self.assertFalse(pc.view('device-b')['me']['home_visit'])

    def test_a_visit_ends_with_the_round_and_is_refused_outside_one(self):
        pc, s = party()
        pc.visit_home('device-b')
        pc.begin_end('device-a', pc.party.version)
        pc.end_confirmed(s.id, True)
        self.assertFalse(pc.view('device-b')['me']['home_visit'])
        with self.assertRaises(Refused) as e:
            pc.visit_home('device-b')
        self.assertEqual(e.exception.code, 'not_in_round')

    def test_the_switch_is_a_boolean_and_unknown_names_are_warnings(self):
        self.assertEqual(party_config.check_proposals({})[0], {'home_in_round': False})
        self.assertIn('true or false', party_config.check_proposals({'proposals': {'home_in_round': 1}})[1][0])
        self.assertIn("unknown key 'k9'", party_config.check_proposals({'proposals': {'k9': True}})[2][0])


if __name__ == '__main__':
    unittest.main()
