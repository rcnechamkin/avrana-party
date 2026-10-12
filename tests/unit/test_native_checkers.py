"""Party drives the real grant-declared Checkers child and both Unix sockets (Linux CI).
No fake game/server results or alternate TCP launch path. Synthetic keys stay in temporary files.
"""
import json
import os
from pathlib import Path
import random
import sys
import threading
import time
import unittest

from avrana.contracts import appliance, catalog, party_config, vocabulary
from avrana.party import identity, service, sessions
import test_party_service as phone_helpers

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests/provider'))
from native_runtime import NativeRuntime, ActivatedLink


class CheckersContract(unittest.TestCase):
    def test_catalog_and_party_share_the_two_player_contract(self):
        contracts = party_config.load_contracts()
        meta = party_config.resolve({'checkers': {}})['checkers']
        self.assertEqual((meta['min_players'], meta['max_players'], meta['pregame']), (2, 2, False))
        profile = appliance.load(catalog.DEFAULT_APPLIANCE, vocabulary.load())
        grant = appliance.grants(profile)['checkers']
        self.assertEqual(grant['runtime']['command'], ['/usr/bin/python3', '-m', 'checkers'])
        compiled = catalog.build(vocabulary.load(), profile, contracts, artwork=catalog.load_artwork())
        entry = next(g for g in compiled['games'] if g['id'] == 'checkers')
        self.assertTrue(entry['installed'] and entry['playableHere'])
        self.assertEqual((entry['provider'], entry['entry'], entry['players']),
                         ('native', '/games/checkers/', {'min': 2, 'max': 2}))

    def test_stale_gauntlet_config_is_refused(self):
        with self.assertRaises(party_config.ConfigError):
            party_config.resolve({'arcade-gauntlet2': {'max_players': 2}})


@unittest.skipUnless(os.name == 'posix' and hasattr(__import__('socket'), 'AF_UNIX'), 'POSIX native process; Linux CI required')
class NativeCheckers(unittest.TestCase):
    def setUp(self):
        games = os.environ.get('AVRANA_GAMES_REPO')
        if not games or not (Path(games) / 'checkers/__main__.py').is_file():
            if os.environ.get('AVRANA_REQUIRE_NATIVE') == '1':
                self.fail('AVRANA_GAMES_REPO must name the paired Checkers checkout')
            self.skipTest('explicit paired Games checkout required')
        self.runtime = NativeRuntime(ROOT, games, 'checkers', phone_helpers.ORIGIN)
        self.addCleanup(self.runtime.close)
        endpoints = {'checkers': self.runtime.endpoint}
        self.svc = service.PartyService(identity.DeviceStore(None), party_config.resolve({'checkers': {}}),
                                        ActivatedLink(endpoints, self.runtime))
        extra, internal = sessions.routes(self.svc, endpoints)
        cfg = service.Config({phone_helpers.HOST}, {phone_helpers.ORIGIN}, secure_cookie=True,
                             game_origins={phone_helpers.GAMES_ORIGIN: ['checkers']})
        self.party = service.make_server(self.svc, cfg, port=0, extra_routes=extra, internal_routes=internal)
        self.internal = service.make_internal_server(self.svc, internal, path=self.runtime.party_path)
        for server in (self.party, self.internal):
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
        self.phones = [phone_helpers.Phone(self.party.server_address[1]) for _ in range(3)]
        for phone, name in zip(self.phones, ('Ana', 'Ben', 'Cleo')):
            self.assertEqual(phone.post('join', {'name': name})[0], 200)
        self.launch()

    def launch(self):
        version = self.phones[0].state()[1]['version']
        status, view, _ = self.phones[0].post('session/launch', {'game': 'checkers', 'if_version': version})
        self.assertEqual(status, 200, view)
        self.assertEqual(view['session']['state'], 'active')
        return view

    def request(self, path, body):
        status, headers, raw = self.runtime.request('POST', '/games/checkers/api/' + path,
                json.dumps(body).encode(), {'Content-Type': 'application/json', 'X-Forwarded-For': '127.0.0.1'})
        self.assertNotIn('set-cookie', [k.lower() for k, v in headers])
        return status, json.loads(raw)

    def ticket(self, phone):
        status, body, _ = phone.post('session/ticket', {'game': 'checkers', 'origin': phone_helpers.GAMES_ORIGIN})
        self.assertEqual(status, 200, body)
        return body['ticket']

    def redeem(self, phone):
        status, seat = self.request('redeem', {'ticket': self.ticket(phone)})
        self.assertEqual(status, 200, seat)
        return seat

    def end(self):
        version = self.phones[0].state()[1]['version']
        status, view, _ = self.phones[0].post('session/end', {'if_version': version})
        self.assertEqual(status, 200, view)
        return view

    def test_seats_private_controls_spectator_illegal_move_and_reload(self):
        a, b, c = [self.redeem(p) for p in self.phones]
        self.assertEqual([s['view']['seat'] for s in (a, b, c)], ['w', 'b', None])
        self.assertTrue(a['view']['moves'])
        self.assertEqual(b['view']['moves'], [])
        self.assertEqual(c['view']['moves'], [])
        self.assertEqual(self.request('move', {'token': b['token'], 'v': 1, 'move': a['view']['moves'][0]})[0], 409)
        self.assertEqual(self.request('move', {'token': c['token'], 'v': 1, 'move': a['view']['moves'][0]})[0], 403)
        self.assertEqual(self.request('move', {'token': a['token'], 'v': 1, 'move': [0, 1]})[0], 409)
        status, moved = self.request('move', {'token': a['token'], 'v': 1, 'move': a['view']['moves'][0]})
        self.assertEqual(status, 200)
        reloaded = self.redeem(self.phones[0])
        self.assertEqual(reloaded['token'], a['token'])
        self.assertEqual(reloaded['view']['board'], moved['view']['board'])
        self.assertEqual(self.request('redeem', {'ticket': 'not-a-ticket'})[0], 403)

    def test_complete_legal_match_is_accepted_by_party_then_host_goes_home(self):
        seats = [self.redeem(p) for p in self.phones[:2]]
        tokens = {s['view']['seat']: s['token'] for s in seats}
        rng = random.Random(7)
        view = seats[0]['view']
        for _ in range(500):
            token = tokens[view['turn']]
            view = self.request('poll', {'token': token, 'since': -1})[1]['view']
            status, moved = self.request('move', {'token': token, 'v': view['v'], 'move': rng.choice(view['moves'])})
            self.assertEqual(status, 200)
            view = moved['view']
            if view['result']:
                break
        self.assertIsNotNone(view['result'], 'legal match exceeded bounded 500 plies')
        for _ in range(100):
            state = self.phones[0].state()[1]
            if state['session'].get('result_summary'):
                break
            time.sleep(.05)
        self.assertEqual(state['session']['outcome'], 'completed')
        self.assertEqual(self.svc.core.party.session.result['schema'], 'avrana.game-result/v1')
        self.assertIsNone(self.svc.core.party.session.result_refused)
        self.assertEqual(len(state['session']['result_summary']['players']), 2)
        self.assertEqual(self.phones[0].post('session/ticket', {'game': 'checkers'})[0], 409)
        status, home, _ = self.phones[0].post('home', {'if_version': state['version']})
        self.assertEqual(status, 200, home)
        self.assertEqual(home['location']['at'], 'home')
        self.assertEqual(self.request('poll', {'token': seats[0]['token'], 'since': -1})[0], 403)

    def test_host_end_invalidates_tokens_and_old_ticket_on_next_launch(self):
        seat = self.redeem(self.phones[0])
        stale = self.ticket(self.phones[1])
        self.end()
        self.assertEqual(self.request('poll', {'token': seat['token'], 'since': -1})[0], 403)
        self.launch()
        self.assertEqual(self.request('redeem', {'ticket': stale})[0], 403)
        self.assertNotEqual(self.redeem(self.phones[0])['token'], seat['token'])

    def test_process_failure_host_cleanup_and_subsequent_launch(self):
        old = self.redeem(self.phones[0])
        stale = self.ticket(self.phones[1])
        self.runtime.stop_process()
        # Host End itself activates the empty child, as systemd's listening socket would.
        # Party records the refusal honestly: the empty child cannot confirm the lost session.
        ended = self.end()
        self.assertEqual(ended['session']['outcome'], 'ended_by_host')
        self.assertFalse(self.svc.core.party.session.game_confirmed_end)
        self.assertEqual(self.request('poll', {'token': old['token'], 'since': -1})[0], 403)
        self.launch()
        self.assertEqual(self.request('redeem', {'ticket': stale})[0], 403)
        self.assertEqual(self.redeem(self.phones[0])['view']['seat'], 'w')
