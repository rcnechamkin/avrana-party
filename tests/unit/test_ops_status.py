"""The status document (avrana.ops.status) with fake probes, plus the live route in Party Core."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import threading
import unittest

from avrana.contracts import party_games
from avrana.ops import manifest, status
from avrana.party import identity, service
from test_ops_manifest import SHA_A, SHA_B, sample
from test_party_service import HOST, BLUFF, FakeLink, Phone

NOW = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)


class FakeProbes:
    def __init__(self, checkouts=None, units=None, cert_days=90, games=None, arcade=None, web=None):
        self.checkouts = checkouts or {}
        self.units = units or {}
        self.cert_days = cert_days
        self.games_doc = games if games is not None else {'avranaIntegration': 'avrana.lan-launch/v1', 'games': []}
        self.arcade_doc = arcade if arcade is not None else {'players': 0, 'max_players': 2, 'state': 'idle',
                                                              'party_managed': True, 'emulator_running': False,
                                                              'error': None, 'sample_age_s': {}}
        self.web = web

    def checkout(self, path):
        return self.checkouts.get(str(path))

    def web_release(self, root):
        return self.web

    def unit_state(self, unit):
        return self.units.get(unit, 'active')

    def certificate_not_after(self, path):
        return None if self.cert_days is None else NOW + timedelta(days=self.cert_days)

    def get_json(self, url):
        if url.endswith('/api/games'):
            return self.games_doc
        if url.endswith('/stats'):
            return self.arcade_doc
        return None


def checkout(sha, dirty=False, ref='main', path='/p', untracked=0):
    return {'sha': sha, 'short': sha[:12], 'dirty': dirty, 'untracked': untracked, 'ref': ref, 'checkout': path}


class Document(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.manifest = Path(self.temp.name) / 'deployment.json'
        self.cfg = {'manifest': str(self.manifest), 'party_checkout': '/p', 'games_checkout': '/g',
                    'units': ['avrana-party-core', 'nginx']}

    def build(self, probes, **over):
        return status.build_status(dict(self.cfg, **over), probes, now=NOW)

    def test_healthy_deployment_is_ok_and_names_the_build(self):
        manifest.write(self.manifest, sample())
        probes = FakeProbes({'/p': checkout(SHA_A), '/g': checkout(SHA_B, ref=None, path='/g')})
        doc = self.build(probes)
        self.assertEqual(doc['schema'], status.SCHEMA)
        self.assertEqual(doc['summary'], {'state': 'ok', 'reasons': [], 'notes': []})
        self.assertEqual(doc['party'], {'deployed_sha': SHA_A, 'checkout_sha': SHA_A, 'dirty': False,
                                        'untracked': 0, 'deployed_dirty': False, 'ref': 'main', 'mismatch': False})
        self.assertEqual(doc['contract']['party_games'], party_games.versions()['party_games'])
        self.assertEqual(doc['contract']['games_advertises'], 'avrana.lan-launch/v1')
        self.assertEqual(doc['certificate']['status'], 'ok')
        self.assertEqual(doc['services'], {'avrana-party-core': 'active', 'nginx': 'active'})
        self.assertEqual(doc['deployment']['party']['sha'], SHA_A)

    def test_no_manifest_is_unknown_not_ok(self):
        doc = self.build(FakeProbes({'/p': checkout(SHA_A), '/g': checkout(SHA_B)}))
        self.assertIsNone(doc['deployment'])
        self.assertEqual(doc['summary']['state'], 'unknown')
        self.assertIn('no deployment manifest', doc['summary']['reasons'])
        self.assertEqual(doc['party']['checkout_sha'], SHA_A)  # still answers what is on disk

    def test_mismatch_dirty_failed_unit_and_expiring_certificate_degrade(self):
        manifest.write(self.manifest, sample())
        probes = FakeProbes({'/p': checkout('c' * 40, dirty=True), '/g': checkout(SHA_B)},
                            units={'nginx': 'failed'}, cert_days=3)
        doc = self.build(probes)
        self.assertTrue(doc['party']['mismatch'])
        self.assertEqual(doc['summary']['state'], 'degraded')
        for reason in ('party checkout differs from the deployment manifest', 'party checkout is dirty',
                       'nginx is failed', 'certificate expiring'):
            self.assertIn(reason, doc['summary']['reasons'])

    def test_malformed_manifest_is_reported_not_hidden(self):
        self.manifest.write_text('{"schema": "avrana.deployment/v0"}')
        doc = self.build(FakeProbes())
        self.assertIsNone(doc['deployment'])
        self.assertIn('deployed_at', doc['manifest_error'])
        self.assertIn('deployment manifest malformed', doc['summary']['reasons'])
        self.assertEqual(doc['summary']['state'], 'degraded')

    def test_unreachable_providers_and_unavailable_systemd(self):
        manifest.write(self.manifest, sample())
        probes = FakeProbes({'/p': checkout(SHA_A), '/g': checkout(SHA_B)}, games=False, arcade=False,
                            units={'avrana-party-core': 'unavailable', 'nginx': 'unavailable'}, cert_days=None)
        probes.games_doc, probes.arcade_doc = None, None
        doc = self.build(probes)
        self.assertFalse(doc['games_provider']['ok'])
        self.assertFalse(doc['arcade']['ok'])
        self.assertEqual(doc['certificate']['status'], 'unavailable')
        self.assertEqual(doc['summary']['state'], 'degraded')
        self.assertIn('games provider unreachable', doc['summary']['reasons'])

    def test_incompatible_games_advertisement_is_named(self):
        manifest.write(self.manifest, sample())
        probes = FakeProbes({'/p': checkout(SHA_A), '/g': checkout(SHA_B)}, games={'avranaIntegration': 'avrana.lan-launch/v9'})
        doc = self.build(probes)
        self.assertIs(doc['games_provider']['compatible'], False)
        self.assertIn('games provider advertises a different launch integration', doc['summary']['reasons'])

    def test_no_secrets_or_peer_addresses_leak(self):
        manifest.write(self.manifest, sample())
        probes = FakeProbes({'/p': checkout(SHA_A), '/g': checkout(SHA_B)},
                            arcade={'players': 1, 'error': None, 'peers': [{'addr': '10.42.0.7'}], 'sample_age_s': {'video': 0.1}})
        probes.web = {'path': '/var/www/avrana-party/web/releases/x', 'build': 'b', 'commit': SHA_A}
        doc = self.build(probes)
        text = json.dumps(doc)
        for forbidden in ('10.42.0.7', 'peers', 'privkey', 'token', 'cookie', '/var/www', '/w/releases',
                          '"checkout"', 'deployed_by', 'cody'):
            self.assertNotIn(forbidden, text)
        self.assertEqual(doc['web_release'], {'build': 'b', 'commit': SHA_A})
        self.assertEqual(doc['deployment']['party']['sha'], SHA_A)      # the build identity stays

    def test_dirty_deployment_and_untracked_files_are_reported_accurately(self):
        dirty = sample()
        dirty['games'] = dict(dirty['games'], dirty=True)
        manifest.write(self.manifest, dirty)
        probes = FakeProbes({'/p': checkout(SHA_A, untracked=2), '/g': checkout(SHA_B)})
        doc = self.build(probes)
        self.assertTrue(doc['games']['deployed_dirty'])
        self.assertFalse(doc['games']['dirty'])                         # clean now, but deployed dirty
        self.assertEqual(doc['summary']['state'], 'degraded')
        self.assertIn('games was deployed from a dirty checkout', doc['summary']['reasons'])
        self.assertEqual(doc['party']['untracked'], 2)
        self.assertIn('party checkout has 2 untracked file(s)', doc['summary']['notes'])

    def test_cache_serves_the_same_document_briefly(self):
        clock = [0.0]
        calls = []
        probes = FakeProbes({'/p': checkout(SHA_A), '/g': checkout(SHA_B)})
        original = probes.unit_state
        probes.unit_state = lambda unit: calls.append(unit) or original(unit)
        cache = status.StatusCache(self.cfg, probes, ttl=5, clock=lambda: clock[0])
        first = cache.get()
        self.assertFalse(first['cached'])
        self.assertTrue(cache.get()['cached'])
        self.assertEqual(len(calls), 2)
        clock[0] = 6
        self.assertFalse(cache.get()['cached'])
        self.assertEqual(len(calls), 4)

    def test_config_block_overrides_only_known_keys(self):
        cfg = status.load_config({'status': {'manifest': '/x/m.json', 'bogus': 1}})
        self.assertEqual(cfg['manifest'], '/x/m.json')
        self.assertNotIn('bogus', cfg)
        self.assertEqual(cfg['units'], status.DEFAULT_CONFIG['units'])


class LiveRoute(unittest.TestCase):
    """GET /party/api/status through the real HTTP handler: Host guard applies, no identity needed."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        svc = service.PartyService(identity.DeviceStore(None), service.load_games(BLUFF), FakeLink())
        cfg = service.Config({HOST}, {'https://' + HOST}, secure_cookie=False)
        probes = FakeProbes({'/p': checkout(SHA_A), '/g': checkout(SHA_B)})
        routes = status.route(svc, {'manifest': str(Path(self.temp.name) / 'none.json'),
                                    'party_checkout': '/p', 'games_checkout': '/g', 'units': []}, probes, ttl=0)
        self.server = service.make_server(svc, cfg, port=0, extra_routes=routes)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.svc = svc

    def test_anyone_on_the_right_host_reads_status(self):
        phone = Phone(self.port)
        code, doc, _ = phone.req("GET", "/party/api/status")
        self.assertEqual(code, 200)
        self.assertEqual(doc['schema'], status.SCHEMA)
        self.assertEqual(doc['party_core']['members'], 0)
        self.assertTrue(doc['party_core']['ok'])
        phone.req('POST', '/party/api/join', {'name': 'Ada'})
        self.assertEqual(phone.req('GET', '/party/api/status')[1]['party_core']['members'], 1)

    def test_wrong_host_is_refused_like_every_route(self):
        code, doc, _ = Phone(self.port, host="evil.example").req("GET", "/party/api/status")
        self.assertEqual(code, 421)


if __name__ == '__main__':
    unittest.main()
