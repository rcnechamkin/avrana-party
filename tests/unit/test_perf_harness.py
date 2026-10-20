"""The local performance harness itself (AVR-138): its statistics, bounds, report and one short run.

TIER: T1 for the pure parts (tools/perf/perfstats.py); T2-process for the smoke run, which starts a
real Party Core for a few seconds. The smoke run checks that the harness measures and writes a
well-formed result, not what the numbers are: those depend on the machine.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

PERF = Path(__file__).resolve().parents[2] / 'tools' / 'perf'
sys.path.insert(0, str(PERF))

import party_perf                                  # noqa: E402
import perfstats                                   # noqa: E402


class Statistics(unittest.TestCase):
    def test_percentiles_interpolate_between_ranks(self):
        self.assertEqual(perfstats.percentile([1, 2, 3, 4], 50), 2.5)
        self.assertEqual(perfstats.percentile([4, 1, 3, 2], 0), 1)
        self.assertEqual(perfstats.percentile([4, 1, 3, 2], 100), 4)
        self.assertAlmostEqual(perfstats.percentile(range(1, 101), 95), 95.05)
        self.assertEqual(perfstats.percentile([7], 95), 7)
        self.assertIsNone(perfstats.percentile([], 50))
        self.assertIsNone(perfstats.percentile([None, None], 50))
        with self.assertRaises(ValueError):
            perfstats.percentile([1], 101)

    def test_summary_drops_missing_values_and_reports_its_sample_size(self):
        s = perfstats.summary([3, None, 1, 2])
        self.assertEqual((s['n'], s['min'], s['p50'], s['max'], s['mean']), (3, 1, 2, 3, 2))
        self.assertEqual(s['stdev'], 1.0)
        self.assertEqual(perfstats.summary([]), {'n': 0})
        self.assertEqual(perfstats.summary([5])['stdev'], 0.0)

    def test_variability_across_repeats(self):
        a = perfstats.across([{'p50': 10}, {'p50': 12}, {'p50': 14}, {'p50': None}, {}])
        self.assertEqual((a['n'], a['median'], a['min'], a['max']), (3, 12, 10, 14))
        self.assertEqual(a['values'], [10, 12, 14])
        self.assertAlmostEqual(a['cv'], 2 / 12, places=3)
        self.assertEqual(perfstats.across([{}]), {'n': 0, 'values': []})

    def test_benchmarks_stay_bounded(self):
        self.assertEqual(perfstats.bounded(3, 1, 10, 'repeats'), 3)
        with self.assertRaises(ValueError):
            perfstats.bounded(11, 1, 10, 'repeats')
        with self.assertRaises(ValueError):
            party_perf.main(['--repeats', '11', '--out', tempfile.mkdtemp()])
        with self.assertRaises(ValueError):
            party_perf.main(['--clients', str(party_perf.MAX_CLIENTS + 1), '--out', tempfile.mkdtemp()])
        with self.assertRaises(ValueError):
            party_perf.main(['--window', '61', '--out', tempfile.mkdtemp()])


class Report(unittest.TestCase):
    def result(self, scenarios):
        return {'schema': perfstats.SCHEMA, 'evidence': 'local loopback simulation on one machine',
                'environment': {'captured_at': 'now', 'os': 'TestOS', 'logical_cpus': 4, 'python': '3.x',
                                'party': {'commit': 'abc123def456789', 'dirty': True}, 'games': None},
                'config': {'repeats': 2}, 'scenarios': scenarios}

    def test_the_report_states_its_evidence_errors_and_what_was_not_measured(self):
        md = perfstats.markdown(self.result({
            'lifecycle': {'skipped': 'needs --games PATH'},
            'longpoll_4': {'evidence': 'real Party Core process', 'what': 'four phones', 'errors': 1,
                           'runs': [{'error': 'TimeoutError: no'}, {}],
                           'aggregate': {'host action POST p50': {**perfstats.across([{'p50': 4.0}]), 'unit': 'ms'},
                                         'never measured': {'n': 0, 'values': [], 'unit': 'ms'}}}}))
        self.assertIn('Not a Pi, not Wi-Fi, not a phone', md)
        self.assertIn('abc123def456 (dirty)', md)
        self.assertIn('Not measured: needs --games PATH', md)
        self.assertIn('Evidence: real Party Core process.', md)
        self.assertIn('repeat 1 failed:** TimeoutError: no', md)
        self.assertIn('| host action POST p50 | ms | 4 (4-4, cv 0.00) |', md)
        self.assertIn('| never measured | ms | n/a |', md)

    def test_aggregate_reaches_into_lists_and_ignores_failed_repeats(self):
        runs = [{'a': [{'b': 2.0}]}, {'a': [{'b': 4.0}]}, {'error': 'x', 'a': [{'b': 100.0}]}]
        agg = party_perf.aggregate(runs, [('b', 'ms', 'a.0.b'), ('missing', 'ms', 'a.5.b')])
        self.assertEqual((agg['b']['median'], agg['b']['n'], agg['b']['unit']), (3.0, 2, 'ms'))
        self.assertEqual(agg['missing']['n'], 0)

    def test_the_simulated_phones_poll_like_the_party_page(self):
        src = (party_perf.PARTY_ROOT / 'web' / 'party' / 'lib' / 'party-client.js').read_text(encoding='utf-8')
        self.assertIn(f'const WAIT_S = {party_perf.client_wait()};', src)


class SmokeRun(unittest.TestCase):
    """A few seconds against a real Party Core: the harness runs, measures, and writes both files."""

    def test_a_short_run_writes_a_well_formed_result(self):
        out = Path(tempfile.mkdtemp(prefix='avr138-'))
        code = party_perf.main(['--quick', '--only', 'idle,longpoll', '--clients', '2', '--repeats', '1',
                                '--window', '0.5', '--actions', '2', '--out', str(out)])
        self.assertEqual(code, 0)
        files = sorted(out.iterdir())
        self.assertEqual([f.suffix for f in files], ['.json', '.md'])
        result = json.loads(files[0].read_text(encoding='utf-8'))
        self.assertEqual(result['schema'], perfstats.SCHEMA)
        self.assertIn('quick smoke run', result['evidence'])
        self.assertEqual(sorted(result['scenarios']), ['idle', 'longpoll_2_clients'])
        self.assertIsNotNone(result['environment']['party'])
        lp = result['scenarios']['longpoll_2_clients']
        self.assertEqual(lp['errors'], 0, lp['runs'])
        run = lp['runs'][0]
        self.assertEqual(run['host_action_ms']['n'], 2)
        self.assertEqual(run['propagation_ms']['n'], 4)              # two actions, two phones
        self.assertEqual(run['missed_deliveries'], 0)
        self.assertLess(run['propagation_ms']['max'], 5000)
        self.assertGreater(run['bytes_in_per_client_update'], 0)
        self.assertIn('Evidence: real Party Core process', files[1].read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
