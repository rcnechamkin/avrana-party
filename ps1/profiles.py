#!/usr/bin/env python3
"""PS1 title profiles: the only place that knows which titles exist (stdlib only).

A title is DATA — ps1/titles/<id>.json — never raw RetroArch config. The launcher and the stream
server read it through this module, which validates it against an allowlist and GENERATES the
per-title core options and RetroArch override, so a profile can't load plugins, open ports,
redirect folders or remap another player's keys (docs/design/GAME-INSTALLATION.md).

    profiles.py list                      titles, one per line
    profiles.py cue <id> --roms DIR       absolute cue path (DIR + the profile's relative path)
    profiles.py write <id> RUNDIR         RUNDIR/core-options.opt and RUNDIR/game.cfg
    profiles.py slots <id>                controller slots the stream offers

Only settings verified on real hardware are allowed (multitap "disabled" / "port 2"); a new
value needs a hardware check before it is added here.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TITLES = os.path.join(HERE, 'titles')
ID_RE = re.compile(r'^[a-z][a-z0-9_-]{0,31}$')
KEYS = {'version', 'id', 'name', 'serial', 'cue', 'retroarch_users', 'stream_slots',
        'multitap', 'notes'}
REQUIRED = KEYS - {'notes', 'serial'}
MULTITAP = ('disabled', 'port 2')          # verified values only
MAX_USERS = 5                              # mode-xvfb.cfg binds keyboard banks for players 1-5
MAX_SLOTS = 4                              # stream_ps1.py has 4 key banks (BANKS)

# Core options every title shares, in the order the pre-profile .opt files used; the per-title
# multitap line is inserted at MULTITAP_LINE.
COMMON_OPTIONS = (
    ('pcsx_rearmed_bios', 'auto'),
    ('pcsx_rearmed_show_bios_bootlogo', 'disabled'),
    ('pcsx_rearmed_region', 'auto'),
    ('pcsx_rearmed_drc', 'enabled'),
    ('pcsx_rearmed_frameskip_type', 'disabled'),
    ('pcsx_rearmed_neon_enhancement_enable', 'disabled'),
    ('pcsx_rearmed_memcard2', 'none'),
)
MULTITAP_LINE = 6


class ProfileError(ValueError):
    pass


def _no_duplicates(pairs):
    seen = {}
    for k, v in pairs:
        if k in seen:
            raise ProfileError(f'duplicate key {k!r}')
        seen[k] = v
    return seen


def load(title_id, titles_dir=TITLES):
    """Read and validate one profile. Raises ProfileError with a human-readable reason."""
    if not isinstance(title_id, str) or not ID_RE.match(title_id):
        raise ProfileError(f'bad title id {title_id!r}')
    path = os.path.join(titles_dir, title_id + '.json')
    try:
        with open(path, encoding='utf-8') as f:
            p = json.load(f, object_pairs_hook=_no_duplicates)
    except FileNotFoundError:
        raise ProfileError(f'unknown title {title_id!r}') from None
    except json.JSONDecodeError as e:
        raise ProfileError(f'{title_id}: invalid JSON ({e})') from None
    if not isinstance(p, dict):
        raise ProfileError(f'{title_id}: profile must be an object')
    unknown, missing = set(p) - KEYS, REQUIRED - set(p)
    if unknown:
        raise ProfileError(f'{title_id}: unknown keys {sorted(unknown)}')
    if missing:
        raise ProfileError(f'{title_id}: missing keys {sorted(missing)}')
    if p['version'] != 1:
        raise ProfileError(f'{title_id}: unsupported version {p["version"]!r}')
    if p['id'] != title_id:
        raise ProfileError(f'{title_id}: id {p["id"]!r} does not match the file name')
    cue = p['cue']
    if (not isinstance(cue, str) or not cue.endswith('.cue') or cue.startswith(('/', '\\'))
            or re.match(r'^[A-Za-z]:', cue) or '..' in re.split(r'[\\/]', cue)):
        raise ProfileError(f'{title_id}: cue must be a relative path to a .cue without ".."')
    users, slots = p['retroarch_users'], p['stream_slots']
    for name, v, hi in (('retroarch_users', users, MAX_USERS), ('stream_slots', slots, MAX_SLOTS)):
        if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= hi:
            raise ProfileError(f'{title_id}: {name} must be an integer 1..{hi}')
    if slots > users:
        raise ProfileError(f'{title_id}: stream_slots ({slots}) exceeds retroarch_users ({users})')
    if p['multitap'] not in MULTITAP:
        raise ProfileError(f'{title_id}: multitap must be one of {MULTITAP} (hardware-verified values)')
    for k in ('name', 'serial', 'notes'):
        if k in p and not isinstance(p[k], str):
            raise ProfileError(f'{title_id}: {k} must be a string')
    return p


def available(titles_dir=TITLES):
    """Ids of every valid profile, sorted. Invalid files raise: a broken title is loud."""
    ids = sorted(f[:-5] for f in os.listdir(titles_dir) if f.endswith('.json'))
    for i in ids:
        load(i, titles_dir)
    return ids


def stream_slots(titles_dir=TITLES):
    """{id: controller slots the stream offers} for every title."""
    return {i: load(i, titles_dir)['stream_slots'] for i in available(titles_dir)}


def core_options(p):
    """The core-options file content (LF line endings)."""
    opts = list(COMMON_OPTIONS)
    opts.insert(MULTITAP_LINE, ('pcsx_rearmed_multitap', p['multitap']))
    return ''.join(f'{k} = "{v}"\n' for k, v in opts)


def retroarch_override(p):
    """The per-title RetroArch override: only input_max_users, generated from the profile."""
    return (f'# {p["name"]}{" " + p["serial"] if p.get("serial") else ""} — generated from '
            f'ps1/titles/{p["id"]}.json; do not edit\n'
            f'input_max_users = "{p["retroarch_users"]}"\n')


def cue_path(p, roms):
    root = os.path.realpath(roms)
    full = os.path.realpath(os.path.join(root, *re.split(r'[\\/]', p['cue'])))
    if os.path.commonpath([root, full]) != root:
        raise ProfileError(f'{p["id"]}: cue escapes the ROM directory')
    return full


def write(p, run_dir):
    for name, text in (('core-options.opt', core_options(p)), ('game.cfg', retroarch_override(p))):
        with open(os.path.join(run_dir, name), 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)


def main(argv):
    try:
        if argv[:1] == ['list']:
            print('\n'.join(available()))
        elif len(argv) == 4 and argv[0] == 'cue' and argv[2] == '--roms':
            print(cue_path(load(argv[1]), argv[3]))
        elif len(argv) == 3 and argv[0] == 'write':
            write(load(argv[1]), argv[2])
        elif len(argv) == 2 and argv[0] == 'slots':
            print(load(argv[1])['stream_slots'])
        else:
            print(__doc__.split('\n\n')[1], file=sys.stderr)
            return 2
    except ProfileError as e:
        print(f'profiles: {e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
