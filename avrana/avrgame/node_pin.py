"""The ONE Node.js build an appliance may run for EXPERIMENTAL .avrgame packages (AVR-68): its
version, where it lives, and the SHA-256 of the official tarball for each architecture.

EXPERIMENTAL: values may change. Data only: nothing here runs, imports or requires Node, so Party
Core and a Python package are the same with or without the runtime. The runtime is optional. It is
installed by `avrana.ops.node_runtime` from a tarball the operator supplies (never downloaded on the
appliance) whose SHA-256 must equal the pin below, into a root-owned directory named after the
version. A package only says `"interpreter": "node"`; the path is the appliance's
(`avrana.avrgame.manifest.INTERPRETERS`, which a unit test holds equal to EXECUTABLE).

Moving the pin: change VERSION and both digests here (from nodejs.org/dist/v<VERSION>/SHASUMS256.txt),
the `node` path of INTERPRETERS, and the revision of the developer tools export, which states the
interpreters (tools/build_avrgame_tools.py). A package installed under the old version keeps naming
the old directory until it is installed again.
"""
from types import MappingProxyType

VERSION = '22.22.2'
RUNTIMES_ROOT = '/opt/avrana-runtimes'
ROOT = f'{RUNTIMES_ROOT}/node-{VERSION}'
EXECUTABLE = f'{ROOT}/bin/node'

# The official builds, by this project's arch name.
ARCHIVES = MappingProxyType({
    'arm64': (f'node-v{VERSION}-linux-arm64.tar.xz',
              'e9e1930fd321a470e29bb68f30318bf58e3ecb4acb4f1533fb19c58328a091fe'),
    'x64': (f'node-v{VERSION}-linux-x64.tar.xz',
            '88fd1ce767091fd8d4a99fdb2356e98c819f93f3b1f8663853a2dee9b438068a'),
})
MACHINES = MappingProxyType({'aarch64': 'arm64', 'arm64': 'arm64', 'x86_64': 'x64', 'amd64': 'x64'})


def arch_of(machine):
    """This project's name (arm64, x64) for a `platform.machine()` value, or None."""
    return MACHINES.get(str(machine).lower())
