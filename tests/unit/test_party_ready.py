"""Party Ready (avrana.ops.party_ready, AVR-86): the preflight document said for an owner. No Pi, no network."""
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from avrana.ops import party_ready, preflight
from avrana.ops.preflight import FAIL, PASS, UNKNOWN, WARN, check


def doc(checks, horizon=0, waived=(), unverified=('Wi-Fi capacity with the real number of phones',)):
    """An avrana.preflight/v0 document as preflight.run builds it, from a list of checks."""
    result, overall = preflight.verdict(checks, waived)
    return {'schema': preflight.SCHEMA, 'generated_at': '2026-10-26T10:00:00Z', 'host': 'party', 'verdict': result,
            'overall': overall, 'horizon_days': horizon, 'checks': checks, 'waived': list(waived),
            'physically_unverified': list(unverified)}


def healthy():
    return [
        check('revision.party', 'revision', PASS, 'party deployed'),
        check('service.avrana-party-core', 'services', PASS, 'active'),
        check('serving.party_home', 'serving', PASS, 'Party Home over HTTPS'),
        check('tls.party.avrana.net', 'tls', PASS, 'verified, 80 days left'),
        check('network.topology', 'network', PASS, 'AP up'),
        check('wifi.gate', 'network', PASS, 'gate PASS'),
        check('dns.party.avrana.net', 'network', PASS, '-> 10.42.0.1'),
        check('storage./', 'pi', PASS, '20 GiB free'),
        check('pi.clock', 'pi', PASS, 'NTP synchronized'),
        check('packages.installed', 'packages', PASS, 'no .avrgame packages installed (none required)'),
        check('runtime.python', 'runtime', PASS, '3.11'),
    ]


def area(ready, name):
    return next(a for a in ready['areas'] if a['area'] == name)


class SummaryTests(unittest.TestCase):
    def test_healthy_box_is_ready_for_party(self):
        r = party_ready.summarize(doc(healthy(), horizon=7))
        self.assertIs(r['ready'], True)
        self.assertEqual(r['headline'], 'READY FOR PARTY')
        self.assertEqual({a['state'] for a in r['areas']}, {'ok'})
        self.assertEqual(area(r, 'trust')['says'],
                         'Phones will trust the box until at least 2026-11-02 10:00 UTC (7 days from the check)')
        self.assertTrue(all('do' not in a for a in r['areas']))
        self.assertEqual(r['schema'], 'avrana.party-ready/v0')

    def test_certificate_inside_the_trip_is_one_thing_to_fix_with_what_to_do(self):
        checks = healthy()
        checks[3] = check('tls.party.avrana.net', 'tls', FAIL,
                          'party.avrana.net: certificate expires 2026-10-30, inside the 7-day horizon; renew before leaving')
        r = party_ready.summarize(doc(checks, horizon=7))
        self.assertIs(r['ready'], False)
        self.assertEqual(r['headline'], '1 thing to fix before leaving home')
        trust = area(r, 'trust')
        self.assertEqual(trust['state'], 'fix')
        self.assertEqual(trust['says'], 'Phones will refuse the box before 2026-11-02 10:00 UTC (7 days from the check)')
        self.assertIn('Renew the certificate at home', trust['do'])
        self.assertEqual(trust['details'][0]['id'], 'tls.party.avrana.net')

    def test_two_problems_count_as_two_things(self):
        checks = healthy()
        checks[2] = check('serving.party_home', 'serving', FAIL, 'HTTP 502')
        checks[7] = check('storage./', 'pi', FAIL, '300 MiB free (below the minimum)')
        r = party_ready.summarize(doc(checks))
        self.assertEqual(r['headline'], '2 things to fix before leaving home')
        self.assertEqual(area(r, 'games')['state'], 'fix')
        self.assertEqual(area(r, 'space')['state'], 'fix')
        self.assertEqual(area(r, 'space')['says'], 'The box is almost out of space')

    def test_an_unchecked_blocking_fact_is_never_called_ready(self):
        checks = healthy()
        checks[5] = check('wifi.gate', 'network', UNKNOWN, 'no wifi-lab gate result')
        r = party_ready.summarize(doc(checks))
        self.assertIsNone(r['ready'])
        self.assertEqual(r['headline'], 'Not confirmed: 1 thing could not be checked')
        self.assertEqual(area(r, 'wifi')['state'], 'unchecked')
        self.assertIn('Wi-Fi check at home', area(r, 'wifi')['do'])

    def test_a_waived_unknown_is_ready_and_says_what_was_accepted(self):
        checks = healthy()
        checks[5] = check('wifi.gate', 'network', UNKNOWN, 'no wifi-lab gate result')
        r = party_ready.summarize(doc(checks, waived=['wifi.gate']))
        self.assertIs(r['ready'], True)
        self.assertEqual(r['waived'], ['wifi.gate'])
        self.assertIn('Accepted without checking: wifi.gate', party_ready.render_text(r))
        wifi = area(r, 'wifi')
        self.assertEqual(wifi['state'], 'accepted')        # AVR-742: never the all-clear sentence for a waived check
        self.assertEqual(wifi['says'], 'The Party Wi-Fi has not been checked recently (accepted without checking)')
        self.assertIn('[ ~ ] The Party Wi-Fi has not been checked recently', party_ready.render_text(r))

    def test_a_waived_certificate_does_not_promise_trust_for_the_trip(self):
        checks = healthy()
        checks[3] = check('tls.party.avrana.net', 'tls', UNKNOWN, 'could not connect')
        r = party_ready.summarize(doc(checks, horizon=7, waived=['tls.party.avrana.net']))
        self.assertIs(r['ready'], True)
        self.assertNotIn('will trust', area(r, 'trust')['says'])
        self.assertIn('accepted without checking', area(r, 'trust')['says'])

    def test_a_waiver_never_hides_a_fail_even_in_a_hand_edited_report(self):
        """AVR-742: the preflight only waives a blocking UNKNOWN; a saved report listing a FAIL as waived (and saying
        READY) is still one thing to fix."""
        checks = healthy()
        checks[3] = check('tls.party.avrana.net', 'tls', FAIL, 'expired')
        edited = dict(doc(checks, horizon=7), waived=['tls.party.avrana.net'], verdict='READY')
        r = party_ready.summarize(edited)
        self.assertIs(r['ready'], False)
        self.assertEqual(area(r, 'trust')['state'], 'fix')
        self.assertEqual(r['waived'], [])

    def test_a_blocking_check_in_an_unrecognised_state_is_not_called_fine(self):
        checks = healthy()
        checks[3] = dict(checks[3], status='SKIPPED')
        r = party_ready.summarize(dict(doc(healthy()), checks=checks))
        self.assertIsNone(r['ready'])
        self.assertEqual(area(r, 'trust')['state'], 'unchecked')
        checks[3] = dict(checks[3], status=None)
        self.assertIsNone(party_ready.summarize(dict(doc(healthy()), checks=checks))['ready'])

    def test_the_trip_horizon_is_counted_from_the_check_not_from_reading_it(self):
        """AVR-742: a saved report read 23 hours later must not promise seven more days."""
        late = datetime(2026, 10, 27, 9, 0, tzinfo=timezone.utc)
        r = party_ready.summarize(doc(healthy(), horizon=7), now=late)
        self.assertIs(r['ready'], True)
        self.assertNotIn('next 7 days', area(r, 'trust')['says'])
        self.assertIn('2026-11-02 10:00 UTC', area(r, 'trust')['says'])
        checks = healthy()
        checks[3] = check('tls.party.avrana.net', 'tls', FAIL, 'expires inside the horizon')
        self.assertEqual(area(party_ready.summarize(doc(checks, horizon=7)), 'trust')['says'],
                         'Phones will refuse the box before 2026-11-02 10:00 UTC (7 days from the check)')

    def test_no_horizon_says_only_the_moment_of_the_check_was_covered(self):
        trust = area(party_ready.summarize(doc(healthy())), 'trust')
        self.assertEqual(trust['says'], 'Phones will trust the box right now (no trip length was checked)')

    def test_the_offline_note_does_not_promise_games_that_are_not_served(self):
        self.assertIn('still gets every game from the box', party_ready.summarize(doc(healthy()))['offline_note'])
        checks = healthy()
        checks[2] = check('serving.party_home', 'serving', FAIL, 'not served')
        note = party_ready.summarize(doc(checks))['offline_note']
        self.assertNotIn('still gets every game', note)
        self.assertIn('cannot be counted on', note)

    def test_a_fail_is_never_hidden_by_a_waiver_of_something_else(self):
        checks = healthy()
        checks[8] = check('pi.clock', 'pi', FAIL, 'clock is 37 h behind')
        r = party_ready.summarize(doc(checks, waived=['wifi.gate']))
        self.assertIs(r['ready'], False)
        self.assertEqual(area(r, 'health')['state'], 'fix')

    def test_an_advisory_warning_keeps_ready_but_is_noted(self):
        checks = healthy() + [check('pi.journal', 'pi', WARN, 'journal is volatile', blocking=False)]
        r = party_ready.summarize(doc(checks))
        self.assertIs(r['ready'], True)
        self.assertIn('keep an eye on', area(r, 'health')['note'])

    def test_an_area_with_no_checks_at_all_is_unchecked(self):
        checks = [c for c in healthy() if not c['id'].startswith('tls.')]
        r = party_ready.summarize(doc(checks))
        self.assertIsNone(r['ready'])
        self.assertEqual(area(r, 'trust')['state'], 'unchecked')

    def test_an_unknown_check_id_is_shown_under_health_not_dropped(self):
        checks = healthy() + [check('future.thing', 'future', FAIL, 'something new failed')]
        r = party_ready.summarize(doc(checks))
        self.assertEqual(area(r, 'health')['details'][0]['id'], 'future.thing')
        self.assertIs(r['ready'], False)

    def test_the_node_runtime_counts_as_games_and_other_runtime_checks_as_software(self):
        self.assertEqual(party_ready.area_of('runtime.node'), 'games')
        self.assertEqual(party_ready.area_of('runtime.python'), 'software')
        self.assertEqual(party_ready.area_of('services'), 'health')
        self.assertEqual(party_ready.area_of('config.party_core'), 'software')

    def test_the_owner_text_has_no_daemon_words_outside_the_details(self):
        checks = healthy()
        checks[1] = check('service.avrana-party-core', 'services', FAIL, 'avrana-party-core is failed')
        text = party_ready.render_text(party_ready.summarize(doc(checks)))
        owner_part = text.split('Details for whoever helps you:')[0]
        for word in ('systemd', 'avrana-party-core', 'nginx', 'service.', 'HTTP'):
            self.assertNotIn(word, owner_part)
        self.assertIn('service.avrana-party-core', text)          # still there for support
        self.assertIn('Only a real phone can show these:', text)

    def test_the_wifi_gate_line_is_not_repeated_as_a_phone_test(self):
        checks = healthy()
        checks[5] = check('wifi.gate', 'network', UNKNOWN, 'no wifi-lab gate result')
        r = party_ready.summarize(doc(checks, unverified=('Wi-Fi qualification: the wifi-lab gate did not PASS for this run',
                                                          'phones staying connected through screen lock')))
        self.assertEqual(r['phones_still_to_try'], ['phones staying connected through screen lock'])
        self.assertEqual(area(r, 'wifi')['state'], 'unchecked')

    def test_anything_but_a_preflight_document_is_refused(self):
        for bad in (None, [], {}, {'schema': 'avrana.status/v0', 'checks': []}, {'schema': preflight.SCHEMA}):
            with self.assertRaises(ValueError):
                party_ready.summarize(bad)
        with self.assertRaises(ValueError):
            party_ready.summarize(dict(doc(healthy()), checks=['tls.x']))

    def test_a_saved_report_must_be_recent(self):
        at = lambda iso: datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)
        self.assertIs(party_ready.summarize(doc(healthy()), now=at('2026-10-26T12:00:00'))['ready'], True)
        old = party_ready.summarize(doc(healthy()), now=at('2026-10-28T10:00:00'))
        self.assertIsNone(old['ready'])
        self.assertIn('48 hours old', old['headline'])
        self.assertIsNone(party_ready.summarize(doc(healthy()), now=at('2026-10-26T08:00:00'))['ready'])
        self.assertIsNone(party_ready.summarize(dict(doc(healthy()), generated_at=None), now=at('2026-10-26T12:00:00'))['ready'])
        self.assertIs(party_ready.summarize(doc(healthy()))['ready'], True)          # fresh from the preflight


class CommandTests(unittest.TestCase):
    def run_main(self, argv, stdin=''):
        out = io.StringIO()
        with mock.patch('sys.stdout', out), mock.patch('sys.stdin', io.StringIO(stdin)), \
                mock.patch('sys.stderr', io.StringIO()), \
                mock.patch.object(party_ready, '_now', lambda: datetime(2026, 10, 26, 11, 0, tzinfo=timezone.utc)):
            code = party_ready.main(argv)
        return code, out.getvalue()

    def test_a_saved_preflight_file_gives_the_plain_answer_and_the_preflight_exit_code(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'preflight.json'
            path.write_text(json.dumps(doc(healthy())), encoding='utf-8')
            code, text = self.run_main([str(path)])
        self.assertEqual(code, 0)
        self.assertTrue(text.startswith('READY FOR PARTY'))

    def test_stdin_and_json(self):
        checks = healthy()
        checks[3] = check('tls.party.avrana.net', 'tls', FAIL, 'expired')
        code, text = self.run_main(['-', '--json'], json.dumps(doc(checks)))
        self.assertEqual(code, 1)
        self.assertIs(json.loads(text)['ready'], False)

    def test_unreadable_input_is_a_usage_error(self):
        self.assertEqual(self.run_main(['-'], 'not json')[0], 2)
        self.assertEqual(self.run_main(['-'], json.dumps({'schema': 'x'}))[0], 2)

    def test_exit_codes_match_the_preflight(self):
        self.assertEqual(party_ready.EXIT, {True: preflight.EXIT[preflight.READY], False: preflight.EXIT[preflight.NOT_READY],
                                            None: preflight.EXIT[preflight.UNKNOWN]})


class PreflightFlagTests(unittest.TestCase):
    def test_preflight_party_ready_prints_the_plain_answer(self):
        out = io.StringIO()
        with mock.patch.object(preflight, 'run', return_value=doc(healthy(), horizon=3)), mock.patch('sys.stdout', out):
            code = preflight.main(['--party-ready', '--horizon-days', '3'])
        self.assertEqual(code, 0)
        self.assertIn('READY FOR PARTY', out.getvalue())
        self.assertIn('until at least 2026-10-29 10:00 UTC (3 days from the check)', out.getvalue())


if __name__ == '__main__':
    unittest.main()
