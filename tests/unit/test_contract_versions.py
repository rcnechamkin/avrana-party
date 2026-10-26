"""Contract version shapes and the support window (avrana.ops.contract_versions, AVR-72 V1/V2/V4)."""
import unittest

from avrana.ops import contract_versions as v

DECL = {'current': '1.2', 'min_supported': '1.0'}
WIRE = {'current': '1', 'min_supported': '0'}


class Parse(unittest.TestCase):
    def test_both_shapes(self):
        self.assertEqual(v.parse('avrana.avrgame/1.2'), ('avrgame', 1, 2))
        self.assertEqual(v.parse('avrana.party-session/v0'), ('party-session', 0, None))
        self.assertEqual(v.parse('avrana.game-result/v1'), ('game-result', 1, None))

    def test_todays_contract_strings_parse(self):
        for text in ('avrana.game/v0', 'avrana.party-bridge/v1', 'avrana.party-layer/v1', 'avrana.party-games/v0'):
            self.assertIsNone(v.parse(text)[2], text)

    def test_junk_is_refused(self):
        for bad in ('avrana.game/1', 'avrana.game/v01', 'avrana.Game/v1', 'avrana.game/1.02', 'avrgame/1.2',
                    'avrana.game/v1 ', '', None, 7, 'avrana.game/v99999'):
            with self.assertRaises(v.BadVersion, msg=repr(bad)):
                v.parse(bad)


class Window(unittest.TestCase):
    def test_declarations(self):
        self.assertTrue(v.check('avrana.avrgame/1.0', DECL)[0])
        self.assertTrue(v.check('avrana.avrgame/1.2', DECL)[0])
        ok, words = v.check('avrana.avrgame/1.3', DECL)
        self.assertFalse(ok)
        self.assertIn('needs a newer Party', words)
        self.assertIn('1.0–1.2', words)
        ok, words = v.check('avrana.avrgame/0.9', DECL)
        self.assertFalse(ok)
        self.assertIn('migration note', words)
        self.assertFalse(v.check('avrana.avrgame/2.0', DECL)[0])

    def test_wire_protocols(self):
        self.assertTrue(v.check('avrana.party-session/v0', WIRE)[0])
        self.assertTrue(v.check('avrana.party-session/v1', WIRE)[0])
        self.assertIn('needs a newer Party', v.check('avrana.party-session/v2', WIRE)[1])
        self.assertIn('no longer supported', v.check('avrana.party-session/v0', {'current': '2', 'min_supported': '1'})[1])

    def test_shapes_do_not_mix(self):
        self.assertFalse(v.check('avrana.avrgame/v1', DECL)[0])
        self.assertFalse(v.check('avrana.party-session/1.0', WIRE)[0])


class Features(unittest.TestCase):
    def test_missing_features(self):
        self.assertEqual(v.missing_features(['party_layer', 'artwork'], ['artwork', 'party_layer', 'options']), [])
        self.assertEqual(v.missing_features(['options', 'party_layer'], ['party_layer']), ['options'])
        self.assertEqual(v.missing_features(['Bad Name'], ['Bad Name']), ['Bad Name'])
        self.assertEqual(v.missing_features(None, ['x']), [])


if __name__ == '__main__':
    unittest.main()
