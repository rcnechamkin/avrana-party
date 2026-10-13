#!/usr/bin/env python3
"""Build the EXPERIMENTAL `.avrgame` developer tools export (AVR-59).

    python tools/build_avrgame_tools.py --out DIR [--no-verify] [--allow-dirty] [--force]

writes `DIR/avrana-avrgame-tools-experimental.1.zip` and `DIR/<same>.sha256` (`sha256sum` format):
the `.avrgame` validator and packer (`python -m avrana.avrgame validate|pack|inspect|extract`) with
exactly the files they need, a README for an outside developer, a snapshot of the package format
description, a NOTICE and a MANIFEST.json with a hash for every file. Unpacked next to the Games
repository's developer kit bundle it lets a newcomer go from a kit-generated game to a `.avrgame`
file with only a stock Python 3. The command only writes a local file; it publishes nothing, and
CI does not keep the zip (it prints the sha256 and the file list).

EXPERIMENTAL. Not an SDK; the package format and these tools carry no compatibility promise and
no signing. Format validation is not publisher trust.

What is in the export (standard library only; nothing from a package is ever executed):

  code copied from this repository: the code is unchanged, LF-normalised
      avrana/avrgame/{__init__,archive,build,common,manifest,__main__}.py
      avrana/contracts/{strictjson,game,vocabulary}.py
    Comments and docstrings that name internal material (the deny list below) are removed from the
    exported copy only, by `tokenize` and `ast` (whole comment blocks, and the flagged sentences of a
    docstring). The build PROVES the code did not change: both trees, with every docstring stripped, must
    have an identical `ast.dump`; and a module that reads its own `__doc__` (the CLI's help text) must not
    have had its docstring touched at all. MANIFEST.json flags every file that was scrubbed.

  generated stand-ins, because the real modules carry more than the packer needs
      avrana/__init__.py            CONTRACTS_DIR only
      avrana/contracts/__init__.py, avrana/party/__init__.py   empty package markers
      avrana/party/protocol.py      VERSION only (the HMAC ticket implementation is NOT shipped)
      avrana/party/result.py        SCHEMA only
      avrana/contracts/party_games.py  load() returning only {'bridge': {'protocol': ...}}
      contracts/capabilities.v0.json   the capability NAMES the validator accepts; probes, labels and
                                    summaries are placeholders (shipped code reads only the names)

What the build guarantees, and what it does not. The closure check is a STATIC check on the parsed shipped
code: every import (lazy ones included) is the standard library or a shipped module; `__import__`, `eval`,
`exec`, `importlib`/`runpy`, `sys.modules` and `from x import *` are refused; a stand-in module may only be
used as `module.NAME` for a name it defines (no aliasing, no `getattr`), and `party_games.load()` may only be
subscripted down to the bridge protocol; the vocabulary's labels, summaries and probes are never read outside
vocabulary.py. It does NOT prove what the code does at run time, and it cannot see code reached through
`getattr` with computed names, `open()` of a file, or a third-party import hidden in a string. The run-time
side is covered by `verify`: the unpacked tool is exercised from a clean place and its output compared
byte for byte with this repository's tool. A content gate then refuses any shipped file that matches the deny
list unless the match is allow-listed line by line (and the allow-list is printed in NOTICE.md).
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
import textwrap
import tokenize
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

EXPORT_FORMAT = 'avrana.avrgame-tools-export/experimental.1'
TOOLS_REVISION = 1
TOOLS_VERSION = f'experimental.{TOOLS_REVISION}'
NAME = f'avrana-avrgame-tools-{TOOLS_VERSION}'
ZIP_NAME = f'{NAME}.zip'
FIXED_TIME = (1980, 1, 1, 0, 0, 0)
FILE_ATTR = (stat.S_IFREG | 0o644) << 16

# What this revision of the tools speaks. If the code's idea of any of these moves, a different tool carries the
# same file name, so the build FAILS until TOOLS_REVISION is bumped and this tuple updated together.
SPEAKS = {
    'package_format': 'avrana.avrgame/experimental.1',
    'recipe_format': 'avrana.avrgame-build/experimental.1',
    'session': 'avrana.party-session/v0',
    'bridge': 'avrana.party-bridge/v1',
    'result': 'avrana.game-result/v1',
}

# Code copied from the repository (LF-normalised, internal comments and docstrings scrubbed).
COPIED = (
    'avrana/avrgame/__init__.py', 'avrana/avrgame/archive.py', 'avrana/avrgame/build.py',
    'avrana/avrgame/common.py', 'avrana/avrgame/manifest.py', 'avrana/avrgame/__main__.py',
    'avrana/contracts/strictjson.py', 'avrana/contracts/game.py', 'avrana/contracts/vocabulary.py',
)
PROTOCOL_SOURCE = 'avrana/party/protocol.py'       # read for VERSION only; never shipped
RESULT_SOURCE = 'avrana/party/result.py'           # read for SCHEMA only; never shipped
PARTY_GAMES_JSON = 'contracts/party-games.v0.json'     # read for bridge.protocol only; never shipped
PARTY_GAMES_SOURCE = 'avrana/contracts/party_games.py'     # replaced by a stand-in; listed so a change marks the tree dirty
CAPABILITIES_JSON = 'contracts/capabilities.v0.json'   # read for the names only; a reduced copy is shipped
PROVISION_SOURCE = 'avrana/ops/provision_game.py'  # read for the community-tier ceilings (README text); never shipped
FORMAT_DOC = 'docs/design/AVRGAME-PACKAGE.md'
TEMPLATES = {'README.md': 'tools/avrgame-tools/README.md.in', 'NOTICE.md': 'tools/avrgame-tools/NOTICE.md.in'}
SELF = 'tools/build_avrgame_tools.py'

# What the generated stand-ins define, and so what shipped code may read from them.
SHIMMED = {'avrana.party.protocol': ('VERSION',), 'avrana.party.result': ('SCHEMA',),
           'avrana.contracts.party_games': ('load',)}
# What the stand-in party_games.load() returns; shipped code may subscript only down to a leaf (None) of this.
REDUCED_SHAPE = {'bridge': {'protocol': None}}
BANNED_NAMES = ('__import__', 'eval', 'exec')
BANNED_MODULES = ('importlib', 'runpy', 'imp')

# Sections of the format note that the snapshot keeps, in order (by heading text).
KEEP_SECTIONS = ('What a package is', 'Archive', 'Manifest `avrgame.json`', 'Build recipe (developer convenience)',
                 'API and CLI')
DROPPED_PARAGRAPH = '**Run the tooling from the Party checkout, or from the experimental tools export.**'
# Exact phrases of the note that name internal material; each must occur exactly once, so a changed note fails the build.
SNAPSHOT_SUBSTITUTIONS = (
    ('(grant, tier, sandbox, ADR 0016)', '(grant, tier, sandbox)'),
    ('each must equal what this Party implements (read from `avrana/party/protocol.py`, `avrana/party/result.py` and '
     '`contracts/party-games.v0.json`)', 'each must equal a value this Party implements (listed in the README)'),
)
NEUTRAL_DOCSTRING = 'EXPERIMENTAL; not frozen; may change without notice.'

# ---- the content gate ------------------------------------------------------------------------------------------------

I = re.IGNORECASE
DENY = (
    (r'AVR-\d+', 0), (r'ADR \d+', 0), (r'\bBLUFF\b', I), (r'\bEXPO\b', I), (r'Spades', I), (r'Gauntlet', I),
    (r'Checkers', I), (r'RetroArch', I), (r'libretro', I), (r'LAN[ _]Games', I), (r'Raspberry', I), (r'\bPi\b', 0),
    (r'H\.264', I), (r'/etc/', 0), (r'/opt/', 0), (r'/var/', 0), (r'/run/', 0), (r'10\.\d+\.\d+\.\d+', 0),
    (r'192\.168\.', 0), (r'\.local\b', I), (r'avrana\.net', I), (r'docs/(design|research|findings|runbooks|adr)/', 0),
    (r'\bops/', 0), (r'deploy/', 0), (r'PRIVATE KEY', 0), (r'cnechamkin|rcnechamkin|BEACNpool', I),
    # beyond the owner's list: in-repo paths and branch names that would only confuse an outsider
    (r'appliance\.py', 0), (r'contracts/README', 0), (r'\bexperiments?/', 0), (r'\btests/', 0), (r'\btools/', 0),
    (r'web/party', 0), (r'\.md\.in\b', 0),
)
DENY_RX = [(src, re.compile(src, flags)) for src, flags in DENY]

# A deny match that the tool genuinely needs. Matched line by line (file, deny pattern, the line); an entry that no
# longer matches anything fails the build, so the list cannot go stale. `describe` is printed in NOTICE.md under
# "Things this export reveals about the platform" and is itself gated, so it must not repeat the matched text.
ALLOW = (
    dict(file='avrana/contracts/game.py', deny=r'LAN[ _]Games', line=r'an emulated game is not a LAN Games module',
         describe='one validation message of the Game Contract check names the platform\'s older built-in game runtime',
         reason='the message is output of the validator; the exported tool must print what the in-repo tool prints'),
    dict(file='avrana/contracts/game.py', deny=r'LAN[ _]Games', line=r"lan_games_module|runtime\.lan_games",
         describe="the Game Contract validator names the platform's older built-in game runtime type (an accepted value of "
                  "`runtime.type`) and its capability",
         reason='an enum value and capability name the validator checks; changing the code would change behaviour'),
    dict(file='avrana/contracts/game.py', deny=r'RetroArch', line=r"runtime\.retroarch",
         describe='the Game Contract validator names an emulator runtime capability',
         reason='a capability name the validator checks; changing the code would change behaviour'),
    dict(file='contracts/capabilities.v0.json', deny=r'RetroArch', line=r'"runtime\.retroarch"',
         describe='the capability names include the name of an emulator runtime capability',
         reason='capability names are the vocabulary a manifest may use, and the validator\'s unknown-name message lists them'),
    dict(file='contracts/capabilities.v0.json', deny=r'LAN[ _]Games', line=r'"runtime\.lan_games"',
         describe='the capability names include the name of the platform\'s older built-in game runtime',
         reason='same: a name of the vocabulary'),
    dict(file='contracts/capabilities.v0.json', deny=r'\.local\b', line=r'"storage\.local"',
         describe='the capability names include a browser storage capability',
         reason='same: a name of the vocabulary; the match is only the name\'s suffix'),
)


class ExportError(Exception):
    """The export cannot be built or does not verify; the message names the file and the remedy."""


def content_gate(files, skip=()):
    """(problems, used): every deny-list match in the text of `files` that is not allow-listed, and the indexes
    of the ALLOW entries that were used."""
    problems, used = [], set()
    for path in sorted(files):
        if path in skip:
            continue
        for number, line in enumerate(files[path].decode('utf-8').split('\n'), 1):
            for source, rx in DENY_RX:
                if not rx.search(line):
                    continue
                for index, entry in enumerate(ALLOW):
                    if entry['file'] == path and entry['deny'] == source and re.search(entry['line'], line):
                        used.add(index)
                        break
                else:
                    problems.append(f'{path}:{number}: matches the deny pattern {source!r}: {line.strip()[:100]}')
    return problems, used


# ---- reading sources ---------------------------------------------------------------------------------------------------

def lf(data):
    """Text with LF line endings whatever the checkout did to it (CRLF, or a lone CR), so the same commit gives the
    same bytes. Everything this export holds is UTF-8 text."""
    if b'\0' in data:
        raise ExportError('a NUL byte in a file that should be text')
    try:
        data.decode('utf-8')
    except UnicodeDecodeError:
        raise ExportError('a file that should be UTF-8 text is not') from None
    return data.replace(b'\r\n', b'\n').replace(b'\r', b'\n')


def read_text_file(source, rel):
    try:
        return lf((Path(source) / rel).read_bytes())
    except OSError as exc:
        raise ExportError(f'{rel}: cannot read ({type(exc).__name__}); build from a complete checkout') from None
    except ExportError as exc:
        raise ExportError(f'{rel}: {exc}') from None


def input_paths():
    """Every repository file the export is made from (also what decides "dirty")."""
    return sorted({*COPIED, PROTOCOL_SOURCE, RESULT_SOURCE, PARTY_GAMES_JSON, PARTY_GAMES_SOURCE, CAPABILITIES_JSON,
                   PROVISION_SOURCE, FORMAT_DOC, SELF, *TEMPLATES.values()})


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


# ---- scrubbing copied code -------------------------------------------------------------------------------------------

def flagged(text):
    return any(rx.search(text) for _, rx in DENY_RX)


def scrub_docstring(value):
    """The docstring without its flagged parentheticals and sentences; only paragraphs that contain a flagged
    phrase are touched (and re-wrapped), the others are kept byte for byte. A first paragraph that vanishes is
    replaced by a neutral sentence. Escaped so it can be written back as a triple-quoted literal."""
    out, first_dropped = [], False
    for index, paragraph in enumerate(re.split(r'\n[ \t]*\n', value)):
        if not flagged(paragraph):
            out.append(paragraph)
            continue
        text = ' '.join(paragraph.split())
        text = re.sub(r'\s*\(([^()]*)\)', lambda m: '' if flagged(m.group(1)) else m.group(0), text)
        sentences = [s for s in re.split(r'(?<=[.!?])\s+', text) if s and not flagged(s)]
        if sentences:
            out.append(textwrap.fill(' '.join(sentences), width=100))
        elif index == 0:
            first_dropped = True
    if not out or first_dropped:
        out.insert(0, NEUTRAL_DOCSTRING)
    return '\n\n'.join(out).replace('\\', '\\\\').replace('"""', '\\"\\"\\"')


def _docstring_nodes(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                yield node, first


def scrub_python(text, path='<module>'):
    """(scrubbed text, stats) for Python source: flagged comment blocks removed, flagged docstring parts removed."""
    tree = ast.parse(text, filename=path)
    if not text.isascii() and flagged(text):
        raise ExportError(f'{path}: non-ASCII source with flagged text cannot be scrubbed; extend scrub_python')
    lines = text.split('\n')
    stats = {'comment_blocks': 0, 'docstrings': 0}
    # docstrings (replaced in place, last first so positions stay valid)
    edits = []
    for _, expr in _docstring_nodes(tree):
        value = expr.value.value
        if flagged(value):
            edits.append((expr, scrub_docstring(value)))
    for expr, new in sorted(edits, key=lambda e: (e[0].lineno, e[0].col_offset), reverse=True):
        indent = ' ' * expr.col_offset
        body = new.replace('\n', '\n' + (indent if expr.col_offset else ''))
        first, last = expr.lineno - 1, expr.end_lineno - 1
        lines[first:last + 1] = [lines[first][:expr.col_offset] + '"""' + body + '"""' + lines[last][expr.end_col_offset:]]
        stats['docstrings'] += 1
    # comments (positions are of the ORIGINAL lines, so recompute on the edited text)
    text = '\n'.join(lines)
    comment_lines, trailing, comment_only = set(), {}, set()
    split = text.split('\n')
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type != tokenize.COMMENT:
            continue
        row, col = tok.start
        whole_line = split[row - 1][:col].strip() == ''
        if whole_line:
            comment_only.add(row - 1)
        if flagged(tok.string):
            if whole_line:
                comment_lines.add(row - 1)
            else:
                trailing[row - 1] = col
    lines = split
    drop = set()
    for i in comment_lines:                       # the whole contiguous block around a flagged comment line
        j = i
        while j - 1 in comment_only:
            j -= 1
        k = i
        while k + 1 in comment_only:
            k += 1
        drop.update(range(j, k + 1))
    stats['comment_blocks'] = len([1 for i in sorted(drop) if i - 1 not in drop]) + len(trailing)
    for i, col in trailing.items():
        lines[i] = lines[i][:col].rstrip()
    lines = [l for i, l in enumerate(lines) if i not in drop]
    return '\n'.join(lines), stats


def strip_docstrings(tree):
    for node, _ in list(_docstring_nodes(tree)):
        node.body = node.body[1:] or [ast.Pass()]
    return tree


def prove_same_code(original, scrubbed, path):
    """Raise ExportError unless the two sources have identical code: equal `ast.dump` once every docstring is
    stripped, unflagged docstrings untouched, and a module that reads `__doc__` has its docstring untouched."""
    a, b = ast.parse(original, filename=path), ast.parse(scrubbed, filename=path)
    compile(scrubbed, path, 'exec')
    docs_a = [e.value.value for _, e in _docstring_nodes(a)]
    docs_b = [e.value.value for _, e in _docstring_nodes(b)]
    if len(docs_a) != len(docs_b):
        raise ExportError(f'{path}: scrubbing changed the number of docstrings')
    for before, after in zip(docs_a, docs_b):
        if before != after and not flagged(before):
            raise ExportError(f'{path}: scrubbing changed a docstring that names nothing internal')
        if flagged(after):
            raise ExportError(f'{path}: a docstring still names internal material after scrubbing')
    if ast.dump(strip_docstrings(a)) != ast.dump(strip_docstrings(b)):
        raise ExportError(f'{path}: scrubbing changed the code (the ASTs differ once docstrings are stripped)')
    uses_doc = any((isinstance(n, ast.Name) and n.id == '__doc__') or (isinstance(n, ast.Attribute) and n.attr == '__doc__')
                   for n in ast.walk(ast.parse(original)))
    if uses_doc and docs_a and docs_a[0] != docs_b[0]:
        raise ExportError(f'{path}: reads __doc__ at run time (help text) but its docstring would change')


# ---- generated stand-ins ----------------------------------------------------------------------------------------------

def reduced_vocabulary(source):
    """The capability vocabulary with the real NAMES and placeholder probes, labels and summaries."""
    doc = json.loads(read_text_file(source, CAPABILITIES_JSON))
    out = {'schema': doc['schema'],
           'note': 'Reduced copy for the .avrgame developer tools: the capability names only. Probes, labels and '
                   'summaries are placeholders.',
           'device': {}, 'runtime': {}}
    for scope in ('device', 'runtime'):
        for name in doc[scope]:
            entry = {'summary': 'Placeholder summary.', 'label': 'Placeholder label.', 'missing': 'Placeholder text.'}
            out[scope][name] = {'probe': 'presence', **entry} if scope == 'device' else entry
    return (json.dumps(out, indent=2) + '\n').encode('utf-8')


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
            'Generated. The rest of the platform is not part of this export. `contracts/` sits next to this directory.\n"""\n'
            'from pathlib import Path\n\n'
            'TOOLS_ROOT = Path(__file__).resolve().parent.parent\n'
            "CONTRACTS_DIR = TOOLS_ROOT / 'contracts'\n"),
        'avrana/contracts/__init__.py': (
            '"""Contract validators used by the .avrgame tools (the export ships only the ones they need)."""\n'),
        'avrana/party/__init__.py': (
            '"""Stand-ins for the version strings the .avrgame tools read (generated; see protocol.py)."""\n'),
        'avrana/party/protocol.py': (
            '"""Stand-in for `avrana.party.protocol` in the EXPERIMENTAL .avrgame developer tools export.\n\n'
            'Generated. The .avrgame tools only need the session protocol\'s version string (to check a package\'s\n'
            '`requires.session`). The protocol implementation itself is not part of this export.\n"""\n'
            f'VERSION = {protocol_version!r}\n'),
        'avrana/contracts/party_games.py': (
            '"""Stand-in for `avrana.contracts.party_games` in the EXPERIMENTAL .avrgame developer tools export.\n\n'
            'Generated. The .avrgame tools only need the bridge protocol version string (to check a package\'s\n'
            '`requires.bridge`). The declaration it comes from is not part of this export.\n"""\n'
            f'_DECLARATION = {{"bridge": {{"protocol": {bridge_protocol!r}}}}}\n\n\n'
            'def load(path=None):\n'
            '    return {"bridge": dict(_DECLARATION["bridge"])}\n'),
        'avrana/party/result.py': (
            '"""Stand-in for `avrana.party.result` in the EXPERIMENTAL .avrgame developer tools export.\n\n'
            'Generated. The .avrgame tools only need the game-result schema string (to check a package\'s\n'
            '`requires.result`). The result envelope implementation itself is not part of this export.\n"""\n'
            f'SCHEMA = {result_schema!r}\n'),
    }
    files = {name: text.encode('utf-8') for name, text in texts.items()}
    files[CAPABILITIES_JSON] = reduced_vocabulary(source)
    return files


# ---- the format note ------------------------------------------------------------------------------------------------

_LINK = re.compile(r'\[([^\]]+)\]\((?!https?://)[^)\s]*\)')


def format_snapshot(doc, commit):
    """A faithful excerpt of the package format note, marked as a snapshot, without links into the repository, its
    freeze-gate bookkeeping, tracker ids or other internal references."""
    lines = doc.decode('utf-8').split('\n')
    if not lines or not lines[0].startswith('# '):
        raise ExportError(f'{FORMAT_DOC}: expected a first-level title')
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
    body = ['# `.avrgame` package format (EXPERIMENTAL): snapshot', '',
            f'> **Snapshot** of the package format description of the Avrana Party project, taken at source commit '
            f'`{commit}`; it does not update itself. Sections about the appliance installer and about work not yet '
            'done are left out, and so is one paragraph about running the tools from a repository checkout. '
            '**Experimental; not frozen; may change without notice.**', '',
            '- **Status:** **EXPERIMENTAL; not frozen; may change without notice.** The format string is '
            '`avrana.avrgame/experimental.1`. Every name, field and limit here may change.', '']
    for title in KEEP_SECTIONS:
        block = [l for l in sections[title] if not l.startswith(DROPPED_PARAGRAPH)]
        body.extend(block if block[-1] == '' else block + [''])
    text = _LINK.sub(r'\1', '\n'.join(body))
    for old, new in SNAPSHOT_SUBSTITUTIONS:
        if text.count(old) != 1:
            raise ExportError(f'{FORMAT_DOC}: the phrase {old[:50]!r} is not there exactly once; update SNAPSHOT_SUBSTITUTIONS')
        text = text.replace(old, new)
    return (text.rstrip('\n') + '\n').encode('utf-8')


# ---- README / NOTICE ------------------------------------------------------------------------------------------------

def template_values(source, files):
    """Placeholder values read from the sources, so the README cannot disagree with the code."""
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


def revealed_text(used):
    if not used:
        return '- Nothing beyond the deny list\'s own scope was found to need an exception.'
    return '\n'.join(f'- {ALLOW[i]["describe"]}.' for i in sorted(used))


# ---- the closure check ---------------------------------------------------------------------------------------------------

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
    """Raise ExportError unless the shipped Python is self-contained. See the module docstring for what this does and
    does not guarantee. `files` maps export paths to bytes; `source` is the repository root (to recognise a module that
    was left out)."""
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
        parents = {id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
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
                if any(a.name == '*' for a in node.names):
                    problems.append(f'{path}: `from {module} import *` hides what is used')
                targets = [(module, tuple(a.name for a in node.names))]
                for a in node.names:
                    if f'{module}.{a.name}' in SHIMMED:
                        bound[a.asname or a.name] = f'{module}.{a.name}'
                if module in SHIMMED:
                    for a in node.names:
                        if a.name not in SHIMMED[module]:
                            problems.append(f'{path}: reads {module}.{a.name}; the stand-in defines only {SHIMMED[module]}')
            else:
                targets = []
                if isinstance(node, ast.Name) and node.id in BANNED_NAMES:
                    problems.append(f'{path}: uses {node.id}, which would hide an import or code from this check')
                elif (isinstance(node, ast.Attribute) and node.attr == 'modules' and isinstance(node.value, ast.Name)
                      and node.value.id == 'sys'):
                    problems.append(f'{path}: uses sys.modules')
                continue
            for module, names in targets:
                top = module.split('.')[0]
                if top in BANNED_MODULES:
                    problems.append(f'{path}: imports {module}, which can load code this check cannot see')
                    continue
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
                    if full in modules or name == '*':
                        continue
                    if in_repo(full):
                        problems.append(f'{path}: imports {full}, which is a module of the repository left out of the export')
                    elif modules[module] and name not in defined_in_package(files, module):
                        problems.append(f'{path}: imports {name} from {module}, which is neither a shipped module nor defined there')
        for node in ast.walk(tree):
            # a stand-in module may only appear as the base of `module.NAME` with NAME it defines: no aliases, no getattr
            if isinstance(node, ast.Name) and node.id in bound and isinstance(node.ctx, ast.Load):
                parent = parents.get(id(node))
                if not (isinstance(parent, ast.Attribute) and parent.value is node):
                    problems.append(f'{path}: uses the stand-in module {bound[node.id]} other than as `{node.id}.NAME`')
                elif parent.attr not in SHIMMED[bound[node.id]]:
                    problems.append(f'{path}: reads {bound[node.id]}.{parent.attr}; the stand-in defines only {SHIMMED[bound[node.id]]}')
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'load'
                    and isinstance(node.func.value, ast.Name) and bound.get(node.func.value.id) == 'avrana.contracts.party_games'):
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
            if path != 'avrana/contracts/vocabulary.py':
                # the vocabulary stand-in has real names and placeholder labels, summaries and probes
                if isinstance(node, ast.Attribute) and node.attr in ('label', 'missing'):
                    problems.append(f'{path}: reads .{node.attr} of the capability vocabulary, which holds placeholders')
                if isinstance(node, ast.Attribute) and node.attr in ('device', 'runtime'):
                    parent = parents.get(id(node))
                    if (isinstance(parent, ast.Attribute) and parent.attr in ('items', 'values')) or \
                            (isinstance(parent, ast.Subscript) and parent.value is node):
                        problems.append(f'{path}: reads capability entries beyond their names ({node.attr})')
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


def check_speaks(files, source):
    """The versions the tools speak must be the ones SPEAKS records for this TOOLS_REVISION."""
    common = constants(files['avrana/avrgame/common.py'].decode())
    actual = {
        'package_format': common['FORMAT'], 'recipe_format': common['RECIPE_FORMAT'],
        'session': string_constant(read_text_file(source, PROTOCOL_SOURCE).decode(), 'VERSION', PROTOCOL_SOURCE),
        'bridge': json.loads(read_text_file(source, PARTY_GAMES_JSON))['bridge']['protocol'],
        'result': string_constant(read_text_file(source, RESULT_SOURCE).decode(), 'SCHEMA', RESULT_SOURCE),
    }
    if actual != SPEAKS:
        raise ExportError(f'the tools now speak {actual}, not {SPEAKS}: a different tool would carry the file name '
                          f'{ZIP_NAME}. Bump TOOLS_REVISION and update SPEAKS in {SELF} together')
    return hashlib.sha256(json.dumps(actual, sort_keys=True).encode()).hexdigest()[:12]


# ---- the source commit --------------------------------------------------------------------------------------------------

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


# ---- collecting and writing ----------------------------------------------------------------------------------------------

def collect(source=REPO_ROOT, commit=None):
    """({export path: bytes}, {export path: info}, speaks digest, used allow-list entries) for everything except
    MANIFEST.json. `commit` is the text shown in the format snapshot's header."""
    source = Path(source)
    files, info = {}, {}
    for rel in COPIED:
        original = read_text_file(source, rel).decode('utf-8')
        scrubbed, stats = scrub_python(original, rel)
        prove_same_code(original, scrubbed, rel)
        files[rel] = scrubbed.encode('utf-8')
        info[rel] = {'origin': 'copied; code unchanged', 'scrubbed': scrubbed != original,
                     'comment_blocks_removed': stats['comment_blocks'], 'docstrings_scrubbed': stats['docstrings']}
    for rel, data in generated_files(source).items():
        files[rel] = data
        info[rel] = {'origin': 'generated stand-in' if rel.endswith('.py') else 'generated: names of the real file, placeholders for the rest'}
    check_closure(files, source)
    check_syntax_floor(files)
    digest = check_speaks(files, source)
    values = template_values(source, files)
    files['README.md'] = fill(read_text_file(source, TEMPLATES['README.md']), values, TEMPLATES['README.md'])
    info['README.md'] = {'origin': 'written for this export'}
    files['AVRGAME-PACKAGE-FORMAT.md'] = format_snapshot(read_text_file(source, FORMAT_DOC), commit or 'unknown')
    info['AVRGAME-PACKAGE-FORMAT.md'] = {'origin': 'excerpt of the project\'s format note'}
    problems, used = content_gate(files)
    if problems:
        raise ExportError('the export names internal material (add it to ALLOW only if the tool needs it):\n  '
                          + '\n  '.join(problems))
    files['NOTICE.md'] = fill(read_text_file(source, TEMPLATES['NOTICE.md']), {**values, 'REVEALED': revealed_text(used)},
                              TEMPLATES['NOTICE.md'])
    info['NOTICE.md'] = {'origin': 'written for this export'}
    return files, info, digest, used


def manifest_bytes(files, info, commit, dirty, digest, values):
    manifest = {
        'export': EXPORT_FORMAT, 'tools_version': TOOLS_VERSION, 'speaks_digest': digest, 'experimental': True,
        'package_format': SPEAKS['package_format'], 'recipe_format': SPEAKS['recipe_format'],
        'requires_spoken': {k: SPEAKS[k] for k in ('session', 'bridge', 'result')},
        'source_commit': commit, 'source_dirty': dirty,
        'python': 'stock Python 3; verified on 3.12 only; the shipped code parses with the 3.10 grammar',
        'files': {name: {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), **info[name]}
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
    files, info, digest, used = collect(source, commit)
    manifest = manifest_bytes(files, info, commit, dirty, digest, None)
    final = {**files, 'MANIFEST.json': manifest}
    problems, used_final = content_gate(final)
    everything = set(range(len(ALLOW)))
    if problems or used_final != used or used_final != everything:
        stale = [ALLOW[i]['file'] + ' ' + ALLOW[i]['deny'] for i in sorted(everything - used_final)]
        raise ExportError('the finished export names internal material, or ALLOW has entries that match nothing:\n  '
                          + '\n  '.join(problems + stale or ['(allow-list changed)']))
    return zip_bytes(final)


def zip_name(dirty):
    if dirty is False:
        return ZIP_NAME
    return f'{NAME}-{"dirty" if dirty else "unverified"}.zip'


def build(out_dir, source=REPO_ROOT, commit=None, dirty=None, allow_dirty=False, force=False):
    """Write the zip and its checksum file; returns (zip path, checksum path, sha256 hex). Refuses an output
    directory inside the repository, a dirty or unverifiable tree (unless `allow_dirty`, which adds a suffix to the
    file name) and replacing a different file (unless `force`)."""
    if commit is None:
        commit, dirty = source_commit(source)
    if dirty is not False and not allow_dirty:
        raise ExportError('the source tree is ' + ('dirty (files this export is made from differ from HEAD)' if dirty
                                                  else 'not a clean repository checkout')
                          + '; commit first, or pass --allow-dirty (the file name then says so)')
    out_dir = Path(out_dir).resolve()
    root = Path(source).resolve()
    if out_dir == root or root in out_dir.parents:
        raise ExportError(f'--out {out_dir} is inside the repository; write the export outside it')
    data = build_bytes(source, commit, dirty)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / zip_name(dirty)
    digest = hashlib.sha256(data).hexdigest()
    checksum = out_dir / f'{path.name}.sha256'
    line = f'{digest}  {path.name}\n'.encode('ascii')
    for target, content in ((path, data), (checksum, line)):
        if target.exists() and target.read_bytes() != content and not force:
            raise ExportError(f'{target} exists with different content; remove it or pass --force')
    path.write_bytes(data)
    checksum.write_bytes(line)
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


# ---- the fixture game ---------------------------------------------------------------------------------------------------

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


# ---- verification ---------------------------------------------------------------------------------------------------------

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

    Checks: the checksum file; every file against MANIFEST.json (and nothing extra); the content gate on the unpacked
    files; then, with PYTHONPATH and friends cleared, from the unpacked directory (outside any repository): `--help`;
    a real validate, pack, inspect and extract round trip on a minimal fixture game; the modules the tool really
    loaded are exactly the modules shipped; the packed bytes, the `inspect --json` text, the `requires` it speaks and
    the refusal of a deliberately broken manifest are identical to what THIS repository's own tool produces for the
    same input."""
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
        gate, _ = content_gate({p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()})
        if gate:
            return ['the unpacked export names internal material:'] + gate
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
        ref_help = run_tool(['--help'], elsewhere, ref_env)
        if via_path.stdout != ref_help.stdout:
            problems.append('`--help` text differs between the export and this repository\'s tool')

        code = 'import json, avrana.avrgame as a; print(json.dumps(a.supported_requires(), sort_keys=True))'
        spoken = run_tool([], root, env, extra=['-c', code])
        ref_spoken = run_tool([], elsewhere, ref_env, extra=['-c', code])
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


# ---- command line ------------------------------------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--out', required=True, help='directory for the zip and its .sha256 (outside the repository)')
    ap.add_argument('--no-verify', action='store_true', help='skip unpacking and exercising the export')
    ap.add_argument('--allow-dirty', action='store_true', help='build from a tree that differs from HEAD (the file name says so)')
    ap.add_argument('--force', action='store_true', help='replace an existing file with different content')
    args = ap.parse_args(argv)
    try:
        path, checksum, digest = build(args.out, allow_dirty=args.allow_dirty, force=args.force)
        commit, dirty = source_commit()
        with zipfile.ZipFile(path) as z:
            listing = [(i.filename[len(NAME) + 1:], i.file_size) for i in z.infolist()]
            manifest = json.loads(z.read(f'{NAME}/MANIFEST.json'))
        print(f'{path}\n{checksum}\nsha256: {digest}\nsource_commit: {commit}{" (dirty)" if dirty else ""}\nfiles:')
        for name, size in listing:
            sha = manifest['files'].get(name, {}).get('sha256', '-' * 64)
            print(f'  {size:>7}  {sha[:16]}  {name}')
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
