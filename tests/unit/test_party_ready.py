"""Party Ready (avrana.ops.party_ready, AVR-86): the preflight document said for an owner. No Pi, no network."""
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
        self.assertEqual(area(r, 'trust')['says'], 'Phones will trust the box for the next 7 days')
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
        self.assertEqual(trust['says'], 'Phones will refuse the box for the next 7 days')
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

    def test_anything_but_a_preflight_document_is_refused(self):
        for bad in (None, [], {}, {'schema': 'avrana.status/v0', 'checks': []}, {'schema': preflight.SCHEMA}):
            with self.assertRaises(ValueError):
                party_ready.summarize(bad)


class CommandTests(unittest.TestCase):
    def run_main(self, argv, stdin=''):
        out = io.StringIO()
        with mock.patch('sys.stdout', out), mock.patch('sys.stdin', io.StringIO(stdin)), \
                mock.patch('sys.stderr', io.StringIO()):
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
        self.assertIn('for the next 3 days', out.getvalue())


if __name__ == '__main__':
    unittest.main()
