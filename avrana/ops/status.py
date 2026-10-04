"""The machine-readable appliance status (avrana.status/v0), served as GET /party/api/status.

Answers "what exact Avrana build is running right now?" for people and agents:

    curl -s https://party.avrana.net/party/api/status            # from a phone or the LAN
    curl -s -H 'Host: party.avrana.net' http://127.0.0.1:8191/party/api/status   # on the Pi

Sources, in order of authority: the deployment manifest written by ops/deploy.sh (what was
deployed), the production checkouts (what is on disk now; a mismatch is reported, never hidden),
the installed web release's version.json, systemd unit states, the certificate's expiry and the
provider health endpoints on loopback. Never included: keys, tokens, cookies, environment,
logs, peer addresses, filesystem paths, the operator's login or anything from a request (the
manifest file on the Pi keeps paths and operator; the public document drops them). Every probe is bounded by a timeout and a
failure is reported as unavailable, not as healthy. Results are cached for a few seconds so a
party full of phones cannot turn this into a systemctl storm.

Shape (docs/design/STATUS-ENDPOINT.md):
    schema, generated_at, cached
    deployment    the manifest without paths/operator (or null) and manifest_error
    party, games  {deployed_sha, checkout_sha, dirty, untracked, deployed_dirty, ref, mismatch}
    web_release   {build, commit} or null
    contract      versions Party implements (+ games_advertises from /api/games)
    services      {unit: active|inactive|failed|not-installed|unknown|unavailable}
    certificate   {not_after, days_left, status: ok|expiring|expired|unavailable}
    party_core    {ok, uptime_s, members, session}
    games_provider, arcade   health summaries
    summary       ok|degraded|unknown with reasons
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import threading
import time
import urllib.error
import urllib.request

from avrana.contracts import party_games
from avrana.ops import manifest

SCHEMA = 'avrana.status/v0'
CACHE_S = 5.0
PROBE_TIMEOUT_S = 2.0
EXPIRING_DAYS = 21
DEFAULT_CONFIG = {
    'manifest': manifest.DEFAULT_PATH,
    'party_checkout': '/home/cody/avrana-party',
    'games_checkout': '/home/cody/avrana-party-games',
    'web_root': '/var/www/avrana-party/web',
    'certificate': '/etc/avrana-party/tls/current/fullchain.pem',
    'games_url': 'http://127.0.0.1:8096',
    'arcade_url': 'http://127.0.0.1:8097',      # the arcade's web port serves /stats; :8098 is its Party link
    'units': ['avrana-party-core', 'avranaparty-games', 'avranaparty-arcade', 'nginx',
              'NetworkManager', 'avrana-party-certificate.timer'],
    # Units an appliance may legitimately not have. Automatic certificate renewal is enabled only
    # once its Cloudflare token exists on the Pi (docs/runbooks/party-https.md); until then renewal
    # is manual and the certificate's own expiry check is what guards it. Not installed is reported
    # and is not a fault; installed and not running is a fault like any other unit.
    'optional_units': ['avrana-party-certificate.timer'],
}


def unit_state(unit, runner=subprocess.run, timeout=PROBE_TIMEOUT_S):
    """active|inactive|failed|... as `systemctl is-active` prints it, `not-installed` when systemd
    has no such unit (is-active calls that `inactive` too), `unavailable` without systemctl."""
    if platform.system() != 'Linux':
        return 'unavailable'
    try:
        out = runner(['systemctl', 'is-active', unit], capture_output=True, timeout=timeout)
        state = out.stdout.decode('utf-8', 'replace').strip() or 'unknown'
        if state in ('inactive', 'unknown'):
            load = runner(['systemctl', 'show', '--property=LoadState', '--value', unit],
                          capture_output=True, timeout=timeout)
            if load.stdout.decode('utf-8', 'replace').strip() == 'not-found':
                return 'not-installed'
    except (OSError, subprocess.TimeoutExpired):
        return 'unavailable'
    return state


class Probes:
    """Every contact with the machine, in one place, so tests can replace it."""

    def __init__(self, timeout=PROBE_TIMEOUT_S):
        self.timeout = timeout

    def checkout(self, path):
        try:
            if not Path(path).exists():
                return None
            return manifest.observe_checkout(path)
        except (manifest.ManifestError, OSError):     # OSError: a service user that may not look there
            return None

    def web_release(self, web_root):
        try:
            return manifest.observe_web_release(web_root)
        except OSError:
            return None

    def unit_state(self, unit):
        return unit_state(unit, timeout=self.timeout)

    def certificate_not_after(self, path):
        """The notAfter instant as an aware datetime, or None when unreadable. On the appliance
        the certificate directory is root-only, so inside the service this is None by design."""
        try:
            if not Path(path).exists():
                return None
            out = subprocess.run(['openssl', 'x509', '-noout', '-enddate', '-in', str(path)],
                                 capture_output=True, timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired):
            return None
        text = out.stdout.decode('ascii', 'replace').strip()
        if not text.startswith('notAfter='):
            return None
        try:
            return datetime.strptime(text[len('notAfter='):], '%b %d %H:%M:%S %Y %Z').replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    def get_json(self, url):
        """A small JSON document from loopback, or None. Never raises."""
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as r:
                if r.status != 200:
                    return None
                return json.loads(r.read(65536).decode('utf-8'))
        except (urllib.error.URLError, OSError, ValueError):
            return None


def _repo(name, deployed, observed):
    d = deployed.get(name) if deployed else None
    return {'deployed_sha': d['sha'] if d else None,
            'checkout_sha': observed['sha'] if observed else None,
            'dirty': observed['dirty'] if observed else (d['dirty'] if d else None),
            'untracked': observed.get('untracked') if observed else None,
            'deployed_dirty': d['dirty'] if d else None,
            'ref': observed['ref'] if observed else (d['ref'] if d else None),
            'mismatch': bool(d and observed and d['sha'] != observed['sha'])}


def _public_deployment(deployed):
    """The manifest as phones may see it: no filesystem paths, no operator login."""
    if deployed is None:
        return None
    doc = {k: v for k, v in deployed.items() if k != 'deployed_by'}
    for repo in ('party', 'games'):
        doc[repo] = {k: v for k, v in deployed[repo].items() if k != 'checkout'}
    if isinstance(deployed.get('web_release'), dict):
        doc['web_release'] = {k: v for k, v in deployed['web_release'].items() if k != 'path'}
    return doc


def _public_web(release):
    return None if release is None else {'build': release.get('build'), 'commit': release.get('commit')}


def _certificate(not_after, now):
    if not_after is None:
        return {'not_after': None, 'days_left': None, 'status': 'unavailable'}
    days = (not_after - now).total_seconds() / 86400
    status = 'expired' if days <= 0 else 'expiring' if days < EXPIRING_DAYS else 'ok'
    return {'not_after': not_after.isoformat().replace('+00:00', 'Z'), 'days_left': round(days, 1),
            'status': status}


def _games(doc, contract):
    if doc is None:
        return {'ok': False, 'integration': None, 'compatible': None}
    integration = doc.get('avranaIntegration') if isinstance(doc, dict) else None
    return {'ok': True, 'integration': integration, 'compatible': integration == contract['lan_launch']}


def _arcade(doc):
    if not isinstance(doc, dict):
        return {'ok': False}
    ages = doc.get('sample_age_s') if isinstance(doc.get('sample_age_s'), dict) else {}
    return {'ok': True, 'state': doc.get('state'), 'players': doc.get('players'),
            'max_players': doc.get('max_players'), 'party_managed': doc.get('party_managed'),
            'emulator_running': doc.get('emulator_running'), 'error': doc.get('error'),
            'video_frames': doc.get('video_frames'), 'sample_age_s': ages}


def build_status(config=None, probes=None, party_core=None, now=None):
    """The status document. `party_core` is a callable returning {"uptime_s", "members",
    "session"} from inside the service (or None when built outside it)."""
    cfg = dict(DEFAULT_CONFIG, **(config or {}))
    probes = probes or Probes()
    now = now or datetime.now(timezone.utc)
    reasons = []
    try:
        deployed = manifest.read(cfg['manifest'])
        manifest_error = None
        if deployed is None:
            reasons.append('no deployment manifest')
    except manifest.ManifestError as e:
        # The error names the file; the public document never carries a filesystem path.
        deployed, manifest_error = None, str(e).replace(str(cfg['manifest']), 'deployment manifest')
        reasons.append('deployment manifest malformed')
    party = _repo('party', deployed, probes.checkout(cfg['party_checkout']))
    games = _repo('games', deployed, probes.checkout(cfg['games_checkout']))
    notes = []
    for name, repo in (('party', party), ('games', games)):
        if repo['mismatch']:
            reasons.append(f'{name} checkout differs from the deployment manifest')
        if repo['dirty']:
            # A dirty tree degrades a deployed appliance; on a never-deployed checkout (dev server,
            # laptop) it is merely a fact worth reporting.
            (reasons if deployed is not None else notes).append(f'{name} checkout is dirty')
        if repo['deployed_dirty']:
            reasons.append(f'{name} was deployed from a dirty checkout')
        if repo['untracked']:
            notes.append(f'{name} checkout has {repo["untracked"]} untracked file(s)')
    contract = party_games.versions()
    services = {unit: probes.unit_state(unit) for unit in cfg['units']}
    for unit, state in services.items():
        if state == 'not-installed' and unit in cfg['optional_units']:
            notes.append(f'{unit} is not installed (optional)')
        elif state in ('failed', 'inactive', 'not-installed'):
            reasons.append(f'{unit} is {state.replace("-", " ")}')
    certificate = _certificate(probes.certificate_not_after(cfg['certificate']), now)
    if certificate['status'] in ('expiring', 'expired'):
        reasons.append(f'certificate {certificate["status"]}')
    games_doc = probes.get_json(cfg['games_url'].rstrip('/') + '/api/games')
    provider = _games(games_doc, contract)
    if not provider['ok']:
        reasons.append('games provider unreachable')
    elif provider['compatible'] is False:
        reasons.append('games provider advertises a different launch integration')
    arcade = _arcade(probes.get_json(cfg['arcade_url'].rstrip('/') + '/stats'))
    if not arcade['ok']:
        reasons.append('arcade unreachable')
    elif arcade.get('error'):
        reasons.append('arcade reports an error')
    core = {'ok': False}
    if party_core is not None:
        try:
            core = dict({'ok': True}, **party_core())
        except Exception:  # the status page must not take the party down
            core = {'ok': False}
            reasons.append('party core view failed')
    unknown = any(s == 'unavailable' for s in services.values()) or deployed is None
    summary = 'degraded' if [r for r in reasons if 'unavailable' not in r and 'no deployment' not in r] else (
        'unknown' if unknown else 'ok')
    return {
        'schema': SCHEMA,
        'generated_at': now.replace(microsecond=0).isoformat().replace('+00:00', 'Z'),
        'cached': False,
        'deployment': _public_deployment(deployed),
        'manifest_error': manifest_error,
        'party': party,
        'games': games,
        'web_release': _public_web(probes.web_release(cfg['web_root'])),
        'contract': dict(contract, games_advertises=provider['integration']),
        'services': services,
        'certificate': certificate,
        'party_core': core,
        'games_provider': provider,
        'arcade': arcade,
        'summary': {'state': summary, 'reasons': reasons, 'notes': notes},
    }


class StatusCache:
    def __init__(self, config=None, probes=None, party_core=None, ttl=CACHE_S, clock=time.monotonic):
        self.config, self.probes, self.party_core = config, probes, party_core
        self.ttl, self.clock = ttl, clock
        self.lock = threading.Lock()
        self._doc, self._at = None, None

    def get(self):
        with self.lock:
            if self._doc is not None and self.clock() - self._at < self.ttl:
                return dict(self._doc, cached=True)
            doc = build_status(self.config, self.probes, self.party_core)
            self._doc, self._at = doc, self.clock()
            return doc


def route(service, config=None, probes=None, ttl=CACHE_S):
    """('GET', '/party/api/status') -> handler, for service.make_server's extra_routes."""
    from avrana.party.service import _send
    started = time.monotonic()

    def core_view():
        with service.lock:
            party = service.core.party
            session = party.session
            return {'uptime_s': round(time.monotonic() - started),
                    'members': len(party.members),
                    'session': {'game': session.game_id, 'state': session.state} if session else None}

    cache = StatusCache(config, probes, core_view, ttl=ttl)

    def handler(h, device, body):
        return _send(h, 200, cache.get())

    return {('GET', '/party/api/status'): handler}


def load_config(conf):
    """The optional "status" block of party-core.json merged over the defaults."""
    block = conf.get('status') if isinstance(conf, dict) else None
    cfg = dict(DEFAULT_CONFIG)
    if isinstance(block, dict):
        for key in DEFAULT_CONFIG:
            if key in block:
                cfg[key] = block[key]
    return cfg


def main(argv=None):
    """Print the status built outside the service (no party_core block)."""
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--config', help='party-core.json (its optional "status" block)')
    args = ap.parse_args(argv)
    conf = json.loads(Path(args.config).read_text(encoding='utf-8')) if args.config else {}
    print(json.dumps(build_status(load_config(conf)), indent=2))
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
