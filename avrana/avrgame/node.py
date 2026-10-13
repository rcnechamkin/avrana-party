"""The optional Node.js runtime of an EXPERIMENTAL .avrgame package (AVR-68): which build the
appliance runs, where it lives, and what a package that names it may contain.

EXPERIMENTAL: names and values may change. Data and pure checks only: nothing here runs, imports or
requires Node, so Party Core and a Python package are the same with or without the runtime.

The runtime is one pinned official build, installed by `avrana.ops.node_runtime` from a tarball the
operator supplies (never downloaded on the appliance) whose SHA-256 must equal the pin below, into
a root-owned directory named after the version. A package only says `"interpreter": "node"`; the
path is the appliance's.

A Node package starts as `node <entry>.mjs [args...]`: the first argument is the entry, an ES
module file of the package (`.mjs`; not `.js` or `.cjs`, whose meaning depends on a package.json),
outside any `node_modules`. Nothing after it is an option of Node: Node stops reading options at the
script. Dependencies are vendored as plain files under `node_modules`: nothing is fetched, built or
run at install (there is no npm on the appliance, and `scripts` of a vendored package.json are
never read). Compiled code is refused by name and by content, because it is not reviewable source.
That is review hygiene, not a boundary: the unit sandbox is the boundary.
"""
from types import MappingProxyType

from .common import clip, name_problem

NAME = 'node'
VERSION = '22.22.2'
RUNTIMES_ROOT = '/opt/avrana-runtimes'
ROOT = f'{RUNTIMES_ROOT}/node-{VERSION}'
EXECUTABLE = f'{ROOT}/bin/node'

# The official builds of nodejs.org/dist/v<VERSION>/ (SHASUMS256.txt), by this project's arch name.
ARCHIVES = MappingProxyType({
    'arm64': (f'node-v{VERSION}-linux-arm64.tar.xz',
              'e9e1930fd321a470e29bb68f30318bf58e3ecb4acb4f1533fb19c58328a091fe'),
    'x64': (f'node-v{VERSION}-linux-x64.tar.xz',
            '88fd1ce767091fd8d4a99fdb2356e98c819f93f3b1f8663853a2dee9b438068a'),
})
MACHINES = MappingProxyType({'aarch64': 'arm64', 'arm64': 'arm64', 'x86_64': 'x64', 'amd64': 'x64'})

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
    if entry.startswith('-') or not entry.endswith(ENTRY_SUFFIX) or len(entry) == len(ENTRY_SUFFIX) \
            or entry.rsplit('/', 1)[-1] == ENTRY_SUFFIX or MODULES_DIR in entry.split('/'):
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


def arch_of(machine):
    """This project's name (arm64, x64) for a `platform.machine()` value, or None."""
    return MACHINES.get(str(machine).lower())
