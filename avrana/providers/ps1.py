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
import argparse
import dataclasses
import hashlib
import json
import os
import re
import stat
import sys
import time
import unicodedata
from pathlib import Path, PurePosixPath

from avrana import REPO_ROOT
from avrana.contracts import provider_metadata, strictjson
from avrana.providers.base import ProviderInfo

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
    except RecursionError:          # thousands of open brackets fit in 16 KiB
        raise ProfileError(f'{title_id}: invalid JSON (nested too deeply)') from None
    except (ValueError, OverflowError):    # not a JSONDecodeError: an integer of over 4300 digits, for one
        raise ProfileError(f'{title_id}: invalid JSON (a number the parser cannot take)') from None
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
    try:
        base = Path(root).resolve()
        full = base.joinpath(*re.split(r'[\\/]', p['cue'])).resolve()
    except RuntimeError:     # links that loop: Python before 3.13 raises instead of leaving the path as it is
        raise ContentPathError(f'{p["id"]}: the content path loops through links') from None
    if not full.is_relative_to(base):
        raise ContentPathError(f'{p["id"]}: cue escapes the content root')
    return full


# --- the owner's content ----------------------------------------------------------------------

ENV_CONTENT = 'AVRANA_PS1_CONTENT'
ENV_CORE = 'AVRANA_PS1_CORE'
CORE_PIN = PS1_DIR / 'evidence' / 'selected-core.json'
BIOS_NAME = 'SCPH1001.BIN'   # the US BIOS the hardware runs used (SCPH-1001 v2.2), by exactly this name
BIOS_SIZE = 524288           # a PS1 BIOS image is 512 KiB
MAX_CUE_BYTES = 1 << 20      # a cue sheet is a few hundred bytes: anything larger is not one
MAX_CUE_FILES = 99           # a disc has at most 99 tracks, so a cue sheet names at most that many files
CUE_FILE = re.compile(r'\s*FILE\s+(?:"([^"]*)"|(\S+))', re.IGNORECASE)

# Every way the content check can fail has its own code (docs/runbooks/ps1-titles.md says what to do).
FAILURES = {
    'content_root_unset': 'no content root was given',
    'content_root_missing': 'the content root is not a folder',
    'unreadable': 'a file or folder could not be looked at',
    'cue_outside_root': 'the cue path leads out of the content root, or loops through links',
    'cue_missing': 'the cue sheet is not there',
    'cue_invalid': 'the cue sheet cannot be read as a cue sheet',
    'cue_no_files': 'the cue sheet names no file',
    'bin_unsafe': 'the cue sheet names a file outside its own folder',
    'bin_missing': 'a file the cue sheet names is not there',
    'bios_missing': 'the BIOS image is not in the content root under its exact name',
    'bios_wrong_size': f'the BIOS image is not {BIOS_SIZE} bytes',
    'core_unset': 'no core was given',
    'core_missing': 'the core file is not there',
    'core_pin_invalid': "the repository's core pin is unusable",
    'core_hash_mismatch': 'the core is not the pinned build',
}


@dataclasses.dataclass(frozen=True)
class Check:
    name: str       # content_root, cue, bin, bios or core
    subject: str    # what was looked at: relative to the content root, or a bare file name
    ok: bool
    code: str       # 'ok', or one key of FAILURES
    detail: str     # a sentence for the owner

    def __post_init__(self):
        if self.code not in ('ok', *FAILURES) or self.ok != (self.code == 'ok'):
            raise ValueError(f'inconsistent check {self.name!r}: {self.code!r}, ok={self.ok}')

    def to_dict(self):
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class ContentReport:
    title: str
    checks: tuple

    @property
    def ok(self):
        return all(check.ok for check in self.checks)

    @property
    def failures(self):
        return tuple(check for check in self.checks if not check.ok)

    def to_dict(self):
        """JSON-safe. Files are named relative to the content root or by bare name, never by an
        absolute path of the owner's machine."""
        return {'title': self.title, 'ok': self.ok, 'checks': [check.to_dict() for check in self.checks]}


def file_sha256(path, chunk=1 << 20):
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(chunk), b''):
            digest.update(block)
    return digest.hexdigest()


def _pin_sha256(pin):
    sha = pin.get('so_sha256') if isinstance(pin, dict) else None
    if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{64}', sha):
        raise ProfileError('the core pin has no lowercase hex so_sha256')
    return sha


def load_core_pin(path=CORE_PIN):
    """ps1/evidence/selected-core.json, the core build the hardware runs were made with. The check
    uses its so_sha256 only; the rest of the file is provenance."""
    try:
        pin = strictjson.load_path(path)
    except (OSError, ValueError, RecursionError) as e:
        raise ProfileError(f'the core pin {Path(path).name} cannot be read ({e})') from None
    try:
        _pin_sha256(pin)
    except ProfileError as e:
        raise ProfileError(f'{Path(path).name}: {e}') from None
    return pin


def cue_files(text):
    """The file names a cue sheet's FILE lines reference, in order, each once."""
    names = []
    for line in text.splitlines():
        match = CUE_FILE.match(line)
        if match:
            name = match[1] if match[1] is not None else match[2]
            if name not in names:
                names.append(name)
    return names


def _inside_folder(name):
    """A file name a cue sheet may use: relative, no '..', no control character."""
    return (bool(name) and not name.startswith(('/', '\\')) and not re.match(r'[A-Za-z]:', name)
            and '..' not in re.split(r'[\\/]', name) and all(ord(c) >= 32 and ord(c) != 127 for c in name))


def _shown(name, longest=80):
    return name if len(name) <= longest else name[:longest] + '...'


def _is_file(path):
    """Whether `path` is a regular file. Only "not there" is False: a folder the user may not enter
    raises PermissionError, which check_content reports as 'unreadable' (Path.is_file() hides that
    from Python 3.13 on, and would turn it into "not there")."""
    try:
        return stat.S_ISREG(os.stat(path).st_mode)
    except (FileNotFoundError, NotADirectoryError):
        return False


def _is_dir(path):
    try:
        return stat.S_ISDIR(os.stat(path).st_mode)
    except (FileNotFoundError, NotADirectoryError):
        return False


def _check_disc(profile, base, add):
    rel = profile['cue']
    try:
        cue = cue_path(profile, base)
    except ContentPathError:
        add('cue', rel, 'cue_outside_root', 'the cue sheet resolves to a place outside the content root '
                                            '(a link that leads out of it, or that loops?)')
        return
    if not _is_file(cue):
        add('cue', rel, 'cue_missing', 'the cue sheet is not there: the disc folders belong directly '
                                       'under the content root')
        return
    with open(cue, 'rb') as f:
        data = f.read(MAX_CUE_BYTES + 1)
    problem, names = None, []
    if len(data) > MAX_CUE_BYTES:
        problem = 'is larger than 1 MiB'
    else:
        try:
            names = cue_files(data.decode('utf-8-sig'))
        except UnicodeDecodeError:
            problem = 'is not UTF-8 text'
        else:
            if len(names) > MAX_CUE_FILES:
                problem = f'names more than {MAX_CUE_FILES} files'
    if problem:
        add('cue', rel, 'cue_invalid', f'the cue sheet {problem}')
        return
    if not names:
        add('cue', rel, 'cue_no_files', 'the cue sheet has no FILE line, so there is no disc image to find')
        return
    add('cue', rel, 'ok', 'the cue sheet is there')
    shown = PurePosixPath(rel.replace('\\', '/')).parent
    for name in names:
        if not _inside_folder(name):
            add('bin', _shown(name), 'bin_unsafe',
                f'the cue sheet names {_shown(name)!r}, which is not a file in its own folder')
            continue
        subject = (shown / name.replace('\\', '/')).as_posix()
        if _is_file(cue.parent.joinpath(*re.split(r'[\\/]', name))):
            add('bin', subject, 'ok', 'the disc image is there')
        else:
            add('bin', subject, 'bin_missing', f'the cue sheet names {name!r}, which is not in the disc folder')


def _check_bios(base, add):
    # The exact name: the Pi's filesystem is case-sensitive and the launcher asks for SCPH1001.BIN. A
    # listing gives the names as they are stored, so this holds on a case-insensitive host too, where
    # stat() would find scph1001.bin under the other name.
    names = os.listdir(base)
    if BIOS_NAME not in names or not _is_file(base / BIOS_NAME):
        other = next((n for n in sorted(names) if n != BIOS_NAME and n.lower() == BIOS_NAME.lower()), None)
        hint = f'; the content root has {_shown(other)!r} instead, and the name must match exactly' if other else ''
        add('bios', BIOS_NAME, 'bios_missing', f'{BIOS_NAME} is not in the content root{hint}')
        return
    size = (base / BIOS_NAME).stat().st_size
    if size != BIOS_SIZE:
        add('bios', BIOS_NAME, 'bios_wrong_size',
            f'{BIOS_NAME} is {size} bytes; a PS1 BIOS image is exactly {BIOS_SIZE} bytes')
    else:
        add('bios', BIOS_NAME, 'ok', f'{BIOS_NAME} is {BIOS_SIZE} bytes')


def _check_core(core_path, env, pin, add):
    value = core_path if core_path not in (None, '') else env.get(ENV_CORE)
    if not value:
        add('core', ENV_CORE, 'core_unset',
            f'no core: pass one, or set {ENV_CORE} to the pinned pcsx_rearmed_libretro.so')
        return
    core = Path(value)
    if not _is_file(core):
        add('core', core.name, 'core_missing', f'the core file {core.name} is not there')
        return
    try:
        wanted = _pin_sha256(load_core_pin() if pin is None else pin)
    except ProfileError as e:
        add('core', core.name, 'core_pin_invalid', str(e))
        return
    found = file_sha256(core)
    if found != wanted:
        add('core', core.name, 'core_hash_mismatch',
            f'the core file {core.name} has SHA-256 {found[:16]}..., not the pinned {wanted[:16]}...: it is '
            f'not the build validated on hardware (ps1/evidence/selected-core.json)')
    else:
        add('core', core.name, 'ok', f'the core file {core.name} is the pinned build ({wanted[:16]}...)')


def check_content(profile, root=None, core_path=None, *, environ=None, pin=None):
    """Is the owner's content ready to run `profile`? Returns a ContentReport. A problem with the
    content is a failed Check with its own code and sentence, never an exception; a profile that
    fails validate() is the only thing raised.

    `root` (else $AVRANA_PS1_CONTENT) holds the BIOS image and the disc folders; `core_path` (else
    $AVRANA_PS1_CORE) is the libretro core. Nothing defaults to a place on this machine. The check
    looks at the files (that they exist, how big they are), reads the cue sheet to find the disc
    images and hashes the core against the pin (`pin` replaces the committed one, for tests); it
    never opens a disc image or the BIOS."""
    validate(profile)
    env = os.environ if environ is None else environ
    checks = []

    def add(name, subject, code, detail):
        checks.append(Check(name, subject, code == 'ok', code, detail))

    value = root if root not in (None, '') else env.get(ENV_CONTENT)

    def guarded(name, subject, what, step):
        try:
            step()
        except OSError as e:    # e.g. a folder the user running the check may not enter
            add(name, subject, 'unreadable', f'could not look at the {what}: {e.strerror or type(e).__name__} '
                                             '(the user running the check needs read access to the content)')

    def folder():
        base = Path(value)
        if not _is_dir(base):
            add('content_root', '.', 'content_root_missing', 'the content root is not a folder')
            return
        add('content_root', '.', 'ok', 'the content root is a folder')
        guarded('cue', profile['cue'], 'cue sheet and disc images', lambda: _check_disc(profile, base, add))
        guarded('bios', BIOS_NAME, 'BIOS image', lambda: _check_bios(base, add))

    if not value:
        add('content_root', '.', 'content_root_unset',
            f'no content root: pass one, or set {ENV_CONTENT} to the read-only folder that holds the BIOS '
            'image and the disc folders')
    else:
        guarded('content_root', '.', 'content root', folder)
    guarded('core', 'core', 'core file', lambda: _check_core(core_path, env, pin, add))
    return ContentReport(profile['id'], tuple(checks))


# --- the XTest input provider -----------------------------------------------------------------

DISPLAY_RE = re.compile(r':[0-9]{1,4}(\.[0-9]{1,2})?')    # a local display: never a host to connect to
INFO = ProviderInfo(
    id='xtest-keys', kind='input', offers=('input.virtual_gamepad',),
    implementation='X11 XTest key events (libX11 and libXtst through ctypes, nothing copied) into a private '
                   'display, one key bank per seat',
    isolation='private')


def _local_display(display):
    """`display` if it names a display on this machine (":99"). A name with a host in it makes Xlib connect
    to that machine over TCP, which no seat's keys are ever for."""
    if not isinstance(display, str) or not DISPLAY_RE.fullmatch(display):
        raise ValueError('display must be a local X display such as ":99"')
    return display


class X11:
    """One XTest connection to one display, by ctypes. The display is the PS1 instance's private
    Xvfb and nothing else: the launcher that starts it knows its name and its cookie file. A name that
    is not a local display (":99") is refused here, before any library is loaded, whoever calls.

    Known limit, as in the donor: Xlib's default I/O error handler ends the whole process when the
    display goes away. Run the provider in the process that owns the display (ps1/README.md)."""

    def __init__(self, display, xauthority=None, *, cdll=None):
        _local_display(display)
        import ctypes  # noqa: PLC0415 - only a machine that is about to press keys needs it
        load = ctypes.CDLL if cdll is None else cdll
        try:
            self.x = load('libX11.so.6')
            self.tst = load('libXtst.so.6')
        except OSError as e:
            raise RuntimeError(f'XTest needs libX11.so.6 and libXtst.so.6 (Linux with X11): {e}') from None
        x, tst = self.x, self.tst
        x.XOpenDisplay.restype = ctypes.c_void_p
        x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x.XStringToKeysym.restype = ctypes.c_ulong
        x.XStringToKeysym.argtypes = [ctypes.c_char_p]
        x.XKeysymToKeycode.restype = ctypes.c_ubyte
        x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        x.XFlush.argtypes = [ctypes.c_void_p]
        x.XCloseDisplay.argtypes = [ctypes.c_void_p]
        tst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        # XOpenDisplay reads the cookie file from the environment; it is needed for that call only.
        previous = os.environ.get('XAUTHORITY')
        if xauthority is not None:
            os.environ['XAUTHORITY'] = str(xauthority)
        try:
            self.dpy = x.XOpenDisplay(display.encode())
        finally:
            if xauthority is not None:
                if previous is None:
                    os.environ.pop('XAUTHORITY', None)
                else:
                    os.environ['XAUTHORITY'] = previous
        if not self.dpy:
            raise RuntimeError(f'cannot open PS1 display {display}')

    def _display(self):
        if not self.dpy:
            raise RuntimeError('the XTest connection is closed')
        return self.dpy

    def keycode(self, name):
        code = self.x.XKeysymToKeycode(self._display(), self.x.XStringToKeysym(name.encode()))
        if not code:
            raise RuntimeError(f'no keycode for {name}')
        return code

    def key(self, code, down):
        self.tst.XTestFakeKeyEvent(self._display(), code, int(down), 0)

    def flush(self):
        self.x.XFlush(self._display())

    def close(self):
        if self.dpy:
            dpy, self.dpy = self.dpy, None
            self.x.XCloseDisplay(dpy)


def _running_loop():
    import asyncio  # noqa: PLC0415
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


class XTestController:
    """One seat's controller (a VirtualController): its slot's fixed key bank on the shared
    connection. A snapshot only ever presses or releases keys of this bank, and the keys come from
    BANKS, never from the caller, so a seat cannot name a key or reach another seat's.

    A key is held at least MIN_HOLD seconds. A release that comes sooner waits out the rest of the
    hold: on the event loop's call_later when one is running (or was passed), else by sleeping in
    the caller, which never takes longer than MIN_HOLD. neutralize() and close() release at once."""

    def __init__(self, x11, slot, layout, *, clock=time.monotonic, sleep=time.sleep, loop=None, on_close=None):
        self.slot = slot
        self.layout = layout
        self.state = frozenset()         # the snapshot last applied: what the seat is holding
        self.updated = clock()           # clock() of that snapshot, for the stale-input policy
        self._x11, self._clock, self._sleep, self._loop, self._on_close = x11, clock, sleep, loop, on_close
        self._codes = {name: x11.keycode(key) for name, key in zip(BUTTONS, BANKS[slot])}
        self._down = {}                  # button -> clock() when its key went down, for keys down now
        self._timer = None
        self._closed = False
        self.release_all()               # also clears keys a crashed earlier process left down

    @property
    def device(self):
        """The arcade's Stream.cleanup() closes pad.device; this controller is its own device."""
        return self

    def set_state(self, pressed):
        if self._closed:
            raise RuntimeError('this XTest controller is closed')
        self.state = self.layout.parse(pressed)
        self.updated = self._clock()
        self._apply()

    update = set_state   # the name arcade/stream.py has always used

    def neutralize(self):
        self._cancel_timer()
        self.state = frozenset()
        self.updated = self._clock()
        if not self._closed:
            self.release_all()

    def close(self):
        if self._closed:
            return
        try:
            self._cancel_timer()
            self.state = frozenset()
            self.release_all()
        finally:
            self._closed = True
            if self._on_close is not None:
                self._on_close(self)

    def release_all(self):
        """Every key of this seat's bank up, whatever was held: unconditional, no minimum hold."""
        self._down.clear()
        for code in self._codes.values():
            self._x11.key(code, False)
        self._x11.flush()

    def _step(self):
        """Press what is wanted, release what may be released; return the seconds until the next
        release that has to wait for its minimum hold (None when nothing waits)."""
        now = self._clock()
        wait, sent = None, False
        for name, code in self._codes.items():
            held = name in self._down
            if name in self.state and not held:
                self._x11.key(code, True)
                self._down[name] = now
                sent = True
            elif held and name not in self.state:
                left = self._down[name] + MIN_HOLD - now
                if left > 0:
                    wait = left if wait is None else min(wait, left)
                    continue
                self._x11.key(code, False)
                del self._down[name]
                sent = True
        if sent:
            self._x11.flush()
        return wait

    def _apply(self):
        while True:
            wait = self._step()
            if wait is None:
                return
            loop = self._loop or _running_loop()
            if loop is None:
                self._sleep(wait)
                continue
            if self._timer is None:
                self._timer = loop.call_later(wait, self._expire)
            return

    def _expire(self):
        self._timer = None
        if not self._closed:
            self._apply()

    def _cancel_timer(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None


class XTestKeysProvider:
    """InputProvider over X11 XTest: each seat is a bank of keys in the PS1 instance's private
    display (ps1/mode-xvfb.cfg binds them), so no input device exists for another process to find.
    That is isolation 'private'; the uinput provider's is 'global'.

    Unlike uinput, a controller needs its display, so open() comes after the private Xvfb is up (the
    launcher creates it with RetroArch): the other way round from the base.py docstring. The
    connection is made at the first open(), shared by every seat, and closed by close().
    Not thread-safe: use it from the one thread (the event loop) that owns the seats."""
    info = INFO

    def __init__(self, display, xauthority=None, *, loop=None, clock=time.monotonic, sleep=time.sleep,
                 connect=None):
        _local_display(display)
        self.display, self.xauthority = display, xauthority
        self._loop, self._clock, self._sleep = loop, clock, sleep
        self._connect = X11 if connect is None else connect
        self._x11 = None
        self._seats = {}

    def open(self, slot, layout):
        if type(slot) is not int or not 0 <= slot < len(BANKS):
            raise ValueError(f'slot must be 0 to {len(BANKS) - 1}')
        unmapped = sorted(layout.names - set(BUTTONS))
        if unmapped:
            raise ValueError(f'no XTest key for {unmapped}')
        if slot in self._seats:
            raise ValueError(f'slot {slot} is already open')
        if self._x11 is None:
            self._x11 = self._connect(self.display, self.xauthority)
        pad = XTestController(self._x11, slot, layout, clock=self._clock, sleep=self._sleep, loop=self._loop,
                              on_close=self._forget)
        self._seats[slot] = pad
        return pad

    def _forget(self, pad):
        if self._seats.get(pad.slot) is pad:
            del self._seats[pad.slot]

    def close(self):
        """Release and close every open seat, then the connection. Safe to repeat. A seat that
        fails to release does not stop the others, or the connection, from closing: the first
        failure is raised at the end."""
        failure = None
        for pad in list(self._seats.values()):
            try:
                pad.close()
            except Exception as e:  # noqa: BLE001 - the other seats must still be released
                failure = failure or e
        if self._x11 is not None:
            x11, self._x11 = self._x11, None
            x11.close()
        if failure is not None:
            raise failure


# --- command line -----------------------------------------------------------------------------

def main(argv=None, environ=None, stdout=None, stderr=None):
    """python3 -m avrana.providers.ps1 check <title>: the content check, one line per check. Exit 0
    when everything passes, 1 when anything fails or the title is refused."""
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr
    parser = argparse.ArgumentParser(prog='python3 -m avrana.providers.ps1', description=__doc__.split('\n\n')[0])
    commands = parser.add_subparsers(dest='command', required=True)
    check = commands.add_parser('check', help="check the owner's content for one title; opens no disc image")
    check.add_argument('title')
    check.add_argument('--content', metavar='DIR', help=f'the content root (default: ${ENV_CONTENT})')
    check.add_argument('--core', metavar='FILE', help=f'the pinned core (default: ${ENV_CORE})')
    args = parser.parse_args(argv)
    try:
        profile = load_checked(args.title)
    except ProfileError as e:
        print(f'ps1: {e}', file=err)
        return 1
    report = check_content(profile, args.content, args.core, environ=environ)
    print(f'PS1 content check: {profile["id"]} ({profile.get("serial", "no serial")})', file=out)
    for c in report.checks:
        print(f'  ok    {c.name:<13}{c.subject}' if c.ok else f'  FAIL  {c.name:<13}{c.detail} [{c.code}]', file=out)
    failed = len(report.failures)
    print(f'all {len(report.checks)} checks passed' if not failed else
          f'{failed} of {len(report.checks)} checks failed: the content is not ready', file=out)
    return 0 if report.ok else 1


if __name__ == '__main__':
    sys.exit(main())
