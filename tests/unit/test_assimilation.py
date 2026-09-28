"""Cloud-safe donor normalization, installation boundary and PS1 metadata tests."""
import copy
import unittest

from avrana import CONTRACTS_DIR
from avrana.contracts import appliance, catalog, game, lan_catalog, provider_metadata, strictjson, vocabulary

VOCAB = vocabulary.load()


class DonorCatalog(unittest.TestCase):
    def setUp(self):
        self.source = strictjson.load_path(CONTRACTS_DIR / 'catalogs/lan-games.json')

    def test_known_library_is_individual_valid_contracts(self):
        games = lan_catalog.parse(self.source, VOCAB)
        self.assertEqual(len(games), 30)
        self.assertIn('lan-wordclash', games)
        self.assertNotIn('lan-template', games)
        self.assertNotIn('lan-bluff', games)
        self.assertEqual(games['lan-chess']['players'], {'min': 1, 'max': 2})
        self.assertEqual(games['lan-fifthsignal']['screen'], 'tv_required')
        for cid, contract in games.items():
            self.assertEqual(game.validate(contract, VOCAB), contract)
            self.assertNotIn('entry', contract)
            self.assertNotIn('launchTarget', contract['extensions']['net.avrana.catalog'])
            self.assertEqual(contract['extensions']['net.avrana.catalog']['legacySlug'], ('bluff' if cid == 'bluff' else cid[4:]))

    def test_bad_or_authority_bearing_metadata_is_rejected(self):
        for key, value in [('slug', '../party'), ('min_p', True), ('max_p', 99),
                           ('tv', 'yes'), ('entry', '/evil/'), ('requires', ['camera']),
                           ('title', '<invalid>\x00'), ('launch', '//outside.test/'), ('id', 'invented'), ('accent', 'bad')]:
            doc = copy.deepcopy(self.source)
            doc['games'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                lan_catalog.parse(doc, VOCAB)
        doc = copy.deepcopy(self.source)
        doc['games'].append(doc['games'][0])
        with self.assertRaises(ValueError):
            lan_catalog.parse(doc, VOCAB)

    def test_catalog_carries_multiple_providers_without_ps1_grants(self):
        contracts = catalog.load_contracts(CONTRACTS_DIR / 'games', VOCAB)
        ap = appliance.load(CONTRACTS_DIR / 'appliances/avrana-pi4.json', VOCAB)
        result = catalog.build(VOCAB, ap, contracts)
        self.assertEqual({g['provider'] for g in result['games']},
                         {'lan-games', 'arcade', 'retroarch-ps1'})
        self.assertEqual(result['collections'], [])
        installed = [g for g in result['games'] if g['installed']]
        self.assertEqual(len(installed), 31)
        self.assertEqual(next(g for g in installed if g['id'] == 'lan-chess')['entry'], '/games/chess/')
        # BLUFF is live in the Games fork; the appliance grants it under its own ID.
        bluff = next(g for g in installed if g['id'] == 'bluff')
        self.assertEqual((bluff['entry'], bluff['launchTarget'], bluff['status']),
                         ('/games/bluff/', '/games/bluff/', 'current'))
        self.assertEqual(bluff['integration'], 'avrana.lan-launch/v1')
        self.assertTrue(bluff['private_player_ui'])
        for cid in ('ps1-bomberman', 'ps1-worms'):
            entry = next(g for g in result['games'] if g['id'] == cid)
            self.assertFalse(entry['installed'])
            self.assertIsNone(entry['entry'])
            self.assertEqual(entry['status'], 'experimental')
            self.assertTrue(entry['hardwareValidationRequired'])
            crop = next(p for p in entry['presentations'] if p['method'] == 'personal_viewport')
            self.assertFalse(crop['available'])


class PS1Metadata(unittest.TestCase):
    def test_authoritative_title_facts(self):
        for cid, serial, slots, model in [('ps1-bomberman', 'SLUS-01189', 4, 'controller_slots'),
                                          ('ps1-worms', 'SLUS-00888', 1, 'hotseat')]:
            c = game.load(CONTRACTS_DIR / 'games' / (cid + '.json'), VOCAB)
            self.assertEqual(provider_metadata.ps1(c),
                             {'profile': cid[4:], 'serial': serial, 'streamSlots': slots})
            self.assertEqual(c['input']['model'], model)
            self.assertEqual(c['players']['max'], 4)

    def test_metadata_is_not_an_unchecked_install_hook(self):
        c = game.load(CONTRACTS_DIR / 'games/ps1-worms.json', VOCAB)
        for key, value in [('stream_slots', 4), ('stream_slots', True),
                           ('serial', 'invented'), ('cue', '/roms/private.cue'),
                           ('entry', '/ps1/worms/')]:
            bad = copy.deepcopy(c)
            bad['extensions']['net.avrana.ps1'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                provider_metadata.ps1(bad)
