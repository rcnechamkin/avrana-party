"""The EXPERIMENTAL `.avrgame` developer tools export (AVR-59): tools/build_avrgame_tools.py.

    python3 -m unittest discover -s tests/unit -p test_avrgame_tools_export.py

The export is a zip of the validator and packer with exactly the files they need, so an outside
developer can validate and pack a game without a checkout. These tests pin what is in it (an explicit
allowlist), that it builds the same bytes anywhere, that its tool behaves exactly like this repository's
(packed bytes, refusals, extract), that the copied code is the repository's code (only comments and
docstrings that name internal material are removed, proven by comparing syntax trees), and that nothing
platform-, key- or install-related leaks into it (a deny-list content gate; every match is declared in the builder's ALLOW
table, NOTICE.md is generated from it, and a second, independently written pattern set checks the same files). They run the
exported tool in a subprocess with a clean path, so an in-repo change that makes the packer import something new
fails here (and in the build itself) until the export is deliberately extended.
"""
import ast
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from avrana import REPO_ROOT, CONTRACTS_DIR
from avrana import avrgame
from avrana.contracts import vocabulary
from avrana.party import protocol, result

from test_avrgame_package import BASE_FILES, good_manifest, make_zip, mjson, patch_central

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
    'avrana/avrgame/build.py', 'avrana/avrgame/common.py', 'avrana/avrgame/manifest.py', 'avrana/avrgame/node.py',
    'avrana/contracts/__init__.py', 'avrana/contracts/game.py', 'avrana/contracts/party_games.py',
    'avrana/contracts/strictjson.py', 'avrana/contracts/vocabulary.py',
    'avrana/party/__init__.py', 'avrana/party/protocol.py', 'avrana/party/result.py',
    'contracts/capabilities.v0.json',
}
ALLOWED_MODULES = {
    'avrana', 'avrana.avrgame', 'avrana.avrgame.__main__', 'avrana.avrgame.archive', 'avrana.avrgame.build',
    'avrana.avrgame.common', 'avrana.avrgame.manifest', 'avrana.avrgame.node', 'avrana.contracts', 'avrana.contracts.game',
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

clean_env = tools.clean_env          # PYTHONPATH and friends removed; optionally set to one directory


def lf(path):
    return path.read_bytes().replace(b'\r\n', b'\n')


def read_zip(data_or_path):
    with zipfile.ZipFile(data_or_path if isinstance(data_or_path, Path) else io.BytesIO(data_or_path)) as z:
        return {i.filename: z.read(i) for i in z.infolist()}, z.infolist()


def copy_inputs(dest, eol=b'\n'):
    """The repository files the export is made from, copied into `dest` (optionally with other line endings)."""
    for rel in tools.input_paths():
        data = (REPO_ROOT / rel).read_bytes().replace(b'\r\n', b'\n').replace(b'\n', eol)
        target = Path(dest) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return Path(dest)


def strip_docs(source):
    return ast.dump(tools.strip_docstrings(ast.parse(source)))


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
        cls.plain = {n[len(TOP) + 1:]: d for n, d in cls.files.items()}

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def names(self):
        return set(self.plain)

    def run_exported(self, args, cwd=None, env=None):
        return subprocess.run([sys.executable, '-m', 'avrana.avrgame', *map(str, args)], cwd=str(cwd or self.root),
                              env=env or clean_env(), capture_output=True, text=True, timeout=180)

    def run_in_repo(self, args, cwd):
        return subprocess.run([sys.executable, '-m', 'avrana.avrgame', *map(str, args)], cwd=str(cwd),
                              env=clean_env(REPO_ROOT), capture_output=True, text=True, timeout=180)

    def fixture(self, dest):
        common = tools.constants((self.root / 'avrana/avrgame/common.py').read_text(encoding='utf-8'))
        requires = {k: v[0] for k, v in avrgame.supported_requires().items()}
        return tools.fixture_game(Path(dest) / 'game', {'format': common['FORMAT'], 'recipe': common['RECIPE_FORMAT'],
                                                         'requires': requires})


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
        for name, data in self.plain.items():
            text = data.decode('utf-8')
            self.assertNotIn('PRIVATE KEY', text, name)
            self.assertNotRegex(text, r'(?m)^\s*(import|from)\s+(hmac|secrets)\b', name)

    def test_the_protocol_and_result_implementations_are_not_shipped_only_one_constant_each(self):
        for rel, constant, real in (('avrana/party/protocol.py', 'VERSION', protocol.VERSION),
                                    ('avrana/party/result.py', 'SCHEMA', result.SCHEMA)):
            text = self.plain[rel].decode('utf-8')
            body = [n for n in ast.parse(text).body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
            self.assertEqual(len(body), 1, rel)
            self.assertEqual(ast.literal_eval(body[0].value), real)
            self.assertLess(len(text), 600, rel)
            self.assertNotIn('hmac', text)

    def test_the_party_games_declaration_is_not_shipped_only_the_one_value_the_packer_reads(self):
        for name, data in self.plain.items():
            for leaked in ('reference_sha256', 'party_ended', '/internal/', 'keys_dir', 'AVRANA_PARTY_KEYS', 'vectors_sha256'):
                self.assertNotIn(leaked, data.decode('utf-8'), name)
        namespace = {}
        exec(compile(self.plain['avrana/contracts/party_games.py'].decode('utf-8'), 'party_games_shim', 'exec'), namespace)
        declared = json.loads((CONTRACTS_DIR / 'party-games.v0.json').read_text())
        self.assertEqual(namespace['load'](), {'bridge': {'protocol': declared['bridge']['protocol']}})
        self.assertEqual(sorted(n for n in namespace if not n.startswith('__')), ['_DECLARATION', 'load'])

    def test_the_capability_vocabulary_has_the_real_names_and_only_placeholders_for_the_rest(self):
        shipped = json.loads(self.plain['contracts/capabilities.v0.json'])
        real = json.loads((CONTRACTS_DIR / 'capabilities.v0.json').read_text(encoding='utf-8'))
        self.assertEqual(set(shipped), {'schema', 'note', 'device', 'runtime'})
        for scope in ('device', 'runtime'):
            self.assertEqual(list(shipped[scope]), list(real[scope]), scope)         # the names, in order
            for name, entry in shipped[scope].items():
                self.assertEqual(entry['label'], 'Placeholder label.')
                self.assertEqual(entry['summary'], 'Placeholder summary.')
                self.assertNotIn(real[scope][name]['summary'], json.dumps(shipped))
        loaded = vocabulary.load(self.root / 'contracts/capabilities.v0.json')        # the unchanged validator accepts it
        self.assertEqual(set(loaded.device), set(real['device']))
        self.assertEqual(set(loaded.runtime), set(real['runtime']))

    def test_the_readme_gives_every_capability_name_a_meaning_and_the_build_checks_it(self):
        shipped = json.loads(self.plain['contracts/capabilities.v0.json'])
        names = [n for scope in ('device', 'runtime') for n in shipped[scope]]
        readme = self.plain['README.md'].decode('utf-8')
        table = tools.capability_table(readme)
        self.assertEqual(sorted(table), sorted(names))
        for name, meaning in table.items():
            self.assertGreater(len(meaning), 20, name)
        self.assertIn('A `browser_native` presentation needs none of the `runtime.*`, `input.*` or `presentation.*` names',
                      re.sub(r'\s+', ' ', readme.replace('**', '')))
        tools.check_capability_table(readme, names)
        with self.assertRaises(tools.ExportError) as ctx:
            tools.check_capability_table(readme, names + ['brand.new'])
        self.assertIn('brand.new', str(ctx.exception))
        with self.assertRaises(tools.ExportError):
            tools.check_capability_table(readme.replace('| `touch` |', '| `tou` |'), names)
        # the meanings are written for this export, not copied from the in-repo vocabulary
        real = json.loads((CONTRACTS_DIR / 'capabilities.v0.json').read_text(encoding='utf-8'))
        for scope in ('device', 'runtime'):
            for name, entry in real[scope].items():
                for field in ('label', 'summary', 'missing'):
                    if isinstance(entry.get(field), str) and len(entry[field]) > 25:
                        self.assertNotIn(entry[field], readme, (name, field))

    def test_copied_code_is_the_repositorys_code_and_only_internal_comments_and_docstrings_are_gone(self):
        manifest = json.loads(self.plain['MANIFEST.json'])
        scrubbed = []
        for rel in tools.COPIED:
            original = lf(REPO_ROOT / rel).decode('utf-8')
            shipped = self.plain[rel].decode('utf-8')
            self.assertEqual(strip_docs(original), strip_docs(shipped), rel)             # identical code
            flags = manifest['files'][rel]
            self.assertEqual(flags['origin'], 'copied; code unchanged')
            self.assertEqual(flags['scrubbed'], shipped != original, rel)
            if shipped != original:
                scrubbed.append(rel)
            # no comment or docstring that survives is one the scrub should have removed
            for _, expr in tools._docstring_nodes(ast.parse(shipped)):
                self.assertFalse(tools.flagged(expr.value.value), rel)
        self.assertTrue(scrubbed)                                                         # something was scrubbed
        self.assertEqual(self.plain['avrana/avrgame/__main__.py'], lf(REPO_ROOT / 'avrana/avrgame/__main__.py'))
        self.assertEqual(self.plain['avrana/contracts/strictjson.py'], lf(REPO_ROOT / 'avrana/contracts/strictjson.py'))
        # the CLI help text comes from the module docstring of __main__, which is untouched
        self.assertIn('__doc__', self.plain['avrana/avrgame/__main__.py'].decode('utf-8'))

    def test_every_file_has_its_hash_in_the_manifest_and_the_manifest_says_what_it_speaks(self):
        manifest = json.loads(self.plain['MANIFEST.json'])
        self.assertEqual(set(manifest['files']), ALLOWED - {'MANIFEST.json'})
        for name, info in manifest['files'].items():
            data = self.plain[name]
            self.assertEqual((info['sha256'], info['bytes']), (hashlib.sha256(data).hexdigest(), len(data)), name)
            self.assertIn('origin', info)
        self.assertEqual(manifest['package_format'], avrgame.FORMAT)
        self.assertEqual(manifest['recipe_format'], avrgame.RECIPE_FORMAT)
        self.assertEqual(manifest['requires_spoken'], {k: v[0] for k, v in avrgame.supported_requires().items()})
        self.assertEqual(tools.SPEAKS, {'package_format': avrgame.FORMAT, 'recipe_format': avrgame.RECIPE_FORMAT,
                                        **manifest['requires_spoken']})
        self.assertEqual((manifest['source_commit'], manifest['source_dirty'], manifest['experimental']), (COMMIT, False, True))
        self.assertEqual(manifest['tools_version'], 'experimental.2')
        self.assertRegex(manifest['speaks_digest'], r'^[0-9a-f]{12}$')

    def test_the_documents_are_complete_experimental_and_say_what_is_open(self):
        readme = self.plain['README.md'].decode('utf-8')
        notice = self.plain['NOTICE.md'].decode('utf-8')
        snapshot = self.plain['AVRGAME-PACKAGE-FORMAT.md'].decode('utf-8')
        for name, text in (('README', readme), ('NOTICE', notice), ('snapshot', snapshot)):
            self.assertNotIn('{{', text, name)
            self.assertIn('EXPERIMENTAL', text.upper(), name)
        self.assertIn('What your game will run under on an appliance', readme)
        self.assertNotIn('<!--', readme)
        self.assertNotIn('provision_game', readme)
        plain = re.sub(r'[\s*]+', ' ', readme)
        for phrase in ('experimental and not deployed', 'provisional, may change', 'party_roster', 'No IP networking',
                       'socket-activated', 'read-only by ownership', 'filesystem sandbox directive',
                       'no compatibility promise', 'no signing', 'not trusted', 'does not install', 'python3',
                       'Reading the refusal messages', 'this appliance', 'these tools', 'code unchanged'):
            self.assertIn(phrase, plain)
        self.assertIn('open owner decision', notice)
        self.assertIn('Things this export reveals about the platform', notice)
        self.assertIn('`extract`', notice)
        for word in ('python3', 'persistent_storage', str(avrgame.MAX_FILES), avrgame.FORMAT):
            self.assertIn(word, readme)
        for interpreter in avrgame.INTERPRETERS:
            self.assertIn(f'`{interpreter}`', readme)
        self.assertIn('Snapshot', snapshot)
        self.assertIn(COMMIT, snapshot)
        self.assertNotIn('Freeze gates', snapshot)
        self.assertIn('not frozen; may change without notice', snapshot)
        for target in re.findall(r'\]\(([^)\s]*)\)', readme + snapshot + notice):
            self.assertRegex(target, r'^https?://')


# A second set of patterns, written out here on purpose and NOT imported from the builder: a gap in either list is
# caught by the other. Case-insensitive unless the pattern says otherwise.
BROAD = [(r'\bpi\b', re.I), (r'\bRPi\b', 0), (r'\bPi\d', 0), (r'\bavr-\d+', re.I), (r'\bADR[- ]?\d+', re.I),
         (r'h\.?264', re.I), (r'Debian', re.I), (r'systemd', re.I), (r'LoadCredential', 0), (r'DynamicUser', 0),
         (r'AVRANA_[A-Z_]+', 0), (r'Party Core', re.I), (r'provision-game', re.I), (r'hdmi', re.I), (r'hw_encoder', re.I),
         (r'net\.avrana', re.I), (r'\bTUF\b', 0), (r'arm64', re.I),
         # more: the platform's own vocabulary and the internal names the owner listed
         (r'install[-_ ]game', re.I), (r'lift_manifest|shared_video', re.I), (r'emulat', re.I), (r'arcade', re.I),
         (r'linux/(arm|amd)', re.I), (r'\b[0-9a-f]{40}\b', 0), (r'/usr/', 0), (r'libretro|retroarch|raspberry', re.I),
         (r'lan[ _]games', re.I), (r'\bbluff\b|\bexpo\b|spades|gauntlet|checkers', re.I), (r'webrtc|webgpu|wake_lock', re.I),
         (r'freeze|lane\b|party service', re.I), (r'owned by root|as root', re.I),
         # paths, addresses, units: as strong as the builder's own deny list on these
         (r'\.service\b|systemctl', re.I), (r'/etc/|/opt/|/var/|/run/', 0), (r'\b10\.\d+\.\d+\.\d+|192\.168\.', 0),
         (r'\.local\b|avrana\.net', re.I), (r'deploy/|\bops/|docs/|\btests/|\btools/', 0), (r'PRIVATE KEY', 0),
         (r'cnechamkin|BEACNpool', re.I)]


class ContentGateTests(Built):
    def covered(self, path, line, span):
        """Written here, not shared with the builder: the match must lie inside a declared term (or span) of an entry
        for this file, on a line that entry names."""
        for entry in tools.ALLOW:
            if path not in entry['files'] or not re.search(entry['line'], line):
                continue
            words = [re.escape(t) for t in entry['terms']] + list(entry.get('spans', ()))
            for word in words:
                for found in re.finditer(word, line, re.I):
                    if found.start() <= span[0] and span[1] <= found.end():
                        return True
        return False

    def test_the_shipped_text_matches_no_pattern_except_the_declared_places(self):
        problems, used = tools.content_gate(self.plain, skip=('NOTICE.md',))
        self.assertEqual(problems, [])
        required = {i for i, entry in enumerate(tools.ALLOW) if not entry.get('optional')}
        self.assertLessEqual(required, used)                               # no stale declaration
        self.assertEqual(tools.unseen_terms(self.plain), [])

    def test_a_second_independent_and_broader_pattern_set_finds_nothing_outside_the_declared_places(self):
        found = 0
        for path, data in sorted(self.plain.items()):
            if path == 'NOTICE.md':
                continue                                                   # it is the declaration itself
            for number, line in enumerate(data.decode('utf-8').splitlines(), 1):
                for source, flags in BROAD:
                    for match in re.finditer(source, line, flags):
                        found += 1
                        self.assertTrue(self.covered(path, line, match.span()),
                                        f'{path}:{number} {source!r}: {line.strip()[:100]}')
        self.assertGreater(found, 20)                                      # the patterns do find the declared places

    def test_a_declaration_covers_only_the_matched_text_not_the_rest_of_its_line(self):
        line = 'run install-game; it reads /etc/avrana/keys on the Pi, AVR-12, 10.0.0.142'
        problems, _ = tools.content_gate({'README.md': line.encode()})
        self.assertTrue(problems)
        for needle in ('/etc/', 'Pi', 'AVR-12', '10.0.0.142'):
            self.assertTrue(any(needle in p for p in problems), (needle, problems))
        self.assertFalse(any('install-game' in p.split('): ')[0] for p in problems))        # the declared term itself passes
        self.assertEqual(tools.content_gate({'README.md': b'run install-game; done'})[1], {0})
        for match in re.finditer('install-game|/etc/|Pi|AVR-12|10[.]0[.]0[.]142', line):
            expected = match.group() == 'install-game'
            self.assertEqual(self.covered('README.md', line, match.span()), expected, match.group())
        # a declared word cannot hide a longer undeclared one (RetroArch is only declared inside `runtime.retroarch`)
        self.assertTrue(tools.content_gate({'README.md': b'`runtime.retroarch` runs RetroArch'})[0])

    def test_the_unit_claims_of_the_readme_are_tied_to_the_unit_text(self):
        units = tools.unit_texts(REPO_ROOT)
        tools.check_unit_claims(units)
        for bad in (dict(units, COMMUNITY_UNIT=units['COMMUNITY_UNIT'] + 'SystemCallFilter=@system-service\n'),
                    dict(units, COMMUNITY_UNIT=units['COMMUNITY_UNIT'].replace('PrivateNetwork=yes\n', '')),
                    dict(units, COMMUNITY_UNIT=units['COMMUNITY_UNIT'].replace('CapabilityBoundingSet=\n', '')),
                    dict(units, COMMUNITY_UNIT=units['COMMUNITY_UNIT'] + 'ProtectSystem=strict\n'),
                    dict(units, NO_STATE='StateDirectory=party\n')):
            with self.assertRaises(tools.ExportError):
                tools.check_unit_claims(bad)
        with tempfile.TemporaryDirectory() as tmp:                      # and any change of the text moves the digest
            tree = copy_inputs(tmp)
            path = tree / 'avrana/ops/provision_game.py'
            path.write_bytes(path.read_bytes().replace(b"'ProtectClock=yes\\n'", b"'ProtectClock=no\\n'"))
            with self.assertRaises(tools.ExportError) as ctx:
                tools.build_bytes(tree, commit=COMMIT, dirty=False)
            self.assertIn('TOOLS_REVISION', str(ctx.exception))

    def test_the_snapshot_has_no_lane_bookkeeping_and_notice_names_the_run_time_conditions(self):
        snapshot = self.plain['AVRGAME-PACKAGE-FORMAT.md'].decode('utf-8')
        self.assertNotRegex(snapshot, r'(?i)\blanes?\b')
        self.assertIn("the appliance owner's installer stages it", snapshot)
        notice = re.sub(r'\s+', ' ', self.plain['NOTICE.md'].decode('utf-8'))
        for phrase in ('throwaway unprivileged identity with its own key', "Party's internal socket", 'private `/tmp`',
                       '`party_roster`', 'What your game will run under on an appliance', 'separately written set'):
            self.assertIn(phrase, notice)
        self.assertNotIn('broader', notice)

    def test_every_declared_term_occurs_in_a_shipped_file_and_is_printed_in_notice(self):
        notice = self.plain['NOTICE.md'].decode('utf-8')
        others = {n: d.decode('utf-8') for n, d in self.plain.items() if n != 'NOTICE.md'}
        for entry in tools.ALLOW:
            self.assertGreater(len(entry['reason']), 20)
            for name in entry['files']:
                self.assertIn(name, ALLOWED)
            self.assertIn(entry['describe'], notice)
            for term in entry['terms']:
                self.assertTrue(any(term in others[name] for name in entry['files']), (entry['describe'][:40], term))
                self.assertIn(f'`{term}`', notice)
        # everything the owner listed as shipping is named in NOTICE (read from here, not from the builder)
        for term in ('install-game', 'run by the appliance owner as root', 'home', 'party', 'admin', 'shared', 'diag', 'api',
                     'emulated', 'arcade', 'emulator_profile', 'emulator_slot', 'hw_encoder', 'host_rendering', 'hdmi',
                     'linux/arm64', 'linux/amd64', 'webrtc', 'video.h264', 'presentation.shared_stream',
                     'presentation.personal_viewport.crop', 'presentation.tv', 'input.virtual_gamepad', 'wake_lock', 'webgpu',
                     'lift_manifest_v0', 'shared_video', 'TUF', 'net.avrana.example', 'source_commit', 'deny list',
                     'no system-call filter', 'no disk quota', 'world-readable', 'file descriptor 3', 'no IP networking'):
            self.assertIn(term, notice)
        self.assertNotIn('found only', notice)
        self.assertIn('not a proof', notice)

    def test_notice_lists_a_term_only_because_a_declaration_exists_and_the_gate_fails_without_one(self):
        with mock.patch.object(tools, 'ALLOW', tools.ALLOW[:-2]):
            problems, _ = tools.content_gate(self.plain, skip=('NOTICE.md',))
        self.assertTrue(any('net.avrana' in p for p in problems) or any('TUF' in p for p in problems), problems)
        stale = dict(files=('README.md',), line='this line is in no file', terms=(), describe='x', reason='y' * 30)
        with mock.patch.object(tools, 'ALLOW', (*tools.ALLOW, stale)):
            with self.assertRaises(tools.ExportError):
                tools.build_bytes(REPO_ROOT, commit=COMMIT, dirty=False)
        gone = dict(tools.ALLOW[-3], terms=('a term that is nowhere',))
        with mock.patch.object(tools, 'ALLOW', (*tools.ALLOW[:-3], gone, *tools.ALLOW[-2:])):
            self.assertTrue(tools.unseen_terms(self.plain))

    def test_each_denied_kind_of_text_is_caught(self):
        samples = ['AVR-123', 'avr-12', 'ADR 0016', 'ADR-0016', 'the BLUFF game', 'Spades', 'Gauntlet', 'Checkers', 'EXPO',
                   'RetroArch', 'libretro', 'LAN Games', 'Raspberry Pi', 'on the Pi now', 'H.264', '/etc/passwd', '/opt/games',
                   '/var/lib', '/run/x.sock', '10.0.0.142', '192.168.1.1', 'party.local', 'party.avrana.net', 'docs/design/X.md',
                   'docs/research/Y.md', 'docs/findings/Z.md', 'docs/runbooks/a.md', 'docs/adr/0001.md', 'avrana/ops/x.py',
                   'deploy/games', '-----BEGIN PRIVATE KEY-----', 'rcnechamkin', 'cnechamkin', 'BEACNpool', 'appliance.py',
                   'tests/unit', 'tools/x.py', 'web/party/x', 'experiments/native-game', 'the freeze gates are unmet',
                   'a separate lane', '(default: the repository\'s)', 'while the party service moves over',
                   # platform vocabulary (declared or refused)
                   'install-game', 'install_game', 'run as root', 'RESERVED_IDS', 'an emulated game', 'arcade', 'emulator_slot',
                   'hw_encoder', 'hdmi', 'linux/arm64', '/usr/bin/python3', 'lift_manifest_v0', 'shared_video', 'TUF orders',
                   'net.avrana.example', '0123456789abcdef0123456789abcdef01234567', 'webrtc', 'video.h264', 'wake_lock',
                   'presentation.tv', 'input.virtual_gamepad', 'runtime.retroarch']
        for text in samples:
            problems, _ = tools.content_gate({'doc.md': f'a line {text} here\n'.encode()})
            self.assertTrue(problems, text)
        for clean in ('The appliance runs your game.', 'pipe', 'operations and options', 'the Party', 'a pip install',
                      'the number 10.5', 'a hash of 64 hex digits ' + '0123456789abcdef' * 4):
            self.assertEqual(tools.content_gate({'doc.md': clean.encode()})[0], [], clean)

    def test_a_new_leak_in_a_shipped_file_or_the_manifest_fails_the_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = copy_inputs(tmp)
            path = tree / 'tools/avrgame-tools/README.md.in'
            path.write_bytes(path.read_bytes() + b'\nSee AVR-999 and the Pi.\n')
            with self.assertRaises(tools.ExportError) as ctx:
                tools.build_bytes(tree, commit=COMMIT, dirty=False)
            self.assertIn('AVR-999', str(ctx.exception))
            tree = copy_inputs(Path(tmp) / 'two')
            path = tree / 'avrana/avrgame/archive.py'
            path.write_bytes(path.read_bytes() + b"\nNOTE = 'ask rcnechamkin'\n")
            with self.assertRaises(tools.ExportError):
                tools.build_bytes(tree, commit=COMMIT, dirty=False)
            tree = copy_inputs(Path(tmp) / 'three')                         # new platform vocabulary in code is refused too
            path = tree / 'avrana/avrgame/archive.py'
            path.write_bytes(path.read_bytes() + b"\nNOTE = 'systemd-run and provision-game'\nHW = 'hdmi'\n")
            with self.assertRaises(tools.ExportError) as ctx:
                tools.build_bytes(tree, commit=COMMIT, dirty=False)
            self.assertIn('hdmi', str(ctx.exception))

    def test_notice_text_that_is_fixed_in_the_template_passes_the_gate_without_the_declarations(self):
        values = {k: 'x' for k in re.findall(r'\{\{([A-Z_]+)\}\}', (REPO_ROOT / tools.TEMPLATES['NOTICE.md']).read_text(encoding='utf-8'))}
        fixed = tools.fill((REPO_ROOT / tools.TEMPLATES['NOTICE.md']).read_bytes().replace(b'\r\n', b'\n'), {**values, 'REVEALED': ''}, 'n')
        self.assertEqual(tools.content_gate({'NOTICE.md': fixed})[0], [])


class ScrubTests(unittest.TestCase):
    SOURCE = '''"""Does the thing.

Sentence one stays (see docs/design/X.md). Sentence two names AVR-12 and goes.
"""
import os

# A harmless comment.
# Limits for a Pi: generous.
# (this block goes whole)
VALUE = 3  # on the Pi


def f(x):
    """Return x (AVR-9)."""
    return x  # fine


def g():
    """A clean docstring.

        With    spacing kept."""
    return os
'''

    def test_flagged_comments_and_docstring_parts_are_removed_and_the_code_is_untouched(self):
        scrubbed, stats = tools.scrub_python(self.SOURCE)
        tools.prove_same_code(self.SOURCE, scrubbed, 'x.py')
        self.assertNotRegex(scrubbed, r'AVR-|\bPi\b|docs/design')
        self.assertIn('Sentence one stays.', scrubbed)
        self.assertIn('VALUE = 3\n', scrubbed)
        self.assertIn('return x  # fine', scrubbed)                      # unflagged comments stay
        self.assertIn('A clean docstring.\n\n        With    spacing kept.', scrubbed)      # unflagged docstrings byte for byte
        self.assertNotIn('A harmless comment', scrubbed)                  # the whole block around a flagged line goes
        self.assertGreaterEqual(stats['docstrings'], 2)
        self.assertEqual(ast.parse(scrubbed).body[0].value.value.split('\n')[0], 'Does the thing.')

    def test_a_docstring_whose_first_paragraph_vanishes_gets_the_neutral_sentence(self):
        scrubbed, _ = tools.scrub_python('"""See AVR-1.\n\nSecond paragraph stays."""\nX = 1\n')
        doc = ast.get_docstring(ast.parse(scrubbed))
        self.assertTrue(doc.startswith(tools.NEUTRAL_DOCSTRING))
        self.assertIn('Second paragraph stays.', doc)

    def test_the_proof_fails_when_code_changes_or_a_help_text_docstring_would_change(self):
        scrubbed, _ = tools.scrub_python(self.SOURCE)
        with self.assertRaises(tools.ExportError):
            tools.prove_same_code(self.SOURCE, scrubbed.replace('VALUE = 3', 'VALUE = 4'), 'x.py')
        with self.assertRaises(tools.ExportError):
            tools.prove_same_code(self.SOURCE, scrubbed.replace('return x ', 'return x + 1 '), 'x.py')
        with self.assertRaises(tools.ExportError):
            tools.prove_same_code(self.SOURCE, scrubbed.replace('A clean docstring.', 'Changed.'), 'x.py')
        helped = '"""Help text for AVR-3."""\nimport argparse\nargparse.ArgumentParser(description=__doc__)\n'
        scrubbed, _ = tools.scrub_python(helped)
        with self.assertRaises(tools.ExportError) as ctx:
            tools.prove_same_code(helped, scrubbed, 'cli.py')
        self.assertIn('__doc__', str(ctx.exception))

    INDENTED = ('def f():\n    """First paragraph keeps its layout.\n\n        Indented example stays   as it is.\n    \n'
                '    Second mentions AVR-5 and more text after. And a clean sentence.\n\n    Last paragraph, untouched.\n    """\n'
                '    return 1\n')

    def test_unflagged_paragraphs_of_an_indented_docstring_and_blank_lines_are_kept_verbatim(self):
        scrubbed, stats = tools.scrub_python(self.INDENTED)
        tools.prove_same_code(self.INDENTED, scrubbed, 'x.py')
        self.assertEqual(stats['docstrings'], 1)
        self.assertEqual(scrubbed, ('def f():\n    """First paragraph keeps its layout.\n\n        Indented example stays   as it is.\n    \n'
                                    '    And a clean sentence.\n\n    Last paragraph, untouched.\n    """\n    return 1\n'))
        # a flagged one-line paragraph that has to be wrapped keeps the docstring's indentation
        long = ('class C:\n    """Intro.\n\n    ' + ' '.join(['word'] * 40) + ' AVR-3 and more. ' + ' '.join(['tail'] * 40) + '.\n    """\n')
        scrubbed, _ = tools.scrub_python(long)
        tools.prove_same_code(long, scrubbed, 'y.py')
        wrapped = [l for l in scrubbed.split('\n') if 'word' in l or 'tail' in l]
        self.assertTrue(wrapped and all(l.startswith('    ') and not l.startswith('     ') for l in wrapped), wrapped)
        self.assertNotIn('AVR-3', scrubbed)

    def test_a_shebang_and_an_encoding_cookie_are_never_removed(self):
        for head in ('#!/usr/bin/env python3\n', '# -*- coding: utf-8 -*-\n', '#!/usr/bin/python\n# vim: set fileencoding=utf-8 :\n'):
            source = head + '# internal note about AVR-9\nX = 1\n'
            scrubbed, stats = tools.scrub_python(source)
            self.assertEqual(scrubbed, head + 'X = 1\n')
            tools.prove_same_code(source, scrubbed, 'x.py')
            with self.assertRaises(tools.ExportError):                      # the proof notices if one were dropped
                tools.prove_same_code(source, scrubbed[len(head.split('\n')[0]) + 1:], 'x.py')
        with self.assertRaises(tools.ExportError):                          # and a flagged one cannot be scrubbed
            tools.scrub_python('# -*- coding: utf-8 -*- AVR-1\nX = 1\n')
        block = '# coding: utf-8\n# harmless\n# about AVR-2\nX = 1\n'                 # the block starts after the cookie
        self.assertEqual(tools.scrub_python(block)[0], '# coding: utf-8\nX = 1\n')

    def test_docstring_readers_block_a_scrub_unless_the_reader_reads_only_its_own_unchanged_docstring(self):
        own = '"""Help for AVR-1."""\nimport argparse\nargparse.ArgumentParser(description=__doc__)\n'
        other = 'import m\nTEXT = m.__doc__\n'
        via_getattr = 'import m\nTEXT = getattr(m, "__doc__")\n'
        via_inspect = 'import inspect\nimport m\nTEXT = inspect.getdoc(m)\n'
        dirty_doc = '"""Mentions AVR-2 here."""\nX = 1\n'
        clean_own = '"""Clean help."""\nimport argparse\nargparse.ArgumentParser(description=__doc__)\n'

        def pair(text):
            scrubbed, stats = tools.scrub_python(text)
            return (text, scrubbed, stats['docstrings'])
        tools.check_doc_readers({'a.py': pair(dirty_doc), 'b.py': pair(clean_own)})        # unchanged own reader: fine
        tools.check_doc_readers({'a.py': pair('X = 1\n'), 'b.py': pair(other)})           # nothing scrubbed anywhere: fine
        for reader in (other, via_getattr, via_inspect):
            with self.assertRaises(tools.ExportError, msg=reader) as ctx:
                tools.check_doc_readers({'a.py': pair(dirty_doc), 'b.py': pair(reader)})
            self.assertIn('b.py', str(ctx.exception))
        with self.assertRaises(tools.ExportError):                                       # an own reader whose file changed
            tools.check_doc_readers({'a.py': pair(dirty_doc), 'b.py': pair(own)})
        changed_comment = '# note for AVR-5\n' + clean_own
        with self.assertRaises(tools.ExportError):                                       # not byte-identical (comment removed)
            tools.check_doc_readers({'a.py': pair(dirty_doc), 'b.py': pair(changed_comment)})
        kinds = lambda text: tools.doc_reads(ast.parse(text))
        for reader in ('import ast\nTEXT = ast.get_docstring(None)\n', 'from ast import get_docstring\nTEXT = get_docstring(None)\n',
                       'import cmd\nclass Shell(cmd.Cmd):\n    pass\n', 'from cmd import Cmd\nclass Shell(Cmd):\n    pass\n'):
            with self.assertRaises(tools.ExportError, msg=reader):
                tools.check_doc_readers({'a.py': pair(dirty_doc), 'b.py': pair(reader)})
            self.assertEqual(kinds(reader), {'other'}, reader)
        self.assertEqual((kinds(own), kinds(other), kinds(via_getattr), kinds(via_inspect), kinds(dirty_doc)),
                         ({'own'}, {'other'}, {'other'}, {'other'}, set()))

    def test_a_clean_file_is_returned_byte_for_byte(self):
        clean = '"""Clean."""\n# fine\nX = 1  # also fine\n'
        self.assertEqual(tools.scrub_python(clean)[0], clean)


class ReproducibilityTests(unittest.TestCase):
    def test_two_builds_are_identical_and_the_zip_is_sorted_stored_and_fixed(self):
        a = tools.build_bytes(REPO_ROOT, commit=COMMIT, dirty=False)
        b = tools.build_bytes(REPO_ROOT, commit=COMMIT, dirty=False)
        self.assertEqual(a, b)
        files, infos = read_zip(a)
        names = [i.filename for i in infos]
        self.assertEqual(names, sorted(names))
        for i in infos:
            self.assertEqual(i.date_time, (1980, 1, 1, 0, 0, 0))
            self.assertEqual(i.compress_type, zipfile.ZIP_STORED)
            self.assertEqual(i.create_system, 3)
            self.assertEqual(i.external_attr >> 16, 0o100644)
            self.assertFalse(i.filename.endswith('/'))
            self.assertNotIn(b'\r', files[i.filename], i.filename)

    def test_crlf_and_lone_cr_checkouts_give_the_same_bytes_as_an_lf_checkout(self):
        reference = tools.build_bytes(REPO_ROOT, commit=COMMIT, dirty=False)
        with tempfile.TemporaryDirectory() as tmp:
            for label, eol in (('lf', b'\n'), ('crlf', b'\r\n'), ('cr', b'\r')):
                tree = copy_inputs(Path(tmp) / label, eol)
                self.assertIn(eol, (tree / 'avrana/avrgame/common.py').read_bytes())
                self.assertEqual(tools.build_bytes(tree, commit=COMMIT, dirty=False), reference, label)

    def test_a_changed_source_changes_the_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = copy_inputs(tmp)
            path = tree / 'avrana/avrgame/common.py'
            path.write_bytes(path.read_bytes() + b'\n# a harmless comment\n')
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


class BuildHygieneTests(unittest.TestCase):
    def test_an_output_directory_inside_the_repository_is_refused(self):
        out = REPO_ROOT / 'build-export-test-should-not-exist'
        with self.assertRaises(tools.ExportError) as ctx:
            tools.build(out, REPO_ROOT, commit=COMMIT, dirty=False)
        self.assertIn('inside the repository', str(ctx.exception))
        self.assertFalse(out.exists())
        with self.assertRaises(tools.ExportError):
            tools.build(REPO_ROOT, REPO_ROOT, commit=COMMIT, dirty=False)

    def test_a_dirty_or_unverifiable_tree_is_refused_unless_allowed_and_then_the_name_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            for dirty, suffix in ((True, '-dirty'), (None, '-unverified')):
                with self.assertRaises(tools.ExportError):
                    tools.build(Path(tmp) / 'a', REPO_ROOT, commit=COMMIT, dirty=dirty)
                path, checksum, digest = tools.build(Path(tmp) / 'a', REPO_ROOT, commit=COMMIT, dirty=dirty, allow_dirty=True)
                self.assertEqual(path.name, f'{tools.NAME}{suffix}.zip')
                self.assertTrue(checksum.name.startswith(path.name))
                with zipfile.ZipFile(path) as z:                      # the unpacked directory says it too
                    self.assertEqual({n.split('/')[0] for n in z.namelist()}, {f'{tools.NAME}{suffix}'})
                root = tools.unpack(path, Path(tmp) / ('unpacked' + suffix))
                self.assertEqual(root.name, f'{tools.NAME}{suffix}')
                self.assertTrue((root / 'README.md').is_file())
                self.assertEqual(json.loads((root / 'MANIFEST.json').read_text(encoding='utf-8'))['source_dirty'], dirty)
            path, _, _ = tools.build(Path(tmp) / 'a', REPO_ROOT, commit=COMMIT, dirty=False)
            self.assertEqual(path.name, tools.ZIP_NAME)
            with zipfile.ZipFile(path) as z:
                self.assertEqual({n.split('/')[0] for n in z.namelist()}, {tools.NAME})

    def test_an_existing_file_is_replaced_only_when_identical_or_forced(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, checksum, digest = tools.build(tmp, REPO_ROOT, commit=COMMIT, dirty=False)
            again = tools.build(tmp, REPO_ROOT, commit=COMMIT, dirty=False)           # identical: fine
            self.assertEqual(again[2], digest)
            path.write_bytes(b'something else')
            with self.assertRaises(tools.ExportError) as ctx:
                tools.build(tmp, REPO_ROOT, commit=COMMIT, dirty=False)
            self.assertIn('--force', str(ctx.exception))
            self.assertEqual(path.read_bytes(), b'something else')
            tools.build(tmp, REPO_ROOT, commit=COMMIT, dirty=False, force=True)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_the_build_fails_when_what_the_tools_speak_moves_without_a_revision_bump(self):
        moved = dict(tools.SPEAKS, session='avrana.party-session/v1')
        with mock.patch.object(tools, 'SPEAKS', moved):
            with self.assertRaises(tools.ExportError) as ctx:
                tools.build_bytes(REPO_ROOT, commit=COMMIT, dirty=False)
        self.assertIn('TOOLS_REVISION', str(ctx.exception))
        with tempfile.TemporaryDirectory() as tmp:
            tree = copy_inputs(tmp)
            path = tree / 'avrana/party/protocol.py'
            path.write_bytes(path.read_bytes().replace(b"VERSION = 'avrana.party-session/v0'", b"VERSION = 'avrana.party-session/v1'"))
            with self.assertRaises(tools.ExportError):
                tools.build_bytes(tree, commit=COMMIT, dirty=False)

    def test_the_build_fails_when_a_limit_a_permission_an_interpreter_a_ceiling_or_a_capability_moves_without_a_bump(self):
        def changed(rel, old, new, label):
            with tempfile.TemporaryDirectory() as tmp:
                tree = copy_inputs(tmp)
                path = tree / rel
                data = path.read_bytes()
                self.assertEqual(data.count(old), 1, label)
                path.write_bytes(data.replace(old, new))
                with self.assertRaises(tools.ExportError, msg=label) as ctx:
                    tools.build_bytes(tree, commit=COMMIT, dirty=False)
                self.assertIn('TOOLS_REVISION', str(ctx.exception), label)
        changed('avrana/avrgame/common.py', b'MAX_FILES = 2000', b'MAX_FILES = 2001', 'a limit')
        changed('avrana/avrgame/manifest.py', b'MAX_ARG = 200', b'MAX_ARG = 201', 'a manifest limit')
        changed('avrana/contracts/game.py', b"'party_roster', 'controllers'", b"'party_roster', 'jukebox', 'controllers'", 'a permission')
        changed('avrana/avrgame/manifest.py', b"{'python3': '/usr/bin/python3', ", b"{'python3': '/usr/bin/python3', 'deno': '/usr/bin/deno', ", 'an interpreter')
        changed('avrana/ops/provision_game.py', b'MemoryMax=256M', b'MemoryMax=512M', 'a ceiling')
        vocab = json.loads((REPO_ROOT / 'contracts/capabilities.v0.json').read_text(encoding='utf-8'))
        vocab['device']['brand_new'] = vocab['device']['touch']
        with tempfile.TemporaryDirectory() as tmp:
            tree = copy_inputs(tmp)
            (tree / 'contracts/capabilities.v0.json').write_text(json.dumps(vocab, indent=2) + '\n', encoding='utf-8')
            with self.assertRaises(tools.ExportError) as ctx:
                tools.build_bytes(tree, commit=COMMIT, dirty=False)
            self.assertIn('TOOLS_REVISION', str(ctx.exception))
        with mock.patch.object(tools, 'SPEAKS_DIGEST', '0' * 12):                 # and the recorded digest is what is compared
            with self.assertRaises(tools.ExportError) as ctx:
                tools.build_bytes(REPO_ROOT, commit=COMMIT, dirty=False)
        self.assertIn('TOOLS_REVISION', str(ctx.exception))


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

    def same(self, args, label=''):
        """Run `args` through both tools; paths under the work directory are made comparable."""
        a, b = self.exported(args), self.run_in_repo(args, self.work)
        return a, b

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

    def test_pack_is_identical_on_a_second_fixture_with_several_include_roots_and_unusual_names(self):
        root = self.work / 'second'
        files = {
            'alpha/__init__.py': b'', 'alpha/__main__.py': b'print("a")\r\nprint("b")\n',
            'alpha/web/index.html': b'<!doctype html>\n', 'alpha/web/a+b@c=d~e.txt': b'plus at equals tilde\n',
            'alpha/web/UPPER.TXT': b'upper\n', 'alpha/web/empty.dat': b'', 'alpha/web/bin.dat': bytes(range(256)),
            'beta/Mixed-Case_1/x.y.z': b'dots\n', 'beta/' + '/'.join(['d'] * 12) + '/deep.txt': b'deep\n',
            'gamma/only.txt': b'only\n', 'top.txt': b'a single file include\n', 'z_last.txt': b'last\n',
            'alpha/.hidden': b'skipped\n', 'alpha/__pycache__/m.cpython-312.pyc': b'\0skipped',
            'beta/skipme.pyc': b'\0skipped',
        }
        for rel, data in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        manifest = good_manifest(server={'interpreter': 'python3', 'args': ['-m', 'alpha']}, client={'root': 'alpha/web'})
        (root / 'avrgame.json').write_bytes(mjson(manifest))
        (root / 'avrgame.build.json').write_text(json.dumps({
            'recipe': avrgame.RECIPE_FORMAT, 'manifest': 'avrgame.json', 'root': '.',
            'include': ['z_last.txt', 'gamma', 'beta', 'alpha', 'top.txt']}))
        recipe = root / 'avrgame.build.json'
        for extra in ((), ('--deflate',)):
            mine, theirs = self.work / 'mine2.avrgame', self.work / 'theirs2.avrgame'
            a = self.exported(['pack', recipe, '--out', mine, *extra])
            b = self.run_in_repo(['pack', recipe, '--out', theirs, *extra], self.work)
            self.assertEqual((a.returncode, b.returncode), (0, 0), a.stderr + b.stderr)
            self.assertEqual(mine.read_bytes(), theirs.read_bytes(), extra)
        listed = avrgame.read(self.work / 'mine2.avrgame')
        names = [f.path for f in listed.files]
        self.assertNotIn('alpha/.hidden', names)
        self.assertFalse([n for n in names if n.endswith('.pyc')])
        self.assertIn('alpha/web/a+b@c=d~e.txt', names)

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

    def hostile_archives(self):
        attr = lambda kind, perm=0o644: (kind | perm) << 16
        cases = {
            'dotdot': make_zip(extra=[('../evil.py', b'x')]), 'absolute': make_zip(extra=[('/abs', b'x')]),
            'drive letter': make_zip(extra=[('C:/evil.txt', b'x')]), 'backslash': make_zip(extra=[('a\\b.py', b'x')]),
            'nul': make_zip(extra=[('game_pkg/evil\x00.py', b'x')]), 'unicode': make_zip(extra=[('game_pkg/caf\u00e9.py', b'x')]),
            'dotfile': make_zip(extra=[('game_pkg/.hidden', b'x')]), 'device CON': make_zip(extra=[('game_pkg/CON', b'x')]),
            'device nul.txt': make_zip(extra=[('game_pkg/nul.txt', b'x')]), 'device COM1': make_zip(extra=[('game_pkg/Com1.txt', b'x')]),
            'too deep': make_zip(extra=[('d/' * 16 + 'f.txt', b'x')]),
            'duplicate name': make_zip(extra=[('game_pkg/web/app.js', b'evil')]),
            'case collision': make_zip(extra=[('game_pkg/web/APP.js', b'evil')]),
            'case collision dir': make_zip(extra=[('Game_Pkg/x.py', b'evil')]),
            'file and directory': make_zip(extra=[('game_pkg/web/app.js/x', b'evil')]),
            'symlink': make_zip(extra=[('game_pkg/x', b'target', attr(stat.S_IFLNK, 0o777))]),
            'fifo': make_zip(extra=[('game_pkg/x', b'', attr(stat.S_IFIFO))]),
            'setuid': make_zip(extra=[('game_pkg/x', b'x', attr(stat.S_IFREG, 0o4755))]),
            'reparse point': make_zip(extra=[('game_pkg/x', b'x', 0x400)]),
            'encrypted': patch_central(make_zip(), 'game_pkg/__main__.py', 8, '<H', 1),
            'strong encryption': patch_central(make_zip(), 'game_pkg/__main__.py', 8, '<H', 0x40),
            'bzip2': make_zip(method=zipfile.ZIP_BZIP2), 'lzma': make_zip(method=zipfile.ZIP_LZMA),
            'bytecode': make_zip(extra=[('game_pkg/mod.pyc', b'\0')]),
            'key material': make_zip(extra=[('game_pkg/server.key', b'x')]),
            'bomb': make_zip(extra=[(f'bomb{i}.bin', bytes(15 * 1024 * 1024)) for i in range(5)]),
            'one file too big': make_zip(extra=[('one.bin', bytes(avrgame.MAX_FILE_BYTES + 1))]),
            'size header lies': patch_central(make_zip(extra=[('z.bin', bytes(1024 * 1024))]), 'z.bin', 24, '<I', 10),
            'size header huge': patch_central(make_zip(extra=[('z.bin', bytes(1024 * 1024))]), 'z.bin', 24, '<I', 200 * 1024 * 1024),
            'no manifest': make_zip(with_manifest=False), 'duplicate manifest': make_zip(extra=[('avrgame.json', mjson())]),
            'bad json': make_zip(manifest=b'{"format": "a", "format": "b"}'),
            'wrong format': make_zip(manifest=mjson(good_manifest(format='avrana.avrgame/v9'))),
            'reserved key': make_zip(manifest=mjson(good_manifest(signature='x'))),
            'missing module': make_zip(files={'game_pkg/web/index.html': b'x'}),
            'directory with content': make_zip(extra=[('weird/', b'content', (stat.S_IFDIR | 0o755) << 16)]),
            'not a zip': b'this is not a zip file', 'empty file': b'',
            'truncated': make_zip()[:-30],
        }
        return cases

    def test_extract_refuses_the_whole_hostile_set_like_the_repository_tool_and_creates_nothing(self):
        for label, data in self.hostile_archives().items():
            path = self.work / 'case.avrgame'
            path.write_bytes(data)
            dest_a, dest_b = self.work / 'out-a', self.work / 'out-b'
            a = self.exported(['extract', path, dest_a])
            b = self.run_in_repo(['extract', path, dest_b], self.work)
            norm = lambda text, dest: text.replace(str(dest), '<dest>')
            self.assertEqual(b.returncode, 1, (label, b.stderr))
            self.assertNotEqual(b.stderr.strip(), '', label)
            self.assertEqual((a.returncode, norm(a.stdout, dest_a), norm(a.stderr, dest_a)),
                             (b.returncode, norm(b.stdout, dest_b), norm(b.stderr, dest_b)), label)
            self.assertFalse(dest_a.exists(), label)
            self.assertFalse(dest_b.exists(), label)
            for command in ('validate',):
                x, y = self.exported([command, path]), self.run_in_repo([command, path], self.work)
                self.assertEqual((x.returncode, x.stdout, x.stderr), (y.returncode, y.stdout, y.stderr), (label, command))

    def test_extract_destination_rules_match(self):
        good = self.work / 'good.avrgame'
        good.write_bytes(make_zip())

        def setup(label, base):
            """A fresh destination of the given kind under `base`; returns (dest, the directory a link points to)."""
            base.mkdir()
            dest, target = base / 'dest', base / 'link-target'
            target.mkdir()
            if label == 'not empty':
                dest.mkdir()
                (dest / 'keep.txt').write_text('mine')
            elif label == 'a file':
                dest.write_text('x')
            elif label == 'empty directory':
                dest.mkdir()
            elif label == 'symbolic link to a directory':
                os.symlink(target, dest, target_is_directory=True)
            elif label == 'missing parent':
                dest = base / 'no' / 'such' / 'dir'
            return dest, target

        labels = ['not empty', 'a file', 'empty directory', 'missing parent']
        try:
            os.symlink(self.work, self.work / 'probe-link', target_is_directory=True)
            labels.append('symbolic link to a directory')
        except (OSError, NotImplementedError):
            pass                                                             # this host cannot create symbolic links
        for label in labels:
            dest_a, target_a = setup(label, self.work / ('a-' + label.replace(' ', '-')))
            dest_b, target_b = setup(label, self.work / ('b-' + label.replace(' ', '-')))
            a = self.exported(['extract', good, dest_a])
            b = self.run_in_repo(['extract', good, dest_b], self.work)
            norm = lambda text, d: text.replace(str(d), '<dest>')
            self.assertEqual((a.returncode, norm(a.stdout, dest_a), norm(a.stderr, dest_a)),
                             (b.returncode, norm(b.stdout, dest_b), norm(b.stderr, dest_b)), label)
            self.assertEqual(sorted(p.name for p in target_a.iterdir()), sorted(p.name for p in target_b.iterdir()), label)
            if label in ('not empty', 'a file'):
                self.assertEqual(a.returncode, 1, label)
            if label == 'not empty':
                self.assertEqual(sorted(p.name for p in dest_a.iterdir()), ['keep.txt'])
            if label == 'a file':
                self.assertEqual(dest_a.read_text(), 'x')
            if label == 'empty directory':
                self.assertEqual(a.returncode, 0, a.stderr)

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

    def test_validation_verdicts_and_messages_about_capabilities_are_identical(self):
        # a requirement naming an unknown capability, and one naming a real one: the verdicts and messages are identical
        for name in ('no.such.capability', 'websocket'):
            manifest = good_manifest()
            manifest['game']['presentations'][0]['requires'] = {'device': [name]}
            data = make_zip(manifest=mjson(manifest))
            path = self.work / 'cap.avrgame'
            path.write_bytes(data)
            a, b = self.exported(['validate', path]), self.run_in_repo(['validate', path], self.work)
            self.assertEqual((a.returncode, a.stdout, a.stderr), (b.returncode, b.stdout, b.stderr), name)
        self.assertEqual(a.returncode, 0)
        manifest = good_manifest()
        manifest['game']['presentations'][0]['requires'] = {'device': ['no.such.capability'], 'runtime': ['runtime.nothing']}
        path = self.work / 'cap2.avrgame'
        path.write_bytes(make_zip(manifest=mjson(manifest)))
        a, b = self.exported(['validate', path]), self.run_in_repo(['validate', path], self.work)
        self.assertEqual(b.returncode, 1)
        self.assertEqual((a.returncode, a.stdout, a.stderr), (b.returncode, b.stdout, b.stderr))
        self.assertIn("unknown 'no.such.capability'", a.stderr)
        self.assertNotIn('websocket', a.stderr)                  # the message does not list the valid names: the README does

    def test_from_another_working_directory_with_the_export_on_pythonpath(self):
        done = self.exported(['--help'], cwd=self.work)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('validate', done.stdout)


class ClosureCheckTests(unittest.TestCase):
    """The build refuses to produce an export that would not be self-contained."""

    def files(self):
        files, _, _, _ = tools.collect(REPO_ROOT, COMMIT)
        return {k: v for k, v in files.items() if k.endswith('.py')}

    def test_this_commit_is_self_contained(self):
        tools.check_closure(self.files(), REPO_ROOT)
        tools.check_syntax_floor(self.files())

    def refused(self, files, expect):
        with self.assertRaises(tools.ExportError) as ctx:
            tools.check_closure(files, REPO_ROOT)
        self.assertIn(expect, str(ctx.exception))

    def with_extra(self, body, path='avrana/avrgame/manifest.py'):
        files = self.files()
        files[path] += ('\n\n' + body + '\n').encode()
        return files

    def test_a_new_import_of_a_repository_module_is_refused_even_when_lazy(self):
        self.refused(self.with_extra('def extra():\n    from avrana.ops import install_game'), 'avrana.ops')
        self.refused(self.with_extra('def extra():\n    from avrana.avrgame import installed', 'avrana/avrgame/build.py'),
                     'avrana.avrgame.installed')
        self.refused(self.with_extra('from . import installed', 'avrana/avrgame/build.py'), 'avrana.avrgame.installed')
        self.refused(self.with_extra('from avrana.party import sessions'), 'sessions')

    def test_reading_more_of_the_protocol_than_its_version_is_refused(self):
        self.refused(self.with_extra('def extra():\n    from avrana.party import protocol\n    return protocol.seal'),
                     'avrana.party.protocol.seal')
        self.refused(self.with_extra('from avrana.party.result import validate'), 'avrana.party.result.validate')

    def test_aliases_of_a_stand_in_module_and_getattr_through_it_are_refused(self):
        self.refused(self.with_extra('def extra():\n    from avrana.party import protocol\n    alias = protocol\n    return alias.seal'),
                     'other than as `protocol.NAME`')
        self.refused(self.with_extra('def extra():\n    from avrana.party import protocol\n    return getattr(protocol, "seal")'),
                     'other than as `protocol.NAME`')
        self.refused(self.with_extra('def extra():\n    from avrana.party import protocol as p\n    return p'),
                     'other than as `p.NAME`')

    def test_reading_more_of_the_declaration_than_the_bridge_protocol_is_refused(self):
        use = 'from avrana.contracts import party_games'
        for expr, expect in (("party_games.load()['routes']", "['routes']"),
                             ("party_games.load()['bridge']['frame']", "['frame']"),
                             ("party_games.load()", 'party_games.load()'),
                             ("party_games.versions()", 'versions')):
            self.refused(self.with_extra('def extra():\n    ' + use + '\n    return ' + expr), expect)

    def test_things_that_hide_imports_are_refused(self):
        self.refused(self.with_extra('x = __import__("os")'), '__import__')
        self.refused(self.with_extra('import importlib'), 'importlib')
        self.refused(self.with_extra('import runpy'), 'runpy')
        self.refused(self.with_extra('import sys\nx = sys.modules'), 'sys.modules')
        self.refused(self.with_extra('from os import *'), 'import *')
        self.refused(self.with_extra('eval("1")'), 'eval')
        self.refused(self.with_extra('exec("x = 1")'), 'exec')

    def test_reading_more_of_the_capability_vocabulary_than_its_names_is_refused(self):
        self.refused(self.with_extra('def extra(vocab):\n    return vocab.label("x")'), 'label')
        self.refused(self.with_extra('def extra(vocab):\n    return vocab.missing("x")'), 'missing')
        self.refused(self.with_extra('def extra(vocab):\n    return vocab.device.items()', 'avrana/contracts/game.py'), 'beyond their names')
        self.refused(self.with_extra('def extra(vocab):\n    return vocab.runtime["x"]', 'avrana/contracts/game.py'), 'beyond their names')

    def test_a_third_party_import_is_refused(self):
        self.refused(self.with_extra('import requests', 'avrana/avrgame/common.py'), 'requests')

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
