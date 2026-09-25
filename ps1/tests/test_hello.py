"""The PS1 socket handshake: the slot token travels in the first message (hello), never in the
URL. GStreamer/aiohttp are stubbed; runs anywhere.   python ps1/tests/test_hello.py
"""
import asyncio
import os
import re
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
fake.web = types.SimpleNamespace(WSMsgType=types.SimpleNamespace(TEXT='TEXT', BINARY='BINARY'))
fake.log = types.SimpleNamespace(info=print, warning=print)
fake.ROOT = None
fake.ap_addresses = lambda: set()
fake.Window = object
sys.modules['stream'] = fake
PS1 = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, PS1)
import stream_ps1 as m  # noqa: E402


class FakeWS:
    def __init__(self, messages=(), hang=False):
        self.messages = list(messages)
        self.hang = hang
        self.closed_with = None

    async def receive(self, timeout=None):
        if self.hang or not self.messages:
            await asyncio.sleep(3600)                 # a silent client: the handler's own deadline must fire
        return self.messages.pop(0)

    async def close(self, code=None, message=b''):
        self.closed_with = code


def text(data):
    return types.SimpleNamespace(type='TEXT', data=data)


class ParseHello(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(m.parse_hello('{"type":"hello","role":"play","token":"abcdefgh12"}'),
                         (False, 'abcdefgh12'))
        self.assertEqual(m.parse_hello('{"type":"hello","role":"play","token":null}'), (False, None))
        self.assertEqual(m.parse_hello('{"type":"hello","role":"play"}'), (False, None))

    def test_watch_never_carries_a_token(self):
        self.assertEqual(m.parse_hello('{"type":"hello","role":"watch","token":"abcdefgh12"}'),
                         (True, None))

    def test_invalid(self):
        for bad in ['', 'not json', '[]', '{"type":"state","b":1,"seq":1}',
                    '{"type":"hello","role":"admin"}', '{"type":"hello","role":"play","token":5}',
                    '{"type":"hello"}', '{"type":"hello","role":"play","token":"' + 'x' * 600 + '"}']:
            with self.assertRaises(ValueError, msg=bad):
                m.parse_hello(bad)


class ReadHello(unittest.TestCase):
    def setUp(self):
        m.HELLO_TIMEOUT = 0.05
        self.s = m.PS1Stream('bomberman')

    def run_hello(self, ws):
        return asyncio.run(self.s.read_hello(ws))

    def test_hello_first(self):
        ws = FakeWS([text('{"type":"hello","role":"play","token":"abcdefgh12"}')])
        self.assertEqual(self.run_hello(ws), (False, 'abcdefgh12'))
        self.assertIsNone(ws.closed_with)

    def test_silence_times_out_and_closes(self):
        ws = FakeWS(hang=True)
        self.assertIsNone(self.run_hello(ws))
        self.assertEqual(ws.closed_with, 1008)

    def test_non_hello_first_message_closes(self):
        ws = FakeWS([text('{"type":"state","b":1,"seq":1}')])
        self.assertIsNone(self.run_hello(ws))
        self.assertEqual(ws.closed_with, 1008)

    def test_binary_first_message_closes(self):
        ws = FakeWS([types.SimpleNamespace(type='BINARY', data=b'x')])
        self.assertIsNone(self.run_hello(ws))
        self.assertEqual(ws.closed_with, 1008)


class NoTokenInUrls(unittest.TestCase):
    def test_client_and_server_never_use_the_query_string(self):
        with open(os.path.join(PS1, 'index.html'), encoding='utf-8') as f:
            page = f.read()
        self.assertNotIn("q.set('token'", page)
        self.assertNotRegex(page, r"new URL\('ws\?")
        self.assertIn("type:'hello'", page)
        with open(os.path.join(PS1, 'stream_ps1.py'), encoding='utf-8') as f:
            server = f.read()
        self.assertFalse(re.search(r"request\.query\.get\('token'\)", server))


class Capture(unittest.TestCase):
    def test_sizes(self):
        import argparse
        self.assertEqual(m.parse_capture('320x240'), (320, 240))
        self.assertEqual(m.parse_capture('640X480'), (640, 480))
        for bad in ('321x240', 'abc', '100x100', '320x', '4000x3000', '-320x240'):
            with self.assertRaises(argparse.ArgumentTypeError, msg=bad):
                m.parse_capture(bad)


if __name__ == '__main__':
    unittest.main(verbosity=1)
