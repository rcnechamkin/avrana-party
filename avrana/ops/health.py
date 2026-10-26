"""Avrana Health (avrana.health/v0): the preflight's facts as four owner-facing states (AVR-74).

    python3 -m avrana.ops.health                     # runs the preflight (on the Pi, as the operator, no sudo)
    python3 -m avrana.ops.health --preflight pf.json # or reads one it already wrote (`-` for stdin)
    python3 -m avrana.ops.health --json

PROTOTYPE for docs/design/proposals/2026-10-26-health-and-support-bundle.md; owner decision D1 is open.
It is a reader: every fact comes from avrana.ops.preflight, which already folds in the status document
(revisions, services, systemd recovery), the certificate, serving, network, pi-health and storage. It
re-implements no check, opens no connection, changes nothing and adds no endpoint.

Each check becomes one item: PASS is healthy, WARN or a non-blocking FAIL is degraded, a blocking FAIL is
action_required, UNKNOWN is unknown. The overall state is the worst item, in the order action_required,
degraded, unknown, healthy, so an unobserved fact never rolls up as healthy (as in AVR-31 and the
preflight). Two time rules: a preflight older than --max-age-min is not health, so every item is unknown;
and when the Pi's own clock is not trusted (`pi.clock` not PASS), the certificate items and the age of
the report cannot be judged either, so they are unknown with that reason (AVR-79).
"""
import argparse
from datetime import datetime, timezone
import json
import subprocess
import sys

SCHEMA = 'avrana.health/v0'
PREFLIGHT_SCHEMA = 'avrana.preflight/v0'
HEALTHY, DEGRADED, ACTION, UNKNOWN = 'healthy', 'degraded', 'action_required', 'unknown'
SEVERITY = {HEALTHY: 0, UNKNOWN: 1, DEGRADED: 2, ACTION: 3}
MAX_AGE_MIN = 15
UNTRUSTED_CLOCK = 'the date on this box is not trusted, so this cannot be judged'
# Checks whose answer depends on today's date.
TIME_DEPENDENT = ('tls.',)


def _parse_time(text):
    try:
        value = datetime.fromisoformat(str(text).replace('Z', '+00:00'))
    except ValueError:
        return None
    return value if value.tzinfo else None


def item_state(check):
    status = check.get('status')
    if status == 'PASS':
        return HEALTHY
    if status == 'WARN':
        return DEGRADED
    if status == 'FAIL':
        return ACTION if check.get('blocking') else DEGRADED
    return UNKNOWN


def worst(states):
    return max(states, key=SEVERITY.__getitem__, default=UNKNOWN)


def build_health(report, now=None, max_age_min=MAX_AGE_MIN):
    """Pure: an avrana.preflight/v0 document -> an avrana.health/v0 document."""
    now = now or datetime.now(timezone.utc)
    if not isinstance(report, dict) or report.get('schema') != PREFLIGHT_SCHEMA or not isinstance(report.get('checks'), list):
        return {'schema': SCHEMA, 'at': now.isoformat(), 'state': UNKNOWN, 'items': [],
                'reasons': ['no readable preflight report'], 'ready': None}
    checks = [c for c in report['checks'] if isinstance(c, dict) and isinstance(c.get('id'), str)]
    clock = next((c for c in checks if c['id'] == 'pi.clock'), None)
    clock_trusted = clock is not None and clock.get('status') == 'PASS'
    reasons = []
    stale = False
    generated = _parse_time(report.get('generated_at'))
    if not clock_trusted:
        reasons.append(f'the report\'s age: {UNTRUSTED_CLOCK}')
    elif generated is None:
        stale = True
        reasons.append('the preflight report has no readable time')
    elif (now - generated).total_seconds() > max_age_min * 60:
        stale = True
        reasons.append(f'the last check is {int((now - generated).total_seconds() // 60)} minutes old '
                       f'(more than {max_age_min}); run it again')
    items = []
    for c in checks:
        state, words = item_state(c), str(c.get('reason', ''))
        if stale:
            state = UNKNOWN
        elif not clock_trusted and c['id'].startswith(TIME_DEPENDENT):
            state, words = UNKNOWN, f'{words} ({UNTRUSTED_CLOCK})'
        item = {'id': c['id'], 'state': state, 'words': words, 'source': f'preflight:{c["id"]}'}
        if state == ACTION:
            item['action'] = {'kind': 'runbook', 'ref': 'docs/runbooks/service-recovery.md'
                              if c.get('category') == 'services' else 'docs/runbooks/preflight.md'}
        items.append(item)
    state = UNKNOWN if stale else worst([i['state'] for i in items])
    if not clock_trusted and state == HEALTHY:
        state = UNKNOWN
    ready = None if stale else {'verdict': report.get('verdict'), 'horizon_days': report.get('horizon_days')}
    items.sort(key=lambda i: (-SEVERITY[i['state']], i['id']))
    return {'schema': SCHEMA, 'at': now.isoformat(), 'state': state, 'items': items, 'reasons': reasons,
            'ready': ready, 'preflight_generated_at': report.get('generated_at')}


WORDS = {HEALTHY: 'Healthy', DEGRADED: 'Working, with problems', ACTION: 'Needs you', UNKNOWN: 'Not known'}


def render_text(doc):
    lines = [f'Avrana Health: {WORDS[doc["state"]]}']
    lines += [f'  ({r})' for r in doc['reasons']]
    for i in doc['items']:
        if i['state'] == HEALTHY:
            continue
        lines.append(f'- {WORDS[i["state"]]}: {i["words"]}  [{i["source"]}]')
        if 'action' in i:
            lines.append(f'    see {i["action"]["ref"]}')
    healthy = sum(1 for i in doc['items'] if i['state'] == HEALTHY)
    lines.append(f'{healthy} of {len(doc["items"])} checks healthy.')
    return '\n'.join(lines) + '\n'


def run_preflight(extra=()):
    out = subprocess.run([sys.executable, '-m', 'avrana.ops.preflight', '--json', *extra],
                         capture_output=True, text=True, timeout=600)
    return json.loads(out.stdout)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--preflight', metavar='PATH', help='an avrana.preflight/v0 JSON file, or - for stdin')
    ap.add_argument('--json', action='store_true', help='print the JSON document instead of the summary')
    ap.add_argument('--max-age-min', type=int, default=MAX_AGE_MIN, help='an older preflight report is not health')
    args, extra = ap.parse_known_args(argv)
    try:
        if args.preflight == '-':
            report = json.load(sys.stdin)
        elif args.preflight:
            with open(args.preflight, encoding='utf-8') as f:
                report = json.load(f)
        else:
            report = run_preflight(extra)
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        print(f'health: cannot read a preflight report: {e}', file=sys.stderr)
        report = None
    doc = build_health(report, max_age_min=args.max_age_min)
    sys.stdout.write(json.dumps(doc, indent=2) + '\n' if args.json else render_text(doc))
    return {HEALTHY: 0, DEGRADED: 1, ACTION: 2, UNKNOWN: 3}[doc['state']]


if __name__ == '__main__':
    sys.exit(main())
