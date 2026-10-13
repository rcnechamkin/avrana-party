"""The optional Node.js runtime of EXPERIMENTAL .avrgame packages (AVR-68): the manifest and archive
rules, the installer's refusal when the runtime is missing, the runtime tool, and the Node fixture
game. Scratch directories and a recorded `systemctl`, on any OS; the real unit on a real systemd is
the Linux CI job's (experiments/native-game/node-package-proof.sh).

    python -m unittest discover -s tests/unit -p test_node_game_runtime.py
"""
import hashlib
import http.client
import http.server
import io
import json
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

from avrana import REPO_ROOT
from avrana import avrgame
from avrana.avrgame import installed, node_pin as pin
from avrana.ops import install_game as ig
from avrana.ops import node_runtime as nr
from avrana.ops import provision_game as pg
from avrana.party import protocol, result

from test_avrgame_package import good_manifest, make_zip, mjson, problems_of
from test_install_game import Base, REPO

FIXTURE = REPO_ROOT / 'tests' / 'fixtures' / 'node-game'
NODE = '/opt/avrana-runtimes/node-22.22.2/bin/node'
LIFECYCLE_MARK = 'avr68-lifecycle-ran'
PACKAGE_JSON = json.dumps({'name': 'dep', 'version': '1.0.0', 'type': 'module', 'exports': './index.js',
                           'scripts': {'preinstall': 'node lifecycle.cjs', 'install': 'node lifecycle.cjs',
                                       'postinstall': 'node lifecycle.cjs'}}).encode()
NODE_FILES = {
    'server/main.mjs': b'import { a } from "dep";\nconsole.log(a);\n',
    'web/index.html': b'<!doctype html><title>x</title>\n',
    'node_modules/dep/package.json': PACKAGE_JSON,
    'node_modules/dep/index.js': b'export const a = 1;\n',
    'node_modules/dep/lifecycle.cjs': b'require("node:fs").writeFileSync("avr68-lifecycle-ran", "x");\n',
}
ELF = b'\x7fELF\x02\x01\x01\x00' + b'\x00' * 56


def node_manifest(args=('server/main.mjs',), **over):
    m = good_manifest(**over)
    m['server'] = {'interpreter': 'node', 'args': list(args)}
    m['client'] = {'root': 'web'}
    return m


def node_zip(files=None, manifest=None, **kw):
    return make_zip(files=NODE_FILES if files is None else files,
                    manifest=mjson(node_manifest() if manifest is None else manifest), method=zipfile.ZIP_STORED, **kw)


def refusal(data):
    with unittest.TestCase().assertRaises(avrgame.Refused) as ctx:
        avrgame.scan(data)[1].close()
    return ctx.exception.problems


class ManifestTests(unittest.TestCase):
    def test_a_manifest_may_name_the_node_runtime_and_the_appliance_owns_its_path(self):
        self.assertEqual(dict(avrgame.INTERPRETERS), {'python3': '/usr/bin/python3', 'node': NODE})
        self.assertEqual(avrgame.OPTIONAL_RUNTIMES, frozenset({'node'}))
        self.assertEqual(avrgame.INTERPRETERS['node'], pin.EXECUTABLE)      # the literal of the manifest module is the pin
        out = avrgame.validate_manifest(node_manifest())
        self.assertEqual(out['server'], {'interpreter': 'node', 'args': ['server/main.mjs']})
        avrgame.validate_manifest(node_manifest(['main.mjs']))
        avrgame.validate_manifest(node_manifest(['server/main.mjs', '--rounds', '3']))     # the script's own arguments
        for path in ('/usr/bin/node', 'node22', 'nodejs', 'deno', 'bun', 'npm', 'npx', 'sh'):
            m = node_manifest()
            m['server']['interpreter'] = path
            self.assertTrue(any(p.startswith('server.interpreter') for p in problems_of(m)), path)

    def test_the_node_entry_is_an_mjs_file_of_the_package_and_never_an_option(self):
        bad = {'js': ['server/main.js'], 'cjs': ['server/main.cjs'], 'no suffix': ['server/main'],
               'upper case suffix': ['server/main.MJS'], 'typescript': ['server/main.mts'],
               'eval': ['-e', 'process.exit()'], 'long eval': ['--eval=1', 'server/main.mjs'],
               'require': ['--require', './x.cjs', 'server/main.mjs'], 'import': ['--import=./x.mjs', 'server/main.mjs'],
               'an option named like a file': ['--x.mjs'], 'dash': ['-.mjs'],
               'traversal': ['../other/main.mjs'], 'inner traversal': ['server/../../main.mjs'],
               'absolute': ['/opt/evil/main.mjs'], 'drive': ['C:/main.mjs'], 'backslash': ['server\\main.mjs'],
               'in node_modules': ['node_modules/dep/cli.mjs'], 'nested node_modules': ['server/node_modules/dep/cli.mjs'],
               'hidden': ['.hidden/main.mjs'], 'only the suffix': ['.mjs'], 'directory': ['server/'],
               'a url': ['data:text/javascript,1.mjs'], 'a file url': ['file:///x/main.mjs'], 'not a string': [3]}
        for label, args in bad.items():
            self.assertTrue(any(p.startswith('server.args') for p in problems_of(node_manifest(args))), label)
        said = ' '.join(problems_of(node_manifest(['server/main.js'])))
        self.assertIn('".mjs"', said)
        self.assertIn('never an option of Node', said)

    def test_a_missing_entry_is_refused(self):
        self.assertTrue(any(p.startswith('server.args') for p in problems_of(node_manifest([]))))
        m = node_manifest()
        del m['server']['args']
        self.assertIn("server: missing 'args'", problems_of(m))
        files = {k: v for k, v in NODE_FILES.items() if k != 'server/main.mjs'}
        self.assertTrue(any('has no file' in p and 'server/main.mjs' in p for p in refusal(node_zip(files))))

    def test_the_arguments_after_the_entry_keep_the_general_rules(self):
        for args in (['server/main.mjs', '/etc/passwd'], ['server/main.mjs', '../x'], ['server/main.mjs', 'a\nb'],
                     ['server/main.mjs'] + ['x'] * 16):
            self.assertTrue(any(p.startswith('server.args') for p in problems_of(node_manifest(args))), args)

    def test_python_packages_are_judged_exactly_as_before(self):
        avrgame.validate_manifest(good_manifest())
        m = good_manifest()
        m['server']['args'] = ['server/main.mjs']                     # the node form is not a python3 form
        self.assertTrue(any('for python3 only' in p for p in problems_of(m)))
        m = node_manifest(['-m', 'game_pkg'])                          # and the python3 form is not a node form
        self.assertTrue(any(p.startswith('server.args[0]') for p in problems_of(m)))

    def test_a_package_still_cannot_say_what_to_run_or_install(self):
        for key in ('command', 'env', 'cwd', 'entry'):
            m = node_manifest()
            m['server'][key] = 'x'
            self.assertIn(f'server.{key}: set by the appliance, never by a package', problems_of(m))
        for key in ('scripts', 'install', 'postinstall', 'dependencies', 'runtime'):
            m = node_manifest()
            m['server'][key] = {'postinstall': 'curl x | sh'}
            self.assertTrue(any(p.startswith('server: unknown key') for p in problems_of(m)), key)
            m = node_manifest()
            m[key] = 'npm install'
            self.assertTrue(any(p.startswith('manifest: unknown key') for p in problems_of(m)), key)


class ArchiveTests(unittest.TestCase):
    def test_a_node_package_with_vendored_plain_files_validates(self):
        package, zf = avrgame.scan(node_zip())
        zf.close()
        self.assertEqual(package.manifest['server'], {'interpreter': 'node', 'args': ['server/main.mjs']})
        self.assertIn('node_modules/dep/package.json', [f.path for f in package.files])

    def test_a_native_addon_is_refused_by_name_and_by_content(self):
        for name in ('node_modules/dep/build/Release/addon.node', 'node_modules/dep/prebuilds/linux-arm64/dep.NODE',
                     'node_modules/dep/lib/libdep.so', 'node_modules/dep/bin/tool.exe', 'server/native.dll',
                     'node_modules/dep/lib/libdep.dylib'):
            said = refusal(node_zip({**NODE_FILES, name: b'not even a binary'}))
            self.assertTrue(any('compiled code' in p and name.rsplit('/', 1)[-1] in p for p in said), name)
        # by content: an ELF (or Mach-O) under a name that says nothing
        for label, head in (('elf', ELF), ('mach-o 64', b'\xcf\xfa\xed\xfe' + b'\x00' * 28),
                            ('mach-o fat', b'\xca\xfe\xba\xbe' + b'\x00' * 28)):
            for name in ('node_modules/dep/data.bin', 'node_modules/dep/helper.js', 'server/blob'):
                said = refusal(node_zip({**NODE_FILES, name: head}))
                self.assertTrue(any('compiled code' in p and name.rsplit('/', 1)[-1] in p for p in said), (label, name))
        said = refusal(node_zip({**NODE_FILES, 'node_modules/a/x.node': b'x', 'node_modules/b/y': ELF}))
        self.assertEqual(len([p for p in said if 'compiled code' in p]), 1)      # names are judged first, before any content is read

    def test_webassembly_and_scripts_with_a_shebang_are_plain_files(self):
        wasm = bytes([0, 97, 115, 109, 1, 0, 0, 0])
        avrgame.scan(node_zip({**NODE_FILES, 'node_modules/dep/dep.wasm': wasm,
                               'node_modules/dep/cli.js': b'#!/usr/bin/env node\nconsole.log(1);\n'}))[1].close()

    def test_a_symbolic_link_is_refused_wherever_it_is(self):
        link = (stat.S_IFLNK | 0o777) << 16
        for name in ('node_modules/dep', 'node_modules/linked.js', 'server/alias.mjs'):
            said = refusal(node_zip(extra=[(name, b'../../../etc/passwd', link)]))
            self.assertTrue(any('only regular files and directories' in p for p in said), name)

    def test_the_bin_directory_and_other_dot_entries_of_node_modules_are_refused(self):
        for name in ('node_modules/.bin/dep', 'node_modules/.package-lock.json', 'node_modules/dep/.npmrc'):
            said = refusal(node_zip({**NODE_FILES, name: b'x'}))
            self.assertTrue(any('hidden (dot) files' in p for p in said), name)

    def test_the_limits_are_the_ones_every_package_has(self):
        many = {**NODE_FILES, **{f'node_modules/dep/f{i}.js': b'' for i in range(avrgame.MAX_FILES)}}
        self.assertTrue(any('entries; at most' in p for p in refusal(node_zip(many))))
        self.assertEqual((avrgame.MAX_FILES, avrgame.MAX_TOTAL_BYTES, avrgame.MAX_FILE_BYTES),
                         (2000, 64 * 1024 * 1024, 16 * 1024 * 1024))

    def test_a_python_package_is_not_judged_by_the_node_rules(self):
        files = {'game_pkg/__init__.py': b'', 'game_pkg/__main__.py': b'print(1)\n',
                 'game_pkg/web/index.html': b'<!doctype html>\n', 'game_pkg/data.node': b'a graph node, as text\n'}
        avrgame.scan(make_zip(files=files, method=zipfile.ZIP_STORED))[1].close()


class PackerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.src = Path(tmp.name) / 'src'
        for name, data in NODE_FILES.items():
            path = self.src / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (self.src / 'avrgame.json').write_bytes(mjson(node_manifest()))
        self.out = Path(tmp.name) / 'out.avrgame'

    def pack(self):
        return avrgame.pack(self.src, self.src / 'avrgame.json', ['server', 'web', 'node_modules'], self.out)

    def test_pack_takes_vendored_files_and_leaves_out_what_npm_adds_for_itself(self):
        (self.src / 'node_modules' / '.bin').mkdir()
        (self.src / 'node_modules' / '.bin' / 'dep').write_bytes(b'#!/bin/sh\n')
        (self.src / 'node_modules' / '.package-lock.json').write_bytes(b'{}')
        package = self.pack()
        names = [f.path for f in package.files]
        self.assertEqual(names, sorted(['avrgame.json', *NODE_FILES]))
        first = self.out.read_bytes()
        self.pack()
        self.assertEqual(self.out.read_bytes(), first)                 # deterministic, node_modules included

    def test_pack_refuses_a_native_addon_and_a_wrong_entry(self):
        addon = self.src / 'node_modules' / 'dep' / 'build' / 'addon.node'
        addon.parent.mkdir()
        addon.write_bytes(ELF)
        with self.assertRaises(avrgame.Refused) as ctx:
            self.pack()
        self.assertTrue(any('compiled code' in p for p in ctx.exception.problems))
        self.assertFalse(self.out.exists())
        shutil.rmtree(addon.parent)
        (self.src / 'avrgame.json').write_bytes(mjson(node_manifest(['server/main.js'])))
        with self.assertRaises(avrgame.Refused):
            self.pack()
        self.assertFalse(self.out.exists())

    def test_pack_refuses_a_linked_dependency(self):
        target = self.src / 'node_modules' / 'dep'
        try:
            os.symlink(target, self.src / 'node_modules' / 'alias', target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('this account cannot create symbolic links')
        with self.assertRaises(avrgame.Refused) as ctx:
            self.pack()
        self.assertTrue(any('symbolic links are refused' in p for p in ctx.exception.problems))


class InstallTests(Base):
    """Base (test_install_game) is a scratch host with a recorded systemctl."""

    def node_package(self, name='hello.avrgame', files=None, manifest=None):
        path = self.inputs / name
        path.write_bytes(node_zip(files, manifest))
        return path

    def marks(self):
        found = [p for p in self.root.rglob(LIFECYCLE_MARK)]
        found += [p for p in (Path(tempfile.gettempdir()) / LIFECYCLE_MARK, Path.cwd() / LIFECYCLE_MARK) if p.exists()]
        return found

    def test_without_the_runtime_a_node_package_is_refused_and_nothing_is_written(self):
        before = self.snapshot()
        with self.assertRaises(ig.Refused) as ctx:
            self.install(self.node_package(), present=lambda path: False)
        said = str(ctx.exception)
        for part in ('node runtime', 'does not have', NODE, 'install-node-runtime', 'nothing was installed'):
            self.assertIn(part, said)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.calls, [])
        with self.assertRaises(ig.Refused):                           # the real check: this machine has no such file
            self.install(self.node_package())
        self.assertEqual(self.snapshot(), before)

    def test_a_python_package_installs_on_an_appliance_without_the_runtime(self):
        seen = []
        self.install(present=lambda path: seen.append(path) or False)
        self.assertEqual(seen, [])                                    # python3 is not an optional runtime: nothing is looked for
        self.assertIn('ExecStart="/usr/bin/python3" "-m" "game_pkg"',
                      self.layout.provision.dropin('hello').read_text(encoding='utf-8'))

    def test_with_the_runtime_a_node_package_is_staged_and_runs_the_pinned_node_by_absolute_path(self):
        lines = self.install(self.node_package(), present=lambda path: path == NODE)
        self.assertTrue(lines[0].startswith('hello: installed 0.1.0'))
        dropin = self.layout.provision.dropin('hello').read_text(encoding='utf-8')
        record = json.loads(self.layout.record('hello').read_text(encoding='utf-8'))
        self.assertIn(f'ExecStart="{NODE}" "server/main.mjs"\n', dropin)
        self.assertIn(f'WorkingDirectory={record["root"]}\n', dropin)
        self.assertEqual(record['grant']['runtime'], {'command': [NODE, 'server/main.mjs'], 'working_directory': record['root']})
        self.assertIn(NODE, self.trusted_paths)                       # root-owned code all the way up, as for python3
        staged = self.layout.on_disk(record['root'])
        self.assertEqual((staged / 'node_modules/dep/package.json').read_bytes(), PACKAGE_JSON)
        self.assertEqual(ig.verify('hello', self.layout, REPO), [])
        found = installed.load(self.layout.records_dir, REPO, games_root=self.layout.root_text())
        self.assertEqual(found.problems, [])
        self.assertEqual(found.grants['hello']['runtime']['command'][0], NODE)

    def test_install_scripts_of_a_vendored_package_json_are_never_run(self):
        self.assertEqual(self.marks(), [])
        self.install(self.node_package(), present=lambda path: True)
        # the only programs the installer ran: systemctl. No npm, no node, no shell, no lifecycle script.
        self.assertTrue(self.calls)
        self.assertEqual({argv[0] for argv in self.calls}, {'systemctl'})
        self.assertEqual(self.marks(), [])
        source = (REPO_ROOT / 'avrana' / 'ops' / 'install_game.py').read_text(encoding='utf-8') \
            + ''.join(p.read_text(encoding='utf-8') for p in (REPO_ROOT / 'avrana' / 'avrgame').glob('*.py'))
        for word in ('npm', 'npx', 'yarn', 'pnpm', 'corepack', 'node-gyp', 'shell=True', 'os.system'):
            self.assertNotIn(f'[\'{word}\'', source)
            self.assertNotIn(f'["{word}"', source)
        self.assertNotIn('shell=True', source)
        self.assertNotIn('os.system', source)

    def test_the_node_unit_has_exactly_the_sandbox_and_ceilings_of_a_python_package_unit(self):
        self.install(self.node_package(), present=lambda path: True)
        node_unit = self.layout.provision.dropin('hello').read_text(encoding='utf-8')
        self.remove()
        self.install()
        python_unit = self.layout.provision.dropin('hello').read_text(encoding='utf-8')

        def rest(text):
            return [line for line in text.splitlines() if not line.startswith(('ExecStart=', 'WorkingDirectory='))]
        self.assertEqual(rest(node_unit), rest(python_unit))
        for line in ('MemoryMax=256M', 'TasksMax=64', 'CPUQuota=100%', 'CapabilityBoundingSet=', 'PrivateNetwork=yes',
                     'RestrictNamespaces=yes', 'StateDirectory='):
            self.assertIn(line, node_unit.splitlines())
        template = (REPO_ROOT / 'deploy' / 'games' / 'avrana-game@.service').read_text(encoding='utf-8')
        # V8 needs to map executable memory; neither the template nor the drop-in forbids it, so no
        # directive is relaxed for Node. If one of these appears, the Node proof must be read again.
        for directive in ('MemoryDenyWriteExecute', 'SystemCallFilter', 'NoExecPaths', 'ExecPaths'):
            self.assertNotIn(directive, template + node_unit)

    def test_a_record_cannot_make_node_run_anything_but_an_entry_of_the_package(self):
        self.install(self.node_package(), present=lambda path: True)
        good = json.loads(self.layout.record('hello').read_text(encoding='utf-8'))
        installed.validate_record(json.loads(json.dumps(good)), 'hello', REPO, games_root=self.layout.root_text())
        bad = {'an option': ['--eval', 'process.exit()'], 'a js file': ['server/main.js'],
               'a file the package does not have': ['server/other.mjs'], 'a dependency': ['node_modules/dep/cli.mjs'],
               'a traversal': ['../x.mjs'], 'nothing': []}
        for label, args in bad.items():
            doc = json.loads(json.dumps(good))
            doc['grant']['runtime']['command'] = [NODE, *args]
            with self.assertRaises(installed.RecordError, msg=label):
                installed.validate_record(doc, 'hello', REPO, games_root=self.layout.root_text())
        doc = json.loads(json.dumps(good))
        doc['grant']['runtime']['command'][0] = '/usr/local/bin/node'      # only the pinned, appliance-owned path
        with self.assertRaises(installed.RecordError):
            installed.validate_record(doc, 'hello', REPO, games_root=self.layout.root_text())

    def test_a_native_addon_or_a_wrong_entry_never_reaches_the_host(self):
        before = self.snapshot()
        cases = (self.node_package('addon.avrgame', {**NODE_FILES, 'node_modules/dep/build/addon.node': ELF}),
                 self.node_package('elf.avrgame', {**NODE_FILES, 'node_modules/dep/data': ELF}),
                 self.node_package('js.avrgame', manifest=node_manifest(['server/main.js'])),
                 self.node_package('missing.avrgame', {k: v for k, v in NODE_FILES.items() if k != 'server/main.mjs'}))
        for path in cases:
            with self.assertRaises(ig.Refused, msg=path.name) as ctx:
                self.install(path, present=lambda path: True)
            self.assertIn('package refused', str(ctx.exception))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.calls, [])

    def test_dry_run_and_main_say_the_same_refusal(self):
        out, err = io.StringIO(), io.StringIO()
        argv = ['install', str(self.node_package()), '--grant', 'party_roster', '--dry-run',
                '--key-dir', str(self.root / 'etc/game-keys'), '--registry-dir', str(self.root / 'etc/games.d'),
                '--socket-dir', str(self.root / 'run/games'), '--state-dir', str(self.root / 'var/games'),
                '--unit-dir', str(self.root / 'etc/systemd'), '--party-config', str(self.root / 'etc/party-core.json'),
                '--records-dir', str(self.root / 'etc/packages.d'), '--games-root', str(self.root / 'opt/avrana-games'),
                '--visible-root', '/opt/avrana-games', '--lock-file', str(self.root.parent / 'install.lock')]
        code = ig.main(argv, run=self.run_, own=self.own, is_root=True, contracts=REPO, out=out, err=err)
        self.assertEqual(code, 1)
        self.assertIn('install-game: refused: this package runs on the node runtime', err.getvalue())
        self.assertEqual(out.getvalue(), '')


def runtime_tarball(path, arch='x64', node_bytes=b'\x7fELF fake node\n', extra=True, prefix=None):
    """A tarball shaped like the official one: bin/node, LICENSE, and what must NOT be taken."""
    prefix = prefix or pin.ARCHIVES[arch][0][:-len('.tar.xz')]
    with tarfile.open(path, 'w:xz') as tar:
        def add(name, data, mode=0o644):
            info = tarfile.TarInfo(f'{prefix}/{name}')
            info.size, info.mode = len(data), mode
            tar.addfile(info, io.BytesIO(data))
        add('LICENSE', b'the license\n')
        if node_bytes is not None:
            add('bin/node', node_bytes, 0o755)
        if extra:
            link = tarfile.TarInfo(f'{prefix}/bin/npm')
            link.type, link.linkname = tarfile.SYMTYPE, '../lib/node_modules/npm/bin/npm-cli.js'
            tar.addfile(link)
            add('lib/node_modules/npm/bin/npm-cli.js', b'#!/usr/bin/env node\n', 0o755)
            add('include/node/node.h', b'// header\n')
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class RuntimeToolTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.opt = self.tmp / 'opt'
        self.opt.mkdir()
        self.runtimes = self.opt / 'avrana-runtimes'
        self.final = self.runtimes / f'node-{pin.VERSION}'
        self.tarball = self.tmp / pin.ARCHIVES['x64'][0]
        digest = runtime_tarball(self.tarball)
        other = runtime_tarball(self.tmp / 'arm.tar.xz', 'arm64', b'\x7fELF fake arm node\n')
        self.archives = {'x64': (pin.ARCHIVES['x64'][0], digest), 'arm64': (pin.ARCHIVES['arm64'][0], other)}
        self.versions = []

    def version(self, executable):
        self.versions.append(Path(executable))
        return f'v{pin.VERSION}'

    def install(self, path=None, arch='x64', **kw):
        kw.setdefault('version_of', self.version)
        return nr.install(path or self.tarball, self.runtimes, arch, archives=self.archives, **kw)

    def tree(self):
        return sorted(p.relative_to(self.opt).as_posix() for p in self.opt.rglob('*'))

    def test_the_pins_are_the_official_builds_of_one_version_for_both_architectures(self):
        self.assertGreaterEqual(int(pin.VERSION.split('.')[0]), 22)
        self.assertEqual(sorted(pin.ARCHIVES), ['arm64', 'x64'])
        for arch, (name, digest) in pin.ARCHIVES.items():
            self.assertEqual(name, f'node-v{pin.VERSION}-linux-{arch}.tar.xz')
            self.assertRegex(digest, r'^[0-9a-f]{64}\Z')
        self.assertEqual(len({d for _, d in pin.ARCHIVES.values()}), 2)
        self.assertEqual(pin.EXECUTABLE, f'/opt/avrana-runtimes/node-{pin.VERSION}/bin/node')
        self.assertEqual((pin.arch_of('aarch64'), pin.arch_of('x86_64'), pin.arch_of('armv7l')), ('arm64', 'x64', None))

    def test_install_takes_exactly_the_binary_and_the_license_and_records_what_it_came_from(self):
        lines = self.install()
        self.assertIn('installed from', lines[0])
        base = f'avrana-runtimes/node-{pin.VERSION}'
        self.assertEqual(self.tree(), ['avrana-runtimes', base, f'{base}/LICENSE', f'{base}/avrana-runtime.json',
                                       f'{base}/bin', f'{base}/bin/node'])        # no npm, npx, corepack, headers or link
        self.assertEqual((self.final / 'bin' / 'node').read_bytes(), b'\x7fELF fake node\n')
        doc = json.loads((self.final / 'avrana-runtime.json').read_text(encoding='utf-8'))
        self.assertEqual(doc, {'record': 'avrana.runtime/experimental.1', 'runtime': 'node', 'version': pin.VERSION,
                               'arch': 'x64', 'archive': pin.ARCHIVES['x64'][0], 'archive_sha256': self.archives['x64'][1],
                               'node_sha256': hashlib.sha256(b'\x7fELF fake node\n').hexdigest()})
        self.assertEqual(nr.problems(self.final, 'x64', archives=self.archives), [])
        self.assertEqual(len(self.versions), 1)                       # asked once, while still under the staging name
        self.assertTrue(self.versions[0].parent.parent.name.startswith('.staging-'))
        if os.name == 'posix':
            self.assertEqual(stat.S_IMODE(os.stat(self.final / 'bin' / 'node').st_mode), 0o755)
            self.assertEqual(stat.S_IMODE(os.stat(self.final).st_mode), 0o755)
            self.assertEqual(stat.S_IMODE(os.stat(self.final / 'avrana-runtime.json').st_mode), 0o644)

    def test_a_second_install_changes_nothing(self):
        self.install()
        before = {p: p.stat().st_mtime_ns for p in self.opt.rglob('*')}
        lines = self.install()
        self.assertIn('already installed', lines[0])
        self.assertEqual({p: p.stat().st_mtime_ns for p in self.opt.rglob('*')}, before)
        self.assertEqual(len(self.versions), 1)

    def test_a_tarball_that_is_not_the_pinned_build_is_refused_and_nothing_is_created(self):
        wrong = self.tmp / 'wrong.tar.xz'
        runtime_tarball(wrong, node_bytes=b'\x7fELF another node\n')
        cases = {'another build under the right name': (wrong, 'not the one pinned'),
                 'the other architecture': (self.tmp / 'arm.tar.xz', 'this machine is x64'),
                 'not a tarball': (self.tmp / 'junk', 'not the one pinned'),
                 'missing': (self.tmp / 'nope.tar.xz', 'does not exist')}
        (self.tmp / 'junk').write_bytes(b'hello')
        for label, (path, part) in cases.items():
            with self.assertRaises(nr.Refused, msg=label) as ctx:
                self.install(path)
            self.assertIn(part, str(ctx.exception), label)
            self.assertEqual(self.tree(), [], label)
        self.assertEqual(self.versions, [])                          # nothing unverified was ever run
        shutil.copy(wrong, self.tmp / 'renamed')
        os.replace(self.tmp / 'renamed', wrong.with_name(pin.ARCHIVES['x64'][0] + '.copy'))
        with self.assertRaises(nr.Refused):                           # the name of the file is not evidence
            self.install(wrong.with_name(pin.ARCHIVES['x64'][0] + '.copy'))

    def test_the_real_pins_refuse_a_made_up_tarball(self):
        with self.assertRaises(nr.Refused) as ctx:
            nr.install(self.tarball, self.runtimes, 'x64', version_of=self.version)
        self.assertIn(pin.ARCHIVES['x64'][1], str(ctx.exception))
        self.assertEqual(self.tree(), [])

    def test_a_binary_that_does_not_say_the_pinned_version_or_an_incomplete_tarball_leaves_nothing(self):
        with self.assertRaises(nr.Refused) as ctx:
            self.install(version_of=lambda executable: 'v20.0.0')
        self.assertIn("'v20.0.0'", str(ctx.exception))
        self.assertEqual(self.tree(), [])
        bare = self.tmp / 'bare.tar.xz'
        self.archives['x64'] = (pin.ARCHIVES['x64'][0], runtime_tarball(bare, node_bytes=None))
        with self.assertRaises(nr.Refused) as ctx:
            self.install(bare)
        self.assertIn('has no bin/node', str(ctx.exception))
        self.assertEqual(self.tree(), [])
        linked = self.tmp / 'linked.tar.xz'
        prefix = pin.ARCHIVES['x64'][0][:-len('.tar.xz')]
        with tarfile.open(linked, 'w:xz') as tar:
            info = tarfile.TarInfo(f'{prefix}/bin/node')
            info.type, info.linkname = tarfile.SYMTYPE, '/bin/sh'
            tar.addfile(info)
        self.archives['x64'] = (pin.ARCHIVES['x64'][0], hashlib.sha256(linked.read_bytes()).hexdigest())
        with self.assertRaises(nr.Refused):
            self.install(linked)
        self.assertEqual(self.tree(), [])

    def test_verify_notices_a_changed_binary_an_extra_file_and_a_foreign_tree(self):
        self.assertTrue(nr.problems(self.final, 'x64', archives=self.archives)[0].endswith('not installed'))
        self.install()
        (self.final / 'bin' / 'npm').write_bytes(b'x')
        self.assertIn('bin/npm: not part of the runtime', nr.problems(self.final, 'x64', archives=self.archives))
        (self.final / 'bin' / 'npm').unlink()
        (self.final / 'bin' / 'node').write_bytes(b'\x7fELF tampered\n')
        self.assertEqual(nr.problems(self.final, 'x64', archives=self.archives), ['bin/node: changed since it was installed'])
        with self.assertRaises(nr.Refused) as ctx:                    # never repaired in place
            self.install()
        self.assertIn('remove', str(ctx.exception))
        self.assertTrue(nr.problems(self.final, 'arm64', archives=self.archives))      # a tree of the other architecture
        self.assertIn('not owned by uid', ' '.join(nr.problems(self.final, 'x64', owner=2 ** 31 - 7, archives=self.archives)))

    def test_remove_is_refused_while_a_package_runs_on_the_runtime(self):
        self.install()
        records = self.tmp / 'packages.d'
        records.mkdir()
        (records / 'tanks.json').write_text(json.dumps({'grant': {'runtime': {'command': [NODE, 'server/main.mjs']}}}))
        (records / 'hello.json').write_text(json.dumps({'grant': {'runtime': {'command': ['/usr/bin/python3', '-m', 'x']}}}))
        (records / 'broken.json').write_text('{')
        with self.assertRaises(nr.Refused) as ctx:
            nr.remove(self.runtimes, records)
        self.assertIn('tanks', str(ctx.exception))
        self.assertNotIn('hello', str(ctx.exception))
        self.assertTrue(self.final.is_dir())
        (records / 'tanks.json').unlink()
        self.assertIn('would remove', nr.remove(self.runtimes, records, dry_run=True)[0])
        self.assertTrue(self.final.is_dir())
        self.assertIn('removed', nr.remove(self.runtimes, records)[0])
        self.assertEqual(self.tree(), [])
        self.assertIn('nothing to remove', nr.remove(self.runtimes, records)[0])

    def test_the_command_line_needs_root_and_dry_run_changes_nothing(self):
        common = ['--runtimes-root', str(self.runtimes), '--records-dir', str(self.tmp / 'none'), '--machine', 'x86_64']
        out, err = io.StringIO(), io.StringIO()
        self.assertEqual(nr.main(['install', str(self.tarball), *common], is_root=False, out=out, err=err), 1)
        self.assertIn('must run as root', err.getvalue())
        self.assertEqual(nr.main(['verify', *common], is_root=False, out=out, err=io.StringIO()), 1)
        err = io.StringIO()
        self.assertEqual(nr.main(['install', str(self.tarball), *common], is_root=True, out=out, err=err), 1)
        self.assertIn('not the one pinned', err.getvalue())           # the real pins: a made-up tarball never passes
        self.assertEqual(nr.main(['install', str(self.tarball), '--runtimes-root', str(self.runtimes), '--machine', 'riscv64'],
                                 is_root=True, out=out, err=err), 1)
        self.assertIn('no pinned Node build', err.getvalue())
        self.assertEqual(self.tree(), [])
        self.assertEqual(self.install(dry_run=True)[0].split(': ')[1].split(' ')[0:2], ['would', 'install'])
        self.assertEqual(self.tree(), [])

    def test_the_tool_and_the_library_never_open_a_network_connection(self):
        for path in (REPO_ROOT / 'avrana' / 'ops' / 'node_runtime.py', REPO_ROOT / 'avrana' / 'avrgame' / 'node_pin.py'):
            text = path.read_text(encoding='utf-8')
            for word in ('urllib', 'http.client', 'import socket', 'requests', 'curl', 'wget', 'https://'):
                self.assertNotIn(word, text, f'{path.name}: {word}')

    def test_party_core_never_imports_or_runs_node(self):
        for path in sorted((REPO_ROOT / 'avrana' / 'party').glob('*.py')) + sorted((REPO_ROOT / 'avrana' / 'web').glob('*.py')):
            text = path.read_text(encoding='utf-8')
            self.assertNotIn('node_runtime', text, path.name)
            self.assertNotIn('avrana-runtimes', text, path.name)


@unittest.skipUnless((FIXTURE / 'avrgame.json').is_file(), 'the Node fixture game is missing')
class FixtureTests(unittest.TestCase):
    """tests/fixtures/node-game: what the real-systemd proof installs. Here it is packed, unpacked
    and, where a `node` is on PATH, played over loopback by this test acting as the Party."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        tmp = Path(cls.tmp.name)
        cls.src = tmp / 'src'
        cls.src.mkdir()
        for name in ('avrgame.json', 'avrgame.build.json'):
            shutil.copy(FIXTURE / name, cls.src / name)
        for name in ('server', 'web'):
            shutil.copytree(FIXTURE / name, cls.src / name)
        shutil.copytree(FIXTURE / 'vendored', cls.src / 'node_modules')     # vendored: plain files, no npm
        cls.archive = tmp / 'hellonode.avrgame'
        cls.package = avrgame.pack_recipe(cls.src / 'avrgame.build.json', cls.archive)
        cls.unpacked = tmp / 'unpacked'
        avrgame.extract(cls.archive, cls.unpacked)

    def test_the_fixture_is_a_valid_node_package_and_builds_the_same_bytes_twice(self):
        self.assertEqual(self.package.id, 'hellonode')
        self.assertEqual(self.package.manifest['server'], {'interpreter': 'node', 'args': ['server/main.mjs']})
        self.assertEqual([f.path for f in self.package.files],
                         ['avrgame.json', 'node_modules/avr-fixture-dep/index.js', 'node_modules/avr-fixture-dep/lifecycle.cjs',
                          'node_modules/avr-fixture-dep/package.json', 'server/game.mjs', 'server/main.mjs', 'web/index.html'])
        again = avrgame.recipe_build(self.src / 'avrgame.build.json')
        self.assertEqual(hashlib.sha256(again).hexdigest(), self.package.sha256)
        scripts = json.loads((FIXTURE / 'vendored/avr-fixture-dep/package.json').read_text(encoding='utf-8'))['scripts']
        self.assertEqual(sorted(scripts), ['install', 'postinstall', 'preinstall'])      # the bait the installer must never take
        self.assertNotIn('hellonode', REPO)                           # the fixture is known only through its package

    def test_the_fixture_files_use_lf_and_no_nul(self):
        for path in sorted(p for p in FIXTURE.rglob('*') if p.is_file()):
            data = path.read_bytes()
            self.assertNotIn(b'\r', data, path.name)
            self.assertNotIn(b'\x00', data, path.name)

    @unittest.skipUnless(shutil.which('node'), 'no node on PATH (the real-systemd CI job runs the pinned build)')
    def test_a_real_node_serves_the_party_protocol_from_the_unpacked_package(self):
        key = protocol.new_key()
        reports = []

        class Party(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                reports.append((self.path, body))
                data = json.dumps({'ok': True, 'result': 'accepted'}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        party = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Party)
        threading.Thread(target=party.serve_forever, daemon=True).start()
        self.addCleanup(party.server_close)
        self.addCleanup(party.shutdown)
        env = {k: v for k, v in os.environ.items() if not k.startswith(('NODE_', 'npm_'))}
        proc = subprocess.Popen([shutil.which('node'), str(FIXTURE / 'dev-harness.mjs'), str(self.unpacked), key.hex(),
                                 str(party.server_address[1])], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, cwd=self.unpacked, env=env)

        def stop():
            proc.stdin.close()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(10)
            proc.stdout.close()
            proc.stderr.close()
        self.addCleanup(stop)
        line = proc.stdout.readline().decode()
        self.assertRegex(line, r'^listening [0-9]+\s*$', proc.stderr.read1(4000) if not line else '')
        port = int(line.split()[1])

        def call(method, path, body=None, headers=None):
            conn = http.client.HTTPConnection('127.0.0.1', port, timeout=20)
            try:
                data = None if body is None else json.dumps(body).encode()
                conn.request(method, '/games/hellonode' + path, body=data,
                             headers={**({'Content-Type': 'application/json'} if data is not None else {}), **(headers or {})})
                r = conn.getresponse()
                raw = r.read()
                return r.status, (json.loads(raw) if r.getheader('Content-Type', '').startswith('application/json') else raw)
            finally:
                conn.close()

        sid = 'session-' + 'ab' * 16
        ana, ben, cy = ('participant-' + c * 32 for c in 'abc')
        roster = [{'participant': ana, 'name': 'Ana', 'role': 'player'}, {'participant': ben, 'name': 'Ben', 'role': 'player'}]
        launch = protocol.launch_message(key, 'hellonode', sid, roster)
        self.assertEqual(call('GET', '/')[0], 200)                                       # health: the page is served
        self.assertEqual(call('GET', '/api/party'), (200, {'partyOrigin': None}))
        self.assertEqual(call('POST', '/avrana/session/v0/launch', {'message': launch}, {'X-Forwarded-For': '10.0.0.9'})[0], 404)
        self.assertEqual(call('POST', '/avrana/session/v0/launch', {'message': protocol.launch_message(protocol.new_key(), 'hellonode', sid, roster)})[0], 403)
        self.assertEqual(call('POST', '/avrana/session/v0/launch', {'message': launch}), (200, {'ok': True}))
        self.assertEqual(call('POST', '/avrana/session/v0/launch', {'message': launch})[0], 403)      # a replay

        def redeem(participant, role='player'):
            ticket = protocol.mint_ticket(key, 'hellonode', sid, participant, role)
            status, out = call('POST', '/api/redeem', {'ticket': ticket})
            self.assertEqual(status, 200, out)
            self.assertEqual(call('POST', '/api/redeem', {'ticket': ticket})[0], 403)    # single use
            return out
        a, b = redeem(ana), redeem(ben)
        self.assertEqual(a['token'], protocol.game_token(key, sid, ana))                 # the same token the Python side derives
        self.assertEqual({a['view']['seat'], b['view']['seat']}, {0, 1})
        self.assertNotEqual(a['view']['you']['secret'], b['view']['you']['secret'])
        self.assertNotIn(b['view']['you']['secret'], json.dumps(a['view']))
        watcher = redeem(cy, 'spectator')
        self.assertIsNone(watcher['view']['you'])
        for bad in (protocol.mint_ticket(key, 'hellonode', 'session-' + 'cd' * 16, ana, 'player'),
                    protocol.mint_ticket(key, 'hello', sid, ana, 'player'),
                    protocol.mint_ticket(protocol.new_key(), 'hellonode', sid, ana, 'player'),
                    protocol.mint_ticket(key, 'hellonode', sid, cy, 'player'), 'x' * 120):
            self.assertEqual(call('POST', '/api/redeem', {'ticket': bad})[0], 403)
        self.assertEqual(call('POST', '/api/greet', {'token': watcher['token'], 'text': 'hi'})[0], 403)
        self.assertEqual(call('POST', '/api/poll', {'token': 'x' * 44, 'since': 0})[0], 403)
        self.assertEqual(call('POST', '/api/greet', {'token': a['token'], 'text': 'hello from Ana'})[0], 200)
        status, out = call('POST', '/api/greet', {'token': a['token'], 'text': 'again'})
        self.assertEqual((status, out['error']), (409, 'already'))
        status, seen = call('POST', '/api/poll', {'token': b['token'], 'since': b['view']['v']})
        self.assertEqual([e['text'] for e in seen['view']['board']], ['hello from Ana'])
        status, out = call('POST', '/api/greet', {'token': b['token'], 'text': 'hello from Ben'})
        self.assertEqual((out['view']['over'], out['view']['result']), (True, {'greetings': 2}))
        for _ in range(100):
            if reports:
                break
            threading.Event().wait(0.1)
        self.assertEqual(len(reports), 1)
        path, body = reports[0]
        self.assertEqual(path, '/internal/party-session/v0/ended')
        ended = protocol.open_message(key, body['message'], 'ended', 'party', protocol.ReplayGuard())     # the Party's own check
        self.assertEqual((ended['iss'], ended['sid'], ended['outcome']), ('hellonode', sid, 'completed'))
        clean = result.check(ended['result'], 'hellonode', [ana, ben])                                    # and its result check
        self.assertEqual((clean['mode'], {s['standing'] for s in clean['standings']}, clean['data']),
                         ('cooperative', {'won'}, {'greetings': 2}))
        # the Party releases the reported session, then a second session is ended by the Host
        self.assertEqual(call('POST', '/avrana/session/v0/end', {'message': protocol.end_message(key, 'hellonode', sid)}), (200, {'ok': True}))
        sid2 = 'session-' + 'ef' * 16
        self.assertEqual(call('POST', '/avrana/session/v0/launch', {'message': protocol.launch_message(key, 'hellonode', sid2, roster)})[0], 200)
        token = call('POST', '/api/redeem', {'ticket': protocol.mint_ticket(key, 'hellonode', sid2, ana, 'player')})[1]['token']
        self.assertEqual(call('POST', '/avrana/session/v0/end', {'message': protocol.end_message(key, 'hellonode', sid)})[0], 403)
        self.assertEqual(call('POST', '/avrana/session/v0/end', {'message': protocol.end_message(key, 'hellonode', sid2)})[0], 200)
        self.assertEqual(call('POST', '/api/poll', {'token': token, 'since': 0})[0], 403)
        self.assertEqual(len(reports), 1)                             # an end by the Party is not reported back
        self.assertEqual(list(self.unpacked.rglob(LIFECYCLE_MARK)), [])


if __name__ == '__main__':
    unittest.main()
