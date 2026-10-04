"""The service boundary of ADR 0016 (contracts/service-boundary.v1.json, avrana/ops/boundary.py).

Two sets of facts: what the Pi actually looked like on 2026-10-03 (recorded read-only by the
module's own collector; every service runs as the operator), and a host built to the ADR. The
first must be reported as failing for the right reasons; the second must pass, and each single
departure from it must be caught by the rule that names it."""
import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from avrana import CONTRACTS_DIR, REPO_ROOT
from avrana.ops import boundary

PI = json.loads((REPO_ROOT / 'tests/fixtures/boundary/pi-2026-10-03.json').read_text(encoding='utf-8'))
SPEC = boundary.load_spec()
KEYS = '/etc/avrana-party/game-keys'
NOLOGIN = '/usr/sbin/nologin'


def entry(path, owner, group, mode):
    return {'path': path, 'owner': owner, 'group': group, 'mode': mode}


def service(unit, role, user, creds, **more):
    s = {'unit': unit, 'role': role, 'user': user, 'no_new_privileges': True, 'protect_system': 'strict',
         'protect_home': 'yes', 'private_tmp': True, 'private_devices': True,
         'address_families': ['AF_UNIX'], 'credentials': creds, 'tcp': [],
         'code': [entry(f'/opt/avrana/{role}', 'root', 'root', '0755')],
         'state': [entry(f'/var/lib/{user}', user, user, '0700')]}
    s.update(more)
    return s


def target():
    """A host after phases 1 to 3: Party Core, the arcade and one native game, Checkers."""
    users = {u: {'uid': 900 + i, 'shell': NOLOGIN, 'groups': [u] + extra}
             for i, (u, extra) in enumerate((('avrana-party', []), ('avrana-game-checkers', []),
                                             ('avrana-arcade', ['input', 'video', 'render', 'audio'])))}
    return {
        'users': users,
        'keys': {'dir': entry(KEYS, 'root', 'root', '0700'),
                 'files': [entry(f'{KEYS}/{k}.key', 'root', 'root', '0600')
                           for k in ('arcade-gauntlet2', 'checkers')]},
        'services': [
            service('avrana-party-core.service', 'party', 'avrana-party', [KEYS]),
            service('avrana-game@checkers.service', 'native-game', 'avrana-game-checkers',
                    [f'{KEYS}/checkers.key'], slug='checkers'),
            service('avranaparty-arcade.service', 'arcade', 'avrana-arcade',
                    [f'{KEYS}/arcade-gauntlet2.key'], tcp=['127.0.0.1:8097', '127.0.0.1:8098'],
                    address_families=['AF_INET', 'AF_UNIX'], private_devices=False),
        ],
        'sockets': [
            entry('/run/avrana/party/api.sock', 'avrana-party', 'www-data', '0660'),
            entry('/run/avrana/party/game/checkers.sock', 'avrana-party', 'avrana-game-checkers', '0660'),
            entry('/run/avrana/game/checkers/control.sock', 'avrana-game-checkers', 'avrana-party', '0660'),
            entry('/run/avrana/game/checkers/public.sock', 'avrana-game-checkers', 'www-data', '0660'),
        ],
    }


def failed(facts, phases=(1, 2, 3)):
    return sorted({(r['rule'], r['subject']) for r in boundary.evaluate(facts, SPEC, phases) if not r['ok']})


def game(facts):
    return next(s for s in facts['services'] if s['role'] == 'native-game')


class Spec(unittest.TestCase):
    def test_the_spec_names_its_decision_and_every_role_has_an_identity(self):
        self.assertEqual(SPEC['schema'], 'avrana.service-boundary/v1')
        self.assertTrue((REPO_ROOT / SPEC['decision']).is_file())
        self.assertEqual(set(SPEC['roles']), {'party', 'native-game', 'legacy-games', 'arcade'})
        self.assertEqual({u['role'] for u in SPEC['units'].values()}, set(SPEC['roles']))
        self.assertEqual(len({r['user'] for r in SPEC['roles'].values()}), 4)        # no shared identity
        self.assertTrue((CONTRACTS_DIR / 'service-boundary.v1.json').is_file())
        adr = (REPO_ROOT / SPEC['decision']).read_text(encoding='utf-8')
        for socket in SPEC['sockets'].values():
            self.assertIn(socket['path'].replace('{slug}', '<slug>'), adr)

    def test_no_socket_is_open_to_everyone_and_none_is_abstract(self):
        for socket in SPEC['sockets'].values():
            self.assertEqual(socket['mode'], '0660')
            self.assertTrue(socket['path'].startswith('/run/avrana/'))


class TheApplianceToday(unittest.TestCase):
    """Facts recorded on the Pi on 2026-10-03. This is the prototype, not the target."""

    def test_every_service_is_the_operator(self):
        self.assertEqual({s['user'] for s in PI['services']}, {'cody'})
        self.assertIn('sudo', PI['users']['cody']['groups'])
        bad = failed(PI, (1,))
        for unit in ('avrana-party-core.service', 'avranaparty-games.service', 'avranaparty-arcade.service'):
            for rule in ('identity.expected', 'identity.distinct', 'identity.unprivileged',
                         'code.readonly', 'keys.credentials'):
                self.assertIn((rule, unit), bad)

    def test_a_0600_key_is_reported_as_no_boundary(self):
        """The keys are 0600, and their owner is the user every service runs as."""
        self.assertEqual({f['mode'] for f in PI['keys']['files']}, {'0600'})
        self.assertIn(('keys.root_only', KEYS), failed(PI, (1,)))
        detail = next(r['detail'] for r in boundary.evaluate(PI, SPEC, (1,)) if r['rule'] == 'keys.root_only')
        self.assertIn('cody:cody', detail)

    def test_the_games_listener_is_not_loopback_and_party_is_on_tcp(self):
        self.assertIn(('ipc.loopback_only', 'avranaparty-games.service'), failed(PI, (1,)))
        self.assertIn(('ipc.party_off_tcp', 'avrana-party-core.service'), failed(PI, (3,)))
        self.assertIn(('legacy.retired', 'avranaparty-games.service'), failed(PI, (3,)))

    def test_what_already_holds_is_reported_as_holding(self):
        ok = {(r['rule'], r['subject']) for r in boundary.evaluate(PI, SPEC, (1,)) if r['ok']}
        self.assertIn(('hardening.base', 'avrana-party-core.service'), ok)
        self.assertIn(('ipc.loopback_only', 'avranaparty-arcade.service'), ok)
        self.assertEqual(len(ok), 6)

    def test_the_recording_holds_no_secret(self):
        text = json.dumps(PI)
        self.assertNotRegex(text, r'[0-9a-f]{64}')                      # no key material
        self.assertNotIn('password', text.lower())


class TheTarget(unittest.TestCase):
    def test_a_host_built_to_the_adr_passes_every_phase(self):
        self.assertEqual(failed(target()), [])
        self.assertGreater(len(boundary.evaluate(target(), SPEC)), 25)

    def mutate(self, change, expected, phases=(1, 2, 3)):
        facts = target()
        change(facts)
        self.assertEqual(failed(facts, phases), sorted(expected))

    def test_two_services_under_one_identity(self):
        def change(f):
            game(f)['user'] = 'avrana-party'
            game(f)['state'][0]['owner'] = 'avrana-party'
        unit = 'avrana-game@checkers.service'
        self.mutate(change, [('identity.distinct', 'avrana-party-core.service'), ('identity.distinct', unit),
                             ('identity.expected', unit), ('ipc.socket.game_control', unit),
                             ('ipc.socket.game_public', unit), ('ipc.socket.party_report', unit)])

    def test_a_service_that_could_become_root(self):
        self.mutate(lambda f: f['users']['avrana-game-checkers']['groups'].append('sudo'),
                    [('identity.unprivileged', 'avrana-game@checkers.service')])
        self.mutate(lambda f: f['users']['avrana-party'].update(shell='/bin/bash'),
                    [('identity.unprivileged', 'avrana-party-core.service')])

    def test_a_service_that_can_rewrite_code(self):
        self.mutate(lambda f: game(f)['code'].append(entry('/opt/x', 'avrana-game-checkers', 'root', '0755')),
                    [('code.readonly', 'avrana-game@checkers.service')])
        self.mutate(lambda f: game(f)['code'].append(entry('/opt/x', 'root', 'root', '0777')),
                    [('code.readonly', 'avrana-game@checkers.service')])

    def test_a_game_handed_more_than_its_own_key(self):
        unit = 'avrana-game@checkers.service'
        self.mutate(lambda f: game(f)['credentials'].append(f'{KEYS}/arcade-gauntlet2.key'),
                    [('keys.credentials', unit)])
        self.mutate(lambda f: game(f).update(credentials=[KEYS]), [('keys.credentials', unit)])
        self.mutate(lambda f: game(f).update(keys_env=KEYS), [('keys.credentials', unit)])

    def test_a_key_file_a_service_could_read_from_disk(self):
        self.mutate(lambda f: f['keys']['files'][0].update(owner='avrana-party'), [('keys.root_only', KEYS)])
        self.mutate(lambda f: f['keys']['files'][0].update(mode='0640'), [('keys.root_only', KEYS)])
        self.mutate(lambda f: f['keys']['dir'].update(mode='0755'), [('keys.root_only', KEYS)])

    def test_a_key_left_behind_by_a_removed_game(self):
        self.mutate(lambda f: f['keys']['files'].append(entry(f'{KEYS}/spades.key', 'root', 'root', '0600')),
                    [('keys.registered', KEYS)])

    def test_state_another_identity_can_read(self):
        self.mutate(lambda f: game(f)['state'][0].update(mode='0750'),
                    [('state.owned', 'avrana-game@checkers.service')])
        self.mutate(lambda f: game(f)['state'][0].update(owner='avrana-party'),
                    [('state.owned', 'avrana-game@checkers.service')])

    def test_a_native_game_with_ip_networking(self):
        unit = 'avrana-game@checkers.service'
        self.mutate(lambda f: game(f).update(tcp=['127.0.0.1:9000']), [('ipc.no_ip', unit)])
        self.mutate(lambda f: game(f).update(address_families=['AF_INET', 'AF_UNIX']), [('ipc.no_ip', unit)])
        self.mutate(lambda f: game(f).update(tcp=['0.0.0.0:9000']),
                    [('ipc.loopback_only', unit), ('ipc.no_ip', unit)])

    def test_sockets_that_let_the_wrong_peer_connect(self):
        unit = 'avrana-game@checkers.service'

        def sock(facts, suffix):
            return next(s for s in facts['sockets'] if s['path'].endswith(suffix))
        # the control socket open to nginx: a browser request could reach launch/end
        self.mutate(lambda f: sock(f, 'control.sock').update(group='www-data'),
                    [('ipc.socket.game_control', unit)])
        # the report socket open to another game: it could report for this one
        self.mutate(lambda f: sock(f, 'game/checkers.sock').update(group='avrana-arcade'),
                    [('ipc.socket.party_report', unit)])
        self.mutate(lambda f: sock(f, 'public.sock').update(mode='0666'), [('ipc.socket.game_public', unit)])
        self.mutate(lambda f: f['sockets'].remove(sock(f, 'control.sock')), [('ipc.socket.game_control', unit)])

    def test_party_still_on_loopback_tcp_is_a_phase_3_failure_only(self):
        change = lambda f: f['services'][0].update(tcp=['127.0.0.1:8191'])       # noqa: E731
        self.mutate(change, [('ipc.party_off_tcp', 'avrana-party-core.service')])
        self.mutate(change, [], phases=(1, 2))

    def test_missing_hardening(self):
        self.mutate(lambda f: game(f).update(no_new_privileges=False),
                    [('hardening.base', 'avrana-game@checkers.service')])
        self.mutate(lambda f: game(f).update(private_devices=False),
                    [('hardening.native', 'avrana-game@checkers.service')])


class Permissions(unittest.TestCase):
    def test_can_write(self):
        e = entry('/x', 'alice', 'staff', '0640')
        self.assertTrue(boundary.can_write('alice', {'alice'}, e))
        self.assertFalse(boundary.can_write('bob', {'bob', 'staff'}, e))
        self.assertTrue(boundary.can_write('bob', {'bob', 'staff'}, dict(e, mode='0660')))
        self.assertTrue(boundary.can_write('eve', {'eve'}, dict(e, mode='0646')))
        self.assertFalse(boundary.can_write('alice', {'alice'}, dict(e, mode='0440')))


class CommandLine(unittest.TestCase):
    def run_cli(self, facts, *args):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'facts.json'
            path.write_text(json.dumps(facts), encoding='utf-8')
            out = io.StringIO()
            with redirect_stdout(out):
                code = boundary.main(['--facts', str(path), *args])
        return code, out.getvalue()

    def test_exit_status_and_report(self):
        code, text = self.run_cli(PI)
        self.assertEqual(code, 1)
        self.assertIn('Phase 1: 6/26 rules met', text)
        self.assertIn('runs as cody, expected avrana-party', text)
        code, text = self.run_cli(target())
        self.assertEqual(code, 0)
        self.assertNotIn('FAIL', text)

    def test_one_phase_and_json(self):
        facts = copy.deepcopy(target())
        facts['services'][0]['tcp'] = ['127.0.0.1:8191']
        self.assertEqual(self.run_cli(facts, '--phase', '1', '--phase', '2')[0], 0)
        code, text = self.run_cli(facts, '--phase', '3', '--json')
        self.assertEqual(code, 1)
        self.assertEqual([r['rule'] for r in json.loads(text) if not r['ok']], ['ipc.party_off_tcp'])


if __name__ == '__main__':
    unittest.main()
