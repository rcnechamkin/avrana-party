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

    def own(self, path):
        self.owned.append(Path(path))

    def provision(self, slug='checkers', **kw):
        return pg.provision(slug, self.layout, CONTRACTS, GRANTS, self.run_, self.own, **kw)

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
        self.assertEqual(self.owned[1].parent, key.parent)
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
        self.assertEqual(self.calls, [['systemctl', 'enable', '--now', 'avrana-game@checkers.socket']])   # no reload
        self.assertEqual(self.owned, [])

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
        pg.provision('bluff', self.layout, CONTRACTS, BLUFF, self.run_, self.own)
        for slug in ('checkers', 'bluff'):
            self.layout.state(slug).mkdir(parents=True)
            (self.layout.state(slug) / 'save.json').write_text('{}', encoding='utf-8')
            self.layout.socket(slug).parent.mkdir(parents=True, exist_ok=True)
            self.layout.socket(slug).write_text('', encoding='utf-8')
        self.calls.clear()
        self.assertEqual(pg.remove('checkers', self.layout, self.run_), ['registry', 'dropin', 'key', 'socket', 'state'])
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
                                      ['systemctl', 'daemon-reload']])
        # the entry goes before the key, so Party Core never reloads onto an entry with no key
        self.assertEqual(pg.remove('checkers', self.layout, self.run_), [])             # again: nothing left

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
                                      ['systemctl', 'enable', '--now', 'avrana-game@checkers.socket']])   # no Party reload

    def test_a_changed_runtime_rewrites_only_the_dropin_and_restarts_nothing(self):
        self.provision()
        self.calls.clear()
        grants = {'checkers': {'game': 'checkers', 'runtime': dict(RUNTIME, working_directory='/srv/checkers')}}
        self.assertEqual(pg.provision('checkers', self.layout, CONTRACTS, grants, self.run_, self.own), ['dropin'])
        self.assertIn('WorkingDirectory=/srv/checkers\n', self.layout.dropin('checkers').read_text(encoding='utf-8'))
        self.assertEqual(self.calls, [['systemctl', 'daemon-reload'],
                                      ['systemctl', 'enable', '--now', 'avrana-game@checkers.socket']])
        self.assertNotRegex(' '.join(' '.join(c) for c in self.calls), r'restart|stop|start ')

    def test_a_grant_without_runtime_is_refused_before_anything_is_written(self):
        for grants in ({'checkers': {'game': 'checkers'}}, {'checkers': {'runtime': {'command': ['x'], 'working_directory': '/'}}},
                       {'checkers': {'runtime': dict(RUNTIME, command=['/bin/x', 'a\nExecStart=/bin/sh'])}}):
            with self.assertRaises(pg.Refused):
                pg.provision('checkers', self.layout, CONTRACTS, grants, self.run_, self.own)
        self.assertEqual((self.tree(), self.calls, self.owned), ([], [], []))

    def test_the_dropin_text_for_an_example(self):
        self.provision()
        self.assertEqual(self.layout.dropin('checkers').read_text(encoding='utf-8'),
                         '# Written by provision-game from the appliance grant (AVR-236). Edits are overwritten.\n'
                         '[Service]\n'
                         'ExecStart="/opt/games/checkers/run" "--port" "x y"\n'
                         'WorkingDirectory=/opt/games/checkers\n')

    def test_the_dropin_quotes_for_systemd(self):
        text = pg.dropin_text({'command': ['/bin/g', 'a b', '100%', 'cost $HOME', 'say "hi"', 'back\\slash'],
                               'working_directory': '/srv/50%'})
        self.assertIn('ExecStart="/bin/g" "a b" "100%%" "cost $$HOME" "say \\"hi\\"" "back\\\\slash"\n', text)
        self.assertIn('WorkingDirectory=/srv/50%%\n', text)
        for bad in ('a\nb', 'a\rb', 'a\x00b', 'a\tb'):
            with self.assertRaises(pg.Refused):
                pg.dropin_text({'command': ['/bin/g', bad], 'working_directory': '/'})

    def test_dry_run_plans_the_same_changes_and_changes_nothing(self):
        self.assertEqual(pg.plan_provision('checkers', self.layout, CONTRACTS, GRANTS), FIRST)
        self.assertEqual((self.tree(), self.calls), ([], []))
        self.provision()
        self.assertEqual(pg.plan_provision('checkers', self.layout, CONTRACTS, GRANTS), [])
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

        def slow(url, timeout):
            raise TimeoutError()

        def broken(url, timeout):
            raise urllib.error.HTTPError(url, 500, 'x', {}, None)
        self.assertFalse(pg.party_session_check('http://x', down)('checkers'))
        self.assertFalse(pg.party_session_check('http://x', slow)('checkers'))
        with self.assertRaises(pg.Refused):
            pg.party_session_check('http://x', broken)('checkers')

        class Junk(Response):
            body = b'<html>'
        with self.assertRaises(pg.Refused):
            pg.party_session_check('http://x', lambda url, timeout: Junk({}))('checkers')


class CommandLine(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.calls, self.owned = [], []
        self.doc = {'installed': [{'game': 'checkers', 'runtime': RUNTIME}, {'game': 'bluff'}]}
        self.status = STATUS_IDLE

    def main(self, *args, root=True, doc=None, status=None):
        out, err = io.StringIO(), io.StringIO()
        paths = []
        for flag, sub in (('key-dir', 'keys'), ('registry-dir', 'games.d'), ('socket-dir', 'run'), ('state-dir', 'var'),
                          ('unit-dir', 'units'), ('template-dir', None)):
            paths += [f'--{flag}', str(TEMPLATES if sub is None else self.root / sub)]
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
