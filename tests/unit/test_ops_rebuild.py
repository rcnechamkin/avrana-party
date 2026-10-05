"""A clean target against deploy/appliance-inventory.json (AVR-32).

Three things are pinned here, all Tier 1 (no device, any platform):

  1. the inventory agrees with what the repository would install: unit files, drop-ins, the
     installers' package and user lists, the network profile the scripts name, the paths the
     units and the nginx site read. A unit added without an inventory entry fails here;
  2. the procedure of docs/runbooks/rebuild.md, rehearsed on a SIMULATED host (real file
     contents in a temporary directory; owners, modes, users, packages and units in a ledger):
     a clean host reaches the expected state, `plan` changes nothing, a second `apply` changes
     nothing, secrets are handoffs that the tool never creates, reads or copies, and `restore`
     puts replaced files back;
  3. the runbook names every handoff and every unknown.

None of this is evidence about a Raspberry Pi: the commands a real `apply` runs (apt-get, useradd,
systemctl, nginx) are recorded here, never executed, and the simulated host answers as the
inventory expects. Building a device is an owner step.
"""
import contextlib
import copy
import hashlib
import io
import json
import os
import platform
import re
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from avrana import REPO_ROOT
from avrana.ops import rebuild, smoke, status

INV = rebuild.load_inventory()
RUNBOOK = (REPO_ROOT / 'docs/runbooks/rebuild.md').read_text(encoding='utf-8')
SENTINEL = b'SIMULATED-SECRET-never-a-real-key'
GAMES_UNIT = '[Service]\nUser=avrana-lan-games\n'
SECRET_PATHS = [p['path'] for s in INV['secrets'] for p in s['paths']]


def text(rel):
    return (REPO_ROOT / rel).read_text(encoding='utf-8')


def by(section, key='id'):
    return {entry[key]: entry for entry in INV[section]}


def tree(root):
    """{relative path: sha256} of every real file under a simulated host, ledger included."""
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(root).rglob('*')) if p.is_file()}


class Simulated(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / 'host'
        self.clock = 0

    def host(self, readonly=False):
        return rebuild.Host(self.root, readonly=readonly)

    def plan(self):
        return rebuild.plan(INV, self.host(readonly=True))

    def apply(self, **kw):
        self.clock += 1
        now = datetime(2026, 1, 1, 0, 0, self.clock, tzinfo=timezone.utc)
        return rebuild.apply(INV, self.host(), now=now, log=lambda *_: None, **kw)

    def statuses(self, kind=None):
        return {s['name']: s['status'] for s in self.plan() if kind in (None, s['kind'])}

    def hand_over(self, only=None):
        """What the owner and the existing scripts provide between two applies: stand-ins for
        the checkouts, releases, core, ROM, lego, the keys and the certificate."""
        host = self.host()
        for artifact in INV['artifacts']:
            if only in (None, artifact['id']):
                host.install(b'stand-in', artifact['path'], 'root', 'root', '0644')
        for rel in ('deploy/avranaparty-games.service', 'deploy/avrana-party-session.conf'):
            if only in (None, 'games-release'):
                host.install(GAMES_UNIT.encode(), f'{rebuild.GAMES_RELEASE}/{rel}', 'root', 'root', '0644')
        for secret in INV['secrets']:
            if only in (None, secret['id']) and not secret.get('optional'):
                for p in secret['paths']:
                    host.install(SENTINEL, p['path'], p['owner'], p['group'], p['mode'])

    def build(self):
        first = self.apply()
        self.hand_over()
        second = self.apply(activate=True)
        return first, second


class Inventory(unittest.TestCase):
    def test_it_agrees_with_the_repository(self):
        self.assertEqual(rebuild.validate(INV), [])

    def test_every_installable_unit_and_config_in_the_repository_is_listed(self):
        sources = {f['source'].partition(':')[2] for f in INV['files'] if f['source'].startswith('party:')}
        telemetry = 'installed by the telemetry scripts, optional (inventory not_managed)'
        elsewhere = {'telemetry/beszel-agent.service': telemetry, 'telemetry/pi-throttle-check.service': telemetry,
                     'telemetry/pi-throttle-check.timer': telemetry}
        self.assertTrue(any('telemetry' in n['what'] for n in INV['not_managed']))
        found = set()
        for pattern in ('**/*.service', '**/*.timer', '**/*.socket', 'deploy/**/*.conf', 'arcade/*.rules',
                        'arcade/avrana-uinput.conf', '*.nginx', 'avrana-captive.conf'):
            found |= {p.relative_to(REPO_ROOT).as_posix() for p in REPO_ROOT.glob(pattern)
                      if 'node_modules' not in p.parts and not p.parts[len(REPO_ROOT.parts)].startswith('.')}
        self.assertGreaterEqual(len(found), 10)
        self.assertEqual(sorted(found - sources - set(elsewhere)), [],
                         'a unit or config file in the repository that no rebuild would install')

    def test_units_are_installed_where_the_migration_installs_them(self):
        script = text('ops/migrate-service-users.sh')
        pairs = re.findall(r'^\s+"([^"=]+)=\$(party|games)_release/([^"]+)"$', script, re.M)
        self.assertEqual(len(pairs), 5)
        listed = {(f['path'], f['source']) for f in INV['files']}
        for name, repo, rel in pairs:
            self.assertIn((f'/etc/systemd/system/{name}', f'{repo}:{rel}'), listed)

    def test_service_identities_are_the_migration_s(self):
        script = text('ops/migrate-service-users.sh')
        self.assertEqual({g['name'] for g in INV['groups']},
                         set(re.search(r'for group in ([a-z -]+); do', script).group(1).split()))
        self.assertEqual({u['name'] for u in INV['users']},
                         set(re.search(r'for user in ([a-z -]+); do', script).group(1).split()))
        members = {u['name']: set(u['groups']) for u in INV['users']}
        members.update({m['user']: set(m['groups']) for m in INV['memberships']})
        for groups, user in re.findall(r'^run usermod -a -G (\S+) (\S+)$', script, re.M):
            self.assertEqual(members[user], set(groups.split(',')), user)
        # ...and apply creates them with the same flags.
        self.assertIn('useradd --system --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin',
                      script)

    def test_scripted_packages_are_exactly_the_arcade_installer_s(self):
        listed = re.search(r'--no-install-recommends \\\n(.*)', text('arcade/install-dependencies.sh'), re.S).group(1)
        self.assertEqual({p['name'] for p in INV['packages'] if p['confidence'] == 'scripted'},
                         set(listed.replace('\\', ' ').split()))
        names = [p['name'] for p in INV['packages']]
        self.assertEqual(len(names), len(set(names)))

    def test_every_key_a_unit_or_the_config_names_is_a_secret_with_a_provisioning_path(self):
        secret_paths = set(SECRET_PATHS)
        named = set(re.findall(r'^LoadCredential=[^:]+:(\S+)$', text('deploy/arcade/avrana-party-session.conf'), re.M))
        config = json.loads(text('deploy/party-core/party-core.example.json'))
        named |= {game['key_file'] for game in config['games'].values()}
        self.assertEqual(len(named), 3)
        self.assertLessEqual(named, secret_paths)
        self.assertIn(config['status']['certificate'], secret_paths)
        for secret in INV['secrets']:
            self.assertTrue(secret['provision'], secret['id'])
        for slug in config['games']:
            self.assertIn(f'provision-party-game-key.sh {slug}', by('secrets')[f'game-key-{slug}']['provision'])
        core = by('units', 'name')['avrana-party-core']['requires']
        for slug in config['games']:
            self.assertIn(f'secret:game-key-{slug}', core)       # Party Core starts only with every key

    def test_units_cover_what_status_and_smoke_expect(self):
        units = by('units', 'name')
        self.assertLessEqual(set(status.DEFAULT_CONFIG['units']), set(units))
        self.assertEqual({n for n, u in units.items() if u.get('optional')}, set(status.DEFAULT_CONFIG['optional_units']))

    def test_paths_are_the_ones_the_units_and_the_site_read(self):
        artifacts, site = by('artifacts'), text('avrana-party.nginx')
        self.assertEqual(set(re.findall(r'ssl_certificate(?:_key)? (\S+);', site)),
                         {p['path'] for p in by('secrets')['tls-certificate']['paths']})
        web = re.search(r'alias (/var/www/\S+)/;', site).group(1)
        self.assertTrue(artifacts['web-release']['path'].startswith(web + '/'))
        for unit in ('deploy/party-core/avrana-party-core.service', 'arcade/avranaparty-arcade.service'):
            workdir = re.search(r'^WorkingDirectory=(\S+)', text(unit), re.M).group(1)
            self.assertTrue(workdir.startswith('/opt/avrana-party/current'), unit)
        self.assertTrue(artifacts['party-release']['path'].startswith('/opt/avrana-party/current/'))
        self.assertIn(f'AVRANA_ARCADE_CORE={artifacts["arcade-core"]["path"]}', text('arcade/avranaparty-arcade.service'))
        self.assertIn(f"ROM = '{artifacts['arcade-rom']['path']}'", text('arcade/stream.py'))
        renew = text('ops/renew-party-certificate.sh')
        self.assertIn(f'lego={artifacts["lego"]["path"]}', renew)
        self.assertIn(f'credentials={by("secrets")["cloudflare-token"]["paths"][0]["path"]}', renew)
        installed = {f['path'] for f in INV['files']}
        self.assertIn(re.search(r'^ExecStart=(\S+)', text('ops/avrana-party-certificate.service'), re.M).group(1), installed)
        self.assertIn(status.DEFAULT_CONFIG['certificate'], SECRET_PATHS)
        self.assertEqual(rebuild.GAMES_RELEASE + '/server.py', artifacts['games-release']['path'])
        core = json.loads(text(artifacts['arcade-core']['sha256_evidence']))
        self.assertRegex(core['core_sha256'], r'^[0-9a-f]{64}$')

    def test_the_network_profile_is_the_one_every_script_targets(self):
        net = INV['network']
        ap, address = net['access_point'], net['party_address']
        self.assertEqual(ap['address'], address + '/24')
        self.assertIn(f"'AVRANA_AP_PROFILE', '{ap['profile']}'", text('install-captive-dns.py'))
        self.assertIn(f"ap='{ap['profile']}'", text('ops/deploy-party-https.sh'))
        self.assertIn(f'ifname {ap["interface"]}', text('ops/deploy-party-https.sh'))
        topology = text('tools/avrana-topology-check')
        self.assertIn(f'AP={ap["interface"]}; ADDR={address}; APN="{ap["profile"]}"', topology)
        self.assertIn(f'--dhcp-range={net["dhcp_range"]}', topology)
        self.assertIn('upstream path via ' + net['management']['interface'], topology)
        captive = text('avrana-captive.conf')
        self.assertEqual(set(re.findall(r'^address=/[^/]+/(\S+)$', captive, re.M)), {address})
        self.assertIn(f'host-record={net["party_hostname"]},{address}', captive)
        self.assertEqual(smoke.HOST, net['party_hostname'])
        self.assertEqual(smoke.check_dns.__defaults__[0], address)
        for rel in net['pinned_in']:
            self.assertIn(address, text(rel), rel)
        record = text(net['evidence'])                 # the dated record the profile is taken from
        for fact in (f'"{ap["profile"]}"', f'interface `{ap["interface"]}`', f'mode `{ap["mode"]}`',
                     f'band `{ap["band"]}`', f'channel {ap["channel"]}', f'`{ap["key_mgmt"]}`',
                     f'`ipv4.method {ap["ipv4_method"]}`', f'`ipv4.addresses {ap["address"]}`',
                     f'`ipv6.method {ap["ipv6_method"]}`', f'ssid "{ap["ssid"]}"'):
            self.assertIn(fact, record)

    def test_the_access_point_command_carries_no_passphrase(self):
        argv = rebuild.ap_profile_command(INV)
        self.assertEqual(argv[:3], ['nmcli', 'connection', 'add'])
        self.assertFalse([a for a in argv if 'psk' in a.lower() and a != 'wpa-psk'])
        out = []
        self.assertEqual(rebuild.main(['ap-profile'], out=out.append), 0)
        self.assertIn('--ask', '\n'.join(out))
        self.assertNotIn('wifi-sec.psk', '\n'.join(out))

    def test_nothing_secret_is_in_the_inventory(self):
        raw = text('deploy/appliance-inventory.json')
        self.assertNotRegex(raw, r'\b[0-9a-f]{40,}\b')              # no key, token or fingerprint
        self.assertNotRegex(raw, r'BEGIN [A-Z ]*PRIVATE KEY|psk=|CF_DNS_API_TOKEN\s*=')
        for secret in INV['secrets']:
            self.assertNotIn('value', secret)

    @unittest.skipUnless(os.environ.get('AVRANA_GAMES_REPO'), 'set AVRANA_GAMES_REPO to a Games checkout')
    def test_the_games_repository_has_what_the_inventory_installs_from_it(self):
        games = Path(os.environ['AVRANA_GAMES_REPO'])
        sources = [f for f in INV['files'] if f['source'].startswith('games:')]
        self.assertEqual(len(sources), 2)
        merged = ''
        for f in sources:
            path = games / f['source'].partition(':')[2]
            self.assertTrue(path.is_file(), path)
            merged += path.read_text(encoding='utf-8')
        self.assertIn('User=avrana-lan-games', merged)
        self.assertIn(f'WorkingDirectory={rebuild.GAMES_RELEASE}', merged)
        self.assertIn(by('artifacts')['games-venv']['path'], merged)
        self.assertTrue((games / 'requirements.txt').is_file())        # what the games-venv handoff installs
        keys = set(re.findall(r'^LoadCredential=[^:]+:(\S+)$', merged, re.M))
        dropin = next(f for f in sources if f['path'].endswith('.conf'))
        self.assertEqual({f'secret:game-key-{Path(k).stem}' for k in keys},
                         {r for r in dropin['requires'] if r.startswith('secret:')})
        self.assertLessEqual(keys, set(SECRET_PATHS))

    def test_drift_is_named(self):
        def broken(change):
            inv = copy.deepcopy(INV)
            change(inv)
            return ' | '.join(rebuild.validate(inv))
        self.assertIn('is not in this repository', broken(lambda i: i['files'][0].update(source='party:deploy/gone.conf')))
        self.assertIn('no provisioning path', broken(lambda i: i['secrets'][0].update(provision='')))
        self.assertIn('never an installed file',
                      broken(lambda i: i['secrets'][0]['paths'][0].update(path=i['files'][0]['path'])))
        self.assertIn('writable by group or other', broken(lambda i: i['secrets'][0]['paths'][0].update(mode='0660')))
        self.assertIn('names nothing in the inventory', broken(lambda i: i['units'][0].update(requires=['secret:nope'])))
        self.assertIn('4-digit mode', broken(lambda i: i['files'][0].update(mode='644')))
        self.assertIn('not root or an inventory user', broken(lambda i: i['directories'][0].update(owner='cody')))
        self.assertIn('evidence', broken(lambda i: i['packages'][0].update(evidence='docs/nowhere.md')))
        self.assertIn('listed twice', broken(lambda i: i['files'].append(dict(i['files'][0]))))
        self.assertIn('hardware_checks: nothing for dns',
                      broken(lambda i: i.update(hardware_checks=[h for h in i['hardware_checks'] if h['area'] != 'dns'])))
        self.assertIn('unknowns', broken(lambda i: i['unknowns'][0].update(confirm='')))


class Runbook(unittest.TestCase):
    def test_it_separates_the_four_kinds_of_step(self):
        for heading in ('## 1. Automated, reproducible steps', '## 2. Secret and certificate provisioning',
                        '## 3. Owner-only production actions', '## 4. Real-hardware verification still required',
                        '## Install order', '## File locations and ownership', '## Verification checklist',
                        '## Rollback and recovery', '## Unknown: the owner must confirm on the device'):
            self.assertIn(heading + '\n', RUNBOOK)
        self.assertIn('**PROPOSED procedure, NOT RUN**', RUNBOOK.splitlines()[2])

    def test_it_names_every_handoff(self):
        for secret in INV['secrets']:
            self.assertIn(f'`{secret["id"]}`', RUNBOOK)
            for p in secret['paths']:
                self.assertIn(f'`{p["path"]}` `{p["owner"]}:{p["group"]}` `{p["mode"]}`', RUNBOOK)
        for artifact in INV['artifacts']:
            self.assertIn(f'`{artifact["id"]}`', RUNBOOK)
            self.assertIn(f'`{artifact["path"]}`', RUNBOOK)

    def test_it_lists_every_installed_path_with_its_owner_and_mode(self):
        for d in INV['directories']:
            self.assertIn(f'| `{d["path"]}/` | `{d["owner"]}:{d["group"]}` `{d["mode"]}` |', RUNBOOK)
        for f in INV['files']:
            self.assertRegex(RUNBOOK, re.escape(f'| `{f["path"]}` | `{f["owner"]}:{f["group"]}` `{f["mode"]}` | ')
                             + r'(Games )?`' + re.escape(f['source'].partition(':')[2]) + '`')
        for link in INV['links']:
            self.assertIn(f'| `{link["path"]}` | link |', RUNBOOK)

    def test_it_lists_every_unknown_and_every_phone_check(self):
        for unknown in INV['unknowns']:
            self.assertRegex(RUNBOOK, rf'\n\| {unknown["id"]} \| ')
        section = RUNBOOK.split('## 4. Real-hardware verification still required')[1].split('\n## ')[0]
        for check in INV['hardware_checks']:
            self.assertIn(f'- **{check["area"]}**:', section)
        for area in ('Party', 'Games', 'nginx', 'AP', 'DHCP and DNS', 'Health'):
            self.assertIn(f'\n| {area} | ', RUNBOOK)


class CleanTarget(Simulated):
    def test_plan_changes_nothing_not_even_on_a_host_that_does_not_exist_yet(self):
        steps = self.plan()
        self.assertFalse(self.root.exists())
        self.assertGreater(sum(1 for s in steps if s['status'] == rebuild.CHANGE), 40)
        host = self.host(readonly=True)
        for change in (lambda: host.mkdir('/x', 'root', 'root', '0755'), lambda: host.install(b'', '/x', 'root', 'root', '0644'),
                       lambda: host.symlink('/a', '/b'), lambda: host.remove('/x'), lambda: host.run(['true'])):
            with self.assertRaises(rebuild.RebuildError):
                change()
        self.assertFalse(self.root.exists())

    def test_the_command_line_plan_and_verify_change_nothing(self):
        self.apply()
        before = tree(self.root)
        with contextlib.redirect_stderr(io.StringIO()):
            for command in ('plan', 'verify'):
                lines = []
                rc = rebuild.main([command, '--root', str(self.root)], out=lines.append)
                self.assertIn('SIMULATED', lines[0])
                self.assertEqual(rc, 0 if command == 'plan' else 1)   # verify: handoffs are still open
        self.assertEqual(tree(self.root), before)

    def test_first_apply_does_the_base_and_waits_for_every_handoff(self):
        result = self.apply()
        self.assertEqual(result['failed'], [])
        self.assertEqual(set(self.statuses('package').values()) | set(self.statuses('user').values())
                         | set(self.statuses('group').values()) | set(self.statuses('membership').values()), {rebuild.OK})
        status_of = {**self.statuses('directory'), **self.statuses('file')}
        for path in ('/etc/avrana-party/game-keys', '/etc/systemd/journald.conf.d/avrana.conf',
                     '/etc/NetworkManager/dnsmasq-shared.d/avrana-captive.conf', '/etc/avrana-party/party-core.json',
                     '/usr/local/libexec/avrana-party/install-party-certificate.sh'):
            self.assertEqual(status_of[path], rebuild.OK, path)
        host = self.host(readonly=True)
        self.assertEqual(host.meta('/etc/avrana-party/game-keys'), ('avrana-party', 'avrana-party', '0700'))
        self.assertEqual(host.path('/etc/NetworkManager/dnsmasq-shared.d/avrana-captive.conf').read_bytes(),
                         (REPO_ROOT / 'avrana-captive.conf').read_bytes())
        # Units and the site wait: for a release, a key, the certificate.
        waiting = {s['name']: s['detail'] for s in self.plan() if s['status'] == rebuild.BLOCKED}
        self.assertIn('artifact:party-release', waiting['/etc/systemd/system/avrana-party-core.service'])
        self.assertIn('secret:tls-certificate', waiting['/etc/nginx/sites-available/avrana-party'])
        self.assertIn('secret:game-key-bluff', waiting['/etc/systemd/system/avranaparty-games.service.d/avrana-party-session.conf'])
        self.assertIn('secret:game-key-expo', waiting['avrana-party-core'])
        self.assertIn('artifact:arcade-core', waiting['avranaparty-arcade'])
        handoffs = {s['name']: s['detail'] for s in self.plan() if s['status'] == rebuild.HANDOFF}
        self.assertEqual(set(handoffs), set(by('secrets')) | set(by('artifacts')))
        self.assertIn('provision-party-game-key.sh bluff', handoffs['game-key-bluff'])
        self.assertIn('deploy.sh', handoffs['party-release'])
        # Nothing that touches a running service or the network was run without --activate.
        ran = [' '.join(c) for c in host.ledger['commands']]
        self.assertFalse([c for c in ran if c.startswith(('systemctl', 'nginx', 'nmcli', 'modprobe', 'udevadm'))])
        self.assertIn('sudo systemctl restart systemd-journald', result['pending'])
        self.assertTrue(any('nmcli connection down' in line for line in result['pending']))

    def test_no_secret_is_ever_created_by_the_tool(self):
        self.apply()
        self.apply(activate=True)
        host = self.host(readonly=True)
        for path in SECRET_PATHS:
            self.assertIsNone(host.kind(path), path)
        ran = ' '.join(' '.join(c) for c in host.ledger['commands'])
        for word in ('provision-party-game-key', 'install-party-certificate', 'lego', 'nmcli', 'psk'):
            self.assertNotIn(word, ran)

    def test_the_whole_order_reaches_the_expected_state(self):
        first, second = self.build()
        self.assertEqual((first['failed'], second['failed']), ([], []))
        left = {s['name']: s['status'] for s in self.plan() if s['status'] != rebuild.OK}
        # What remains is exactly what no file can show, and what is optional.
        self.assertEqual(left, {
            'wifi-passphrase': rebuild.HANDOFF, 'operator-access': rebuild.HANDOFF, 'cloudflare-token': rebuild.HANDOFF,
            '/etc/systemd/system/avrana-party-certificate.service': rebuild.BLOCKED,
            '/etc/systemd/system/avrana-party-certificate.timer': rebuild.BLOCKED,
            'avrana-party-certificate.timer': rebuild.BLOCKED})
        host = self.host(readonly=True)
        self.assertEqual(host.link_target('/etc/nginx/sites-enabled/avrana-party'), '/etc/nginx/sites-available/avrana-party')
        self.assertEqual(host.path('/etc/systemd/system/avrana-party-core.service').read_bytes(),
                         (REPO_ROOT / 'deploy/party-core/avrana-party-core.service').read_bytes())
        self.assertEqual(host.path('/etc/systemd/system/avranaparty-games.service').read_text(encoding='utf-8'), GAMES_UNIT)
        ran = [' '.join(c) for c in host.ledger['commands']]
        self.assertLess(ran.index('systemctl daemon-reload'), ran.index('systemctl enable --now avrana-party-core'))
        self.assertLess(ran.index('nginx -t'), ran.index('systemctl reload nginx'))
        # Providers before the party that launches into them, as ops/deploy.sh starts them.
        self.assertLess(ran.index('systemctl enable --now avranaparty-games'), ran.index('systemctl enable --now avrana-party-core'))
        self.assertEqual([c for c in ran if 'nmcli' in c], [])              # NetworkManager is the owner's

    def test_a_second_apply_changes_nothing(self):
        self.build()
        before, commands = tree(self.root), len(self.host().ledger['commands'])
        again = self.apply(activate=True)
        self.assertEqual((again['changed'], again['pending'], again['failed'], again['backup']), ([], [], [], None))
        self.assertEqual(tree(self.root), before)
        self.assertEqual(len(self.host().ledger['commands']), commands)

    def test_handoffs_can_arrive_one_at_a_time(self):
        self.apply()
        self.hand_over('tls-certificate')
        result = self.apply()
        self.assertEqual(result['changed'], ['file /etc/nginx/sites-available/avrana-party',
                                             'link /etc/nginx/sites-enabled/avrana-party'])
        self.assertEqual(result['pending'][:2], ['sudo nginx -t', 'sudo systemctl reload nginx'])
        self.assertEqual(self.statuses('file')['/etc/systemd/system/avrana-party-core.service'], rebuild.BLOCKED)

    def test_secret_contents_are_never_read_or_copied(self):
        self.build()
        host = self.host()                              # drift, so the next apply backs a file up
        host.install(b'edited\n', '/etc/systemd/journald.conf.d/avrana.conf', 'root', 'root', '0644')
        self.apply()
        self.assertTrue(list((self.root / 'var/backups/avrana-party').glob('rebuild-*/files/*')))
        for rel in tree(self.root):
            if '/' + rel in SECRET_PATHS:
                continue
            self.assertNotIn(SENTINEL, (self.root / rel).read_bytes(), rel)
        checker = self.host(readonly=True)
        rebuild.plan(INV, checker)
        for path in SECRET_PATHS:
            with self.assertRaises(rebuild.RebuildError):
                checker.sha256(path)

    def test_a_secret_with_the_wrong_owner_or_mode_is_reported(self):
        self.build()
        self.host().install(SENTINEL, '/etc/avrana-party/game-keys/bluff.key', 'avrana-party', 'avrana-party', '0644')
        self.assertIn('owner or mode', {s['name']: s['detail'] for s in self.plan()}['game-key-bluff'])
        results = rebuild.verify(INV, self.host(readonly=True))
        self.assertIn(('party', 'secret game-key-bluff', rebuild.FAIL), [r[:3] for r in results])

    def test_an_edited_party_core_config_is_kept(self):
        self.build()
        self.host().install(b'{"edited": true}', '/etc/avrana-party/party-core.json', 'root', 'root', '0644')
        self.assertEqual(self.apply()['changed'], [])
        self.assertEqual(self.host().path('/etc/avrana-party/party-core.json').read_bytes(), b'{"edited": true}')
        self.assertEqual(self.statuses('file')['/etc/avrana-party/party-core.json'], rebuild.KEPT)


class Recovery(Simulated):
    def test_restore_puts_back_what_one_apply_replaced_and_removed(self):
        host = self.host()
        host.install(b'debian default\n', '/etc/nginx/sites-enabled/default', 'root', 'root', '0644')
        host.install(b'SystemMaxUse=1G\n', '/etc/systemd/journald.conf.d/avrana.conf', 'root', 'adm', '0640')
        self.hand_over()
        result = self.apply(activate=True)
        self.assertRegex(result['backup'], r'^/var/backups/avrana-party/rebuild-\d{8}T\d{6}Z$')
        self.assertIsNone(self.host().kind('/etc/nginx/sites-enabled/default'))
        restored = rebuild.restore(self.host(), result['backup'])
        host = self.host(readonly=True)
        self.assertEqual(host.path('/etc/nginx/sites-enabled/default').read_bytes(), b'debian default\n')
        self.assertEqual(host.path('/etc/systemd/journald.conf.d/avrana.conf').read_bytes(), b'SystemMaxUse=1G\n')
        self.assertEqual(host.meta('/etc/systemd/journald.conf.d/avrana.conf'), ('root', 'adm', '0640'))
        self.assertIsNone(host.kind('/etc/nginx/sites-available/avrana-party'))     # it did not exist before
        self.assertIsNone(host.kind('/etc/nginx/sites-enabled/avrana-party'))
        self.assertIn('/etc/systemd/system/avrana-party-core.service', restored)
        self.assertEqual(host.meta(result['backup']), ('root', 'root', '0700'))
        with self.assertRaises(rebuild.RebuildError):
            rebuild.restore(self.host(), '/var/backups/avrana-party/nothing')

    def test_the_unit_file_of_a_running_service_is_not_replaced(self):
        """Today's Pi: services running from units this repository does not have. That is the
        service-users migration, with its state moves and its reverse; never a silent overwrite."""
        host = self.host()
        old = b'[Service]\nUser=operator\n'
        for name in ('avrana-party-core', 'avranaparty-arcade', 'avranaparty-games'):
            host.install(old, f'/etc/systemd/system/{name}.service', 'root', 'root', '0644')
            host.run(['systemctl', 'enable', '--now', name])
        host.install(old, '/etc/systemd/system/avranaparty-games.service.d/avrana-party-session.conf', 'root', 'root', '0644')
        self.hand_over()
        self.apply(activate=True)
        details = {s['name']: (s['status'], s['detail']) for s in self.plan() if s['kind'] == 'file'}
        for path in ('/etc/systemd/system/avrana-party-core.service', '/etc/systemd/system/avranaparty-arcade.service',
                     '/etc/systemd/system/avranaparty-games.service',
                     '/etc/systemd/system/avranaparty-games.service.d/avrana-party-session.conf'):
            self.assertEqual(details[path][0], rebuild.BLOCKED, path)
            self.assertIn('service-users-migration', details[path][1])
            self.assertEqual(self.host().path(path).read_bytes(), old)

    def test_a_failed_syntax_check_stops_before_the_reload(self):
        self.apply()
        self.hand_over()

        class NginxRejects(rebuild.Host):
            def run(self, argv):
                return super().run(argv) and argv != ['nginx', '-t']
        result = rebuild.apply(INV, NginxRejects(self.root), activate=True, log=lambda *_: None)
        self.assertEqual(result['failed'], ['nginx -t'])
        ran = [' '.join(c) for c in self.host().ledger['commands']]
        self.assertNotIn('systemctl reload nginx', ran)
        self.assertFalse([c for c in ran if c.startswith('systemctl enable --now avrana')])
        self.assertIn('sudo systemctl reload nginx', result['pending'])
        self.assertTrue(result['backup'])                                    # and restore can undo it


class Verify(Simulated):
    LIVE = [('party', 'smoke party_core', 'pass', ''), ('games', 'smoke games_provider', 'pass', ''),
            ('nginx', 'smoke captive_probe', 'pass', ''), ('dns', 'smoke dns', 'pass', ''),
            ('ap', 'topology wlan0 is in AP mode', 'pass', ''), ('health', 'smoke status', 'pass', '')]

    def test_a_clean_target_fails_and_a_built_one_passes_its_state(self):
        fresh = rebuild.summarize(INV, rebuild.verify(INV, self.host(readonly=True)))
        self.assertFalse(fresh['ok'])
        self.build()
        built = rebuild.summarize(INV, rebuild.verify(INV, self.host(readonly=True)))
        self.assertTrue(built['ok'], [c for c in built['checks'] if c['status'] == 'fail'])
        self.assertEqual(built['counts']['fail'], 0)

    def test_a_simulated_host_never_claims_the_live_checks(self):
        self.build()
        summary = rebuild.summarize(INV, rebuild.verify(INV, self.host(readonly=True)))
        skipped = [c for c in summary['checks'] if c['status'] == 'skip']
        self.assertIn('live checks (smoke, topology, boundary)', [c['name'] for c in skipped])
        # The radio and the resolver cannot be judged from files: said, not passed.
        self.assertEqual(summary['areas_without_a_live_pass'], list(rebuild.REQUIRED_AREAS))
        self.assertEqual(summary['hardware_checks'], INV['hardware_checks'])
        lines = []
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(rebuild.main(['verify', '--root', str(self.root)], out=lines.append), 0)
        printed = '\n'.join(lines)
        self.assertIn('skips are not passes', printed)
        self.assertIn('no passing live check here for:', printed)
        self.assertIn('Still a human step, on real phones over the party Wi-Fi:', printed)

    def test_live_results_cover_party_games_nginx_ap_dns_and_health(self):
        self.build()
        summary = rebuild.summarize(INV, rebuild.verify(INV, self.host(readonly=True), live=lambda root: self.LIVE))
        self.assertEqual(summary['areas_without_a_live_pass'], [])
        self.assertEqual(set(rebuild.REQUIRED_AREAS), {'party', 'games', 'nginx', 'ap', 'dns', 'health'})
        failing = self.LIVE + [('dns', 'smoke dns', 'fail', 'party.avrana.net -> ')]
        self.assertFalse(rebuild.summarize(INV, rebuild.verify(INV, self.host(readonly=True), live=lambda root: failing))['ok'])

    def test_the_core_is_compared_with_the_recorded_checksum_and_only_warned_about(self):
        self.build()
        results = rebuild.verify(INV, self.host(readonly=True))
        core = [r for r in results if r[1] == 'artifact arcade-core sha256']
        self.assertEqual([r[2] for r in core], [rebuild.WARN])               # the stand-in is not that binary
        self.assertIn('owner confirms', core[0][3])

    def test_topology_lines_land_under_their_area(self):
        sample = ('PASS wlan0 is in AP mode\nINFO eth0 10.0.0.2/24\nFAIL DHCP range unexpected\n'
                  'PASS DNS captive.apple.com -> 10.42.0.1\nWARN nftables.service enabled\nPASS live nginx site == repo\n'
                  'PASS HTTP Apple probe -> Success\n')
        self.assertEqual([(r[0], r[2]) for r in rebuild.parse_topology(sample)],
                         [('ap', 'pass'), ('dns', 'fail'), ('dns', 'pass'), ('ap', 'warn'), ('nginx', 'pass'), ('nginx', 'pass')])
        self.assertEqual(rebuild.parse_topology('')[0][2], rebuild.FAIL)     # silence is not a pass
        # Every smoke check has an area, so none is filed under a default by accident.
        names = {r.name.split(':')[0] for r in smoke.run_local('http://127.0.0.1:9', http=_Dead())}
        self.assertLessEqual(names, set(rebuild.SMOKE_AREAS))
        self.assertLessEqual({'games_provider', 'arcade', 'encoder', 'unit', 'certificate', 'dns'}, set(rebuild.SMOKE_AREAS))


class _Dead:
    def get(self, *args, **kwargs):
        raise OSError('nothing listens')


class CommandLine(unittest.TestCase):
    def run_cli(self, *argv):
        lines = []
        with contextlib.redirect_stderr(io.StringIO()) as err:
            rc = rebuild.main(list(argv), out=lines.append)
        return rc, '\n'.join(lines), err.getvalue()

    def test_check_packages_and_unknowns(self):
        rc, out, _ = self.run_cli('check')
        self.assertEqual(rc, 0)
        self.assertIn('none in the repository', out)
        self.assertEqual(self.run_cli('packages')[1].split(), [p['name'] for p in INV['packages']])
        unknowns = self.run_cli('unknowns')[1]
        for unknown in INV['unknowns']:
            self.assertIn(f'{unknown["id"]}: ', unknowns)

    def test_a_broken_inventory_stops_every_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            broken = copy.deepcopy(INV)
            broken['secrets'][0]['provision'] = ''
            path = Path(tmp) / 'inventory.json'
            path.write_text(json.dumps(broken), encoding='utf-8')
            rc, out, err = self.run_cli('apply', '--root', str(Path(tmp) / 'host'), '--inventory', str(path))
            self.assertEqual(rc, 1)
            self.assertIn('no provisioning path', err)
            self.assertFalse((Path(tmp) / 'host').exists())

    @unittest.skipIf(platform.system() == 'Linux', 'a real host is refused only where there is none')
    def test_a_real_host_is_refused_off_linux(self):
        rc, _, err = self.run_cli('plan')
        self.assertEqual(rc, 2)
        self.assertIn('--root', err)

    @unittest.skipUnless(platform.system() == 'Linux' and hasattr(os, 'geteuid') and os.geteuid() != 0,
                         'needs Linux as an ordinary user')
    def test_a_real_host_is_read_but_never_changed_without_root(self):
        rc, _, err = self.run_cli('apply')
        self.assertEqual(rc, 2)
        self.assertIn('run as root', err)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'file'
            target.write_bytes(b'x')
            os.chmod(target, 0o640)
            os.symlink(target, Path(tmp) / 'link')
            host = rebuild.Host(readonly=True)
            self.assertEqual(host.meta(str(target))[2], '0640')
            self.assertEqual((host.kind(str(target)), host.kind(str(Path(tmp) / 'link')), host.kind(tmp)),
                             ('file', 'link', 'dir'))
            self.assertIsNone(host.kind(str(Path(tmp) / 'absent')))
            self.assertIsNone(host.user_groups('avrana-no-such-user'))


if __name__ == '__main__':
    unittest.main()
