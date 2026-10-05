"""The Party <-> Games contract declaration and tools/contract_check.py (mutation tests)."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from avrana import REPO_ROOT
from avrana.contracts import party_games
from avrana.party import protocol, result, sessions

spec = importlib.util.spec_from_file_location('contract_check', REPO_ROOT / 'tools/contract_check.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)

PARTY_FILES = ['contracts/party-games.v0.json', 'avrana/party/protocol.py', 'avrana/party/sessions.py',
               'avrana/party/result.py', 'contracts/vectors/game-result.v1.json',
               'avrana/contracts/lan_catalog.py', 'contracts/vectors/party-session.v0.json',
               'contracts/catalogs/lan-games.json', 'deploy/arcade/avrana-party-session.conf',
               'docs/runbooks/party-core-deploy.md', 'web/party/bridge/shim.js', 'web/party/bridge.html',
               'contracts/vectors/party-bridge.v1.json']


def fake_games(root, party_decl):
    """A minimal games checkout that agrees with the Party declaration."""
    p = party_decl
    (root / 'core').mkdir(parents=True)
    (root / 'provider').mkdir()
    (root / 'tests/vectors').mkdir(parents=True)
    (root / 'ops').mkdir()
    (root / 'deploy').mkdir()
    shutil.copyfile(REPO_ROOT / 'avrana/party/protocol.py', root / 'core/party_protocol.py')
    shutil.copyfile(REPO_ROOT / 'contracts/vectors/party-session.v0.json', root / 'tests/vectors/party-session.v0.json')
    shutil.copyfile(REPO_ROOT / 'contracts/catalogs/lan-games.json', root / 'provider/catalog.json')
    shutil.copyfile(REPO_ROOT / 'avrana/party/result.py', root / 'core/party_result.py')
    shutil.copyfile(REPO_ROOT / 'contracts/vectors/game-result.v1.json', root / 'tests/vectors/game-result.v1.json')
    (root / 'web').mkdir()
    shutil.copyfile(REPO_ROOT / 'web/party/bridge/shim.js', root / 'web/avrana-party-bridge.js')
    shutil.copyfile(REPO_ROOT / 'contracts/vectors/party-bridge.v1.json', root / 'tests/vectors/party-bridge.v1.json')
    (root / 'games/bluff').mkdir(parents=True)
    (root / 'games/bluff/game.py').write_text('class S:\n    def game_result(self, ref):\n        return None\n',
                                              encoding='utf-8')
    (root / 'core/party_session.py').write_text(f'KEYS_ENV = "{p["environment"]["keys_dir"]}"\n'
                                                f'ENDED_PATH = "{p["routes"]["party_ended"]}"\n'
                                                f'HOST_PATH = "{p["routes"]["party_host"]}"\n', encoding='utf-8')
    (root / 'server.py').write_text(f'@app.post("/games/{{slug}}{p["routes"]["game_launch"]}")\n'
                                    f'@app.post("/games/{{slug}}{p["routes"]["game_end"]}")\n', encoding='utf-8')
    (root / 'ops/export_avrana_catalog.py').write_text(f"INTEGRATION = '{p['launch']['integration']}'\n", encoding='utf-8')
    (root / 'deploy/avrana-party-session.conf').write_text(
        ''.join(f'Environment={v}=/x\n' for v in p['environment'].values()))
    decl = {'requires': p['contract'],
            'session_protocol': {'version': p['session_protocol']['version'], 'vendored': 'core/party_protocol.py',
                                 'vendored_sha256': p['session_protocol']['reference_sha256'],
                                 'vectors': 'tests/vectors/party-session.v0.json',
                                 'vectors_sha256': p['session_protocol']['vectors_sha256']},
            'result': {'schema': p['result']['schema'], 'carried_by': p['result']['carried_by'],
                       'vendored': 'core/party_result.py', 'vendored_sha256': p['result']['reference_sha256'],
                       'vectors': 'tests/vectors/game-result.v1.json',
                       'vectors_sha256': p['result']['vectors_sha256'], 'reported_by': ['bluff']},
            'bridge': {'protocol': p['bridge']['protocol'], 'vendored': 'web/avrana-party-bridge.js',
                       'vendored_sha256': p['bridge']['reference_sha256'],
                       'vectors': 'tests/vectors/party-bridge.v1.json',
                       'vectors_sha256': p['bridge']['vectors_sha256']},
            'party_side_games': ['bluff', 'expo'],
            'routes': dict(p['routes']), 'launch': dict(p['launch']), 'environment': dict(p['environment'])}
    (root / 'provider/avrana-contract.json').write_text(json.dumps(decl), encoding='utf-8')
    return decl


class Declaration(unittest.TestCase):
    def test_declaration_matches_the_code(self):
        d = party_games.load()
        self.assertEqual(d['session_protocol']['version'], protocol.VERSION)
        self.assertEqual(d['session_protocol']['prefix'], protocol.PREFIX)
        self.assertEqual(d['routes']['party_ticket'], sessions.TICKET_ROUTE)
        self.assertEqual(d['routes']['party_ended'], sessions.ENDED_ROUTE)
        self.assertEqual(d['routes']['party_host'], sessions.HOST_ROUTE)
        self.assertEqual(d['routes']['game_launch'], sessions.LAUNCH_PATH)
        self.assertEqual(d['routes']['game_end'], sessions.END_PATH)
        self.assertEqual(party_games.versions(d), {'party_games': 'avrana.party-games/v0',
                                                   'party_session': protocol.VERSION,
                                                   'lan_launch': 'avrana.lan-launch/v1'})

        self.assertEqual((d['result']['schema'], d['result']['carried_by']), (result.SCHEMA, 'ended.result'))

    def test_party_side_check_passes_on_this_checkout(self):
        checker.check_party(REPO_ROOT)


class Mutations(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.party = Path(self.temp.name) / 'party'
        for rel in PARTY_FILES:
            target = self.party / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO_ROOT / rel, target)
        self.decl = json.loads((self.party / 'contracts/party-games.v0.json').read_text(encoding='utf-8'))
        self.games = Path(self.temp.name) / 'games'
        self.games_decl = fake_games(self.games, self.decl)

    def write_party(self):
        (self.party / 'contracts/party-games.v0.json').write_text(json.dumps(self.decl), encoding='utf-8')

    def write_games(self):
        (self.games / 'provider/avrana-contract.json').write_text(json.dumps(self.games_decl), encoding='utf-8')

    def run_all(self):
        checker.run(self.party, self.games)

    def test_compatible_pair_passes(self):
        self.run_all()

    def test_party_protocol_edit_without_redeclaring_is_named(self):
        with open(self.party / 'avrana/party/protocol.py', 'a', encoding='utf-8') as f:
            f.write('\n# a change\n')
        with self.assertRaises(checker.Drift) as cm:
            checker.check_party(self.party)
        self.assertIn('session protocol file digest', str(cm.exception))

    def test_party_protocol_change_redeclared_but_not_revendored_is_cross_drift(self):
        with open(self.party / 'avrana/party/protocol.py', 'a', encoding='utf-8') as f:
            f.write('\n# a change\n')
        self.decl['session_protocol']['reference_sha256'] = checker.sha256_normalized(self.party / 'avrana/party/protocol.py')
        self.write_party()
        with self.assertRaises(checker.Drift) as cm:
            self.run_all()
        self.assertIn('re-vendor', str(cm.exception))

    def test_bridge_shim_edit_without_redeclaring_is_named(self):
        with open(self.party / 'web/party/bridge/shim.js', 'a', encoding='utf-8') as f:
            f.write('\n// a change\n')
        with self.assertRaises(checker.Drift) as cm:
            checker.check_party(self.party)
        self.assertIn('bridge shim file digest', str(cm.exception))

    def test_bridge_shim_change_redeclared_but_not_revendored_is_cross_drift(self):
        with open(self.party / 'web/party/bridge/shim.js', 'a', encoding='utf-8') as f:
            f.write('\n// a change\n')
        self.decl['bridge']['reference_sha256'] = checker.sha256_normalized(self.party / 'web/party/bridge/shim.js')
        self.write_party()
        with self.assertRaises(checker.Drift) as cm:
            self.run_all()
        self.assertIn('bridge shim drifted', str(cm.exception))
        self.assertIn('re-vendor', str(cm.exception))

    def test_a_vendored_shim_edited_in_games_is_named(self):
        with open(self.games / 'web/avrana-party-bridge.js', 'a', encoding='utf-8') as f:
            f.write('\n// a local edit\n')
        with self.assertRaises(checker.Drift) as cm:
            self.run_all()
        self.assertIn('bridge shim file digest', str(cm.exception))

    def test_bridge_vectors_divergence_is_named(self):
        with open(self.games / 'tests/vectors/party-bridge.v1.json', 'a', encoding='utf-8') as f:
            f.write('\n')
        self.games_decl['bridge']['vectors_sha256'] = checker.sha256_normalized(
            self.games / 'tests/vectors/party-bridge.v1.json')
        self.write_games()
        with self.assertRaises(checker.Drift) as cm:
            self.run_all()
        self.assertIn('bridge vectors drifted', str(cm.exception))

    def test_games_on_another_bridge_protocol_is_named(self):
        self.games_decl['bridge']['protocol'] = 'avrana.party-bridge/v2'
        self.write_games()
        with self.assertRaises(checker.Drift) as cm:
            self.run_all()
        self.assertIn('bridge protocol drifted', str(cm.exception))

    def test_a_games_repository_that_does_not_declare_the_bridge_is_named(self):
        # Never "not compared": a declaration without the shim would pass with nothing checked.
        del self.games_decl['bridge']
        self.write_games()
        with self.assertRaises(checker.Drift) as cm:
            self.run_all()
        self.assertIn('declares no bridge', str(cm.exception))

    def test_a_declared_bridge_frame_must_exist(self):
        (self.party / 'web/party/bridge.html').unlink()
        with self.assertRaises(checker.Drift) as cm:
            checker.check_party(self.party)
        self.assertIn('bridge frame drifted', str(cm.exception))

    def test_result_module_edit_without_redeclaring_is_named(self):
        with open(self.party / 'avrana/party/result.py', 'a', encoding='utf-8') as f:
            f.write('\n# a change\n')
        with self.assertRaises(checker.Drift) as cm:
            checker.check_party(self.party)
        self.assertIn('result reference file digest', str(cm.exception))

    def test_result_change_redeclared_but_not_revendored_is_cross_drift(self):
        with open(self.party / 'avrana/party/result.py', 'a', encoding='utf-8') as f:
            f.write('\n# a change\n')
        self.decl['result']['reference_sha256'] = checker.sha256_normalized(self.party / 'avrana/party/result.py')
        self.write_party()
        with self.assertRaises(checker.Drift) as cm:
            self.run_all()
        self.assertIn('result envelope drifted', str(cm.exception))

    def test_games_on_another_result_schema_is_named(self):
        self.games_decl['result']['schema'] = 'avrana.game-result/v2'
        self.write_games()
        with self.assertRaises(checker.Drift) as cm:
            self.run_all()
        self.assertIn('result schema', str(cm.exception))

    def test_result_vectors_divergence_is_named(self):
        with open(self.games / 'tests/vectors/game-result.v1.json', 'a', encoding='utf-8') as f:
            f.write('\n')
        self.games_decl['result']['vectors_sha256'] = checker.sha256_normalized(
            self.games / 'tests/vectors/game-result.v1.json')
        self.write_games()
        with self.assertRaises(checker.Drift) as cm:
            self.run_all()
        self.assertIn('result vectors drifted', str(cm.exception))

    def test_a_declared_result_reporter_must_define_game_result(self):
        (self.games / 'games/bluff/game.py').write_text('class S:\n    pass\n', encoding='utf-8')
        with self.assertRaises(checker.Drift) as cm:
            self.run_all()
        self.assertIn('defines no game_result()', str(cm.exception))

    def test_a_result_reporter_must_be_a_party_side_game(self):
        self.games_decl['result']['reported_by'] = ['snake']
        self.write_games()
        with self.assertRaises(checker.Drift) as cm:
            self.run_all()
        self.assertIn('not under party_side_games', str(cm.exception))

    def test_a_declaration_without_the_result_section_is_a_readable_failure(self):
        del self.games_decl['result']
        self.write_games()
        self.assertEqual(checker.main(['--party', str(self.party), '--games', str(self.games)]), 1)

    def test_games_requiring_a_newer_contract_fails(self):
        self.games_decl['requires'] = 'avrana.party-games/v1'
        self.write_games()
        with self.assertRaises(checker.Drift) as cm:
            self.run_all()
        self.assertIn('Games requires', str(cm.exception))

    def test_route_rename_on_one_side_is_named(self):
        text = (self.party / 'avrana/party/sessions.py').read_text(encoding='utf-8')
        (self.party / 'avrana/party/sessions.py').write_text(text.replace("TICKET_ROUTE = '/party/api/session/ticket'",
                                                                          "TICKET_ROUTE = '/party/api/session/ticket2'"), encoding='utf-8')
        with self.assertRaises(checker.Drift) as cm:
            checker.check_party(self.party)
        self.assertIn('party ticket route', str(cm.exception))

    def test_catalog_snapshot_divergence_is_named(self):
        snapshot = json.loads((self.games / 'provider/catalog.json').read_text(encoding='utf-8'))
        snapshot['games'][0]['title'] = 'Renamed'
        (self.games / 'provider/catalog.json').write_text(json.dumps(snapshot), encoding='utf-8')
        with self.assertRaises(checker.Drift) as cm:
            self.run_all()
        self.assertIn('catalog snapshot drifted', str(cm.exception))

    def test_missing_field_is_a_readable_failure(self):
        del self.games_decl['routes']
        self.write_games()
        self.assertEqual(checker.main(['--party', str(self.party), '--games', str(self.games)]), 1)


if __name__ == '__main__':
    unittest.main()
