"""The appliance profile: which providers this Party box has, and which games it grants.

Data: contracts/appliances/<id>.json. This is the appliance's side of the contract: runtime
capabilities come from providers (not from games), and URL paths, health checks, tier and granted
permissions are grants the appliance makes (a game contract never sets them). A grant can only
give permissions the game's contract requested (checked by the catalog build).

Provider status:
  live        deployed production code (whether its service is running is a health question)
  experiment  exists on an experiment branch or dev port; off unless explicitly included
  planned     a documented seam with no implementation yet
"""
import re

from avrana.contracts import strictjson
from avrana.contracts.game import ID

APPLIANCE = 'avrana.appliance/v0'
PROVIDER_KINDS = ('runtime', 'input', 'presentation')
STATUSES = ('live', 'experiment', 'planned')
TIERS = ('builtin', 'trusted', 'community')
PATH = re.compile(r'^/(?:[a-z0-9][a-z0-9._-]*/)*$')
HEALTH = re.compile(r'^/(?:[a-z0-9][a-z0-9._-]*/)*[a-z0-9][a-z0-9._-]*$')
ADAPTER = re.compile(r'^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*$')
RESERVED_PREFIXES = ('/party/', '/admin/', '/shared/')
CONTROL = re.compile(r'[\x00-\x1f\x7f]')       # written into a systemd unit: no newline, no control character


def _plain_path(path):
    """No `.` or `..` component and no `//`: the path names one place, and the root-owned-code
    check (provision-game) walks the same components that systemd will."""
    return '//' not in path and not any(part in ('.', '..') for part in path.split('/'))


def runtime_problems(runtime, where):
    """A native game's `runtime` (AVR-236): {"command": [absolute path, args...], "working_directory": "/abs"}."""
    if not isinstance(runtime, dict) or set(runtime) != {'command', 'working_directory'}:
        return [f'{where}: an object with exactly "command" and "working_directory"']
    p = []
    command = runtime['command']
    if (not isinstance(command, list) or not command
            or not all(isinstance(a, str) and a and not CONTROL.search(a) for a in command)):
        p.append(f'{where}.command: a non-empty list of non-empty strings without control characters')
    elif not command[0].startswith('/'):
        p.append(f'{where}.command: the first element is an absolute path')
    elif not _plain_path(command[0]):
        p.append(f'{where}.command: the first element has no "." or ".." component and no "//"')
    cwd = runtime['working_directory']
    if not isinstance(cwd, str) or not cwd.startswith('/') or CONTROL.search(cwd):
        p.append(f'{where}.working_directory: an absolute path without control characters')
    elif not _plain_path(cwd) or cwd.endswith('\\'):
        p.append(f'{where}.working_directory: no "." or ".." component, no "//" and no trailing backslash')
    return p


def _problems(doc, vocab):
    p = []
    if not isinstance(doc, dict):
        return ['appliance: must be an object']
    allowed = {'schema', 'id', 'name', 'providers', 'installed', 'collections'}
    p += [f'appliance: unknown key {k!r}' for k in sorted(set(doc) - allowed)]
    if doc.get('schema') != APPLIANCE:
        p.append(f'appliance.schema: must be {APPLIANCE!r}')
    if not isinstance(doc.get('id'), str) or not ID.fullmatch(doc['id']):
        p.append('appliance.id: an id')
    if not isinstance(doc.get('name'), str) or not 1 <= len(doc['name']) <= 80:
        p.append('appliance.name: 1-80 characters')
    runtime_names = set(vocab.runtime) if vocab else None
    for key in ('providers', 'installed', 'collections'):
        if key in doc and not isinstance(doc[key], list):
            p.append(f'appliance.{key}: a list')
            doc = {**doc, key: []}
    if not isinstance(doc.get('providers'), list) or not doc.get('providers'):
        p.append('appliance.providers: a non-empty list')
    seen = set()
    for i, prov in enumerate(doc.get('providers') or []):
        where = f'providers[{i}]'
        keys = {'id', 'kind', 'offers', 'status', 'adapter', 'implementation'}
        if not isinstance(prov, dict) or set(prov) - keys or {'id', 'kind', 'offers', 'status'} - set(prov):
            p.append(f'{where}: keys {sorted(keys)} (adapter and implementation optional)')
            continue
        if not isinstance(prov['id'], str) or not ID.fullmatch(prov['id']) or prov['id'] in seen:
            p.append(f'{where}.id: a unique id')
        else:
            seen.add(prov['id'])
        if prov['kind'] not in PROVIDER_KINDS:
            p.append(f'{where}.kind: one of {list(PROVIDER_KINDS)}')
        if prov['status'] not in STATUSES:
            p.append(f'{where}.status: one of {list(STATUSES)}')
        offers = prov['offers']
        if not isinstance(offers, list) or not offers or not all(isinstance(o, str) for o in offers):
            p.append(f'{where}.offers: a non-empty list of runtime capability names')
        elif runtime_names is not None:
            p += [f'{where}.offers: unknown capability {o!r}' for o in offers if o not in runtime_names]
        adapter = prov.get('adapter')
        if adapter is not None and (not isinstance(adapter, str) or not ADAPTER.match(adapter)):
            p.append(f'{where}.adapter: "package.module:Class" or null')
        if 'implementation' in prov and not isinstance(prov['implementation'], str):
            p.append(f'{where}.implementation: text')
    games = set()
    for i, inst in enumerate(doc.get('installed') or []):
        where = f'installed[{i}]'
        keys = {'game', 'entry', 'health', 'tier', 'permissions_granted', 'runtime'}
        if not isinstance(inst, dict) or set(inst) - keys or {'game', 'entry', 'tier'} - set(inst):
            p.append(f'{where}: keys {sorted(keys)} (health, permissions_granted and runtime optional)')
            continue
        if not isinstance(inst['game'], str) or not ID.fullmatch(inst['game']) or inst['game'] in games:
            p.append(f'{where}.game: a unique game id')
        else:
            games.add(inst['game'])
        entry = inst['entry']
        if not isinstance(entry, str) or not PATH.match(entry) or '..' in entry or entry.startswith(RESERVED_PREFIXES):
            p.append(f'{where}.entry: a same-origin path ending in "/" outside {list(RESERVED_PREFIXES)}')
        health = inst.get('health')
        if health is not None and (not isinstance(health, str) or not HEALTH.match(health) or '..' in health):
            p.append(f'{where}.health: a same-origin path')
        if inst['tier'] not in TIERS:
            p.append(f'{where}.tier: one of {list(TIERS)}')
        if 'runtime' in inst:
            p += runtime_problems(inst['runtime'], f'{where}.runtime')
        granted = inst.get('permissions_granted', [])
        if not isinstance(granted, list) or not all(isinstance(g, str) for g in granted):
            p.append(f'{where}.permissions_granted: a list of permission names')
    for i, col in enumerate(doc.get('collections') or []):
        where = f'collections[{i}]'
        keys = {'id', 'name', 'summary', 'entry', 'requires'}
        if not isinstance(col, dict) or set(col) - keys or keys - {'summary'} - set(col):
            p.append(f'{where}: keys {sorted(keys)} (summary optional)')
            continue
        if not isinstance(col.get('id'), str) or not ID.fullmatch(col['id']) or not isinstance(col.get('name'), str):
            p.append(f'{where}: id and name are text')
        if not isinstance(col['entry'], str) or not PATH.match(col['entry']):
            p.append(f'{where}.entry: a same-origin path ending in "/"')
        req = col['requires']
        if not isinstance(req, list) or (runtime_names is not None and any(r not in runtime_names for r in req)):
            p.append(f'{where}.requires: runtime capability names')
    return p


def validate(doc, vocab=None):
    problems = _problems(doc, vocab)
    if problems:
        raise ValueError('; '.join(problems))
    return doc


def load(path, vocab=None):
    return validate(strictjson.load_path(path), vocab)


def runtime_capabilities(appliance, include=('live',)):
    """The runtime capability names offered by providers whose status is in `include`."""
    return sorted({o for prov in appliance['providers'] if prov['status'] in include for o in prov['offers']})


def grants(appliance):
    return {inst['game']: inst for inst in appliance.get('installed') or []}
