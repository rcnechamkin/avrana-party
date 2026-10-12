"""The deployment manifest (avrana.ops.manifest): observation, validation, atomic write, CLI."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from avrana.contracts import party_games
from avrana.ops import manifest

SHA_A = 'a' * 40
SHA_B = 'b' * 40


def git_repo(root, name):
    repo = Path(root) / name
    repo.mkdir()
    env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@x', GIT_COMMITTER_NAME='t',
               GIT_COMMITTER_EMAIL='t@x', GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
    def run(*args):
        subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, env=env)
    run('init', '-q', '-b', 'main')
    (repo / 'file').write_text('one\n')
    run('add', 'file')
    run('commit', '-q', '-m', 'one')
    return repo


def sample(**over):
    doc = manifest.build({'sha': SHA_A, 'short': SHA_A[:12], 'dirty': False, 'ref': 'main', 'checkout': '/p'},
                         {'sha': SHA_B, 'short': SHA_B[:12], 'dirty': False, 'ref': None, 'checkout': '/g'},
                         {'path': '/w/releases/x', 'build': 'aaaaaaaaaaaa', 'commit': SHA_A},
                         restarted=['avrana-party-core'], deployed_by='cody', now='2026-10-03T00:00:00Z')
    doc.update(over)
    return doc


class Observation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_observes_sha_branch_and_cleanliness(self):
        repo = git_repo(self.temp.name, 'party')
        seen = manifest.observe_checkout(repo)
        self.assertRegex(seen['sha'], r'^[0-9a-f]{40}$')
        self.assertEqual(seen['short'], seen['sha'][:12])
        self.assertEqual(seen['ref'], 'main')
        self.assertFalse(seen['dirty'])
        (repo / 'stray').write_text('new\n')
        seen = manifest.observe_checkout(repo)
        self.assertEqual((seen['dirty'], seen['untracked']), (False, 1))   # untracked is counted, not "dirty"
        (repo / 'file').write_text('two\n')
        seen = manifest.observe_checkout(repo)
        self.assertEqual((seen['dirty'], seen['untracked']), (True, 1))

    def test_detached_checkout_has_no_ref(self):
        repo = git_repo(self.temp.name, 'games')
        sha = manifest.observe_checkout(repo)['sha']
        subprocess.run(['git', '-C', str(repo), 'checkout', '-q', '--detach', sha], check=True, capture_output=True)
        self.assertIsNone(manifest.observe_checkout(repo)['ref'])

    def test_not_a_checkout_is_an_error(self):
        with self.assertRaises(manifest.ManifestError):
            manifest.observe_checkout(Path(self.temp.name) / 'missing')

    def test_web_release_reads_version_json(self):
        root = Path(self.temp.name) / 'web'
        release = root / 'releases' / '20260101T000000Z-abc'
        release.mkdir(parents=True)
        (release / 'version.json').write_text(json.dumps({'build': 'abc', 'commit': SHA_A}))
        self.assertIsNone(manifest.observe_web_release(root))
        try:
            os.symlink(release, root / 'current', target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('symlinks unavailable here')
        seen = manifest.observe_web_release(root)
        self.assertEqual((seen['build'], seen['commit']), ('abc', SHA_A))


class Validation(unittest.TestCase):
    def test_sample_is_valid_and_carries_the_contract(self):
        doc = sample()
        self.assertEqual(manifest.validate(doc), [])
        self.assertEqual(doc['contract'], party_games.versions())
        self.assertEqual(doc['smoke'], {'status': 'pending', 'at': None})

    def test_rejects_bad_shapes_with_named_fields(self):
        cases = {
            'schema': 'nope', 'deployed_at': '2026-10-03', 'deployed_by': '',
            'party': {'sha': 'short'}, 'games': dict(sample()['games'], dirty='no'),
            'contract': {'party_games': 'x'}, 'restarted': 'avrana-party-core',
            'smoke': {'status': 'maybe', 'at': None}, 'web_release': 'str',
        }
        for field, value in cases.items():
            errors = manifest.validate(sample(**{field: value}))
            self.assertTrue(errors, field)
            self.assertTrue(any(field.split('.')[0] in e for e in errors), (field, errors))

    def test_secret_looking_text_is_refused(self):
        self.assertTrue(manifest.validate(sample(deployed_by='token=abc')))


class Files(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'state' / 'deployment.json'

    def test_write_read_roundtrip_and_smoke_update(self):
        manifest.write(self.path, sample())
        self.assertFalse(self.path.with_name('deployment.json.new').exists())
        doc = manifest.read(self.path)
        self.assertEqual(doc['party']['sha'], SHA_A)
        manifest.record_smoke(self.path, 'passed', now='2026-10-03T00:01:00Z')
        self.assertEqual(manifest.read(self.path)['smoke'], {'status': 'passed', 'at': '2026-10-03T00:01:00Z'})
        if os.name == 'posix':
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o644)

    def test_the_nginx_site_and_the_flags_are_recorded_additively_and_validated(self):
        """AVR-271: which site file is live (its hash), and every flag the deployment ran with."""
        manifest.write(self.path, sample())
        doc = manifest.read(self.path)
        self.assertNotIn('nginx_site', doc)                                  # older manifests stay valid
        self.assertNotIn('deploy_options', doc)
        digest = 'ab' * 32
        manifest.record_deploy_info(self.path, 'installed', digest, ['skip_smoke', 'force_busy'], 'auto',
                                    now='2026-10-12T00:00:00Z')
        doc = manifest.read(self.path)
        self.assertEqual(doc['nginx_site'], {'status': 'installed', 'sha256': digest, 'at': '2026-10-12T00:00:00Z'})
        self.assertEqual({k for k, v in doc['deploy_options'].items() if v is True}, {'skip_smoke', 'force_busy'})
        self.assertEqual(doc['deploy_options']['rollback'], 'auto')
        self.assertEqual(set(doc['deploy_options']) - {'rollback'}, set(manifest.OPTION_NAMES))
        for bad in (dict(doc, nginx_site={'status': 'maybe', 'sha256': None, 'at': '2026-10-12T00:00:00Z'}),
                    dict(doc, nginx_site={'status': 'installed', 'sha256': 'xyz', 'at': '2026-10-12T00:00:00Z'}),
                    dict(doc, deploy_options={'skip_smoke': 'yes'}),
                    dict(doc, deploy_options={'rollback': 'sideways'}),
                    dict(doc, deploy_options={'invented': True})):
            self.assertTrue(manifest.validate(bad), bad)
        self.assertEqual(manifest.main(['deploy-info', str(self.path), '--nginx-status', 'skipped',
                                        '--option', 'skip_nginx_site', '--option', 'no_auto_rollback']), 0)
        doc = manifest.read(self.path)
        self.assertEqual((doc['nginx_site']['status'], doc['nginx_site']['sha256']), ('skipped', None))
        self.assertTrue(doc['deploy_options']['skip_nginx_site'] and doc['deploy_options']['no_auto_rollback'])
        self.assertIsNone(doc['deploy_options']['rollback'])

    def test_the_contract_check_is_recorded_additively_and_validated(self):
        manifest.write(self.path, sample())
        self.assertNotIn('contract_check', manifest.read(self.path))       # older manifests stay valid
        for status in manifest.CONTRACT_CHECK_STATES:
            manifest.record_contract_check(self.path, status, now='2026-10-12T00:00:00Z')
            self.assertEqual(manifest.read(self.path)['contract_check'],
                             {'status': status, 'at': '2026-10-12T00:00:00Z'})
        with self.assertRaises(manifest.ManifestError):
            manifest.record_contract_check(self.path, 'fine')
        bad = dict(sample(), contract_check={'status': 'maybe', 'at': None})
        self.assertTrue(any('contract_check' in e for e in manifest.validate(bad)))
        self.assertEqual(manifest.main(['contract-check', str(self.path), 'skipped']), 0)
        self.assertEqual(manifest.read(self.path)['contract_check']['status'], 'skipped')

    def test_missing_is_none_and_malformed_is_an_error(self):
        self.assertIsNone(manifest.read(self.path))
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"schema": "avrana.deployment/v0"}')
        with self.assertRaises(manifest.ManifestError):
            manifest.read(self.path)
        self.path.write_text('not json')
        with self.assertRaises(manifest.ManifestError):
            manifest.read(self.path)

    def test_write_refuses_invalid(self):
        with self.assertRaises(manifest.ManifestError):
            manifest.write(self.path, sample(schema='x'))
        self.assertFalse(self.path.exists())


class Cli(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.party = git_repo(self.temp.name, 'party')
        self.games = git_repo(self.temp.name, 'games')
        self.out = Path(self.temp.name) / 'deployment.json'

    def run_cli(self, *args):
        return subprocess.run(['python' if os.name == 'nt' else 'python3', '-m', 'avrana.ops.manifest', *args],
                              capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[2]))

    def test_write_validate_and_dirty_refusal(self):
        r = self.run_cli('write', '--out', str(self.out), '--party', str(self.party), '--games', str(self.games),
                         '--web-root', str(Path(self.temp.name) / 'nope'), '--restarted', 'nginx')
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = manifest.read(self.out)
        self.assertEqual(doc['restarted'], ['nginx'])
        self.assertIsNone(doc['web_release'])
        self.assertEqual(self.run_cli('validate', str(self.out)).returncode, 0)
        (self.games / 'file').write_text('dirty\n')
        r = self.run_cli('write', '--out', str(self.out), '--party', str(self.party), '--games', str(self.games))
        self.assertEqual(r.returncode, 1)
        self.assertIn('uncommitted', r.stderr)
        r = self.run_cli('write', '--out', str(self.out), '--party', str(self.party), '--games', str(self.games),
                         '--allow-dirty', '--web-root', str(Path(self.temp.name) / 'nope'))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(manifest.read(self.out)['games']['dirty'])

    def test_validate_names_the_missing_manifest(self):
        r = self.run_cli('validate', str(self.out))
        self.assertEqual(r.returncode, 1)
        self.assertIn('no deployment manifest', r.stderr)


if __name__ == '__main__':
    unittest.main()
