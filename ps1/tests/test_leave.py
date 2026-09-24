"""Explicit Leave: a player who presses Leave frees the slot at once (no 30 s grace), and only the
slot's current socket can do it. GStreamer/aiohttp stubbed; runs anywhere.
    python ps1/tests/test_leave.py
"""
import asyncio
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


class Pad:
    def __init__(self):
        self.mask = 0
        self.released = 0

    def set(self, b):
        self.mask = b

    def release_all(self):
        self.mask = 0
        self.released += 1


class WS:
    def __init__(self):
        self.closed = False

    async def close(self, code=None, message=None):
        self.closed = True


class Leave(unittest.TestCase):
    def run_async(self, coro):
        return asyncio.run(coro)

    def setUp(self):
        self.s = m.PS1Stream('bomberman')
        self.s.pads = [Pad() for _ in range(4)]

    def test_leave_frees_the_slot_now_and_schedules_no_grace(self):
        async def go():
            self.s.loop = asyncio.get_running_loop()
            a, b = WS(), WS()
            (sa, ta), (sb, tb) = self.s.claim(a, None, False), self.s.claim(b, None, False)
            self.s.pads[sb].set(0b101)
            self.assertTrue(self.s.leave(sb, b))
            self.assertIsNone(self.s.owners[sb])                 # free immediately
            self.assertEqual(self.s.pads[sb].mask, 0)            # buttons released
            self.s.release(sb, b)                                # the socket's finally: no-op now
            self.assertIsNone(self.s.owners[sb])                 # no grace timer was scheduled
            c = WS()
            self.assertEqual(self.s.claim(c, None, False)[0], sb)   # next player gets it at once
            slot, token = self.s.claim(WS(), tb, False)          # the old token is dead:
            self.assertNotEqual(token, tb)                       # a fresh identity if anything
        self.run_async(go())

    def test_only_the_current_socket_can_leave(self):
        async def go():
            self.s.loop = asyncio.get_running_loop()
            old, new = WS(), WS()
            slot, token = self.s.claim(old, None, False)
            self.assertEqual(self.s.claim(new, token, False)[0], slot)   # takeover by token
            await asyncio.sleep(0)
            self.assertFalse(self.s.leave(slot, old))            # replaced socket: refused
            self.assertIs(self.s.owners[slot]['ws'], new)
        self.run_async(go())

    def test_a_dropped_connection_still_gets_the_grace_period(self):
        async def go():
            self.s.loop = asyncio.get_running_loop()
            a = WS()
            slot, token = self.s.claim(a, None, False)
            self.s.release(slot, a)                              # connection lost, no Leave
            self.assertIsNotNone(self.s.owners[slot])            # still reserved for the token
            self.assertIsNotNone(self.s.owners[slot]['grace'])
            self.assertEqual(self.s.claim(WS(), token, False)[0], slot)
        self.run_async(go())

    def test_client_sends_leave_only_from_the_leave_button(self):
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'index.html'),
                  encoding='utf-8') as f:
            page = f.read()
        self.assertIn("leave.onclick=()=>{if(ws?.readyState===WebSocket.OPEN&&mySlot)ws.send(JSON.stringify({type:'leave'}))", page)
        self.assertEqual(page.count("{type:'leave'}"), 1)        # not on pagehide / reload


if __name__ == '__main__':
    unittest.main(verbosity=1)
