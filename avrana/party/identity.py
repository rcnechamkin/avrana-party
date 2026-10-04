"""Server-issued device identity (ADR 0003 §2; PARTY-PLATFORM.md §13).

* A device token is `secrets.token_urlsafe(32)` (256 bits), minted only here. A browser that
  presents an unknown, malformed or revoked value is issued a fresh token: a client can never
  choose its identity (unlike the games' `wc-token`, which the browser mints).
* It travels only in a cookie. In production (HTTPS) that is `__Host-avrana_device`:
  `Path=/; Secure; HttpOnly; SameSite=Lax` (ADR 0013, AVR-226). The `__Host-` prefix makes the
  browser refuse the name from any other host, with a `Domain` attribute, or over plain HTTP, so
  a sibling origin (a game page on `games.avrana.net`) cannot plant one. It needs `Path=/`,
  which is safe because game servers do not share the Party's host name.
* For one release the earlier `avrana_device; Path=/party/` cookie is still read, so phones in
  the room keep their member: a request that presents only the old cookie is answered with the
  new one carrying the same token. When both are present the `__Host-` one wins.
* A plain-HTTP loopback server (tests, the dev server: `secure=False`) cannot use the prefix and
  keeps the old name and path.
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

COOKIE = 'avrana_device'                  # the earlier name; also the only one over plain HTTP
COOKIE_PATH = '/party/'
HOST_COOKIE = '__Host-avrana_device'      # production: host-only by the browser's own rule
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


def _values(header, name):
    return [v for k, _, v in (part.strip().partition('=') for part in (header or '').split(';'))
            if k == name]


def read_cookie(header, name=COOKIE):
    """The value of cookie `name` in a Cookie header, or None. Other cookies are ignored.

    Exactly one value, or none at all: a header that carries the name twice is ambiguous and is
    treated as no identity. A browser sends two when a second cookie of the same name was planted
    at a more specific path (`Path=/party/api/`) or from a parent or sibling host name
    (`Domain=…`), and it lists the more specific one first. Taking "the first" would let whoever
    planted it choose the identity this phone presents (session fixation); see ambiguous()."""
    values = _values(header, name)
    return values[0] if len(values) == 1 else None


def presented(header):
    """(token, source) from a Cookie header: source is 'host' (`__Host-avrana_device`), 'legacy'
    (`avrana_device`) or None. Either name carried twice is ambiguous and yields no identity. The
    `__Host-` cookie wins over the old one: a page elsewhere cannot have planted it."""
    host, legacy = _values(header, HOST_COOKIE), _values(header, COOKIE)
    if len(host) > 1 or len(legacy) > 1:
        return None, None
    if host:
        return host[0], 'host'
    if legacy:
        return legacy[0], 'legacy'
    return None, None


def ambiguous(header, name=None):
    """True when the Cookie header carries a device cookie name more than once."""
    names = (name,) if name else (HOST_COOKIE, COOKIE)
    return any(len(_values(header, n)) > 1 for n in names)


def set_cookie(token, secure=True, name=None):
    """The Set-Cookie value for a device token: the `__Host-` cookie when `secure`, else the old
    name and path (a plain-HTTP loopback server cannot set a `__Host-` cookie)."""
    if secure and name is None:
        return f'{HOST_COOKIE}={token}; Path=/; Max-Age={MAX_AGE}; HttpOnly; Secure; SameSite=Lax'
    flags = '; Secure' if secure else ''
    return f'{name or COOKIE}={token}; Path={COOKIE_PATH}; Max-Age={MAX_AGE}; HttpOnly{flags}; SameSite=Lax'
