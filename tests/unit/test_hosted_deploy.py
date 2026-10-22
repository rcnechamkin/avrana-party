"""The hosted staging deployment files agree with each other (docs/design/HOSTED-STAGING.md,
docs/runbooks/hosted-staging.md). Nothing here runs a VM, a tunnel or a firewall: these are static
checks that a name, an address range or a port changed in one file is changed in all of them. The
isolation itself is proven by trying (deploy/hosted/vm/verify-isolation.sh, runbook steps 3 and 6)."""
import ipaddress
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest
import xml.etree.ElementTree as ET

from avrana.contracts import appliance, party_config, vocabulary
from avrana.ops import hosted_site, status

REPO = Path(__file__).resolve().parents[2]
HOSTED = REPO / 'deploy' / 'hosted'
CONF = json.loads((HOSTED / 'party-core.hosted.json').read_text(encoding='utf-8'))
NWFILTER = ET.parse(HOSTED / 'vm' / 'avrana-staging-egress.nwfilter.xml').getroot()
NFT = (HOSTED / 'vm' / 'avrana-staging.nft').read_text(encoding='utf-8')
TUNNEL = (HOSTED / 'cloudflared' / 'config.yml.example').read_text(encoding='utf-8')
SITE = (HOSTED / 'avrana-party.hosted.nginx').read_text(encoding='utf-8')
BASH = shutil.which('bash')
SCRIPTS = sorted((HOSTED / 'vm').glob('*.sh'))


def nwfilter_drops():
    nets = set()
    for rule in NWFILTER.iter('rule'):
        if rule.get('action') == 'drop' and rule.get('direction') == 'out':
            for match in rule:
                if match.get('dstipaddr'):
                    nets.add(ipaddress.ip_network(f"{match.get('dstipaddr')}/{match.get('dstipmask')}"))
    return nets


def nft_private():
    block = re.search(r'set private4 \{.*?elements = \{(.*?)\}', NFT, re.S).group(1)
    return {ipaddress.ip_network(x.strip()) for x in block.split(',') if x.strip()}


class Network(unittest.TestCase):
    MUST_BLOCK = ['10.0.0.218', '10.0.0.1', '10.0.0.142', '192.168.122.1', '172.17.0.1', '169.254.169.254',
                  '127.0.0.1', '100.64.0.1', '192.168.1.1', '224.0.0.251']

    def test_host_filter_and_vm_firewall_block_the_same_ranges(self):
        self.assertEqual(nwfilter_drops(), nft_private())

    def test_every_media_and_lan_address_is_in_a_blocked_range(self):
        for addr in self.MUST_BLOCK:
            ip = ipaddress.ip_address(addr)
            self.assertTrue(any(ip in net for net in nwfilter_drops()), addr)

    def test_the_only_gateway_exceptions_are_dns_out_and_ssh_in(self):
        exceptions = []
        for rule in NWFILTER.iter('rule'):
            for match in rule:
                if '192.168.122.1' in (match.get('dstipaddr'), match.get('srcipaddr')):
                    exceptions.append((rule.get('action'), rule.get('direction'), match.tag, match.get('dstportstart')))
        self.assertEqual(sorted(exceptions), [('accept', 'in', 'tcp', '22'), ('accept', 'out', 'tcp', '53'),
                                              ('accept', 'out', 'udp', '53')])
        # and the exceptions come before the private-range drops
        prio = {(r.get('action'), next(iter(r)).tag, next(iter(r)).get('dstipaddr')): int(r.get('priority')) for r in NWFILTER.iter('rule')}
        drop = min(p for (a, _, d), p in prio.items() if a == 'drop' and d and d != '0.0.0.0')
        self.assertLess(prio[('accept', 'udp', '192.168.122.1')], drop)

    def test_anti_spoofing_ipv6_off_and_default_drop(self):
        self.assertEqual([f.get('filter') for f in NWFILTER.iter('filterref')], ['clean-traffic'])
        rules = list(NWFILTER.iter('rule'))
        self.assertTrue(any(r.get('action') == 'drop' and next(iter(r)).tag == 'ipv6' for r in rules))
        last = max(rules, key=lambda r: int(r.get('priority')))
        self.assertEqual((last.get('action'), last.get('direction'), next(iter(last)).tag), ('drop', 'inout', 'all'))

    def test_vm_firewall_defaults_to_drop_and_admits_only_ssh_from_the_gateway(self):
        self.assertEqual(len(re.findall(r'policy drop;', NFT)), 3)
        inbound = re.search(r'chain input \{(.*?)\n    \}', NFT, re.S).group(1)
        self.assertIn('ip saddr $gateway tcp dport 22 ct state new accept', inbound)
        self.assertNotRegex(inbound, r'tcp dport (?!22\b)\d+')
        self.assertEqual(re.findall(r'udp dport (\d+)', inbound), ['68'])      # the DHCP answer only
        self.assertIn('define gateway = 192.168.122.1', NFT)
        self.assertIn('meta nfproto ipv6 drop', NFT)

    def test_isolation_probes_cover_the_media_host_on_both_addresses(self):
        script = (HOSTED / 'vm' / 'verify-isolation.sh').read_text(encoding='utf-8')
        ports = set(re.search(r'MEDIA_PORTS=\(([^)]*)\)', script).group(1).split())
        # what the Media host was seen listening on (docs/design/HOSTED-STAGING.md §4), the ones a VM could abuse
        for port in ('22', '80', '8096', '8123', '9000', '32400', '25600', '13378'):
            self.assertIn(port, ports)
        self.assertIn('forbid "$GATEWAY"', script)
        self.assertIn('forbid "$MEDIA_LAN"', script)
        self.assertIn('--host-layer-only', script)


class Names(unittest.TestCase):
    def test_core_config_is_valid_and_names_the_rendered_hosts(self):
        party, games = hosted_site.PARTY_HOST, hosted_site.GAME_HOST
        self.assertEqual(CONF['hosts'], [party])
        self.assertEqual(CONF['origins'], [f'https://{party}'])
        self.assertEqual(list(CONF['game_origins']), [f'https://{games}'])
        self.assertTrue(CONF['secure_cookie'])
        self.assertNotIn('limited', CONF)                        # no plain-HTTP listener hosted
        self.assertEqual(CONF['games'], {})                      # no loopback provider (8096, arcade) in the first wave
        r = subprocess.run(['python', '-m', 'avrana.contracts.party_config', '--check', str(HOSTED / 'party-core.hosted.json')],
                           cwd=REPO, capture_output=True, text=True) if shutil.which('python') else None
        if r is not None:
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_status_block_has_no_appliance_parts_and_compares_the_hosted_site(self):
        cfg = status.load_config(CONF)
        self.assertIsNone(cfg['certificate'])
        self.assertIsNone(cfg['games_url'])
        self.assertIsNone(cfg['arcade_url'])
        for unit in ('avranaparty-games', 'avranaparty-arcade', 'NetworkManager', 'avrana-party-certificate.timer'):
            self.assertNotIn(unit, cfg['units'])
        self.assertIn('cloudflared-avrana-party', cfg['units'])
        self.assertTrue(all(s.endswith('deploy/hosted/avrana-party.hosted.nginx') for s in cfg['nginx_site_sources']))

    def test_tunnel_routes_exactly_the_two_hosts_to_the_edge_with_access_required(self):
        hosts = re.findall(r'^\s*- hostname: (\S+)', TUNNEL, re.M)
        self.assertEqual(hosts, [hosted_site.PARTY_HOST, hosted_site.GAME_HOST])
        self.assertEqual(set(re.findall(r'service: (\S+)', TUNNEL)), {f'http://{hosted_site.LISTEN}', 'http_status:404'})
        self.assertEqual(TUNNEL.count('required: true'), 2)
        self.assertTrue(TUNNEL.rstrip().endswith('- service: http_status:404'))
        self.assertNotRegex(TUNNEL, r'eyJ|AccountTag|TunnelSecret')        # no credential in the example

    def test_site_listens_where_the_tunnel_sends(self):
        self.assertEqual(set(re.findall(r'listen ([^ ;]+)', SITE)), {hosted_site.LISTEN})

    def test_hosted_appliance_grants_first_wave_only(self):
        doc = appliance.load(REPO / 'contracts' / 'appliances' / 'avrana-hosted.json', vocabulary.load())
        self.assertEqual([g['game'] for g in doc['installed']], ['checkers'])
        self.assertFalse([p for p in doc['providers'] if p['status'] == 'live'])
        pi = json.loads((REPO / 'contracts' / 'appliances' / 'avrana-pi4.json').read_text(encoding='utf-8'))
        self.assertEqual(doc['installed'][0], next(g for g in pi['installed'] if g['game'] == 'checkers'))


class Scripts(unittest.TestCase):
    @unittest.skipUnless(BASH, 'bash')
    def test_every_script_parses(self):
        self.assertTrue(SCRIPTS)
        for script in SCRIPTS:
            r = subprocess.run([BASH, '-n', str(script)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f'{script.name}: {r.stderr}')

    def test_scripts_never_touch_the_media_tunnels_or_docker(self):
        for script in SCRIPTS:
            text = script.read_text(encoding='utf-8')
            code = '\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('#'))
            # reading a Media tunnel's state (host-preflight's `systemctl is-active`) is allowed; changing one is not
            self.assertNotRegex(code, r'systemctl\s+(?:stop|start|restart|reload|enable|disable|mask|edit)\b[^\n]*cloudflared(?!-avrana-party)'
                                      r'|docker\s|\.cloudflared/|/etc/nginx/sites-(?:available|enabled)/homeassistant', script.name)

    def test_create_vm_refuses_without_a_ready_preflight_and_has_an_undo(self):
        text = (HOSTED / 'vm' / 'create-vm.sh').read_text(encoding='utf-8')
        self.assertIn('host-preflight.sh', text)
        self.assertIn('nothing was changed', text)
        self.assertIn('--destroy', text)
        self.assertIn('filterref.filter=avrana-staging-egress', text)
        self.assertNotIn('hostfwd', text)
        self.assertNotRegex(text, r'--network\s+"?bridge')

    def test_provision_never_writes_a_secret(self):
        text = (HOSTED / 'vm' / 'provision.sh').read_text(encoding='utf-8')
        self.assertNotRegex(text, r'game-keys/\S+\.key|cloudflared tunnel|cert\.pem')


if __name__ == '__main__':
    unittest.main()
