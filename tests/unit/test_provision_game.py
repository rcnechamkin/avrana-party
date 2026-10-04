"""provision_game's core against ADR 0016 section 8, on a scratch directory with a recorded
systemctl. Real systemd (socket activation, LoadCredential, DynamicUser) is the Linux CI job's."""
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from avrana.ops import provision_game as pg
from avrana.party import protocol, registry

CONTRACTS = {'checkers': {'id': 'checkers'}, 'bluff': {'id': 'bluff'}}
GRANTS = {'checkers': {'game': 'checkers'}}


class Provisioning(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.layout = pg.Layout(key_dir=root / 'etc/game-keys', registry_dir=root / 'etc/games.d',
                                socket_dir=root / 'run/avrana-games', state_dir=root / 'var/avrana-games')
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
        self.assertEqual(self.provision(), ['key', 'registry'])
        key = self.layout.key('checkers')
        self.assertEqual(len(protocol.read_key(key)), 32)                 # the loader accepts it
        if os.name == 'posix':
            self.assertEqual(stat.S_IMODE(key.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(key.parent.stat().st_mode), 0o700)
        self.assertEqual(self.owned, [key.parent, self.owned[1]])        # the directory, then the key
        self.assertEqual(self.owned[1].parent, key.parent)
        self.assertEqual(self.tree(), ['etc/game-keys/checkers.key', 'etc/games.d/checkers.json'])
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
        self.assertEqual(self.tree(), ['etc/game-keys/checkers.key', 'etc/games.d/checkers.json'])   # no stray temp file
        with self.assertRaises(pg.Refused):
            pg.rotate('bluff', self.layout, CONTRACTS, {'bluff': {}}, self.run_, self.own, lambda s: False)   # never provisioned

    def test_remove_leaves_nothing_for_the_slug_and_nothing_else_is_touched(self):
        self.provision()
        pg.provision('bluff', self.layout, CONTRACTS, {'bluff': {}}, self.run_, self.own)
        for slug in ('checkers', 'bluff'):
            self.layout.state(slug).mkdir(parents=True)
            (self.layout.state(slug) / 'save.json').write_text('{}', encoding='utf-8')
            self.layout.socket(slug).parent.mkdir(parents=True, exist_ok=True)
            self.layout.socket(slug).write_text('', encoding='utf-8')
        self.calls.clear()
        self.assertEqual(pg.remove('checkers', self.layout, self.run_), ['registry', 'key', 'socket', 'state'])
        self.assertEqual([p for p in self.tree() if 'checkers' in p], [])
        self.assertFalse(self.layout.state('checkers').exists())
        self.assertEqual(self.tree(), ['etc/game-keys/bluff.key', 'etc/games.d/bluff.json', 'run/avrana-games/bluff.sock',
                                       'var/avrana-games/bluff/save.json'])
        self.assertEqual(self.calls, [['systemctl', 'disable', '--now', 'avrana-game@checkers.socket'],
                                      ['systemctl', 'stop', 'avrana-game@checkers.service'],
                                      ['systemctl', 'reload', 'avrana-party-core.service']])
        # the entry goes before the key, so Party Core never reloads onto an entry with no key
        self.assertEqual(pg.remove('checkers', self.layout, self.run_), [])             # again: nothing left

    def test_remove_can_keep_the_state_directory_and_needs_no_contract(self):
        self.provision()
        self.layout.state('checkers').mkdir(parents=True)
        (self.layout.state('checkers') / 'save.json').write_text('{}', encoding='utf-8')
        self.assertEqual(pg.remove('checkers', self.layout, self.run_, keep_state=True), ['registry', 'key'])
        self.assertEqual(self.tree(), ['var/avrana-games/checkers/save.json'])
        with self.assertRaises(pg.Refused):
            pg.remove('../etc', self.layout, self.run_)

    def test_the_layout_has_no_default_path(self):
        with self.assertRaises(TypeError):
            pg.Layout()


if __name__ == '__main__':
    unittest.main()
