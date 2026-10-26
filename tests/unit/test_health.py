"""Avrana Health (avrana.ops.health): preflight checks mapped to four states, with the time rules."""
from datetime import datetime, timedelta, timezone
import io
import json
import unittest
from unittest import mock

from avrana.ops import health

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


def chk(check_id, status, blocking=True, category='pi', reason='r'):
    return {'id': check_id, 'category': category, 'status': status, 'blocking': blocking, 'reason': reason}


def report(*checks, age_min=1, clock='PASS', verdict='READY'):
    all_checks = [chk('pi.clock', clock, reason='clock')] + list(checks)
    return {'schema': 'avrana.preflight/v0', 'generated_at': (NOW - timedelta(minutes=age_min)).isoformat(),
            'verdict': verdict, 'horizon_days': 0, 'checks': all_checks}


class ItemStates(unittest.TestCase):
    def test_each_status_maps_to_one_state(self):
        self.assertEqual(health.item_state(chk('a', 'PASS')), 'healthy')
        self.assertEqual(health.item_state(chk('a', 'WARN')), 'degraded')
        self.assertEqual(health.item_state(chk('a', 'FAIL', blocking=False)), 'degraded')
        self.assertEqual(health.item_state(chk('a', 'FAIL', blocking=True)), 'action_required')
        self.assertEqual(health.item_state(chk('a', 'UNKNOWN')), 'unknown')
        self.assertEqual(health.item_state(chk('a', 'something new')), 'unknown')

    def test_overall_is_the_worst_item(self):
        doc = health.build_health(report(chk('services', 'PASS'), chk('storage./', 'WARN')), now=NOW)
        self.assertEqual(doc['state'], 'degraded')
        doc = health.build_health(report(chk('storage./', 'WARN'), chk('services', 'FAIL', category='services')), now=NOW)
        self.assertEqual(doc['state'], 'action_required')
        self.assertEqual(doc['items'][0]['id'], 'services')
        self.assertEqual(doc['items'][0]['action']['ref'], 'docs/runbooks/service-recovery.md')

    def test_unknown_never_rolls_up_as_healthy(self):
        doc = health.build_health(report(chk('services', 'PASS'), chk('wifi.gate', 'UNKNOWN')), now=NOW)
        self.assertEqual(doc['state'], 'unknown')

    def test_all_healthy(self):
        doc = health.build_health(report(chk('services', 'PASS'), chk('tls.party', 'PASS', category='tls')), now=NOW)
        self.assertEqual(doc['state'], 'healthy')
        self.assertEqual(doc['ready'], {'verdict': 'READY', 'horizon_days': 0})
        self.assertTrue(all(i['source'].startswith('preflight:') for i in doc['items']))


class TimeRules(unittest.TestCase):
    def test_a_stale_report_is_not_health(self):
        doc = health.build_health(report(chk('services', 'PASS'), age_min=40), now=NOW)
        self.assertEqual(doc['state'], 'unknown')
        self.assertTrue(all(i['state'] == 'unknown' for i in doc['items']))
        self.assertIsNone(doc['ready'])
        self.assertIn('40 minutes old', doc['reasons'][0])

    def test_untrusted_clock_makes_certificates_unknown(self):
        doc = health.build_health(report(chk('services', 'PASS'), chk('tls.party', 'PASS', category='tls'),
                                         clock='UNKNOWN', age_min=500), now=NOW)
        by_id = {i['id']: i for i in doc['items']}
        self.assertEqual(by_id['tls.party']['state'], 'unknown')
        self.assertIn('not trusted', by_id['tls.party']['words'])
        self.assertEqual(by_id['services']['state'], 'healthy')   # the age cannot be judged, so it is not stale
        self.assertEqual(doc['state'], 'unknown')

    def test_untrusted_clock_never_gives_healthy(self):
        doc = health.build_health(report(chk('services', 'PASS'), clock='FAIL'), now=NOW)
        self.assertNotEqual(doc['state'], 'healthy')

    def test_a_missing_clock_check_counts_as_untrusted(self):
        doc = report(chk('tls.party', 'PASS', category='tls'))
        doc['checks'] = doc['checks'][1:]
        self.assertEqual(health.build_health(doc, now=NOW)['state'], 'unknown')


class Inputs(unittest.TestCase):
    def test_unreadable_reports(self):
        for bad in (None, {}, {'schema': 'avrana.status/v0'}, {'schema': 'avrana.preflight/v0', 'checks': 'x'}):
            doc = health.build_health(bad, now=NOW)
            self.assertEqual(doc['state'], 'unknown')
            self.assertEqual(doc['items'], [])

    def test_cli_reads_stdin_and_exits_by_state(self):
        r = report(chk('services', 'FAIL', category='services'), age_min=0)
        r['generated_at'] = datetime.now(timezone.utc).isoformat()
        out = io.StringIO()
        with mock.patch('sys.stdin', io.StringIO(json.dumps(r))), mock.patch('sys.stdout', out):
            code = health.main(['--preflight', '-', '--json'])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out.getvalue())['state'], 'action_required')

    def test_text_summary_lists_only_problems(self):
        doc = health.build_health(report(chk('services', 'PASS', reason='all up'),
                                         chk('storage./', 'WARN', reason='3% free')), now=NOW)
        text = health.render_text(doc)
        self.assertIn('Working, with problems', text)
        self.assertIn('3% free', text)
        self.assertNotIn('all up', text)
        self.assertIn('2 of 3 checks healthy', text)


if __name__ == '__main__':
    unittest.main()
