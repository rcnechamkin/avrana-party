"""The offline appliance preflight (avrana.ops.preflight) with fake probes: no Pi, no network."""
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import socket
import struct
import sys
import tempfile
import threading
import unittest
from unittest import mock

from avrana import REPO_ROOT
from avrana.contracts import party_games
from avrana.ops import preflight, smoke

NOW = datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)
PARTY = 'a' * 40
GAMES = 'b' * 40


def status_doc(**over):
    doc = {
        'schema': 'avrana.status/v0',
        'deployment': {'deployed_at': '2026-10-20T12:00:00Z', 'party': {'sha': PARTY}, 'games': {'sha': GAMES}},
        'manifest_error': None,
        'party': {'deployed_sha': PARTY, 'checkout_sha': PARTY, 'dirty': False, 'deployed_dirty': False, 'ref': 'main',
                  'mismatch': False},
        'games': {'deployed_sha': GAMES, 'checkout_sha': GAMES, 'dirty': False, 'deployed_dirty': False, 'ref': 'main',
                  'mismatch': False},
        'web_release': {'build': '20261020T120000Z', 'commit': PARTY},
        'nginx_site': {'status': 'match', 'sha256': 'c' * 64},
        'last_known_good': {'party_sha': PARTY, 'games_sha': GAMES},
        'contract': dict(party_games.versions(), games_advertises=party_games.versions()['lan_launch']),
        'services': {'avrana-party-core': 'active', 'avranaparty-games': 'active', 'nginx': 'active',
                     'avrana-party-certificate.timer': 'not-installed'},
        'recovery': {'units': {}, 'failed_game_units': []},
        'party_core': {'ok': True, 'members': 0, 'session': None},
    }
    doc.update(over)
    return doc


def gate(verdict='PASS', hours_ago=2.0, channel=36, schema='avrana.wifi-gate/v1'):
    return {'schema': schema, 'verdict': verdict, 'started': (NOW - timedelta(hours=hours_ago)).isoformat(),
            'ap': {'band': '5GHz', 'channel': channel, 'width_mhz': 80}, 'client': {'model': 'SM-T510'},
            'thresholds_status': 'provisional',
            'results': [{'level': verdict, 'text': f'idle p99 RTT {verdict.lower()}'}]}


def cert(days=80, names=('party.avrana.net',), verified=True, error=None):
    return {'verified': verified, 'error': error, 'not_after': NOW + timedelta(days=days), 'names': list(names)}


class FakeProbes:
    def __init__(self, **over):
        self.config = over.pop('config', {'hosts': ['party.avrana.net'], 'origins': ['https://party.avrana.net']})
        self.doc = over.pop('doc', status_doc())
        self.source = over.pop('source', 'party-core')
        self.smoke_results = over.pop('smoke', [smoke.Result('captive_probe', 'pass', 'ok'),
                                                smoke.Result('party_home', 'pass', 'ok'),
                                                smoke.Result('encoder', 'skip', 'emulator idle')])
        self.certs = over.pop('certs', {'party.avrana.net': cert(), 'games.avrana.net': cert(names=('party.avrana.net',
                                                                                                  'games.avrana.net'))})
        self.dns = over.pop('dns', {'party.avrana.net': '10.42.0.1', 'games.avrana.net': '10.42.0.1'})
        self.topo = over.pop('topology', ([('PASS', 'wlan0 is in AP mode'), ('INFO', 'channel 36')], None))
        self.channel = over.pop('channel', 36)
        self.health = over.pop('health', ({'state': 'HEALTHY', 'reasons': [], 'evidence': {'ts': '2026-10-21T17:55:00Z'}},
                                          'timer state file', None))
        self.clock_doc = over.pop('clock', {'synchronized': False, 'now': NOW})
        self.files = over.pop('files', set())
        self.journal = over.pop('journal', 'persistent')
        self.disks = over.pop('disks', {'/': {'total': 64 << 30, 'free': 40 << 30},
                                        '/var/lib': {'total': 64 << 30, 'free': 40 << 30}})
        self.pkgs = over.pop('packages', ([], [], None))
        self.node = over.pop('node', None)
        self.tools = over.pop('tools', {t: True for t in preflight.REQUIRED_TOOLS + ('dig',)})
        self.python = over.pop('python', (3, 11, 2))
        assert not over, over

    def party_config(self, path):
        return (self.config, None) if self.config is not None else (None, 'not readable by this user')

    def status_doc(self, cfg):
        return self.doc, self.source

    def smoke(self):
        return self.smoke_results

    def smoke_local(self, base):
        return self.smoke_results

    def local_status(self, base):
        return self.doc, self.source

    def served_certificate(self, name):
        return self.certs.get(name)

    def resolve(self, name):
        return self.dns.get(name)

    def topology(self):
        return self.topo

    def ap_channel(self):
        return self.channel

    def pi_health(self, now):
        return self.health

    def clock(self):
        return self.clock_doc

    def exists(self, path):
        return path in self.files

    def journal_storage(self):
        return self.journal

    def disk(self, path):
        return self.disks.get(path)

    def packages(self):
        return self.pkgs

    def node_runtime(self):
        return self.node

    def which(self, tool):
        return self.tools.get(tool, False)

    def python_version(self):
        return self.python


def run(probes=None, **kw):
    kw.setdefault('wifi_gate', gate())
    return preflight.run(probes or FakeProbes(), now=NOW, **kw)


def by_id(doc, check_id):
    return next(c for c in doc['checks'] if c['id'] == check_id)


class Verdicts(unittest.TestCase):
    def test_a_healthy_appliance_with_a_fresh_gate_is_ready(self):
        doc = run()
        self.assertEqual((doc['verdict'], doc['blocking']), ('READY', []))
        self.assertEqual(doc['schema'], 'avrana.preflight/v0')
        self.assertEqual(doc['revisions']['party']['deployed_sha'], PARTY)
        self.assertEqual(doc['revisions']['games']['deployed_sha'], GAMES)
        self.assertEqual(preflight.EXIT[doc['verdict']], 0)
        json.dumps(doc)                       # serializable as it is

    def test_advisory_problems_warn_but_stay_ready(self):
        doc = run(FakeProbes(journal='volatile', files={preflight.REBOOT_REQUIRED}))
        self.assertEqual((doc['verdict'], doc['overall']), ('READY', 'WARN'))
        self.assertEqual(by_id(doc, 'pi.journal')['status'], 'WARN')
        self.assertIn('AVR-29', by_id(doc, 'pi.journal')['reason'])
        self.assertEqual(by_id(doc, 'pi.reboot_required')['status'], 'WARN')

    def test_any_blocking_fail_is_not_ready_and_named(self):
        doc = run(FakeProbes(dns={'party.avrana.net': '192.168.1.5'}))
        self.assertEqual((doc['verdict'], doc['overall']), ('NOT_READY', 'FAIL'))
        self.assertEqual(doc['blocking'], ['dns.party.avrana.net'])
        self.assertIn('phones need 10.42.0.1', by_id(doc, 'dns.party.avrana.net')['reason'])
        self.assertEqual(preflight.EXIT['NOT_READY'], 1)

    def test_a_blocking_unknown_is_never_ready(self):
        doc = run(FakeProbes(dns={}))
        self.assertEqual(doc['verdict'], 'UNKNOWN')
        self.assertEqual(by_id(doc, 'dns.party.avrana.net')['status'], 'UNKNOWN')

    def test_fail_wins_over_unknown(self):
        doc = run(FakeProbes(dns={}, disks={'/': {'total': 64 << 30, 'free': 100 << 20}, '/var/lib': None}))
        self.assertEqual(doc['verdict'], 'NOT_READY')

    def test_waiving_a_blocking_unknown_is_recorded(self):
        doc = run(wifi_gate=None, waive=['wifi.gate'])
        self.assertEqual((doc['verdict'], doc['waived']), ('READY', ['wifi.gate']))
        self.assertIn('(waived)', preflight.render_text(doc))
        self.assertIn('Wi-Fi qualification', doc['physically_unverified'][0])

    def test_a_fail_cannot_be_waived(self):
        doc = run(FakeProbes(dns={'party.avrana.net': ''}), waive=['dns.party.avrana.net'])
        self.assertEqual((doc['verdict'], doc['waived']), ('NOT_READY', []))
        self.assertTrue(any('--waive ignored' in n for n in doc['notes']))

    def test_the_phone_only_list_is_always_there(self):
        doc = run()
        self.assertTrue(any('Safari' in u for u in doc['physically_unverified']))
        self.assertIn('Needs a real phone', preflight.render_text(doc))
        self.assertIn('not a phone or human acceptance result', doc['level'])


class WifiGate(unittest.TestCase):
    def status(self, **kw):
        return preflight.wifi_checks(kw.pop('doc', gate()), NOW, kw.pop('channel', 36), **kw)[0]

    def test_missing_is_unknown_with_the_command_to_run(self):
        c = preflight.wifi_checks(None, NOW, 36)[0]
        self.assertEqual(c['status'], 'UNKNOWN')
        self.assertIn('wifilab.py gate', c['reason'])

    def test_fresh_results_map_to_their_level(self):
        for v in ('PASS', 'WARN', 'FAIL'):
            self.assertEqual(self.status(doc=gate(v))['status'], v)

    def test_stale_result_is_unknown_not_its_old_verdict(self):
        c = self.status(doc=gate('PASS', hours_ago=30))
        self.assertEqual(c['status'], 'UNKNOWN')
        self.assertIn('30 h old', c['reason'])

    def test_the_age_limit_is_configurable(self):
        self.assertEqual(self.status(doc=gate(hours_ago=30), max_age_h=48)['status'], 'PASS')

    def test_another_channel_is_unknown(self):
        c = self.status(doc=gate(channel=149), channel=36)
        self.assertEqual(c['status'], 'UNKNOWN')
        self.assertIn('channel 149', c['reason'])

    def test_future_dated_wrong_schema_and_bad_time_are_unknown(self):
        self.assertEqual(self.status(doc=gate(hours_ago=-3))['status'], 'UNKNOWN')
        self.assertEqual(self.status(doc=gate(schema='avrana.wifi-trial/v1'))['status'], 'UNKNOWN')
        self.assertEqual(self.status(doc=dict(gate(), started='yesterday'))['status'], 'UNKNOWN')
        self.assertEqual(self.status(doc=dict(gate(), verdict='GREAT'))['status'], 'UNKNOWN')

    def test_naive_wifilab_timestamps_are_local_time(self):
        local = (NOW - timedelta(hours=1)).astimezone().replace(tzinfo=None).isoformat(timespec='seconds')
        self.assertEqual(self.status(doc=dict(gate(), started=local))['status'], 'PASS')

    def test_newest_gate_in_a_results_directory(self):
        with tempfile.TemporaryDirectory() as d:
            for stamp in ('20261020-100000', '20261021-090000'):
                (Path(d) / f'{stamp}_gate_510A').mkdir()
                (Path(d) / f'{stamp}_gate_510A' / 'gate.json').write_text(json.dumps(dict(gate(), started=stamp)))
            (Path(d) / '20261022-000000_x_idle_510A').mkdir()
            doc, source = preflight.load_wifi_gate(d)
            self.assertEqual((doc['started'], source), ('20261021-090000', '20261021-090000_gate_510A'))

    def test_unreadable_gate_file(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'gate.json').write_text('{not json')
            self.assertEqual(preflight.load_wifi_gate(str(Path(d) / 'gate.json'))[0], 'unreadable')


class Certificates(unittest.TestCase):
    def one(self, facts, horizon=0, name='party.avrana.net'):
        return preflight.tls_checks([name], {name: facts}, NOW, horizon)[0]

    def test_verified_and_long_enough(self):
        self.assertEqual(self.one(cert(80))['status'], 'PASS')

    def test_inside_the_renewal_window_warns(self):
        self.assertEqual(self.one(cert(15))['status'], 'WARN')

    def test_expiring_during_the_trip_fails(self):
        c = self.one(cert(15), horizon=20)
        self.assertEqual(c['status'], 'FAIL')
        self.assertIn('20-day horizon', c['reason'])

    def test_the_horizon_widens_the_warning(self):
        self.assertEqual(self.one(cert(30), horizon=14)['status'], 'WARN')

    def test_expired_unverified_uncovered_and_unreachable_fail(self):
        self.assertEqual(self.one(cert(-1))['status'], 'FAIL')
        c = self.one(cert(80, verified=False, error='self-signed certificate', names=('party.avrana.net',)))
        self.assertEqual(c['status'], 'FAIL')
        self.assertIn('a phone would refuse', c['reason'])
        c = self.one(cert(80, verified=False, error="Hostname mismatch", names=('party.avrana.net',)), name='games.avrana.net')
        self.assertIn('names party.avrana.net', c['reason'])
        self.assertEqual(self.one(None)['status'], 'FAIL')

    def test_wildcards(self):
        self.assertTrue(preflight._name_matches('*.avrana.net', 'games.avrana.net'))
        self.assertFalse(preflight._name_matches('*.avrana.net', 'a.b.avrana.net'))

    def test_game_origin_names_come_from_party_core_config(self):
        config = {'hosts': ['party.avrana.net'], 'game_origins': {'https://games.avrana.net': ['checkers']}}
        doc = run(FakeProbes(config=config, certs={'party.avrana.net': cert(), 'games.avrana.net': cert()}))
        self.assertEqual(doc['names'], {'party': ['party.avrana.net'], 'game_origins': ['games.avrana.net']})
        self.assertEqual(by_id(doc, 'tls.games.avrana.net')['status'], 'FAIL')    # one-name certificate
        self.assertIn('dns.games.avrana.net', {c['id'] for c in doc['checks']})

    def test_unreadable_config_falls_back_and_says_so(self):
        doc = run(FakeProbes(config=None))
        self.assertEqual(doc['names']['party'], ['party.avrana.net'])
        self.assertEqual(by_id(doc, 'config.party_core')['status'], 'WARN')


class Revisions(unittest.TestCase):
    def test_checkout_moved_since_the_deploy_fails(self):
        d = status_doc()
        d['party'] = dict(d['party'], checkout_sha='d' * 40, mismatch=True)
        c = by_id(run(FakeProbes(doc=d)), 'revision.party')
        self.assertEqual(c['status'], 'FAIL')
        self.assertIn('d' * 12, c['reason'])

    def test_no_manifest_is_unknown(self):
        d = status_doc(deployment=None)
        d['party'] = dict(d['party'], deployed_sha=None)
        doc = run(FakeProbes(doc=d))
        self.assertEqual(by_id(doc, 'revision.manifest')['status'], 'UNKNOWN')
        self.assertEqual(by_id(doc, 'revision.party')['status'], 'UNKNOWN')
        self.assertEqual(doc['verdict'], 'UNKNOWN')

    def test_web_build_and_nginx_drift_fail(self):
        doc = run(FakeProbes(doc=status_doc(web_release={'build': 'x', 'commit': 'e' * 40},
                                            nginx_site={'status': 'differs'})))
        self.assertEqual(by_id(doc, 'revision.web_release')['status'], 'FAIL')
        self.assertEqual(by_id(doc, 'revision.nginx_site')['status'], 'FAIL')

    def test_no_rollback_target_is_advisory(self):
        doc = run(FakeProbes(doc=status_doc(last_known_good=None)))
        c = by_id(doc, 'revision.last_known_good')
        self.assertEqual((c['status'], c['blocking'], doc['verdict']), ('WARN', False, 'READY'))

    def test_a_status_built_locally_says_so(self):
        self.assertEqual(by_id(run(FakeProbes(source='local')), 'revision.source')['status'], 'WARN')


class Services(unittest.TestCase):
    def test_failed_unavailable_and_crash_looping_units(self):
        d = status_doc(services={'avrana-party-core': 'failed', 'nginx': 'unavailable', 'avranaparty-games': 'active'},
                       recovery={'units': {'avranaparty-games': {'restarts': 3, 'active_for_s': 5}}, 'failed_game_units': []})
        doc = run(FakeProbes(doc=d))
        self.assertEqual(by_id(doc, 'service.avrana-party-core')['status'], 'FAIL')
        self.assertEqual(by_id(doc, 'service.nginx')['status'], 'UNKNOWN')
        self.assertIn('not yet stable', by_id(doc, 'service.avranaparty-games')['reason'])

    def test_optional_unit_absent_is_not_a_fault(self):
        c = by_id(run(), 'service.avrana-party-certificate.timer')
        self.assertEqual((c['status'], c['blocking']), ('PASS', False))

    def test_a_live_session_is_an_advisory(self):
        d = status_doc(party_core={'ok': True, 'session': {'game': 'bluff', 'state': 'playing'}})
        c = by_id(run(FakeProbes(doc=d)), 'session.live')
        self.assertEqual((c['status'], c['blocking']), ('WARN', False))
        self.assertIn('--force-busy', c['reason'])

    def test_smoke_skip_is_unknown_and_encoder_is_advisory(self):
        doc = run(FakeProbes(smoke=[smoke.Result('party_home', 'skip', 'x'), smoke.Result('encoder', 'fail', 'y')]))
        self.assertEqual(by_id(doc, 'serving.party_home')['status'], 'UNKNOWN')
        self.assertFalse(by_id(doc, 'serving.encoder')['blocking'])


class PiAndPackages(unittest.TestCase):
    def test_storage_thresholds(self):
        cases = {10 << 30: 'PASS', (1 << 30) + (1 << 29): 'WARN', 100 << 20: 'FAIL'}
        for free, want in cases.items():
            c = preflight.storage_checks({'/': {'total': 16 << 30, 'free': free}}, {'/': preflight.STORAGE['/']})[0]
            self.assertEqual(c['status'], want, free)
        self.assertEqual(preflight.storage_checks({'/': None}, {'/': preflight.STORAGE['/']})[0]['status'], 'UNKNOWN')

    def test_pi_health_states(self):
        for state, want in preflight.PI_HEALTH_LEVEL.items():
            doc = run(FakeProbes(health=({'state': state, 'reasons': ['r']}, 'one bounded run', None)))
            self.assertEqual(by_id(doc, 'pi.health')['status'], want, state)
        doc = run(FakeProbes(health=(None, 'none', 'pi-health-check.py not found')))
        self.assertEqual(by_id(doc, 'pi.health')['status'], 'UNKNOWN')

    def test_a_clock_behind_the_last_deploy_fails(self):
        doc = preflight.run(FakeProbes(clock={'synchronized': False, 'now': datetime(2026, 1, 1, tzinfo=timezone.utc)}),
                            wifi_gate=gate())
        self.assertEqual(by_id(doc, 'pi.clock')['status'], 'FAIL')

    def test_package_verify_problems_fail(self):
        rows = [{'id': 'hello', 'version': '1.0.0', 'ok': True, 'problems': []},
                {'id': 'tanks', 'version': '0.1.0', 'ok': False, 'problems': ['tanks: server.py differs from the record']}]
        doc = run(FakeProbes(packages=(rows, ['bad.json: not a record'], None), node=(False, ['binary changed'])))
        self.assertEqual(by_id(doc, 'packages.hello')['status'], 'PASS')
        self.assertIn('differs', by_id(doc, 'packages.tanks')['reason'])
        self.assertEqual(by_id(doc, 'packages.refused')['status'], 'FAIL')
        self.assertEqual(by_id(doc, 'runtime.node')['status'], 'FAIL')
        self.assertEqual(doc['verdict'], 'NOT_READY')

    def test_package_listing_failure_is_unknown(self):
        doc = run(FakeProbes(packages=(None, None, 'Permission denied')))
        self.assertEqual(by_id(doc, 'packages.installed')['status'], 'UNKNOWN')

    def test_runtime_prerequisites(self):
        tools = {t: True for t in preflight.REQUIRED_TOOLS}
        tools['nginx'] = False
        doc = run(FakeProbes(tools=tools, python=(3, 9, 2)))
        self.assertEqual(by_id(doc, 'runtime.python')['status'], 'FAIL')
        self.assertIn('nginx', by_id(doc, 'runtime.tools')['reason'])
        self.assertEqual(by_id(doc, 'runtime.dig')['status'], 'PASS')

    def test_topology_lines_are_consumed(self):
        doc = run(FakeProbes(topology=([('PASS', 'a'), ('FAIL', 'wlan0 not in AP mode'), ('WARN', 'w')], None)))
        c = by_id(doc, 'network.topology')
        self.assertEqual((c['status'], c['reason']), ('FAIL', 'wlan0 not in AP mode'))
        self.assertEqual(by_id(run(FakeProbes(topology=(None, 'no bash'))), 'network.topology')['status'], 'UNKNOWN')

    def test_offline_mode_is_noted(self):
        doc = run(FakeProbes(files={preflight.OFFLINE_MARK}))
        self.assertTrue(any('offline mode is ON' in n for n in doc['notes']))


class LocalMode(unittest.TestCase):
    def test_appliance_only_checks_are_unknown(self):
        doc = run(local='http://127.0.0.1:8180')
        self.assertEqual(doc['mode'], 'local')
        self.assertEqual(doc['verdict'], 'UNKNOWN')
        for category in ('tls', 'network', 'pi', 'packages', 'runtime'):
            self.assertEqual(by_id(doc, f'{category}.appliance')['status'], 'UNKNOWN')


class DnsQuery(unittest.TestCase):
    def serve(self, answer_ip):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(('127.0.0.1', 0))
        self.addCleanup(s.close)

        def reply():
            data, peer = s.recvfrom(512)
            qid = data[:2]
            question = data[12:]
            body = qid + struct.pack('>HHHHH', 0x8180, 1, 1 if answer_ip else 0, 0, 0) + question
            if answer_ip:
                body += b'\xc0\x0c' + struct.pack('>HHIH', 1, 1, 60, 4) + bytes(int(x) for x in answer_ip.split('.'))
            s.sendto(body, peer)
        threading.Thread(target=reply, daemon=True).start()
        return s.getsockname()

    def test_answer_and_no_answer(self):
        host, port = self.serve('10.42.0.1')
        with mock.patch.object(preflight.socket.socket, 'sendto',
                               lambda self, data, addr, _orig=socket.socket.sendto: _orig(self, data, (host, port) if addr[0] == '10.42.0.1' else addr)):
            self.assertEqual(preflight.dns_query('10.42.0.1', 'party.avrana.net', 2), '10.42.0.1')
        host, port = self.serve(None)
        with mock.patch.object(preflight.socket.socket, 'sendto',
                               lambda self, data, addr, _orig=socket.socket.sendto: _orig(self, data, (host, port) if addr[0] == '10.42.0.1' else addr)):
            self.assertEqual(preflight.dns_query('10.42.0.1', 'party.avrana.net', 2), '')

    def test_no_server(self):
        self.assertIsNone(preflight.dns_query('127.0.0.1', 'party.avrana.net', 0.3))


class Offline(unittest.TestCase):
    def test_the_real_probes_only_contact_loopback_and_the_party_ap(self):
        """Every outbound connection a full run would make, intercepted: none leaves the appliance."""
        seen = []

        def connect(address, *a, **k):
            seen.append(address[0])
            raise OSError('intercepted')

        def sendto(self, data, address):
            seen.append(address[0])
            raise OSError('intercepted')

        def urlopen(req, *a, **k):
            url = req.full_url if hasattr(req, 'full_url') else req
            seen.append(url.split('/')[2].split(':')[0])
            raise OSError('intercepted')

        with mock.patch('socket.create_connection', connect), mock.patch.object(socket.socket, 'sendto', sendto), \
                mock.patch('urllib.request.urlopen', urlopen), mock.patch.object(preflight.shutil, 'which', lambda t: None):
            probes = preflight.Probes(timeout=0.5)
            probes.status_doc = lambda cfg: (None, 'local')
            probes.topology = lambda: (None, 'skipped in the test')
            probes.pi_health = lambda now: (None, 'none', 'skipped in the test')
            probes.packages = lambda: (None, None, 'skipped in the test')
            doc = preflight.run(probes, wifi_gate=None, config_path='/nonexistent/party-core.json')
        self.assertTrue(seen)
        self.assertEqual(set(seen) - {'127.0.0.1', '10.42.0.1'}, set(), seen)
        self.assertEqual(doc['verdict'], 'NOT_READY')       # nothing answered: a FAIL, never a PASS


class Cli(unittest.TestCase):
    def test_main_writes_json_and_markdown_and_exits_by_verdict(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(preflight, 'run', return_value=run()) as r, \
                mock.patch('sys.stdout', new_callable=io.StringIO) as out:
            code = preflight.main(['--json', '--out', d, '--horizon-days', '5'])
            self.assertEqual(code, 0)
            self.assertEqual(r.call_args.kwargs['horizon_days'], 5)
            self.assertEqual(json.loads(out.getvalue())['verdict'], 'READY')
            self.assertEqual(sorted(p.suffix for p in Path(d).iterdir()), ['.json', '.md'])

    def test_markdown_lists_every_check(self):
        doc = run()
        md = preflight.render_markdown(doc)
        for c in doc['checks']:
            self.assertIn(f'`{c["id"]}`', md)

    def test_laptop_wrapper_quotes_the_remote_command(self):
        sys.path.insert(0, str(REPO_ROOT / 'tools'))
        try:
            import importlib
            wrapper = importlib.import_module('preflight')
        finally:
            sys.path.pop(0)
        args = mock.Mock(horizon_days=3, wifi_max_age_h=24.0, waive=['wifi.gate; rm -rf /'])
        cmd = wrapper.remote_command('/opt/avrana-party/current', args)
        self.assertTrue(cmd.startswith('cd /opt/avrana-party/current && exec python3 -m avrana.ops.preflight --json'))
        self.assertIn("'wifi.gate; rm -rf /'", cmd)


if __name__ == '__main__':
    unittest.main()
