"""ops/deploy.sh: argument validation and a dry run against throwaway checkouts. The real thing
runs as root on the Pi (docs/runbooks/deploy.md); nothing here touches services."""
import json
import os
from pathlib import Path
import shutil
import signal
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
                        AVRANA_BACKUP_ROOT=str(Path(self.temp.name) / 'backups'),
                        AVRANA_NGINX_SITE=str(Path(self.temp.name) / 'site'), AVRANA_DEPLOY_DETACH='0')

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

    @unittest.skipIf(hasattr(os, 'geteuid') and os.geteuid() == 0, 'running as root')
    def test_a_real_run_without_root_is_refused_before_anything_is_touched(self):
        """The service restarts, the web root and the nginx site file all need root: a run that is not
        root (and is not the test-only unprivileged mode) refuses up front instead of half-running."""
        r = self.run_script('--party', self.party_sha, '--games', self.games_sha)
        self.assertEqual(r.returncode, 1)
        self.assertIn('run as root', r.stderr)
        self.assertFalse((Path(self.temp.name) / 'backups').exists())

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

    def commit_pair_files(self, checker_exit):
        """Give the throwaway pair what the real ones have: the checker (Party) and a declaration
        (Games). The stub stands for tools/contract_check.py; the real one is proved in
        test_contract.py against real snapshots."""
        (self.party / 'tools').mkdir()
        (self.party / 'tools/contract_check.py').write_text(
            'import sys\nprint("CONTRACT DRIFT: stub", file=sys.stderr)\nsys.exit(%d)\n' % checker_exit)
        self.git(self.party, 'add', 'tools')
        self.git(self.party, 'commit', '-q', '-m', 'checker')
        self.git(self.party, 'push', '-q', 'origin', 'main')
        (self.games / 'provider').mkdir()
        (self.games / 'provider/avrana-contract.json').write_text('{}\n')
        self.git(self.games, 'add', 'provider')
        self.git(self.games, 'commit', '-q', '-m', 'declaration')
        self.env['AVRANA_DEPLOY_PYTHON'] = sys.executable
        return self.git(self.party, 'rev-parse', 'HEAD'), self.git(self.games, 'rev-parse', 'HEAD')

    def test_a_pair_that_disagrees_on_the_contract_is_refused_before_anything_changes(self):
        """Party <-> Games skew (AVR-336): the exact pair about to be deployed is checked with
        tools/contract_check.py, in the dry run too, instead of failing at runtime."""
        party_sha, games_sha = self.commit_pair_files(checker_exit=1)
        r = self.run_script('--party', party_sha, '--games', games_sha, '--dry-run')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('Party <-> Games contract', r.stderr)
        self.assertIn('--skip-contract-check', r.stderr)
        self.assertNotIn('dry run: nothing changed', r.stdout)
        r = self.run_script('--party', party_sha, '--games', games_sha, '--dry-run', '--skip-contract-check')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('WARNING', r.stdout)

    def test_a_pair_that_agrees_passes_and_a_pair_that_predates_the_checker_is_warned_about(self):
        party_sha, games_sha = self.commit_pair_files(checker_exit=0)
        r = self.run_script('--party', party_sha, '--games', games_sha, '--dry-run')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('contract: compatible', r.stdout)
        r = self.run_script('--party', self.party_sha, '--games', self.games_sha, '--dry-run')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('predates the contract check', r.stdout)

    def test_a_rollback_to_a_pair_that_predates_the_checker_warns_and_is_not_refused(self):
        """Going back to commits from before tools/contract_check.py existed must stay possible,
        even though the checker of the newer commit would fail: the old pair is warned about."""
        party_sha, games_sha = self.commit_pair_files(checker_exit=1)
        for old_party, old_games in ((self.party_sha, self.games_sha),      # both predate
                                     (party_sha, self.games_sha),           # only Games predates
                                     (self.party_sha, games_sha)):          # only Party predates
            r = self.run_script('--party', old_party, '--games', old_games, '--dry-run')
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn('predates the contract check', r.stdout)

    def test_the_temporary_pair_directory_is_removed_when_the_archive_fails(self):
        """A commit whose object is missing makes `git archive` fail: the run stops, and nothing
        is left behind in the temporary directory."""
        party_sha, games_sha = self.commit_pair_files(checker_exit=0)
        tmp = Path(self.temp.name) / 'tmp'
        tmp.mkdir()
        self.env['TMPDIR'] = str(tmp)
        blob = self.git(self.games, 'rev-parse', f'{games_sha}:provider/avrana-contract.json')
        loose = self.games / '.git/objects' / blob[:2] / blob[2:]
        self.assertTrue(loose.exists())
        os.chmod(loose, 0o644)
        loose.unlink()
        r = self.run_script('--party', party_sha, '--games', games_sha, '--dry-run', '--allow-dirty')
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn('dry run: nothing changed', r.stdout)
        self.assertEqual(list(tmp.iterdir()), [])


SYSTEMCTL_SHIM = """#!/usr/bin/env bash
# Records every call. `is-active` fails for the unit named in $FAIL_UNIT (a unit that does not come
# back); `start` and `restart` fail for the unit named in $FAIL_START (a unit that will not start).
echo "$*" >> "$SHIM_LOG"
if [[ $1 == is-active && -n ${FAIL_UNIT:-} && " $* " == *" $FAIL_UNIT "* ]]; then exit 3; fi
if [[ $1 == start || $1 == restart ]] && [[ -n ${FAIL_START:-} && " $* " == *" $FAIL_START "* ]]; then exit 1; fi
# $FAIL_RELOAD=once: the first `reload` fails, later ones work; =always: every one fails.
if [[ $1 == reload && -n ${FAIL_RELOAD:-} ]]; then
    if [[ $FAIL_RELOAD == always ]]; then exit 1; fi
    if [[ ! -e "$SHIM_LOG.reload-failed" ]]; then : > "$SHIM_LOG.reload-failed"; exit 1; fi
fi
exit 0
"""

# Stands for the smoke checks (AVRANA_DEPLOY_SMOKE): each call consumes the first line of $SMOKE_QUEUE
# (`pass` or `fail`); an empty queue fails.
SMOKE_STUB = """#!/usr/bin/env bash
line=$(head -n1 "$SMOKE_QUEUE"); sed -i 1d "$SMOKE_QUEUE"
echo "smoke stub: ${line:-fail}"
[[ $line == pass ]]
"""

# Stands for nginx: `-t` rejects a site file that contains FAKE-NGINX-REJECT the way the real one rejects a
# site that names a certificate file this appliance does not have.
NGINX_SHIM = """#!/usr/bin/env bash
echo "nginx $*" >> "$NGINX_LOG"
if [[ $1 == -t ]]; then
    if grep -q FAKE-NGINX-REJECT "$AVRANA_NGINX_SITE"; then
        echo 'nginx: [emerg] cannot load certificate "/etc/avrana-party/tls/games/fullchain.pem": BIO_new_file() failed (No such file or directory)' >&2
        echo 'nginx: configuration file /etc/nginx/nginx.conf test failed' >&2
        exit 1
    fi
    echo 'nginx: configuration file /etc/nginx/nginx.conf test is successful' >&2
fi
exit 0
"""


@unittest.skipUnless(sys.platform == 'linux' and BASH, 'the real deployment path needs Linux (symlinks, install, flock)')
class Harness(unittest.TestCase):
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
        with open(self.origin / 'avrana-party.nginx', 'a', newline='') as site:    # the target's site file differs
            site.write('# deploy test: the next commit\n')
        self.run_git(self.origin, 'add', 'deploy-test-marker', 'avrana-party.nginx')
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
        nginx = root / 'fake-nginx'
        nginx.write_text(NGINX_SHIM)
        nginx.chmod(0o755)
        (root / 'nginx').mkdir()
        self.site = root / 'nginx' / 'avrana-party'                  # what is live: the site file of before_party
        self.site.write_bytes(subprocess.run(['git', '-C', str(self.party), 'show', f'{self.before_party}:avrana-party.nginx'],
                                             check=True, capture_output=True, env=self.genv).stdout)
        self.site_before = self.site.read_bytes()
        self.nginx_log = root / 'nginx.log'
        self.manifest_path = root / 'state' / 'deployment.json'
        self.web = root / 'web'
        self.env = dict(self.genv, AVRANA_PARTY_CHECKOUT=str(self.party), AVRANA_GAMES_CHECKOUT=str(self.games),
                        AVRANA_PARTY_CORE_URL='http://127.0.0.1:1', AVRANA_WEB_ROOT=str(self.web),
                        AVRANA_DEPLOYMENT_MANIFEST=str(self.manifest_path), AVRANA_BACKUP_ROOT=str(root / 'backups'),
                        AVRANA_DEPLOY_UNPRIVILEGED='1', AVRANA_SYSTEMCTL=str(shim), SHIM_LOG=str(self.log),
                        AVRANA_PARTY_RELEASES=str(root / 'opt-party'), AVRANA_GAMES_RELEASES=str(root / 'opt-games'),
                        AVRANA_NGINX_SITE=str(self.site), AVRANA_NGINX=str(nginx), NGINX_LOG=str(self.nginx_log),
                        AVRANA_NGINX_ENABLED=str(root / 'nginx' / 'enabled'), AVRANA_DEPLOY_DETACH='0', AVRANA_DEPLOY_LOCK=str(root / 'deploy.lock'))
        self.hooks = root / 'hooks'
        self.hooks.mkdir()
        self.party_release, self.games_release = root / 'opt-party' / 'current', root / 'opt-games' / 'current'

    def run_git(self, repo, *args):
        return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, env=self.genv).stdout.decode().strip()

    def deploy(self, party, games, *flags, **env):
        return subprocess.run([BASH, str(SCRIPT), '--party', party, '--games', games, *flags], capture_output=True,
                              text=True, env=dict(self.env, **env), timeout=300)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def target_site(self):
        return subprocess.run(['git', '-C', str(self.origin), 'show', f'{self.target_party}:avrana-party.nginx'],
                              check=True, capture_output=True, env=self.genv).stdout

    def nginx_calls(self):
        return self.nginx_log.read_text().splitlines() if self.nginx_log.exists() else []

    def starts(self):
        """Every attempt to bring a unit up: a plain start, or the restart a rollback uses."""
        return [c for c in self.calls() if c.startswith(('start ', 'restart '))]

    def journal(self):
        path = Path(self.temp.name) / 'backups' / 'deploy.journal'
        if not path.exists():
            return None
        return dict(line.split('=', 1) for line in path.read_text().splitlines() if '=' in line)

    def deploy_interrupted(self, party, games, phase, signum, *flags, release=False, **env):
        """Run a deployment, hold it at `phase` (the test-only hook), send it `signum`, return the
        finished process and its output. With release=True the pause is lifted instead."""
        import time
        (self.hooks / f'pause-at-{phase}').write_text('')
        proc = subprocess.Popen([BASH, str(SCRIPT), '--party', party, '--games', games, *flags],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                env=dict(self.env, AVRANA_DEPLOY_TEST_HOOK_DIR=str(self.hooks), **env))
        deadline = time.time() + 120
        while not (self.hooks / f'reached-{phase}').exists():
            if proc.poll() is not None or time.time() > deadline:
                out = proc.communicate()[0] if proc.poll() is not None else ''
                proc.kill()
                self.fail(f'the deployment never reached {phase}: {out}')
            time.sleep(0.05)
        if release:
            (self.hooks / f'pause-at-{phase}').unlink()
        else:
            proc.send_signal(signum)
        out = proc.communicate(timeout=120)[0]
        return proc.returncode, out


class RealRun(Harness):
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
        backups = [d for d in (Path(self.temp.name) / 'backups').iterdir() if d.is_dir()]
        self.assertEqual(len(backups), 1)
        self.assertEqual(manifest.read(backups[0] / 'before.json')['party']['sha'], self.before_party)

    def test_builds_a_code_release_of_exactly_the_commit_that_no_service_user_can_write(self):
        """ADR 0016 / AVR-256: services run <root>/current, not the operator's checkout."""
        r = self.deploy(self.target_party, self.target_games, '--skip-smoke')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.party_release.resolve().name, self.target_party)
        self.assertEqual(self.games_release.resolve().name, self.target_games)
        self.assertEqual((self.party_release / 'deploy-test-marker').read_text(), 'next\n')
        self.assertTrue((self.party_release / 'avrana/party/service.py').is_file())
        self.assertFalse((self.party_release / '.git').exists())                  # tracked files only
        for path in [self.party_release.resolve(), *self.party_release.resolve().rglob('*')]:
            self.assertFalse(path.stat().st_mode & 0o022, path)                    # not group/world writable
        # going back reuses the release that is already there: only the link moves
        r = self.deploy(self.target_party, self.before_games, '--skip-smoke')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.games_release.resolve().name, self.before_games)
        self.assertTrue((self.games_release.parent / 'releases' / self.target_games).is_dir())

    def test_a_failed_deployment_puts_the_code_release_link_back(self):
        self.assertEqual(self.deploy(self.before_party, self.target_games, '--skip-smoke').returncode, 0)
        r = self.deploy(self.before_party, self.before_games, '--skip-smoke', FAIL_UNIT='avranaparty-games')
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.games_release.resolve().name, self.target_games)

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
        self.assertEqual(len(self.starts()), 6)             # started once, then again by the rollback

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
        self.assertFalse(self.party_release.parent.exists() or self.games_release.parent.exists())

    def test_the_manifest_is_reachable_by_a_service_user_without_opening_the_acme_state(self):
        '''On the appliance the manifest's directory was created 0700 for the lego state beside it.'''
        state = self.manifest_path.parent
        state.mkdir()
        (state / 'lego').mkdir()
        state.chmod(0o700)
        (state / 'lego').chmod(0o700)
        r = self.deploy(self.target_party, self.target_games, '--skip-smoke')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(state.stat().st_mode & 0o777, 0o711)                   # search, not listing
        self.assertEqual((state / 'lego').stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.manifest_path.stat().st_mode & 0o777, 0o644)

    def test_the_manifest_directory_stays_closed_while_something_in_it_is_open(self):
        state = self.manifest_path.parent
        state.mkdir()
        (state / 'lego').mkdir()
        state.chmod(0o700)
        (state / 'lego').chmod(0o755)
        r = self.deploy(self.target_party, self.target_games, '--skip-smoke')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(state.stat().st_mode & 0o777, 0o700)
        self.assertIn('left as it is', r.stdout)


class Interrupted(Harness):
    """AVR-271: the SSH session dies (SIGHUP), the operator presses Ctrl-C (SIGINT) or something
    sends SIGTERM at each phase of a deployment. The restore runs exactly once, everything that
    was stopped is started again, and the journal says what happened."""

    def assert_restored(self, code, out, phase, signame, stopped_units):
        self.assertEqual(code, 1, out)
        self.assertEqual(out.count('rolling back'), 1, out)               # once, never twice
        self.assertIn(f'interrupted by SIG{signame}', out)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.before_party, out)
        self.assertEqual(self.run_git(self.party, 'rev-parse', '--abbrev-ref', 'HEAD'), 'main')
        self.assertEqual(self.run_git(self.games, 'rev-parse', 'HEAD'), self.before_games, out)
        self.assertFalse(self.manifest_path.exists())
        self.assertFalse(self.party_release.is_symlink() or self.games_release.is_symlink())
        restarted = sorted(c.split()[1] for c in self.calls() if c.startswith('restart '))
        self.assertEqual(restarted, sorted(stopped_units), out)
        journal = self.journal()
        self.assertEqual((journal['phase'], journal['signal']), ('rolled-back', signame), journal)

    def test_a_signal_at_every_phase_before_the_commit_restores_everything_once(self):
        everything = ['avrana-party-core', 'avranaparty-arcade', 'avranaparty-games']
        for phase, signame, stopped_units in (
                ('started', 'TERM', []), ('stopped-services', 'TERM', everything),
                ('switched', 'HUP', everything), ('restarted', 'INT', everything)):
            with self.subTest(phase=phase, signal=signame):
                self.setUp()
                code, out = self.deploy_interrupted(self.target_party, self.target_games, phase,
                                                    getattr(signal, 'SIG' + signame), '--skip-smoke')
                self.assert_restored(code, out, phase, signame, stopped_units)
                self.assertIn(f'phase: {phase}', out)

    def test_a_signal_after_the_commit_point_rolls_nothing_back(self):
        code, out = self.deploy_interrupted(self.target_party, self.target_games, 'committed', signal.SIGTERM, '--skip-smoke')
        self.assertEqual(code, 143, out)
        self.assertNotIn('rolling back', out)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.target_party)
        self.assertTrue(self.manifest_path.exists())
        self.assertEqual(self.journal()['phase'], 'committed')          # the next run reads "smoke never ran"

    def test_every_unit_is_attempted_and_a_failed_start_is_reported_as_needing_a_person(self):
        r = self.deploy(self.target_party, self.target_games, '--skip-smoke', FAIL_START='avranaparty-games')
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertEqual(r.stdout.count('rolling back'), 1)
        self.assertIn('FAILED to start avranaparty-games', r.stdout)
        self.assertIn('ROLLBACK DID NOT COMPLETE', r.stdout)
        attempted = [c for c in self.starts() if c.startswith('start ')]
        self.assertEqual(sorted(attempted), sorted(f'start {u}' for u in
                                                   ('avrana-party-core', 'avranaparty-arcade', 'avranaparty-games')))
        rollback = [c for c in self.starts() if c.startswith('restart ')]
        self.assertEqual(len(rollback), 3, rollback)                    # the others were still restarted
        self.assertEqual(self.journal()['phase'], 'rollback-failed')
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.before_party)

    def test_units_active_at_exit_are_printed_and_recorded(self):
        r = self.deploy(self.target_party, self.target_games, '--skip-smoke', FAIL_UNIT='avrana-party-core')
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertIn('units NOT active at exit: avrana-party-core', r.stdout)
        self.assertIn('units active at exit: avranaparty-games avranaparty-arcade', r.stdout)
        self.assertEqual(self.journal()['inactive'], 'avrana-party-core')
        r = self.deploy(self.before_party, self.before_games, '--skip-smoke')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.journal()['inactive'], '')
        self.assertEqual(self.journal()['phase'], 'smoke-skipped')

    def test_the_journal_names_each_phase_of_a_normal_run(self):
        r = self.deploy(self.target_party, self.target_games, '--skip-smoke')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        phases = [l.split('phase: ')[1] for l in r.stdout.splitlines() if 'phase: ' in l]
        self.assertEqual(phases, ['started', 'site-installed', 'stopped-services', 'switched', 'restarted', 'committed', 'smoke-skipped'])
        j = self.journal()
        self.assertEqual((j['party_target'], j['games_target'], j['before_party']),
                         (self.target_party, self.target_games, self.before_party))
        self.assertFalse(list((Path(self.temp.name) / 'backups').glob('deploy.journal.tmp.*')))


class NginxSite(Harness):
    """AVR-271: the nginx site file of the deployed commit is part of the deployment unit. It is read
    from Git, installed atomically, checked with `nginx -t`, reloaded; any failure puts the previous
    file back and fails the deployment before or as part of the rollback."""

    def test_a_differing_site_file_is_installed_tested_and_reloaded_before_anything_stops(self):
        import hashlib
        from avrana.ops import manifest
        self.assertNotEqual(self.site_before, self.target_site())
        r = self.deploy(self.target_party, self.target_games, '--skip-smoke')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.site.read_bytes(), self.target_site())
        self.assertEqual(self.nginx_calls(), ['nginx -t'])
        calls = self.calls()
        self.assertLess(calls.index('reload nginx'), calls.index('stop avrana-party-core'))   # fails fast: before any stop
        backup = [d for d in (Path(self.temp.name) / 'backups').iterdir() if d.is_dir()][0]
        self.assertEqual((backup / 'nginx-site-before').read_bytes(), self.site_before)       # next to the deploy backup
        doc = manifest.read(self.manifest_path)
        self.assertEqual(doc['nginx_site']['status'], 'installed')
        self.assertEqual(doc['nginx_site']['sha256'], hashlib.sha256(self.target_site()).hexdigest())
        self.assertEqual(doc['deploy_options']['rollback'], None)
        self.assertEqual(self.journal()['phase'], 'smoke-skipped')
        self.assertFalse(list(self.site.parent.glob('avrana-party.new.*')))                   # no staging file left

    def test_a_site_file_that_already_matches_is_left_alone(self):
        from avrana.ops import manifest
        self.site.write_bytes(self.target_site())
        r = self.deploy(self.target_party, self.target_games, '--skip-smoke')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.nginx_calls(), [])
        self.assertNotIn('reload nginx', self.calls())
        self.assertEqual(manifest.read(self.manifest_path)['nginx_site']['status'], 'unchanged')

    def test_nginx_t_rejecting_the_new_file_restores_the_old_one_and_names_the_missing_prerequisite(self):
        """The games.avrana.net certificate is not on the appliance yet (AVR-319): nginx -t fails."""
        reject = self.target_site() + b'# FAKE-NGINX-REJECT\n'
        (self.origin / 'avrana-party.nginx').write_bytes(reject)
        self.run_git(self.origin, 'commit', '-q', '-am', 'a site that names a missing certificate')
        bad = self.run_git(self.origin, 'rev-parse', 'HEAD')
        r = self.deploy(bad, self.target_games, '--skip-smoke')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(self.site.read_bytes(), self.site_before)                      # the previous file is back
        self.assertEqual(self.nginx_calls(), ['nginx -t', 'nginx -t'])                  # rejected, then the restored one tested
        self.assertEqual(self.calls().count('reload nginx'), 1)                         # ...and reloaded
        self.assertIn('nginx -t REJECTED', r.stdout)
        self.assertIn('cannot load certificate', r.stdout)
        self.assertIn('MISSING PREREQUISITE', r.stdout)
        self.assertIn('docs/runbooks/game-origin.md', r.stdout)
        self.assertFalse([c for c in self.calls() if c.startswith('stop ')])            # nothing was stopped
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.before_party)
        self.assertFalse(self.manifest_path.exists())
        self.assertEqual(self.journal()['phase'], 'rolled-back')

    def test_a_failed_reload_restores_the_old_file_and_fails_the_deployment(self):
        r = self.deploy(self.target_party, self.target_games, '--skip-smoke', FAIL_RELOAD='once')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('nginx reload FAILED', r.stdout)
        self.assertEqual(self.site.read_bytes(), self.site_before)
        self.assertEqual(self.calls().count('reload nginx'), 2)                         # the failed one, the restore
        self.assertFalse(self.manifest_path.exists())

    def test_a_reload_that_keeps_failing_means_the_restore_did_not_finish(self):
        r = self.deploy(self.target_party, self.target_games, '--skip-smoke', FAIL_RELOAD='always')
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertIn('ROLLBACK INCOMPLETE: nginx did not accept (or reload)', r.stdout)
        self.assertEqual(self.site.read_bytes(), self.site_before)                      # the file is back even so
        self.assertEqual(self.journal()['phase'], 'rollback-failed')

    def test_a_failure_after_the_install_restores_site_file_and_checkouts_together(self):
        r = self.deploy(self.target_party, self.target_games, '--skip-smoke', FAIL_UNIT='avrana-party-core')
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.site.read_bytes(), self.site_before)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.before_party)
        self.assertEqual(self.calls().count('reload nginx'), 2)                         # install, restore
        self.assertEqual(self.nginx_calls(), ['nginx -t', 'nginx -t'])

    def test_a_signal_right_after_the_site_install_restores_it(self):
        code, out = self.deploy_interrupted(self.target_party, self.target_games, 'site-installed', signal.SIGTERM, '--skip-smoke')
        self.assertEqual(code, 1, out)
        self.assertEqual(self.site.read_bytes(), self.site_before)
        self.assertEqual(self.journal()['phase'], 'rolled-back')
        self.assertFalse([c for c in self.calls() if c.startswith('stop ')])

    def test_a_site_file_that_did_not_exist_is_removed_again_on_failure(self):
        self.site.unlink()
        r = self.deploy(self.target_party, self.target_games, '--skip-smoke', FAIL_UNIT='avrana-party-core')
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(self.site.exists())

    def test_dry_run_reports_the_difference_without_changing_anything(self):
        r = self.deploy(self.target_party, self.target_games, '--dry-run')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r'nginx site: DIFFERS from avrana-party.nginx of \w+ \(live \d+ lines, deployed \d+; \+1 -0\)')
        self.assertEqual(self.site.read_bytes(), self.site_before)
        self.assertEqual(self.nginx_calls(), [])
        self.assertEqual(self.calls(), [])
        self.site.write_bytes(self.target_site())
        r = self.deploy(self.target_party, self.target_games, '--dry-run')
        self.assertIn('already equals avrana-party.nginx', r.stdout)

    def test_the_site_file_can_be_left_alone_and_the_manifest_says_so(self):
        from avrana.ops import manifest
        r = self.deploy(self.target_party, self.target_games, '--skip-smoke', '--skip-nginx-site')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.site.read_bytes(), self.site_before)
        self.assertEqual(self.nginx_calls(), [])
        doc = manifest.read(self.manifest_path)
        self.assertEqual(doc['nginx_site']['status'], 'skipped')
        self.assertTrue(doc['deploy_options']['skip_nginx_site'] and doc['deploy_options']['skip_smoke'])


class LastKnownGood(Harness):
    """AVR-271: the last deployment whose smoke PASSED is an explicit record that a failed or
    skipped-smoke deployment never overwrites; a failed smoke rolls back to it automatically."""

    def setUp(self):
        super().setUp()
        self.lkg = self.manifest_path.parent / 'last-known-good.json'

    def smoke(self, *results):
        root = Path(self.temp.name)
        queue, stub = root / 'smoke-queue', root / 'smoke-stub'
        queue.write_text(''.join(r + '\n' for r in results))
        stub.write_text(SMOKE_STUB)
        stub.chmod(0o755)
        self.env.update(AVRANA_DEPLOY_SMOKE=str(stub), SMOKE_QUEUE=str(queue))
        return queue

    def script(self, *args, **env):
        return subprocess.run([BASH, str(SCRIPT), *args], capture_output=True, text=True,
                              env=dict(self.env, **env), timeout=300)

    def record(self):
        return json.loads(self.lkg.read_text())

    def manifest(self):
        from avrana.ops import manifest
        return manifest.read(self.manifest_path)

    def test_a_passed_smoke_records_it_and_nothing_else_overwrites_it(self):
        import hashlib
        self.smoke('pass')
        r = self.deploy(self.target_party, self.target_games)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rec = self.record()
        self.assertEqual((rec['party_sha'], rec['games_sha']), (self.target_party, self.target_games))
        self.assertEqual(rec['web_release']['commit'], self.target_party)
        self.assertEqual(rec['nginx_site_sha256'], hashlib.sha256(self.target_site()).hexdigest())
        self.assertTrue(rec['smoke_at'] and rec['recorded_at'])
        self.assertEqual(self.lkg.stat().st_mode & 0o777, 0o644)
        # skipped smoke: another revision is running, the record stays
        r = self.deploy(self.before_party, self.before_games, '--skip-smoke')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('NOT updated', r.stdout)
        self.assertEqual(self.record()['party_sha'], self.target_party)
        # failed smoke with the rollback switched off: same
        self.smoke('fail')
        r = self.deploy(self.before_party, self.target_games, '--no-auto-rollback')
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(self.record()['party_sha'], self.target_party)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.before_party)    # kept for debugging
        doc = self.manifest()
        self.assertEqual(doc['smoke']['status'], 'failed')
        self.assertTrue(doc['deploy_options']['no_auto_rollback'])                            # and on the record
        self.assertIn('--rollback', r.stdout)

    def test_a_failed_smoke_rolls_back_to_the_last_known_good_and_reports_both_results(self):
        self.smoke('pass')
        self.assertEqual(self.deploy(self.target_party, self.target_games).returncode, 0)
        self.assertEqual(self.site.read_bytes(), self.target_site())
        self.smoke('fail', 'pass')
        r = self.deploy(self.before_party, self.before_games)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)                      # failed, rolled back cleanly
        self.assertIn('smoke FAILED', r.stdout)
        self.assertIn('AUTOMATIC ROLLBACK to the last known good', r.stdout)
        self.assertIn('DEPLOYMENT FAILED, ROLLED BACK', r.stdout)
        self.assertIn('its smoke PASSED', r.stdout)
        # everything is the last known good again: checkouts, code releases, web build, site file
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.target_party)
        self.assertEqual(self.run_git(self.games, 'rev-parse', 'HEAD'), self.target_games)
        self.assertEqual(self.party_release.resolve().name, self.target_party)
        self.assertEqual(self.site.read_bytes(), self.target_site())
        doc = self.manifest()
        self.assertEqual((doc['party']['sha'], doc['smoke']['status']), (self.target_party, 'passed'))
        self.assertEqual(doc['web_release']['commit'], self.target_party)
        self.assertEqual(doc['deploy_options']['rollback'], 'auto')
        self.assertEqual(doc['nginx_site']['sha256'], self.record()['nginx_site_sha256'])
        # the failed deployment's own record is kept
        failed = [d / 'failed-manifest.json' for d in (Path(self.temp.name) / 'backups').iterdir()
                  if d.is_dir() and (d / 'failed-manifest.json').exists()]
        self.assertEqual(len(failed), 1)
        self.assertEqual(json.loads(failed[0].read_text())['party']['sha'], self.before_party)
        self.assertEqual(self.journal()['phase'], 'auto-rolled-back')
        self.assertEqual(self.record()['party_sha'], self.target_party)

    def test_when_the_rolled_back_revision_fails_its_smoke_too_a_person_is_needed_and_it_stops_there(self):
        self.smoke('pass')
        self.assertEqual(self.deploy(self.target_party, self.target_games).returncode, 0)
        queue = self.smoke('fail', 'fail', 'pass')                                  # a third result must never be used
        r = self.deploy(self.before_party, self.before_games)
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertIn('ROLLBACK APPLIED BUT ITS SMOKE ALSO FAILED', r.stdout)
        self.assertEqual(r.stdout.count('AUTOMATIC ROLLBACK'), 1)                  # no loop
        self.assertEqual(queue.read_text(), 'pass\n')
        self.assertEqual(self.journal()['phase'], 'rollback-failed')

    def test_the_first_deployment_ever_keeps_the_old_behaviour(self):
        self.smoke('fail')
        r = self.deploy(self.target_party, self.target_games)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('no last known good exists yet', r.stdout)
        self.assertIn(f'--party {self.before_party} --games {self.before_games}', r.stdout)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.target_party)
        self.assertFalse(self.lkg.exists())

    def test_never_back_to_the_pair_that_just_failed(self):
        self.smoke('pass')
        self.assertEqual(self.deploy(self.target_party, self.target_games).returncode, 0)
        self.smoke('fail')
        r = self.deploy(self.target_party, self.target_games)                       # the same pair again
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('the very pair that failed', r.stdout)
        self.assertNotIn('AUTOMATIC ROLLBACK', r.stdout)

    def test_an_appliance_deployed_before_the_record_existed_is_seeded_from_its_running_deployment(self):
        self.smoke('pass')
        self.assertEqual(self.deploy(self.target_party, self.target_games).returncode, 0)
        self.lkg.unlink()                                                           # as on the Pi today
        self.smoke('fail', 'pass')
        r = self.deploy(self.before_party, self.before_games)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn('last-known-good seeded from the running deployment', r.stdout)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.target_party)
        # a running deployment that did not pass is no record
        self.lkg.unlink()
        self.smoke('fail')
        r = self.deploy(self.before_party, self.before_games, '--skip-smoke')
        r = self.deploy(self.target_party, self.target_games)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertNotIn('seeded', r.stdout)

    def test_rollback_goes_back_without_any_sha(self):
        r = self.script('--rollback')
        self.assertEqual(r.returncode, 1)
        self.assertIn('no last-known-good record', r.stderr)
        self.smoke('pass')
        self.assertEqual(self.deploy(self.target_party, self.target_games).returncode, 0)
        self.assertEqual(self.deploy(self.before_party, self.before_games, '--skip-smoke').returncode, 0)
        self.smoke('pass')
        r = self.script('--rollback')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.target_party)
        self.assertEqual(self.site.read_bytes(), self.target_site())
        doc = self.manifest()
        self.assertEqual((doc['party']['sha'], doc['deploy_options']['rollback']), (self.target_party, 'manual'))
        self.assertIn('contract: not applied to a manual', r.stdout)
        r = self.script('--rollback', '--party', self.target_party)
        self.assertEqual(r.returncode, 1)

    def test_a_killed_deployment_blocks_the_next_one_and_recover_restores_the_last_known_good(self):
        import time
        self.smoke('pass')
        self.assertEqual(self.deploy(self.target_party, self.target_games).returncode, 0)
        (self.hooks / 'pause-at-switched').write_text('')
        proc = subprocess.Popen([BASH, str(SCRIPT), '--party', self.before_party, '--games', self.before_games, '--skip-smoke'],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                env=dict(self.env, AVRANA_DEPLOY_TEST_HOOK_DIR=str(self.hooks)))
        deadline = time.time() + 120
        while not (self.hooks / 'reached-switched').exists():
            self.assertLess(time.time(), deadline)
            time.sleep(0.05)
        proc.kill()                                                                 # SIGKILL: no trap can run
        proc.communicate()
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.before_party)    # half-switched
        deadline = time.time() + 30
        while True:                                                                 # until the lock is free again
            r = self.deploy(self.target_party, self.target_games, '--skip-smoke')
            if 'another deployment is running' not in r.stderr or time.time() > deadline:
                break
            time.sleep(0.2)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("died at phase 'switched'", r.stderr)
        self.assertIn('--recover', r.stderr)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.before_party)    # the evidence is untouched
        self.smoke('pass')
        r = self.script('--recover')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.target_party)
        self.assertEqual(self.run_git(self.games, 'rev-parse', 'HEAD'), self.target_games)
        self.assertEqual(self.site.read_bytes(), self.target_site())
        self.assertEqual(self.journal()['phase'], 'smoke-passed')
        self.assertEqual(self.manifest()['deploy_options']['rollback'], 'recover')
        self.assertEqual(sorted(self.manifest()['restarted']),                      # everything is re-applied
                         ['avrana-party-core', 'avranaparty-arcade', 'avranaparty-games'])
        r = self.deploy(self.before_party, self.before_games, '--skip-smoke')       # and normal deploys work again
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_recover_without_a_record_returns_to_the_before_state_of_the_dead_deployment(self):
        import time
        (self.hooks / 'pause-at-switched').write_text('')
        proc = subprocess.Popen([BASH, str(SCRIPT), '--party', self.target_party, '--games', self.target_games, '--skip-smoke'],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                env=dict(self.env, AVRANA_DEPLOY_TEST_HOOK_DIR=str(self.hooks)))
        deadline = time.time() + 120
        while not (self.hooks / 'reached-switched').exists():
            self.assertLess(time.time(), deadline)
            time.sleep(0.05)
        proc.kill()
        proc.communicate()
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.target_party)
        time.sleep(1)
        self.smoke('pass')
        r = self.script('--recover')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('recovering to the before-state', r.stdout)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.before_party)
        self.assertEqual(self.site.read_bytes(), self.site_before)


class Detached(Harness):
    """AVR-271: a real run survives its controlling terminal. The launcher only follows a log."""

    def wait_for(self, predicate, what, seconds=120):
        import time
        deadline = time.time() + seconds
        while not predicate():
            if time.time() > deadline:
                self.fail(f'timed out waiting for {what}')
            time.sleep(0.1)

    def test_a_detached_run_prints_its_log_and_returns_the_exit_code(self):
        r = self.deploy(self.target_party, self.target_games, '--skip-smoke', AVRANA_DEPLOY_DETACH='1')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('detaching', r.stdout)
        self.assertIn('smoke checks skipped', r.stdout)                       # the run's own output, followed
        logs = list((Path(self.temp.name) / 'backups').glob('deploy-*.log'))
        self.assertEqual(len(logs), 1)
        self.assertIn('smoke checks skipped', logs[0].read_text())
        r = self.deploy(self.target_party, 'f' * 40, '--skip-smoke', AVRANA_DEPLOY_DETACH='1')
        self.assertNotEqual(r.returncode, 0)                                  # a refusal still fails the command

    def test_a_dropped_session_does_not_stop_the_deployment(self):
        import signal
        (self.hooks / 'pause-at-stopped-services').write_text('')
        proc = subprocess.Popen([BASH, str(SCRIPT), '--party', self.target_party, '--games', self.target_games, '--skip-smoke'],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                env=dict(self.env, AVRANA_DEPLOY_DETACH='1', AVRANA_DEPLOY_TEST_HOOK_DIR=str(self.hooks)))
        self.wait_for((self.hooks / 'reached-stopped-services').exists, 'the deployment to stop its services')
        pid = int(self.journal()['pid'])
        proc.send_signal(signal.SIGHUP)                                       # the SSH session dies
        proc.communicate(timeout=60)
        os.kill(pid, 0)                                                       # the deployment itself is alive
        status = subprocess.run([BASH, str(SCRIPT), '--status'], capture_output=True, text=True, env=self.env)
        self.assertIn("RUNNING", status.stdout, status.stdout)
        (self.hooks / 'pause-at-stopped-services').unlink()                   # let it go on
        self.wait_for(lambda: (self.journal() or {}).get('phase') == 'smoke-skipped', 'the deployment to finish')
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.target_party)
        self.assertTrue(self.manifest_path.exists())

    def test_status_names_the_phase_where_a_killed_deployment_stopped(self):
        import signal
        status = subprocess.run([BASH, str(SCRIPT), '--status'], capture_output=True, text=True, env=self.env)
        self.assertEqual(status.returncode, 0)
        self.assertIn('no journal', status.stdout)
        (self.hooks / 'pause-at-switched').write_text('')
        proc = subprocess.Popen([BASH, str(SCRIPT), '--party', self.target_party, '--games', self.target_games, '--skip-smoke'],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                env=dict(self.env, AVRANA_DEPLOY_TEST_HOOK_DIR=str(self.hooks)))
        self.wait_for((self.hooks / 'reached-switched').exists, 'the switch')
        proc.kill()                                                           # SIGKILL: no trap can run
        proc.communicate()
        out = ''
        def interrupted():
            nonlocal out
            out = subprocess.run([BASH, str(SCRIPT), '--status'], capture_output=True, text=True, env=self.env).stdout
            return 'INTERRUPTED' in out
        self.wait_for(interrupted, 'status to see a dead deployment', 30)
        self.assertIn("phase 'switched'", out)
        self.assertIn('--recover', out)


class FirstRunFromACheckoutWithoutTheTooling(Harness):
    '''AVR-262: the appliance ran a commit from before avrana.ops and ops/deploy.sh existed. The
    script (from the target commit) must take it forward, roll it back and take it back again
    without ever running Python tooling out of that older checkout.'''

    def setUp(self):
        super().setUp()
        # origin: ... -> target_party -> old (no tooling) -> new (tooling restored); production sits on old.
        self.run_git(self.origin, 'rm', '-r', '-q', 'avrana/ops', 'ops/deploy.sh')
        self.run_git(self.origin, 'commit', '-q', '-m', 'as it was before the deploy tooling')
        self.old = self.run_git(self.origin, 'rev-parse', 'HEAD')
        self.run_git(self.origin, 'revert', '--no-edit', 'HEAD')
        self.new = self.run_git(self.origin, 'rev-parse', 'HEAD')
        self.run_git(self.party, 'fetch', '-q', 'origin')
        self.run_git(self.party, 'checkout', '-q', '-B', 'main', self.old)
        self.assertFalse((self.party / 'avrana/ops').exists() or (self.party / 'ops/deploy.sh').exists())
        self.assertTrue((self.origin / 'avrana/ops/manifest.py').is_file())

    def test_deploys_forward_with_the_target_commits_tooling(self):
        from avrana.ops import manifest
        r = self.deploy(self.new, self.target_games, '--skip-smoke')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.new)
        self.assertEqual(self.party_release.resolve().name, self.new)
        doc = manifest.read(self.manifest_path)
        self.assertEqual((doc['party']['sha'], doc['games']['sha']), (self.new, self.target_games))
        self.assertEqual(doc['tool']['party_sha'], self.new)
        self.assertEqual(doc['web_release']['commit'], self.new)
        backups = [d for d in (Path(self.temp.name) / 'backups').iterdir() if d.is_dir()]
        self.assertEqual(manifest.read(backups[0] / 'before.json')['party']['sha'], self.old)
        self.assertEqual(len([c for c in self.calls() if c.startswith('start ')]), 3)

    def test_smoke_runs_from_the_target_commit_too(self):
        from avrana.ops import manifest
        r = self.deploy(self.new, self.target_games)                 # nothing listens: smoke must fail
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('smoke FAILED', r.stdout)
        self.assertIn(f'--party {self.old} --games {self.before_games}', r.stdout)
        self.assertEqual(manifest.read(self.manifest_path)['smoke']['status'], 'failed')

    def test_a_unit_that_does_not_come_back_still_rolls_back(self):
        r = self.deploy(self.new, self.target_games, '--skip-smoke', FAIL_UNIT='avrana-party-core')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('rolling back', r.stdout)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.old)
        self.assertEqual(self.run_git(self.party, 'rev-parse', '--abbrev-ref', 'HEAD'), 'main')
        self.assertEqual(self.run_git(self.games, 'rev-parse', 'HEAD'), self.before_games)
        self.assertFalse(self.manifest_path.exists())
        # no release ran before this deployment, so none is left looking current
        self.assertFalse(self.party_release.is_symlink() or self.games_release.is_symlink())
        self.assertEqual(len(self.starts()), 6)

    def test_going_back_to_that_commit_uses_the_tooling_of_the_release_that_was_running(self):
        from avrana.ops import manifest
        self.assertEqual(self.deploy(self.new, self.target_games, '--skip-smoke').returncode, 0)
        r = self.deploy(self.old, self.before_games, '--skip-smoke')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('predates the deploy tooling', r.stdout)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.old)
        self.assertEqual(self.party_release.resolve().name, self.old)
        doc = manifest.read(self.manifest_path)
        self.assertEqual((doc['party']['sha'], doc['games']['sha']), (self.old, self.before_games))
        self.assertEqual(doc['tool']['party_sha'], self.new)

    def test_refuses_before_stopping_anything_when_no_release_has_the_tooling(self):
        r = self.deploy(self.old, self.target_games, '--skip-smoke')
        self.assertEqual(r.returncode, 1)
        self.assertIn('nothing was stopped', r.stderr)
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.run_git(self.games, 'rev-parse', 'HEAD'), self.before_games)
        self.assertFalse(self.manifest_path.exists() or (Path(self.temp.name) / 'backups').exists())


if __name__ == '__main__':
    unittest.main()
