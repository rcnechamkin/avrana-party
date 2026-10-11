"""Install, remove, list and verify EXPERIMENTAL `.avrgame` packages (AVR-39).

    python3 -m avrana.ops.install_game install <file.avrgame> [--grant PERM ...] [--dry-run]
    python3 -m avrana.ops.install_game remove <id> [--keep-state] [--dry-run]
    python3 -m avrana.ops.install_game list [--json]
    python3 -m avrana.ops.install_game verify <id>

NOT an SDK, NOT stable, NOT run on the appliance (docs/runbooks/install-game.md). Installing is an
explicit act by root. A package that validates is still NOT trusted: installing it makes the
appliance run third-party code as an isolated systemd DynamicUser, in the hardened shared template
unit, with its own key and its own Unix socket, nothing more (ADR 0016). This tool never imports,
executes or evaluates anything from a package.

There is ONE way a native game gets onto this appliance: `avrana.ops.provision_game`. This tool
does not fork it. It validates the archive (avrana.avrgame.read), stages its files into a
root-owned tree under the games root, writes the install record
(avrana.avrgame.installed), and then calls provision_game.provision with the repository's contracts
merged with the installed games', exactly as for a first-party game. The pieces that are
effects (`run` for systemctl, `own`, `trusted`, `active`) are arguments, so the core is tested in
scratch directories on any OS; `main` supplies the real ones.

Install is all or nothing. Every step that changes the host is recorded in a ledger as it begins,
and on ANY failure after the first one the ledger is unwound in reverse (provisioning removed, the
record deleted, the staged tree deleted, Party Core reloaded so it forgets) before the original
failure is reported. A crash that gives no chance to unwind (kill -9, power) leaves a partial
state that `remove <id>` clears and that the next `install` of that id refuses to guess about. The
lock file keeps two runs from interleaving.

Upgrade and rollback are not implemented: an installed id is refused ("remove it first"). That is
AVR-58 and AVR-60.
"""
import argparse
import contextlib
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from avrana import avrgame
from avrana.avrgame import installed
from avrana.contracts import game as game_contract
from avrana.ops import provision_game as pg

Refused = pg.Refused
STAGING_PREFIX = '.staging-'
DEFAULT_LOCK = '/run/avrana-install-game.lock'
MAX_PROBLEMS = 20


class RollbackIncomplete(Exception):
    """An install failed and the undo could not finish. `original` is why it failed; `problems`
    are the steps that did not undo. `remove <id>` clears whatever is left."""

    def __init__(self, original, problems):
        self.original, self.problems = original, list(problems)
        super().__init__(f'{original}; and the undo is incomplete ({"; ".join(self.problems)})')


@dataclass(frozen=True)
class Layout:
    """Where things are on this host. No field has a default but `visible_root`."""
    provision: pg.Layout        # keys, registry entries, sockets, state and units (provision_game's)
    records_dir: Path           # /etc/avrana-party/packages.d: one install record per package
    games_root: Path            # /opt/avrana-games: staged trees at <id>/<version>-<sha12>
    lock_file: Path             # /run/avrana-install-game.lock
    visible_root: str = None    # the path the units and records say for games_root, when it is not
                                # the same as where this process sees it (a test's scratch directory)

    def record(self, package_id):
        return Path(self.records_dir) / f'{package_id}.json'

    def id_dir(self, package_id):
        return Path(self.games_root) / package_id

    def root_text(self):
        return (self.visible_root or Path(self.games_root).as_posix()).rstrip('/')

    def tree_text(self, package_id, version, sha256):
        """The staged tree as a record and a unit name it."""
        return f'{self.root_text()}/{package_id}/{installed.tree_name(version, sha256)}'

    def on_disk(self, text):
        """Where the path `text` of a record is, seen from this process."""
        prefix = self.root_text() + '/'
        if not text.startswith(prefix):
            raise Refused(f'{text} is not under the games root {self.root_text()}')
        return Path(self.games_root).joinpath(*PurePosixPath(text[len(prefix):]).parts)


@dataclass
class Plan:
    """Everything decided before anything is written."""
    package: object
    grant: dict
    root: str
    doc: dict
    contracts: dict
    grants: dict
    notes: list = field(default_factory=list)


# ---- the tree on disk ------------------------------------------------------------------------------

def _sha256_of(path):
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    h = hashlib.sha256()
    fd = os.open(path, flags)
    with os.fdopen(fd, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def check_tree(root, files, owner=None, modes=None):
    """Why the tree at `root` is not exactly the package `files` ((path, size, sha256) triples or
    PackageFile), as a list of at most MAX_PROBLEMS sentences; [] when it is. A symbolic link, a
    file that is not listed, a listed file that is missing, changed or of the wrong size, and (when
    `modes`, default on POSIX) anything group- or world-writable are problems. `owner` (a uid)
    additionally requires that owner."""
    want = {}
    for item in files:
        path, size, sha = (item.path, item.size, item.sha256) if hasattr(item, 'path') else item
        want[path] = (size, sha)
    if modes is None:
        modes = os.name == 'posix'
    problems = []

    def add(text):
        if len(problems) < MAX_PROBLEMS:
            problems.append(text)

    def judge(path, st, label):
        if owner is not None and st.st_uid != owner:
            add(f'{label}: not owned by uid {owner}')
        if modes and st.st_mode & 0o022:
            add(f'{label}: writable by a group or others')

    try:
        top = os.lstat(root)
    except OSError:
        return [f'{root}: the staged tree is missing']
    if stat.S_ISLNK(top.st_mode) or not stat.S_ISDIR(top.st_mode):
        return [f'{root}: not a plain directory']
    judge(root, top, 'the tree root')
    seen = set()

    def walk(directory, prefix):
        try:
            entries = sorted(os.scandir(directory), key=lambda e: e.name)
        except OSError:
            add(f'{prefix or "."}: cannot be listed')
            return
        for entry in entries:
            rel = prefix + entry.name
            st = entry.stat(follow_symlinks=False)
            if stat.S_ISLNK(st.st_mode):
                add(f'{rel}: a symbolic link')
            elif stat.S_ISDIR(st.st_mode):
                judge(entry.path, st, rel + '/')
                walk(entry.path, rel + '/')
            elif stat.S_ISREG(st.st_mode):
                seen.add(rel)
                judge(entry.path, st, rel)
                if rel not in want:
                    add(f'{rel}: not part of the package')
                else:
                    size, sha = want[rel]
                    try:
                        if st.st_size != size or _sha256_of(entry.path) != sha:
                            add(f'{rel}: changed since it was installed')
                    except OSError:
                        add(f'{rel}: cannot be read')
            else:
                add(f'{rel}: not a regular file or directory')

    walk(root, '')
    for path in sorted(set(want) - seen):
        add(f'{path}: missing')
    return problems


def _fsync(path, directory=False):
    if os.name != 'posix':
        return                      # Windows cannot flush a read-only handle; the real tool runs on Linux
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _seal(root):
    """Directories 0755, files 0644, nothing writable by group or others; everything on disk."""
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in names:
            path = os.path.join(directory, name)
            os.chmod(path, 0o644)
            _fsync(path)
        os.chmod(directory, 0o755)
        _fsync(directory, directory=True)


def _mkdir(path, mode=0o755):
    """Make one directory with exactly `mode`, whatever the umask."""
    os.mkdir(path, mode)
    os.chmod(path, mode)


def _rmtree(path):
    if os.path.islink(path):
        os.unlink(path)
    elif os.path.lexists(path):
        shutil.rmtree(path)


def _rmdir_if_empty(path):
    try:
        os.rmdir(path)
    except OSError:
        pass


def _write_record(layout, package_id, doc):
    """Put the record in place atomically: written, flushed and closed under a hidden name (the
    reader ignores it), made 0644, then renamed."""
    data = installed.dumps(doc)
    path = layout.record(package_id)
    tmp = path.with_name(f'.{path.name}.{secrets.token_hex(4)}.tmp')
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0)
                     | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
        _fsync(path.parent, directory=True)
    finally:
        if tmp.exists():
            tmp.unlink()


# ---- the lock ---------------------------------------------------------------------------------------

@contextlib.contextmanager
def locked(path):
    """One install, remove or repair at a time. Where `fcntl` does not exist (Windows, where the
    tests run) there is nothing to lock. The lock dies with the process, so a crash never leaves
    it held."""
    try:
        import fcntl
    except ImportError:
        yield
        return
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise Refused('another install-game is running (the lock is held); wait for it') from None
        yield
    finally:
        os.close(fd)


_shield = [0]       # above zero: a signal is swallowed (see interrupts_as_exceptions)


@contextlib.contextmanager
def shielded():
    """No signal interrupts this block: an undo must run to its end whatever arrives."""
    _shield[0] += 1
    try:
        yield
    finally:
        _shield[0] -= 1


@contextlib.contextmanager
def interrupts_as_exceptions():
    """A hang-up (the ssh session drops), a TERM or a Ctrl-C during install or remove becomes a
    KeyboardInterrupt, so `install` unwinds what it began instead of dying half way, and a second
    signal cannot cut the undo short. A run killed outright (KILL, power) leaves a partial state
    that `remove <id>` clears."""
    import signal
    import threading
    names = [n for n in ('SIGINT', 'SIGTERM', 'SIGHUP') if hasattr(signal, n)]
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = {}
    _shield[0] = 0

    def handler(signum, frame):
        if _shield[0]:
            return                  # an undo is running, or the install has completed: not interruptible
        for n in names:
            signal.signal(getattr(signal, n), signal.SIG_IGN)
        raise KeyboardInterrupt(f'signal {signum}')
    try:
        for n in names:
            previous[n] = signal.signal(getattr(signal, n), handler)
        yield
    finally:
        for n, old in previous.items():
            signal.signal(getattr(signal, n), old)
        _shield[0] = 0


# ---- checks that change nothing ---------------------------------------------------------------------

def _empty_plain_dir(path, owner=None):
    """True for an empty plain directory that only the expected owner (a uid; None skips the check)
    can write to; Refused for an empty one that anybody else could write to or that is not theirs."""
    if not os.path.isdir(path) or os.path.islink(path) or os.listdir(path):
        return False
    st = os.lstat(path)
    if (owner is not None and st.st_uid != owner) or (os.name == 'posix' and st.st_mode & 0o022):
        raise Refused(f'{path} is an empty directory that is not root-owned or is writable by a group or others; '
                      'delete it by hand before installing')
    return True


def _plain_dir(path, what):
    if os.path.islink(path) or not os.path.isdir(path):
        raise Refused(f'{what} {path} is not a plain directory (an owner prerequisite: '
                      'docs/runbooks/install-game.md)')


def check_packages_read(config_path, records_dir):
    """Refuse to install when Party Core would never see the game: its config must name the install
    records directory (`packages` in party-core.json). Like check_party_reads, this tool never
    edits Party Core's configuration."""
    try:
        with open(config_path, encoding='utf-8') as f:
            conf = json.load(f)
    except (OSError, ValueError) as e:
        raise Refused(f"Party Core's config {config_path} is unreadable ({type(e).__name__})") from None
    named = conf.get('packages') if isinstance(conf, dict) else None
    if not isinstance(named, str) or Path(named) != Path(records_dir):
        raise Refused(f'the Party Core config {config_path} does not name the install records directory '
                      f'("packages": "{Path(records_dir).as_posix()}"); it would never see this game')


def _leftover_staging(layout, owner=None):
    """The `.staging-*` directories of earlier runs. Any is stale: the lock is held. Only a plain
    directory (owned by `owner` when given) is ours to delete; anything else is a leftover this tool
    will not guess about."""
    found = []
    if not os.path.isdir(layout.games_root):
        return found
    for entry in sorted(os.scandir(layout.games_root), key=lambda e: e.name):
        if not entry.name.startswith(STAGING_PREFIX):
            continue
        st = entry.stat(follow_symlinks=False)
        if not stat.S_ISDIR(st.st_mode) or (owner is not None and st.st_uid != owner):
            raise Refused(f'{entry.path} is not a staging directory this tool made; remove it by hand')
        found.append(Path(entry.path))
    return found


def _check_permissions(contract, allow):
    """(granted, notes): the permissions the contract requests that the operator allowed. Fails
    closed (AVR-336): Party Core does not enforce grants at launch, so a grant is only honest for what
    the sandbox really provides. A permission it cannot provide (anything but `GRANTABLE`) is refused
    as a grant; and a package must request, and be granted, `party_roster`, because every game gets
    the roster in its launch whatever it asked for."""
    for name in allow:
        if name not in game_contract.PERMISSIONS:
            raise Refused(f'--grant {name!r}: not a permission name (one of {", ".join(game_contract.PERMISSIONS)})')
        if name not in installed.GRANTABLE:
            raise Refused(f'--grant {name}: the package sandbox cannot provide it (no IP sockets, no devices); '
                          f'only {", ".join(installed.GRANTABLE)} can be granted, and a grant must not say more than is true')
    requested = list(contract['runtime']['permissions'])
    if installed.ALWAYS_PROVIDED not in requested:
        raise Refused(f'the package does not request {installed.ALWAYS_PROVIDED}, but Party Core hands every game '
                      'the roster (participant, name, role) at launch, requested or not; a package that does not '
                      f'declare it would receive it unannounced. Add "{installed.ALWAYS_PROVIDED}" to runtime.permissions')
    if installed.ALWAYS_PROVIDED not in allow:
        raise Refused(f'the package receives the Party roster at launch and Party Core cannot withhold it; '
                      f'install it only with --grant {installed.ALWAYS_PROVIDED}, so the record says what is true')
    granted = sorted(set(requested) & set(allow))
    notes = [f'ignored --grant {name}: the package never requested it' for name in sorted(set(allow) - set(requested))]
    missing = [name for name in requested if name not in granted]
    if missing:
        notes.append(f'requested but not granted: {", ".join(missing)} (grant with --grant NAME; '
                     'permissions are recorded for the catalog, Party Core does not yet enforce them at launch; '
                     'what the sandbox cannot provide stays unavailable to the package)')
        if 'persistent_storage' in missing:
            notes.append('persistent_storage is NOT withheld by leaving it ungranted: every package unit has a '
                         'state directory (StateDirectory=) whatever was granted')
    return granted, notes


def plan_install(path, layout, repo_contracts, allow=(), trusted=None, interpreters=avrgame.INTERPRETERS,
                 now=None, read=avrgame.read, owner=None):
    """Every refusal, in one place, before anything is written. Returns a Plan."""
    try:
        package = read(path)
    except avrgame.Refused as exc:
        raise Refused('package refused: ' + '; '.join(exc.problems[:8])) from None
    pid = package.id
    if not pg.GAME_ID.fullmatch(pid):
        raise Refused(f'{pid!r} is not a game id')
    if pid in repo_contracts:
        raise Refused(f'{pid}: this appliance has a first-party game of that id; a package cannot shadow it')
    granted, notes = _check_permissions(package.game, allow)
    _plain_dir(layout.games_root, 'the games root')
    if trusted is not None:
        trusted(str(layout.games_root))            # root-owned and not writable by others, all the way up
        records = layout.records_dir               # the records are what Party Core believes: same rule
        trusted(str(records if os.path.isdir(records) else Path(records).parent))
    record, tree = layout.record(pid), layout.id_dir(pid)
    if os.path.lexists(record):
        version = ''
        try:
            version = ' ' + installed.read_record_file(record, pid, repo_contracts, games_root=layout.root_text(),
                                                       owner=owner).version
        except installed.RecordError:
            pass
        raise Refused(f'{pid}{version} is already installed (or its record is damaged); remove it first: '
                      f'install-game remove {pid}. Upgrade and rollback are not implemented yet (AVR-58, AVR-60).')
    if os.path.lexists(tree) and not _empty_plain_dir(tree, owner):      # an empty one is what a crash after mkdir leaves
        raise Refused(f'{tree} exists without a record (an interrupted install?); run install-game remove {pid} first '
                      '(if that reports nothing to remove, it is not a tree this tool made: delete it by hand)')
    left = pg.plan_remove(pid, layout.provision, False, None)
    if left:
        raise Refused(f'{pid} is already provisioned by other means ({", ".join(left)}); '
                      'a package never takes over an existing game')
    interpreter = interpreters[package.manifest['server']['interpreter']]
    if trusted is not None:
        trusted(interpreter)
    root = layout.tree_text(pid, package.version, package.sha256)
    grant = installed.build_grant(package, granted, root, interpreters)
    stamp = (now or (lambda: time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())))()
    doc = installed.build_record(package, grant, root, stamp)
    try:        # what is about to be written must be readable by Party Core, or it is not written
        installed.validate_record(json.loads(installed.dumps(doc)), pid, repo_contracts, interpreters=interpreters,
                                  games_root=layout.root_text())
    except installed.RecordError as exc:
        raise Refused('the install record would not be accepted: ' + '; '.join(exc.problems[:5])) from None
    others = installed.load(layout.records_dir, repo_contracts, interpreters=interpreters,
                            games_root=layout.root_text(), owner=owner)
    return Plan(package=package, grant=grant, root=root, doc=doc, notes=notes,
                contracts={**repo_contracts, **others.contracts, pid: package.game},
                grants={**others.grants, pid: grant})


# ---- install ----------------------------------------------------------------------------------------

class _Ledger:
    """What has begun, so it can be undone in reverse."""

    def __init__(self):
        self.steps = []

    def add(self, label, undo):
        self.steps.append((label, undo))

    def unwind(self):
        problems = []
        for label, undo in reversed(self.steps):
            try:
                undo()
            except Exception as exc:                  # every step is tried; the report names the failures
                problems.append(f'{label} ({type(exc).__name__})')
        self.steps.clear()
        return problems


def _undo_provision(package_id, layout, run):
    def undo():
        error = None
        for _ in range(2):          # a failed Party reload stops the first pass half way; the second finishes
            try:
                pg.remove(package_id, layout.provision, run, keep_state=False, active=None)
                return
            except (subprocess.CalledProcessError, OSError, pg.Refused) as exc:
                error = exc
        if pg.plan_remove(package_id, layout.provision, False, None):
            raise error                                # something of it is still there
        # only systemd's own bookkeeping failed; every file is gone. `remove` repairs the rest.
    return undo


def install(path, layout, repo_contracts, run, own, origin, trusted=None, allow=(), owner=None,
            interpreters=avrgame.INTERPRETERS, now=None, extract=avrgame.extract, read=avrgame.read):
    """Install the package at `path`. Returns the lines to show. On any failure the host is put
    back as it was (see the module docstring) and the original failure is raised;
    RollbackIncomplete when the undo itself could not finish. `owner` is the uid the staged tree
    must belong to (0 in real use); None skips that check (tests as a normal user)."""
    plan = plan_install(path, layout, repo_contracts, allow, trusted, interpreters, now, read, owner)
    package, pid = plan.package, plan.package.id
    final = layout.on_disk(plan.root)
    ledger = _Ledger()
    began = {'provisioning': False}
    try:
        for stale in _leftover_staging(layout, owner):
            shutil.rmtree(stale)                       # an earlier run died here; nothing else uses it
        if not os.path.isdir(layout.records_dir):
            _mkdir(layout.records_dir)
            ledger.add('records directory', lambda: _rmdir_if_empty(layout.records_dir))
        if not os.path.lexists(layout.id_dir(pid)):
            _mkdir(layout.id_dir(pid))
            ledger.add('game directory', lambda: _rmdir_if_empty(layout.id_dir(pid)))
        staging = Path(layout.games_root) / f'{STAGING_PREFIX}{secrets.token_hex(8)}'
        _mkdir(staging, 0o700)
        ledger.add('staging directory', lambda: _rmtree(staging))
        extracted = extract(path, staging)
        if extracted.sha256 != package.sha256 or extracted.files != package.files:
            raise Refused('the archive changed while it was being installed; nothing was installed')
        wrong = check_tree(staging, package.files, owner=owner, modes=False)
        if wrong:
            raise Refused('the staged files do not match the package: ' + '; '.join(wrong[:5]))
        _seal(staging)
        ledger.add('staged tree', lambda: _rmtree(final))
        os.rename(staging, final)
        _fsync(layout.id_dir(pid), directory=True)
        ledger.add('install record', lambda: os.path.lexists(layout.record(pid)) and os.unlink(layout.record(pid)))
        _write_record(layout, pid, plan.doc)
        ledger.add('provisioning', _undo_provision(pid, layout, run))
        began['provisioning'] = True
        changed = pg.provision(pid, layout.provision, plan.contracts, plan.grants, run, own, origin,
                               trusted=trusted)
        _shield[0] += 1                                # installed (the LAST statement here): a late signal must not report an undo that did not happen
    except BaseException as exc:
        _shield[0] += 1                                # FIRST statement: the undo is never cut short, by a signal or a second one
        try:
            problems = ledger.unwind()
            if began['provisioning']:
                try:
                    pg.reload_party(run)               # Party Core forgets the game it may have loaded
                except Exception:
                    problems.append('Party Core reload')
        finally:
            _shield[0] -= 1
        if problems:
            raise RollbackIncomplete(exc, problems) from exc
        raise
    lines = [f'{pid}: installed {package.version} (sha256 {package.sha256[:12]}...) as {installed.TIER}, '
             f'granted: {", ".join(plan.grant["permissions_granted"]) or "nothing"}',
             f'{pid}: staged {plan.root}', f'{pid}: wrote {layout.record(pid)}']
    lines += [f'{pid}: provisioned {item}' for item in changed]
    lines += [f'{pid}: note: {note}' for note in plan.notes]
    return lines


def plan_install_lines(plan, layout, origin):
    """What `install --dry-run` shows."""
    pid, package = plan.package.id, plan.package
    lines = [f'{pid}: would install {package.version} (sha256 {package.sha256[:12]}...) as {installed.TIER}, '
             f'granted: {", ".join(plan.grant["permissions_granted"]) or "nothing"}',
             f'{pid}: would stage {len(package.files)} files ({package.total_bytes} bytes) at {plan.root}',
             f'{pid}: would write {layout.record(pid)}']
    lines += [f'{pid}: would provision {item}'
              for item in pg.plan_provision(pid, layout.provision, plan.contracts, plan.grants, origin)]
    lines += [f'{pid}: note: {note}' for note in plan.notes]
    return lines


# ---- remove -----------------------------------------------------------------------------------------

TREE_NAME = re.compile(r'[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]{1,32})?-[0-9a-f]{12}')


def _tree_is_ours(package_id, layout, owner=None):
    """True when `<games root>/<id>` has the shape only this installer makes: a plain directory
    (owned by `owner` when given) holding nothing but plain directories named <version>-<sha12>. A
    stray directory, a file or a link of that name is nobody's evidence."""
    path = layout.id_dir(package_id)
    try:
        st = os.lstat(path)
        if not stat.S_ISDIR(st.st_mode) or (owner is not None and st.st_uid != owner):
            return False
        names = os.listdir(path)
        if not names:
            return False                # nothing the installer made is in it
        for name in names:
            child = os.lstat(os.path.join(path, name))
            if not TREE_NAME.fullmatch(name) or not stat.S_ISDIR(child.st_mode):
                return False
            if owner is not None and child.st_uid != owner:
                return False
    except OSError:
        return False
    return True


def _record_is_ours(package_id, layout, strict, owner=None):
    """Whether the install record file marks this id as installed by this tool. For `strict` the
    file must be a root-owned regular file that parses as JSON and says it is an install record of
    exactly this id; otherwise any file at the record's name counts (a damaged record is the thing
    `remove` exists to clear)."""
    path = layout.record(package_id)
    if not os.path.lexists(path):
        return False
    if not strict:
        return True
    try:
        st = os.lstat(path)
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode) or st.st_size > installed.MAX_RECORD_BYTES \
                or (owner is not None and st.st_uid != owner):
            return False
        with open(path, 'rb') as f:
            doc = json.loads(f.read(installed.MAX_RECORD_BYTES + 1).decode('utf-8'))
    except (OSError, ValueError):
        return False
    return isinstance(doc, dict) and doc.get('record') == installed.RECORD and doc.get('id') == package_id


def _ours(package_id, layout, repo_contracts=(), owner=None):
    """What marks this id as an installed package (or the leftover of one), and so as this tool's to
    clear: a record, a tree of the shape this installer makes under the games root, or a drop-in
    whose WorkingDirectory is under it. For an id that is a game of this repository the only
    evidence is an install record that says it is one: a stray directory or drop-in must never be
    enough to deprovision a first-party game."""
    first_party = package_id in repo_contracts
    found = []
    if _record_is_ours(package_id, layout, first_party, owner):
        found.append('record')
    if first_party:
        if found and os.path.lexists(layout.id_dir(package_id)):
            found.append('files')           # a package's own tree goes with its record
        return found
    if _tree_is_ours(package_id, layout, owner):
        found.append('files')
    try:
        text = layout.provision.dropin(package_id).read_text(encoding='utf-8')
    except OSError:
        text = ''
    if f'WorkingDirectory={layout.root_text()}/{package_id}/' in text:
        found.append('dropin')
    return found


def _check_removable(package_id, repo_contracts, layout, owner=None):
    if not isinstance(package_id, str) or not pg.GAME_ID.fullmatch(package_id):
        raise Refused(f'{package_id!r} is not a game id')
    if package_id in repo_contracts and not _ours(package_id, layout, repo_contracts, owner):
        # no install record that says so: nothing says this was ever a package
        raise Refused(f'{package_id}: a first-party game of this appliance, not a package; '
                      'use provision-game --remove for those')


def plan_remove(package_id, layout, repo_contracts, keep_state=False, active=None, owner=None):
    _check_removable(package_id, repo_contracts, layout, owner)
    ours = _ours(package_id, layout, repo_contracts, owner)
    left = pg.plan_remove(package_id, layout.provision, keep_state, active)
    if left and not ours:
        raise Refused(f'{package_id} is provisioned but was not installed by install-game; '
                      'use provision-game --remove')
    return [*(item for item in ('record', 'files') if item in ours), *left]


def remove(package_id, layout, repo_contracts, run, active=None, keep_state=False, owner=None):
    """Leave nothing for this id: the game provisioned by provision_game.remove (units, key,
    registry entry, socket, state unless `keep_state`), then the staged files, then the record, then
    one more Party reload. The record goes LAST: it is the evidence that this id is ours, so every
    state an interruption can leave still has it (or, for an id that is not a repository game, a
    tree of the installer's shape) and a second `remove` finishes the job. Works from any partial
    state, with a damaged record or none, and twice. Refused while that game has a session
    (`active`), before anything is touched. Never touches a first-party game (one that has no
    install record naming it) or a game this tool did not install."""
    plan_remove(package_id, layout, repo_contracts, keep_state, None, owner)    # may refuse; changes nothing
    ours = _ours(package_id, layout, repo_contracts, owner)
    removed = pg.remove(package_id, layout.provision, run, keep_state, active)
    if 'files' in ours and os.path.lexists(layout.id_dir(package_id)):
        _rmtree(layout.id_dir(package_id))
        removed.append('files')
    record = layout.record(package_id)
    if os.path.lexists(record):
        os.unlink(record)
        removed.append('record')
    pg.reload_party(run)                              # Party Core no longer reads a record that is gone
    return removed


# ---- list and verify --------------------------------------------------------------------------------

def listing(layout, repo_contracts, owner=None):
    """({id: row}, [problems]) for every readable install record, each row with whether its tree
    still matches (`tree`: ok | modified | missing)."""
    found = installed.load(layout.records_dir, repo_contracts, games_root=layout.root_text(), owner=owner)
    rows = {}
    for pid, rec in sorted(found.records.items()):
        try:
            problems = check_tree(layout.on_disk(rec.root), rec.files, owner=owner)
        except Refused as exc:
            problems = [str(exc)]
        state = 'ok' if not problems else 'missing' if problems[0].endswith('the staged tree is missing') else 'modified'
        rows[pid] = {'id': pid, 'version': rec.version, 'sha256': rec.sha256, 'sha12': rec.sha12,
                     'tier': rec.grant['tier'], 'permissions_granted': list(rec.grant['permissions_granted']),
                     'permissions_requested': list(rec.contract['runtime']['permissions']),
                     'publisher': rec.package['publisher'], 'license': rec.package['license'],
                     'installed_at': rec.doc.get('installed_at'), 'root': rec.root, 'tree': state}
    return rows, found.problems


def verify(package_id, layout, repo_contracts, owner=None):
    """[] when the install record is valid and the staged tree still matches it file for file."""
    if not isinstance(package_id, str) or not pg.GAME_ID.fullmatch(package_id):
        raise Refused(f'{package_id!r} is not a game id')
    path = layout.record(package_id)
    if not os.path.lexists(path):
        raise Refused(f'{package_id}: not installed (no install record)')
    try:
        rec = installed.read_record_file(path, package_id, repo_contracts, games_root=layout.root_text(), owner=owner)
    except installed.RecordError as exc:
        return [f'record refused: {x}' for x in exc.problems]
    return check_tree(layout.on_disk(rec.root), rec.files, owner=owner)


# ---- the command line -------------------------------------------------------------------------------

class _Usage(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _Usage(message)


def _parser():
    ap = _Parser(prog='install-game', description='Install, remove, list or verify an EXPERIMENTAL .avrgame package.')
    sub = ap.add_subparsers(dest='command')
    i = sub.add_parser('install', help='validate, stage and provision a package (root)')
    i.add_argument('package', help='a .avrgame file')
    i.add_argument('--grant', action='append', default=[], metavar='PERM',
                   help='a permission the package requests that this appliance grants it (repeatable); default: none')
    r = sub.add_parser('remove', help='take an installed package off this appliance (root)')
    r.add_argument('id')
    r.add_argument('--keep-state', action='store_true', help='keep the state directory')
    sub.add_parser('list', help='installed packages').add_argument('--json', action='store_true')
    sub.add_parser('verify', help='check a package\'s staged files against its install record').add_argument('id')
    for p in (i, r):
        p.add_argument('--dry-run', action='store_true', help='show what would change; change nothing')
    for p in (i, r):
        p.add_argument('--party-url', default=pg.DEFAULT_PARTY_URL, help=f'Party Core on loopback (default {pg.DEFAULT_PARTY_URL})')
    for p in (i, r, sub.choices['list'], sub.choices['verify']):
        for name in ('key-dir', 'registry-dir', 'socket-dir', 'state-dir', 'unit-dir', 'template-dir',
                     'party-config', 'records-dir', 'games-root', 'lock-file', 'visible-root'):
            p.add_argument(f'--{name}', help=argparse.SUPPRESS)
    return ap


def _default_layout(a):
    tree = Path(__file__).resolve().parent.parent.parent
    d = lambda value, default: Path(value or default)
    provision = pg.Layout(key_dir=d(a.key_dir, '/etc/avrana-party/game-keys'),
                          registry_dir=d(a.registry_dir, '/etc/avrana-party/games.d'),
                          socket_dir=d(a.socket_dir, '/run/avrana-games'),
                          state_dir=d(a.state_dir, '/var/lib/avrana-games'),
                          unit_dir=d(a.unit_dir, '/etc/systemd/system'),
                          template_dir=d(a.template_dir, tree / 'deploy' / 'games'))
    return Layout(provision=provision, records_dir=d(a.records_dir, installed.DEFAULT_RECORDS_DIR),
                  games_root=d(a.games_root, installed.DEFAULT_GAMES_ROOT),
                  lock_file=d(a.lock_file, DEFAULT_LOCK), visible_root=a.visible_root)


def _show_listing(rows, problems, as_json, out):
    if as_json:
        json.dump({'installed': list(rows.values()), 'refused': problems}, out, indent=2, sort_keys=True)
        out.write('\n')
        return
    for row in rows.values():
        granted = ', '.join(row['permissions_granted']) or 'nothing'
        print(f'{row["id"]} {row["version"]}  sha256 {row["sha12"]}  tier {row["tier"]}  granted: {granted}', file=out)
        print(f'    publisher: {row["publisher"]} (unverified claim)   license: {row["license"]} (unverified claim)', file=out)
        print(f'    files: {row["tree"]}  {row["root"]}', file=out)
    for problem in problems:
        print(f'REFUSED {problem}', file=out)
    if not rows and not problems:
        print('no packages installed', file=out)


def main(argv=None, *, run=None, own=None, is_root=None, opener=None, contracts=None, out=None, err=None):
    """Exit 0 done, 1 refused or failed (the reason on stderr, never a key), 2 usage. Every effect
    can be injected: `run`, `own`, `is_root`, `opener` (Party Core's status), `contracts` (the
    repository's Game Contracts) and the output streams."""
    out, err = out or sys.stdout, err or sys.stderr
    try:
        a = _parser().parse_args(sys.argv[1:] if argv is None else argv)
        if a.command is None:
            raise _Usage('a command is required: install, remove, list or verify')
    except _Usage as e:
        print(f'install-game: {e}', file=err)
        return 2
    except SystemExit as e:                                  # --help
        return int(e.code or 0)
    try:
        if is_root is None:
            is_root = hasattr(os, 'geteuid') and os.geteuid() == 0
        writes = a.command in ('install', 'remove')
        dry = writes and a.dry_run
        if writes and not is_root and not dry:
            raise Refused('must run as root (use sudo)')
        layout = _default_layout(a)
        real = own is None
        own = own or pg.real_own
        run = run or pg._real_run
        if contracts is None:
            from avrana.contracts import party_config
            contracts = party_config.load_contracts()
        owner = 0 if real else None
        conf = a.party_config if getattr(a, 'party_config', None) else pg.PARTY_CONFIG
        if a.command == 'list':
            rows, problems = listing(layout, contracts, owner=owner)
            _show_listing(rows, problems, a.json, out)
            return 0
        if a.command == 'verify':
            wrong = verify(a.id, layout, contracts, owner=owner)
            for item in wrong:
                print(f'{a.id}: {item}', file=err)
            if wrong:
                return 1
            print(f'{a.id}: every staged file matches its install record', file=out)
            return 0
        if a.command == 'remove':
            active = pg.party_session_check(a.party_url, opener or pg._direct_open,
                                            settle=pg.STATUS_SETTLE_S if opener is None and not a.dry_run else 0.0,
                                            host=pg.party_host(conf) if opener is None else None)
            if a.dry_run:
                changes = plan_remove(a.id, layout, contracts, a.keep_state, active, owner)
                for item in changes:
                    print(f'{a.id}: would remove {item}', file=out)
                if not changes:
                    print(f'{a.id}: nothing to remove', file=out)
                return 0
            with interrupts_as_exceptions(), locked(layout.lock_file):
                changes = remove(a.id, layout, contracts, run, active, a.keep_state, owner)
            for item in changes:
                print(f'{a.id}: removed {item}', file=out)
            if not changes:
                print(f'{a.id}: nothing to remove', file=out)
            return 0
        # install
        if real and not dry:
            pg._phase_1()                                    # before anything is written
        if real or dry:
            pg.check_party_reads(conf, layout.provision.registry_dir)
            check_packages_read(conf, layout.records_dir)
        origin = pg.party_origin(conf)
        trusted = pg.trusted_path if real else None
        if dry:
            plan = plan_install(a.package, layout, contracts, a.grant, trusted, owner=owner)
            for line in plan_install_lines(plan, layout, origin):
                print(line, file=out)
            return 0
        with interrupts_as_exceptions(), locked(layout.lock_file):
            lines = install(a.package, layout, contracts, run, own, origin, trusted, a.grant, owner)
        for line in lines:
            print(line, file=out)
        return 0
    except KeyboardInterrupt:
        if a.command == 'remove':
            print(f'install-game: interrupted; the removal of {a.id} may be half done. Run '
                  f'"install-game remove {a.id}" again: it finishes the job from any state', file=err)
        else:
            print('install-game: interrupted; the install was undone as far as it had gone '
                  '(nothing is installed), and "install-game remove <id>" clears anything left', file=err)
        return 1
    except RollbackIncomplete as e:
        print(f'install-game: failed: {_describe(e.original)}', file=err)
        print('install-game: the undo is incomplete: ' + '; '.join(e.problems), file=err)
        print('install-game: run "install-game remove <id>" to clear what is left', file=err)
        return 1
    except Refused as e:
        print(f'install-game: refused: {e}', file=err)
        return 1
    except subprocess.CalledProcessError as e:
        print(f'install-game: failed: {" ".join(map(str, e.cmd))} exited {e.returncode}; nothing is left installed', file=err)
        return 1
    except (OSError, ValueError) as e:
        print(f'install-game: failed: {type(e).__name__}: {e}', file=err)
        return 1


def _describe(exc):
    if isinstance(exc, subprocess.CalledProcessError):
        return f'{" ".join(map(str, exc.cmd))} exited {exc.returncode}'
    return f'{type(exc).__name__}: {exc}'


if __name__ == '__main__':
    sys.exit(main())
