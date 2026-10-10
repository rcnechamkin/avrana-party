"""Shared pieces of the experimental .avrgame library: the refusal type, the limits and the one
rule for what a path inside a package may look like.

EXPERIMENTAL: names and values may change. Freeze gates are unmet (see docs/design/AVRGAME-PACKAGE.md).
"""
import re
import unicodedata

FORMAT = 'avrana.avrgame/experimental.1'
MANIFEST_NAME = 'avrgame.json'
RECIPE_NAME = 'avrgame.build.json'
RECIPE_FORMAT = 'avrana.avrgame-build/experimental.1'

# Limits. Experimental: generous for a small native game, cheap to enforce on a Pi.
MAX_FILES = 2000
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
MAX_NAME_LENGTH = 200
MAX_DEPTH = 16
MAX_PROBLEMS = 50

SEGMENT = re.compile(r'^[A-Za-z0-9._+@=~-]+$')
RESERVED_DEVICES = frozenset(['CON', 'PRN', 'AUX', 'NUL', 'CLOCK$'] + [f'COM{i}' for i in range(1, 10)]
                             + [f'LPT{i}' for i in range(1, 10)])
DRIVE = re.compile(r'^[A-Za-z]:')


def clip(value, limit=60):
    """A bounded, escaped rendering of untrusted text for a message (never raw, never long)."""
    if not isinstance(value, str):
        return f'<{type(value).__name__}>'
    text = ascii(value)
    return text if len(text) <= limit else text[:limit - 3] + '...'


class Refused(Exception):
    """The package, archive, manifest or recipe is not acceptable. `problems` lists every reason."""

    def __init__(self, problems):
        if isinstance(problems, str):
            problems = [problems]
        self.problems = list(problems)
        super().__init__('; '.join(self.problems))


class Problems(list):
    """Collects problems (bounded) and raises them together."""

    def add(self, message):
        if len(self) < MAX_PROBLEMS:
            self.append(message)
        elif len(self) == MAX_PROBLEMS:
            self.append('... more problems not listed')

    def raise_if_any(self):
        if self:
            raise Refused(self)


def text_ok(value, low, high):
    """Printable text: bounded, no control or format characters, no surrounding space."""
    return (isinstance(value, str) and low <= len(value) <= high and value == value.strip()
            and all(unicodedata.category(c)[0] not in 'CZ' or c == ' ' for c in value))


def bytecode(name):
    parts = name.split('/')
    return '__pycache__' in parts or parts[-1].lower().endswith(('.pyc', '.pyo'))


def name_problem(name, what='path'):
    """Why `name` (a file path inside a package, '/'-separated, no trailing '/') is not allowed,
    or None. The rules are the same for archive entries, pack inputs and manifest paths."""
    if not isinstance(name, str):
        return f'{what}: must be a string'
    shown = clip(name)
    if not name:
        return f'{what}: empty name'
    if len(name) > MAX_NAME_LENGTH:
        return f'{what} {shown}: longer than {MAX_NAME_LENGTH} characters'
    if any(unicodedata.category(c) == 'Cc' for c in name):
        return f'{what} {shown}: contains a control or NUL character'
    if '\\' in name:
        return f'{what} {shown}: backslash; use "/" as the separator'
    if name.startswith('/'):
        return f'{what} {shown}: absolute path; paths are relative to the package root'
    if DRIVE.match(name) or ':' in name:
        return f'{what} {shown}: drive letter or ":" is not allowed'
    segments = name.split('/')
    if len(segments) > MAX_DEPTH:
        return f'{what} {shown}: deeper than {MAX_DEPTH} directories'
    for seg in segments:
        if seg == '':
            return f'{what} {shown}: empty path segment'
        if seg in ('.', '..'):
            return f'{what} {shown}: "." and ".." segments are not allowed'
        if seg.endswith(('.', ' ')):
            return f'{what} {shown}: a segment ends with "." or a space'
        if seg.startswith('.'):
            return f'{what} {shown}: hidden (dot) files and directories are not allowed'
        if seg.split('.')[0].upper() in RESERVED_DEVICES:
            return f'{what} {shown}: reserved device name {clip(seg)} (Windows)'
        if not SEGMENT.match(seg):
            return (f'{what} {shown}: only ASCII letters, digits and . _ + @ = ~ - are allowed '
                    'in file names')
    return None
