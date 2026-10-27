"""Heartbeat diagnostics (AVR-302): off by default and inert when off; when on, per-member gaps,
late beats and rejoins, read only from the box itself and with nothing that names a person."""
import json
import threading
import unittest

from avrana.contracts import party_config
from avrana.party import core, heartbeats, identity, service
from test_party_core import BLUFF, make
from test_party_service import BLUFF as BLUFF_ENTRIES, HOST, FakeLink, Phone


class Off(unittest.TestCase):
    def test_party_core_holds_nothing_and_behaves_the_same_when_off(self):
        runs = []
        for on in (False, True):
            pc, clock = make()
            if on:
                pc.heartbeats = heartbeats.Heartbeats()
            pc.join('device-a', 'Ana')
            pc.join('device-b', 'Ben')
            for step in (10, 40, 70):
                clock.advance(step)
                pc.touch('device-a')
            pc.join('device-b', 'Ben')
            pc.tick()
            v = pc.view('device-a')
            runs.append((pc.party.version, [(m['name'], m['presence'], m['host']) for m in v['members']]))
        self.assertEqual(runs[0], runs[1])               # observing changes nothing Party Core decides
        self.assertIsNone(make()[0].heartbeats)          # and the default is no observer at all

    def test_the_config_switch_is_off_unless_set_and_must_be_a_boolean(self):
        self.assertEqual(party_config.check_diagnostics({})[0], {'heartbeats': False})
        self.assertEqual(party_config.check_diagnostics({'diagnostics': {'heartbeats': True}})[0], {'heartbeats': True})
        _, problems, _ = party_config.check_diagnostics({'diagnostics': {'heartbeats': 'yes'}})
        self.assertIn('diagnostics.heartbeats: true or false', problems[0])
        _, problems, warnings = party_config.check_diagnostics({'diagnostics': {'rtt': True}})
        self.assertEqual(problems, [])
        self.assertIn("unknown key 'rtt'", warnings[0])


class On(unittest.TestCase):
    def test_gaps_late_beats_and_rejoins_per_member(self):
        pc, clock = make()
        pc.heartbeats = heartbeats.Heartbeats()
        pc.join('device-a', 'Ana')
        pc.join('device-b', 'Ben')
        pc.touch('device-a')                              # first beat: no gap yet
        for gap in (3, 20, 40, 100):
            clock.advance(gap)
            pc.touch('device-a')
        pc.join('device-b', 'Ben')                       # a reload: the member joins again
        doc = pc.heartbeats.document(clock())
        ana, ben = doc['members']
        self.assertEqual((ana['member'], ana['beats'], ana['late'], ana['longest_gap_s']), (1, 5, 2, 100.0))
        self.assertEqual(ana['gaps'], {'<= 5 s': 1, '<= 15 s': 0, '<= 30 s': 1, '<= 45 s': 1, '<= 90 s': 0, '> 90 s': 1})
        self.assertEqual((ben['member'], ben['rejoins'], ben['beats']), (2, 1, 0))
        text = json.dumps(doc)
        for secret in ('Ana', 'Ben', 'device-a', *pc.party.members):
            self.assertNotIn(secret, text)               # nobody can be recognised from it

    def test_tracking_is_bounded(self):
        hb = heartbeats.Heartbeats()
        for i in range(heartbeats.MAX_MEMBERS + 5):
            hb.beat(f'member-{i}', 0.0)
        self.assertEqual(len(hb.document(1.0)['members']), heartbeats.MAX_MEMBERS)


class Route(unittest.TestCase):
    def setUp(self):
        svc = service.PartyService(identity.DeviceStore(None), service.load_games(BLUFF_ENTRIES), FakeLink())
        svc.core.heartbeats = heartbeats.Heartbeats()
        cfg = service.Config({HOST}, {'https://' + HOST}, secure_cookie=False)
        self.server = service.make_server(svc, cfg, port=0, extra_routes=heartbeats.route(svc))
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)

    def test_read_on_the_box_and_refused_through_the_proxy(self):
        phone = Phone(self.port)
        phone.req('POST', '/party/api/join', {'name': 'Ada'})
        code, doc, _ = phone.req('GET', heartbeats.ROUTE)
        self.assertEqual(code, 200)
        self.assertEqual(doc['schema'], 'avrana.heartbeats/v0')
        self.assertEqual(len(doc['members']), 1)
        for header in ('X-Forwarded-For', 'X-Real-IP', 'Forwarded'):
            with self.subTest(header=header):
                self.assertEqual(phone.req('GET', heartbeats.ROUTE, headers={header: '10.0.0.5'})[0], 404)


if __name__ == '__main__':
    unittest.main()
