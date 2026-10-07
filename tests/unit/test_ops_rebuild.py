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
  3. the runbook names every handoff and every unknown;
  4. `apply` and `restore` refuse a host that already looks like an installed appliance and
     carries no marker of this tool (class Guard): the mistake of running them on today's Pi.

No test here changes the machine it runs on, as any user: every host that can be changed is a
temporary directory, and the one test that reads the real machine is read-only with `apply` and
`restore` replaced (CommandLine).

None of this is evidence about a Raspberry Pi: the commands a real `apply` runs (apt-get, useradd,
systemctl, nginx) are recorded here, never executed, and the simulated host answers as the
inventory expects. Building a device is an owner step.
"""
import ast
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
from unittest import mock
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
    NAME = 'simulated-host'

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / 'host'
        self.clock = 0
        self.base = 0

    def host(self, readonly=False):
        return rebuild.Host(self.root, readonly=readonly)

    def step_one(self):
        """Runbook step 1, the owner's: NetworkManager installed and running the network. The
        tool never does either, so a simulated target gets them here."""
        host = self.host()
        host.run(['apt-get', 'install', 'network-manager'])
        host.run(['systemctl', 'enable', '--now', 'NetworkManager'])
        self.base = len(host.ledger['commands'])

    def ran(self):
        """What the tool itself ran, as strings (the owner's step 1 left out)."""
        return [' '.join(c) for c in self.host().ledger['commands'][self.base:]]

    def plan(self):
        return rebuild.plan(INV, self.host(readonly=True))

    def apply(self, **kw):
        if not self.host().has_package('network-manager'):
            self.step_one()
        self.clock += 1
        now = datetime(2026, 1, 1, 0, 0, self.clock, tzinfo=timezone.utc)
        kw.setdefault('target_hostname', self.NAME)
        return rebuild.apply(INV, self.host(), now=now, log=lambda *_: None, **kw)

    def statuses(self, kind=None):
        return {s['name']: s['status'] for s in self.plan() if kind in (None, s['kind'])}

    def place_secret(self, path, owner, group, mode, data=SENTINEL):
        """A stand-in secret, put there the way the owner's scripts would: not through the tool,
        which refuses to write one."""
        host = self.host()
        real = host.path(path)
        real.parent.mkdir(parents=True, exist_ok=True)
        real.write_bytes(data)
        host.ledger['meta'][path] = [owner, group, mode]
        host._save()

    def stop_units(self):
        host = self.host()
        for state in host.ledger['units'].values():
            state['active'] = False
        host._save()

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
                    self.place_secret(p['path'], p['owner'], p['group'], p['mode'])

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
                     'telemetry/pi-throttle-check.timer': telemetry, 'telemetry/pi-health-check.service': telemetry,
                     'telemetry/pi-health-check.timer': telemetry}
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

    def test_secret_safety_and_the_commands_root_runs_do_not_depend_on_the_inventory(self):
        def broken(change):
            inv = copy.deepcopy(INV)
            change(inv)
            return ' | '.join(rebuild.validate(inv))
        key = '/etc/avrana-party/game-keys/bluff.key'
        for path in (key, '/etc/avrana-party/game-keys', '/etc/avrana-party/tls/current', '/etc/avrana-party/cloudflare.env',
                     '/etc/NetworkManager/system-connections/x.nmconnection', '/var/lib/avrana-party/lego/accounts'):
            self.assertIn('never managed', broken(lambda i: i['absent'][0].update(path=path)), path)
            self.assertIn('never managed', broken(lambda i: i['links'][0].update(path=path)), path)
            self.assertIn('never managed', broken(lambda i: i['files'][0].update(path=path)), path)
        self.assertIn('never managed', broken(lambda i: i['directories'][0].update(path='/etc/avrana-party/tls/current')))
        self.assertIn('would not protect it', broken(lambda i: i['secrets'][0]['paths'][0].update(path='/etc/elsewhere.key')))
        for argv in (['rm', '-rf', '/'], ['systemctl', 'stop', 'nginx'], ['nginx', '-t', '-c', '/tmp/x'], 'nginx -t'):
            self.assertIn('is not one of the commands this tool runs', broken(lambda i: i['files'][0].update(activate=[argv])))
        self.assertIn('unknown owner step', broken(lambda i: i['files'][0].update(owner_activate=['sudo rm -rf /'])))
        shipped = [argv for section in ('files', 'links', 'absent') for e in INV[section] for argv in e.get('activate', [])]
        self.assertEqual({tuple(a) for a in shipped}, {tuple(a) for a in rebuild.ACTIVATIONS})    # the seven, no spare
        self.assertEqual(len(rebuild.ACTIVATIONS), 7)
        for secret_path in SECRET_PATHS:
            self.assertTrue(rebuild.is_secret(secret_path), secret_path)
        # ...and the host refuses by itself, with no inventory loaded at all.
        with tempfile.TemporaryDirectory() as tmp:
            host = rebuild.Host(tmp)
            real = host.path(key)
            real.parent.mkdir(parents=True)
            real.write_bytes(SENTINEL)
            for touch in (lambda: host.install(b'x', key, 'root', 'root', '0600'), lambda: host.remove(key),
                          lambda: host.sha256(key), lambda: host.symlink('/x', key),
                          lambda: rebuild._record(host, [], '/var/backups/avrana-party/rebuild-x', key),
                          lambda: host.mkdir('/etc/avrana-party/game-keys/sub', 'root', 'root', '0700')):
                with self.assertRaises(rebuild.RebuildError):
                    touch()
            self.assertEqual(real.read_bytes(), SENTINEL)
            self.assertEqual([p.name for p in Path(tmp).rglob('*') if p.is_file()], ['bluff.key'])

    def test_the_tool_never_installs_or_starts_networkmanager(self):
        package = by('packages', 'name')['network-manager']
        unit = by('units', 'name')['NetworkManager']
        for text_ in (package['manual'], unit['manual']):
            self.assertIn('console', text_)
            self.assertIn('U1', text_)
        self.assertIn('does NOT install the network-manager package', rebuild.__doc__)
        self.assertNotIn('never touches NetworkManager', rebuild.__doc__)
        with tempfile.TemporaryDirectory() as tmp:
            host = rebuild.Host(tmp)
            result = rebuild.apply(INV, host, target_hostname=host.hostname(), activate=True, log=lambda *_: None)
            ran = [' '.join(c) for c in host.ledger['commands']]
            self.assertFalse([c for c in ran if 'network-manager' in c or 'NetworkManager' in c or 'nmcli' in c])
            self.assertEqual(result['failed'], [])
            steps = {(s['kind'], s['name']): s for s in rebuild.plan(INV, rebuild.Host(tmp, readonly=True))}
            self.assertEqual(steps[('package', 'network-manager')]['status'], rebuild.HANDOFF)
            self.assertEqual(steps[('unit', 'NetworkManager')]['status'], rebuild.HANDOFF)
            captive = steps[('file', '/etc/NetworkManager/dnsmasq-shared.d/avrana-captive.conf')]
            self.assertEqual((captive['status'], captive['detail']), (rebuild.BLOCKED, 'needs package:network-manager'))


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

    def test_it_says_what_the_tool_does_to_a_running_machine(self):
        for sentence in ('does **not** install the `network-manager` package', 'starts nginx at once, on port 80',
                         'install `git`, `sudo` and Python 3.11 or newer',
                         '**No repository records the lego command', 'is not known (U5)',
                         'PYTHONDONTWRITEBYTECODE=1 python3 -m avrana.ops.rebuild apply --target-hostname',
                         'it is refused, like any other run, whenever one of the Avrana units',
                         '## Real-host code that has never executed anywhere', 'may share a hostname (U6)',
                         'restarts `systemd-journald` and reloads nginx even when nothing changed',
                         '--target-hostname <the name you read on the card>',
                         'prints the `sudo systemctl stop'):
            self.assertIn(sentence, RUNBOOK)
        self.assertNotIn('sudo python3 -m avrana.ops.rebuild apply\n```', RUNBOOK)     # never without the name, never bytecode
        self.assertNotIn('--target-hostname "$(hostname)"', RUNBOOK)                   # a check that cannot fail is no check
        never_run = RUNBOOK.split('## Real-host code that has never executed anywhere')[1].split('\n## ')[0]
        for name in ('Host.exists', 'link_target', 'has_package', 'has_group', 'user_groups', 'unit_sign', 'systemctl_show',
                     '_own', 'symlink', 'remove', 'run', 'hostname', 'identity', 'live_checks', '/dev/uinput',
                     'seal', 'restore', 'entries', '_parents'):
            self.assertIn(name, never_run)
            if name not in ('/dev/uinput', 'seal', 'restore'):
                self.assertTrue(hasattr(rebuild.Host, name.replace('Host.', '')) or hasattr(rebuild, name), name)
        for line in RUNBOOK.splitlines():
            if line.startswith('sudo ') and 'avrana.ops.rebuild' in line and '#' not in line:
                self.assertIn('PYTHONDONTWRITEBYTECODE=1', line)

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
        self.assertFalse([c for c in self.ran() if c.startswith(('systemctl', 'nginx', 'nmcli', 'modprobe', 'udevadm'))])
        self.assertIn('sudo systemctl restart systemd-journald', result['pending'])
        bounce = [line for line in result['pending'] if 'nmcli connection down' in line]
        self.assertEqual(len(bounce), 1)
        self.assertTrue(bounce[0].startswith('only if the access point profile is already up'))

    def test_no_secret_is_ever_created_by_the_tool(self):
        self.apply()
        self.apply(activate=True)
        host = self.host(readonly=True)
        for path in SECRET_PATHS:
            self.assertIsNone(host.kind(path), path)
        ran = ' '.join(self.ran())
        for word in ('provision-party-game-key', 'install-party-certificate', 'lego', 'nmcli', 'psk', 'NetworkManager'):
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
        ran = self.ran()
        self.assertLess(ran.index('systemctl daemon-reload'), ran.index('systemctl enable --now avrana-party-core'))
        self.assertLess(ran.index('nginx -t'), ran.index('systemctl reload nginx'))
        # Providers before the party that launches into them, as ops/deploy.sh starts them.
        self.assertLess(ran.index('systemctl enable --now avranaparty-games'), ran.index('systemctl enable --now avrana-party-core'))
        self.assertEqual([c for c in ran if 'nmcli' in c], [])              # NetworkManager is the owner's

    def test_a_second_apply_changes_nothing(self):
        self.build()
        files = {k: v for k, v in tree(self.root).items() if k != rebuild.Host.LEDGER}
        ledger = dict(self.host().ledger, commands=None)
        ran = len(self.ran())
        again = self.apply()
        self.assertEqual((again['changed'], again['pending'], again['failed'], again['backup']), ([], [], [], None))
        self.assertEqual(len(self.ran()), ran)                               # not one command
        again = self.apply(activate=True)
        self.assertEqual((again['changed'], again['pending'], again['failed'], again['backup']), ([], [], [], None))
        self.assertEqual({k: v for k, v in tree(self.root).items() if k != rebuild.Host.LEDGER}, files)
        self.assertEqual(dict(self.host().ledger, commands=None), ledger)   # nothing but the command log moved
        # --activate reloads everything that is in place, every time: exactly the reload commands.
        self.assertEqual(sorted(self.ran()[ran:]), sorted(' '.join(a) for a in rebuild.ACTIVATIONS))

    def test_activate_runs_the_reloads_of_what_earlier_runs_installed(self):
        """Step 3 installs the uinput rule without --activate; step 8's --activate must still
        load it, or the arcade starts with no controllers."""
        self.apply()
        self.hand_over()
        self.apply()                                     # everything installed, nothing activated
        self.assertFalse([c for c in self.ran() if c.startswith(('systemctl', 'nginx', 'modprobe', 'udevadm'))])
        result = self.apply(activate=True)
        ran = self.ran()
        for argv in rebuild.ACTIVATIONS:
            self.assertEqual(ran.count(' '.join(argv)), 1, argv)
        self.assertLess(ran.index('systemctl daemon-reload'), ran.index('modprobe uinput'))
        self.assertLess(ran.index('udevadm control --reload-rules'), ran.index('udevadm trigger --subsystem-match=misc'))
        self.assertLess(ran.index('udevadm trigger --subsystem-match=misc'), ran.index('systemctl enable --now avranaparty-arcade'))
        self.assertLess(ran.index('nginx -t'), ran.index('systemctl reload nginx'))
        self.assertEqual(sorted(result['changed']), sorted(f'unit {u["name"]}' for u in INV['units']
                                                           if not u.get('optional') and not u.get('manual')))
        self.assertEqual((result['pending'], result['failed']), ([], []))

    def test_two_applies_in_the_same_second_keep_separate_backups(self):
        self.apply()
        now = datetime(2026, 3, 1, tzinfo=timezone.utc)
        backups = []
        for content in (b'one\n', b'two\n'):
            self.host().install(content, '/etc/systemd/journald.conf.d/avrana.conf', 'root', 'root', '0644')
            backups.append(rebuild.apply(INV, self.host(), now=now, log=lambda *_: None)['backup'])
        self.assertEqual(backups, ['/var/backups/avrana-party/rebuild-20260301T000000Z',
                                   '/var/backups/avrana-party/rebuild-20260301T000000Z-2'])
        self.assertEqual([self.host().path(b + '/files/000').read_bytes() for b in backups], [b'one\n', b'two\n'])
        rebuild.restore(INV, self.host(), backups[1])
        self.assertEqual(self.host().path('/etc/systemd/journald.conf.d/avrana.conf').read_bytes(), b'two\n')

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
        self.place_secret('/etc/avrana-party/game-keys/bluff.key', 'avrana-party', 'avrana-party', '0644')
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
        host.install(b'SystemMaxUse=1G\n', '/etc/systemd/journald.conf.d/avrana.conf', 'root', 'avrana-front', '0640')
        first = self.apply()
        self.assertRegex(first['backup'], r'^/var/backups/avrana-party/rebuild-\d{8}T\d{6}Z$')
        self.assertIsNone(self.host().kind('/etc/nginx/sites-enabled/default'))
        self.hand_over()
        second = self.apply(activate=True)
        self.assertNotEqual(first['backup'], second['backup'])
        before = tree(self.root)
        with self.assertRaises(rebuild.RebuildError) as refused:             # the units it installed are running
            rebuild.restore(INV, self.host(), second['backup'])
        self.assertIn('sudo systemctl stop avrana-party-core avranaparty-arcade avranaparty-games', str(refused.exception))
        self.assertEqual(tree(self.root), before)
        self.stop_units()
        restored = rebuild.restore(INV, self.host(), second['backup'])       # newest first, as a person would
        host = self.host(readonly=True)
        self.assertIn('/etc/systemd/system/avrana-party-core.service', restored)
        self.assertIsNone(host.kind('/etc/nginx/sites-available/avrana-party'))     # it did not exist before
        self.assertIsNone(host.kind('/etc/nginx/sites-enabled/avrana-party'))
        rebuild.restore(INV, self.host(), first['backup'])
        host = self.host(readonly=True)
        self.assertEqual(host.path('/etc/nginx/sites-enabled/default').read_bytes(), b'debian default\n')
        self.assertEqual(host.path('/etc/systemd/journald.conf.d/avrana.conf').read_bytes(), b'SystemMaxUse=1G\n')
        self.assertEqual(host.meta('/etc/systemd/journald.conf.d/avrana.conf'), ('root', 'avrana-front', '0640'))
        self.assertEqual(host.meta(first['backup']), ('root', 'root', '0700'))
        with self.assertRaises(rebuild.RebuildError):
            rebuild.restore(INV, self.host(), '/var/backups/avrana-party/nothing')

    def test_the_unit_file_of_a_running_service_is_not_replaced(self):
        """The second line of defence, behind the guard (class Guard): even on a host this tool
        is allowed to change, a running service's unit file is never silently overwritten."""
        self.apply()                                     # a clean target: the marker is written
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
        ran = self.ran()
        self.assertNotIn('systemctl reload nginx', ran)
        self.assertFalse([c for c in ran if c.startswith('systemctl enable --now avrana')])
        self.assertIn('sudo systemctl reload nginx', result['pending'])
        self.assertTrue(result['backup'])                                    # and restore can undo it

    def test_a_failed_step_stops_the_run_and_is_not_reported_as_changed(self):
        self.step_one()

        class SecondUserFails(rebuild.Host):
            def run(self, argv):
                return super().run(argv) and not (argv[0] == 'useradd' and argv[-1] == 'avrana-arcade')
        result = rebuild.apply(INV, SecondUserFails(self.root), target_hostname=self.NAME, activate=True, log=lambda *_: None)
        self.assertEqual(len(result['failed']), 1)
        self.assertIn('useradd', result['failed'][0])
        users = [c for c in result['changed'] if c.startswith('user ')]
        self.assertEqual(users, ['user avrana-party'])                       # not the one that failed, nor the next
        self.assertFalse([c for c in result['changed'] if c.startswith(('directory', 'file', 'link', 'unit'))])
        self.assertIsNone(self.host().kind('/etc/avrana-party'))             # nothing after the failure
        self.assertFalse([c for c in self.ran() if c.startswith(('systemctl', 'modprobe', 'udevadm', 'nginx'))])
        lines = []
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(rebuild.main(['plan', '--root', str(self.root)], out=lines.append), 0)

    def test_a_path_in_the_way_or_a_missing_user_is_a_clean_failure(self):
        self.step_one()
        (self.root / 'etc/systemd/journald.conf.d/avrana.conf').mkdir(parents=True)    # a directory where a file goes
        lines = []
        with contextlib.redirect_stderr(io.StringIO()):
            rc = rebuild.main(['apply', '--target-hostname', self.NAME, '--root', str(self.root)], out=lines.append)
        self.assertEqual(rc, 1)
        printed = '\n'.join(lines)
        self.assertIn('FAILED   file /etc/systemd/journald.conf.d/avrana.conf: RebuildError', printed)
        self.assertIn('stopped at the first failure', printed)
        self.assertNotIn('changed  file /etc/systemd/journald.conf.d/avrana.conf', printed)
        self.assertEqual([p for p in self.root.rglob('.*.avrana-new')], [])
        self.assertIsNone(self.host().kind('/etc/modules-load.d/avrana-uinput.conf'))   # the next file was not tried

        class NoSuchUser(rebuild.Host):                  # what shutil.chown raises on a real host
            def _own(self, path, owner, group, mode):
                if owner == 'avrana-party':
                    raise LookupError(f'no such user: {owner!r}')
                return super()._own(path, owner, group, mode)
        self.root = self.root.parent / 'second-host'
        self.step_one()
        result = rebuild.apply(INV, NoSuchUser(self.root), target_hostname=self.NAME, log=lambda *_: None)
        self.assertEqual(len(result['failed']), 1)
        self.assertIn('directory /etc/avrana-party/game-keys: LookupError', result['failed'][0])
        self.assertNotIn('directory /etc/avrana-party/game-keys', result['changed'])
        # ...and anything the steps do not catch still ends as a message and exit 1, not a traceback.
        for error in (LookupError('no such group'), PermissionError(13, 'denied')):
            with mock.patch.object(rebuild, 'apply', side_effect=error), contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(rebuild.main(['apply', '--root', str(self.root)], out=lambda *_: None), 1)
            self.assertIn('apply failed:', err.getvalue())

    def test_a_tampered_journal_or_a_foreign_directory_is_refused_whole(self):
        self.build()
        self.stop_units()
        self.host().install(b'edited\n', '/etc/systemd/journald.conf.d/avrana.conf', 'root', 'root', '0644')
        backup = self.apply()['backup']
        journal = self.root / backup.lstrip('/') / 'journal.json'
        good = json.loads(journal.read_text(encoding='utf-8'))
        self.assertEqual([e['path'] for e in good], ['/etc/systemd/journald.conf.d/avrana.conf'])
        (self.root / 'etc/passwd').write_bytes(b'root:x:0:0\n')
        before = None
        for change in ({'path': '/etc/passwd'}, {'path': '/etc/systemd/journald.conf.d/../../passwd'},
                       {'path': 'etc/systemd/journald.conf.d/avrana.conf'}, {'path': '/etc/avrana-party/game-keys/bluff.key'},
                       {'path': '/etc/avrana-party/party-core.json/../game-keys/bluff.key'},
                       {'copy': '../../../../etc/avrana-party/game-keys/bluff.key'}, {'copy': 'files/999'},
                       {'kind': 'dir'}, {'meta': ['root', 'root', '4755x']}, {'meta': ['cody', 'root', '0644']},
                       {'meta': ['root', 'somebody', '0644']}):
            journal.write_text(json.dumps([dict(good[0], **change)]), encoding='utf-8')
            before = tree(self.root)
            with self.subTest(change=change), self.assertRaises(rebuild.RebuildError) as refused:
                rebuild.restore(INV, self.host(), backup)
            self.assertIn('nothing was changed', str(refused.exception))
            self.assertEqual(tree(self.root), before)
        journal.write_text(json.dumps(good), encoding='utf-8')
        for elsewhere in ('/tmp/rebuild-20260101T000000Z', backup + '/../' + backup.rsplit('/', 1)[1] + '/files',
                          '/var/backups/avrana-party', '/etc'):
            with self.assertRaises(rebuild.RebuildError):
                rebuild.restore(INV, self.host(), elsewhere)
        self.assertEqual(rebuild.restore(INV, self.host(), backup), ['/etc/systemd/journald.conf.d/avrana.conf'])
        self.assertEqual((self.root / 'etc/passwd').read_bytes(), b'root:x:0:0\n')


class Guard(Simulated):
    """`apply`, `restore` and `seal` change only a host this tool is building. Today's Pi, on
    which somebody types `sudo python3 -m avrana.ops.rebuild apply` by mistake, is refused before
    anything, and so is a rebuilt card once its build was sealed."""
    MARKER = INV['guard']['marker']
    OVERRIDE = '--owner-confirms-not-the-live-appliance'

    def live_appliance(self):
        """A simulated host with what SYSTEM records on the Pi: the three services running from
        units of the operator's, the key store owned by the operator, the site, the manifest."""
        self.step_one()
        host = self.host()
        for name in ('avrana-party-core', 'avranaparty-arcade', 'avranaparty-games'):
            host.install(b'[Service]\nUser=operator\n', f'/etc/systemd/system/{name}.service', 'root', 'root', '0644')
            host.run(['systemctl', 'enable', '--now', name])
        host.install(b'old site\n', '/etc/nginx/sites-available/avrana-party', 'root', 'root', '0644')
        host.install(b'{}', '/etc/avrana-party/party-core.json', 'root', 'root', '0644')
        host.install(b'{}', '/var/lib/avrana-party/deployment.json', 'root', 'root', '0644')
        host.install(b'debian default\n', '/etc/nginx/sites-enabled/default', 'root', 'root', '0644')
        host.mkdir('/etc/avrana-party/game-keys', 'cody', 'cody', '0700')
        self.place_secret('/etc/avrana-party/game-keys/bluff.key', 'cody', 'cody', '0600')
        self.base = len(self.host().ledger['commands'])

    def refused(self, *argv):
        """Run the command line; assert exit 2 and that the host is exactly as it was."""
        before = tree(self.root) if self.root.exists() else None
        with contextlib.redirect_stderr(io.StringIO()) as err:
            try:
                rc = rebuild.main([*argv, '--root', str(self.root)], out=lambda *_: None)
            except SystemExit as e:                      # argparse: an option it does not know
                rc = e.code
        self.assertEqual(rc, 2, argv)
        self.assertEqual(tree(self.root) if self.root.exists() else None, before, argv)
        return err.getvalue()

    def test_a_live_appliance_is_refused_with_nothing_changed_and_no_command_run(self):
        self.live_appliance()
        before = tree(self.root)
        for kw in ({}, {'activate': True}):
            with self.assertRaises(rebuild.RebuildError) as refused:
                self.apply(**kw)
            self.assertIn('service-users-migration.md', str(refused.exception))
            self.assertIn('nothing was changed', str(refused.exception))
        self.assertEqual(tree(self.root), before)                        # no file, no backup, no marker
        self.assertEqual(self.ran(), [])                                 # no apt-get, useradd, systemctl
        self.assertIsNone(self.host().kind(self.MARKER))
        self.assertIn('refused', self.refused('apply', '--activate', '--target-hostname', self.NAME))
        self.assertIn('no valid rebuild marker', self.refused('restore', '/var/backups/avrana-party/rebuild-20260101T000000Z'))
        self.assertIn('no valid rebuild marker', self.refused('seal'))

    def test_the_override_cannot_be_abbreviated_or_guessed(self):
        """argparse accepts any unambiguous prefix unless told not to: `--o` was the override."""
        self.live_appliance()
        for flag in ('--o', '--owner', '--owner-confirms', '--owner-confirms-not-the-live', '--a', '--act', '--t',
                     '--force', '--yes', '-f', '--override'):
            self.assertIn('unrecognized arguments', self.refused('apply', flag, '--target-hostname', self.NAME), flag)
        self.assertEqual(self.ran(), [])
        with tempfile.TemporaryDirectory() as tmp:       # the same on a clean target: no flag is guessed
            self.root = Path(tmp) / 'clean'
            for flag in ('--o', '--a', '--target', '--r'):
                self.refused('apply', flag, self.NAME)
            self.assertFalse(self.root.exists())

    def test_the_override_is_refused_while_an_appliance_service_is_enabled_or_running(self):
        """Today's Pi with the override: before this rule it re-owned the key store away from
        the user the services run as, replaced the site and installed thirty packages."""
        self.live_appliance()
        text_ = self.refused('apply', self.OVERRIDE, '--activate', '--target-hostname', self.NAME)
        self.assertIn('override included', text_)
        self.assertIn('avrana-party-core is active', text_)
        self.assertIn('half-built target', text_)
        self.assertEqual(self.ran(), [])
        self.assertEqual(self.host().meta('/etc/avrana-party/game-keys'), ('cody', 'cody', '0700'))
        self.assertEqual(self.host().path('/etc/nginx/sites-available/avrana-party').read_bytes(), b'old site\n')
        self.assertEqual(self.host().kind('/etc/nginx/sites-enabled/default'), 'file')
        self.refused('restore', '/var/backups/avrana-party/rebuild-20260101T000000Z', self.OVERRIDE,
                     '--target-hostname', self.NAME)
        host = self.host()                               # stopped but still enabled: still an appliance
        for state in host.ledger['units'].values():
            state['active'] = False
        host._save()
        self.assertIn('avrana-party-core is enabled', self.refused('apply', self.OVERRIDE, '--target-hostname', self.NAME))

    def test_the_override_lets_a_half_built_target_go_on_and_is_recorded(self):
        self.step_one()
        host = self.host()                               # ops/deploy.sh ran before the first apply
        host.install(b'stand-in', '/opt/avrana-party/current/avrana/ops/smoke.py', 'root', 'root', '0644')
        host.install(b'{}', '/var/lib/avrana-party/deployment.json', 'root', 'root', '0644')
        self.assertIn('refused', self.refused('apply', '--target-hostname', self.NAME))
        for argv in (['apply'], ['restore', '/var/backups/avrana-party/rebuild-20260101T000000Z']):
            self.assertIn('must name the machine too', self.refused(*argv, self.OVERRIDE))   # the override too
        result = self.apply(owner_override=True)
        self.assertEqual(result['failed'], [])
        marker = json.loads(self.host().path(self.MARKER).read_text(encoding='utf-8'))
        self.assertTrue(marker['owner_override'])
        self.assertIn('/opt/avrana-party exists', marker['signs_at_creation'])
        self.assertEqual(self.apply()['changed'], [])                                # open now: no flag needed
        self.assertIn(f'`{self.OVERRIDE}`', RUNBOOK)

    def test_a_path_with_dot_dot_never_reaches_a_secret(self):
        """The host-level check normalised nothing: `/etc/avrana-party/x/../game-keys/x` passed it."""
        self.step_one()
        host = self.host()
        key = '/etc/avrana-party/game-keys/bluff.key'
        self.place_secret(key, 'cody', 'cody', '0600')
        before = tree(self.root)
        for path in ('/etc/avrana-party/x/../game-keys/x', '/etc/avrana-party/x/../game-keys/bluff.key',
                     '/etc/avrana-party/game-keys/../game-keys/bluff.key', '/var/lib/avrana-party/../avrana-party/lego/a',
                     '/etc/../etc/avrana-party/cloudflare.env', 'etc/avrana-party/game-keys/bluff.key', '../x', ''):
            for touch in (lambda: host.install(b'x', path, 'root', 'root', '0600'), lambda: host.remove(path),
                          lambda: host.symlink('/x', path), lambda: host.sha256(path),
                          lambda: host.mkdir(path, 'root', 'root', '0700'),
                          lambda: rebuild._record(host, [], '/var/backups/avrana-party/rebuild-x', path)):
                with self.subTest(path=path), self.assertRaises(rebuild.RebuildError):
                    touch()
        self.assertEqual(tree(self.root), before)
        self.assertEqual(host.path(key).read_bytes(), SENTINEL)

    def test_a_marker_written_for_another_machine_opens_nothing(self):
        self.live_appliance()
        foreign = {'schema': 'avrana.rebuild-marker/v0', 'created': '20260101T000000Z', 'hostname': 'spare-card'}
        self.host().install(json.dumps(foreign).encode(), self.MARKER, 'root', 'root', '0644')
        self.assertIsNone(rebuild.read_marker(INV, self.host(readonly=True)))
        self.assertEqual(rebuild.guard_state(INV, self.host(readonly=True)), 'appliance')
        for argv in (['apply'], ['apply', '--activate'], ['apply', '--target-hostname', self.NAME],
                     ['restore', '/var/backups/avrana-party/rebuild-20260101T000000Z'], ['seal']):
            self.assertIn('refused', self.refused(*argv), argv)
        self.assertEqual(self.ran(), [])
        lines = []
        with contextlib.redirect_stderr(io.StringIO()):
            rebuild.main(['plan', '--root', str(self.root)], out=lines.append)
        self.assertIn("written for another machine ('spare-card'; this one is 'simulated-host') and is ignored", lines[1])
        # The same file on the machine it names is a marker.
        host = self.host()
        host.ledger['hostname'] = 'spare-card'
        host._save()
        self.assertEqual(rebuild.guard_state(INV, self.host(readonly=True)), 'open')

    def test_a_systemd_that_does_not_answer_is_a_sign_not_an_all_clear(self):
        """The override's "no service running" was read from `systemctl` output; a timeout came
        back as None and counted as not running. The parsing and the question are the real-host
        code; only the process is replaced."""
        def shown(active, file_state, load='loaded'):
            return f'LoadState={load}\nActiveState={active}\nUnitFileState={file_state}\n'
        for text_, sign in ((None, rebuild.UNANSWERED), ('', rebuild.UNANSWERED), ('garbage', rebuild.UNANSWERED),
                            ('ActiveState=active\n', rebuild.UNANSWERED),
                            (shown('active', 'enabled'), 'active'), (shown('activating', 'disabled'), 'activating'),
                            (shown('reloading', 'disabled'), 'reloading'), (shown('deactivating', ''), 'deactivating'),
                            (shown('failed', 'enabled'), 'failed but enabled'), (shown('inactive', 'enabled'), 'enabled'),
                            (shown('inactive', 'linked'), 'linked'), (shown('inactive', 'enabled-runtime'), 'enabled-runtime'),
                            (shown('inactive', 'disabled'), None), (shown('failed', 'disabled'), None),
                            (shown('inactive', '', load='not-found'), None)):
            self.assertEqual(rebuild.unit_sign(text_), sign, text_)

        def timeout(argv, **kw):
            raise rebuild.subprocess.TimeoutExpired(argv, 20)

        def missing(argv, **kw):
            raise FileNotFoundError('systemctl')
        calls = []

        def answers(argv, **kw):
            calls.append(argv)
            return mock.Mock(returncode=0, stdout=shown('inactive', 'disabled').encode())
        self.assertIsNone(rebuild.systemctl_show('avrana-party-core', runner=timeout))
        self.assertIsNone(rebuild.systemctl_show('avrana-party-core', runner=missing))
        self.assertIsNone(rebuild.systemctl_show('x', runner=lambda argv, **kw: mock.Mock(returncode=1, stdout=b'')))
        self.assertIsNone(rebuild.unit_sign(rebuild.systemctl_show('avrana-party-core', runner=answers)))
        self.assertEqual(calls, [['systemctl', 'show', '--property=LoadState,ActiveState,UnitFileState', 'avrana-party-core']])
        # A half-built target (paths, no marker) on which systemd does not answer: the override is refused.
        self.step_one()
        self.host().install(b'{}', '/var/lib/avrana-party/deployment.json', 'root', 'root', '0644')
        before = tree(self.root)
        for query in (lambda name: None, lambda name: '', lambda name: shown('activating', 'disabled'),
                      lambda name: shown('failed', 'enabled'), lambda name: shown('inactive', 'linked')):
            deaf = rebuild.Host(self.root, unit_query=query)
            self.assertEqual(len(rebuild.appliance_units(INV, deaf)), len(INV['guard']['appliance_units']))
            for command in ('apply', 'restore'):
                with self.assertRaises(rebuild.RebuildError) as refused:
                    rebuild.authorize(INV, deaf, command, owner_override=True, target_hostname=self.NAME)
                self.assertIn('override included', str(refused.exception))
            with self.assertRaises(rebuild.RebuildError):
                rebuild.apply(INV, deaf, owner_override=True, target_hostname=self.NAME, log=lambda *_: None)
        self.assertEqual((tree(self.root), self.ran()), (before, []))
        with self.assertRaises(rebuild.RebuildError) as refused:
            rebuild.authorize(INV, rebuild.Host(self.root, unit_query=lambda name: None), 'apply',
                              owner_override=True, target_hostname=self.NAME)
        self.assertIn('avrana-party-core is not answering', str(refused.exception))
        # ...and with systemd answering "nothing runs" the same override goes on.
        quiet = rebuild.Host(self.root, unit_query=lambda name: shown('inactive', '', load='not-found'))
        rebuild.authorize(INV, quiet, 'restore', owner_override=True, target_hostname=self.NAME)
        # A unit whose state cannot be read is treated as running when its file would be replaced.
        self.assertEqual(rebuild._running_unit(rebuild.Host(self.root, unit_query=lambda name: None),
                                               '/etc/systemd/system/avrana-party-core.service'), 'avrana-party-core')

    def test_a_populated_key_store_of_another_owner_is_never_re_owned(self):
        """An old-layout host with every unit stopped and disabled, the override given: the key
        store went from the operator to avrana-party with a key inside."""
        self.step_one()
        host = self.host()
        host.mkdir('/etc/avrana-party/game-keys', 'cody', 'cody', '0700')
        self.place_secret('/etc/avrana-party/game-keys/bluff.key', 'cody', 'cody', '0600')
        result = self.apply(owner_override=True)
        self.assertEqual(result['failed'], [])
        self.assertNotIn('directory /etc/avrana-party/game-keys', result['changed'])
        self.assertEqual(self.host().meta('/etc/avrana-party/game-keys'), ('cody', 'cody', '0700'))
        step = next(s for s in self.plan() if s['name'] == '/etc/avrana-party/game-keys')
        self.assertEqual(step['status'], rebuild.HANDOFF)
        self.assertIn('owner decides: /etc/avrana-party/game-keys belongs to cody and holds 1 entries', step['detail'])
        self.assertIn(('party', 'directory /etc/avrana-party/game-keys', rebuild.FAIL),
                      [r[:3] for r in rebuild.verify(INV, self.host(readonly=True))])
        with self.assertRaises(rebuild.RebuildError):                # and the host refuses by itself
            self.host().mkdir('/etc/avrana-party/game-keys', 'avrana-party', 'avrana-party', '0700')
        self.assertEqual(self.host().meta('/etc/avrana-party/game-keys'), ('cody', 'cody', '0700'))
        # An empty one, or one that already belongs to the service user, is set as before.
        (self.root / 'etc/avrana-party/game-keys/bluff.key').unlink()
        self.assertIn('directory /etc/avrana-party/game-keys', self.apply()['changed'])
        self.assertEqual(self.host().meta('/etc/avrana-party/game-keys'), ('avrana-party', 'avrana-party', '0700'))
        self.place_secret('/etc/avrana-party/game-keys/bluff.key', 'avrana-party', 'avrana-party', '0600')
        loose = self.host()
        loose.ledger['meta']['/etc/avrana-party/game-keys'] = ['avrana-party', 'avrana-party', '0750']
        loose._save()
        self.assertIn('directory /etc/avrana-party/game-keys', self.apply()['changed'])      # same owner: mode repaired

    def test_each_sign_alone_is_enough(self):
        for path in INV['guard']['appliance_paths']:
            with self.subTest(path=path), tempfile.TemporaryDirectory() as tmp:
                host = rebuild.Host(tmp)
                leaf = path if Path(path).suffix else path + '/x'      # a unit or config file, else a directory
                host.install(b'x', leaf, 'root', 'root', '0644')
                self.assertTrue(rebuild.appliance_signs(INV, host), path)
                with self.assertRaises(rebuild.RebuildError):
                    rebuild.apply(INV, host, target_hostname=self.NAME, log=lambda *_: None)
                self.assertEqual(host.ledger['commands'], [])
        for unit in INV['guard']['appliance_units']:
            for state in ({'enabled': True, 'active': False}, {'enabled': False, 'active': True}):
                with self.subTest(unit=unit, state=state), tempfile.TemporaryDirectory() as tmp:
                    host = rebuild.Host(tmp)
                    host.ledger['units'][unit] = state
                    for override in (False, True):
                        with self.assertRaises(rebuild.RebuildError):
                            rebuild.apply(INV, host, target_hostname=self.NAME, owner_override=override, log=lambda *_: None)
                    self.assertEqual(host.ledger['commands'], [])
        # A fresh Debian image already runs these; they are not signs of an Avrana appliance.
        with tempfile.TemporaryDirectory() as tmp:
            host = rebuild.Host(tmp)
            for unit in ('nginx', 'NetworkManager', 'avahi-daemon'):
                host.ledger['units'][unit] = {'enabled': True, 'active': True}
            host.install(b'stand-in', '/home/cody/avrana-party/.git', 'cody', 'cody', '0644')   # runbook step 2
            self.assertEqual(rebuild.appliance_signs(INV, host), [])

    def test_the_first_apply_must_name_the_machine_and_writes_the_marker_first(self):
        self.step_one()
        self.host().install(b'PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\nID=debian\n', '/etc/os-release', 'root', 'root', '0644')
        before = tree(self.root)
        self.assertIn(f'--target-hostname {self.NAME}', self.refused('apply'))
        self.assertIn("says 'party' but this machine is 'simulated-host'", self.refused('apply', '--target-hostname', 'party'))
        self.assertEqual((tree(self.root), self.ran()), (before, []))
        order, said = [], []

        class Watching(rebuild.Host):
            def install(self, data, path, *meta):
                order.append(path)
                return super().install(data, path, *meta)

            def run(self, argv):
                order.append(' '.join(argv))
                return super().run(argv)
        rebuild.apply(INV, Watching(self.root), target_hostname=self.NAME, log=said.append)
        self.assertEqual(order[0], self.MARKER)
        self.assertEqual(order[1], 'apt-get update')
        self.assertEqual(said, ['about to build an appliance on: hostname simulated-host, Debian GNU/Linux 13 (trixie), simulated'])
        host = self.host(readonly=True)
        marker = json.loads(host.path(self.MARKER).read_text(encoding='utf-8'))
        self.assertEqual({k: marker[k] for k in ('schema', 'owner_override', 'signs_at_creation', 'hostname', 'os', 'arch')},
                         {'schema': 'avrana.rebuild-marker/v0', 'owner_override': False, 'signs_at_creation': [],
                          'hostname': self.NAME, 'os': 'Debian GNU/Linux 13 (trixie)', 'arch': 'simulated'})
        self.assertRegex(marker['created'], r'^\d{8}T\d{6}Z$')
        if (REPO_ROOT / '.git').exists():              # a checkout or worktree: the commit is known, exactly
            self.assertRegex(marker['party_sha'], r'^[0-9a-f]{40}$')
        else:                                           # an exported tree outside a release directory
            self.assertIsNone(marker['party_sha'])
        self.assertEqual(host.meta(self.MARKER), ('root', 'root', '0644'))
        self.assertEqual(self.apply(target_hostname=None)['failed'], [])       # later runs need no name...
        self.assertIn('this machine is', self.refused('apply', '--target-hostname', 'other'))   # ...but a wrong one stops

    def test_with_the_marker_repeat_applies_converge_after_units_are_running(self):
        self.build()                                     # apply, handoffs, apply --activate
        self.assertTrue(rebuild.appliance_units(INV, self.host(readonly=True)))     # it is an appliance now
        marker = self.host().path(self.MARKER).read_bytes()
        for _ in range(2):
            again = self.apply(activate=True, target_hostname=None)
            self.assertEqual((again['changed'], again['failed']), ([], []))
        self.assertEqual(self.host().path(self.MARKER).read_bytes(), marker)        # written once

    def test_something_that_is_not_a_marker_does_not_open_the_guard(self):
        self.live_appliance()
        host = self.host()
        good = {'schema': 'avrana.rebuild-marker/v0', 'created': '20260101T000000Z', 'hostname': self.NAME}
        shapes = [b'', b'not json', b'[]', json.dumps(dict(good, schema='other')).encode(),
                  json.dumps({k: v for k, v in good.items() if k != 'hostname'}).encode(),
                  json.dumps(dict(good, created=7)).encode(), json.dumps(dict(good, sealed=True)).encode()]
        for data in shapes:
            host.install(data, self.MARKER, 'root', 'root', '0644')
            with self.subTest(data=data):
                self.assertIsNone(rebuild.read_marker(INV, self.host(readonly=True)))
                self.assertEqual(rebuild.guard_state(INV, self.host(readonly=True)), 'appliance')
                self.assertIn('no valid rebuild marker', self.refused('apply', '--target-hostname', self.NAME))
        host.remove(self.MARKER)
        host.mkdir(self.MARKER, 'root', 'root', '0755')                      # a directory
        self.assertIn('no valid rebuild marker', self.refused('apply', '--target-hostname', self.NAME))
        host.path(self.MARKER).rmdir()
        host.install(json.dumps(good).encode(), '/tmp/elsewhere.json', 'root', 'root', '0644')
        host.symlink('/tmp/elsewhere.json', self.MARKER)                     # a link to a perfectly good one
        self.assertIsNone(rebuild.read_marker(INV, self.host(readonly=True)))
        self.assertIn('refused', self.refused('apply', '--target-hostname', self.NAME))
        lines = []
        with contextlib.redirect_stderr(io.StringIO()):
            rebuild.main(['plan', '--root', str(self.root)], out=lines.append)
        self.assertIn('no valid rebuild marker', lines[1])
        self.assertEqual(self.ran(), [])
        host.symlink('/nowhere', self.MARKER)
        host.remove(self.MARKER)
        host.install(json.dumps(good).encode(), self.MARKER, 'root', 'root', '0644')    # the real thing does
        self.assertEqual(rebuild.guard_state(INV, self.host(readonly=True)), 'open')

    def test_seal_ends_the_build_and_the_host_is_then_refused_like_any_appliance(self):
        self.assertIn('no valid rebuild marker', self.refused('seal'))               # nothing to seal on a clean host
        self.build()
        self.host().install(b'edited\n', '/etc/systemd/journald.conf.d/avrana.conf', 'root', 'root', '0644')
        backup = self.apply(target_hostname=None)['backup']
        lines = []
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(rebuild.main(['plan', '--root', str(self.root)], out=lines.append), 0)
            self.assertIn('guard: open', lines[1])
            self.assertEqual(rebuild.main(['seal', '--root', str(self.root)], out=lines.append), 0)
        marker = json.loads(self.host().path(self.MARKER).read_text(encoding='utf-8'))
        self.assertRegex(marker['sealed'], r'^\d{8}T\d{6}Z$')
        self.assertEqual(rebuild.guard_state(INV, self.host(readonly=True)), 'sealed')
        ran = len(self.ran())
        self.assertIn('was sealed', self.refused('apply', '--activate'))
        self.assertIn('was sealed', self.refused('apply', '--target-hostname', self.NAME))
        self.assertIn('was sealed', self.refused('restore', backup))
        self.assertIn('override included', self.refused('apply', self.OVERRIDE, '--target-hostname', self.NAME))
        self.assertIn('override included', self.refused('restore', backup, self.OVERRIDE, '--target-hostname', self.NAME))
        self.assertEqual(len(self.ran()), ran)
        sealed = self.host().path(self.MARKER).read_bytes()
        with contextlib.redirect_stderr(io.StringIO()):                              # sealing twice changes nothing
            self.assertEqual(rebuild.main(['seal', '--root', str(self.root)], out=lambda *_: None), 0)
            self.assertEqual(self.host().path(self.MARKER).read_bytes(), sealed)
            for command, rc in (('plan', 0), ('verify', 0)):                         # reading is always allowed
                lines = []
                self.assertEqual(rebuild.main([command, '--root', str(self.root)], out=lines.append), rc)
                self.assertIn('guard: SEALED on ' + marker['sealed'], lines[1])
            self.assertEqual(rebuild.main(['verify', '--json', '--root', str(self.root)], out=lines.append), 0)
        self.assertEqual(json.loads(lines[-1])['guard'], 'sealed')
        self.assertEqual(self.host().path(self.MARKER).read_bytes(), sealed)
        self.assertIn('avrana.ops.rebuild seal', RUNBOOK)
        self.assertIn('| 12 | owner | `seal`', RUNBOOK)

    def test_restore_obeys_the_same_rule(self):
        first = self.apply()
        self.host().install(b'edited\n', '/etc/systemd/journald.conf.d/avrana.conf', 'root', 'root', '0644')
        backup = self.apply()['backup']
        self.assertTrue(backup and backup != first['backup'])
        self.host().remove(self.MARKER)                  # the same host, as if this tool never built it
        before = tree(self.root)
        with self.assertRaises(rebuild.RebuildError) as refused:
            rebuild.restore(INV, self.host(), backup)
        self.assertIn('no valid rebuild marker', str(refused.exception))
        self.assertIn('refused', self.refused('restore', backup))
        with self.assertRaises(rebuild.RebuildError):    # and apply no longer goes on either
            self.apply()
        self.assertEqual(tree(self.root), before)

    def test_plan_and_verify_are_allowed_on_a_live_appliance_and_change_nothing(self):
        self.live_appliance()
        before = tree(self.root)
        with contextlib.redirect_stderr(io.StringIO()):
            lines = []
            self.assertEqual(rebuild.main(['plan', '--root', str(self.root)], out=lines.append), 0)
            self.assertIn('apply and restore are refused', lines[1])
            self.assertEqual(rebuild.main(['verify', '--root', str(self.root)], out=lines.append), 1)
        self.assertEqual(tree(self.root), before)
        with tempfile.TemporaryDirectory() as tmp:
            lines = []
            with contextlib.redirect_stderr(io.StringIO()):
                rebuild.main(['plan', '--root', str(Path(tmp) / 'clean')], out=lines.append)
            self.assertEqual(lines[1], 'guard: clean target, no marker: the first apply needs --target-hostname simulated-host')

    def test_the_guard_is_pinned_to_the_inventory(self):
        def broken(change):
            inv = copy.deepcopy(INV)
            change(inv)
            return ' | '.join(rebuild.validate(inv))
        self.assertIn('is not an appliance sign', broken(lambda i: i['guard']['appliance_paths'].remove(
            '/etc/systemd/system/avranaparty-games.service')))
        self.assertIn('unit avrana-party-core is not an appliance sign',
                      broken(lambda i: i['guard']['appliance_units'].remove('avrana-party-core')))
        self.assertIn('marker must live outside', broken(lambda i: i['guard'].update(marker='/var/lib/avrana-party/m.json')))
        self.assertIn('guard: needs', broken(lambda i: i.pop('guard')))
        self.assertIn(self.MARKER, RUNBOOK)


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

    def test_the_uinput_device_shows_whether_the_rule_was_activated(self):
        self.assertEqual(rebuild.uinput_check(('root', 'input', '0660'))[:3], ('arcade', 'uinput device', rebuild.PASS))
        for meta, hint in ((None, 'modprobe uinput'), (('root', 'root', '0600'), 'udevadm trigger'),
                           (('root', 'input', '0600'), 'udevadm control --reload-rules')):
            result = rebuild.uinput_check(meta)
            self.assertEqual(result[2], rebuild.FAIL, meta)
            self.assertIn(hint, result[3])
        rule = text('arcade/70-avrana-uinput.rules')
        self.assertIn('GROUP="input"', rule)
        self.assertIn('MODE="0660"', rule)

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

    @unittest.skipUnless(platform.system() == 'Linux', 'a real host needs Linux')
    def test_a_real_host_is_read_but_never_changed_without_root(self):
        """The only test that looks at the machine it runs on, and it only looks. `apply` and
        `restore` are replaced for its duration, so no user this runs as (root in a container
        included) can reach a real change; the refusal itself is checked with a pretended uid."""
        def unreachable(*args, **kwargs):
            raise AssertionError('a test reached a real apply or restore')
        with mock.patch.object(rebuild, 'apply', unreachable), mock.patch.object(rebuild, 'restore', unreachable), \
                mock.patch.object(rebuild, 'seal', unreachable), mock.patch.object(os, 'geteuid', lambda: 1000):
            for command in (['apply'], ['apply', '--activate'], ['restore', '/var/backups/avrana-party/x'], ['seal']):
                rc, _, err = self.run_cli(*command)
                self.assertEqual(rc, 2, command)
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
            for change in (lambda: host.install(b'', str(target), 'root', 'root', '0644'), lambda: host.remove(str(target)),
                           lambda: host.mkdir(tmp + '/d', 'root', 'root', '0755'), lambda: host.run(['true'])):
                with self.assertRaises(rebuild.RebuildError):
                    change()
            self.assertEqual(target.read_bytes(), b'x')

    def test_every_other_test_works_on_a_simulated_host(self):
        """No test may construct a real host that can change anything. Read from the syntax tree,
        so `Host()`, `Host(None)` and `Host(root=None)` are all seen: every Host (or subclass of
        it defined here) gets a root that is not None, except one read-only real host; and every
        `main` call that can change something carries --root or runs under the patches above."""
        module = ast.parse(Path(__file__).read_text(encoding='utf-8'))
        hosts = {'Host'} | {n.name for n in ast.walk(module) if isinstance(n, ast.ClassDef)
                            and any(getattr(b, 'attr', None) == 'Host' for b in n.bases)}
        self.assertGreater(len(hosts), 3)
        real = []
        mains = 0
        for node in ast.walk(module):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, 'attr', None) or getattr(node.func, 'id', None)
            if name in hosts:
                root = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == 'root'), None)
                if root is None or (isinstance(root, ast.Constant) and root.value is None):
                    real.append(node)
            if name == 'main' and node.args and isinstance(node.args[0], ast.List):
                words = [e.value for e in node.args[0].elts if isinstance(e, ast.Constant)]
                if {'apply', 'restore', 'seal'} & set(words):
                    mains += 1
                    self.assertIn('--root', words, ast.unparse(node))
        self.assertGreaterEqual(mains, 3)
        self.assertEqual(len(real), 1)
        self.assertEqual([(k.arg, k.value.value) for k in real[0].keywords], [('readonly', True)])
        # run_cli (this class) and Guard.refused build their argv elsewhere: both checked here.
        source = Path(__file__).read_text(encoding='utf-8')
        self.assertIn("rebuild.main([*argv, '--root', str(self.root)]", source)
        direct = re.findall(r"self\.run_cli\(([^)]*)\)", source)
        for call in direct:
            if any(word in call for word in ("'apply'", "'restore'", "'seal'", '*command')):
                self.assertTrue("'--root'" in call or call == '*command', call)


if __name__ == '__main__':
    unittest.main()
