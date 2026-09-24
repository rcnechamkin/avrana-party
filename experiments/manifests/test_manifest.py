"""Manifest v0 validator tests (stdlib only).   python experiments/manifests/test_manifest.py"""
import copy
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import manifest as mf  # noqa: E402

GOOD = {'manifest': 0, 'id': 'demo', 'name': 'Demo', 'kind': 'native',
        'runtime': {'type': 'lan_games_module', 'entry': '/games/demo/'},
        'players': {'min': 2, 'max': 6}, 'screen': 'no_tv_needed',
        'input': {'model': 'browser_native'}}


def with_(path, value):
    m = copy.deepcopy(GOOD)
    *parents, last = path.split('.')
    node = m
    for p in parents:
        node = node[p]
    if value is KeyError:
        del node[last]
    else:
        node[last] = value
    return m


class Validate(unittest.TestCase):
    def test_minimal_manifest_gets_defaults(self):
        m = mf.validate(GOOD)
        self.assertEqual((m['late_join'], m['spectators'], m['runtime']['start']),
                         ('spectator_only', 'watch', 'always_on'))
        self.assertEqual(set(m['accessibility'].values()), {'unknown'})   # nobody is forced to guess

    def test_rejections(self):
        bad = {
            'unknown top key': with_('teams', 'none'),
            'missing required': with_('screen', KeyError),
            'version': with_('manifest', 1),
            'bool as version': with_('manifest', False),
            'id pattern': with_('id', 'Demo'),
            'reserved id': with_('id', 'party'),
            'bad enum': with_('screen', 'tv'),
            'min > max': with_('players', {'min': 5, 'max': 2}),
            'bool as int': with_('players', {'min': True, 'max': 4}),
            'too many players': with_('players', {'min': 1, 'max': 99}),
            'slots on browser_native': with_('input', {'model': 'browser_native', 'slots': 2}),
            'no slots for controller_slots': with_('input', {'model': 'controller_slots'}),
            'native with emulator profile': with_('runtime', {'type': 'emulator_profile', 'profile': 'x', 'start': 'service', 'entry': None}),
            'profile without emulator': with_('runtime.profile', 'bomberman'),
            'viewports format is open': with_('personal_viewports', {'layouts': {}}),
            'a11y must be tri-state': with_('accessibility', {'timing_pressure': 1}),
            'unknown a11y key': with_('accessibility', {'sparkles': True}),
            'name too long': with_('name', 'x' * 61),
            'shared_video not bool': with_('shared_video', 'yes'),
        }
        for why, m in bad.items():
            with self.subTest(why), self.assertRaises(mf.ManifestError):
                mf.validate(m)

    def test_entries_must_be_safe_same_origin_paths(self):
        for entry in ('https://evil.example/', '//evil.example/', '/games/../party/', '/games/x',
                      '/games/x/?a=1', '/games/%2e%2e/', '/party/', '/shared/x/', '/games/x/#y',
                      'games/x/', '/Games/X/', '/games/.hidden/', '\\\\host\\x\\'):
            with self.subTest(entry), self.assertRaises(mf.ManifestError):
                mf.validate(with_('runtime.entry', entry))
        self.assertEqual(mf.validate(with_('runtime.entry', '/'))['runtime']['entry'], '/')
        self.assertIsNone(mf.validate(with_('runtime.entry', None))['runtime']['entry'])

    def test_strict_json(self):
        for text in ('{"id": "a", "id": "b"}', '{"x": NaN}', '[1, 2]', '{bad'):
            with self.subTest(text), self.assertRaises(mf.ManifestError):
                m = mf.parse(text)
                mf.validate(m)


class Sources(unittest.TestCase):
    def test_builtin_manifests_load(self):
        ms = {m['id']: m for m in mf.load_builtin()}
        self.assertEqual(set(ms), {'arcade-gauntlet2', 'ps1-bomberman', 'ps1-worms'})
        self.assertEqual(ms['ps1-worms']['input'], {'model': 'hotseat', 'slots': 1})
        self.assertIsNone(ms['ps1-bomberman']['runtime']['entry'])   # no nginx location yet: not selectable

    def test_file_name_must_match_id(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'other.json')
            with open(p, 'w', encoding='utf-8') as f:
                json.dump(GOOD, f)
            with self.assertRaises(mf.ManifestError):
                mf.load_file(p)

    def test_lan_titles_are_derived_not_handwritten(self):
        with open(os.path.join(HERE, 'fixtures', 'api-games.sample.json'), encoding='utf-8') as f:
            api = json.load(f)
        ms, problems = mf.derive_lan(api, mf.load_overlay())
        by = {m['id']: m for m in ms}
        self.assertNotIn('_template', by)                       # hidden titles are skipped
        self.assertEqual(problems, ['mystery: no min_p/max_p in the registry'])   # reported, not guessed
        self.assertEqual(by['smelterskelter']['screen'], 'tv_required')
        self.assertEqual(by['bluff']['players'], {'min': 1, 'max': 6})
        self.assertTrue(by['bluff']['private_player_ui'])        # from the overlay
        self.assertEqual(by['bluff']['accessibility']['audio_required'], False)
        self.assertEqual(by['wordclash']['runtime'], {'type': 'external', 'start': 'always_on', 'entry': '/games/wordclash/'})

    def test_hostile_registry_url_is_refused(self):
        api = {'games': [], 'external': [{'slug': 'evil', 'title': 'Evil', 'min_p': 1, 'max_p': 2,
                                          'url': 'http://evil.example/'}]}
        ms, problems = mf.derive_lan(api)
        self.assertEqual(ms, [])
        self.assertTrue(problems and problems[0].startswith('evil:'))

    def test_catalog_for_the_party_service(self):
        with open(os.path.join(HERE, 'fixtures', 'api-games.sample.json'), encoding='utf-8') as f:
            lan, _ = mf.derive_lan(json.load(f), mf.load_overlay())
        cat = {c['id']: c for c in mf.catalog(mf.load_builtin() + lan)}
        self.assertNotIn('ps1-bomberman', cat)                  # entry null: not reachable yet
        self.assertEqual(cat['arcade-gauntlet2']['max_players'], 2)     # seats = controller slots
        self.assertTrue(cat['arcade-gauntlet2']['open_seat'])
        self.assertEqual(cat['bluff']['href'], '/games/bluff/')
        self.assertEqual(cat['wordrush']['launch'], 'always_on')
        with self.assertRaises(mf.ManifestError):
            mf.catalog(lan + lan)                               # duplicate ids

    def test_ps1_manifests_agree_with_title_profiles(self):
        repo = os.path.dirname(os.path.dirname(HERE))
        titles = os.path.join(repo, 'ps1', 'titles')
        ms = mf.load_builtin()
        if os.path.isdir(titles):                               # the PS1 branch: check the real files
            self.assertEqual(mf.cross_check_ps1(ms, titles), [])
            return
        with tempfile.TemporaryDirectory() as d:                # elsewhere: the same data, inline
            for name, slots in (('bomberman', 4), ('worms', 1)):
                with open(os.path.join(d, name + '.json'), 'w', encoding='utf-8') as f:
                    json.dump({'id': name, 'stream_slots': slots}, f)
            self.assertEqual(mf.cross_check_ps1(ms, d), [])
            with open(os.path.join(d, 'worms.json'), 'w', encoding='utf-8') as f:
                json.dump({'id': 'worms', 'stream_slots': 2}, f)
            self.assertTrue(mf.cross_check_ps1(ms, d))
            with open(os.path.join(d, 'tekken.json'), 'w', encoding='utf-8') as f:
                json.dump({'id': 'tekken', 'stream_slots': 2}, f)
            self.assertIn("profile 'tekken' has no manifest", mf.cross_check_ps1(ms, d))


if __name__ == '__main__':
    unittest.main(verbosity=1)
