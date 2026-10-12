"""Hello Party (AVR-38, experimental): the Party half is a test-only Game Contract and a test-only
appliance grant. Nothing about it is in Party Core, the product appliance or the product catalog.

    python3 -m unittest tests.unit.test_hello_party_contract
"""
import json
import os
import unittest
from pathlib import Path

from avrana import CONTRACTS_DIR, REPO_ROOT
from avrana.contracts import appliance, catalog, game, party_config, vocabulary
from avrana.ops import provision_game

GAME = 'hello'
VOCAB = vocabulary.load()
FIXTURE = REPO_ROOT / 'tests' / 'fixtures' / 'appliances' / 'ci-hello.json'


class HelloPartyContract(unittest.TestCase):
    def setUp(self):
        self.contract = game.load(CONTRACTS_DIR / 'games' / 'hello.json', VOCAB)

    def test_it_is_a_native_test_only_game_for_one_to_six_players(self):
        c = self.contract
        self.assertEqual((c['id'], c['kind'], c['runtime']['type'], c['runtime']['start']),
                         (GAME, 'native', 'external', 'service'))
        self.assertEqual((c['players']['min'], c['players']['max']), (1, 6))
        self.assertIs(c['extensions']['net.avrana.test']['test_only'], True)
        self.assertEqual(party_config.metadata(c)['pregame'], False)

    def test_the_product_appliance_and_catalog_know_nothing_of_it(self):
        pi4 = appliance.load(CONTRACTS_DIR / 'appliances' / 'avrana-pi4.json', VOCAB)
        self.assertNotIn(GAME, appliance.grants(pi4))
        self.assertNotIn('hello', (CONTRACTS_DIR / 'appliances' / 'avrana-pi4.json').read_text(encoding='utf-8'))
        contracts = {p.stem: game.load(p, VOCAB) for p in (CONTRACTS_DIR / 'games').glob('*.json')}
        self.assertNotIn(GAME, [g['id'] for g in catalog.build(VOCAB, pi4, contracts)['games']])
        self.assertNotIn(GAME, (REPO_ROOT / 'provider' / 'catalog.json').read_text(encoding='utf-8')
                         if (REPO_ROOT / 'provider' / 'catalog.json').exists() else '')

    def test_only_the_ci_fixture_grants_it_and_says_how_to_run_it(self):
        ci = appliance.load(FIXTURE, VOCAB)
        grant = appliance.grants(ci)[GAME]
        self.assertEqual((grant['entry'], grant['tier']), ('/games/hello/', 'builtin'))
        self.assertEqual(grant['runtime']['command'], ['/usr/bin/python3', '-m', 'hello_party'])
        self.assertEqual([g['id'] for g in catalog.build(VOCAB, ci, {GAME: self.contract})['games']], [GAME])

    def test_provision_game_would_accept_it_on_an_appliance_that_grants_it(self):
        # Nothing is provisioned here: this is the pure check provision-game starts with.
        ci = appliance.load(FIXTURE, VOCAB)
        provision_game.check(GAME, {GAME: self.contract}, appliance.grants(ci))
        pi4 = appliance.load(CONTRACTS_DIR / 'appliances' / 'avrana-pi4.json', VOCAB)
        with self.assertRaises(provision_game.Refused):
            provision_game.check(GAME, {GAME: self.contract}, appliance.grants(pi4))

    def test_it_matches_the_games_repository_copy_when_that_is_at_hand(self):
        games = os.environ.get('AVRANA_GAMES_REPO')
        path = Path(games) / 'hello_party' / 'game-contract.json' if games else None
        if not path or not path.exists():
            self.skipTest('no Games checkout (AVRANA_GAMES_REPO); the Games CI compares the two files')
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')),
                         json.loads((CONTRACTS_DIR / 'games' / 'hello.json').read_text(encoding='utf-8')))


if __name__ == '__main__':
    unittest.main()
