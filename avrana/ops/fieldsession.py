"""Field-session diagnostics (avrana.field-session/v0): opt-in, bounded evidence of one test night.

    python3 -m avrana.ops.fieldsession start --label "four phones bluff"
    python3 -m avrana.ops.fieldsession mark "phone C froze on the lobby" --outcome fail --step A-12
    python3 -m avrana.ops.fieldsession snapshot [--attach-preflight preflight.json]
    python3 -m avrana.ops.fieldsession stop
    python3 -m avrana.ops.fieldsession timeline              # the session as one ordered Markdown page
    python3 -m avrana.ops.fieldsession export --out ~/       # avrana-field-<id>.tar.gz, validated first
    python3 -m avrana.ops.fieldsession validate PACKAGE.tar.gz [--forbid-terms names.txt]
    python3 -m avrana.ops.fieldsession status

Nothing is recorded until the operator runs `start` (there is no service, timer or endpoint), and
nothing is recorded after `stop`. It runs on the Pi as the operator, without sudo, and writes only
under ~/avrana-field-sessions (or $AVRANA_FIELD_SESSIONS). It reuses what exists:

    revisions and health   /party/api/status on loopback (the public avrana.status/v0 document)
    Pi health              /run/avrana/pi-health.json (telemetry/pi-health-check.py's timer) when present
    power                  /var/log/avrana/pi-throttle.jsonl lines inside the session window
    logs                   journalctl for the Avrana units (and kernel warnings) inside the window, only
                           MESSAGE / PRIORITY / unit / time; NetworkManager and dnsmasq are left out on
                           purpose (they log phones' addresses and names)
    preflight              an avrana.preflight/v0 document the operator attaches (avrana.ops.preflight)

Every string goes through avrana.ops.redact before it is written, and the finished package is
validated again before it is exported (`validate` repeats that on any package). A package that
fails validation is not written. Bounds: the session directory stops accepting data at
--max-bytes (default 4 MiB), a session expires after --max-hours (default 12), journal lines are
capped per run and per line, and an export is refused above 2 MiB. Party Core and its telemetry
are not changed and nothing is recorded per member: the status document carries only counts.
"""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request

from avrana import REPO_ROOT
from avrana.ops import redact

SCHEMA = 'avrana.field-session/v0'
PACKAGE_SCHEMA = 'avrana.field-package/v0'
PREFLIGHT_SCHEMA = 'avrana.preflight/v0'
STATUS_SCHEMA = 'avrana.status/v0'
STATUS_URL = 'http://127.0.0.1:8191/party/api/status'
STATUS_HOST = 'party.avrana.net'
PI_HEALTH_STATE = '/run/avrana/pi-health.json'
THROTTLE_LOG = '/var/log/avrana/pi-throttle.jsonl'
DEFAULT_ROOT = Path.home() / 'avrana-field-sessions'
DEFAULT_MAX_BYTES = 4 << 20
DEFAULT_MAX_HOURS = 12.0
EXPORT_MAX_BYTES = 2 << 20
JOURNAL_MAX_LINES = 1500
JOURNAL_LINE_CHARS = 300
THROTTLE_MAX_LINES = 1000
MARK_CHARS = 200
COMMAND_TIMEOUT_S = 20.0
UNITS = ('avrana-party-core', 'avrana-party-core.socket', 'avranaparty-games', 'avranaparty-arcade',
         'avrana-game@*', 'pi-health-check', 'pi-throttle-check', 'nginx')
OUTCOMES = ('note', 'pass', 'fail', 'blocked', 'observed')
MEMBER = re.compile(r'^(session\.json|events\.jsonl|journal\.jsonl|throttle\.jsonl|timeline\.md|manifest\.json|'
                    r'snapshots/\d{3}\.json)$')


class Refused(Exception):
    pass


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _parse(text):
    try:
        return datetime.fromisoformat(str(text).replace('Z', '+00:00'))
    except ValueError:
        return None


def _slug(label):
    s = re.sub(r'[^a-z0-9]+', '-', label.lower()).strip('-')
    return s[:32].strip('-') or 'session'


class Probes:
    """Every read of the machine, replaceable in tests. Nothing here writes outside the session."""

    def __init__(self, status_url=STATUS_URL, host=STATUS_HOST, timeout=COMMAND_TIMEOUT_S):
        self.status_url, self.host, self.timeout = status_url, host, timeout

    def status(self):
        """(document or None, error or None)."""
        req = urllib.request.Request(self.status_url, headers={'Host': self.host} if self.host else {})
        try:
            with urllib.request.urlopen(req, timeout=min(self.timeout, 5.0)) as r:
                doc = json.loads(r.read(1 << 20).decode('utf-8'))
        except (urllib.error.URLError, OSError, ValueError) as e:
            return None, f'status unreachable ({type(getattr(e, "reason", e)).__name__})'
        if not isinstance(doc, dict) or doc.get('schema') != STATUS_SCHEMA:
            return None, f'not an {STATUS_SCHEMA} document'
        return doc, None

    def pi_health(self):
        try:
            return json.loads(Path(PI_HEALTH_STATE).read_text(encoding='utf-8')), None
        except FileNotFoundError:
            return None, 'no Pi health state file (pi-health-check.timer not installed)'
        except (OSError, ValueError) as e:
            return None, f'Pi health unreadable ({type(e).__name__})'

    def throttle_lines(self):
        try:
            with open(THROTTLE_LOG, encoding='utf-8', errors='replace') as f:
                return f.readlines()[-20000:], None
        except OSError as e:
            return [], f'{THROTTLE_LOG} unreadable ({type(e).__name__})'

    def journal(self, since, until, units):
        """(entries, error). Entries are journalctl -o json objects, bounded in count and time."""
        if platform.system() != 'Linux':
            return [], 'journal unavailable (not Linux)'
        cmd = ['journalctl', '--no-pager', '-o', 'json', '--since', f'@{int(since.timestamp())}',
               '--until', f'@{int(until.timestamp()) + 1}', '-n', str(JOURNAL_MAX_LINES * 2)]
        for unit in units:
            cmd += ['-u', unit]
        entries, problems = [], []
        for extra in (cmd, ['journalctl', '--no-pager', '-o', 'json', '-k', '-p', 'warning', '--since',
                            f'@{int(since.timestamp())}', '--until', f'@{int(until.timestamp()) + 1}', '-n', '500']):
            try:
                p = subprocess.run(extra, capture_output=True, timeout=self.timeout)
            except (OSError, subprocess.TimeoutExpired) as e:
                problems.append(f'journalctl failed ({type(e).__name__})')
                continue
            for line in p.stdout.decode('utf-8', 'replace').splitlines():
                try:
                    entries.append(json.loads(line))
                except ValueError:
                    continue
            if p.returncode != 0 or b'insufficient permissions' in p.stderr:
                problems.append('journalctl: ' + (p.stderr.decode('utf-8', 'replace').strip().splitlines() or ['no access'])[0][:120])
        return entries, '; '.join(problems) or None


# ---- the session on disk -----------------------------------------------------------------------------

class Store:
    def __init__(self, root=None):
        self.root = Path(root or os.environ.get('AVRANA_FIELD_SESSIONS') or DEFAULT_ROOT)

    def active_id(self):
        try:
            sid = (self.root / 'ACTIVE').read_text(encoding='utf-8').strip()
        except OSError:
            return None
        return sid if re.fullmatch(r'\d{8}T\d{6}Z-[a-z0-9-]{1,32}', sid) else None

    def dir(self, sid):
        if not re.fullmatch(r'\d{8}T\d{6}Z-[a-z0-9-]{1,32}', sid or ''):
            raise Refused(f'not a session id: {sid!r}')
        return self.root / sid

    def resolve(self, sid=None):
        """The named session, else the active one, else the newest."""
        if sid:
            d = self.dir(sid)
        elif self.active_id():
            d = self.dir(self.active_id())
        else:
            found = sorted(p for p in self.root.glob('*Z-*') if (p / 'session.json').is_file()) if self.root.is_dir() else []
            if not found:
                raise Refused(f'no field session under {self.root}; start one with `start --label ...`')
            d = found[-1]
        if not (d / 'session.json').is_file():
            raise Refused(f'no such session: {d.name}')
        return d


def _read_session(d):
    return json.loads((d / 'session.json').read_text(encoding='utf-8'))


def _write_json(path, doc):
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def _dir_bytes(d):
    return sum(p.stat().st_size for p in d.rglob('*') if p.is_file())


def _append_event(d, event, max_bytes):
    line = json.dumps(redact.scrub_json(event), sort_keys=True) + '\n'
    if _dir_bytes(d) + len(line) > max_bytes:
        raise Refused(f'the session reached its size limit ({max_bytes} bytes); stop and export it')
    with open(d / 'events.jsonl', 'a', encoding='utf-8') as f:
        f.write(line)


def _events(d):
    out = []
    try:
        for line in (d / 'events.jsonl').read_text(encoding='utf-8').splitlines():
            if line.strip():
                out.append(json.loads(line))
    except (OSError, ValueError):
        pass
    return out


def revisions(doc):
    """Exact component revisions from a status document (or what is unknown)."""
    if not isinstance(doc, dict):
        return {'party': None, 'games': None, 'web_build': None, 'contract': None}
    web = doc.get('web_release') or {}
    contract = doc.get('contract') or {}
    return {'party': (doc.get('party') or {}).get('deployed_sha') or (doc.get('party') or {}).get('checkout_sha'),
            'games': (doc.get('games') or {}).get('deployed_sha') or (doc.get('games') or {}).get('checkout_sha'),
            'web_build': web.get('build'), 'web_commit': web.get('commit'),
            'contract': {k: contract.get(k) for k in ('party_games', 'party_session', 'lan_launch', 'games_advertises')}}


def _collector_sha():
    try:
        out = subprocess.run(['git', '-C', str(REPO_ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=5)
        if re.fullmatch(r'[0-9a-f]{40}', out.stdout.strip()):
            return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return REPO_ROOT.name if re.fullmatch(r'[0-9a-f]{40}', REPO_ROOT.name) else None


def _check_open(session, now):
    if session.get('stopped_at'):
        raise Refused(f'session {session["id"]} is stopped; start a new one')
    started = _parse(session['started_at'])
    if started and (now - started).total_seconds() > session['limits']['max_hours'] * 3600:
        raise Refused(f'session {session["id"]} is older than {session["limits"]["max_hours"]:g} h; stop it')


def take_snapshot(d, session, probes, now, attach_preflight=None, reason='snapshot'):
    snaps = sorted((d / 'snapshots').glob('*.json'))
    n = len(snaps) + 1
    if n > 999:
        raise Refused('999 snapshots: stop the session')
    status, status_error = probes.status()
    health, health_error = probes.pi_health()
    doc = {'at': _iso(now), 'reason': reason, 'status': status, 'status_error': status_error,
           'revisions': revisions(status),
           'pi_health': None if health is None else {k: health.get(k) for k in ('state', 'reasons', 'notes')},
           'pi_health_error': health_error}
    if attach_preflight is not None:
        doc['preflight'] = _preflight_summary(attach_preflight)
    doc = redact.scrub_json(doc)
    data = json.dumps(doc, indent=2, sort_keys=True) + '\n'
    if _dir_bytes(d) + len(data) > session['limits']['max_bytes']:
        raise Refused(f'the session reached its size limit ({session["limits"]["max_bytes"]} bytes); stop and export it')
    (d / 'snapshots').mkdir(exist_ok=True)
    (d / 'snapshots' / f'{n:03d}.json').write_text(data, encoding='utf-8')
    summary = (status or {}).get('summary') or {}
    _append_event(d, {'at': _iso(now), 'kind': 'snapshot', 'snapshot': f'{n:03d}', 'reason': reason,
                      'state': summary.get('state') or ('unreachable' if status is None else None)},
                  session['limits']['max_bytes'])
    return n, doc


def _preflight_summary(doc):
    if not isinstance(doc, dict) or doc.get('schema') != PREFLIGHT_SCHEMA:
        return {'error': f'not an {PREFLIGHT_SCHEMA} document'}
    return {'generated_at': doc.get('generated_at'), 'verdict': doc.get('verdict'), 'overall': doc.get('overall'),
            'blocking': doc.get('blocking'), 'counts': doc.get('counts'),
            'checks': [{k: c.get(k) for k in ('id', 'status', 'blocking', 'reason')} for c in doc.get('checks', [])
                       if c.get('status') != 'PASS']}


def start(store, label, probes, now=None, max_bytes=DEFAULT_MAX_BYTES, max_hours=DEFAULT_MAX_HOURS):
    now = now or _now()
    active = store.active_id()
    if active:
        raise Refused(f'session {active} is still running; stop it first')
    label = redact.scrub_text(label, 80)
    sid = f'{now.strftime("%Y%m%dT%H%M%SZ")}-{_slug(label)}'
    d = store.dir(sid)
    store.root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(store.root, 0o700)
    except OSError:
        pass
    d.mkdir()
    (d / 'snapshots').mkdir()
    session = {'schema': SCHEMA, 'id': sid, 'label': label, 'started_at': _iso(now), 'stopped_at': None,
               'limits': {'max_bytes': int(max_bytes), 'max_hours': float(max_hours), 'journal_lines': JOURNAL_MAX_LINES,
                          'export_bytes': EXPORT_MAX_BYTES},
               'collector': {'party_sha': _collector_sha(), 'rules': redact.RULES_VERSION},
               'revisions_at_start': None, 'revisions_at_stop': None}
    _write_json(d / 'session.json', session)
    _append_event(d, {'at': _iso(now), 'kind': 'start', 'label': label}, max_bytes)
    _, snap = take_snapshot(d, session, probes, now, reason='start')
    session['revisions_at_start'] = snap['revisions']
    _write_json(d / 'session.json', session)
    (store.root / 'ACTIVE').write_text(sid + '\n', encoding='utf-8')
    return session


def mark(store, text, outcome='note', step=None, now=None):
    now = now or _now()
    if not store.active_id():
        raise Refused('no running session: `start --label ...` first')
    d = store.resolve()
    session = _read_session(d)
    _check_open(session, now)
    if outcome not in OUTCOMES:
        raise Refused(f'outcome must be one of {", ".join(OUTCOMES)}')
    event = {'at': _iso(now), 'kind': 'mark', 'outcome': outcome, 'note': redact.scrub_text(text, MARK_CHARS)}
    if step:
        event['step'] = redact.scrub_text(step, 24)
    _append_event(d, event, session['limits']['max_bytes'])
    return event


def snapshot(store, probes, now=None, attach_preflight=None):
    now = now or _now()
    if not store.active_id():
        raise Refused('no running session: `start --label ...` first')
    d = store.resolve()
    session = _read_session(d)
    _check_open(session, now)
    return take_snapshot(d, session, probes, now, attach_preflight)


def stop(store, probes, now=None, units=UNITS):
    now = now or _now()
    if not store.active_id():
        raise Refused('no running session')
    d = store.resolve()
    session = _read_session(d)
    if session.get('stopped_at'):
        raise Refused(f'session {session["id"]} is already stopped')
    try:
        _, snap = take_snapshot(d, session, probes, now, reason='stop')
        session['revisions_at_stop'] = snap['revisions']
    except Refused as e:
        _append_event_unbounded(d, {'at': _iso(now), 'kind': 'limit', 'note': str(e)})
    started = _parse(session['started_at'])
    entries, journal_error = probes.journal(started, now, units)
    lines, dropped = journal_lines(entries, started, now)
    _write_jsonl(d / 'journal.jsonl', lines)
    raw, throttle_error = probes.throttle_lines()
    throttle = throttle_window(raw, started, now)
    _write_jsonl(d / 'throttle.jsonl', throttle)
    session['stopped_at'] = _iso(now)
    session['collected'] = {'journal_lines': len(lines), 'journal_dropped': dropped, 'journal_error': journal_error,
                            'throttle_lines': len(throttle), 'throttle_error': throttle_error}
    _write_json(d / 'session.json', session)
    _append_event_unbounded(d, {'at': _iso(now), 'kind': 'stop'})
    (d / 'timeline.md').write_text(timeline(d), encoding='utf-8')
    try:
        (store.root / 'ACTIVE').unlink()
    except OSError:
        pass
    return session


def _append_event_unbounded(d, event):
    """The stop record is always written: a full session must still say that it ended."""
    with open(d / 'events.jsonl', 'a', encoding='utf-8') as f:
        f.write(json.dumps(redact.scrub_json(event), sort_keys=True) + '\n')


def _write_jsonl(path, rows):
    path.write_text(''.join(json.dumps(r, sort_keys=True) + '\n' for r in rows), encoding='utf-8')


def journal_lines(entries, since, until):
    """Scrubbed {at, unit, priority, message} rows inside the window; warnings first when over the cap.
    Returns (rows sorted by time, {'chat': n, 'cap': n, 'outside': n})."""
    rows, dropped = [], {'chat': 0, 'cap': 0, 'outside': 0}
    for e in entries:
        try:
            at = datetime.fromtimestamp(int(e.get('__REALTIME_TIMESTAMP')) / 1e6, timezone.utc)
        except (TypeError, ValueError):
            continue
        if not since <= at <= until:
            dropped['outside'] += 1
            continue
        message = e.get('MESSAGE')
        if isinstance(message, list):          # journald's byte-array form for non-UTF-8 messages
            message = bytes(x for x in message if isinstance(x, int)).decode('utf-8', 'replace')
        clean = redact.scrub_log_line(str(message or ''), JOURNAL_LINE_CHARS)
        if clean is None:
            dropped['chat'] += 1
            continue
        try:
            priority = int(e.get('PRIORITY', 6))
        except (TypeError, ValueError):
            priority = 6
        unit = e.get('_SYSTEMD_UNIT') or ('kernel' if e.get('_TRANSPORT') == 'kernel' else e.get('SYSLOG_IDENTIFIER') or '?')
        rows.append({'at': at.isoformat(timespec='milliseconds').replace('+00:00', 'Z'), 'priority': priority,
                     'unit': redact.scrub_text(str(unit), 64), 'message': clean})
    seen, unique = set(), []
    for r in sorted(rows, key=lambda r: (r['at'], r['unit'], r['message'])):
        key = (r['at'], r['unit'], r['message'])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    if len(unique) > JOURNAL_MAX_LINES:
        keep = sorted(unique, key=lambda r: (r['priority'], [-ord(c) for c in r['at']]))[:JOURNAL_MAX_LINES]
        dropped['cap'] = len(unique) - len(keep)
        unique = sorted(keep, key=lambda r: (r['at'], r['unit'], r['message']))
    return unique, dropped


def throttle_window(raw_lines, since, until):
    """pi-throttle.jsonl records inside the window (power and temperature; no personal data), scrubbed."""
    out = []
    for line in raw_lines:
        try:
            doc = json.loads(line)
        except ValueError:
            continue
        at = _parse(doc.get('ts') or doc.get('at') or doc.get('time')) if isinstance(doc, dict) else None
        if at is None or at.tzinfo is None or not since <= at <= until:
            continue
        out.append(redact.scrub_json(doc))
    return out[-THROTTLE_MAX_LINES:]


# ---- the timeline ------------------------------------------------------------------------------------

def _short(sha):
    return str(sha)[:12] if sha else 'unknown'


def _service_changes(prev, cur):
    a = ((prev or {}).get('status') or {}).get('services') or {}
    b = ((cur or {}).get('status') or {}).get('services') or {}
    return [f'{u}: {a.get(u, "?")} -> {b.get(u, "?")}' for u in sorted(set(a) | set(b)) if a.get(u) != b.get(u)]


def _reasons(snap):
    return set((((snap or {}).get('status') or {}).get('summary') or {}).get('reasons') or [])


def timeline(d):
    session = _read_session(d)
    snaps = {p.stem: json.loads(p.read_text(encoding='utf-8')) for p in sorted((d / 'snapshots').glob('*.json'))}
    journal = []
    try:
        journal = [json.loads(l) for l in (d / 'journal.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    except (OSError, ValueError):
        pass
    start_rev, stop_rev = session.get('revisions_at_start') or {}, session.get('revisions_at_stop') or {}
    md = [f'# Field session {session["id"]}', '',
          f'- label: {session["label"]}', f'- started: `{session["started_at"]}`; stopped: `{session.get("stopped_at")}`',
          f'- party: `{_short(start_rev.get("party"))}`, games: `{_short(start_rev.get("games"))}`, web build: '
          f'`{start_rev.get("web_build")}`, contract: `{(start_rev.get("contract") or {}).get("party_games")}`',
          f'- collector: `{_short((session.get("collector") or {}).get("party_sha"))}`, rules `{redact.RULES_VERSION}`']
    if stop_rev and (stop_rev.get('party'), stop_rev.get('games')) != (start_rev.get('party'), start_rev.get('games')):
        md.append(f'- **revisions changed during the session**: party `{_short(stop_rev.get("party"))}`, games '
                  f'`{_short(stop_rev.get("games"))}` at the stop')
    c = session.get('collected') or {}
    if c:
        md.append(f'- journal: {c.get("journal_lines")} lines kept, dropped {c.get("journal_dropped")}'
                  + (f'; {c["journal_error"]}' if c.get('journal_error') else ''))
    rows = []
    prev = None
    for e in _events(d):
        at = e.get('at', '')
        if e.get('kind') == 'mark':
            step = f' [{e["step"]}]' if e.get('step') else ''
            rows.append((at, 0, f'**MARK {e.get("outcome", "note").upper()}**{step}: {e.get("note", "")}'))
        elif e.get('kind') == 'snapshot':
            snap = snaps.get(e.get('snapshot'))
            text = f'snapshot {e.get("snapshot")} ({e.get("reason")}): status {e.get("state")}'
            if snap is not None and snap.get('status') is None:
                # Nothing to compare: the next reachable snapshot is compared with the last reachable one.
                text = f'snapshot {e.get("snapshot")} ({e.get("reason")}): **{snap.get("status_error") or "no status"}**'
            elif snap is not None:
                changes = _service_changes(prev, snap)
                added, gone = sorted(_reasons(snap) - _reasons(prev)), sorted(_reasons(prev) - _reasons(snap))
                if changes:
                    text += '; services ' + ', '.join(changes)
                if added:
                    text += '; new: ' + '; '.join(added)
                if gone:
                    text += '; cleared: ' + '; '.join(gone)
                core = ((snap.get('status') or {}).get('party_core') or {})
                if core.get('ok'):
                    sess = core.get('session') or {}
                    text += f'; {core.get("members")} member(s), session ' + (
                        f'{sess.get("game")} {sess.get("state")}' if sess else 'none')
                if (snap.get('pi_health') or {}).get('state'):
                    text += f'; Pi {snap["pi_health"]["state"]}'
                if snap.get('preflight'):
                    text += f'; preflight {snap["preflight"].get("verdict")}'
                prev = snap
            rows.append((at, 1, text))
        elif e.get('kind') in ('start', 'stop', 'limit'):
            rank = {'start': -1, 'stop': 9}.get(e['kind'], 0)
            rows.append((at, rank, f'session {e["kind"]}' + (f': {e.get("note")}' if e.get('note') else '')))
    for j in journal:
        if j.get('priority', 6) <= 4:
            level = {0: 'EMERG', 1: 'ALERT', 2: 'CRIT', 3: 'ERROR', 4: 'WARN'}.get(j['priority'], 'WARN')
            rows.append((j['at'][:19] + 'Z', 2, f'{level} {j.get("unit")}: {j.get("message")}'))
    info = {}
    for j in journal:
        if j.get('priority', 6) > 4:
            info[j.get('unit')] = info.get(j.get('unit'), 0) + 1
    md += ['', '| Time (UTC) | Event |', '|---|---|']
    for at, _, text in sorted(rows, key=lambda r: (r[0][:19], r[1], r[2])):
        md.append(f'| `{at[:19].replace("T", " ")}` | {text.replace("|", "/")} |')
    if info:
        md += ['', 'Informational journal lines (in journal.jsonl): ' +
               ', '.join(f'{u} {n}' for u, n in sorted(info.items()))]
    md += ['', '_Server-side evidence only: what phones showed is in the operator marks, not measured here._']
    return '\n'.join(md) + '\n'


# ---- export and validation ---------------------------------------------------------------------------

def package_members(d):
    """{member name: bytes} for a stopped session, plus its manifest. Deterministic."""
    session = _read_session(d)
    if not session.get('stopped_at'):
        raise Refused(f'session {session["id"]} is still running: stop it before exporting')
    members = {}
    for p in sorted(d.rglob('*')):
        name = p.relative_to(d).as_posix()
        if p.is_file() and MEMBER.match(name) and name != 'manifest.json':
            members[name] = p.read_bytes()
    members['timeline.md'] = timeline(d).encode('utf-8')
    manifest = {'schema': PACKAGE_SCHEMA, 'session': session['id'], 'started_at': session['started_at'],
                'stopped_at': session['stopped_at'], 'rules': redact.RULES_VERSION,
                'revisions_at_start': session.get('revisions_at_start'),
                'revisions_at_stop': session.get('revisions_at_stop'),
                'members': {n: {'sha256': hashlib.sha256(b).hexdigest(), 'bytes': len(b)} for n, b in sorted(members.items())}}
    members['manifest.json'] = (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode('utf-8')
    return session, members


def tar_bytes(prefix, members, mtime):
    """A gzip'd tar whose bytes depend only on the members and `mtime`."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode='w', format=tarfile.PAX_FORMAT) as tar:
        for name in sorted(members):
            data = members[name]
            info = tarfile.TarInfo(f'{prefix}/{name}')
            info.size, info.mtime, info.mode = len(data), int(mtime), 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            tar.addfile(info, io.BytesIO(data))
    out = io.BytesIO()
    with gzip.GzipFile(filename='', mode='wb', fileobj=out, mtime=0, compresslevel=9) as gz:
        gz.write(raw.getvalue())
    return out.getvalue()


def export(store, out_dir, sid=None, forbid_terms=(), max_bytes=EXPORT_MAX_BYTES):
    d = store.resolve(sid)
    session, members = package_members(d)
    problems = redact.validate_members(members, forbid_terms, max_bytes, allowed_names=MEMBER.match)
    if problems:
        raise Refused('the package failed privacy validation and was not written: ' +
                      ', '.join(f'{p["member"]}:{p["rule"]}x{p["count"]}' for p in problems))
    prefix = f'avrana-field-{session["id"]}'
    data = tar_bytes(prefix, members, _parse(session['stopped_at']).timestamp())
    out = Path(out_dir) / f'{prefix}.tar.gz'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return out, hashlib.sha256(data).hexdigest(), len(members), sum(len(b) for b in members.values())


def read_package(path):
    """{member: bytes} of a package file or a session directory."""
    p = Path(path)
    if p.is_dir():
        return {q.relative_to(p).as_posix(): q.read_bytes() for q in sorted(p.rglob('*')) if q.is_file()}
    members = {}
    with tarfile.open(p, 'r:gz') as tar:
        for info in tar.getmembers():
            if not info.isfile():
                raise Refused(f'{info.name}: not a regular file')
            name = info.name.split('/', 1)[1] if '/' in info.name else info.name
            if info.size > EXPORT_MAX_BYTES:
                raise Refused(f'{name}: larger than the export limit')
            members[name] = tar.extractfile(info).read()
    return members


def validate(path, forbid_terms=(), max_bytes=EXPORT_MAX_BYTES):
    members = read_package(path)
    problems = redact.validate_members(members, forbid_terms, max_bytes, allowed_names=MEMBER.match)
    if 'manifest.json' in members:
        try:
            manifest = json.loads(members['manifest.json'])
            for name, facts in (manifest.get('members') or {}).items():
                if name not in members:
                    problems.append({'member': name, 'rule': 'missing_member', 'count': 1})
                elif hashlib.sha256(members[name]).hexdigest() != facts.get('sha256'):
                    problems.append({'member': name, 'rule': 'digest_mismatch', 'count': 1})
        except ValueError:
            pass
    elif not Path(path).is_dir():
        problems.append({'member': 'manifest.json', 'rule': 'missing_member', 'count': 1})
    return members, problems


def _read_terms(path):
    if not path:
        return ()
    return tuple(t.strip() for t in Path(path).read_text(encoding='utf-8').splitlines() if t.strip())


def main(argv=None):
    ap = argparse.ArgumentParser(prog='fieldsession', description=__doc__.split('\n')[0])
    ap.add_argument('--root', help=f'session directory (default {DEFAULT_ROOT} or $AVRANA_FIELD_SESSIONS)')
    ap.add_argument('--status-url', default=STATUS_URL)
    ap.add_argument('--status-host', default=STATUS_HOST, help='Host header for the status URL ("" for none)')
    sub = ap.add_subparsers(dest='command', required=True)
    s = sub.add_parser('start', help='begin recording (opt-in; nothing is recorded before this)')
    s.add_argument('--label', required=True)
    s.add_argument('--max-bytes', type=int, default=DEFAULT_MAX_BYTES)
    s.add_argument('--max-hours', type=float, default=DEFAULT_MAX_HOURS)
    m = sub.add_parser('mark', help='an operator marker: what you saw and its outcome (never names)')
    m.add_argument('text')
    m.add_argument('--outcome', default='note', choices=OUTCOMES)
    m.add_argument('--step', help='a runbook step id, e.g. A-12')
    n = sub.add_parser('snapshot', help='record the service health now')
    n.add_argument('--attach-preflight', metavar='JSON', help='an avrana.preflight/v0 document to summarize')
    sub.add_parser('stop', help='final snapshot, journal and power excerpts, timeline; stops recording')
    sub.add_parser('status', help='the running session, if any')
    t = sub.add_parser('timeline', help='print the session timeline')
    t.add_argument('session', nargs='?')
    e = sub.add_parser('export', help='write the validated package')
    e.add_argument('session', nargs='?')
    e.add_argument('--out', default='.')
    e.add_argument('--forbid-terms', metavar='FILE', help='words that must not appear, one per line (e.g. guest names)')
    v = sub.add_parser('validate', help='check a package or session directory; prints rule ids, never the content')
    v.add_argument('path')
    v.add_argument('--forbid-terms', metavar='FILE')
    a = ap.parse_args(argv)
    store = Store(a.root)
    probes = Probes(a.status_url, a.status_host or None)
    try:
        if a.command == 'start':
            session = start(store, a.label, probes, max_bytes=a.max_bytes, max_hours=a.max_hours)
            r = session['revisions_at_start'] or {}
            print(f'recording {session["id"]} (party {_short(r.get("party"))}, games {_short(r.get("games"))}); '
                  f'limits {session["limits"]["max_bytes"]} bytes, {session["limits"]["max_hours"]:g} h')
        elif a.command == 'mark':
            event = mark(store, a.text, a.outcome, a.step)
            print(f'{event["at"]} {event["outcome"]}: {event["note"]}')
        elif a.command == 'snapshot':
            doc = json.loads(Path(a.attach_preflight).read_text(encoding='utf-8')) if a.attach_preflight else None
            n_, snap = snapshot(store, probes, attach_preflight=doc)
            state = ((snap.get('status') or {}).get('summary') or {}).get('state') or snap.get('status_error')
            print(f'snapshot {n_:03d}: {state}')
        elif a.command == 'stop':
            session = stop(store, probes)
            c = session['collected']
            print(f'stopped {session["id"]}: {c["journal_lines"]} journal lines'
                  + (f' ({c["journal_error"]})' if c['journal_error'] else '') + f'; {store.dir(session["id"])}')
        elif a.command == 'status':
            sid = store.active_id()
            if not sid:
                print('no field session is recording (diagnostics are off)')
            else:
                session = _read_session(store.dir(sid))
                print(f'recording {sid} since {session["started_at"]}, {_dir_bytes(store.dir(sid))} of '
                      f'{session["limits"]["max_bytes"]} bytes, {len(_events(store.dir(sid)))} events')
        elif a.command == 'timeline':
            sys.stdout.write(timeline(store.resolve(a.session)))
        elif a.command == 'export':
            out, digest, count, size = export(store, a.out, a.session, _read_terms(a.forbid_terms))
            print(f'{out}  sha256 {digest}  {count} members, {size} bytes; privacy validation clean')
        elif a.command == 'validate':
            members, problems = validate(a.path, _read_terms(a.forbid_terms))
            for p in problems:
                print(f'VIOLATION {p["member"]}: {p["rule"]} x{p["count"]}')
            print(f'{len(members)} members, {sum(len(b) for b in members.values())} bytes: '
                  + ('clean' if not problems else f'{len(problems)} violation(s)'))
            return 1 if problems else 0
    except Refused as e:
        print(f'fieldsession: {e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
