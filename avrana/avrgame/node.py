"""What an EXPERIMENTAL .avrgame package that names the `node` runtime may contain, and how it starts.

EXPERIMENTAL: names and values may change. Pure checks on names and bytes: nothing here runs,
imports or requires Node.

A Node package starts as `node <entry>.mjs [args...]`: the first argument is the entry, an ES
module file of the package (`.mjs`; not `.js` or `.cjs`, whose meaning depends on a package.json),
outside any `node_modules`. Nothing after it is an option of Node: Node stops reading options at the
script. Dependencies are vendored as plain files under `node_modules`: nothing is fetched, built or
run for a package, and the `scripts` of a vendored package.json are never read. Compiled code is
refused by name and by content, because it is not reviewable source. That is review hygiene, not a
boundary: where the package runs is what confines it.
"""
from .common import clip, name_problem

NAME = 'node'
ENTRY_SUFFIX = '.mjs'
MODULES_DIR = 'node_modules'
ENTRY_RULE = ('for node the first argument is the entry: an ES module file of the package ending in ".mjs" '
              '(not ".js" or ".cjs"), a relative "/"-separated path outside node_modules; '
              'it is never an option of Node')
# Compiled code, by name. `.node` is a native addon: a shared library Node loads into the process.
NATIVE_SUFFIXES = ('.node', '.so', '.dylib', '.dll', '.exe')
# Compiled code, by content: ELF, and Mach-O in its four byte orders and the fat form.
NATIVE_MAGIC = (b'\x7fELF', b'\xfe\xed\xfa\xce', b'\xfe\xed\xfa\xcf', b'\xce\xfa\xed\xfe', b'\xcf\xfa\xed\xfe',
                b'\xca\xfe\xba\xbe')
MAGIC_BYTES = 4
NATIVE_MESSAGE = ('compiled code (a native addon, shared library or executable) is not allowed in a Node package: '
                  'it is not reviewable source; vendor pure JavaScript (or WebAssembly) only')


def entry_form(args):
    """True for ["<entry>.mjs", ...]: the one way a node package starts."""
    return isinstance(args, list) and len(args) >= 1 and entry_problem(args[0]) is None


def entry_problem(entry):
    """Why `entry` cannot be the entry of a Node package, or None."""
    if not isinstance(entry, str) or name_problem(entry, 'entry') is not None:
        return ENTRY_RULE
    if entry.startswith('-') or not entry.endswith(ENTRY_SUFFIX) or MODULES_DIR in entry.split('/'):
        return ENTRY_RULE
    return None


def native_name_problem(name):
    """Why a file of this name must not be in a Node package, or None."""
    if str(name).rsplit('/', 1)[-1].lower().endswith(NATIVE_SUFFIXES):
        return f'entry {clip(name)}: {NATIVE_MESSAGE}'
    return None


def native_content_problem(name, head):
    """Why a file that begins with the bytes `head` must not be in a Node package, or None."""
    if bytes(head[:MAGIC_BYTES]) in NATIVE_MAGIC:
        return f'entry {clip(name)}: {NATIVE_MESSAGE}'
    return None
