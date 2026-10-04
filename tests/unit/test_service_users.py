"""ADR 0016 phase 1 (AVR-256): the three existing services as dedicated users.

`tests/fixtures/boundary/after-phase-1.json` is a synthetic host: what the boundary collector
would report after ops/migrate-service-users.sh has run. It was never recorded on a machine. So
that it cannot drift from the source it stands for, everything in it that a unit file decides
(user, hardening, credentials, working directory) is compared here with the unit files in this
repository. The fork's unit lives in the Games repository; its entry is checked there.

The migration script itself is only ever dry-run here: it changes users, ownership and units on a
real host, and running it is an owner deployment (docs/runbooks/service-users-migration.md)."""
import copy
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from avrana import REPO_ROOT
from avrana.ops import boundary

SPEC = boundary.load_spec()
AFTER = json.loads((REPO_ROOT / 'tests/fixtures/boundary/after-phase-1.json').read_text(encoding='utf-8'))
PI = json.loads((REPO_ROOT / 'tests/fixtures/boundary/pi-2026-10-03.json').read_text(encoding='utf-8'))
PARTY, ARCADE, LEGACY = 'avrana-party-core.service', 'avranaparty-arcade.service', 'avranaparty-games.service'
UNITS = {
    PARTY: ['deploy/party-core/avrana-party-core.service'],
    ARCADE: ['arcade/avranaparty-arcade.service', 'deploy/arcade/avrana-party-session.conf'],
}
SCRIPT = REPO_ROOT / 'ops/migrate-service-users.sh'
BASH = shutil.which('bash')


def unit_text(unit):
    return '\n'.join((REPO_ROOT / p).read_text(encoding='utf-8') for p in UNITS[unit])


def directives(unit):
    """{key: [values]} of a unit and its drop-in, comments left out."""
    out = {}
    for line in unit_text(unit).splitlines():
        key, sep, value = line.partition('=')
        if sep and not line.lstrip().startswith('#'):
            out.setdefault(key.strip(), []).append(value.strip())
    return out


def credentials(unit):
    real = boundary._run
    boundary._run = lambda *argv: unit_text(unit) if argv[:2] == ('systemctl', 'cat') else ''
    try:
        return boundary._credentials(unit, {})
    finally:
        boundary._run = real


def service(facts, unit):
    return next(s for s in facts['services'] if s['unit'] == unit)


def failed(facts, phases=(1,)):
    return sorted({(r['rule'], r['subject']) for r in boundary.evaluate(facts, SPEC, phases) if not r['ok']})


class UnitFiles(unittest.TestCase):
    def test_no_unit_names_the_operator_or_a_home_directory(self):
        for unit in UNITS:
            for key, values in directives(unit).items():
                for value in values:
                    self.assertNotRegex(value, r'\bcody\b|/home/', f'{unit}: {key}={value}')

    def test_each_runs_as_the_identity_the_contract_names(self):
        for unit in UNITS:
            d = directives(unit)
            user = SPEC['roles'][SPEC['units'][unit]['role']]['user']
            self.assertEqual((d['User'], d['Group']), ([user], [user]), unit)
            self.assertEqual((d['NoNewPrivileges'], d['ProtectSystem'], d['ProtectHome']), (['yes'], ['strict'], ['yes']), unit)
            self.assertTrue(d['WorkingDirectory'][0].startswith('/opt/avrana-party/current'), unit)

    def test_the_arcade_keeps_only_its_device_groups_and_writes_only_under_its_state_directory(self):
        d = directives(ARCADE)
        self.assertEqual(d['SupplementaryGroups'], ['input video render'])
        self.assertEqual((d['StateDirectory'], d['StateDirectoryMode']), (['avrana-arcade'], ['0700']))
        env = dict(v.split('=', 1) for v in d['Environment'])
        self.assertEqual(env['AVRANA_ARCADE_RUNTIME'], '%S/avrana-arcade')
        self.assertFalse(env['AVRANA_ARCADE_CORE'].startswith('/opt/avrana-party/'))     # not in Git, not in a release
        self.assertEqual(env['AVRANA_PARTY_KEYS'], '%d')
        for script in ('arcade/run-stream.sh', 'arcade/with-audio.sh'):
            self.assertNotIn('/home/', (REPO_ROOT / script).read_text(encoding='utf-8'), script)

    def test_party_core_is_handed_no_credential_and_the_arcade_exactly_its_own_key(self):
        self.assertEqual(credentials(PARTY), [])
        self.assertEqual(credentials(ARCADE), ['/etc/avrana-party/game-keys/arcade-gauntlet2.key'])


class TheHostAfterPhase1(unittest.TestCase):
    def test_the_fixture_says_what_the_unit_files_say(self):
        for unit in UNITS:
            d, s = directives(unit), service(AFTER, unit)
            self.assertEqual(s['user'], d['User'][0], unit)
            self.assertEqual(s['credentials'], credentials(unit), unit)
            self.assertEqual((s['no_new_privileges'], s['protect_system'], s['protect_home']), (True, 'strict', 'yes'), unit)
            self.assertNotIn('keys_env', s, unit)
            self.assertIn(d['WorkingDirectory'][0], [c['path'] for c in s['code']], unit)
        self.assertEqual(sorted(service(AFTER, ARCADE)['user_groups']),
                         sorted(['avrana-arcade'] + directives(ARCADE)['SupplementaryGroups'][0].split()))

    def test_it_meets_every_phase_1_rule_where_the_pi_met_six(self):
        results = boundary.evaluate(AFTER, SPEC, (1,))
        self.assertEqual([r for r in results if not r['ok']], [])
        self.assertEqual(len(results), 25)                       # the same 25 rules the Pi was judged by
        self.assertEqual(sum(r['ok'] for r in boundary.evaluate(PI, SPEC, (1,))), 6)
        self.assertEqual(failed(AFTER, (3,)), [('legacy.retired', LEGACY)])       # phase 3 is AVR-228's

    def mutate(self, change, expected):
        facts = copy.deepcopy(AFTER)
        change(facts)
        self.assertEqual(failed(facts), sorted(expected))

    def test_each_single_departure_is_reported(self):
        self.mutate(lambda f: service(f, ARCADE).update(user='cody'),
                    [('identity.expected', ARCADE), ('identity.unprivileged', ARCADE), ('state.owned', ARCADE)])
        self.mutate(lambda f: service(f, LEGACY).update(user='avrana-party'),
                    [('identity.distinct', LEGACY), ('identity.distinct', PARTY), ('identity.expected', LEGACY),
                     ('state.owned', LEGACY)])
        self.mutate(lambda f: service(f, ARCADE).update(keys_env='/etc/avrana-party/game-keys'),
                    [('keys.credentials', ARCADE)])
        self.mutate(lambda f: service(f, LEGACY)['credentials'].pop(), [('keys.credentials', LEGACY)])
        self.mutate(lambda f: service(f, PARTY)['code'][0].update(owner='avrana-party'), [('code.readonly', PARTY)])
        self.mutate(lambda f: service(f, LEGACY)['state'][0].update(mode='0775'), [('state.owned', LEGACY)])
        self.mutate(lambda f: service(f, LEGACY).update(tcp=['0.0.0.0:8096']), [('ipc.loopback_only', LEGACY)])
        self.mutate(lambda f: f['keys']['dir'].update(owner='cody', group='cody'),
                    [('keys.party_owned', '/etc/avrana-party/game-keys')])
        self.mutate(lambda f: service(f, ARCADE).update(no_new_privileges=False), [('hardening.base', ARCADE)])
        self.mutate(lambda f: f['users']['avrana-lan-games']['groups'].append('sudo'),
                    [('identity.unprivileged', LEGACY)])


@unittest.skipUnless(os.name == 'posix' and BASH, 'needs bash and POSIX modes')
class MigrationScript(unittest.TestCase):
    """Dry run only: what it would do, and what makes it refuse."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        party = self.tmp / 'opt-party/releases/aaa'
        shutil.copytree(REPO_ROOT / 'deploy', party / 'deploy')
        (party / 'arcade').mkdir()
        shutil.copy(REPO_ROOT / 'arcade/avranaparty-arcade.service', party / 'arcade')
        (party / 'avrana/party').mkdir(parents=True)
        shutil.copy(REPO_ROOT / 'avrana/party/protocol.py', party / 'avrana/party')
        games = self.tmp / 'opt-games/releases/bbb'
        (games / 'core').mkdir(parents=True)
        (games / 'core/party_protocol.py').write_text("ACL_XATTR = 'system.posix_acl_access'\n")
        (games / 'deploy').mkdir()
        for name in ('avranaparty-games.service', 'avrana-party-session.conf'):
            (games / 'deploy' / name).write_text('[Service]\n')
        for root, sha in (('opt-party', 'aaa'), ('opt-games', 'bbb')):
            os.symlink(self.tmp / root / 'releases' / sha, self.tmp / root / 'current')
            subprocess.run(['chmod', '-R', 'go-w', str(self.tmp / root)], check=True)
        self.core = self.tmp / 'core.so'
        self.core.write_bytes(b'core')
        (self.tmp / 'venv/bin').mkdir(parents=True)
        (self.tmp / 'venv/bin/python').write_text('#!/bin/sh\n')
        (self.tmp / 'venv/bin/python').chmod(0o755)
        (self.tmp / 'keys').mkdir(mode=0o700)
        (self.tmp / 'keys/arcade-gauntlet2.key').write_text('0' * 64 + '\n')
        self.env = dict(
            os.environ, AVRANA_PARTY_RELEASES=str(self.tmp / 'opt-party'), AVRANA_GAMES_RELEASES=str(self.tmp / 'opt-games'),
            AVRANA_ARCADE_CORE_SOURCE=str(self.core), AVRANA_ARCADE_CORE_TARGET=str(self.tmp / 'arcade-core/core.so'),
            AVRANA_GAMES_VENV_SOURCE=str(self.tmp / 'venv'), AVRANA_GAMES_VENV_TARGET=str(self.tmp / 'venv-root'),
            AVRANA_PARTY_KEY_DIR=str(self.tmp / 'keys'), AVRANA_DEVICE_STORE=str(self.tmp / 'devices'),
            AVRANA_GAMES_STATE=str(self.tmp / 'games-state'), AVRANA_GAMES_CHECKOUT=str(self.tmp / 'games-checkout'),
            AVRANA_UNIT_DIR=str(self.tmp / 'units'), AVRANA_BACKUP_ROOT=str(self.tmp / 'backups'),
            AVRANA_PARTY_CORE_URL='http://127.0.0.1:1')

    def run_script(self, *args):
        return subprocess.run([BASH, str(SCRIPT), *args], capture_output=True, text=True, env=self.env, timeout=60)

    def test_syntax(self):
        self.assertEqual(subprocess.run([BASH, '-n', str(SCRIPT)], capture_output=True).returncode, 0)

    def test_dry_run_prints_the_plan_and_changes_nothing(self):
        before = sorted(str(p) for p in self.tmp.rglob('*'))
        r = self.run_script('--dry-run')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for expected in ('groupadd --system avrana-front', 'groupadd --system avrana-games',
                         'usermod -a -G avrana-front www-data', 'usermod -a -G input,video,render avrana-arcade',
                         f'chown -R avrana-party:avrana-party {self.tmp}/keys',
                         'systemctl stop avrana-party-core', 'systemctl daemon-reload',
                         f'{self.tmp}/units/avranaparty-arcade.service.d/avrana-party-session.conf',
                         f'{self.tmp}/units/avranaparty-games.service', 'dry run: nothing changed'):
            self.assertIn(expected, r.stdout)
        for user in ('avrana-party', 'avrana-arcade', 'avrana-lan-games'):
            self.assertRegex(r.stdout, rf'useradd --system .*--shell /usr/sbin/nologin {user}\n')
        self.assertRegex(r.stdout, r'arcade core sha256: [0-9a-f]{64} ')
        self.assertNotRegex(r.stdout, r'(?i)curl|wget|pip|apt')                        # nothing is downloaded
        self.assertEqual(sorted(str(p) for p in self.tmp.rglob('*')), before)

    def test_refuses_without_what_it_needs(self):
        key = self.tmp / 'keys/arcade-gauntlet2.key'
        key.unlink()                       # a unit whose credential source is missing never starts
        r = self.run_script('--dry-run')
        self.assertEqual(r.returncode, 1)
        self.assertIn('provision-party-game-key.sh arcade-gauntlet2', r.stderr)
        key.write_text('0' * 64 + '\n')
        self.core.unlink()
        r = self.run_script('--dry-run')
        self.assertEqual(r.returncode, 1)
        self.assertIn('nothing is downloaded', r.stderr)
        self.core.write_bytes(b'core')
        (self.tmp / 'opt-games/current/deploy/avranaparty-games.service').unlink()
        self.assertIn('Games half of AVR-256', self.run_script('--dry-run').stderr)
        (self.tmp / 'opt-games/current/deploy/avranaparty-games.service').write_text('[Service]\n')
        (self.tmp / 'opt-games/current/core/party_protocol.py').write_text('old\n')
        self.assertIn('AVR-253', self.run_script('--dry-run').stderr)
        (self.tmp / 'opt-party/current/deploy/README.md').chmod(0o666)
        self.assertIn('writable by root only', self.run_script('--dry-run').stderr)

    def test_refuses_to_run_for_real_without_root(self):
        if os.geteuid() == 0:
            self.skipTest('running as root')
        r = self.run_script()
        self.assertEqual(r.returncode, 1)
        self.assertIn('run as root', r.stderr)
        self.assertIn('not a backup', self.run_script('--dry-run', '--reverse', str(self.tmp)).stderr)


if __name__ == '__main__':
    unittest.main()
