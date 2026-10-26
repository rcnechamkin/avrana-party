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
    nginx_site    {status: match|differs|unavailable, sha256}: the installed site file against the one in
                  the deployed Party release (AVR-271; deploy, web build and site file are one unit)
    last_attempt  {party_sha, games_sha, at, outcome, backup} or null: the last deploy run that got past validation and how it
                  ended (a rolled-back run leaves the manifest naming the old pair); a note, never a fault, unless outcome is ok
    last_known_good  {party_sha, games_sha, smoke_at, recorded_at, nginx_site_sha256} or null: the last
                  deployment whose smoke checks passed; what `ops/deploy.sh --rollback` returns to
    contract      versions Party implements (+ games_advertises from /api/games)
    services      {unit: active|inactive|failed|not-installed|unknown|unavailable}
    recovery      {units: {unit: {restarts, result, active_for_s}}, failed_game_units: [unit, ...]}: what
                  systemd's own recovery did (AVR-33). A unit restarting after failures, one restarted
                  less than RECENT_RESTART_S ago, one that hit its start limit and a failed native game
                  unit or socket of the live Party session's game degrade; a failed game unit nothing is
                  using, and a unit that came back and stayed up, are notes
    certificate   {not_after, days_left, status: ok|expiring|expired|unavailable}
                  (unavailable is never `ok`: the summary is `unknown` then, AVR-31)
    party_core    {ok, uptime_s, members, session}
    games_provider, arcade   health summaries
    summary       ok|degraded|unknown with reasons
"""
from datetime import datetime, timezone
import hashlib
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
# The certificate directory is root-only (ADR 0016), so the service user cannot read the
# certificate itself. ops/install-party-certificate.sh therefore also writes the one public,
# non-secret fact health needs, the `openssl x509 -enddate` line, here (AVR-31).
CERTIFICATE_RECORD = '/etc/avrana-party/certificate-not-after'
DEFAULT_CONFIG = {
    'manifest': manifest.DEFAULT_PATH,
    'party_checkout': '/home/cody/avrana-party',
    'games_checkout': '/home/cody/avrana-party-games',
    'web_root': '/var/www/avrana-party/web',
    'certificate': '/etc/avrana-party/tls/current/fullchain.pem',
    # The installed nginx site and where the deployed commit's copy lives (tried in order). ops/deploy.sh
    # installs the site file with the deployment (AVR-271); this independent comparison is how a drift
    # between the two (a hand edit, a deployment made by an older script) is noticed.
    'nginx_site': '/etc/nginx/sites-available/avrana-party',
    'nginx_site_sources': ['/opt/avrana-party/current/avrana-party.nginx',
                           '/home/cody/avrana-party/avrana-party.nginx'],
    'last_known_good': None,            # default: last-known-good.json beside the manifest
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


GAME_UNITS = 'avrana-game@*'      # native game instances and their sockets (ADR 0016 section 5)


# An `active` unit that systemd restarted within this many seconds may be mid crash loop: one that
# dies every ~2 s under RestartSec=3 is often sampled `active`. It degrades until it has stayed up.
RECENT_RESTART_S = 60


def unit_recovery(unit, runner=subprocess.run, timeout=PROBE_TIMEOUT_S, clock=time.monotonic):
    """{'restarts': NRestarts, 'result': Result, 'active_for_s': ...} from `systemctl show`, or None
    when unobservable. NRestarts counts systemd's automatic restarts since the unit was last started
    by hand (a deploy's restart sets it back to 0); Result is `success`, `exit-code`,
    `start-limit-hit`, ... `active_for_s` is how long the unit has been in its current active spell:
    ActiveEnterTimestampMonotonic is CLOCK_MONOTONIC in microseconds, the clock `time.monotonic()`
    reads in seconds on Linux. None when the property is missing, 0 (never active) or unparseable."""
    if platform.system() != 'Linux':
        return None
    try:
        out = runner(['systemctl', 'show', '--property=NRestarts', '--property=Result',
                      '--property=ActiveEnterTimestampMonotonic', unit],
                     capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    facts = dict(line.partition('=')[::2] for line in out.stdout.decode('utf-8', 'replace').splitlines() if '=' in line)
    try:
        restarts = int(facts.get('NRestarts', ''))
    except ValueError:
        restarts = None
    result = facts.get('Result') or None
    if restarts is None and result is None:
        return None
    try:
        entered_us = int(facts.get('ActiveEnterTimestampMonotonic', ''))
    except ValueError:
        entered_us = 0
    active_for_s = max(0, int(clock() - entered_us / 1e6)) if entered_us > 0 else None
    return {'restarts': restarts, 'result': result, 'active_for_s': active_for_s}


def failed_units(pattern, runner=subprocess.run, timeout=PROBE_TIMEOUT_S):
    """Names of units matching `pattern` that systemd has in the failed state ([] when none), or
    None when unobservable."""
    if platform.system() != 'Linux':
        return None
    try:
        out = runner(['systemctl', 'list-units', '--all', '--state=failed', '--plain', '--no-legend',
                      '--no-pager', pattern], capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode not in (0, None):
        return None
    names = []
    for line in out.stdout.decode('utf-8', 'replace').splitlines():
        fields = line.split()
        if fields and fields[0] not in ('●', '*'):
            names.append(fields[0])
        elif len(fields) > 1:
            names.append(fields[1])
    return sorted(names)


def _parse_enddate(text):
    """`notAfter=Dec 25 10:00:00 2026 GMT` (openssl x509 -enddate) as an aware datetime, or None."""
    text = text.strip()
    if not text.startswith('notAfter='):
        return None
    try:
        return datetime.strptime(text[len('notAfter='):], '%b %d %H:%M:%S %Y %Z').replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class Probes:
    """Every contact with the machine, in one place, so tests can replace it."""

    def __init__(self, timeout=PROBE_TIMEOUT_S, certificate_record=CERTIFICATE_RECORD):
        self.timeout = timeout
        self.certificate_record = certificate_record

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

    def unit_recovery(self, unit):
        return unit_recovery(unit, timeout=self.timeout)

    def failed_units(self, pattern):
        return failed_units(pattern, timeout=self.timeout)

    def certificate_not_after(self, path):
        """The notAfter instant as an aware datetime, or None when unreadable. On the appliance
        the certificate directory is root-only, so inside the service the certificate itself is
        unreadable by design; the expiry record the installer writes next to it is the fallback
        (a stale record is bounded by the next install, which rewrites it)."""
        return self._enddate_of_file(path) or self._enddate_record(self.certificate_record)

    def _enddate_of_file(self, path):
        try:
            if not Path(path).exists():
                return None
            out = subprocess.run(['openssl', 'x509', '-noout', '-enddate', '-in', str(path)],
                                 capture_output=True, timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return _parse_enddate(out.stdout.decode('ascii', 'replace'))

    def _enddate_record(self, path):
        try:
            return _parse_enddate(Path(path).read_text(encoding='ascii', errors='replace')[:256])
        except (OSError, TypeError):
            return None

    def nginx_site(self, installed, sources):
        """match|differs|unavailable: the installed nginx site file byte for byte against the first
        readable source. Unreadable on either side is unavailable, never a match."""
        try:
            have = hashlib.sha256(Path(installed).read_bytes()).hexdigest()
        except OSError:
            return 'unavailable'
        for source in sources:
            try:
                want = hashlib.sha256(Path(source).read_bytes()).hexdigest()
            except OSError:
                continue
            return 'match' if have == want else 'differs'
        return 'unavailable'

    def nginx_site_sha256(self, installed):
        """sha256 of the installed site file (not a secret), or None."""
        try:
            return hashlib.sha256(Path(installed).read_bytes()).hexdigest()
        except OSError:
            return None

    def last_known_good(self, path):
        """The last-known-good record ops/deploy.sh keeps beside the manifest, or None."""
        try:
            return manifest.read_last_known_good(path)
        except (manifest.ManifestError, OSError):
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


def _public_attempt(deployed):
    attempt = deployed.get('last_attempt') if deployed else None
    return dict(attempt) if isinstance(attempt, dict) else None


def _public_web(release):
    return None if release is None else {'build': release.get('build'), 'commit': release.get('commit')}


NOT_APPLICABLE_CERTIFICATE = {'not_after': None, 'days_left': None, 'status': 'not_applicable'}
NOT_APPLICABLE = {'ok': None, 'not_applicable': True, 'integration': None, 'compatible': None}


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


def _game_slug(unit):
    """'avrana-game@checkers.socket' -> 'checkers' (the Party game id is the unit's instance name)."""
    return unit.partition('@')[2].rpartition('.')[0]


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
    # What systemd's own recovery did (AVR-33). A crash loop under Restart=on-failure with
    # RestartSec=3 never reaches the default start limit, so `is-active` says `activating`, not
    # `failed`: without NRestarts it would look like a unit that is merely starting.
    recovery_of = getattr(probes, 'unit_recovery', lambda unit: None)
    restarts = {}
    for unit, state in services.items():
        facts = recovery_of(unit) if state not in ('not-installed', 'unavailable') else None
        if facts is None:
            continue
        restarts[unit] = facts
        n = facts.get('restarts') or 0
        if facts.get('result') == 'start-limit-hit':
            reasons.append(f'{unit} stopped restarting (start limit hit); see docs/runbooks/service-recovery.md')
        elif state == 'activating' and n > 0:      # between automatic restarts
            reasons.append(f'{unit} is restarting after failures ({n} automatic restarts)')
        elif state == 'active' and n > 0:
            up = facts.get('active_for_s')
            if not isinstance(up, int) or up < RECENT_RESTART_S:
                # Restarted and not yet proven stable (or its uptime cannot be read: fail safe), so a
                # crash loop sampled between crashes is not recorded as a good deploy.
                since = f'up {up} s' if isinstance(up, int) else 'uptime unreadable'
                reasons.append(f'{unit} restarted recently after failures ({n} automatic restarts, {since})')
            else:
                notes.append(f'{unit} came back after {n} automatic restart(s) since it was last started')
    failed_games = getattr(probes, 'failed_units', lambda pattern: [])(GAME_UNITS)
    web = probes.web_release(cfg['web_root'])
    # One deployment unit (AVR-271): the web build must be the deployed Party commit, and the
    # installed nginx site file must be that commit's. Either drift degrades the appliance.
    expected = (deployed['party']['sha'] if deployed else party['checkout_sha'])
    web_commit = web.get('commit') if isinstance(web, dict) else None
    if web_commit and expected and web_commit != expected:
        reasons.append('web build is from a different commit than the deployed Party')
    nginx_site = probes.nginx_site(cfg['nginx_site'], cfg['nginx_site_sources'])
    nginx_sha256 = getattr(probes, 'nginx_site_sha256', lambda path: None)(cfg['nginx_site'])
    lkg_path = cfg.get('last_known_good') or str(Path(str(cfg['manifest'])).with_name('last-known-good.json'))
    lkg = getattr(probes, 'last_known_good', lambda path: None)(lkg_path)
    if nginx_site == 'differs':
        reasons.append('nginx site file differs from the deployed commit (install avrana-party.nginx, docs/runbooks/deploy.md)')
    elif nginx_site == 'unavailable':
        reasons.append('nginx site file unavailable to compare')
    attempt = _public_attempt(deployed)
    if attempt and attempt.get('outcome') != 'ok':
        notes.append(f'the last deployment attempt (party {str(attempt.get("party_sha"))[:12]}) ended {attempt.get("outcome")}; '
                     f'the running pair is the one in "deployment" (see docs/runbooks/deploy.md)')
    # null in the config: this deployment has no such part (hosted staging: TLS ends at the edge, no
    # games provider on 8096, no arcade; docs/design/HOSTED-STAGING.md). Reported as not_applicable,
    # never a reason, never ok-by-default on an appliance (whose config keeps the paths).
    certificate = (NOT_APPLICABLE_CERTIFICATE if cfg['certificate'] is None
                   else _certificate(probes.certificate_not_after(cfg['certificate']), now))
    if certificate['status'] in ('expiring', 'expired'):
        reasons.append(f'certificate {certificate["status"]}')
    elif certificate['status'] == 'unavailable':
        # Not a fault of the certificate, but an expiry nobody can see is a cliff nobody sees
        # coming: never `ok` (AVR-31). `unknown`, like a unit that cannot be observed.
        reasons.append('certificate expiry unavailable')
    provider = (dict(NOT_APPLICABLE) if cfg['games_url'] is None
                else _games(probes.get_json(cfg['games_url'].rstrip('/') + '/api/games'), contract))
    if provider.get('not_applicable'):
        pass
    elif not provider['ok']:
        reasons.append('games provider unreachable')
    elif provider['compatible'] is False:
        reasons.append('games provider advertises a different launch integration')
    arcade = (dict(NOT_APPLICABLE) if cfg['arcade_url'] is None
              else _arcade(probes.get_json(cfg['arcade_url'].rstrip('/') + '/stats')))
    if arcade.get('not_applicable'):
        pass
    elif not arcade['ok']:
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
    # A failed native game unit is a fault only while it matters: it is the game of the live Party
    # session. Any other failed unit is stale (nothing is using it), so it is a note naming the
    # remedy and must not fail a deploy's smoke or trigger --auto-rollback (AVR-33 decision 2026-10-14).
    session = core.get('session') if isinstance(core.get('session'), dict) else None
    live_game = session.get('game') if session and session.get('state') != 'ended' else None
    for unit in failed_games or []:
        if live_game is not None and _game_slug(unit) == live_game:
            reasons.append(f'{unit} is failed and its game is in the live session; see docs/runbooks/service-recovery.md')
        else:
            notes.append(f'{unit} is failed but no live session uses it: sudo systemctl reset-failed {unit} '
                         f'(docs/runbooks/service-recovery.md)')
    # Unobservable failures only matter while a game is live; with none, nothing depends on them.
    games_unobservable = failed_games is None and live_game is not None
    unknown = (any(s == 'unavailable' for s in services.values()) or deployed is None or games_unobservable
               or certificate['status'] == 'unavailable' or nginx_site == 'unavailable')
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
        'web_release': _public_web(web),
        'nginx_site': {'status': nginx_site, 'sha256': nginx_sha256},
        'last_attempt': _public_attempt(deployed),
        'last_known_good': None if lkg is None else {k: lkg.get(k) for k in (
            'party_sha', 'games_sha', 'smoke_at', 'recorded_at', 'nginx_site_sha256')},
        'contract': dict(contract, games_advertises=provider['integration']),
        'services': services,
        'recovery': {'units': restarts, 'failed_game_units': failed_games},
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
                    # the lifecycle bounds this round runs under (AVR-260: the game's, clamped)
                    'session': {'game': session.game_id, 'state': session.state,
                                'launch_timeout_s': session.launch_timeout,
                                'end_timeout_s': session.end_timeout} if session else None}

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
