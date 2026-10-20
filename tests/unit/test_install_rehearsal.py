"""tools/install_rehearsal.py (AVR-676, EXPERIMENTAL): the disposable install rehearsal drives the
real install-game against a scratch root, on any OS.

    python -m unittest discover -s tests/unit -p test_install_rehearsal.py
"""
import copy
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

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

    # Each check can fail: an installer that misbehaves after the fact is caught, never a crash.
    def misbehave(self, verb, after):
        """Run the rehearsal with `after(root, argv)` called once the installer has done `verb`."""
        real = rehearsal.installer

        def wrapped(argv, run):
            result = real(argv, run)
            if argv[0] == verb and '--dry-run' not in argv:
                after(Path(argv[argv.index('--games-root') + 1]).parent.parent, argv)
            return result
        with mock.patch.object(rehearsal, 'installer', wrapped):
            return rehearsal.rehearse(package(self.tmp, 'sparkle'), ['party_roster'])

    def failed(self, report):
        return [s['step'] for s in report['steps'] if s['result'] == 'FAIL']

    def test_an_empty_directory_left_by_remove_fails(self):
        report = self.misbehave('remove', lambda root, argv: (root / 'opt/avrana-games/sparkle').mkdir())
        self.assertFalse(report['ok'])
        self.assertEqual(len(self.failed(report)), 1)
        self.assertIn('after remove', self.failed(report)[0])

    def test_a_missing_catalog_overlay_fails_without_a_crash(self):
        def drop(root, argv):
            overlay = root / 'var/lib/avrana-party/catalog/catalog.json'
            if overlay.is_file() and 'rollback-root' not in str(root):
                overlay.unlink()
        report = self.misbehave('install', drop)
        self.assertFalse(report['ok'])
        self.assertTrue(any('catalog' in s for s in self.failed(report)))

    def test_a_leftover_after_a_failed_install_fails(self):
        def litter(root, argv):
            if root.name == 'rollback-root':
                (root / 'opt/avrana-games/stray').write_text('x')
        report = self.misbehave('install', litter)
        self.assertEqual(self.failed(report), ['a failed install is undone: the root is exactly as before'])

    def test_main_reports_json_and_exit_1_on_a_failure(self):
        out = io.StringIO()
        with mock.patch.object(rehearsal, 'rehearse', lambda *a: {'ok': False, 'steps': [], 'not_reproduced': []}), \
                redirect_stdout(out):
            self.assertEqual(rehearsal.main([str(package(self.tmp, 'sparkle')), '--json']), 1)
        self.assertFalse(json.loads(out.getvalue())['ok'])


if __name__ == '__main__':
    unittest.main()
