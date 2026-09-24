"""Server-issued device identity (ADR 0003; PARTY-PLATFORM.md §13) — the smallest testable form.

- A device token is `secrets.token_urlsafe(32)` (256 bits), issued ONLY by the server. A browser
  that presents an unknown or malformed value is simply issued a fresh token: a client can never
  choose its identity.
- The token travels only in a cookie: `HttpOnly; SameSite=Lax; Path=/party/` (plain-HTTP LAN, so
  no `Secure`). Path scoping keeps it away from game servers; the front door also strips `Cookie`
  on every non-party path. It never appears in a URL, a response body or a log line.
- At rest only its SHA-256 is kept (`hash -> device_id`); revoke = delete the entry. `device_id` is
  an opaque random identifier that authorizes nothing.
- Dev instances use a different cookie name (`avrana_dev_device`) so they can never overwrite a
  production cookie on the same host (cookies are keyed by name, host and path — not port).
"""
import hashlib
import json
import os
import re
import secrets
import tempfile
import threading

DEV_COOKIE = 'avrana_dev_device'
COOKIE_PATH = '/party/'
MAX_AGE = 400 * 24 * 3600          # ~400 days: browsers cap longer lifetimes anyway
TOKEN_RE = re.compile(r'^[A-Za-z0-9_-]{43}$')   # token_urlsafe(32) is 43 characters


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def new_id(kind):
    return f'{kind}-{secrets.token_hex(16)}'       # 128-bit, never derived from anything


class DeviceStore:
    """hash(token) -> device_id. Optionally persisted as JSON (0600) so phones keep their identity
    across service restarts; parties themselves stay in memory (reboot survival is OPEN)."""

    def __init__(self, path=None):
        self.path = path
        self.lock = threading.Lock()
        self.by_hash = {}
        if path and os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict) or not all(
                    isinstance(k, str) and re.fullmatch(r'[0-9a-f]{64}', k) and isinstance(v, str)
                    for k, v in data.items()):
                raise ValueError(f'{path}: not a device store')
            self.by_hash = data

    def issue(self):
        """Mint a token for a new device. Returns (token, device_id); only the hash is stored."""
        token = secrets.token_urlsafe(32)
        device_id = new_id('device')
        with self.lock:
            self.by_hash[token_hash(token)] = device_id
            self._save()
        return token, device_id

    def resolve(self, token):
        """The device_id for a presented token, or None (unknown, malformed or revoked)."""
        if not isinstance(token, str) or not TOKEN_RE.match(token):
            return None
        with self.lock:
            return self.by_hash.get(token_hash(token))

    def revoke(self, token):
        with self.lock:
            gone = self.by_hash.pop(token_hash(token), None) if isinstance(token, str) else None
            self._save()
        return gone is not None

    def reset(self):
        """Development: forget every device (every phone gets a new identity on its next visit)."""
        with self.lock:
            self.by_hash.clear()
            self._save()

    def _save(self):
        if not self.path:
            return
        folder = os.path.dirname(os.path.abspath(self.path))
        fd, tmp = tempfile.mkstemp(dir=folder, prefix='.devices-')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(self.by_hash, f)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)                     # atomic: power loss leaves old or new
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise


def read_cookie(header, name=DEV_COOKIE):
    """The value of cookie `name` from a Cookie header, or None. Tolerant of other cookies."""
    for part in (header or '').split(';'):
        k, _, v = part.strip().partition('=')
        if k == name:
            return v
    return None


def set_cookie(token, name=DEV_COOKIE):
    return f'{name}={token}; Path={COOKIE_PATH}; Max-Age={MAX_AGE}; HttpOnly; SameSite=Lax'


def clear_cookie(name=DEV_COOKIE):
    return f'{name}=; Path={COOKIE_PATH}; Max-Age=0; HttpOnly; SameSite=Lax'
