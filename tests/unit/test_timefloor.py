"""The time floor and time state (avrana.ops.timefloor): AVR-79 R2-R4, with no clock or root needed."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import tempfile
import unittest

from avrana.ops import timefloor as tf

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
DAY = timedelta(days=1)


class Floor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'state' / 'time-floor'

    def tearDown(self):
        self.tmp.cleanup()

    def test_round_trip_and_bad_files(self):
        self.assertIsNone(tf.read_floor(self.path))
        tf.write_floor(self.path, NOW)
        self.assertEqual(tf.read_floor(self.path), NOW)
        for junk in ('', 'yesterday', '2026-10-26T12:00:00', 'x' * 100, '\xff'):
            self.path.write_text(junk, encoding='utf-8')
            self.assertIsNone(tf.read_floor(self.path), junk[:10])

    def test_it_only_moves_forward_and_one_step_is_capped(self):
        self.assertEqual(tf.advance(None, NOW), NOW)
        self.assertEqual(tf.advance(NOW, NOW - DAY), NOW)                       # never back
        self.assertEqual(tf.advance(NOW, NOW + DAY), NOW + DAY)
        self.assertEqual(tf.advance(NOW, NOW + 400 * DAY), NOW + tf.FORWARD_CAP)  # a rogue forward step
        self.assertEqual(tf.advance(NOW, NOW + 400 * DAY, agreed_twice=True), NOW + 400 * DAY)
        self.assertEqual(tf.advance(NOW, None), NOW)

    def test_record_writes_only_when_synchronised(self):
        old, new = tf.record(self.path, now=NOW, synced=False)
        self.assertEqual((old, new), (None, None))
        self.assertFalse(self.path.exists())
        self.assertEqual(tf.record(self.path, now=NOW, synced=True), (None, NOW))
        self.assertEqual(tf.record(self.path, now=NOW - DAY, synced=True), (NOW, NOW))   # a backward clock: kept
        self.assertEqual(tf.read_floor(self.path), NOW)


class State(unittest.TestCase):
    def test_the_three_states(self):
        self.assertEqual(tf.time_state(NOW, None, True)['state'], 'unknown')
        self.assertEqual(tf.time_state(NOW, NOW - DAY, True)['state'], 'synced')
        self.assertEqual(tf.time_state(NOW, NOW - DAY, False)['state'], 'floor')
        self.assertEqual(tf.time_state(NOW, NOW + 2 * DAY, False)['state'], 'unknown')   # rollback or damage
        self.assertEqual(tf.time_state(NOW, NOW + 2 * DAY, True)['state'], 'unknown')    # a large backward step
        self.assertEqual(tf.time_state(NOW, NOW + timedelta(hours=2), False)['state'], 'floor')


class Judge(unittest.TestCase):
    def test_synced_decides_normally(self):
        self.assertEqual(tf.judge(NOW - DAY, NOW + DAY, 'synced', NOW, NOW - 9 * DAY), (True, 'valid'))
        self.assertFalse(tf.judge(NOW - DAY, NOW, 'synced', NOW, None)[0])
        self.assertFalse(tf.judge(NOW + DAY, None, 'synced', NOW, None)[0])

    def test_floor_is_a_lower_bound(self):
        floor = NOW - 10 * DAY
        ok, words = tf.judge(NOW - 20 * DAY, NOW + DAY, 'floor', NOW, floor)
        self.assertTrue(ok)
        self.assertIn('time not verified', words)
        self.assertEqual(tf.judge(NOW - 20 * DAY, floor - DAY, 'floor', NOW, floor)[0], False)      # expired by the floor
        self.assertIn('certainly', tf.judge(NOW - 20 * DAY, floor, 'floor', NOW, floor)[1])
        self.assertFalse(tf.judge(floor + DAY, NOW + 9 * DAY, 'floor', NOW, floor)[0])             # starts after the floor

    def test_unknown_accepts_nothing_that_needs_freshness(self):
        ok, words = tf.judge(NOW - DAY, NOW + DAY, 'unknown', NOW, None)
        self.assertFalse(ok)
        self.assertIn('not trusted', words)


class Probe(unittest.TestCase):
    def test_timedatectl_answers(self):
        fake = lambda out: (lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=out, stderr=''))
        self.assertTrue(tf.ntp_synchronised(fake('yes\n')))
        self.assertFalse(tf.ntp_synchronised(fake('no\n')))
        self.assertIsNone(tf.ntp_synchronised(fake('')))

        def missing(*a, **k):
            raise FileNotFoundError('timedatectl')
        self.assertIsNone(tf.ntp_synchronised(missing))

    def test_nothing_takes_a_phone_or_request_time(self):
        # R1: the only inputs are the floor file, this process's clock and timedatectl.
        source = Path(tf.__file__).read_text(encoding='utf-8')
        for word in ('request', 'header', 'Date:', 'urllib', 'http'):
            self.assertNotIn(word, source.split('"""', 2)[2], word)


if __name__ == '__main__':
    unittest.main()
