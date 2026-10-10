"""EXPERIMENTAL .avrgame package format (AVR-37, first half of AVR-39): manifest, validator, pack,
read, extract and the CLI. Cross-platform; builds a small synthetic game in a temp directory.

    python3 -m unittest tests.unit.test_avrgame_package

Everything here is about an experimental format that is not frozen (docs/design/AVRGAME-PACKAGE.md).
"""
import ast
import copy
import io
import json
import os
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest import mock

from avrana import CONTRACTS_DIR, REPO_ROOT
from avrana import avrgame
from avrana.avrgame import archive, common, manifest as manifest_module
from avrana.contracts import strictjson

HELLO = strictjson.load_path(CONTRACTS_DIR / 'games' / 'hello.json')


def good_manifest(**over):
    m = {
        'format': avrgame.FORMAT,
        'game': copy.deepcopy(HELLO),
        'package': {'version': '0.1.0', 'publisher': 'Example Studio', 'license': 'MIT',
                    'source': 'https://example.invalid/src'},
        'requires': {'session': 'avrana.party-session/v0', 'bridge': 'avrana.party-bridge/v1',
                     'result': 'avrana.game-result/v1'},
        'server': {'interpreter': 'python3', 'args': ['-m', 'game_pkg']},
        'client': {'root': 'game_pkg/web'},
    }
    m.update(over)
    return m


def problems_of(obj, **kw):
    with unittest.TestCase().assertRaises(avrgame.Refused) as ctx:
        avrgame.validate_manifest(obj, **kw)
    return ctx.exception.problems


def mjson(m=None):
    return json.dumps(good_manifest() if m is None else m, indent=2).encode()


BASE_FILES = {
    'game_pkg/__init__.py': b'',
    'game_pkg/__main__.py': b'print("hi")\n',
    'game_pkg/web/index.html': b'<!doctype html><title>x</title>\n',
    'game_pkg/web/app.js': b'export const a = 1;\n',
}


def make_zip(files=None, manifest=None, extra=(), method=zipfile.ZIP_DEFLATED, with_manifest=True):
    """A ZIP with exactly the entries given. `extra` items: (name, data) or (name, data, external_attr).
    A name is written as given (backslash, NUL and so on included)."""
    buf = io.BytesIO()
    entries = []
    if with_manifest:
        entries.append(('avrgame.json', manifest if manifest is not None else mjson(), None))
    for name, data in (BASE_FILES if files is None else files).items():
        entries.append((name, data, None))
    for item in extra:
        entries.append((item[0], item[1], item[2] if len(item) > 2 else None))
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')          # duplicate names are the point of some cases
        with zipfile.ZipFile(buf, 'w') as zf:
            for name, data, attr in entries:
                info = zipfile.ZipInfo('placeholder', (1980, 1, 1, 0, 0, 0))
                info.filename = name             # after construction: no truncation or separator rewrite
                info.compress_type = method
                info.external_attr = attr if attr is not None else (stat.S_IFREG | 0o644) << 16
                zf.writestr(info, data)
    return buf.getvalue()


def patch_central(data, name, offset, fmt, value):
    """Overwrite a field of one central directory record (found by name)."""
    raw = name.encode('latin-1')
    pos = 0
    while True:
        pos = data.find(b'PK\x01\x02', pos)
        if pos < 0:
            raise AssertionError('no such record')
        if data[pos + 46:pos + 46 + len(raw)] == raw and struct.unpack('<H', data[pos + 28:pos + 30])[0] == len(raw):
            break
        pos += 4
    out = bytearray(data)
    struct.pack_into(fmt, out, pos + offset, value)
    return bytes(out)


class Tmp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def write_zip(self, data, name='x.avrgame'):
        path = self.tmp / name
        path.write_bytes(data)
        return path

    def refused(self, data, expect):
        with self.assertRaises(avrgame.Refused) as ctx:
            avrgame.read(self.write_zip(data))
        text = '\n'.join(ctx.exception.problems)
        self.assertIn(expect, text)
        return ctx.exception.problems

    def make_tree(self, name='src'):
        """A synthetic Python game tree with a manifest and a build recipe; returns its root."""
        root = self.tmp / name
        for rel, data in {**BASE_FILES, 'shared/helper.py': b'X = 1\n'}.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        (root / 'avrgame.json').write_bytes(mjson())
        (root / 'avrgame.build.json').write_text(json.dumps({
            'recipe': avrgame.RECIPE_FORMAT, 'manifest': 'avrgame.json', 'root': '.',
            'include': ['game_pkg', 'shared']}))
        return root


class ManifestTests(unittest.TestCase):
    def test_a_valid_manifest_is_normalised_and_the_game_id_is_the_contracts(self):
        out = avrgame.validate_manifest(good_manifest())
        self.assertEqual(out['game']['id'], 'hello')
        self.assertEqual(out['format'], 'avrana.avrgame/experimental.1')
        self.assertEqual(out['server'], {'interpreter': 'python3', 'args': ['-m', 'game_pkg']})
        self.assertEqual(out['package']['version'], '0.1.0')

    def test_source_is_optional_but_version_publisher_and_license_are_required(self):
        m = good_manifest()
        del m['package']['source']
        avrgame.validate_manifest(m)
        for key in ('version', 'publisher', 'license'):
            m = good_manifest()
            del m['package'][key]
            self.assertIn(f"package: missing '{key}'", problems_of(m))

    def test_any_other_format_is_refused_and_the_message_names_what_is_supported(self):
        for fmt in ('avrana.avrgame/v0', 'avrana.avrgame/experimental.2', '', None, 1):
            p = problems_of(good_manifest(format=fmt))
            self.assertTrue(any(avrgame.FORMAT in x and x.startswith('format:') for x in p), p)

    def test_duplicate_keys_nan_and_non_utf8_are_refused(self):
        for raw in (b'{"format": "a", "format": "b"}', b'{"format": NaN}', b'\xff\xfe', b'[1', b'\xef\xbb\xbf{}'):
            with self.assertRaises(avrgame.Refused, msg=raw):
                avrgame.parse_manifest(raw)
        with self.assertRaises(avrgame.Refused):
            avrgame.parse_manifest(b'[' * 5000 + b']' * 5000)
        with self.assertRaises(avrgame.Refused):
            avrgame.parse_manifest(b' ' * (common.MAX_MANIFEST_BYTES + 1))

    def test_unknown_keys_are_refused_at_every_level(self):
        cases = [(lambda m: m.update(extra=1), 'manifest: unknown key'),
                 (lambda m: m['package'].update(color='red'), 'package: unknown key'),
                 (lambda m: m['requires'].update(party='x'), 'requires: unknown key'),
                 (lambda m: m['server'].update(shell=True), 'server: unknown key'),
                 (lambda m: m['client'].update(onboarding='x'), 'client: unknown key'),
                 (lambda m: m['game'].update(color='x'), "game: contract: unknown key 'color'")]
        for mutate, expect in cases:
            m = good_manifest()
            mutate(m)
            self.assertTrue(any(expect in p for p in problems_of(m)), (expect, problems_of(m)))

    def test_a_package_requests_but_never_grants(self):
        # The envelope rejects appliance-owned names by name, at every level; the embedded contract
        # validator already did the same for the game block.
        for key in ('tier', 'entry', 'health', 'permissions', 'key', 'socket', 'path', 'trust', 'url'):
            m = good_manifest()
            m[key] = 'x'
            self.assertTrue(any(f'manifest.{key}: set by the appliance' in p for p in problems_of(m)), key)
        for where, key in (('server', 'command'), ('server', 'env'), ('server', 'working_directory'),
                           ('client', 'entry'), ('package', 'tier'), ('requires', 'permissions')):
            m = good_manifest()
            m[where][key] = 'x'
            self.assertTrue(any(f'{where}.{key}: set by the appliance' in p for p in problems_of(m)), (where, key))
        for key in ('tier', 'entry', 'path', 'grant'):
            m = good_manifest()
            m['game'][key] = 'x'
            self.assertTrue(any(f'game: contract.{key}: set by the appliance grant' in p for p in problems_of(m)), key)

    def test_signature_provenance_entitlement_and_publisher_key_are_reserved_not_ignored(self):
        for key in ('signature', 'provenance', 'entitlement', 'publisher_key'):
            m = good_manifest()
            m[key] = 'x'
            p = problems_of(m)
            self.assertTrue(any(key in x and 'reserved; not implemented in this experimental format' in x for x in p), p)

    def test_only_native_games_are_packageable(self):
        for mutate in (lambda g: g.update(kind='emulated', runtime={'type': 'emulator_profile', 'start': 'service',
                                                                    'profile': 'snes'}),
                       lambda g: g.update(kind='other')):
            m = good_manifest()
            mutate(m['game'])
            self.assertTrue(any('emulation is a separate provider' in p for p in problems_of(m)))
        m = good_manifest()
        m['game']['runtime'] = {'type': 'lan_games_module'}
        self.assertTrue(any('game.runtime' in p and 'external' in p for p in problems_of(m)))
        m = good_manifest()
        m['game']['runtime']['start'] = 'always_on'
        self.assertTrue(any('game.runtime' in p for p in problems_of(m)))

    def test_the_embedded_contract_is_validated_by_the_existing_validator(self):
        m = good_manifest()
        m['game']['players'] = {'min': 5, 'max': 2}
        self.assertTrue(any(p.startswith('game: ') and 'min > max' in p for p in problems_of(m)))
        m = good_manifest()
        m['game']['presentations'][0]['requires'] = {'device': ['no_such_capability']}
        self.assertTrue(any('no_such_capability' in p for p in problems_of(m)))
        m = good_manifest()
        m['game']['package'] = {'version': '1', 'platforms': ['any']}
        self.assertTrue(any('game.package' in p for p in problems_of(m)))

    def test_package_claims_are_bounded_display_text(self):
        for version in ('1.0', 'v1.0.0', '1.0.0-' + 'x' * 33, '1.0.0 ', '../1.0.0', '', 5):
            m = good_manifest()
            m['package']['version'] = version
            self.assertTrue(any(p.startswith('package.version') for p in problems_of(m)), version)
        for version in ('0.1.0', '10.20.30-rc.1', '1.0.0-' + 'x' * 32):
            m = good_manifest()
            m['package']['version'] = version
            avrgame.validate_manifest(m)
        for key, bad in (('publisher', 'x' * 81), ('license', ''), ('source', 'x\ny'), ('publisher', ' lead')):
            m = good_manifest()
            m['package'][key] = bad
            self.assertTrue(any(p.startswith(f'package.{key}') for p in problems_of(m)), (key, bad))

    def test_requires_is_checked_against_what_this_party_implements(self):
        sup = avrgame.supported_requires()
        from avrana.party import protocol, result, service
        self.assertEqual(sup['session'], (protocol.VERSION,))
        self.assertEqual(sup['result'], (result.SCHEMA,))
        self.assertEqual(sup['bridge'], (service.BRIDGE_SCHEMA,))
        for key in ('session', 'bridge', 'result'):
            m = good_manifest()
            m['requires'][key] = 'avrana.nope/v9'
            self.assertTrue(any(p.startswith(f'requires.{key}') for p in problems_of(m)))
            m = good_manifest()
            del m['requires'][key]
            self.assertIn(f"requires: missing '{key}'", problems_of(m))

    def test_server_names_an_interpreter_never_a_path(self):
        self.assertEqual(dict(avrgame.INTERPRETERS), {'python3': '/usr/bin/python3'})
        with self.assertRaises(TypeError):
            avrgame.INTERPRETERS['sh'] = '/bin/sh'
        for interp in ('/usr/bin/python3', 'python', 'sh', '', None, ['python3']):
            m = good_manifest()
            m['server']['interpreter'] = interp
            self.assertTrue(any(p.startswith('server.interpreter') for p in problems_of(m)), interp)

    def test_server_args_are_bounded_printable_and_relative(self):
        bad = {'none': [], 'too many': ['a'] * 17, 'too long': ['x' * 201], 'empty': [''], 'control': ['a\x00b'],
               'newline': ['a\nb'], 'not strings': [1], 'absolute': ['/etc/passwd'], 'drive': ['C:\\x'],
               'dotdot': ['../x'], 'not a list': '-m x'}
        for label, args in bad.items():
            m = good_manifest()
            m['server']['args'] = args
            self.assertTrue(any(p.startswith('server.args') for p in problems_of(m)), label)
        m = good_manifest()
        m['server']['args'] = ['-m', 'game_pkg'] + ['--flag'] * 14
        avrgame.validate_manifest(m)

    def test_client_root_is_a_safe_relative_path(self):
        for root in ('/abs', '../x', 'a//b', 'a\\b', 'C:/x', '', '.', 'x/.', 'a' * 201, 'con', None, 5):
            m = good_manifest()
            m['client']['root'] = root
            self.assertTrue(any('client.root' in p for p in problems_of(m)), root)

    def test_every_problem_is_collected_not_just_the_first(self):
        m = good_manifest(format='nope', extra=1)
        m['server']['interpreter'] = '/bin/sh'
        m['requires']['session'] = 'x'
        m['package']['version'] = 'x'
        self.assertGreaterEqual(len(problems_of(m)), 5)

    def test_untrusted_text_in_a_message_is_escaped_and_bounded(self):
        m = good_manifest(format='\x1b[31m' + 'A' * 5000)
        for p in problems_of(m):
            self.assertLess(len(p), 400)
            self.assertNotIn('\x1b', p)

    def test_validation_never_executes_anything(self):
        m = good_manifest()
        m['server']['args'] = ['-c', '__import__("os").system("echo hacked > pwned.txt")']
        avrgame.validate_manifest(m)
        self.assertFalse(Path('pwned.txt').exists())


class PackAndReadTests(Tmp):
    def pack(self, root=None, out='out.avrgame', **kw):
        root = root or self.make_tree()
        return avrgame.pack(root, root / 'avrgame.json', ['game_pkg', 'shared'], self.tmp / out, **kw)

    def test_pack_is_deterministic_and_a_changed_byte_changes_the_hash(self):
        root = self.make_tree()
        a = self.pack(root, 'a.avrgame')
        b = self.pack(root, 'b.avrgame')
        self.assertEqual((self.tmp / 'a.avrgame').read_bytes(), (self.tmp / 'b.avrgame').read_bytes())
        self.assertEqual(a.sha256, b.sha256)
        s = self.pack(root, 's.avrgame', compress=False)
        self.assertEqual(s.sha256, self.pack(root, 's2.avrgame', compress=False).sha256)
        os.utime(root / 'shared' / 'helper.py', (1, 1))          # mtime is not part of the archive
        self.assertEqual(self.pack(root, 'c.avrgame').sha256, a.sha256)
        (root / 'shared' / 'helper.py').write_bytes(b'X = 2\n')
        self.assertNotEqual(self.pack(root, 'd.avrgame').sha256, a.sha256)

    def test_the_archive_is_sorted_with_fixed_times_modes_and_forward_slashes(self):
        self.pack()
        with zipfile.ZipFile(self.tmp / 'out.avrgame') as zf:
            infos = zf.infolist()
        names = [i.filename for i in infos]
        self.assertEqual(names[0], 'avrgame.json')
        self.assertEqual(names[1:], sorted(names[1:]))
        for i in infos:
            self.assertEqual(i.date_time, (1980, 1, 1, 0, 0, 0))
            self.assertEqual(i.external_attr >> 16, stat.S_IFREG | 0o644)
            self.assertFalse(i.filename.endswith('/'))
            self.assertNotIn('\\', i.filename)
            self.assertIn(i.compress_type, (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED))

    def test_bytecode_caches_dotfiles_and_the_recipe_are_left_out_of_a_directory_include(self):
        root = self.make_tree()
        (root / 'game_pkg' / '__pycache__').mkdir()
        (root / 'game_pkg' / '__pycache__' / 'x.cpython-312.pyc').write_bytes(b'\0')
        (root / 'game_pkg' / 'stray.pyc').write_bytes(b'\0')
        (root / 'game_pkg' / '.hidden').write_bytes(b'secret')
        (root / 'game_pkg' / '.git').mkdir()
        (root / 'game_pkg' / '.git' / 'config').write_bytes(b'x')
        (root / 'game_pkg' / 'avrgame.build.json').write_bytes(b'{}')
        paths = [f.path for f in self.pack(root).files]
        self.assertEqual(paths, sorted(['avrgame.json', 'game_pkg/__init__.py', 'game_pkg/__main__.py',
                                        'game_pkg/web/app.js', 'game_pkg/web/index.html', 'shared/helper.py']))

    def test_naming_a_forbidden_file_explicitly_is_refused(self):
        root = self.make_tree()
        (root / '.env').write_bytes(b'x')
        (root / 'mod.pyc').write_bytes(b'x')
        (root / 'bad name.txt').write_bytes(b'x')
        for include in ('.env', 'mod.pyc', 'bad name.txt', '../x', '/etc/passwd', 'a\\b', 'missing', 'con.txt'):
            with self.assertRaises(avrgame.Refused, msg=include):
                avrgame.pack(root, root / 'avrgame.json', ['game_pkg', include], self.tmp / 'o.avrgame')
            self.assertFalse((self.tmp / 'o.avrgame').exists())

    def test_symbolic_links_are_refused(self):
        root = self.make_tree()
        target = self.tmp / 'outside.txt'
        target.write_bytes(b'secret')
        try:
            os.symlink(target, root / 'game_pkg' / 'link.txt')
        except (OSError, NotImplementedError, AttributeError):
            self.skipTest('this host cannot create symbolic links')
        with self.assertRaises(avrgame.Refused) as ctx:
            self.pack(root)
        self.assertIn('symbolic links are refused', '\n'.join(ctx.exception.problems))
        self.assertFalse((self.tmp / 'out.avrgame').exists())

    def test_pack_validates_the_manifest_and_the_file_list_and_writes_nothing_on_failure(self):
        root = self.make_tree()
        (root / 'game_pkg' / 'web' / 'index.html').unlink()
        with self.assertRaises(avrgame.Refused) as ctx:
            self.pack(root)
        self.assertIn('index.html', '\n'.join(ctx.exception.problems))
        bad = good_manifest(format='nope')
        (root / 'avrgame.json').write_bytes(mjson(bad))
        with self.assertRaises(avrgame.Refused):
            self.pack(root)
        self.assertEqual([p.name for p in self.tmp.iterdir() if p.suffix in ('.avrgame', '.tmp')], [])

    def test_the_manifest_must_not_also_be_a_different_root_file(self):
        root = self.make_tree()
        (root / 'm').mkdir()
        (root / 'm' / 'avrgame.json').write_bytes(mjson())
        with self.assertRaises(avrgame.Refused) as ctx:
            avrgame.pack(root, root / 'm' / 'avrgame.json', ['game_pkg', 'avrgame.json'], self.tmp / 'o.avrgame')
        self.assertIn('avrgame.json', '\n'.join(ctx.exception.problems))

    def test_read_describes_the_package_without_extracting(self):
        packed = self.pack()
        pkg = avrgame.read(self.tmp / 'out.avrgame')
        self.assertEqual((pkg.id, pkg.version, pkg.sha256), ('hello', '0.1.0', packed.sha256))
        self.assertEqual(pkg.size, (self.tmp / 'out.avrgame').stat().st_size)
        self.assertEqual(pkg.game['id'], 'hello')
        self.assertEqual(pkg.manifest['server']['args'], ['-m', 'game_pkg'])
        sizes = {f.path: f.size for f in pkg.files}
        self.assertEqual(sizes['game_pkg/web/app.js'], len(BASE_FILES['game_pkg/web/app.js']))
        self.assertEqual(pkg.total_bytes, sum(sizes.values()))
        self.assertIs(avrgame.inspect, avrgame.read)
        self.assertEqual([p.name for p in self.tmp.iterdir() if p.is_dir() and p.name != 'src'], [])

    def test_extract_round_trips_bytes_and_uses_fixed_modes(self):
        root = self.make_tree()
        self.pack(root)
        dest = self.tmp / 'unpacked'
        pkg = avrgame.extract(self.tmp / 'out.avrgame', dest)
        for f in pkg.files:
            src = root / f.path
            self.assertEqual((dest / f.path).read_bytes(), src.read_bytes(), f.path)
        self.assertEqual(sorted(p.relative_to(dest).as_posix() for p in dest.rglob('*') if p.is_file()),
                         sorted(f.path for f in pkg.files))
        if os.name == 'posix':
            self.assertEqual(stat.S_IMODE((dest / 'game_pkg/__main__.py').stat().st_mode), 0o644)
            self.assertEqual(stat.S_IMODE((dest / 'game_pkg').stat().st_mode), 0o755)
        again = self.tmp / 'empty'
        again.mkdir()
        avrgame.extract(self.tmp / 'out.avrgame', again)             # an empty directory is fine

    def test_extract_refuses_a_destination_that_is_not_new_or_empty(self):
        self.pack()
        full = self.tmp / 'full'
        full.mkdir()
        (full / 'keep.txt').write_bytes(b'mine')
        with self.assertRaises(avrgame.Refused):
            avrgame.extract(self.tmp / 'out.avrgame', full)
        self.assertEqual((full / 'keep.txt').read_bytes(), b'mine')
        afile = self.tmp / 'afile'
        afile.write_bytes(b'x')
        with self.assertRaises(avrgame.Refused):
            avrgame.extract(self.tmp / 'out.avrgame', afile)

    def test_extract_never_follows_a_symlinked_destination(self):
        self.pack()
        real = self.tmp / 'real'
        real.mkdir()
        try:
            os.symlink(real, self.tmp / 'link', target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError):
            self.skipTest('this host cannot create symbolic links')
        with self.assertRaises(avrgame.Refused):
            avrgame.extract(self.tmp / 'out.avrgame', self.tmp / 'link')
        self.assertEqual(list(real.iterdir()), [])

    def test_extract_removes_what_it_wrote_when_it_fails_midway(self):
        self.pack()
        dest = self.tmp / 'unpacked'
        real_open = archive.os.open
        calls = []

        def flaky(path, *a, **k):
            calls.append(path)
            if len(calls) == 3:
                raise OSError('disk full')
            return real_open(path, *a, **k)
        with mock.patch.object(archive.os, 'open', flaky):
            with self.assertRaises(avrgame.Refused):
                avrgame.extract(self.tmp / 'out.avrgame', dest)
        self.assertFalse(dest.exists())

    def test_a_missing_or_non_zip_file_is_a_refusal_not_a_crash(self):
        with self.assertRaises(avrgame.Refused):
            avrgame.read(self.tmp / 'nope.avrgame')
        with self.assertRaises(avrgame.Refused):
            avrgame.read(self.tmp)
        self.refused(b'this is not a zip', 'not a valid ZIP')
        good = make_zip()
        self.refused(good[:len(good) // 2], 'not a valid ZIP')

    def test_the_recipe_is_strict_and_stays_inside_its_root(self):
        root = self.make_tree()
        recipe = root / 'avrgame.build.json'

        def write(**over):
            doc = {'recipe': avrgame.RECIPE_FORMAT, 'manifest': 'avrgame.json', 'root': '.', 'include': ['game_pkg']}
            doc.update(over)
            recipe.write_text(json.dumps(doc))
        write()
        r = avrgame.load_recipe(recipe)
        self.assertEqual(r.include, ('game_pkg',))
        for over in ({'extra': 1}, {'recipe': 'avrana.avrgame-build/v0'}, {'include': []}, {'include': ['../x']},
                     {'include': ['/abs']}, {'include': ['a\\b']}, {'include': [1]}, {'include': 'game_pkg'},
                     {'root': '/abs'}, {'manifest': 'C:/m.json'}, {'root': 5}):
            write(**over)
            with self.assertRaises(avrgame.Refused, msg=over):
                avrgame.load_recipe(recipe)
        recipe.write_text('{"recipe": "x", "recipe": "y"}')
        with self.assertRaises(avrgame.Refused):
            avrgame.load_recipe(recipe)

    def test_a_recipe_can_reach_a_root_above_it_and_packs_like_pack(self):
        root = self.make_tree()
        (root / 'sub').mkdir()
        (root / 'avrgame.json').replace(root / 'sub' / 'avrgame.json')
        (root / 'avrgame.build.json').unlink()
        (root / 'sub' / 'avrgame.build.json').write_text(json.dumps({
            'recipe': avrgame.RECIPE_FORMAT, 'manifest': 'avrgame.json', 'root': '..',
            'include': ['game_pkg', 'shared']}))
        via = avrgame.pack_recipe(root / 'sub' / 'avrgame.build.json', self.tmp / 'r.avrgame')
        direct = avrgame.pack(root, root / 'sub' / 'avrgame.json', ['game_pkg', 'shared'], self.tmp / 'd.avrgame')
        self.assertEqual(via.sha256, direct.sha256)
        self.assertEqual(avrgame.validate_recipe(root / 'sub' / 'avrgame.build.json').sha256, via.sha256)


class HostileArchiveTests(Tmp):
    """Each case is a hand-made ZIP; the library must refuse it with an actionable message."""

    def test_the_hand_made_baseline_is_valid(self):
        pkg = avrgame.read(self.write_zip(make_zip()))
        self.assertEqual(pkg.id, 'hello')
        pkg = avrgame.read(self.write_zip(make_zip(method=zipfile.ZIP_STORED), 'stored.avrgame'))
        self.assertEqual(pkg.id, 'hello')

    def test_unsafe_names(self):
        long_ok = 'd/' * 15 + 'f.txt'                     # 16 segments
        cases = {
            'absolute': ('/etc/passwd', 'absolute path'),
            'drive letter': ('C:/evil.txt', 'drive letter'),
            'backslash': ('game_pkg\\evil.py', 'backslash'),
            'dotdot': ('game_pkg/../../evil.py', '".." segments'),
            'dotdot first': ('../evil.py', '".." segments'),
            'empty segment': ('game_pkg//evil.py', 'empty path segment'),
            'dot segment': ('game_pkg/./evil.py', '"." and ".." segments'),
            'nul': ('game_pkg/evil\x00.py', 'control or NUL'),
            'control': ('game_pkg/ev\x1bil.py', 'control or NUL'),
            'newline': ('game_pkg/ev\nil.py', 'control or NUL'),
            'too long': ('a' * 201, 'longer than 200'),
            'too deep': ('d/' * 16 + 'f.txt', 'deeper than 16'),
            'unicode': ('game_pkg/caf\u00e9.py', 'only ASCII'),
            'space': ('game_pkg/a b.py', 'only ASCII'),
            'dotfile': ('game_pkg/.hidden', 'hidden'),
            'device CON': ('game_pkg/CON', 'reserved device name'),
            'device nul.txt': ('game_pkg/nul.txt', 'reserved device name'),
            'device aux lower': ('game_pkg/aux.py', 'reserved device name'),
            'device COM1': ('game_pkg/Com1.txt', 'reserved device name'),
            'trailing dot': ('game_pkg/evil.', 'ends with'),
            'trailing space': ('game_pkg/evil ', 'ends with'),
            'colon stream': ('game_pkg/a:b', 'drive letter or ":"'),
        }
        for label, (name, expect) in cases.items():
            with self.subTest(label):
                self.refused(make_zip(extra=[(name, b'x')]), expect)
        avrgame.read(self.write_zip(make_zip(extra=[(long_ok, b'x')]), 'deep.avrgame'))

    def test_duplicates_and_case_collisions(self):
        self.refused(make_zip(extra=[('game_pkg/web/app.js', b'evil')]), 'duplicate name')
        self.refused(make_zip(extra=[('game_pkg/web/APP.js', b'evil')]), 'differs only by case')
        self.refused(make_zip(extra=[('Game_Pkg/x.py', b'evil')]), 'differs only by case')
        self.refused(make_zip(extra=[('game_pkg/web/app.js/x', b'evil')]), 'both a file and a directory')

    def test_links_special_files_and_mode_bits(self):
        def attr(kind, perm=0o644):
            return (kind | perm) << 16
        cases = {
            'symlink': (attr(stat.S_IFLNK, 0o777), 'only regular files'),
            'fifo': (attr(stat.S_IFIFO), 'only regular files'),
            'char device': (attr(stat.S_IFCHR), 'only regular files'),
            'block device': (attr(stat.S_IFBLK), 'only regular files'),
            'socket': (attr(stat.S_IFSOCK), 'only regular files'),
            'setuid': (attr(stat.S_IFREG, 0o4755), 'setuid'),
            'setgid': (attr(stat.S_IFREG, 0o2755), 'setuid'),
            'sticky': (attr(stat.S_IFREG, 0o1755), 'setuid'),
            'windows reparse point': (0x400, 'only regular files'),
        }
        for label, (a, expect) in cases.items():
            with self.subTest(label):
                self.refused(make_zip(extra=[('game_pkg/x', b'target', a)]), expect)
        # Ordinary Unix execute bits are fine: modes are not preserved on extract anyway.
        avrgame.read(self.write_zip(make_zip(extra=[('game_pkg/run.sh', b'x', attr(stat.S_IFREG, 0o755))])))

    def test_encrypted_entries_and_unsupported_compression(self):
        data = make_zip()
        self.refused(patch_central(data, 'game_pkg/__main__.py', 8, '<H', 1), 'encrypted')
        self.refused(patch_central(data, 'game_pkg/__main__.py', 8, '<H', 0x40), 'encrypted')
        self.refused(make_zip(method=zipfile.ZIP_BZIP2), 'compression method')
        self.refused(make_zip(method=zipfile.ZIP_LZMA), 'compression method')

    def test_bytecode_is_refused(self):
        self.refused(make_zip(extra=[('game_pkg/mod.pyc', b'\0')]), 'bytecode')
        self.refused(make_zip(extra=[('game_pkg/__pycache__/mod.cpython-312.pyc', b'\0')]), 'bytecode')
        self.refused(make_zip(extra=[('game_pkg/__pycache__/notes.txt', b'\0')]), 'bytecode')

    def test_counts_and_sizes_are_limited(self):
        with mock.patch.object(common, 'MAX_FILES', 5):
            self.refused(make_zip(extra=[('f1', b'x'), ('f2', b'x')]), 'entries; at most 5')
        with mock.patch.object(common, 'MAX_FILE_BYTES', 100):
            self.refused(make_zip(extra=[('big.bin', b'x' * 101)]), 'at most 100')
        with mock.patch.object(common, 'MAX_TOTAL_BYTES', 3000):
            self.refused(make_zip(extra=[('a.bin', b'\0' * 2000), ('b.bin', b'\0' * 2000)]), 'at most 3000')
        data = make_zip()
        with mock.patch.object(common, 'MAX_ARCHIVE_BYTES', len(data) - 1):
            self.refused(data, 'larger than')

    def test_a_compression_bomb_is_refused_by_the_real_limits(self):
        big = bytes(15 * 1024 * 1024)                       # 15 MiB each, tiny once deflated
        data = make_zip(extra=[(f'bomb{i}.bin', big) for i in range(5)])     # 75 MiB > 64 MiB total
        self.assertLess(len(data), 1024 * 1024)
        self.refused(data, 'unpacked')
        self.refused(make_zip(extra=[('one.bin', bytes(common.MAX_FILE_BYTES + 1))]), 'a file may be at most')

    def test_limits_are_enforced_on_the_bytes_actually_read(self):
        data = make_zip(extra=[('z.bin', bytes(1024 * 1024))])
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            info = zf.getinfo('z.bin')
            with self.assertRaises(avrgame.Refused) as ctx:
                archive._stream(zf, info, 4096, 10 ** 9)                 # per-file limit
            self.assertIn('once unpacked', str(ctx.exception))
            with self.assertRaises(avrgame.Refused):
                archive._stream(zf, info, 10 ** 9, 4096)                 # total limit
            self.assertEqual(archive._stream(zf, info, 2 ** 21, 2 ** 21)[0], 1024 * 1024)
        # An archive whose headers lie about the size is refused, not trusted.
        lie = patch_central(data, 'z.bin', 24, '<I', 10)
        self.refused(lie, 'z.bin')
        huge = patch_central(data, 'z.bin', 24, '<I', 200 * 1024 * 1024)
        self.refused(huge, 'declares')

    def test_manifest_placement_and_size(self):
        self.refused(make_zip(with_manifest=False), 'missing at the archive root')
        nested = make_zip(with_manifest=False, extra=[('sub/avrgame.json', mjson())])
        self.assertIn('found only at', '\n'.join(self.refused(nested, 'missing at the archive root')))
        self.refused(make_zip(extra=[('avrgame.json', mjson())]), 'duplicate name')
        self.refused(make_zip(extra=[('AVRGAME.JSON', mjson())]), 'differs only by case')
        self.refused(make_zip(manifest=b' ' * (common.MAX_MANIFEST_BYTES + 1)), 'larger than')
        self.refused(make_zip(manifest=b'{"format": "a", "format": "b"}'), 'not strict JSON')
        self.refused(make_zip(manifest=b'[]'), 'JSON object')

    def test_manifest_problems_are_reported_together_from_an_archive(self):
        m = good_manifest(format='nope')
        m['server']['interpreter'] = '/bin/sh'
        problems = self.refused(make_zip(manifest=mjson(m)), 'format:')
        self.assertGreaterEqual(len(problems), 2)

    def test_the_client_bundle_must_exist_and_have_an_index(self):
        files = {k: v for k, v in BASE_FILES.items() if k != 'game_pkg/web/index.html'}
        self.refused(make_zip(files=files), 'game_pkg/web/index.html')
        m = good_manifest()
        m['client']['root'] = 'nowhere'
        self.refused(make_zip(manifest=mjson(m)), 'nowhere/index.html')

    def test_a_package_with_a_directory_entry_is_fine_and_a_bad_directory_entry_is_not(self):
        ok = make_zip(extra=[('game_pkg/web/', b'', (stat.S_IFDIR | 0o755) << 16 | 0x10)])
        avrgame.read(self.write_zip(ok))
        self.refused(make_zip(extra=[('game_pkg/../', b'', (stat.S_IFDIR | 0o755) << 16)]), '".." segments')
        self.refused(make_zip(extra=[('weird/', b'content', (stat.S_IFDIR | 0o755) << 16)]), 'directory with content')

    def test_extract_applies_the_same_refusals_and_creates_nothing(self):
        dest = self.tmp / 'dest'
        bad = self.write_zip(make_zip(extra=[('../evil.py', b'x')]))
        with self.assertRaises(avrgame.Refused):
            avrgame.extract(bad, dest)
        self.assertFalse(dest.exists())
        self.assertFalse((self.tmp.parent / 'evil.py').exists())

    def test_extract_never_writes_through_a_link_planted_in_the_destination(self):
        # The destination is required to be empty; a link appearing there mid-extraction (a race)
        # is still not followed.
        outside = self.tmp / 'outside'
        outside.mkdir()
        dest = self.tmp / 'dest'
        good = self.write_zip(make_zip())
        real_mkdir = os.mkdir

        def plant(path, *a, **k):
            real_mkdir(path, *a, **k)
            if os.path.basename(path) == 'game_pkg':
                os.rmdir(path)
                try:
                    os.symlink(outside, path, target_is_directory=True)
                except (OSError, NotImplementedError, AttributeError):
                    raise unittest.SkipTest('this host cannot create symbolic links')
        with mock.patch.object(archive.os, 'mkdir', plant):
            with self.assertRaises(avrgame.Refused):
                avrgame.extract(good, dest)
        self.assertEqual(list(outside.iterdir()), [])


class CommandLineTests(Tmp):
    def run_cli(self, *args, cwd=None):
        env = {**os.environ, 'PYTHONPATH': str(REPO_ROOT)}
        return subprocess.run([sys.executable, '-m', 'avrana.avrgame', *map(str, args)], capture_output=True,
                              text=True, cwd=cwd or self.tmp, env=env, timeout=120)

    def test_validate_pack_and_inspect_exit_codes_and_output(self):
        root = self.make_tree()
        done = self.run_cli('validate', root)
        self.assertEqual(done.returncode, 0, done.stderr)
        for word in ('id: hello', 'version: 0.1.0', 'files: ', 'bytes: ', 'sha256: '):
            self.assertIn(word, done.stdout)
        out = self.tmp / 'game.avrgame'
        done = self.run_cli('pack', root / 'avrgame.build.json', '--out', out)
        self.assertEqual(done.returncode, 0, done.stderr)
        pkg = avrgame.read(out)
        self.assertIn(pkg.sha256, done.stdout)
        done = self.run_cli('validate', out)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(pkg.sha256, done.stdout)
        done = self.run_cli('inspect', out)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('game_pkg/web/index.html', done.stdout)
        done = self.run_cli('inspect', out, '--json')
        info = json.loads(done.stdout)
        self.assertEqual((info['id'], info['version'], info['sha256']), ('hello', '0.1.0', pkg.sha256))
        self.assertEqual({f['path'] for f in info['files']}, {f.path for f in pkg.files})

    def test_pack_defaults_to_id_version_in_the_current_directory(self):
        root = self.make_tree()
        done = self.run_cli('pack', root / 'avrgame.build.json')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue((self.tmp / 'hello-0.1.0.avrgame').is_file())
        first = (self.tmp / 'hello-0.1.0.avrgame').read_bytes()
        self.assertEqual(self.run_cli('pack', root / 'avrgame.build.json', '--store', '--out', 's.avrgame').returncode, 0)
        self.assertNotEqual((self.tmp / 's.avrgame').read_bytes(), first)

    def test_a_refused_package_exits_1_with_one_problem_per_line_on_stderr(self):
        bad = self.write_zip(make_zip(extra=[('../evil.py', b'x'), ('/abs', b'x')]))
        done = self.run_cli('validate', bad)
        self.assertEqual(done.returncode, 1)
        self.assertEqual(done.stdout, '')
        self.assertEqual(len(done.stderr.strip().splitlines()), 2)
        for sub in ('validate', 'inspect'):
            self.assertEqual(self.run_cli(sub, self.tmp / 'missing.avrgame').returncode, 1)
        root = self.make_tree()
        (root / 'avrgame.json').write_bytes(mjson(good_manifest(format='nope')))
        done = self.run_cli('validate', root)
        self.assertEqual(done.returncode, 1)
        self.assertIn('format:', done.stderr)
        self.assertEqual(self.run_cli('pack', root / 'avrgame.build.json').returncode, 1)
        self.assertEqual(list(self.tmp.glob('*.avrgame')), [bad])

    def test_bad_usage_exits_2(self):
        self.assertEqual(self.run_cli().returncode, 2)
        self.assertEqual(self.run_cli('frobnicate').returncode, 2)
        self.assertEqual(self.run_cli('validate').returncode, 2)
        self.assertEqual(self.run_cli('pack', 'a', '--bogus').returncode, 2)


class ModuleStanceTests(unittest.TestCase):
    def test_modules_say_experimental_and_never_claim_stability(self):
        for path in (REPO_ROOT / 'avrana' / 'avrgame').glob('*.py'):
            text = path.read_text(encoding='utf-8')
            self.assertNotIn('avrana.avrgame/v0', text, path.name)
            self.assertNotRegex(text.lower(), r'\b(is|are) (stable|frozen)\b', path.name)
        init = (REPO_ROOT / 'avrana' / 'avrgame' / '__init__.py').read_text(encoding='utf-8')
        self.assertIn('EXPERIMENTAL', init)
        self.assertIn('NOT an SDK', init)
        self.assertEqual(avrgame.FORMAT, 'avrana.avrgame/experimental.1')

    def test_party_code_has_no_title_specific_cases(self):
        # Code, not prose: identifiers and string literals outside docstrings.
        for path in (REPO_ROOT / 'avrana' / 'avrgame').glob('*.py'):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            docs = {id(n.body[0].value) for n in ast.walk(tree)
                    if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                    and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
            words = [n.value.lower() for n in ast.walk(tree)
                     if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]
            words += [n.id.lower() for n in ast.walk(tree) if isinstance(n, ast.Name)]
            for title in ('hello', 'checkers', 'bluff', 'expo', 'spades'):
                self.assertFalse([w for w in words if title in w], f'{path.name} mentions {title}')

    def test_manifest_module_exposes_the_validator_the_installer_uses(self):
        self.assertIs(avrgame.validate_manifest, manifest_module.validate_manifest)


if __name__ == '__main__':
    unittest.main()
