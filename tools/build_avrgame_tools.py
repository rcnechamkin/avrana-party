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
      avrana/avrgame/{__init__,archive,build,common,manifest,node,__main__}.py
      avrana/contracts/{strictjson,game,vocabulary}.py
    Comments and docstrings that name internal material (the DENY list below) are removed from the
    exported copy only, by `tokenize` and `ast` (whole comment blocks, and the flagged sentences of a
    docstring; unflagged text, a shebang and an encoding cookie are kept byte for byte). The build PROVES the
    code did not change: both trees, with every docstring stripped, must have an identical `ast.dump`; and if
    any shipped module reads docstrings at run time (the CLI's help text reads its own `__doc__`), the build
    fails when any docstring anywhere was scrubbed, unless that reader reads only its own docstring and is
    byte-identical. MANIFEST.json flags every file that was scrubbed.

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
byte for byte with this repository's tool. A content gate then refuses any shipped file that matches the DENY list
(internal material) or the PLATFORM list (platform vocabulary the tools genuinely ship) unless the place is declared
in ALLOW; NOTICE.md prints that declaration, generated from ALLOW. The gate is a deny list: it is NOT a proof that
nothing else about the platform is in the export, and NOTICE.md says so. The tests run a second, separately
written pattern set over the shipped files with the same rule.
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
TOOLS_REVISION = 2
TOOLS_VERSION = f'experimental.{TOOLS_REVISION}'
NAME = f'avrana-avrgame-tools-{TOOLS_VERSION}'
ZIP_NAME = f'{NAME}.zip'
FIXED_TIME = (1980, 1, 1, 0, 0, 0)
FILE_ATTR = (stat.S_IFREG | 0o644) << 16

# What this revision of the tools speaks. If the code's idea of any of these moves, a different tool carries the
# same file name, so the build FAILS until TOOLS_REVISION is bumped and this dict updated together. The version
# strings are named here; everything else the README states or the validator enforces (the limits, the permission
# names, the interpreter names, the community-tier ceilings, the capability names) is folded into SPEAKS_DIGEST.
SPEAKS = {
    'package_format': 'avrana.avrgame/experimental.1',
    'recipe_format': 'avrana.avrgame-build/experimental.1',
    'session': 'avrana.party-session/v0',
    'bridge': 'avrana.party-bridge/v1',
    'result': 'avrana.game-result/v1',
}
SPEAKS_DIGEST = '80d21bea6809'

# Code copied from the repository (LF-normalised, internal comments and docstrings scrubbed).
COPIED = (
    'avrana/avrgame/__init__.py', 'avrana/avrgame/archive.py', 'avrana/avrgame/build.py',
    'avrana/avrgame/common.py', 'avrana/avrgame/manifest.py', 'avrana/avrgame/node.py', 'avrana/avrgame/__main__.py',
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
    ('an installer (later lane) stages it', "the appliance owner's installer stages it"),
    ('each must equal what this Party implements (read from `avrana/party/protocol.py`, `avrana/party/result.py` and '
     '`contracts/party-games.v0.json`)', 'each must equal a value this Party implements (listed in the README)'),
)
NEUTRAL_DOCSTRING = 'EXPERIMENTAL; not frozen; may change without notice.'

# ---- the content gate ------------------------------------------------------------------------------------------------
#
# The gate is a DENY LIST: it can only find what it was told to look for. It is not a proof that nothing else about the
# platform is in the export. Two lists:
#   DENY      internal material (tracker ids, other games, hardware, paths, addresses, people, internal vocabulary of
#             comments). Comments and docstrings that match are removed from the exported copy (see scrub_python).
#   PLATFORM  vocabulary of the platform that the tools genuinely ship (it is in code strings and enums that the
#             validator checks, so it cannot be removed without changing what it accepts or says). It is never
#             scrubbed; every place it appears must be DECLARED in ALLOW, and NOTICE.md is generated from ALLOW.

I = re.IGNORECASE
DENY = (
    (r'\bAVR-\d+', I), (r'\bADR[- ]?\d+', I), (r'\bBLUFF\b', I), (r'\bEXPO\b', I), (r'Spades', I), (r'Gauntlet', I),
    (r'Checkers', I), (r'RetroArch', I), (r'libretro', I), (r'LAN[ _]Games', I), (r'Raspberry', I), (r'\bPi\b', 0),
    (r'H\.264', I), (r'/etc/', 0), (r'/opt/', 0), (r'/var/', 0), (r'/run/', 0), (r'10\.\d+\.\d+\.\d+', 0),
    (r'192\.168\.', 0), (r'\.local\b', I), (r'avrana\.net', I), (r'docs/(design|research|findings|runbooks|adr)/', 0),
    (r'\bops/', 0), (r'deploy/', 0), (r'PRIVATE KEY', 0), (r'cnechamkin|rcnechamkin|BEACNpool', I),
    # beyond the owner's list: in-repo paths and branch names that would only confuse an outsider
    (r'appliance\.py', 0), (r'contracts/README', 0), (r'\bexperiments?/', 0), (r'\btests/', 0), (r'\btools/', 0),
    (r'web/party', 0), (r'\.md\.in\b', 0),
    # internal bookkeeping words that only comments and docstrings used
    (r'freeze[- ]gates?', I), (r'\b(later |separate )?lanes?\b', I), (r'default: the repository', I), (r'party service', I),
)
PLATFORM = (
    (r'install[-_]game', I), (r'(run as|owned by) root', I), (r'RESERVED_IDS|home, party, admin', 0),
    (r'\bemulat\w*|\barcade\b|emulator_(profile|slot)|host_rendering|hw_encoder|\bhdmi\b', I),
    (r'linux/(arm64|amd64)', 0), (r'/usr/bin/', 0), (r'lift_manifest_v0|shared_video', 0), (r'\bTUF\b', 0),
    (r'net\.avrana', I), (r'\b[0-9a-f]{40}\b', 0),
    (r'webrtc|video\.h264|wake_lock|webgpu|presentation\.(shared_stream|personal_viewport|tv)|input\.virtual_gamepad|'
     r'runtime\.(lan_games|retroarch)', I),
)
DENY_RX = [(src, re.compile(src, flags)) for src, flags in DENY]
GATE_RX = DENY_RX + [(src, re.compile(src, flags)) for src, flags in PLATFORM]
NOTICE_NAME = 'NOTICE.md'

# Every place where a DENY or PLATFORM pattern matches in a shipped file and is meant to stay. The gate matches line by
# line: an entry covers a line of one of its files when its `line` regex matches. An entry that matches nothing fails the build (unless `optional`), so the list cannot go
# stale, and each `terms` string must occur in a line the entry covers. `describe` and `terms` are printed in NOTICE.md
# under "Things this export reveals about the platform": this list IS the declaration; nothing else is.
FORMAT_NOTE = 'AVRGAME-PACKAGE-FORMAT.md'
CAPABILITY_LINE = (r'webrtc|video\.h264|wake_lock|webgpu|presentation\.|input\.virtual_gamepad|runtime\.(lan_games|retroarch)|'
                   r'storage\.local|runtime_caps')
ALLOW = (
    dict(files=('README.md',), line=r'install-game|owned by root', terms=('install-game', 'owned by root'),
         describe="the name of the platform's installer command (run by the appliance owner as root on the appliance; "
                  "`README.md` says so) and the fact that an installed package's files are owned by root:",
         reason='documentation of the conditions a game runs under; the README states them on purpose'),
    dict(files=('avrana/contracts/game.py', 'avrana/avrgame/manifest.py'), line=r'RESERVED_IDS|home, party, admin', spans=(r'RESERVED_IDS', r'home, party, admin'),
         terms=('home', 'party', 'admin', 'shared', 'diag', 'api'),
         describe='the game ids the platform reserves for itself (a game may not use them; the validator refuses and '
                  'its message lists them):',
         reason='a constant and a message of the validator; changing the code would change what it accepts and prints'),
    dict(files=('avrana/contracts/game.py', 'avrana/avrgame/manifest.py', 'README.md', FORMAT_NOTE),
         line=r'emulat|arcade|lan_games_module|LAN Games', spans=(r'emulat\w*', r'arcade', r'lan_games_module', r'LAN Games'),
         terms=('emulated', 'emulator_profile', 'lan_games_module', 'arcade', 'LAN Games', 'emulation'),
         describe='the other kinds of game and runtime that the Game Contract validator knows (the packer refuses all of '
                  'them; only a native game can be packaged): emulated games, an emulator profile runtime, arcade '
                  "games, and the platform's older built-in game server, written \"LAN Games\" in one message and "
                  '`lan_games_module` as a runtime type:',
         reason='enum values and messages of the Game Contract validator; changing the code would change behaviour'),
    dict(files=('avrana/contracts/game.py',), line=r'RESOURCES', terms=('emulator_slot', 'hw_encoder', 'host_rendering', 'hdmi'),
         describe='the names of the hardware-related resources that a Game Contract may list (the validator accepts '
                  'them; the packer refuses every game that would use them):',
         reason='a constant of the Game Contract validator; changing the code would change what it accepts'),
    dict(files=('avrana/contracts/game.py',), line=r'linux/(arm64|amd64)', terms=('linux/arm64', 'linux/amd64'),
         describe='the CPU platforms that `package.platforms` may name:',
         reason='a constant and a message of the validator; changing the code would change what it accepts'),
    dict(files=('avrana/avrgame/__init__.py', 'avrana/avrgame/manifest.py', FORMAT_NOTE), line=r'/usr/bin/',
         terms=('/usr/bin/python3',),
         describe="the path of the appliance's Python interpreter, which `server.interpreter: python3` stands for:",
         reason='a constant of the manifest validator and its documentation; changing the code would change behaviour'),
    dict(files=('avrana/avrgame/manifest.py',), line=r'/opt/avrana-runtimes',
         terms=('/opt/avrana-runtimes',),
         describe="the directory of the appliance's optional Node.js runtime, which `server.interpreter: node` stands "
                  'for (one pinned official build, named after its version; an appliance may not have it):',
         reason='a constant of the manifest validator; changing the code would change behaviour'),
    dict(files=('avrana/contracts/game.py',), line=r'lift_manifest_v0|shared_video', terms=('lift_manifest_v0', 'shared_video'),
         describe="a converter from the platform's earlier, pre-contract game manifest (`lift_manifest_v0`, not used by the "
                  'packer; it is still in the Game Contract module) and that earlier manifest\'s `shared_video` flag:',
         reason='code of the Game Contract module, copied unchanged; the verdicts of the exported tool do not depend on it, '
                'but removing it would make the copied code differ from the in-repo code'),
    dict(files=('avrana/contracts/game.py', 'avrana/contracts/vocabulary.py', 'README.md', 'contracts/capabilities.v0.json'),
         line=CAPABILITY_LINE,
         terms=('webrtc', 'video.h264', 'wake_lock', 'webgpu', 'storage.local', 'input.virtual_gamepad',
                'presentation.shared_stream', 'presentation.personal_viewport.crop',
                'presentation.personal_viewport.dedicated_stream', 'presentation.tv', 'runtime.lan_games',
                'runtime.retroarch'),
         describe='the capability names a presentation may require. All of them are in the README table with a one-line '
                  'meaning and in `contracts/capabilities.v0.json`; those that say something about the platform itself '
                  '(streams, a TV, a virtual gamepad, two older runtimes) or about the phone are:',
         reason='the vocabulary of capability names the validator checks, and the table that gives each its meaning'),
    dict(files=('avrana/contracts/game.py',), line=r'\bTUF\b', terms=('TUF',),
         describe="one validation message about `package.version` names a software-update framework as the reason the "
                  'version is display-only:',
         reason='the message is output of the validator; the exported tool must print what the in-repo tool prints'),
    dict(files=('avrana/contracts/game.py',), line=r'net\.avrana', terms=('net.avrana.example',),
         describe="one validation message about extension keys gives an example name in the platform's reverse-DNS "
                  'namespace:',
         reason='the message is output of the validator; the exported tool must print what the in-repo tool prints'),
    dict(files=('MANIFEST.json', FORMAT_NOTE), line=r'source_commit|source commit', terms=(), spans=(r'\b[0-9a-f]{40}\b',), optional=True,
         describe="the full commit id of the private repository that this export was built from (`source_commit` in "
                  '`MANIFEST.json`, and in the header of the format snapshot).',
         reason='provenance: the manifest says exactly which source the files are made from'),
)


class ExportError(Exception):
    """The export cannot be built or does not verify; the message names the file and the remedy."""


def _declared_spans(entry, line):
    """(start, end) of every occurrence in `line` of a declared term or span of the entry."""
    expressions = [re.escape(term) for term in entry['terms']] + list(entry.get('spans', ()))
    return [m.span() for rx in expressions for m in re.finditer(rx, line, re.IGNORECASE)]


def _covers(entry, path, line, span):
    """The entry declares the matched text: the file and line fit, and the whole match lies inside one declared term
    (so an exempted line cannot also carry some other, undeclared match)."""
    return (path in entry['files'] and re.search(entry['line'], line) is not None
            and any(start <= span[0] and span[1] <= end for start, end in _declared_spans(entry, line)))


def content_gate(files, skip=()):
    """(problems, used): every DENY or PLATFORM match in the text of `files` that is not declared in ALLOW, and the
    indexes of the ALLOW entries that were used. A declaration covers only the matched text, not its line. NOTICE.md
    is checked separately (it is where the declaration is printed): see `collect`."""
    problems, used = [], set()
    for path in sorted(files):
        if path in skip:
            continue
        for number, line in enumerate(files[path].decode('utf-8').splitlines(), 1):
            for source, rx in GATE_RX:
                for match in rx.finditer(line):
                    covering = {i for i, entry in enumerate(ALLOW) if _covers(entry, path, line, match.span())}
                    used |= covering
                    if not covering:
                        problems.append(f'{path}:{number}: matches the pattern {source!r} ({match.group()!r}): '
                                        f'{line.strip()[:100]}')
    return problems, used


def unseen_terms(files):
    """Declared terms (ALLOW entry, term) that occur in none of the lines the entry covers: a declaration that has
    gone stale or never matched what it names."""
    seen = set()
    for path, data in files.items():
        for line in data.decode('utf-8').splitlines():
            for index, entry in enumerate(ALLOW):
                if path in entry['files'] and re.search(entry['line'], line):
                    seen.update((index, term) for term in entry['terms'] if term in line)
    return [f'{ALLOW[i]["files"][0]}: declared term {term!r} occurs in no covered line'
            for i, entry in enumerate(ALLOW) if not entry.get('optional') for term in entry['terms'] if (i, term) not in seen]


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


def scrub_docstring(value, indent=''):
    """The docstring without its flagged parentheticals and sentences. Only paragraphs that contain a flagged phrase are
    touched (and re-wrapped, at the indentation they had); every other paragraph and every blank line is kept byte
    for byte. A first paragraph that vanishes is replaced by a neutral sentence. `indent` is the indentation of the
    docstring's own lines, used when a flagged one-line paragraph has to be wrapped. Escaped so it can be written
    back as a triple-quoted literal."""
    parts = re.split(r'(\n[ \t]*\n)', value)
    paragraphs, separators = parts[0::2], parts[1::2]
    out, first_dropped = [], False                       # out: [separator before, text]
    for index, paragraph in enumerate(paragraphs):
        separator = separators[index - 1] if index else ''
        if not flagged(paragraph):
            out.append([separator, paragraph])
            continue
        lines = paragraph.split('\n')
        lead = re.match(r'[ \t]*', lines[0]).group() if index else ''
        follow = re.match(r'[ \t]*', lines[1]).group() if len(lines) > 1 and lines[1].strip() else (lead or indent)
        tail = paragraph[len(paragraph.rstrip()):]
        text = ' '.join(paragraph.split())
        text = re.sub(r'\s*\(([^()]*)\)', lambda m: '' if flagged(m.group(1)) else m.group(0), text)
        sentences = [x for x in re.split(r'(?<=[.!?])\s+', text) if x and not flagged(x)]
        if sentences:
            out.append([separator, textwrap.fill(' '.join(sentences), width=100, initial_indent=lead,
                                                 subsequent_indent=follow) + tail])
        elif index == 0:
            first_dropped = True
    if not out or first_dropped:
        out.insert(0, ['', NEUTRAL_DOCSTRING])
        if len(out) > 1:
            out[1][0] = out[1][0] or '\n\n'
    elif out[0][0]:
        out[0][0] = ''
    return ''.join(sep + text for sep, text in out).replace('\\', '\\\\').replace('"""', '\\"\\"\\"')


def _docstring_nodes(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                yield node, first


CODING_COOKIE = re.compile(r'^[ \t\f]*#.*?coding[:=][ \t]*[-\w.]+')


def _is_header_comment(row, text):
    """A shebang on line 1 or an encoding cookie on line 1 or 2: these mean something to the interpreter."""
    return (row == 1 and text.startswith('#!')) or (row <= 2 and CODING_COOKIE.match(text) is not None)


def scrub_python(text, path='<module>'):
    """(scrubbed text, stats) for Python source: flagged comment blocks removed, flagged docstring parts removed.
    A shebang and an encoding cookie are never removed (a build error if one is flagged)."""
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
            edits.append((expr, scrub_docstring(value, ' ' * expr.col_offset)))
    for expr, new in sorted(edits, key=lambda e: (e[0].lineno, e[0].col_offset), reverse=True):
        first, last = expr.lineno - 1, expr.end_lineno - 1
        lines[first:last + 1] = [lines[first][:expr.col_offset] + '"""' + new + '"""' + lines[last][expr.end_col_offset:]]
        stats['docstrings'] += 1
    # comments (positions are of the ORIGINAL lines, so recompute on the edited text)
    text = '\n'.join(lines)
    comment_lines, trailing, comment_only = set(), {}, set()
    split = text.split('\n')
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type != tokenize.COMMENT:
            continue
        row, col = tok.start
        if _is_header_comment(row, tok.string):
            if flagged(tok.string):
                raise ExportError(f'{path}: line {row} (shebang or encoding cookie) names internal material')
            continue
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
    if (doc_reads(a) or doc_reads(b)) and docs_a != docs_b:
        raise ExportError(f'{path}: reads __doc__ at run time (help text) but its docstring would change')
    head_a = [l for n, l in enumerate(original.split('\n')[:2], 1) if _is_header_comment(n, l)]
    head_b = [l for n, l in enumerate(scrubbed.split('\n')[:2], 1) if _is_header_comment(n, l)]
    if head_a != head_b:
        raise ExportError(f'{path}: scrubbing changed the shebang or encoding cookie')


DOC_MODULES = ('inspect', 'pydoc', 'doctest', 'cmd')       # `cmd.Cmd` prints method docstrings as help


def doc_reads(tree):
    """How a module can read docstrings at run time: 'own' for a bare `__doc__` name, 'other' for `x.__doc__`, the
    string `'__doc__'` (getattr and friends), `help`, or the doc helpers of `inspect`, `pydoc`, `doctest` and `cmd`, and
    `ast.get_docstring`."""
    kinds = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == '__doc__':
            kinds.add('own')
        elif isinstance(node, ast.Name) and node.id in ('help', 'getdoc', 'cleandoc', 'get_docstring'):
            kinds.add('other')
        elif isinstance(node, ast.Attribute) and node.attr in ('__doc__', 'getdoc', 'cleandoc', 'get_docstring'):
            kinds.add('other')
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and '__doc__' in node.value:
            kinds.add('other')
        elif isinstance(node, ast.Import) and any(a.name.split('.')[0] in DOC_MODULES for a in node.names):
            kinds.add('other')
        elif isinstance(node, ast.ImportFrom) and (node.module or '').split('.')[0] in DOC_MODULES:
            kinds.add('other')
    return kinds


def check_doc_readers(modules):
    """`modules`: {path: (original, scrubbed, docstrings scrubbed)}. If any shipped module reads docstrings at run time
    (help text and the like) the build fails when any docstring anywhere was scrubbed, unless the reader reads only its
    own `__doc__` and is byte-identical to the original (then nothing it can read has changed)."""
    scrubbed_anywhere = sorted(path for path, (_, _, count) in modules.items() if count)
    if not scrubbed_anywhere:
        return
    for path, (original, scrubbed, _) in sorted(modules.items()):
        kinds = doc_reads(ast.parse(original))
        if kinds and not (kinds == {'own'} and scrubbed == original):
            raise ExportError(f'{path}: reads __doc__ (or docstrings through inspect/getattr) at run time, and docstrings '
                              f'were scrubbed in {scrubbed_anywhere}; the exported tool could print different text. '
                              'Remove the internal text from the source docstring, or stop reading it')


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
    ceilings = community_ceilings(source)
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
    """The declaration printed in NOTICE.md: one bullet per ALLOW entry that the shipped files use, each with the exact
    terms it covers."""
    if not used:
        return '- (nothing: no declared term occurs in the files)'
    return '\n'.join(_bullet(ALLOW[i]) for i in sorted(used))


def _bullet(entry):
    terms = ', '.join(f'`{t}`' for t in entry['terms'])
    return f'- {entry["describe"]}' + (f' {terms}.' if terms else '')


def capability_table(text):
    """{name: meaning} from the table of the README section "Capability names" (rows `| `name` | meaning |`)."""
    start = text.find('\n## Capability names\n')
    if start < 0:
        return {}
    end = text.find('\n## ', start + 1)
    text = text[start:end if end > 0 else len(text)]
    return {m.group(1): m.group(2).strip() for m in re.finditer(r'(?m)^\| `([a-z0-9_.]+)` \| (.+?) \|$', text)}


def check_capability_table(readme, names):
    """Raise ExportError unless the README's capability table has a meaning for every name the shipped vocabulary has,
    and no other name."""
    table = capability_table(readme)
    missing, extra = sorted(set(names) - set(table)), sorted(set(table) - set(names))
    empty = sorted(name for name, meaning in table.items() if len(meaning) < 12)
    if missing or extra or empty:
        raise ExportError(f'the README capability table does not match contracts/capabilities.v0.json: no meaning for '
                          f'{missing}, not in the vocabulary {extra}, meaning too short {empty}')


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


def interpreter_names(manifest_text):
    """{name: executable} of the module-level `INTERPRETERS = MappingProxyType({...})` of the manifest module."""
    for node in ast.parse(manifest_text).body:
        if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'INTERPRETERS' for t in node.targets)
                and isinstance(node.value, ast.Call) and node.value.args):
            return ast.literal_eval(node.value.args[0])
    raise ExportError('avrana/avrgame/manifest.py: no INTERPRETERS mapping; the export states the interpreter names')


def community_ceilings(source):
    unit = constants(read_text_file(source, PROVISION_SOURCE).decode()).get('COMMUNITY_UNIT')
    ceilings = dict(line.split('=', 1) for line in (unit or '').splitlines() if '=' in line and not line.startswith('#'))
    for key in ('MemoryMax', 'TasksMax', 'CPUQuota'):
        if not ceilings.get(key):
            raise ExportError(f'{PROVISION_SOURCE}: COMMUNITY_UNIT has no {key}=; the README states the ceilings')
    return {key: ceilings[key] for key in ('MemoryMax', 'TasksMax', 'CPUQuota')}


def unit_texts(source):
    """The community-tier unit text and the no-state text, which the README describes in words."""
    provision = constants(read_text_file(source, PROVISION_SOURCE).decode())
    texts = {name: provision.get(name) for name in ('COMMUNITY_UNIT', 'NO_STATE')}
    if not all(isinstance(text, str) for text in texts.values()):
        raise ExportError(f'{PROVISION_SOURCE}: COMMUNITY_UNIT or NO_STATE is not a string constant; the README states them')
    return texts


UNIT_DENIED = r'(SystemCall\w*|ProtectSystem|ProtectHome|ReadOnlyPaths|ReadWritePaths|InaccessiblePaths|TemporaryFileSystem|LimitFSIZE)='
UNIT_REQUIRED = ('CapabilityBoundingSet=', 'PrivateNetwork=yes')


def check_unit_claims(units):
    """The README says: no system-call filter, no filesystem sandbox directive or disk quota, an empty capability
    set, an empty network namespace, and no state directory without the grant. Fail unless the unit text agrees."""
    lines = units['COMMUNITY_UNIT'].splitlines()
    directives = [l for l in lines if l and not l.startswith('#')]
    wrong = [f'{l!r} contradicts the README' for l in directives if re.match(UNIT_DENIED, l)]
    wrong += [f'{d!r} is missing, but the README says it is there' for d in UNIT_REQUIRED if d not in directives]
    if 'StateDirectory=' not in units['NO_STATE'].splitlines():
        wrong.append("NO_STATE no longer resets 'StateDirectory=', but the README says there is no state directory")
    if wrong:
        raise ExportError('the community unit no longer matches what the README says about it:\n  ' + '\n  '.join(wrong))


def speaks_facts(files, source):
    """Everything the shipped tools say or enforce that a game developer relies on: the protocol version strings, and
    the limits, permission names, interpreter names, community-tier ceilings and capability names that the README
    states or the validator checks."""
    common = constants(files['avrana/avrgame/common.py'].decode())
    manifest_text = files['avrana/avrgame/manifest.py'].decode()
    manifest = constants(manifest_text)
    vocabulary_names = json.loads(files[CAPABILITIES_JSON].decode())
    return {
        'versions': {
            'package_format': common['FORMAT'], 'recipe_format': common['RECIPE_FORMAT'],
            'session': string_constant(read_text_file(source, PROTOCOL_SOURCE).decode(), 'VERSION', PROTOCOL_SOURCE),
            'bridge': json.loads(read_text_file(source, PARTY_GAMES_JSON))['bridge']['protocol'],
            'result': string_constant(read_text_file(source, RESULT_SOURCE).decode(), 'SCHEMA', RESULT_SOURCE),
        },
        'limits': {**{k: v for k, v in sorted(common.items()) if k.startswith('MAX_')},
                   **{k: manifest[k] for k in ('MAX_ARGS', 'MAX_ARG')}},
        'permissions': list(constants(files['avrana/contracts/game.py'].decode())['PERMISSIONS']),
        'interpreters': interpreter_names(manifest_text),
        'ceilings': community_ceilings(source),
        'unit': unit_texts(source),
        'capabilities': {scope: list(vocabulary_names[scope]) for scope in ('device', 'runtime')},
    }


def speaks_digest(facts):
    return hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()[:12]


def check_speaks(files, source):
    """What the tools speak must be what SPEAKS and SPEAKS_DIGEST record for this TOOLS_REVISION."""
    facts = speaks_facts(files, source)
    check_unit_claims(facts['unit'])
    if facts['versions'] != SPEAKS:
        raise ExportError(f"the tools now speak {facts['versions']}, not {SPEAKS}: a different tool would carry the file "
                          f'name {ZIP_NAME}. Bump TOOLS_REVISION and update SPEAKS in {SELF} together')
    digest = speaks_digest(facts)
    if digest != SPEAKS_DIGEST:
        raise ExportError(f'a limit, permission name, interpreter name, community-tier unit text or ceiling, or capability name changed '
                          f'(speaks digest {digest}, recorded {SPEAKS_DIGEST}): a different tool would carry the file name '
                          f'{ZIP_NAME}. Bump TOOLS_REVISION and update SPEAKS_DIGEST in {SELF} together')
    return digest


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
    texts = {}
    for rel in COPIED:
        original = read_text_file(source, rel).decode('utf-8')
        scrubbed, stats = scrub_python(original, rel)
        prove_same_code(original, scrubbed, rel)
        texts[rel] = (original, scrubbed, stats['docstrings'])
        files[rel] = scrubbed.encode('utf-8')
        info[rel] = {'origin': 'copied; code unchanged', 'scrubbed': scrubbed != original,
                     'comment_blocks_removed': stats['comment_blocks'], 'docstrings_scrubbed': stats['docstrings']}
    for rel, data in generated_files(source).items():
        files[rel] = data
        info[rel] = {'origin': 'generated stand-in' if rel.endswith('.py') else 'generated: names of the real file, placeholders for the rest'}
    check_doc_readers(texts)
    check_closure(files, source)
    check_syntax_floor(files)
    digest = check_speaks(files, source)
    values = template_values(source, files)
    files['README.md'] = fill(read_text_file(source, TEMPLATES['README.md']), values, TEMPLATES['README.md'])
    check_capability_table(files['README.md'].decode('utf-8'), [n for scope in ('device', 'runtime')
                                                                for n in json.loads(files[CAPABILITIES_JSON])[scope]])
    info['README.md'] = {'origin': 'written for this export'}
    files['AVRGAME-PACKAGE-FORMAT.md'] = format_snapshot(read_text_file(source, FORMAT_DOC), commit or 'unknown')
    info['AVRGAME-PACKAGE-FORMAT.md'] = {'origin': 'excerpt of the project\'s format note'}
    problems, used = content_gate(files)
    problems += unseen_terms(files)
    notice_template = read_text_file(source, TEMPLATES['NOTICE.md'])
    # the fixed text of NOTICE.md is gated like any other file; the declaration is printed from ALLOW afterwards
    problems += content_gate({NOTICE_NAME: fill(notice_template, {**values, 'REVEALED': ''}, TEMPLATES['NOTICE.md'])})[0]
    if problems:
        raise ExportError('the export names internal or platform material that is not declared (declare it in ALLOW only '
                          'if the tool needs it, and say so in the README):\n  ' + '\n  '.join(problems))
    files[NOTICE_NAME] = fill(notice_template, {**values, 'REVEALED': revealed_text(used)}, TEMPLATES['NOTICE.md'])
    info[NOTICE_NAME] = {'origin': 'written for this export; the list of declared platform terms is generated'}
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


def zip_bytes(files, top=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as z:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(f'{top or NAME}/{name}', FIXED_TIME)
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
    problems, used_final = content_gate(final, skip=(NOTICE_NAME,))
    required = {i for i, entry in enumerate(ALLOW) if not entry.get('optional')}
    if problems or used_final != used or not required <= used_final:
        stale = [ALLOW[i]['files'][0] + ' ' + ALLOW[i]['line'] for i in sorted(required - used_final)]
        raise ExportError('the finished export names internal material, or ALLOW has entries that match nothing:\n  '
                          + '\n  '.join(problems + stale or ['(allow-list changed)']))
    return zip_bytes(final, export_name(dirty))


def export_name(dirty):
    """The name of the zip (without `.zip`) and of the one directory in it: marked when the tree was not clean, so a
    dirty export cannot be mistaken for a clean one once unpacked."""
    if dirty is False:
        return NAME
    return f'{NAME}-{"dirty" if dirty else "unverified"}'


def zip_name(dirty):
    return export_name(dirty) + '.zip'


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
    allowed = {export_name(False), export_name(True), export_name(None)}
    if len(roots) != 1 or not roots <= allowed:
        raise ExportError(f'{path}: expected the single top-level directory {NAME} (or its -dirty/-unverified form), '
                          f'found {sorted(roots)}')
    return dest / roots.pop()


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
        unpacked = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}
        gate = content_gate(unpacked, skip=(NOTICE_NAME,))[0] + unseen_terms(unpacked)
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
            top = z.infolist()[0].filename.split('/')[0]
            listing = [(i.filename[len(top) + 1:], i.file_size) for i in z.infolist()]
            manifest = json.loads(z.read(f'{top}/MANIFEST.json'))
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
