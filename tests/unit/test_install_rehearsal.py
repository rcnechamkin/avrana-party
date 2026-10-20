"""tools/install_rehearsal.py (AVR-676, EXPERIMENTAL): the disposable install rehearsal drives the
real install-game against a scratch root, on any OS.

    python -m unittest discover -s tests/unit -p test_install_rehearsal.py
"""
import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path

from avrana import REPO_ROOT
from avrana.avrgame import installed

from test_avrgame_package import good_manifest, make_zip, mjson

spec = importlib.util.spec_from_file_location('install_rehearsal', REPO_ROOT / 'tools/install_rehearsal.py')
rehearsal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rehearsal)


def package(tmp, game_id):
    m = good_manifest()
    m['game'] = copy.deepcopy(m['game'])
    m['game']['id'] = game_id
    path = Path(tmp) / f'{game_id}.avrgame'
    path.write_bytes(make_zip(manifest=mjson(m)))
    return path


class Rehearsal(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name

    def test_every_step_passes_for_a_good_package(self):
        owner = installed.EXPECTED_OWNER
        report = rehearsal.rehearse(package(self.tmp, 'sparkle'), ['party_roster'])
        self.assertTrue(report['ok'], [s for s in report['steps'] if s['result'] != 'PASS'])
        self.assertEqual(len(report['steps']), 11)
        self.assertEqual(report['id'], 'sparkle')
        self.assertIn('reload avrana-party-core.service', ' '.join(' '.join(c) for c in report['systemctl']))
        self.assertTrue(report['not_reproduced'])
        self.assertEqual(installed.EXPECTED_OWNER, owner)                 # restored
        self.assertTrue(report['root'].endswith('(deleted)'))

    def test_a_first_party_id_stops_at_the_dry_run(self):
        report = rehearsal.rehearse(package(self.tmp, 'hello'), ['party_roster'])
        self.assertFalse(report['ok'])
        self.assertEqual([s['result'] for s in report['steps']], ['FAIL'])

    def test_keep_leaves_the_root(self):
        keep = Path(self.tmp) / 'kept'
        report = rehearsal.rehearse(package(self.tmp, 'sparkle'), ['party_roster'], keep=keep)
        self.assertTrue(report['ok'])
        self.assertTrue((keep / 'root/etc/avrana-party/party-core.json').is_file())
        self.assertFalse((keep / 'root/opt/avrana-games/sparkle').exists())  # removed by the last step

    def test_main_exit_codes(self):
        self.assertEqual(rehearsal.main([str(Path(self.tmp) / 'missing.avrgame')]), 2)


if __name__ == '__main__':
    unittest.main()
