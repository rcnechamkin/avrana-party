"""Tier 1: Capability Engine v0 seat evaluation (Python side of the shared vectors)."""
import random
import unittest

from avrana import CONTRACTS_DIR
from avrana.contracts import appliance, catalog, strictjson, vocabulary
from avrana.contracts.evaluate import STATUSES, compile_presentations, evaluate_seat, plan_party

VECTORS = strictjson.load_path(CONTRACTS_DIR / 'vectors' / 'evaluate.v0.json')


class SharedVectors(unittest.TestCase):
    def test_every_vector(self):
        self.assertGreaterEqual(len(VECTORS['cases']), 15)
        for case in VECTORS['cases']:
            with self.subTest(case['name']):
                got = evaluate_seat(VECTORS['games'][case['game']], case['caps'], case['role'])
                self.assertEqual(got, case['expect'])

    def test_role_must_be_known(self):
        with self.assertRaises(ValueError):
            evaluate_seat(VECTORS['games']['table'], {}, 'host')


class Properties(unittest.TestCase):
    """Invariants over random capability reports (seeded, so failures reproduce)."""
    NAMES = ['websocket', 'webrtc', 'video.h264', 'wake_lock', 'web_audio', 'vibration', 'storage.local',
             'gamepad', 'webgl', 'webgl2', 'webgpu']

    def reports(self, seed, n=300):
        rng = random.Random(seed)
        for _ in range(n):
            yield {name: rng.choice(STATUSES + ('absent',)) for name in self.NAMES if rng.random() < .9}

    def test_unknown_is_never_worse_than_yes_and_never_treated_as_no(self):
        for game in VECTORS['games'].values():
            for caps in self.reports(7):
                for name, status in list(caps.items()):
                    if status not in ('unknown', 'absent'):
                        continue
                    as_yes = evaluate_seat(game, dict(caps, **{name: 'yes'}), 'player')
                    as_unknown = evaluate_seat(game, caps, 'player')
                    if as_yes['outcome'] in ('ready', 'limited', 'watch'):
                        self.assertNotEqual(as_unknown['outcome'], 'unavailable', (game['id'], name, caps))

    def test_a_weak_seat_never_changes_another_seat(self):
        game = VECTORS['games']['bomber_tv']
        rng = random.Random(11)
        reports = list(self.reports(11, 60))
        for _ in range(100):
            seats = [{'id': f's{i}', 'role': 'player', 'caps': rng.choice(reports)} for i in range(4)]
            alone = [evaluate_seat(game, s['caps'], 'player') for s in seats]
            weak = {'id': 'weak', 'role': 'player', 'caps': {n: 'no' for n in self.NAMES}}
            plan = plan_party(game, seats + [weak])
            self.assertEqual([{k: v for k, v in r.items() if k != 'seat'} for r in plan['seats'][:4]], alone)
            self.assertEqual(plan['seats'][4]['outcome'], 'unavailable')

    def test_can_start_counts_players_only(self):
        game = VECTORS['games']['table']
        ok = {'websocket': 'yes'}
        plan = plan_party(game, [{'id': 'a', 'caps': ok}, {'id': 'b', 'caps': {'websocket': 'no'}}])
        self.assertEqual(plan['players'], 1)
        self.assertFalse(plan['canStart'])  # BLUFF-like table needs two
        plan = plan_party(game, [{'id': 'a', 'caps': ok}, {'id': 'b', 'caps': ok},
                                 {'id': 'c', 'role': 'spectator', 'caps': ok}])
        self.assertEqual(plan['players'], 2)
        self.assertTrue(plan['canStart'])


class CompiledFromRealContracts(unittest.TestCase):
    def test_runtime_gating_uses_the_appliance(self):
        vocab = vocabulary.load()
        contracts = catalog.load_contracts(CONTRACTS_DIR / 'games', vocab)
        live = appliance.runtime_capabilities(appliance.load(CONTRACTS_DIR / 'appliances' / 'avrana-pi4.json', vocab))
        bomber = compile_presentations(contracts['ps1-bomberman'], live)
        game = {'id': 'x', 'fallback': 'spectate', 'players': {'min': 1, 'max': 4}, 'presentations': bomber}
        # Without a TV provider, a phone that cannot decode H.264 cannot fall back to TV controls.
        self.assertEqual(evaluate_seat(game, {'websocket': 'yes', 'webrtc': 'yes', 'video.h264': 'no'})['blockedBy'],
                         'device')
        bomber_tv = compile_presentations(contracts['ps1-bomberman'], live + ['presentation.tv'])
        game['presentations'] = bomber_tv
        self.assertEqual(evaluate_seat(game, {'websocket': 'yes', 'video.h264': 'no'})['presentation'],
                         'tv_controller')


if __name__ == '__main__':
    unittest.main()
