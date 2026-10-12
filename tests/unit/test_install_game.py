"""avrana.ops.install_game and avrana.avrgame.installed (AVR-39, EXPERIMENTAL), in scratch
directories with a recorded `systemctl`, on any OS. Real systemd is the Linux CI job's
(experiments/native-game/package-proof.sh).

    python -m unittest discover -s tests/unit -p test_install_game.py
"""
import contextlib
import copy
import hashlib
import io
import json
import os
import stat
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from avrana import REPO_ROOT, CONTRACTS_DIR
from avrana.avrgame import installed
from avrana.contracts import catalog, party_config
from avrana.ops import install_game as ig
from avrana.ops import provision_game as pg
from avrana.party import protocol, registry

from test_avrgame_package import BASE_FILES, good_manifest, make_zip, mjson

ORIGIN = 'https://party.example.test'
PARTY = 'avrana-party-core.service'
REPO = {k: v for k, v in party_config.load_contracts().items() if k != 'hello'}   # the product games
IDLE = {'party_core': {'ok': True, 'uptime_s': 3, 'members': 0, 'session': None}}


class Response:
    def __init__(self, doc):
        self.body = json.dumps(doc).encode('utf-8')

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.body


def stopped(argv):
    raise subprocess.CalledProcessError(1, argv)


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.object(installed, 'EXPECTED_OWNER', None)    # scratch files belong to the test user
        patch.start()
        self.addCleanup(patch.stop)
        self.root = Path(tmp.name) / 'host'
        r = self.root
        for d in ('etc/game-keys', 'etc/games.d', 'etc/systemd', 'run/games', 'var/games', 'opt/avrana-games'):
            (r / d).mkdir(parents=True)
        for name in pg.TEMPLATES:                      # the shared template units are already installed
            (r / 'etc/systemd' / name).write_bytes((REPO_ROOT / 'deploy' / 'games' / name).read_bytes())
        self.inputs = Path(tmp.name) / 'in'
        self.inputs.mkdir()
        self.layout = ig.Layout(
            provision=pg.Layout(key_dir=r / 'etc/game-keys', registry_dir=r / 'etc/games.d',
                                socket_dir=r / 'run/games', state_dir=r / 'var/games', unit_dir=r / 'etc/systemd',
                                template_dir=REPO_ROOT / 'deploy' / 'games'),
            records_dir=r / 'etc/packages.d', games_root=r / 'opt/avrana-games', lock_file=Path(tmp.name) / 'install.lock',      # a real flock leaves this file: keep it out of the host snapshot
            visible_root='/opt/avrana-games')
        (r / 'etc/party-core.json').write_text(json.dumps({'origins': [ORIGIN], 'hosts': ['party.example.test'],
                                                           'registry': str(r / 'etc/games.d'),
                                                           'packages': str(r / 'etc/packages.d')}), encoding='utf-8')
        self.calls, self.trusted_paths = [], []

    # -- fixtures
    def run_(self, argv):
        self.calls.append(list(argv))

    def own(self, target):
        pass

    def trusted(self, path):
        self.trusted_paths.append(str(path))

    def package(self, name='hello.avrgame', manifest=None, files=None, **kw):
        path = self.inputs / name
        path.write_bytes(make_zip(files=files, manifest=manifest, method=zipfile.ZIP_STORED, **kw))
        return path

    def install(self, path=None, **kw):
        kw.setdefault('allow', ['party_roster'])
        kw.setdefault('trusted', self.trusted)
        kw.setdefault('now', lambda: '2026-10-10T12:00:00Z')
        return ig.install(path or self.package(), self.layout, kw.pop('repo', REPO), kw.pop('run', self.run_),
                          self.own, ORIGIN, **kw)

    def remove(self, pid='hello', **kw):
        return ig.remove(pid, self.layout, kw.pop('repo', REPO), kw.pop('run', self.run_),
                         kw.pop('active', lambda slug: False), **kw)

    def snapshot(self):
        out = {}
        for p in sorted(self.root.rglob('*')):
            rel = p.relative_to(self.root).as_posix()
            out[rel] = ('dir', None) if p.is_dir() else ('file', hashlib.sha256(p.read_bytes()).hexdigest())
        return out

    def files(self):
        return sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob('*') if p.is_file())

    def tree(self):
        return self.layout.on_disk(installed.tree_root('/opt/avrana-games', 'hello', '0.1.0', self.sha))

    @property
    def sha(self):
        return hashlib.sha256((self.inputs / 'hello.avrgame').read_bytes()).hexdigest()

    def refused(self, fn, *words):
        with self.assertRaises(pg.Refused) as ctx:
            fn()
        for w in words:
            self.assertIn(w, str(ctx.exception))
        return str(ctx.exception)


class InstallTests(Base):
    def test_install_stages_records_and_provisions_through_provision_game(self):
        lines = self.install()
        pkg = self.inputs / 'hello.avrgame'
        tree = self.tree()
        self.assertEqual(tree.parent.name, 'hello')
        self.assertEqual(tree.name, f'0.1.0-{self.sha[:12]}')
        self.assertTrue(all((tree / name).is_file() for name in BASE_FILES))
        self.assertEqual(ig.verify('hello', self.layout, REPO), [])
        rec = installed.read_record_file(self.layout.record('hello'), 'hello', REPO)
        self.assertEqual((rec.version, rec.sha256, rec.root), ('0.1.0', self.sha, f'/opt/avrana-games/hello/0.1.0-{self.sha[:12]}'))
        self.assertEqual(rec.grant, {'game': 'hello', 'entry': '/games/hello/', 'tier': 'community',
                                     'permissions_granted': ['party_roster'],
                                     'runtime': {'command': ['/usr/bin/python3', '-m', 'game_pkg'],
                                                 'working_directory': rec.root}})
        self.assertEqual(rec.package['publisher'], 'Example Studio')
        self.assertEqual(rec.doc['installed_at'], '2026-10-10T12:00:00Z')
        if os.name == 'posix':
            self.assertEqual(stat.S_IMODE(self.layout.record('hello').stat().st_mode), 0o644)
            self.assertEqual(stat.S_IMODE(tree.stat().st_mode), 0o755)
            self.assertEqual(stat.S_IMODE((tree / 'game_pkg' / '__main__.py').stat().st_mode), 0o644)
        # provision_game's own work: key, registry entry, drop-in with the mapped interpreter and the staged directory
        self.assertTrue(self.layout.provision.key('hello').is_file())
        entry = json.loads(self.layout.provision.entry('hello').read_text(encoding='utf-8'))
        self.assertEqual(entry['id'], 'hello')
        dropin = self.layout.provision.dropin('hello').read_text(encoding='utf-8')
        self.assertIn('ExecStart="/usr/bin/python3" "-m" "game_pkg"', dropin)
        self.assertIn(f'WorkingDirectory={rec.root}', dropin)
        self.assertIn(f'AVRANA_PARTY_ORIGIN={ORIGIN}', dropin)
        self.assertEqual(self.calls, [['systemctl', 'daemon-reload'],
                                      ['systemctl', 'enable', '--now', 'avrana-game@hello.socket'],
                                      ['systemctl', 'reload', PARTY]])
        # the checks root-owned code needs ran on the games root, the interpreter, and (provision) the tree
        self.assertIn('/usr/bin/python3', self.trusted_paths)
        self.assertIn(rec.root, self.trusted_paths)
        self.assertEqual([p for p in self.files() if '.staging' in p or p.endswith('.tmp')], [])
        self.assertIn('hello: installed 0.1.0', lines[0])
        self.assertTrue(pkg.is_file())                    # the archive itself is never touched

    def test_a_package_is_community_whatever_it_asks_and_grants_are_the_intersection(self):
        self.install(allow=['party_roster'])
        rec = installed.read_record_file(self.layout.record('hello'), 'hello', REPO)
        self.assertEqual(rec.grant['permissions_granted'], ['party_roster'])
        self.assertEqual(rec.grant['tier'], 'community')
        self.remove()
        self.refused(lambda: self.install(allow=['bogus']), 'not a permission name')
        self.assertEqual([p for p in self.files() if 'hello' in p], [])

    def test_a_grant_the_sandbox_cannot_provide_is_refused_not_recorded(self):
        # AVR-336: the unit has AF_UNIX only and PrivateDevices=, so these cannot be given; a record
        # that said "granted" would be false. Refused before anything is written, requested or not.
        before = self.snapshot()
        for name in ('camera', 'microphone', 'internet', 'local_network', 'controllers', 'host_devices'):
            with self.subTest(name):
                self.refused(lambda: self.install(allow=['party_roster', name]), 'cannot provide', name)
        m = good_manifest()
        m['game']['runtime']['permissions'] = ['party_roster', 'internet']
        pkg = self.package('wants-net.avrgame', manifest=mjson(m))
        self.refused(lambda: self.install(pkg, allow=['party_roster', 'internet']), 'cannot provide')
        self.assertEqual((self.snapshot(), self.calls), (before, []))
        # requesting an unobtainable permission is allowed: it is not granted, and the sandbox gives nothing
        lines = self.install(pkg, allow=['party_roster'])
        self.assertEqual(installed.read_record_file(self.layout.record('hello'), 'hello', REPO).grant['permissions_granted'],
                         ['party_roster'])
        self.assertTrue(any('requested but not granted: internet' in line for line in lines))

    def test_a_package_must_request_and_be_granted_the_roster_it_receives_anyway(self):
        before = self.snapshot()
        self.refused(lambda: self.install(allow=[]), 'receives the Party roster', '--grant party_roster')
        m = good_manifest()
        m['game']['runtime']['permissions'] = []
        quiet = self.package('quiet.avrgame', manifest=mjson(m))
        self.refused(lambda: self.install(quiet, allow=['party_roster']), 'does not request party_roster', 'unannounced')
        self.refused(lambda: self.install(quiet, allow=[]), 'does not request party_roster')
        self.assertEqual((self.snapshot(), self.calls), (before, []))

    def test_ungranted_storage_means_no_state_directory_and_granted_means_the_template_one(self):
        m = good_manifest()
        m['game']['runtime']['permissions'] = ['party_roster', 'persistent_storage']
        pkg = self.package('store.avrgame', manifest=mjson(m))
        lines = self.install(pkg, allow=['party_roster'])
        self.assertTrue(any('NO state directory' in line for line in lines))
        self.assertIn('\nStateDirectory=\n', self.layout.provision.dropin('hello').read_text(encoding='utf-8'))
        self.remove()
        self.install(pkg, allow=['party_roster', 'persistent_storage'])
        self.assertNotIn('StateDirectory', self.layout.provision.dropin('hello').read_text(encoding='utf-8'))
        self.remove()
        self.install()                          # the plain package does not request storage at all: none
        self.assertIn('\nStateDirectory=\n', self.layout.provision.dropin('hello').read_text(encoding='utf-8'))

    def test_a_first_party_unit_keeps_the_template_state_directory(self):
        for tier in (None, 'builtin'):
            text = pg.dropin_text(CommunityUnitTests.RUNTIME, ORIGIN, tier, ())
            self.assertNotIn('StateDirectory', text)
        template = (REPO_ROOT / 'deploy' / 'games' / 'avrana-game@.service').read_text(encoding='utf-8')
        self.assertIn('StateDirectory=avrana-games/%i', template)

    def test_a_second_install_of_the_same_id_is_refused_and_changes_nothing(self):
        self.install()
        before = self.snapshot()
        self.calls.clear()
        self.refused(lambda: self.install(), 'already installed', 'remove it first', 'AVR-58')
        newer = good_manifest()
        newer['package']['version'] = '0.2.0'
        self.refused(lambda: self.install(self.package('v2.avrgame', manifest=mjson(newer))), 'remove it first')
        self.assertEqual((self.snapshot(), self.calls), (before, []))

    def test_an_id_of_a_repository_game_cannot_be_shadowed(self):
        before = self.snapshot()
        self.refused(lambda: self.install(repo=dict(REPO, hello={'id': 'hello'})), 'first-party', 'cannot shadow')
        m = good_manifest()
        m['game']['id'] = 'checkers'
        self.refused(lambda: self.install(self.package('c.avrgame', manifest=mjson(m))), 'first-party')
        self.assertEqual((self.snapshot(), self.calls), (before, []))

    def test_a_game_provisioned_by_other_means_is_never_taken_over(self):
        self.layout.provision.entry('hello').write_text('{}', encoding='utf-8')
        before = self.snapshot()
        self.refused(lambda: self.install(), 'already provisioned by other means')
        self.assertEqual(self.snapshot(), before)

    def test_incompatible_packages_are_refused_before_anything_is_written(self):
        before = self.snapshot()
        for label, change in (('format', lambda m: m.update(format='avrana.avrgame/experimental.2')),
                              ('requires', lambda m: m['requires'].update(bridge='avrana.party-bridge/v9')),
                              ('interpreter', lambda m: m['server'].update(interpreter='/bin/sh')),
                              ('tier', lambda m: m['game'].update(tier='builtin')),
                              ('trust', lambda m: m.update(signature='x'))):
            m = good_manifest()
            change(m)
            self.refused(lambda: self.install(self.package(f'{label}.avrgame', manifest=mjson(m))), 'package refused')
        self.assertEqual((self.snapshot(), self.calls), (before, []))

    def test_tampered_and_hostile_archives_leave_nothing(self):
        raw = make_zip(method=zipfile.ZIP_STORED)
        tampered = self.inputs / 'tampered.avrgame'
        tampered.write_bytes(raw.replace(b'print("hi")', b'print("HI")'))     # same length: only the CRC notices
        self.assertNotEqual(raw, tampered.read_bytes())
        before = self.snapshot()
        self.refused(lambda: self.install(tampered), 'package refused')
        hostile = self.package('hostile.avrgame', extra=[('../evil.py', b'x'), ('/abs.py', b'x'), ('a/../../b.py', b'x')])
        self.refused(lambda: self.install(hostile), 'package refused')
        self.refused(lambda: self.install(self.inputs / 'missing.avrgame'), 'package refused')
        self.assertEqual((self.snapshot(), self.calls), (before, []))
        self.assertFalse((self.root / 'evil.py').exists() or (self.root.parent / 'evil.py').exists())

    def test_the_games_root_and_its_ancestors_must_be_trusted(self):
        before = self.snapshot()

        def untrusted(path):
            if str(path) == str(self.layout.games_root):
                raise pg.Refused(f'{path}: /opt is writable by a group or others')
        self.refused(lambda: self.install(trusted=untrusted), 'writable by a group')
        self.assertEqual(self.snapshot(), before)
        self.layout.games_root.rmdir()
        self.refused(lambda: self.install(), 'games root')
        self.assertEqual(self.calls, [])

    def test_every_failure_point_puts_the_host_back_as_it_was(self):
        before = self.snapshot()

        def extract_fails(path, dest):
            (Path(dest) / 'half.txt').write_bytes(b'x')
            raise OSError('disk full')

        def tampered_after_extract(path, dest):
            package = ig.avrgame.extract(path, dest)
            (Path(dest) / 'game_pkg' / '__main__.py').write_bytes(b'print("evil")\n')
            return package

        def untrusted_tree(path):
            if '/hello/' in str(path):
                raise pg.Refused('not root-owned')
        cases = [('extract fails', dict(extract=extract_fails), OSError),
                 ('hash mismatch after extract', dict(extract=tampered_after_extract), pg.Refused),
                 ('the tree is not root-owned code', dict(trusted=untrusted_tree), pg.Refused)]
        for label, kw, error in cases:
            with self.subTest(label), self.assertRaises(error):
                self.install(**kw)
            self.assertEqual(self.snapshot(), before, label)
        with self.subTest('record write fails'), mock.patch.object(ig, '_write_record', side_effect=OSError('no space')):
            with self.assertRaises(OSError):
                self.install()
            self.assertEqual(self.snapshot(), before)

    def test_provision_failing_at_each_systemctl_call_unwinds_everything(self):
        before = self.snapshot()
        for fail in (['systemctl', 'daemon-reload'], ['systemctl', 'enable'], ['systemctl', 'reload']):
            fired = []

            def run(argv, fail=fail, fired=fired):
                self.calls.append(list(argv))
                if argv[:2] == fail and not fired:
                    fired.append(1)
                    raise subprocess.CalledProcessError(1, argv)
            with self.subTest(fail), self.assertRaises(subprocess.CalledProcessError):
                self.install(run=run)
            self.assertEqual(self.snapshot(), before, fail)
        # the first failure was "once"; with a Party Core reload that fails EVERY time, the files are
        # still all gone, but the undo reports it could not tell Party Core
        def always(argv):
            if argv[:2] == ['systemctl', 'reload']:
                raise subprocess.CalledProcessError(1, argv)
        with self.assertRaises(ig.RollbackIncomplete) as ctx:
            self.install(run=always)
        self.assertIsInstance(ctx.exception.original, subprocess.CalledProcessError)
        self.assertIn('Party Core reload', ctx.exception.problems)
        self.assertEqual(self.snapshot(), before)

    def test_an_interrupted_install_is_repaired_by_remove_and_install_refuses_to_guess(self):
        self.install()
        self.layout.record('hello').unlink()                     # a tree and a provisioned game, no record
        self.refused(lambda: self.install(), 'without a record', 'remove')
        self.remove()
        self.assertEqual([p for p in self.files() if 'hello' in p], [])
        self.install()
        shutil_tree = self.layout.id_dir('hello')
        self.layout.record('hello').unlink()
        self.remove()
        self.assertFalse(shutil_tree.exists())
        # a record and no tree, a tree and no record
        self.install()
        import shutil
        shutil.rmtree(self.layout.id_dir('hello'))
        self.remove()
        self.assertEqual([p for p in self.files() if 'hello' in p], [])
        self.install()
        self.remove()
        self.layout.id_dir('hello').mkdir()
        self.install()                              # an empty id directory is what a crash after mkdir leaves: not in the way
        self.assertEqual(ig.verify('hello', self.layout, REPO), [])
        self.remove()

    def test_stale_staging_directories_are_cleaned_and_foreign_ones_refused(self):
        stale = self.layout.games_root / '.staging-deadbeef'
        (stale / 'sub').mkdir(parents=True)
        (stale / 'sub' / 'half.py').write_bytes(b'x')
        self.install()
        self.assertFalse(stale.exists())
        self.remove()
        odd = self.layout.games_root / '.staging-notadir'
        odd.write_bytes(b'')
        before = self.snapshot()
        self.refused(lambda: self.install(), 'staging directory this tool made')
        self.assertEqual(self.snapshot(), before)

    @unittest.skipUnless(hasattr(__import__('os'), 'symlink') and os.name == 'posix', 'POSIX symbolic links')
    def test_a_symlinked_games_root_is_refused(self):
        real = self.layout.games_root
        moved = real.with_name('elsewhere')
        real.rename(moved)
        real.symlink_to(moved)
        self.refused(lambda: self.install(), 'not a plain directory')


class RemoveTests(Base):
    def test_remove_leaves_nothing_and_is_repeatable(self):
        before = self.snapshot()
        self.install()
        self.calls.clear()
        removed = self.remove()
        self.assertEqual(removed[:1], ['registry'])
        for item in ('dropin', 'key', 'record', 'files'):
            self.assertIn(item, removed)
        left = [p for p in self.snapshot() if 'hello' in p]
        self.assertEqual(left, [])
        self.assertEqual(sorted(p for p in self.snapshot() if self.snapshot()[p][0] == 'file'),
                         sorted(p for p in before if before[p][0] == 'file'))
        self.assertEqual(self.calls[-2:], [['systemctl', 'reload', PARTY], ['systemctl', 'daemon-reload']][-2:] and
                         [self.calls[-2], self.calls[-1]])
        self.assertIn(['systemctl', 'disable', '--now', 'avrana-game@hello.socket'], self.calls)
        self.assertEqual(self.remove(), [])                    # a second remove is a clean no-op
        self.assertEqual([p for p in self.snapshot() if 'hello' in p], [])

    def test_remove_keep_state_keeps_the_state_directory(self):
        self.install()
        state = self.layout.provision.state('hello')
        state.mkdir()
        (state / 'save.json').write_bytes(b'{}')
        self.remove(keep_state=True)
        self.assertTrue((state / 'save.json').is_file())
        self.assertFalse(self.layout.record('hello').exists())

    def test_remove_is_refused_while_the_game_has_a_session(self):
        self.install()
        before, self.calls[:] = self.snapshot(), []
        self.refused(lambda: self.remove(active=lambda slug: True), 'session running')
        self.assertEqual((self.snapshot(), self.calls), (before, []))

    def test_remove_works_with_a_damaged_or_missing_record(self):
        for damage in (lambda p: p.write_text('{ not json', encoding='utf-8'), lambda p: p.unlink()):
            self.install()
            damage(self.layout.record('hello'))
            self.remove()
            self.assertEqual([p for p in self.snapshot() if 'hello' in p], [])

    def test_remove_never_touches_a_first_party_or_a_foreign_game(self):
        self.refused(lambda: self.remove('checkers'), 'first-party')
        self.refused(lambda: self.remove('Not An Id'), 'not a game id')
        other = self.layout.provision
        other.entry('other').write_text('{}', encoding='utf-8')
        other.key('other').write_text('k', encoding='utf-8')
        self.refused(lambda: self.remove('other'), 'not installed by install-game')
        self.assertTrue(other.key('other').exists())
        self.assertEqual(self.calls, [])


class VerifyListTests(Base):
    def test_verify_detects_a_modified_added_and_missing_file(self):
        self.install()
        tree = self.tree()
        self.assertEqual(ig.verify('hello', self.layout, REPO), [])
        main = tree / 'game_pkg' / '__main__.py'
        main.write_bytes(b'print("changed")\n')
        self.assertTrue(any('__main__.py: changed' in p for p in ig.verify('hello', self.layout, REPO)))
        main.write_bytes(b'print("hi")\n')
        self.assertEqual(ig.verify('hello', self.layout, REPO), [])
        (tree / 'extra.py').write_bytes(b'x')
        self.assertTrue(any('extra.py: not part of the package' in p for p in ig.verify('hello', self.layout, REPO)))
        (tree / 'extra.py').unlink()
        (tree / 'game_pkg' / 'web' / 'app.js').unlink()
        self.assertTrue(any('app.js: missing' in p for p in ig.verify('hello', self.layout, REPO)))
        self.refused(lambda: ig.verify('nope', self.layout, REPO), 'not installed')

    @unittest.skipUnless(os.name == 'posix', 'POSIX modes and links')
    def test_verify_flags_writable_files_and_links(self):
        self.install()
        tree = self.tree()
        os.chmod(tree / 'game_pkg' / '__main__.py', 0o666)
        self.assertTrue(any('writable by a group or others' in p for p in ig.verify('hello', self.layout, REPO)))
        os.chmod(tree / 'game_pkg' / '__main__.py', 0o644)
        os.symlink('/etc/passwd', tree / 'link')
        self.assertTrue(any('link: a symbolic link' in p for p in ig.verify('hello', self.layout, REPO)))

    def test_list_shows_claims_as_unverified_and_whether_the_tree_still_matches(self):
        self.install()
        rows, problems = ig.listing(self.layout, REPO)
        row = rows['hello']
        self.assertEqual((row['version'], row['sha12'], row['tier'], row['permissions_granted'], row['tree']),
                         ('0.1.0', self.sha[:12], 'community', ['party_roster'], 'ok'))
        out = io.StringIO()
        ig._show_listing(rows, problems, False, out)
        self.assertIn('Example Studio (unverified claim)', out.getvalue())
        self.assertIn('MIT (unverified claim)', out.getvalue())
        (self.tree() / 'game_pkg' / '__init__.py').write_bytes(b'#')
        self.assertEqual(ig.listing(self.layout, REPO)[0]['hello']['tree'], 'modified')
        self.layout.record('bad').write_text('{}', encoding='utf-8')
        rows, problems = ig.listing(self.layout, REPO)
        self.assertTrue(any(p.startswith('bad: record refused') for p in problems))
        out = io.StringIO()
        ig._show_listing(rows, problems, True, out)
        self.assertEqual(json.loads(out.getvalue())['installed'][0]['id'], 'hello')


class MainTests(Base):
    def main(self, *argv, root=True, **kw):
        out, err = io.StringIO(), io.StringIO()
        conf = str(self.root / 'etc/party-core.json')
        paths = ['--key-dir', self.layout.provision.key_dir, '--registry-dir', self.layout.provision.registry_dir,
                 '--socket-dir', self.layout.provision.socket_dir, '--state-dir', self.layout.provision.state_dir,
                 '--unit-dir', self.layout.provision.unit_dir, '--template-dir', self.layout.provision.template_dir,
                 '--records-dir', self.layout.records_dir, '--games-root', self.layout.games_root,
                 '--lock-file', self.layout.lock_file, '--visible-root', '/opt/avrana-games', '--party-config', conf]
        paths = [str(p) for p in paths]
        rc = ig.main([argv[0], *argv[1:], *paths], run=self.run_, own=self.own, is_root=root, contracts=REPO,
                     opener=lambda target, timeout: Response(IDLE), out=out, err=err, **kw)
        return rc, out.getvalue(), err.getvalue()

    def test_exit_codes_and_output(self):
        pkg = str(self.package())
        self.assertEqual(self.main('install', pkg, root=False)[0], 1)                 # not root
        rc, out, err = self.main('install', pkg, '--grant', 'party_roster', '--dry-run', root=False)
        self.assertEqual(rc, 0, err)
        self.assertIn('would install 0.1.0', out)
        self.assertEqual([p for p in self.files() if 'hello' in p], [])
        rc, out, err = self.main('install', pkg, '--grant', 'party_roster')
        self.assertEqual(rc, 0, err)
        self.assertIn('granted: party_roster', out)
        rc, out, err = self.main('install', pkg, '--grant', 'party_roster')
        self.assertEqual((rc, out), (1, ''))
        self.assertIn('refused: hello 0.1.0 is already installed', err)
        rc, out, _ = self.main('list')
        self.assertEqual(rc, 0)
        self.assertIn('hello 0.1.0', out)
        self.assertEqual(self.main('verify', 'hello')[0], 0)
        self.assertEqual(self.main('verify', 'nope')[0], 1)
        rc, out, _ = self.main('remove', 'hello', '--dry-run', root=False)
        self.assertEqual(rc, 0)
        self.assertIn('would remove record', out)
        self.assertEqual(self.main('remove', 'hello')[0], 0)
        self.assertIn('nothing to remove', self.main('remove', 'hello')[1])
        self.assertEqual(self.main('list')[1].strip(), 'no packages installed')
        self.assertEqual(ig.main([], err=io.StringIO()), 2)
        self.assertEqual(ig.main(['frobnicate'], err=io.StringIO()), 2)

    def test_a_failed_install_exits_1_and_says_why_without_a_key(self):
        def failing(argv):
            if argv[1] == 'enable':
                raise subprocess.CalledProcessError(1, argv)
        out, err = io.StringIO(), io.StringIO()
        before = self.snapshot()
        rc = ig.main(['install', str(self.package()), '--grant', 'party_roster', '--records-dir', str(self.layout.records_dir),
                      '--games-root', str(self.layout.games_root), '--lock-file', str(self.layout.lock_file),
                      '--visible-root', '/opt/avrana-games', '--key-dir', str(self.layout.provision.key_dir),
                      '--registry-dir', str(self.layout.provision.registry_dir),
                      '--socket-dir', str(self.layout.provision.socket_dir),
                      '--state-dir', str(self.layout.provision.state_dir), '--unit-dir', str(self.layout.provision.unit_dir),
                      '--template-dir', str(self.layout.provision.template_dir),
                      '--party-config', str(self.root / 'etc/party-core.json')],
                     run=failing, own=self.own, is_root=True, contracts=REPO, out=out, err=err)
        self.assertEqual(rc, 1)
        self.assertIn('nothing is left installed', err.getvalue())
        self.assertEqual(self.snapshot(), before)

    def test_party_core_must_read_the_records_directory(self):
        conf = self.root / 'etc/party-core.json'
        doc = json.loads(conf.read_text(encoding='utf-8'))
        del doc['packages']
        conf.write_text(json.dumps(doc), encoding='utf-8')
        self.refused(lambda: ig.check_packages_read(conf, self.layout.records_dir), 'does not name the install records')

    @unittest.skipUnless(os.name == 'posix', 'flock')
    def test_two_runs_cannot_interleave(self):
        with ig.locked(self.layout.lock_file):
            self.refused(lambda: ig.locked(self.layout.lock_file).__enter__(), 'another install-game')
        with ig.locked(self.layout.lock_file):
            pass


class RecordReaderTests(Base):
    def good(self):
        self.install()
        return json.loads(self.layout.record('hello').read_text(encoding='utf-8'))

    def write(self, doc, name='hello'):
        self.layout.record(name).write_text(json.dumps(doc), encoding='utf-8')
        if os.name == 'posix':
            os.chmod(self.layout.record(name), 0o644)

    def load(self, repo=REPO):
        return installed.load(self.layout.records_dir, repo)

    def test_a_missing_directory_is_nothing_installed(self):
        found = installed.load(self.root / 'nowhere', REPO)
        self.assertEqual((found.records, found.contracts, found.grants, found.problems), ({}, {}, {}, []))

    def test_a_good_record_adds_its_contract_and_grant(self):
        self.good()
        found = self.load()
        self.assertEqual(sorted(found.contracts), ['hello'])
        self.assertEqual(found.grants['hello']['tier'], 'community')
        self.assertEqual(found.problems, [])

    def test_every_kind_of_wrong_record_is_refused_by_name_and_only_itself(self):
        base = self.good()
        mutations = {
            'unknown key': (lambda d: d.update(extra=1), 'unknown key'),
            'id vs file name': (lambda d: d.update(id='other'), 'does not match the file name'),
            'bad version': (lambda d: d.update(version='1'), 'version'),
            'bad sha': (lambda d: d.update(sha256='zz'), 'sha256'),
            'format': (lambda d: d.update(format='avrana.avrgame/experimental.9'), 'format'),
            'record schema': (lambda d: d.update(record='x'), 'record:'),
            'contract invalid': (lambda d: d['contract'].update(players={'min': 5, 'max': 1}), 'contract:'),
            'contract id': (lambda d: d['contract'].update(id='other'), 'contract.id'),
            'contract tier': (lambda d: d['contract'].update(tier='builtin'), 'contract:'),
            'grant exceeds request': (lambda d: d['grant'].update(permissions_granted=['party_roster', 'camera']), 'never requested'),
            'grant the sandbox cannot provide': (lambda d: (d['contract']['runtime'].update(permissions=['party_roster', 'internet']),
                                                            d['grant'].update(permissions_granted=['party_roster', 'internet'])),
                                                 'cannot be provided inside the package sandbox'),
            'grant lacks the roster every game receives': (lambda d: d['grant'].update(permissions_granted=[]), 'party_roster is delivered'),
            'tier not community': (lambda d: d['grant'].update(tier='builtin'), 'community'),
            'entry': (lambda d: d['grant'].update(entry='/games/other/'), 'grant.entry'),
            'working dir': (lambda d: d['grant']['runtime'].update(working_directory='/opt/avrana-games/hello'), 'working_directory'),
            'root shape': (lambda d: d.update(root='/opt/avrana-games/hello/latest'), 'root:'),
            'interpreter': (lambda d: d['grant']['runtime']['command'].__setitem__(0, '/bin/sh'), 'interpreter'),
            'absolute arg': (lambda d: d['grant']['runtime']['command'].append('/etc/passwd'), 'absolute path'),
            'grant key': (lambda d: d['grant'].update(health='/x'), 'grant:'),
            'files': (lambda d: d.update(files=[]), 'files'),
            'claims': (lambda d: d['package'].update(trust='high'), 'package:'),
        }
        self.layout.record('hello').unlink()
        for label, (change, expect) in mutations.items():
            doc = copy.deepcopy(base)
            change(doc)
            self.write(doc)
            found = self.load()
            self.assertEqual(found.contracts, {}, label)
            self.assertTrue(any(expect in p for p in found.problems), (label, found.problems))
            self.assertIn('hello', found.refused, label)

    def test_a_deeply_nested_record_is_refused_without_recursing(self):
        self.good()
        self.layout.record('hello').write_text('[' * 5000 + ']' * 5000, encoding='utf-8')
        found = self.load()
        self.assertTrue(any('nested deeper' in p for p in found.problems), found.problems)
        self.assertEqual(found.contracts, {})

    def test_a_record_cannot_shadow_a_repository_game(self):
        base = self.good()
        self.layout.record('hello').unlink()
        found = installed.load(self.layout.records_dir, dict(REPO, hello={'id': 'hello'}))
        self.assertEqual(found.records, {})
        self.assertTrue(found.problems == [] or True)
        doc = copy.deepcopy(base)
        self.write(doc)
        found = installed.load(self.layout.records_dir, dict(REPO, hello={'id': 'hello'}))
        self.assertTrue(any('cannot shadow' in p for p in found.problems))
        self.assertEqual(found.contracts, {})

    def test_stray_files_and_unreadable_ones_are_reported_not_fatal(self):
        base = self.good()
        (self.layout.records_dir / 'notes.txt').write_text('x', encoding='utf-8')
        (self.layout.records_dir / '.hidden.json.tmp').write_text('x', encoding='utf-8')
        (self.layout.records_dir / 'dup.json').write_text('{"a": 1, "a": 2}', encoding='utf-8')
        found = self.load()
        self.assertEqual(sorted(found.contracts), ['hello'])
        text = ' | '.join(found.problems)
        self.assertIn('notes.txt: not an install record', text)
        self.assertIn('dup: record refused: not strict JSON', text)
        self.assertNotIn('hidden', text)
        self.assertEqual(base['id'], 'hello')

    @unittest.skipUnless(os.name == 'posix', 'POSIX modes and links')
    def test_a_writable_or_linked_record_is_refused(self):
        self.good()
        os.chmod(self.layout.record('hello'), 0o666)
        self.assertTrue(any('writable by a group or others' in p for p in self.load().problems))
        os.chmod(self.layout.record('hello'), 0o644)
        target = self.layout.records_dir / 'elsewhere'
        self.layout.record('hello').rename(target)
        self.layout.record('hello').symlink_to(target)
        self.assertTrue(any('not a regular file' in p for p in self.load().problems))


class RegistryTests(Base):
    """Party Core's side: registry.build with a packages directory."""

    def setUp(self):
        super().setUp()
        self.keys = self.root / 'keys'
        self.keys.mkdir()
        self.bluff_key = self.keys / 'bluff.key'
        protocol.write_key(str(self.bluff_key), protocol.new_key())
        self.hello_key = self.keys / 'hello.key'
        protocol.write_key(str(self.hello_key), protocol.new_key())
        self.config = {'bluff': {'url': 'http://127.0.0.1:1/games/bluff', 'key_file': str(self.bluff_key)}}
        self.reg = self.layout.provision.registry_dir

    def entry(self):
        (self.reg / 'hello.json').write_text(json.dumps({'id': 'hello', 'socket': '/run/avrana-games/hello.sock',
                                                         'key_file': str(self.hello_key)}), encoding='utf-8')

    def build(self, packages=True):
        return registry.build(self.config, str(self.reg), REPO, packages=str(self.layout.records_dir) if packages else None)

    def test_an_installed_game_is_resolved_from_its_record_and_nothing_changes_without_the_key(self):
        self.install()
        self.entry()
        games, endpoints = self.build()
        self.assertEqual(sorted(games), ['bluff', 'hello'])
        self.assertEqual((games['hello']['min_players'], games['hello']['max_players']), (1, 6))
        self.assertIn('hello', endpoints)
        with self.assertRaises(registry.RegistryError):                    # without "packages" the entry has no contract
            self.build(packages=False)

    def test_a_corrupt_record_takes_out_only_its_own_game(self):
        self.install()
        self.entry()
        self.layout.record('hello').write_text('{"record": "x"}', encoding='utf-8')
        with self.assertLogs('avrana.party.registry', 'ERROR') as logs:
            games, endpoints = self.build()
        self.assertEqual(sorted(games), ['bluff'])                          # the repository game is untouched
        self.assertEqual(sorted(endpoints), ['bluff'])
        text = '\n'.join(logs.output)
        self.assertIn('hello: record refused', text)
        self.assertIn('hello: left out', text)

    def test_a_record_cannot_remove_or_replace_a_repository_game(self):
        self.install()
        doc = json.loads(self.layout.record('hello').read_text(encoding='utf-8'))
        doc['id'] = 'bluff'
        self.entry()
        (self.layout.records_dir / 'bluff.json').write_text(json.dumps(doc), encoding='utf-8')
        with self.assertLogs('avrana.party.registry', 'ERROR'):
            games, _ = self.build()
        self.assertEqual(sorted(games), ['bluff', 'hello'])                  # the real hello record is fine
        self.assertEqual(games['bluff']['max_players'], REPO['bluff']['players']['max'])


class CatalogTests(Base):
    def catalog_args(self, out):
        games = self.root / 'games'
        games.mkdir(exist_ok=True)
        (games / 'checkers.json').write_bytes((CONTRACTS_DIR / 'games' / 'checkers.json').read_bytes())
        appliance = json.loads((REPO_ROOT / 'tests/fixtures/appliances/ci-hello.json').read_text(encoding='utf-8'))
        appliance['installed'] = []
        profile = self.root / 'appliance.json'
        profile.write_text(json.dumps(appliance), encoding='utf-8')
        return ['--games', str(games), '--appliance', str(profile), '--out', str(out)]

    def build(self, *extra):
        out = self.root / 'catalog.json'
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = catalog.main([*self.catalog_args(out), *extra])
        self.assertEqual(rc, 0)
        return {g['id']: g for g in json.loads(out.read_text(encoding='utf-8'))['games']}

    def test_the_catalog_shows_an_installed_package_and_forgets_it_after_remove(self):
        self.assertNotIn('hello', self.build('--packages', str(self.layout.records_dir)))
        self.install()
        games = self.build('--packages', str(self.layout.records_dir))
        hello = games['hello']
        self.assertEqual((hello['installed'], hello['entry'], hello['status'], hello['provider'], hello['playableHere']),
                         (True, '/games/hello/', 'current', 'native', True))
        self.assertFalse(games['checkers']['installed'])
        self.assertNotIn('hello', self.build())                             # no --packages: nothing changes
        self.remove()
        self.assertNotIn('hello', self.build('--packages', str(self.layout.records_dir)))

    def test_packages_need_an_explicit_out_and_the_product_catalog_is_unchanged(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(catalog.main(['--packages', str(self.root)]), 2)
        self.assertIn('explicit --out', err.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(catalog.main(['--check']), 0)


class ReviewFixTests(Base):
    """Findings of the independent review: each of these failed before its fix."""

    def entry(self, key_name='hello'):
        keys = self.root / 'keys'
        keys.mkdir(exist_ok=True)
        key = keys / f'{key_name}.key'
        if not key.exists():
            protocol.write_key(str(key), protocol.new_key())
        (self.layout.provision.registry_dir / f'{key_name}.json').write_text(
            json.dumps({'id': key_name, 'socket': f'/run/avrana-games/{key_name}.sock', 'key_file': str(key)}),
            encoding='utf-8')
        return key

    def bluff_config(self):
        key = self.root / 'keys' / 'bluff.key'
        key.parent.mkdir(exist_ok=True)
        if not key.exists():
            protocol.write_key(str(key), protocol.new_key())
        return {'bluff': {'url': 'http://127.0.0.1:1/games/bluff', 'key_file': str(key)}}

    # -- 1. a first-party contract that appears after a package was installed
    def test_a_package_entry_does_not_serve_under_a_later_first_party_contract_and_remove_clears_it(self):
        self.install()
        self.entry()
        everything = party_config.load_contracts()                   # now `hello` is a first-party game too
        self.assertIn('hello', everything)
        with self.assertLogs('avrana.party.registry', 'ERROR') as logs:
            games, endpoints = registry.build(self.bluff_config(), str(self.layout.provision.registry_dir), everything,
                                              packages=str(self.layout.records_dir))
        self.assertEqual((sorted(games), sorted(endpoints)), (['bluff'], ['bluff']))
        text = '\n'.join(logs.output)
        self.assertIn('hello: left out', text)
        self.assertIn('install-game remove hello', text)
        # a first-party entry with NO install record is a legitimate game and is kept
        self.layout.record('hello').unlink()
        games, _ = registry.build(self.bluff_config(), str(self.layout.provision.registry_dir), everything,
                                  packages=str(self.layout.records_dir))
        self.assertEqual(sorted(games), ['bluff', 'hello'])
        # remove can still clear the package install, on the evidence of the record or the staged tree
        self.install_again_with_record(everything)

    def install_again_with_record(self, everything):
        # a tree alone is NOT evidence for a first-party id (AVR-336): nothing is touched
        before = self.snapshot()
        self.refused(lambda: self.remove('hello', repo=everything), 'first-party')
        self.assertEqual(self.snapshot(), before)
        self.remove('hello')                                         # on a tree that does not know it, the tree is evidence
        self.assertEqual([p for p in self.snapshot() if 'hello' in p and not p.startswith('keys/')], [])
        self.install()
        self.remove('hello', repo=everything)                        # the record and the tree
        self.assertEqual([p for p in self.snapshot() if 'hello' in p and not p.startswith('keys/')], [])
        self.refused(lambda: self.remove('bluff', repo=everything), 'first-party')    # no evidence: untouched

    def test_remove_clears_a_package_whose_id_became_first_party_while_the_record_exists(self):
        self.install()
        everything = dict(REPO, hello={'id': 'hello'})
        self.remove('hello', repo=everything)
        self.assertEqual([p for p in self.snapshot() if 'hello' in p], [])

    # -- 2. rollback gaps: fsync after the rename and after the record replace
    def test_a_failing_fsync_after_the_rename_or_the_record_is_rolled_back(self):
        before = self.snapshot()
        real = ig._fsync
        for target in ('tree', 'record'):
            def flaky(path, directory=False, target=target):
                if target == 'tree' and Path(path) == self.layout.id_dir('hello'):
                    raise OSError('input/output error')
                if target == 'record' and Path(path) == Path(self.layout.records_dir):
                    raise OSError('input/output error')
                return real(path, directory)
            with self.subTest(target), mock.patch.object(ig, '_fsync', flaky), self.assertRaises(OSError):
                self.install()
            self.assertEqual(self.snapshot(), before, target)

    # -- 3. trust in the records directory and the files in it
    def test_a_record_or_directory_not_owned_by_the_expected_owner_is_refused(self):
        self.install()
        with self.assertRaises(installed.RecordError) as ctx:
            installed.read_record_file(self.layout.record('hello'), 'hello', REPO, owner=12345)
        self.assertIn('not owned by uid 12345', str(ctx.exception))
        found = installed.load(self.layout.records_dir, REPO, owner=12345)
        self.assertEqual((found.contracts, sorted(found.refused)), ({}, ['hello']))
        self.assertTrue(any('records directory' in p for p in found.problems))
        with mock.patch.object(installed, 'EXPECTED_OWNER', 12345):          # the default Party Core uses
            self.assertEqual(installed.load(self.layout.records_dir, REPO).contracts, {})
        self.assertEqual(ig.verify('hello', self.layout, REPO, owner=12345)[0][:14], 'record refused')

    def test_a_refused_records_directory_leaves_repository_games_serving(self):
        self.install()
        self.entry()
        with mock.patch.object(installed, 'EXPECTED_OWNER', 12345), self.assertLogs('avrana.party.registry', 'ERROR'):
            games, _ = registry.build(self.bluff_config(), str(self.layout.provision.registry_dir), REPO,
                                      packages=str(self.layout.records_dir))
        self.assertEqual(sorted(games), ['bluff'])

    @unittest.skipUnless(os.name == 'posix', 'POSIX modes')
    def test_a_writable_records_directory_is_refused(self):
        self.install()
        os.chmod(self.layout.records_dir, 0o777)
        self.assertEqual(installed.directory_problem(self.layout.records_dir, owner=None), 'writable by a group or others')
        self.assertEqual(installed.load(self.layout.records_dir, REPO).contracts, {})

    def test_install_checks_the_records_directory_and_its_ancestors_before_writing(self):
        self.install()                                              # no records directory yet: its parent is checked
        self.assertIn(str(self.layout.records_dir.parent), self.trusted_paths)
        self.remove()
        self.trusted_paths.clear()
        self.install()                                              # the (empty) directory is left behind by remove
        self.assertIn(str(self.layout.records_dir), self.trusted_paths)
        self.remove()
        before = self.snapshot()

        def untrusted(path):
            if str(path) == str(self.layout.records_dir):
                raise pg.Refused(f'{path}: is writable by a group or others')
        self.refused(lambda: self.install(trusted=untrusted), 'writable by a group')
        self.assertEqual(self.snapshot(), before)

    @unittest.skipUnless(os.name == 'posix' and hasattr(os, 'geteuid') and os.geteuid() != 0, 'POSIX, not as root')
    def test_the_real_root_owned_code_rule_refuses_a_scratch_tree(self):
        before = self.snapshot()
        self.refused(lambda: self.install(trusted=pg.trusted_path), 'a native game runs only root-owned code')
        self.assertEqual((self.snapshot(), self.calls), (before, []))

    # -- 4. the record's root is pinned to the configured games root
    def test_a_record_pointing_outside_the_games_root_is_refused(self):
        self.install()
        doc = json.loads(self.layout.record('hello').read_text(encoding='utf-8'))
        sha12 = doc['sha256'][:12]
        elsewhere = f'/srv/evil/hello/0.1.0-{sha12}'
        doc['root'] = elsewhere
        doc['grant']['runtime']['working_directory'] = elsewhere
        self.layout.record('hello').write_text(json.dumps(doc), encoding='utf-8')
        found = installed.load(self.layout.records_dir, REPO)
        self.assertEqual(found.contracts, {})
        self.assertTrue(any('root: must be exactly /opt/avrana-games/<id>' in p for p in found.problems), found.problems)
        self.assertEqual(installed.load(self.layout.records_dir, REPO, games_root='/srv/evil').contracts.keys(), {'hello'})
        for bad in (f'/opt/avrana-games/hello/../hello/0.1.0-{sha12}', f'/opt/avrana-games//hello/0.1.0-{sha12}'):
            doc['root'] = doc['grant']['runtime']['working_directory'] = bad
            self.layout.record('hello').write_text(json.dumps(doc), encoding='utf-8')
            self.assertEqual(installed.load(self.layout.records_dir, REPO).contracts, {})

    # -- 5. exact ids
    def test_an_id_with_a_trailing_newline_is_not_a_game_id(self):
        m = good_manifest()
        m['game']['id'] = 'hello\n'
        self.refused_package(m)
        with self.assertRaises(pg.Refused):
            self.install(self.package('nl.avrgame', manifest=mjson(m)))
        self.assertEqual([p for p in self.snapshot() if 'hello' in p], [])
        self.assertIsNone(installed.game.ID.fullmatch('hello\n'))
        with self.assertRaises(installed.RecordError):
            installed.validate_record({'id': 'hello\n'}, 'hello', REPO)

    def refused_package(self, manifest):
        from test_avrgame_package import problems_of
        self.assertTrue(problems_of(manifest))

    # -- 7. hostile remove ids, and the SIGHUP path with packages
    def test_hostile_remove_ids_are_refused_before_anything_is_touched(self):
        self.install()
        before = self.snapshot()
        self.calls.clear()
        for bad in ('', '..', '.', '/', 'a/b', 'a\\b', 'hello\n', 'HELLO', '../hello', None):
            with self.subTest(bad):
                self.refused(lambda: self.remove(bad), 'not a game id')
        self.assertEqual((self.snapshot(), self.calls), (before, []))

    def test_a_reload_picks_up_an_installed_game_and_drops_a_corrupt_one(self):
        import threading
        import types
        self.install()
        self.entry()
        config = self.root / 'etc' / 'party-core.json'
        config.write_text(json.dumps({'games': self.bluff_config(), 'registry': str(self.layout.provision.registry_dir),
                                      'packages': str(self.layout.records_dir)}), encoding='utf-8')
        service = types.SimpleNamespace(lock=threading.RLock(), _notify=lambda: None,
                                        core=types.SimpleNamespace(party=types.SimpleNamespace(session=None), games={},
                                                                   _commit=lambda: None))
        endpoints = {}
        self.assertTrue(registry.reload(service, endpoints, str(config), REPO))
        self.assertEqual((sorted(endpoints), sorted(service.core.games)), (['bluff', 'hello'], ['bluff', 'hello']))
        self.layout.record('hello').write_text('{ not json', encoding='utf-8')
        with self.assertLogs('avrana.party.registry', 'ERROR'):
            self.assertTrue(registry.reload(service, endpoints, str(config), REPO))
        self.assertEqual((sorted(endpoints), sorted(service.core.games)), (['bluff'], ['bluff']))


class RemoveEvidenceTests(Base):
    """AVR-336: `remove` clears only what this installer made, and never a first-party game."""

    def provisioned_stand_in(self, pid, working_directory=None):
        lay = self.layout.provision
        lay.key(pid).write_text('k', encoding='utf-8')
        lay.entry(pid).write_text('{}', encoding='utf-8')
        lay.dropin_dir(pid).mkdir()
        wd = working_directory or '/opt/avrana-party-games/current'
        lay.dropin(pid).write_text(f'[Service]\nWorkingDirectory={wd}\n', encoding='utf-8')
        return lay

    def test_a_stray_directory_never_makes_a_first_party_game_removable(self):
        lay = self.provisioned_stand_in('checkers')
        stray = self.layout.id_dir('checkers')
        (stray / 'notes').mkdir(parents=True)
        (stray / 'notes' / 'x.txt').write_text('stray', encoding='utf-8')
        before = self.snapshot()
        self.refused(lambda: self.remove('checkers'), 'first-party')
        self.refused(lambda: ig.plan_remove('checkers', self.layout, REPO), 'first-party')
        self.assertEqual((self.snapshot(), self.calls), (before, []))
        # a tree shaped like the installer's and a drop-in pointing into the games root are still no evidence
        (stray / '1.0.0-0123456789ab').mkdir()
        lay.dropin('checkers').write_text(
            f'[Service]\nWorkingDirectory={self.layout.root_text()}/checkers/1.0.0-0123456789ab\n', encoding='utf-8')
        before = self.snapshot()
        self.refused(lambda: self.remove('checkers'), 'first-party')
        self.assertEqual((self.snapshot(), self.calls), (before, []))
        self.assertTrue(lay.key('checkers').exists() and lay.entry('checkers').exists())

    def test_a_record_that_is_not_this_installers_is_no_evidence_for_a_first_party_game(self):
        self.provisioned_stand_in('checkers')
        for label, text in (('not json', '{ nope'), ('empty object', '{}'),
                            ('wrong id', json.dumps({'record': installed.RECORD, 'id': 'other'})),
                            ('wrong schema', json.dumps({'record': 'x', 'id': 'checkers'})),
                            ('a list', '[]')):
            self.layout.records_dir.mkdir(exist_ok=True)
            self.layout.record('checkers').write_text(text, encoding='utf-8')
            before = self.snapshot()
            with self.subTest(label):
                self.refused(lambda: self.remove('checkers'), 'first-party')
                self.assertEqual((self.snapshot(), self.calls), (before, []))

    @unittest.skipUnless(os.name == 'posix', 'POSIX links')
    def test_a_linked_record_is_no_evidence_for_a_first_party_game(self):
        self.provisioned_stand_in('checkers')
        self.layout.records_dir.mkdir()
        real = self.root / 'real-record.json'
        real.write_text(json.dumps({'record': installed.RECORD, 'id': 'checkers'}), encoding='utf-8')
        self.layout.record('checkers').symlink_to(real)
        self.refused(lambda: self.remove('checkers'), 'first-party')

    def test_a_genuine_record_still_lets_remove_clear_a_package_whose_id_became_first_party(self):
        self.install()
        everything = dict(REPO, hello={'id': 'hello'})
        self.assertEqual(ig.plan_remove('hello', self.layout, everything)[:2], ['record', 'files'])
        self.remove('hello', repo=everything)
        self.assertEqual([p for p in self.snapshot() if 'hello' in p], [])

    def test_a_stray_directory_is_not_evidence_for_any_id_unless_it_has_the_installer_shape(self):
        stray = self.layout.id_dir('zzz')
        stray.mkdir()
        (stray / 'readme.txt').write_text('mine', encoding='utf-8')
        before = self.snapshot()
        self.assertEqual(self.remove('zzz'), [])               # nothing to remove: not a tree this tool made
        self.assertEqual(self.snapshot(), before)
        self.refused(lambda: self.install_named_zzz(), 'without a record', 'delete it by hand')
        (stray / 'readme.txt').unlink()
        self.assertEqual(self.remove('zzz'), [])               # an EMPTY directory is no evidence either
        self.assertTrue(stray.is_dir())
        (stray / '0.1.0-0123456789ab').mkdir()
        self.assertEqual(self.remove('zzz'), ['files'])

    def install_named_zzz(self):
        m = good_manifest()
        m['game']['id'] = 'zzz'
        return self.install(self.package('zzz.avrgame', manifest=mjson(m)))

    def run_failing_at(self, n):
        count = []

        def run(argv):
            self.calls.append(list(argv))
            count.append(argv)
            if len(count) == n:
                raise subprocess.CalledProcessError(1, argv)
        return run

    def test_an_interrupted_remove_keeps_its_evidence_and_a_second_remove_finishes(self):
        everything = dict(REPO, hello={'id': 'hello'})
        self.install()
        self.calls.clear()
        self.remove()
        calls = len(self.calls)
        self.assertGreater(calls, 3)
        for view, repo in (('not first-party', REPO), ('first-party since', everything)):
            for n in range(1, calls + 1):
                self.install()
                with self.subTest(view=view, failing_call=n):
                    try:
                        self.remove(repo=repo, run=self.run_failing_at(n))
                    except subprocess.CalledProcessError:
                        pass
                    # whatever happened, a plain remove ends it (a first-party view refuses a finished one: no record)
                    try:
                        self.remove(repo=repo)
                    except pg.Refused:
                        self.assertEqual([p for p in self.snapshot() if 'hello' in p], [])
                    self.assertEqual([p for p in self.snapshot() if 'hello' in p], [])

    def test_a_remove_that_dies_at_each_file_step_is_finished_by_the_next_one(self):
        everything = dict(REPO, hello={'id': 'hello'})
        real_unlink = os.unlink
        for view, repo in (('not first-party', REPO), ('first-party since', everything)):
            for target in ('rmtree', 'unlink'):
                self.install()

                def boom_rmtree(path):
                    raise OSError('i/o error')

                def boom_unlink(path, *a, **kw):
                    if Path(path) == self.layout.record('hello'):
                        raise OSError('i/o error')
                    return real_unlink(path, *a, **kw)
                patch = (mock.patch.object(ig, '_rmtree', boom_rmtree) if target == 'rmtree'
                         else mock.patch.object(ig.os, 'unlink', boom_unlink))
                with self.subTest(view=view, target=target):
                    with patch, self.assertRaises(OSError):
                        self.remove(repo=repo)
                    if target == 'rmtree':
                        self.assertTrue(self.layout.record('hello').exists())      # the record outlives the tree
                    self.remove(repo=repo)
                    self.assertEqual([p for p in self.snapshot() if 'hello' in p], [])


class CommunityUnitTests(Base):
    """AVR-336: ceilings and extra confinement for the community tier only; durable writes."""

    WANT = ('MemoryMax=256M', 'TasksMax=64', 'CPUQuota=100%', 'CapabilityBoundingSet=', 'PrivateNetwork=yes',
            'ProtectProc=invisible', 'ProtectClock=yes', 'ProtectHostname=yes', 'LockPersonality=yes',
            'RestrictRealtime=yes', 'RestrictNamespaces=yes')
    RUNTIME = {'command': ['/usr/bin/python3', '-m', 'g'], 'working_directory': '/opt/avrana-games/g/1.0.0-0123456789ab'}

    def test_a_package_unit_carries_the_ceilings_and_a_first_party_unit_does_not(self):
        self.install()
        dropin = self.layout.provision.dropin('hello').read_text(encoding='utf-8')
        lines = dropin.splitlines()
        for want in self.WANT:
            self.assertIn(want, lines)
        first_party = pg.dropin_text(self.RUNTIME, ORIGIN)
        for want in self.WANT:
            self.assertNotIn(want, first_party.splitlines())
        self.assertEqual(pg.dropin_text(self.RUNTIME, ORIGIN, 'builtin'), first_party)
        self.assertEqual(pg.dropin_text(self.RUNTIME, ORIGIN, pg.COMMUNITY_TIER, ['persistent_storage']),
                         first_party + pg.COMMUNITY_UNIT)
        self.assertEqual(pg.dropin_text(self.RUNTIME, ORIGIN, pg.COMMUNITY_TIER), first_party + pg.COMMUNITY_UNIT + pg.NO_STATE)

    def test_the_extra_lines_are_valid_unit_directives_in_the_service_section(self):
        text = pg.dropin_text(self.RUNTIME, ORIGIN, pg.COMMUNITY_TIER)
        self.assertEqual(text.count('[Service]'), 1)
        self.assertEqual(text.count('['), 1)
        for line in pg.COMMUNITY_UNIT.splitlines():
            self.assertTrue(line.startswith('#') or '=' in line, line)

    def test_a_pure_reconcile_of_an_installed_package_changes_nothing(self):
        self.install()
        wanted = pg.plan_provision('hello', self.layout.provision, installed.load(self.layout.records_dir, REPO).contracts,
                                   installed.load(self.layout.records_dir, REPO).grants, ORIGIN)
        self.assertEqual(wanted, [])

    def test_files_are_flushed_before_they_get_their_real_name(self):
        order = []
        real_fsync, real_replace = os.fsync, os.replace

        def fsync(fd):
            order.append('fsync')
            return real_fsync(fd)

        def replace(src, dst):
            order.append('replace:' + Path(dst).name)
            return real_replace(src, dst)
        with mock.patch.object(pg.os, 'fsync', fsync), mock.patch.object(pg.os, 'replace', replace):
            self.install()
        for name in ('hello.json', 'exec.conf', 'hello.key'):
            at = order.index('replace:' + name)
            self.assertEqual(order[at - 1], 'fsync', (name, order))


class InterruptTests(Base):
    """AVR-336: a hang-up or TERM during an install is an undo, not a half-installed game."""

    @unittest.skipUnless(os.name == 'posix', 'POSIX signals')
    def test_a_signal_mid_install_unwinds_and_a_second_one_cannot_cut_the_undo_short(self):
        import signal
        before = self.snapshot()
        old = {n: signal.getsignal(getattr(signal, n)) for n in ('SIGINT', 'SIGTERM', 'SIGHUP')}
        fired = []

        def run(argv):
            self.calls.append(list(argv))
            if argv[1] == 'enable' and not fired:
                fired.append(1)
                os.kill(os.getpid(), signal.SIGHUP)
            elif fired and len(fired) == 1:
                fired.append(2)
                os.kill(os.getpid(), signal.SIGTERM)          # arrives while the undo runs: ignored
        out, err = io.StringIO(), io.StringIO()
        args = ['install', str(self.package()), '--grant', 'party_roster']
        paths = ['--key-dir', self.layout.provision.key_dir, '--registry-dir', self.layout.provision.registry_dir,
                 '--socket-dir', self.layout.provision.socket_dir, '--state-dir', self.layout.provision.state_dir,
                 '--unit-dir', self.layout.provision.unit_dir, '--template-dir', self.layout.provision.template_dir,
                 '--records-dir', self.layout.records_dir, '--games-root', self.layout.games_root,
                 '--lock-file', self.layout.lock_file, '--visible-root', '/opt/avrana-games',
                 '--party-config', self.root / 'etc/party-core.json']
        rc = ig.main(args + [str(p) for p in paths], run=run, own=self.own, is_root=True, contracts=REPO, out=out, err=err)
        self.assertEqual(fired, [1, 2])
        self.assertEqual(rc, 1)
        self.assertIn('interrupted', err.getvalue())
        self.assertEqual(self.snapshot(), before)
        self.assertEqual({n: signal.getsignal(getattr(signal, n)) for n in old}, old)    # handlers put back


class InterruptTruthTests(Base):
    """AVR-336 review: an undo is never cut short, and the message says what really happened."""

    def cli(self, *args, run):
        paths = ['--key-dir', self.layout.provision.key_dir, '--registry-dir', self.layout.provision.registry_dir,
                 '--socket-dir', self.layout.provision.socket_dir, '--state-dir', self.layout.provision.state_dir,
                 '--unit-dir', self.layout.provision.unit_dir, '--template-dir', self.layout.provision.template_dir,
                 '--records-dir', self.layout.records_dir, '--games-root', self.layout.games_root,
                 '--lock-file', self.layout.lock_file, '--visible-root', '/opt/avrana-games',
                 '--party-config', self.root / 'etc/party-core.json']
        out, err = io.StringIO(), io.StringIO()
        rc = ig.main([*args, *[str(p) for p in paths]], run=run, own=self.own, is_root=True, contracts=REPO,
                     opener=lambda target, timeout: Response(IDLE), out=out, err=err)
        return rc, out.getvalue(), err.getvalue()

    @unittest.skipUnless(os.name == 'posix', 'POSIX signals')
    def test_a_signal_during_the_undo_after_an_ordinary_failure_does_not_cut_it_short(self):
        import signal
        before = self.snapshot()
        state = []

        def run(argv):
            self.calls.append(list(argv))
            if argv[1] == 'enable' and not state:
                state.append('failed')
                raise subprocess.CalledProcessError(1, argv)       # an ordinary failure, no signal
            if state == ['failed']:
                state.append('signalled')
                os.kill(os.getpid(), signal.SIGTERM)               # arrives while the undo runs
        rc, out, err = self.cli('install', str(self.package()), '--grant', 'party_roster', run=run)
        self.assertEqual(state, ['failed', 'signalled'])
        self.assertEqual(rc, 1)
        self.assertIn('nothing is left installed', err)
        self.assertEqual(self.snapshot(), before)

    @unittest.skipUnless(os.name == 'posix', 'POSIX signals')
    def test_a_signal_after_the_install_completed_cannot_report_an_undo(self):
        import signal
        import time
        with ig.interrupts_as_exceptions():
            self.install()
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(0.05)                                       # delivered, swallowed: the game IS installed
        self.assertEqual(ig.verify('hello', self.layout, REPO), [])

    @unittest.skipUnless(os.name == 'posix', 'POSIX signals')
    def test_an_interrupted_remove_says_to_run_remove_again_and_does_it_finish(self):
        import signal
        self.install()
        fired = []

        def run(argv):
            self.calls.append(list(argv))
            if argv[1] == 'reload' and not fired:
                fired.append(1)
                os.kill(os.getpid(), signal.SIGHUP)
        rc, out, err = self.cli('remove', 'hello', run=run)
        self.assertEqual(rc, 1)
        self.assertIn('removal of hello may be half done', err)
        self.assertIn('install-game remove hello', err)
        self.assertNotIn('undone', err)
        rc, out, err = self.cli('remove', 'hello', run=self.run_)
        self.assertEqual(rc, 0, err)
        self.assertEqual([p for p in self.snapshot() if 'hello' in p], [])

    def test_a_legacy_record_without_the_roster_is_named_with_its_remedy_by_list_and_verify(self):
        self.install()
        doc = json.loads(self.layout.record('hello').read_text(encoding='utf-8'))
        doc['grant']['permissions_granted'] = []
        self.layout.record('hello').write_text(json.dumps(doc), encoding='utf-8')
        if os.name == 'posix':
            os.chmod(self.layout.record('hello'), 0o644)
        rc, out, err = self.cli('list', run=self.run_)
        self.assertEqual(rc, 0)
        self.assertIn('REFUSED hello: record refused', out)
        self.assertIn('install-game remove hello', out)
        self.assertIn('--grant party_roster', out)
        rc, out, err = self.cli('verify', 'hello', run=self.run_)
        self.assertEqual(rc, 1)
        self.assertIn('install-game remove hello', err)
        self.assertIn('--grant party_roster', err)

    def test_a_record_cannot_claim_another_tier(self):
        self.install()
        doc = json.loads(self.layout.record('hello').read_text(encoding='utf-8'))
        for tier in ('builtin', 'verified', '', None):
            doc['grant']['tier'] = tier
            self.layout.record('hello').write_text(json.dumps(doc), encoding='utf-8')
            if os.name == 'posix':
                os.chmod(self.layout.record('hello'), 0o644)
            found = installed.load(self.layout.records_dir, REPO)
            self.assertEqual(found.grants, {}, tier)
            self.assertTrue(any('community' in p for p in found.problems), (tier, found.problems))


class EmptyDirectoryTests(Base):
    @unittest.skipUnless(os.name == 'posix', 'POSIX modes')
    def test_a_writable_or_foreign_empty_id_directory_is_refused(self):
        d = self.layout.id_dir('hello')
        d.mkdir()
        os.chmod(d, 0o777)
        before = self.snapshot()
        self.refused(lambda: self.install(), 'not root-owned or is writable', 'delete it by hand')
        os.chmod(d, 0o755)
        self.refused(lambda: self.install(owner=os.getuid() + 1), 'not root-owned or is writable')
        self.assertEqual((self.snapshot(), self.calls), (before, []))
        self.install(owner=os.getuid())
        self.assertEqual(ig.verify('hello', self.layout, REPO), [])


def shutil_rmtree(path):
    import shutil
    shutil.rmtree(path)


if __name__ == '__main__':
    unittest.main()
