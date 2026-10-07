"""The systemd units of the native-game path (ADR 0016 sections 4 and 5, AVR-236), read as text:
the template every native game runs from, its socket, and Party Core's game-facing socket. What
systemd makes of them (DynamicUser, LoadCredential, socket activation) is proven on a Linux
runner; here the files are held to the ADR and to contracts/service-boundary.v1.json."""
import configparser
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from avrana import REPO_ROOT
from avrana.contracts import catalog, vocabulary

GAMES = REPO_ROOT / 'deploy' / 'games'
PARTY = REPO_ROOT / 'deploy' / 'party-core'
SPEC = json.loads((REPO_ROOT / 'contracts' / 'service-boundary.v1.json').read_text(encoding='utf-8'))


def unit(path):
    """{section: {key: [values]}}; a key may repeat (Environment=)."""
    parser = configparser.RawConfigParser(strict=False, delimiters=('=',), comment_prefixes=('#',))
    parser.optionxform = str
    out = {}
    section = None
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('['):
            section = out.setdefault(line.strip('[]'), {})
            continue
        key, _, value = line.partition('=')
        section.setdefault(key.strip(), []).append(value.strip())
    return out


class GameTemplate(unittest.TestCase):
    def setUp(self):
        self.socket = unit(GAMES / 'avrana-game@.socket')['Socket']
        self.service = unit(GAMES / 'avrana-game@.service')['Service']

    def test_the_socket_is_the_one_the_boundary_and_nginx_expect(self):
        want = SPEC['sockets']['game']
        front = SPEC['groups']['front']['name']
        self.assertEqual(self.socket, {'ListenStream': [want['path'].format(slug='%i')],
                                       'SocketUser': [want['owner']], 'SocketGroup': [front],
                                       'SocketMode': [want['mode']]})
        native = (GAMES / 'nginx-native-games.location').read_text(encoding='utf-8')
        self.assertIn('proxy_pass http://unix:/run/avrana-games/$native_game.sock:', native)

    def test_the_service_is_the_adr_0016_section_5_baseline(self):
        games = SPEC['groups']['games']['name']
        for key, value in {'DynamicUser': 'yes', 'SupplementaryGroups': games,
                           'StateDirectory': 'avrana-games/%i', 'StateDirectoryMode': '0700',
                           'LoadCredential': '%i.key:/etc/avrana-party/game-keys/%i.key',
                           'RestrictAddressFamilies': 'AF_UNIX', 'ProtectHome': 'yes',
                           'PrivateDevices': 'yes', 'UMask': '0077', 'Restart': 'on-failure',
                           'ProtectKernelTunables': 'yes', 'ProtectKernelModules': 'yes',
                           'ProtectControlGroups': 'yes'}.items():
            self.assertEqual(self.service.get(key), [value], key)
        self.assertIn('AVRANA_PARTY_KEYS=%d', self.service['Environment'])

    def test_a_game_is_handed_party_cores_internal_socket(self):
        want = SPEC['sockets']['party_internal']['path']
        self.assertEqual(want, '/run/avrana-party/internal.sock')
        self.assertIn(f'AVRANA_PARTY_SOCKET={want}', self.service['Environment'])
        head = (GAMES / 'avrana-game@.service').read_text(encoding='utf-8').split('[Unit]')[0]
        self.assertIn('drop-in', head)                                    # the ExecStart decision is recorded
        self.assertNotIn('pending', head)

    def test_the_party_origin_is_per_appliance_so_the_template_says_so_and_does_not_carry_it(self):
        head = (GAMES / 'avrana-game@.service').read_text(encoding='utf-8').split('[Unit]')[0]
        self.assertIn('AVRANA_PARTY_ORIGIN', head)                        # what a game is handed is all in one place
        self.assertIn('provision-game writes it', head.replace('\n# ', ' '))
        self.assertFalse([e for e in self.service['Environment'] if e.startswith('AVRANA_PARTY_ORIGIN')])

    def test_a_game_gets_one_key_one_group_no_user_and_no_ip(self):
        self.assertEqual(len(self.service['LoadCredential']), 1)         # its own key, no other
        self.assertNotIn('User', self.service)                            # the instance is the identity
        self.assertNotIn('Group', self.service)
        self.assertNotIn(SPEC['groups']['front']['name'], ' '.join(self.service['SupplementaryGroups']))
        for line in self.service['Environment']:
            self.assertNotRegex(line.lower(), r'key=|token|secret')       # the key is never in the unit
        text = (GAMES / 'avrana-game@.service').read_text(encoding='utf-8')
        self.assertNotRegex(text, r'(?m)^(ListenStream|ExecStart|WantedBy)=')   # socket-activated; no command here

    def test_no_per_title_unit_exists(self):
        units = sorted(p.name for p in GAMES.glob('*.s*') if p.suffix in ('.service', '.socket'))
        self.assertEqual(units, ['avrana-game@.service', 'avrana-game@.socket'])


class PartyInternalSocket(unittest.TestCase):
    def test_the_socket_unit_is_the_one_the_boundary_expects(self):
        socket = unit(PARTY / 'avrana-party-core.socket')['Socket']
        want = SPEC['sockets']['party_internal']
        self.assertEqual((socket['ListenStream'], socket['SocketMode']), ([want['path']], [want['mode']]))
        self.assertEqual(socket['SocketUser'], [SPEC['units']['avrana-party-core.service'].get('user', 'avrana-party')])
        self.assertEqual(socket['SocketGroup'], [SPEC['groups']['games']['name']])

    def test_party_core_reloads_its_registry_on_systemctl_reload(self):
        service = unit(PARTY / 'avrana-party-core.service')['Service']
        self.assertEqual(service['ExecReload'], ['/bin/kill -HUP $MAINPID'])
        self.assertIn('AF_UNIX', service['RestrictAddressFamilies'][0])   # it connects to game sockets
        head = unit(PARTY / 'avrana-party-core.service')['Unit']
        self.assertEqual(head['Wants'], ['avrana-party-core.socket'])     # inherited, never raced
        self.assertIn('avrana-party-core.socket', head['After'][0])
        self.assertNotIn('Requires', head)                                # no native game: still starts


class DuplicateSlug(unittest.TestCase):
    def test_two_contracts_cannot_claim_one_slug(self):
        """A slug names one game everywhere: its socket, key, unit instance and registry entry.
        A contract's file name must be its id (avrana.contracts.game.load), so one directory
        cannot hold two contracts with one id; the loader refuses the second by name."""
        with tempfile.TemporaryDirectory() as tmp:
            src = REPO_ROOT / 'contracts' / 'games' / 'bluff.json'
            shutil.copy(src, Path(tmp) / 'bluff.json')
            self.assertEqual(sorted(catalog.load_contracts(tmp, vocabulary.load())), ['bluff'])
            shutil.copy(src, Path(tmp) / 'bluff-again.json')
            with self.assertRaises(ValueError) as e:
                catalog.load_contracts(tmp, vocabulary.load())
            self.assertIn('bluff-again', str(e.exception))
            self.assertIn("'bluff'", str(e.exception))

    def test_the_repository_contracts_have_one_id_each(self):
        ids = [json.loads(p.read_text(encoding='utf-8'))['id'] for p in (REPO_ROOT / 'contracts' / 'games').glob('*.json')]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == '__main__':
    unittest.main()
