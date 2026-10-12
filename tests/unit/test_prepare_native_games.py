"""ops/prepare-native-games (ADR 0016 sections 4, 8 and 9; AVR-304) on a scratch root, with a
recording stand-in for systemctl. Real systemd (the units, socket activation, the handed-over
socket) is the Linux CI job's: experiments/native-game/prepare-proof.sh.

The simulated host is a directory: `etc/passwd` and `etc/group` say which identities exist, the unit
files and party-core.json are real files under it, and `FakeSystemd` keeps the little state the
command asks systemd about (enabled, active, what was loaded at the last daemon-reload, when each unit
last became active). It records every call, so a test can say what was run, in what order, and that a
second run runs nothing that changes anything. Nothing here needs root, Linux or systemd."""
import io
import json
import os
import random
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import types
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from avrana import REPO_ROOT
from avrana.ops import prepare_native_games as pn
from avrana.ops import provision_game as pg

SOURCE = REPO_ROOT / 'deploy' / 'party-core'
UNIT = (SOURCE / pn.SERVICE).read_bytes()
SOCKET_UNIT = (SOURCE / pn.SOCKET).read_bytes()
NOW = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)
STAMP = 'native-games-20261007T120000Z'
READ_ONLY = {'is-active', 'is-enabled', 'show'}
REGISTRY = '/etc/avrana-party/games.d'
POSIX = os.name == 'posix'
MAX_CALLS = 2000                 # systemctl calls in one test: a command asks a few dozen; more is a loop
MAX_EVENTS = 20000               # entries in the shared event log (what was said, asked and run)
MAX_ENTRIES, MAX_BYTES = 400, 1 << 20       # a simulated host is a handful of small files
UNIT_PATH = 'etc/systemd/system/' + pn.SERVICE
SOCKET_PATH = 'etc/systemd/system/' + pn.SOCKET
CONFIG_PATH = 'etc/avrana-party/party-core.json'


def earlier_unit():
    """Party Core's unit as a phase 1 host has it: the repository's from before ExecReload= and the
    socket unit (the service-users migration installed that one): no ExecReload=, and no Wants= or
    After= the socket unit."""
    text = UNIT.decode('utf-8')
    kept = [line for line in text.splitlines(keepends=True)
            if not line.startswith('ExecReload=') and line.strip() != f'Wants={pn.SOCKET}']
    return ''.join(kept).replace(f'After=network.target {pn.SOCKET}', 'After=network.target').encode('utf-8')


EARLIER_UNIT = earlier_unit()
EARLIER_CONFIG = (SOURCE / 'party-core.example.json').read_bytes()       # exactly one bare origin
PASSWD = 'root:x:0:0:root:/root:/bin/bash\navrana-party:x:998:998::/nonexistent:/usr/sbin/nologin\n'
GROUP = 'root:x:0:\navrana-party:x:998:\navrana-front:x:997:avrana-party,www-data\navrana-games:x:996:\n'


class FakeSystemd:
    """The part of systemd this command talks to, on a scratch root. A call is recorded as its
    argument list (without `systemctl`); `fail[(verb, unit)]` or `fail[(verb, None)]` makes that call
    fail with the given status; `states[unit]` makes `is-active` say that word (activating...).

    It keeps the one rule of real systemd that a careless sequence breaks: a socket unit cannot be
    started or restarted while the service it triggers is running ("Socket service ... already
    active, refusing"). A service is handed its socket only as it starts, which is what `entered` is
    for: the command compares when Party Core became active with when the socket did."""

    def __init__(self, root, events, party='active'):
        self.root, self.events, self.calls = Path(root), events, []
        self.hook = None                                          # called with the argument list before each call
        self.clock = 1000
        self.enabled, self.active, self.failed = set(), set(), set()
        self.entered = {}
        self.fail, self.states = {}, {}
        self.refusals = []                                        # socket units systemd refused to start
        self.loaded = {}
        self.daemon_reload()
        if party == 'active':
            self.start(pn.SERVICE)
        elif party == 'failed':
            self.failed.add(pn.SERVICE)

    def tick(self):
        self.clock += 10
        return self.clock

    def disk(self, unit):
        path = self.root / 'etc/systemd/system' / unit
        return path.read_bytes() if path.is_file() else None

    def daemon_reload(self):
        self.loaded = {unit: self.disk(unit) for unit in (pn.SERVICE, pn.SOCKET)}

    def start(self, unit):
        """The unit became active (also what a test does to say 'it started later')."""
        self.active.add(unit)
        self.failed.discard(unit)
        self.entered[unit] = self.tick()
        if unit == pn.SOCKET:
            self.node().parent.mkdir(parents=True, exist_ok=True)
            self.node().write_text('socket\n')

    def job(self, verb, unit):
        """`systemctl start|restart <unit>`."""
        if self.loaded.get(unit) is None:
            return pn.Result(5, '', f'Unit {unit} not found.')
        if verb == 'start' and unit in self.active:
            return pn.Result(0, '', '')                           # already active: nothing to do
        if unit == pn.SOCKET and pn.SERVICE in self.active:
            self.refusals.append(unit)
            return pn.Result(1, '', f'Socket service {pn.SERVICE} already active, refusing.')
        self.start(unit)
        return pn.Result(0, '', '')

    def node(self):
        return self.root / 'run/avrana-party/internal.sock'

    def wants(self, unit):
        return self.root / 'etc/systemd/system/sockets.target.wants' / unit

    def has_exec_reload(self, unit):
        return bool(re.search(r'(?m)^ExecReload=', (self.loaded.get(unit) or b'').decode('utf-8')))

    def __call__(self, args):
        if len(self.calls) >= MAX_CALLS:
            raise AssertionError(f'systemctl was called {MAX_CALLS} times: a loop, not a command')
        self.calls.append(list(args))
        self.events.append(('systemctl', list(args)))
        if self.hook is not None:
            self.hook(list(args))
        verb, rest = args[0], args[1:]
        unit = rest[-1] if rest else None
        for key in ((verb, unit), (verb, None)):
            if key in self.fail:
                return pn.Result(self.fail[key], '', f'{verb} failed')
        ok = pn.Result(0, '', '')
        if verb == 'is-active':
            state = self.states.get(unit) or ('active' if unit in self.active else ('failed' if unit in self.failed else 'inactive'))
            return pn.Result(0 if state == 'active' else 3, state + '\n', '')
        if verb == 'is-enabled':
            on = unit in self.enabled
            return pn.Result(0 if on else 1, ('enabled' if on else 'disabled') + '\n', '')
        if verb == 'show':
            prop = rest[rest.index('-p') + 1]
            if prop == 'ActiveEnterTimestampMonotonic':
                return pn.Result(0, f'{self.entered.get(unit, 0)}\n', '')
            if prop == 'NeedDaemonReload':
                return pn.Result(0, ('yes' if self.disk(unit) != self.loaded.get(unit) else 'no') + '\n', '')
            if prop == 'ExecReload':
                text = '{ path=/bin/kill ; argv[]=/bin/kill -HUP $MAINPID ; ignore_errors=no }'
                return pn.Result(0, (text if self.has_exec_reload(unit) else '') + '\n', '')
            return pn.Result(0, '\n', '')
        if verb == 'daemon-reload':
            self.daemon_reload()
            return ok
        if verb == 'enable':
            if self.disk(unit) is None:
                return pn.Result(1, '', f'Unit file {unit} does not exist.')
            self.enabled.add(unit)
            self.wants(unit).parent.mkdir(parents=True, exist_ok=True)
            self.wants(unit).write_text('link\n')
            return self.job('start', unit) if '--now' in rest else ok
        if verb == 'disable':
            self.enabled.discard(unit)
            if self.wants(unit).exists():
                self.wants(unit).unlink()
            if '--now' in rest:
                self.active.discard(unit)                       # systemd leaves the socket's node behind
            return ok
        if verb in ('restart', 'start'):
            return self.job(verb, unit)
        if verb == 'reload':
            if unit not in self.active or not self.has_exec_reload(unit):
                return pn.Result(1, '', f'Job type reload is not applicable for unit {unit}.')
            return ok
        if verb == 'stop':
            self.active.discard(unit)
            return ok
        if verb == 'reset-failed':
            self.failed.discard(unit)
            return ok
        return pn.Result(1, '', f'unknown verb {verb}')


class Response:
    """What `urlopen` returns: a context manager with `read()`. `doc` is a JSON document, or bytes."""

    def __init__(self, doc):
        self.body = doc if isinstance(doc, bytes) else json.dumps(doc).encode('utf-8')

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.body


class Status:
    """What Party Core answers on /party/api/status: an opener. `session` is {'game', 'state'} or
    None; `sequence` gives a different session for each question in turn (the last one repeats);
    `error` is raised instead of an answer; `doc` is answered instead of the usual document. A test
    that asks it far more often than any run would is a loop, and it fails instead of spinning."""
    LIMIT = 200

    def __init__(self, events, session=None, members=0, error=None, doc=None, sequence=None, healed=None):
        self.events, self.session, self.members, self.error, self.doc = events, session, members, error, doc
        self.sequence, self.healed = sequence, healed             # `healed()` true: the error no longer happens
        self.targets = []

    def __call__(self, target, timeout=None):
        self.targets.append(target)
        if len(self.targets) > self.LIMIT:
            raise AssertionError(f'Party Core was asked {self.LIMIT} times: a loop')
        self.events.append(('ask', target))
        if self.error is not None and not (self.healed and self.healed()):
            raise self.error
        if self.doc is not None:
            return Response(self.doc)
        session = self.sequence[min(len(self.targets) - 1, len(self.sequence) - 1)] if self.sequence else self.session
        return Response({'party_core': {'ok': True, 'uptime_s': 3, 'members': self.members, 'session': session}})


class Tape:
    """An output stream that also writes into the shared event log, so the order of what was said
    and what was run can be asserted."""

    def __init__(self, events):
        self.events, self.parts = events, []

    def write(self, text):
        if len(self.events) >= MAX_EVENTS:
            raise AssertionError(f'{MAX_EVENTS} events: a loop, not a command')
        self.parts.append(text)
        self.events.append(('out', text))
        return len(text)

    def flush(self):
        pass

    def text(self):
        return ''.join(self.parts)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds
        if self.t > 3600:
            raise AssertionError('slept for an hour of injected time: a loop, not a command')


def snapshot(root):
    """Every entry under `root` and the bytes of each file (None for a directory). The simulated host
    is a few small files, so this refuses a tree that is not: it never reads on through a runaway one."""
    found = {}
    for p in Path(root).rglob('*'):
        if len(found) >= MAX_ENTRIES:
            raise AssertionError(f'more than {MAX_ENTRIES} entries under {root}: not a simulated host')
        if p.is_file():
            if p.stat().st_size > MAX_BYTES:
                raise AssertionError(f'{p} is over {MAX_BYTES} bytes: not a file of a simulated host')
            found[p.relative_to(root).as_posix()] = p.read_bytes()
        else:
            found[p.relative_to(root).as_posix()] = None
    return dict(sorted(found.items()))


class Prepared(unittest.TestCase):
    """A phase 1 host: the identities, the earlier Party Core unit, a party-core.json with no registry
    key, no socket unit, Party Core running. `self.run_main(...)` is the command on it."""

    PARTY = 'active'

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / 'host'
        self.put('etc/passwd', PASSWD.encode())
        self.put('etc/group', GROUP.encode())
        self.put(UNIT_PATH, EARLIER_UNIT)
        self.put(CONFIG_PATH, EARLIER_CONFIG)
        self.events = []
        self.systemd = FakeSystemd(self.root, self.events, self.PARTY)
        self.status = Status(self.events)
        self.clock = Clock()
        self.backups = self.root / 'var/backups/avrana-party'

    def put(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def read(self, name):
        return (self.root / name).read_bytes()

    def config(self):
        return json.loads(self.read(CONFIG_PATH))

    def run_main(self, *args, status=None, **kw):
        out, err = Tape(self.events), io.StringIO()
        rc = pn.main(['--root', str(self.root), *args], environ={}, sysctl=self.systemd, opener=status or self.status,
                     now=lambda: NOW, sleep=self.clock.sleep, clock=self.clock, out=out, err=err, **kw)
        return rc, out.text(), err.getvalue()

    def prepare(self):
        rc, out, err = self.run_main()
        self.assertEqual((rc, err), (0, ''), out)
        return out

    def mutating(self, calls=None):
        return [c for c in (self.systemd.calls if calls is None else calls) if c[0] not in READ_ONLY]

    def backup_dirs(self):
        return sorted(p.name for p in self.backups.glob('native-games-*')) if self.backups.exists() else []

    def only_reads_since(self, mark):
        self.assertEqual(self.mutating(self.systemd.calls[mark:]), [])

    def socket_listens_again(self):
        """The socket unit began listening after Party Core started, as in a boot where the two raced:
        Party Core is running and was never handed it. (systemd will not restart a socket under a
        running service, so a test cannot get here by calling systemctl.)"""
        self.systemd.entered[pn.SOCKET] = self.systemd.tick()

    def refused(self, *args, why, **kw):
        """The command refuses: exit 1, the reason on stderr, nothing on the host changed, nothing run
        that changes anything."""
        before, mark = snapshot(self.root), len(self.systemd.calls)
        rc, out, err = self.run_main(*args, **kw)
        self.assertEqual(rc, 1, out + err)
        self.assertIn(why, err)
        self.assertIn('nothing was changed', err)
        self.assertEqual(snapshot(self.root), before)
        self.only_reads_since(mark)
        return out, err


# ---- the registry key: only that member of party-core.json changes ---------------------------------

def random_json(rng, depth=0):
    kinds = ['str', 'num', 'bool', 'null'] + (['arr', 'obj'] if depth < 3 else [])
    kind = rng.choice(kinds)
    if kind == 'str':
        return rng.choice(['x', 'caf\u00e9', 'a "q" b', 'tab\there', '\u2603 snow', 'back\\slash', ''])
    if kind == 'num':
        return rng.choice([0, 1, -7, 1.5, 1e3, 12345678901234567890])
    if kind == 'bool':
        return rng.choice([True, False])
    if kind == 'null':
        return None
    if kind == 'arr':
        return [random_json(rng, depth + 1) for _ in range(rng.randint(0, 3))]
    return {rng.choice(['a', 'b', 'status', 'x y', 'caf\u00e9', 'registry' if depth else 'k']) + str(i): random_json(rng, depth + 1)
            for i in range(rng.randint(0, 3))}


def random_text(rng, value, depth=0):
    """`value` as JSON text with whitespace and number and string spellings chosen at random."""
    def ws():
        return rng.choice(['', '', ' ', '  ', '\n', '\n  ', '\r\n', '\t', ' \n '])
    if isinstance(value, dict):
        inner = (',' + ws()).join(ws() + json.dumps(k, ensure_ascii=rng.random() < .5) + ws() + ':' + ws()
                                  + random_text(rng, v, depth + 1) + ws() for k, v in value.items())
        return '{' + inner + '}'
    if isinstance(value, list):
        return '[' + (',' + ws()).join(random_text(rng, v, depth + 1) for v in value) + ']'
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=rng.random() < .5)
    return json.dumps(value)


class RegistryEdit(unittest.TestCase):
    NEW = '"/etc/avrana-party/games.d"'

    def edit(self, text, **kw):
        new, earlier = pn.set_registry(text, REGISTRY)
        self.assertEqual(json.loads(new), dict(json.loads(text), registry=REGISTRY))
        self.assertEqual(list(json.loads(new)), list(json.loads(text)) + ([] if 'registry' in json.loads(text) else ['registry']))
        return new, earlier

    def test_a_member_is_inserted_the_way_the_file_writes_its_members(self):
        n = self.NEW
        for name, old, new in (
                ('multi-line, last member an object',
                 '{\n  "hosts": ["party.avrana.net"],\n  "status": {\n    "units": ["a"]\n  }\n}\n',
                 '{\n  "hosts": ["party.avrana.net"],\n  "status": {\n    "units": ["a"]\n  },\n  "registry": ' + n + '\n}\n'),
                ('compact with spaces', '{"hosts": ["x"], "secure_cookie": true}',
                 '{"hosts": ["x"], "secure_cookie": true, "registry": ' + n + '}'),
                ('tight, numbers spelled their own way', '{"hosts":["x"],"n":1e3,"big":12345678901234567890.50}',
                 '{"hosts":["x"],"n":1e3,"big":12345678901234567890.50,"registry":' + n + '}'),
                ('one member, tab indent', '{\n\t"hosts": ["x"]\n}', '{\n\t"hosts": ["x"],\n\t"registry": ' + n + '\n}'),
                ('Windows line ends', '{\r\n  "hosts": ["x"],\r\n  "secure_cookie": true\r\n}\r\n',
                 '{\r\n  "hosts": ["x"],\r\n  "secure_cookie": true,\r\n  "registry": ' + n + '\r\n}\r\n'),
                ('an empty object', '{}', '{\n  "registry": ' + n + '\n}'),
                ('other keys, escapes and a number spelled 1.50',
                 '{\n  "name": "caf\u00e9 \\"quoted\\" \\u00e9",\n  "n": 1.50\n}\n',
                 '{\n  "name": "caf\u00e9 \\"quoted\\" \\u00e9",\n  "n": 1.50,\n  "registry": ' + n + '\n}\n'),
                ('a nested registry is not the top-level one', '{\n  "status": {"registry": "/elsewhere"}\n}\n',
                 '{\n  "status": {"registry": "/elsewhere"},\n  "registry": ' + n + '\n}\n'),
                ('trailing space before the brace', '{"a": 1, "b": 2 }', '{"a": 1, "b": 2, "registry": ' + n + ' }'),
                ('one compact member: nothing to copy, so the member follows the gap after the brace', '{"a": 1}',
                 '{"a": 1,"registry": ' + n + '}'),
                ('one member after a space', '{ "a": 1 }', '{ "a": 1, "registry": ' + n + ' }')):
            with self.subTest(name):
                got, earlier = self.edit(old)
                self.assertEqual(got, new)
                self.assertIs(earlier, pn.ABSENT)

    def test_an_existing_registry_value_is_replaced_where_it_stands(self):
        n = self.NEW
        for name, old, new, earlier in (
                ('another directory', '{\n  "registry": "/old/dir",\n  "hosts": ["x"]\n}\n',
                 '{\n  "registry": ' + n + ',\n  "hosts": ["x"]\n}\n', '/old/dir'),
                ('null', '{"registry": null, "a": 1}', '{"registry": ' + n + ', "a": 1}', None),
                ('odd spacing', '{ "registry" : "/old" , "a" : 1 }', '{ "registry" : ' + n + ' , "a" : 1 }', '/old')):
            with self.subTest(name):
                got, was = self.edit(old)
                self.assertEqual((got, was), (new, earlier))

    def test_a_file_that_already_says_it_is_returned_as_it_is(self):
        text = '{\n  "registry": "/etc/avrana-party/games.d",\n  "a": 1\n}\n'
        self.assertEqual(pn.set_registry(text, REGISTRY), (text, REGISTRY))

    def test_what_it_cannot_edit_safely_it_refuses(self):
        for name, text, why in (
                ('not JSON', '{"a": 1,}', 'not valid JSON'),
                ('a byte order mark', '\ufeff{"a": 1}', 'not valid JSON'),
                ('text after the object', '{"a": 1} x', 'not valid JSON'),
                ('an array', '[1, 2]', 'not a JSON object'),
                ('registry twice', '{"registry": "/a", "registry": "/b"}', 'more than once'),
                ('nothing', '', 'not valid JSON')):
            with self.subTest(name), self.assertRaises(pn.Refused) as caught:
                pn.set_registry(text, REGISTRY)
            self.assertIn(why, str(caught.exception))

    def test_whatever_the_formatting_one_member_is_added_and_every_other_byte_stays(self):
        """300 random objects in random layouts: the new text is the old one with exactly one
        `,<whitespace>"registry"<whitespace>:<whitespace>"..."` put in, nowhere else touched."""
        rng = random.Random(304)
        member = re.compile(r',\s*"registry"\s*:\s*"/etc/avrana-party/games\.d"')
        for n in range(300):
            keys = {rng.choice(['hosts', 'origins', 'devices', 'games', 'status', 'secure_cookie', 'caf\u00e9']) + str(i): random_json(rng)
                    for i in range(rng.randint(0, 4))}
            old = random_text(rng, keys) + rng.choice(['', '\n', '\r\n', '  \n'])
            if old.lstrip()[:1] != '{':
                continue
            with self.subTest(n=n, old=old):
                new, earlier = self.edit(old) if keys else (pn.set_registry(old, REGISTRY)[0], pn.ABSENT)
                self.assertIs(earlier, pn.ABSENT)
                head = 0
                while head < len(old) and old[head] == new[head]:
                    head += 1
                tail = 0
                while tail < len(old) - head and old[-1 - tail] == new[-1 - tail]:
                    tail += 1
                inserted = new[head:len(new) - tail]
                if keys:
                    self.assertRegex(inserted, member)
                    self.assertEqual(old[:head] + old[head:], old)
                    self.assertEqual(new.replace(inserted, '', 1), old)
                else:
                    self.assertIn('"registry"', new)


class Applying(Prepared):
    def test_the_host_starts_as_the_issue_describes_it(self):
        self.assertNotRegex(EARLIER_UNIT.decode(), r'(?m)^ExecReload=')
        self.assertRegex(UNIT.decode(), r'(?m)^ExecReload=')
        self.assertFalse((self.root / SOCKET_PATH).exists())
        self.assertNotIn('registry', self.config())
        origins = self.config()['origins']
        self.assertEqual(origins, ['https://party.avrana.net'])         # exactly one bare origin (provision-game needs one)

    def test_it_installs_the_repository_units_enables_the_socket_and_sets_the_registry(self):
        out = self.prepare()
        self.assertEqual(self.read(UNIT_PATH), UNIT)
        self.assertEqual(self.read(SOCKET_PATH), SOCKET_UNIT)
        self.assertRegex(self.read(UNIT_PATH).decode(), r'(?m)^ExecReload=/bin/kill -HUP \$MAINPID$')
        self.assertIn(pn.SOCKET, self.systemd.enabled)
        self.assertIn(pn.SOCKET, self.systemd.active)
        self.assertTrue(self.systemd.node().exists())                   # /run/avrana-party/internal.sock
        self.assertEqual(self.config()['registry'], REGISTRY)
        # Party Core is stopped, the socket made ready and Party Core started: systemd will not start a socket
        # unit while its service runs, and Party Core is handed the socket only as it starts
        self.assertEqual(self.mutating(), [['daemon-reload'], ['stop', pn.SERVICE], ['enable', '--now', pn.SOCKET],
                                           ['start', pn.SERVICE]])
        self.assertIn('done', out)
        self.assertIn(STAMP, out)

    def test_after_it_systemctl_reload_works_and_provision_games_own_check_of_the_registry_passes(self):
        config = self.root / CONFIG_PATH
        self.assertEqual((pn.SERVICE, pn.REGISTRY_DIR), (pg.PARTY_UNIT, REGISTRY))
        with self.assertRaises(pg.Refused) as before:                    # what provision-game refuses for, before
            pg.check_party_reads(config, Path(REGISTRY))
        self.assertIn('does not name the registry directory', str(before.exception))
        self.assertNotEqual(self.systemd(['reload', pn.SERVICE]).rc, 0)  # before: no ExecReload=, a reload fails
        self.prepare()
        pg.check_party_reads(config, Path(REGISTRY))                     # after: the check provision-game makes passes
        self.assertEqual(self.systemd(['reload', pn.SERVICE]).rc, 0)     # and `systemctl reload avrana-party-core` works

    def test_every_other_byte_of_party_core_json_is_unchanged(self):
        self.prepare()
        old, new = EARLIER_CONFIG.decode('utf-8'), self.read(CONFIG_PATH).decode('utf-8')
        status_closes = old.rindex('}', 0, old.rindex('}')) + 1          # the last member is the status object
        self.assertEqual(new, old[:status_closes] + ',\n  "registry": "/etc/avrana-party/games.d"' + old[status_closes:])
        self.assertEqual(json.loads(new)['origins'], json.loads(old)['origins'])
        self.assertEqual({k: v for k, v in json.loads(new).items() if k != 'registry'}, json.loads(old))

    def test_it_says_whether_it_restarts_party_core_before_it_does_anything(self):
        keeping = pn.keep_before_state

        def keep(*args, **kwargs):                                       # the first thing written on the host
            self.events.append(('keep', None))
            return keeping(*args, **kwargs)
        with mock.patch.object(pn, 'keep_before_state', keep):
            self.prepare()
        index = lambda match: next(i for i, e in enumerate(self.events) if match(e))
        asked = index(lambda e: e[0] == 'ask')
        said = index(lambda e: e[0] == 'out' and 'Party Core: will be restarted (a restart ends the party)' in e[1])
        kept = index(lambda e: e[0] == 'keep')
        first_change = index(lambda e: e[0] == 'systemctl' and e[1][0] not in READ_ONLY)
        stop = index(lambda e: e[0] == 'systemctl' and e[1] == ['stop', pn.SERVICE])
        start = index(lambda e: e[0] == 'systemctl' and e[1] == ['start', pn.SERVICE])
        self.assertLess(asked, said)                                    # it asked who is on Party Core first
        self.assertLess(said, kept)                                     # said it before it kept or wrote anything
        self.assertLess(said, first_change)                             # and before the first systemctl change
        self.assertLess(first_change, stop)
        self.assertLess(stop, start)

    def test_the_plan_names_what_changes_in_the_unit(self):
        out = self.prepare()
        for line in ('+ ExecReload=/bin/kill -HUP $MAINPID', f'+ Wants={pn.SOCKET}', f'+ After=network.target {pn.SOCKET}',
                     '- After=network.target', f'install /etc/systemd/system/{pn.SOCKET} (new)',
                     '"registry" absent -> "/etc/avrana-party/games.d"'):
            self.assertIn(line, out)

    def test_it_touches_nothing_but_its_own_files(self):
        before = snapshot(self.root)
        self.prepare()
        self.assertEqual(self.run_main('--reverse')[0], 0)
        after = snapshot(self.root)
        self.assertEqual({name: data for name, data in after.items() if name in before}, before)    # all as it was
        added = set(after) - set(before)
        self.assertTrue(added)
        allowed = ('var/backups/avrana-party', 'run/avrana-party', 'etc/systemd/system/sockets.target.wants')
        stray = {name for name in added if not name.startswith(allowed) and name not in ('var', 'var/backups', 'run')}
        self.assertEqual(stray, set())
        verbs = {c[0] for c in self.systemd.calls}
        self.assertLessEqual(verbs, {'is-active', 'is-enabled', 'show', 'daemon-reload', 'stop', 'enable', 'start', 'disable'})
        self.assertEqual(self.read('etc/passwd').decode(), PASSWD)       # no user or group is created
        self.assertEqual(self.read('etc/group').decode(), GROUP)

    def test_the_configuration_is_written_with_the_mode_and_owner_it_had(self):
        """Not POSIX-only: the stat result is a stand-in, and the real write_file runs without the chown."""
        written = {}
        real_write, real_facts = pn.write_file, pn.read_facts

        def facts(host, sysctl):
            found = real_facts(host, sysctl)
            found.config_stat = types.SimpleNamespace(st_mode=stat.S_IFREG | 0o640, st_uid=1234, st_gid=4321)
            return found

        def write(path, data, mode, owner=None):
            written[path.name] = (mode, owner)
            return real_write(path, data, mode)
        with mock.patch.object(pn, 'read_facts', facts), mock.patch.object(pn, 'write_file', write):
            self.prepare()
        self.assertEqual(written['party-core.json'], (0o640, (1234, 4321)))
        self.assertEqual(written[pn.SERVICE], (0o644, None))
        self.assertEqual(written[pn.SOCKET], (0o644, None))

    @unittest.skipUnless(POSIX, 'modes and owners are POSIX')
    def test_modes_are_kept_and_the_before_state_is_private(self):
        config = self.root / CONFIG_PATH
        config.chmod(0o640)
        self.prepare()
        mode = lambda p: stat.S_IMODE(p.stat().st_mode)
        self.assertEqual(mode(config), 0o640)                            # the config keeps its mode
        self.assertEqual(mode(self.root / UNIT_PATH), 0o644)
        self.assertEqual(mode(self.root / SOCKET_PATH), 0o644)
        kept = self.backups / STAMP
        self.assertEqual(mode(kept), 0o750)
        self.assertEqual(mode(kept / 'state.json'), 0o600)


class DryRun(Prepared):
    def test_it_prints_every_file_and_unit_it_would_change_and_changes_nothing(self):
        before, mark = snapshot(self.root), len(self.systemd.calls)
        rc, out, err = self.run_main('--dry-run')
        self.assertEqual((rc, err), (0, ''), out)
        for expected in ('/etc/systemd/system/avrana-party-core.service', '/etc/systemd/system/avrana-party-core.socket',
                         '/etc/avrana-party/party-core.json', 'systemctl daemon-reload',
                         'systemctl enable --now avrana-party-core.socket', 'systemctl stop avrana-party-core.service',
                         'systemctl start avrana-party-core.service',
                         'Party Core: will be restarted', STAMP, '+ ExecReload=', 'dry run: nothing changed'):
            self.assertIn(expected, out)
        self.assertEqual(snapshot(self.root), before)
        self.only_reads_since(mark)
        self.assertEqual(self.backup_dirs(), [])
        self.assertEqual(len(self.status.targets), 1)                    # asked once: a dry run does not wait out the cache
        self.assertEqual(self.clock.t, 0.0)

    def test_it_reports_a_refusal_a_real_run_would_make(self):
        self.status.session = {'game': 'checkers', 'state': 'active'}
        out, err = self.refused('--dry-run', why='a game session is running (checkers)')


class Repeating(Prepared):
    def test_a_second_run_reports_nothing_to_change_and_restarts_nothing(self):
        self.prepare()
        before, mark = snapshot(self.root), len(self.systemd.calls)
        rc, out, err = self.run_main()
        self.assertEqual((rc, err), (0, ''), out)
        self.assertIn('nothing to change', out)
        self.assertIn('Party Core: will not be restarted: it already holds the socket', out)
        self.assertEqual(snapshot(self.root), before)
        self.only_reads_since(mark)                                      # no daemon-reload, enable, restart or reload
        self.assertEqual(self.backup_dirs(), [STAMP])

    def test_a_third_run_is_the_same(self):
        self.prepare()
        self.run_main()
        mark = len(self.systemd.calls)
        rc, out, err = self.run_main()
        self.assertEqual(rc, 0)
        self.assertIn('nothing to change', out)
        self.only_reads_since(mark)

    def test_a_run_that_failed_half_way_is_finished_by_running_again(self):
        self.systemd.fail[('enable', pn.SOCKET)] = 1
        rc, out, err = self.run_main()
        self.assertEqual(rc, 3, out + err)                               # changed, then failed
        self.assertIn('NOT complete', err)
        self.assertIn('Party Core was started again', err)               # it was stopped for the socket: never left so
        self.assertEqual(self.read(UNIT_PATH), UNIT)                     # the files were written
        self.assertEqual(self.backup_dirs(), [STAMP])
        self.systemd.fail.clear()
        self.prepare()
        self.assertIn(pn.SOCKET, self.systemd.active)
        self.assertEqual(self.backup_dirs(), [STAMP])                    # the same before-state, added to
        rc, out, err = self.run_main('--reverse')                        # goes back to how the host was at the start
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(self.read(UNIT_PATH), EARLIER_UNIT)
        self.assertEqual(self.read(CONFIG_PATH), EARLIER_CONFIG)

    def test_a_run_that_failed_before_the_daemon_reload_still_reloads_next_time(self):
        self.systemd.fail[('daemon-reload', None)] = 1
        rc, out, err = self.run_main()
        self.assertEqual(rc, 3, out + err)
        self.systemd.fail.clear()
        rc, out, err = self.run_main()
        self.assertEqual(rc, 0, out + err)
        self.assertIn('run systemctl daemon-reload', out)                # systemd had not loaded what was on disk
        self.assertTrue(self.systemd.has_exec_reload(pn.SERVICE))

    def test_a_changed_repository_unit_is_installed_on_the_next_run_and_the_first_before_state_is_kept(self):
        self.prepare()
        self.put(UNIT_PATH, UNIT + b'# edited on the host\n')
        rc, out, err = self.run_main()
        self.assertEqual((rc, err), (0, ''), out)
        self.assertEqual(self.read(UNIT_PATH), UNIT)
        self.assertIn('Party Core: will not be restarted: it already holds the socket', out)
        self.assertIn('the running Party Core keeps the unit it started with until its next restart', out)
        self.assertEqual(self.backup_dirs(), [STAMP])
        self.assertEqual((self.backups / STAMP / 'units' / pn.SERVICE).read_bytes(), EARLIER_UNIT)   # still the first one
        self.run_main('--reverse')
        self.assertEqual(self.read(UNIT_PATH), EARLIER_UNIT)

    def test_a_config_that_lost_the_registry_key_is_read_again_not_restarted(self):
        self.prepare()
        mark = len(self.systemd.calls)
        self.put(CONFIG_PATH, EARLIER_CONFIG)
        rc, out, err = self.run_main()
        self.assertEqual((rc, err), (0, ''), out)
        self.assertEqual(self.config()['registry'], REGISTRY)
        self.assertEqual(self.mutating(self.systemd.calls[mark:]), [['reload', pn.SERVICE]])
        self.assertIn('Party Core: will not be restarted: it already holds the socket', out)

    def test_a_before_state_is_kept_for_each_prepared_period(self):
        self.prepare()
        self.assertEqual(self.run_main('--reverse')[0], 0)
        self.prepare()
        self.assertEqual(self.backup_dirs(), [STAMP, STAMP + '-2'])      # the same clock tick: the name is made unique
        self.assertEqual(self.run_main('--reverse')[0], 0)
        self.assertEqual(self.read(UNIT_PATH), EARLIER_UNIT)
        self.assertEqual(json.loads((self.backups / (STAMP + '-2') / 'state.json').read_text())['schema'], pn.SCHEMA)


class Restarting(Prepared):
    def test_it_does_not_restart_party_core_while_a_session_is_running(self):
        self.status.session = {'game': 'checkers', 'state': 'active'}
        out, err = self.refused(why='a game session is running (checkers) and Party Core would have to restart')
        self.assertEqual(out, '')                                        # it said nothing about a plan it will not carry out
        self.assertIn('wait until the party is back at Party Home', err)
        self.assertEqual(self.backup_dirs(), [])

    def test_a_session_that_started_while_it_waited_out_the_status_cache_is_still_a_session(self):
        self.status.sequence = [None, {'game': 'checkers', 'state': 'launching'}]
        self.refused(why='a game session is running (checkers)')
        self.assertEqual(len(self.status.targets), 2)
        self.assertGreaterEqual(self.clock.t, pg.STATUS_SETTLE_S)

    def test_an_ended_session_is_no_session(self):
        self.status.session = {'game': 'checkers', 'state': 'ended'}
        self.prepare()
        self.assertIn(['stop', pn.SERVICE], self.systemd.calls)
        self.assertIn(['start', pn.SERVICE], self.systemd.calls)

    def test_a_real_run_asks_twice_a_status_cache_apart_and_once_more_after_the_restart(self):
        self.prepare()
        self.assertEqual(len(self.status.targets), 3)
        self.assertGreaterEqual(self.clock.t, pg.STATUS_SETTLE_S)

    def test_party_core_is_asked_on_loopback_naming_the_first_host_of_its_configuration(self):
        self.run_main('--dry-run')
        target = self.status.targets[0]
        self.assertEqual(target.full_url, 'http://127.0.0.1:8191/party/api/status')
        self.assertEqual(target.get_header('Host'), 'party.avrana.net')
        self.status.targets.clear()
        self.run_main('--dry-run', '--party-url', 'http://127.0.0.1:9')
        self.assertEqual(self.status.targets[0].full_url, 'http://127.0.0.1:9/party/api/status')

    def test_a_configuration_without_hosts_is_asked_without_a_host_name(self):
        self.put(CONFIG_PATH, json.dumps({'origins': ['https://party.avrana.net']}, indent=2).encode() + b'\n')
        self.run_main('--dry-run')
        self.assertEqual(self.status.targets, ['http://127.0.0.1:8191/party/api/status'])

    def test_the_party_url_can_come_from_the_environment(self):
        out, err = io.StringIO(), io.StringIO()
        rc = pn.main(['--root', str(self.root), '--dry-run'], environ={'AVRANA_PARTY_CORE_URL': 'http://127.0.0.1:9'},
                     sysctl=self.systemd, opener=self.status, now=lambda: NOW, sleep=self.clock.sleep, clock=self.clock,
                     out=out, err=err)
        self.assertEqual(rc, 0, err.getvalue())
        self.assertEqual(self.status.targets[0].full_url, 'http://127.0.0.1:9/party/api/status')

    def test_party_core_is_asked_directly_never_through_an_environment_proxy(self):
        with mock.patch.object(urllib.request, 'build_opener') as build:
            build.return_value.open.return_value = 'reply'
            self.assertEqual(pn._direct_open('http://127.0.0.1:8191/x', 3), 'reply')
        (handler,), _ = build.call_args
        self.assertEqual((type(handler), handler.proxies), (urllib.request.ProxyHandler, {}))

    def test_a_party_core_that_cannot_be_asked_is_not_restarted(self):
        for name, error, doc, why in (
                ('a timeout', TimeoutError(), None, 'did not answer in time'),
                ('a timeout inside a URL error', urllib.error.URLError(TimeoutError()), None, 'did not answer in time'),
                ('another network error', urllib.error.URLError(OSError('no route')), None, 'could not be asked'),
                ('an HTTP error', urllib.error.HTTPError('http://x', 500, 'err', {}, None), None, 'answered HTTP 500'),
                ('something that is not JSON', None, b'not a document', 'not JSON'),
                ('no session in the answer', None, {'party_core': {'ok': True}}, 'did not report its session'),
                ('an answer that is not ok', None, {'party_core': {'ok': False, 'session': None}}, 'did not report its session'),
                ('a session it cannot read', None, {'party_core': {'ok': True, 'session': 'x'}}, 'session this tool cannot read')):
            with self.subTest(name):
                self.refused(why=why, status=Status(self.events, error=error, doc=doc))

    def restarted(self):
        return ['start', pn.SERVICE] in self.systemd.calls

    def test_nobody_listening_on_loopback_is_no_party_and_no_session(self):
        for error in (ConnectionRefusedError(), urllib.error.URLError(ConnectionRefusedError())):
            with self.subTest(type(error).__name__):
                self.setUp()
                self.status = Status(self.events, error=error, healed=self.restarted)     # it answers once restarted
                out = self.prepare()
                self.assertIn('Nothing answers on loopback, so there is no party and no session', out)
                self.assertIn(['start', pn.SERVICE], self.systemd.calls)

    def test_a_party_core_that_does_not_answer_after_the_restart_is_a_failed_check_with_a_way_back(self):
        self.status = Status(self.events, error=ConnectionRefusedError())                 # never answers
        rc, out, err = self.run_main()
        self.assertEqual(rc, 3, out + err)
        self.assertIn('FAIL Party Core answers on loopback after the restart', out)
        self.assertIn('journalctl -u avrana-party-core', out)
        self.assertIn('NOT complete', err)
        self.assertIn(f'sudo ops/prepare-native-games --reverse {self.backups / STAMP}', err)
        self.assertGreaterEqual(self.clock.t, pn.ANSWER_WAIT_S)                           # it waited, on the injected clock

    def test_the_party_it_will_end_is_described(self):
        for members, said in ((0, 'Nobody is in the party'), (1, '1 member is in the party and will have to join again'),
                              (3, '3 members are in the party and will have to join again')):
            with self.subTest(members=members):
                self.setUp()
                self.status.members = members
                rc, out, err = self.run_main('--dry-run')
                self.assertIn(said, out)

    def test_a_party_core_that_is_stopped_is_left_stopped_and_is_not_a_session(self):
        self.systemd.active.discard(pn.SERVICE)
        out = self.prepare()
        self.assertIn('Party Core: will not be restarted: it is not running (inactive)', out)
        self.assertEqual(self.status.targets, [])                        # nobody to ask
        for verb in ('stop', 'start', 'restart'):
            self.assertNotIn([verb, pn.SERVICE], self.systemd.calls)
        self.assertNotIn(pn.SERVICE, self.systemd.active)
        self.assertIn(pn.SOCKET, self.systemd.active)                    # the socket is there for it to take
        self.assertTrue(self.systemd.node().exists())
        self.systemd.start(pn.SERVICE)                                   # it starts later, and inherits the socket
        mark = len(self.systemd.calls)
        rc, out, err = self.run_main()
        self.assertIn('nothing to change', out)
        self.only_reads_since(mark)

    def test_a_stopped_party_core_is_not_asked_even_for_a_session_a_real_one_would_have(self):
        self.systemd.active.discard(pn.SERVICE)
        self.status.session = {'game': 'checkers', 'state': 'active'}
        self.prepare()                                                   # not refused: nothing runs to be ended

    def test_a_failed_party_core_is_not_restarted_either(self):
        self.systemd.active.discard(pn.SERVICE)
        self.systemd.failed.add(pn.SERVICE)
        out = self.prepare()
        self.assertIn('it is not running (failed)', out)
        self.assertIn('it is failed: read journalctl -u avrana-party-core', out)    # the check says where to look
        for verb in ('stop', 'start', 'restart'):
            self.assertNotIn([verb, pn.SERVICE], self.systemd.calls)
        self.assertIn(pn.SERVICE, self.systemd.failed)

    def test_a_party_core_that_started_after_the_socket_is_not_restarted(self):
        self.systemd.active.discard(pn.SERVICE)
        self.prepare()                                                   # stopped: socket installed, nothing restarted
        self.systemd.start(pn.SERVICE)
        self.put(CONFIG_PATH, EARLIER_CONFIG)                            # something to do that needs no restart
        mark = len(self.systemd.calls)
        out = self.prepare()
        self.assertIn('it already holds the socket', out)
        self.assertEqual(self.mutating(self.systemd.calls[mark:]), [['reload', pn.SERVICE]])

    def test_a_party_core_that_started_before_the_socket_listened_must_be_restarted_even_with_nothing_else_to_do(self):
        self.prepare()
        self.socket_listens_again()                                      # Party Core holds an older socket
        mark, before = len(self.systemd.calls), snapshot(self.root)
        out = self.prepare()
        self.assertEqual(self.mutating(self.systemd.calls[mark:]), [['stop', pn.SERVICE], ['start', pn.SERVICE]])
        self.assertIn('does not hold the socket', out)
        self.assertEqual({k: v for k, v in snapshot(self.root).items() if not k.startswith('var/')},
                         {k: v for k, v in before.items() if not k.startswith('var/')})

    def test_that_restart_is_refused_while_a_session_runs_and_done_when_it_ends(self):
        self.prepare()
        self.socket_listens_again()
        self.status.session = {'game': 'checkers', 'state': 'active'}
        self.refused(why='a game session is running (checkers)')
        self.status.session = {'game': 'checkers', 'state': 'ended'}
        self.prepare()
        self.run_main()
        mark = len(self.systemd.calls)
        self.assertIn('nothing to change', self.run_main()[1])
        self.only_reads_since(mark)

    def test_a_changed_socket_unit_takes_a_restart_of_the_socket_and_of_party_core(self):
        self.prepare()
        self.put(SOCKET_PATH, SOCKET_UNIT.replace(b'SocketMode=0660', b'SocketMode=0666'))    # edited on the host
        mark = len(self.systemd.calls)
        out = self.prepare()
        self.assertEqual(self.read(SOCKET_PATH), SOCKET_UNIT)
        # the service is stopped before its socket is restarted: systemd would refuse the other way round
        self.assertEqual(self.mutating(self.systemd.calls[mark:]),
                         [['daemon-reload'], ['stop', pn.SERVICE], ['restart', pn.SOCKET], ['start', pn.SERVICE]])
        self.assertIn('Party Core: will be restarted (a restart ends the party): the socket unit changes', out)
        self.assertEqual(self.systemd.refusals, [])

    def test_a_socket_unit_changed_only_in_a_comment_takes_no_restart(self):
        self.prepare()
        self.put(SOCKET_PATH, SOCKET_UNIT + b'# changed on the host\n')
        mark = len(self.systemd.calls)
        out = self.prepare()
        self.assertEqual(self.read(SOCKET_PATH), SOCKET_UNIT)
        self.assertEqual(self.mutating(self.systemd.calls[mark:]), [['daemon-reload']])
        self.assertIn('Party Core: will not be restarted: it already holds the socket', out)

    def test_a_changed_socket_unit_is_not_applied_while_a_session_runs(self):
        self.prepare()
        edited = SOCKET_UNIT.replace(b'SocketMode=0660', b'SocketMode=0666')
        self.put(SOCKET_PATH, edited)
        self.status.session = {'game': 'checkers', 'state': 'active'}
        self.refused(why='a game session is running (checkers)')
        self.assertEqual(self.read(SOCKET_PATH), edited)                 # nothing was put back
        self.status.session = None
        self.prepare()
        self.assertEqual(self.read(SOCKET_PATH), SOCKET_UNIT)

    def test_the_socket_is_never_started_under_a_running_party_core(self):
        """The stand-in refuses what systemd refuses, and the command never asks for it."""
        self.prepare()
        self.systemd(['disable', '--now', pn.SOCKET])                    # the socket stops; Party Core keeps running
        self.assertEqual(self.systemd(['enable', '--now', pn.SOCKET]).rc, 1)     # systemd's rule, on its own
        self.assertEqual(self.systemd.refusals, [pn.SOCKET])
        self.systemd.refusals.clear()
        self.assertEqual(self.systemd.node().exists(), True)             # the node stays behind, as systemd leaves it
        out = self.prepare()                                             # Party Core runs without the socket: restarted
        self.assertIn('does not hold the socket', out)
        self.assertEqual(self.systemd.refusals, [])
        self.assertIn(pn.SOCKET, self.systemd.active)
        self.assertEqual(self.mutating()[-3:], [['stop', pn.SERVICE], ['enable', '--now', pn.SOCKET], ['start', pn.SERVICE]])

    def test_a_party_core_that_is_still_changing_state_is_not_touched(self):
        for word in ('activating', 'deactivating', 'reloading'):
            with self.subTest(word):
                self.systemd.states[pn.SERVICE] = word
                self.refused(why=f'Party Core is {word}, not settled; wait a moment and run this again')

    def test_a_failure_with_party_core_stopped_starts_it_again(self):
        self.systemd.fail[('enable', pn.SOCKET)] = 1
        rc, out, err = self.run_main()
        self.assertEqual(rc, 3, out + err)
        self.assertIn('NOT complete', err)
        self.assertIn('Party Core was started again', err)
        self.assertIn(['start', pn.SERVICE], self.systemd.calls)
        self.assertIn(pn.SERVICE, self.systemd.active)                   # the party's core is not left stopped
        self.assertIn(f'sudo ops/prepare-native-games --reverse {self.backups / STAMP}', err)
        self.assertIn('or run this again to finish', err)

    def test_a_failure_to_start_party_core_says_it_is_stopped(self):
        self.systemd.fail[('start', pn.SERVICE)] = 1
        rc, out, err = self.run_main()
        self.assertEqual(rc, 3, out + err)
        self.assertIn('systemctl start avrana-party-core.service exited 1', err)
        self.assertIn('Party Core is STOPPED and could not be started again', err)
        self.assertIn('journalctl -u avrana-party-core -n 50', err)
        self.assertNotIn(pn.SERVICE, self.systemd.active)

    def test_a_failed_stop_leaves_party_core_as_it_was_and_says_so(self):
        self.systemd.fail[('stop', pn.SERVICE)] = 1
        rc, out, err = self.run_main()
        self.assertEqual(rc, 3, out + err)
        self.assertIn('systemctl stop avrana-party-core.service exited 1', err)
        self.assertIn('Party Core is running', err)
        self.assertIn(pn.SERVICE, self.systemd.active)
        self.assertIn(f'sudo ops/prepare-native-games --reverse {self.backups / STAMP}', err)

    def test_nothing_ends_the_run_between_stopping_party_core_and_starting_it_again(self):
        """A dropped SSH session (SIGHUP) or Ctrl-C there would leave the party's front stopped."""
        names = [n for n in ('SIGHUP', 'SIGINT', 'SIGTERM') if hasattr(signal, n)]
        handlers = lambda: {n: signal.getsignal(getattr(signal, n)) for n in names}
        before, seen = handlers(), {}
        self.systemd.hook = lambda args: seen.setdefault(args[0], handlers()) if args[0] in (
            'daemon-reload', 'stop', 'enable', 'start') else None
        self.prepare()
        self.assertEqual(sorted(seen), ['daemon-reload', 'enable', 'start', 'stop'])
        for verb in ('stop', 'enable', 'start'):
            self.assertEqual(seen[verb], {n: signal.SIG_IGN for n in names}, verb)
        self.assertEqual(seen['daemon-reload'], before)                  # before Party Core is touched, Ctrl-C still works
        self.assertEqual(handlers(), before)                             # and everything is put back afterwards

    def test_the_handlers_come_back_when_the_restart_fails_too(self):
        names = [n for n in ('SIGHUP', 'SIGINT', 'SIGTERM') if hasattr(signal, n)]
        before = {n: signal.getsignal(getattr(signal, n)) for n in names}
        self.systemd.fail[('start', pn.SERVICE)] = 1
        self.assertEqual(self.run_main()[0], 3)
        self.assertEqual({n: signal.getsignal(getattr(signal, n)) for n in names}, before)


class Refusals(Prepared):
    def test_without_the_phase_1_identities_it_refuses_and_changes_nothing(self):
        for name, passwd, group, missing in (
                ('no avrana-party', 'root:x:0:0::/root:/bin/sh\n', GROUP, 'user avrana-party'),
                ('no avrana-games', PASSWD, 'root:x:0:\navrana-party:x:998:\navrana-front:x:997:\n', 'group avrana-games'),
                ('no avrana-front', PASSWD, 'root:x:0:\navrana-games:x:996:\n', 'group avrana-front'),
                ('none of them', 'root:x:0:0::/root:/bin/sh\n', 'root:x:0:\n', 'user avrana-party, group avrana-front, group avrana-games'),
                ('no files', None, None, 'user avrana-party')):
            with self.subTest(name):
                for path, text in (('etc/passwd', passwd), ('etc/group', group)):
                    if text is None:
                        (self.root / path).unlink()
                    else:
                        self.put(path, text.encode())
                before, mark = snapshot(self.root), len(self.systemd.calls)
                for args in ((), ('--dry-run',)):
                    rc, out, err = self.run_main(*args)
                    self.assertEqual(rc, 1, out + err)
                    self.assertIn('ADR 0016 phase 1 has not been applied on this host', err)
                    self.assertIn(missing, err)
                    self.assertIn('ops/migrate-service-users.sh', err)
                    self.assertIn('nothing was changed', err)
                self.assertEqual(snapshot(self.root), before)
                self.assertEqual(self.systemd.calls[mark:], [])          # it did not even look at systemd
                self.put('etc/passwd', PASSWD.encode())
                self.put('etc/group', GROUP.encode())

    def test_an_injected_identity_check_is_honoured(self):
        rc, out, err = self.run_main(identities=lambda: ['group avrana-games'])
        self.assertEqual(rc, 1)
        self.assertIn('missing: group avrana-games', err)

    def test_the_real_identity_check_refuses_a_machine_that_has_not_had_phase_1(self):
        try:
            import pwd
            pwd.getpwnam(pn.USER)
        except KeyError:
            pass
        except ImportError:
            pass
        else:
            self.skipTest(f'{pn.USER} exists here: this is a phase 1 host')
        try:
            missing = pn.os_identities()
        except pn.Refused as e:
            self.assertIn('Linux appliance', str(e))                     # no pwd and grp on this platform
        else:
            self.assertIn(f'user {pn.USER}', missing)

    def test_it_will_not_run_for_real_without_root(self):
        for args in ((), ('--reverse',)):
            out, err = Tape(self.events), io.StringIO()
            rc = pn.main(list(args), environ={}, sysctl=self.systemd, is_root=False, out=out, err=err)
            self.assertEqual(rc, 1)
            self.assertIn('run as root (sudo), or with --dry-run', err.getvalue())
        self.assertEqual(self.systemd.calls, [])

    def test_a_simulated_host_never_talks_to_the_real_systemd(self):
        before = snapshot(self.root)
        err = io.StringIO()
        rc = pn.main(['--root', str(self.root)], environ={}, out=io.StringIO(), err=err)
        self.assertEqual(rc, 1)
        self.assertIn('AVRANA_SYSTEMCTL must name a stand-in for systemctl', err.getvalue())
        self.assertEqual(snapshot(self.root), before)

    def test_the_root_and_the_stand_in_can_come_from_the_environment(self):
        shim = self.root / 'shim'
        shim.write_text('x')
        for env in ({'AVRANA_ROOT': str(self.root)},):
            out, err = io.StringIO(), io.StringIO()
            rc = pn.main(['--dry-run'], environ=dict(env, AVRANA_SYSTEMCTL=str(shim)), sysctl=self.systemd, opener=self.status,
                         out=out, err=err, now=lambda: NOW)
            self.assertEqual(rc, 0, err.getvalue())
            self.assertIn('a simulated host under', out.getvalue())

    def test_the_backup_root_can_be_named(self):
        elsewhere = self.root / 'elsewhere'
        out, err = io.StringIO(), io.StringIO()
        rc = pn.main(['--root', str(self.root)], environ={'AVRANA_BACKUP_ROOT': str(elsewhere)}, sysctl=self.systemd,
                     opener=self.status, out=out, err=err, now=lambda: NOW, sleep=self.clock.sleep, clock=self.clock)
        self.assertEqual(rc, 0, err.getvalue())
        self.assertTrue((elsewhere / STAMP / 'state.json').is_file())
        self.assertEqual(self.backup_dirs(), [])

    def test_without_party_cores_configuration_it_does_not_make_one(self):
        (self.root / CONFIG_PATH).unlink()
        self.refused(why='/etc/avrana-party/party-core.json does not exist: Party Core is not installed here')
        self.assertFalse((self.root / CONFIG_PATH).exists())

    def test_a_configuration_that_is_not_json_is_refused_untouched(self):
        for name, data, why in (('not JSON', b'{"hosts": ["x"],}\n', 'not valid JSON'),
                                ('not UTF-8', b'{"a": "\xff"}', 'not UTF-8 text'),
                                ('registry twice', b'{"registry": "/a", "registry": "/b"}', 'more than once'),
                                ('an array', b'[]', 'not a JSON object')):
            with self.subTest(name):
                self.put(CONFIG_PATH, data)
                self.refused(why=why)
                self.assertEqual(self.read(CONFIG_PATH), data)

    def test_the_units_root_installs_come_only_from_root_owned_code(self):
        """On a real host the repository's two unit files must be code no one but root can change (the same
        rule provision-game applies to a game's code); the check itself is provision-game's."""
        host = pn.Host(self.root, SOURCE)
        with mock.patch.object(pg, 'untrusted_reason', return_value='/home/cody is not owned by root'):
            with self.assertRaises(pn.Refused) as caught:
                pn.read_sources(host, trusted=True)
        self.assertIn('/home/cody is not owned by root', str(caught.exception))
        self.assertIn('comes only from root-owned code', str(caught.exception))
        self.assertIn('/opt/avrana-party/current', str(caught.exception))
        with mock.patch.object(pg, 'untrusted_reason', return_value=None) as asked:
            self.assertEqual(set(pn.read_sources(host, trusted=True)), {pn.SERVICE, pn.SOCKET})
        self.assertEqual(sorted(Path(c.args[0]).name for c in asked.call_args_list), [pn.SERVICE, pn.SOCKET])

    def test_a_missing_source_unit_is_refused(self):
        empty = self.root / 'empty'
        empty.mkdir()
        self.refused('--source-dir', str(empty), why=f'{pn.SERVICE} is missing from {empty}')

    @unittest.skipUnless(POSIX, 'symbolic links')
    def test_a_unit_or_configuration_that_is_a_symbolic_link_is_refused(self):
        for name in (UNIT_PATH, CONFIG_PATH):
            with self.subTest(name):
                path = self.root / name
                data = path.read_bytes()
                target = self.root / 'real'
                target.write_bytes(data)
                path.unlink()
                os.symlink(target, path)
                self.refused(why='is a symbolic link')
                path.unlink()
                path.write_bytes(data)
                target.unlink()

    def test_a_bad_command_line_is_a_usage_error(self):
        for args in (['--nope'], ['--rev'], ['extra'], ['--reverse', 'a', 'b']):
            with self.subTest(args=args):
                err = io.StringIO()
                self.assertEqual(pn.main(args, environ={}, out=io.StringIO(), err=err), 2)
                self.assertIn('prepare-native-games:', err.getvalue())
        self.assertEqual(pn.main(['--help'], environ={}, out=io.StringIO(), err=io.StringIO()), 0)


class Reversing(Prepared):
    def test_it_puts_the_earlier_files_back_disables_the_socket_and_leaves_party_core_running(self):
        self.prepare()
        started = self.systemd.entered[pn.SERVICE]
        mark = len(self.systemd.calls)
        rc, out, err = self.run_main('--reverse')
        self.assertEqual((rc, err), (0, ''), out)
        self.assertEqual(self.read(UNIT_PATH), EARLIER_UNIT)
        self.assertEqual(self.read(CONFIG_PATH), EARLIER_CONFIG)         # byte for byte
        self.assertFalse((self.root / SOCKET_PATH).exists())             # it did not exist before
        self.assertNotIn(pn.SOCKET, self.systemd.enabled)
        self.assertNotIn(pn.SOCKET, self.systemd.active)
        self.assertFalse(self.systemd.node().exists())
        self.assertFalse(self.systemd.wants(pn.SOCKET).exists())
        self.assertEqual(self.mutating(self.systemd.calls[mark:]), [['disable', '--now', pn.SOCKET], ['daemon-reload']])
        self.assertIn(pn.SERVICE, self.systemd.active)                   # Party Core was not restarted: the party is untouched
        self.assertEqual(self.systemd.entered[pn.SERVICE], started)
        self.assertNotEqual(self.systemd(['reload', pn.SERVICE]).rc, 0)  # the earlier state: no ExecReload= again
        self.assertIn('reversed', out)
        self.assertIn('Party Core was not restarted', out)

    def test_it_disables_the_socket_before_its_unit_file_goes(self):
        self.prepare()
        self.run_main('--reverse')
        calls = [e[1][0] for e in self.events if e[0] == 'systemctl' and e[1][0] in ('disable', 'daemon-reload')]
        self.assertEqual(calls[-2:], ['disable', 'daemon-reload'])

    def test_a_dry_run_reverse_prints_the_plan_and_changes_nothing(self):
        self.prepare()
        before, mark = snapshot(self.root), len(self.systemd.calls)
        rc, out, err = self.run_main('--reverse', '--dry-run')
        self.assertEqual((rc, err), (0, ''), out)
        for expected in (f'restore /etc/systemd/system/{pn.SERVICE}', f'remove /etc/systemd/system/{pn.SOCKET}',
                         'restore /etc/avrana-party/party-core.json', f'run systemctl disable --now {pn.SOCKET}',
                         'run systemctl daemon-reload', 'dry run: nothing changed'):
            self.assertIn(expected, out)
        self.assertEqual(snapshot(self.root), before)
        self.only_reads_since(mark)

    def test_the_directory_can_be_named_and_a_second_reverse_has_nothing_to_do(self):
        self.prepare()
        kept = self.backups / STAMP
        self.assertEqual(self.run_main('--reverse', str(kept))[0], 0)
        mark = len(self.systemd.calls)
        rc, out, err = self.run_main('--reverse')
        self.assertEqual((rc, err), (0, ''))
        self.assertIn('nothing to reverse', out)
        self.assertIn(f'{STAMP}', out)
        rc, out, err = self.run_main('--reverse', str(kept))              # named again: it looks, finds it done
        self.assertEqual((rc, err), (0, ''))
        self.assertIn('nothing to change', out)
        self.only_reads_since(mark)

    def test_it_is_refused_while_a_native_game_is_provisioned(self):
        self.prepare()
        templates = ('etc/systemd/system/avrana-game@.socket', 'etc/systemd/system/avrana-game@.service')
        for name in templates:
            self.put(name, b'[Unit]\n')
        (self.root / 'etc/avrana-party/games.d').mkdir()                 # an empty registry and the two shared templates:
        self.assertEqual(self.run_main('--reverse', '--dry-run')[0], 0)  # no game
        for name, what in (('etc/avrana-party/games.d/checkers.json', 'a registry entry'),
                           ('etc/systemd/system/avrana-game@checkers.socket', 'an instance socket unit'),
                           ('etc/systemd/system/avrana-game@checkers.service.d/exec.conf', 'an exec drop-in'),
                           ('etc/systemd/system/sockets.target.wants/avrana-game@checkers.socket', 'an enabled link')):
            with self.subTest(what):
                path = self.put(name, b'{}\n')
                for args in (('--reverse',), ('--reverse', '--dry-run')):
                    out, err = self.refused(*args, why='native games are provisioned here (checkers)')
                    self.assertIn('provision-game <slug> --remove', err)
                self.assertEqual(self.read(UNIT_PATH), UNIT)             # nothing was put back
                path.unlink()
                if path.parent.name.endswith('.service.d'):
                    path.parent.rmdir()
        self.assertEqual(self.run_main('--reverse')[0], 0)               # the game is gone: it goes through

    def test_it_names_every_provisioned_game(self):
        self.prepare()
        self.put('etc/avrana-party/games.d/checkers.json', b'{}')
        self.put('etc/systemd/system/avrana-game@bluff-2.socket', b'')
        out, err = self.refused('--reverse', why='native games are provisioned here (bluff-2, checkers)')

    def test_it_keeps_what_it_overwrites_and_says_when_that_was_changed_after_it_wrote_it(self):
        self.prepare()
        edited = self.read(CONFIG_PATH).replace(b'"secure_cookie": true', b'"secure_cookie": false')
        self.put(CONFIG_PATH, edited)
        rc, out, err = self.run_main('--reverse')
        self.assertEqual((rc, err), (0, ''), out)
        self.assertIn('NOTE: /etc/avrana-party/party-core.json was changed after this command wrote it', out)
        self.assertEqual((self.backups / STAMP / 'replaced' / 'party-core.json').read_bytes(), edited)
        self.assertEqual(self.read(CONFIG_PATH), EARLIER_CONFIG)
        # a unit nobody changed is kept too, without the note
        self.assertTrue((self.backups / STAMP / 'replaced' / 'units' / pn.SERVICE).is_file())
        self.assertNotIn(f'NOTE: /etc/systemd/system/{pn.SERVICE}', out)

    def test_a_failed_party_core_is_started_again_and_a_stopped_one_is_left_alone(self):
        self.prepare()
        self.systemd.active.discard(pn.SERVICE)
        self.systemd.failed.add(pn.SERVICE)
        mark = len(self.systemd.calls)
        self.assertEqual(self.run_main('--reverse')[0], 0)
        calls = self.mutating(self.systemd.calls[mark:])
        self.assertEqual(calls, [['disable', '--now', pn.SOCKET], ['daemon-reload'], ['reset-failed', pn.SERVICE],
                                 ['start', pn.SERVICE]])
        self.assertIn(pn.SERVICE, self.systemd.active)
        self.setUp()
        self.prepare()
        self.systemd.active.discard(pn.SERVICE)                          # stopped on purpose
        mark = len(self.systemd.calls)
        self.assertEqual(self.run_main('--reverse')[0], 0)
        self.assertEqual(self.mutating(self.systemd.calls[mark:]), [['disable', '--now', pn.SOCKET], ['daemon-reload']])

    def test_it_needs_a_before_state_this_command_wrote(self):
        self.refused('--reverse', why='there is no before-state written by this command under')
        stranger = self.root / 'stranger'
        stranger.mkdir()
        self.refused('--reverse', str(stranger), why=f'{stranger} is not a before-state written by this command')
        for name, state in (('another schema', {'schema': 'other', 'files': {}}),
                            ('not an object', ['x']),
                            ('files that are not this command\'s', {'schema': pn.SCHEMA, 'files': {'../../victim': {'existed': False}}})):
            with self.subTest(name):
                (stranger / 'state.json').write_text(json.dumps(state))
                self.refused('--reverse', str(stranger), why='is not a before-state written by this command')

    def test_a_before_state_cannot_send_it_to_a_file_of_its_own_choosing(self):
        victim = self.root / 'victim'
        victim.write_text('keep me\n')
        stranger = self.root / 'stranger'
        stranger.mkdir()
        (stranger / 'state.json').write_text(json.dumps({'schema': pn.SCHEMA, 'files': {str(victim): {'existed': False}}}))
        self.refused('--reverse', str(stranger), why='is not a before-state written by this command')
        self.assertEqual(victim.read_text(), 'keep me\n')

    def test_an_incomplete_before_state_is_refused(self):
        self.prepare()
        (self.backups / STAMP / 'party-core.json').unlink()
        self.refused('--reverse', why='this before-state is incomplete')


class WhatWasKept(Prepared):
    def test_the_previous_unit_and_configuration_are_kept_with_what_each_was(self):
        self.prepare()
        kept = self.backups / STAMP
        self.assertEqual((kept / 'units' / pn.SERVICE).read_bytes(), EARLIER_UNIT)
        self.assertEqual((kept / 'party-core.json').read_bytes(), EARLIER_CONFIG)
        self.assertFalse((kept / 'units' / pn.SOCKET).exists())          # there was none to keep
        state = json.loads((kept / 'state.json').read_text(encoding='utf-8'))
        self.assertEqual(state['schema'], pn.SCHEMA)
        self.assertEqual(sorted(state['files']), sorted(pn.TARGETS))
        self.assertEqual(state['files'][pn.SOCKET_KEY]['existed'], False)
        self.assertEqual(state['files'][pn.UNIT_KEY]['existed'], True)
        self.assertEqual(state['socket'], {'enabled': False, 'active': False})
        self.assertTrue(state['party_core']['restarted'])
        self.assertTrue(all(len(f['wrote']) == 64 for f in state['files'].values()))   # a digest, never the content
        self.assertNotIn('reversed', state)

    def test_a_dry_run_and_a_second_run_keep_nothing_new(self):
        self.run_main('--dry-run')
        self.assertEqual(self.backup_dirs(), [])
        self.prepare()
        self.run_main()
        self.assertEqual(self.backup_dirs(), [STAMP])

    def test_a_run_that_changes_no_file_and_no_unit_keeps_nothing(self):
        self.prepare()
        self.socket_listens_again()                                      # only a restart of Party Core is due
        self.prepare()
        self.assertEqual(self.backup_dirs(), [STAMP])
        state = json.loads((self.backups / STAMP / 'state.json').read_text(encoding='utf-8'))
        self.assertEqual(sorted(state['files']), sorted(pn.TARGETS))     # unchanged: no new entries, no new directory


class Pure(unittest.TestCase):
    def test_what_is_wrong_with_the_internal_socket(self):
        sock = mock.Mock(st_mode=stat.S_IFSOCK | 0o660)
        self.assertEqual(pn.socket_problems(sock, 'avrana-party', 'avrana-games'), [])
        bad = mock.Mock(st_mode=stat.S_IFREG | 0o666)
        problems = pn.socket_problems(bad, 'cody', 'cody')
        self.assertEqual(len(problems), 4)
        for word in ('not a socket', '0666', 'cody, not avrana-party', 'cody, not avrana-games'):
            self.assertTrue(any(word in p for p in problems), word)

    def test_a_link_or_a_directory_is_not_a_file_this_command_replaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'unit'
            path.write_bytes(b'x')
            self.assertEqual(pn.read_optional(path, '/etc/unit'), b'x')
            self.assertIsNone(pn.read_optional(Path(tmp) / 'absent', '/etc/absent'))
            with mock.patch.object(Path, 'is_symlink', return_value=True), self.assertRaises(pn.Refused) as link:
                pn.read_optional(path, '/etc/unit')
            self.assertIn('/etc/unit is a symbolic link', str(link.exception))
            with self.assertRaises(pn.Refused) as directory:
                pn.read_optional(Path(tmp), '/etc/dir')
            self.assertIn('not a regular file', str(directory.exception))

    def test_unit_directive_changes_ignore_comments_and_blank_lines(self):
        old, new = b'# c\n[Unit]\nA=1\n\nB=2\n', b'[Unit]\n# other\nA=1\nB=3\n'
        self.assertEqual(pn.directive_changes(old, new), ['- B=2', '+ B=3'])
        many = pn.directive_changes(b'', b''.join(b'K%d=1\n' % i for i in range(20)), limit=3)
        self.assertEqual(many[-1], '... and 17 more')

    def test_the_two_units_it_installs_are_the_ones_the_repository_ships(self):
        self.assertEqual((pn.SERVICE, pn.SOCKET), ('avrana-party-core.service', 'avrana-party-core.socket'))
        self.assertTrue((SOURCE / pn.SERVICE).is_file() and (SOURCE / pn.SOCKET).is_file())
        self.assertEqual(pn.REGISTRY_DIR, '/etc/avrana-party/games.d')
        self.assertEqual(pn.INTERNAL_SOCKET, '/run/avrana-party/internal.sock')
        self.assertEqual((pn.SOCKET_OWNER, pn.SOCKET_GROUP, pn.SOCKET_MODE), ('avrana-party', 'avrana-games', 0o660))

    def test_a_shielded_section_holds_off_the_signals_and_gives_them_back_when_it_fails(self):
        names = [n for n in ('SIGHUP', 'SIGINT', 'SIGTERM') if hasattr(signal, n)]
        before = {n: signal.getsignal(getattr(signal, n)) for n in names}
        with self.assertRaises(RuntimeError), pn.shielded():
            self.assertEqual({n: signal.getsignal(getattr(signal, n)) for n in names}, {n: signal.SIG_IGN for n in names})
            raise RuntimeError('the section failed')
        self.assertEqual({n: signal.getsignal(getattr(signal, n)) for n in names}, before)

    def test_a_shield_off_the_main_thread_changes_nothing_and_does_not_fail(self):
        ran = []

        def section():
            with pn.shielded():
                ran.append('ran')
        thread = threading.Thread(target=section)
        thread.start()
        thread.join(30)
        self.assertEqual(ran, ['ran'])

    def test_the_command_creates_no_users_and_runs_nothing_but_systemctl(self):
        source = Path(pn.__file__).read_text(encoding='utf-8')
        code = '\n'.join(line for line in source.splitlines() if not line.lstrip().startswith('#'))
        self.assertNotRegex(code.split('"""', 2)[2], r'useradd|groupadd|usermod|adduser|addgroup')
        self.assertEqual(code.count('subprocess.run('), 1)               # only the systemctl seam


class Story(Prepared):
    """The sequence experiments/native-game/prepare-proof.sh runs on real systemd, here on the stand-in:
    the states carry over from one step to the next, which a test of one step at a time does not show."""

    def test_prepare_repeat_edit_session_restart_game_reverse_stopped(self):
        # 1. the earlier host, then the run
        out = self.prepare()
        self.assertIn('Party Core: will be restarted', out)
        started = self.systemd.entered[pn.SERVICE]
        prepared = snapshot(self.root)
        # 2. again: nothing to change, nothing restarted
        mark = len(self.systemd.calls)
        self.assertIn('nothing to change', self.run_main()[1])
        self.only_reads_since(mark)
        self.assertEqual(snapshot(self.root), prepared)
        # 3. a game is provisioned (provision-game's registry entry and units), and the reverse is refused
        self.put('etc/avrana-party/games.d/standin.json', b'{}')
        self.put('etc/systemd/system/avrana-game@standin.socket', b'')
        self.refused('--reverse', why='native games are provisioned here (standin)')
        # 4. the installed socket unit differs from the repository's while a session runs: refused, nothing changed
        edited = SOCKET_UNIT.replace(b'SocketMode=0660', b'SocketMode=0666')
        self.put(SOCKET_PATH, edited)
        self.status.session = {'game': 'standin', 'state': 'active'}
        self.refused('--dry-run', why='a game session is running (standin)')
        self.refused(why='a game session is running (standin)')
        self.assertEqual(self.read(SOCKET_PATH), edited)
        self.assertEqual(self.systemd.entered[pn.SERVICE], started)
        # 5. the session ends: the repository's socket unit comes back, with Party Core stopped around the socket's restart
        self.status.session = {'game': 'standin', 'state': 'ended'}
        mark = len(self.systemd.calls)
        self.prepare()
        self.assertEqual(self.read(SOCKET_PATH), SOCKET_UNIT)
        self.assertEqual(self.mutating(self.systemd.calls[mark:]),
                         [['daemon-reload'], ['stop', pn.SERVICE], ['restart', pn.SOCKET], ['start', pn.SERVICE]])
        self.assertGreater(self.systemd.entered[pn.SERVICE], started)
        self.assertEqual(self.systemd.refusals, [])
        self.assertEqual(self.backup_dirs(), [STAMP])                    # added to the one before-state, not a second
        # 6. the game is removed; the reverse puts back what the host had before the first run, byte for byte
        (self.root / 'etc/avrana-party/games.d/standin.json').unlink()
        (self.root / 'etc/systemd/system/avrana-game@standin.socket').unlink()
        mark = len(self.systemd.calls)
        rc, out, err = self.run_main('--reverse')
        self.assertEqual((rc, err), (0, ''), out)
        self.assertEqual(self.read(UNIT_PATH), EARLIER_UNIT)
        self.assertEqual(self.read(CONFIG_PATH), EARLIER_CONFIG)
        self.assertFalse((self.root / SOCKET_PATH).exists())
        self.assertFalse(self.systemd.node().exists())
        self.assertNotIn(pn.SOCKET, self.systemd.enabled | self.systemd.active)
        self.assertEqual(self.mutating(self.systemd.calls[mark:]), [['disable', '--now', pn.SOCKET], ['daemon-reload']])
        self.assertIn(pn.SERVICE, self.systemd.active)
        self.assertNotEqual(self.systemd(['reload', pn.SERVICE]).rc, 0)  # the earlier state: a reload is refused again
        self.assertIn('nothing to reverse', self.run_main('--reverse')[1])
        # 7. Party Core is stopped for maintenance: prepared again it is left stopped, with a new before-state
        self.systemd.active.discard(pn.SERVICE)
        out = self.prepare()
        self.assertIn('Party Core: will not be restarted: it is not running (inactive)', out)
        self.assertNotIn(pn.SERVICE, self.systemd.active)
        self.assertEqual(len(self.backup_dirs()), 2)
        # 8. it starts by hand, takes the socket, and a run then has nothing to change
        self.systemd.start(pn.SERVICE)
        mark = len(self.systemd.calls)
        self.assertIn('nothing to change', self.run_main()[1])
        self.only_reads_since(mark)
        # 9. and the reverse of that period puts the earlier files back again
        self.assertEqual(self.run_main('--reverse')[0], 0)
        self.assertEqual(self.read(UNIT_PATH), EARLIER_UNIT)
        self.assertEqual(self.read(CONFIG_PATH), EARLIER_CONFIG)


@unittest.skipUnless(POSIX and shutil.which('bash'), 'a shim and a wrapper need POSIX and bash')
class CommandLine(Prepared):
    """The overrides the command reads from the environment, through a real process."""
    SHIM = ('#!/usr/bin/env python3\nimport os, sys\n'
            'open(os.environ["SHIM_LOG"], "a").write(" ".join(sys.argv[1:]) + "\\n")\n'
            'verb = sys.argv[1]\n'
            'if verb == "is-active": print("inactive"); sys.exit(3)\n'
            'if verb == "is-enabled": print("disabled"); sys.exit(1)\n'
            'if verb == "show": print("no" if "NeedDaemonReload" in sys.argv else "0"); sys.exit(0)\n'
            'sys.exit(0)\n')

    def test_a_dry_run_through_a_process_with_a_recording_systemctl(self):
        shim = self.root / 'systemctl'
        shim.write_text(self.SHIM)
        shim.chmod(0o755)
        log = self.root / 'systemctl.log'
        env = dict(os.environ, AVRANA_ROOT=str(self.root), AVRANA_SYSTEMCTL=str(shim), SHIM_LOG=str(log))
        before = snapshot(self.root)
        r = subprocess.run([sys.executable, '-m', 'avrana.ops.prepare_native_games', '--dry-run'], cwd=REPO_ROOT, env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('Party Core: will not be restarted: it is not running (inactive)', r.stdout)
        self.assertIn('dry run: nothing changed', r.stdout)
        verbs = {line.split()[0] for line in log.read_text().splitlines()}
        self.assertLessEqual(verbs, READ_ONLY)
        self.assertEqual({k: v for k, v in snapshot(self.root).items() if k not in ('systemctl', 'systemctl.log')},
                         {k: v for k, v in before.items() if k not in ('systemctl', 'systemctl.log')})

    def test_the_wrapper_runs_the_module_from_the_tree_it_is_in(self):
        wrapper = REPO_ROOT / 'ops' / 'prepare-native-games'
        self.assertEqual(subprocess.run(['bash', '-n', str(wrapper)]).returncode, 0)
        self.assertTrue(os.access(wrapper, os.X_OK))
        if not shutil.which('python3'):
            self.skipTest('python3 is not on PATH')
        r = subprocess.run(['bash', str(wrapper), '--help'], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('--reverse', r.stdout)
        self.assertIn('--dry-run', r.stdout)


if __name__ == '__main__':
    unittest.main()
