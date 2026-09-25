"""Game capability manifest v0 — the smallest useful version (docs/design/GAME-INTEGRATION.md §1).

A manifest says what a game IS and CAN DO (capabilities). It never says how to launch it (that is
runtime/launch data: e.g. a PS1 title profile) and it grants nothing (a grant is the appliance's
decision). Stdlib only. Three sources:

  builtin/*.json         hand-written manifests for runtimes that have no registry (arcade, PS1)
  LAN Games /api/games   DERIVED — never hand-written — plus lan-overlay.json for the few fields the
                         registry cannot express (private_player_ui, accessibility)
  (later) installed games, whose paths the grant assigns — not built

Only fields with at least two consumers today are in v0; see README.md for the list and why.
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))

ID_RE = re.compile(r'^[a-z][a-z0-9_-]{0,39}$')
ENTRY_RE = re.compile(r'^/(?:[a-z0-9][a-z0-9._-]*/)*$')        # same-origin path, ends in '/'
RESERVED_IDS = {'home', 'party', 'admin'}
RESERVED_PATHS = ('/party/', '/admin/', '/shared/')

KINDS = {'native', 'emulated', 'other'}
RUNTIMES = {'lan_games_module', 'emulator_profile', 'external'}
STARTS = {'always_on', 'service'}
SCREENS = {'no_tv_needed', 'tv_optional', 'tv_required'}
INPUTS = {'browser_native', 'controller_slots', 'hotseat'}
LATE_JOIN = {'spectator_only', 'next_round', 'supported'}
SPECTATORS = {'none', 'watch'}
A11Y_KEYS = ('color_independent', 'audio_required', 'text_scalable', 'reduced_motion_respected',
             'timing_pressure')
TRI = (True, False, 'unknown')
MAX_PLAYERS, MAX_SLOTS = 32, 4

TOP = {'manifest', 'id', 'name', 'kind', 'runtime', 'players', 'screen', 'input', 'late_join',
       'spectators', 'shared_video', 'personal_viewports', 'private_player_ui', 'accessibility'}
REQUIRED = {'manifest', 'id', 'name', 'kind', 'runtime', 'players', 'screen', 'input'}


class ManifestError(ValueError):
    pass


def _no_dupes(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ManifestError(f'duplicate key {k!r}')
        out[k] = v
    return out


def _bad_constant(name):
    raise ManifestError(f'{name} is not valid JSON here')


def parse(text):
    """Strict JSON: no duplicate keys, no NaN/Infinity."""
    try:
        return json.loads(text, object_pairs_hook=_no_dupes, parse_constant=_bad_constant)
    except json.JSONDecodeError as e:
        raise ManifestError(f'bad JSON: {e}') from None


def _int(v, lo, hi, what):
    if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
        raise ManifestError(f'{what} must be an integer {lo}..{hi}')
    return v


def _enum(v, allowed, what):
    if not isinstance(v, str) or v not in allowed:
        raise ManifestError(f'{what} must be one of {sorted(allowed)}')
    return v


def _keys(obj, allowed, required, what):
    if not isinstance(obj, dict):
        raise ManifestError(f'{what} must be an object')
    unknown = set(obj) - allowed
    if unknown:
        raise ManifestError(f'{what}: unknown key(s) {sorted(unknown)}')
    missing = required - set(obj)
    if missing:
        raise ManifestError(f'{what}: missing key(s) {sorted(missing)}')


def check_entry(entry, what='runtime.entry'):
    if entry is None:
        return None
    if not isinstance(entry, str) or len(entry) > 128 or not ENTRY_RE.match(entry):
        raise ManifestError(f'{what} must be a same-origin path like /games/x/ (no scheme, host, '
                            f'query, "..", or trailing file)')
    if entry.startswith(RESERVED_PATHS):
        raise ManifestError(f'{what} uses a reserved path')
    return entry


def validate(m):
    """Return a normalised copy (defaults filled in) or raise ManifestError."""
    _keys(m, TOP, REQUIRED, 'manifest')
    if m['manifest'] != 0 or isinstance(m['manifest'], bool):
        raise ManifestError('manifest must be 0 (this validator understands v0 only)')
    mid = m['id']
    if not isinstance(mid, str) or not ID_RE.match(mid) or mid in RESERVED_IDS:
        raise ManifestError(f'id {mid!r}: lowercase letter first, then a-z 0-9 _ -, max 40, not reserved')
    name = m['name']
    if not isinstance(name, str) or not 1 <= len(name) <= 60 or not name.isprintable():
        raise ManifestError('name must be 1..60 printable characters')
    kind = _enum(m['kind'], KINDS, 'kind')

    rt = m['runtime']
    _keys(rt, {'type', 'start', 'profile', 'entry'}, {'type', 'entry'}, 'runtime')
    rtype = _enum(rt['type'], RUNTIMES, 'runtime.type')
    start = _enum(rt.get('start', 'always_on' if rtype == 'lan_games_module' else None) or '',
                  STARTS, 'runtime.start')
    if (rtype == 'emulator_profile') != ('profile' in rt):
        raise ManifestError('runtime.profile is required for emulator_profile and forbidden otherwise')
    if 'profile' in rt and (not isinstance(rt['profile'], str) or not ID_RE.match(rt['profile'])):
        raise ManifestError('runtime.profile must be a profile id')
    if kind == 'native' and rtype == 'emulator_profile':
        raise ManifestError('a native game cannot use an emulator profile')
    if kind == 'emulated' and rtype == 'lan_games_module':
        raise ManifestError('an emulated game cannot be a LAN Games module')
    entry = check_entry(rt['entry'])

    pl = m['players']
    _keys(pl, {'min', 'max'}, {'min', 'max'}, 'players')
    pmin, pmax = _int(pl['min'], 1, MAX_PLAYERS, 'players.min'), _int(pl['max'], 1, MAX_PLAYERS, 'players.max')
    if pmin > pmax:
        raise ManifestError('players.min > players.max')
    screen = _enum(m['screen'], SCREENS, 'screen')

    inp = m['input']
    _keys(inp, {'model', 'slots'}, {'model'}, 'input')
    model = _enum(inp['model'], INPUTS, 'input.model')
    if (model == 'browser_native') == ('slots' in inp):
        raise ManifestError('input.slots is required for controller_slots/hotseat and forbidden for browser_native')
    slots = _int(inp['slots'], 1, MAX_SLOTS, 'input.slots') if 'slots' in inp else None
    if slots is not None and slots > pmax:
        raise ManifestError('input.slots > players.max')

    late = _enum(m.get('late_join', 'spectator_only'), LATE_JOIN, 'late_join')
    spect = _enum(m.get('spectators', 'watch'), SPECTATORS, 'spectators')
    for flag in ('shared_video', 'private_player_ui'):
        if not isinstance(m.get(flag, False), bool):
            raise ManifestError(f'{flag} must be true or false')
    if m.get('personal_viewports') is not None:
        raise ManifestError('personal_viewports must be null in v0 (its format is still OPEN)')
    a11y = m.get('accessibility', {})
    _keys(a11y, set(A11Y_KEYS), set(), 'accessibility')
    for k, v in a11y.items():
        if v not in TRI or (isinstance(v, int) and not isinstance(v, bool)):
            raise ManifestError(f'accessibility.{k} must be true, false or "unknown"')

    out = {'manifest': 0, 'id': mid, 'name': name, 'kind': kind,
           'runtime': {'type': rtype, 'start': start, 'entry': entry},
           'players': {'min': pmin, 'max': pmax}, 'screen': screen,
           'input': {'model': model}, 'late_join': late, 'spectators': spect,
           'shared_video': m.get('shared_video', False), 'personal_viewports': None,
           'private_player_ui': m.get('private_player_ui', False),
           'accessibility': {k: a11y.get(k, 'unknown') for k in A11Y_KEYS}}
    if 'profile' in rt:
        out['runtime']['profile'] = rt['profile']
    if slots is not None:
        out['input']['slots'] = slots
    return out


def load_file(path):
    with open(path, encoding='utf-8') as f:
        m = validate(parse(f.read()))
    stem = os.path.splitext(os.path.basename(path))[0]
    if m['id'] != stem:
        raise ManifestError(f'{path}: id {m["id"]!r} does not match the file name')
    return m


def load_builtin(folder=os.path.join(HERE, 'builtin')):
    return [load_file(os.path.join(folder, n)) for n in sorted(os.listdir(folder)) if n.endswith('.json')]


def load_overlay(path=os.path.join(HERE, 'lan-overlay.json')):
    with open(path, encoding='utf-8') as f:
        data = parse(f.read())
    if not isinstance(data, dict):
        raise ManifestError('overlay must map ids to objects')
    for gid, extra in data.items():
        _keys(extra, {'private_player_ui', 'accessibility'}, set(), f'overlay {gid}')
    return data


def derive_lan(api_games, overlay=None):
    """Manifests for LAN Games titles from the games server's own GET /api/games answer.
    Returns (manifests, problems). Hidden titles are skipped; titles without min_p/max_p are
    reported, not guessed."""
    overlay = overlay or {}
    out, problems = [], []
    rows = [(g, 'lan_games_module', f"/games/{g.get('slug')}/") for g in api_games.get('games', [])]
    rows += [(g, 'external', g.get('url')) for g in api_games.get('external', [])]
    for g, rtype, entry in rows:
        slug = g.get('slug')
        if g.get('hidden'):
            continue
        if g.get('min_p') is None or g.get('max_p') is None:
            problems.append(f'{slug}: no min_p/max_p in the registry')
            continue
        m = {'manifest': 0, 'id': slug, 'name': g.get('title') or slug, 'kind': 'native',
             'runtime': {'type': rtype, 'start': 'always_on', 'entry': entry},
             'players': {'min': g['min_p'], 'max': g['max_p']},
             # The registry's `tv` flag is what the hub labels "TV required"; it cannot say optional.
             'screen': 'tv_required' if g.get('tv') else 'no_tv_needed',
             'input': {'model': 'browser_native'},
             'late_join': 'spectator_only',          # LAN Games locks players at the countdown
             'spectators': 'watch'}
        m.update(overlay.get(slug, {}))
        try:
            out.append(validate(m))
        except ManifestError as e:
            problems.append(f'{slug}: {e}')
    return out, problems


def catalog(manifests):
    """Catalog entries the party service / reference model understand. Only games reachable on
    the party origin (entry not null) can be selected."""
    ids = [m['id'] for m in manifests]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ManifestError(f'duplicate game ids: {sorted(dupes)}')
    out = []
    for m in manifests:
        if m['runtime']['entry'] is None:
            continue
        slots = m['input'].get('slots')
        out.append({'id': m['id'], 'name': m['name'],
                    'max_players': slots or m['players']['max'],
                    'late_join': m['late_join'], 'launch': m['runtime']['start'],
                    'href': m['runtime']['entry'],
                    # what a launcher needs to start a 'service' game (never a command line)
                    'runtime': {k: m['runtime'][k] for k in ('type', 'profile') if k in m['runtime']},
                    'open_seat': m['late_join'] == 'supported' and m['input']['model'] == 'controller_slots',
                    'screen': m['screen']})
    return out


def cross_check_ps1(manifests, titles_dir):
    """A PS1 manifest and its title profile agree (ps1/titles/*.json on the PS1 branch)."""
    problems = []
    profiles = {}
    for n in sorted(os.listdir(titles_dir)):
        if n.endswith('.json'):
            with open(os.path.join(titles_dir, n), encoding='utf-8') as f:
                profiles[n[:-5]] = json.load(f)
    ps1 = [m for m in manifests if m['runtime']['type'] == 'emulator_profile']
    for m in ps1:
        prof = profiles.get(m['runtime']['profile'])
        if prof is None:
            problems.append(f"{m['id']}: no title profile {m['runtime']['profile']!r}")
            continue
        if m['id'] != 'ps1-' + m['runtime']['profile']:
            problems.append(f"{m['id']}: id must be ps1-<profile>")
        if m['input'].get('slots') != prof.get('stream_slots'):
            problems.append(f"{m['id']}: input.slots {m['input'].get('slots')} != stream_slots {prof.get('stream_slots')}")
        if m['input']['model'] == 'hotseat' and prof.get('stream_slots') != 1:
            problems.append(f"{m['id']}: hotseat needs exactly one stream slot")
    used = {m['runtime']['profile'] for m in ps1}
    problems += [f'profile {p!r} has no manifest' for p in sorted(set(profiles) - used)]
    return problems
