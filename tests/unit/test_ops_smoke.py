"""Smoke checks (avrana.ops.smoke): scripted HTTP, and the real local subset against the dev server."""
from datetime import datetime, timedelta, timezone
import json
import os
import subprocess
import sys
import threading
import unittest

from avrana.ops import smoke, status
from avrana.web import devserver

NOW = datetime(2026, 10, 3, tzinfo=timezone.utc)


class ScriptedHttp:
    """(address, port, path) -> (status, headers, body) or an OSError to raise."""

    def __init__(self, table):
        self.table = table
        self.calls = []

    def get(self, scheme, address, port, path, host=None, verify=True):
        self.calls.append((scheme, address, port, path, host))
        answer = self.table.get((port, path))
        if answer is None:
            raise ConnectionRefusedError('scripted: nothing listening')
        if isinstance(answer, Exception):
            raise answer
        return answer


def ok_json(doc):
    return 200, {}, json.dumps(doc).encode()


def healthy_table():
    status_doc = {'schema': status.SCHEMA, 'summary': {'state': 'ok', 'reasons': []},
                  'contract': {'party_games': 'avrana.party-games/v0'}, 'party': {'checkout_sha': 'a' * 40}}
    return {
        (80, '/hotspot-detect.html'): (200, {}, b'Success'),
        (443, '/party/'): (200, {'Content-Security-Policy': "default-src 'self'"}, b'<!doctype html><html>'),
        (443, '/party/api/state'): ok_json({'party': {}, 'me': None}),
        (443, '/party/api/status'): ok_json(status_doc),
        (8096, '/health'): ok_json({'ok': True}),
        (8096, '/api/games'): ok_json({'avranaIntegration': 'avrana.lan-launch/v1', 'games': []}),
        (8098, '/stats'): ok_json({'players': 0, 'state': 'idle', 'error': None, 'emulator_running': False}),
    }


class Checks(unittest.TestCase):
    def names(self, results):
        return {r.name: r.status for r in results}

    def test_healthy_pi_passes_everything_it_can_see(self):
        http = ScriptedHttp(healthy_table())
        probes = type('P', (), {'certificate_not_after': lambda self, p: NOW + timedelta(days=80)})()
        results = smoke.run_pi(http, probes, units=[], resolver=lambda server, name: server)
        by = self.names(results)
        for name in ('captive_probe', 'party_home', 'party_core', 'status', 'games_provider', 'arcade'):
            self.assertEqual(by[name], smoke.PASS, name)
        self.assertEqual(by['encoder'], smoke.SKIP)         # emulator idle: nothing to encode
        self.assertEqual(by['dns'], smoke.PASS)
        self.assertEqual(by['certificate'], smoke.PASS)
        # HTTPS checks speak to the Pi's loopback but validate the party host name (SNI/Host).
        self.assertIn(('https', '127.0.0.1', 443, '/party/', smoke.HOST), http.calls)

    def test_every_failure_mode_is_named(self):
        table = healthy_table()
        table[(80, '/hotspot-detect.html')] = (200, {}, b'<html>captive portal</html>')
        table[(443, '/party/')] = (200, {}, b'<!doctype html><html>')    # no CSP
        table[(443, '/party/api/state')] = (502, {}, b'bad gateway')
        table[(8096, '/api/games')] = ok_json({'avranaIntegration': 'avrana.lan-launch/v2'})
        table[(8098, '/stats')] = ok_json({'players': 0, 'error': 'encoder died', 'emulator_running': True,
                                           'sample_age_s': {'video': 42.0}})
        del table[(443, '/party/api/status')]
        results = smoke.run_pi(ScriptedHttp(table), type('P', (), {'certificate_not_after': lambda s, p: NOW})(), units=[],
                               resolver=lambda server, name: None)
        by = {r.name: r for r in results}
        self.assertEqual(by['captive_probe'].status, smoke.FAIL)
        self.assertIn('Success', by['captive_probe'].detail)
        self.assertEqual(by['party_home'].status, smoke.FAIL)
        self.assertIn('Content-Security-Policy', by['party_home'].detail)
        self.assertEqual(by['party_core'].status, smoke.FAIL)
        self.assertEqual(by['status'].status, smoke.FAIL)
        self.assertIn('unreachable', by['status'].detail)
        self.assertEqual(by['games_provider'].status, smoke.FAIL)
        self.assertIn('lan-launch/v2', by['games_provider'].detail)
        self.assertEqual(by['arcade'].status, smoke.FAIL)
        self.assertEqual(by['encoder'].status, smoke.FAIL)
        self.assertEqual(by['certificate'].status, smoke.FAIL)
        self.assertEqual(by['dns'].status, smoke.SKIP)                 # no answer at all: not run, not passed
        self.assertFalse(smoke.summarize(results)['ok'])

    def test_dig_output_is_parsed_for_addresses_only(self):
        def fake(stdout, code):
            return lambda *a, **k: subprocess.CompletedProcess(a, code, stdout=stdout)
        original = smoke.subprocess.run
        try:
            smoke.subprocess.run = fake(b'10.42.0.1\n', 0)
            self.assertEqual(smoke._dig('10.42.0.1', smoke.HOST), '10.42.0.1')
            smoke.subprocess.run = fake(b';; communications error to 10.42.0.1#53: timed out\n', 9)
            self.assertIsNone(smoke._dig('10.42.0.1', smoke.HOST))
            smoke.subprocess.run = fake(b'', 0)
            self.assertEqual(smoke._dig('10.42.0.1', smoke.HOST), '')
        finally:
            smoke.subprocess.run = original

    def test_degraded_status_fails_with_its_reasons(self):
        table = healthy_table()
        table[(443, '/party/api/status')] = ok_json({'schema': status.SCHEMA, 'contract': {'party_games': 'avrana.party-games/v0'},
                                                     'summary': {'state': 'degraded', 'reasons': ['nginx is failed']}, 'party': {}})
        r = smoke.check_status(ScriptedHttp(table), 'https', '127.0.0.1', 443, smoke.HOST)
        self.assertEqual(r.status, smoke.FAIL)
        self.assertIn('nginx is failed', r.detail)

    def test_units_and_dns_with_fakes(self):
        def runner(cmd, **kw):
            state = {'nginx': b'active\n', 'avrana-party-core': b'failed\n'}[cmd[-1]]
            return subprocess.CompletedProcess(cmd, 0, stdout=state)
        results = smoke.check_units(['nginx', 'avrana-party-core'], runner)
        if sys.platform != 'linux':
            self.assertTrue(all(r.status == smoke.SKIP for r in results))
        else:
            self.assertEqual([r.status for r in results], [smoke.PASS, smoke.FAIL])
        self.assertEqual(smoke.check_dns(resolver=lambda s, n: '10.42.0.1').status, smoke.PASS)
        self.assertEqual(smoke.check_dns(resolver=lambda s, n: '93.184.216.34').status, smoke.FAIL)
        self.assertEqual(smoke.check_dns(resolver=lambda s, n: None).status, smoke.SKIP)

    def test_summary_counts_skips_separately(self):
        s = smoke.summarize([smoke.Result('a', smoke.PASS), smoke.Result('b', smoke.SKIP)])
        self.assertTrue(s['ok'])
        self.assertEqual(s['counts'], {'pass': 1, 'fail': 0, 'skip': 1})


class LocalSubset(unittest.TestCase):
    """The real `--local` subset against the dev server with a real simulated Party Core."""

    @classmethod
    def setUpClass(cls):
        cls.server = devserver.make_server(0, test_controls=True, party=True)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.cfg['party'].close()
        cls.server.server_close()

    def test_local_run_passes(self):
        results = smoke.run_local(f'http://127.0.0.1:{self.port}')
        by = {r.name: r for r in results}
        self.assertEqual({n: r.status for n, r in by.items()},
                         {'captive_probe': smoke.PASS, 'party_home': smoke.PASS, 'party_core': smoke.PASS,
                          'status': smoke.PASS}, {n: r.detail for n, r in by.items()})

    def test_cli_exit_codes(self):
        python = 'python' if os.name == 'nt' else 'python3'
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        good = subprocess.run([python, '-m', 'avrana.ops.smoke', '--local', f'http://127.0.0.1:{self.port}', '--json'],
                              capture_output=True, text=True, cwd=root)
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
        self.assertTrue(json.loads(good.stdout)['ok'])
        bad = subprocess.run([python, '-m', 'avrana.ops.smoke', '--local', 'http://127.0.0.1:1'],
                             capture_output=True, text=True, cwd=root)
        self.assertEqual(bad.returncode, 1)
        self.assertIn('FAIL', bad.stdout)


if __name__ == '__main__':
    unittest.main()
