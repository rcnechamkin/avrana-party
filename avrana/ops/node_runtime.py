"""Install, verify or remove the OPTIONAL pinned Node.js runtime of EXPERIMENTAL .avrgame packages (AVR-68).

    python3 -m avrana.ops.node_runtime install <node-v<version>-linux-<arch>.tar.xz> [--dry-run]
    python3 -m avrana.ops.node_runtime verify
    python3 -m avrana.ops.node_runtime remove [--dry-run]

NOT an SDK, NOT stable, NOT run on the appliance (docs/runbooks/install-game.md). The appliance
does not need Node: Party Core never imports, runs or looks for it, and Python packages are the
same with or without it. Only a package whose manifest says `"interpreter": "node"` does, and
`install-game` refuses such a package while the runtime is missing.

What `install` does, as root, OFFLINE: it never opens a network connection. The operator brings
the official tarball of exactly the pinned version (avrana.avrgame.node: VERSION and one SHA-256
per architecture, from nodejs.org's SHASUMS256.txt). The file is read once, bounded; its SHA-256
must equal the pin for THIS machine's architecture, whatever the file is called. Then exactly two
members are taken out of it, `bin/node` and `LICENSE`: no npm, npx or corepack, no headers, no
symbolic link. They are written under a staging name, root-owned, `bin/node` 0755 and the rest
0644, the binary is asked for its version (it must answer the pinned one), and the directory is
renamed to

    /opt/avrana-runtimes/node-<version>/{bin/node, LICENSE, avrana-runtime.json}

The record file says which archive it came from and the SHA-256 of the binary; `verify` checks the
tree against it (owner root, nothing group- or world-writable, no link, nothing extra, the binary
unchanged, the archive digest still the pin). A second `install` of a tree that verifies changes
nothing. `remove` is refused while an install record names the runtime.

Every path and effect is an argument of the core (`install`, `verify`, `remove`), so it is tested
in scratch directories on any OS; `main` supplies the real ones.
"""
import argparse
import hashlib
import json
import lzma
import os
import platform
import secrets
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

from avrana.avrgame import installed, node

RECORD = 'avrana.runtime/experimental.1'
RECORD_NAME = 'avrana-runtime.json'
STAGING_PREFIX = '.staging-'
MAX_ARCHIVE_BYTES = 96 * 1024 * 1024       # the official builds are about 30 MB
MAX_NODE_BYTES = 384 * 1024 * 1024         # bin/node is about 120 MB
MAX_LICENSE_BYTES = 4 * 1024 * 1024
MEMBERS = (('bin/node', 0o755, MAX_NODE_BYTES), ('LICENSE', 0o644, MAX_LICENSE_BYTES))
CHUNK = 1024 * 1024


class Refused(Exception):
    """The runtime tool will not do this. The message says why."""


def _sha256_file(path, limit=None):
    h = hashlib.sha256()
    n = 0
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    with os.fdopen(os.open(path, flags), 'rb') as f:
        for chunk in iter(lambda: f.read(CHUNK), b''):
            n += len(chunk)
            if limit is not None and n > limit:
                raise Refused(f'{path}: larger than {limit} bytes; not an official Node build')
            h.update(chunk)
    return h.hexdigest()


def machine_arch(machine=None):
    arch = node.arch_of(platform.machine() if machine is None else machine)
    if arch is None or arch not in node.ARCHIVES:
        raise Refused(f'this machine ({platform.machine() if machine is None else machine}) has no pinned Node build; '
                      f'pinned: {", ".join(sorted(node.ARCHIVES))}')
    return arch


def check_archive(path, arch, archives=node.ARCHIVES):
    """The SHA-256 of the tarball at `path`, which must be the pinned build for `arch`. The name of
    the file is not evidence of anything; the digest is."""
    try:
        st = os.lstat(path)
    except OSError:
        raise Refused(f'{path}: does not exist or cannot be read') from None
    if not stat.S_ISREG(st.st_mode):
        raise Refused(f'{path}: not a regular file')
    digest = _sha256_file(path, MAX_ARCHIVE_BYTES)
    name, want = archives[arch]
    if digest == want:
        return digest
    for other, (other_name, other_digest) in sorted(archives.items()):
        if digest == other_digest:
            raise Refused(f'{path}: this is {other_name} (the {other} build); this machine is {arch} and needs {name}')
    raise Refused(f'{path}: its SHA-256 is {digest}, not the one pinned for {name} ({want}); only the official '
                  f'Node {node.VERSION} build is accepted. Nothing was installed')


def _extract(path, arch, staging, archives=node.ARCHIVES):
    """Write the two wanted members of the verified tarball under `staging`; returns the SHA-256 of bin/node."""
    prefix = archives[arch][0][:-len('.tar.xz')]
    wanted = {f'{prefix}/{rel}': (rel, mode, limit) for rel, mode, limit in MEMBERS}
    digests = {}
    try:
        with tarfile.open(path, 'r:xz') as tar:
            for member in tar:
                if member.name not in wanted:
                    continue
                rel, mode, limit = wanted[member.name]
                if not member.isreg() or member.size > limit or rel in digests:
                    raise Refused(f'{path}: {member.name} is not a plain file of the expected size')
                target = Path(staging) / rel
                target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                source = tar.extractfile(member)
                h = hashlib.sha256()
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
                with os.fdopen(os.open(target, flags, 0o600), 'wb') as out:
                    for chunk in iter(lambda: source.read(CHUNK), b''):
                        h.update(chunk)
                        out.write(chunk)
                    out.flush()
                    os.fsync(out.fileno())
                os.chmod(target, mode)
                digests[rel] = h.hexdigest()
                if len(digests) == len(wanted):
                    break
    except (tarfile.TarError, lzma.LZMAError, EOFError, OSError, ValueError) as exc:
        raise Refused(f'{path}: cannot be unpacked ({type(exc).__name__})') from None
    missing = sorted(rel for rel, _, _ in MEMBERS if rel not in digests)
    if missing:
        raise Refused(f'{path}: has no {", ".join(missing)}')
    return digests['bin/node']


def real_version(executable):
    """What the binary says it is, run with an empty environment (`v22.22.2`)."""
    done = subprocess.run([str(executable), '--version'], capture_output=True, text=True, timeout=30, env={},
                          check=False)
    return done.stdout.strip()


def record_doc(arch, archive_sha256, node_sha256, archives=node.ARCHIVES):
    return {'record': RECORD, 'runtime': node.NAME, 'version': node.VERSION, 'arch': arch,
            'archive': archives[arch][0], 'archive_sha256': archive_sha256, 'node_sha256': node_sha256}


def _dumps(doc):
    return (json.dumps(doc, indent=2, sort_keys=True) + '\n').encode('utf-8')


def problems(root, arch, owner=None, modes=None, archives=node.ARCHIVES):
    """Why the tree at `root` is not the runtime this tool installs for `arch`, as sentences; []
    when it is. `owner` (a uid) additionally requires that owner; `modes` (default on POSIX) that
    nothing is group- or world-writable and that bin/node can be executed."""
    root = Path(root)
    if modes is None:
        modes = os.name == 'posix'
    try:
        top = os.lstat(root)
    except OSError:
        return [f'{root}: the Node runtime is not installed']
    if stat.S_ISLNK(top.st_mode) or not stat.S_ISDIR(top.st_mode):
        return [f'{root}: not a plain directory']
    found = []
    want = {'bin': 'dir', 'bin/node': 'file', 'LICENSE': 'file', RECORD_NAME: 'file'}
    seen = {}
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in dirs + names:
            path = Path(directory) / name
            seen[path.relative_to(root).as_posix()] = path
    for rel in sorted(set(seen) - set(want)):
        found.append(f'{rel}: not part of the runtime')
    for rel in sorted(set(want) - set(seen)):
        found.append(f'{rel}: missing')
    for rel, path in sorted({'.': root, **seen}.items()):
        st = os.lstat(path)
        kind = 'dir' if stat.S_ISDIR(st.st_mode) else 'file' if stat.S_ISREG(st.st_mode) else 'other'
        if rel != '.' and rel in want and kind != want[rel]:
            found.append(f'{rel}: not a plain {"directory" if want[rel] == "dir" else "file"}')
        if owner is not None and st.st_uid != owner:
            found.append(f'{rel}: not owned by uid {owner}')
        if modes and kind != 'other' and st.st_mode & 0o022:
            found.append(f'{rel}: writable by a group or others')
    if found:
        return found
    try:
        doc = json.loads((root / RECORD_NAME).read_bytes().decode('utf-8'))
    except (OSError, ValueError):
        return [f'{RECORD_NAME}: cannot be read']
    if not isinstance(doc, dict):
        return [f'{RECORD_NAME}: not an object']
    node_sha = doc.get('node_sha256')
    if doc != record_doc(arch, archives[arch][1], node_sha, archives):
        found.append(f'{RECORD_NAME}: does not describe the pinned Node {node.VERSION} build for {arch}')
    elif _sha256_file(root / 'bin' / 'node') != node_sha:
        found.append('bin/node: changed since it was installed')
    if modes and not os.lstat(root / 'bin' / 'node').st_mode & 0o111:
        found.append('bin/node: not executable')
    return found


def _fsync_dir(path):
    if os.name != 'posix':
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def install(archive_path, runtimes_root, arch, trusted=None, owner=None, version_of=real_version,
            archives=node.ARCHIVES, dry_run=False):
    """Install the pinned runtime from the tarball at `archive_path` into <runtimes_root>/node-<version>.
    Returns the lines to show. Refused, changing nothing, for a tarball that is not the pinned
    build of `arch`; an existing tree that verifies is left alone, one that does not is refused
    (remove it first: it is never repaired in place). `trusted(path)` raises unless a path is
    root-owned all the way up; `owner` is the uid the tree must belong to (0 in real use)."""
    runtimes_root = Path(runtimes_root)
    final = runtimes_root / f'node-{node.VERSION}'
    if os.path.lexists(final):
        wrong = problems(final, arch, owner, archives=archives)
        if wrong:
            raise Refused(f'{final} exists and is not the runtime this tool installs ({"; ".join(wrong[:3])}); '
                          'run "install-node-runtime remove" first')
        return [f'node {node.VERSION} ({arch}): already installed at {final}; nothing changed']
    digest = check_archive(archive_path, arch, archives)
    parent = runtimes_root if os.path.isdir(runtimes_root) else runtimes_root.parent
    if os.path.islink(runtimes_root) or (os.path.lexists(runtimes_root) and not os.path.isdir(runtimes_root)):
        raise Refused(f'{runtimes_root} is not a plain directory')
    if trusted is not None:
        trusted(str(parent))
    if dry_run:
        return [f'node {node.VERSION} ({arch}): would install {archives[arch][0]} (sha256 {digest[:12]}...) at {final}']
    made_root = not os.path.isdir(runtimes_root)
    if made_root:
        os.mkdir(runtimes_root, 0o755)
        os.chmod(runtimes_root, 0o755)
    staging = runtimes_root / f'{STAGING_PREFIX}{secrets.token_hex(8)}'
    try:
        os.mkdir(staging, 0o700)
        node_sha = _extract(archive_path, arch, staging, archives)
        said = version_of(staging / 'bin' / 'node')
        if said != f'v{node.VERSION}':
            raise Refused(f'the unpacked binary says it is {said!r}, not v{node.VERSION}; nothing was installed')
        record = staging / RECORD_NAME
        record.write_bytes(_dumps(record_doc(arch, digest, node_sha, archives)))
        os.chmod(record, 0o644)
        os.chmod(staging / 'bin', 0o755)
        os.chmod(staging, 0o755)
        _fsync_dir(staging / 'bin')
        _fsync_dir(staging)
        wrong = problems(staging, arch, owner, archives=archives)
        if wrong:
            raise Refused('the unpacked runtime does not verify: ' + '; '.join(wrong[:3]))
        os.rename(staging, final)
        _fsync_dir(runtimes_root)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        if made_root:
            try:
                os.rmdir(runtimes_root)
            except OSError:
                pass
        raise
    return [f'node {node.VERSION} ({arch}): installed from {archives[arch][0]} (sha256 {digest[:12]}...)',
            f'node {node.VERSION} ({arch}): {final / "bin" / "node"} (sha256 {node_sha[:12]}...)']


def users(records_dir, executable):
    """The ids of the install records whose command runs `executable`. A record is read as plain
    JSON here: a damaged one that names the runtime still counts."""
    found = []
    if not records_dir or not os.path.isdir(records_dir):
        return found
    for name in sorted(os.listdir(records_dir)):
        if name.startswith('.') or not name.endswith('.json'):
            continue
        try:
            with open(os.path.join(records_dir, name), 'rb') as f:
                doc = json.loads(f.read(installed.MAX_RECORD_BYTES + 1).decode('utf-8'))
            command = doc['grant']['runtime']['command']
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if isinstance(command, list) and command and command[0] == executable:
            found.append(name[:-5])
    return found


def remove(runtimes_root, records_dir, executable=node.EXECUTABLE, dry_run=False):
    """Take the runtime off this host. Refused while an installed package runs on it."""
    runtimes_root = Path(runtimes_root)
    final = runtimes_root / f'node-{node.VERSION}'
    using = users(records_dir, executable)
    if using:
        raise Refused(f'installed packages run on this runtime ({", ".join(using)}); remove them first '
                      '(install-game remove <id>)')
    if not os.path.lexists(final):
        return [f'node {node.VERSION}: nothing to remove']
    if dry_run:
        return [f'node {node.VERSION}: would remove {final}']
    if os.path.islink(final):
        os.unlink(final)
    else:
        shutil.rmtree(final)
    for entry in sorted(os.listdir(runtimes_root)):
        if entry.startswith(STAGING_PREFIX):                 # what a killed install left
            shutil.rmtree(runtimes_root / entry, ignore_errors=True)
    try:
        os.rmdir(runtimes_root)                              # only when nothing else is in it
    except OSError:
        pass
    return [f'node {node.VERSION}: removed {final}']


# ---- the command line -------------------------------------------------------------------------------

def _parser():
    ap = argparse.ArgumentParser(prog='install-node-runtime',
                                 description='Install, verify or remove the optional pinned Node.js runtime (EXPERIMENTAL).')
    sub = ap.add_subparsers(dest='command', required=True)
    i = sub.add_parser('install', help='install from an official tarball you supply; offline (root)')
    i.add_argument('archive', help=f'node-v{node.VERSION}-linux-<arch>.tar.xz')
    sub.add_parser('verify', help='check the installed runtime against its record and the pin')
    r = sub.add_parser('remove', help='remove the runtime; refused while a package runs on it (root)')
    for p in (i, r):
        p.add_argument('--dry-run', action='store_true', help='show what would change; change nothing')
    for p in (i, r, sub.choices['verify']):
        for name in ('runtimes-root', 'records-dir', 'machine'):
            p.add_argument(f'--{name}', help=argparse.SUPPRESS)
    return ap


def main(argv=None, *, is_root=None, trusted=None, version_of=real_version, out=None, err=None):
    """Exit 0 done, 1 refused or failed (the reason on stderr), 2 usage."""
    out, err = out or sys.stdout, err or sys.stderr
    try:
        a = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as e:
        return int(e.code or 0)
    try:
        if is_root is None:
            is_root = hasattr(os, 'geteuid') and os.geteuid() == 0
        real = a.runtimes_root is None
        runtimes_root = a.runtimes_root or node.RUNTIMES_ROOT
        records_dir = a.records_dir or installed.DEFAULT_RECORDS_DIR
        arch = machine_arch(a.machine)
        owner = 0 if real else None
        if a.command == 'verify':
            wrong = problems(Path(runtimes_root) / f'node-{node.VERSION}', arch, owner)
            for item in wrong:
                print(f'node {node.VERSION}: {item}', file=err)
            if wrong:
                return 1
            print(f'node {node.VERSION} ({arch}): installed and unchanged ({runtimes_root}/node-{node.VERSION}/bin/node)', file=out)
            return 0
        if not is_root and not a.dry_run:
            raise Refused('must run as root (use sudo)')
        if a.command == 'remove':
            lines = remove(runtimes_root, records_dir, dry_run=a.dry_run)
        else:
            if trusted is None and real:
                from avrana.ops import provision_game
                trusted = provision_game.trusted_path
                provision_refused = provision_game.Refused
            else:
                provision_refused = ()
            try:
                lines = install(a.archive, runtimes_root, arch, trusted, owner, version_of, dry_run=a.dry_run)
            except provision_refused as e:
                raise Refused(str(e)) from None
        for line in lines:
            print(line, file=out)
        return 0
    except Refused as e:
        print(f'install-node-runtime: refused: {e}', file=err)
        return 1
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        print(f'install-node-runtime: failed: {type(e).__name__}: {e}', file=err)
        return 1


if __name__ == '__main__':
    sys.exit(main())
