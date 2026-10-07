"""Provision a native game on the appliance (ADR 0016 sections 3, 4, 5 and 8; AVR-236).

    python3 -m avrana.ops.provision_game <slug> [--rotate | --remove [--keep-state]] [--dry-run]
                                         [--appliance PATH] [--party-url URL]

One command, run as root, makes a game from this repository a native game of this appliance: its
key (the Party's, 0600), its registry entry (/etc/avrana-party/games.d/<slug>.json), its socket
unit instance, and the drop-in that says what the shared service template runs. Everything below
`main` is the core, which takes every path and every effect as an argument (no defaults, so a test
can point it at a scratch directory with a recorded `run`); `main` is the command line that
supplies the real ones.

What it never does: create a Unix user or group (a game's identity is its DynamicUser= unit
instance; the users and groups come from ADR 0016 phase 1), restart Party Core (it reloads),
print or log a key, or touch a game that has no Game Contract and no appliance grant in this
repository.

What a game runs is the `runtime` object of its appliance grant (`installed[]` in
contracts/appliances/<id>.json): {"command": [absolute path, args...], "working_directory": "/abs"}.
`provision` writes it as the root-owned drop-in <unit_dir>/avrana-game@<slug>.service.d/exec.conf
and installs the two shared template units from the repository into <unit_dir> when they are
missing or differ. A grant without `runtime` is refused: there would be nothing to start.

Reconcile never restarts a game. If only the drop-in or the templates changed and the game's
service is already running, it keeps running the old command until it next stops (systemd re-reads
the unit at `daemon-reload`, and applies it at the next start). A game behind a live session is
not restarted for a configuration change; restart it by hand when the party is between games.

`run` is how systemd is told: a callable taking an argv list. Tests pass a recorder; the real
one is subprocess.run(check=True) as root. `own` re-owns a path to Party Core's user.
"""
import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

GAME_ID = re.compile(r'^[a-z][a-z0-9_-]{0,39}$')      # the Game Contract id pattern (contracts/game.py)
PARTY_UNIT = 'avrana-party-core.service'
TEMPLATES = ('avrana-game@.socket', 'avrana-game@.service')
PARTY_USER = 'avrana-party'
PHASE_1_GROUPS = ('avrana-front', 'avrana-games')
DEFAULT_PARTY_URL = 'http://127.0.0.1:8191'
STATUS_PATH = '/party/api/status'
PARTY_CONFIG = '/etc/avrana-party/party-core.json'
STATUS_SETTLE_S = 6.0          # longer than Party Core's status cache (avrana.ops.status.CACHE_S)
CONTROL = re.compile(r'[\x00-\x1f\x7f]')


class Refused(Exception):
    """Provisioning will not do this. The message says why and names no secret."""


@dataclass(frozen=True)
class Layout:
    """Where things are on this host. No field has a default: the caller states every path."""
    key_dir: Path           # ADR 0016 section 3: /etc/avrana-party/game-keys, 0700, the Party's
    registry_dir: Path      # root-owned, world-readable; one <slug>.json per native game
    socket_dir: Path        # /run/avrana-games
    state_dir: Path         # /var/lib/avrana-games
    unit_dir: Path          # /etc/systemd/system: the template units and the per-slug drop-in
    template_dir: Path      # the repository's deploy/games: the source of the two template units

    def key(self, slug):
        return Path(self.key_dir) / f'{slug}.key'

    def entry(self, slug):
        return Path(self.registry_dir) / f'{slug}.json'

    def socket(self, slug):
        return Path(self.socket_dir) / f'{slug}.sock'

    def state(self, slug):
        return Path(self.state_dir) / slug

    def state_paths(self, slug):
        """Everything that is this game's state. With DynamicUser= systemd keeps the directory
        under <parent>/private/ and leaves a symbolic link at the public path, so both are named."""
        root = Path(self.state_dir)
        return [root / slug, root.parent / 'private' / root.name / slug]

    def dropin_dir(self, slug):
        return Path(self.unit_dir) / f'avrana-game@{slug}.service.d'

    def dropin(self, slug):
        return self.dropin_dir(slug) / 'exec.conf'


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


def _runtime(slug, grants):
    from avrana.contracts import appliance
    grant = grants[slug]
    if not isinstance(grant, dict) or 'runtime' not in grant:
        raise Refused(f'{slug}: the appliance grant has no "runtime" (what to run, and where); nothing to start')
    problems = appliance.runtime_problems(grant['runtime'], f'{slug}.runtime')
    if problems:
        raise Refused('; '.join(problems))
    return grant['runtime']


def quote_exec(arg):
    """One ExecStart= word: double-quoted, with the backslash, the quote, the specifier `%` and
    the environment `$` escaped, so no argument can be split, expanded or read as a modifier."""
    escaped = arg.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%').replace('$', '$$')
    return f'"{escaped}"'


def dropin_text(runtime):
    """The exec.conf for a validated `runtime`. Refuses any control character itself, since the
    text goes into a unit file where a newline would add a directive."""
    strings = list(runtime['command']) + [runtime['working_directory']]
    if any(not isinstance(s, str) or CONTROL.search(s) for s in strings):
        raise Refused('runtime: control characters are not allowed in a unit file')
    return ('# Written by provision-game from the appliance grant (AVR-236). Edits are overwritten.\n'
            '[Service]\n'
            f"ExecStart={' '.join(quote_exec(a) for a in runtime['command'])}\n"
            f"WorkingDirectory={runtime['working_directory'].replace('%', '%%')}\n")


def _put(path, data, mode):
    """Write `data` (bytes) to `path` atomically with `mode`."""
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    tmp = path.with_name(f'.{path.name}.{secrets.token_hex(4)}')
    try:
        tmp.write_bytes(data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _differs(path, data):
    return not path.is_file() or path.read_bytes() != data


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


def _wanted(slug, layout, grants, timeout):
    """(registry text, drop-in text, [(template path, bytes)]) this slug should have."""
    runtime = _runtime(slug, grants)
    entry = json.dumps(_entry(layout, slug, timeout), indent=2, sort_keys=True) + '\n'
    templates = []
    for name in TEMPLATES:
        src = Path(layout.template_dir) / name
        if not src.is_file():
            raise Refused(f'{name}: missing from {layout.template_dir}')
        templates.append((Path(layout.unit_dir) / name, src.read_bytes()))
    return entry, dropin_text(runtime), templates


def plan_provision(slug, layout, contracts, grants, timeout=None):
    """What `provision` would change, without changing anything (for --dry-run)."""
    check(slug, contracts, grants)
    entry, dropin, templates = _wanted(slug, layout, grants, timeout)
    changed = []
    if not layout.key(slug).exists():
        changed.append('key')
    if not layout.entry(slug).exists() or layout.entry(slug).read_text(encoding='utf-8') != entry:
        changed.append('registry')
    changed += [f'unit {path.name}' for path, data in templates if _differs(path, data)]
    if _differs(layout.dropin(slug), dropin.encode('utf-8')):
        changed.append('dropin')
    return changed


def provision(slug, layout, contracts, grants, run, own, timeout=None):
    """Create or reconcile. Returns the list of what changed ('key', 'registry', 'unit <name>',
    'dropin'); [] on a second run, which then touches nothing (no daemon-reload, no Party reload).
    The key and the state directory are kept if they exist (ADR 0016 section 8); the registry
    entry, the template units and the drop-in are rewritten to match. Party Core is reloaded only
    when something it reads (key, registry) changed. A running game is not restarted; see the
    module docstring."""
    check(slug, contracts, grants)
    entry_text, dropin, templates = _wanted(slug, layout, grants, timeout)       # refuse before writing anything
    changed = []
    key = layout.key(slug)
    if not key.exists():
        _write_key(key, own)
        changed.append('key')
    entry = layout.entry(slug)
    if not entry.exists() or entry.read_text(encoding='utf-8') != entry_text:
        _put(entry, entry_text.encode('utf-8'), 0o644)
        changed.append('registry')
    for path, data in templates:
        if _differs(path, data):
            _put(path, data, 0o644)
            changed.append(f'unit {path.name}')
    if _differs(layout.dropin(slug), dropin.encode('utf-8')):
        _put(layout.dropin(slug), dropin.encode('utf-8'), 0o644)
        changed.append('dropin')
    socket_unit, _ = units(slug)
    if changed:
        run(['systemctl', 'daemon-reload'])
    run(['systemctl', 'enable', '--now', socket_unit])       # a no-op when already enabled and listening
    if 'key' in changed or 'registry' in changed:
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


def plan_rotate(slug, layout, contracts, grants, active):
    check(slug, contracts, grants)
    if not layout.key(slug).exists():
        raise Refused(f'{slug}: not provisioned')
    if active(slug):
        raise Refused(f'{slug}: has a session running; rotate when it has ended')
    return ['key']


def _leftovers(slug, layout, keep_state):
    found = []
    if layout.entry(slug).exists():
        found.append('registry')
    if layout.dropin_dir(slug).exists():
        found.append('dropin')
    for name, path in (('key', layout.key(slug)), ('socket', layout.socket(slug))):
        if path.exists() or path.is_symlink():
            found.append(name)
    if not keep_state and any(p.exists() or p.is_symlink() for p in layout.state_paths(slug)):
        found.append('state')
    return found


def plan_remove(slug, layout, keep_state=False):
    if not isinstance(slug, str) or not GAME_ID.match(slug):
        raise Refused(f'{slug!r} is not a game id')
    return _leftovers(slug, layout, keep_state)


def remove(slug, layout, run, keep_state=False):
    """Leave nothing behind for this slug: units stopped and disabled, registry entry, exec
    drop-in, key, runtime socket and (unless keep_state) the state directory. The shared template
    units stay: other games use them. Works for a slug whose contract is already gone, so a game
    can always be taken off the appliance. The registry entry goes first and Party reloads before
    the key disappears."""
    if not isinstance(slug, str) or not GAME_ID.match(slug):
        raise Refused(f'{slug!r} is not a game id')
    socket_unit, service_unit = units(slug)
    for argv in (['systemctl', 'disable', '--now', socket_unit], ['systemctl', 'stop', service_unit]):
        try:
            run(argv)
        except subprocess.CalledProcessError:
            pass          # already gone (a second remove, or a half-removed game): the rest still goes
    removed = []
    if layout.entry(slug).exists():
        layout.entry(slug).unlink()
        removed.append('registry')
        run(['systemctl', 'reload', PARTY_UNIT])
    if layout.dropin_dir(slug).exists():
        shutil.rmtree(layout.dropin_dir(slug))
        removed.append('dropin')
    for name, path in (('key', layout.key(slug)), ('socket', layout.socket(slug))):
        if path.exists() or path.is_symlink():
            path.unlink()
            removed.append(name)
    if not keep_state:
        gone = False
        for path in layout.state_paths(slug):                # the link first, then what it pointed at
            if path.is_symlink():
                path.unlink()
            elif path.exists():
                shutil.rmtree(path)
            else:
                continue
            gone = True
        if gone:
            removed.append('state')
    run(['systemctl', 'daemon-reload'])                      # the drop-in is gone; systemd forgets it
    return removed


# ---- asking Party Core whether a game has a session (owner decision Q3) ----------------------

def session_game(doc):
    """The id of the game whose session is running, or None, from Party Core's status document
    (GET /party/api/status): party_core.session is {"game": id, "state": ...} or null. The session
    is "the current or most recent", so state 'ended' is no session. A document that does not have
    that shape is Refused: Party Core answered, and we cannot tell, so we do not rotate."""
    core = doc.get('party_core') if isinstance(doc, dict) else None
    if not isinstance(core, dict) or core.get('ok') is not True or 'session' not in core:
        raise Refused('Party Core did not report its session; not rotating')
    session = core['session']
    if session is None:
        return None
    if not isinstance(session, dict) or not isinstance(session.get('game'), str):
        raise Refused('Party Core reported a session this tool cannot read; not rotating')
    return None if session.get('state') == 'ended' else session['game']


def party_session_check(base_url, opener=urllib.request.urlopen, timeout=3, settle=0.0, sleep=time.sleep,
                        host=None):
    """An `active(slug)` for `rotate`. Party Core unreachable means no party and so no session
    (it is memory-only): rotation proceeds. Reachable but unreadable is refused.

    Party Core answers the status route from a short cache (avrana.ops.status.CACHE_S), so one
    "no session" can be older than a launch. With `settle` above that cache's age, a "no session"
    is asked again after waiting that long, and only two in a row count."""
    url = base_url.rstrip('/') + STATUS_PATH
    # Party Core answers only for a Host it is configured with (party-core.json `hosts`), also on
    # loopback; `host` is that name, as ops.smoke sends it.
    target = urllib.request.Request(url, headers={'Host': host}) if host else url

    def active(slug):
        first = look(slug)
        if first is not False or not settle:
            return first is True
        sleep(settle)
        return look(slug) is True

    def look(slug):
        """True: this game has a session. False: Party Core says it has none. None: Party Core
        is not there, so there is no party."""
        try:
            with opener(target, timeout=timeout) as response:
                doc = json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            raise Refused(f'Party Core answered HTTP {e.code}; not rotating') from None
        except (urllib.error.URLError, OSError):             # nothing is listening, or it timed out
            return None
        except ValueError:
            raise Refused('Party Core answered something that is not JSON; not rotating') from None
        return session_game(doc) == slug
    return active


# ---- the command line --------------------------------------------------------------------------

def _real_run(argv):
    subprocess.run(argv, check=True)


def _phase_1():
    """(uid, gid) of Party Core's user, or Refused if ADR 0016 phase 1 has not been applied."""
    try:
        import grp
        import pwd
    except ImportError:
        raise Refused('this tool changes a Linux appliance; ADR 0016 phase 1 has not been applied on this host') from None
    try:
        user = pwd.getpwnam(PARTY_USER)
        for name in PHASE_1_GROUPS:
            grp.getgrnam(name)
    except KeyError:
        raise Refused('ADR 0016 phase 1 has not been applied on this host '
                      f'(user {PARTY_USER} and groups {" and ".join(PHASE_1_GROUPS)} are required)') from None
    return user.pw_uid, user.pw_gid


def real_own(path):
    """Re-own `path` to Party Core's user."""
    uid, gid = _phase_1()
    os.chown(path, uid, gid)


def check_party_reads(config_path, registry_dir):
    """Refuse to provision when Party Core would never see the game: its config must name this
    registry directory (`registry` in party-core.json). Installing that key and Party Core's
    socket unit is a one-time owner deployment (docs/runbooks/provision-game.md), not this
    command's: it never edits Party Core's config."""
    try:
        with open(config_path, encoding='utf-8') as f:
            conf = json.load(f)
    except (OSError, ValueError) as e:
        raise Refused(f"Party Core's config {config_path} is unreadable ({type(e).__name__})") from None
    named = conf.get('registry') if isinstance(conf, dict) else None
    if not isinstance(named, str) or Path(named) != Path(registry_dir):
        raise Refused(f'the Party Core config {config_path} does not name the registry directory '
                      f'("registry": "{Path(registry_dir).as_posix()}"); it would never see this game')


def party_host(config_path):
    """The first Host name Party Core answers for (party-core.json `hosts`), or None when the
    config cannot say: the query then goes out with the loopback address as its Host."""
    try:
        with open(config_path, encoding='utf-8') as f:
            hosts = json.load(f).get('hosts')
    except (OSError, ValueError, AttributeError):
        return None
    ok = isinstance(hosts, list) and hosts and isinstance(hosts[0], str) and re.fullmatch(r'[A-Za-z0-9.:\[\]-]{1,255}', hosts[0])
    return hosts[0] if ok else None


def _default_layout(a):
    tree = Path(__file__).resolve().parent.parent.parent
    d = lambda value, default: Path(value or default)
    return Layout(key_dir=d(a.key_dir, '/etc/avrana-party/game-keys'),
                  registry_dir=d(a.registry_dir, '/etc/avrana-party/games.d'),
                  socket_dir=d(a.socket_dir, '/run/avrana-games'),
                  state_dir=d(a.state_dir, '/var/lib/avrana-games'),
                  unit_dir=d(a.unit_dir, '/etc/systemd/system'),
                  template_dir=d(a.template_dir, tree / 'deploy' / 'games'))


class _Usage(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _Usage(message)


def _parser():
    ap = _Parser(prog='provision-game', description='Provision, rotate or remove a native game on this appliance.')
    ap.add_argument('slug')
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--rotate', action='store_true', help="replace the game's key (refused during its session)")
    mode.add_argument('--remove', action='store_true', help='take the game off this appliance')
    ap.add_argument('--keep-state', action='store_true', help='with --remove: keep the state directory')
    ap.add_argument('--dry-run', action='store_true', help='print what would change; change nothing')
    ap.add_argument('--appliance', help='the appliance grant file (default: contracts/appliances/avrana-pi4.json)')
    ap.add_argument('--party-url', default=DEFAULT_PARTY_URL, help=f'Party Core on loopback (default {DEFAULT_PARTY_URL})')
    for name in ('key-dir', 'registry-dir', 'socket-dir', 'state-dir', 'unit-dir', 'template-dir', 'party-config'):
        ap.add_argument(f'--{name}', help=argparse.SUPPRESS)
    return ap


def main(argv=None, *, run=None, own=None, is_root=None, opener=None, contracts=None, appliance_doc=None,
         out=None, err=None):
    """Exit 0 done, 1 refused (message on stderr, never a key), 2 usage. Every effect can be
    injected: `run`, `own`, `is_root`, `opener` (Party Core's status), `contracts`,
    `appliance_doc`, and the output streams."""
    out, err = out or sys.stdout, err or sys.stderr
    try:
        a = _parser().parse_args(sys.argv[1:] if argv is None else argv)
        if a.keep_state and not a.remove:
            raise _Usage('--keep-state goes with --remove')
    except _Usage as e:
        print(f'provision-game: {e}', file=err)
        return 2
    except SystemExit as e:                                  # --help
        return int(e.code or 0)
    try:
        if is_root is None:
            is_root = hasattr(os, 'geteuid') and os.geteuid() == 0
        if not is_root and not a.dry_run:
            raise Refused('must run as root (use sudo), or --dry-run to see what would change')
        layout = _default_layout(a)
        tree = Path(__file__).resolve().parent.parent.parent
        if contracts is None:
            from avrana.contracts import party_config
            contracts = party_config.load_contracts()
        if appliance_doc is None:
            from avrana.contracts import appliance, vocabulary
            appliance_doc = appliance.load(a.appliance or tree / 'contracts' / 'appliances' / 'avrana-pi4.json',
                                           vocabulary.load())
        from avrana.contracts import appliance as appliance_module
        grants = appliance_module.grants(appliance_doc)
        own = own or real_own
        if own is real_own and not a.dry_run:
            _phase_1()                                       # before anything is written
            if not a.remove and not a.rotate:
                check_party_reads(a.party_config or PARTY_CONFIG, layout.registry_dir)
        # The real query waits out Party Core's status cache before a rotation; a dry run and an
        # injected opener do not.
        active = party_session_check(a.party_url, opener or urllib.request.urlopen,
                                     settle=STATUS_SETTLE_S if opener is None and not a.dry_run else 0.0,
                                     host=party_host(a.party_config or PARTY_CONFIG) if opener is None else None)
        if a.remove:
            changes = (plan_remove(a.slug, layout, a.keep_state) if a.dry_run
                       else remove(a.slug, layout, run or _real_run, a.keep_state))
            verb = 'remove'
        elif a.rotate:
            changes = (plan_rotate(a.slug, layout, contracts, grants, active) if a.dry_run
                       else rotate(a.slug, layout, contracts, grants, run or _real_run, own, active))
            verb = 'replace'
        else:
            changes = (plan_provision(a.slug, layout, contracts, grants) if a.dry_run
                       else provision(a.slug, layout, contracts, grants, run or _real_run, own))
            verb = 'change'
    except Refused as e:
        print(f'provision-game: refused: {e}', file=err)
        return 1
    except subprocess.CalledProcessError as e:
        print(f'provision-game: failed: {" ".join(map(str, e.cmd))} exited {e.returncode}', file=err)
        return 1
    except (OSError, ValueError) as e:
        print(f'provision-game: failed: {type(e).__name__}: {e}', file=err)
        return 1
    prefix = f'would {verb}' if a.dry_run else {'change': 'changed', 'replace': 'replaced', 'remove': 'removed'}[verb]
    for item in changes:
        print(f'{a.slug}: {prefix} {item}', file=out)
    if not changes:
        print(f'{a.slug}: nothing to {"remove" if a.remove else "change"}', file=out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
