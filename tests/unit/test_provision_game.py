"""provision_game's core against ADR 0016 section 8, on a scratch directory with a recorded
systemctl. Real systemd (socket activation, LoadCredential, DynamicUser) is the Linux CI job's."""
import io
import json
import os
import stat
import tempfile
import unittest
import urllib.error
from pathlib import Path

from avrana import REPO_ROOT
from avrana.contracts import appliance
from avrana.ops import provision_game as pg
from avrana.party import protocol, registry

RUNTIME = {'command': ['/opt/games/checkers/run', '--port', 'x y'], 'working_directory': '/opt/games/checkers'}
CONTRACTS = {'checkers': {'id': 'checkers'}, 'bluff': {'id': 'bluff'}}
GRANTS = {'checkers': {'game': 'checkers', 'runtime': RUNTIME}}
BLUFF = {'bluff': {'game': 'bluff', 'runtime': RUNTIME}}
TEMPLATES = REPO_ROOT / 'deploy' / 'games'
FIRST = ['key', 'registry', 'unit avrana-game@.socket', 'unit avrana-game@.service', 'dropin']
PROVISIONED = ['etc/game-keys/checkers.key', 'etc/games.d/checkers.json', 'etc/systemd/avrana-game@.service',
               'etc/systemd/avrana-game@.socket', 'etc/systemd/avrana-game@checkers.service.d/exec.conf']
ORIGIN = 'https://party.example.test'
STATUS_IDLE ={'party_core': {'ok': True, 'uptime_s': 3, 'members': 0, 'session': None}}


def status_with(game, state='active'):
    return {'party_core': {'ok': True, 'uptime_s': 3, 'members': 2, 'session': {'game': game, 'state': state}}}


class Response:
    def __init__(self, doc):
        self.body = json.dumps(doc).encode('utf-8')

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.body


class Provisioning(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.layout = pg.Layout(key_dir=root / 'etc/game-keys', registry_dir=root / 'etc/games.d',
                                socket_dir=root / 'run/avrana-games', state_dir=root / 'var/avrana-games',
                                unit_dir=root / 'etc/systemd', template_dir=TEMPLATES)
        self.root = root
        self.calls, self.owned = [], []

    def run_(self, argv):
        self.calls.append(argv)

    def own(self, target):
        """Records what `own` was handed: the directory by path, the key by OPEN DESCRIPTOR (an
        int: nothing can be swapped under it), recorded as ('fd', inode of that file)."""
        self.owned.append(('fd', os.fstat(target).st_ino) if isinstance(target, int) else Path(target))

    def provision(self, slug='checkers', **kw):
        return pg.provision(slug, self.layout, CONTRACTS, GRANTS, self.run_, self.own, ORIGIN, **kw)

    def tree(self):
        return sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob('*') if p.is_file())

    def test_create_makes_a_private_key_a_registry_entry_and_enables_the_socket(self):
        self.assertEqual(self.provision(), FIRST)
        key = self.layout.key('checkers')
        self.assertEqual(len(protocol.read_key(key)), 32)                 # the loader accepts it
        if os.name == 'posix':
            self.assertEqual(stat.S_IMODE(key.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(key.parent.stat().st_mode), 0o700)
        self.assertEqual(self.owned, [key.parent, self.owned[1]])        # the directory, then the key
        self.assertEqual(self.owned[1][0], 'fd')                         # the key by descriptor, never by name
        if os.name == 'posix':
            self.assertEqual(self.owned[1][1], key.stat().st_ino)        # that descriptor was the file now in place
        self.assertEqual(self.tree(), PROVISIONED)
        entry = json.loads(self.layout.entry('checkers').read_text(encoding='utf-8'))
        self.assertEqual(entry, {'id': 'checkers', 'socket': self.layout.socket('checkers').as_posix(),
                                 'key_file': key.as_posix()})
        # Party Core's own reader takes the directory as written
        if os.name == 'posix':                 # the reader wants "/…"; a Windows scratch path is "C:/…"
            self.assertEqual(registry.read_directory(self.layout.registry_dir), {'checkers': entry})
        self.assertEqual(self.calls, [['systemctl', 'daemon-reload'],
                                      ['systemctl', 'enable', '--now', 'avrana-game@checkers.socket'],
                                      ['systemctl', 'reload', 'avrana-party-core.service']])
        # no user or group is created, and Party Core is never restarted
        flat = ' '.join(' '.join(c) for c in self.calls)
        self.assertNotRegex(flat, r'useradd|groupadd|adduser|restart')

    def test_a_second_run_changes_nothing_and_keeps_the_key(self):
        self.provision()
        key, entry = self.layout.key('checkers').read_bytes(), self.layout.entry('checkers').read_bytes()
        self.calls.clear()
        self.owned.clear()
        self.assertEqual(self.provision(), [])
        self.assertEqual((self.layout.key('checkers').read_bytes(), self.layout.entry('checkers').read_bytes()), (key, entry))
        # nothing written, no daemon-reload; but the socket is enabled and Party Core reloaded every
        # run, so a run that failed half way is repaired by running again
        self.assertEqual(self.calls, [['systemctl', 'enable', '--now', 'avrana-game@checkers.socket'],
                                      ['systemctl', 'reload', 'avrana-party-core.service']])
        self.assertEqual(self.owned, [])

    def test_a_failed_run_is_repaired_by_running_again(self):
        import subprocess

        def failing(argv):
            if argv[1] == 'enable':
                raise subprocess.CalledProcessError(1, argv)
            self.calls.append(argv)
        with self.assertRaises(subprocess.CalledProcessError):
            pg.provision('checkers', self.layout, CONTRACTS, GRANTS, failing, self.own, ORIGIN)
        self.assertEqual(self.tree(), PROVISIONED)                      # everything was written, nothing reloaded
        self.assertNotIn(['systemctl', 'reload', 'avrana-party-core.service'], self.calls)
        self.calls.clear()
        self.assertEqual(self.provision(), [])                           # the change list is unchanged: nothing to write
        self.assertEqual(self.calls, [['systemctl', 'enable', '--now', 'avrana-game@checkers.socket'],
                                      ['systemctl', 'reload', 'avrana-party-core.service']])

    def test_reconcile_rewrites_a_drifted_entry_and_keeps_key_and_state(self):
        self.provision()
        key = self.layout.key('checkers').read_bytes()
        state = self.layout.state('checkers')
        state.mkdir(parents=True)
        (state / 'save.json').write_text('{}', encoding='utf-8')
        self.layout.entry('checkers').write_text('{"id": "checkers", "socket": "/elsewhere"}', encoding='utf-8')
        self.calls.clear()
        self.assertEqual(self.provision(timeout=8), ['registry'])
        self.assertEqual(json.loads(self.layout.entry('checkers').read_text(encoding='utf-8'))['timeout'], 8)
        self.assertEqual(self.layout.key('checkers').read_bytes(), key)
        self.assertTrue((state / 'save.json').exists())
        self.assertIn(['systemctl', 'reload', 'avrana-party-core.service'], self.calls)

    def test_refuses_a_slug_with_no_contract_or_no_grant_and_touches_nothing(self):
        for slug, why in (('nosuch', 'no Game Contract'), ('bluff', 'no grant'), ('Checkers', 'not a game id'),
                          ('../x', 'not a game id'), ('a' * 41, 'not a game id'), (None, 'not a game id')):
            with self.assertRaises(pg.Refused) as e:
                self.provision(slug)
            self.assertIn(why, str(e.exception), slug)
        self.assertEqual((self.tree(), self.calls), ([], []))

    def test_rotate_replaces_only_the_key_and_is_refused_during_a_session(self):
        self.provision()
        before = self.layout.key('checkers').read_bytes()
        entry = self.layout.entry('checkers').read_bytes()
        self.calls.clear()
        asked = []
        with self.assertRaises(pg.Refused) as e:
            pg.rotate('checkers', self.layout, CONTRACTS, GRANTS, self.run_, self.own, lambda s: asked.append(s) or True)
        self.assertIn('session running', str(e.exception))
        self.assertEqual((asked, self.layout.key('checkers').read_bytes(), self.calls), (['checkers'], before, []))
        self.assertEqual(pg.rotate('checkers', self.layout, CONTRACTS, GRANTS, self.run_, self.own, lambda s: False), ['key'])
        after = self.layout.key('checkers').read_bytes()
        self.assertNotEqual(after, before)
        self.assertEqual(len(protocol.read_key(self.layout.key('checkers'))), 32)
        self.assertEqual(self.layout.entry('checkers').read_bytes(), entry)
        self.assertEqual(self.calls, [['systemctl', 'stop', 'avrana-game@checkers.service'],
                                      ['systemctl', 'reload', 'avrana-party-core.service']])
        self.assertEqual(self.tree(), PROVISIONED)                                       # no stray temp file
        with self.assertRaises(pg.Refused):
            pg.rotate('bluff', self.layout, CONTRACTS, BLUFF, self.run_, self.own, lambda s: False)   # never provisioned

    def test_remove_leaves_nothing_for_the_slug_and_nothing_else_is_touched(self):
        self.provision()
        pg.provision('bluff', self.layout, CONTRACTS, BLUFF, self.run_, self.own, ORIGIN)
        for slug in ('checkers', 'bluff'):
            self.layout.state(slug).mkdir(parents=True)
            (self.layout.state(slug) / 'save.json').write_text('{}', encoding='utf-8')
            self.layout.socket(slug).parent.mkdir(parents=True, exist_ok=True)
            self.layout.socket(slug).write_text('', encoding='utf-8')
        self.calls.clear()
        seen = []

        def snapshot(argv):                 # which of the game's files exist at each systemctl call
            self.calls.append(argv)
            seen.append((argv[1], self.layout.entry('checkers').exists(), self.layout.key('checkers').exists()))
        self.assertEqual(pg.remove('checkers', self.layout, snapshot), ['registry', 'dropin', 'key', 'socket', 'state'])
        # (call, registry entry exists, key exists): the entry is gone before Party reloads, and the
        # key is still there at that first reload; at the last reload both are gone
        self.assertEqual(seen, [('disable', True, True), ('stop', True, True), ('reload', False, True),
                                ('reload', False, False), ('daemon-reload', False, False)])
        self.assertEqual([p for p in self.tree() if 'checkers' in p], [])
        self.assertFalse(self.layout.state('checkers').exists())
        self.assertFalse(self.layout.dropin_dir('checkers').exists())
        # the shared templates stay, and so does everything of the other game
        self.assertEqual(self.tree(), ['etc/game-keys/bluff.key', 'etc/games.d/bluff.json', 'etc/systemd/avrana-game@.service',
                                       'etc/systemd/avrana-game@.socket', 'etc/systemd/avrana-game@bluff.service.d/exec.conf',
                                       'run/avrana-games/bluff.sock', 'var/avrana-games/bluff/save.json'])
        self.assertEqual(self.calls, [['systemctl', 'disable', '--now', 'avrana-game@checkers.socket'],
                                      ['systemctl', 'stop', 'avrana-game@checkers.service'],
                                      ['systemctl', 'reload', 'avrana-party-core.service'],
                                      ['systemctl', 'reload', 'avrana-party-core.service'],
                                      ['systemctl', 'daemon-reload']])
        # the entry goes before the key, so Party Core never reloads onto an entry with no key
        self.assertEqual(pg.remove('checkers', self.layout, self.run_), [])             # again: nothing left

    def test_remove_is_refused_during_that_games_session_before_anything_is_stopped(self):
        self.provision()
        before = self.tree()
        self.calls.clear()
        asked = []
        for fn in (lambda a: pg.remove('checkers', self.layout, self.run_, active=a),
                   lambda a: pg.plan_remove('checkers', self.layout, active=a)):
            with self.assertRaisesRegex(pg.Refused, 'has a session running; end it from Party Home first'):
                fn(lambda slug: asked.append(slug) or True)
        self.assertEqual((asked, self.calls, self.tree()), (['checkers', 'checkers'], [], before))
        self.assertEqual(pg.remove('checkers', self.layout, self.run_, active=lambda slug: False),
                         ['registry', 'dropin', 'key'])

    def test_a_stopped_party_core_is_not_a_failed_reload_but_a_running_one_that_refuses_is(self):
        import subprocess
        for stopped in (True, False):
            for step in ('provision', 'rotate', 'remove'):
                with self.subTest(stopped=stopped, step=step):
                    calls = []

                    def run(argv):
                        calls.append(argv)
                        if argv[1] == 'reload' or (argv[1] == 'is-active' and stopped):
                            raise subprocess.CalledProcessError(3, argv)
                    if step != 'provision':
                        self.provision()
                    do = {'provision': lambda r: pg.provision('checkers', self.layout, CONTRACTS, GRANTS, r, self.own, ORIGIN),
                          'rotate': lambda r: pg.rotate('checkers', self.layout, CONTRACTS, GRANTS, r, self.own, lambda s: False),
                          'remove': lambda r: pg.remove('checkers', self.layout, r)}[step]
                    if stopped:
                        do(run)                              # Party Core reads the registry when it starts
                        self.assertIn(['systemctl', 'is-active', '--quiet', 'avrana-party-core.service'], calls)
                    else:
                        with self.assertRaises(subprocess.CalledProcessError) as caught:
                            do(run)
                        self.assertEqual(caught.exception.cmd[:2], ['systemctl', 'reload'])
                    pg.remove('checkers', self.layout, self.run_)

    def test_party_core_is_asked_directly_never_through_an_environment_proxy(self):
        import urllib.request
        from unittest import mock
        with mock.patch.object(urllib.request, 'build_opener') as build:
            build.return_value.open.return_value = 'reply'
            self.assertEqual(pg._direct_open('http://127.0.0.1:8191/x', 3), 'reply')
        (handler,), _ = build.call_args
        self.assertEqual((type(handler), handler.proxies), (urllib.request.ProxyHandler, {}))

    def test_a_second_remove_still_reloads_party_core_and_tolerates_a_failed_reload(self):
        import subprocess
        self.provision()
        pg.remove('checkers', self.layout, self.run_)
        self.calls.clear()
        self.assertEqual(pg.remove('checkers', self.layout, self.run_), [])             # nothing left, but Party reloads
        self.assertEqual(self.calls, [['systemctl', 'disable', '--now', 'avrana-game@checkers.socket'],
                                      ['systemctl', 'stop', 'avrana-game@checkers.service'],
                                      ['systemctl', 'reload', 'avrana-party-core.service'],
                                      ['systemctl', 'daemon-reload']])
        calls = []

        def reload_fails(argv):
            calls.append(argv)
            if argv[1] == 'reload':
                raise subprocess.CalledProcessError(1, argv)
        self.assertEqual(pg.remove('checkers', self.layout, reload_fails), [])
        self.assertEqual(calls[-1], ['systemctl', 'daemon-reload'])                      # the rest still goes

    def test_rotate_fails_when_stop_or_reload_fails_and_a_plain_rerun_reloads(self):
        import subprocess
        self.provision()
        for failing in ('stop', 'reload'):
            def run(argv, failing=failing):
                if argv[1] == failing:
                    raise subprocess.CalledProcessError(1, argv)
                self.calls.append(argv)
            with self.assertRaises(subprocess.CalledProcessError, msg=failing):
                pg.rotate('checkers', self.layout, CONTRACTS, GRANTS, run, self.own, lambda s: False)
            self.calls.clear()
            self.assertEqual(self.provision(), [])
            self.assertIn(['systemctl', 'reload', 'avrana-party-core.service'], self.calls)   # I3's repair

    def test_remove_can_keep_the_state_directory_and_needs_no_contract(self):
        self.provision()
        self.layout.state('checkers').mkdir(parents=True)
        (self.layout.state('checkers') / 'save.json').write_text('{}', encoding='utf-8')
        self.assertEqual(pg.remove('checkers', self.layout, self.run_, keep_state=True), ['registry', 'dropin', 'key'])
        self.assertEqual([p for p in self.tree() if 'checkers' in p], ['var/avrana-games/checkers/save.json'])
        with self.assertRaises(pg.Refused):
            pg.remove('../etc', self.layout, self.run_)

    def test_the_layout_has_no_default_path(self):
        with self.assertRaises(TypeError):
            pg.Layout()

    def test_the_templates_are_installed_0644_and_refreshed_when_they_drift(self):
        self.provision()
        socket_unit = Path(self.layout.unit_dir) / 'avrana-game@.socket'
        self.assertEqual(socket_unit.read_bytes(), (TEMPLATES / 'avrana-game@.socket').read_bytes())
        if os.name == 'posix':
            self.assertEqual(stat.S_IMODE(socket_unit.stat().st_mode), 0o644)
            self.assertEqual(stat.S_IMODE(self.layout.dropin('checkers').stat().st_mode), 0o644)
        socket_unit.write_text('# drifted\n', encoding='utf-8')
        self.calls.clear()
        self.assertEqual(self.provision(), ['unit avrana-game@.socket'])
        self.assertEqual(socket_unit.read_bytes(), (TEMPLATES / 'avrana-game@.socket').read_bytes())
        self.assertEqual(self.calls, [['systemctl', 'daemon-reload'],
                                      ['systemctl', 'enable', '--now', 'avrana-game@checkers.socket'],
                                      ['systemctl', 'reload', 'avrana-party-core.service']])

    def test_a_changed_runtime_rewrites_only_the_dropin_and_restarts_nothing(self):
        self.provision()
        self.calls.clear()
        grants = {'checkers': {'game': 'checkers', 'runtime': dict(RUNTIME, working_directory='/srv/checkers')}}
        self.assertEqual(pg.provision('checkers', self.layout, CONTRACTS, grants, self.run_, self.own, ORIGIN), ['dropin'])
        self.assertIn('WorkingDirectory=/srv/checkers\n', self.layout.dropin('checkers').read_text(encoding='utf-8'))
        self.assertEqual(self.calls, [['systemctl', 'daemon-reload'],
                                      ['systemctl', 'enable', '--now', 'avrana-game@checkers.socket'],
                                      ['systemctl', 'reload', 'avrana-party-core.service']])
        self.assertNotRegex(' '.join(' '.join(c) for c in self.calls), r'restart|stop|start ')

    def test_a_grant_without_runtime_is_refused_before_anything_is_written(self):
        for grants in ({'checkers': {'game': 'checkers'}}, {'checkers': {'runtime': {'command': ['x'], 'working_directory': '/'}}},
                       {'checkers': {'runtime': dict(RUNTIME, command=['/bin/x', 'a\nExecStart=/bin/sh'])}}):
            with self.assertRaises(pg.Refused):
                pg.provision('checkers', self.layout, CONTRACTS, grants, self.run_, self.own, ORIGIN)
        self.assertEqual((self.tree(), self.calls, self.owned), ([], [], []))

    def test_the_dropin_text_for_an_example(self):
        self.provision()
        self.assertEqual(self.layout.dropin('checkers').read_text(encoding='utf-8'),
                         '# Written by provision-game from the appliance grant (AVR-236). Edits are overwritten.\n'
                         '[Service]\n'
                         'ExecStart="/opt/games/checkers/run" "--port" "x y"\n'
                         'WorkingDirectory=/opt/games/checkers\n'
                         'Environment=AVRANA_PARTY_ORIGIN=https://party.example.test\n')

    def test_the_dropin_quotes_for_systemd(self):
        text = pg.dropin_text({'command': ['/bin/g', 'a b', '100%', 'cost $HOME', 'say "hi"', 'back\\slash'],
                               'working_directory': '/srv/50%'}, ORIGIN)
        self.assertIn('ExecStart="/bin/g" "a b" "100%%" "cost $$HOME" "say \\"hi\\"" "back\\\\slash"\n', text)
        self.assertIn('WorkingDirectory=/srv/50%%\n', text)
        for bad in ('a\nb', 'a\rb', 'a\x00b', 'a\tb'):
            with self.assertRaises(pg.Refused):
                pg.dropin_text({'command': ['/bin/g', bad], 'working_directory': '/'}, ORIGIN)

    def test_the_party_origin_is_in_the_dropin_a_change_rewrites_it_and_nothing_else_changes(self):
        self.provision()
        self.calls.clear()
        other = 'http://10.0.0.142:8080'
        self.assertEqual(pg.plan_provision('checkers', self.layout, CONTRACTS, GRANTS, other), ['dropin'])
        self.assertEqual(pg.provision('checkers', self.layout, CONTRACTS, GRANTS, self.run_, self.own, other), ['dropin'])
        self.assertIn(f'\nEnvironment=AVRANA_PARTY_ORIGIN={other}\n', self.layout.dropin('checkers').read_text(encoding='utf-8'))
        self.assertNotRegex(' '.join(' '.join(c) for c in self.calls), r'restart|stop|start ')
        self.calls.clear()
        self.assertEqual(pg.provision('checkers', self.layout, CONTRACTS, GRANTS, self.run_, self.own, other), [])

    def test_an_origin_that_is_not_bare_is_refused_before_anything_is_written(self):
        for bad in ('', 'party.example.test', 'ftp://party.example.test', 'https://party.example.test/', 'https://party.example.test/x',
                    'https://party.example.test?a=1', 'https://party.example.test#f', 'https://u@party.example.test',
                    'https://party.example.test:99999', 'https://party.example.test:0', 'https://party.example.test\n',
                    'https://party.example.test\nExecStart=/bin/sh', 'https://party .example.test', 'https://par%ty.test',
                    'https://pa$ty.test', 'https://party.example.test"', 'https://', None, 7):
            with self.assertRaises(pg.Refused, msg=repr(bad)):
                pg.provision('checkers', self.layout, CONTRACTS, GRANTS, self.run_, self.own, bad)
            with self.assertRaises(pg.Refused, msg=repr(bad)):
                pg.plan_provision('checkers', self.layout, CONTRACTS, GRANTS, bad)
        self.assertEqual((self.tree(), self.calls, self.owned), ([], [], []))
        for good in ('https://party.avrana.net', 'http://10.0.0.142', 'https://p.example.test:8443'):
            self.assertEqual(pg.bare_origin(good), good)

    def test_the_party_origin_is_the_one_usable_entry_of_the_core_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            conf = Path(tmp) / 'party-core.json'
            conf.write_text(json.dumps({'origins': ['https://party.avrana.net', 'https://party.avrana.net']}), encoding='utf-8')
            self.assertEqual(pg.party_origin(conf), 'https://party.avrana.net')
            conf.write_text(json.dumps({'origins': ['https://party.avrana.net', 'http://10.0.0.142']}), encoding='utf-8')
            with self.assertRaisesRegex(pg.Refused, 'party-core.json.*more than one Party origin'):
                pg.party_origin(conf)                    # a game is told exactly one; no guessing
            for loose in ('https://PARTY.avrana.net', 'https://party.avrana.net:443', 'http://10.0.0.142:80',
                          'http://10.0.0.142:080', 'https://party.avrana.net.'):
                self.assertIsNone(pg.bare_origin(loose), loose)   # never what a browser calls the origin
            conf.write_text(json.dumps({'origins': ['https://x.test/y', 7, 'junk', 'http://10.0.0.142:8080/', 'http://10.0.0.142']}),
                            encoding='utf-8')
            self.assertEqual(pg.party_origin(conf), 'http://10.0.0.142')
            for doc in ({}, {'origins': []}, {'origins': 'https://party.avrana.net'}, {'origins': ['x', 'https://a.test/p']}, [], 'x'):
                conf.write_text(json.dumps(doc), encoding='utf-8')
                with self.assertRaisesRegex(pg.Refused, 'party-core.json.*no usable "origins"'):
                    pg.party_origin(conf)
            conf.write_text('{', encoding='utf-8')
            with self.assertRaisesRegex(pg.Refused, 'unreadable'):
                pg.party_origin(conf)
            with self.assertRaisesRegex(pg.Refused, 'unreadable'):
                pg.party_origin(Path(tmp) / 'absent.json')

    def test_dry_run_plans_the_same_changes_and_changes_nothing(self):
        self.assertEqual(pg.plan_provision('checkers', self.layout, CONTRACTS, GRANTS, ORIGIN), FIRST)
        self.assertEqual((self.tree(), self.calls), ([], []))
        self.provision()
        self.assertEqual(pg.plan_provision('checkers', self.layout, CONTRACTS, GRANTS, ORIGIN), [])
        self.assertEqual(pg.plan_remove('checkers', self.layout), ['registry', 'dropin', 'key'])
        self.assertEqual(pg.plan_remove('checkers', self.layout, keep_state=True), ['registry', 'dropin', 'key'])
        self.assertEqual(len(self.tree()), len(PROVISIONED))


class SessionQuery(unittest.TestCase):
    def test_the_parser_reads_the_real_status_shape(self):
        self.assertIsNone(pg.session_game(STATUS_IDLE))
        self.assertEqual(pg.session_game(status_with('checkers', 'launching')), 'checkers')
        self.assertEqual(pg.session_game(status_with('checkers', 'ending')), 'checkers')
        self.assertIsNone(pg.session_game(status_with('checkers', 'ended')))      # "current or most recent"
        for bad in (None, [], {}, {'party_core': {'ok': False}}, {'party_core': {'ok': True}},
                    {'party_core': {'ok': True, 'session': 'x'}}, {'party_core': {'ok': True, 'session': {'state': 'active'}}}):
            with self.assertRaises(pg.Refused, msg=repr(bad)):
                pg.session_game(bad)

    def test_the_parser_accepts_what_party_core_actually_builds(self):
        """The document comes from avrana/ops/status.py: build_status merges core_view() into
        `party_core`, with session {"game": id, "state": state} or None."""
        from avrana.ops import status
        for session, want in (({'game': 'checkers', 'state': 'active'}, 'checkers'), (None, None)):
            doc = status.build_status(config=None, probes=None, party_core=lambda: {
                'uptime_s': 1, 'members': 0, 'session': session})
            self.assertEqual(doc['party_core']['session'], session)
            self.assertEqual(pg.session_game(doc), want)

    def test_the_checker_asks_loopback_and_only_refuses_for_its_own_game(self):
        asked = []

        def opener(url, timeout):
            asked.append(url)
            return Response(status_with('bluff'))
        active = pg.party_session_check('http://127.0.0.1:8191/', opener)
        self.assertFalse(active('checkers'))
        self.assertTrue(active('bluff'))
        self.assertEqual(asked[0], 'http://127.0.0.1:8191/party/api/status')

    def test_remove_goes_on_when_systemd_no_longer_knows_the_units(self):
        """A second remove, or one after a half-finished one: systemctl fails on units that are
        gone, and what is left must still be taken away (the real-systemd proof found exit 1)."""
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            layout = pg.Layout(key_dir=root / 'keys', registry_dir=root / 'games.d', socket_dir=root / 'run',
                               state_dir=root / 'lib' / 'avrana-games', unit_dir=root / 'units',
                               template_dir=REPO_ROOT / 'deploy' / 'games')
            layout.key('checkers').parent.mkdir(parents=True)
            layout.key('checkers').write_text('k', encoding='utf-8')
            calls = []

            def run(argv):
                calls.append(argv)
                if argv[1] in ('disable', 'stop'):
                    raise subprocess.CalledProcessError(5, argv)
            self.assertEqual(pg.remove('checkers', layout, run), ['key'])
            self.assertEqual(pg.remove('checkers', layout, run), [])
            self.assertEqual(calls[-1], ['systemctl', 'daemon-reload'])

    def test_remove_takes_a_dynamic_user_state_directory_and_its_link(self):
        """systemd keeps a DynamicUser= unit's state under private/ and links to it (the first run
        on real systemd found rmtree refusing the link)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            layout = pg.Layout(key_dir=root / 'keys', registry_dir=root / 'games.d', socket_dir=root / 'run',
                               state_dir=root / 'lib' / 'avrana-games', unit_dir=root / 'units',
                               template_dir=REPO_ROOT / 'deploy' / 'games')
            public, private = layout.state_paths('checkers')
            self.assertEqual(private, root / 'lib' / 'private' / 'avrana-games' / 'checkers')
            private.mkdir(parents=True)
            (private / 'save').write_text('x', encoding='utf-8')
            public.parent.mkdir(parents=True)
            try:
                public.symlink_to(private, target_is_directory=True)
            except OSError:
                self.skipTest('this account cannot create symbolic links')
            self.assertEqual(pg.plan_remove('checkers', layout, keep_state=True), [])
            self.assertEqual(pg.remove('checkers', layout, lambda argv: None, keep_state=True), [])
            self.assertTrue(private.exists())
            self.assertEqual(pg.plan_remove('checkers', layout), ['state'])
            self.assertEqual(pg.remove('checkers', layout, lambda argv: None), ['state'])
            self.assertFalse(public.is_symlink() or public.exists() or private.exists())

    def test_provisioning_is_refused_when_party_core_does_not_read_the_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            conf, registry = Path(tmp) / 'party-core.json', Path(tmp) / 'games.d'
            with self.assertRaisesRegex(pg.Refused, 'unreadable'):
                pg.check_party_reads(conf, registry)
            for doc in ({}, {'registry': None}, {'registry': str(registry) + 'x'}, []):
                conf.write_text(json.dumps(doc), encoding='utf-8')
                with self.assertRaisesRegex(pg.Refused, 'does not name the registry'):
                    pg.check_party_reads(conf, registry)
            conf.write_text(json.dumps({'registry': str(registry)}), encoding='utf-8')
            pg.check_party_reads(conf, registry)

    def test_the_query_names_the_host_party_core_answers_for(self):
        with tempfile.TemporaryDirectory() as tmp:
            conf = Path(tmp) / 'party-core.json'
            self.assertIsNone(pg.party_host(conf))
            for hosts in (None, [], [7], ['bad host']):
                conf.write_text(json.dumps({'hosts': hosts}), encoding='utf-8')
                self.assertIsNone(pg.party_host(conf))
            conf.write_text(json.dumps({'hosts': ['party.avrana.net', '10.42.0.1']}), encoding='utf-8')
            self.assertEqual(pg.party_host(conf), 'party.avrana.net')
        asked = []

        def opener(request, timeout):
            asked.append(request)
            return Response(status_with('bluff'))
        self.assertTrue(pg.party_session_check('http://127.0.0.1:8191', opener, host='party.avrana.net')('bluff'))
        self.assertEqual(asked[0].full_url, 'http://127.0.0.1:8191/party/api/status')
        self.assertEqual(asked[0].get_header('Host'), 'party.avrana.net')

    def test_a_no_session_answer_is_asked_again_after_the_status_cache(self):
        """Party Core's status is cached for a few seconds: a launch can be newer than the first
        answer. With `settle`, only two "no session" answers in a row let a rotation go on."""
        answers, slept = [status_with('bluff'), status_with('checkers')], []

        def opener(url, timeout):
            return Response(answers.pop(0))
        active = pg.party_session_check('http://x', opener, settle=6.0, sleep=slept.append)
        self.assertTrue(active('checkers'))                  # the second look saw the launch
        self.assertEqual(slept, [6.0])
        answers[:] = [status_with('checkers')]
        self.assertTrue(active('checkers'))                  # seen at once: no wait
        self.assertEqual(slept, [6.0])
        answers[:] = [status_with('bluff'), status_with('bluff')]
        self.assertFalse(active('checkers'))
        self.assertEqual(slept, [6.0, 6.0])
        self.assertGreater(pg.STATUS_SETTLE_S, __import__('avrana.ops.status', fromlist=['x']).CACHE_S)

        def down(url, timeout):
            raise urllib.error.URLError(ConnectionRefusedError())
        self.assertFalse(pg.party_session_check('http://x', down, settle=6.0, sleep=slept.append)('checkers'))
        self.assertEqual(slept, [6.0, 6.0])                  # nobody there: no party, no wait

    def test_unreachable_means_no_session_but_unreadable_is_refused(self):
        def down(url, timeout):
            raise urllib.error.URLError(ConnectionRefusedError())

        def bare_down(url, timeout):
            raise ConnectionRefusedError()

        def broken(url, timeout):
            raise urllib.error.HTTPError(url, 500, 'x', {}, None)
        self.assertFalse(pg.party_session_check('http://x', down)('checkers'))          # nobody is listening
        self.assertFalse(pg.party_session_check('http://x', bare_down)('checkers'))
        with self.assertRaises(pg.Refused):
            pg.party_session_check('http://x', broken)('checkers')

        class Junk(Response):
            body = b'<html>'
        with self.assertRaises(pg.Refused):
            pg.party_session_check('http://x', lambda url, timeout: Junk({}))('checkers')


    def test_a_timeout_or_any_other_failure_is_refused_not_taken_for_no_party(self):
        """Party Core may be there and busy (an uncached status build takes seconds): only a
        refused connection means nobody is listening."""
        import socket
        for name, exc, text in (('bare timeout', TimeoutError(), 'did not answer in time'),
                                ('socket.timeout', socket.timeout(), 'did not answer in time'),
                                ('URLError timeout', urllib.error.URLError(TimeoutError()), 'did not answer in time'),
                                ('URLError socket.timeout', urllib.error.URLError(socket.timeout()), 'did not answer in time'),
                                ('reset', ConnectionResetError(), 'ConnectionResetError'),
                                ('unreachable', urllib.error.URLError(OSError(113, 'no route')), 'OSError'),
                                ('dns', urllib.error.URLError(socket.gaierror(-2, 'x')), 'gaierror'),
                                ('other OSError', OSError('x'), 'OSError')):
            def opener(url, timeout, exc=exc):
                raise exc
            with self.assertRaises(pg.Refused, msg=name) as e:
                pg.party_session_check('http://x', opener)('checkers')
            self.assertIn(text, str(e.exception), name)
            self.assertIn('not rotating', str(e.exception), name)

    def test_the_query_waits_long_enough_for_an_uncached_status_build(self):
        seen = []

        def opener(url, timeout):
            seen.append(timeout)
            return Response(STATUS_IDLE)
        pg.party_session_check('http://x', opener)('checkers')
        self.assertEqual(seen, [10])


class Hardening(unittest.TestCase):
    """The temporary key is never chmod-ed or chown-ed by name; the root-owned-code check; a
    game id is matched in full."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    @unittest.skipUnless(os.name == 'posix', 'descriptors and O_EXCL symlink semantics are POSIX')
    def test_a_link_planted_at_the_temporary_name_cannot_redirect_ownership(self):
        import unittest.mock
        victim = self.root / 'victim'
        victim.write_text('not a key\n', encoding='utf-8')
        os.chmod(victim, 0o644)
        owned = []
        key = self.root / 'keys' / 'g.key'
        key.parent.mkdir()
        (key.parent / '.g.key.abababab').symlink_to(victim)
        with unittest.mock.patch.object(pg.secrets, 'token_hex', lambda n: 'ab' * n):
            with self.assertRaises(FileExistsError):            # O_EXCL: a planted name is never opened
                pg._write_key(key, owned.append)
        self.assertEqual((victim.read_text(encoding='utf-8'), stat.S_IMODE(victim.stat().st_mode)), ('not a key\n', 0o644))
        self.assertTrue(all(isinstance(o, Path) for o in owned))      # only the directory, by path
        self.assertFalse(key.exists())

    @unittest.skipUnless(os.name == 'posix', 'descriptors are POSIX')
    def test_the_key_is_owned_through_the_open_descriptor_and_never_by_name(self):
        handed = []
        key = self.root / 'keys' / 'g.key'
        pg._write_key(key, handed.append)
        self.assertEqual([isinstance(h, int) for h in handed], [False, True])       # directory by path, key by descriptor
        self.assertEqual(stat.S_IMODE(key.stat().st_mode), 0o600)

    @unittest.skipUnless(os.name == 'posix', 'symbolic links')
    def test_a_key_directory_that_is_a_link_is_refused(self):
        real = self.root / 'real'
        real.mkdir()
        (self.root / 'keys').symlink_to(real, target_is_directory=True)
        owned = []
        with self.assertRaisesRegex(pg.Refused, 'symbolic link'):
            pg._write_key(self.root / 'keys' / 'g.key', owned.append)
        self.assertEqual((owned, list(real.iterdir())), ([], []))

    def test_the_real_own_refuses_a_linked_directory_and_takes_a_descriptor(self):
        import unittest.mock
        with unittest.mock.patch.object(pg, '_phase_1', lambda: (1, 2)), \
                unittest.mock.patch.object(pg.os, 'chown', create=True) as chown:
            pg.real_own(7)
            chown.assert_called_once_with(7, 1, 2)
            chown.reset_mock()
            plain = self.root / 'plain'
            plain.mkdir()
            pg.real_own(plain)
            self.assertEqual(chown.call_args.args, (plain, 1, 2))
            link = self.root / 'link'
            try:
                link.symlink_to(plain, target_is_directory=True)
            except OSError:
                self.skipTest('this account cannot create symbolic links')
            chown.reset_mock()
            with self.assertRaisesRegex(pg.Refused, 'symbolic link'):
                pg.real_own(link)
            chown.assert_not_called()

    def test_the_root_owned_code_decision_on_injected_stat_results(self):
        from types import SimpleNamespace as St
        d755, f755 = stat.S_IFDIR | 0o755, stat.S_IFREG | 0o755
        table = {'/': St(st_uid=0, st_mode=d755), '/opt': St(st_uid=0, st_mode=d755),
                 '/opt/g': St(st_uid=0, st_mode=d755), '/opt/g/run': St(st_uid=0, st_mode=f755)}

        def why(path, **changes):
            seen = {**table, **{k.replace('_', '/'): v for k, v in changes.items()}}

            def lstat(part):
                if part not in seen:
                    raise FileNotFoundError(part)
                return seen[part]
            return pg.untrusted_reason(path, lstat, lambda p: p)
        self.assertIsNone(why('/opt/g/run'))
        self.assertIsNone(why('/opt/g'))
        self.assertIn('/opt/g/missing does not exist', why('/opt/g/missing'))
        self.assertIn('/opt/g is not owned by root', why('/opt/g/run', _opt_g=St(st_uid=1000, st_mode=d755)))
        self.assertIn('/opt is writable by a group or others', why('/opt/g/run', _opt=St(st_uid=0, st_mode=stat.S_IFDIR | 0o775)))
        self.assertIn('/ is writable', why('/opt/g/run', _=St(st_uid=0, st_mode=stat.S_IFDIR | 0o757)))
        self.assertIn('/opt/g/run is writable', why('/opt/g/run', _opt_g_run=St(st_uid=0, st_mode=stat.S_IFREG | 0o722)))
        self.assertIn('/opt/g/run is not owned by root', why('/opt/g/run', _opt_g_run=St(st_uid=1000, st_mode=f755)))
        # a link is followed: the resolved path is checked as well as the ancestors of the link
        link = {'/opt/l': St(st_uid=0, st_mode=stat.S_IFLNK | 0o777)}
        resolved = lambda p: '/opt/g/run' if p == '/opt/l' else p
        self.assertIsNone(pg.untrusted_reason('/opt/l', lambda part: {**table, **link}[part], resolved))
        bad = {**table, **link, '/opt/g': St(st_uid=1000, st_mode=d755)}
        self.assertIn('/opt/g is not owned by root', pg.untrusted_reason('/opt/l', lambda part: bad[part], resolved))
        with self.assertRaisesRegex(pg.Refused, r'root-owned code \(ADR 0016 section 2\)'):
            pg.trusted_path('/nonexistent-avrana/x')

    def test_provision_checks_trust_before_writing_anything(self):
        layout = pg.Layout(key_dir=self.root / 'keys', registry_dir=self.root / 'games.d', socket_dir=self.root / 'run',
                           state_dir=self.root / 'var', unit_dir=self.root / 'units', template_dir=TEMPLATES)
        asked, calls = [], []

        def distrust(path):
            asked.append(path)
            raise pg.Refused(f'{path}: not root-owned')
        with self.assertRaisesRegex(pg.Refused, 'not root-owned'):
            pg.provision('checkers', layout, CONTRACTS, GRANTS, calls.append, lambda t: None, ORIGIN, trusted=distrust)
        self.assertEqual((asked, calls, list(self.root.rglob('*'))), (['/opt/games/checkers/run'], [], []))
        asked.clear()
        pg.provision('checkers', layout, CONTRACTS, GRANTS, calls.append, lambda t: None, ORIGIN, trusted=asked.append)
        self.assertEqual(asked, ['/opt/games/checkers/run', '/opt/games/checkers'])      # command, then working directory

    def test_a_game_id_is_matched_in_full(self):
        layout = pg.Layout(key_dir=self.root, registry_dir=self.root, socket_dir=self.root, state_dir=self.root,
                           unit_dir=self.root, template_dir=TEMPLATES)
        for slug in ('checkers\n', 'checkers\n\n'):
            with self.assertRaisesRegex(pg.Refused, 'not a game id'):
                pg.check(slug, CONTRACTS, GRANTS)
            with self.assertRaisesRegex(pg.Refused, 'not a game id'):
                pg.remove(slug, layout, lambda argv: None)
            with self.assertRaisesRegex(pg.Refused, 'not a game id'):
                pg.plan_remove(slug, layout)


class CommandLine(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.calls, self.owned = [], []
        self.doc = {'installed': [{'game': 'checkers', 'runtime': RUNTIME}, {'game': 'bluff'}]}
        self.status = STATUS_IDLE
        conf_dir = tempfile.TemporaryDirectory()          # outside the scratch tree: it is Party Core's, not ours
        self.addCleanup(conf_dir.cleanup)
        self.config = Path(conf_dir.name) / 'party-core.json'
        self.config.write_text(json.dumps({'origins': [ORIGIN]}), encoding='utf-8')

    def main(self, *args, root=True, doc=None, status=None):
        out, err = io.StringIO(), io.StringIO()
        paths = []
        for flag, sub in (('key-dir', 'keys'), ('registry-dir', 'games.d'), ('socket-dir', 'run'), ('state-dir', 'var'),
                          ('unit-dir', 'units'), ('template-dir', None)):
            paths += [f'--{flag}', str(TEMPLATES if sub is None else self.root / sub)]
        paths += ['--party-config', str(self.config)]
        code = pg.main([*args, *paths], run=self.calls.append, own=self.owned.append, is_root=root,
                       opener=lambda url, timeout: Response(status or self.status),
                       contracts=CONTRACTS, appliance_doc=doc or self.doc, out=out, err=err)
        return code, out.getvalue(), err.getvalue()

    def files(self):
        return sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob('*') if p.is_file())

    def test_provision_then_again_then_remove(self):
        code, out, err = self.main('checkers')
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(out.splitlines(), [f'checkers: changed {c}' for c in FIRST])
        self.assertEqual(len(self.files()), 5)
        key = (self.root / 'keys' / 'checkers.key').read_text(encoding='ascii').strip()
        self.assertNotIn(key, out + err)                                              # never printed
        self.assertEqual(self.main('checkers')[1], 'checkers: nothing to change\n')
        code, out, _ = self.main('checkers', '--remove')
        self.assertEqual((code, out.splitlines()), (0, ['checkers: removed registry', 'checkers: removed dropin',
                                                         'checkers: removed key']))
        self.assertEqual(len(self.files()), 2)                                        # the two shared templates

    def test_the_origin_is_read_from_the_core_config_a_change_rewrites_the_dropin_and_dry_run_says_so(self):
        self.main('checkers')
        dropin = self.root / 'units' / 'avrana-game@checkers.service.d' / 'exec.conf'
        self.assertIn(f'Environment=AVRANA_PARTY_ORIGIN={ORIGIN}\n', dropin.read_text(encoding='utf-8'))
        self.config.write_text(json.dumps({'origins': ['http://10.0.0.142:8080']}), encoding='utf-8')
        code, out, _ = self.main('checkers', '--dry-run', root=False)
        self.assertEqual((code, out), (0, 'checkers: would change dropin\n'))
        self.assertEqual(self.main('checkers')[1], 'checkers: changed dropin\n')
        self.assertIn('AVRANA_PARTY_ORIGIN=http://10.0.0.142:8080\n', dropin.read_text(encoding='utf-8'))

    def test_a_config_with_no_usable_origin_refuses_naming_the_file_and_writes_nothing(self):
        for doc in ({}, {'origins': ['https://x.test/path']}, {'origins': []}):
            self.config.write_text(json.dumps(doc), encoding='utf-8')
            for extra in ((), ('--dry-run',)):
                code, out, err = self.main('checkers', *extra)
                self.assertEqual((code, out), (1, ''), (doc, extra))
                self.assertIn(str(self.config), err)
                self.assertIn('no usable "origins"', err)
        self.assertEqual((self.files(), self.calls, self.owned), ([], [], []))
        self.config.unlink()
        self.assertEqual(self.main('checkers')[0], 1)                         # no config at all
        self.assertEqual(self.main('checkers', '--remove')[0], 0)               # a removal reads no origin

    def test_refusals_exit_1_with_the_reason_on_stderr(self):
        for args, doc, why in ((('Nope!',), None, 'not a game id'), (('nosuch',), None, 'no Game Contract'),
                               (('bluff',), None, 'no "runtime"'), (('bluff',), {'installed': []}, 'no grant')):
            code, out, err = self.main(*args, doc=doc)
            self.assertEqual((code, out), (1, ''), args)
            self.assertIn(why, err)
        code, out, err = self.main('checkers', root=False)
        self.assertEqual((code, out), (1, ''))
        self.assertIn('must run as root', err)
        self.assertEqual((self.files(), self.calls), ([], []))

    def test_usage_errors_exit_2(self):
        for args in ((), ('checkers', '--rotate', '--remove'), ('checkers', '--keep-state'), ('checkers', '--nonsense')):
            code, out, err = self.main(*args)
            self.assertEqual((code, out), (2, ''), args)
            self.assertIn('provision-game:', err)

    def test_dry_run_needs_no_root_prints_the_plan_and_changes_nothing(self):
        code, out, _ = self.main('checkers', '--dry-run', root=False)
        self.assertEqual((code, out.splitlines()), (0, [f'checkers: would change {c}' for c in FIRST]))
        self.assertEqual((self.files(), self.calls, self.owned), ([], [], []))
        self.main('checkers')
        before = self.files()
        self.calls.clear()
        self.assertEqual(self.main('checkers', '--remove', '--dry-run', root=False)[1].splitlines(),
                         ['checkers: would remove registry', 'checkers: would remove dropin', 'checkers: would remove key'])
        self.assertEqual((self.files(), self.calls), (before, []))

    def test_rotate_through_the_command_line(self):
        self.main('checkers')
        key = (self.root / 'keys' / 'checkers.key').read_bytes()
        self.calls.clear()
        code, out, err = self.main('checkers', '--rotate', status=status_with('checkers'))
        self.assertEqual((code, out), (1, ''))
        self.assertIn('session running', err)
        self.assertEqual((self.calls, (self.root / 'keys' / 'checkers.key').read_bytes()), ([], key))
        code, out, _ = self.main('checkers', '--rotate', status=status_with('bluff'))     # another game's session
        self.assertEqual((code, out), (0, 'checkers: replaced key\n'))
        self.assertNotEqual((self.root / 'keys' / 'checkers.key').read_bytes(), key)

    def test_rotate_proceeds_when_party_core_is_unreachable(self):
        self.main('checkers')
        out, err = io.StringIO(), io.StringIO()

        def down(url, timeout):
            raise urllib.error.URLError(ConnectionRefusedError())
        paths = ['--key-dir', str(self.root / 'keys'), '--registry-dir', str(self.root / 'games.d'),
                 '--unit-dir', str(self.root / 'units'), '--template-dir', str(TEMPLATES)]
        code = pg.main(['checkers', '--rotate', *paths], run=self.calls.append, own=self.owned.append, is_root=True,
                       opener=down, contracts=CONTRACTS, appliance_doc=self.doc, out=out, err=err)
        self.assertEqual((code, out.getvalue()), (0, 'checkers: replaced key\n'))

    def test_rotate_reports_failure_when_systemctl_fails(self):
        import subprocess
        self.main('checkers')
        out, err = io.StringIO(), io.StringIO()

        def run(argv):
            if argv[1] == 'stop':
                raise subprocess.CalledProcessError(1, argv)
        paths = ['--key-dir', str(self.root / 'keys'), '--registry-dir', str(self.root / 'games.d'),
                 '--unit-dir', str(self.root / 'units'), '--template-dir', str(TEMPLATES)]
        code = pg.main(['checkers', '--rotate', *paths], run=run, own=self.owned.append, is_root=True,
                       opener=lambda url, timeout: Response(STATUS_IDLE), contracts=CONTRACTS,
                       appliance_doc=self.doc, out=out, err=err)
        self.assertEqual((code, out.getvalue()), (1, ''))
        self.assertIn('failed: systemctl stop avrana-game@checkers.service exited 1', err.getvalue())

    def test_a_failed_party_reload_names_the_likely_cause(self):
        import subprocess
        out, err = io.StringIO(), io.StringIO()

        def run(argv):
            if argv[1] == 'reload':
                raise subprocess.CalledProcessError(1, argv)
        paths = ['--key-dir', str(self.root / 'keys'), '--registry-dir', str(self.root / 'games.d'),
                 '--unit-dir', str(self.root / 'units'), '--template-dir', str(TEMPLATES),
                 '--party-config', str(self.config)]
        code = pg.main(['checkers', *paths], run=run, own=self.owned.append, is_root=True,
                       opener=lambda url, timeout: Response(STATUS_IDLE), contracts=CONTRACTS,
                       appliance_doc=self.doc, out=out, err=err)
        self.assertEqual((code, out.getvalue()), (1, ''))
        self.assertIn('systemctl reload avrana-party-core.service exited 1', err.getvalue())
        self.assertIn("no ExecReload=: reinstall deploy/party-core/avrana-party-core.service, "
                      "see docs/runbooks/provision-game.md", err.getvalue())
        self.assertEqual(self.main('checkers')[0], 0)                      # running again repairs it

    def test_remove_is_refused_during_a_session_through_the_command_line(self):
        self.main('checkers')
        before = self.files()
        self.calls.clear()
        code, out, err = self.main('checkers', '--remove', status=status_with('checkers'))
        self.assertEqual((code, out, self.calls, self.files()), (1, '', [], before))
        self.assertIn('has a session running; end it from Party Home first', err)
        self.assertEqual(self.main('checkers', '--remove', '--dry-run', status=status_with('checkers'))[0], 1)
        self.assertEqual(self.main('checkers', '--remove', status=status_with('bluff'))[0], 0)    # another game's session

    def test_remove_loads_no_contracts_and_needs_no_phase_1_identities(self):
        def boom(*a, **k):
            raise AssertionError('--remove must not load contracts or the appliance profile')

        class Boom(dict):
            def __getitem__(self, k):
                boom()
            get = __contains__ = __iter__ = items = keys = boom
        self.main('checkers')
        out, err = io.StringIO(), io.StringIO()
        paths = ['--key-dir', str(self.root / 'keys'), '--registry-dir', str(self.root / 'games.d'),
                 '--socket-dir', str(self.root / 'run'), '--state-dir', str(self.root / 'var'),
                 '--unit-dir', str(self.root / 'units'), '--template-dir', str(TEMPLATES)]
        import unittest.mock
        # no injected `own`: the real one would need phase 1; a remove must not ask for it
        with unittest.mock.patch.object(pg, '_phase_1', boom):
            code = pg.main(['checkers', '--remove', *paths], run=self.calls.append, is_root=True,
                           opener=lambda url, timeout: Response(STATUS_IDLE), contracts=Boom(),
                           appliance_doc=Boom(), out=out, err=err)
        self.assertEqual((code, err.getvalue()), (0, ''))
        self.assertIn('removed registry', out.getvalue())
        # with the loaders not injected either, the real ones are never reached
        with unittest.mock.patch.object(pg, '_phase_1', boom), \
                unittest.mock.patch('avrana.contracts.party_config.load_contracts', boom), \
                unittest.mock.patch('avrana.contracts.appliance.load', boom):
            code = pg.main(['checkers', '--remove', *paths], run=self.calls.append, is_root=True,
                           opener=lambda url, timeout: Response(STATUS_IDLE), out=out, err=err)
        self.assertEqual(code, 0)

    def test_a_non_root_dry_run_that_cannot_read_the_key_store_says_so(self):
        import unittest.mock
        for args in (('checkers', '--dry-run'), ('checkers', '--remove', '--dry-run')):
            with unittest.mock.patch.object(pg, 'plan_provision', side_effect=PermissionError(13, 'denied')), \
                    unittest.mock.patch.object(pg, 'plan_remove', side_effect=PermissionError(13, 'denied')):
                code, out, err = self.main(*args, root=False)
            self.assertEqual((code, out), (1, ''), args)
            self.assertIn('needs root to read the key store', err)
            self.assertNotIn('Traceback', err)
        with unittest.mock.patch.object(pg, 'plan_provision', side_effect=PermissionError(13, 'denied')):
            code, _, err = self.main('checkers', '--dry-run', root=True)
        self.assertEqual(code, 1)
        self.assertNotIn('needs root', err)                                # root has another problem: say it

    def test_the_not_root_refusal_does_not_promise_a_dry_run(self):
        code, out, err = self.main('checkers', root=False)
        self.assertEqual((code, out), (1, ''))
        self.assertIn('must run as root', err)
        self.assertNotIn('dry-run', err)

    def test_keep_state_through_the_command_line(self):
        self.main('checkers')
        (self.root / 'var' / 'checkers').mkdir(parents=True)
        (self.root / 'var' / 'checkers' / 'save.json').write_text('{}', encoding='utf-8')
        code, out, _ = self.main('checkers', '--remove', '--keep-state')
        self.assertEqual(code, 0)
        self.assertNotIn('state', out)
        self.assertIn('var/checkers/save.json', self.files())

    def test_the_real_effects_refuse_cleanly_without_phase_1(self):
        out, err = io.StringIO(), io.StringIO()
        if os.name == 'posix':
            import pwd
            try:
                pwd.getpwnam('avrana-party')
                self.skipTest('this host has phase 1 applied')
            except KeyError:
                pass
        code = pg.main(['checkers'], is_root=True, contracts=CONTRACTS, appliance_doc=self.doc, out=out, err=err)
        self.assertEqual((code, out.getvalue()), (1, ''))
        self.assertIn('phase 1 has not been applied', err.getvalue())

    def test_the_shipped_appliance_has_no_runtime_so_a_real_slug_is_refused_by_name(self):
        out, err = io.StringIO(), io.StringIO()
        self.assertEqual(pg.main(['bluff', '--dry-run'], is_root=False, out=out, err=err), 1)
        self.assertIn('no "runtime"', err.getvalue())
        self.assertEqual(out.getvalue(), '')


if __name__ == '__main__':
    unittest.main()
