"""Tier 1: capability vocabulary, Game Contract v0, appliance profile and web catalog.

    python3 -m unittest discover -s tests/unit
"""
import copy
import importlib
import json
import re
import subprocess
import sys
import unittest

from avrana import CONTRACTS_DIR, REPO_ROOT, WEB_DIR
from avrana.contracts import appliance, catalog, game, strictjson, vocabulary

VOCAB = vocabulary.load()
GAMES = CONTRACTS_DIR / 'games'
APPLIANCE = CONTRACTS_DIR / 'appliances' / 'avrana-pi4.json'
JARGON = re.compile(r'\b(seat|session|runtime|server|websocket|presence|manifest|launch(ing)?|backend|token|slot|'
                    r'capabilit(y|ies)|provider|webrtc|h\.?264|codec)\b', re.I)


def minimal(**over):
    doc = {
        'contract': 'avrana.game/v0', 'id': 'demo', 'name': 'Demo', 'kind': 'native',
        'players': {'min': 1, 'max': 4}, 'screen': 'no_tv_needed', 'input': {'model': 'browser_native'},
        'runtime': {'type': 'lan_games_module'},
        'presentations': [{'id': 'phone', 'method': 'browser_native', 'roles': ['player', 'spectator'],
                           'requires': {'device': ['websocket'], 'runtime': ['runtime.lan_games']}}],
    }
    doc.update(over)
    return doc


class Vocabulary(unittest.TestCase):
    def test_loads_and_scopes_are_disjoint(self):
        self.assertIn('secure_context', VOCAB.device)
        self.assertIn('presentation.shared_stream', VOCAB.runtime)
        self.assertFalse(set(VOCAB.device) & set(VOCAB.runtime))

    def test_rejects_bad_documents(self):
        doc = strictjson.load_path(CONTRACTS_DIR / 'capabilities.v0.json')
        broken = copy.deepcopy(doc)
        broken['device']['webrtc']['probe'] = 'guess'
        self.assertTrue(vocabulary.check(broken))
        broken = copy.deepcopy(doc)
        broken['runtime']['flat'] = broken['runtime'].pop('runtime.retroarch')
        self.assertTrue(any('namespaced' in p for p in vocabulary.check(broken)))
        broken = copy.deepcopy(doc)
        del broken['device']['touch']['missing']
        self.assertTrue(vocabulary.check(broken))

    def test_browser_probe_uses_exactly_the_vocabulary(self):
        src = (WEB_DIR / 'lib' / 'capabilities.js').read_text(encoding='utf-8')
        listed = re.search(r'DEVICE_CAPABILITIES = Object\.freeze\(\[(.*?)\]\)', src, re.S).group(1)
        names = re.findall(r"'([^']+)'", listed)
        self.assertEqual(sorted(names), sorted(VOCAB.device))
        for name in VOCAB.device:
            self.assertTrue(f'caps.{name} =' in src or f"caps['{name}'] =" in src, f'the probe never sets {name}')

    def test_guest_words_have_no_machinery_terms(self):
        for scope in (VOCAB.device, VOCAB.runtime):
            for name, entry in scope.items():
                for key in ('label', 'missing'):
                    self.assertIsNone(JARGON.search(entry[key]), f'{name}.{key}: {entry[key]!r}')


class GameContract(unittest.TestCase):
    def test_examples_are_valid_and_named_by_id(self):
        paths = sorted(GAMES.glob('*.json'))
        self.assertGreaterEqual(len(paths), 3)
        for path in paths:
            c = game.load(path, VOCAB)
            self.assertEqual(c['contract'], 'avrana.game/v0')

    def test_defaults(self):
        c = game.validate(minimal(), VOCAB)
        self.assertEqual(c['late_join'], 'spectator_only')
        self.assertEqual(c['spectators'], 'watch')
        self.assertEqual(c['fallback'], 'explain')
        self.assertEqual(c['runtime']['start'], 'always_on')
        self.assertEqual(c['runtime']['permissions'], [])
        self.assertEqual(set(c['accessibility'].values()), {'unknown'})
        self.assertEqual(c['presentations'][0]['optional'], {'device': [], 'runtime': []})

    def assertRejects(self, doc, fragment):
        with self.assertRaises(game.ContractError) as ctx:
            game.validate(doc, VOCAB)
        self.assertTrue(any(fragment in p for p in ctx.exception.problems),
                        f'{fragment!r} not in {ctx.exception.problems}')

    def test_rejections(self):
        self.assertRejects(minimal(contract='avrana.game/v1'), 'contract')
        self.assertRejects(minimal(id='Party'), 'id')
        self.assertRejects(minimal(id='party'), 'id')
        self.assertRejects(minimal(colour='red'), "unknown key 'colour'")
        self.assertRejects(minimal(players={'min': 3, 'max': 2}), 'min > max')
        self.assertRejects(minimal(players={'min': True, 'max': 2}), 'integers')
        self.assertRejects(minimal(screen='projector'), 'screen')
        self.assertRejects(minimal(input={'model': 'browser_native', 'slots': 2}), 'only for controller')
        self.assertRejects(minimal(input={'model': 'controller_slots'}), 'input.slots')
        self.assertRejects(minimal(input={'model': 'controller_slots', 'slots': 5}), 'more slots')
        self.assertRejects(minimal(input={'model': 'hotseat', 'slots': 2}), 'exactly one slot')
        self.assertRejects(minimal(input={'model': 'controller_slots', 'slots': 2, 'buttons': ['up']}),
                           'direction names')
        self.assertRejects(minimal(runtime={'type': 'emulator_profile', 'start': 'service', 'profile': 'x'}),
                           'native game has no emulator')
        self.assertRejects(minimal(kind='emulated'), 'not a LAN Games module')
        self.assertRejects(minimal(runtime={'type': 'external'}), 'runtime.start')
        self.assertRejects(minimal(runtime={'type': 'lan_games_module', 'permissions': ['root']}), 'unknown')
        self.assertRejects(minimal(presentations=[]), 'presentations')
        self.assertRejects(minimal(fallback='spectate', spectators='none',
                                   presentations=[{'id': 'p', 'method': 'browser_native', 'roles': ['player']}]),
                           'needs spectators')

    def test_grant_side_keys_are_named(self):
        self.assertRejects(minimal(entry='/games/demo/'), 'contract.entry: set by the appliance grant')
        self.assertRejects(minimal(tier='builtin'), 'contract.tier')
        doc = minimal()
        doc['runtime'] = {'type': 'lan_games_module', 'path': '/x/'}
        self.assertRejects(doc, 'runtime.path')

    def test_presentation_rules(self):
        p = {'id': 'p', 'method': 'shared_stream', 'roles': ['player', 'spectator'],
             'requires': {'device': ['webrtc'], 'runtime': []}}
        self.assertRejects(minimal(presentations=[p]), "must require 'presentation.shared_stream'")
        p = {'id': 'p', 'method': 'personal_viewport', 'roles': ['player', 'spectator'],
             'requires': {'runtime': ['presentation.personal_viewport.crop']}}
        self.assertRejects(minimal(presentations=[p]), 'viewport')
        p = {'id': 'p', 'method': 'browser_native', 'roles': ['player', 'spectator'], 'viewport': 'crop'}
        self.assertRejects(minimal(presentations=[p]), 'only for a personal_viewport')
        p = {'id': 'p', 'method': 'browser_native', 'roles': ['player', 'spectator'],
             'requires': {'device': ['telepathy']}}
        self.assertRejects(minimal(presentations=[p]), "unknown 'telepathy'")
        p = {'id': 'p', 'method': 'browser_native', 'roles': ['player', 'spectator'],
             'requires': {'device': ['websocket']}, 'optional': {'device': ['websocket']}}
        self.assertRejects(minimal(presentations=[p]), 'both required and optional')
        p = {'id': 'p', 'method': 'browser_native', 'roles': ['spectator']}
        self.assertRejects(minimal(presentations=[p]), 'none of them is for players')
        p = {'id': 'p', 'method': 'browser_native', 'roles': ['player']}
        self.assertRejects(minimal(presentations=[p]), 'no presentation is for spectators')
        self.assertRejects(minimal(presentations=[p, dict(p, roles=['player', 'spectator'])]), 'duplicate')
        p = {'id': 'p', 'method': 'controller_only', 'roles': ['player', 'spectator'],
             'requires': {'runtime': ['presentation.tv']}}
        self.assertRejects(minimal(presentations=[p]), 'controller input model')
        stream = {'id': 's', 'method': 'shared_stream', 'roles': ['player', 'spectator'],
                  'requires': {'runtime': ['presentation.shared_stream']}}
        self.assertRejects(minimal(private_player_ui=True, presentations=[stream]), 'rendered on the phone')

    def test_personal_viewport_is_not_only_a_crop(self):
        for viewport, runtime in (('crop', ['presentation.personal_viewport.crop']),
                                  ('dedicated_stream', ['presentation.personal_viewport.dedicated_stream']),
                                  ('browser_renderer', []), ('private_panel', [])):
            p = {'id': 'mine', 'method': 'personal_viewport', 'viewport': viewport, 'roles': ['player', 'spectator'],
                 'requires': {'runtime': runtime}}
            c = game.validate(minimal(presentations=[p]), VOCAB)
            self.assertEqual(c['presentations'][0]['viewport'], viewport)

    def test_package_and_extensions(self):
        pkg = {'version': '1.0.0', 'license': 'MIT OR Apache-2.0', 'platforms': ['linux/arm64']}
        self.assertEqual(game.validate(minimal(package=pkg), VOCAB)['package'], pkg)
        self.assertRejects(minimal(package=dict(pkg, platforms=['any', 'linux/arm64'])), 'package.platforms')
        self.assertRejects(minimal(package=dict(pkg, license='MIT; rm -rf')), 'SPDX')
        self.assertRejects(minimal(package={'platforms': ['any']}), "missing 'version'")
        ok = game.validate(minimal(extensions={'net.avrana.example': {'x': 1}}), VOCAB)
        self.assertEqual(ok['extensions'], {'net.avrana.example': {'x': 1}})
        self.assertRejects(minimal(extensions={'mine': 1}), 'reverse-DNS')

    def test_strict_json(self):
        with self.assertRaises(strictjson.StrictJSONError):
            strictjson.loads('{"id": "a", "id": "b"}')
        with self.assertRaises(strictjson.StrictJSONError):
            strictjson.loads('{"x": NaN}')

    def test_file_name_must_equal_id(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'other.json'
            path.write_text(json.dumps(minimal()), encoding='utf-8')
            with self.assertRaises(game.ContractError):
                game.load(path, VOCAB)

    def test_lift_from_experimental_manifest_v0(self):
        # Verbatim builtins from experiment/party-service (experiments/manifests/builtin/) and a
        # derived LAN title, as manifest v0 produced them.
        gauntlet = {"manifest": 0, "id": "arcade-gauntlet2", "name": "Gauntlet II", "kind": "emulated",
                    "runtime": {"type": "external", "start": "always_on", "entry": "/arcade/"},
                    "players": {"min": 1, "max": 2}, "screen": "tv_optional",
                    "input": {"model": "controller_slots", "slots": 2}, "late_join": "supported",
                    "spectators": "none", "shared_video": True, "private_player_ui": False,
                    "accessibility": {"timing_pressure": True, "text_scalable": False,
                                      "reduced_motion_respected": False}}
        bomberman = {"manifest": 0, "id": "ps1-bomberman", "name": "Bomberman Party Edition", "kind": "emulated",
                     "runtime": {"type": "emulator_profile", "profile": "bomberman", "start": "service",
                                 "entry": "/ps1/bomberman/"},
                     "players": {"min": 1, "max": 4}, "screen": "tv_optional",
                     "input": {"model": "controller_slots", "slots": 4}, "late_join": "supported",
                     "spectators": "watch", "shared_video": True, "private_player_ui": False}
        wordrush = {"manifest": 0, "id": "wordrush", "name": "WORD RUSH", "kind": "native",
                    "runtime": {"type": "lan_games_module", "start": "always_on", "entry": "/games/wordrush/"},
                    "players": {"min": 1, "max": 12}, "screen": "no_tv_needed", "input": {"model": "browser_native"},
                    "late_join": "spectator_only", "spectators": "watch"}
        for m in (gauntlet, bomberman, wordrush):
            doc, grant = game.lift_manifest_v0(m)
            c = game.validate(doc, VOCAB)
            self.assertEqual(c['id'], m['id'])
            self.assertEqual(grant['entry'], m['runtime']['entry'])
            self.assertNotIn('entry', c['runtime'])
        lifted, _ = game.lift_manifest_v0(gauntlet)
        self.assertEqual(game.validate(lifted, VOCAB)['presentations'][0]['method'], 'shared_stream')


class ApplianceAndCatalog(unittest.TestCase):
    def setUp(self):
        self.appliance = appliance.load(APPLIANCE, VOCAB)
        self.contracts = catalog.load_contracts(GAMES, VOCAB)

    def test_runtime_capabilities_follow_provider_status(self):
        live = appliance.runtime_capabilities(self.appliance)
        self.assertIn('presentation.shared_stream', live)
        self.assertNotIn('presentation.personal_viewport.crop', live)
        lab = appliance.runtime_capabilities(self.appliance, ('live', 'experiment'))
        self.assertIn('presentation.personal_viewport.crop', lab)

    def test_committed_catalog_is_fresh(self):
        out = subprocess.run([sys.executable, '-m', 'avrana.contracts.catalog', '--check'], cwd=REPO_ROOT,
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_catalog_shape(self):
        built = catalog.build(VOCAB, self.appliance, self.contracts)
        self.assertEqual(built['schema'], 'avrana.catalog/v0')
        installed = [g for g in built['games'] if g['installed']]
        self.assertEqual([g['id'] for g in installed], ['arcade-gauntlet2'])
        self.assertEqual(installed[0]['entry'], '/arcade/')
        bomber = next(g for g in built['games'] if g['id'] == 'ps1-bomberman')
        tv = next(p for p in bomber['presentations'] if p['id'] == 'tv_controller')
        self.assertFalse(tv['available'])
        self.assertEqual(tv['runtimeMissing'], ['presentation.tv'])
        for name in built['labels']:
            self.assertTrue(name in VOCAB.device or name in VOCAB.runtime)

    def test_grants_are_checked(self):
        doc = copy.deepcopy(self.appliance)
        doc['installed'].append({'game': 'ghost', 'entry': '/ghost/', 'tier': 'builtin'})
        with self.assertRaises(ValueError):
            catalog.build(VOCAB, doc, self.contracts)
        doc = copy.deepcopy(self.appliance)
        doc['installed'][0]['permissions_granted'].append('internet')
        with self.assertRaisesRegex(ValueError, 'never requested'):
            catalog.build(VOCAB, doc, self.contracts)
        doc = copy.deepcopy(self.appliance)
        doc['providers'] = [p for p in doc['providers'] if p['id'] != 'shared-webrtc']
        with self.assertRaisesRegex(ValueError, 'cannot present'):
            catalog.build(VOCAB, doc, self.contracts)
        for bad in ({'entry': '/party/x/'}, {'entry': 'http://evil/'}, {'entry': '/a/../b/'}, {'tier': 'god'}):
            doc = copy.deepcopy(self.appliance)
            doc['installed'][0].update(bad)
            with self.assertRaises(ValueError):
                appliance.validate(doc, VOCAB)

    def test_adapters_named_in_the_profile_exist_and_agree(self):
        for prov in self.appliance['providers']:
            if not prov.get('adapter'):
                continue
            module, cls = prov['adapter'].split(':')
            info = getattr(importlib.import_module(module), cls).info
            self.assertEqual(info.id, prov['id'])
            self.assertEqual(info.kind, prov['kind'])
            self.assertEqual(sorted(info.offers), sorted(prov['offers']))


if __name__ == '__main__':
    unittest.main()
