"""Prepare an appliance for native games: one owner-run step, repeatable, checked, reversible
(ADR 0016 sections 4, 8 and 9; AVR-304).

    sudo python3 -m avrana.ops.prepare_native_games [--dry-run]
    sudo python3 -m avrana.ops.prepare_native_games --reverse [BACKUP_DIR] [--dry-run]
    sudo ops/prepare-native-games ...              (the same, from the deployed code tree)

An appliance that has ADR 0016 phase 1 (ops/migrate-service-users.sh) still lacks three things
before `provision-game` can provision a native game on it. This command brings it to that state:

  1. Party Core's service unit is the repository's deploy/party-core/avrana-party-core.service: it
     has `ExecReload=` (what `systemctl reload` sends, a SIGHUP; provision-game reloads Party Core
     with it and never restarts it) and wants its socket unit;
  2. Party Core's game-facing socket unit, deploy/party-core/avrana-party-core.socket, is installed,
     enabled and listening: /run/avrana-party/internal.sock, avrana-party:avrana-games 0660;
  3. "registry": "/etc/avrana-party/games.d" is in /etc/avrana-party/party-core.json. That file is
     edited in place and every other byte of it stays as it was (formatting, key order, the
     other keys' spelling): the member is inserted, or its value replaced, as text.

The default is: refuse what is unsafe, print the plan, keep the before-state, apply, check. It does
not create users or groups, install nginx, DNS or certificate files, or provision any game, and it
never starts a Party Core that is stopped. It is the one-time owner step that provision-game's
runbook names; docs/runbooks/prepare-native-games.md is the procedure.

    --dry-run           print every file and unit it would change, and whether it would restart Party
                        Core; change nothing
    --reverse [DIR]     put the before-state of an earlier run back (the newest one, or DIR)
    --root DIR          work on a SIMULATED host under DIR (rehearsals, tests): needs AVRANA_SYSTEMCTL

Party Core is restarted only when it has to be: it is running and does not hold the socket, because
it started before the socket unit was listening (a file descriptor is handed to a process when it
starts, never later), or the socket unit's directives change. A restart ends the party (the party is
memory-only, ADR 0006), so the plan says whether it will restart before anything is touched, and a
restart is REFUSED, with nothing changed, while a game session is running. The restart is a stop, the
socket made ready (enabled, started, restarted if its unit changed) and a start: systemd will not
start or restart a socket unit while the service it triggers is running. Between the stop and the
start the run holds off SIGHUP, SIGINT and SIGTERM (a dropped SSH session, Ctrl-C), so it cannot be
ended there with Party Core stopped; and if a step in that window fails, Party Core is started again.

Party Core is asked the way provision-game asks it: on loopback, never through a proxy, naming the
first of `hosts`; only "nobody is listening" means no session, and an answer that cannot be read
refuses. A Party Core that is stopped is not a session: it is left stopped and takes the socket and
the registry when it next starts.

A second run changes nothing and restarts nothing: what to do is decided from the host as it is
(file bytes, systemd's enabled and active state, what systemd has loaded, when Party Core started
against when the socket began listening), never from what an earlier run did, so a run that failed
half way is finished by running again.

Before it writes anything it keeps the previous unit file(s) and party-core.json in
/var/backups/avrana-party/native-games-<UTC>/ (override the root with AVRANA_BACKUP_ROOT) with a
state.json, and prints that directory. `--reverse` puts them back (a file that did not exist is
removed), disables the socket unit when the run enabled it, and is REFUSED while any native game is
provisioned (a registry entry or an avrana-game@<slug> unit exists): remove the game first with
`provision-game <slug> --remove`. A reverse never restarts Party Core; it starts one that is `failed`,
since the earlier files are what that one ran on. It needs only root and a backup directory, not
phase 1.

Exit status: 0 done (or nothing to change, or a dry run); 1 refused or failed before anything was
changed (the reason is on stderr); 2 usage; 3 the host was changed and a step or check after that
failed ("NOT complete"; run it again to finish, or reverse).

Everything below `main` takes its effects as arguments (the systemctl call, Party Core's status,
the clock), so a test can run it on a scratch root with a recording systemctl. The environment
overrides are the repository's: AVRANA_SYSTEMCTL (one executable, as ops/deploy.sh), AVRANA_BACKUP_ROOT,
AVRANA_PARTY_CORE_URL and AVRANA_ROOT (for --root).
"""
import argparse
import contextlib
import hashlib
import http.client
import json
import os
import re
import secrets
import signal
import socket
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import namedtuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from avrana import REPO_ROOT
from avrana.ops import provision_game as pg

SERVICE = 'avrana-party-core.service'
SOCKET = 'avrana-party-core.socket'
UNIT_DIR = '/etc/systemd/system'
CONFIG = pg.PARTY_CONFIG                            # /etc/avrana-party/party-core.json
REGISTRY_DIR = '/etc/avrana-party/games.d'          # what provision-game's registry directory is
INTERNAL_SOCKET = '/run/avrana-party/internal.sock'
BACKUP_ROOT = '/var/backups/avrana-party'           # as ops/migrate-service-users.sh and ops/deploy.sh
BACKUP_PREFIX = 'native-games-'
STATE_FILE = 'state.json'
REPLACED = 'replaced'
SCHEMA = 'avrana.prepare-native-games/v1'
USER = pg.PARTY_USER
GROUPS = pg.PHASE_1_GROUPS
SOCKET_OWNER, SOCKET_GROUP, SOCKET_MODE = USER, 'avrana-games', 0o660
UNIT_MODE = 0o644
LATEST = ''                                         # `--reverse` with no directory
ANSWER_WAIT_S = 30                                  # how long a restarted Party Core has to answer
SYSTEMCTL_TIMEOUT_S = 180

# What this command changes: the name of each in the backup directory, and where it lives on the host.
UNIT_KEY, SOCKET_KEY, CONFIG_KEY = f'units/{SERVICE}', f'units/{SOCKET}', 'party-core.json'
TARGETS = {UNIT_KEY: f'{UNIT_DIR}/{SERVICE}', SOCKET_KEY: f'{UNIT_DIR}/{SOCKET}', CONFIG_KEY: CONFIG}
WRITE_ORDER = (SOCKET_KEY, UNIT_KEY, CONFIG_KEY)
ABSENT = object()                                   # the earlier value of a key the file did not have


class Refused(Exception):
    """The command will not do this, and has changed nothing. The message says why."""


class Incomplete(Exception):
    """The host was changed and a step or a check after that failed."""


class Progress:
    """Whether anything on the host has been changed yet: what a failure is called."""
    changed = False


Result = namedtuple('Result', 'rc out err')
Check = namedtuple('Check', 'ok text')
Party = namedtuple('Party', 'running game members')   # answering?; the game of its session, or None; members


@dataclass(frozen=True)
class Host:
    """`root` re-bases every path of a SIMULATED host; None is this machine. `source` is where the
    repository's deploy/party-core files are."""
    root: object                    # a Path, or None for this machine
    source: Path

    @property
    def simulated(self):
        return self.root is not None

    def path(self, logical):
        return Path(self.root) / logical.lstrip('/') if self.root is not None else Path(logical)

    def targets(self):
        return {key: self.path(logical) for key, logical in TARGETS.items()}


# ---- systemd, as this command asks it ---------------------------------------------------------

def real_systemctl(command=None):
    """The seam to systemd: `call(args) -> Result`, never raising for a failed command. `command` is
    one executable (AVRANA_SYSTEMCTL, as ops/deploy.sh); the default is `systemctl`."""
    argv = [command or 'systemctl']

    def call(args):
        try:
            done = subprocess.run([*argv, *args], capture_output=True, text=True, timeout=SYSTEMCTL_TIMEOUT_S)
        except FileNotFoundError:
            raise Refused(f'{argv[0]} was not found') from None
        except subprocess.TimeoutExpired:
            return Result(124, '', f'timed out after {SYSTEMCTL_TIMEOUT_S} s')
        return Result(done.returncode, done.stdout, done.stderr)
    return call


def must(sysctl, *args):
    """Run a systemctl command that has to succeed."""
    result = sysctl(list(args))
    if result.rc != 0:
        why = (result.err or result.out).strip().splitlines()
        raise Incomplete(f'systemctl {" ".join(args)} exited {result.rc}' + (f' ({why[0][:160]})' if why else ''))
    return result


def unit_state(sysctl, unit):
    """The word `systemctl is-active` prints: active, inactive, failed, activating..."""
    result = sysctl(['is-active', unit])
    words = result.out.split()
    return words[0] if words else ('active' if result.rc == 0 else 'inactive')


def is_enabled(sysctl, unit):
    result = sysctl(['is-enabled', unit])
    return result.rc == 0 and result.out.strip() in ('enabled', 'enabled-runtime')


def show(sysctl, unit, prop):
    result = sysctl(['show', '-p', prop, '--value', unit])
    return result.out.strip() if result.rc == 0 else ''


def entered(sysctl, unit):
    """When the unit last became active, in microseconds on systemd's monotonic clock (0: never)."""
    value = show(sysctl, unit, 'ActiveEnterTimestampMonotonic')
    return int(value) if value.isdigit() else 0


def holds_socket(sysctl, party_state=None, socket_state=None):
    """Whether the running Party Core has the socket unit's listening socket. systemd hands a socket
    to a service when it STARTS, so Party Core has it exactly when it started after the socket unit
    began listening. A Party Core that is not running, or a socket that is not listening, has none.
    The two states are asked for unless the caller has them."""
    party_state = party_state or unit_state(sysctl, SERVICE)
    socket_state = socket_state or unit_state(sysctl, SOCKET)
    if party_state != 'active' or socket_state != 'active':
        return False
    started, listening = entered(sysctl, SERVICE), entered(sysctl, SOCKET)
    return listening > 0 and started >= listening


# ---- the registry key: a text edit that leaves every other byte alone ------------------------

_JSON = json.JSONDecoder()
_SPACE = ' \t\r\n'


def _skip(text, i):
    while i < len(text) and text[i] in _SPACE:
        i += 1
    return i


def members(text):
    """(position of the opening brace, of the closing brace, [(key, key start, key end, value start,
    value end)]) for the top-level object of `text`; ValueError for anything but one JSON object."""
    i = _skip(text, 0)
    if i >= len(text) or text[i] != '{':
        raise ValueError('the top level is not an object')
    opening, found = i, []
    i = _skip(text, i + 1)
    if i < len(text) and text[i] == '}':
        closing = i
    else:
        while True:
            if i >= len(text) or text[i] != '"':
                raise ValueError('a member name was expected')
            key, name_end = _JSON.raw_decode(text, i)
            j = _skip(text, name_end)
            if j >= len(text) or text[j] != ':':
                raise ValueError('a colon was expected')
            start = _skip(text, j + 1)
            _, end = _JSON.raw_decode(text, start)
            found.append((key, i, name_end, start, end))
            j = _skip(text, end)
            if j < len(text) and text[j] == ',':
                i = _skip(text, j + 1)
            elif j < len(text) and text[j] == '}':
                closing = j
                break
            else:
                raise ValueError('a comma or a closing brace was expected')
    if _skip(text, closing + 1) != len(text):
        raise ValueError('text after the object')
    return opening, closing, found


def set_registry(text, value):
    """(new text, earlier value) with the top-level "registry" member of `text` set to `value`.

    Only that member changes: it is replaced where it stands, or, when the file has none, inserted
    after the last member in the way the file separates its members (the same newline and indent, or
    the same compact comma), so a diff of the two texts is exactly one member. The earlier value is
    ABSENT when there was none. The result is parsed again and must be the same object with that one
    key set and the keys in the same order, or this refuses: it never guesses."""
    try:
        before = json.loads(text)
    except ValueError as e:
        raise Refused(f'{CONFIG} is not valid JSON ({type(e).__name__}); Party Core would not start from it') from None
    if not isinstance(before, dict):
        raise Refused(f'{CONFIG} is not a JSON object')
    try:
        opening, closing, found = members(text)
    except ValueError as e:
        raise Refused(f'{CONFIG} cannot be edited safely ({e}); edit it by hand') from None
    hits = [m for m in found if m[0] == 'registry']
    if len(hits) > 1:
        raise Refused(f'{CONFIG} names "registry" more than once; make it one member, then run this again')
    literal = json.dumps(value)
    if hits:
        earlier = before['registry']
        if earlier == value:
            return text, earlier
        new = text[:hits[0][3]] + literal + text[hits[0][4]:]
    elif found:
        earlier = ABSENT
        _, key_start, key_end, value_start, last_end = found[-1]
        if len(found) > 1:
            gap_start = _skip(text, found[-2][4]) + 1            # after the comma that precedes the last member
        else:
            gap_start = opening + 1
        separator = text[gap_start:key_start]                    # the newline and indent, or nothing
        new = (text[:last_end] + ',' + separator + '"registry"' + text[key_end:value_start] + literal
               + text[last_end:])
    else:
        earlier = ABSENT
        newline = '\r\n' if '\r\n' in text else '\n'
        new = text[:opening + 1] + newline + '  "registry": ' + literal + newline + text[closing:]
    try:
        after = json.loads(new)
    except ValueError:
        after = None
    wanted = dict(before, registry=value)
    if after != wanted or list(after) != list(before) + ([] if 'registry' in before else ['registry']):
        raise Refused(f'{CONFIG} cannot be edited safely (the edit did not give the object it should); edit it by hand')
    return new, earlier


# ---- reading the host ---------------------------------------------------------------------------

def _digest(data):
    return hashlib.sha256(data).hexdigest()


def read_optional(path, logical):
    """The bytes of a plain file, None when there is none. A link or anything else is refused: this
    command installs plain files, as `install` does."""
    if path.is_symlink():
        raise Refused(f'{logical} is a symbolic link; this command installs plain files (remove the link first)')
    if not path.exists():
        return None
    if not path.is_file():
        raise Refused(f'{logical} is not a regular file')
    return path.read_bytes()


@dataclass
class Facts:
    """What is on the host, as the plan needs it."""
    unit: object                    # bytes of the installed service unit, or None
    socket_unit: object
    config: bytes
    config_stat: object
    socket_enabled: bool
    socket_active: bool
    party_state: str                # active, inactive, failed, activating...
    holds: bool                     # the running Party Core has the socket
    need_reload: bool               # systemd has loaded other unit text than is on disk


def read_facts(host, sysctl):
    paths = host.targets()
    try:
        config = read_optional(paths[CONFIG_KEY], CONFIG)
    except PermissionError:
        raise Refused(f'{CONFIG} cannot be read: needs root (run it with sudo)') from None
    if config is None:
        raise Refused(f'{CONFIG} does not exist: Party Core is not installed here, and this command never creates '
                      'its configuration')
    unit = read_optional(paths[UNIT_KEY], TARGETS[UNIT_KEY])
    socket_unit = read_optional(paths[SOCKET_KEY], TARGETS[SOCKET_KEY])
    party_state, socket_state = unit_state(sysctl, SERVICE), unit_state(sysctl, SOCKET)
    return Facts(unit=unit, socket_unit=socket_unit, config=config, config_stat=paths[CONFIG_KEY].stat(),
                 socket_enabled=is_enabled(sysctl, SOCKET), socket_active=socket_state == 'active',
                 party_state=party_state, holds=holds_socket(sysctl, party_state, socket_state),
                 need_reload=any(show(sysctl, u, 'NeedDaemonReload') == 'yes' for u in (SERVICE, SOCKET)))


def read_sources(host, trusted):
    """The repository's two unit files. On a real host they must be root-owned code (the same rule
    provision-game applies to a game's code), since root installs them into /etc/systemd/system."""
    sources = {}
    for name in (SERVICE, SOCKET):
        path = Path(host.source) / name
        if not path.is_file():
            raise Refused(f'{name} is missing from {host.source}')
        if trusted:
            why = pg.untrusted_reason(str(path))
            if why:
                raise Refused(f'{path}: {why}; a unit that root installs comes only from root-owned code '
                              '(run this from the deployed release, /opt/avrana-party/current)')
        sources[name] = path.read_bytes()
    return sources


# ---- the plan --------------------------------------------------------------------------------------

@dataclass
class Plan:
    facts: Facts
    writes: dict = field(default_factory=dict)      # key -> bytes, only what differs
    registry_before: object = ABSENT
    daemon_reload: bool = False
    enable_socket: bool = False
    restart_socket: bool = False
    restart: bool = False                           # Party Core: a restart ends the party
    reload: bool = False                            # Party Core: read the configuration again
    why: str = ''                                   # why Party Core is or is not restarted

    @property
    def backup(self):
        return bool(self.writes) or self.enable_socket

    @property
    def empty(self):
        return not (self.writes or self.daemon_reload or self.enable_socket or self.restart_socket
                    or self.restart or self.reload)


def make_plan(facts, sources):
    if facts.party_state not in ('active', 'inactive', 'failed'):
        raise Refused(f'Party Core is {facts.party_state}, not settled; wait a moment and run this again')
    plan = Plan(facts)
    if facts.unit != sources[SERVICE]:
        plan.writes[UNIT_KEY] = sources[SERVICE]
    if facts.socket_unit != sources[SOCKET]:
        plan.writes[SOCKET_KEY] = sources[SOCKET]
    try:
        text = facts.config.decode('utf-8')
    except UnicodeDecodeError:
        raise Refused(f'{CONFIG} is not UTF-8 text; Party Core would not start from it') from None
    new, plan.registry_before = set_registry(text, REGISTRY_DIR)
    if new != text:
        plan.writes[CONFIG_KEY] = new.encode('utf-8')
    plan.daemon_reload = (UNIT_KEY in plan.writes or SOCKET_KEY in plan.writes) or facts.need_reload
    plan.enable_socket = not facts.socket_enabled or not facts.socket_active
    # A changed socket unit takes effect when the socket is restarted, and that hands Party Core a
    # new socket it does not have: so a change to its directives (a comment is not one) is a reason
    # to restart Party Core too.
    plan.restart_socket = bool(SOCKET_KEY in plan.writes and facts.socket_active
                               and directive_changes(facts.socket_unit, plan.writes[SOCKET_KEY], limit=1))
    running = facts.party_state == 'active'
    if not running:
        plan.why = (f'it is not running ({facts.party_state}), and this command does not start it; it takes the socket '
                    'and the registry when it next starts')
    elif plan.restart_socket:
        plan.restart = True
        plan.why = 'the socket unit changes, and Party Core has to take the new socket'
    elif facts.holds:
        plan.why = 'it already holds the socket'
        plan.reload = CONFIG_KEY in plan.writes
    else:
        plan.restart = True
        plan.why = ('it is running and does not hold the socket: it started before the socket unit was listening, '
                    'and a process is handed a socket only when it starts')
    return plan


def directive_changes(old, new, limit=10):
    """The directive lines the installed unit has and the new one lacks (`-`) and the reverse (`+`)."""
    def lines(data):
        text = (data or b'').decode('utf-8', 'replace')
        return [s for s in (line.strip() for line in text.splitlines()) if s and not s.startswith(('#', ';'))]
    before, after = lines(old), lines(new)
    changes = [f'- {s}' for s in before if s not in after] + [f'+ {s}' for s in after if s not in before]
    if len(changes) > limit:
        changes = changes[:limit] + [f'... and {len(changes) - limit} more']
    return changes


def party_sentence(party):
    if not party.running:
        return 'Nothing answers on loopback, so there is no party and no session.'
    people = ('Nobody is in the party' if not party.members else
              f'{party.members} member{"s" if party.members != 1 else ""} {"is" if party.members == 1 else "are"} '
              'in the party and will have to join again')
    return f'No game session is running. {people}.'


def plan_lines(plan, party, backup_dir, reuse=False):
    out = []
    if plan.restart:
        out.append(f'Party Core: will be restarted (a restart ends the party): {plan.why}. {party_sentence(party)}')
    else:
        out.append(f'Party Core: will not be restarted: {plan.why}.')
        if (UNIT_KEY in plan.writes) and plan.facts.party_state == 'active':
            out.append('  (the running Party Core keeps the unit it started with until its next restart)')
    facts = plan.facts
    for key in (UNIT_KEY, SOCKET_KEY):
        if key in plan.writes:
            old = facts.unit if key == UNIT_KEY else facts.socket_unit
            out.append(f'  {"replace" if old is not None else "install"} {TARGETS[key]}' + ('' if old is not None else ' (new)'))
            if old is not None:
                out += [f'      {line}' for line in directive_changes(old, plan.writes[key])]
    if CONFIG_KEY in plan.writes:
        was = 'absent' if plan.registry_before is ABSENT else json.dumps(plan.registry_before)
        out.append(f'  edit {CONFIG}: "registry" {was} -> {json.dumps(REGISTRY_DIR)}; every other byte stays as it is')
    if plan.daemon_reload:
        out.append('  run systemctl daemon-reload')
    if plan.restart:                    # in the order they run: see `apply` for why Party Core is stopped first
        out.append(f'  run systemctl stop {SERVICE}')
    if plan.restart_socket:
        out.append(f'  run systemctl restart {SOCKET}')
    if plan.enable_socket:
        out.append(f'  run systemctl enable --now {SOCKET}')
    if plan.restart:
        out.append(f'  run systemctl start {SERVICE}')
    elif plan.reload:
        out.append(f'  run systemctl reload {SERVICE}')
    if plan.backup:
        out.append(f'  add to the before-state an earlier run kept in {backup_dir}' if reuse
                   else f'  keep the before-state in {backup_dir}')
    return out


# ---- asking Party Core whether a session is running -------------------------------------------------

def _direct_open(target, timeout):
    """Party Core is asked on loopback, never through a proxy named in the environment: a dead proxy
    refuses the connection, and that would read as 'no Party Core'."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(target, timeout=timeout)


def ask_party(url, host, opener=_direct_open, timeout=pg.QUERY_TIMEOUT_S):
    """Party(running, game, members) from GET /party/api/status; Refused when Party Core is there and
    this cannot tell (as provision-game: only 'nobody is listening' is an answer of 'no party')."""
    target = url.rstrip('/') + pg.STATUS_PATH
    if host:
        target = urllib.request.Request(target, headers={'Host': host})
    try:
        with opener(target, timeout=timeout) as response:
            doc = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        raise Refused(f'Party Core answered HTTP {e.code}; not restarting it') from None
    except ConnectionRefusedError:
        return Party(False, None, None)
    except urllib.error.URLError as e:
        if isinstance(e.reason, ConnectionRefusedError):
            return Party(False, None, None)
        if isinstance(e.reason, (TimeoutError, socket.timeout)):
            raise Refused('Party Core did not answer in time; not restarting it') from None
        raise Refused(f'Party Core could not be asked ({type(e.reason).__name__}); not restarting it') from None
    except (TimeoutError, socket.timeout):
        raise Refused('Party Core did not answer in time; not restarting it') from None
    except (OSError, http.client.HTTPException) as e:
        raise Refused(f'Party Core could not be asked ({type(e).__name__}); not restarting it') from None
    except ValueError:
        raise Refused('Party Core answered something that is not JSON; not restarting it') from None
    core = doc.get('party_core') if isinstance(doc, dict) else None
    if not isinstance(core, dict) or core.get('ok') is not True or 'session' not in core:
        raise Refused('Party Core did not report its session; not restarting it')
    session, count = core['session'], core.get('members')
    if isinstance(count, bool) or not isinstance(count, int):
        count = None
    if session is None:
        return Party(True, None, count)
    if not isinstance(session, dict) or not isinstance(session.get('game'), str):
        raise Refused('Party Core reported a session this tool cannot read; not restarting it')
    return Party(True, None if session.get('state') == 'ended' else session['game'], count)


def party_before_restart(url, host, opener, settle, sleep):
    """Who is on Party Core, asked twice a status-cache apart (a session launched a moment ago is not
    in a cached answer) when `settle`; Refused while a game session is running."""
    party = ask_party(url, host, opener)
    if party.running and party.game is None and settle:
        sleep(settle)
        party = ask_party(url, host, opener)
    if party.game is not None:
        raise Refused(f'a game session is running ({party.game}) and Party Core would have to restart, which ends it; '
                      'wait until the party is back at Party Home, then run this again')
    return party


def wait_until_answering(url, host, opener, sleep, clock, limit=ANSWER_WAIT_S):
    deadline = clock() + limit
    while True:
        try:
            if ask_party(url, host, opener, timeout=5).running:
                return True
        except Refused:
            pass
        if clock() >= deadline:
            return False
        sleep(1)


# ---- changing files -----------------------------------------------------------------------------------

def write_file(path, data, mode, owner=None):
    """Write `data` to `path` atomically: a temporary name beside it, then a rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'.{path.name}.{secrets.token_hex(4)}')
    try:
        with open(tmp, 'xb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        if owner is not None and hasattr(os, 'chown'):
            os.chown(tmp, *owner)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _meta(path):
    st = path.stat()
    return {'mode': format(stat.S_IMODE(st.st_mode), '04o'), 'uid': getattr(st, 'st_uid', 0), 'gid': getattr(st, 'st_gid', 0)}


def new_backup_dir(root, when):
    base = Path(root) / f'{BACKUP_PREFIX}{when:%Y%m%dT%H%M%SZ}'
    candidate, n = base, 1
    while candidate.exists():
        n += 1
        candidate = base.with_name(f'{base.name}-{n}')
    return candidate


def backups(root):
    """The before-states under `root`, oldest first: [(directory, state)]."""
    found = []
    for directory in sorted(Path(root).glob(BACKUP_PREFIX + '*')):
        try:
            state = json.loads((directory / STATE_FILE).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(state, dict) and state.get('schema') == SCHEMA:
            found.append((directory, state))
    return found


def active_backup(root):
    """The newest before-state that has not been reversed, or None. A prepared host has one: runs
    after the first add to it (what they replace is kept only if no earlier run kept it), so a
    reverse always goes back to how the host was before this command first changed it."""
    for directory, state in reversed(backups(root)):
        if not state.get('reversed'):
            return directory
    return None


def save_state(directory, state):
    write_file(directory / STATE_FILE, (json.dumps(state, indent=2, sort_keys=True) + '\n').encode('utf-8'), 0o600)


def keep_before_state(host, plan, directory, when):
    """Copy what the run will replace into `directory` and say, in state.json, what each was. In a
    directory an earlier run made, only what that run did not keep is added: the first copy of a
    file is the one a reverse puts back."""
    paths = host.targets()
    if (directory / STATE_FILE).is_file():
        state = load_state(directory)
    else:
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0o750)
        state = {'schema': SCHEMA, 'created': f'{when:%Y-%m-%dT%H:%M:%SZ}', 'files': {},
                 'socket': {'enabled': plan.facts.socket_enabled, 'active': plan.facts.socket_active},
                 'party_core': {'state': plan.facts.party_state, 'restarted': False}}
    for key in WRITE_ORDER:
        if key not in plan.writes or key in state['files']:
            continue
        path = paths[key]
        entry = {'existed': path.is_file()}
        if entry['existed']:
            entry.update(_meta(path))
            write_file(directory / key, path.read_bytes(), UNIT_MODE)
        state['files'][key] = entry
    save_state(directory, state)
    return state


# ---- checking what was done -----------------------------------------------------------------------------

def socket_problems(st, owner, group):
    """What is wrong with the internal socket's node, from its stat result and the names of its
    owner and group (ADR 0016 section 4: avrana-party:avrana-games 0660)."""
    problems = []
    if not stat.S_ISSOCK(st.st_mode):
        problems.append('it is not a socket')
    if stat.S_IMODE(st.st_mode) != SOCKET_MODE:
        problems.append(f'its mode is {stat.S_IMODE(st.st_mode):04o}, not {SOCKET_MODE:04o}')
    if owner != SOCKET_OWNER:
        problems.append(f'its owner is {owner}, not {SOCKET_OWNER}')
    if group != SOCKET_GROUP:
        problems.append(f'its group is {group}, not {SOCKET_GROUP}')
    return problems


def _names(st):
    try:
        import grp
        import pwd
        return pwd.getpwuid(st.st_uid).pw_name, grp.getgrgid(st.st_gid).gr_name
    except (ImportError, KeyError):
        return str(st.st_uid), str(st.st_gid)


def verify(host, sysctl, sources, *, restarted, answering=None):
    """The checks after a run (read-only): [Check(ok, text)]."""
    paths = host.targets()
    checks = []

    def add(ok, text):
        checks.append(Check(bool(ok), text))
    add(paths[UNIT_KEY].is_file() and paths[UNIT_KEY].read_bytes() == sources[SERVICE],
        f'{TARGETS[UNIT_KEY]} is the repository unit')
    add(show(sysctl, SERVICE, 'ExecReload'), f'systemd has {SERVICE} loaded with ExecReload= (systemctl reload works)')
    add(paths[SOCKET_KEY].is_file() and paths[SOCKET_KEY].read_bytes() == sources[SOCKET],
        f'{TARGETS[SOCKET_KEY]} is the repository unit')
    add(is_enabled(sysctl, SOCKET) and unit_state(sysctl, SOCKET) == 'active', f'{SOCKET} is enabled and listening')
    add(not any(show(sysctl, u, 'NeedDaemonReload') == 'yes' for u in (SERVICE, SOCKET)),
        'systemd has loaded the unit files that are on disk')
    node = host.path(INTERNAL_SOCKET)
    if not os.path.lexists(node):
        add(False, f'{INTERNAL_SOCKET} exists')
    elif host.simulated:
        add(True, f'{INTERNAL_SOCKET} exists')
    else:
        st = node.stat()
        problems = socket_problems(st, *_names(st))
        add(not problems, f'{INTERNAL_SOCKET} is {SOCKET_OWNER}:{SOCKET_GROUP} {SOCKET_MODE:04o}'
                          + (f' ({"; ".join(problems)})' if problems else ''))
    try:
        configured = json.loads(paths[CONFIG_KEY].read_text(encoding='utf-8')).get('registry')
    except (OSError, ValueError, AttributeError):
        configured = None
    add(configured == REGISTRY_DIR, f'{CONFIG} has "registry": {json.dumps(REGISTRY_DIR)}')
    state = unit_state(sysctl, SERVICE)
    if state != 'active':
        add(True, f'Party Core is not running ({state}); it takes the socket and the registry when it next starts'
                  + (' (it is failed: read journalctl -u avrana-party-core -n 50)' if state == 'failed' else ''))
    else:
        add(holds_socket(sysctl), 'Party Core holds the socket')
        if restarted:
            add(answering, 'Party Core answers on loopback after the restart'
                           + ('' if answering else ' (read: journalctl -u avrana-party-core -n 50)'))
    return checks


# ---- the two operations -------------------------------------------------------------------------------------

@contextlib.contextmanager
def shielded():
    """Hold off the signals that end a run (a dropped SSH session, Ctrl-C, SIGTERM) while Party Core is
    stopped and not yet started: a run killed there would leave the party's front stopped. `systemctl`
    inherits the same disposition, so the commands inside are not interrupted either. The handlers are
    put back afterwards. Where a signal cannot be held off (not the main thread, or this platform has no
    such signal) it is left alone."""
    held = []
    for name in ('SIGHUP', 'SIGINT', 'SIGTERM'):
        number = getattr(signal, name, None)
        if number is None:
            continue
        try:
            held.append((number, signal.signal(number, signal.SIG_IGN)))
        except (ValueError, OSError):
            continue
    try:
        yield
    finally:
        for number, handler in held:
            try:
                signal.signal(number, handler if handler is not None else signal.SIG_DFL)
            except (ValueError, OSError):
                pass


def apply(host, plan, sysctl, directory, when, progress):
    """Do the plan. Returns the state kept for --reverse (None when nothing was kept)."""
    paths = host.targets()
    state = None
    if plan.backup:
        state = keep_before_state(host, plan, directory, when)
        progress.changed = True
    for key in WRITE_ORDER:
        if key not in plan.writes:
            continue
        progress.changed = True
        owner = None
        mode = UNIT_MODE
        if key == CONFIG_KEY:                                  # the file keeps its mode and its owner
            mode = stat.S_IMODE(plan.facts.config_stat.st_mode)
            owner = (plan.facts.config_stat.st_uid, plan.facts.config_stat.st_gid) if hasattr(plan.facts.config_stat, 'st_uid') else None
        write_file(paths[key], plan.writes[key], mode, owner)
        if state is not None:
            state['files'][key]['wrote'] = _digest(plan.writes[key])
    if state is not None:
        save_state(directory, state)
    if plan.daemon_reload:
        progress.changed = True
        must(sysctl, 'daemon-reload')
    # systemd refuses to start or restart a socket unit while the service it triggers is running
    # ("Socket service ... already active, refusing"), and a service is handed its socket only when
    # it starts. So a Party Core that has to take the socket is stopped first, the socket is made
    # ready, and Party Core is started last: never `systemctl restart` of the service.
    if plan.restart:
        progress.changed = True
        with shielded():
            try:
                must(sysctl, 'stop', SERVICE)
                if state is not None:
                    state['party_core']['restarted'] = True
                    save_state(directory, state)
                make_socket_ready(plan, sysctl)
                must(sysctl, 'start', SERVICE)
            except (Incomplete, OSError) as e:                   # never leave Party Core stopped
                raise Incomplete(f'{e}; {bring_back(sysctl)}') from None
        return state
    make_socket_ready(plan, sysctl, progress)
    if plan.reload:
        progress.changed = True
        must(sysctl, 'reload', SERVICE)
    return state


def make_socket_ready(plan, sysctl, progress=None):
    """The socket unit restarted when its directives changed, then enabled and listening."""
    if plan.restart_socket:
        if progress:
            progress.changed = True
        must(sysctl, 'restart', SOCKET)
    if plan.enable_socket:
        if progress:
            progress.changed = True
        must(sysctl, 'enable', '--now', SOCKET)


def bring_back(sysctl):
    """After a failure with Party Core stopped by this command: start it again, and say where it is."""
    if unit_state(sysctl, SERVICE) == 'active':
        return 'Party Core is running'
    if sysctl(['start', SERVICE]).rc == 0:
        return 'Party Core was started again (it may not hold the socket: run this again)'
    return ('Party Core is STOPPED and could not be started again: read journalctl -u avrana-party-core -n 50, '
            'then systemctl start avrana-party-core')


def provisioned_games(host):
    """The native games provisioned here: a registry entry, or an avrana-game@<slug> unit, drop-in
    directory or enabled link. The two shared templates (avrana-game@.socket and .service) are not games."""
    found = set()
    registry = host.path(REGISTRY_DIR)
    if registry.is_dir():
        found.update(p.stem for p in registry.iterdir() if p.suffix == '.json' and not p.name.startswith('.'))
    pattern = re.compile(r'avrana-game@([a-z][a-z0-9_-]*)\.(?:socket|service)(?:\.d)?')
    unit_dir = host.path(UNIT_DIR)
    for directory in (unit_dir, unit_dir / 'sockets.target.wants'):
        if directory.is_dir():
            for p in directory.iterdir():
                m = pattern.fullmatch(p.name)
                if m:
                    found.add(m.group(1))
    return sorted(found)


@dataclass
class Reversal:
    state: dict
    directory: Path
    restores: dict = field(default_factory=dict)        # key -> bytes of the kept copy
    removals: list = field(default_factory=list)        # keys of files that did not exist before
    replaced: list = field(default_factory=list)        # keys of files the reverse overwrites or removes
    edited: list = field(default_factory=list)          # of those, the ones changed since this command wrote them
    disable_socket: bool = False
    remove_node: bool = False
    daemon_reload: bool = False
    recover_party: bool = False                         # Party Core is `failed`: start it again
    party_state: str = ''

    @property
    def empty(self):
        return not (self.restores or self.removals or self.disable_socket or self.remove_node
                    or self.daemon_reload or self.recover_party)


def find_backup(root, given):
    """(directory, reversed_at) of the before-state to go back to: `given`, or the one in force. With
    none given and every before-state already reversed: the newest, and when it was reversed."""
    if given != LATEST:
        return Path(given), None
    active = active_backup(root)
    if active is not None:
        return active, None
    older = backups(root)
    if not older:
        raise Refused(f'there is no before-state written by this command under {root}; name its directory: '
                      '--reverse DIR')
    return older[-1][0], older[-1][1].get('reversed')


def load_state(directory):
    try:
        state = json.loads((directory / STATE_FILE).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        state = None
    if (not isinstance(state, dict) or state.get('schema') != SCHEMA or not isinstance(state.get('files'), dict)
            or set(state['files']) - set(TARGETS)):
        raise Refused(f'{directory} is not a before-state written by this command')
    return state


def plan_reverse(host, directory, sysctl):
    state = load_state(directory)
    games = provisioned_games(host)
    if games:
        raise Refused(f'native games are provisioned here ({", ".join(games)}); a reverse would take away what they '
                      'need. Remove each first: provision-game <slug> --remove')
    paths = host.targets()
    plan = Reversal(state, directory)
    for key, entry in sorted(state['files'].items()):
        current = read_optional(paths[key], TARGETS[key])
        if entry.get('existed'):
            try:
                kept = (directory / key).read_bytes()
            except OSError:
                raise Refused(f'{directory / key} is missing: this before-state is incomplete') from None
            if current != kept:
                plan.restores[key] = kept
        elif current is not None:
            plan.removals.append(key)
        if (key in plan.restores or key in plan.removals) and current is not None:
            plan.replaced.append(key)
            if entry.get('wrote') and entry['wrote'] != _digest(current):
                plan.edited.append(key)
    was_enabled = bool((state.get('socket') or {}).get('enabled'))
    if not was_enabled and (is_enabled(sysctl, SOCKET) or unit_state(sysctl, SOCKET) == 'active'):
        plan.disable_socket = True
    plan.remove_node = not was_enabled and os.path.lexists(host.path(INTERNAL_SOCKET))
    plan.party_state = unit_state(sysctl, SERVICE)
    plan.recover_party = plan.party_state == 'failed'
    plan.daemon_reload = bool(plan.restores or plan.removals or plan.disable_socket) \
        or any(show(sysctl, u, 'NeedDaemonReload') == 'yes' for u in (SERVICE, SOCKET))
    return plan


def reverse_lines(plan):
    out = ['Party Core: will not be restarted by a reverse; it keeps running as it is until its next restart'
           + (' (it is failed: it will be started again)' if plan.recover_party else '') + '.']
    if plan.disable_socket:
        out.append(f'  run systemctl disable --now {SOCKET}')
    for key in sorted(plan.restores):
        out.append(f'  restore {TARGETS[key]} from {plan.directory / key}')
    for key in sorted(plan.removals):
        out.append(f'  remove {TARGETS[key]} (it did not exist before the run)')
    for key in plan.replaced:
        out.append(f'  keep the file it replaces in {plan.directory / REPLACED / key}')
    for key in plan.edited:
        out.append(f'  NOTE: {TARGETS[key]} was changed after this command wrote it; those changes are in the kept '
                   'copy above, and are not in the file that comes back')
    if plan.remove_node:
        out.append(f'  remove {INTERNAL_SOCKET} (the socket node systemd leaves behind)')
    if plan.daemon_reload:
        out.append('  run systemctl daemon-reload')
    if plan.recover_party:
        out.append(f'  run systemctl reset-failed {SERVICE}, then systemctl start {SERVICE}')
    return out


def apply_reverse(host, plan, sysctl, progress):
    paths = host.targets()
    if plan.disable_socket:
        progress.changed = True
        must(sysctl, 'disable', '--now', SOCKET)                 # while its unit file is still there
    for key in plan.replaced:                                    # what a reverse overwrites is never lost
        path = paths[key]
        if path.is_file():
            write_file(plan.directory / REPLACED / key, path.read_bytes(), UNIT_MODE)
    for key, data in sorted(plan.restores.items()):
        entry = plan.state['files'][key]
        progress.changed = True
        try:
            mode = int(entry.get('mode', '0644'), 8)
        except (TypeError, ValueError):
            mode = UNIT_MODE
        owner = (entry['uid'], entry['gid']) if isinstance(entry.get('uid'), int) and isinstance(entry.get('gid'), int) else None
        write_file(paths[key], data, mode, owner)
    for key in plan.removals:
        progress.changed = True
        paths[key].unlink()
    if plan.remove_node:
        progress.changed = True
        try:
            host.path(INTERNAL_SOCKET).unlink()
        except FileNotFoundError:
            pass
        try:
            host.path(INTERNAL_SOCKET).parent.rmdir()               # only when nothing else is in it
        except OSError:
            pass
    if plan.daemon_reload:
        progress.changed = True
        must(sysctl, 'daemon-reload')
    if plan.recover_party:
        progress.changed = True
        sysctl(['reset-failed', SERVICE])
        must(sysctl, 'start', SERVICE)


def verify_reverse(host, plan, sysctl):
    paths = host.targets()
    checks = []
    for key, data in sorted(plan.restores.items()):
        checks.append(Check(paths[key].is_file() and paths[key].read_bytes() == data, f'{TARGETS[key]} is the earlier file'))
    for key in sorted(plan.removals):
        checks.append(Check(not paths[key].exists(), f'{TARGETS[key]} is gone'))
    if plan.disable_socket:
        checks.append(Check(not is_enabled(sysctl, SOCKET) and unit_state(sysctl, SOCKET) != 'active',
                            f'{SOCKET} is disabled and stopped'))
    if plan.remove_node:
        checks.append(Check(not os.path.lexists(host.path(INTERNAL_SOCKET)), f'{INTERNAL_SOCKET} is gone'))
    return checks


# ---- identities -----------------------------------------------------------------------------------------------

def os_identities():
    """What of the ADR 0016 phase 1 identities this machine lacks (provision-game's own test)."""
    try:
        import grp
        import pwd
    except ImportError:
        raise Refused('this command changes a Linux appliance; ADR 0016 phase 1 has not been applied on this host') from None
    missing = []
    try:
        pwd.getpwnam(USER)
    except KeyError:
        missing.append(f'user {USER}')
    for name in GROUPS:
        try:
            grp.getgrnam(name)
        except KeyError:
            missing.append(f'group {name}')
    return missing


def file_identities(host):
    """The same question of a simulated host: its etc/passwd and etc/group."""
    def names(logical):
        try:
            lines = host.path(logical).read_text(encoding='utf-8').splitlines()
        except OSError:
            return set()
        return {line.split(':', 1)[0] for line in lines if line and not line.startswith('#')}
    users, groups = names('/etc/passwd'), names('/etc/group')
    return ([f'user {USER}'] if USER not in users else []) + [f'group {g}' for g in GROUPS if g not in groups]


# ---- the command line -------------------------------------------------------------------------------------------

class _Usage(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _Usage(message)


def _parser():
    ap = _Parser(prog='prepare-native-games', allow_abbrev=False,
                 description='Prepare this appliance for native games: Party Core\'s unit and socket, and the '
                             'registry key. Run as root; see docs/runbooks/prepare-native-games.md.')
    ap.add_argument('--dry-run', action='store_true', help='print what would change, and whether Party Core would '
                                                          'restart; change nothing')
    ap.add_argument('--reverse', nargs='?', const=LATEST, default=None, metavar='BACKUP_DIR',
                    help='put the before-state of an earlier run back (the newest, or BACKUP_DIR); refused while a '
                         'native game is provisioned')
    ap.add_argument('--root', metavar='DIR', help='work on a SIMULATED host under DIR (default: AVRANA_ROOT); needs '
                                                  'AVRANA_SYSTEMCTL to name a stand-in for systemctl')
    ap.add_argument('--party-url', help=f'Party Core on loopback (default AVRANA_PARTY_CORE_URL, else {pg.DEFAULT_PARTY_URL})')
    ap.add_argument('--source-dir', help=argparse.SUPPRESS)
    return ap


def _run(a, *, environ, sysctl, opener, when, sleep, clock, identities, is_root, out, progress):
    def say(line=''):
        print(line, file=out, flush=True)

    root = a.root or environ.get('AVRANA_ROOT') or None
    host = Host(Path(root) if root else None, Path(a.source_dir) if a.source_dir else REPO_ROOT / 'deploy' / 'party-core')
    if not host.simulated:
        if is_root is None:
            is_root = hasattr(os, 'geteuid') and os.geteuid() == 0
        if not is_root and not a.dry_run:
            raise Refused('run as root (sudo), or with --dry-run')
        if os.name != 'posix':
            raise Refused('this command changes a Linux appliance; use --root DIR to rehearse on a scratch directory')
    if sysctl is None:
        command = environ.get('AVRANA_SYSTEMCTL') or None
        if host.simulated and not command:
            raise Refused('with --root, AVRANA_SYSTEMCTL must name a stand-in for systemctl: a simulated host never '
                          'talks to the real systemd')
        sysctl = real_systemctl(command)
    backups_dir = Path(environ.get('AVRANA_BACKUP_ROOT') or host.path(BACKUP_ROOT))
    party_url = a.party_url or environ.get('AVRANA_PARTY_CORE_URL') or pg.DEFAULT_PARTY_URL
    where = f'a simulated host under {host.root}' if host.simulated else 'this host'

    if a.reverse is not None:
        directory, already = find_backup(backups_dir, a.reverse)
        if already:
            say(f'prepare-native-games: nothing to reverse; the newest before-state, {directory}, was reversed at {already}')
            return 0
        plan = plan_reverse(host, directory, sysctl)
        say(f'prepare-native-games: reverse of {directory} on {where}'
            + (' (dry run: nothing will be changed)' if a.dry_run else ''))
        if plan.empty:
            say('prepare-native-games: nothing to change; the host is already as that before-state left it')
        else:
            for line in reverse_lines(plan):
                say(line)
        if a.dry_run:
            say('dry run: nothing changed')
            return 0
        if not plan.empty:
            apply_reverse(host, plan, sysctl, progress)
            checks = verify_reverse(host, plan, sysctl)
            for c in checks:
                say(f'  {"ok  " if c.ok else "FAIL"} {c.text}')
            if not all(c.ok for c in checks):
                raise Incomplete('a check after the reverse failed (above); the before-state is still in ' + str(directory))
        plan.state['reversed'] = f'{when:%Y-%m-%dT%H:%M:%SZ}'
        save_state(directory, plan.state)
        if not plan.empty:
            say('prepare-native-games: reversed. The earlier files are back and Party Core was not restarted: '
                'it keeps the unit it is running with until its next restart.')
        return 0

    missing = (identities or (lambda: file_identities(host) if host.simulated else os_identities()))()
    if missing:
        raise Refused('ADR 0016 phase 1 has not been applied on this host (missing: ' + ', '.join(missing) + '); run '
                      'ops/migrate-service-users.sh first (docs/runbooks/service-users-migration.md)')
    sources = read_sources(host, trusted=not host.simulated)
    facts = read_facts(host, sysctl)
    plan = make_plan(facts, sources)
    party = Party(False, None, None)
    if plan.restart:
        header = pg.party_host(str(host.path(CONFIG)))
        party = party_before_restart(party_url, header, opener or _direct_open,
                                     0.0 if a.dry_run else pg.STATUS_SETTLE_S, sleep)
    directory = active_backup(backups_dir)
    reuse = directory is not None
    directory = directory or new_backup_dir(backups_dir, when)
    say(f'prepare-native-games: plan for {where}' + (' (dry run: nothing will be changed)' if a.dry_run else ''))
    if plan.empty:
        say('Party Core: will not be restarted: ' + plan.why + '.')
    else:
        for line in plan_lines(plan, party, directory, reuse):
            say(line)
    if a.dry_run:
        say('dry run: nothing changed' if not plan.empty else 'prepare-native-games: nothing to change')
        return 0
    state = None
    if not plan.empty:
        try:
            state = apply(host, plan, sysctl, directory, when, progress)
        except Incomplete as e:
            how = (f'; to go back: sudo ops/prepare-native-games --reverse {directory}' if progress.changed and plan.backup
                   else '')
            raise Incomplete(f'{e}{how}; or run this again to finish') from None
    answering = None
    if plan.restart:
        answering = wait_until_answering(party_url, pg.party_host(str(host.path(CONFIG))), opener or _direct_open,
                                         sleep, clock)
    checks = verify(host, sysctl, sources, restarted=plan.restart, answering=answering)
    if not plan.empty:
        say('checks:')
    for c in checks:
        if not plan.empty or not c.ok:
            say(f'  {"ok  " if c.ok else "FAIL"} {c.text}')
    how_back = f'sudo ops/prepare-native-games --reverse {directory}' if state is not None else None
    if not all(c.ok for c in checks):
        raise Incomplete('a check failed (above)' + (f'; to go back: {how_back}' if how_back else '') +
                         '; run this again to finish')
    if plan.empty:
        say('prepare-native-games: nothing to change; the host is ready for provision-game')
    else:
        say('prepare-native-games: done; the host is ready for provision-game (docs/runbooks/prepare-native-games.md '
            'says what to check)')
        if how_back:
            say(f'Reverse, if a check fails: {how_back}')
    return 0


def main(argv=None, *, environ=None, sysctl=None, opener=None, now=None, sleep=time.sleep, clock=time.monotonic,
         identities=None, is_root=None, out=None, err=None):
    """Exit 0 done, 1 refused or failed before a change, 2 usage, 3 changed and then failed. Every
    effect can be injected: `sysctl` (a call taking an argv tail and giving a Result), `opener`
    (Party Core's status), `now`, `sleep`, `clock`, `identities` (what phase 1 lacks), `is_root`."""
    out, err = out or sys.stdout, err or sys.stderr
    environ = os.environ if environ is None else environ
    try:
        with contextlib.redirect_stdout(out):                  # --help prints where `out` goes
            a = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    except _Usage as e:
        print(f'prepare-native-games: {e}', file=err)
        return 2
    except SystemExit as e:                                    # --help
        return int(e.code or 0)
    progress = Progress()
    when = (now() if now else datetime.now(timezone.utc))
    try:
        return _run(a, environ=environ, sysctl=sysctl, opener=opener, when=when, sleep=sleep, clock=clock,
                    identities=identities, is_root=is_root, out=out, progress=progress)
    except Refused as e:
        print(f'prepare-native-games: refused: {e}' + ('' if progress.changed else ' (nothing was changed)'), file=err)
        return 3 if progress.changed else 1
    except Incomplete as e:
        print(f'prepare-native-games: NOT complete: {e}', file=err)
        return 3 if progress.changed else 1
    except PermissionError as e:
        print('prepare-native-games: failed: ' + ('needs root (run it with sudo)' if not progress.changed
                                                   else f'{type(e).__name__}: {e}'), file=err)
        return 3 if progress.changed else 1
    except (OSError, ValueError) as e:
        print(f'prepare-native-games: failed: {type(e).__name__}: {e}'
              + ('; the host was changed: run this again to finish, or reverse' if progress.changed else ''), file=err)
        return 3 if progress.changed else 1


if __name__ == '__main__':
    sys.exit(main())
