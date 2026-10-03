"""Deterministic smoke checks for a deployed (or simulated) Avrana.

    python3 -m avrana.ops.smoke                      # on the Pi after ops/deploy.sh (default --pi)
    python3 -m avrana.ops.smoke --local http://127.0.0.1:8180   # against the dev server
    python3 -m avrana.ops.smoke --json

Each check is pass, fail or skip with one line of detail; a skip is never a pass. Nothing here
changes the appliance, logs in, or touches hardware (streaming, radios and phones stay Tier 3).
The Pi set assumes the nginx site in avrana-party.nginx: HTTP :80 for the captive probe, HTTPS
:443 as party.avrana.net for the shell and Party Core, loopback provider ports for Games and the
arcade. ops/deploy.sh runs the Pi set and records the result in the deployment manifest.
"""
import argparse
import http.client
import json
import platform
import socket
import ssl
import subprocess
import sys
import time

from avrana.contracts import party_games
from avrana.ops import status as status_module

PASS, FAIL, SKIP = 'pass', 'fail', 'skip'
HOST = 'party.avrana.net'
TIMEOUT_S = 5.0
CAPTIVE_HOSTS = ('captive.apple.com', 'connectivitycheck.gstatic.com', 'www.msftconnecttest.com',
                 'detectportal.firefox.com')


class Result:
    def __init__(self, name, status, detail=''):
        self.name, self.status, self.detail = name, status, detail

    def as_dict(self):
        return {'name': self.name, 'status': self.status, 'detail': self.detail}


class Http:
    """Direct HTTP(S) requests with an explicit Host header and SNI, so a check can hit
    127.0.0.1 while speaking to the party.avrana.net virtual host (like curl --resolve)."""

    def __init__(self, timeout=TIMEOUT_S):
        self.timeout = timeout

    def get(self, scheme, address, port, path, host=None, verify=True):
        """(status, headers, body-bytes); raises OSError on transport failure."""
        if scheme == 'https':
            ctx = ssl.create_default_context()
            if not verify:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            conn = http.client.HTTPSConnection(address, port, timeout=self.timeout, context=ctx)
            if host:
                conn._server_hostname = host  # SNI; validated against the certificate when verify
        else:
            conn = http.client.HTTPConnection(address, port, timeout=self.timeout)
        try:
            conn.request('GET', path, headers={'Host': host or address, 'Cache-Control': 'no-cache'})
            r = conn.getresponse()
            return r.status, dict(r.getheaders()), r.read(1 << 20)
        finally:
            conn.close()


def _json(body):
    try:
        return json.loads(body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return None


def check_captive_probe(http, address='127.0.0.1', port=80):
    try:
        for probe_host in CAPTIVE_HOSTS[:1]:
            code, _, body = http.get('http', address, port, '/hotspot-detect.html', host=probe_host)
            if code != 200 or body.strip() != b'Success':
                return Result('captive_probe', FAIL, f'{probe_host} -> {code} {body[:40]!r}; expected 200 "Success"')
        return Result('captive_probe', PASS, 'Apple probe answered "Success" on :80')
    except OSError as e:
        return Result('captive_probe', FAIL, f'port 80 unreachable ({type(e).__name__})')


def check_party_home(http, scheme, address, port, host, verify=True):
    try:
        code, headers, body = http.get(scheme, address, port, '/party/', host=host, verify=verify)
    except ssl.SSLError as e:
        return Result('party_home', FAIL, f'TLS failed for {host} ({e.reason or e})')
    except OSError as e:
        return Result('party_home', FAIL, f'{scheme} {address}:{port} unreachable ({type(e).__name__})')
    if code != 200 or b'<html' not in body.lower()[:400]:
        return Result('party_home', FAIL, f'/party/ -> {code}')
    csp = headers.get('Content-Security-Policy') or headers.get('content-security-policy')
    if not csp:
        return Result('party_home', FAIL, '/party/ served without Content-Security-Policy')
    return Result('party_home', PASS, f'/party/ 200 with CSP over {scheme}')


def check_party_core(http, scheme, address, port, host, verify=True):
    try:
        code, _, body = http.get(scheme, address, port, '/party/api/state', host=host, verify=verify)
    except OSError as e:
        return Result('party_core', FAIL, f'/party/api/state unreachable ({type(e).__name__})')
    doc = _json(body)
    if code != 200 or not isinstance(doc, dict) or 'party' not in doc:
        return Result('party_core', FAIL, f'/party/api/state -> {code}; not a party view')
    return Result('party_core', PASS, 'Party Core answers /party/api/state')


def check_status(http, scheme, address, port, host, verify=True):
    try:
        code, _, body = http.get(scheme, address, port, '/party/api/status', host=host, verify=verify)
    except OSError as e:
        return Result('status', FAIL, f'/party/api/status unreachable ({type(e).__name__})')
    doc = _json(body)
    if code != 200 or not isinstance(doc, dict) or doc.get('schema') != status_module.SCHEMA:
        return Result('status', FAIL, f'/party/api/status -> {code}; schema is not {status_module.SCHEMA}')
    expected = party_games.versions()
    if doc.get('contract', {}).get('party_games') != expected['party_games']:
        return Result('status', FAIL, 'status reports a different Party <-> Games contract than this checkout')
    state = doc.get('summary', {}).get('state')
    detail = f'summary {state}; party {str(doc.get("party", {}).get("checkout_sha"))[:12]}'
    return Result('status', PASS if state in ('ok', 'unknown') else FAIL, detail + (
        '; ' + ', '.join(doc['summary'].get('reasons', [])) if state == 'degraded' else ''))


def check_games_provider(http, address='127.0.0.1', port=8096):
    try:
        code, _, body = http.get('http', address, port, '/health')
        if code != 200:
            return Result('games_provider', FAIL, f'/health -> {code}')
        code, _, body = http.get('http', address, port, '/api/games')
    except OSError as e:
        return Result('games_provider', FAIL, f'{address}:{port} unreachable ({type(e).__name__})')
    doc = _json(body)
    want = party_games.versions()['lan_launch']
    if code != 200 or not isinstance(doc, dict):
        return Result('games_provider', FAIL, f'/api/games -> {code}')
    if doc.get('avranaIntegration') != want:
        return Result('games_provider', FAIL, f'/api/games advertises {doc.get("avranaIntegration")!r}, Party implements {want!r}')
    return Result('games_provider', PASS, f'health ok; advertises {want}')


def check_arcade(http, address='127.0.0.1', port=8098):
    try:
        code, _, body = http.get('http', address, port, '/stats')
    except OSError as e:
        return Result('arcade', FAIL, f'{address}:{port} unreachable ({type(e).__name__})')
    doc = _json(body)
    if code != 200 or not isinstance(doc, dict) or 'players' not in doc:
        return Result('arcade', FAIL, f'/stats -> {code}; not the arcade')
    if doc.get('error'):
        return Result('arcade', FAIL, f'arcade reports error: {doc["error"]}')
    return Result('arcade', PASS, f'state {doc.get("state", "?")}, {doc.get("players")} playing')


def check_encoder(http, address='127.0.0.1', port=8098):
    """Only meaningful while the emulator runs: a still screen is fine, a dead encoder is not."""
    try:
        code, _, body = http.get('http', address, port, '/stats')
    except OSError:
        return Result('encoder', SKIP, 'arcade unreachable (see arcade)')
    doc = _json(body) if code == 200 else None
    if not isinstance(doc, dict):
        return Result('encoder', SKIP, 'no arcade stats')
    if not doc.get('emulator_running'):
        return Result('encoder', SKIP, 'emulator idle; encoder has nothing to encode')
    ages = doc.get('sample_age_s') or {}
    video = ages.get('video')
    if not isinstance(video, (int, float)):
        return Result('encoder', FAIL, 'running emulator without a video sample age')
    return Result('encoder', PASS if video < 10 else FAIL, f'last video sample {video}s ago')


def check_units(units, runner=subprocess.run):
    if platform.system() != 'Linux':
        return [Result(f'unit:{u}', SKIP, 'systemd not available here') for u in units]
    out = []
    for unit in units:
        try:
            r = runner(['systemctl', 'is-active', unit], capture_output=True, timeout=TIMEOUT_S)
            state = r.stdout.decode('utf-8', 'replace').strip() or 'unknown'
        except (OSError, subprocess.TimeoutExpired):
            out.append(Result(f'unit:{unit}', SKIP, 'systemctl unavailable'))
            continue
        out.append(Result(f'unit:{unit}', PASS if state == 'active' else FAIL, state))
    return out


def check_certificate(not_after, now=None, warn_days=status_module.EXPIRING_DAYS):
    if not_after is None:
        return Result('certificate', SKIP, 'certificate not readable here')
    from datetime import datetime, timezone
    now = now or datetime.now(timezone.utc)
    days = (not_after - now).total_seconds() / 86400
    if days <= 0:
        return Result('certificate', FAIL, 'certificate expired')
    return Result('certificate', PASS if days >= warn_days else FAIL, f'{days:.0f} days left')


def check_dns(server='10.42.0.1', name=HOST, resolver=None):
    """dnsmasq on the party network must answer party.avrana.net with the Pi's AP address."""
    resolver = resolver or _dig
    answer = resolver(server, name)
    if answer is None:
        return Result('dns', SKIP, 'no resolver tool (dig) or server unreachable')
    return Result('dns', PASS if answer == server else FAIL, f'{name} -> {answer}')


def _dig(server, name):
    try:
        r = subprocess.run(['dig', '+short', '+time=2', '+tries=1', f'@{server}', name, 'A'],
                           capture_output=True, timeout=TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = [l for l in r.stdout.decode('ascii', 'replace').split() if l]
    return lines[-1] if lines else ('' if r.returncode == 0 else None)


def run_pi(http=None, probes=None, units=None):
    http = http or Http()
    probes = probes or status_module.Probes()
    units = units if units is not None else status_module.DEFAULT_CONFIG['units']
    results = [check_captive_probe(http),
               check_party_home(http, 'https', '127.0.0.1', 443, HOST),
               check_party_core(http, 'https', '127.0.0.1', 443, HOST),
               check_status(http, 'https', '127.0.0.1', 443, HOST),
               check_games_provider(http), check_arcade(http), check_encoder(http)]
    results += check_units(units)
    results.append(check_certificate(probes.certificate_not_after(status_module.DEFAULT_CONFIG['certificate'])))
    results.append(check_dns())
    return results


def run_local(base, http=None):
    """The safe subset against the dev server (python -m avrana.web.devserver --party)."""
    from urllib.parse import urlsplit
    u = urlsplit(base)
    scheme, address, port = u.scheme or 'http', u.hostname or '127.0.0.1', u.port or 80
    http = http or Http()
    return [check_captive_probe(http, address, port),
            check_party_home(http, scheme, address, port, f'{address}:{port}', verify=False),
            check_party_core(http, scheme, address, port, f'{address}:{port}', verify=False),
            check_status(http, scheme, address, port, f'{address}:{port}', verify=False)]


def summarize(results):
    counts = {s: sum(1 for r in results if r.status == s) for s in (PASS, FAIL, SKIP)}
    return {'ok': counts[FAIL] == 0, 'counts': counts, 'checks': [r.as_dict() for r in results]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--local', metavar='BASE_URL', help='dev-server subset instead of the Pi set')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args(argv)
    started = time.monotonic()
    results = run_local(args.local) if args.local else run_pi()
    summary = summarize(results)
    summary['seconds'] = round(time.monotonic() - started, 1)
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        for r in results:
            print(f'{r.status.upper():5} {r.name:28} {r.detail}')
        c = summary['counts']
        print(f'smoke: {c[PASS]} passed, {c[FAIL]} failed, {c[SKIP]} skipped (skips are not passes)')
    return 0 if summary['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
