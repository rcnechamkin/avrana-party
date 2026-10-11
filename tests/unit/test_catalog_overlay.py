"""The effective game catalog (AVR-337, EXPERIMENTAL): avrana.ops.catalog_overlay and its calls
from install-game, in scratch directories on any OS. nginx serving it is test_nginx_site.py's;
real systemd is the Linux CI job's (experiments/native-game/package-proof.sh).

    python -m unittest discover -s tests/unit -p test_catalog_overlay.py
"""
import copy
import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from avrana import REPO_ROOT
from avrana.ops import catalog_overlay as co
from avrana.ops import install_game as ig

from test_install_game import Base, REPO, IDLE, Response

COMMITTED = REPO_ROOT / 'web' / 'party' / 'catalog.json'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class OverlayBase(Base):
    def setUp(self):
        super().setUp()
        self.out_dir = self.root / 'var' / 'catalog'
        self.overlay = self.out_dir / co.FILE_NAME
        self.base = COMMITTED
        self.committed_sha = sha(COMMITTED)
        self.addCleanup(lambda: self.assertEqual(sha(COMMITTED), self.committed_sha))

    def kw(self):
        return {'games_root': '/opt/avrana-games', 'owner': None, 'repo_contracts': REPO}

    def refresh(self, base=None):
        return co.refresh(self.out_dir, base or self.base, self.layout.records_dir, **self.kw())

    def doc(self):
        return json.loads(self.overlay.read_text(encoding='utf-8'))

    def main(self, *argv, root=True, base=None):
        out, err = io.StringIO(), io.StringIO()
        paths = ['--key-dir', self.layout.provision.key_dir, '--registry-dir', self.layout.provision.registry_dir,
                 '--socket-dir', self.layout.provision.socket_dir, '--state-dir', self.layout.provision.state_dir,
                 '--unit-dir', self.layout.provision.unit_dir, '--template-dir', self.layout.provision.template_dir,
                 '--records-dir', self.layout.records_dir, '--games-root', self.layout.games_root,
                 '--lock-file', self.layout.lock_file, '--visible-root', '/opt/avrana-games',
                 '--party-config', self.root / 'etc/party-core.json',
                 '--catalog-dir', self.out_dir, '--catalog-base', base or self.base]
        rc = ig.main([argv[0], *argv[1:], *[str(p) for p in paths]], run=self.run_, own=self.own, is_root=root,
                     contracts=REPO, opener=lambda target, timeout: Response(IDLE), out=out, err=err)
        return rc, out.getvalue(), err.getvalue()


class NoPackage(OverlayBase):
    def test_no_package_means_no_overlay_and_a_stale_one_is_removed(self):
        self.assertEqual(self.refresh(), ([], []))
        self.assertFalse(self.overlay.exists())
        self.out_dir.mkdir(parents=True)
        self.overlay.write_text('old', encoding='utf-8')
        (self.out_dir / '.catalog.json.abcd.tmp').write_text('half', encoding='utf-8')
        self.assertEqual(self.refresh(), ([], []))
        self.assertEqual(os.listdir(self.out_dir), [])
        self.assertEqual(co.check(self.out_dir, self.base, self.layout.records_dir, **self.kw()), [])

    def test_a_failure_removes_the_overlay_instead_of_leaving_it_stale(self):
        self.install()
        self.refresh()
        self.assertTrue(self.overlay.exists())
        with self.assertRaises(co.OverlayError) as ctx:
            self.refresh(base=self.root / 'missing.json')
        self.assertIn('release catalog', str(ctx.exception))
        self.assertFalse(self.overlay.exists())
        bad = self.root / 'bad.json'
        bad.write_text('{"schema": "avrana.catalog/v0"', encoding='utf-8')
        self.refresh()
        with self.assertRaises(co.OverlayError):
            self.refresh(base=bad)
        self.assertFalse(self.overlay.exists())
        wrong = self.root / 'wrong.json'
        wrong.write_text('{"schema": "other", "games": [], "labels": {}}', encoding='utf-8')
        self.refresh()
        with self.assertRaises(co.OverlayError):
            self.refresh(base=wrong)
        self.assertFalse(self.overlay.exists())


class WithPackage(OverlayBase):
    def test_the_package_is_appended_after_untouched_first_party_rows(self):
        self.install()
        base = json.loads(COMMITTED.read_text(encoding='utf-8'))
        self.assertEqual(self.refresh(), (['hello'], []))
        doc = self.doc()
        self.assertEqual(doc['games'][:len(base['games'])], base['games'])        # first-party rows: equal, same order, first
        self.assertEqual([g['id'] for g in doc['games'][len(base['games']):]], ['hello'])
        row = doc['games'][-1]
        self.assertEqual((row['installed'], row['entry'], row['provider'], row['status'], row['playableHere']),
                         (True, '/games/hello/', 'native', 'current', True))
        for key in ('schema', 'appliance', 'providers', 'runtime', 'collections'):
            self.assertEqual(doc[key], base[key], key)
        self.assertTrue(all(doc['labels'][k] == v for k, v in base['labels'].items()))
        # the shape the web shell checks (web/party/lib/catalog-load.js normalizeCatalog) and build.py checks
        self.assertEqual(doc['schema'], 'avrana.catalog/v0')
        self.assertIsInstance(doc['games'], list)
        # every device label the package row needs is there
        for p in row['presentations']:
            for name in p['requires']['device'] + p['optional']['device']:
                self.assertIn(name, doc['labels'])

    def test_deterministic_bytes_and_permissions_and_no_leftovers(self):
        self.install()
        self.refresh()
        first = self.overlay.read_bytes()
        self.refresh()
        self.assertEqual(self.overlay.read_bytes(), first)
        self.assertTrue(first.endswith(b'\n'))
        self.assertNotIn(b'\r', first)
        self.assertEqual(os.listdir(self.out_dir), [co.FILE_NAME])
        if os.name == 'posix':
            self.assertEqual(self.overlay.stat().st_mode & 0o777, 0o644)
        self.assertEqual(co.check(self.out_dir, self.base, self.layout.records_dir, **self.kw()), [])
        self.assertEqual(co.effective(self.base, self.layout.records_dir, **self.kw())[0].encode('utf-8'), first)

    def test_a_package_cannot_shadow_replace_or_reorder_a_first_party_row(self):
        self.install()
        base = json.loads(COMMITTED.read_text(encoding='utf-8'))
        clash = copy.deepcopy(base)
        clash['games'].insert(1, {'id': 'hello', 'name': 'First-party hello', 'installed': False})
        path = self.root / 'clash.json'
        path.write_text(json.dumps(clash), encoding='utf-8')
        text, listed, problems = co.effective(path, self.layout.records_dir, **self.kw())
        self.assertEqual((text, listed), (None, []))
        self.assertTrue(any('already has a game with this id' in p for p in problems), problems)

    def test_a_moved_release_catalog_makes_the_overlay_stale_and_refresh_keeps_new_first_party_rows_first(self):
        self.install()
        self.refresh()
        newer = json.loads(COMMITTED.read_text(encoding='utf-8'))
        extra = copy.deepcopy(newer['games'][0])
        extra.update({'id': 'newgame', 'name': 'A new first-party game'})
        newer['games'].append(extra)
        path = self.root / 'newer.json'
        path.write_text(json.dumps(newer), encoding='utf-8')
        wrong = co.check(self.out_dir, path, self.layout.records_dir, **self.kw())
        self.assertTrue(wrong and 'stale' in wrong[0], wrong)
        self.refresh(base=path)
        self.assertEqual([g['id'] for g in self.doc()['games']][-2:], ['newgame', 'hello'])
        self.assertEqual(co.check(self.out_dir, path, self.layout.records_dir, **self.kw()), [])

    def test_a_refused_record_drops_that_game_only(self):
        self.install()
        records = Path(self.layout.records_dir)
        (records / 'broken.json').write_text('{not json', encoding='utf-8')
        other = json.loads((records / 'hello.json').read_text(encoding='utf-8'))
        other['id'] = 'other'                                  # a record whose contract is another game's
        (records / 'other.json').write_text(json.dumps(other), encoding='utf-8')
        listed, problems = self.refresh()
        self.assertEqual(listed, ['hello'])
        self.assertTrue(any(p.startswith('broken:') for p in problems), problems)
        self.assertTrue(any(p.startswith('other:') for p in problems), problems)
        self.assertEqual(self.doc()['games'][-1]['id'], 'hello')

    def test_a_row_the_builder_rejects_drops_that_game_only(self):
        self.install()
        calls = []

        def build(vocab, appliance, contracts, *a, **kw):
            calls.append(sorted(kw.get('extra_grants') or {}))
            raise ValueError('hello cannot be presented here')
        with mock.patch.object(co.catalog, 'build', build):
            text, listed, problems = co.effective(self.base, self.layout.records_dir, **self.kw())
        self.assertEqual((text, listed, calls), (None, [], [['hello']]))
        self.assertIn('hello: not listed', problems[0])

    def test_an_interrupted_write_leaves_the_old_file_whole_and_no_temporary(self):
        self.install()
        self.refresh()
        before = self.overlay.read_bytes()
        with mock.patch.object(co.os, 'replace', side_effect=OSError('power')):
            with self.assertRaises(OSError):
                co.write_atomic(self.overlay, 'half')
        self.assertEqual(self.overlay.read_bytes(), before)       # a direct write that fails changes nothing
        self.assertEqual(os.listdir(self.out_dir), [co.FILE_NAME])
        with mock.patch.object(co.os, 'replace', side_effect=OSError('power')):
            with self.assertRaises(co.OverlayError):
                co.refresh(self.out_dir, self.base, self.layout.records_dir, **self.kw())
        # fail closed: the overlay is gone, not stale or half-written; refresh brings it back
        self.assertEqual(os.listdir(self.out_dir), [])
        self.refresh()
        self.assertEqual(self.overlay.read_bytes(), before)


class PackageControlledFields(OverlayBase):
    """A package's contract is free text. Whatever it says, its row is the allowlisted, bounded,
    native, community row and never passes for a first-party game."""

    def edit_record(self, **changes):
        path = Path(self.layout.records_dir) / 'hello.json'
        doc = json.loads(path.read_text(encoding='utf-8'))
        doc['contract'].update(changes)
        path.write_text(json.dumps(doc), encoding='utf-8')

    def row(self):
        self.refresh()
        return self.doc()['games'][-1]

    def test_the_reviewers_probe_is_neutralised(self):
        self.install()
        self.edit_record(extensions={'net.avrana.catalog': {
            'provider': 'lan-games', 'status': 'experimental', 'legacySlug': 'bluff', 'integration': 'avrana.lan-launch/v1',
            'icon': 'skull', 'category': 'x' * 5000, 'art': 'lan:bluff', 'accent': '#ff0000', 'description': 'd' * 3000,
            'playersLabel': 'p', 'hardwareValidationRequired': True}})
        row = self.row()
        self.assertEqual(row['id'], 'hello')
        for key in ('legacySlug', 'integration', 'icon', 'category', 'art', 'accent', 'description', 'playersLabel',
                    'launchTarget', 'artwork', 'providerMetadata', 'hardwareValidationRequired'):
            self.assertNotIn(key, row)
        self.assertEqual((row['provider'], row['status'], row['tier'], row['installed'], row['entry']),
                         ('native', 'current', 'community', True, '/games/hello/'))
        self.assertLessEqual(len(json.dumps(row)), co.MAX_ROW_BYTES)
        self.assertEqual(set(row) - set(co.ROW_KEYS), {'provider', 'status', 'tier'})

    def test_the_row_keys_are_an_allowlist_even_if_the_builder_adds_one(self):
        self.install()
        real = co.catalog.build

        def build(*a, **kw):
            doc = real(*a, **kw)
            for g in doc['games']:
                g['surprise'] = 'x'
                g['provider'] = 'lan-games'
            return doc
        with mock.patch.object(co.catalog, 'build', build):
            self.refresh()
        self.assertNotIn('surprise', self.doc()['games'][-1])
        self.assertEqual(self.doc()['games'][-1]['provider'], 'native')

    def test_oversize_text_and_rows_are_refused(self):
        self.install()
        for field, value in (('name', 'N' * (co.MAX_NAME + 1)), ('summary', 'S' * (co.MAX_SUMMARY + 1)),
                             ('name', 'bad\nname')):
            self.edit_record(**{field: value})
            text, listed, problems = co.effective(self.base, self.layout.records_dir, **self.kw())
            self.assertEqual((text, listed), (None, []), field)
            self.assertIn('hello: ', problems[0])
        row = {'id': 'hello', 'name': 'Hello', 'presentations': ['p' * 190] * 30}
        with self.assertRaises(ValueError) as ctx:
            co.package_row(row, 'hello', set())
        self.assertIn('larger than', str(ctx.exception))
        with self.assertRaises(ValueError):
            co.package_row({'id': 'hello', 'name': 'Hello', 'fallback': 'f' * 201}, 'hello', set())

    def test_a_name_that_passes_for_a_first_party_game_is_refused(self):
        self.install()
        for name in ('BLUFF', 'bluff', 'ＢＬＵＦＦ', 'Checkers', 'ExPo'):
            self.edit_record(name=name)
            text, listed, problems = co.effective(self.base, self.layout.records_dir, **self.kw())
            self.assertEqual((text, listed), (None, []), name)
            self.assertIn('first-party', problems[0], name)
        self.edit_record(name='Hello Party')
        self.assertEqual(co.effective(self.base, self.layout.records_dir, **self.kw())[1], ['hello'])

    def test_a_refused_row_fails_the_install_and_undoes_it(self):
        def refuse(row, pid, names):
            raise ValueError('the display name is, or is easily mistaken for, a first-party game')
        with mock.patch.object(co, 'package_row', refuse):
            rc, out, err = self.main('install', str(self.package()), '--grant', 'party_roster')
        self.assertEqual(rc, 1)
        self.assertIn('the effective catalog:', err)
        self.assertIn('first-party game', err)
        self.assertIn('nothing is left installed', err)
        self.assertFalse(self.overlay.exists())
        self.assertEqual([p for p in self.files() if 'hello' in p], [])

    def test_a_refused_row_at_refresh_time_drops_only_that_row_and_check_says_so(self):
        self.install()
        self.edit_record(name='Bluff')
        self.assertEqual(self.refresh()[0], [])
        notes = []
        self.assertEqual(co.check(self.out_dir, self.base, self.layout.records_dir, notes, **self.kw()), [])
        self.assertTrue(any('first-party' in n for n in notes), notes)
        out, err = io.StringIO(), io.StringIO()
        co.main(['check', '--base', str(self.base), '--out-dir', str(self.out_dir), '--records-dir',
                 str(self.layout.records_dir), '--games-root', '/opt/avrana-games'], out=out, err=err)
        self.assertIn('catalog-overlay: warning: hello:', err.getvalue())

    def test_the_whole_overlay_is_bounded(self):
        self.install()
        with mock.patch.object(co, 'MAX_OVERLAY_BYTES', 100):
            with self.assertRaises(co.OverlayError):
                self.refresh()
        self.assertFalse(self.overlay.exists())

    @unittest.skipUnless(os.name == 'posix', 'a umask')
    def test_the_catalog_directory_is_0755_whatever_the_umask(self):
        self.install()
        old = os.umask(0o077)
        try:
            self.refresh()
        finally:
            os.umask(old)
        self.assertEqual(self.out_dir.stat().st_mode & 0o777, 0o755)
        self.assertEqual(self.overlay.stat().st_mode & 0o777, 0o644)


class ShellHook(unittest.TestCase):
    """ops/install-party-web.sh refresh_catalog: any failure removes the overlay (never left built
    from the previous release) and says how to repair. Real bash, a python3 that fails."""

    @unittest.skipUnless(os.name == 'posix' and shutil.which('bash'), 'needs bash on POSIX')
    def test_a_failed_refresh_removes_the_overlay_and_is_loud(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / 'bin').mkdir()
            (tmp / 'bin' / 'python3').write_text('#!/bin/sh\nexit 1\n')
            (tmp / 'bin' / 'python3').chmod(0o755)
            (tmp / 'ov').mkdir()
            (tmp / 'ov' / 'catalog.json').write_text('old first-party catalog')
            (tmp / 'rec').mkdir()
            script = REPO_ROOT / 'ops' / 'install-party-web.sh'
            fn = subprocess.run(['sed', '-n', '/^refresh_catalog()/,/^}/p', str(script)], capture_output=True, text=True).stdout
            self.assertIn('catalog_overlay refresh', fn)
            env = dict(os.environ, PATH=f'{tmp}/bin:{os.environ["PATH"]}', AVRANA_CATALOG_OVERLAY=str(tmp / 'ov' / 'catalog.json'),
                       AVRANA_PACKAGE_RECORDS=str(tmp / 'rec'))
            run = subprocess.run(['bash', '-c', f'BASH_SOURCE={script}; {fn}\nrefresh_catalog {tmp}/rel'], env=env,
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)               # a failure never fails the web install
            self.assertFalse((tmp / 'ov' / 'catalog.json').exists())
            self.assertIn('could NOT be regenerated', run.stderr)
            self.assertIn('ops/catalog-overlay refresh', run.stderr)


class FromInstallGame(OverlayBase):
    def test_install_and_remove_through_the_command_line_keep_the_overlay_in_step(self):
        pkg = str(self.package())
        rc, out, err = self.main('install', pkg, '--grant', 'party_roster')
        self.assertEqual(rc, 0, err)
        self.assertIn('catalog: the effective catalog lists hello', out)
        self.assertEqual(self.doc()['games'][-1]['id'], 'hello')
        self.assertEqual(co.check(self.out_dir, self.base, self.layout.records_dir, **self.kw()), [])
        rc, out, err = self.main('remove', 'hello')
        self.assertEqual(rc, 0, err)
        self.assertIn('catalog: no package is listed', out)
        self.assertFalse(self.overlay.exists())
        self.assertEqual(os.listdir(self.out_dir), [])

    def test_a_dry_run_writes_no_overlay(self):
        rc, _, err = self.main('install', str(self.package()), '--dry-run', root=False)
        self.assertEqual(rc, 0, err)
        self.assertFalse(self.out_dir.exists())

    def test_a_catalog_that_cannot_be_written_fails_the_install_and_undoes_it(self):
        rc, out, err = self.main('install', str(self.package()), '--grant', 'party_roster', base=self.root / 'missing.json')
        self.assertEqual(rc, 1)
        self.assertIn('the effective catalog:', err)
        self.assertIn('nothing is left installed', err)
        self.assertFalse(self.overlay.exists())
        self.assertEqual([p for p in self.files() if 'hello' in p], [])
        self.assertEqual(ig.listing(self.layout, REPO)[0], {})
        self.assertIn(['systemctl', 'reload', 'avrana-party-core.service'], self.calls)

    def test_a_catalog_that_cannot_be_written_after_a_remove_leaves_the_release_catalog_served(self):
        self.assertEqual(self.main('install', str(self.package()), '--grant', 'party_roster')[0], 0)
        rc, out, err = self.main('remove', 'hello', base=self.root / 'missing.json')
        self.assertEqual(rc, 1)
        self.assertIn('the effective catalog:', err)
        self.assertIn('hello: removed record', out)         # the completed removal is reported beside the problem
        self.assertFalse(self.overlay.exists())            # absent, so the release catalog is served
        self.assertEqual([p for p in self.files() if 'hello' in p], [])


class Command(OverlayBase):
    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        rc = co.main([*args, '--base', str(self.base), '--out-dir', str(self.out_dir),
                      '--records-dir', str(self.layout.records_dir), '--games-root', '/opt/avrana-games'], out=out, err=err)
        return rc, out.getvalue(), err.getvalue()

    def test_show_and_check_without_a_package(self):
        rc, out, _ = self.run_main('show')
        self.assertEqual((rc, out), (0, COMMITTED.read_text(encoding='utf-8')))      # nothing installed: the release catalog
        self.assertEqual(self.run_main('check')[0], 0)

    @unittest.skipUnless(os.name == 'posix' and hasattr(os, 'geteuid') and os.geteuid() != 0, 'needs a non-root POSIX user')
    def test_refresh_needs_root(self):
        rc, _, err = self.run_main('refresh')
        self.assertEqual(rc, 1)
        self.assertIn('must run as root', err)


if __name__ == '__main__':
    unittest.main()
