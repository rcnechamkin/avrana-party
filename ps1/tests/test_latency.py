"""Latency instrumentation: the frame barcode round-trips, the injection counter moves only when a
key actually changes, and an idle stream costs nothing. GStreamer/aiohttp stubbed; runs anywhere.
    python ps1/tests/test_latency.py
"""
import os
import sys
import types
import unittest

fake = types.ModuleType('stream')


class Stream:
    def __init__(self):
        self.pads = []
        self.peers = {}
        self.serial = 0


fake.Stream = Stream
fake.Gst = fake.GstWebRTC = fake.GstSdp = None
fake.web = types.SimpleNamespace(WSMsgType=types.SimpleNamespace(TEXT='TEXT'))
fake.log = types.SimpleNamespace(info=lambda *a: None, warning=print)
fake.ROOT = None
fake.ap_addresses = lambda: set()
fake.Window = object
sys.modules['stream'] = fake
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import stream_ps1 as m  # noqa: E402


class Barcode(unittest.TestCase):
    def frame(self, w, h, fill=90):
        return bytearray([fill]) * (w * h * 3 // 2)

    def test_round_trip_at_both_capture_sizes(self):
        for w, h in ((320, 240), (640, 480)):
            for value in (0, 0xFFFFFFFF, 0x12345678, (123456789 & 0xFFFFFF) << 8 | 0x2A):
                data = self.frame(w, h)
                m.stamp_i420(data, w, h, value)
                self.assertEqual(m.read_stamp(data, w), value, (w, value))

    def test_only_the_strip_changes_and_its_chroma_is_neutral(self):
        w, h = 320, 240
        data = self.frame(w, h)
        m.stamp_i420(data, w, h, 0xA5A5A5A5)
        self.assertEqual(data[8 * w], 90)                       # row 8: untouched picture
        self.assertEqual(data[256], 90)                         # right of the strip: untouched
        u = w * h
        self.assertEqual(data[u], 128)                          # chroma under the strip: neutral
        self.assertEqual(data[u + 128], 90)                     # beyond it: untouched
        self.assertEqual(len(data), w * h * 3 // 2)


class X11:
    def __init__(self):
        self.events = []

    def keycode(self, name):
        return len(name)

    def key(self, code, down):
        self.events.append((code, down))

    def flush(self):
        pass


class Loop:
    def call_later(self, delay, fn):
        return types.SimpleNamespace(cancel=lambda: None)


class Injection(unittest.TestCase):
    def test_counter_moves_only_on_a_real_key_change(self):
        hits = []
        pad = m.XTestPad(X11(), 0, Loop(), on_inject=lambda: hits.append(1))
        pad.set(0b1)          # press Up
        pad.set(0b1)          # heartbeat, same mask: nothing sent
        pad.set(0b11)         # add Down
        self.assertEqual(len(hits), 2)
        pad.pressed_at = [0.0] * len(m.BUTTONS)   # past MIN_HOLD: the release goes out now
        pad.set(0)
        self.assertEqual(len(hits), 3)

    def test_measure_mode_is_off_unless_asked(self):
        self.assertFalse(m.PS1Stream('bomberman').measure or os.environ.get('AVRANA_PS1_MEASURE') == '1')


if __name__ == '__main__':
    unittest.main(verbosity=1)
