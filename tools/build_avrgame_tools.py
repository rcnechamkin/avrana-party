#!/usr/bin/env python3
"""Build the EXPERIMENTAL `.avrgame` developer tools export (AVR-59).

    python tools/build_avrgame_tools.py --out DIR [--no-verify]

writes `DIR/avrana-avrgame-tools-experimental.1.zip` and `DIR/<same>.sha256` (`sha256sum` format):
the `.avrgame` validator and packer (`python -m avrana.avrgame validate|pack|inspect|extract`) with
exactly the files it needs, a README for an outside developer, a snapshot of the package format
description, a NOTICE and a MANIFEST.json with a hash for every file. Unpacked next to the Games
repository's developer kit bundle it lets a newcomer go from a kit-generated game to a `.avrgame`
file with only a stock Python 3. The command only writes a local file; it publishes nothing.

EXPERIMENTAL. Not an SDK; the package format and these tools carry no compatibility promise and
no signing. Format validation is not publisher trust.

What is in the export, and why (standard library only, nothing executed from the packages):

  copied unchanged (LF-normalised) from this repository
      avrana/avrgame/{__init__,archive,build,common,manifest,__main__}.py
      avrana/contracts/{strictjson,game,vocabulary}.py
      contracts/capabilities.v0.json    the public capability vocabulary a manifest author must use

  generated stand-ins, because the real modules carry more than the packer needs
      avrana/__init__.py            CONTRACTS_DIR only (the real one also names web and provider code)
      avrana/contracts/__init__.py  empty package marker
      avrana/party/__init__.py      empty package marker
      avrana/party/protocol.py      VERSION only: manifest.supported_requires() reads nothing else of
                                    the session protocol; the HMAC ticket implementation is NOT shipped
      avrana/party/result.py        SCHEMA only: likewise for the result envelope
      avrana/contracts/party_games.py  load() returning only {'bridge': {'protocol': ...}}: the one key the
                                    packer reads of the Party <-> Games declaration. The declaration file itself
                                    (internal routes, reference hashes) is NOT shipped

The build fails (it does not guess) when a shipped module imports anything that is not the standard
library or inside the export, or reads a name the stand-ins do not define: an in-repo change that
makes the packer need more has to decide here, deliberately, what to ship. The export is built
reproducibly (sorted entries, fixed timestamps, STORED, LF text, created-by Unix) and, unless
`--no-verify`, unpacked and exercised from a clean place: see `verify`.
"""
import argparse
import ast
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

EXPORT_FORMAT = 'avrana.avrgame-tools-export/experimental.1'
TOOLS_VERSION = 'experimental.1'
NAME = f'avrana-avrgame-tools-{TOOLS_VERSION}'
ZIP_NAME = f'{NAME}.zip'
FIXED_TIME = (1980, 1, 1, 0, 0, 0)
FILE_ATTR = (stat.S_IFREG | 0o644) << 16

# Copied unchanged (apart from LF line endings): repository path == export path.
COPIED = (
    'avrana/avrgame/__init__.py', 'avrana/avrgame/archive.py', 'avrana/avrgame/build.py',
    'avrana/avrgame/common.py', 'avrana/avrgame/manifest.py', 'avrana/avrgame/__main__.py',
    'avrana/contracts/strictjson.py', 'avrana/contracts/game.py', 'avrana/contracts/vocabulary.py',
    'contracts/capabilities.v0.json',
)
PROTOCOL_SOURCE = 'avrana/party/protocol.py'     # read for VERSION only; never shipped
RESULT_SOURCE = 'avrana/party/result.py'         # read for SCHEMA only; never shipped
PARTY_GAMES_JSON = 'contracts/party-games.v0.json'   # read for bridge.protocol only; never shipped
PARTY_GAMES_SOURCE = 'avrana/contracts/party_games.py'   # replaced by a stand-in; listed so a change marks the tree dirty
PROVISION_SOURCE = 'avrana/ops/provision_game.py'    # read for the community-tier ceilings (README text); never shipped
FORMAT_DOC = 'docs/design/AVRGAME-PACKAGE.md'
TEMPLATES = {'README.md': 'tools/avrgame-tools/README.md.in', 'NOTICE.md': 'tools/avrgame-tools/NOTICE.md.in'}
SELF = 'tools/build_avrgame_tools.py'

# What the generated stand-ins define, and so what shipped code may read from them.
SHIMMED = {'avrana.party.protocol': ('VERSION',), 'avrana.party.result': ('SCHEMA',),
           'avrana.contracts.party_games': ('load',)}
# What the stand-in party_games.load() returns; shipped code may subscript only down to a leaf (None) of this.
REDUCED_SHAPE = {'bridge': {'protocol': None}}

# Sections of the format note that the snapshot keeps, in order (by heading text).
KEEP_SECTIONS = ('What a package is', 'Archive', 'Manifest `avrgame.json`', 'Build recipe (developer convenience)',
                 'API and CLI')
DROPPED_PARAGRAPH = '**Run the tooling from the Party checkout, or from the experimental tools export.**'


class ExportError(Exception):
    """The export cannot be built or does not verify; the message names the file and the remedy."""


# ---- reading sources ---------------------------------------------------------------------------------

def lf(data):
    """Text with LF line endings whatever the checkout did to it (a Windows checkout may have CRLF), so
    the same commit gives the same bytes. Everything this export holds is UTF-8 text."""
    if b'\0' in data:
        raise ExportError('a NUL byte in a file that should be text')
    try:
        data.decode('utf-8')
    except UnicodeDecodeError:
        raise ExportError('a file that should be UTF-8 text is not') from None
    return data.replace(b'\r\n', b'\n')


def read_text_file(source, rel):
    try:
        return lf((Path(source) / rel).read_bytes())
    except OSError as exc:
        raise ExportError(f'{rel}: cannot read ({type(exc).__name__}); build from a complete checkout') from None
    except ExportError as exc:
        raise ExportError(f'{rel}: {exc}') from None


def input_paths():
    """Every repository file the export is made from (also what decides "dirty")."""
    return sorted({*COPIED, PROTOCOL_SOURCE, RESULT_SOURCE, PARTY_GAMES_JSON, PARTY_GAMES_SOURCE, PROVISION_SOURCE,
                   FORMAT_DOC, SELF, *TEMPLATES.values()})


def _const_eval(node):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Tuple):
        return tuple(_const_eval(e) for e in node.elts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mult, ast.Add)):
        left, right = _const_eval(node.left), _const_eval(node.right)
        return left * right if isinstance(node.op, ast.Mult) else left + right
    raise ValueError('not a constant expression')


def constants(text):
    """{NAME: value} for the module-level `NAME = <constant expression>` assignments of Python source."""
    out = {}
    for node in ast.parse(text).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                out[node.targets[0].id] = _const_eval(node.value)
            except (ValueError, TypeError):
                pass
    return out


def string_constant(text, name, where):
    value = constants(text).get(name)
    if not isinstance(value, str):
        raise ExportError(f'{where}: no string constant {name}; the export reads it for the stand-in module')
    return value


# ---- generated stand-ins ------------------------------------------------------------------------------

def generated_files(source):
    protocol_version = string_constant(read_text_file(source, PROTOCOL_SOURCE).decode(), 'VERSION', PROTOCOL_SOURCE)
    result_schema = string_constant(read_text_file(source, RESULT_SOURCE).decode(), 'SCHEMA', RESULT_SOURCE)
    declaration = json.loads(read_text_file(source, PARTY_GAMES_JSON))
    bridge_protocol = declaration.get('bridge', {}).get('protocol')
    if not isinstance(bridge_protocol, str):
        raise ExportError(f'{PARTY_GAMES_JSON}: no bridge.protocol string; the export reads it for the stand-in module')
    texts = {
        'avrana/__init__.py': (
            '"""Minimal `avrana` package root of the EXPERIMENTAL .avrgame developer tools export.\n\n'
            'Generated by tools/build_avrgame_tools.py in the Avrana Party repository; the rest of the platform\n'
            'is not part of this export. `contracts/` sits next to this directory.\n"""\n'
            'from pathlib import Path\n\n'
            'TOOLS_ROOT = Path(__file__).resolve().parent.parent\n'
            "CONTRACTS_DIR = TOOLS_ROOT / 'contracts'\n"),
        'avrana/contracts/__init__.py': (
            '"""Contract validators used by the .avrgame tools (the export ships only the ones they need)."""\n'),
        'avrana/party/__init__.py': (
            '"""Stand-ins for the two constants the .avrgame tools read from Party Core (generated; see protocol.py)."""\n'),
        'avrana/party/protocol.py': (
            '"""Stand-in for `avrana.party.protocol` in the EXPERIMENTAL .avrgame developer tools export.\n\n'
            'Generated. The .avrgame tools only need the session protocol\'s version string (to check a package\'s\n'
            '`requires.session`). The protocol implementation itself is not part of this export.\n"""\n'
            f'VERSION = {protocol_version!r}\n'),
        'avrana/contracts/party_games.py': (
            '"""Stand-in for `avrana.contracts.party_games` in the EXPERIMENTAL .avrgame developer tools export.\n\n'
            'Generated. The .avrgame tools only need the bridge protocol version string of the Party <-> Games\n'
            'declaration (to check a package\'s `requires.bridge`). The declaration file is not part of this export.\n"""\n'
            f'_DECLARATION = {{"bridge": {{"protocol": {bridge_protocol!r}}}}}\n\n\n'
            'def load(path=None):\n'
            '    return {"bridge": dict(_DECLARATION["bridge"])}\n'),
        'avrana/party/result.py': (
            '"""Stand-in for `avrana.party.result` in the EXPERIMENTAL .avrgame developer tools export.\n\n'
            'Generated. The .avrgame tools only need the game-result schema string (to check a package\'s\n'
            '`requires.result`). The result envelope implementation itself is not part of this export.\n"""\n'
            f'SCHEMA = {result_schema!r}\n'),
    }
    return {name: text.encode('utf-8') for name, text in texts.items()}


# ---- the format note ------------------------------------------------------------------------------------

_LINK = re.compile(r'\[([^\]]+)\]\((?!https?://)[^)\s]*\)')


def format_snapshot(doc, commit):
    """A faithful excerpt of the package format note, marked as a snapshot, without links into the repository."""
    lines = doc.decode('utf-8').split('\n')
    if not lines or not lines[0].startswith('# '):
        raise ExportError(f'{FORMAT_DOC}: expected a first-level title')
    status = [l for l in lines if l.startswith('- **Status:**')]
    freeze = [l for l in lines if l.startswith('**Freeze gates')]
    if len(status) != 1 or len(freeze) != 1:
        raise ExportError(f'{FORMAT_DOC}: expected one Status line and one "Freeze gates" paragraph')
    sections, current = {}, None
    for line in lines:
        if line.startswith('## '):
            current = line[3:].strip()
            sections[current] = [line]
        elif current is not None:
            sections[current].append(line)
    missing = [s for s in KEEP_SECTIONS if s not in sections]
    if missing:
        raise ExportError(f'{FORMAT_DOC}: section(s) {missing} not found; update KEEP_SECTIONS in {SELF}')
    dropped = [s for s in sections if s not in KEEP_SECTIONS]
    body = ['# `.avrgame` package format (EXPERIMENTAL): snapshot', '',
            f'> **Snapshot.** An excerpt of the Avrana Party repository\'s design note `{FORMAT_DOC}` taken from '
            f'source commit `{commit}`; it does not update itself. Sections left out (they describe the appliance '
            'installer and the issue tracker, not the file you build): ' + ', '.join(f'"{s}"' for s in dropped)
            + '. One paragraph about running the tools from a repository checkout is also left out. '
            'Links into the repository were removed, and file paths such as `avrana/party/protocol.py` name files '
            'of that repository, not of this export. `AVR-nnn` are ids in a private issue tracker. '
            '**The note is experimental: every name, field and limit may change without notice.**', '',
            status[0], '', freeze[0], '']
    for title in KEEP_SECTIONS:
        block = [l for l in sections[title] if not l.startswith(DROPPED_PARAGRAPH)]
        body.extend(block if block[-1] == '' else block + [''])
    text = _LINK.sub(r'\1', '\n'.join(body)).rstrip('\n') + '\n'
    return text.encode('utf-8')


# ---- README / NOTICE ------------------------------------------------------------------------------------

def template_values(source, files):
    """Placeholder values read from the shipped sources, so the README cannot disagree with the code."""
    common = constants(files['avrana/avrgame/common.py'].decode())
    manifest = constants(files['avrana/avrgame/manifest.py'].decode())
    game = constants(files['avrana/contracts/game.py'].decode())
    bridge = json.loads(read_text_file(source, PARTY_GAMES_JSON))['bridge']['protocol']
    unit = constants(read_text_file(source, PROVISION_SOURCE).decode()).get('COMMUNITY_UNIT')
    ceilings = dict(line.split('=', 1) for line in (unit or '').splitlines() if '=' in line and not line.startswith('#'))
    for key in ('MemoryMax', 'TasksMax', 'CPUQuota'):
        if not ceilings.get(key):
            raise ExportError(f'{PROVISION_SOURCE}: COMMUNITY_UNIT has no {key}=; the README states the ceilings')
    mib, kib = 1024 * 1024, 1024
    return {
        'NAME': NAME, 'TOOLS_VERSION': TOOLS_VERSION, 'FORMAT': common['FORMAT'], 'RECIPE_FORMAT': common['RECIPE_FORMAT'],
        'MAX_FILES': str(common['MAX_FILES']), 'MAX_FILE_MIB': str(common['MAX_FILE_BYTES'] // mib),
        'MAX_TOTAL_MIB': str(common['MAX_TOTAL_BYTES'] // mib), 'MAX_ARCHIVE_MIB': str(common['MAX_ARCHIVE_BYTES'] // mib),
        'MAX_MANIFEST_KIB': str(common['MAX_MANIFEST_BYTES'] // kib), 'MAX_NAME_LENGTH': str(common['MAX_NAME_LENGTH']),
        'MAX_DEPTH': str(common['MAX_DEPTH']), 'MAX_ARGS': str(manifest['MAX_ARGS']), 'MAX_ARG': str(manifest['MAX_ARG']),
        'PERMISSIONS': ', '.join(f'`{p}`' for p in game['PERMISSIONS']),
        'REQ_SESSION': string_constant(read_text_file(source, PROTOCOL_SOURCE).decode(), 'VERSION', PROTOCOL_SOURCE),
        'REQ_RESULT': string_constant(read_text_file(source, RESULT_SOURCE).decode(), 'SCHEMA', RESULT_SOURCE),
        'REQ_BRIDGE': bridge,
        'MEMORY_MAX': ceilings['MemoryMax'], 'TASKS_MAX': ceilings['TasksMax'], 'CPU_QUOTA': ceilings['CPUQuota'],
    }


def fill(template, values, where):
    text = re.sub(r'<!--.*?-->\n?', '', template.decode('utf-8'), flags=re.S)       # comments in a template are not shipped
    unknown = sorted(set(re.findall(r'\{\{([A-Z_]+)\}\}', text)) - set(values))
    if unknown:
        raise ExportError(f'{where}: unknown placeholder(s) {unknown}')
    for key, value in values.items():
        text = text.replace('{{' + key + '}}', value)
    return text.encode('utf-8')


# ---- the closure check -----------------------------------------------------------------------------------

def _module_name(path):
    parts = path[:-3].split('/')
    return '.'.join(parts[:-1] if parts[-1] == '__init__' else parts), parts[-1] == '__init__'


def defined_in_package(files, package):
    """Names a shipped package's `__init__.py` defines at module level (assigned, defined or imported)."""
    tree = ast.parse(files[package.replace('.', '/') + '/__init__.py'].decode('utf-8'))
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update((a.asname or a.name).split('.')[0] for a in node.names)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def check_closure(files, source):
    """Raise ExportError unless every import in the shipped Python (lazy ones included) is the standard library
    or a module that is in `files`, and every read from a stand-in module is a name the stand-in defines.
    `files` maps export paths to bytes; `source` is the repository root (to recognise a module left out)."""
    modules = {}
    for path in files:
        if path.endswith('.py'):
            name, is_pkg = _module_name(path)
            modules[name] = is_pkg
    problems = []

    def in_repo(dotted):
        base = Path(source).joinpath(*dotted.split('.'))
        return base.with_suffix('.py').exists() or base.is_dir()

    for path in sorted(files):
        if not path.endswith('.py'):
            continue
        here, is_pkg = _module_name(path)
        package = here if is_pkg else here.rpartition('.')[0]
        tree = ast.parse(files[path].decode('utf-8'), filename=path)
        bound = {}                                   # local name -> shimmed module
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                targets = [(a.name, ()) for a in node.names]
                for a in node.names:
                    if a.name in SHIMMED:
                        problems.append(f'{path}: `import {a.name}` is not understood; use `from {a.name.rpartition(".")[0]} import ...`')
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    parts = package.split('.') if package else []
                    if node.level - 1 > len(parts):
                        problems.append(f'{path}: relative import beyond the top-level package')
                        continue
                    base = '.'.join(parts[:len(parts) - (node.level - 1)])
                    module = f'{base}.{node.module}' if node.module else base
                else:
                    module = node.module or ''
                targets = [(module, tuple(a.name for a in node.names))]
                for a in node.names:
                    full = f'{module}.{a.name}'
                    if full in SHIMMED:
                        bound[a.asname or a.name] = full
                if module in SHIMMED:
                    for a in node.names:
                        if a.name not in SHIMMED[module]:
                            problems.append(f'{path}: reads {module}.{a.name}; the stand-in defines only {SHIMMED[module]}')
            else:
                continue
            for module, names in targets:
                top = module.split('.')[0]
                if top and top != 'avrana':
                    if top not in sys.stdlib_module_names:
                        problems.append(f'{path}: imports {module}, which is neither the standard library nor in the export')
                    continue
                if module not in modules:
                    problems.append(f'{path}: imports {module}, which is not in the export  '
                                    '[ship it deliberately in tools/build_avrgame_tools.py, or do not import it]')
                    continue
                for name in names:
                    full = f'{module}.{name}'
                    if full in modules:
                        continue
                    if in_repo(full):
                        problems.append(f'{path}: imports {full}, which is a module of the repository left out of the export')
                    elif modules[module] and name not in defined_in_package(files, module):
                        problems.append(f'{path}: imports {name} from {module}, which is neither a shipped module nor defined there')
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in bound:
                module = bound[node.value.id]
                if node.attr not in SHIMMED[module]:
                    problems.append(f'{path}: reads {module}.{node.attr}; the stand-in defines only {SHIMMED[module]}')
    for path in sorted(files):
        if not path.endswith('.py'):
            continue
        tree = ast.parse(files[path].decode('utf-8'), filename=path)
        here, is_pkg = _module_name(path)
        package = here if is_pkg else here.rpartition('.')[0]
        bound = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                base = node.module or ''
                if node.level:
                    parts = package.split('.') if package else []
                    base = '.'.join(parts[:len(parts) - (node.level - 1)] + ([node.module] if node.module else []))
                for a in node.names:
                    if f'{base}.{a.name}' == 'avrana.contracts.party_games':
                        bound[a.asname or a.name] = f'{base}.{a.name}'
        parents = {id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'load'
                    and isinstance(node.func.value, ast.Name) and node.func.value.id in bound):
                continue
            keys, current = [], node
            while isinstance(parents.get(id(current)), ast.Subscript) and parents[id(current)].value is current:
                current = parents[id(current)]
                keys.append(current.slice.value if isinstance(current.slice, ast.Constant) else None)
            shape = REDUCED_SHAPE
            for key in keys:
                shape = shape.get(key, 'missing') if isinstance(shape, dict) else 'missing'
                if shape == 'missing':
                    break
            if shape is not None:
                shown = ''.join('[' + repr(k) + ']' for k in keys)
                problems.append(f'{path}: reads party_games.load(){shown}; the stand-in holds only {REDUCED_SHAPE} '
                                'and must be read down to one of its values')
    for module in SHIMMED:
        if module not in modules:
            problems.append(f'stand-in {module} missing')
    if problems:
        raise ExportError('the export would not be self-contained:\n  ' + '\n  '.join(dict.fromkeys(problems)))


def check_syntax_floor(files):
    """The shipped Python parses with the Python 3.10 grammar (what is claimed; it is not a run on 3.10)."""
    for path, data in files.items():
        if path.endswith('.py'):
            try:
                ast.parse(data.decode('utf-8'), filename=path, feature_version=(3, 10))
            except SyntaxError as exc:
                raise ExportError(f'{path}: not valid for the Python 3.10 grammar ({exc.msg}, line {exc.lineno})') from None


# ---- the source commit --------------------------------------------------------------------------------------

def source_commit(source=REPO_ROOT):
    """(commit, dirty): the full HEAD of the repository whose top level IS `source` and True when any file the
    export is made from differs from it (or is untracked). ("unknown", None) when `source` is not a repository
    root (an enclosing repository's HEAD says nothing about these files) or git is not there."""
    source = Path(source).resolve()

    def git(*args):
        return subprocess.run(['git', *args], cwd=str(source), capture_output=True, text=True, timeout=60)
    try:
        top = git('rev-parse', '--show-toplevel')
        if top.returncode != 0 or Path(top.stdout.strip()).resolve() != source:
            return 'unknown', None
        head = git('rev-parse', 'HEAD')
        if head.returncode != 0 or not re.fullmatch(r'[0-9a-f]{40}', head.stdout.strip()):
            return 'unknown', None
        present = [p for p in input_paths() if (source / p).exists()]
        status = git('status', '--porcelain', '--', *present)
        if status.returncode != 0:
            return head.stdout.strip(), None
        return head.stdout.strip(), bool(status.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return 'unknown', None


# ---- collecting and writing ---------------------------------------------------------------------------------

def collect(source=REPO_ROOT, commit=None):
    """({export path: bytes}, {export path: origin}) for everything except MANIFEST.json. `commit` is the text
    shown in the format snapshot's header."""
    source = Path(source)
    files, origin = {}, {}
    for rel in COPIED:
        files[rel] = read_text_file(source, rel)
        origin[rel] = f'copied from {rel}'
    for rel, data in generated_files(source).items():
        files[rel] = data
        origin[rel] = 'generated stand-in'
    check_closure(files, source)
    check_syntax_floor(files)
    values = template_values(source, files)
    for out, rel in TEMPLATES.items():
        files[out] = fill(read_text_file(source, rel), values, rel)
        origin[out] = f'filled from {rel}'
    files['AVRGAME-PACKAGE-FORMAT.md'] = format_snapshot(read_text_file(source, FORMAT_DOC), commit or 'unknown')
    origin['AVRGAME-PACKAGE-FORMAT.md'] = f'excerpt of {FORMAT_DOC}'
    return files, origin


def manifest_bytes(files, origin, commit, dirty, values_source):
    common = constants(files['avrana/avrgame/common.py'].decode())
    manifest = {
        'export': EXPORT_FORMAT, 'tools_version': TOOLS_VERSION, 'experimental': True,
        'package_format': common['FORMAT'], 'recipe_format': common['RECIPE_FORMAT'],
        'requires_spoken': {'session': values_source['REQ_SESSION'], 'bridge': values_source['REQ_BRIDGE'],
                            'result': values_source['REQ_RESULT']},
        'source_commit': commit, 'source_dirty': dirty,
        'python': 'stock Python 3; verified on 3.12 only; the shipped code parses with the 3.10 grammar',
        'files': {name: {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'origin': origin[name]}
                  for name, data in sorted(files.items())},
    }
    return (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode('utf-8')


def zip_bytes(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as z:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(f'{NAME}/{name}', FIXED_TIME)
            info.create_system, info.external_attr, info.compress_type = 3, FILE_ATTR, zipfile.ZIP_STORED
            z.writestr(info, data)
    return buf.getvalue()


def build_bytes(source=REPO_ROOT, commit=None, dirty=None):
    """The zip as bytes. `commit`/`dirty` default to what git says about `source`."""
    if commit is None:
        commit, dirty = source_commit(source)
    files, origin = collect(source, commit)
    values = template_values(source, files)
    files = {**files, 'MANIFEST.json': manifest_bytes(files, origin, commit, dirty, values)}
    return zip_bytes(files)


def build(out_dir, source=REPO_ROOT, commit=None, dirty=None):
    """Write the zip and its checksum file; returns (zip path, checksum path, sha256 hex)."""
    data = build_bytes(source, commit, dirty)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / ZIP_NAME
    path.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    checksum = out_dir / f'{ZIP_NAME}.sha256'
    checksum.write_bytes(f'{digest}  {ZIP_NAME}\n'.encode('ascii'))
    return path, checksum, digest


def unpack(path, dest):
    """Unpack an export made by `build` into the NEW directory `dest`; returns the export root inside it."""
    dest = Path(dest).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        for name in names:
            target = (dest / name).resolve()
            if name.startswith('/') or '..' in name.split('/') or '\\' in name or dest not in target.parents:
                raise ExportError(f'unsafe entry {name!r}  [not an export this tool made]')
        z.extractall(dest)
    roots = {n.split('/')[0] for n in names}
    if roots != {NAME}:
        raise ExportError(f'{path}: expected the single top-level directory {NAME}, found {sorted(roots)}')
    return dest / NAME


# ---- the fixture game ---------------------------------------------------------------------------------------

def fixture_game(dest, root_manifest):
    """Write a minimal valid game package tree into `dest` (new or empty) and return its recipe path.
    `root_manifest` supplies format and requires (read from the export's own sources)."""
    dest = Path(dest)
    contract = {
        'contract': 'avrana.game/v0', 'id': 'toolsfixture', 'name': 'Tools export fixture',
        'summary': 'A minimal game used to exercise the packer.', 'kind': 'native',
        'players': {'min': 1, 'max': 4}, 'screen': 'no_tv_needed', 'input': {'model': 'browser_native'},
        'late_join': 'spectator_only', 'spectators': 'watch', 'private_player_ui': True,
        'runtime': {'type': 'external', 'start': 'service', 'permissions': ['party_roster']},
        'presentations': [{'id': 'phone_table', 'method': 'browser_native', 'roles': ['player', 'spectator'],
                           'requires': {'device': []}}],
        'fallback': 'spectate', 'accessibility': {'timing_pressure': False, 'audio_required': False},
    }
    manifest = {
        'format': root_manifest['format'], 'game': contract,
        'package': {'version': '0.1.0', 'publisher': 'Tools export fixture', 'license': 'MIT'},
        'requires': root_manifest['requires'],
        'server': {'interpreter': 'python3', 'args': ['-m', 'fixturegame']},
        'client': {'root': 'fixturegame/web'},
    }
    recipe = {'recipe': root_manifest['recipe'], 'manifest': 'avrgame.json', 'root': '.', 'include': ['fixturegame']}
    tree = {
        'fixturegame/__init__.py': '', 'fixturegame/__main__.py': 'print("fixture")\n',
        'fixturegame/web/index.html': '<!doctype html><title>fixture</title>\n',
        'avrgame.json': json.dumps(manifest, indent=2) + '\n', 'avrgame.build.json': json.dumps(recipe, indent=2) + '\n',
    }
    for rel, text in tree.items():
        p = dest / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode('utf-8'))
    return dest / 'avrgame.build.json'


# ---- verification ---------------------------------------------------------------------------------------------

TRACE = '''
import contextlib, io, json, sys
from avrana.avrgame import __main__ as m
codes = []
for argv in json.loads(sys.argv[1]):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        codes.append(m.main(argv))
mods = {n: getattr(sys.modules[n], "__file__", None) for n in sys.modules if n == "avrana" or n.startswith("avrana.")}
print(json.dumps({"codes": codes, "modules": mods}))
'''

_DROP_ENV = ('PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'PYTHONSAFEPATH', 'PYTHONINSPECT', 'PYTHONOPTIMIZE',
             'LISTEN_PID', 'LISTEN_FDS', 'AVRANA_PARTY_KEYS', 'AVRANA_PARTY_SOCKET', 'AVRANA_PARTY_ORIGIN')


def clean_env(pythonpath=None):
    env = {k: v for k, v in os.environ.items() if k not in _DROP_ENV}
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'
    if pythonpath is not None:
        env['PYTHONPATH'] = str(pythonpath)
    return env


def run_tool(args, cwd, env, extra=()):
    """Run `python -m avrana.avrgame ARGS` (or `python -c ...` with `extra`); returns CompletedProcess."""
    cmd = [sys.executable, *(extra or ['-m', 'avrana.avrgame']), *map(str, args)]
    return subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True, timeout=180)


def verify(zip_path, say=print, source=REPO_ROOT):
    """Check a written export from a clean place. Returns a list of problems (empty when it is good).

    Checks: the checksum file; every file against MANIFEST.json (and nothing extra); then, with PYTHONPATH and
    friends cleared, from the unpacked directory (outside any repository): `--help`; a real validate, pack,
    inspect and extract round trip on a minimal fixture game; the modules the tool really loaded are exactly the
    modules shipped; the packed bytes, the `inspect --json` text, the `requires` it speaks and the refusal of a
    deliberately broken manifest are identical to what THIS repository's own tool produces for the same input."""
    problems = []
    zip_path = Path(zip_path)
    want = (zip_path.with_name(zip_path.name + '.sha256')).read_text(encoding='ascii').split()[0]
    if hashlib.sha256(zip_path.read_bytes()).hexdigest() != want:
        return [f'{zip_path.name} does not match its .sha256  [rebuild]']
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        root = unpack(zip_path, tmp / 'unpacked')
        listed = json.loads((root / 'MANIFEST.json').read_text(encoding='utf-8'))
        on_disk = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()} - {'MANIFEST.json'}
        if on_disk != set(listed['files']):
            problems.append(f'files differ from MANIFEST.json: {sorted(on_disk ^ set(listed["files"]))}')
        for name, info in listed['files'].items():
            if (root / name).is_file() and hashlib.sha256((root / name).read_bytes()).hexdigest() != info['sha256']:
                problems.append(f'{name} differs from MANIFEST.json')
        if problems:
            return problems
        env = clean_env()
        ref_env = clean_env(source)
        probe = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=str(root), capture_output=True, text=True)
        if probe.returncode == 0:
            problems.append(f'the temporary directory {root} is inside a git repository ({probe.stdout.strip()}); '
                            'run the verification from outside any repository (set TMPDIR)')
            return problems

        helped = run_tool(['--help'], root, env)
        if helped.returncode != 0 or 'validate' not in helped.stdout or 'pack' not in helped.stdout:
            problems.append(f'`python -m avrana.avrgame --help` failed from the unpacked export: {helped.stderr.strip()[:300]}')
            return problems
        elsewhere = tmp / 'elsewhere'
        elsewhere.mkdir()
        via_path = run_tool(['--help'], elsewhere, clean_env(root))
        if via_path.returncode != 0:
            problems.append('`--help` with PYTHONPATH set to the unpacked export and another working directory failed')

        spoken = run_tool([], root, env, extra=['-c', 'import json, avrana.avrgame as a; print(json.dumps(a.supported_requires(), sort_keys=True))'])
        ref_spoken = run_tool([], elsewhere, ref_env, extra=['-c', 'import json, avrana.avrgame as a; print(json.dumps(a.supported_requires(), sort_keys=True))'])
        if spoken.returncode != 0 or spoken.stdout != ref_spoken.stdout:
            problems.append(f'the export speaks other `requires` values than this repository: {spoken.stdout.strip()} vs {ref_spoken.stdout.strip()}')
            return problems
        spoken_requires = {k: v[0] for k, v in json.loads(spoken.stdout).items()}
        common = constants((root / 'avrana/avrgame/common.py').read_text(encoding='utf-8'))
        game = tmp / 'game'
        recipe = fixture_game(game, {'format': common['FORMAT'], 'recipe': common['RECIPE_FORMAT'], 'requires': spoken_requires})

        tool_env = clean_env(root)                  # the export on the path, run from a directory that is not it

        def both(args):
            return run_tool(args, game, tool_env), run_tool(args, game, ref_env)

        for label, args in (('validate (recipe)', ['validate', recipe]), ('pack', ['pack', recipe, '--out', tmp / 'mine.avrgame'])):
            mine = run_tool(args, game, tool_env)
            if mine.returncode != 0:
                problems.append(f'{label} failed from the unpacked export: {mine.stderr.strip()[:300]}')
                return problems
        ref_pack = run_tool(['pack', recipe, '--out', tmp / 'ref.avrgame'], game, ref_env)
        if ref_pack.returncode != 0:
            return problems + [f'this repository\'s own tool failed on the fixture: {ref_pack.stderr.strip()[:300]}']
        if (tmp / 'mine.avrgame').read_bytes() != (tmp / 'ref.avrgame').read_bytes():
            problems.append('the packed bytes differ between the export and this repository\'s tool')
        mine, ref = both(['inspect', tmp / 'mine.avrgame', '--json'])
        if mine.returncode != 0 or mine.stdout != ref.stdout:
            problems.append('`inspect --json` differs between the export and this repository\'s tool')
        mine, ref = both(['validate', tmp / 'mine.avrgame'])
        if mine.returncode != 0 or mine.stdout != ref.stdout:
            problems.append('`validate` of the packed file differs between the export and this repository\'s tool')
        done = run_tool(['extract', tmp / 'mine.avrgame', tmp / 'extracted'], game, tool_env)
        if done.returncode != 0 or not (tmp / 'extracted/fixturegame/__main__.py').is_file():
            problems.append(f'`extract` failed from the unpacked export: {done.stderr.strip()[:300]}')

        broken = json.loads((game / 'avrgame.json').read_text(encoding='utf-8'))
        broken['format'] = 'avrana.avrgame/nope'
        broken['signature'] = 'x'
        (game / 'avrgame.json').write_text(json.dumps(broken), encoding='utf-8')
        mine, ref = both(['validate', recipe])
        if mine.returncode != 1 or (mine.returncode, mine.stderr) != (ref.returncode, ref.stderr):
            problems.append('the refusal of a broken manifest differs between the export and this repository\'s tool')

        (game / 'avrgame.json').write_text(json.dumps({**broken, 'format': common['FORMAT']}), encoding='utf-8')
        traced = run_tool([json.dumps([['validate', str(recipe)], ['pack', str(recipe), '--out', str(tmp / 't.avrgame')],
                                       ['inspect', str(tmp / 'mine.avrgame')], ['inspect', str(tmp / 'mine.avrgame'), '--json'],
                                       ['extract', str(tmp / 'mine.avrgame'), str(tmp / 'extracted2')],
                                       ['validate', str(tmp / 'mine.avrgame')]])], root, env, extra=['-c', TRACE])
        if traced.returncode != 0:
            problems.append(f'tracing the tool failed: {traced.stderr.strip()[:300]}')
            return problems
        data = json.loads(traced.stdout)
        shipped = {_module_name(n)[0] for n in listed['files'] if n.endswith('.py')}
        loaded = set(data['modules'])
        if loaded != shipped:
            problems.append(f'modules loaded {sorted(loaded - shipped)} are not shipped; modules shipped but never loaded: {sorted(shipped - loaded)}')
        for module, path in data['modules'].items():
            if not path or not Path(os.path.realpath(path)).is_relative_to(os.path.realpath(root)):
                problems.append(f'{module} was loaded from {path}, outside the unpacked export')
    return problems


# ---- command line ---------------------------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--out', required=True, help='directory for the zip and its .sha256 (created if missing)')
    ap.add_argument('--no-verify', action='store_true', help='skip unpacking and exercising the export')
    args = ap.parse_args(argv)
    try:
        path, checksum, digest = build(args.out)
        commit, dirty = source_commit()
        print(f'{path}\n{checksum}\nsha256: {digest}\nsource_commit: {commit}{" (dirty)" if dirty else ""}')
        if not args.no_verify:
            problems = verify(path)
            if problems:
                for problem in problems:
                    print(f'FAIL  {problem}', file=sys.stderr)
                return 1
            print('verified: unpacked, exercised from a clean place, identical to this repository\'s tool')
    except ExportError as exc:
        print(f'build_avrgame_tools: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
