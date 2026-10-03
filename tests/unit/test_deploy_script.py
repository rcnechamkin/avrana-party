"""ops/deploy.sh: argument validation and a dry run against throwaway checkouts. The real thing
runs as root on the Pi (docs/runbooks/deploy.md); nothing here touches services."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from avrana import REPO_ROOT

SCRIPT = REPO_ROOT / 'ops/deploy.sh'
BASH = shutil.which('bash')


def git_repo(root, name, with_origin=False):
    env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@x', GIT_COMMITTER_NAME='t',
               GIT_COMMITTER_EMAIL='t@x', GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
    def run(repo, *args):
        return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, env=env).stdout.decode().strip()
    origin = Path(root) / f'{name}-origin.git'
    repo = Path(root) / name
    if with_origin:
        subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(origin)], check=True, env=env)
        subprocess.run(['git', 'clone', '-q', str(origin), str(repo)], check=True, env=env, capture_output=True)
        run(repo, 'checkout', '-q', '-b', 'main')
    else:
        repo.mkdir()
        run(repo, 'init', '-q', '-b', 'main')
    (repo / 'file').write_text('one\n')
    run(repo, 'add', 'file')
    run(repo, 'commit', '-q', '-m', 'one')
    if with_origin:
        run(repo, 'push', '-q', '-u', 'origin', 'main')
    return repo, run(repo, 'rev-parse', 'HEAD'), run


@unittest.skipUnless(BASH, 'bash not available')
class DeployScript(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.party, self.party_sha, self.git = git_repo(self.temp.name, 'party', with_origin=True)
        self.games, self.games_sha, _ = git_repo(self.temp.name, 'games')
        self.env = dict(os.environ, AVRANA_PARTY_CHECKOUT=str(self.party), AVRANA_GAMES_CHECKOUT=str(self.games),
                        AVRANA_PARTY_CORE_URL='http://127.0.0.1:1', AVRANA_CHECKOUT_USER=os.environ.get('USER', 'nobody'),
                        AVRANA_BACKUP_ROOT=str(Path(self.temp.name) / 'backups'))

    def run_script(self, *args):
        return subprocess.run([BASH, str(SCRIPT), *args], capture_output=True, text=True, env=self.env, timeout=120)

    def test_syntax_and_help(self):
        self.assertEqual(subprocess.run([BASH, '-n', str(SCRIPT)], capture_output=True).returncode, 0)
        r = self.run_script('--help')
        self.assertEqual(r.returncode, 0)
        self.assertIn('--party <sha> --games <sha>', r.stdout)

    def test_requires_full_shas(self):
        r = self.run_script('--party', 'abc', '--games', self.games_sha, '--dry-run')
        self.assertEqual(r.returncode, 1)
        self.assertIn('40-character', r.stderr)
        r = self.run_script('--party', self.party_sha, '--dry-run')
        self.assertIn('--games', r.stderr)

    def test_dry_run_plans_without_changing_anything(self):
        r = self.run_script('--party', self.party_sha, '--games', self.games_sha, '--dry-run')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('already at the requested commits', r.stdout)
        self.assertIn('restart nothing', r.stdout)
        self.assertIn('dry run: nothing changed', r.stdout)
        self.assertFalse((Path(self.temp.name) / 'backups').exists())

    def test_dry_run_refuses_dirty_and_unknown_commits(self):
        (self.games / 'file').write_text('dirty\n')
        r = self.run_script('--party', self.party_sha, '--games', self.games_sha, '--dry-run')
        self.assertEqual(r.returncode, 1)
        self.assertIn('uncommitted changes', r.stderr)
        r = self.run_script('--party', self.party_sha, '--games', self.games_sha, '--dry-run', '--allow-dirty')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('WARNING', r.stdout)
        r = self.run_script('--party', self.party_sha, '--games', 'f' * 40, '--dry-run', '--allow-dirty')
        self.assertEqual(r.returncode, 1)
        self.assertIn('stage it first', r.stderr)

    def test_party_commit_must_be_on_origin_main(self):
        (self.party / 'file').write_text('two\n')
        self.git(self.party, 'checkout', '-q', '-b', 'topic')
        self.git(self.party, 'commit', '-q', '-am', 'two')
        topic = self.git(self.party, 'rev-parse', 'HEAD')
        self.git(self.party, 'checkout', '-q', 'main')          # production sits on main; topic is the target
        r = self.run_script('--party', topic, '--games', self.games_sha, '--dry-run')
        self.assertEqual(r.returncode, 1)
        self.assertIn('not on origin/main', r.stderr)
        r = self.run_script('--party', topic, '--games', self.games_sha, '--dry-run', '--allow-branch')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('changed=1', r.stdout)
        self.assertIn('avrana-party-core avranaparty-arcade', r.stdout)


SYSTEMCTL_SHIM = """#!/usr/bin/env bash
# Records every call; `is-active` fails for the unit named in $FAIL_UNIT (to exercise rollback).
echo "$*" >> "$SHIM_LOG"
if [[ $1 == is-active && -n ${FAIL_UNIT:-} && " $* " == *" $FAIL_UNIT "* ]]; then exit 3; fi
exit 0
"""


@unittest.skipUnless(sys.platform == 'linux' and BASH, 'the real deployment path needs Linux (symlinks, install, flock)')
class RealRun(unittest.TestCase):
    """The non-dry path end to end against clones of this repository: checkout at exact commits,
    web release, selective restarts through a recording systemctl, manifest, rollback."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.genv = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@x', GIT_COMMITTER_NAME='t',
                         GIT_COMMITTER_EMAIL='t@x', GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
        # "origin": this repository's HEAD plus one more commit, so there is something to deploy.
        self.origin = root / 'origin'
        self.run_git(root, 'clone', '-q', '--no-local', str(REPO_ROOT), str(self.origin))
        self.run_git(self.origin, 'checkout', '-q', '-B', 'main')
        self.party = root / 'party'
        self.run_git(root, 'clone', '-q', str(self.origin), str(self.party))
        self.before_party = self.run_git(self.party, 'rev-parse', 'HEAD')
        (self.origin / 'deploy-test-marker').write_text('next\n')
        self.run_git(self.origin, 'add', 'deploy-test-marker')
        self.run_git(self.origin, 'commit', '-q', '-m', 'next')
        self.target_party = self.run_git(self.origin, 'rev-parse', 'HEAD')
        self.games, self.before_games, _ = git_repo(root, 'games')
        (self.games / 'file').write_text('two\n')
        self.run_git(self.games, 'commit', '-q', '-am', 'two')
        self.target_games = self.run_git(self.games, 'rev-parse', 'HEAD')
        self.run_git(self.games, 'checkout', '-q', '--detach', self.before_games)
        shim = root / 'systemctl'
        shim.write_text(SYSTEMCTL_SHIM)
        shim.chmod(0o755)
        self.log = root / 'systemctl.log'
        self.manifest_path = root / 'state' / 'deployment.json'
        self.web = root / 'web'
        self.env = dict(self.genv, AVRANA_PARTY_CHECKOUT=str(self.party), AVRANA_GAMES_CHECKOUT=str(self.games),
                        AVRANA_PARTY_CORE_URL='http://127.0.0.1:1', AVRANA_WEB_ROOT=str(self.web),
                        AVRANA_DEPLOYMENT_MANIFEST=str(self.manifest_path), AVRANA_BACKUP_ROOT=str(root / 'backups'),
                        AVRANA_DEPLOY_UNPRIVILEGED='1', AVRANA_SYSTEMCTL=str(shim), SHIM_LOG=str(self.log))

    def run_git(self, repo, *args):
        return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, env=self.genv).stdout.decode().strip()

    def deploy(self, party, games, *flags, **env):
        return subprocess.run([BASH, str(SCRIPT), '--party', party, '--games', games, *flags], capture_output=True,
                              text=True, env=dict(self.env, **env), timeout=300)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_deploys_exact_commits_restarts_what_changed_and_writes_the_manifest(self):
        from avrana.ops import manifest
        r = self.deploy(self.target_party, self.target_games, '--skip-smoke')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.target_party)
        self.assertEqual(self.run_git(self.games, 'rev-parse', 'HEAD'), self.target_games)
        doc = manifest.read(self.manifest_path)
        self.assertEqual((doc['party']['sha'], doc['games']['sha']), (self.target_party, self.target_games))
        self.assertFalse(doc['party']['dirty'] or doc['games']['dirty'])
        self.assertEqual(doc['smoke']['status'], 'skipped')
        self.assertEqual(sorted(doc['restarted']), ['avrana-party-core', 'avranaparty-arcade', 'avranaparty-games'])
        self.assertEqual(doc['web_release']['commit'], self.target_party)
        calls = self.calls()
        stops = [c for c in calls if c.startswith('stop ')]
        starts = [c for c in calls if c.startswith('start ')]
        self.assertEqual(len(stops), 3)
        self.assertEqual(starts, ['start avranaparty-games', 'start avranaparty-arcade', 'start avrana-party-core'])
        self.assertLess(calls.index(stops[-1]), calls.index(starts[0]))
        backups = list((Path(self.temp.name) / 'backups').iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual(manifest.read(backups[0] / 'before.json')['party']['sha'], self.before_party)

    def test_only_the_changed_repository_restarts_and_going_back_is_the_same_operation(self):
        from avrana.ops import manifest
        r = self.deploy(self.before_party, self.target_games, '--skip-smoke')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual([c for c in self.calls() if c.startswith(('stop ', 'start '))],
                         ['stop avranaparty-games', 'start avranaparty-games'])
        self.assertEqual(manifest.read(self.manifest_path)['restarted'], ['avranaparty-games'])
        r = self.deploy(self.before_party, self.before_games, '--skip-smoke')      # roll Games back
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.run_git(self.games, 'rev-parse', 'HEAD'), self.before_games)
        self.assertEqual(manifest.read(self.manifest_path)['games']['sha'], self.before_games)

    def test_a_unit_that_does_not_come_back_rolls_everything_back_and_writes_no_manifest(self):
        r = self.deploy(self.target_party, self.target_games, '--skip-smoke', FAIL_UNIT='avrana-party-core')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('rolling back', r.stdout)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.before_party)
        self.assertEqual(self.run_git(self.party, 'rev-parse', '--abbrev-ref', 'HEAD'), 'main')   # same branch as before
        self.assertEqual(self.run_git(self.games, 'rev-parse', 'HEAD'), self.before_games)
        self.assertFalse(self.manifest_path.exists())
        starts = [c for c in self.calls() if c.startswith('start ')]
        self.assertEqual(len(starts), 6)                    # started once, then again by the rollback

    def test_failed_smoke_is_reported_loudly_and_recorded(self):
        from avrana.ops import manifest
        r = self.deploy(self.target_party, self.target_games)        # nothing listens: smoke must fail
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('smoke FAILED', r.stdout)
        self.assertIn(f'--party {self.before_party} --games {self.before_games}', r.stdout)   # the way back
        self.assertEqual(manifest.read(self.manifest_path)['smoke']['status'], 'failed')

    def test_dry_run_changes_nothing_at_all(self):
        r = self.deploy(self.target_party, self.target_games, '--dry-run')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.before_party)
        self.assertEqual(self.run_git(self.games, 'rev-parse', 'HEAD'), self.before_games)
        self.assertEqual(self.calls(), [])
        self.assertFalse(self.manifest_path.exists() or self.web.exists() or (Path(self.temp.name) / 'backups').exists())


if __name__ == '__main__':
    unittest.main()
