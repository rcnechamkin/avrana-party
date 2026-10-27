"""The owner's shelves (AVR-155): contracts/shelves.json is validated and carried into the catalog as a
placement only. Run: PYTHONPATH=. python tests/unit/test_catalog_shelves.py"""
import json
import tempfile
import unittest
from pathlib import Path

from avrana import CONTRACTS_DIR, WEB_DIR
from avrana.contracts import appliance, catalog, strictjson, vocabulary

VOCAB = vocabulary.load()


def write(doc):
    fh = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8')
    with fh:
        json.dump(doc, fh)
    return Path(fh.name)


class Shelves(unittest.TestCase):
    def load(self, games, schema='avrana.shelves/v0'):
        path = write({'schema': schema, 'games': games})
        try:
            return catalog.load_shelves(path)
        finally:
            path.unlink()

    def test_the_committed_file_is_valid_and_places_nothing_until_the_owner_decides(self):
        self.assertEqual(catalog.load_shelves(), {})       # D1: the recommendations are in the proposal

    def test_a_bad_word_id_or_schema_is_refused(self):
        for games in ({'bluff': 'spotlight'}, {'Bluff': 'lab'}, {'bluff\n': 'lab'}, {'bluff': None}):
            with self.assertRaises(ValueError):
                self.load(games)
        with self.assertRaises(ValueError):
            self.load({'bluff': 'lab'}, schema='avrana.shelves/v1')

    def test_a_package_id_not_in_the_contracts_may_be_placed(self):
        self.assertEqual(self.load({'courting': 'featured', 'bluff': 'lab'}), {'bluff': 'lab', 'courting': 'featured'})

    def test_build_carries_shelves_and_changes_nothing_else(self):
        contracts = catalog.load_contracts(CONTRACTS_DIR / 'games', VOCAB)
        ap = appliance.load(CONTRACTS_DIR / 'appliances/avrana-pi4.json', VOCAB)
        plain = catalog.build(VOCAB, ap, contracts)
        placed = catalog.build(VOCAB, ap, contracts, shelves={'ps1-worms': 'hidden', 'checkers': 'classics'})
        self.assertNotIn('shelves', plain)
        self.assertEqual(placed.pop('shelves'), {'ps1-worms': 'hidden', 'checkers': 'classics'})
        self.assertEqual(placed, plain)          # no row is dropped, moved, installed or edited by a placement

    def test_the_committed_catalog_is_in_step_and_has_no_shelves_while_none_are_placed(self):
        doc = strictjson.load_path(WEB_DIR / 'catalog.json')
        self.assertNotIn('shelves', doc)
        self.assertEqual(catalog.main(['--check']), 0)


if __name__ == '__main__':
    unittest.main()
