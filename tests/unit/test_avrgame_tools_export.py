"""The EXPERIMENTAL `.avrgame` developer tools export (AVR-59): tools/build_avrgame_tools.py.

    python3 -m unittest discover -s tests/unit -p test_avrgame_tools_export.py

The export is a zip of the validator and packer with exactly the files they need, so an outside
developer can validate and pack a game without a checkout. These tests pin what is in it (an explicit
allowlist), that it builds the same bytes anywhere, that its tool behaves exactly like this repository's
(packed bytes and refusals), and that nothing platform-, key- or install-related leaks into it. They run
the exported tool in a subprocess with a clean path, so an in-repo change that makes the packer import
something new fails here (and in the build itself) until the export is deliberately extended.
"""
import ast
import hashlib
import importlib.util
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from avrana import REPO_ROOT, CONTRACTS_DIR
from avrana import avrgame
from avrana.party import protocol, result

from test_avrgame_package import BASE_FILES, good_manifest, make_zip, mjson

spec = importlib.util.spec_from_file_location('build_avrgame_tools', REPO_ROOT / 'tools/build_avrgame_tools.py')
tools = importlib.util.module_from_spec(spec)
sys.modules['build_avrgame_tools'] = tools
spec.loader.exec_module(tools)

TOP = tools.NAME
COMMIT = '0123456789abcdef0123456789abcdef01234567'

# The explicit allowlist: the export holds exactly these files and no other.
ALLOWED = {
    'AVRGAME-PACKAGE-FORMAT.md', 'MANIFEST.json', 'NOTICE.md', 'README.md',
    'avrana/__init__.py',
    'avrana/avrgame/__init__.py', 'avrana/avrgame/__main__.py', 'avrana/avrgame/archive.py',
    'avrana/avrgame/build.py', 'avrana/avrgame/common.py', 'avrana/avrgame/manifest.py',
    'avrana/contracts/__init__.py', 'avrana/contracts/game.py', 'avrana/contracts/party_games.py',
    'avrana/contracts/strictjson.py', 'avrana/contracts/vocabulary.py',
    'avrana/party/__init__.py', 'avrana/party/protocol.py', 'avrana/party/result.py',
    'contracts/capabilities.v0.json', 'contracts/party-games.v0.json',
}
ALLOWED_MODULES = {
    'avrana', 'avrana.avrgame', 'avrana.avrgame.__main__', 'avrana.avrgame.archive', 'avrana.avrgame.build',
    'avrana.avrgame.common', 'avrana.avrgame.manifest', 'avrana.contracts', 'avrana.contracts.game',
    'avrana.contracts.party_games', 'avrana.contracts.strictjson', 'avrana.contracts.vocabulary',
    'avrana.party', 'avrana.party.protocol', 'avrana.party.result',
}

TRACE = '''
import contextlib, io, json, sys
from avrana.avrgame import __main__ as m
codes = []
for argv in json.loads(sys.argv[1]):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        codes.append(m.main(argv))
print(json.dumps({"codes": codes, "modules": sorted(n for n in sys.modules if n == "avrana" or n.startswith("avrana."))}))
'''


def lf(path):
    return path.read_bytes().replace(b'\r\n', b'\n')


def read_zip(data_or_path):
    with zipfile.ZipFile(data_or_path if isinstance(data_or_path, Path) else io.BytesIO(data_or_path)) as z:
        return {i.filename: z.read(i) for i in z.infolist()}, z.infolist()


def copy_inputs(dest, crlf=False):
    """The repository files the export is made from, copied into `dest` (optionally with CRLF line endings)."""
    for rel in tools.input_paths():
        data = (REPO_ROOT / rel).read_bytes().replace(b'\r\n', b'\n')
        if crlf:
            data = data.replace(b'\n', b'\r\n')
        target = Path(dest) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return Path(dest)


clean_env = tools.clean_env          # PYTHONPATH and friends removed; optionally set to one directory


class Built(unittest.TestCase):
    """One build of this commit's export, unpacked once, shared by the tests that only read it."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._tmp.name)
        cls.data = tools.build_bytes(REPO_ROOT, commit=COMMIT, dirty=False)
        cls.zip_path = cls.tmp / tools.ZIP_NAME
        cls.zip_path.write_bytes(cls.data)
        cls.zip_path.with_name(cls.zip_path.name + '.sha256').write_bytes(
            f'{hashlib.sha256(cls.data).hexdigest()}  {tools.ZIP_NAME}\n'.encode('ascii'))
        cls.root = tools.unpack(cls.zip_path, cls.tmp / 'unpacked')
        cls.files, cls.infos = read_zip(cls.data)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def names(self):
        return {n[len(TOP) + 1:] for n in self.files}

    def run_exported(self, args, cwd=None, env=None):
        return subprocess.run([sys.executable, '-m', 'avrana.avrgame', *map(str, args)], cwd=str(cwd or self.root),
                              env=env or clean_env(), capture_output=True, text=True, timeout=180)

    def run_in_repo(self, args, cwd):
        return subprocess.run([sys.executable, '-m', 'avrana.avrgame', *map(str, args)], cwd=str(cwd),
                              env=clean_env(REPO_ROOT), capture_output=True, text=True, timeout=180)


class ContentsTests(Built):
    def test_the_export_holds_exactly_the_allowlist(self):
        self.assertEqual(self.names(), ALLOWED)
        self.assertEqual({n.split('/')[0] for n in self.files}, {TOP})

    def test_the_modules_the_tool_really_loads_are_exactly_the_allowlist_and_come_from_the_export(self):
        tmp = self.tmp / 'trace'
        tmp.mkdir()
        recipe = self.fixture(tmp)
        argvs = [['validate', str(recipe)], ['pack', str(recipe), '--out', str(tmp / 'a.avrgame')],
                 ['inspect', str(tmp / 'a.avrgame')], ['extract', str(tmp / 'a.avrgame'), str(tmp / 'x')]]
        done = subprocess.run([sys.executable, '-c', TRACE, json.dumps(argvs)], cwd=str(self.root), env=clean_env(),
                              capture_output=True, text=True, timeout=180)
        self.assertEqual(done.returncode, 0, done.stderr)
        seen = json.loads(done.stdout)
        self.assertEqual(seen['codes'], [0, 0, 0, 0])
        self.assertEqual(set(seen['modules']), ALLOWED_MODULES)

    def test_no_platform_ops_installer_key_or_test_material(self):
        for name in self.names():
            for banned in ('ops/', 'installed', 'appliance', 'sessions', 'service', 'core', 'nginx', 'deploy', 'tests/',
                           '.pem', '.key', '.env', 'id_rsa', 'catalog', 'web/', 'providers', 'identity'):
                self.assertNotIn(banned, name, name)
        for name, data in self.files.items():
            text = data.decode('utf-8')
            self.assertNotIn('PRIVATE KEY', text, name)
            self.assertNotRegex(text, r'(?m)^\s*(import|from)\s+(hmac|secrets)\b', name)

    def test_the_protocol_and_result_implementations_are_not_shipped_only_one_constant_each(self):
        for rel, constant, real in (('avrana/party/protocol.py', 'VERSION', protocol.VERSION),
                                    ('avrana/party/result.py', 'SCHEMA', result.SCHEMA)):
            text = self.files[f'{TOP}/{rel}'].decode('utf-8')
            body = [n for n in ast.parse(text).body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
            self.assertEqual(len(body), 1, rel)
            self.assertEqual(ast.literal_eval(body[0].value), real)
            self.assertLess(len(text), 600, rel)
            self.assertNotIn('hmac', text)

    def test_the_package_root_is_a_stand_in_that_only_names_the_contracts_directory(self):
        text = self.files[f'{TOP}/avrana/__init__.py'].decode('utf-8')
        self.assertIn("CONTRACTS_DIR = TOOLS_ROOT / 'contracts'", text)
        self.assertNotIn('WEB_DIR', text)

    def test_copied_files_are_the_repositorys_own_bytes_with_lf_line_endings(self):
        for rel in tools.COPIED:
            self.assertEqual(self.files[f'{TOP}/{rel}'], lf(REPO_ROOT / rel), rel)

    def test_every_file_has_its_hash_in_the_manifest_and_the_manifest_says_what_it_speaks(self):
        manifest = json.loads(self.files[f'{TOP}/MANIFEST.json'])
        self.assertEqual(set(manifest['files']), ALLOWED - {'MANIFEST.json'})
        for name, info in manifest['files'].items():
            data = self.files[f'{TOP}/{name}']
            self.assertEqual((info['sha256'], info['bytes']), (hashlib.sha256(data).hexdigest(), len(data)), name)
        self.assertEqual(manifest['package_format'], avrgame.FORMAT)
        self.assertEqual(manifest['recipe_format'], avrgame.RECIPE_FORMAT)
        self.assertEqual({k: manifest['requires_spoken'][k] for k in ('session', 'bridge', 'result')},
                         {k: v[0] for k, v in avrgame.supported_requires().items()})
        self.assertEqual((manifest['source_commit'], manifest['source_dirty'], manifest['experimental']),
                         (COMMIT, False, True))
        self.assertEqual(manifest['tools_version'], 'experimental.1')

    def test_the_documents_are_complete_experimental_and_say_what_is_open(self):
        readme = self.files[f'{TOP}/README.md'].decode('utf-8')
        notice = self.files[f'{TOP}/NOTICE.md'].decode('utf-8')
        snapshot = self.files[f'{TOP}/AVRGAME-PACKAGE-FORMAT.md'].decode('utf-8')
        for name, text in (('README', readme), ('NOTICE', notice), ('snapshot', snapshot)):
            self.assertNotIn('{{', text, name)
            self.assertIn('EXPERIMENTAL', text.upper(), name)
        plain = re.sub(r'[\s*]+', ' ', readme)
        for phrase in ('no compatibility promise', 'no signing', 'not trusted', 'does not install', 'python3'):
            self.assertIn(phrase, plain)
        self.assertIn('open owner decision', notice)
        for word in ('python3', 'persistent_storage', str(avrgame.MAX_FILES), avrgame.FORMAT):
            self.assertIn(word, readme)
        for interpreter in avrgame.INTERPRETERS:
            self.assertIn(f'`{interpreter}`', readme)
        self.assertIn('Snapshot', snapshot)
        self.assertIn(COMMIT, snapshot)
        # no markdown link into the repository: only http(s) links, if any
        for target in re.findall(r'\]\(([^)\s]*)\)', readme + snapshot + notice):
            self.assertRegex(target, r'^https?://')

    def fixture(self, dest):
        common = tools.constants((self.root / 'avrana/avrgame/common.py').read_text(encoding='utf-8'))
        requires = {k: v[0] for k, v in avrgame.supported_requires().items()}
        return tools.fixture_game(Path(dest) / 'game', {'format': common['FORMAT'], 'recipe': common['RECIPE_FORMAT'],
                                                         'requires': requires})


class ReproducibilityTests(unittest.TestCase):
    def test_two_builds_are_identical_and_the_zip_is_sorted_stored_and_fixed(self):
        a = tools.build_bytes(REPO_ROOT, commit=COMMIT, dirty=False)
        b = tools.build_bytes(REPO_ROOT, commit=COMMIT, dirty=False)
        self.assertEqual(a, b)
        _, infos = read_zip(a)
        names = [i.filename for i in infos]
        self.assertEqual(names, sorted(names))
        for i in infos:
            self.assertEqual(i.date_time, (1980, 1, 1, 0, 0, 0))
            self.assertEqual(i.compress_type, zipfile.ZIP_STORED)
            self.assertEqual(i.create_system, 3)
            self.assertEqual(i.external_attr >> 16, 0o100644)
            self.assertFalse(i.filename.endswith('/'))
            self.assertNotIn(b'\r', read_zip(a)[0][i.filename], i.filename)

    def test_a_crlf_checkout_gives_the_same_bytes_as_an_lf_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            lf_tree = copy_inputs(Path(tmp) / 'lf')
            crlf_tree = copy_inputs(Path(tmp) / 'crlf', crlf=True)
            self.assertIn(b'\r\n', (crlf_tree / 'avrana/avrgame/common.py').read_bytes())
            a = tools.build_bytes(lf_tree, commit=COMMIT, dirty=False)
            b = tools.build_bytes(crlf_tree, commit=COMMIT, dirty=False)
            self.assertEqual(a, b)
            self.assertEqual(a, tools.build_bytes(REPO_ROOT, commit=COMMIT, dirty=False))

    def test_a_changed_source_changes_the_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = copy_inputs(tmp)
            path = tree / 'avrana/avrgame/common.py'
            path.write_bytes(path.read_bytes().replace(b'MAX_FILES = 2000', b'MAX_FILES = 2001'))
            self.assertNotEqual(tools.build_bytes(tree, commit=COMMIT, dirty=False),
                                tools.build_bytes(REPO_ROOT, commit=COMMIT, dirty=False))

    def test_the_commit_is_unknown_outside_a_repository_root_and_dirty_is_marked(self):
        if shutil.which('git') is None:
            self.skipTest('git is not installed')
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            outer = tmp / 'outer'
            outer.mkdir()
            git = lambda cwd, *a: subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@example.invalid',
                                                  '-c', 'commit.gpgsign=false', *a], cwd=str(cwd), capture_output=True, text=True)
            self.assertEqual(git(outer, 'init', '-q').returncode, 0)
            git(outer, 'commit', '-q', '--allow-empty', '-m', 'x')
            inner = copy_inputs(outer / 'sub' / 'tree')               # inside an UNRELATED enclosing repository
            self.assertEqual(tools.source_commit(inner), ('unknown', None))
            self.assertEqual(tools.source_commit(tmp / 'nowhere'), ('unknown', None))
            own = copy_inputs(tmp / 'own')
            self.assertEqual(git(own, 'init', '-q').returncode, 0)
            git(own, 'add', '-A')
            self.assertEqual(git(own, 'commit', '-q', '-m', 'inputs').returncode, 0)
            head = git(own, 'rev-parse', 'HEAD').stdout.strip()
            self.assertEqual(tools.source_commit(own), (head, False))
            (own / 'avrana/avrgame/common.py').write_bytes(b'# changed\n')
            self.assertEqual(tools.source_commit(own), (head, True))
            git(own, 'checkout', '-q', '--', '.')
            (own / 'tools/avrgame-tools').joinpath('extra.md.in').write_text('x')       # untracked, not an input: clean
            self.assertEqual(tools.source_commit(own), (head, False))


class SameBehaviourTests(Built):
    """The exported tool and this repository's tool give the same answers for the same input."""

    def setUp(self):
        self.work = self.tmp / self._testMethodName
        self.work.mkdir()

    def make_tree(self):
        root = self.work / 'src'
        for rel, data in {**BASE_FILES, 'shared/helper.py': b'X = 1\n'}.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        (root / 'avrgame.json').write_bytes(mjson())
        (root / 'avrgame.build.json').write_text(json.dumps({
            'recipe': avrgame.RECIPE_FORMAT, 'manifest': 'avrgame.json', 'root': '.', 'include': ['game_pkg', 'shared']}))
        return root

    def exported(self, args, cwd=None):
        return self.run_exported(args, cwd or self.work, clean_env(self.root))

    def test_packed_bytes_are_identical_stored_and_deflated(self):
        root = self.make_tree()
        recipe = root / 'avrgame.build.json'
        for extra in ((), ('--deflate',)):
            mine, theirs = self.work / 'mine.avrgame', self.work / 'theirs.avrgame'
            a = self.exported(['pack', recipe, '--out', mine, *extra])
            b = self.run_in_repo(['pack', recipe, '--out', theirs, *extra], self.work)
            self.assertEqual((a.returncode, b.returncode), (0, 0), a.stderr + b.stderr)
            self.assertEqual(mine.read_bytes(), theirs.read_bytes(), extra)
            self.assertEqual(a.stdout.replace(str(mine), '-'), b.stdout.replace(str(theirs), '-'))
        self.assertEqual(avrgame.read(mine).sha256, hashlib.sha256(mine.read_bytes()).hexdigest())

    def test_validate_inspect_and_extract_agree(self):
        recipe = self.make_tree() / 'avrgame.build.json'
        packed = self.work / 'p.avrgame'
        self.assertEqual(self.exported(['pack', recipe, '--out', packed]).returncode, 0)
        for args in (['validate', recipe], ['validate', recipe.parent], ['validate', packed], ['inspect', packed],
                     ['inspect', packed, '--json']):
            a, b = self.exported(args), self.run_in_repo(args, self.work)
            self.assertEqual((a.returncode, a.stdout, a.stderr), (b.returncode, b.stdout, b.stderr), args)
            self.assertEqual(a.returncode, 0, a.stderr)
        a = self.exported(['extract', packed, self.work / 'e1'])
        b = self.run_in_repo(['extract', packed, self.work / 'e2'], self.work)
        self.assertEqual((a.returncode, b.returncode), (0, 0))
        self.assertEqual(sorted(p.relative_to(self.work / 'e1').as_posix() for p in (self.work / 'e1').rglob('*')),
                         sorted(p.relative_to(self.work / 'e2').as_posix() for p in (self.work / 'e2').rglob('*')))

    def test_refusals_are_the_same_text_and_status(self):
        bad_manifest = good_manifest(format='avrana.avrgame/v9')
        reserved = good_manifest(signature='x')
        dup_keys = b'{"format": "a", "format": "b"}'
        cases = {
            'dotdot': make_zip(extra=[('../evil.py', b'x')]),
            'absolute': make_zip(extra=[('/abs', b'x')]),
            'backslash': make_zip(extra=[('a\\b.py', b'x')]),
            'bytecode': make_zip(extra=[('game_pkg/m.pyc', b'x')]),
            'key material': make_zip(extra=[('game_pkg/server.key', b'x')]),
            'symlink': make_zip(extra=[('game_pkg/link', b'x', 0o120777 << 16)]),
            'setuid': make_zip(extra=[('game_pkg/su', b'x', 0o104755 << 16)]),
            'no manifest': make_zip(with_manifest=False),
            'wrong format': make_zip(manifest=mjson(bad_manifest)),
            'reserved key': make_zip(manifest=mjson(reserved)),
            'duplicate json keys': make_zip(manifest=dup_keys),
            'missing module': make_zip(files={'game_pkg/web/index.html': b'x'}),
            'not a zip': b'this is not a zip file',
        }
        for label, data in cases.items():
            path = self.work / 'case.avrgame'
            path.write_bytes(data)
            for command in ('validate', 'inspect'):
                a, b = self.exported([command, path]), self.run_in_repo([command, path], self.work)
                self.assertEqual(b.returncode, 1, (label, b.stderr))
                self.assertNotEqual(b.stderr.strip(), '', label)
                self.assertEqual((a.returncode, a.stdout, a.stderr), (b.returncode, b.stdout, b.stderr), (label, command))

    def test_usage_errors_and_help_match(self):
        for args in ([], ['frobnicate'], ['validate'], ['pack', 'a', '--bogus'], ['--help'], ['pack', '--help']):
            a, b = self.exported(args), self.run_in_repo(args, self.work)
            self.assertEqual((a.returncode, a.stdout, a.stderr), (b.returncode, b.stdout, b.stderr), args)

    def test_the_export_speaks_the_same_requires_as_the_repository(self):
        code = 'import json, avrana.avrgame as a; print(json.dumps(a.supported_requires(), sort_keys=True))'
        a = subprocess.run([sys.executable, '-c', code], cwd=str(self.root), env=clean_env(), capture_output=True, text=True)
        b = subprocess.run([sys.executable, '-c', code], cwd=str(self.work), env=clean_env(REPO_ROOT), capture_output=True, text=True)
        self.assertEqual(a.stdout, b.stdout)
        self.assertEqual(json.loads(a.stdout)['bridge'], [json.loads((CONTRACTS_DIR / 'party-games.v0.json').read_text())['bridge']['protocol']])

    def test_from_another_working_directory_with_the_export_on_pythonpath(self):
        done = self.exported(['--help'], cwd=self.work)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('validate', done.stdout)


class ClosureCheckTests(unittest.TestCase):
    """The build refuses to produce an export that would not be self-contained."""

    def files(self):
        files, _ = tools.collect(REPO_ROOT, COMMIT)
        return {k: v for k, v in files.items() if k.endswith('.py')}

    def test_this_commit_is_self_contained(self):
        tools.check_closure(self.files(), REPO_ROOT)
        tools.check_syntax_floor(self.files())

    def refused(self, files, expect):
        with self.assertRaises(tools.ExportError) as ctx:
            tools.check_closure(files, REPO_ROOT)
        self.assertIn(expect, str(ctx.exception))

    def test_a_new_import_of_a_repository_module_is_refused_even_when_lazy(self):
        files = self.files()
        files['avrana/avrgame/manifest.py'] += b'\n\ndef extra():\n    from avrana.ops import install_game\n'
        self.refused(files, 'avrana.ops')
        files = self.files()
        files['avrana/avrgame/build.py'] += b'\n\ndef extra():\n    from avrana.avrgame import installed\n'
        self.refused(files, 'avrana.avrgame.installed')
        files = self.files()
        files['avrana/avrgame/build.py'] += b'\n\nfrom . import installed\n'
        self.refused(files, 'avrana.avrgame.installed')

    def test_reading_more_of_the_protocol_than_its_version_is_refused(self):
        files = self.files()
        files['avrana/avrgame/manifest.py'] += b'\n\ndef extra():\n    from avrana.party import protocol\n    return protocol.seal\n'
        self.refused(files, 'avrana.party.protocol.seal')
        files = self.files()
        files['avrana/avrgame/manifest.py'] += b'\n\nfrom avrana.party.result import validate\n'
        self.refused(files, 'avrana.party.result.validate')

    def test_a_third_party_import_is_refused(self):
        files = self.files()
        files['avrana/avrgame/common.py'] += b'\nimport requests\n'
        self.refused(files, 'requests')

    def test_the_build_fails_on_a_tree_whose_packer_needs_more(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = copy_inputs(tmp)
            path = tree / 'avrana/avrgame/archive.py'
            path.write_bytes(path.read_bytes() + b'\n\ndef more():\n    from avrana.party import sessions\n')
            with self.assertRaises(tools.ExportError):
                tools.build_bytes(tree, commit=COMMIT, dirty=False)


class VerificationTests(Built):
    def test_the_self_verification_passes_on_a_good_export(self):
        self.assertEqual(tools.verify(self.zip_path), [])

    def test_a_file_changed_after_the_build_is_found(self):
        files, _ = read_zip(self.data)
        files[f'{TOP}/avrana/avrgame/common.py'] += b'\n# tampered\n'
        bad = self.tmp / 'bad' / tools.ZIP_NAME
        bad.parent.mkdir()
        with zipfile.ZipFile(bad, 'w') as z:
            for name, data in sorted(files.items()):
                info = zipfile.ZipInfo(name, tools.FIXED_TIME)
                info.compress_type = zipfile.ZIP_STORED
                z.writestr(info, data)
        bad.with_name(bad.name + '.sha256').write_text(f'{hashlib.sha256(bad.read_bytes()).hexdigest()}  {bad.name}\n')
        problems = tools.verify(bad)
        self.assertTrue(any('common.py' in p for p in problems), problems)

    def test_a_wrong_checksum_file_is_found(self):
        copy = self.tmp / 'sum' / tools.ZIP_NAME
        copy.parent.mkdir()
        copy.write_bytes(self.data)
        copy.with_name(copy.name + '.sha256').write_text('0' * 64 + f'  {copy.name}\n')
        self.assertTrue(tools.verify(copy))


if __name__ == '__main__':
    unittest.main()
