"""Contract version shapes and the Party's support window (AVR-72 V1, V2, V4).

PROTOTYPE for docs/design/proposals/2026-10-26-contract-versioning-and-deprecation.md (owner decisions open). Pure parsing
and checking only: no contract changes version, no support file is published, and no validator calls this.

Two shapes (V1): a wire protocol is `avrana.<name>/v<MAJOR>`, a declaration `avrana.<name>/<MAJOR>.<MINOR>`.
A support window (V2) says, per contract, `current` and `min_supported` (and, for a declaration, the minor
it reads up to, which is `current`'s). `check` answers whether this Party accepts a version, and when it
does not, says why in the words the proposal's section 4 uses: a newer minor names the need for a newer
Party, an older major names the migration. Feature names (V4) are checked by `missing_features`.
"""
import re

WIRE = re.compile(r'^avrana\.([a-z][a-z0-9-]*)/v(0|[1-9][0-9]{0,3})$')
DECLARATION = re.compile(r'^avrana\.([a-z][a-z0-9-]*)/(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})$')
FEATURE = re.compile(r'^[a-z][a-z0-9_]{0,39}$')


class BadVersion(ValueError):
    pass


def parse(text):
    """(name, major, minor) for a declaration, (name, major, None) for a wire protocol, else BadVersion."""
    m = DECLARATION.match(text or '') if isinstance(text, str) else None
    if m:
        return m.group(1), int(m.group(2)), int(m.group(3))
    m = WIRE.match(text or '') if isinstance(text, str) else None
    if m:
        return m.group(1), int(m.group(2)), None
    raise BadVersion(f'not a contract version: {text!r}')


def _pair(text):
    major, _, minor = str(text).partition('.')
    if not major.isdigit() or (minor and not minor.isdigit()):
        raise BadVersion(f'not a window version: {text!r}')
    return int(major), int(minor) if minor else None


def check(version, window):
    """(accepted, words) for `version` against {current, min_supported} ("1.2" / "1.0", or "1" / "0" for a
    wire protocol)."""
    name, major, minor = parse(version)
    cur_major, cur_minor = _pair(window['current'])
    min_major, min_minor = _pair(window['min_supported'])
    if (minor is None) != (cur_minor is None):
        return False, f'{name}: a {"wire" if minor is None else "declaration"} version where the other shape is expected'
    if minor is None:
        if major > cur_major:
            return False, f'{name} v{major} needs a newer Party (this Party speaks v{min_major}–v{cur_major})'
        if major < min_major:
            return False, f'{name} v{major} is no longer supported (oldest v{min_major}); see its migration note'
        return True, f'{name} v{major} supported'
    if (major, minor) > (cur_major, cur_minor):
        return False, (f'{name} {major}.{minor} needs a newer Party '
                       f'(this Party supports {min_major}.{min_minor or 0}–{cur_major}.{cur_minor})')
    if (major, minor) < (min_major, min_minor or 0):
        return False, f'{name} {major}.{minor} is no longer supported (oldest {min_major}.{min_minor or 0}); see its migration note'
    return True, f'{name} {major}.{minor} supported'


def missing_features(required, offered):
    """The `requires.features` this Party lacks, sorted (V4). A malformed name counts as missing."""
    offered = {f for f in offered if isinstance(f, str) and FEATURE.match(f)}
    return sorted({str(f) for f in required or () if not (isinstance(f, str) and FEATURE.match(f) and f in offered)})
