"""Field-session diagnostics (avrana.ops.fieldsession) and its privacy rules (avrana.ops.redact).

The redaction suite plants every kind of secret and private datum the appliance could log into
realistic text and documents, and checks both halves: scrubbing removes each one, and the
validator finds each one when it was NOT scrubbed (so a scrubber regression cannot pass silently).
"""
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import random
import secrets
import string
import tarfile
import tempfile
import unittest
from unittest import mock

from avrana.ops import fieldsession as fs
from avrana.ops import redact

T0 = datetime(2026, 10, 21, 19, 0, tzinfo=timezone.utc)
PARTY = '8de7ef20835a1d98ec55cb772c216cbd348084fa'
GAMES = '1dc48d2a3b4c5d6e7f8091a2b3c4d5e6f7a8b9c0'
FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures' / 'field-session'

# One of each thing that must never leave the appliance, in the shape it would really have.
PEM = '-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\n-----END PRIVATE KEY-----'
GAME_KEY = secrets.token_hex(32)                       # ops/provision-game writes token_hex(32)
DEVICE_TOKEN = secrets.token_urlsafe(32)               # avrana.party.identity mints token_urlsafe(32)
PLANTED = {
    'pem': f'loaded key {PEM} ok',
    'game_key': f'game bluff key {GAME_KEY} rotated',
    'device_token': f'resume with {DEVICE_TOKEN}',
    'host_cookie': f'Cookie: __Host-avrana_device={DEVICE_TOKEN}; theme=dark',
    'legacy_cookie': f'sent avrana_device={DEVICE_TOKEN} over http',
    'limited_cookie': f'avrana_limited={DEVICE_TOKEN}',
    'set_cookie': f'Set-Cookie: __Host-avrana_device={DEVICE_TOKEN}; Path=/; HttpOnly',
    'authorization': 'Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl',
    'basic': 'proxy sent Basic dXNlcjpwYXNzd29yZA== to us',
    'password': 'wifi password=hunter2isnotgood configured',
    'ticket': f'ticket={secrets.token_urlsafe(24)} accepted',
    'member_id': f'member-{secrets.token_hex(16)} joined',
    'device_id': f'device-{secrets.token_hex(16)} reconnected',
    'phone_ipv4': 'request from 10.42.0.57 port 51234',
    'home_ipv4': 'upstream 192.168.1.23',
    'ipv6': 'peer fe80::1c2a:3bff:fe4d:5e6f%wlan0',
    'ipv6_full': 'peer 2001:0db8:85a3:0000:0000:8a2e:0370:7334',
    'mapped_ipv4': 'client ::ffff:10.42.0.57:51234 GET /party/',          # a dual-stack server's access log
    'mapped_ipv4_bracketed': 'peer=[::ffff:10.42.0.57]:443',
    'mac': 'station a4:83:e7:12:34:56 associated',
    'mac_bare': 'wlan0: STA a483e7123456 roamed',                          # a driver that prints no separators
    'mac_dotted': 'neighbor a483.e712.3456 learned on wlan0',
    'email': 'owner mail cody.example@example.com',
    'email_spelled': 'contact cody.example (at) example (dot) com',
    'email_bracketed': 'contact cody.example [at] example.com',
    'pin_words': 'Admin PIN 482915 accepted',
    'passcode_words': 'the passcode is 7391',
    'pin_code_hyphen': 'owner pin-code 5038 set',
    'pin_was': 'the old PIN was 6274',
    'player_name': 'player "Benjamin" took seat 2',
    'chat': 'chat from seat 2: meet me at the bar later',
}


class FakeProbes:
    def __init__(self):
        self.doc = status(PARTY, GAMES)
        self.entries = []
        self.health = {'state': 'HEALTHY', 'reasons': [], 'notes': []}
        self.throttle = []

    def status(self):
        return (self.doc, None) if self.doc is not None else (None, 'status unreachable (ConnectionRefusedError)')

    def pi_health(self):
        return self.health, None

    def throttle_lines(self):
        return self.throttle, None

    def journal(self, since, until, units):
        return self.entries, None


def status(party, games, games_state='active', reasons=(), members=3, session=None):
    return {'schema': 'avrana.status/v0', 'generated_at': '2026-10-21T19:00:00Z',
            'deployment': {'deployed_at': '2026-10-20T12:00:00Z', 'party': {'sha': party, 'short': party[:12]},
                           'games': {'sha': games, 'short': games[:12]}},
            'party': {'deployed_sha': party, 'checkout_sha': party}, 'games': {'deployed_sha': games, 'checkout_sha': games},
            'web_release': {'build': '20261020T120000Z', 'commit': party},
            'nginx_site': {'status': 'match', 'sha256': 'ab' * 32},
            'contract': {'party_games': 'avrana.party-games/v0', 'lan_launch': 'avrana.lan-launch/v1'},
            'services': {'avrana-party-core': 'active', 'avranaparty-games': games_state, 'nginx': 'active'},
            'party_core': {'ok': True, 'members': members, 'session': session},
            'summary': {'state': 'ok' if not reasons else 'degraded', 'reasons': list(reasons), 'notes': []}}


def entry(at, message, unit='avrana-party-core.service', priority=6):
    return {'__REALTIME_TIMESTAMP': str(int(at.timestamp() * 1e6)), 'MESSAGE': message, 'PRIORITY': str(priority),
            '_SYSTEMD_UNIT': unit, '_HOSTNAME': 'avrana', '_CMDLINE': 'python3 -m avrana.party.service', '_PID': '812'}


class Redaction(unittest.TestCase):
    def test_every_planted_secret_is_scrubbed_and_the_raw_one_is_caught(self):
        for kind, text in PLANTED.items():
            with self.subTest(kind):
                raw_hits = redact.violations_in_text(text, log=True)
                self.assertTrue(raw_hits, f'the validator missed raw {kind}')
                clean = redact.scrub_log_line(text) if kind == 'chat' else redact.scrub_text(text)
                if clean is None:
                    continue                                  # the whole chat line is dropped
                self.assertEqual(redact.violations_in_text(clean, log=True), [], f'{kind} survived: {clean!r}')
                for secret in (GAME_KEY, DEVICE_TOKEN, 'hunter2isnotgood', 'Benjamin', '10.42.0.57', '.0.57',
                               'a4:83:e7:12:34:56', 'a483e7123456', 'a483.e712.3456', 'cody.example', '482915', '7391', '5038', '6274'):
                    self.assertNotIn(secret, clean)

    def test_a_short_commit_a_version_or_a_count_is_not_a_mac_or_a_pin(self):
        for text in (f'deployed {PARTY[:12]} at 18:00', 'python 3.11.2', 'pinned 12345 packages', 'PIN set by the owner',
                     'Admin PIN [redacted] accepted'):
            with self.subTest(text):
                self.assertEqual(redact.scrub_text(text), text)
                self.assertEqual(redact.violations_in_text(text, log=True), [])

    def test_useful_operational_text_survives(self):
        text = ('2026-10-21T18:00:00Z avranaparty-games.service restarted at 18:00:05 on 10.42.0.1 via 127.0.0.1:8096; '
                'python 3.11.2; registry reloaded: 3 games (added bluff); HTTP 502 for /party/api/state')
        self.assertEqual(redact.scrub_text(text), text)
        self.assertEqual(redact.violations_in_text(text, log=True), [])

    def test_revisions_survive_only_at_their_own_paths(self):
        doc = {'revisions': {'party': PARTY}, 'nginx_site': {'sha256': 'ab' * 32}, 'note': f'deployed {PARTY}',
               'deployment': {'party': {'sha': PARTY, 'short': PARTY[:12]}}, 'files': {'x.json': {'sha256': 'cd' * 32}}}
        out = redact.scrub_json(doc)
        self.assertEqual((out['revisions']['party'], out['nginx_site']['sha256'], out['deployment']['party']['sha']),
                         (PARTY, 'ab' * 32, PARTY))
        self.assertNotIn(PARTY, out['note'])
        self.assertEqual(redact.violations_in_json(out), [])
        self.assertTrue(redact.violations_in_json({'note': f'key {GAME_KEY}'}))
        self.assertTrue(redact.violations_in_json({'party': GAME_KEY + 'zz'}))

    def test_a_game_key_under_a_digest_looking_key_is_still_caught(self):
        for doc in ({'sha256': GAME_KEY}, {'party': GAME_KEY}, {'commit': GAME_KEY}, {'games': [GAME_KEY]},
                    {'revisions': {'party': GAME_KEY}}, {'deployment': {'party': {'sha': GAME_KEY}}}):
            with self.subTest(doc=list(doc)):
                self.assertTrue(redact.violations_in_json(doc))
                self.assertNotIn(GAME_KEY, json.dumps(redact.scrub_json(doc)))

    def test_secret_named_fields_are_dropped_whatever_they_hold(self):
        doc = {'token': 'short', 'cookie': 'x', 'Authorization': 'y', 'nickname': 'Ben', 'user_agent': 'iPhone',
               'peer': '1.2.3.4', 'device_id': 'abc', 'members': 4, 'state': 'ok', 'name': 'Alice Smith',
               'playerName': 'Ben', 'deviceId': 'x', 'userAgent': 'y', 'psk': 'z',
               'nested': [{'password': 'p'}, {'session_key': 'k', 'game': 'bluff'}]}
        out = redact.scrub_json(doc)
        for k in ('token', 'cookie', 'Authorization', 'nickname', 'user_agent', 'peer', 'device_id', 'name',
                  'playerName', 'deviceId', 'userAgent', 'psk'):
            self.assertEqual(out[k], redact.REDACTED, k)
            self.assertTrue(redact.violations_in_json({k: doc[k]}), f'the validator passed a raw {k}')
        self.assertEqual((out['members'], out['state']), (4, 'ok'))
        self.assertEqual(redact.scrub_json({'members': ['Alice Smith', 'Bob']}), {'members': redact.REDACTED})
        self.assertTrue(redact.violations_in_json({'members': ['Alice Smith', 'Bob']}))
        self.assertEqual(redact.violations_in_json(out), [])
        self.assertEqual(out['nested'], [{'password': redact.REDACTED}, {'session_key': redact.REDACTED, 'game': 'bluff'}])

    def test_fuzz_secrets_in_random_text_never_survive(self):
        rng = random.Random(697)
        words = ['party', 'game', 'seat', 'lobby', 'round', 'host', 'ok', 'retry', 'phone', 'state', '502']
        makers = [lambda: secrets.token_hex(32), lambda: secrets.token_urlsafe(32),
                  lambda: f'member-{secrets.token_hex(16)}', lambda: f'__Host-avrana_device={secrets.token_urlsafe(32)}',
                  lambda: '.'.join(str(rng.randrange(11, 223)) for _ in range(4)),
                  lambda: ':'.join(f'{rng.randrange(256):02x}' for _ in range(6)),
                  lambda: f'"{rng.choice(["Ada", "Ben", "Cleo", "Dev"])} {rng.choice(["Smith", "Jones"])}"']
        for _ in range(400):
            secret = rng.choice(makers)()
            parts = [rng.choice(words) for _ in range(rng.randrange(1, 8))]
            parts.insert(rng.randrange(len(parts) + 1), secret)
            text = ' '.join(parts)
            clean = redact.scrub_text(text)
            self.assertEqual(redact.violations_in_text(clean), [], (text, clean))
            self.assertNotIn(secret.strip('"'), clean)

    def test_device_tokens_are_caught_by_shape_alone(self):
        """Without a cookie or key=value around it, a bare device token is still caught (the shape rule)."""
        missed = sum(1 for _ in range(20000) if not redact.violations_in_text(secrets.token_urlsafe(32)))
        self.assertEqual(missed, 0)
        for benign in ('ConnectionRefusedError', '20261021T190000Z-four-phones-bluff', 'avrana-party-certificate.timer'):
            self.assertEqual(redact.violations_in_text(benign), [], benign)

    def test_review_scrub_gaps_are_closed(self):
        cases = {'psk=hunter2hunter2': 'hunter2hunter2', 'passphrase=correct-horse': 'correct-horse',
                 'pwd=letmein99': 'letmein99', 'pin=4821': '4821', 'sta_10.42.0.57 joined': '10.42.0.57',
                 'chat_message from Alice': 'Alice', 'x 0123456789abcdef0123456789 y': '0123456789abcdef0123456789',
                 'ip 192\uff0e168\uff0e1\uff0e5': '168', '"' + 'n' * 250 + '"': 'n' * 250,
                 'token ab+cd/Ef12GhIjKl34MnOpQr56StUvWx==': 'Ef12GhIjKl34MnOpQr56'}
        for raw, secret in cases.items():
            with self.subTest(raw=raw[:30]):
                clean = redact.scrub_log_line(raw)
                if clean is not None:
                    self.assertNotIn(secret, clean)
                    self.assertEqual(redact.violations_in_text(clean, log=True), [])

    def test_apostrophes_are_not_quotes(self):
        text = "Party Core's game didn't load"
        self.assertEqual(redact.scrub_text(text), text)

    def test_truncation_never_leaves_half_a_marker(self):
        text = 'x' * 281 + ' password=abcdefgh'
        out = redact.scrub_text(text, 290)
        self.assertNotIn('[redac', out.rstrip('…')[-8:] if out.endswith('[') else out[-12:-1].rpartition(']')[0] + 'ok')
        self.assertEqual(redact.violations_in_text(out), [])

    def test_keys_are_scrubbed_too(self):
        doc = {f'member-{"a" * 32}': 1, '192.168.1.5': 1}
        out = redact.scrub_json(doc)
        self.assertEqual(redact.violations_in_json(out), [])
        self.assertTrue(redact.violations_in_json(doc))

    def test_forbidden_terms_are_whole_words(self):
        self.assertTrue(redact.violations_in_text('Cleo joined late', ('cleo',)))
        self.assertFalse(redact.violations_in_text('cleopatra joined late', ('cleo',)))
        self.assertTrue(redact.violations_in_text('Zo\u0065\u0301 joined', ('Zo\u00e9',)))     # NFD text, NFC term
        self.assertTrue(redact.violations_in_text('\u674e joined', ('\u674e',)))              # one-character name

    def test_lengths_are_bounded(self):
        self.assertLessEqual(len(redact.scrub_text('x' * 5000, 300)), 301)


class Sessions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'sessions'
        self.store = fs.Store(self.root)
        self.probes = FakeProbes()

    def started(self, **kw):
        return fs.start(self.store, 'four phones bluff', self.probes, now=T0, **kw)

    def test_off_by_default_nothing_is_written_before_start(self):
        out = io.StringIO()
        with mock.patch('sys.stdout', out):
            self.assertEqual(fs.main(['--root', str(self.root), 'status']), 0)
        self.assertIn('diagnostics are off', out.getvalue())
        self.assertFalse(self.root.exists())
        with self.assertRaises(fs.Refused):
            fs.mark(self.store, 'x', now=T0)
        with self.assertRaises(fs.Refused):
            fs.snapshot(self.store, self.probes, now=T0)

    def test_start_records_revisions_and_refuses_a_second_session(self):
        s = self.started()
        self.assertEqual(s['revisions_at_start']['party'], PARTY)
        self.assertEqual(s['revisions_at_start']['games'], GAMES)
        self.assertEqual(s['id'], '20261021T190000Z-four-phones-bluff')
        self.assertEqual(self.store.active_id(), s['id'])
        with self.assertRaises(fs.Refused):
            fs.start(self.store, 'again', self.probes, now=T0)

    def test_marks_are_scrubbed_bounded_and_validated(self):
        self.started()
        e = fs.mark(self.store, f'phone C froze; token={DEVICE_TOKEN} ' + 'x' * 400, 'fail', 'A-12', now=T0)
        self.assertNotIn(DEVICE_TOKEN, json.dumps(e))
        self.assertLessEqual(len(e['note']), fs.MARK_CHARS + 1)
        with self.assertRaises(fs.Refused):
            fs.mark(self.store, 'x', 'great', now=T0)

    def test_size_limit_stops_recording_but_not_the_stop(self):
        self.started(max_bytes=4000)
        with self.assertRaises(fs.Refused):
            for i in range(200):
                fs.mark(self.store, f'note {i} ' + 'y' * 150, now=T0 + timedelta(seconds=i))
        s = fs.stop(self.store, self.probes, now=T0 + timedelta(minutes=5))
        self.assertIsNotNone(s['stopped_at'])
        self.assertIn('session stop', (self.store.dir(s['id']) / 'timeline.md').read_text(encoding='utf-8'))

    def test_a_stale_or_dangling_active_pointer_never_wedges(self):
        s = self.started()
        fs.stop(self.store, self.probes, now=T0 + timedelta(minutes=1))
        (self.root / 'ACTIVE').write_text(s['id'] + '\n', encoding='utf-8')        # crash before the unlink
        self.assertIsNone(self.store.active_id())
        fs.start(self.store, 'next', self.probes, now=T0 + timedelta(minutes=2))
        (self.root / 'ACTIVE').write_text('20261021T000000Z-gone\n', encoding='utf-8')
        self.assertIsNone(self.store.active_id())
        self.assertFalse((self.root / 'ACTIVE').exists())

    def test_a_full_session_still_fits_one_package(self):
        self.started()
        with self.assertRaises(fs.Refused):
            for i in range(5000):
                fs.snapshot(self.store, self.probes, now=T0 + timedelta(seconds=i))
        self.probes.entries = [entry(T0 + timedelta(seconds=i), f'info line {i} ' + 'z' * 200) for i in range(1500)]
        s = fs.stop(self.store, self.probes, now=T0 + timedelta(hours=2))
        path, _, _, size = fs.export(self.store, self.tmp.name)
        self.assertLessEqual(size, fs.EXPORT_MAX_BYTES)
        self.assertGreater(s['collected']['journal_dropped']['cap'], 0)

    def test_byte_array_messages_with_bad_values_do_not_break_stop(self):
        self.started()
        e = entry(T0 + timedelta(minutes=1), 'x')
        e['MESSAGE'] = [104, 105, 300, -1, 'x']
        self.probes.entries = [e]
        s = fs.stop(self.store, self.probes, now=T0 + timedelta(minutes=2))
        self.assertEqual(s['collected']['journal_lines'], 1)

    def test_marks_in_the_same_second_keep_their_order(self):
        self.started()
        fs.mark(self.store, 'zebra first', now=T0 + timedelta(seconds=5))
        fs.mark(self.store, 'apple second', now=T0 + timedelta(seconds=5))
        s = fs.stop(self.store, self.probes, now=T0 + timedelta(minutes=1))
        t = (self.store.dir(s['id']) / 'timeline.md').read_text(encoding='utf-8')
        self.assertLess(t.index('zebra first'), t.index('apple second'))

    def test_a_session_expires(self):
        self.started(max_hours=1)
        with self.assertRaises(fs.Refused):
            fs.mark(self.store, 'late', now=T0 + timedelta(hours=2))

    def test_journal_window_scrubbing_chat_and_cap(self):
        self.started()
        self.probes.entries = [entry(T0 + timedelta(minutes=1), f'GET /party/api/join from 10.42.0.57 member-{"a" * 32}'),
                               entry(T0 + timedelta(minutes=2), 'chat from seat 2: secret plans', 'avranaparty-games.service'),
                               entry(T0 - timedelta(hours=1), 'before the session'),
                               entry(T0 + timedelta(minutes=3), 'game bluff: session s1 closed, the game stopped answering',
                                     priority=4),
                               entry(T0 + timedelta(minutes=3), 'game bluff: session s1 closed, the game stopped answering',
                                     priority=4)]
        s = fs.stop(self.store, self.probes, now=T0 + timedelta(minutes=10))
        d = self.store.dir(s['id'])
        rows = [json.loads(l) for l in (d / 'journal.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(len(rows), 2)                   # duplicate collapsed, chat and outside dropped
        self.assertEqual(s['collected']['journal_dropped'], {'conversation': 1, 'cap': 0, 'outside': 1})
        self.assertEqual(set(rows[0]), {'at', 'priority', 'unit', 'message'})   # no hostname, cmdline, pid
        self.assertNotIn('10.42.0.57', rows[0]['message'])
        self.assertIn('WARN avrana-party-core.service: game bluff', (d / 'timeline.md').read_text(encoding='utf-8'))

    def test_journal_cap_keeps_warnings(self):
        rows = [entry(T0 + timedelta(seconds=i), f'info {i}') for i in range(fs.JOURNAL_MAX_LINES + 50)]
        rows.append(entry(T0 + timedelta(seconds=1), 'the important warning', priority=3))
        kept, dropped = fs.journal_lines(rows, T0, T0 + timedelta(hours=1))
        self.assertEqual((len(kept), dropped['cap']), (fs.JOURNAL_MAX_LINES, 51))
        self.assertTrue(any(r['message'] == 'the important warning' for r in kept))

    def test_throttle_window(self):
        lines = [json.dumps({'ts': '2026-10-21T19:05:00Z', 'throttled': '0x0', 'temp_c': 61.2}),
                 json.dumps({'ts': '2026-10-21T17:00:00Z', 'throttled': '0x50005'}), 'not json']
        self.assertEqual(len(fs.throttle_window(lines, T0, T0 + timedelta(hours=1))), 1)

    def simulated_failure(self):
        """The acceptance story: baseline, a provider dies, the operator marks it, it comes back, export."""
        self.started()
        fs.mark(self.store, 'baseline: four phones on Party Home', 'pass', 'A-01', now=T0 + timedelta(minutes=1))
        self.probes.doc = status(PARTY, GAMES, 'failed', ['avranaparty-games is failed', 'games provider unreachable'],
                                 session={'game': 'bluff', 'state': 'playing'})
        fs.snapshot(self.store, self.probes, now=T0 + timedelta(minutes=5))
        fs.mark(self.store, 'phones B and D show the game is not responding', 'fail', 'A-12', now=T0 + timedelta(minutes=5, seconds=20))
        self.probes.entries = [entry(T0 + timedelta(minutes=4, seconds=50), 'Main process exited, code=killed, status=9/KILL',
                                     'avranaparty-games.service', 3)]
        self.probes.doc = status(PARTY, GAMES)
        fs.snapshot(self.store, self.probes, now=T0 + timedelta(minutes=8))
        fs.mark(self.store, 'games back after systemd restart; round lost', 'observed', now=T0 + timedelta(minutes=8, seconds=30))
        return fs.stop(self.store, self.probes, now=T0 + timedelta(minutes=10))

    def test_simulated_failure_is_reproducible_in_a_sanitized_package(self):
        s = self.simulated_failure()
        out = Path(self.tmp.name) / 'out'
        path, digest, count, size = fs.export(self.store, out)
        self.assertLessEqual(size, fs.EXPORT_MAX_BYTES)
        members, problems = fs.validate(path)
        self.assertEqual(problems, [])
        timeline = members['timeline.md'].decode('utf-8')
        self.assertIn('avranaparty-games: active -> failed', timeline)
        self.assertIn('avranaparty-games: failed -> active', timeline)
        self.assertIn('**MARK FAIL** [A-12]: phones B and D show the game is not responding', timeline)
        self.assertIn('ERROR avranaparty-games.service: Main process exited', timeline)
        self.assertIn(f'party: `{PARTY[:12]}`, games: `{GAMES[:12]}`', timeline)
        manifest = json.loads(members['manifest.json'])
        self.assertEqual(manifest['revisions_at_start']['party'], PARTY)
        self.assertEqual(sorted(manifest['files']), sorted(n for n in members if n != 'manifest.json'))
        # Reproducible: the same session exports to the same bytes.
        path2, digest2, _, _ = fs.export(self.store, Path(self.tmp.name) / 'again')
        self.assertEqual((digest, path.read_bytes()), (digest2, path2.read_bytes()))
        with tarfile.open(path) as tar:
            self.assertTrue(all(i.uid == 0 and i.uname == '' and i.mode == 0o644 for i in tar.getmembers()))
            self.assertTrue(all(i.name.startswith(f'avrana-field-{s["id"]}/') for i in tar.getmembers()))

    def test_export_needs_a_stopped_session(self):
        self.started()
        with self.assertRaises(fs.Refused):
            fs.export(self.store, self.tmp.name)

    def test_a_poisoned_session_is_refused_and_nothing_is_written(self):
        s = self.simulated_failure()
        d = self.store.dir(s['id'])
        with open(d / 'events.jsonl', 'a', encoding='utf-8') as f:     # someone edits the evidence by hand
            f.write(json.dumps({'at': 'x', 'kind': 'mark', 'note': f'Cookie: __Host-avrana_device={DEVICE_TOKEN}'}) + '\n')
        out = Path(self.tmp.name) / 'out'
        with self.assertRaises(fs.Refused) as cm:
            fs.export(self.store, out)
        self.assertIn('events.jsonl:cookie_header', str(cm.exception))
        self.assertNotIn(DEVICE_TOKEN, str(cm.exception))
        self.assertFalse(out.exists())

    def test_guest_names_can_be_forbidden(self):
        self.started()
        fs.mark(self.store, 'Cleo could not see the lobby', 'fail', now=T0 + timedelta(minutes=1))
        fs.stop(self.store, self.probes, now=T0 + timedelta(minutes=2))
        names = Path(self.tmp.name) / 'names.txt'
        names.write_text('Ada\nCleo\n', encoding='utf-8')
        with self.assertRaises(fs.Refused) as cm:
            fs.export(self.store, self.tmp.name, forbid_terms=fs._read_terms(names))
        self.assertIn('forbidden_term', str(cm.exception))
        self.assertNotIn('Cleo', str(cm.exception))

    def test_validate_finds_tampering_extra_members_and_size(self):
        self.simulated_failure()
        path, _, _, _ = fs.export(self.store, self.tmp.name)
        members = fs.read_package(path)
        members['timeline.md'] += b'\nedited\n'
        tampered = Path(self.tmp.name) / 'tampered.tar.gz'
        tampered.write_bytes(fs.tar_bytes('avrana-field-x', members, 0))
        _, problems = fs.validate(tampered)
        self.assertIn(('timeline.md', 'digest_mismatch'), {(p['member'], p['rule']) for p in problems})
        extra = Path(self.tmp.name) / 'extra.tar.gz'
        extra.write_bytes(fs.tar_bytes('avrana-field-x', dict(members, **{'notes.txt': b'hello'}), 0))
        with self.assertRaises(fs.Refused):
            fs.validate(extra)
        self.assertTrue(redact.validate_members({'notes.txt': b'x'}, allowed_names=fs.MEMBER.match))

    def hostile(self, entries):
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode='w:gz') as tar:
            for name, data in entries:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        path = Path(self.tmp.name) / f'hostile-{len(entries)}.tar.gz'
        path.write_bytes(raw.getvalue())
        return path

    def test_hostile_packages_are_refused(self):
        pem = json.dumps({'note': PEM}).encode() + b'\n'
        cases = [[('avrana-field-x/events.jsonl', pem), ('avrana-field-x/events.jsonl', b'')],     # duplicate
                 [('avrana-field-x/../session.json', b'{}')],                                     # traversal
                 [('avrana-field-x/session.json', b'{}'), ('avrana-field-y/session.json', b'{}')],  # two prefixes
                 [('session.json', b'{}')]]                                                         # no prefix
        for entries in cases:
            with self.subTest(names=[n for n, _ in entries]), self.assertRaises(fs.Refused):
                fs.validate(self.hostile(entries))
        for manifest in (b'{"files": ["a"]}', b'{"files": {"x": 5}}', b'[1]'):
            _, problems = fs.validate(self.hostile([('avrana-field-x/manifest.json', manifest)]))
            self.assertIn('bad_manifest', {p['rule'] for p in problems})

    def test_symlinks_in_a_session_are_refused(self):
        s = self.simulated_failure()
        link = self.store.dir(s['id']) / 'snapshots' / '099.json'
        try:
            link.symlink_to(Path(self.tmp.name) / 'outside.json')
        except (OSError, NotImplementedError):
            self.skipTest('symbolic links need privileges on this platform')
        with self.assertRaises(fs.Refused):
            fs.export(self.store, self.tmp.name)
        self.assertTrue(redact.validate_members({'timeline.md': b'x' * 100}, max_bytes=10))

    def test_cli_round_trip(self):
        root = ['--root', str(self.root), '--status-url', 'http://127.0.0.1:1/party/api/status', '--status-host', '']
        out = io.StringIO()
        with mock.patch('sys.stdout', out), mock.patch('sys.stderr', io.StringIO()):
            self.assertEqual(fs.main(root + ['start', '--label', 'cli demo']), 0)
            self.assertEqual(fs.main(root + ['mark', 'party core unreachable on purpose', '--outcome', 'observed']), 0)
            self.assertEqual(fs.main(root + ['stop']), 0)
            self.assertEqual(fs.main(root + ['export', '--out', self.tmp.name]), 0)
            pkg = next(Path(self.tmp.name).glob('avrana-field-*.tar.gz'))
            self.assertEqual(fs.main(root + ['validate', str(pkg)]), 0)
        self.assertIn('privacy validation clean', out.getvalue())
        self.assertIn('status unreachable', fs.read_package(pkg)['timeline.md'].decode('utf-8'))


class PoisonedFixture(unittest.TestCase):
    def test_the_poisoned_journal_fixture_comes_out_clean(self):
        """tests/fixtures/field-session/poisoned-journal.json holds one journal entry per planted kind."""
        entries = json.loads((FIXTURES / 'poisoned-journal.json').read_text(encoding='utf-8'))
        start = datetime(2026, 10, 21, 0, 0, tzinfo=timezone.utc)
        raw = {'journal.jsonl': ''.join(json.dumps({'message': e['MESSAGE']}) + '\n' for e in entries).encode()}
        self.assertGreaterEqual(len({p['rule'] for p in redact.validate_members(raw)}), 10)
        rows, dropped = fs.journal_lines(entries, start, start + timedelta(days=1))
        clean = {'journal.jsonl': ''.join(json.dumps(r) + '\n' for r in rows).encode()}
        self.assertEqual(redact.validate_members(clean), [])
        self.assertGreaterEqual(dropped['conversation'], 1)
        text = clean['journal.jsonl'].decode()
        for needle in ('BEGIN PRIVATE KEY', 'avrana_device=', 'Bearer', '10.42.0.57', 'a4:83:e7', 'Benjamin', '@example.com'):
            self.assertNotIn(needle, text)



class SupportBundle(unittest.TestCase):
    """`bundle` (AVR-74): a field package of the last hours without a session, through the same rules."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'sessions'
        self.out = Path(self.tmp.name) / 'out'
        self.store = fs.Store(self.root)
        self.probes = FakeProbes()

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_window_reaches_back_and_the_package_validates(self):
        self.probes.entries = [entry(T0 - timedelta(hours=7), 'too old to be in the window', priority=3),
                               entry(T0 - timedelta(hours=5), 'unit restarted after a failure', priority=3),
                               entry(T0 - timedelta(minutes=5), 'game provider answered slowly', priority=4)]
        out, digest, count, size = fs.bundle(self.store, self.probes, self.out, hours=6, now=T0)
        self.assertTrue(out.name.startswith('avrana-field-') and out.name.endswith('-support-6h.tar.gz'), out.name)
        members, problems = fs.validate(out)
        self.assertEqual(problems, [])
        session = json.loads(members['session.json'])
        self.assertEqual(session['kind'], 'support')
        self.assertEqual(session['window'], {'since': '2026-10-21T13:00:00Z', 'until': '2026-10-21T19:00:00Z', 'hours': 6.0})
        journal = members['journal.jsonl'].decode()
        self.assertIn('unit restarted after a failure', journal)
        self.assertIn('answered slowly', journal)
        self.assertNotIn('too old', journal)
        self.assertIsNone(self.store.active_id())               # nothing is left recording

    def test_private_data_in_the_journal_never_reaches_the_bundle(self):
        self.probes.entries = [entry(T0 - timedelta(minutes=10), text) for text in PLANTED.values()]
        out, *_ = fs.bundle(self.store, self.probes, self.out, hours=1, now=T0)
        members, problems = fs.validate(out)
        self.assertEqual(problems, [])
        blob = b''.join(members.values()).decode('utf-8', 'replace')
        for secret in (GAME_KEY, DEVICE_TOKEN, '10.42.0.57', 'a4:83:e7:12:34:56', 'Benjamin', 'meet me at the bar'):
            self.assertNotIn(secret, blob)

    def test_the_same_window_gives_the_same_bytes(self):
        self.probes.entries = [entry(T0 - timedelta(hours=1), 'one line', priority=4)]
        _, first, *_ = fs.bundle(self.store, self.probes, self.out / 'a', hours=2, now=T0)
        shutil_root = Path(self.tmp.name) / 'sessions2'
        _, second, *_ = fs.bundle(fs.Store(shutil_root), self.probes, self.out / 'b', hours=2, now=T0)
        self.assertEqual(first, second)

    def test_refusals(self):
        for hours in (0, -1, 24.5, 100):
            with self.assertRaises(fs.Refused, msg=hours):
                fs.bundle(self.store, self.probes, self.out, hours=hours, now=T0)
        fs.start(self.store, 'a real night', self.probes, now=T0 - timedelta(minutes=30))
        with self.assertRaises(fs.Refused) as ctx:
            fs.bundle(self.store, self.probes, self.out, hours=1, now=T0)
        self.assertIn('stop it and export it instead', str(ctx.exception))
        self.assertFalse(self.out.exists())

    def test_a_bundle_keeps_no_working_copy_even_when_refused(self):
        # AVR-740: a bundle refused for naming a guest left the name in the store's journal.jsonl and timeline.md,
        # and every bundle left its working session behind.
        self.probes.entries = [entry(T0 - timedelta(minutes=5), 'Benjamin rejoined after a Wi-Fi drop', priority=4)]
        with self.assertRaises(fs.Refused):
            fs.bundle(self.store, self.probes, self.out, hours=1, now=T0, forbid_terms=['Benjamin'])
        self.assertFalse(self.out.exists())
        left = [f for f in self.root.rglob('*') if f.is_file() and 'Benjamin' in f.read_text(encoding='utf-8', errors='ignore')]
        self.assertEqual(left, [])
        out, *_ = fs.bundle(self.store, self.probes, self.out, hours=1, now=T0 + timedelta(minutes=1))
        self.assertTrue(out.is_file())
        self.assertEqual([p for p in self.root.iterdir() if p.is_dir()], [])
        # A recorded night is never touched by a bundle's clean-up.
        night = fs.start(self.store, 'a real night', self.probes, now=T0 + timedelta(minutes=2))
        fs.stop(self.store, self.probes, now=T0 + timedelta(minutes=3))
        fs.bundle(self.store, self.probes, self.out / 'c', hours=1, now=T0 + timedelta(minutes=4))
        self.assertEqual([p.name for p in self.root.iterdir() if p.is_dir()], [night['id']])

    def test_a_garbled_preflight_never_leaves_a_session_recording(self):
        for n, doc in enumerate(({'schema': fs.PREFLIGHT_SCHEMA, 'checks': 'x'},
                                 {'schema': fs.PREFLIGHT_SCHEMA, 'checks': ['x', None]}, 'not a dict')):
            fs.bundle(self.store, self.probes, self.out, hours=1, now=T0 + timedelta(minutes=n), attach_preflight=doc)
            self.assertIsNone(self.store.active_id())
        with mock.patch.object(fs, 'take_snapshot', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                fs.bundle(self.store, self.probes, self.out, hours=1, now=T0 + timedelta(minutes=9), attach_preflight={})
        self.assertIsNone(self.store.active_id())

    def test_a_forbidden_term_refuses_the_bundle(self):
        self.probes.entries = [entry(T0 - timedelta(minutes=1), 'seat two went quiet: Zelda')]
        with self.assertRaises(fs.Refused):
            fs.bundle(self.store, self.probes, self.out, hours=1, now=T0, forbid_terms=['Zelda'])
        self.assertFalse(self.out.exists() and any(self.out.iterdir()))

    def test_cli(self):
        out = io.StringIO()
        with mock.patch.object(fs, 'Probes', lambda *a, **k: self.probes), mock.patch('sys.stdout', out):
            code = fs.main(['--root', str(self.root), 'bundle', '--out', str(self.out), '--hours', '3'])
        self.assertEqual(code, 0)
        self.assertIn('the last 3 h; privacy validation clean', out.getvalue())

if __name__ == '__main__':
    unittest.main()
