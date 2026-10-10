"""The experimental .avrgame manifest (`avrgame.json` at the archive root).

EXPERIMENTAL: not a stable format, field names may change. A manifest is UNTRUSTED INPUT even when
it validates: validation is pure data checking and never imports, executes or evaluates anything.
`package.publisher`, `package.license` and `package.source` are display-only claims; no trust is
derived from them.

A package may request but never grant: the manifest has no tier, entry path, health check,
granted permission, key, socket or absolute path. The embedded Game Contract is the one source of
game facts; it is checked by the existing avrana.contracts.game validator, unchanged.
"""
import re
from types import MappingProxyType

from avrana.contracts import game as game_contract
from avrana.contracts import strictjson, vocabulary

from .common import FORMAT, MAX_MANIFEST_BYTES, Problems, Refused, clip, name_problem, text_ok

# Interpreter NAME -> absolute executable. The appliance owns this mapping; a package only picks a
# name. The installer sets the working directory to the staged package root.
INTERPRETERS = MappingProxyType({'python3': '/usr/bin/python3'})

TOP = ('format', 'game', 'package', 'requires', 'server', 'client')
RESERVED = ('signature', 'provenance', 'entitlement', 'publisher_key')
APPLIANCE_OWNED = frozenset({
    'tier', 'trust', 'entry', 'health', 'grant', 'granted', 'permissions', 'key', 'socket', 'path', 'url',
    'command', 'cwd', 'working_directory', 'env', 'environment', 'digest'})
VERSION = re.compile(r'^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.]{1,32})?$')
REQUIRES_KEYS = ('session', 'bridge', 'result')
MAX_ARGS = 16
MAX_ARG = 200


def supported_requires():
    """The versions this Party implements, taken from its code and contract declaration."""
    from avrana.contracts import party_games
    from avrana.party import protocol, result
    return {'session': (protocol.VERSION,),
            'bridge': (party_games.load()['bridge']['protocol'],),
            'result': (result.SCHEMA,)}


def parse(data):
    """Bytes of avrgame.json -> object, strictly (duplicate keys, NaN, BOM, nesting are refused)."""
    if len(data) > MAX_MANIFEST_BYTES:
        raise Refused(f'avrgame.json: larger than {MAX_MANIFEST_BYTES} bytes')
    try:
        return strictjson.loads(data.decode('utf-8'))
    except UnicodeDecodeError:
        raise Refused('avrgame.json: not UTF-8') from None
    except (ValueError, RecursionError) as exc:      # StrictJSONError is a ValueError
        raise Refused(f'avrgame.json: not strict JSON ({clip(str(exc), 100)})') from None


def _keys(obj, where, allowed, required, problems):
    if not isinstance(obj, dict):
        problems.add(f'{where}: must be an object')
        return False
    for key in sorted(obj):
        if key in allowed:
            continue
        if key in APPLIANCE_OWNED:
            problems.add(f'{where}.{key}: set by the appliance, never by a package')
        else:
            problems.add(f'{where}: unknown key {clip(key)}')
    for key in required:
        if key not in obj:
            problems.add(f'{where}: missing {key!r}')
    return True


def validate_manifest(obj, vocab=None):
    """Validate a parsed manifest and return its normalised copy, or raise Refused listing every
    problem found. `vocab` is a capability Vocabulary (default: the repository's)."""
    problems = Problems()
    if not isinstance(obj, dict):
        raise Refused('manifest: must be a JSON object')
    for key in RESERVED:
        if key in obj:
            problems.add(f'manifest.{key}: reserved; not implemented in this experimental format '
                         '(an ignored signature must never look like a checked one)')
    fmt = obj.get('format')
    if fmt != FORMAT:
        problems.add(f'format: this appliance supports only {FORMAT!r}, not {clip(fmt)}; '
                     'unknown formats are refused')
    for key in sorted(set(obj) - set(TOP) - set(RESERVED)):
        if key in APPLIANCE_OWNED:
            problems.add(f'manifest.{key}: set by the appliance, never by a package')
        else:
            problems.add(f'manifest: unknown key {clip(key)}')
    for key in TOP:
        if key not in obj:
            problems.add(f'manifest: missing {key!r}')

    out = {'format': fmt}
    # game: the one source of game facts
    if 'game' in obj:
        contract = None
        if vocab is None:
            vocab = vocabulary.load()
        try:
            contract = game_contract.validate(obj['game'], vocab)
        except game_contract.ContractError as exc:
            for p in exc.problems:
                problems.add(f'game: {p}')
        if contract is not None:
            if contract['kind'] != 'native':
                problems.add('game.kind: only "native" games are packageable; emulation is a separate provider')
            rt = contract['runtime']
            if (rt['type'], rt['start']) != ('external', 'service'):
                problems.add('game.runtime: a package game uses type "external" with start "service"')
            if 'package' in contract:
                problems.add('game.package: not allowed inside a package; use the manifest "package" block')
        out['game'] = contract

    # package: display-only claims
    pkg = obj.get('package')
    if 'package' in obj and _keys(pkg, 'package', {'version', 'publisher', 'license', 'source'},
                                  ('version', 'publisher', 'license'), problems):
        if not isinstance(pkg.get('version'), str) or not VERSION.match(pkg['version']):
            problems.add('package.version: like 1.2.3 or 1.2.3-rc.1 (digits, optional short suffix)')
        for key, high in (('publisher', 80), ('license', 80), ('source', 200)):
            if key in pkg and not text_ok(pkg[key], 1, high):
                problems.add(f'package.{key}: 1-{high} printable characters (a display-only claim)')
        out['package'] = {k: pkg[k] for k in ('version', 'publisher', 'license', 'source') if k in pkg}

    # requires: fail closed on anything this Party does not implement
    req = obj.get('requires')
    if 'requires' in obj and _keys(req, 'requires', REQUIRES_KEYS, REQUIRES_KEYS, problems):
        supported = supported_requires()
        for key in REQUIRES_KEYS:
            if key in req and req[key] not in supported[key]:
                problems.add(f'requires.{key}: this appliance implements {list(supported[key])}, '
                             f'not {clip(req[key])}')
        out['requires'] = {k: req[k] for k in REQUIRES_KEYS if k in req}

    # server: an interpreter NAME and arguments; the appliance owns the executable path
    srv = obj.get('server')
    if 'server' in obj and _keys(srv, 'server', {'interpreter', 'args'}, ('interpreter', 'args'), problems):
        interp = srv.get('interpreter')
        if not isinstance(interp, str) or interp not in INTERPRETERS:
            problems.add(f'server.interpreter: one of {sorted(INTERPRETERS)} (a name, never a path), '
                         f'not {clip(interp)}')
        args = srv.get('args')
        if not isinstance(args, list) or not 1 <= len(args) <= MAX_ARGS:
            problems.add(f'server.args: a list of 1-{MAX_ARGS} strings')
        else:
            for i, arg in enumerate(args):
                if not text_ok(arg, 1, MAX_ARG):
                    problems.add(f'server.args[{i}]: 1-{MAX_ARG} printable characters, no control characters')
                elif arg.startswith(('/', '\\')) or re.match(r'^[A-Za-z]:', arg) or '..' in arg.split('/'):
                    problems.add(f'server.args[{i}]: no absolute paths or ".." (the server runs in the package root)')
        out['server'] = {'interpreter': interp, 'args': list(args) if isinstance(args, list) else args}

    # client: where the portable browser bundle lives inside the package
    cli = obj.get('client')
    if 'client' in obj and _keys(cli, 'client', {'root'}, ('root',), problems):
        root = cli.get('root')
        why = name_problem(root, 'client.root') if isinstance(root, str) else 'client.root: must be a string'
        if why:
            problems.add(why)
        out['client'] = {'root': root}

    problems.raise_if_any()
    return out


def client_index(manifest):
    return manifest['client']['root'] + '/index.html'
