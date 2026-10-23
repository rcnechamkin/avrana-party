"""The local performance harness itself (AVR-138): its statistics, bounds, report and short runs.

TIER: T1 for the pure parts (tools/perf/perfstats.py); T2-process for the smoke and error-path runs,
which start a real Party Core for a few seconds. They check that the harness measures, cleans up and
writes a well-formed result, not what the numbers are: those depend on the machine.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

PERF = Path(__file__).resolve().parents[2] / 'tools' / 'perf'
sys.path.insert(0, str(PERF))

import party_perf                                  # noqa: E402
import perfstats                                   # noqa: E402


def psutil_present():
    try:
        import psutil                              # noqa: F401
        return True
    except ImportError:
        return False


def tmpdir(test):
    d = tempfile.mkdtemp(prefix='avr138-')
    test.addCleanup(shutil.rmtree, d, True)
    return d


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
        # around a zero mean (growth deltas, idle CPU) a relative spread is undefined, not 0
        self.assertIsNone(perfstats.across([{'p50': -1}, {'p50': 1}])['cv'])
        self.assertEqual(perfstats.across([{'p50': 0}, {'p50': 0}])['cv'], 0.0)
        self.assertGreater(perfstats.across([{'p50': -2}, {'p50': -4}])['cv'], 0)

    def test_benchmarks_stay_bounded(self):
        self.assertEqual(perfstats.bounded(3, 1, 10, 'repeats'), 3)
        with self.assertRaises(ValueError):
            perfstats.bounded(11, 1, 10, 'repeats')
        with self.assertRaises(ValueError):
            party_perf.main(['--repeats', '11', '--out', tmpdir(self)])
        with self.assertRaises(ValueError):
            party_perf.main(['--clients', str(party_perf.MAX_CLIENTS + 1), '--out', tmpdir(self)])
        with self.assertRaises(ValueError):
            party_perf.main(['--window', '61', '--out', tmpdir(self)])
        with self.assertRaises(SystemExit):                      # not a Games checkout
            party_perf.main(['--games', tmpdir(self), '--out', tmpdir(self)])
        with self.assertRaises(ValueError):
            party_perf.main(['--rt-mix', 'sprinting', '--out', tmpdir(self)])


class FrameLogTest(unittest.TestCase):
    """AVR-674: what a realtime client derives from the state frames it receives."""

    @staticmethod
    def frame(tick, now_ms, vx=0.0, seat=0):
        return json.dumps({'type': 'state', 'now': now_ms, 'phase': 'play',
                           'game': {'tick': tick, 'my_seat': seat,
                                    'units': [{'seat': 0, 'alive': True, 'vx': vx},
                                              {'seat': 1, 'alive': True, 'vx': -vx}]}})

    def test_ticks_repeats_gaps_and_ages(self):
        log = party_perf.FrameLog()
        log.state(self.frame(10, 1000), 0.000, 1002)
        log.state(self.frame(10, 1010), 0.010, 1011)              # an echo of tick 10
        log.state(self.frame(11, 1033), 0.034, 1035)
        log.state(self.frame(12, 1066), 0.067, 1066)
        self.assertEqual((log.states, log.ticks, log.repeats), (4, 3, 1))
        self.assertEqual((log.first_tick, log.last_tick), (10, 12))
        self.assertEqual([round(x) for x in log.intervals_ms], [34, 33])   # only between new ticks
        self.assertEqual(log.ages_ms, [2, 1, 2, 0])

    def test_a_probe_is_timed_until_this_players_own_unit_shows_it(self):
        log = party_perf.FrameLog()
        log.start_probe(-1, 1.000)
        log.state(self.frame(1, 0, vx=50.0), 1.020, 0)            # still moving the old way
        log.state(self.frame(2, 0, vx=-5.0, seat=1), 1.040, 0)    # seat 0 shows it, but this is seat 1's view
        self.assertEqual(log.probe_ms, [])
        log.state(self.frame(3, 0, vx=-12.0), 1.070, 0)
        self.assertEqual([round(x) for x in log.probe_ms], [70])
        self.assertIsNone(log.probe)

    def test_unmatched_probes_are_counted_not_timed(self):
        log = party_perf.FrameLog()
        log.start_probe(1, 0.0)
        log.start_probe(-1, 0.5)                                 # the first never showed
        log.state(self.frame(1, 0, vx=10.0), 1.6, 0)             # past the timeout, still the old way
        log.start_probe(1, 2.0)
        log.end()                                                # the window closed first
        self.assertEqual((log.unmatched, log.probe_ms), (3, []))


class Report(unittest.TestCase):
    def result(self, scenarios):
        return {'schema': perfstats.SCHEMA, 'evidence': 'local loopback simulation on one machine',
                'environment': {'captured_at': 'now', 'os': 'TestOS', 'logical_cpus': 4, 'python': '3.x',
                                'party': {'commit': 'abc123def456789', 'dirty': True}, 'games': None},
                'config': {'repeats': 2, 'client_bound_pct': 70.0}, 'scenarios': scenarios}

    def test_the_report_states_its_evidence_errors_and_what_was_not_measured(self):
        md = perfstats.markdown(self.result({
            'lifecycle': {'skipped': 'needs --games PATH'},
            'longpoll_4': {'evidence': 'real Party Core process', 'what': 'four phones', 'errors': 1,
                           'runs': [{'error': 'TimeoutError: no'}, {}],
                           'aggregate': {'host action POST p50': {**perfstats.across([{'p50': 4.0}]), 'unit': 'ms'},
                                         'never measured': {'n': 0, 'values': [], 'unit': 'ms'},
                                         'around zero': {**perfstats.across([{'p50': -1}, {'p50': 1}]), 'unit': 'MB'}}}}))
        self.assertIn('Not a Pi, not Wi-Fi, not a phone', md)
        self.assertIn('abc123def456 (dirty)', md)
        self.assertIn('Not measured: needs --games PATH', md)
        self.assertIn('Evidence: real Party Core process.', md)
        self.assertIn('repeat 1 failed:** TimeoutError: no', md)
        self.assertIn('| host action POST p50 | ms | 4 (4-4, cv 0.00) |', md)
        self.assertIn('| never measured | ms | n/a |', md)
        self.assertIn('| around zero | MB | 0 (-1-1, cv n/a) |', md)

    def test_the_report_flags_a_client_bound_repeat_poll_errors_and_notes(self):
        md = perfstats.markdown(self.result({'x': {
            'evidence': 'e', 'what': 'w', 'errors': 0, 'aggregate': {},
            'runs': [{'load_generator': {'cpu_pct_window': 95.0}, 'poll_errors': {'Ben': 'HTTP 500'},
                      'notes': ['sampled child 2 of launcher 1']}]}}))
        self.assertIn('this harness used 95% of a core; the result may be client-bound', md)
        self.assertIn("poll errors {'Ben': 'HTTP 500'}", md)
        self.assertIn('sampled child 2 of launcher 1', md)

    def test_aggregate_reaches_into_lists_and_ignores_failed_repeats(self):
        runs = [{'a': [{'b': 2.0}]}, {'a': [{'b': 4.0}]}, {'error': 'x', 'a': [{'b': 100.0}]}]
        agg = party_perf.aggregate(runs, [('b', 'ms', 'a.0.b'), ('missing', 'ms', 'a.5.b')])
        self.assertEqual((agg['b']['median'], agg['b']['n'], agg['b']['unit']), (3.0, 2, 'ms'))
        self.assertEqual(agg['missing']['n'], 0)

    def test_the_simulated_phones_poll_like_the_party_page_within_the_service_cap(self):
        from avrana.party import service
        src = (party_perf.PARTY_ROOT / 'web' / 'party' / 'lib' / 'party-client.js').read_text(encoding='utf-8')
        self.assertIn(f'const WAIT_S = {party_perf.client_wait()};', src)     # read, not the fallback
        self.assertLessEqual(party_perf.client_wait(), service.MAX_WAIT)


class Sampling(unittest.TestCase):
    @unittest.skipUnless(psutil_present(), 'psutil not installed')
    def test_the_sampler_reports_this_process(self):
        s = party_perf.Sampler(os.getpid()).start()
        end = time.perf_counter() + 0.6
        while time.perf_counter() < end:                         # some CPU to see
            sum(range(1000))
        out = s.stop()
        self.assertGreater(out['cpu_pct_window'], 0)
        self.assertGreater(out['rss_mb']['p50'], 1)
        self.assertGreaterEqual(out['threads']['min'], 1)

    def test_without_psutil_the_figures_say_why(self):
        with mock.patch.dict(sys.modules, {'psutil': None}):
            out = party_perf.Sampler(os.getpid()).start().stop()
        self.assertEqual(out, {'unavailable': 'psutil not installed'})


class RecordingStack:
    """Wraps party_perf.Stack to remember each Party Core port, to check it is closed afterwards."""

    def __init__(self):
        self.ports = []
        self.real = party_perf.Stack

    def __call__(self, *a, **k):
        st = self.real(*a, **k)
        self.ports.append(st.party_port)
        return st


class SmokeRun(unittest.TestCase):
    """A few seconds against a real Party Core: the harness runs, measures, writes both files and
    leaves no process behind."""

    def test_a_short_run_writes_a_well_formed_result_and_leaves_no_process(self):
        out = Path(tmpdir(self))
        stacks = RecordingStack()
        with mock.patch.object(party_perf, 'Stack', stacks):
            code = party_perf.main(['--quick', '--only', 'idle,longpoll', '--clients', '2', '--repeats', '1',
                                    '--window', '0.5', '--actions', '2', '--out', str(out)])
        self.assertEqual(code, 0)
        self.assertEqual(len(stacks.ports), 2)
        self.assertFalse(any(party_perf.listening(p) for p in stacks.ports))  # every Party Core stopped
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
        self.assertEqual(run['poll_errors'], {})
        if psutil_present():                                        # measured, and the real interpreter
            self.assertIn('cpu_pct_window', run['party_core'])
            self.assertGreater(run['party_core']['rss_mb']['p50'], 5)
            self.assertIn('cpu_pct_window', run['load_generator'])
        self.assertIn('Evidence: real Party Core process', files[1].read_text(encoding='utf-8'))


class ErrorPath(unittest.TestCase):
    def test_a_failing_run_stops_its_pollers_and_its_party_core(self):
        cfg = party_perf.config(argparse.Namespace(quick=True, repeats=1, window=0.5, actions=2, cycles=1,
                                                   clients='2', rt_clients='2', rt_mix='moving'))
        stacks = RecordingStack()

        def boom(*a, **k):
            raise RuntimeError('injected')

        with mock.patch.object(party_perf, 'Stack', stacks), mock.patch.object(party_perf, 'timed_post', boom):
            with self.assertRaises(RuntimeError):
                party_perf.scenario_longpoll(cfg, None, 2)
        pollers = lambda: [t.name for t in threading.enumerate() if t.name.startswith('perf-poll-')]  # noqa: E731
        deadline = time.perf_counter() + 5
        while time.perf_counter() < deadline and pollers():
            time.sleep(0.05)
        self.assertEqual(pollers(), [])
        self.assertFalse(party_perf.listening(stacks.ports[0]))


if __name__ == '__main__':
    unittest.main()
