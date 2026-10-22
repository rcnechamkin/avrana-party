"""The offline appliance preflight (avrana.preflight/v0): is this Pi ready for a field test?

    python3 -m avrana.ops.preflight                       # on the Pi, as the operator (ssh), no sudo
    python3 -m avrana.ops.preflight --json --out ~/preflight
    python3 -m avrana.ops.preflight --wifi-gate tools/wifi-lab/results/<stamp>_gate_XXXX/gate.json
    python3 -m avrana.ops.preflight --horizon-days 10     # the certificate must outlast a trip
    python3 -m avrana.ops.preflight --local http://127.0.0.1:8180   # dev server; Pi-only checks are UNKNOWN
    python tools/preflight.py --ssh party                 # from the laptop: the same, plus its wifi-lab result

One command over the tooling that already exists; it re-implements none of it:

    revision   avrana.ops.status (the deployment manifest, checkouts, web build, nginx site, last known good)
    services   avrana.ops.status (systemd states and systemd's own recovery, AVR-33)
    serving    avrana.ops.smoke (captive probe, Party Home over HTTPS, Party Core, providers, DNS)
    tls        the certificate each name is SERVED with (names and runway, optionally past --horizon-days)
    network    tools/avrana-topology-check (AP mode, addresses, DNS listeners) and the latest
               tools/wifi-lab gate result (AVR-296); this never measures Wi-Fi itself
    pi         telemetry/pi-health-check.py (its timer's state file when fresh, else one bounded run),
               the clock, free storage, a pending reboot, journal persistence (AVR-29)
    packages   avrana.ops.install_game list/verify and avrana.ops.node_runtime verify
    runtime    the tools the appliance's own scripts need

Every check is PASS, WARN, FAIL or UNKNOWN with a concrete reason. A check that could not observe
its fact is UNKNOWN, never PASS: a missing or stale measurement is not a success. Blocking checks
decide the verdict: any blocking FAIL is NOT_READY, otherwise any blocking UNKNOWN is UNKNOWN
(unless the operator waives that check by id with --waive, which the report records), otherwise
READY. Exit 0 READY, 1 NOT_READY, 3 UNKNOWN, 2 usage.

What it never does: open a connection beyond loopback and the Party AP address (no Internet is
needed or used), use sudo, change, restart or install anything, or read a key, token, cookie or
log line. It adds no endpoint: it runs in the operator's own SSH session and reads the same
public status document phones may read. What the server cannot observe is listed every run in
`physically_unverified`: a PASS here is not a phone test.
"""
import argparse
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

from avrana import REPO_ROOT
from avrana.contracts import party_games
from avrana.ops import smoke as smoke_module
from avrana.ops import status as status_module

SCHEMA = 'avrana.preflight/v0'
# Loopback requests never go through an http_proxy from the environment.
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
PASS, WARN, FAIL, UNKNOWN = 'PASS', 'WARN', 'FAIL', 'UNKNOWN'
READY, NOT_READY = 'READY', 'NOT_READY'
EXIT = {READY: 0, NOT_READY: 1, UNKNOWN: 3}
RANK = {PASS: 0, WARN: 1, UNKNOWN: 2, FAIL: 3}

PARTY_CONFIG = '/etc/avrana-party/party-core.json'
PARTY_CORE_URL = 'http://127.0.0.1:8191'
AP_ADDRESS = '10.42.0.1'
AP_INTERFACE = 'wlan0'
PI_HEALTH_STATE = '/run/avrana/pi-health.json'
PI_HEALTH_SCRIPTS = ('/opt/avrana-telemetry/pi-health-check.py', str(REPO_ROOT / 'telemetry' / 'pi-health-check.py'))
TOPOLOGY_CHECK = str(REPO_ROOT / 'tools' / 'avrana-topology-check')
NODE_RUNTIMES = '/opt/avrana-runtimes'
OFFLINE_MARK = '/run/avrana-offline'
REBOOT_REQUIRED = '/run/reboot-required'
PERSISTENT_JOURNAL = '/var/log/journal'
# Provisional, like the wifi-lab gate's: chosen so a normal party night and one update fit.
STORAGE = {'/': {'warn_bytes': 2 << 30, 'fail_bytes': 512 << 20, 'warn_pct': 10.0, 'fail_pct': 5.0},
           '/var/lib': {'warn_bytes': 1 << 30, 'fail_bytes': 256 << 20, 'warn_pct': 10.0, 'fail_pct': 5.0}}
PI_HEALTH_MAX_AGE_S = 30 * 60
WIFI_GATE_MAX_AGE_H = 24.0
CLOCK_SKEW_S = 120
WIFI_GATE_SCHEMA = 'avrana.wifi-gate/v1'
COMMAND_TIMEOUT_S = 10.0
PI_HEALTH_TIMEOUT_S = 40.0
REQUIRED_UNITS = ('avrana-party-core', 'avranaparty-games', 'nginx')
REQUIRED_TOOLS = ('systemctl', 'openssl', 'nginx', 'git', 'nft', 'nmcli', 'iw')
PYTHON_MINIMUM = (3, 11)

# What no server-side check can show (docs/TESTING.md Tier 3). Always reported.
PHYSICALLY_UNVERIFIED = [
    'a phone joins the Party Wi-Fi and gets an address (iPhone and Android, network forgotten first)',
    'the phone OS treats the network as offline-but-usable (captive sheet, "no internet" prompts, mobile data fallback)',
    'iPhone Safari and Android Chrome trust the served certificate and open https://party.avrana.net',
    'the join card QR code scans and lands on Party Home',
    'Wi-Fi capacity with the real number of phones (the wifi-lab gate measures one Android client)',
    'phones staying connected through screen lock, app switching and battery saver',
    'sound, vibration, rotation and on-screen keyboards on the real devices',
    'a TV or second screen, if the night uses one',
]


def check(check_id, category, status, reason, blocking=True, detail=None):
    doc = {'id': check_id, 'category': category, 'status': status, 'blocking': blocking, 'reason': reason}
    if detail is not None:
        doc['detail'] = detail
    return doc


def _iso(dt):
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _parse_time(text):
    """An ISO 8601 instant as an aware datetime; a naive one is local time (as wifi-lab writes it)."""
    if not isinstance(text, str):
        return None
    try:
        value = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        return None
    return value if value.tzinfo else value.astimezone()


def run_bounded(cmd, timeout=COMMAND_TIMEOUT_S, input_text=None):
    """(returncode or None, stdout, error). Never raises; a hung command is abandoned, not awaited."""
    try:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             start_new_session=hasattr(os, 'setsid'))
    except OSError as e:
        return None, '', f'cannot start {cmd[0]}: {e.strerror or e}'
    try:
        out, err = p.communicate(input_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            if hasattr(os, 'killpg'):
                os.killpg(p.pid, 9)
            else:
                p.kill()
        except OSError:
            pass
        return None, '', f'{cmd[0]} timed out after {timeout:g} s'
    return p.returncode, out, '' if p.returncode == 0 else (err.strip()[:200] or f'exit {p.returncode}')


class Probes:
    """Every contact with the machine, in one place, so tests replace it. Nothing here writes."""

    def __init__(self, party_core_url=PARTY_CORE_URL, host=smoke_module.HOST, timeout=COMMAND_TIMEOUT_S):
        self.party_core_url, self.host, self.timeout = party_core_url.rstrip('/'), host, timeout

    def is_appliance(self):
        return platform.system() == 'Linux' and Path('/etc/avrana-party').is_dir()

    def party_config(self, path=PARTY_CONFIG):
        """(config dict or None, error or None)."""
        try:
            return json.loads(Path(path).read_text(encoding='utf-8')), None
        except FileNotFoundError:
            return None, 'not found'
        except PermissionError:
            return None, 'not readable by this user'
        except (OSError, ValueError) as e:
            return None, f'unreadable ({type(e).__name__})'

    def status_doc(self, status_config):
        """The live service's /party/api/status over loopback (it includes Party Core's own view), else
        one built here; (doc, source). The source says which, because the second has no party_core."""
        req = urllib.request.Request(self.party_core_url + '/party/api/status', headers={'Host': self.host})
        try:
            with _DIRECT.open(req, timeout=self.timeout) as r:
                doc = json.loads(r.read(1 << 20).decode('utf-8'))
                if isinstance(doc, dict) and doc.get('schema') == status_module.SCHEMA:
                    return doc, 'party-core'
        except (urllib.error.URLError, OSError, ValueError):
            pass
        return status_module.build_status(status_config), 'local'

    def smoke(self):
        """The deploy's own smoke checks, minus those this preflight reads in more detail elsewhere."""
        http = smoke_module.Http(timeout=self.timeout)
        return [smoke_module.check_captive_probe(http),
                smoke_module.check_party_home(http, 'https', '127.0.0.1', 443, self.host),
                smoke_module.check_party_core(http, 'https', '127.0.0.1', 443, self.host),
                smoke_module.check_games_provider(http), smoke_module.check_arcade(http),
                smoke_module.check_encoder(http)]

    def smoke_local(self, base):
        return smoke_module.run_local(base, smoke_module.Http(timeout=self.timeout))

    def local_status(self, base):
        try:
            with _DIRECT.open(base.rstrip('/') + '/party/api/status', timeout=self.timeout) as r:
                doc = json.loads(r.read(1 << 20).decode('utf-8'))
            return (doc, 'party-core') if isinstance(doc, dict) else (None, 'unreachable')
        except (urllib.error.URLError, OSError, ValueError):
            return None, 'unreachable'

    def resolve(self, name, server=AP_ADDRESS):
        """The A record the Party's dnsmasq gives for `name`, '' for no answer, None when not asked."""
        answer = smoke_module._dig(server, name) if shutil.which('dig') else None
        return answer if answer is not None else dns_query(server, name, self.timeout)

    def served_certificate(self, name, address='127.0.0.1', port=443):
        """What a phone asking for `name` receives: {verified, error, not_after, names} or None when the
        port is unreachable. Verified against the system trust store (no -k)."""
        ctx = ssl.create_default_context()
        try:
            with socket.create_connection((address, port), self.timeout) as raw:
                with ctx.wrap_socket(raw, server_hostname=name) as tls:
                    cert = tls.getpeercert()
            names = [v for k, v in cert.get('subjectAltName', ()) if k == 'DNS']
            not_after = datetime.fromtimestamp(ssl.cert_time_to_seconds(cert['notAfter']), timezone.utc)
            return {'verified': True, 'error': None, 'not_after': not_after, 'names': names}
        except ssl.SSLCertVerificationError as e:
            facts = self._unverified_certificate(name, address, port)
            return dict(facts or {'not_after': None, 'names': []}, verified=False,
                        error=e.verify_message or str(e.reason or e))
        except ssl.SSLError as e:
            return {'verified': False, 'error': f'TLS failed ({e.reason or e})', 'not_after': None, 'names': []}
        except OSError:
            return None

    def _unverified_certificate(self, name, address, port):
        ctx = ssl.create_default_context()
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        try:
            with socket.create_connection((address, port), self.timeout) as raw:
                with ctx.wrap_socket(raw, server_hostname=name) as tls:
                    der = tls.getpeercert(binary_form=True)
        except OSError:
            return None
        try:
            p = subprocess.run(['openssl', 'x509', '-inform', 'DER', '-noout', '-enddate', '-ext', 'subjectAltName'],
                               input=der, capture_output=True, timeout=self.timeout)
            out = p.stdout.decode('ascii', 'replace')
        except (OSError, subprocess.TimeoutExpired):
            return None
        end = next((status_module._parse_enddate(line) for line in out.splitlines() if line.startswith('notAfter=')), None)
        return {'not_after': end, 'names': re.findall(r'DNS:([^,\s]+)', out)}

    def disk(self, path):
        try:
            u = shutil.disk_usage(path)
            return {'total': u.total, 'free': u.free}
        except OSError:
            return None

    def pi_health(self, now):
        """(document or None, source, error). The timer's state file when fresh, else one bounded run."""
        try:
            st = Path(PI_HEALTH_STATE).stat()
            if now.timestamp() - st.st_mtime <= PI_HEALTH_MAX_AGE_S:
                return json.loads(Path(PI_HEALTH_STATE).read_text(encoding='utf-8')), 'timer state file', None
        except (OSError, ValueError):
            pass
        script = next((s for s in PI_HEALTH_SCRIPTS if Path(s).is_file()), None)
        if script is None:
            return None, 'none', 'pi-health-check.py not found'
        rc, out, err = run_bounded([sys.executable, script], PI_HEALTH_TIMEOUT_S)
        try:
            return json.loads(out), 'one bounded run', None
        except ValueError:
            return None, 'one bounded run', err or 'no JSON'

    def clock(self):
        """{'synchronized': bool or None, 'now': aware datetime}."""
        rc, out, _ = run_bounded(['timedatectl', 'show', '--property=NTPSynchronized', '--value'], self.timeout)
        synced = {'yes': True, 'no': False}.get(out.strip()) if rc == 0 else None
        return {'synchronized': synced, 'now': datetime.now(timezone.utc)}

    def exists(self, path):
        return os.path.lexists(path)

    def journal_storage(self):
        """'persistent' | 'volatile' | None, from whether journald keeps /var/log/journal."""
        if platform.system() != 'Linux':
            return None
        rc, out, _ = run_bounded(['journalctl', '--header', '--no-pager', '-n', '0'], self.timeout)
        if rc == 0 and '/var/log/journal/' in out:
            return 'persistent'
        if rc == 0 and '/run/log/journal/' in out:
            return 'volatile'
        return 'persistent' if Path(PERSISTENT_JOURNAL).is_dir() and any(Path(PERSISTENT_JOURNAL).iterdir()) else None

    def packages(self):
        """(rows, refused, error) from install-game's own listing, then each row's verify problems."""
        from avrana.ops import install_game
        out, err = io.StringIO(), io.StringIO()
        try:
            rc = install_game.main(['list', '--json'], out=out, err=err)
        except Exception as e:      # an unreadable records directory must be UNKNOWN, not a crash
            return None, None, f'{type(e).__name__}'
        if rc != 0:
            return None, None, err.getvalue().strip()[:200] or f'exit {rc}'
        try:
            doc = json.loads(out.getvalue())
        except ValueError:
            return None, None, 'listing is not JSON'
        rows = []
        for row in doc.get('installed', []):
            vout, verr = io.StringIO(), io.StringIO()
            try:
                vrc = install_game.main(['verify', row['id']], out=vout, err=verr)
            except Exception as e:
                vrc, verr = 1, io.StringIO(type(e).__name__)
            rows.append({'id': row['id'], 'version': row.get('version'), 'ok': vrc == 0,
                         'problems': verr.getvalue().strip().splitlines()[:5]})
        return rows, doc.get('refused', []), None

    def node_runtime(self):
        """None when no runtime is installed (it is optional), else (ok, message)."""
        if not Path(NODE_RUNTIMES).is_dir():
            return None
        from avrana.ops import node_runtime
        out, err = io.StringIO(), io.StringIO()
        try:
            rc = node_runtime.main(['verify'], out=out, err=err)
        except Exception as e:
            return False, type(e).__name__
        return rc == 0, (out.getvalue() + err.getvalue()).strip().splitlines()[-1:] or ['']

    def topology(self):
        """[(level, text)] from tools/avrana-topology-check, or (None, error)."""
        bash = shutil.which('bash')
        if bash is None or not Path(TOPOLOGY_CHECK).is_file():
            return None, 'avrana-topology-check or bash not available', None
        rc, out, err = run_bounded([bash, TOPOLOGY_CHECK, str(REPO_ROOT)], 20.0)
        lines = [tuple(line.split(' ', 1)) for line in out.splitlines() if re.match(r'^(PASS|FAIL|WARN|INFO) ', line)]
        return (lines, None, rc) if lines else (None, err or 'no output', rc)

    def ap_channel(self):
        rc, out, _ = run_bounded(['iw', 'dev', AP_INTERFACE, 'info'], self.timeout)
        m = re.search(r'channel (\d+)', out) if rc == 0 else None
        return int(m.group(1)) if m else None

    def which(self, tool):
        return shutil.which(tool) is not None or any(Path(d, tool).exists() for d in ('/usr/sbin', '/sbin'))

    def python_version(self):
        return sys.version_info[:3]


def dns_query(server, name, timeout=COMMAND_TIMEOUT_S):
    """One plain UDP A query (stdlib only), for appliances without dig. The answer's last A record,
    '' when the server answered without one, None when it did not answer."""
    import random
    import struct
    qid = random.randrange(1 << 16)
    try:
        labels = [p.encode('ascii') for p in name.strip('.').split('.')]
    except UnicodeEncodeError:
        return None
    if not labels or any(not 0 < len(p) < 64 for p in labels):
        return None
    qname = b''.join(bytes([len(p)]) + p for p in labels) + b'\0'
    packet = struct.pack('>HHHHHH', qid, 0x0100, 1, 0, 0, 0) + qname + struct.pack('>HH', 1, 1)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(min(timeout, 3.0))
            s.sendto(packet, (server, 53))
            data, _ = s.recvfrom(4096)
    except OSError:
        return None
    try:
        rid, flags, qd, an = struct.unpack('>HHHH', data[:8])
        if rid != qid:
            return None
        pos = 12
        for _ in range(qd):
            while data[pos]:
                pos += data[pos] + 1
            pos += 5
        answer = ''
        for _ in range(an):
            if data[pos] & 0xC0 == 0xC0:
                pos += 2
            else:
                while data[pos]:
                    pos += data[pos] + 1
                pos += 1
            rtype, _, _, rdlen = struct.unpack('>HHIH', data[pos:pos + 10])
            pos += 10
            if rtype == 1 and rdlen == 4:
                answer = '.'.join(str(b) for b in data[pos:pos + 4])
            pos += rdlen
        return answer
    except (IndexError, struct.error):
        return None


# ---- evaluation: pure functions of the facts, tested without a Pi ------------------------------------

def revision_checks(doc, source):
    """Exact Party and Games revisions, and whether what runs is what was deployed."""
    out = []
    if doc is None:
        return [check('revision.status', 'revision', UNKNOWN, 'no status document (Party Core unreachable and none built)')]
    deployment = doc.get('deployment')
    if deployment is None:
        why = doc.get('manifest_error') or 'no deployment manifest'
        out.append(check('revision.manifest', 'revision', UNKNOWN,
                         f'{why}: the deployed revisions cannot be named (ops/deploy.sh writes it)'))
    for name in ('party', 'games'):
        repo = doc.get(name) or {}
        sha = repo.get('deployed_sha')
        if repo.get('mismatch'):
            out.append(check(f'revision.{name}', 'revision', FAIL,
                             f'{name} checkout is at {str(repo.get("checkout_sha"))[:12]} but {str(sha)[:12]} was deployed',
                             detail=repo))
        elif repo.get('deployed_dirty'):
            out.append(check(f'revision.{name}', 'revision', FAIL, f'{name} {str(sha)[:12]} was deployed from a dirty checkout',
                             detail=repo))
        elif sha:
            level = WARN if repo.get('dirty') else PASS
            note = ' (the checkout has local changes since)' if repo.get('dirty') else ''
            out.append(check(f'revision.{name}', 'revision', level, f'{name} deployed at {sha}{note}', detail=repo))
        else:
            out.append(check(f'revision.{name}', 'revision', UNKNOWN,
                             f'{name}: no deployed revision recorded; checkout at {repo.get("checkout_sha") or "unknown"}',
                             detail=repo))
    web = doc.get('web_release') or {}
    party_sha = (doc.get('party') or {}).get('deployed_sha')
    if not web.get('commit'):
        out.append(check('revision.web_release', 'revision', UNKNOWN, 'installed web build has no readable version.json'))
    elif party_sha and web['commit'] != party_sha:
        out.append(check('revision.web_release', 'revision', FAIL,
                         f'web build {web["commit"][:12]} is not the deployed Party {party_sha[:12]}'))
    else:
        out.append(check('revision.web_release', 'revision', PASS, f'web build {web.get("build")} from {web["commit"][:12]}'))
    site = (doc.get('nginx_site') or {}).get('status')
    out.append(check('revision.nginx_site', 'revision',
                     {'match': PASS, 'differs': FAIL}.get(site, UNKNOWN),
                     {'match': 'installed nginx site is the deployed commit\'s',
                      'differs': 'installed nginx site differs from the deployed commit (docs/runbooks/deploy.md)'}.get(
                         site, 'nginx site file could not be compared')))
    lkg = doc.get('last_known_good')
    out.append(check('revision.last_known_good', 'revision', PASS if lkg else WARN,
                     f'rollback target: party {str(lkg.get("party_sha"))[:12]}, games {str(lkg.get("games_sha"))[:12]}'
                     if lkg else 'no last-known-good record: `ops/deploy.sh --rollback` has no target', blocking=False))
    contract = doc.get('contract') or {}
    want = party_games.versions()
    if contract.get('party_games') and contract.get('party_games') != want['party_games']:
        out.append(check('revision.contract', 'revision', FAIL,
                         f'running Party implements {contract.get("party_games")}, this tool {want["party_games"]}'))
    if source == 'local':
        out.append(check('revision.source', 'revision', WARN,
                         'Party Core did not answer /party/api/status on loopback; the status was built by this tool',
                         blocking=False))
    return out


def service_checks(doc, optional=tuple(status_module.DEFAULT_CONFIG['optional_units'])):
    if doc is None:
        return [check('services', 'services', UNKNOWN, 'no status document')]
    out = []
    recovery = (doc.get('recovery') or {}).get('units') or {}
    services = doc.get('services') if isinstance(doc.get('services'), dict) else {}
    for unit in REQUIRED_UNITS:
        if unit not in services:
            out.append(check(f'service.{unit}', 'services', UNKNOWN, f'{unit} is not in the status document'))
    for unit, state in services.items():
        facts = recovery.get(unit) or {}
        n = facts.get('restarts') or 0
        if state == 'active' and n and (facts.get('active_for_s') or 0) < status_module.RECENT_RESTART_S:
            out.append(check(f'service.{unit}', 'services', FAIL, f'{unit} restarted {n} time(s) after failures and is not yet stable'))
        elif state == 'active':
            out.append(check(f'service.{unit}', 'services', PASS,
                             f'{unit} active' + (f' (came back after {n} automatic restart(s))' if n else '')))
        elif state == 'not-installed' and unit in optional:
            out.append(check(f'service.{unit}', 'services', PASS, f'{unit} not installed (optional)', blocking=False))
        elif state in ('unavailable', 'unknown'):
            out.append(check(f'service.{unit}', 'services', UNKNOWN, f'{unit}: systemd state unavailable'))
        elif facts.get('result') == 'start-limit-hit':
            out.append(check(f'service.{unit}', 'services', FAIL,
                             f'{unit} stopped restarting (start limit hit); docs/runbooks/service-recovery.md'))
        else:
            out.append(check(f'service.{unit}', 'services', FAIL, f'{unit} is {state}'))
    failed = (doc.get('recovery') or {}).get('failed_game_units')
    if failed:
        out.append(check('service.game_units', 'services', WARN,
                         f'failed native game unit(s): {", ".join(failed)} (sudo systemctl reset-failed ...)', blocking=False))
    core = doc.get('party_core') or {}
    session = core.get('session') if isinstance(core.get('session'), dict) else None
    if session and session.get('state') != 'ended':
        out.append(check('session.live', 'services', WARN,
                         f'a {session.get("game")} session is {session.get("state")}: a deploy refuses without --force-busy',
                         blocking=False))
    return out


SMOKE_LEVEL = {'pass': PASS, 'fail': FAIL, 'skip': UNKNOWN}


def smoke_checks(results):
    return [check(f'serving.{r.name}', 'serving', SMOKE_LEVEL.get(r.status, UNKNOWN), r.detail or r.status,
                  blocking=r.name != 'encoder') for r in results]


def tls_checks(names, served, now, horizon_days=0):
    """One check per name a phone will ask for: verified, covering the name, and lasting past the horizon."""
    out = []
    horizon = now + timedelta(days=horizon_days)
    for name in names:
        facts = served.get(name)
        cid = f'tls.{name}'
        if facts is None:
            out.append(check(cid, 'tls', FAIL, f'nothing answers HTTPS on 127.0.0.1:443 for {name}'))
            continue
        covered = any(_name_matches(pattern, name) for pattern in facts.get('names') or [])
        end = facts.get('not_after')
        days = None if end is None else round((end - now).total_seconds() / 86400, 1)
        detail = {'not_after': _iso(end) if end else None, 'days_left': days, 'names': facts.get('names')}
        if not facts.get('verified'):
            why = facts.get('error') or 'not verified'
            if facts.get('names') and not covered:
                why += f'; the served certificate names {", ".join(facts["names"])}'
            out.append(check(cid, 'tls', FAIL, f'{name}: a phone would refuse the certificate ({why})', detail=detail))
        elif not covered:
            out.append(check(cid, 'tls', FAIL, f'{name} is not among the served names {facts.get("names")}', detail=detail))
        elif end is None:
            out.append(check(cid, 'tls', UNKNOWN, f'{name}: expiry unreadable', detail=detail))
        elif end <= now:
            out.append(check(cid, 'tls', FAIL, f'{name}: certificate expired {_iso(end)}', detail=detail))
        elif end <= horizon:
            out.append(check(cid, 'tls', FAIL,
                             f'{name}: certificate expires {_iso(end)}, inside the {horizon_days}-day horizon; renew before leaving '
                             '(docs/runbooks/party-https.md; renewal needs the Internet)', detail=detail))
        elif days < status_module.EXPIRING_DAYS + horizon_days:
            out.append(check(cid, 'tls', WARN, f'{name}: {days} days left (renewal window is {status_module.EXPIRING_DAYS} days)',
                             detail=detail))
        else:
            out.append(check(cid, 'tls', PASS, f'{name}: verified, {days} days left', detail=detail))
    return out


def _name_matches(pattern, name):
    pattern, name = pattern.lower(), name.lower()
    if pattern.startswith('*.'):
        return name.endswith(pattern[1:]) and name.count('.') == pattern.count('.')
    return pattern == name


def dns_checks(names, answers, server=AP_ADDRESS):
    out = []
    for name in names:
        got = answers.get(name)
        if got is None:
            out.append(check(f'dns.{name}', 'network', UNKNOWN, f'{server} did not answer for {name}'))
        elif got == server:
            out.append(check(f'dns.{name}', 'network', PASS, f'{name} -> {got} from the Party DNS'))
        else:
            out.append(check(f'dns.{name}', 'network', FAIL, f'{name} -> {got or "no A record"}; phones need {server}'))
    return out


def storage_checks(usage, thresholds=STORAGE):
    out = []
    for path, t in thresholds.items():
        u = usage.get(path)
        if u is None or not u.get('total'):
            out.append(check(f'storage.{path}', 'pi', UNKNOWN, f'free space on {path} unreadable'))
            continue
        pct = 100.0 * u['free'] / u['total']
        text = f'{path}: {u["free"] / (1 << 30):.1f} GiB free ({pct:.0f}%)'
        if u['free'] < t['fail_bytes'] or pct < t['fail_pct']:
            out.append(check(f'storage.{path}', 'pi', FAIL, text + ' (below the minimum)', detail=u))
        elif u['free'] < t['warn_bytes'] or pct < t['warn_pct']:
            out.append(check(f'storage.{path}', 'pi', WARN, text + ' (low)', detail=u))
        else:
            out.append(check(f'storage.{path}', 'pi', PASS, text, detail=u))
    return out


PI_HEALTH_LEVEL = {'HEALTHY': PASS, 'DEGRADED': WARN, 'FIRMWARE_MAILBOX_SUSPECT': FAIL,
                   'POWER_THROTTLE_DETECTED': FAIL, 'UNKNOWN': UNKNOWN}


def pi_checks(health, health_source, health_error, clock, deployed_at, reboot_required, journal, reference=None):
    out = []
    if not isinstance(health, dict):
        health_error, health = health_error or 'not a JSON object', None
    if health is None:
        out.append(check('pi.health', 'pi', UNKNOWN, f'Pi health unavailable ({health_error})'))
    else:
        state = health.get('state', 'UNKNOWN')
        reasons = '; '.join(health.get('reasons') or []) or 'no reasons given'
        out.append(check('pi.health', 'pi', PI_HEALTH_LEVEL.get(state, UNKNOWN),
                         f'{state} ({health_source}): {reasons}' if state != 'HEALTHY' else f'HEALTHY ({health_source})',
                         detail={'state': state, 'evidence_ts': (health.get('evidence') or {}).get('ts')}))
    # Certificate runway and the gate's age are computed from this clock, and an offline Pi without a
    # battery-backed RTC can be days off. Trusted: NTP synchronized, or within CLOCK_SKEW_S of the laptop's
    # clock passed by tools/preflight.py (--reference-time). Otherwise UNKNOWN (waivable after checking `date`).
    now = clock['now']
    synced = clock.get('synchronized')
    skew = None if reference is None else (now - reference).total_seconds()
    if deployed_at is not None and now < deployed_at:
        out.append(check('pi.clock', 'pi', FAIL,
                         f'the clock ({_iso(now)}) is before the last deployment ({_iso(deployed_at)}): '
                         'certificate and staleness checks would be wrong'))
    elif skew is not None and abs(skew) > CLOCK_SKEW_S:
        out.append(check('pi.clock', 'pi', FAIL,
                         f'the clock ({_iso(now)}) is {abs(skew):.0f} s {"ahead of" if skew > 0 else "behind"} the laptop\'s: '
                         'certificate and staleness checks would be wrong (set it, e.g. `sudo date -s`, before the party)'))
    elif skew is not None:
        out.append(check('pi.clock', 'pi', PASS, f'{_iso(now)}, within {abs(skew):.0f} s of the laptop\'s clock'))
    elif synced:
        out.append(check('pi.clock', 'pi', PASS, f'{_iso(now)}, NTP synchronized'))
    else:
        out.append(check('pi.clock', 'pi', UNKNOWN,
                         f'{_iso(now)} is ' + ('not NTP synchronized' if synced is False else 'of unknown sync state') +
                         ': run from the laptop (tools/preflight.py compares the clocks), or check `date` and --waive pi.clock'))
    out.append(check('pi.reboot_required', 'pi', WARN if reboot_required else PASS,
                     'a package update asks for a reboot; do it before guests arrive, not during'
                     if reboot_required else 'no pending reboot', blocking=False))
    out.append(check('pi.journal', 'pi', {'persistent': PASS, 'volatile': WARN}.get(journal, UNKNOWN),
                     {'persistent': 'journal is persistent: logs survive a reboot',
                      'volatile': 'journal is volatile: a reboot loses the evidence (AVR-29, docs/runbooks/logs-and-retention.md)'}.get(
                         journal, 'journal storage unknown'), blocking=False))
    return out


def package_checks(rows, refused, error, node):
    out = []
    if error is not None:
        out.append(check('packages.installed', 'packages', UNKNOWN, f'install-game list failed: {error}'))
    else:
        for r in rows:
            out.append(check(f'packages.{r["id"]}', 'packages', PASS if r['ok'] else FAIL,
                             f'{r["id"]} {r.get("version")}: ' + ('every staged file matches its install record' if r['ok']
                                                                   else '; '.join(r['problems']) or 'verify failed')))
        for problem in refused or []:
            out.append(check('packages.refused', 'packages', FAIL, f'install record refused: {problem}'))
        if not rows and not refused:
            out.append(check('packages.installed', 'packages', PASS, 'no .avrgame packages installed (none required)',
                             blocking=False))
    if node is None:
        out.append(check('runtime.node', 'runtime', PASS, 'optional Node runtime not installed', blocking=False))
    else:
        ok, message = node
        out.append(check('runtime.node', 'runtime', PASS if ok else FAIL,
                         'pinned Node runtime verifies' if ok else f'Node runtime verify failed: {" ".join(message)}'))
    return out


def runtime_checks(have, python_version):
    out = [check('runtime.python', 'runtime', PASS if tuple(python_version[:2]) >= PYTHON_MINIMUM else FAIL,
                 f'python {".".join(map(str, python_version))} (needs {".".join(map(str, PYTHON_MINIMUM))}+)')]
    missing = [t for t in REQUIRED_TOOLS if not have.get(t)]
    out.append(check('runtime.tools', 'runtime', FAIL if missing else PASS,
                     f'missing: {", ".join(missing)}' if missing else f'present: {", ".join(REQUIRED_TOOLS)}'))
    if not have.get('dig'):
        out.append(check('runtime.dig', 'runtime', PASS, 'dig absent: DNS is asked with a built-in query', blocking=False))
    return out


TOPOLOGY_LEVEL = {'PASS': PASS, 'FAIL': FAIL, 'WARN': WARN}


# tools/avrana-topology-check asserts the DEVELOPMENT topology (home LAN on eth0). At a venue there is no
# upstream, which is the point of the appliance, so those assertions are notes here, never failures.
UPSTREAM_ONLY = ('upstream path',)
TOPOLOGY_MIN_ASSERTIONS = 8          # the script makes about a dozen; fewer means it stopped part-way


def topology_checks(lines, error, returncode=None):
    if lines is None:
        return [check('network.topology', 'network', UNKNOWN, f'topology check did not run ({error})')]
    asserted = [(level, t) for level, t in lines if level in ('PASS', 'FAIL', 'WARN')]
    upstream = [t for level, t in asserted if level != 'PASS' and t.startswith(UPSTREAM_ONLY)]
    asserted = [(level, t) for level, t in asserted if not (level != 'PASS' and t.startswith(UPSTREAM_ONLY))]
    fails = [t for level, t in asserted if level == 'FAIL']
    warns = [t for level, t in asserted if level == 'WARN']
    # INFO lines (home-LAN address, gateway) stay out of the saved document.
    detail = {'lines': [f'{level} {text}' for level, text in asserted], 'upstream_notes': upstream}
    if fails:
        return [check('network.topology', 'network', FAIL, '; '.join(fails), detail=detail)]
    if len(asserted) + len(upstream) < TOPOLOGY_MIN_ASSERTIONS:
        return [check('network.topology', 'network', UNKNOWN,
                      f'the topology check stopped after {len(asserted)} assertion(s)'
                      + (f' (exit {returncode})' if returncode not in (None, 0) else ''), detail=detail)]
    reason = '; '.join(warns) if warns else f'{len(asserted)} topology assertions passed'
    if upstream:
        reason += ' (no upstream: expected away from home)'
    return [check('network.topology', 'network', WARN if warns else PASS, reason, detail=detail)]


def wifi_checks(gate, now, current_channel, max_age_h=WIFI_GATE_MAX_AGE_H, source=None, check_channel=False):
    """The latest tools/wifi-lab gate result (AVR-296). Missing, unparseable, stale or taken on another
    channel is UNKNOWN: an old measurement says nothing about tonight's radio."""
    if gate is None:
        return [check('wifi.gate', 'network', UNKNOWN,
                      'no Wi-Fi qualification result: run `python tools/wifi-lab/wifilab.py gate` from the laptop '
                      '(docs/runbooks/wifi-qualification.md) and pass it with --wifi-gate')]
    if not isinstance(gate, dict) or gate.get('schema') != WIFI_GATE_SCHEMA or gate.get('verdict') not in ('PASS', 'WARN', 'FAIL'):
        return [check('wifi.gate', 'network', UNKNOWN, f'not a {WIFI_GATE_SCHEMA} result')]
    started = _parse_time(gate.get('started'))
    if started is None:
        return [check('wifi.gate', 'network', UNKNOWN, 'gate result has no readable start time')]
    age_h = (now - started).total_seconds() / 3600
    ap = gate.get('ap') if isinstance(gate.get('ap'), dict) else {}
    try:
        channel = int(ap.get('channel')) if ap.get('channel') is not None else None
    except (TypeError, ValueError):
        channel = None
    detail = {'verdict': gate['verdict'], 'started': _iso(started), 'age_h': round(age_h, 1), 'channel': channel,
              'client': ((gate.get('client') or {}).get('model')), 'source': source,
              'thresholds_status': gate.get('thresholds_status')}
    if age_h > max_age_h:
        return [check('wifi.gate', 'network', UNKNOWN,
                      f'the latest gate ({gate["verdict"]}) is {age_h:.0f} h old (limit {max_age_h:g} h): run it again', detail=detail)]
    if age_h < -0.25:
        return [check('wifi.gate', 'network', UNKNOWN, 'the gate result is dated in the future: a clock is wrong', detail=detail)]
    if check_channel and (channel is None or current_channel is None):
        return [check('wifi.gate', 'network', UNKNOWN,
                      'cannot tell whether the gate ran on the AP\'s current channel (' +
                      ('the gate recorded none' if channel is None else 'the AP channel is unreadable') + ')', detail=detail)]
    if channel is not None and current_channel is not None and channel != int(current_channel):
        return [check('wifi.gate', 'network', UNKNOWN,
                      f'the gate ran on channel {channel}; the AP is on {current_channel} now', detail=detail)]
    results = gate.get('results') if isinstance(gate.get('results'), list) else []
    worst = [str(r.get('text')) for r in results if isinstance(r, dict) and r.get('level') == gate['verdict']][:3]
    level = {'PASS': PASS, 'WARN': WARN, 'FAIL': FAIL}[gate['verdict']]
    reason = f'wifi-lab gate {gate["verdict"]} {age_h:.1f} h ago on channel {channel}'
    if level != PASS and worst:
        reason += ': ' + '; '.join(worst)
    return [check('wifi.gate', 'network', level, reason + ' (one Android client, provisional thresholds)', detail=detail)]


def verdict(checks, waived=()):
    blocking = [c for c in checks if c['blocking']]
    if any(c['status'] == FAIL for c in blocking):
        result = NOT_READY
    elif any(c['status'] == UNKNOWN and c['id'] not in waived for c in blocking):
        result = UNKNOWN
    else:
        result = READY
    if result == NOT_READY:
        overall = FAIL
    elif result == UNKNOWN:
        overall = UNKNOWN
    elif any(c['status'] != PASS for c in checks):
        overall = WARN
    else:
        overall = PASS
    return result, overall


def _names(config):
    """The host names phones ask the Pi for: Party Core's `hosts` and its game origins' hosts."""
    from urllib.parse import urlsplit
    if not isinstance(config, dict):
        return [smoke_module.HOST], []
    hosts = [h for h in config.get('hosts') or [] if isinstance(h, str)] or [smoke_module.HOST]
    games = sorted({urlsplit(o).hostname for o in (config.get('game_origins') or {}) if urlsplit(o).hostname})
    return hosts[:1] + [h for h in hosts[1:] if h not in hosts[:1]], [g for g in games if g not in hosts]


def _guarded(category, fn):
    """A probe or evaluator that raises becomes one blocking UNKNOWN, never a traceback (or a PASS)."""
    try:
        return fn()
    except Exception as e:      # noqa: BLE001 - the whole point is that nothing here ends the run
        return [check(f'{category}.crashed', category, UNKNOWN, f'the {category} check crashed ({type(e).__name__})')]


def run(probes=None, wifi_gate=None, wifi_source=None, horizon_days=0, waive=(), config_path=PARTY_CONFIG,
        wifi_max_age_h=WIFI_GATE_MAX_AGE_H, local=None, now=None, reference=None):
    probes = probes or Probes()
    started = time.monotonic()
    try:
        clock = probes.clock() if local is None else {'synchronized': None, 'now': datetime.now(timezone.utc)}
    except Exception:           # noqa: BLE001
        clock = {'synchronized': None, 'now': datetime.now(timezone.utc)}
    now = now or clock['now']
    checks, notes, doc = [], [], None
    if local is not None:
        doc, source = probes.local_status(local)
        checks += _guarded('revision', lambda: revision_checks(doc, source))
        checks += _guarded('services', lambda: service_checks(doc))
        checks += _guarded('serving', lambda: smoke_checks(probes.smoke_local(local)))
        not_here = ('tls', 'network', 'pi', 'packages', 'runtime')
        checks += [check(f'{c}.appliance', c, UNKNOWN, f'--local: {c} checks only run on the appliance') for c in not_here]
        checks += _guarded('network', lambda: wifi_checks(wifi_gate, now, None, wifi_max_age_h, wifi_source))
        party_names, game_names = [], []
    else:
        config, config_error = probes.party_config(config_path)
        if config is None:
            checks.append(check('config.party_core', 'revision', WARN,
                                f'{config_path} {config_error}: names and status paths are the defaults', blocking=False))
        party_names, game_names = _names(config)
        status_config = status_module.load_config(config or {})
        try:
            doc, source = probes.status_doc(status_config)
        except Exception:       # noqa: BLE001
            doc, source = None, 'local'
        names = party_names + game_names
        checks += _guarded('revision', lambda: revision_checks(doc, source))
        checks += _guarded('services', lambda: service_checks(doc, status_config.get('optional_units', ())))
        checks += _guarded('serving', lambda: smoke_checks(probes.smoke()))
        checks += _guarded('tls', lambda: tls_checks(names, {n: probes.served_certificate(n) for n in names}, now,
                                                     horizon_days))
        checks += _guarded('network', lambda: dns_checks(names, {n: probes.resolve(n) for n in names}))
        checks += _guarded('network', lambda: topology_checks(*probes.topology()))
        checks += _guarded('network', lambda: wifi_checks(wifi_gate, now, probes.ap_channel(), wifi_max_age_h, wifi_source,
                                                          check_channel=True))
        deployed_at = _parse_time(((doc or {}).get('deployment') or {}).get('deployed_at'))
        checks += _guarded('pi', lambda: pi_checks(*probes.pi_health(now), clock, deployed_at, probes.exists(REBOOT_REQUIRED),
                                                   probes.journal_storage(), reference))
        checks += _guarded('pi', lambda: storage_checks({p: probes.disk(p) for p in STORAGE}))
        checks += _guarded('packages', lambda: package_checks(*probes.packages(), probes.node_runtime()))
        checks += _guarded('runtime', lambda: runtime_checks({t: probes.which(t) for t in REQUIRED_TOOLS + ('dig',)},
                                                             probes.python_version()))
        if probes.exists(OFFLINE_MARK):
            notes.append('development offline mode is ON (tools/avrana-offline): party clients have no upstream')
    # --local can never be READY: what it cannot see is the appliance itself.
    waivable = {c['id'] for c in checks if c['status'] == UNKNOWN and c['blocking'] and not c['id'].endswith('.appliance')}
    waived = sorted(set(waive) & waivable)
    unknown_waivers = sorted(set(waive) - set(waived))
    if unknown_waivers:
        notes.append(f'--waive ignored for {", ".join(unknown_waivers)}: only a blocking UNKNOWN can be waived')
    result, overall = verdict(checks, waived)
    unverified = list(PHYSICALLY_UNVERIFIED)
    if any(c['id'] == 'wifi.gate' and c['status'] != PASS for c in checks):
        unverified.insert(0, 'Wi-Fi qualification: the wifi-lab gate did not PASS for this run')
    party = (doc or {}).get('party') or {}
    games = (doc or {}).get('games') or {}
    return {
        'schema': SCHEMA,
        'generated_at': _iso(now),
        'seconds': round(time.monotonic() - started, 1),
        'mode': 'local' if local is not None else 'appliance',
        'host': socket.gethostname(),
        'tool': {'party_sha': _own_sha()},
        'verdict': result,
        'overall': overall,
        'horizon_days': horizon_days,
        'revisions': {
            'party': {k: party.get(k) for k in ('deployed_sha', 'checkout_sha', 'dirty', 'ref')},
            'games': {k: games.get(k) for k in ('deployed_sha', 'checkout_sha', 'dirty', 'ref')},
            'web_release': (doc or {}).get('web_release'),
            'last_known_good': (doc or {}).get('last_known_good'),
            'contract': (doc or {}).get('contract'),
        },
        'names': {'party': party_names, 'game_origins': game_names},
        'counts': {s: sum(1 for c in checks if c['status'] == s) for s in (PASS, WARN, FAIL, UNKNOWN)},
        'blocking': [c['id'] for c in checks if c['blocking'] and c['status'] in (FAIL, UNKNOWN) and c['id'] not in waived],
        'waived': waived,
        'checks': checks,
        'notes': notes,
        'physically_unverified': unverified,
        'level': 'server-observable checks only; not a phone or human acceptance result',
    }


def _own_sha():
    try:
        out = subprocess.run(['git', '-C', str(REPO_ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and re.fullmatch(r'[0-9a-f]{40}', out.stdout.strip()):
            return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    # A code release under /opt is named by its commit (ops/deploy.sh).
    name = REPO_ROOT.name
    return name if re.fullmatch(r'[0-9a-f]{40}', name) else None


def render_text(doc):
    order = {FAIL: 0, UNKNOWN: 1, WARN: 2, PASS: 3}
    r = doc['revisions']
    lines = [f'Avrana preflight: {doc["verdict"]} ({doc["overall"]})   {doc["generated_at"]}   {doc["mode"]} on {doc["host"]}',
             f'  party  deployed {r["party"].get("deployed_sha") or "unknown"}',
             f'  games  deployed {r["games"].get("deployed_sha") or "unknown"}',
             f'  checks {doc["counts"][PASS]} pass, {doc["counts"][WARN]} warn, {doc["counts"][FAIL]} fail, '
             f'{doc["counts"][UNKNOWN]} unknown ({doc["seconds"]} s)', '']
    if doc['blocking']:
        lines.append('Blocking: ' + ', '.join(doc['blocking']))
        lines.append('')
    for c in sorted(doc['checks'], key=lambda c: (order[c['status']], c['category'], c['id'])):
        if c['status'] == PASS:
            continue
        tag = '' if c['blocking'] else ' (advisory)'
        waived = ' (waived)' if c['id'] in doc['waived'] else ''
        lines.append(f'{c["status"]:7} {c["id"]}{tag}{waived}: {c["reason"]}')
    passed = [c['id'] for c in doc['checks'] if c['status'] == PASS]
    if passed:
        lines.append(f'PASS    {len(passed)}: ' + ', '.join(passed))
    for note in doc['notes']:
        lines.append(f'NOTE    {note}')
    lines += ['', 'Needs a real phone (never shown by this preflight):'] + [f'  - {u}' for u in doc['physically_unverified']]
    return '\n'.join(lines) + '\n'


def render_markdown(doc):
    order = {FAIL: 0, UNKNOWN: 1, WARN: 2, PASS: 3}
    r = doc['revisions']
    md = [f'# Preflight {doc["verdict"]} ({doc["overall"]})', '',
          f'- generated: `{doc["generated_at"]}` on `{doc["host"]}` ({doc["mode"]})',
          f'- party deployed: `{r["party"].get("deployed_sha")}`', f'- games deployed: `{r["games"].get("deployed_sha")}`',
          f'- tool: `{doc["tool"]["party_sha"]}`', f'- horizon: {doc["horizon_days"]} days',
          f'- blocking: {", ".join(doc["blocking"]) or "none"}; waived: {", ".join(doc["waived"]) or "none"}', '',
          '| Status | Check | Blocking | Reason |', '|---|---|---|---|']
    for c in sorted(doc['checks'], key=lambda c: (order[c['status']], c['category'], c['id'])):
        md.append(f'| {c["status"]} | `{c["id"]}` | {"yes" if c["blocking"] else "no"} | {c["reason"].replace("|", "/")} |')
    md += ['', '## Needs a real phone', ''] + [f'- {u}' for u in doc['physically_unverified']]
    if doc['notes']:
        md += ['', '## Notes', ''] + [f'- {n}' for n in doc['notes']]
    md += ['', f'_{doc["level"]}_']
    return '\n'.join(md) + '\n'


def load_wifi_gate(path):
    """(document or None, source). PATH is a gate.json, a wifi-lab results directory (the newest
    *_gate_*/gate.json in it) or '-' for standard input (tools/preflight.py streams it over ssh)."""
    if path is None:
        return None, None
    try:
        if path == '-':
            if sys.stdin is None or sys.stdin.isatty():
                return None, 'stdin is a terminal'
            text = sys.stdin.read(1 << 20)
            return (json.loads(text), 'stdin') if text.strip() else (None, None)
        p = Path(path)
        if p.is_dir():
            found = newest_gate(p)
            if found is None:
                return None, str(p)
            p = found
        return json.loads(p.read_text(encoding='utf-8')), p.name if p.name != 'gate.json' else p.parent.name
    except (OSError, ValueError):
        return 'unreadable', str(path)


def newest_gate(results_dir):
    candidates = sorted(Path(results_dir).glob('*_gate_*/gate.json'))
    return candidates[-1] if candidates else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--json', action='store_true', help='print the JSON document instead of the report')
    ap.add_argument('--out', help='also write preflight-<stamp>.json and .md into this directory')
    ap.add_argument('--wifi-gate', metavar='PATH', help='a wifi-lab gate.json, its results directory, or - for stdin')
    ap.add_argument('--wifi-max-age-h', type=float, default=WIFI_GATE_MAX_AGE_H, help='older gate results are UNKNOWN')
    ap.add_argument('--horizon-days', type=int, default=0, help='the certificate must stay valid this many days (a trip)')
    ap.add_argument('--waive', action='append', default=[], metavar='CHECK_ID',
                    help='accept a blocking UNKNOWN for this run (recorded in the report); never a FAIL')
    ap.add_argument('--config', default=PARTY_CONFIG, help=f'Party Core configuration (default {PARTY_CONFIG})')
    ap.add_argument('--local', metavar='BASE_URL', help='against the dev server; appliance-only checks are UNKNOWN')
    ap.add_argument('--reference-time', metavar='ISO',
                    help='a trusted clock reading taken just before this run (tools/preflight.py sends the laptop\'s)')
    args = ap.parse_args(argv)
    if args.horizon_days < 0:
        ap.error('--horizon-days must be 0 or more')
    if not 0 < args.wifi_max_age_h < float('inf'):
        ap.error('--wifi-max-age-h must be a positive number of hours')
    reference = None
    if args.reference_time:
        reference = _parse_time(args.reference_time)
        if reference is None:
            ap.error('--reference-time must be an ISO 8601 instant')
    gate, source = load_wifi_gate(args.wifi_gate)
    doc = run(wifi_gate=None if gate == 'unreadable' else gate, wifi_source=source, horizon_days=args.horizon_days,
              waive=args.waive, config_path=args.config, wifi_max_age_h=args.wifi_max_age_h, local=args.local,
              reference=reference)
    if gate == 'unreadable':
        doc['notes'].append(f'--wifi-gate {source} could not be read')
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        stamp = doc['generated_at'].replace(':', '').replace('-', '')
        (out / f'preflight-{stamp}.json').write_text(json.dumps(doc, indent=2, default=str) + '\n', encoding='utf-8')
        (out / f'preflight-{stamp}.md').write_text(render_markdown(doc), encoding='utf-8')
    sys.stdout.write(json.dumps(doc, indent=2, default=str) + '\n' if args.json else render_text(doc))
    return EXIT[doc['verdict']]


if __name__ == '__main__':
    sys.exit(main())
