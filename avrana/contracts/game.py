"""Game Contract v0: what a game is, what it needs, and how it can be presented to each seat.

A contract describes and requests; the appliance decides (docs/design/GAME-INTEGRATION.md). It
never carries a URL, trust level or granted permission: those live in the appliance profile
(appliance.py). Field reference: contracts/README.md.

This grows from the experimental manifest v0 (branch experiment/party-service,
experiments/manifests/): same ids, enums and strictness, plus presentations with capability
requirements, fallback, requested permissions and extensions. lift_manifest_v0() converts a v0
manifest so both can coexist while the party service moves over.
"""
import re
import unicodedata

from avrana.contracts import strictjson

CONTRACT = 'avrana.game/v0'

ID = re.compile(r'^[a-z][a-z0-9_-]{0,39}$')      # use fullmatch: `$` alone accepts a trailing newline
RESERVED_IDS = {'home', 'party', 'admin', 'shared', 'diag', 'api'}
PRESENTATION_ID = re.compile(r'^[a-z][a-z0-9_]{0,31}$')
BUTTON = re.compile(r'^[a-z][a-z0-9_]{0,15}$')
EXTENSION_KEY = re.compile(r'^[a-z0-9-]+(\.[a-z0-9-]+)+$')

KINDS = ('native', 'emulated', 'other')
SCREENS = ('no_tv_needed', 'tv_optional', 'tv_required')
INPUT_MODELS = ('browser_native', 'controller_slots', 'hotseat')
DIRECTIONS = ('none', 'dpad', 'analog')
LATE_JOIN = ('spectator_only', 'next_round', 'supported')
SPECTATORS = ('none', 'watch')
RUNTIME_TYPES = ('lan_games_module', 'emulator_profile', 'external')
RUNTIME_STARTS = ('always_on', 'service')
RESOURCES = ('emulator_slot', 'hw_encoder', 'host_rendering', 'hdmi')
# Authority a game may request; deny by default, granted (or not) by the appliance per tier.
PERMISSIONS = ('persistent_storage', 'party_roster', 'controllers', 'microphone', 'camera',
               'local_network', 'internet', 'host_devices')
PLATFORMS = ('any', 'linux/arm64', 'linux/amd64')
SPDX = re.compile(r'^[A-Za-z0-9.+\-]+( (AND|OR|WITH) [A-Za-z0-9.+\-]+)*$')
# Grant-side facts a package must never claim for itself (docs/design/GAME-INTEGRATION.md).
GRANT_ONLY = ('trust', 'tier', 'grant', 'path', 'entry', 'namespace', 'signature', 'digest',
              'provenance', 'permissions_granted')
METHODS = ('browser_native', 'shared_stream', 'personal_viewport', 'controller_only', 'app_native')
VIEWPORTS = ('crop', 'dedicated_stream', 'browser_renderer', 'private_panel')
ROLES = ('player', 'spectator')
FALLBACKS = ('explain', 'spectate')
ACCESSIBILITY = ('color_independent', 'audio_required', 'text_scalable', 'reduced_motion_respected',
                 'timing_pressure')

# A presentation method that needs an appliance-side presenter must say so in requires.runtime,
# so the appliance can never be asked for something the contract forgot to declare.
METHOD_RUNTIME = {
    ('shared_stream', None): 'presentation.shared_stream',
    ('personal_viewport', 'crop'): 'presentation.personal_viewport.crop',
    ('personal_viewport', 'dedicated_stream'): 'presentation.personal_viewport.dedicated_stream',
    ('controller_only', None): 'presentation.tv',
}
PHONE_RENDERED = {('browser_native', None), ('app_native', None), ('personal_viewport', 'browser_renderer'),
                  ('personal_viewport', 'private_panel')}

TOP = {'contract', 'id', 'name', 'summary', 'kind', 'players', 'screen', 'input', 'late_join',
       'spectators', 'private_player_ui', 'runtime', 'presentations', 'fallback', 'package',
       'accessibility', 'extensions'}
REQUIRED_TOP = {'contract', 'id', 'name', 'kind', 'players', 'screen', 'input', 'runtime', 'presentations'}


class ContractError(ValueError):
    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__('; '.join(self.problems))


def _printable(value, low, high):
    return (isinstance(value, str) and low <= len(value) <= high and value == value.strip()
            and all(unicodedata.category(c)[0] not in 'CZ' or c == ' ' for c in value))


def _int(value, low, high):
    return type(value) is int and low <= value <= high


def _names(value, where, problems, allowed=None, pattern=None, limit=24):
    """A list of unique strings; returns it (or [] when invalid)."""
    if not isinstance(value, list) or len(value) > limit or any(not isinstance(v, str) for v in value):
        problems.append(f'{where}: a list of at most {limit} strings')
        return []
    if len(set(value)) != len(value):
        problems.append(f'{where}: duplicates')
    for v in value:
        if allowed is not None and v not in allowed:
            problems.append(f'{where}: unknown {v!r}')
        if pattern is not None and not pattern.match(v):
            problems.append(f'{where}: bad name {v!r}')
    return value


def _keys(obj, where, allowed, required, problems):
    if not isinstance(obj, dict):
        problems.append(f'{where}: must be an object')
        return False
    for key in sorted(set(obj) - allowed):
        problems.append(f'{where}: unknown key {key!r}')
    for key in sorted(required - set(obj)):
        problems.append(f'{where}: missing {key!r}')
    return True


def _enum(obj, key, where, values, problems, default=None):
    value = obj.get(key, default)
    if value not in values:
        problems.append(f'{where}.{key}: one of {list(values)}')
    return value


def _requirements(obj, where, vocab, problems):
    """{device: [...], runtime: [...]} with names from the vocabulary."""
    out = {'device': [], 'runtime': []}
    if obj is None:
        return out
    if not _keys(obj, where, {'device', 'runtime'}, set(), problems):
        return out
    for scope in ('device', 'runtime'):
        if scope in obj:
            allowed = set(getattr(vocab, scope)) if vocab else None
            out[scope] = list(_names(obj[scope], f'{where}.{scope}', problems, allowed))
    return out


def validate(doc, vocab=None):
    """Return a normalised copy of a valid contract, or raise ContractError listing every problem.

    vocab: an avrana.contracts.vocabulary.Vocabulary; without it capability names are not checked.
    """
    problems = []
    if isinstance(doc, dict):
        # Name grant-side keys explicitly (instead of "unknown key") so authors learn where they go.
        for where, obj in (('contract', doc), ('runtime', doc.get('runtime'))):
            if isinstance(obj, dict):
                problems += [f'{where}.{key}: set by the appliance grant, never by the game'
                             for key in GRANT_ONLY if key in obj]
        doc = {k: v for k, v in doc.items() if k not in GRANT_ONLY}
        if isinstance(doc.get('runtime'), dict):
            doc['runtime'] = {k: v for k, v in doc['runtime'].items() if k not in GRANT_ONLY}
    if not _keys(doc, 'contract', TOP, REQUIRED_TOP, problems):
        raise ContractError(problems)
    if doc.get('contract') != CONTRACT:
        problems.append(f'contract: must be {CONTRACT!r} (a newer or older contract needs its own validator)')
    cid = doc.get('id')
    if not isinstance(cid, str) or not ID.fullmatch(cid) or cid in RESERVED_IDS:
        problems.append('id: ^[a-z][a-z0-9_-]{0,39}$ and not reserved')
    if not _printable(doc.get('name'), 1, 60):
        problems.append('name: 1-60 printable characters')
    if 'summary' in doc and not _printable(doc['summary'], 1, 140):
        problems.append('summary: 1-140 printable characters')
    kind = _enum(doc, 'kind', 'contract', KINDS, problems)
    _enum(doc, 'screen', 'contract', SCREENS, problems)
    late_join = _enum(doc, 'late_join', 'contract', LATE_JOIN, problems, 'spectator_only')
    spectators = _enum(doc, 'spectators', 'contract', SPECTATORS, problems, 'watch')
    fallback = _enum(doc, 'fallback', 'contract', FALLBACKS, problems, 'explain')
    private_ui = doc.get('private_player_ui', False)
    if type(private_ui) is not bool:
        problems.append('private_player_ui: true or false')

    players = doc.get('players')
    pmax = 32
    if _keys(players, 'players', {'min', 'max'}, {'min', 'max'}, problems):
        if not (_int(players.get('min'), 1, 32) and _int(players.get('max'), 1, 32)):
            problems.append('players: min and max are integers 1-32')
        elif players['min'] > players['max']:
            problems.append('players: min > max')
        else:
            pmax = players['max']

    inp = doc.get('input')
    model = None
    norm_input = {}
    if _keys(inp, 'input', {'model', 'slots', 'buttons', 'directions'}, {'model'}, problems):
        model = _enum(inp, 'model', 'input', INPUT_MODELS, problems)
        norm_input['model'] = model
        if model == 'browser_native':
            for key in ('slots', 'buttons', 'directions'):
                if key in inp:
                    problems.append(f'input.{key}: only for controller models')
        elif model in INPUT_MODELS:
            slots = inp.get('slots')
            if not _int(slots, 1, 8):
                problems.append('input.slots: integer 1-8, required for controller models')
            elif slots > pmax:
                problems.append('input.slots: more slots than players.max')
            elif model == 'hotseat' and slots != 1:
                problems.append('input.slots: a hotseat game has exactly one slot')
            norm_input['slots'] = slots
            if 'buttons' in inp:
                norm_input['buttons'] = list(_names(inp['buttons'], 'input.buttons', problems,
                                                    pattern=BUTTON, limit=12))
                if not inp['buttons']:
                    problems.append('input.buttons: at least one button')
            norm_input['directions'] = _enum(inp, 'directions', 'input', DIRECTIONS, problems, 'dpad')
            if norm_input['directions'] == 'dpad' and set(norm_input.get('buttons', ())) & {'up', 'down', 'left', 'right'}:
                problems.append('input.buttons: must not reuse the d-pad direction names')

    runtime = doc.get('runtime')
    norm_runtime = {}
    if _keys(runtime, 'runtime', {'type', 'start', 'profile', 'resources', 'permissions'}, {'type'}, problems):
        rtype = _enum(runtime, 'type', 'runtime', RUNTIME_TYPES, problems)
        start_default = 'always_on' if rtype == 'lan_games_module' else None
        if 'start' not in runtime and start_default is None:
            problems.append('runtime.start: required unless the type is lan_games_module')
        start = runtime.get('start', start_default)
        if start is not None and start not in RUNTIME_STARTS:
            problems.append(f'runtime.start: one of {list(RUNTIME_STARTS)}')
        norm_runtime = {'type': rtype, 'start': start}
        if rtype == 'emulator_profile':
            profile = runtime.get('profile')
            if not isinstance(profile, str) or not ID.fullmatch(profile):
                problems.append('runtime.profile: required for emulator_profile (an id)')
            norm_runtime['profile'] = profile
        elif 'profile' in runtime:
            problems.append('runtime.profile: only for emulator_profile')
        norm_runtime['resources'] = list(_names(runtime.get('resources', []), 'runtime.resources',
                                                problems, RESOURCES))
        norm_runtime['permissions'] = list(_names(runtime.get('permissions', []), 'runtime.permissions',
                                                  problems, PERMISSIONS))
        if kind == 'native' and rtype == 'emulator_profile':
            problems.append('runtime.type: a native game has no emulator profile')
        if kind == 'emulated' and rtype == 'lan_games_module':
            problems.append('runtime.type: an emulated game is not a LAN Games module')

    presentations = []
    seen = set()
    raw = doc.get('presentations')
    if not isinstance(raw, list) or not 1 <= len(raw) <= 8:
        problems.append('presentations: 1-8 entries, most preferred first')
        raw = []
    for i, p in enumerate(raw):
        where = f'presentations[{i}]'
        if not _keys(p, where, {'id', 'method', 'viewport', 'roles', 'requires', 'optional'},
                     {'id', 'method', 'roles'}, problems):
            continue
        pid = p.get('id')
        if not isinstance(pid, str) or not PRESENTATION_ID.match(pid):
            problems.append(f'{where}.id: ^[a-z][a-z0-9_]{{0,31}}$')
        elif pid in seen:
            problems.append(f'{where}.id: duplicate {pid!r}')
        else:
            seen.add(pid)
        method = _enum(p, 'method', where, METHODS, problems)
        if method not in METHODS:
            continue  # nothing below is meaningful without a known method
        viewport = p.get('viewport')
        if method == 'personal_viewport':
            if viewport not in VIEWPORTS:
                problems.append(f'{where}.viewport: one of {list(VIEWPORTS)} for a personal_viewport')
                viewport = None
        elif 'viewport' in p:
            problems.append(f'{where}.viewport: only for a personal_viewport')
            viewport = None
        roles = _names(p.get('roles'), f'{where}.roles', problems, ROLES)
        if not roles:
            problems.append(f'{where}.roles: at least one role')
        requires = _requirements(p.get('requires'), f'{where}.requires', vocab, problems)
        optional = _requirements(p.get('optional'), f'{where}.optional', vocab, problems)
        for scope in ('device', 'runtime'):
            both = set(requires[scope]) & set(optional[scope])
            if both:
                problems.append(f'{where}: {sorted(both)} both required and optional')
        needed = METHOD_RUNTIME.get((method, viewport if method == 'personal_viewport' else None))
        if needed and needed not in requires['runtime']:
            problems.append(f'{where}.requires.runtime: a {method} presentation must require {needed!r}')
        if method == 'controller_only' and model == 'browser_native':
            problems.append(f'{where}: controller_only needs a controller input model')
        if 'spectator' in roles and spectators == 'none':
            problems.append(f'{where}.roles: spectators is "none"')
        presentations.append({'id': pid, 'method': method,
                              **({'viewport': viewport} if method == 'personal_viewport' else {}),
                              'roles': list(roles), 'requires': requires, 'optional': optional})
    if raw and not any('player' in p['roles'] for p in presentations):
        problems.append('presentations: none of them is for players')
    tv_only = presentations and all(p['method'] == 'controller_only' for p in presentations)
    if spectators == 'watch' and raw and not tv_only and not any('spectator' in p['roles'] for p in presentations):
        # (A game whose picture is only on the TV lets watchers watch the TV: no phone presentation.)
        problems.append('presentations: spectators is "watch" but no presentation is for spectators')
    if fallback == 'spectate' and spectators != 'watch':
        problems.append('fallback: "spectate" needs spectators "watch"')
    if private_ui is True and presentations and not any(
            'player' in p['roles'] and (p['method'], p.get('viewport')) in PHONE_RENDERED for p in presentations):
        problems.append('private_player_ui: needs a player presentation rendered on the phone')

    package = None
    if 'package' in doc and _keys(doc['package'], 'package',
                                  {'version', 'publisher', 'license', 'source', 'revision', 'platforms'},
                                  {'version', 'platforms'}, problems):
        pkg = doc['package']
        if not _printable(pkg.get('version'), 1, 32):
            problems.append('package.version: 1-32 printable characters (display only; TUF orders updates)')
        for key, high in (('publisher', 80), ('source', 200), ('revision', 64)):
            if key in pkg and not _printable(pkg[key], 1, high):
                problems.append(f'package.{key}: 1-{high} printable characters')
        if 'license' in pkg and (not isinstance(pkg['license'], str) or not SPDX.match(pkg['license'])):
            problems.append('package.license: an SPDX expression')
        platforms = _names(pkg.get('platforms'), 'package.platforms', problems, PLATFORMS, limit=4)
        if not platforms or ('any' in platforms and len(platforms) > 1):
            problems.append('package.platforms: ["any"] or a list of linux/arm64, linux/amd64')
        package = dict(pkg)

    accessibility = {k: 'unknown' for k in ACCESSIBILITY}
    if 'accessibility' in doc and _keys(doc['accessibility'], 'accessibility', set(ACCESSIBILITY), set(),
                                        problems):
        for key, value in doc['accessibility'].items():
            if type(value) is not bool and value != 'unknown':
                problems.append(f'accessibility.{key}: true, false or "unknown"')
            accessibility[key] = value

    extensions = doc.get('extensions', {})
    if not isinstance(extensions, dict):
        problems.append('extensions: an object keyed by reverse-DNS names')
        extensions = {}
    for key in extensions:
        if not EXTENSION_KEY.match(key):
            problems.append(f'extensions: {key!r} is not a reverse-DNS name like "net.avrana.example"')

    if problems:
        raise ContractError(problems)
    out = {
        'contract': CONTRACT, 'id': cid, 'name': doc['name'], 'kind': kind,
        'players': dict(players), 'screen': doc['screen'], 'input': norm_input,
        'late_join': late_join, 'spectators': spectators, 'private_player_ui': private_ui,
        'runtime': norm_runtime, 'presentations': presentations, 'fallback': fallback,
        'accessibility': accessibility, 'extensions': dict(extensions),
    }
    if 'summary' in doc:
        out['summary'] = doc['summary']
    if package is not None:
        out['package'] = package
    return out


def load(path, vocab=None):
    """Load and validate a contract file; the file name must be '<id>.json'."""
    doc = strictjson.load_path(path)
    contract = validate(doc, vocab)
    stem = str(path).replace('\\', '/').rsplit('/', 1)[-1].removesuffix('.json')
    if stem != contract['id']:
        raise ContractError([f'file name {stem!r} must equal the id {contract["id"]!r}'])
    return contract


def lift_manifest_v0(manifest):
    """Convert an experimental manifest v0 (already valid under its own validator) to a contract.

    Returns (contract_document, grant_hint). The v0 'runtime.entry' is appliance data (a grant), so
    it comes back separately instead of inside the contract. Presentations are derived from the
    v0 input model and shared_video flag; accessibility and flags carry over unchanged.
    """
    m = manifest
    spectators = m.get('spectators', 'watch')
    roles = ['player', 'spectator'] if spectators == 'watch' else ['player']
    rt = m['runtime']
    inp = {k: v for k, v in m['input'].items() if k in ('model', 'slots')}
    if inp['model'] == 'browser_native':
        runtime_caps = ['runtime.lan_games'] if rt['type'] == 'lan_games_module' else []
        presentation = {'id': 'phone', 'method': 'browser_native', 'roles': roles,
                        'requires': {'device': ['websocket'], 'runtime': runtime_caps}}
    elif m.get('shared_video'):
        runtime_caps = ['presentation.shared_stream', 'input.virtual_gamepad']
        if m['kind'] == 'emulated':
            runtime_caps.insert(0, 'runtime.retroarch')
        presentation = {'id': 'phone_stream', 'method': 'shared_stream', 'roles': roles,
                        'requires': {'device': ['websocket', 'webrtc', 'video.h264'], 'runtime': runtime_caps}}
    else:
        presentation = {'id': 'controller', 'method': 'controller_only', 'roles': ['player'],
                        'requires': {'device': ['websocket'],
                                     'runtime': ['presentation.tv', 'input.virtual_gamepad']}}
    doc = {
        'contract': CONTRACT, 'id': m['id'], 'name': m['name'], 'kind': m['kind'],
        'players': dict(m['players']), 'screen': m['screen'], 'input': inp,
        'late_join': m.get('late_join', 'spectator_only'), 'spectators': spectators,
        'private_player_ui': m.get('private_player_ui', False),
        'runtime': {k: v for k, v in rt.items() if k in ('type', 'start', 'profile')},
        'presentations': [presentation],
        'fallback': 'spectate' if spectators == 'watch' and 'spectator' in presentation['roles'] else 'explain',
    }
    if 'accessibility' in m:
        doc['accessibility'] = dict(m['accessibility'])
    return doc, {'entry': rt.get('entry')}
