"""Bring a clean target to the appliance's expected state, and say how far it is from it (AVR-32).

    python3 -m avrana.ops.rebuild check                    # the inventory against this repository
    python3 -m avrana.ops.rebuild plan                     # read-only: what is in place, what is not
    sudo python3 -m avrana.ops.rebuild apply --target-hostname NAME   # the first apply on a target
    sudo python3 -m avrana.ops.rebuild apply [--activate]  # install what can be installed now
    sudo python3 -m avrana.ops.rebuild restore BACKUP      # undo the file changes of one apply
    sudo python3 -m avrana.ops.rebuild verify              # state, smoke, topology, boundary
    sudo python3 -m avrana.ops.rebuild seal                # the build is over: refuse apply/restore from now on
    python3 -m avrana.ops.rebuild ap-profile | packages | unknowns

deploy/appliance-inventory.json is the list: packages, service users, directories, configuration
files with owner and mode, the things that are in no repository (artifacts) and the secrets. This
module compares a host with it and closes the gap for the part a script can own.

What it never does. It never creates, reads, prints, copies or removes a secret: keys, the
certificate and the Wi-Fi passphrase are handoffs (`plan` prints who provisions each and with
which command), and the paths in SECRET_TREES and SECRET_FILES below are refused by the code that
writes, removes and hashes files, whatever an inventory says. It never deploys code
(ops/deploy.sh does) and never replaces an edited /etc/avrana-party/party-core.json. It runs no
command an inventory invents: only the package, user and group commands written here and the
reload commands in ACTIVATIONS.

What it does to the network, exactly. It writes one dnsmasq drop-in under
/etc/NetworkManager/dnsmasq-shared.d/. It does NOT install the network-manager package, does not
enable or start NetworkManager and never runs nmcli: on an image whose network is run by
something else, NetworkManager arriving can take over eth0 in the middle of an SSH session
(unknown U1). Those are owner steps at a console, and `plan` lists them as handoffs.

Every item waits for what it needs (a release, a key, the certificate), so `apply` is run again
after each handoff and converges; a second run with nothing new changes nothing. `apply
--activate` then runs the reload commands of everything that is in place, every time, and starts
the units. A step that fails stops the run: only what really changed is reported. Files it
replaces are kept under /var/backups/avrana-party/rebuild-<UTC>/.

Which hosts `apply`, `restore` and `seal` will change (`plan` and `verify` only read, anywhere):

  clean      no sign of an installed appliance (the inventory's `guard`: an Avrana unit enabled
             or active, or an install path of today's layout) and no marker. The first `apply`
             must name the machine (`--target-hostname`, compared with its hostname), prints
             what it is about to change, and writes the marker before anything else.
  open       a valid marker written by that first apply: `apply` and `restore` go on.
  sealed     `seal` was run when the build was accepted: refused, like any live appliance.
  appliance  signs and no valid marker, e.g. today's Pi: refused before a single package, user,
             file or command, exit 2. Moving it is docs/runbooks/service-users-migration.md.

A marker counts only on the machine whose hostname it records. `--owner-confirms-not-the-live-appliance`
(with `--target-hostname`) gets past a refusal only when NO appliance service is running,
starting or set to start, and systemd answers the question: a half-built target whose marker was
lost, or where ops/deploy.sh ran before the first apply. Otherwise it is refused too, and even
then a key store that holds keys and belongs to another user is never re-owned (a handoff).
NEVER RUN ON THE APPLIANCE as of this commit, and most of the real-host code has never executed
anywhere: docs/runbooks/rebuild.md lists it.

`--root DIR` works on a SIMULATED host: file contents are real files under DIR; owners, modes,
links, users, packages, units and the commands that would have run are kept in a ledger file
there. That is what the tests use and it is a rehearsal of the procedure, not evidence about a Pi.
On a real host (`--root` absent) this needs Linux, and root for `apply`, `restore`, `seal` and a
complete `verify`. docs/runbooks/rebuild.md is the procedure and says which steps are the owner's.

Exit status: 0; 1 when `check`, `apply` or `verify` found a failure; 2 for a usage error or a
refused host.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import socket
import stat
import subprocess
import sys

from avrana import REPO_ROOT

SCHEMA = 'avrana.appliance-inventory/v0'
INVENTORY = REPO_ROOT / 'deploy' / 'appliance-inventory.json'
BACKUP_ROOT = '/var/backups/avrana-party'
GAMES_RELEASE = '/opt/avrana-party-games/current'
AREAS = ('party', 'games', 'arcade', 'nginx', 'ap', 'dns', 'tls', 'health', 'base')
REQUIRED_AREAS = ('party', 'games', 'nginx', 'ap', 'dns', 'health')     # the issue's checklist
SECTIONS = ('packages', 'groups', 'users', 'memberships', 'directories', 'files', 'links', 'absent',
            'artifacts', 'secrets', 'units', 'not_managed', 'hardware_checks', 'unknowns')
OK, CHANGE, BLOCKED, HANDOFF, KEPT = 'ok', 'change', 'blocked', 'handoff', 'kept'
PASS, FAIL, SKIP, WARN = 'pass', 'fail', 'skip', 'warn'
MARKER_SCHEMA = 'avrana.rebuild-marker/v0'
# The only commands an inventory entry may ask `apply --activate` to run, as exact argv. Root runs
# them: the list is code, so a changed inventory cannot add one.
ACTIVATIONS = (
    ['systemctl', 'daemon-reload'],
    ['systemctl', 'restart', 'systemd-journald'],
    ['modprobe', 'uinput'],
    ['udevadm', 'control', '--reload-rules'],
    ['udevadm', 'trigger', '--subsystem-match=misc'],
    ['nginx', '-t'],
    ['systemctl', 'reload', 'nginx'],
)
# What only the owner runs after a change, by name; never executed here.
OWNER_STEPS = {
    'bounce-access-point': 'only if the access point profile is already up (it is not before the owner created it): '
                           'sudo nmcli connection down "{profile}" && sudo nmcli connection up "{profile}" '
                           'ifname {interface}   # drops every phone for a few seconds; never over the party Wi-Fi',
}
# Where secrets live. Nothing below these is ever written, linked, removed, hashed or copied by
# this module; the directory itself may be created with its owner and mode. An inventory that
# names a secret outside them, or manages a path inside them, does not validate.
SECRET_TREES = ('/etc/avrana-party/game-keys', '/etc/avrana-party/tls', '/var/lib/avrana-party/lego',
                '/etc/NetworkManager/system-connections')
SECRET_FILES = ('/etc/avrana-party/cloudflare.env',)


def is_secret(path, exact_tree_ok=False):
    """Is `path` a secret file or inside a secret tree? The tree's own directory counts unless
    `exact_tree_ok` (creating it with its owner and mode is the one thing allowed)."""
    path = str(PurePosixPath(path))
    if path in SECRET_FILES:
        return True
    return any(path.startswith(tree + '/') or (path == tree and not exact_tree_ok) for tree in SECRET_TREES)


# Unit states that mean "this service is, or is about to be, running" and "systemd will start it".
RUNNING_STATES = ('active', 'activating', 'reloading', 'deactivating')
ENABLED_STATES = ('enabled', 'enabled-runtime', 'linked', 'linked-runtime', 'static', 'alias', 'indirect', 'generated')
UNANSWERED = 'not answering (systemctl gave no usable answer)'


def systemctl_show(name, runner=subprocess.run):
    """`systemctl show` for one unit, or None when systemd cannot be asked. Reads only."""
    try:
        out = runner(['systemctl', 'show', '--property=LoadState,ActiveState,UnitFileState', name],
                     capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.decode('utf-8', 'replace') if out.returncode == 0 else None


def unit_sign(shown):
    """From `systemctl show` output: None when the unit is neither running nor set to start,
    else what it is. No answer is a sign too: a guard that cannot see must refuse."""
    props = dict(line.split('=', 1) for line in (shown or '').splitlines() if '=' in line)
    if 'LoadState' not in props or 'ActiveState' not in props:
        return UNANSWERED
    active, file_state = props['ActiveState'], props.get('UnitFileState', '')
    if active in RUNNING_STATES:
        return active
    if file_state in ENABLED_STATES:
        return 'failed but ' + file_state if active == 'failed' else file_state
    return None


SMOKE_AREAS = {'captive_probe': 'nginx', 'party_home': 'party', 'party_core': 'party', 'status': 'health',
               'games_provider': 'games', 'arcade': 'arcade', 'encoder': 'arcade', 'unit': 'health',
               'certificate': 'tls', 'dns': 'dns'}


class RebuildError(Exception):
    pass


# ---- the inventory ----------------------------------------------------------------------------
def load_inventory(path=None):
    return json.loads(Path(path or INVENTORY).read_text(encoding='utf-8'))


def _absolute(path):
    return isinstance(path, str) and path.startswith('/') and '..' not in PurePosixPath(path).parts


def _mode_ok(mode):
    return isinstance(mode, str) and len(mode) == 4 and mode[0] == '0' and all(c in '01234567' for c in mode)


def validate(inv, party_root=REPO_ROOT):
    """Every way the inventory disagrees with itself or with this repository, as sentences."""
    errors = []
    if inv.get('schema') != SCHEMA:
        return [f'schema is not {SCHEMA}']
    for section in SECTIONS:
        if not isinstance(inv.get(section), list) or not inv[section]:
            errors.append(f'{section}: missing or empty')
    if errors:
        return errors
    users = {u['name'] for u in inv['users']}
    packages = {p['name'] for p in inv['packages']}
    artifacts = {a['id'] for a in inv['artifacts']}
    secrets = {s['id']: s for s in inv['secrets']}
    managed = {e['path'] for e in inv['directories'] + inv['files'] + inv['links']}
    for section in ('packages', 'groups', 'users', 'memberships', 'directories', 'absent', 'artifacts', 'secrets'):
        for entry in inv[section]:
            evidence = entry.get('evidence')
            if not evidence or not (party_root / evidence).is_file():
                errors.append(f'{section} {entry.get("name") or entry.get("path") or entry.get("id") or entry.get("user")}: '
                              f'evidence {evidence!r} is not a file in this repository')
    for key, fact in inv.get('target', {}).items():
        if not (party_root / fact.get('evidence', '')).is_file():
            errors.append(f'target {key}: evidence is not a file in this repository')
    for entry in inv['packages']:
        if entry.get('confidence') not in ('scripted', 'derived'):
            errors.append(f'package {entry["name"]}: confidence must be scripted or derived')
    for section in ('files', 'links', 'absent'):
        for entry in inv[section]:
            if is_secret(entry.get('path', '')):
                errors.append(f'{section} {entry.get("path")}: is a secret path or inside a secret tree; never managed')
            for argv in entry.get('activate', []):
                if argv not in ACTIVATIONS:
                    errors.append(f'{section} {entry.get("path")}: activation {argv!r} is not one of the commands this tool runs')
            for step in entry.get('owner_activate', []):
                if step not in OWNER_STEPS:
                    errors.append(f'{section} {entry.get("path")}: unknown owner step {step!r}')
    for entry in inv['directories']:
        if is_secret(entry.get('path', ''), exact_tree_ok=True):
            errors.append(f'directories {entry.get("path")}: is inside a secret tree; never managed')
    for entry in inv['artifacts']:
        if is_secret(entry.get('path', '')):
            errors.append(f'artifact {entry.get("id")}: its path is a secret path')
    for section in ('directories', 'files'):
        for entry in inv[section]:
            if not _absolute(entry.get('path')) or not _mode_ok(entry.get('mode')) \
                    or not entry.get('owner') or not entry.get('group'):
                errors.append(f'{section} {entry.get("path")}: needs an absolute path, owner, group and a 4-digit mode')
            if entry.get('owner') not in users | {'root'}:
                errors.append(f'{section} {entry.get("path")}: owner {entry.get("owner")} is not root or an inventory user')
    for entry in inv['files']:
        repo, _, rel = entry.get('source', '').partition(':')
        if repo not in ('party', 'games') or not rel or rel.startswith('/') or '..' in rel.split('/'):
            errors.append(f'file {entry.get("path")}: source must be party:<path> or games:<path>')
        elif repo == 'party' and not (party_root / rel).is_file():
            errors.append(f'file {entry["path"]}: source {rel} is not in this repository')
        if entry.get('policy', 'replace') not in ('replace', 'create-only'):
            errors.append(f'file {entry.get("path")}: unknown policy')
    for entry in inv['links'] + inv['absent'] + inv['artifacts']:
        if not _absolute(entry.get('path')):
            errors.append(f'{entry.get("path")}: not an absolute path')
    for secret in inv['secrets']:
        if not secret.get('provision'):
            errors.append(f'secret {secret.get("id")}: no provisioning path')
        for p in secret.get('paths', []):
            if not _absolute(p.get('path')) or not _mode_ok(p.get('mode')) or p['path'] in managed:
                errors.append(f'secret {secret["id"]}: {p.get("path")} needs a path and a mode, and is never an installed file')
            elif int(p['mode'], 8) & 0o022:
                errors.append(f'secret {secret["id"]}: {p["path"]} would be writable by group or other')
            elif not is_secret(p['path']):
                errors.append(f'secret {secret["id"]}: {p["path"]} is outside SECRET_TREES/SECRET_FILES, '
                              'so the code would not protect it')
    for artifact in inv['artifacts']:
        if not artifact.get('provision') or artifact.get('kind') not in ('owner', 'script'):
            errors.append(f'artifact {artifact.get("id")}: needs a provisioning path and a kind')
    seen = set()
    for section in ('directories', 'files', 'links', 'absent'):
        for entry in inv[section]:
            if entry['path'] in seen:
                errors.append(f'{entry["path"]}: listed twice')
            seen.add(entry['path'])
    for section in ('memberships', 'directories', 'files', 'links', 'secrets', 'units'):
        for entry in inv[section]:
            for req in entry.get('requires', []):
                kind, _, name = req.partition(':')
                known = {'user': name in users, 'package': name in packages, 'artifact': name in artifacts,
                         'secret': bool(secrets.get(name, {}).get('paths')), 'path': _absolute(name)}
                if not known.get(kind):
                    errors.append(f'{entry.get("path") or entry.get("name") or entry.get("id") or entry.get("user")}: '
                                  f'requirement {req} names nothing in the inventory')
    for section in ('directories', 'files', 'links', 'absent', 'artifacts', 'secrets', 'units', 'hardware_checks'):
        for entry in inv[section]:
            if entry.get('area') not in AREAS:
                errors.append(f'{section} {entry.get("path") or entry.get("name") or entry.get("id")}: unknown area')
    for area in REQUIRED_AREAS:
        if not any(h['area'] == area for h in inv['hardware_checks']):
            errors.append(f'hardware_checks: nothing for {area}')
    guard = inv.get('guard') or {}
    signs = guard.get('appliance_paths') or []
    if not _absolute(guard.get('marker')) or not guard.get('appliance_units') or not signs:
        errors.append('guard: needs a marker path, appliance_units and appliance_paths')
    else:
        marker = guard['marker']
        if any(marker == s or marker.startswith(s + '/') for s in signs) or marker in managed \
                or any(marker.startswith(d['path'] + '/') for d in inv['directories']):
            errors.append('guard: the marker must live outside every path that marks an installed appliance')
        for entry in inv['files']:
            if entry['path'].startswith('/etc/systemd/system/') and entry['path'].endswith('.service') \
                    and not entry.get('optional') and entry['path'] not in signs:
                errors.append(f'guard: {entry["path"]} is not an appliance sign')
        for unit in inv['units']:
            if any(r.startswith('path:/etc/systemd/system/') for r in unit.get('requires', [])) \
                    and unit['name'] not in guard['appliance_units']:
                errors.append(f'guard: unit {unit["name"]} is not an appliance sign')
    ids = [u.get('id') for u in inv['unknowns']]
    if len(set(ids)) != len(ids) or not all(u.get('question') and u.get('confirm') for u in inv['unknowns']):
        errors.append('unknowns: each needs a unique id, a question and how to confirm it on the device')
    return errors


def ap_profile_command(inv):
    """The nmcli command that creates the access point profile the scripts name. It carries no
    passphrase: NetworkManager asks for it when the profile is first brought up."""
    ap = inv['network']['access_point']
    return ['nmcli', 'connection', 'add', 'type', 'wifi', 'ifname', ap['interface'], 'con-name', ap['profile'],
            'ssid', ap['ssid'], '802-11-wireless.mode', ap['mode'], '802-11-wireless.band', ap['band'],
            '802-11-wireless.channel', str(ap['channel']), 'wifi-sec.key-mgmt', ap['key_mgmt'],
            'ipv4.method', ap['ipv4_method'], 'ipv4.addresses', ap['address'], 'ipv6.method', ap['ipv6_method'],
            'connection.autoconnect', 'yes' if ap['autoconnect'] else 'no']


def _quote(argv):
    return ' '.join(f'"{a}"' if ' ' in a else a for a in argv)


# ---- the host ---------------------------------------------------------------------------------
class Host:
    """A real host, or a simulated one under `root` (contents real, everything else in a ledger)."""
    LEDGER = '.avrana-rebuild-simulation.json'

    def __init__(self, root=None, readonly=False, runner=subprocess.run, unit_query=None):
        self.unit_query = unit_query    # name -> `systemctl show` text or None; replaces the real question
        self.simulated = root is not None
        self.root = Path(root) if self.simulated else Path('/')
        self.readonly = readonly
        self.runner = runner
        self.commands = []          # every command this object ran, or would have run when simulated
        self.secret_paths = set()   # contents of these are never read
        if self.simulated:
            self.ledger = {'meta': {}, 'links': {}, 'users': {}, 'groups': [], 'packages': [], 'units': {},
                           'commands': []}
            if (self.root / self.LEDGER).is_file():
                self.ledger.update(json.loads((self.root / self.LEDGER).read_text(encoding='utf-8')))
        elif platform.system() != 'Linux':
            raise RebuildError('a real host needs Linux; on this machine pass --root DIR for a simulated one')

    # -- reading
    def path(self, path):
        return self.root / path.lstrip('/') if self.simulated else Path(path)

    def kind(self, path):
        """'file', 'dir', 'link' or None. Never opens the file."""
        if self.simulated and path in self.ledger['links']:
            return 'link'
        real = self.path(path)
        try:
            if not self.simulated and real.is_symlink():
                return 'link'
            if real.is_dir():
                return 'dir'
            return 'file' if real.is_file() else None
        except OSError:
            return None                               # unreadable to this user: reported as absent

    def exists(self, path):
        """Follows links: is something there for whoever opens this path?"""
        if not self.simulated:
            try:
                return self.path(path).exists()
            except OSError:
                return False
        return self.kind(path) is not None

    def link_target(self, path):
        if self.simulated:
            return self.ledger['links'].get(path)
        try:
            return os.readlink(path)
        except OSError:
            return None

    def meta(self, path):
        """(owner, group, mode as '0644'), following links."""
        if self.simulated:
            entry = self.ledger['meta'].get(path)
            return tuple(entry) if entry else None
        import grp
        import pwd
        try:
            st = os.stat(path)
        except OSError:
            return None

        def name(lookup, number):
            try:
                return lookup(number)[0]
            except KeyError:
                return str(number)
        return name(pwd.getpwuid, st.st_uid), name(grp.getgrgid, st.st_gid), f'{stat.S_IMODE(st.st_mode):04o}'

    def _never_a_secret(self, path, exact_tree_ok=False):
        """Every path this object writes, links, removes, hashes or backs up passes here first.
        A path that is not absolute or has a `..` part is refused outright, so nothing can reach a
        secret by a detour; then the secret trees and files themselves."""
        if not isinstance(path, str) or not path.startswith('/') or '..' in PurePosixPath(path).parts:
            raise RebuildError(f'{path!r} is not an absolute path without "..": refused')
        if path in self.secret_paths or is_secret(path, exact_tree_ok):
            raise RebuildError(f'{path} is a secret or inside a secret tree; never read, written or removed here')

    def entries(self, path):
        """The names in a directory (never their contents), or None when it cannot be listed."""
        try:
            return sorted(os.listdir(self.path(path)))
        except OSError:
            return None

    def populated_secret_tree(self, path, owner):
        """Is `path` a secret tree that holds something and belongs to somebody else? Then its
        owner and mode are the owner's decision: the services that read those keys run as that
        user. An unlistable directory counts as populated."""
        if path not in SECRET_TREES or self.kind(path) != 'dir':
            return None
        names, meta = self.entries(path), self.meta(path)
        if names == [] or (meta and meta[0] == owner):
            return None
        return f'{path} belongs to {meta[0] if meta else "an unknown owner"} and holds ' \
               f'{len(names) if names is not None else "an unknown number of"} entries'

    def hostname(self):
        return self.ledger.get('hostname', 'simulated-host') if self.simulated else socket.gethostname()

    def identity(self):
        """What machine this is, for the person about to change it and for the marker."""
        release = 'unknown'
        try:
            found = re.search(r'^PRETTY_NAME="?([^"\n]*)', self.path('/etc/os-release').read_text(encoding='utf-8'), re.M)
            release = found.group(1) if found else release
        except OSError:
            pass
        return {'hostname': self.hostname(), 'os': release,
                'arch': 'simulated' if self.simulated else platform.machine()}

    def sha256(self, path):
        self._never_a_secret(path)
        try:
            return hashlib.sha256(self.path(path).read_bytes()).hexdigest()
        except OSError:
            return None                               # unreadable to this user: never equal to a source

    def _query(self, argv):
        try:
            out = self.runner(argv, capture_output=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return out.stdout.decode('utf-8', 'replace').strip()

    def has_package(self, name):
        if self.simulated:
            return name in self.ledger['packages']
        return 'install ok installed' in (self._query(['dpkg-query', '-W', '-f=${Status}', name]) or '')

    def has_group(self, name):
        if self.simulated:
            return name in self.ledger['groups']
        import grp
        try:
            grp.getgrnam(name)
            return True
        except KeyError:
            return False

    def user_groups(self, name):
        """The supplementary groups of a user, or None when the user does not exist."""
        if self.simulated:
            return self.ledger['users'].get(name)
        import grp
        import pwd
        try:
            pwd.getpwnam(name)
        except KeyError:
            return None
        return sorted(g.gr_name for g in grp.getgrall() if name in g.gr_mem)

    def unit(self, name):
        """(enabled, active)."""
        if self.simulated:
            state = self.ledger['units'].get(name, {})
            return bool(state.get('enabled')), bool(state.get('active'))
        return (self._query(['systemctl', 'is-enabled', name]) in ('enabled', 'static', 'enabled-runtime'),
                self._query(['systemctl', 'is-active', name]) == 'active')

    def unit_sign(self, name):
        """None, or how this unit is running or set to start (see unit_sign). What the guard
        and the override ask; an unanswerable systemd is a sign."""
        if self.unit_query is not None:
            return unit_sign(self.unit_query(name))
        if self.simulated:
            state = self.ledger['units'].get(name, {})
            if 'show' in state:                        # raw `systemctl show` text, or None, for tests
                return unit_sign(state['show'])
            return 'active' if state.get('active') else ('enabled' if state.get('enabled') else None)
        return unit_sign(systemctl_show(name, self.runner))

    # -- changing
    def _guard(self):
        if self.readonly:
            raise RebuildError('a read-only run tried to change the host')

    def _save(self):
        if self.simulated:
            self.root.mkdir(parents=True, exist_ok=True)
            (self.root / self.LEDGER).write_text(json.dumps(self.ledger, indent=1, sort_keys=True), encoding='utf-8')

    def _own(self, path, owner, group, mode):
        if self.simulated:
            self.ledger['meta'][path] = [owner, group, mode]
            self._save()
        else:
            import shutil
            shutil.chown(path, owner, group)
            os.chmod(path, int(mode, 8))

    def _parents(self, real):
        """Create the missing directories above `real`, 0755 whatever root's umask is."""
        missing = [d for d in reversed(real.parents) if not d.exists()]
        for directory in missing:
            directory.mkdir()
            if not self.simulated:
                os.chmod(directory, 0o755)

    def mkdir(self, path, owner, group, mode):
        self._guard()
        self._never_a_secret(path, exact_tree_ok=True)
        theirs = self.populated_secret_tree(path, owner)
        if theirs:
            raise RebuildError(f'{theirs}: its owner and mode are not changed here')
        real = self.path(path)
        self._parents(real)
        if real.exists() and not real.is_dir():
            raise RebuildError(f'{path} exists and is not a directory')
        real.mkdir(exist_ok=True)
        self._own(path, owner, group, mode)

    def install(self, data, path, owner, group, mode):
        """Write atomically: the file appears complete, with its owner and mode, or not at all."""
        self._guard()
        self._never_a_secret(path)
        real = self.path(path)
        if real.is_dir() and not real.is_symlink():
            raise RebuildError(f'{path} is a directory; a file was to be installed there')
        self._parents(real)
        tmp = real.with_name(f'.{real.name}.avrana-new')
        try:
            tmp.write_bytes(data)
            if not self.simulated:
                import shutil
                os.chmod(tmp, int(mode, 8))
                shutil.chown(tmp, owner, group)
            os.replace(tmp, real)
        finally:
            if tmp.is_file() or tmp.is_symlink():
                tmp.unlink()
        if self.simulated:
            self.ledger['links'].pop(path, None)
            self._own(path, owner, group, mode)

    def symlink(self, target, path):
        self._guard()
        self._never_a_secret(path)
        if self.simulated:
            self.ledger['links'][path] = target
            self._save()
            return
        real = self.path(path)
        self._parents(real)
        tmp = real.with_name(f'.{real.name}.avrana-new')
        if tmp.is_symlink():
            tmp.unlink()
        os.symlink(target, tmp)
        os.replace(tmp, real)

    def remove(self, path):
        self._guard()
        self._never_a_secret(path)
        if self.simulated:
            self.ledger['links'].pop(path, None)
            self.ledger['meta'].pop(path, None)
            self._save()
        real = self.path(path)
        if real.is_symlink() or real.is_file():
            real.unlink()

    def run(self, argv):
        """Run a command that changes the host; True when it succeeded. A simulated host records
        it and applies the effect the next reading depends on."""
        self._guard()
        self.commands.append(list(argv))
        if not self.simulated:
            return self.runner(argv).returncode == 0
        self.ledger['commands'].append(list(argv))
        led = self.ledger
        if argv[:2] == ['apt-get', 'install']:
            led['packages'] = sorted(set(led['packages']) | {a for a in argv[2:] if not a.startswith('-')})
        elif argv[0] == 'groupadd':
            led['groups'] = sorted(set(led['groups']) | {argv[-1]})
        elif argv[0] == 'useradd':
            led['users'].setdefault(argv[-1], [])
            led['groups'] = sorted(set(led['groups']) | {argv[-1]})
        elif argv[0] == 'usermod':
            groups = argv[argv.index('-G') + 1].split(',')
            led['users'][argv[-1]] = sorted(set(led['users'].get(argv[-1], [])) | set(groups))
        elif argv[:3] == ['systemctl', 'enable', '--now']:
            led['units'][argv[3]] = {'enabled': True, 'active': True}
        self._save()
        return True


# ---- the plan ---------------------------------------------------------------------------------
def _step(kind, name, status, detail='', entry=None):
    entry = entry or {}
    return {'kind': kind, 'name': name, 'status': status, 'detail': detail, 'area': entry.get('area', 'base'),
            'optional': bool(entry.get('optional')), 'entry': entry}


def _running_unit(host, path):
    """The active unit a unit file or drop-in at `path` belongs to, or None. Replacing the file of
    a running service changes who it runs as at its next restart: never done silently."""
    prefix = '/etc/systemd/system/'
    if not path.startswith(prefix):
        return None
    name = path[len(prefix):].split('/')[0]
    name = name[:-2] if name.endswith('.d') else name
    name = name[:-len('.service')] if name.endswith('.service') else name
    return name if host.unit_sign(name) in RUNNING_STATES + (UNANSWERED,) else None


def plan(inv, host, party_root=REPO_ROOT, games_source=GAMES_RELEASE):
    """Every inventory item against the host, in the order `apply` acts. Reads only: ownership,
    modes, the content of installed (never secret) files, the package/user databases and systemd."""
    artifacts = {a['id']: a for a in inv['artifacts']}
    secrets = {s['id']: s for s in inv['secrets']}
    host.secret_paths = {p['path'] for s in inv['secrets'] for p in s.get('paths', [])}
    coming = set()                                     # what earlier steps of this plan will create

    def met(req):
        kind, _, name = req.partition(':')
        if req in coming:
            return True
        if kind == 'package':
            return host.has_package(name)
        if kind == 'user':
            return host.user_groups(name) is not None
        if kind == 'artifact':
            return host.exists(artifacts[name]['path'])
        if kind == 'secret':
            return all(host.exists(p['path']) for p in secrets[name]['paths'])
        return host.exists(name)

    def waiting(entry):
        missing = [r for r in entry.get('requires', []) if not met(r)]
        return 'needs ' + ', '.join(missing) if missing else ''

    steps = []
    for p in inv['packages']:
        present = host.has_package(p['name'])
        if p.get('manual') and not present:            # the owner installs it; nothing waits on a promise
            steps.append(_step('package', p['name'], HANDOFF, p['manual']))
            continue
        coming.add(f'package:{p["name"]}')
        steps.append(_step('package', p['name'], OK if present else CHANGE, '' if present else f'install ({p["confidence"]})'))
    for g in inv['groups']:
        steps.append(_step('group', g['name'], OK if host.has_group(g['name']) else CHANGE))
    for u in inv['users']:
        groups = host.user_groups(u['name'])
        coming.add(f'user:{u["name"]}')
        lacking = sorted(set(u['groups']) - set(groups or []))
        steps.append(_step('user', u['name'], CHANGE if groups is None or lacking else OK,
                           'create' if groups is None else ('add to ' + ','.join(lacking) if lacking else ''), u))
    for m in inv['memberships']:
        groups = host.user_groups(m['user'])
        lacking = sorted(set(m['groups']) - set(groups or []))
        wait = waiting(m)
        steps.append(_step('membership', m['user'], OK if not lacking else (BLOCKED if wait else CHANGE),
                           wait or ('add to ' + ','.join(lacking) if lacking else ''), m))
    for d in inv['directories']:
        want = (d['owner'], d['group'], d['mode'])
        wait = waiting(d)
        theirs = host.populated_secret_tree(d['path'], d['owner'])
        if host.kind(d['path']) == 'dir' and host.meta(d['path']) == want:
            status, detail = OK, ''
        elif theirs:
            status, detail = HANDOFF, (f'owner decides: {theirs}. This tool does not re-own a populated key store: '
                                       'whoever runs the services that read it would lose it')
        elif wait:
            status, detail = BLOCKED, wait
        else:
            status, detail = CHANGE, ('create' if host.kind(d['path']) != 'dir' else 'set') + ' ' + ' '.join(want)
            coming.add(f'path:{d["path"]}')
        steps.append(_step('directory', d['path'], status, detail, d))
    for f in inv['files']:
        repo, _, rel = f['source'].partition(':')
        source = (party_root / rel) if repo == 'party' else host.path(games_source + '/' + rel)
        want = (f['owner'], f['group'], f['mode'])
        wait = waiting(f)
        there = host.exists(f['path']) and host.kind(f['path']) != 'dir'
        if wait:
            status, detail = BLOCKED, wait
        elif not source.is_file():
            status, detail = BLOCKED, f'source {f["source"]} is not there'
        else:
            same = there and host.sha256(f['path']) == hashlib.sha256(source.read_bytes()).hexdigest()
            if there and not same and f.get('policy') == 'create-only':
                status, detail = KEPT, 'differs from the example; an existing file is never replaced'
            elif there and not same and _running_unit(host, f['path']):
                status, detail = BLOCKED, (f'{_running_unit(host, f["path"])} is running from a different file: that is a '
                                           'migration (docs/runbooks/service-users-migration.md), not a rebuild')
            elif same and host.meta(f['path']) == want:
                status, detail = OK, ''
            else:
                status = CHANGE
                detail = ('install' if not there else 'replace' if not same else 'set') + ' ' + ' '.join(want)
                coming.add(f'path:{f["path"]}')
        steps.append(_step('file', f['path'], status, detail, dict(f, _source=str(source))))
    for link in inv['links']:
        wait = waiting(link)
        if host.kind(link['path']) == 'link' and host.link_target(link['path']) == link['target']:
            status, detail = OK, ''
        elif wait:
            status, detail = BLOCKED, wait
        else:
            status, detail = CHANGE, '-> ' + link['target']
            coming.add(f'path:{link["path"]}')
        steps.append(_step('link', link['path'], status, detail, link))
    for gone in inv['absent']:
        steps.append(_step('absent', gone['path'], OK if host.kind(gone['path']) is None else CHANGE,
                           '' if host.kind(gone['path']) is None else 'remove: ' + gone['why'], gone))
    for a in inv['artifacts']:
        steps.append(_step('artifact', a['id'], OK if host.exists(a['path']) else HANDOFF,
                           '' if host.exists(a['path']) else a['provision'], a))
    for s in inv['secrets']:
        if not s['paths']:
            status, detail = HANDOFF, s['provision']
        elif all(host.exists(p['path']) for p in s['paths']):
            wrong = [p['path'] for p in s['paths'] if host.meta(p['path']) != (p['owner'], p['group'], p['mode'])]
            status, detail = (HANDOFF, 'owner or mode is not as listed: ' + ', '.join(wrong)) if wrong else (OK, '')
        else:
            status, detail = HANDOFF, s['provision']
        steps.append(_step('secret', s['id'], status, detail, s))
    for u in inv['units']:
        enabled, active = host.unit(u['name'])
        wait = waiting(u)
        if enabled and active:
            status, detail = OK, ''
        elif u.get('manual'):
            status, detail = HANDOFF, u['manual']
        elif wait:
            status, detail = BLOCKED, wait
        else:
            status, detail = CHANGE, 'systemctl enable --now (apply --activate, or by hand)'
        steps.append(_step('unit', u['name'], status, detail, u))
    return steps


# ---- which hosts may be changed -------------------------------------------------------------
def _stamp(now=None):
    return (now or datetime.now(timezone.utc)).strftime('%Y%m%dT%H%M%SZ')


def appliance_signs(inv, host):
    """What on this host says an appliance is already installed here: Avrana units that are
    enabled or active, and install paths of the deployed layout. Reads only."""
    guard = inv['guard']
    signs = [f'unit {name} is {state}' for name, state in appliance_units(inv, host)]
    signs += [f'{path} exists' for path in guard['appliance_paths'] if host.exists(path)]
    return signs


def appliance_units(inv, host):
    """[(unit, state)] for the Avrana units that are running, starting, set to start, or about
    which systemd gives no answer."""
    return [(name, sign) for name in inv['guard']['appliance_units'] for sign in [host.unit_sign(name)] if sign]


def read_marker(inv, host, any_machine=False):
    """The marker of a first apply on THIS machine, or None. A directory, a link, unparsable JSON,
    a document without the expected fields, or a marker written on a machine of another name
    (a card moved, a file copied) is no marker: the guard then judges the host by its signs."""
    path = inv['guard']['marker']
    if host.kind(path) != 'file':
        return None
    try:
        doc = json.loads(host.path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or doc.get('schema') != MARKER_SCHEMA:
        return None
    if not all(isinstance(doc.get(key), str) and doc[key] for key in ('created', 'hostname')):
        return None
    if doc.get('sealed') is not None and not isinstance(doc['sealed'], str):
        return None
    if doc['hostname'] != host.hostname() and not any_machine:
        return None
    return doc


def guard_state(inv, host):
    """'open', 'sealed', 'appliance' or 'clean' (see the module docstring)."""
    marker = read_marker(inv, host)
    if marker:
        return 'sealed' if marker.get('sealed') else 'open'
    return 'appliance' if appliance_signs(inv, host) else 'clean'


def describe_guard(inv, host):
    state = guard_state(inv, host)
    marker = read_marker(inv, host) or {}
    return {
        'open': f'guard: open (marker of {marker.get("created")} for host {marker.get("hostname")}): apply and restore '
                'are allowed; run `seal` when the build is accepted',
        'sealed': f'guard: SEALED on {marker.get("sealed")}: this is a finished appliance; apply and restore are refused',
        'appliance': 'guard: an appliance is installed here and there is no valid rebuild marker: apply and restore are '
                     'refused (docs/runbooks/service-users-migration.md)',
        'clean': 'guard: clean target, no marker: the first apply needs --target-hostname ' + host.hostname(),
    }[state] + _foreign_marker_note(inv, host)


def _foreign_marker_note(inv, host):
    if read_marker(inv, host):
        return ''
    foreign = read_marker(inv, host, any_machine=True)
    return (f'. NOTE: the marker there was written for another machine ({foreign["hostname"]!r}; this one is '
            f'{host.hostname()!r}) and is ignored') if foreign else ''


def _party_sha(party_root):
    """The commit of the tree this runs from, for the marker; None when it cannot be told."""
    root = Path(party_root).resolve()
    if root.parent.name == 'releases':                 # /opt/avrana-party/releases/<sha>
        return root.name
    try:
        out = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    sha = out.stdout.decode('ascii', 'replace').strip()
    return sha if len(sha) == 40 and out.returncode == 0 else None


def _write_marker(inv, host, record):
    marker = inv['guard']['marker']
    host.mkdir(str(PurePosixPath(marker).parent), 'root', 'root', '0755')
    host.install((json.dumps(record, indent=1) + '\n').encode('utf-8'), marker, 'root', 'root', '0644')


def authorize(inv, host, command, party_root=REPO_ROOT, owner_override=False, now=None, target_hostname=None,
              log=print):
    """May `apply` or `restore` change this host? Raises RebuildError, having changed nothing,
    unless the host is open, or clean (apply only: the marker is written here, before anything
    else), or the owner overrides on a host where no appliance service is enabled or running."""
    marker_path = inv['guard']['marker']
    state = guard_state(inv, host)
    name = host.hostname()
    if target_hostname is not None and target_hostname != name:
        raise RebuildError(f'{command} refused, nothing was changed: --target-hostname says {target_hostname!r} '
                           f'but this machine is {name!r}')
    if state == 'open':
        return
    if state in ('sealed', 'appliance'):
        what = ('this appliance was sealed: its build is over' if state == 'sealed' else
                'this host already looks like an installed appliance and has no valid rebuild marker at ' + marker_path)
        signs = appliance_signs(inv, host)
        seen = f' ({"; ".join(signs[:4])}{" ..." if len(signs) > 4 else ""})' if signs else ''
        if not owner_override:
            raise RebuildError(
                f'{command} refused, nothing was changed: {what}{seen}. This tool builds a clean target only. '
                'Moving a running appliance to this layout is docs/runbooks/service-users-migration.md; '
                'docs/runbooks/rebuild.md says when the owner may override.')
        running = appliance_units(inv, host)
        if running:
            raise RebuildError(
                f'{command} refused, nothing was changed, override included: {what}, and '
                + ', '.join(f'{unit} is {how}' for unit, how in running)
                + '. The override is only for a half-built target on which no appliance service is enabled or '
                'running (a lost marker, or ops/deploy.sh run before the first apply). A host with services is '
                'a live appliance: docs/runbooks/service-users-migration.md.')
    if owner_override and state in ('sealed', 'appliance') and target_hostname is None:
        raise RebuildError(f'{command} refused, nothing was changed: the override must name the machine too. This '
                           f'machine is {name!r}: --target-hostname {name}')
    if command != 'apply':
        if state == 'clean':
            raise RebuildError(f'{command} refused, nothing was changed: no rebuild marker at {marker_path}, so this '
                               'host was not built by this tool (docs/runbooks/rebuild.md, "Rollback and recovery")')
        return
    if target_hostname is None:
        raise RebuildError(f'apply refused, nothing was changed: the first apply on a target must name it. This '
                           f'machine is {name!r}; if that is the card you mean to build: --target-hostname {name}')
    identity = host.identity()
    log(f'about to build an appliance on: hostname {identity["hostname"]}, {identity["os"]}, {identity["arch"]}')
    old = read_marker(inv, host) or {}
    record = {'schema': MARKER_SCHEMA, 'created': _stamp(now), 'party_sha': _party_sha(party_root),
              'hostname': identity['hostname'], 'os': identity['os'], 'arch': identity['arch'],
              'owner_override': bool(owner_override), 'signs_at_creation': appliance_signs(inv, host)}
    if old:                                            # an overridden seal is kept as history
        record['unsealed'] = (old.get('unsealed') or []) + [{'sealed': old.get('sealed'), 'created': old.get('created')}]
    _write_marker(inv, host, record)


def seal(inv, host, now=None):
    """The build is accepted: from now on this host is an appliance, and `apply` and `restore`
    refuse it like any other. Needs the marker of the build; sealing twice changes nothing."""
    marker = read_marker(inv, host)
    if marker is None:
        raise RebuildError(f'seal refused: no valid rebuild marker at {inv["guard"]["marker"]}; this tool did not build this host')
    if not marker.get('sealed'):
        marker['sealed'] = _stamp(now)
        _write_marker(inv, host, marker)
    return marker


# ---- apply and restore -------------------------------------------------------------------------
def _record(host, journal, backup, path):
    """Keep what is at `path` before it changes. A secret path is refused by the host itself."""
    host._never_a_secret(path)
    kind = host.kind(path)
    entry = {'path': path, 'kind': kind}
    if kind == 'link':
        entry['target'] = host.link_target(path)
    elif kind == 'file':
        entry['meta'] = list(host.meta(path) or ('root', 'root', '0644'))
        entry['copy'] = f'files/{len(journal):03d}'
        host.install(host.path(path).read_bytes(), f'{backup}/{entry["copy"]}', 'root', 'root', '0600')
    journal.append(entry)
    host.install(json.dumps(journal, indent=1).encode('utf-8'), f'{backup}/journal.json', 'root', 'root', '0600')


def activation_set(steps):
    """The reload commands of everything that is in place, in the order they must run:
    daemon-reload first, then inventory order (so `nginx -t` precedes the nginx reload)."""
    commands = []
    for s in steps:
        if s['kind'] in ('file', 'link', 'absent') and s['status'] == OK:
            for argv in s['entry'].get('activate', []):
                if argv in ACTIVATIONS and argv not in commands:
                    commands.append(argv)
    commands.sort(key=lambda argv: argv != ['systemctl', 'daemon-reload'])
    return commands


def apply(inv, host, party_root=REPO_ROOT, games_source=GAMES_RELEASE, activate=False, now=None, log=print,
          owner_override=False, target_hostname=None):
    """Do every step of the plan whose needs are met, stopping at the first that fails. Returns
    {changed, pending, backup, failed}: `changed` holds only what really changed. Refuses, before
    any change, a host `authorize` does not let through."""
    authorize(inv, host, 'apply', party_root, owner_override, now, target_hostname, log)
    todo = [s for s in plan(inv, host, party_root, games_source) if s['status'] == CHANGE]
    backup, journal, changed, failed, ran = None, [], [], [], []
    profile = inv['network']['access_point']

    def run(argv):
        ok = host.run(argv)
        (ran if ok else failed).append(argv if ok else _quote(argv))
        return ok

    def keep(path):
        nonlocal backup
        if backup is None:
            backup, n = f'{BACKUP_ROOT}/rebuild-{_stamp(now)}', 1
            while host.exists(backup):                 # a second apply in the same second
                n += 1
                backup = f'{BACKUP_ROOT}/rebuild-{_stamp(now)}-{n}'
            host.mkdir(backup, 'root', 'root', '0700')
        _record(host, journal, backup, path)

    def do(step):
        entry, kind, name = step['entry'], step['kind'], step['name']
        if kind == 'group':
            return run(['groupadd', '--system', name])
        if kind == 'user':
            if host.user_groups(name) is None and not run(
                    ['useradd', '--system', '--user-group', '--no-create-home', '--home-dir', '/nonexistent',
                     '--shell', '/usr/sbin/nologin', name]):
                return False
            return not entry['groups'] or run(['usermod', '-a', '-G', ','.join(entry['groups']), name])
        if kind == 'membership':
            return run(['usermod', '-a', '-G', ','.join(entry['groups']), name])
        if kind == 'directory':
            host.mkdir(name, entry['owner'], entry['group'], entry['mode'])
        elif kind == 'file':
            keep(name)
            host.install(Path(entry['_source']).read_bytes(), name, entry['owner'], entry['group'], entry['mode'])
        elif kind == 'link':
            keep(name)
            host.symlink(entry['target'], name)
        elif kind == 'absent':
            keep(name)
            host.remove(name)
        return True

    missing = [s['name'] for s in todo if s['kind'] == 'package']
    if missing:
        if run(['apt-get', 'update']) and run(['apt-get', 'install', '--no-install-recommends', '-y'] + missing):
            changed += [f'package {name}' for name in missing]
    touched = []
    for step in todo:
        if failed:
            break
        if step['kind'] in ('package', 'unit'):
            continue
        try:
            done = do(step)
        except (OSError, LookupError, RebuildError) as e:
            failed.append(f'{step["kind"]} {step["name"]}: {type(e).__name__}: {e}')
            break
        if done:
            changed.append(f'{step["kind"]} {step["name"]}')
            touched.append(step['entry'])
    after = plan(inv, host, party_root, games_source)
    wanted = activation_set(after)
    units = [s['name'] for s in after if s['kind'] == 'unit' and s['status'] == CHANGE]
    if activate:
        for argv in wanted:
            if failed or not run(argv):
                break
        for unit in units:
            if failed or not run(['systemctl', 'enable', '--now', unit]):
                break
            changed.append(f'unit {unit}')
        pending = ['sudo ' + _quote(argv) for argv in wanted + [['systemctl', 'enable', '--now', u] for u in units]
                   if argv not in ran]
    else:
        # Only what this run made necessary; `apply --activate` runs the whole set, every time.
        mine = [argv for entry in touched for argv in entry.get('activate', [])]
        pending = ['sudo ' + _quote(argv) for argv in wanted if argv in mine]
        pending += [f'sudo systemctl enable --now {unit}' for unit in units]
    for entry in touched:
        pending += [OWNER_STEPS[step].format(**profile) for step in entry.get('owner_activate', [])]
    return {'changed': changed, 'pending': pending, 'backup': backup, 'failed': failed}


def _journal(inv, host, backup):
    """The journal of one apply, every entry checked before anything is put back: the backup is
    one of ours, each path is one the inventory manages and never a secret, each copy is inside
    the backup."""
    backup = str(PurePosixPath(backup))
    if not re.fullmatch(re.escape(BACKUP_ROOT) + r'/rebuild-\d{8}T\d{6}Z(-\d+)?', backup):
        raise RebuildError(f'{backup} is not a backup directory of this tool ({BACKUP_ROOT}/rebuild-<UTC>)')
    journal_path = host.path(f'{backup}/journal.json')
    if not journal_path.is_file():
        raise RebuildError(f'{backup} is not a backup written by apply (no journal.json)')
    try:
        journal = json.loads(journal_path.read_text(encoding='utf-8'))
    except ValueError:
        journal = None
    managed = {e['path'] for e in inv['files'] + inv['links'] + inv['absent']}
    names = {'root'} | {u['name'] for u in inv['users']} | {g['name'] for g in inv['groups']}
    if not isinstance(journal, list):
        raise RebuildError(f'{backup}/journal.json is not a journal')
    for entry in journal:
        path = entry.get('path') if isinstance(entry, dict) else None
        if not _absolute(path) or path not in managed or is_secret(path):
            raise RebuildError(f'restore refused, nothing was changed: the journal names {path!r}, which is not a '
                               'path this tool manages')
        kind = entry.get('kind')
        if kind == 'file':
            meta = entry.get('meta')
            if not re.fullmatch(r'files/\d{3}', str(entry.get('copy'))) or not host.path(f'{backup}/{entry["copy"]}').is_file() \
                    or not (isinstance(meta, list) and len(meta) == 3 and _mode_ok(meta[2])
                            and meta[0] in names and meta[1] in names):
                raise RebuildError(f'restore refused, nothing was changed: the journal entry for {path} is damaged')
        elif kind == 'link':
            if not _absolute(entry.get('target')):
                raise RebuildError(f'restore refused, nothing was changed: the journal entry for {path} is damaged')
        elif kind is not None:
            raise RebuildError(f'restore refused, nothing was changed: the journal entry for {path} is damaged')
    return backup, journal


def restore(inv, host, backup, owner_override=False, target_hostname=None):
    """Put back every path one `apply` replaced or removed, newest first. Users, groups, packages
    and directories stay: they grant nothing by themselves and the next apply reuses them. Only on
    a host `authorize` lets through, and never under a running service: a unit file or drop-in of
    an active unit is not touched until the owner has stopped that unit."""
    authorize(inv, host, 'restore', owner_override=owner_override, target_hostname=target_hostname)
    backup, journal = _journal(inv, host, backup)
    running = sorted({unit for unit in (_running_unit(host, e['path']) for e in journal) if unit})
    if running:
        raise RebuildError('restore refused, nothing was changed: it would replace or remove the unit files of '
                           f'running services. Stop them first: sudo systemctl stop {" ".join(running)}')
    restored = []
    for entry in reversed(journal):
        path = entry['path']
        if entry['kind'] == 'file':
            host.install(host.path(f'{backup}/{entry["copy"]}').read_bytes(), path, *entry['meta'])
        elif entry['kind'] == 'link':
            host.symlink(entry['target'], path)
        else:
            host.remove(path)
        restored.append(path)
    return restored


# ---- verify -----------------------------------------------------------------------------------
def parse_topology(text):
    """tools/avrana-topology-check's PASS/FAIL/WARN lines as results, each under the area it is about."""
    out = []
    for line in text.splitlines():
        word, _, what = line.partition(' ')
        if word in ('PASS', 'FAIL', 'WARN'):
            lowered = what.lower()
            if 'dns' in lowered or 'dhcp' in lowered:
                area = 'dns'
            elif 'nginx' in lowered or 'http' in lowered:
                area = 'nginx'
            else:
                area = 'ap'
            out.append((area, f'topology {what}', word.lower(), ''))
    return out or [('ap', 'topology', FAIL, 'tools/avrana-topology-check printed no verdict')]


def uinput_check(meta):
    """Did the uinput module and its udev rule take effect? `meta` is (owner, group, mode) of
    /dev/uinput, or None. Without it the arcade starts and no phone can control a hero."""
    if meta is None:
        return ('arcade', 'uinput device', FAIL, '/dev/uinput is not there: sudo modprobe uinput')
    ok = meta[1] == 'input' and meta[2] == '0660'
    return ('arcade', 'uinput device', PASS if ok else FAIL,
            f'/dev/uinput is {meta[0]}:{meta[1]} {meta[2]}' + ('' if ok else '; the udev rule wants group input 0660: '
                                                              'sudo udevadm control --reload-rules && sudo udevadm trigger --subsystem-match=misc'))


def live_checks(party_root=REPO_ROOT):
    """The checks only the real appliance can answer, from the tools that already exist: the
    smoke set, the read-only topology check, the service boundary and the Party Core config."""
    from avrana.contracts import party_config
    from avrana.ops import boundary, smoke
    out = []
    try:
        for r in smoke.run_pi():
            out.append((SMOKE_AREAS.get(r.name.split(':')[0], 'health'), f'smoke {r.name}', r.status, r.detail))
    except Exception as e:                             # one broken probe must not hide the others
        out.append(('health', 'smoke', FAIL, f'did not run ({type(e).__name__})'))
    try:
        topo = subprocess.run(['bash', str(party_root / 'tools' / 'avrana-topology-check'), str(party_root)],
                              capture_output=True, timeout=120).stdout.decode('utf-8', 'replace')
        out += parse_topology(topo)
    except (OSError, subprocess.TimeoutExpired) as e:
        out.append(('ap', 'topology', FAIL, f'did not run ({type(e).__name__})'))
    try:
        for r in boundary.evaluate(boundary.collect(), boundary.load_spec(), (1,)):
            out.append(('health', f'boundary {r["rule"]} {r["subject"]}', PASS if r['ok'] else FAIL, r.get('detail', '')))
    except Exception as e:
        out.append(('health', 'boundary', FAIL, f'did not run ({type(e).__name__})'))
    out.append(uinput_check(Host(readonly=True).meta('/dev/uinput')))
    try:
        conf = json.loads(Path('/etc/avrana-party/party-core.json').read_text(encoding='utf-8'))
        games = party_config.resolve(conf.get('games', {}))
        out.append(('party', 'party-core.json agrees with the Game Contracts', PASS, f'{len(games)} game(s)'))
    except Exception as e:
        out.append(('party', 'party-core.json agrees with the Game Contracts', FAIL, type(e).__name__))
    return out


def verify(inv, host, party_root=REPO_ROOT, games_source=GAMES_RELEASE, live=None):
    """[(area, name, status, detail, 'state' or 'live')]: the inventory's state on this host, then
    the live checks. A simulated host skips the live checks: a skip is never a pass."""
    results = []
    for s in plan(inv, host, party_root, games_source):
        label = f'{s["kind"]} {s["name"]}'
        if s['status'] == OK:
            results.append((s['area'], label, PASS, '', 'state'))
        elif s['status'] == KEPT:
            results.append((s['area'], label, WARN, s['detail'], 'state'))
        elif s['optional']:
            results.append((s['area'], label, SKIP, 'optional: ' + s['detail'], 'state'))
        elif s['kind'] == 'secret' and not s['entry']['paths']:
            results.append((s['area'], label, SKIP, 'no file to look at; see the live and hardware checks', 'state'))
        else:
            results.append((s['area'], label, FAIL, s['detail'], 'state'))
    for a in inv['artifacts']:
        evidence = a.get('sha256_evidence')
        if evidence and host.kind(a['path']) == 'file':
            want = json.loads((party_root / evidence).read_text(encoding='utf-8')).get('core_sha256')
            same = host.sha256(a['path']) == want
            results.append((a['area'], f'artifact {a["id"]} sha256', PASS if same else WARN,
                            f'matches {evidence}' if same else f'differs from {evidence}: the owner confirms which binary this is',
                            'state'))
    if live is None and host.simulated:
        results.append(('health', 'live checks (smoke, topology, boundary)', SKIP,
                        'simulated host: only the real appliance answers these', 'live'))
    else:
        results += [(*r, 'live') for r in (live or live_checks)(party_root)]
    return results


def summarize(inv, results):
    counts = {s: sum(1 for r in results if r[2] == s) for s in (PASS, FAIL, SKIP, WARN)}
    # Files in place say nothing about a radio or a resolver: an area counts as checked only when
    # something that ran against the live system passed.
    unverified = [a for a in REQUIRED_AREAS
                  if not any(r[0] == a and r[2] == PASS and r[4] == 'live' for r in results)]
    return {'ok': counts[FAIL] == 0, 'counts': counts, 'areas_without_a_live_pass': unverified,
            'checks': [dict(zip(('area', 'name', 'status', 'detail', 'source'), r)) for r in results],
            'hardware_checks': inv['hardware_checks']}


# ---- command line -----------------------------------------------------------------------------
def _print_plan(steps, out):
    for s in steps:
        out(f'{s["status"].upper():8} {s["kind"]:10} {s["name"]}' + (f'  ({s["detail"]})' if s['detail'] else ''))
    handoffs = [s for s in steps if s['status'] == HANDOFF]
    if handoffs:
        out('\nHandoffs (the owner or an existing script provides these; nothing here is in the repository):')
        for s in handoffs:
            out(f'  {s["kind"]} {s["name"]}' + (' [optional]' if s['optional'] else '') + f': {s["detail"]}')
    left = sum(1 for s in steps if s['status'] not in (OK, KEPT) and not s['optional'])
    out(f'\nplan: {sum(1 for s in steps if s["status"] == OK)} in place, {left} not yet '
        f'({sum(1 for s in steps if s["status"] == CHANGE)} this tool can do now)')


def main(argv=None, out=print):
    # No abbreviations: `--o` must never mean the owner's override, nor `--a` --activate.
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0], allow_abbrev=False)
    ap.add_argument('command', choices=('check', 'plan', 'apply', 'restore', 'verify', 'seal', 'ap-profile',
                                        'packages', 'unknowns'))
    ap.add_argument('backup', nargs='?', help='restore: the backup directory an apply printed')
    ap.add_argument('--root', help='work on a SIMULATED host under this directory')
    ap.add_argument('--games-source', default=GAMES_RELEASE, help='the Games release the games unit files come from')
    ap.add_argument('--inventory', help='another inventory file (tests)')
    ap.add_argument('--activate', action='store_true',
                    help='apply: also run the reload commands of everything in place and start the units')
    ap.add_argument('--target-hostname', metavar='NAME',
                    help='apply/restore: the hostname of the machine you mean to change, typed, not computed; '
                         'required for the first apply and with the override')
    ap.add_argument('--owner-confirms-not-the-live-appliance', dest='owner_override', action='store_true',
                    help='apply/restore: OWNER ONLY, typed by a person, on a half-built target (marker lost, or '
                         'deploy before the first apply). Refused whenever an appliance service is enabled or running')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args(argv)
    inv = load_inventory(args.inventory)
    errors = validate(inv)
    if args.command == 'check' or errors:
        for e in errors:
            print(f'inventory: {e}', file=sys.stderr)
        if not errors:
            out(f'inventory agrees with the repository: {len(inv["packages"])} packages, {len(inv["files"])} files, '
                f'{len(inv["secrets"])} secrets (none in the repository), {len(inv["unknowns"])} unknowns')
        return 1 if errors else 0
    if args.command == 'ap-profile':
        out('# Owner-run, on the device, never over the party Wi-Fi. No passphrase is in this command:')
        out('sudo ' + _quote(ap_profile_command(inv)))
        out(f'sudo nmcli --ask connection up "{inv["network"]["access_point"]["profile"]}"   # asks for the passphrase')
        return 0
    if args.command == 'packages':
        out(' '.join(p['name'] for p in inv['packages']))
        return 0
    if args.command == 'unknowns':
        for u in inv['unknowns']:
            out(f'{u["id"]}: {u["question"]}\n    confirm: {u["confirm"]}')
        return 0
    changing = args.command in ('apply', 'restore', 'seal')
    try:
        host = Host(args.root, readonly=not changing)
        if host.simulated:
            out(f'SIMULATED host under {args.root}: a rehearsal, not evidence about an appliance')
        elif changing and os.geteuid() != 0:
            raise RebuildError(f'{args.command} changes the host: run as root (sudo)')
        elif os.geteuid() != 0:
            out('not root: root-only paths (the certificate, the key store) read as absent')
        if args.command == 'plan':
            steps = plan(inv, host, games_source=args.games_source)
            if args.json:
                out(json.dumps({'guard': guard_state(inv, host),
                                'steps': [{k: v for k, v in s.items() if k != 'entry'} for s in steps]}, indent=1))
            else:
                out(describe_guard(inv, host))
                _print_plan(steps, out)
            return 0
        if args.command == 'apply':
            result = apply(inv, host, games_source=args.games_source, activate=args.activate, log=out,
                           owner_override=args.owner_override, target_hostname=args.target_hostname)
            for line in result['changed']:
                out(f'changed  {line}')
            if result['backup']:
                out(f'replaced files are kept in {result["backup"]}; undo: rebuild restore {result["backup"]}')
            for line in result['failed']:
                out(f'FAILED   {line}')
            if result['failed']:
                out('stopped at the first failure: nothing after it was attempted')
            if result['pending']:
                out('to activate (owner; `apply --activate` runs the reload commands of everything in place):')
                for line in result['pending']:
                    out(f'  {line}')
            _print_plan(plan(inv, host, games_source=args.games_source), out)
            return 1 if result['failed'] else 0
        if args.command == 'restore':
            if not args.backup:
                raise RebuildError('restore needs the backup directory')
            for path in restore(inv, host, args.backup, owner_override=args.owner_override,
                                target_hostname=args.target_hostname):
                out(f'restored {path}')
            out('reload what reads them: sudo systemctl daemon-reload; sudo nginx -t && sudo systemctl reload nginx')
            return 0
        if args.command == 'seal':
            marker = seal(inv, host)
            out(f'sealed on {marker["sealed"]}: apply and restore now refuse this host; plan and verify still read it')
            return 0
        summary = summarize(inv, verify(inv, host, games_source=args.games_source))
        summary['guard'] = guard_state(inv, host)
        guard_line = describe_guard(inv, host)
    except RebuildError as e:
        print(f'rebuild: {e}', file=sys.stderr)
        return 2
    except (OSError, LookupError) as e:                 # a missing user, a full disk, a path in the way
        print(f'rebuild: {args.command} failed: {type(e).__name__}: {e}', file=sys.stderr)
        return 1
    if args.json:
        out(json.dumps(summary, indent=1))
    else:
        out(guard_line)
        for c in summary['checks']:
            out(f'{c["status"].upper():5} {c["area"]:7} {c["name"]}' + (f'  ({c["detail"]})' if c['detail'] else ''))
        n = summary['counts']
        out(f'verify: {n[PASS]} passed, {n[FAIL]} failed, {n[WARN]} warnings, {n[SKIP]} skipped (skips are not passes)')
        if summary['areas_without_a_live_pass']:
            out('no passing live check here for: ' + ', '.join(summary['areas_without_a_live_pass']))
        out('Still a human step, on real phones over the party Wi-Fi:')
        for h in inv['hardware_checks']:
            out(f'  [ ] {h["area"]:7} {h["check"]}')
    return 0 if summary['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
