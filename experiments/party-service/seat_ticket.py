"""Seat tickets v1 (ROADMAP F5, smallest version): the party tells a game "this connection holds
seat N" without the game ever seeing a device token, presence id or name.

    v1.<slot>.<expires unix s>.<game id>.<mac>     mac = HMAC-SHA256(key, "v1.<slot>.<exp>.<game>")[:32 hex]

The key is random per launch and handed to the game process in its environment (never argv,
never a URL), so a ticket is valid only for that one run of that one game, and it expires within
TTL_S. Only the seated phone's own party view carries its ticket; the game sends it in its first
socket message. The verifier is duplicated in the game (ps1/stream_ps1.py); TEST_VECTOR pins
the format across both.
"""
import hashlib
import hmac
import re
import secrets
import time

TTL_S = 300
FORMAT = re.compile(r'^v1\.([1-9][0-9]?)\.([0-9]{10})\.([a-z][a-z0-9_-]{0,39})\.([0-9a-f]{32})$')
TEST_VECTOR = ('00' * 32, 3, 2000000000, 'ps1-bomberman',
               'v1.3.2000000000.ps1-bomberman.' + hmac.new(bytes(32), b'v1.3.2000000000.ps1-bomberman',
                                                             hashlib.sha256).hexdigest()[:32])


def new_key():
    return secrets.token_hex(32)


def mint(key_hex, game, slot, now=None, ttl=TTL_S):
    exp = int((time.time() if now is None else now) + ttl)
    body = f'v1.{int(slot)}.{exp}.{game}'
    return body + '.' + hmac.new(bytes.fromhex(key_hex), body.encode(), hashlib.sha256).hexdigest()[:32]


def verify(key_hex, ticket, game, max_slot, now=None):
    """The slot this ticket grants in `game`, or None."""
    m = FORMAT.match(ticket) if isinstance(ticket, str) else None
    if not m:
        return None
    slot, exp, tgame, mac = int(m[1]), int(m[2]), m[3], m[4]
    body = f'v1.{slot}.{exp}.{tgame}'
    good = hmac.new(bytes.fromhex(key_hex), body.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(good, mac) or tgame != game or not 1 <= slot <= max_slot:
        return None
    if exp < (time.time() if now is None else now):
        return None
    return slot
