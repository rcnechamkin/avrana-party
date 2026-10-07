"""PS1 title profiles as first-party provider data: a strict loader, deterministic RetroArch
configuration, a check of the owner's content and an XTest keyboard InputProvider (AVR-309).

Nothing here launches an emulator, opens a port, creates a device or reads game data into the
repository. A title is DATA (ps1/titles/<id>.json), never raw RetroArch configuration: this module
validates it against an allowlist and GENERATES the per-title core options and RetroArch override
from it, so a profile cannot load plugins, open ports, redirect folders or remap another player's
keys (docs/design/GAME-INSTALLATION.md, "Emulated titles are content plus a small profile"). Only
settings verified on real hardware are allowed: a new value needs a hardware check before it is
added here.

Recovered from branch experiment/ps1-title-profiles at 4b8fa60afecb4868be0816f4b908b752bc33296d
(ps1/profiles.py, and the X11, XTestPad and BANKS parts of ps1/stream_ps1.py) with `git show`; the
branch itself was not merged. ps1/README.md says what is and is not proven.

One source of truth. The Game Contract (contracts/games/ps1-<id>.json, extension net.avrana.ps1)
owns a title's serial, stream slots and multitap setting. The profile repeats them because the
generators read them from it, and load_checked() refuses any difference (ContractMismatchError), so
service code uses load_checked(). load() reads the profile alone.

The owner's content is configuration, never a path in this repository (the names are provisional;
AVR-310 decides the final ones):

    AVRANA_PS1_CONTENT   the content root: the BIOS image and the disc folders (read-only)
    AVRANA_PS1_CORE      the pinned libretro core, pcsx_rearmed_libretro.so

    python3 -m avrana.providers.ps1 check <title> [--content DIR] [--core FILE]

check_content() looks at the files a title needs, reads the cue sheet and hashes the core: nothing
else is opened, and a report names files relative to the content root, never absolute paths.

XTestKeysProvider presses X keys in a PRIVATE display, so no input device exists for any other
process to find (the live arcade's RetroArch hot-plugs every uinput pad it sees). libX11 and
libXtst load through ctypes when a controller is first opened, so this module imports anywhere.
"""
import json
import os
import re
import unicodedata
from pathlib import Path

from avrana import REPO_ROOT
from avrana.contracts import provider_metadata, strictjson

PS1_DIR = REPO_ROOT / 'ps1'
TITLES = PS1_DIR / 'titles'
GAME_CONTRACTS = REPO_ROOT / 'contracts' / 'games'

# Bit order of a PS1 digital pad, and the order of the keys in every bank below.
BUTTONS = ('up', 'down', 'left', 'right', 'cross', 'circle', 'square', 'triangle',
           'l1', 'r1', 'l2', 'r2', 'start', 'select')
# X keysyms per seat, in BUTTONS order. MUST match input_playerN_* in ps1/mode-xvfb.cfg (tested).
# Keep scroll_lock (the hotkey enable), num_lock and caps_lock out of the banks.
BANKS = (
    ('Up', 'Down', 'Left', 'Right', 'z', 'x', 'a', 's', 'q', 'w', 'e', 'r', 'Return', 'Shift_R'),
    ('t', 'g', 'f', 'h', 'v', 'b', 'n', 'm', 'y', 'u', 'i', 'o', '1', '2'),
    ('KP_8', 'KP_5', 'KP_4', 'KP_6', 'KP_1', 'KP_2', 'KP_7', 'KP_9', 'KP_0', 'KP_Decimal',
     'KP_Divide', 'KP_Multiply', 'KP_Enter', 'KP_Add'),
    ('F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7', 'F8', 'F11', 'F12', 'Prior', 'Next', 'F9', 'F10'),
)
MIN_HOLD = 0.040      # RetroArch polls the keymap once per frame; a shorter tap vanishes.

ID_RE = re.compile(r'[a-z][a-z0-9_-]{0,31}')
SERIAL_RE = re.compile(r'S[A-Z]{3}-[0-9]{5}')    # the shape provider_metadata.ps1() accepts
KEYS = {'version', 'id', 'name', 'title', 'serial', 'cue', 'retroarch_users', 'stream_slots',
        'multitap', 'notes'}
REQUIRED = KEYS - {'notes', 'serial', 'title'}
MULTITAP = ('disabled', 'port 2')   # verified on hardware; "port 1" makes the game ignore all input
MAX_USERS = 5                       # mode-xvfb.cfg binds keyboard banks for RetroArch users 1-5
MAX_SLOTS = len(BANKS)              # a seat needs a key bank: 4 (user 5 has none)
MAX_PROFILE_BYTES = 16 * 1024

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
    """A profile, a contract or a pin is refused; the message says why."""


class DuplicateKeyError(ProfileError):
    """The same JSON key appears twice: most parsers would let the later value win silently."""


class UnknownKeysError(ProfileError):
    """A key outside the allowlist. Raw RetroArch settings are never accepted."""


class ContentPathError(ProfileError):
    """A content path that is absolute, uses '..' or leaves the content root."""


class SlotsExceedUsersError(ProfileError):
    """stream_slots above retroarch_users: a seat would have no RetroArch user to drive."""


class MultitapError(ProfileError):
    """A multitap setting that was not verified on hardware."""


class ContractMismatchError(ProfileError):
    """The profile and the title's Game Contract disagree, or the contract is not a PS1 contract."""


def _no_duplicates(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise DuplicateKeyError(f'duplicate key {key!r}')
        seen[key] = value
    return seen


def _refuse_constant(name):
    raise ProfileError(f'invalid JSON ({name} is not a JSON number)')


def _one_line(who, field, value, longest):
    """A string of 1..longest characters with no control, format or line-separator character, so it
    can never carry a second configuration line into a generated file."""
    if (not isinstance(value, str) or not 1 <= len(value) <= longest
            or any(unicodedata.category(c)[0] == 'C' or unicodedata.category(c) in ('Zl', 'Zp')
                   for c in value)):
        raise ProfileError(f'{who}: {field} must be 1-{longest} characters on one line')


def _relative_cue(who, cue):
    if (not isinstance(cue, str) or not cue.endswith('.cue') or len(cue) > 512
            or cue.startswith(('/', '\\')) or re.match(r'[A-Za-z]:', cue)
            or '..' in re.split(r'[\\/]', cue) or any(ord(c) < 32 or ord(c) == 127 for c in cue)):
        raise ContentPathError(f'{who}: cue must be a relative path to a .cue without ".."')


def validate(p, title_id=None):
    """Check one profile object against the allowlist and return it. `title_id` is the file name it
    was read from: when given, the profile's id must match it."""
    who = title_id or (p['id'] if isinstance(p, dict) and isinstance(p.get('id'), str) else 'profile')
    if not isinstance(p, dict):
        raise ProfileError(f'{who}: profile must be an object')
    unknown, missing = set(p) - KEYS, REQUIRED - set(p)
    if unknown:
        raise UnknownKeysError(f'{who}: unknown keys {sorted(map(str, unknown))}')
    if missing:
        raise ProfileError(f'{who}: missing keys {sorted(missing)}')
    if type(p['version']) is not int or p['version'] != 1:
        raise ProfileError(f'{who}: unsupported version {p["version"]!r}')
    if not isinstance(p['id'], str) or not ID_RE.fullmatch(p['id']):
        raise ProfileError(f'{who}: bad id {p["id"]!r}')
    if title_id is not None and p['id'] != title_id:
        raise ProfileError(f'{who}: id {p["id"]!r} does not match the file name')
    _relative_cue(who, p['cue'])
    users, slots = p['retroarch_users'], p['stream_slots']
    for field, value, highest in (('retroarch_users', users, MAX_USERS), ('stream_slots', slots, MAX_SLOTS)):
        if type(value) is not int or not 1 <= value <= highest:
            raise ProfileError(f'{who}: {field} must be an integer 1..{highest}')
    if slots > users:
        raise SlotsExceedUsersError(f'{who}: stream_slots ({slots}) exceeds retroarch_users ({users})')
    if p['multitap'] not in MULTITAP:
        raise MultitapError(f'{who}: multitap must be one of {MULTITAP} (hardware-verified values)')
    _one_line(who, 'name', p['name'], 80)
    if 'title' in p:
        _one_line(who, 'title (what players see)', p['title'], 40)
    if 'notes' in p:
        _one_line(who, 'notes', p['notes'], 2000)
    if 'serial' in p and not (isinstance(p['serial'], str) and SERIAL_RE.fullmatch(p['serial'])):
        raise ProfileError(f'{who}: serial must be four capital letters, a hyphen and five digits')
    return p


def load(title_id, titles_dir=TITLES):
    """Read and validate one profile. Raises ProfileError, or the subclass that names the refusal."""
    if not isinstance(title_id, str) or not ID_RE.fullmatch(title_id):
        raise ProfileError(f'bad title id {title_id!r}')
    path = os.path.join(titles_dir, title_id + '.json')
    try:
        size = os.path.getsize(path)
    except FileNotFoundError:
        raise ProfileError(f'unknown title {title_id!r}') from None
    except OSError as e:
        raise ProfileError(f'{title_id}: cannot read the profile ({e.strerror})') from None
    if size > MAX_PROFILE_BYTES:
        raise ProfileError(f'{title_id}: a profile is at most {MAX_PROFILE_BYTES} bytes')
    try:
        with open(path, encoding='utf-8') as f:
            p = json.load(f, object_pairs_hook=_no_duplicates, parse_constant=_refuse_constant)
    except ProfileError as e:       # a duplicate key or a non-finite number, raised by the parser hooks
        raise type(e)(f'{title_id}: {e}') from None
    except json.JSONDecodeError as e:
        raise ProfileError(f'{title_id}: invalid JSON ({e})') from None
    except UnicodeDecodeError:
        raise ProfileError(f'{title_id}: invalid JSON (not UTF-8 text)') from None
    except OSError as e:
        raise ProfileError(f'{title_id}: cannot read the profile ({e.strerror})') from None
    return validate(p, title_id)


def available(titles_dir=TITLES):
    """Ids of every valid profile, sorted. An invalid file raises: a broken title is loud."""
    ids = sorted(f[:-5] for f in os.listdir(titles_dir) if f.endswith('.json'))
    for title_id in ids:
        load(title_id, titles_dir)
    return ids


def stream_slots(titles_dir=TITLES):
    """{id: controller seats the stream offers} for every title."""
    return {i: load(i, titles_dir)['stream_slots'] for i in available(titles_dir)}


# --- the Game Contract is the source of truth -------------------------------------------------

def load_contract(title_id, contracts_dir=GAME_CONTRACTS):
    """The title's Game Contract, contracts/games/ps1-<id>.json, read strictly."""
    if not isinstance(title_id, str) or not ID_RE.fullmatch(title_id):
        raise ProfileError(f'bad title id {title_id!r}')
    path = Path(contracts_dir) / f'ps1-{title_id}.json'
    try:
        return strictjson.load_path(path)
    except FileNotFoundError:
        raise ContractMismatchError(f'{title_id}: there is no Game Contract {path.name}') from None
    except (OSError, ValueError) as e:      # strictjson.StrictJSONError and UnicodeDecodeError are ValueErrors
        raise ContractMismatchError(f'{title_id}: Game Contract {path.name} cannot be read ({e})') from None


def cross_check(profile, contract):
    """Raise ContractMismatchError unless the profile agrees with its Game Contract on the serial,
    the stream slots and the multitap setting (extension net.avrana.ps1). Every difference is
    named in one message. The contract's own PS1 block must be valid too: the catalog's validator
    (avrana.contracts.provider_metadata.ps1) runs first."""
    validate(profile)
    title = profile['id']
    try:
        provider_metadata.ps1(contract)
        meta = contract['extensions']['net.avrana.ps1']
        runtime_profile = contract['runtime']['profile']
        contract_id = contract['id']
    except (KeyError, TypeError, AttributeError, ValueError) as e:
        raise ContractMismatchError(f'{title}: the Game Contract is not a valid PS1 contract ({e})') from None
    # The contract writes the multitap setting as multitap_port: 2 (a title with a multitap) or
    # multitap: "disabled"; the profile writes the RetroArch core option's words, "port 2" or "disabled".
    declared = set()
    if 'multitap_port' in meta:
        declared.add(f'port {meta["multitap_port"]}')
    if 'multitap' in meta:
        declared.add(meta['multitap'] if isinstance(meta['multitap'], str) else repr(meta['multitap']))
    problems = []
    if runtime_profile != title:
        problems.append(f'title: profile {title!r}, contract runtime profile {runtime_profile!r}')
    if profile.get('serial') != meta['serial']:
        problems.append(f'serial: profile {profile.get("serial")!r}, contract {meta["serial"]!r}')
    if profile['stream_slots'] != meta['stream_slots']:
        problems.append(f'stream_slots: profile {profile["stream_slots"]}, contract {meta["stream_slots"]}')
    if declared != {profile['multitap']}:
        problems.append(f'multitap: profile {profile["multitap"]!r}, contract {sorted(declared)}')
    if problems:
        raise ContractMismatchError(f'{title}: the profile disagrees with Game Contract {contract_id}: '
                                    + '; '.join(problems))


def load_checked(title_id, titles_dir=TITLES, contracts_dir=GAME_CONTRACTS):
    """The profile, proven to agree with its Game Contract. This is what service code loads."""
    profile = load(title_id, titles_dir)
    cross_check(profile, load_contract(title_id, contracts_dir))
    return profile


# --- generated configuration ------------------------------------------------------------------

def core_options(p):
    """The core-options file content for a profile: UTF-8, LF line endings."""
    validate(p)
    options = list(COMMON_OPTIONS)
    options.insert(MULTITAP_LINE, ('pcsx_rearmed_multitap', p['multitap']))
    return ''.join(f'{key} = "{value}"\n' for key, value in options)


def retroarch_config(p):
    """The per-title RetroArch override: only input_max_users, generated from the profile (UTF-8, LF)."""
    validate(p)
    serial = ' ' + p['serial'] if p.get('serial') else ''
    return (f'# {p["name"]}{serial} — generated from ps1/titles/{p["id"]}.json; do not edit\n'
            f'input_max_users = "{p["retroarch_users"]}"\n')


def cue_path(p, root):
    """The profile's cue sheet under the owner's content root. Refuses a path that leaves the root
    once symbolic links are resolved."""
    validate(p)
    base = Path(root).resolve()
    full = base.joinpath(*re.split(r'[\\/]', p['cue'])).resolve()
    if not full.is_relative_to(base):
        raise ContentPathError(f'{p["id"]}: cue escapes the content root')
    return full
