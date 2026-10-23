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

    def test_test_only_settings_are_refused_unless_testing_on_a_scratch_root(self):
        for var in ('AVRANA_NGINX', 'AVRANA_SYSTEMCTL', 'AVRANA_DEPLOY_SMOKE', 'AVRANA_DEPLOY_TEST_HOOK_DIR',
                    'AVRANA_DEPLOY_UNPRIVILEGED', 'AVRANA_OPENSSL', 'AVRANA_DEPLOY_FAIL_STEP',
                    'AVRANA_DEPLOY_UNIT_GRACE', 'AVRANA_DEPLOY_SMOKE_PAUSE', 'AVRANA_DEPLOY_CATALOG_OWNER_UID',
                    'AVRANA_CATALOG_SETTLE_WAIT', 'AVRANA_CATALOG_PYTHON'):
            for testing in ('', '1'):          # TESTING=1 is not enough while the production roots are in use
                env = dict(self.env, **{var: '1'})
                if testing:
                    env['AVRANA_DEPLOY_TESTING'] = testing
                r = subprocess.run([BASH, str(SCRIPT), '--party', self.party_sha, '--games', self.games_sha, '--dry-run'],
                                   capture_output=True, text=True, env=env, timeout=120)
                self.assertEqual(r.returncode, 1, (var, testing, r.stdout, r.stderr))
                self.assertIn(var, r.stderr)
                self.assertIn('test-only', r.stderr)

    def test_the_production_waits_are_the_defaults_and_only_the_gated_settings_shorten_them(self):
        text = SCRIPT.read_text(encoding='utf-8')
        self.assertIn('${AVRANA_DEPLOY_UNIT_GRACE:-1}', text)      # one second before each unit is checked
        self.assertIn('${AVRANA_DEPLOY_SMOKE_PAUSE:-2}', text)     # two seconds before the first smoke
        self.assertRegex(text, r'for unit in [^\n]*restart[^\n]*; do\r?\n\s+sleep "\$unit_grace"')

    @unittest.skipUnless(shutil.which('flock'), 'flock not available')
    def test_the_internal_arguments_are_not_for_operators(self):
        for args in (['--internal-nested', '--rollback', '--internal-rollback-kind', 'auto'],
                     ['--internal-rollback-kind', 'auto']):
            r = self.run_script(*args, '--party', self.party_sha, '--games', self.games_sha, '--dry-run')
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn('not for operators', r.stderr)
        self.assertNotIn('internal', self.run_script('--help').stdout)               # and they are not advertised

    @unittest.skipUnless(sys.platform == 'linux' and hasattr(os, 'geteuid') and os.geteuid() != 0, 'needs Linux and a non-root user')
    def test_status_as_a_user_who_cannot_read_the_directory_says_so(self):
        backups = Path(self.temp.name) / 'backups'
        backups.mkdir()
        (backups / 'deploy.journal').write_text('phase=smoke-passed\n')
        backups.chmod(0)
        self.addCleanup(backups.chmod, 0o700)
        r = self.run_script('--status')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('run this with sudo', r.stdout)
        self.assertNotIn('no journal', r.stdout)

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


def catalog_tool_shim(directory):
    """A directory with a `python3` that runs `-m avrana.ops.catalog_overlay ...` as the scripts do, but as "root" (the tool
    refuses to refresh as anybody else, and a test user is not root on Linux), from the tree it is run in, with a lock
    file of its own ($SETTLE_LOCK). Every other python3 call is the real interpreter. With $SETTLE_STUB the effective
    catalog is a marker naming the release catalog it was derived from (the stub replaces `_effective`, which `refresh`
    calls since AVR-466 phase C, and names no artwork); with $SETTLE_SKIP_HOOK a `--wait 0` call (the
    hook in install-party-web.sh when ops/deploy.sh runs it) does nothing and succeeds."""
    directory.mkdir()
    python = Path(sys.executable).as_posix()
    wrapper = (
        'import os, sys\n'
        'if sys.argv[1:3] != ["-m", "avrana.ops.catalog_overlay"]:\n'
        '    os.execv(sys.executable, [sys.executable] + sys.argv[1:])\n'
        'sys.path.insert(0, os.getcwd())\n'
        'os.geteuid = lambda: 0\n'
        'from avrana.ops import catalog_overlay as co\n'
        'args = sys.argv[3:]\n'
        'if os.environ.get("SETTLE_SKIP_HOOK") and args[:1] == ["refresh"] and "--wait" in args and args[args.index("--wait") + 1] == "0":\n'
        '    sys.exit(0)\n'
        'if os.environ.get("SETTLE_STUB"):\n'
        '    from pathlib import Path\n'
        '    co._effective = lambda base, records, **kw: ("EFFECTIVE-FOR " + Path(base).read_text(), ["hello"], [], {})\n'
        'sys.exit(co.main(args + ["--lock-file", os.environ["SETTLE_LOCK"]]))\n')
    (directory / 'wrap.py').write_text(wrapper, newline='\n')
    (directory / 'python3').write_text(f'#!/bin/sh\nexec "{python}" "{(directory / "wrap.py").as_posix()}" "$@"\n', newline='\n')
    (directory / 'python3').chmod(0o755)
    return directory


class SettleCatalog(unittest.TestCase):
    """AVR-337 on the deploy path: the effective game catalog is derived from the web release, so every way the web
    release changes (deployment, nested rollback, --recover, a run that is undone) must refresh or remove it, and
    nothing about it may fail a deployment. The function is run on its own, against scratch directories, so this
    holds wherever bash and python are (the full paths are in CatalogOverlayOnReleaseChanges, Linux only)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.overlay = self.root / 'overlay' / 'catalog.json'
        self.overlay.parent.mkdir()
        self.records = self.root / 'records'
        self.records.mkdir()
        self.release = self.root / 'opt' / 'current'            # a directory stands in for the `current` link
        (self.release / 'avrana' / 'ops').mkdir(parents=True)
        self.web = self.root / 'web'
        (self.web / 'current').mkdir(parents=True)
        self.shim = catalog_tool_shim(self.root / 'bin')

    def settle(self, stub=False, wait=None, arg=''):
        text = SCRIPT.read_text(encoding='utf-8')
        start = text.index('\nsettle_catalog() {')
        body = text[start:text.index('\n}\n', start) + 3]
        script = ('set -Eeuo pipefail\nlog() { echo "$*"; }\ntesting=1\n'
                  f'party_releases={(self.root / "opt").as_posix()}\nweb_root={self.web.as_posix()}\n{body}\nsettle_catalog {arg}\n')
        env = dict(os.environ, PATH=f'{self.shim.as_posix()}{os.pathsep}{os.environ["PATH"]}', PYTHONPATH=str(REPO_ROOT),
                   AVRANA_CATALOG_OVERLAY=self.overlay.as_posix(), AVRANA_PACKAGE_RECORDS=self.records.as_posix(),
                   SETTLE_LOCK=(self.root / 'install.lock').as_posix())
        if stub:
            env['SETTLE_STUB'] = '1'
        if wait is not None:
            env['AVRANA_CATALOG_SETTLE_WAIT'] = str(wait)
        return subprocess.run([BASH, '-c', script], capture_output=True, text=True, env=env, timeout=120)

    def code(self):
        (self.release / 'avrana' / 'ops' / 'catalog_overlay.py').write_text('')

    def test_a_stale_overlay_is_regenerated_or_removed_for_the_release_that_is_now_current(self):
        self.code()
        (self.web / 'current' / 'catalog.json').write_bytes((REPO_ROOT / 'web/party/catalog.json').read_bytes())
        self.overlay.write_text('STALE: built for another release')
        r = self.settle()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(self.overlay.exists())                # no package is installed: the release catalog is served
        self.assertIn('matches web release', r.stdout)
        self.assertEqual(list(self.overlay.parent.iterdir()), [])

    def test_the_overlay_is_rewritten_for_each_release_that_becomes_current(self):
        """Not vacuous: with a package to list, settle writes the effective catalog derived from the web release that
        is current NOW, and a later switch changes it with the release (it is neither left alone nor removed)."""
        self.code()
        self.overlay.write_text('STALE: built for another release')
        for release in ('{"release": "one"}', '{"release": "two"}'):
            (self.web / 'current' / 'catalog.json').write_text(release)
            r = self.settle(stub=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(self.overlay.read_text(), 'EFFECTIVE-FOR ' + release)
            self.assertIn('matches web release', r.stdout)

    def hold_install_lock(self, release_after):
        """Hold the install lock (the file settle's tool locks) from a thread; release it after `release_after` seconds,
        or never (None) until the test ends."""
        import fcntl
        import threading
        fd = os.open(self.root / 'install.lock', os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        self.addCleanup(os.close, fd)
        if release_after is not None:
            threading.Timer(release_after, lambda: fcntl.flock(fd, fcntl.LOCK_UN)).start()

    @unittest.skipUnless(sys.platform == 'linux', 'needs flock')
    def test_a_running_install_is_waited_for_and_the_overlay_is_then_regenerated(self):
        self.code()
        (self.web / 'current' / 'catalog.json').write_text('{"release": "one"}')
        self.overlay.write_text('STALE: built for another release')
        self.hold_install_lock(release_after=1.0)
        r = self.settle(stub=True, wait=20)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.overlay.read_text(), 'EFFECTIVE-FOR {"release": "one"}')

    @unittest.skipUnless(sys.platform == 'linux', 'needs flock')
    def test_an_install_that_outlasts_the_wait_removes_the_overlay_with_a_warning_that_names_the_reason(self):
        self.code()
        (self.web / 'current' / 'catalog.json').write_text('{"release": "one"}')
        self.overlay.write_text('STALE: built for another release')
        self.hold_install_lock(release_after=None)
        r = self.settle(stub=True, wait=1)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)             # warning only
        self.assertFalse(self.overlay.exists())
        self.assertIn('WARNING: catalog:', r.stdout)
        self.assertIn('another install-game is running', r.stdout)

    def test_the_reason_is_logged_when_the_tool_fails(self):
        self.code()
        (self.web / 'current' / 'catalog.json').write_text('not json')
        self.overlay.write_text('STALE')
        r = self.settle()
        self.assertFalse(self.overlay.exists())
        self.assertRegex(r.stdout, r'WARNING: catalog: the effective catalog could not be regenerated \(.+\)')

    def test_remove_mode_only_removes_and_does_not_need_the_tool_or_a_lock(self):
        self.overlay.write_text('STALE')
        r = self.settle(arg='remove')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(self.overlay.exists())
        self.assertIn('removed until the web release is settled', r.stdout)

    def test_a_deployment_waits_for_a_running_install_once_and_only_in_its_own_settle(self):
        text = SCRIPT.read_text(encoding='utf-8')
        self.assertIn('AVRANA_CATALOG_WAIT=0 bash "$party_checkout/ops/install-party-web.sh"', text)      # the hook does not wait
        self.assertIn('--wait "$wait"', text)                                                               # settle does
        hook = (REPO_ROOT / 'ops/install-party-web.sh').read_text(encoding='utf-8')
        self.assertIn('local wait=${AVRANA_CATALOG_WAIT:-30}', hook)             # and standalone it still waits 30 s

    def test_when_the_overlay_cannot_be_made_it_is_removed_and_the_run_goes_on(self):
        for label, prepare in (('no overlay code in the running release', lambda: None),
                               ('the release catalog is missing', self.code)):
            with self.subTest(label):
                prepare()
                self.overlay.write_text('STALE: built for another release')
                r = self.settle()
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)          # warning only: never a failed deployment
                self.assertFalse(self.overlay.exists())
                self.assertIn('WARNING: catalog:', r.stdout)
                self.assertIn('first-party catalog is served', r.stdout)

    def test_nothing_is_done_or_said_on_an_appliance_without_packages_or_overlay(self):
        r = self.settle()
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ''), r.stdout + r.stderr)

    def test_a_package_record_alone_is_enough_to_look(self):
        (self.records / 'hello.json').write_text('{}')
        r = self.settle()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('WARNING: catalog:', r.stdout)

    def test_the_paths_are_fixed_and_only_the_test_harness_may_move_them(self):
        text = SCRIPT.read_text(encoding='utf-8')
        start = text.index('\nsettle_catalog() {')
        body = text[start:text.index('\n}\n', start)]
        self.assertIn('overlay=/var/lib/avrana-party/catalog/catalog.json', body)       # the nginx location names this file
        self.assertRegex(body, r'if \[\[ \$testing -eq 1 \]\]; then[^\n]*\n\s+overlay=\$\{AVRANA_CATALOG_OVERLAY')

    def test_it_runs_after_the_web_install_and_before_the_site_file_and_services_are_put_back(self):
        text = SCRIPT.read_text(encoding='utf-8')
        install = text.index('bash "$party_checkout/ops/install-party-web.sh"')
        call = text.index('\n    settle_catalog', install)
        self.assertLess(call, text.index('\njournal switched', install))
        body = text[text.index('\nrollback_body() {'):text.index('\non_signal()')]
        self.assertIn('web-release-before', body)
        removed = body.index('settle_catalog remove')
        self.assertLess(body.index('web-release-before'), removed)                  # the stale file goes as soon as the link is back,
        self.assertLess(removed, body.index('restore_site\n'))                      # before the site file and the units, with no wait
        final = body.rindex('settle_catalog')
        self.assertGreater(final, body.index('start_stopped restart'))              # and the refresh that may wait comes after every unit is back
        self.assertEqual(body.count('settle_catalog'), 2)


SYSTEMCTL_SHIM = """#!/usr/bin/env bash
# Records every call. `is-active` fails for the unit named in $FAIL_UNIT (a unit that does not come
# back); `start` and `restart` fail for the unit named in $FAIL_START (a unit that will not start).
echo "$*" >> "$SHIM_LOG"
if [[ $1 == is-active && -n ${FAIL_UNIT:-} && " $* " == *" $FAIL_UNIT "* ]]; then exit 3; fi
# `list-units --state=failed`: one line per unit named in $FAILED_GAME_UNITS (space-separated).
if [[ $1 == list-units ]]; then
    # `--state=active` (the hosted profile's running native games): one line per unit in $ACTIVE_GAME_UNITS.
    if [[ " $* " == *" --state=active "* ]]; then
        for u in ${ACTIVE_GAME_UNITS:-}; do echo "$u loaded active running Avrana native game"; done; exit 0
    fi
    for u in ${FAILED_GAME_UNITS:-}; do echo "$u loaded failed failed Avrana native game"; done; exit 0
fi
if [[ $1 == start || $1 == restart ]] && [[ -n ${FAIL_START:-} && " $* " == *" $FAIL_START "* ]]; then exit 1; fi
# $FAIL_RELOAD=once: the first `reload` fails, later ones work; =always: every one fails.
if [[ $1 == reload && -n ${FAIL_RELOAD:-} ]]; then
    if [[ $FAIL_RELOAD == always ]]; then exit 1; fi
    if [[ $FAIL_RELOAD == second ]]; then            # the first reload works, every later one fails
        if [[ -e "$SHIM_LOG.reloaded" ]]; then exit 1; fi
        : > "$SHIM_LOG.reloaded"; exit 0
    fi
    if [[ ! -e "$SHIM_LOG.reload-failed" ]]; then : > "$SHIM_LOG.reload-failed"; exit 1; fi
fi
exit 0
"""

# Stands for the smoke checks (AVRANA_DEPLOY_SMOKE): each call consumes the first line of $SMOKE_QUEUE
# (`pass` or `fail`); an empty queue fails.
SMOKE_STUB = """#!/usr/bin/env bash
# Each line of $SMOKE_QUEUE: `pass`, `fail` (every check fails) or `fail:name,name` (those checks fail). It prints the
# JSON of `python3 -m avrana.ops.smoke --json`. An empty queue fails.
echo "$*" >> "${SMOKE_ARGS_LOG:-/dev/null}"
line=$(head -n1 "$SMOKE_QUEUE"); sed -i 1d "$SMOKE_QUEUE"
python3 - "${line:-fail}" <<'EOF'
import json, sys
line = sys.argv[1]
names = ['units', 'status', 'certificate', 'games']
failing = set(names) if line == 'fail' else set(line.split(':', 1)[1].split(',')) if line.startswith('fail:') else set()
skipped = set(line.split(':', 1)[1].split(',')) if line.startswith('skip:') else set()      # `skip:name`: not checked
checks = [{'name': n, 'status': 'fail' if n in failing else 'skip' if n in skipped else 'pass', 'detail': ''} for n in names]
print(json.dumps({'ok': not failing, 'counts': {'pass': len(names) - len(failing) - len(skipped), 'fail': len(failing),
                  'skip': len(skipped)}, 'checks': checks}))
sys.exit(1 if failing else 0)
EOF
"""

# Stands for openssl: games.avrana.net is the name the served certificate does not cover.
OPENSSL_SHIM = """#!/usr/bin/env bash
name=${@: -1}
if [[ $name == games.avrana.net ]]; then echo "Hostname $name does NOT match certificate"; else echo "Hostname $name does match certificate"; fi
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
        for name in ('avrana-party.nginx', 'arcade/nginx-site'):                    # the target's site file differs
            with open(self.origin / name, 'a', newline='') as site:
                site.write('# deploy test: the next commit\n')
        self.run_git(self.origin, 'add', 'deploy-test-marker', 'avrana-party.nginx', 'arcade/nginx-site')
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
        self.lkg = root / 'state' / 'last-known-good.json'
        self.env = dict(self.genv, AVRANA_PARTY_CHECKOUT=str(self.party), AVRANA_GAMES_CHECKOUT=str(self.games),
                        AVRANA_PARTY_CORE_URL='http://127.0.0.1:1', AVRANA_WEB_ROOT=str(self.web),
                        AVRANA_DEPLOYMENT_MANIFEST=str(self.manifest_path), AVRANA_BACKUP_ROOT=str(root / 'backups'),
                        AVRANA_DEPLOY_UNPRIVILEGED='1', AVRANA_SYSTEMCTL=str(shim), SHIM_LOG=str(self.log),
                        AVRANA_PARTY_RELEASES=str(root / 'opt-party'), AVRANA_GAMES_RELEASES=str(root / 'opt-games'),
                        AVRANA_NGINX_SITE=str(self.site), AVRANA_NGINX=str(nginx), NGINX_LOG=str(self.nginx_log),
                        AVRANA_NGINX_ENABLED=str(root / 'nginx' / 'enabled'), AVRANA_DEPLOY_DETACH='0',
                        AVRANA_DEPLOY_TESTING='1', AVRANA_DEPLOY_SMOKE_SETTLE='0',
                        AVRANA_DEPLOY_UNIT_GRACE='0', AVRANA_DEPLOY_SMOKE_PAUSE='0', AVRANA_DEPLOY_LOCK=str(root / 'deploy.lock'))
        self.hooks = root / 'hooks'
        self.hooks.mkdir()
        self.party_release, self.games_release = root / 'opt-party' / 'current', root / 'opt-games' / 'current'

    def run_git(self, repo, *args):
        return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, env=self.genv).stdout.decode().strip()

    def deploy(self, party, games, *flags, **env):
        return subprocess.run([BASH, str(SCRIPT), '--party', party, '--games', games, *flags], capture_output=True,
                              text=True, env=dict(self.env, **env), timeout=300)

    def calls(self, queries=False):
        """systemctl calls. The read-only `list-units` query of the preflight (failed native game units)
        is left out unless `queries`, so "nothing was touched" stays an empty list."""
        lines = self.log.read_text().splitlines() if self.log.exists() else []
        return lines if queries else [c for c in lines if not c.startswith('list-units ')]

    def target_site(self):
        return subprocess.run(['git', '-C', str(self.origin), 'show', f'{self.target_party}:avrana-party.nginx'],
                              check=True, capture_output=True, env=self.genv).stdout

    def nginx_calls(self):
        return self.nginx_log.read_text().splitlines() if self.nginx_log.exists() else []

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

    def starts(self):
        """Every attempt to bring a unit up: a plain start, or the restart a rollback uses."""
        return [c for c in self.calls() if c.startswith(('start ', 'restart '))]

    def journal(self):
        path = Path(self.temp.name) / 'backups' / 'deploy.journal'
        if not path.exists():
            return None
        return dict(line.split('=', 1) for line in path.read_text().splitlines() if '=' in line)

    def deploy_interrupted(self, party, games, phase, signum, *flags, release=False, during=None, **env):
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
        if during:
            during()                # the deployment is held at `phase`: change the machine under it
        if release:
            (self.hooks / f'pause-at-{phase}').unlink()
        else:
            proc.send_signal(signum)
        out = proc.communicate(timeout=120)[0]
        return proc.returncode, out


HOSTED_SITE = """# deploy test: the hosted site file (deploy/hosted/avrana-party.hosted.nginx)
server { listen 127.0.0.1:8080; server_name avrana.party; }
"""


class HostedProfile(Harness):
    """docs/design/HOSTED-STAGING.md: the same deployment on a host whose /etc/avrana-party/deploy-profile says
    "hosted". Party Core and the running native games are what restart, the hosted site file is installed, and
    smoke is the hosted set. The appliance profile is what every other test in this file runs."""

    def setUp(self):
        super().setUp()
        root = Path(self.temp.name)
        site = self.origin / 'deploy' / 'hosted' / 'avrana-party.hosted.nginx'
        site.parent.mkdir(parents=True, exist_ok=True)
        site.write_text(HOSTED_SITE)
        self.run_git(self.origin, 'add', 'deploy/hosted/avrana-party.hosted.nginx')
        self.run_git(self.origin, 'commit', '-q', '-m', 'hosted site')
        self.target_party = self.run_git(self.origin, 'rev-parse', 'HEAD')
        self.profile = root / 'deploy-profile'
        self.profile.write_text('hosted\n')
        self.config = root / 'party-core.json'
        self.config.write_text(json.dumps({'hosts': ['avrana.party'], 'origins': ['https://avrana.party']}))
        self.smoke_args = root / 'smoke-args.log'
        self.env.update(AVRANA_DEPLOY_PROFILE_FILE=str(self.profile), AVRANA_PARTY_CORE_CONFIG=str(self.config),
                        SMOKE_ARGS_LOG=str(self.smoke_args), ACTIVE_GAME_UNITS='avrana-game@bestguess.service avrana-game@checkers.service')

    def test_restarts_party_core_and_the_running_native_games_never_the_appliance_units(self):
        from avrana.ops import manifest
        self.smoke('pass')
        r = self.deploy(self.target_party, self.target_games)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        doc = manifest.read(self.manifest_path)
        self.assertEqual(sorted(doc['restarted']),
                         ['avrana-game@bestguess.service', 'avrana-game@checkers.service', 'avrana-party-core'])
        calls = self.calls()
        for unit in ('avranaparty-arcade', 'avranaparty-games'):
            self.assertFalse(any(unit in c for c in calls), calls)
        # providers first, then the party: the games start before Party Core
        starts = self.starts()
        self.assertLess(starts.index('start avrana-game@bestguess.service'), starts.index('start avrana-party-core'))
        self.assertTrue(doc['deploy_options']['hosted_profile'])

    def test_installs_the_hosted_site_file_not_the_appliance_one(self):
        self.smoke('pass')
        r = self.deploy(self.target_party, self.target_games)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.site.read_text(), HOSTED_SITE)

    def test_smoke_is_the_hosted_set_with_the_party_core_config(self):
        self.smoke('pass')
        r = self.deploy(self.target_party, self.target_games)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        args = self.smoke_args.read_text().split()
        self.assertEqual(args[:2], ['--json', '--hosted'])
        self.assertEqual(args[2:], ['--config', str(self.config)])

    def test_a_party_commit_without_the_hosted_site_file_is_refused_before_anything_changes(self):
        r = self.deploy(self.before_party, self.target_games, '--skip-smoke')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('deploy/hosted/avrana-party.hosted.nginx', r.stdout + r.stderr)
        self.assertEqual(self.site.read_bytes(), self.site_before)
        self.assertEqual(self.starts(), [])

    def test_an_unknown_profile_is_refused(self):
        self.profile.write_text('cloud\n')
        r = self.deploy(self.target_party, self.target_games, '--skip-smoke')
        self.assertEqual(r.returncode, 1)
        self.assertIn('profiles are pi and hosted', r.stderr)
        self.assertEqual(self.calls(queries=True), [])

    def test_the_profile_file_override_is_test_only(self):
        lines = SCRIPT.read_text().splitlines()
        n = next(i for i, line in enumerate(lines) if line.startswith('for v in AVRANA_DEPLOY_SMOKE'))
        loop = lines[n]
        while loop.endswith('\\'):                            # the list continues on the next line
            n += 1
            loop = loop[:-1] + lines[n]
        self.assertIn('AVRANA_DEPLOY_PROFILE_FILE', loop)     # a production run never reads another profile file

    def test_the_party_host_comes_from_the_config(self):
        self.smoke('pass')
        r = self.deploy(self.target_party, self.target_games, '--dry-run')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn('party.avrana.net', r.stdout)


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

    def test_the_public_catalog_directory_does_not_keep_the_manifest_directory_closed(self):
        """AVR-337: the effective catalog lives in /var/lib/avrana-party/catalog (0755, served by nginx); only a
        writable one, or any other open directory, is a reason to leave the manifest directory as it is."""
        state = self.manifest_path.parent
        state.mkdir()
        (state / 'lego').mkdir()
        (state / 'catalog').mkdir()
        state.chmod(0o700)
        (state / 'lego').chmod(0o700)
        (state / 'catalog').chmod(0o755)
        r = self.deploy(self.target_party, self.target_games, '--skip-smoke')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(state.stat().st_mode & 0o777, 0o711)
        self.assertEqual((state / 'catalog').stat().st_mode & 0o777, 0o755)
        (state / 'catalog').chmod(0o775)                      # writable by a group: not a public directory any more
        state.chmod(0o700)
        r = self.deploy(self.before_party, self.before_games, '--skip-smoke')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(state.stat().st_mode & 0o777, 0o700)
        self.assertIn('left as it is', r.stdout)

    def _state(self, **dirs):
        """The manifest's directory 0700 with the named subdirectories (name=mode); returns it."""
        state = self.manifest_path.parent
        state.mkdir()
        for name, mode in dirs.items():
            (state / name).mkdir()
            (state / name).chmod(mode)
        state.chmod(0o700)
        return state

    def test_a_catalog_directory_of_another_owner_does_not_keep_the_exemption(self):
        state = self._state(lego=0o700, catalog=0o755)
        r = self.deploy(self.target_party, self.target_games, '--skip-smoke', AVRANA_DEPLOY_CATALOG_OWNER_UID=str(os.getuid() + 1))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(state.stat().st_mode & 0o777, 0o700)
        self.assertIn('left as it is', r.stdout)

    def test_another_open_directory_beside_the_catalog_still_keeps_it_closed(self):
        state = self._state(lego=0o700, catalog=0o755, other=0o755)
        r = self.deploy(self.target_party, self.target_games, '--skip-smoke')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(state.stat().st_mode & 0o777, 0o700)
        self.assertIn('left as it is', r.stdout)

    def test_a_link_named_catalog_is_never_exempt(self):
        state = self._state(lego=0o700, elsewhere=0o700)
        (state / 'catalog').symlink_to(state / 'elsewhere')
        r = self.deploy(self.target_party, self.target_games, '--skip-smoke')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(state.stat().st_mode & 0o777, 0o700)
        self.assertIn('left as it is', r.stdout)


class FailedGameUnitsPreflight(Harness):
    """A native game unit left failed is a note in /party/api/status (AVR-33; it degrades only for a live
    session's game, so it never fails a deployment's smoke): the preflight names the units and the command that clears them before
    anything is switched, and clears nothing itself."""

    def test_failed_game_units_are_listed_with_the_reset_command_before_switching(self):
        units = 'avrana-game@checkers.service avrana-game@checkers.socket'
        r = self.deploy(self.target_party, self.target_games, '--dry-run', FAILED_GAME_UNITS=units)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f'WARNING: failed native game units: {units}', r.stdout)
        self.assertIn(f'sudo systemctl reset-failed {units}', r.stdout)
        self.assertIn('dry run: nothing changed', r.stdout)
        self.assertFalse([c for c in self.calls() if c.startswith('reset-failed')], 'the operator clears them, not the script')
        self.assertTrue(any(c.startswith('list-units') and 'avrana-game@*' in c for c in self.calls(queries=True)))

    def test_no_failed_game_units_says_nothing(self):
        r = self.deploy(self.target_party, self.target_games, '--dry-run')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn('failed native game units', r.stdout)


class CatalogOverlayOnReleaseChanges(Harness):
    """AVR-337: an effective catalog left behind by another web release is never served after a deployment, a
    rollback or a run that is undone. As root the overlay is regenerated; as the test's user it is removed: both end
    with no stale file, and neither fails the run."""

    def setUp(self):
        super().setUp()
        root = Path(self.temp.name)
        self.overlay = root / 'catalog' / 'catalog.json'
        self.overlay.parent.mkdir()
        (root / 'records').mkdir()
        self.env.update(AVRANA_CATALOG_OVERLAY=str(self.overlay), AVRANA_PACKAGE_RECORDS=str(root / 'records'))

    def plant(self):
        self.overlay.write_text('STALE: built for another release')

    def test_a_deployment_does_not_leave_the_overlay_of_the_previous_release(self):
        self.plant()
        r = self.deploy(self.target_party, self.target_games, '--skip-smoke')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)         # warning only, never a failed deployment
        self.assertFalse(self.overlay.exists(), r.stdout)

    def test_a_deployment_that_is_undone_does_not_leave_the_overlay_of_the_failed_release(self):
        """The overlay appears while the failed release is the web release (after it was switched in); the undo
        puts the earlier web release back and must take the file with it."""
        code, out = self.deploy_interrupted(self.target_party, self.target_games, 'switched', signal.SIGTERM,
                                            '--skip-smoke', during=self.plant)
        self.assertNotEqual(code, 0, out)
        self.assertIn('rolling back', out)
        self.assertFalse(self.overlay.exists(), out)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.before_party)

    def test_a_unit_that_does_not_come_back_leaves_no_stale_overlay(self):
        self.plant()
        r = self.deploy(self.target_party, self.target_games, '--skip-smoke', FAIL_UNIT='avrana-party-core')
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(self.overlay.exists(), r.stdout)

    def test_a_rollback_leaves_no_stale_overlay(self):
        self.smoke('pass')
        self.assertEqual(self.deploy(self.target_party, self.target_games).returncode, 0)
        self.assertEqual(self.deploy(self.before_party, self.before_games, '--skip-smoke').returncode, 0)
        self.plant()
        self.smoke('pass')
        r = self.script('--rollback')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(self.overlay.exists(), r.stdout)

    def test_a_rollback_to_a_commit_that_predates_the_overlay_removes_it_and_still_succeeds(self):
        """The release `current` points to after the rollback has no overlay code at all: the first-party catalog is
        served (packages have no tile until the next forward deploy), and the rollback's exit status is unchanged."""
        self.run_git(self.origin, 'rm', '-q', 'avrana/ops/catalog_overlay.py')
        self.run_git(self.origin, 'commit', '-q', '-m', 'a commit that predates the overlay')
        old = self.run_git(self.origin, 'rev-parse', 'HEAD')
        self.smoke('pass')
        self.assertEqual(self.deploy(old, self.before_games).returncode, 0)           # the last known good
        self.assertFalse((self.party_release.resolve() / 'avrana/ops/catalog_overlay.py').exists())
        self.assertEqual(self.deploy(self.target_party, self.target_games, '--skip-smoke').returncode, 0)
        self.assertTrue((self.party_release.resolve() / 'avrana/ops/catalog_overlay.py').exists())
        self.plant()
        self.smoke('pass')
        r = self.script('--rollback')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), old)
        self.assertFalse(self.overlay.exists(), r.stdout)


class CatalogSettleCallSites(Harness):
    """AVR-337: one test per call site of settle_catalog that fails when that call is deleted. The tool runs as "root"
    through a shim (a test user is not root, so the real one only ever removes) and writes a marker naming the web
    release it was derived from; the hook of install-party-web.sh runs the real tool as the test user, which refuses to
    write, so only deploy.sh's own call can produce the file."""

    def setUp(self):
        super().setUp()
        root = Path(self.temp.name)
        self.overlay = root / 'catalog' / 'catalog.json'
        self.overlay.parent.mkdir()
        (root / 'records').mkdir()
        (root / 'records' / 'hello.json').write_text('{}')            # a package is installed: the settle has work to do
        shim = catalog_tool_shim(root / 'shim')
        self.env.update(AVRANA_CATALOG_OVERLAY=str(self.overlay), AVRANA_PACKAGE_RECORDS=str(root / 'records'),
                        AVRANA_CATALOG_PYTHON=str(shim / 'python3'), SETTLE_STUB='1', SETTLE_LOCK=str(root / 'install.lock'))
        # (ops/deploy.sh and install-party-web.sh put /usr/bin first on PATH, so a shim there would never be found:
        # deploy.sh's settle takes its interpreter from the test-only AVRANA_CATALOG_PYTHON. The hook of
        # install-party-web.sh runs the real tool as the test user, which refuses to write: only settle can.)

    def marker(self):
        return 'EFFECTIVE-FOR ' + (self.web / 'current' / 'catalog.json').read_text()

    def test_a_deployment_regenerates_the_overlay_for_the_web_release_it_installed(self):
        r = self.deploy(self.target_party, self.target_games, '--skip-smoke')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(self.overlay.exists(), r.stdout)
        self.assertEqual(self.overlay.read_text(), self.marker(), r.stdout)
        self.assertEqual(r.stdout.count('the effective catalog matches web release'), 1)       # and settled once

    def test_an_undone_deployment_regenerates_the_overlay_for_the_release_that_was_put_back(self):
        self.assertEqual(self.deploy(self.target_party, self.target_games, '--skip-smoke').returncode, 0)
        before = self.marker()
        code, out = self.deploy_interrupted(self.before_party, self.target_games, 'switched', signal.SIGTERM, '--skip-smoke',
                                            during=lambda: self.overlay.write_text('STALE: the failed release'))
        self.assertNotEqual(code, 0, out)
        self.assertIn('rolling back', out)
        self.assertTrue(self.overlay.exists(), out)
        self.assertEqual(self.overlay.read_text(), before, out)
        self.assertLess(out.index('catalog: the effective catalog was removed until'),
                        out.index('the effective catalog matches web release', out.index('rolling back')))


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
        self.assertEqual(self.nginx_calls(), ['nginx -t', 'nginx -t'])           # the baseline, then the new file
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
        (self.origin / 'arcade/nginx-site').write_bytes(reject)
        self.run_git(self.origin, 'commit', '-q', '-am', 'a site that names a missing certificate')
        bad = self.run_git(self.origin, 'rev-parse', 'HEAD')
        r = self.deploy(bad, self.target_games, '--skip-smoke')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(self.site.read_bytes(), self.site_before)                      # the previous file is back
        self.assertEqual(self.nginx_calls(), ['nginx -t'] * 3)                          # baseline, rejected, restored one tested
        self.assertEqual(self.calls().count('reload nginx'), 1)                         # ...and reloaded
        self.assertIn('nginx -t REJECTED', r.stdout)
        self.assertIn('cannot load certificate', r.stdout)
        self.assertIn('MISSING PREREQUISITE', r.stdout)
        self.assertIn('docs/runbooks/game-origin.md', r.stdout)
        self.assertFalse([c for c in self.calls() if c.startswith('stop ')])            # nothing was stopped
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.before_party)
        self.assertFalse(self.manifest_path.exists())
        self.assertEqual(self.journal()['phase'], 'rolled-back')

    def test_two_tracked_copies_that_differ_are_refused_before_anything_changes(self):
        (self.origin / 'arcade/nginx-site').write_bytes(self.target_site() + b'# drift\n')
        self.run_git(self.origin, 'commit', '-q', '-am', 'the copies drift apart')
        drifted = self.run_git(self.origin, 'rev-parse', 'HEAD')
        r = self.deploy(drifted, self.target_games, '--skip-smoke')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('must be byte-identical', r.stderr)
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.site.read_bytes(), self.site_before)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.before_party)
        r = self.deploy(drifted, self.target_games, '--skip-smoke', '--skip-nginx-site')   # the opt-out still deploys
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

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
        self.assertEqual(self.nginx_calls(), ['nginx -t'] * 3)

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
        r = self.deploy(self.before_party, self.target_games, '--no-auto-rollback')            # accepted, a no-op
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(self.record()['party_sha'], self.target_party)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.before_party)    # kept for debugging
        doc = self.manifest()
        self.assertEqual(doc['smoke']['status'], 'failed')
        self.assertFalse(doc['deploy_options']['auto_rollback'])                              # the default, on the record
        self.assertIn('sudo bash', r.stdout)
        self.assertIn('--rollback', r.stdout)                                                 # the single command back

    def test_a_failed_smoke_rolls_back_to_the_last_known_good_and_reports_both_results(self):
        self.smoke('pass')
        self.assertEqual(self.deploy(self.target_party, self.target_games).returncode, 0)
        self.assertEqual(self.site.read_bytes(), self.target_site())
        self.smoke('pass', 'fail:games', 'pass')                                    # baseline, after, after the rollback
        r = self.deploy(self.before_party, self.before_games, '--auto-rollback')
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)                      # failed, rolled back cleanly
        self.assertIn('smoke FAILED', r.stdout)
        self.assertIn('AUTOMATIC ROLLBACK (--auto-rollback): games passed before', r.stdout)
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
        queue = self.smoke('pass', 'fail', 'fail', 'pass')                          # a fourth result must never be used
        r = self.deploy(self.before_party, self.before_games, '--auto-rollback')
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertIn('ROLLBACK APPLIED BUT ITS SMOKE ALSO FAILED', r.stdout)
        self.assertEqual(r.stdout.count('AUTOMATIC ROLLBACK'), 1)                  # no loop
        self.assertEqual(queue.read_text(), 'pass\n')
        self.assertEqual(self.journal()['phase'], 'rollback-failed')

    def test_the_first_deployment_ever_keeps_the_old_behaviour(self):
        self.smoke('fail')
        r = self.deploy(self.target_party, self.target_games)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('No last known good exists yet', r.stdout)
        self.assertIn(f'--party {self.before_party} --games {self.before_games}', r.stdout)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.target_party)
        self.assertFalse(self.lkg.exists())

    def test_never_back_to_the_pair_that_just_failed(self):
        self.smoke('pass')
        self.assertEqual(self.deploy(self.target_party, self.target_games).returncode, 0)
        self.smoke('pass', 'fail')
        r = self.deploy(self.target_party, self.target_games, '--auto-rollback')    # the same pair again
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('the very pair that failed', r.stdout)
        self.assertNotIn('AUTOMATIC ROLLBACK', r.stdout)

    def test_an_appliance_deployed_before_the_record_existed_is_seeded_from_its_running_deployment(self):
        self.smoke('pass')
        self.assertEqual(self.deploy(self.target_party, self.target_games).returncode, 0)
        self.lkg.unlink()                                                           # as on the Pi today
        self.smoke('pass', 'fail', 'pass')
        r = self.deploy(self.before_party, self.before_games, '--auto-rollback')
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn('last-known-good seeded from the running deployment', r.stdout)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.target_party)
        # a running deployment that did not pass is no record
        self.lkg.unlink()
        self.smoke('pass', 'fail')
        r = self.deploy(self.before_party, self.before_games, '--skip-smoke')
        r = self.deploy(self.target_party, self.target_games, '--auto-rollback')
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


class Pruning(Harness):
    """AVR-271: old code releases, web releases and deploy backups are pruned to the newest N, only after a
    passed smoke, and never what the running state or a rollback points at."""

    def fixture(self):
        """Old releases and backups, and things that must never be touched."""
        import time
        root = Path(self.temp.name)
        self.outside = root / 'outside'
        self.outside.mkdir()
        (self.outside / 'precious').write_text('keep me')
        old = time.time() - 90 * 86400
        self.party_old = []
        for i in range(1, 7):
            d = root / 'opt-party' / 'releases' / f'{i:040x}'
            d.mkdir(parents=True)
            (d / 'x').write_text('x')
            os.utime(d, (old + i, old + i))
            self.party_old.append(d)
        releases = root / 'opt-party' / 'releases'
        (releases / ('e' * 40)).symlink_to(self.outside)                     # named like a release, is a link
        (releases / 'weird name').mkdir()
        (releases / '.new.abc').mkdir()
        self.backups = root / 'backups'
        self.backup_old = []
        for i in range(1, 6):
            d = self.backups / f'deploy-2020010{i}T000000Z'
            d.mkdir(parents=True)
            self.backup_old.append(d)
        (self.backups / 'deploy-20190101T000000Z').symlink_to(self.outside)
        (self.backups / 'deploy-notes.txt').write_text('a file')
        import time as _time
        stale = _time.time() - 3 * 86400
        self.junk = [releases / '.new.Abc123', self.web / 'releases' / '.build.Zz9Yy8', self.backups / 'deploy.journal.tmp.123']
        (releases / '.new.Abc123').mkdir()
        (self.web / 'releases').mkdir(parents=True, exist_ok=True)
        (self.web / 'releases' / '.build.Zz9Yy8').mkdir()
        (self.backups / 'deploy.journal.tmp.123').write_text('x')
        self.logs = []
        for i in range(1, 9):
            log = self.backups / f'deploy-2020010{i}T000000Z-1.log'
            log.write_text('x')
            self.logs.append(log)
        for path in self.junk:
            os.utime(path, (stale, stale))
        self.fresh_junk = releases / '.new.Fresh1'                                # a build that may still be running
        self.fresh_junk.mkdir()
        self.web_old = []
        for i in range(1, 5):
            d = self.web / 'releases' / f'2020010{i}T000000Z-aaaaaaaaaaaa'
            d.mkdir(parents=True)
            self.web_old.append(d)

    def assert_untouchables_untouched(self):
        releases = Path(self.temp.name) / 'opt-party' / 'releases'
        self.assertEqual((self.outside / 'precious').read_text(), 'keep me')
        self.assertTrue((releases / ('e' * 40)).is_symlink())
        self.assertTrue((releases / 'weird name').is_dir() and (releases / '.new.abc').is_dir())
        self.assertTrue((self.backups / 'deploy-20190101T000000Z').is_symlink())
        self.assertTrue((self.backups / 'deploy-notes.txt').is_file())
        self.assertTrue((self.backups / 'deploy.journal').is_file())

    def test_after_a_passed_smoke_only_the_newest_n_remain_and_nothing_unexpected_is_touched(self):
        self.fixture()
        self.smoke('pass')
        r = self.deploy(self.target_party, self.target_games, '--keep', '3')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual([d.exists() for d in self.party_old], [False, False, False, False, True, True])   # newest 3 incl. the new one
        self.assertTrue(self.party_release.resolve().is_dir())
        self.assertEqual([d.exists() for d in self.backup_old], [False, False, False, True, True])           # + this run's backup
        self.assertEqual([d.exists() for d in self.web_old], [False, False, True, True])
        self.assertEqual(len(list((self.web / 'releases').iterdir())), 3)
        self.assert_untouchables_untouched()
        self.assertIn('prune: party code releases: removed', r.stdout)
        self.assertEqual([p.exists() for p in self.junk], [False, False, False])           # stale leftovers
        self.assertTrue(self.fresh_junk.exists())                                          # a fresh one is not touched
        self.assertEqual([p.exists() for p in self.logs], [False] * 5 + [True] * 3)        # the newest 3 run logs
        self.assertEqual(self.web.joinpath('current').resolve().name[-12:], self.target_party[:12])

    def test_nothing_is_pruned_unless_the_smoke_passed(self):
        self.fixture()
        self.smoke('fail')
        r = self.deploy(self.target_party, self.target_games, '--keep', '3')
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('NOT pruned', r.stdout)
        r = self.deploy(self.target_party, self.target_games, '--keep', '3', '--skip-smoke')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('NOT pruned', r.stdout)
        self.assertTrue(all(d.exists() for d in self.party_old + self.backup_old + self.web_old))

    def test_no_prune_leaves_everything(self):
        self.fixture()
        self.smoke('pass')
        r = self.deploy(self.target_party, self.target_games, '--keep', '3', '--no-prune')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('not pruned (--no-prune)', r.stdout)
        self.assertTrue(all(d.exists() for d in self.party_old + self.backup_old + self.web_old))

    def test_the_dry_run_lists_what_would_be_pruned_and_removes_nothing(self):
        self.fixture()
        r = self.deploy(self.target_party, self.target_games, '--dry-run', '--keep', '3')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f'prune: party code releases: would remove {1:040x}', r.stdout)
        self.assertIn('prune: deploy backups: would remove deploy-20200101T000000Z', r.stdout)
        self.assertNotIn(f'would remove {6:040x}', r.stdout)
        self.assertTrue(all(d.exists() for d in self.party_old + self.backup_old + self.web_old))

    def test_a_releases_directory_that_is_a_link_is_never_followed(self):
        self.fixture()
        victim = Path(self.temp.name) / 'victim'
        for i in range(1, 5):
            (victim / f'{i:040x}').mkdir(parents=True)
        (Path(self.temp.name) / 'opt-games').mkdir()
        (Path(self.temp.name) / 'opt-games' / 'releases').symlink_to(victim)
        self.smoke('pass')
        r = self.deploy(self.target_party, self.target_games, '--keep', '2')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('is not a plain directory; nothing removed', r.stdout)
        self.assertEqual(sorted(p.name for p in victim.iterdir() if p.name != self.target_games),
                         [f'{i:040x}' for i in range(1, 5)])

    def test_the_running_and_previous_releases_survive_even_when_older_than_the_newest_n(self):
        import time
        self.smoke('pass', 'pass')
        self.assertEqual(self.deploy(self.target_party, self.target_games).returncode, 0)
        root = Path(self.temp.name)
        future = time.time() + 3600
        for i in (1, 2):                                                           # two newer decoys fill the keep count
            d = root / 'opt-party' / 'releases' / f'{i:040x}'
            d.mkdir()
            os.utime(d, (future + i, future + i))
        old = root / 'opt-party' / 'releases' / ('9' * 40)
        old.mkdir()
        os.utime(old, (1000, 1000))
        r = self.deploy(self.before_party, self.before_games, '--keep', '2')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        releases = root / 'opt-party' / 'releases'
        self.assertTrue((releases / self.before_party).is_dir())                   # being deployed and running
        self.assertTrue((releases / self.target_party).is_dir())                   # the previous one, a rollback target
        self.assertFalse(old.exists())                                             # the unprotected old one is gone
        self.assertIn(f'keeping {self.target_party}', r.stdout)

    def test_keep_must_leave_the_running_and_the_previous_release(self):
        r = self.deploy(self.target_party, self.target_games, '--keep', '1', '--dry-run')
        self.assertEqual(r.returncode, 1)
        self.assertIn('--keep needs a number of at least 2', r.stderr)


class ContractAndOptions(Harness):
    """A pair that disagrees on the Party <-> Games contract is refused before anything changes; every flag
    that loosens a check is on the manifest's record."""

    def setUp(self):
        super().setUp()
        self.run_git(self.games, 'checkout', '-q', self.target_games)
        (self.games / 'provider').mkdir()
        (self.games / 'provider/avrana-contract.json').write_text('{}\n')
        self.run_git(self.games, 'add', 'provider')
        self.run_git(self.games, 'commit', '-q', '-m', 'declaration')
        self.declared_games = self.run_git(self.games, 'rev-parse', 'HEAD')
        self.run_git(self.games, 'checkout', '-q', '--detach', self.before_games)
        fake = Path(self.temp.name) / 'fake-python'
        fake.write_text('#!/usr/bin/env bash\n'
                        'if [[ $1 == tools/contract_check.py ]]; then echo "CONTRACT DRIFT: stub" >&2; exit 1; fi\n'
                        'exec python3 "$@"\n')
        fake.chmod(0o755)
        self.env['AVRANA_DEPLOY_PYTHON'] = str(fake)

    def test_a_contract_mismatch_is_refused_before_anything_is_stopped(self):
        r = self.deploy(self.target_party, self.declared_games, '--skip-smoke')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('Party <-> Games contract', r.stderr)
        self.assertIn('nothing changed', r.stderr)
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.before_party)
        self.assertFalse(self.manifest_path.exists() or (Path(self.temp.name) / 'backups').exists())

    def test_every_flag_that_loosens_a_check_is_recorded_in_the_manifest(self):
        r = self.deploy(self.target_party, self.declared_games, '--skip-contract-check', '--skip-smoke',
                        '--force-busy', '--skip-nginx-site')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        doc = self.manifest()
        self.assertEqual(doc['contract_check']['status'], 'skipped')
        options = doc['deploy_options']
        self.assertEqual({k for k, v in options.items() if v is True},
                         {'skip_contract_check', 'skip_smoke', 'force_busy', 'skip_nginx_site'})

    def test_a_pair_that_agrees_is_recorded_as_compatible(self):
        fake = Path(self.temp.name) / 'fake-python'
        fake.write_text('#!/usr/bin/env bash\nif [[ $1 == tools/contract_check.py ]]; then exit 0; fi\nexec python3 "$@"\n')
        r = self.deploy(self.target_party, self.declared_games, '--skip-smoke')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.manifest()['contract_check']['status'], 'compatible')

    def test_a_rollback_to_a_pair_that_would_now_disagree_is_not_refused(self):
        """The checker of the newer commit may fail the old pair; a rollback must stay possible."""
        self.smoke('pass')
        self.assertEqual(self.deploy(self.target_party, self.target_games, '--skip-contract-check').returncode, 0)
        self.assertEqual(self.deploy(self.before_party, self.before_games, '--skip-smoke').returncode, 0)
        self.smoke('pass')
        r = self.script('--rollback')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.target_party)


class BaselineAutoRollback(Harness):
    """AVR-271 review: automatic rollback is opt-in (--auto-rollback), judged against a baseline smoke taken before
    anything is stopped, so only what this deployment broke can cause it; a slow start gets a settle window."""

    def good_first(self):
        self.smoke('pass')
        r = self.deploy(self.target_party, self.target_games)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_the_default_keeps_a_failed_revision_and_prints_the_one_command_back(self):
        self.good_first()
        self.smoke('fail:games')
        r = self.deploy(self.before_party, self.before_games)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertNotIn('AUTOMATIC ROLLBACK', r.stdout)
        self.assertIn('sudo bash', r.stdout)
        self.assertIn('ops/deploy.sh --rollback', r.stdout)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.before_party)
        self.assertEqual(self.manifest()['last_attempt']['outcome'], 'smoke-failed-kept')

    def test_a_genuine_regression_rolls_back_and_the_rollback_smoke_is_reported(self):
        self.good_first()
        self.smoke('pass', 'fail:games', 'pass')
        r = self.deploy(self.before_party, self.before_games, '--auto-rollback')
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.target_party)
        doc = self.manifest()
        self.assertTrue(doc['deploy_options']['auto_rollback'] is False)          # the nested rollback ran without it
        self.assertEqual(doc['last_attempt'], dict(doc['last_attempt'], party_sha=self.before_party, outcome='rolled-back'))
        self.assertTrue(doc['last_attempt']['backup'].startswith('deploy-'))
        self.assertEqual(doc['party']['sha'], self.target_party)

    def test_a_regression_and_a_failed_rollback_smoke_is_exit_4(self):
        self.good_first()
        self.smoke('pass', 'fail:units', 'fail:units')
        r = self.deploy(self.before_party, self.before_games, '--auto-rollback')
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertEqual(self.manifest()['last_attempt']['outcome'], 'rollback-failed')

    def test_a_check_that_already_failed_before_the_deploy_does_not_roll_it_back(self):
        self.good_first()
        for baseline, after in (('fail:certificate', 'fail:certificate'),            # certificate expiring before and after
                                ('fail:status', 'fail:status')):                      # an already stale web build / site file
            with self.subTest(baseline=baseline):
                self.smoke(baseline, after)
                r = self.deploy(self.before_party, self.before_games, '--auto-rollback')
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn('PRE-EXISTING, NOT CAUSED BY THIS DEPLOY', r.stdout)
                self.assertNotIn('AUTOMATIC ROLLBACK', r.stdout)
                self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.before_party)
                self.assertEqual(self.deploy(self.target_party, self.target_games, '--skip-smoke').returncode, 0)

    def test_a_check_that_was_skipped_before_and_fails_after_is_not_called_pre_existing(self):
        self.good_first()
        self.smoke('skip:games', 'fail:games')
        r = self.deploy(self.before_party, self.before_games, '--auto-rollback')
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('NOT CHECKED BEFORE THE DEPLOY, FAILING AFTER: games', r.stdout)
        self.assertNotIn('PRE-EXISTING', r.stdout)
        self.assertNotIn('AUTOMATIC ROLLBACK', r.stdout)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.before_party)       # kept
        self.assertEqual(self.record()['party_sha'], self.target_party)                           # never the last known good
        self.smoke('pass')                                                                       # the cause is fixed
        r = self.script('--finish')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.journal()['phase'], 'smoke-passed')
        self.assertEqual(self.record()['party_sha'], self.before_party)                          # now it is

    def test_skip_nginx_site_with_a_differing_live_file_does_not_roll_back(self):
        self.good_first()
        self.site.write_bytes(self.site_before)                                       # live no longer equals the deployed commit's
        self.smoke('fail:status', 'fail:status')
        r = self.deploy(self.before_party, self.before_games, '--auto-rollback', '--skip-nginx-site')
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('--auto-rollback is off for this run', r.stdout)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.before_party)
        self.assertEqual(self.site.read_bytes(), self.site_before)
        self.assertEqual(self.manifest()['nginx_site']['status'], 'skipped')

    def test_a_games_only_deploy_with_an_already_stale_web_build_does_not_roll_back(self):
        self.good_first()
        self.smoke('fail:status', 'fail:status')
        r = self.deploy(self.target_party, self.before_games, '--auto-rollback')
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('PRE-EXISTING', r.stdout)
        self.assertEqual(self.run_git(self.games, 'rev-parse', 'HEAD'), self.before_games)

    def test_allow_dirty_deployments_roll_back_too(self):
        self.good_first()
        (self.party / 'README.md').write_text('a local edit\n')
        self.smoke('pass', 'fail:games', 'pass')
        r = self.deploy(self.before_party, self.before_games, '--auto-rollback', '--allow-dirty')
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.target_party)
        self.assertEqual((self.party / 'README.md').read_text(), 'a local edit\n')           # never reset --hard

    def test_a_slow_start_that_answers_within_the_settle_window_is_not_a_failure(self):
        self.good_first()
        queue = self.smoke('pass', 'fail:games', 'fail:games', 'pass')
        r = self.deploy(self.before_party, self.before_games, '--auto-rollback', AVRANA_DEPLOY_SMOKE_SETTLE='30')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.count('smoke is not passing yet'), 2)
        self.assertEqual(queue.read_text(), '')
        self.assertEqual(self.manifest()['smoke']['status'], 'passed')
        self.assertEqual(self.record()['party_sha'], self.before_party)
        # and without the opt-in the settle window applies just the same
        self.smoke('fail:games', 'pass')
        r = self.deploy(self.target_party, self.target_games, AVRANA_DEPLOY_SMOKE_SETTLE='30')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_without_a_baseline_the_opt_in_is_off_for_that_run_and_says_so(self):
        self.smoke('fail:games')
        r = self.deploy(self.target_party, self.target_games, '--auto-rollback')            # the first deployment ever
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('--auto-rollback is off for this run: there is no running deployment', r.stdout)

    def test_the_baseline_is_kept_in_the_backup_directory_and_the_journal(self):
        self.good_first()
        self.smoke('fail:certificate', 'fail:certificate')
        self.deploy(self.before_party, self.before_games, '--auto-rollback')
        backup = sorted(d for d in (Path(self.temp.name) / 'backups').iterdir() if d.is_dir())[-1]
        names = {c['name']: c['status'] for c in json.loads((backup / 'smoke-baseline.json').read_text())['checks']}
        self.assertEqual(names['certificate'], 'fail')
        self.assertEqual(self.journal()['baseline_fail'], 'certificate')


class PostCommitFailures(Harness):
    """A failure after the commit point is never 'everything put back' (exit 1) and never leaves the journal open."""

    def run_step(self, step):
        self.smoke('pass')
        return self.deploy(self.target_party, self.target_games, AVRANA_DEPLOY_FAIL_STEP=step)

    def test_each_post_commit_step_that_fails_ends_in_a_terminal_phase_and_never_exit_1(self):
        for step, code in (('contract-record', 0), ('deploy-info', 0), ('prune', 0), ('copy-manifest', 2),
                           ('chmod-dir', 2), ('smoke-record', 2), ('lkg-record', 2)):
            with self.subTest(step=step):
                self.setUp()
                r = self.run_step(step)
                self.assertEqual(r.returncode, code, r.stdout + r.stderr)
                self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.target_party)   # kept, not restored
                self.assertIn(self.journal()['phase'], ('smoke-passed', 'post-commit-failed'))
                if code == 2:
                    self.assertEqual(self.journal()['phase'], 'post-commit-failed')
                    self.assertIn('applied and kept', r.stdout)
                # a closed journal does not block the next deploy
                self.smoke('pass')
                r2 = self.deploy(self.before_party, self.before_games, '--skip-smoke')
                self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)

    def test_finish_closes_a_post_commit_journal_and_records_the_last_known_good_only_after_smoke_passes(self):
        r = self.run_step('lkg-record')
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertFalse(self.lkg.exists())
        self.smoke('fail')
        r = self.script('--finish')
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertFalse(self.lkg.exists())
        self.assertEqual(self.journal()['phase'], 'smoke-failed')
        # the journal is closed now, so --finish refuses to run again; reopen it as a run killed after the commit point
        self.setUp()
        self.smoke('pass')
        (self.hooks / 'pause-at-committed').write_text('')
        code, out = self.deploy_interrupted(self.target_party, self.target_games, 'committed', signal.SIGKILL)
        self.assertEqual(self.journal()['phase'], 'committed')
        import time
        time.sleep(1)
        r = self.deploy(self.before_party, self.before_games, '--skip-smoke')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('--finish', r.stderr)
        self.smoke('pass')
        r = self.script('--finish')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.journal()['phase'], 'smoke-passed')
        self.assertEqual(self.record()['party_sha'], self.target_party)
        self.assertEqual(self.manifest()['smoke']['status'], 'passed')
        r = self.script('--finish')                                                    # nothing left to finish
        self.assertEqual(r.returncode, 1)


class NginxBaselineAndCertificateNames(Harness):
    def test_an_existing_configuration_that_already_fails_nginx_t_is_refused_with_nothing_changed(self):
        self.site.write_bytes(self.site_before + b'# FAKE-NGINX-REJECT\n')
        r = self.deploy(self.target_party, self.target_games, '--skip-smoke')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('existing nginx configuration is already invalid', r.stderr)
        self.assertIn('cannot load certificate', r.stderr)                               # the first lines of nginx's own output
        self.assertIn('nothing changed', r.stderr)
        self.assertEqual(self.nginx_calls(), ['nginx -t'])
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.before_party)

    def leftovers(self):
        root = Path(self.temp.name)
        backups = [p.name for p in (root / 'backups').glob('deploy-*') if p.is_dir()] if (root / 'backups').exists() else []
        staged = [str(p) for base in ('opt-party', 'opt-games') if (root / base / 'releases').exists()
                  for p in (root / base / 'releases').iterdir()]
        return backups + staged

    def test_a_refusal_after_the_backup_was_made_leaves_no_backup_and_no_staged_release(self):
        self.site.write_bytes(self.site_before + b'# FAKE-NGINX-REJECT\n')
        r = self.deploy(self.target_party, self.target_games, '--skip-smoke')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('nothing changed', r.stderr)
        self.assertEqual(self.leftovers(), [])

    def test_a_refusal_for_the_certificate_names_leaves_nothing_behind_either(self):
        self.fake_openssl()
        r = self.deploy(self.target_party, self.target_games, '--skip-smoke', '--require-cert-names')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('nothing changed', r.stderr)
        self.assertEqual(self.leftovers(), [])

    def test_require_cert_names_is_enforced_when_the_site_file_already_matches_too(self):
        self.site.write_bytes(self.target_site())
        self.fake_openssl()
        r = self.deploy(self.target_party, self.target_games, '--skip-smoke', '--require-cert-names')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('--require-cert-names', r.stderr)
        self.assertEqual(self.calls(), [])
        r = self.deploy(self.target_party, self.target_games, '--skip-smoke')                  # without the flag it is a warning
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def commit_site(self, text):
        data = text.encode()
        for name in ('avrana-party.nginx', 'arcade/nginx-site'):
            (self.origin / name).write_bytes(data)
        self.run_git(self.origin, 'commit', '-q', '-am', 'a site file')
        return self.run_git(self.origin, 'rev-parse', 'HEAD')

    def test_only_port_443_counts_as_a_tls_listener_for_the_certificate_names(self):
        self.fake_openssl()
        for listen, mismatch in (('listen 8443 ssl;', []), ('listen [::]:8443 ssl http2;', []),
                                 ('listen 443 ssl;', ['games.avrana.net']), ('listen [::]:443 ssl http2;', ['games.avrana.net']),
                                 ('listen 0.0.0.0:443 ssl;', ['games.avrana.net'])):
            with self.subTest(listen=listen):
                sha = self.commit_site('server { listen 443 ssl; server_name party.avrana.net; ssl_certificate /c.pem; }\n'
                                       f'server {{ {listen} server_name games.avrana.net; ssl_certificate /c.pem; }}\n')
                r = self.deploy(sha, self.target_games, '--skip-smoke')
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(self.manifest()['nginx_site']['cert_name_mismatch'], mismatch, r.stdout)

    def test_a_failing_baseline_does_not_stop_recover_or_rollback_from_putting_the_known_good_site_back(self):
        import time
        self.smoke('pass')
        self.assertEqual(self.deploy(self.target_party, self.target_games).returncode, 0)        # the last known good
        (self.hooks / 'pause-at-site-installed').write_text('')
        proc = subprocess.Popen([BASH, str(SCRIPT), '--party', self.before_party, '--games', self.before_games, '--skip-smoke'],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                env=dict(self.env, AVRANA_DEPLOY_TEST_HOOK_DIR=str(self.hooks)))
        deadline = time.time() + 120
        while not (self.hooks / 'reached-site-installed').exists():
            self.assertLess(time.time(), deadline)
            time.sleep(0.05)
        proc.kill()                                                                              # died with the site file replaced
        proc.communicate()
        time.sleep(1)
        self.site.write_bytes(self.site.read_bytes() + b'# FAKE-NGINX-REJECT\n')                  # and nginx rejects what is live
        self.smoke('pass')
        r = self.script('--recover')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('nginx -t fails', r.stdout)
        self.assertEqual(self.site.read_bytes(), self.target_site())                             # the known good site file, validated
        self.assertEqual(self.journal()['phase'], 'smoke-passed')
        # the same for --rollback: running something else, live site file rejected
        self.assertEqual(self.deploy(self.before_party, self.before_games, '--skip-smoke').returncode, 0)
        self.site.write_bytes(self.site.read_bytes() + b'# FAKE-NGINX-REJECT\n')
        self.smoke('pass')
        r = self.script('--rollback')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.site.read_bytes(), self.target_site())

    def fake_openssl(self):
        shim = Path(self.temp.name) / 'fake-openssl'
        shim.write_text(OPENSSL_SHIM)
        shim.chmod(0o755)
        self.env['AVRANA_OPENSSL'] = str(shim)

    def test_a_certificate_that_does_not_cover_a_server_name_warns_and_is_recorded_but_does_not_refuse(self):
        self.fake_openssl()
        r = self.deploy(self.target_party, self.target_games, '--skip-smoke')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('does not cover games.avrana.net', r.stdout)
        self.assertIn('docs/runbooks/game-origin.md', r.stdout)
        self.assertIn('party.avrana.net is covered', r.stdout)
        self.assertEqual(self.manifest()['nginx_site']['cert_name_mismatch'], ['games.avrana.net'])
        r = self.deploy(self.target_party, self.target_games, '--dry-run')
        self.assertIn('WARNING: the certificate', r.stdout)

    def test_require_cert_names_makes_it_a_refusal_before_anything_changes(self):
        self.fake_openssl()
        r = self.deploy(self.target_party, self.target_games, '--skip-smoke', '--require-cert-names')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('--require-cert-names', r.stderr)
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.site.read_bytes(), self.site_before)


class RecoverIsSafe(Harness):
    def kill_at_switched(self, party, games):
        import time
        (self.hooks / 'pause-at-switched').write_text('')
        proc = subprocess.Popen([BASH, str(SCRIPT), '--party', party, '--games', games, '--skip-smoke'],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                env=dict(self.env, AVRANA_DEPLOY_TEST_HOOK_DIR=str(self.hooks)))
        deadline = time.time() + 120
        while not (self.hooks / 'reached-switched').exists():
            self.assertLess(time.time(), deadline)
            time.sleep(0.05)
        proc.kill()
        proc.communicate()
        time.sleep(1)

    def test_on_a_healthy_machine_recover_is_a_no_op(self):
        self.smoke('pass')
        self.assertEqual(self.deploy(self.target_party, self.target_games).returncode, 0)
        before = self.calls()
        r = self.script('--recover')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('nothing to recover', r.stdout)
        self.assertEqual(self.calls(), before)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.target_party)

    def test_recover_does_not_move_a_revision_that_was_kept_on_purpose(self):
        self.smoke('pass')
        self.assertEqual(self.deploy(self.target_party, self.target_games).returncode, 0)
        self.assertEqual(self.deploy(self.before_party, self.before_games, '--skip-smoke').returncode, 0)
        r = self.script('--recover')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('--rollback', r.stderr)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.before_party)
        self.smoke('pass')
        r = self.script('--recover', '--force')                                          # an explicit override
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.target_party)

    def test_recover_keeps_the_busy_check(self):
        import http.server
        import threading
        self.smoke('pass')
        self.assertEqual(self.deploy(self.target_party, self.target_games).returncode, 0)
        self.kill_at_switched(self.before_party, self.before_games)

        class Busy(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = b'{"session": {"state": "active"}}'
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(('127.0.0.1', 0), Busy)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        busy = {'AVRANA_PARTY_CORE_URL': f'http://127.0.0.1:{server.server_address[1]}'}
        self.smoke('pass')
        r = self.script('--recover', **busy)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('a game session is live', r.stderr)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.before_party)
        r = self.script('--recover', '--force-busy', **busy)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.target_party)

    def test_the_first_rollback_seeds_the_record_from_a_qualifying_running_deployment(self):
        self.smoke('pass')
        self.assertEqual(self.deploy(self.target_party, self.target_games).returncode, 0)
        self.lkg.unlink()
        self.smoke('pass')
        r = self.script('--rollback')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('last-known-good seeded from the running deployment', r.stdout)
        self.assertEqual(self.record()['party_sha'], self.target_party)


class LastAttempt(Harness):
    def test_an_interrupted_and_restored_run_leaves_a_last_attempt_on_the_previous_manifest(self):
        self.smoke('pass')
        self.assertEqual(self.deploy(self.target_party, self.target_games).returncode, 0)
        code, out = self.deploy_interrupted(self.before_party, self.before_games, 'switched', signal.SIGTERM)
        self.assertEqual(code, 1, out)
        attempt = self.manifest()['last_attempt']
        self.assertEqual((attempt['party_sha'], attempt['outcome']), (self.before_party, 'interrupted-restored'))
        self.assertEqual(self.manifest()['party']['sha'], self.target_party)

    def test_a_refusal_after_validation_and_a_success_are_recorded(self):
        self.smoke('pass')
        self.assertEqual(self.deploy(self.target_party, self.target_games).returncode, 0)
        self.assertEqual(self.manifest()['last_attempt']['outcome'], 'ok')
        self.site.write_bytes(self.site_before + b'# FAKE-NGINX-REJECT\n')
        r = self.deploy(self.before_party, self.before_games, '--skip-smoke')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(self.manifest()['last_attempt']['outcome'], 'refused')


class SignalsWithSmokeAndLaterFailures(Harness):
    def test_signals_with_smoke_enabled_restore_everything_once(self):
        for phase, signame in (('stopped-services', 'TERM'), ('switched', 'HUP'), ('restarted', 'INT')):
            with self.subTest(phase=phase):
                self.setUp()
                self.smoke('pass')
                code, out = self.deploy_interrupted(self.target_party, self.target_games, phase, getattr(signal, 'SIG' + signame))
                self.assertEqual(code, 1, out)
                self.assertEqual(out.count('rolling back'), 1, out)
                self.assertEqual(self.run_git(self.party, 'rev-parse', 'HEAD'), self.before_party)
                self.assertEqual(self.site.read_bytes(), self.site_before)
                self.assertEqual(self.journal()['phase'], 'rolled-back')

    def test_a_signal_at_site_installed_followed_by_a_failing_restore_needs_a_person(self):
        code, out = self.deploy_interrupted(self.target_party, self.target_games, 'site-installed', signal.SIGTERM,
                                            '--skip-smoke', FAIL_RELOAD='second')
        self.assertEqual(code, 4, out)
        self.assertIn('ROLLBACK INCOMPLETE: nginx did not accept (or reload)', out)
        self.assertEqual(self.site.read_bytes(), self.site_before)                      # the file itself was put back
        self.assertEqual(self.journal()['phase'], 'rollback-failed')


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
        self.assertRegex(logs[0].name, r'^deploy-\d{8}T\d{6}Z-\d+\.log$')              # the pid keeps same-second runs apart
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
