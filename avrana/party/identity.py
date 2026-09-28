"""Server-issued device identity (ADR 0003 §2; PARTY-PLATFORM.md §13).

* A device token is `secrets.token_urlsafe(32)` (256 bits), minted only here. A browser that
  presents an unknown, malformed or revoked value is issued a fresh token: a client can never
  choose its identity (unlike the games' `wc-token`, which the browser mints).
* It travels only in the `avrana_device` cookie: `Path=/party/; HttpOnly; Secure; SameSite=Lax`.
  Full Mode lives on the HTTPS server only (ADR 0004), so `Secure` holds in production; tests may
  turn it off for a plain-HTTP loopback server. `Path=/party/` means game pages' own requests
  (`/games/…`) never carry it, while a game page can still ask `/party/api/…` for a ticket.
* It never appears in a URL, a response body or a log line. At rest only its SHA-256 is kept
  (hash -> device_id). `device_id` is opaque and authorizes nothing by itself.

Reference: experiment/party-service identity.py (tested there); this is its production shape.
"""
import hashlib
import json
import os
import re
import secrets
import tempfile
import threading

COOKIE = 'avrana_device'
COOKIE_PATH = '/party/'
MAX_AGE = 400 * 24 * 3600            # browsers cap cookie lifetimes near 400 days anyway
TOKEN_RE = re.compile(r'^[A-Za-z0-9_-]{43}$')


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class DeviceStore:
    """hash(token) -> device_id. With a path, persisted atomically as 0600 JSON so phones keep
    their identity across service restarts. The party itself stays in memory."""

    def __init__(self, path=None):
        self.path = path
        self.lock = threading.Lock()
        self.by_hash = {}
        if path and os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict) or not all(
                    isinstance(k, str) and re.fullmatch(r'[0-9a-f]{64}', k)
                    and isinstance(v, str) and re.fullmatch(r'device-[0-9a-f]{32}', v)
                    for k, v in data.items()):
                raise ValueError(f'{path}: not a device store')
            self.by_hash = data

    def issue(self):
        """Mint a token for a new device. Returns (token, device_id); only the hash is kept."""
        token = secrets.token_urlsafe(32)
        device_id = f'device-{secrets.token_hex(16)}'
        with self.lock:
            self.by_hash[token_hash(token)] = device_id
            self._save()
        return token, device_id

    def resolve(self, token):
        """The device_id for a presented token, or None (absent, malformed, unknown, revoked)."""
        if not isinstance(token, str) or not TOKEN_RE.match(token):
            return None
        with self.lock:
            return self.by_hash.get(token_hash(token))

    def revoke(self, token):
        with self.lock:
            gone = self.by_hash.pop(token_hash(token), None) if isinstance(token, str) else None
            self._save()
        return gone is not None

    def _save(self):
        if not self.path:
            return
        folder = os.path.dirname(os.path.abspath(self.path))
        fd, tmp = tempfile.mkstemp(dir=folder, prefix='.devices-')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(self.by_hash, f)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)                 # power loss leaves the old or the new file
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise


def read_cookie(header, name=COOKIE):
    """The value of cookie `name` in a Cookie header, or None. Other cookies are ignored."""
    for part in (header or '').split(';'):
        k, _, v = part.strip().partition('=')
        if k == name:
            return v
    return None


def set_cookie(token, secure=True, name=COOKIE):
    flags = '; Secure' if secure else ''
    return f'{name}={token}; Path={COOKIE_PATH}; Max-Age={MAX_AGE}; HttpOnly{flags}; SameSite=Lax'
