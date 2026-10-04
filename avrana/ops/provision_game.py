"""Provision a native game on the appliance (ADR 0016 sections 3, 4, 5 and 8; AVR-236).

The core only: what is created, reconciled, rotated and removed, against a `Layout` the caller
supplies. It has no command line yet and no default paths, on purpose: where the registry lives,
what a game executes and how an active session is detected are owner decisions recorded on
AVR-236. Everything here takes them as arguments, so nothing in this module decides them.

What it never does: create a Unix user or group (a game's identity is its DynamicUser= unit
instance), restart Party Core (it reloads), print or log a key, or touch a game that has no Game
Contract and no appliance grant in this repository.

`run` is how systemd is told: a callable taking an argv list. Tests pass a recorder; the real
one is subprocess.run(check=True) as root.
"""
import json
import os
import re
import secrets
import shutil
from dataclasses import dataclass
from pathlib import Path

GAME_ID = re.compile(r'^[a-z][a-z0-9_-]{0,39}$')      # the Game Contract id pattern (contracts/game.py)
PARTY_UNIT = 'avrana-party-core.service'


class Refused(Exception):
    """Provisioning will not do this. The message says why and names no secret."""


@dataclass(frozen=True)
class Layout:
    """Where things are on this host. No field has a default: the caller states every path."""
    key_dir: Path           # ADR 0016 section 3: /etc/avrana-party/game-keys, 0700, the Party's
    registry_dir: Path      # root-owned, world-readable; one <slug>.json per native game
    socket_dir: Path        # /run/avrana-games
    state_dir: Path         # /var/lib/avrana-games

    def key(self, slug):
        return Path(self.key_dir) / f'{slug}.key'

    def entry(self, slug):
        return Path(self.registry_dir) / f'{slug}.json'

    def socket(self, slug):
        return Path(self.socket_dir) / f'{slug}.sock'

    def state(self, slug):
        return Path(self.state_dir) / slug


def units(slug):
    return f'avrana-game@{slug}.socket', f'avrana-game@{slug}.service'


def check(slug, contracts, grants):
    """Refuse a slug that is not a game this repository knows and this appliance is granted."""
    if not isinstance(slug, str) or not GAME_ID.match(slug):
        raise Refused(f'{slug!r} is not a game id')
    if slug not in contracts:
        raise Refused(f'{slug}: no Game Contract (contracts/games/{slug}.json)')
    if slug not in grants:
        raise Refused(f'{slug}: this appliance has no grant for it')


def _write_key(path, own):
    """A new 32-byte key, 0600, owned by Party Core, put in place atomically."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    own(path.parent)
    tmp = path.with_name(f'.{path.name}.{secrets.token_hex(4)}')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='ascii') as f:
            f.write(secrets.token_hex(32) + '\n')
        os.chmod(tmp, 0o600)
        own(tmp)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _entry(layout, slug, timeout):
    entry = {'id': slug, 'socket': layout.socket(slug).as_posix(), 'key_file': layout.key(slug).as_posix()}
    if timeout is not None:
        entry['timeout'] = timeout
    return entry


def provision(slug, layout, contracts, grants, run, own, timeout=None):
    """Create or reconcile. Returns the list of what changed; [] on a second run. The key and
    the state directory are kept if they exist (ADR 0016 section 8); the registry entry is
    rewritten to match. Party Core is reloaded only when something it reads changed."""
    check(slug, contracts, grants)
    changed = []
    key = layout.key(slug)
    if not key.exists():
        _write_key(key, own)
        changed.append('key')
    want = json.dumps(_entry(layout, slug, timeout), indent=2, sort_keys=True) + '\n'
    entry = layout.entry(slug)
    if not entry.exists() or entry.read_text(encoding='utf-8') != want:
        entry.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        tmp = entry.with_name(f'.{entry.name}.tmp')
        tmp.write_text(want, encoding='utf-8', newline='\n')
        os.chmod(tmp, 0o644)
        os.replace(tmp, entry)
        changed.append('registry')
    socket_unit, _ = units(slug)
    if changed:
        run(['systemctl', 'daemon-reload'])
    run(['systemctl', 'enable', '--now', socket_unit])       # a no-op when already enabled and listening
    if changed:
        run(['systemctl', 'reload', PARTY_UNIT])
    return changed


def rotate(slug, layout, contracts, grants, run, own, active):
    """Replace the key, restart the game so it loads the new one, and have Party reload.
    `active(slug)` says whether that game has a session running; rotation is refused if so."""
    check(slug, contracts, grants)
    if not layout.key(slug).exists():
        raise Refused(f'{slug}: not provisioned')
    if active(slug):
        raise Refused(f'{slug}: has a session running; rotate when it has ended')
    _write_key(layout.key(slug), own)
    _, service_unit = units(slug)
    run(['systemctl', 'stop', service_unit])                 # the next connection starts it with the new key
    run(['systemctl', 'reload', PARTY_UNIT])
    return ['key']


def remove(slug, layout, run, keep_state=False):
    """Leave nothing behind for this slug: units stopped and disabled, registry entry, key,
    runtime socket and (unless keep_state) the state directory. Works for a slug whose contract
    is already gone, so a game can always be taken off the appliance. Party reloads first-hand
    knowledge of the registry before the key disappears."""
    if not isinstance(slug, str) or not GAME_ID.match(slug):
        raise Refused(f'{slug!r} is not a game id')
    socket_unit, service_unit = units(slug)
    run(['systemctl', 'disable', '--now', socket_unit])
    run(['systemctl', 'stop', service_unit])
    removed = []
    if layout.entry(slug).exists():
        layout.entry(slug).unlink()
        removed.append('registry')
        run(['systemctl', 'reload', PARTY_UNIT])
    for name, path in (('key', layout.key(slug)), ('socket', layout.socket(slug))):
        if path.exists() or path.is_symlink():
            path.unlink()
            removed.append(name)
    state = layout.state(slug)
    if state.exists() and not keep_state:
        shutil.rmtree(state)
        removed.append('state')
    return removed
