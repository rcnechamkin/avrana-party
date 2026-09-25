"""Party mode (F5 seat tickets v1): with a per-launch key from the party, a controller slot comes
only from a valid ticket for exactly that slot; first-come and reclaim tokens are off.
GStreamer/aiohttp stubbed; runs anywhere.   python ps1/tests/test_seats.py
"""
import asyncio
import hashlib
import hmac
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

KEY = 'ab' * 32


def mint(slot, game='ps1-bomberman', exp=2000000000, key=KEY):
    body = f'v1.{slot}.{exp}.{game}'
    return body + '.' + hmac.new(bytes.fromhex(key), body.encode(), hashlib.sha256).hexdigest()[:32]


class Pad:
    def __init__(self):
        self.mask = 0

    def set(self, b):
        self.mask = b

    def release_all(self):
        self.mask = 0


class WS:
    def __init__(self):
        self.closed = False
        self.code = None

    async def close(self, code=None, message=None):
        self.closed, self.code = True, code


class Tickets(unittest.TestCase):
    def test_vector_matches_the_party_side(self):
        # experiments/party-service/seat_ticket.py TEST_VECTOR: key 00*32, slot 3, exp 2000000000
        ticket = 'v1.3.2000000000.ps1-bomberman.' + hmac.new(bytes(32), b'v1.3.2000000000.ps1-bomberman',
                                                              hashlib.sha256).hexdigest()[:32]
        self.assertEqual(m.verify_ticket('00' * 32, ticket, 'ps1-bomberman', 4, now=1999999999), 3)

    def test_refusals(self):
        now = 1999999999
        self.assertEqual(m.verify_ticket(KEY, mint(2), 'ps1-bomberman', 4, now=now), 2)
        for bad in (mint(2, key='cd' * 32), mint(2, game='ps1-worms'), mint(5), mint(2, exp=1999999998),
                    mint(2).replace('v1.2.', 'v1.1.'), None, '', 'abcdefgh12', mint(2) + 'x', 7):
            self.assertIsNone(m.verify_ticket(KEY, bad, 'ps1-bomberman', 4, now=now), bad)
        self.assertIsNone(m.verify_ticket(None, mint(2), 'ps1-bomberman', 4, now=now))   # no key: no party mode

    def test_hello_carries_the_ticket(self):
        self.assertEqual(m.parse_hello('{"type":"hello","role":"play","ticket":"' + mint(1) + '"}'), (False, mint(1)))


class PartyMode(unittest.TestCase):
    def setUp(self):
        self.s = m.PS1Stream('bomberman', seat_key=KEY)
        self.s.pads = [Pad() for _ in range(4)]

    def test_ticket_gives_exactly_its_seat_and_nothing_is_first_come(self):
        async def go():
            self.s.loop = asyncio.get_running_loop()
            self.assertEqual(self.s.claim(WS(), mint(3), False), (2, None))   # seat 3 = slot index 2
            self.assertEqual(self.s.claim(WS(), None, False), (None, None))   # no ticket: watches
            self.assertEqual(self.s.claim(WS(), 'abcdefgh12', False), (None, None))   # old token path is off
            self.assertEqual(self.s.claim(WS(), mint(3, key='cd' * 32), False), (None, None))
            self.assertEqual(self.s.claim(WS(), mint(1), True), (None, None))  # Watch stays Watch
            self.assertEqual([o is not None for o in self.s.owners], [False, False, True, False])
        asyncio.run(go())

    def test_same_seat_reconnecting_replaces_the_old_socket(self):
        async def go():
            self.s.loop = asyncio.get_running_loop()
            old, new = WS(), WS()
            self.s.claim(old, mint(1), False)
            self.s.pads[0].mask = 5
            self.assertEqual(self.s.claim(new, mint(1), False)[0], 0)
            await asyncio.sleep(0)
            self.assertEqual((old.closed, old.code), (True, 4001))
            self.assertIs(self.s.owners[0]['ws'], new)
            self.assertEqual(self.s.pads[0].mask, 0)                           # nothing left held
            self.s.release(0, old)                                             # the old socket's cleanup
            self.assertIs(self.s.owners[0]['ws'], new)                         # can't unseat the new one
        asyncio.run(go())


if __name__ == '__main__':
    unittest.main(verbosity=1)
