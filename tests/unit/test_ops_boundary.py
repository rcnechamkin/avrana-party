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
PARTY, GAME, ARCADE = 'avrana-party-core.service', 'avrana-game@checkers.service', 'avranaparty-arcade.service'
LEGACY = 'avranaparty-games.service'


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
             for i, (u, extra) in enumerate((('avrana-party', ['avrana-front']),
                                             ('avrana-arcade', ['input', 'video', 'render', 'audio'])))}
    return {
        'users': users,
        'groups': {'avrana-front': ['avrana-party', 'www-data'], 'avrana-games': []},
        'keys': {'dir': entry(KEYS, 'avrana-party', 'avrana-party', '0700'),
                 'files': [entry(f'{KEYS}/{k}.key', 'avrana-party', 'avrana-party', '0600')
                           for k in ('arcade-gauntlet2', 'checkers')]},
        'services': [
            # Party Core owns the store and its public API stays on loopback TCP (ADR 0016)
            service(PARTY, 'party', 'avrana-party', [], tcp=['127.0.0.1:8191'],
                    address_families=['AF_INET', 'AF_INET6', 'AF_UNIX']),
            # a native game is a dynamic identity: no user name, a uid systemd allocates
            service(GAME, 'native-game', '', [f'{KEYS}/checkers.key'], slug='checkers',
                    dynamic_user=True, supplementary_groups=['avrana-games'],
                    state=[entry('/var/lib/private/avrana-games/checkers', '61234', '61234', '0700')]),
            service(ARCADE, 'arcade', 'avrana-arcade', [f'{KEYS}/arcade-gauntlet2.key'],
                    tcp=['127.0.0.1:8097', '127.0.0.1:8098'],
                    address_families=['AF_INET', 'AF_UNIX'], private_devices=False),
        ],
        'sockets': [
            entry('/run/avrana-games/checkers.sock', 'root', 'avrana-front', '0660'),
            entry('/run/avrana-party/internal.sock', 'avrana-party', 'avrana-games', '0660'),
        ],
    }


def failed(facts, phases=(1, 2, 3)):
    return sorted({(r['rule'], r['subject']) for r in boundary.evaluate(facts, SPEC, phases) if not r['ok']})


def game(facts):
    return next(s for s in facts['services'] if s['role'] == 'native-game')


def sock(facts, suffix):
    return next(s for s in facts['sockets'] if s['path'].endswith(suffix))


class Spec(unittest.TestCase):
    def test_the_spec_names_its_decision_and_every_role_has_an_identity(self):
        self.assertEqual(SPEC['schema'], 'avrana.service-boundary/v1')
        self.assertTrue((REPO_ROOT / SPEC['decision']).is_file())
        self.assertEqual(set(SPEC['roles']), {'party', 'native-game', 'legacy-games', 'arcade'})
        self.assertEqual({u['role'] for u in SPEC['units'].values()}, set(SPEC['roles']))
        static = [r['user'] for r in SPEC['roles'].values() if 'user' in r]
        self.assertEqual(len(set(static)), 3)                                  # no shared identity
        self.assertEqual(SPEC['roles']['native-game'], {'dynamic_user': True})  # and none provisioned
        self.assertTrue((CONTRACTS_DIR / 'service-boundary.v1.json').is_file())

    def test_the_adr_and_the_spec_say_the_same_thing(self):
        adr = (REPO_ROOT / SPEC['decision']).read_text(encoding='utf-8')
        for socket in SPEC['sockets'].values():
            self.assertIn(socket['path'].replace('{slug}', '<slug>'), adr)
        for name in [g['name'] for g in SPEC['groups'].values()] + [SPEC['keys']['dir']] + \
                [r['user'] for r in SPEC['roles'].values() if 'user' in r]:
            self.assertIn(name, adr)
        self.assertIn('DynamicUser=yes', adr)

    def test_no_socket_is_open_to_everyone_and_none_is_abstract(self):
        for socket in SPEC['sockets'].values():
            self.assertEqual(socket['mode'], '0660')
            self.assertTrue(socket['path'].startswith('/run/avrana-'))

    def test_a_game_is_not_in_the_group_that_reaches_other_games(self):
        """The front group gates every game's socket, so no game identity may be a member."""
        self.assertEqual(SPEC['groups']['front']['members'], ['avrana-party', 'www-data'])
        self.assertNotEqual(SPEC['groups']['front']['name'], SPEC['groups']['games']['name'])


class TheApplianceToday(unittest.TestCase):
    """Facts recorded on the Pi on 2026-10-03. This is the prototype, not the target."""

    def test_every_service_is_the_operator(self):
        self.assertEqual({s['user'] for s in PI['services']}, {'cody'})
        self.assertIn('sudo', PI['users']['cody']['groups'])
        bad = failed(PI, (1,))
        for unit in (PARTY, LEGACY, ARCADE):
            for rule in ('identity.expected', 'identity.distinct', 'identity.unprivileged', 'code.readonly'):
                self.assertIn((rule, unit), bad)
        for unit in (LEGACY, ARCADE):                       # both read the whole key directory
            self.assertIn(('keys.credentials', unit), bad)

    def test_a_0600_key_is_reported_as_no_boundary(self):
        """The keys are 0600, and their owner is the user every service runs as."""
        self.assertEqual({f['mode'] for f in PI['keys']['files']}, {'0600'})
        self.assertIn(('keys.party_owned', KEYS), failed(PI, (1,)))
        detail = next(r['detail'] for r in boundary.evaluate(PI, SPEC, (1,)) if r['rule'] == 'keys.party_owned')
        self.assertIn('cody:cody', detail)

    def test_the_games_listener_is_not_loopback_and_the_shared_process_runs(self):
        self.assertIn(('ipc.loopback_only', LEGACY), failed(PI, (1,)))
        self.assertEqual(failed(PI, (3,)), [('legacy.retired', LEGACY)])

    def test_party_on_loopback_tcp_is_not_a_failure(self):
        """Owner decision: Party's public API stays on loopback TCP for the field test."""
        self.assertEqual(next(s for s in PI['services'] if s['role'] == 'party')['tcp'], ['127.0.0.1:8191'])
        self.assertNotIn(PARTY, {subject for rule, subject in failed(PI) if rule.startswith('ipc.')})

    def test_what_already_holds_is_reported_as_holding(self):
        ok = {(r['rule'], r['subject']) for r in boundary.evaluate(PI, SPEC, (1,)) if r['ok']}
        self.assertIn(('hardening.base', PARTY), ok)
        self.assertIn(('ipc.loopback_only', ARCADE), ok)
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

    def test_a_native_game_given_a_static_or_shared_user(self):
        def change(f):
            game(f).update(dynamic_user=False, user='avrana-party')
        self.mutate(change, [('identity.distinct', GAME), ('identity.expected', GAME),
                             ('identity.distinct', PARTY), ('state.owned', GAME)])

    def test_a_platform_service_that_is_not_its_own_static_user(self):
        self.mutate(lambda f: f['services'][2].update(user='avrana-party'),
                    [('identity.distinct', ARCADE), ('identity.distinct', PARTY),
                     ('identity.expected', ARCADE), ('state.owned', ARCADE)])

    def test_a_service_that_could_become_root(self):
        self.mutate(lambda f: game(f)['supplementary_groups'].append('sudo'),
                    [('identity.groups', GAME), ('identity.unprivileged', GAME)])
        self.mutate(lambda f: f['users']['avrana-party'].update(shell='/bin/bash'),
                    [('identity.unprivileged', PARTY)])

    def test_a_game_that_could_reach_other_games(self):
        """Membership of the front group would let one game connect to every game's socket."""
        self.mutate(lambda f: game(f).update(supplementary_groups=['avrana-front', 'avrana-games']),
                    [('identity.groups', GAME)])
        self.mutate(lambda f: f['groups']['avrana-front'].append('avrana-arcade'),
                    [('groups.front', 'avrana-front')])

    def test_a_service_that_can_rewrite_code(self):
        self.mutate(lambda f: game(f)['code'].append(entry('/opt/x', 'root', 'avrana-games', '0775')),
                    [('code.readonly', GAME)])
        self.mutate(lambda f: game(f)['code'].append(entry('/opt/x', 'root', 'root', '0777')),
                    [('code.readonly', GAME)])
        self.mutate(lambda f: f['services'][0]['code'].append(entry('/opt/y', 'avrana-party', 'root', '0755')),
                    [('code.readonly', PARTY)])

    def test_a_game_handed_more_than_its_own_key(self):
        self.mutate(lambda f: game(f)['credentials'].append(f'{KEYS}/arcade-gauntlet2.key'),
                    [('keys.credentials', GAME)])
        self.mutate(lambda f: game(f).update(credentials=[KEYS]), [('keys.credentials', GAME)])
        self.mutate(lambda f: game(f).update(keys_env=KEYS), [('keys.credentials', GAME)])

    def test_a_key_store_someone_other_than_party_can_read(self):
        self.mutate(lambda f: f['keys']['files'][0].update(owner='avrana-arcade'), [('keys.party_owned', KEYS)])
        self.mutate(lambda f: f['keys']['files'][0].update(mode='0640'), [('keys.party_owned', KEYS)])
        self.mutate(lambda f: f['keys']['dir'].update(mode='0755'), [('keys.party_owned', KEYS)])

    def test_a_key_left_behind_by_a_removed_game(self):
        self.mutate(lambda f: f['keys']['files'].append(
            entry(f'{KEYS}/spades.key', 'avrana-party', 'avrana-party', '0600')), [('keys.registered', KEYS)])

    def test_state_another_identity_can_read(self):
        self.mutate(lambda f: game(f)['state'][0].update(mode='0750'), [('state.owned', GAME)])
        self.mutate(lambda f: f['services'][0]['state'][0].update(owner='avrana-arcade'),
                    [('state.owned', PARTY)])

    def test_a_native_game_with_ip_networking(self):
        self.mutate(lambda f: game(f).update(tcp=['127.0.0.1:9000']), [('ipc.no_ip', GAME)])
        self.mutate(lambda f: game(f).update(address_families=['AF_INET', 'AF_UNIX']), [('ipc.no_ip', GAME)])
        self.mutate(lambda f: game(f).update(tcp=['0.0.0.0:9000']),
                    [('ipc.loopback_only', GAME), ('ipc.no_ip', GAME)])

    def test_sockets_that_let_the_wrong_peer_connect(self):
        # a game's socket owned by the game: it would have to be in the front group to share it
        self.mutate(lambda f: sock(f, 'checkers.sock').update(group='avrana-games'), [('ipc.socket.game', GAME)])
        self.mutate(lambda f: sock(f, 'checkers.sock').update(mode='0666'), [('ipc.socket.game', GAME)])
        self.mutate(lambda f: f['sockets'].remove(sock(f, 'checkers.sock')), [('ipc.socket.game', GAME)])
        # Party's internal socket open to the front door: a browser request could reach it
        self.mutate(lambda f: sock(f, 'internal.sock').update(group='avrana-front'),
                    [('ipc.socket.party_internal', PARTY)])
        self.mutate(lambda f: f['sockets'].remove(sock(f, 'internal.sock')),
                    [('ipc.socket.party_internal', PARTY)])

    def test_the_legacy_process_is_a_phase_3_failure_only(self):
        def change(f):
            f['users']['avrana-lan-games'] = {'uid': 950, 'shell': NOLOGIN, 'groups': ['avrana-lan-games']}
            f['keys']['files'] += [entry(f'{KEYS}/{k}.key', 'avrana-party', 'avrana-party', '0600')
                                   for k in ('bluff', 'expo')]
            f['services'].append(service(LEGACY, 'legacy-games', 'avrana-lan-games',
                                         [f'{KEYS}/bluff.key', f'{KEYS}/expo.key'], tcp=['127.0.0.1:8096'],
                                         address_families=['AF_INET', 'AF_UNIX']))
        self.mutate(change, [('legacy.retired', LEGACY)])
        self.mutate(change, [], phases=(1, 2))

    def test_missing_hardening(self):
        self.mutate(lambda f: game(f).update(no_new_privileges=False), [('hardening.base', GAME)])
        self.mutate(lambda f: game(f).update(private_devices=False), [('hardening.native', GAME)])


class Permissions(unittest.TestCase):
    def test_can_write(self):
        e = entry('/x', 'alice', 'staff', '0640')
        self.assertTrue(boundary.can_write('alice', {'alice'}, e))
        self.assertFalse(boundary.can_write('bob', {'bob', 'staff'}, e))
        self.assertTrue(boundary.can_write('bob', {'bob', 'staff'}, dict(e, mode='0660')))
        self.assertTrue(boundary.can_write('eve', {'eve'}, dict(e, mode='0646')))
        self.assertFalse(boundary.can_write('alice', {'alice'}, dict(e, mode='0440')))
        self.assertFalse(boundary.can_write(None, {'avrana-games'}, e))          # a dynamic identity


class Collection(unittest.TestCase):
    """`systemctl show` prints LoadCredential as "[unprintable]" (seen on systemd 255 in the proof
    run), so the collector reads the unit's own text."""

    def credentials(self, show, cat):
        real = boundary._run
        boundary._run = lambda *argv: cat if argv[:2] == ('systemctl', 'cat') else ''
        try:
            return boundary._credentials('x.service', {'LoadCredential': show})
        finally:
            boundary._run = real

    def test_credentials_come_from_the_unit_text_when_show_cannot_print_them(self):
        cat = '\n'.join(('# /etc/systemd/system/x.service', '[Service]', 'LoadCredential=b.key:/k/b.key',
                         '# /etc/systemd/system/x.service.d/y.conf', '[Service]',
                         'LoadCredential=a.key:/k/a.key', ''))
        self.assertEqual(self.credentials('[unprintable]', cat), ['/k/a.key', '/k/b.key'])
        self.assertEqual(self.credentials('', ''), [])

    def test_an_empty_assignment_resets_the_list(self):
        cat = '\n'.join(('LoadCredential=old.key:/k/old.key', 'LoadCredential=',
                         'LoadCredential=new.key:/k/new.key', ''))
        self.assertEqual(self.credentials('[unprintable]', cat), ['/k/new.key'])

    def test_a_printable_value_is_used_as_is(self):
        self.assertEqual(self.credentials('a.key:/k/a.key', 'LoadCredential=z.key:/k/z.key'), ['/k/a.key'])


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
        self.assertIn('Phase 1: 6/25 rules met', text)
        self.assertIn('runs as cody, expected avrana-party', text)
        code, text = self.run_cli(target())
        self.assertEqual(code, 0)
        self.assertNotIn('FAIL', text)

    def test_one_phase_and_json(self):
        facts = copy.deepcopy(target())
        game(facts)['address_families'] = ['AF_INET', 'AF_UNIX']
        self.assertEqual(self.run_cli(facts, '--phase', '1', '--phase', '3')[0], 0)
        code, text = self.run_cli(facts, '--phase', '2', '--json')
        self.assertEqual(code, 1)
        self.assertEqual([r['rule'] for r in json.loads(text) if not r['ok']], ['ipc.no_ip'])


if __name__ == '__main__':
    unittest.main()
