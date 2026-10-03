"""AVR-229: Party Core's per-game metadata has one source, the Game Contract."""
import contextlib
import io
import json
import os
import tempfile
import unittest

from avrana import CONTRACTS_DIR, REPO_ROOT
from avrana.contracts import catalog, party_config, vocabulary
from avrana.contracts.party_config import ConfigError

EXAMPLE = REPO_ROOT / 'deploy' / 'party-core' / 'party-core.example.json'


def contract(game_id='tiles', **over):
    c = {'id': game_id, 'players': {'min': 2, 'max': 4}, 'late_join': 'next_round', 'extensions': {}}
    c.update(over)
    return c


class Derivation(unittest.TestCase):
    def test_every_field_party_core_needs_comes_from_the_contract(self):
        c = contract(extensions={'net.avrana.party': {'pregame': True}})
        self.assertEqual(party_config.metadata(c), {'min_players': 2, 'max_players': 4,
                                                    'late_join': 'next_round', 'pregame': True})
        self.assertFalse(party_config.metadata(contract())['pregame'])        # absent: no pregame

    def test_a_config_names_only_what_the_appliance_owns(self):
        games = party_config.resolve({'tiles': {'url': 'http://127.0.0.1:9', 'key_file': '/k',
                                                'timeout': 9}}, {'tiles': contract()})
        self.assertEqual(games, {'tiles': {'id': 'tiles', 'min_players': 2, 'max_players': 4,
                                           'late_join': 'next_round', 'pregame': False}})

    def test_a_repeated_field_must_agree_and_a_stale_copy_never_wins(self):
        same = {'tiles': {'min_players': 2, 'max_players': 4, 'late_join': 'next_round',
                          'pregame': False}}
        self.assertEqual(party_config.resolve(same, {'tiles': contract()})['tiles']['max_players'], 4)
        for key, stale in (('min_players', 1), ('max_players', 6), ('late_join', 'supported'),
                           ('pregame', True)):
            with self.subTest(key=key):
                with self.assertRaises(ConfigError) as e:
                    party_config.resolve({'tiles': {key: stale}}, {'tiles': contract()})
                self.assertIn(f'tiles.{key}', str(e.exception))
                self.assertIn('the contract decides', str(e.exception))

    def test_every_problem_is_reported_at_once(self):
        with self.assertRaises(ConfigError) as e:
            party_config.resolve({'ghost': {}, 'tiles': {'max_players': 9, 'port': 1}, 'odd': []},
                                 {'tiles': contract(), 'odd': contract('odd')})
        text = str(e.exception)
        for needle in ('ghost: no Game Contract', 'tiles.max_players', "unknown key 'port'",
                       'odd: an object'):
            self.assertIn(needle, text)
        self.assertEqual(len(e.exception.problems), 4)

    def test_the_party_extension_is_strict(self):
        for ext, needle in (({'pregame': 'yes'}, 'true or false'), ({'pregme': True}, 'unknown key'),
                            ([], 'must be an object')):
            with self.subTest(ext=ext):
                with self.assertRaises(ConfigError) as e:
                    party_config.metadata(contract(extensions={'net.avrana.party': ext}))
                self.assertIn(needle, str(e.exception))


class Repository(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contracts = party_config.load_contracts()
        cls.example = json.loads(EXAMPLE.read_text(encoding='utf-8'))

    def test_every_committed_contract_yields_party_metadata(self):
        for game_id, c in self.contracts.items():
            with self.subTest(game=game_id):
                meta = party_config.metadata(c)
                self.assertLessEqual(meta['min_players'], meta['max_players'])

    def test_the_example_config_repeats_nothing_the_contracts_state(self):
        for game_id, entry in self.example['games'].items():
            self.assertLessEqual(set(entry), party_config.APPLIANCE_KEYS, game_id)
        games = party_config.resolve(self.example['games'])
        self.assertEqual((games['bluff']['min_players'], games['bluff']['max_players'],
                          games['bluff']['late_join'], games['bluff']['pregame']),
                         (2, 6, 'spectator_only', True))

    def test_party_home_and_party_core_read_the_same_numbers(self):
        """The mismatch this issue found: the browser catalog said BLUFF needs 1 player (the
        donor's standalone lobby) while Party Core enforced 2."""
        vocab = vocabulary.load()
        merged = catalog.load_contracts(CONTRACTS_DIR / 'games', vocab)
        built = json.loads((REPO_ROOT / 'web' / 'party' / 'catalog.json').read_text(encoding='utf-8'))
        shown = {g['id']: g for g in built['games']}
        for game_id, game in party_config.resolve(self.example['games']).items():
            with self.subTest(game=game_id):
                source = json.loads((CONTRACTS_DIR / 'games' / f'{game_id}.json')
                                    .read_text(encoding='utf-8'))
                want = {'min': game['min_players'], 'max': game['max_players']}
                self.assertEqual(source['players'], want)             # the contract file itself
                self.assertEqual(merged[game_id]['players'], want)    # what the catalog is built from
                self.assertEqual(shown[game_id]['players'], want)     # what the phone is shown
                self.assertEqual(shown[game_id]['late_join'], game['late_join'])

    def test_the_browser_catalog_does_not_carry_the_party_extension(self):
        text = (REPO_ROOT / 'web' / 'party' / 'catalog.json').read_text(encoding='utf-8')
        self.assertNotIn(party_config.EXTENSION, text)


class CommandLine(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = party_config.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_check_passes_on_the_committed_example(self):
        code, out, _ = self.run_cli('--check', str(EXAMPLE))
        self.assertEqual(code, 0)
        self.assertIn('agree with their contracts', out)

    def test_show_is_deterministic_json(self):
        first = self.run_cli('--show', str(EXAMPLE))
        self.assertEqual(first, self.run_cli('--show', str(EXAMPLE)))
        self.assertEqual(set(json.loads(first[1])), {'bluff', 'arcade-gauntlet2'})

    def test_check_fails_and_names_the_drifted_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'party-core.json')
            with open(path, 'w', encoding='utf-8') as f:
                json.dump({'games': {'bluff': {'max_players': 8}}}, f)
            code, _, err = self.run_cli('--check', path)
        self.assertEqual(code, 1)
        self.assertIn('bluff.max_players', err)


if __name__ == '__main__':
    unittest.main()


class ServiceStartup(unittest.TestCase):
    def test_the_service_refuses_to_start_on_a_stale_copy(self):
        from avrana.party import service
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'party-core.json')
            with open(path, 'w', encoding='utf-8') as f:
                json.dump({'hosts': ['party.avrana.net'], 'origins': ['https://party.avrana.net'],
                           'games': {'bluff': {'min_players': 1}}}, f)
            with self.assertRaises(SystemExit) as e:
                service.main(['--config', path, '--port', '0'])
        self.assertIn('bluff.min_players', str(e.exception))
