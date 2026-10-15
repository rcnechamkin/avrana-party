"""The status document (avrana.ops.status) with fake probes, plus the live route in Party Core."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from avrana.contracts import party_games
from avrana.ops import manifest, status
from avrana.party import identity, service
from test_ops_manifest import SHA_A, SHA_B, sample
from test_party_service import HOST, BLUFF, FakeLink, Phone

NOW = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)


class FakeProbes:
    def __init__(self, checkouts=None, units=None, cert_days=90, games=None, arcade=None, web=None, nginx='match'):
        self.nginx = nginx
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

    def nginx_site(self, installed, sources):
        return self.nginx

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


class _WithRecord:
    """Real certificate/record reading with every other probe faked."""
    def __init__(self, real):
        self.real, self.fake = real, FakeProbes()

    def __getattr__(self, name):
        return getattr(self.fake, name)

    def certificate_not_after(self, path):
        return self.real.certificate_not_after(path)


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

    def test_an_optional_unit_that_is_not_installed_is_a_note_not_a_fault(self):
        manifest.write(self.manifest, sample())
        timer = 'avrana-party-certificate.timer'
        cfg = dict(self.cfg, units=['nginx', timer])
        both = {'/p': checkout(SHA_A), '/g': checkout(SHA_B, ref=None, path='/g')}
        doc = status.build_status(cfg, FakeProbes(both, units={timer: 'not-installed'}), now=NOW)
        self.assertEqual(doc['services'][timer], 'not-installed')
        self.assertEqual(doc['summary']['state'], 'ok', doc['summary'])
        self.assertIn(f'{timer} is not installed (optional)', doc['summary']['notes'])
        # installed and stopped, or a required unit that is missing, degrades as before
        doc = status.build_status(cfg, FakeProbes(both, units={timer: 'inactive'}), now=NOW)
        self.assertEqual(doc['summary']['reasons'], [f'{timer} is inactive'])
        doc = status.build_status(cfg, FakeProbes(both, units={'nginx': 'not-installed'}), now=NOW)
        self.assertEqual((doc['summary']['state'], doc['summary']['reasons']), ('degraded', ['nginx is not installed']))

    def test_paths_the_service_user_may_not_look_at_are_unavailable_not_a_crash(self):
        '''On the appliance the certificate directory is root-only: stat raises PermissionError
        (found on the Pi 2026-10-04, where it took /party/api/status down with a 502).'''
        probes = status.Probes()
        with mock.patch.object(Path, 'exists', side_effect=PermissionError(13, 'Permission denied')):
            self.assertIsNone(probes.certificate_not_after('/etc/avrana-party/tls/current/fullchain.pem'))
            self.assertIsNone(probes.checkout('/home/cody/avrana-party'))
            self.assertIsNone(probes.web_release('/var/www/avrana-party/web'))
            with self.assertRaises(manifest.ManifestError):
                manifest.read(self.manifest)
            doc = status.build_status(dict(self.cfg, certificate='/x/fullchain.pem', web_root='/w'), probes, now=NOW)
        self.assertEqual(doc['certificate']['status'], 'unavailable')
        self.assertEqual(doc['manifest_error'], 'deployment manifest: unreadable (PermissionError)')

    def test_an_unreadable_certificate_is_never_ok(self):
        """AVR-31: the live appliance (Party c59f1c8) answered certificate `unavailable` with
        summary `ok` while the served certificate was 75 days from its end. The service user cannot
        read the root-only certificate directory, and nothing said so."""
        manifest.write(self.manifest, sample())
        both = {'/p': checkout(SHA_A), '/g': checkout(SHA_B, ref=None, path='/g')}
        doc = self.build(FakeProbes(both, cert_days=None))
        self.assertEqual(doc['certificate'], {'not_after': None, 'days_left': None, 'status': 'unavailable'})
        self.assertEqual(doc['summary']['state'], 'unknown')
        self.assertEqual(doc['summary']['reasons'], ['certificate expiry unavailable'])
        # a readable certificate is still ok, an expiring or expired one still degrades
        self.assertEqual(self.build(FakeProbes(both, cert_days=60))['summary']['state'], 'ok')
        for days, word in ((5, 'expiring'), (-1, 'expired')):
            doc = self.build(FakeProbes(both, cert_days=days))
            self.assertEqual((doc['summary']['state'], doc['summary']['reasons']),
                             ('degraded', [f'certificate {word}']))

    def test_the_installers_expiry_record_stands_in_for_the_root_only_certificate(self):
        record = Path(self.temp.name) / 'certificate-not-after'
        record.write_text('notAfter=Dec 25 10:00:00 2026 GMT\n', encoding='ascii')
        probes = status.Probes(certificate_record=str(record))
        want = datetime(2026, 12, 25, 10, 0, tzinfo=timezone.utc)
        # the certificate itself is out of reach (the service user), so the record answers
        with mock.patch.object(Path, 'exists', side_effect=PermissionError(13, 'Permission denied')):
            self.assertEqual(probes.certificate_not_after('/etc/avrana-party/tls/current/fullchain.pem'), want)
        doc = status.build_status(dict(self.cfg, certificate='/nowhere/fullchain.pem'),
                                  _WithRecord(probes), now=NOW)
        self.assertEqual(doc['certificate']['status'], 'ok')
        self.assertEqual(doc['certificate']['not_after'], '2026-12-25T10:00:00Z')
        # no record, a garbled one, or the wrong thing in it: unavailable, never a crash or a guess
        for text in (None, '', 'notAfter=tomorrow', 'garbage', 'notAfter'):
            if text is None:
                record.unlink()
            else:
                record.write_text(text, encoding='ascii')
            self.assertIsNone(probes.certificate_not_after('/nowhere/fullchain.pem'), text)
        self.assertNotIn(str(record), json.dumps(doc))                 # no filesystem path in public

    def test_malformed_manifest_is_reported_not_hidden(self):
        self.manifest.write_text('{"schema": "avrana.deployment/v0"}')
        doc = self.build(FakeProbes())
        self.assertIsNone(doc['deployment'])
        self.assertIn('deployed_at', doc['manifest_error'])
        self.assertNotIn(str(self.manifest), doc['manifest_error'])     # no filesystem path in public
        self.assertNotIn(str(self.manifest.parent), json.dumps(doc))
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

    def test_web_build_from_another_commit_degrades(self):
        manifest.write(self.manifest, sample())
        probes = FakeProbes({'/p': checkout(SHA_A), '/g': checkout(SHA_B)},
                            web={'path': '/w', 'build': 'b', 'commit': SHA_B})
        doc = self.build(probes)
        self.assertEqual(doc['summary']['state'], 'degraded')
        self.assertIn('web build is from a different commit than the deployed Party', doc['summary']['reasons'])
        probes.web = {'path': '/w', 'build': 'b', 'commit': SHA_A}
        self.assertEqual(self.build(probes)['summary']['state'], 'ok')

    def test_nginx_site_drift_degrades_and_unreadable_is_unknown(self):
        manifest.write(self.manifest, sample())
        probes = FakeProbes({'/p': checkout(SHA_A), '/g': checkout(SHA_B)}, nginx='differs')
        doc = self.build(probes)
        self.assertEqual(doc['nginx_site'], {'status': 'differs', 'sha256': None})
        self.assertEqual(doc['summary']['state'], 'degraded')
        self.assertTrue(any(r.startswith('nginx site file differs') for r in doc['summary']['reasons']))
        probes.nginx = 'unavailable'
        self.assertEqual(self.build(probes)['summary']['state'], 'unknown')
        probes.nginx = 'match'
        self.assertEqual(self.build(probes)['summary']['state'], 'ok')

    def test_a_last_attempt_that_did_not_end_ok_is_a_note_not_a_fault(self):
        attempt = {'party_sha': SHA_B, 'games_sha': SHA_A, 'at': '2026-10-12T00:00:00Z', 'outcome': 'rolled-back',
                   'backup': 'deploy-20261012T000000Z'}
        manifest.write(self.manifest, sample(last_attempt=attempt))
        probes = FakeProbes({'/p': checkout(SHA_A), '/g': checkout(SHA_B)})
        doc = self.build(probes)
        self.assertEqual(doc['last_attempt'], attempt)
        self.assertEqual(doc['summary']['state'], 'ok')                         # the machine runs the good pair
        self.assertTrue(any('ended rolled-back' in n for n in doc['summary']['notes']), doc['summary'])
        manifest.write(self.manifest, sample(last_attempt=dict(attempt, outcome='ok')))
        doc = self.build(probes)
        self.assertEqual(doc['last_attempt']['outcome'], 'ok')
        self.assertFalse(any('last deployment attempt' in n for n in doc['summary']['notes']))
        manifest.write(self.manifest, sample())                                 # an old manifest without the field
        self.assertIsNone(self.build(probes)['last_attempt'])

    def test_the_installed_site_hash_and_the_last_known_good_are_reported_additively(self):
        manifest.write(self.manifest, sample())
        probes = FakeProbes({'/p': checkout(SHA_A), '/g': checkout(SHA_B)})
        self.assertIsNone(self.build(probes)['last_known_good'])
        probes.nginx_site_sha256 = lambda path: 'ab' * 32
        probes.last_known_good = lambda path: {'party_sha': SHA_A, 'games_sha': SHA_B, 'smoke_at': '2026-10-12T00:00:00Z',
                                               'recorded_at': '2026-10-12T00:00:01Z', 'nginx_site_sha256': 'ab' * 32,
                                               'web_release': {'build': 'x'}, 'seeded_from_running_deployment': True}
        doc = self.build(probes)
        self.assertEqual(doc['nginx_site'], {'status': 'match', 'sha256': 'ab' * 32})
        self.assertEqual(doc['last_known_good'], {'party_sha': SHA_A, 'games_sha': SHA_B, 'smoke_at': '2026-10-12T00:00:00Z',
                                                  'recorded_at': '2026-10-12T00:00:01Z', 'nginx_site_sha256': 'ab' * 32})
        self.assertEqual(doc['summary']['state'], 'ok')                    # informational: never a fault by itself

    def test_the_real_probes_read_the_site_hash_and_the_record_beside_the_manifest(self):
        import hashlib
        root = Path(self.temp.name)
        site = root / 'site'
        site.write_text('server {}')
        self.assertEqual(status.Probes().nginx_site_sha256(site), hashlib.sha256(b'server {}').hexdigest())
        self.assertIsNone(status.Probes().nginx_site_sha256(root / 'missing'))
        record = root / 'last-known-good.json'
        self.assertIsNone(status.Probes().last_known_good(record))
        record.write_text('{"schema": "avrana.last-known-good/v0", "party_sha": "%s", "games_sha": "%s"}' % (SHA_A, SHA_B))
        self.assertEqual(status.Probes().last_known_good(record)['party_sha'], SHA_A)
        record.write_text('not json')
        self.assertIsNone(status.Probes().last_known_good(record))          # unreadable is absent, never a crash

    def test_real_probe_compares_installed_site_with_first_readable_source(self):
        root = Path(self.temp.name)
        installed, new, old = root / 'installed', root / 'new', root / 'old'
        installed.write_text('server {}')
        new.write_text('server {}')
        old.write_text('server { old }')
        probe = status.Probes().nginx_site
        self.assertEqual(probe(installed, [root / 'missing', new]), 'match')
        self.assertEqual(probe(installed, [old, new]), 'differs')        # first readable source wins
        self.assertEqual(probe(installed, [root / 'missing']), 'unavailable')
        self.assertEqual(probe(root / 'missing', [new]), 'unavailable')

    def test_first_readable_source_wins_over_a_differing_fallback(self):
        root = Path(self.temp.name)
        installed, release, home = root / 'installed', root / 'release', root / 'home'
        installed.write_text('server {}')
        release.write_text('server {}')
        home.write_text('server { other }')
        self.assertEqual(status.Probes().nginx_site(installed, [release, home]), 'match')

    def test_web_drift_without_a_manifest_compares_with_the_checkout(self):
        probes = FakeProbes({'/p': checkout(SHA_A), '/g': checkout(SHA_B)}, web={'path': '/w', 'build': 'b', 'commit': SHA_B})
        self.assertIn('web build is from a different commit than the deployed Party', self.build(probes)['summary']['reasons'])
        probes.web = {'path': '/w', 'build': 'b', 'commit': SHA_A}
        self.assertNotIn('web build is from a different commit than the deployed Party', self.build(probes)['summary']['reasons'])

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


class RecoveryProbes(FakeProbes):
    """FakeProbes plus what systemd's own recovery did (AVR-33)."""

    def __init__(self, *a, recovery=None, failed=(), **k):
        super().__init__(*a, **k)
        self.recovery, self.failed = recovery or {}, failed

    def unit_recovery(self, unit):
        return self.recovery.get(unit, {'restarts': 0, 'result': 'success', 'active_for_s': 3600})

    def failed_units(self, pattern):
        self.pattern = pattern
        return None if self.failed is None else list(self.failed)


class FailedRecovery(unittest.TestCase):
    """Health exposes recovery that did not work (AVR-33): a crash loop, a start limit, a failed
    native game; a unit that came back is a note, so a deploy's smoke check is not failed by it."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.manifest = Path(self.temp.name) / 'deployment.json'
        manifest.write(self.manifest, sample())
        self.cfg = {'manifest': str(self.manifest), 'party_checkout': '/p', 'games_checkout': '/g',
                    'units': ['avrana-party-core', 'avranaparty-arcade', 'nginx']}

    def build(self, **kw):
        probes = RecoveryProbes({'/p': checkout(SHA_A), '/g': checkout(SHA_B, ref=None, path='/g')}, **kw)
        return status.build_status(self.cfg, probes, now=NOW), probes

    def test_a_healthy_appliance_stays_ok_and_reports_zero_restarts(self):
        doc, probes = self.build()
        self.assertEqual(doc['summary'], {'state': 'ok', 'reasons': [], 'notes': []})
        self.assertEqual(doc['recovery']['units']['nginx'], {'restarts': 0, 'result': 'success', 'active_for_s': 3600})
        self.assertEqual(doc['recovery']['failed_game_units'], [])
        self.assertEqual(probes.pattern, 'avrana-game@*')

    def test_a_crash_loop_that_never_reaches_the_start_limit_degrades(self):
        doc, _ = self.build(units={'avranaparty-arcade': 'activating'},
                            recovery={'avranaparty-arcade': {'restarts': 7, 'result': 'exit-code'}})
        self.assertEqual(doc['summary']['state'], 'degraded')
        self.assertIn('avranaparty-arcade is restarting after failures (7 automatic restarts)', doc['summary']['reasons'])

    def test_a_unit_that_is_merely_starting_is_not_a_fault(self):
        doc, _ = self.build(units={'nginx': 'activating'})
        self.assertEqual(doc['summary']['state'], 'ok')

    def test_a_start_limit_is_named_with_where_to_look(self):
        doc, _ = self.build(units={'avranaparty-arcade': 'failed'},
                            recovery={'avranaparty-arcade': {'restarts': 4, 'result': 'start-limit-hit'}})
        reasons = doc['summary']['reasons']
        self.assertIn('avranaparty-arcade is failed', reasons)
        self.assertIn('avranaparty-arcade stopped restarting (start limit hit); see docs/runbooks/service-recovery.md',
                      reasons)

    def test_a_unit_that_came_back_and_stayed_up_is_a_note_not_a_fault(self):
        doc, _ = self.build(recovery={'avrana-party-core': {'restarts': 2, 'result': 'success', 'active_for_s': 900}})
        self.assertEqual(doc['summary']['state'], 'ok')
        self.assertEqual(doc['summary']['notes'],
                         ['avrana-party-core came back after 2 automatic restart(s) since it was last started'])

    def test_a_crash_loop_sampled_while_active_degrades(self):
        """Crashing every ~2 s under RestartSec=3 is often seen `active`: up for seconds, restarts > 0."""
        doc, _ = self.build(recovery={'avranaparty-arcade': {'restarts': 5, 'result': 'success', 'active_for_s': 1}})
        self.assertEqual(doc['summary']['state'], 'degraded')
        self.assertIn('avranaparty-arcade restarted recently after failures (5 automatic restarts, up 1 s)',
                      doc['summary']['reasons'])
        self.assertEqual(doc['summary']['notes'], [])

    def test_restarted_just_under_the_window_degrades_and_at_it_is_a_note(self):
        doc, _ = self.build(recovery={'nginx': {'restarts': 1, 'result': 'success',
                                                'active_for_s': status.RECENT_RESTART_S - 1}})
        self.assertEqual(doc['summary']['state'], 'degraded')
        doc, _ = self.build(recovery={'nginx': {'restarts': 1, 'result': 'success',
                                                'active_for_s': status.RECENT_RESTART_S}})
        self.assertEqual(doc['summary']['state'], 'ok')

    def test_restarts_with_an_unreadable_uptime_fail_safe_as_degraded(self):
        for facts in ({'restarts': 2, 'result': 'success'}, {'restarts': 2, 'result': 'success', 'active_for_s': None},
                      {'restarts': 2, 'result': 'success', 'active_for_s': 'soon'}):
            doc, _ = self.build(recovery={'avrana-party-core': facts})
            self.assertEqual(doc['summary']['state'], 'degraded', facts)
            self.assertIn('avrana-party-core restarted recently after failures (2 automatic restarts, uptime unreadable)',
                          doc['summary']['reasons'])

    def test_no_restarts_never_needs_an_uptime(self):
        doc, _ = self.build(recovery={'nginx': {'restarts': 0, 'result': 'success', 'active_for_s': None}})
        self.assertEqual(doc['summary']['state'], 'ok')

    CHECKERS = ['avrana-game@checkers.service', 'avrana-game@checkers.socket']

    def build_in_session(self, game, state='active', **kw):
        probes = RecoveryProbes({'/p': checkout(SHA_A), '/g': checkout(SHA_B, ref=None, path='/g')}, **kw)
        core = lambda: {'uptime_s': 5, 'members': 2, 'session': {'game': game, 'state': state} if game else None}
        return status.build_status(self.cfg, probes, core, now=NOW)

    def test_a_stale_failed_game_with_no_session_is_a_note_and_the_status_smoke_passes(self):
        from avrana.ops import smoke
        doc = self.build_in_session(None, failed=self.CHECKERS)
        self.assertEqual(doc['summary']['state'], 'ok')
        self.assertEqual(doc['summary']['reasons'], [])
        self.assertEqual(doc['recovery']['failed_game_units'], self.CHECKERS)
        self.assertEqual(len(doc['summary']['notes']), 2)
        self.assertIn('sudo systemctl reset-failed avrana-game@checkers.socket', doc['summary']['notes'][1])
        self.assertIn('docs/runbooks/service-recovery.md', doc['summary']['notes'][1])

        class Http:
            def get(self, *a, **k):
                return 200, {}, json.dumps(doc).encode()
        self.assertEqual(smoke.check_status(Http(), 'https', '127.0.0.1', 443, 'h').status, smoke.PASS,
                         'a failed game unit that existed before a deploy cannot roll it back')

    def test_a_failed_unit_of_the_live_sessions_game_degrades(self):
        for state in ('launching', 'active', 'ending', 'setup'):
            doc = self.build_in_session('checkers', state, failed=self.CHECKERS)
            self.assertEqual(doc['summary']['state'], 'degraded', state)
            self.assertIn('avrana-game@checkers.socket is failed and its game is in the live session; '
                          'see docs/runbooks/service-recovery.md', doc['summary']['reasons'])

    def test_a_failed_unit_of_another_game_during_a_session_is_a_note(self):
        doc = self.build_in_session('bluff', failed=self.CHECKERS)
        self.assertEqual(doc['summary']['state'], 'ok')
        self.assertEqual(doc['summary']['reasons'], [])
        self.assertEqual(len(doc['summary']['notes']), 2)

    def test_an_ended_session_no_longer_makes_its_game_meaningful(self):
        doc = self.build_in_session('checkers', 'ended', failed=self.CHECKERS)
        self.assertEqual(doc['summary']['state'], 'ok')

    def test_unobservable_failures_are_unknown_only_while_a_session_is_live(self):
        self.assertEqual(self.build_in_session('checkers', failed=None)['summary']['state'], 'unknown')
        for game in (None,):
            doc = self.build_in_session(game, failed=None)
            self.assertEqual(doc['summary']['state'], 'ok')
            self.assertIsNone(doc['recovery']['failed_game_units'])
        self.assertEqual(self.build_in_session('checkers', 'ended', failed=None)['summary']['state'], 'ok')

    def test_a_failed_native_game_or_its_socket_of_the_live_session_names_only_that_game(self):
        doc = self.build_in_session('checkers', failed=['avrana-game@checkers.service', 'avrana-game@checkers.socket'])
        self.assertEqual(doc['summary']['state'], 'degraded')
        self.assertEqual(doc['recovery']['failed_game_units'],
                         ['avrana-game@checkers.service', 'avrana-game@checkers.socket'])
        self.assertIn('avrana-game@checkers.socket is failed and its game is in the live session; '
                      'see docs/runbooks/service-recovery.md', doc['summary']['reasons'])
        self.assertEqual(doc['services'], {'avrana-party-core': 'active', 'avranaparty-arcade': 'active',
                                           'nginx': 'active'}, 'the other services are untouched')

    def test_without_a_party_core_view_unobservable_game_units_do_not_by_themselves_make_it_unknown(self):
        doc, _ = self.build(failed=None)
        self.assertEqual(doc['summary']['state'], 'ok')

    def test_an_uninstalled_unit_is_not_asked_about(self):
        doc, _ = self.build(units={'nginx': 'not-installed'})
        self.assertNotIn('nginx', doc['recovery']['units'])


class RecoveryProbeParsing(unittest.TestCase):
    """The real probes against a scripted `systemctl` (no systemd needed)."""

    def run_with(self, stdout, returncode=0):
        calls = []

        def runner(argv, capture_output, timeout):
            calls.append(argv)
            return mock.Mock(stdout=stdout.encode(), returncode=returncode)
        return runner, calls

    def test_nrestarts_and_result_are_read(self):
        runner, calls = self.run_with('NRestarts=3\nResult=start-limit-hit\n')
        with mock.patch.object(status.platform, 'system', return_value='Linux'):
            self.assertEqual(status.unit_recovery('avranaparty-arcade', runner=runner),
                             {'restarts': 3, 'result': 'start-limit-hit', 'active_for_s': None})
        self.assertEqual(calls[0][:2], ['systemctl', 'show'])
        self.assertIn('--property=ActiveEnterTimestampMonotonic', calls[0])

    def test_active_for_is_monotonic_now_minus_the_microsecond_enter_timestamp(self):
        runner, _ = self.run_with('NRestarts=4\nResult=success\nActiveEnterTimestampMonotonic=5000000000\n')
        with mock.patch.object(status.platform, 'system', return_value='Linux'):
            facts = status.unit_recovery('x', runner=runner, clock=lambda: 5002.5)
        self.assertEqual(facts, {'restarts': 4, 'result': 'success', 'active_for_s': 2})

    def test_an_unparseable_or_zero_enter_timestamp_is_none_not_a_crash(self):
        for value in ('', 'n/a', '0', '-3'):
            runner, _ = self.run_with(f'NRestarts=1\nResult=success\nActiveEnterTimestampMonotonic={value}\n')
            with mock.patch.object(status.platform, 'system', return_value='Linux'):
                self.assertIsNone(status.unit_recovery('x', runner=runner, clock=lambda: 100.0)['active_for_s'], value)

    def test_unreadable_output_or_no_systemd_is_none(self):
        runner, _ = self.run_with('')
        with mock.patch.object(status.platform, 'system', return_value='Linux'):
            self.assertIsNone(status.unit_recovery('x', runner=runner))
        with mock.patch.object(status.platform, 'system', return_value='Windows'):
            self.assertIsNone(status.unit_recovery('x'))
            self.assertIsNone(status.failed_units('avrana-game@*'))

    def test_failed_units_are_listed_by_name(self):
        out = ('avrana-game@checkers.service loaded failed failed Avrana native game (checkers)\n'
               'avrana-game@checkers.socket  loaded failed failed Avrana native game socket (checkers)\n')
        runner, calls = self.run_with(out)
        with mock.patch.object(status.platform, 'system', return_value='Linux'):
            self.assertEqual(status.failed_units('avrana-game@*', runner=runner),
                             ['avrana-game@checkers.service', 'avrana-game@checkers.socket'])
            self.assertEqual(status.failed_units('avrana-game@*', runner=self.run_with('')[0]), [])
            self.assertIsNone(status.failed_units('avrana-game@*', runner=self.run_with('', returncode=1)[0]))
        self.assertIn('--state=failed', calls[0])


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
