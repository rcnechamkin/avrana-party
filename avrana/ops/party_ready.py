"""Party Ready (avrana.party-ready/v0): the preflight, said for an owner who is about to leave home (AVR-86).

    python3 -m avrana.ops.preflight --horizon-days 7 --party-ready      # on the Pi: the plain answer
    python3 -m avrana.ops.party_ready preflight-<stamp>.json            # from a saved preflight (tools/preflight.py --out)
    python3 -m avrana.ops.party_ready - < preflight.json --json

This is not a second diagnostics subsystem. It reads one avrana.preflight/v0 document and groups its checks
into the few things an owner cares about (games, phones trusting the box, Wi-Fi, space, the box itself,
its software), each with one plain sentence and what to do. It runs nothing, opens no connection and
needs no Internet. The preflight's own rules decide: a blocking FAIL is something to fix, a blocking
UNKNOWN is something nobody could check, and READY needs neither. The raw check ids stay in `details`
for whoever helps the owner, and the preflight's list of what only a real phone can show is kept. A saved
preflight read from a file must be recent (MAX_AGE_H) to be READY.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import sys

SCHEMA = 'avrana.party-ready/v0'
PREFLIGHT_SCHEMA = 'avrana.preflight/v0'

# Each area: the check-id prefixes it covers, then what an owner reads when it is fine, when it needs a fix,
# and when it could not be checked, and what to do. Order is the order an owner reads them.
AREAS = (
    ('games', ('packages.', 'serving.', 'runtime.node'),
     'Games are on the box and it is serving them',
     'Some games or the party page are not being served',
     'Could not check that the games are being served',
     'Ask for help with the details below before you go; reinstalling a game does not need the Internet.'),
    ('trust', ('tls.',),
     'Phones will trust the box{until}',
     'Phones will refuse the box{before}',
     'Could not check the box\'s security certificate',
     'Renew the certificate at home, while the box has the Internet (docs/runbooks/party-https.md).'),
    ('wifi', ('network.', 'wifi.', 'dns.'),
     'The Party Wi-Fi is set up',
     'The Party Wi-Fi is not set up correctly',
     'The Party Wi-Fi has not been checked recently',
     'Run the Wi-Fi check at home (docs/runbooks/wifi-qualification.md) before you leave.'),
    ('space', ('storage.',),
     'There is enough free space',
     'The box is almost out of space',
     'Could not read the free space',
     'Remove games you will not play, or ask for help clearing old logs.'),
    ('health', ('service.', 'services', 'session.', 'pi.'),
     'The box is healthy',
     'The box has a health problem',
     'Could not check the box\'s health',
     'Restart the box once at home and run Party Ready again; if it repeats, ask for help with the details below.'),
    ('software', ('revision.', 'runtime.', 'config.'),
     'The box\'s software is complete',
     'The box\'s software is incomplete or mismatched',
     'Could not confirm which software the box is running',
     'Ask for help before you go: an update may not have finished.'),
)

ORDER = {'FAIL': 0, 'UNKNOWN': 1, 'WARN': 2, 'PASS': 3}
SETTLED = ('PASS', 'WARN')        # a blocking check in any other state (FAIL, UNKNOWN, unrecognised) is not fine
MAX_AGE_H = 24                    # a saved preflight older than this (or dated ahead) confirms nothing


def _now():
    return datetime.now(timezone.utc)


def _when(generated_at):
    try:
        then = datetime.fromisoformat(str(generated_at).replace('Z', '+00:00'))
    except ValueError:
        return None
    return then if then.tzinfo else None


def _age_hours(generated_at, now):
    then = _when(generated_at)
    return None if then is None else (now - then).total_seconds() / 3600


def area_of(check_id):
    for name, prefixes, *_ in AREAS:
        if any(check_id == p or check_id.startswith(p) for p in prefixes):
            return name
    return 'health'          # an unknown check is still shown, never dropped


def _horizon(days, generated_at):
    """The certificate sentence's ending. The preflight measured the horizon from when it ran, not from now, so a
    saved report names the date it covers; with no horizon only the moment of the check was covered."""
    if not days:
        return {'until': ' right now (no trip length was checked)', 'before': ''}
    then = _when(generated_at)
    if then is None:
        return {'until': f' for {days} days from the check', 'before': f' within {days} days of the check'}
    end = (then + timedelta(days=days)).astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    return {'until': f' until at least {end} ({days} days from the check)',
            'before': f' before {end} ({days} days from the check)'}


def summarize(doc, now=None, max_age_h=MAX_AGE_H):
    """The Party Ready document for one avrana.preflight/v0 document. Raises ValueError for anything else.
    With `now` (a saved report), one older than `max_age_h`, dated ahead or undated is never READY."""
    if not isinstance(doc, dict) or doc.get('schema') != PREFLIGHT_SCHEMA or not isinstance(doc.get('checks'), list):
        raise ValueError(f'not an {PREFLIGHT_SCHEMA} document')
    horizon = doc.get('horizon_days') or 0
    grouped = {name: [] for name, *_ in AREAS}
    for c in doc['checks']:
        if not isinstance(c, dict):
            raise ValueError('a preflight check is not an object')
        grouped[area_of(str(c.get('id', '')))].append(c)
    # The preflight only lets a blocking UNKNOWN be waived; a waiver of anything else (a hand-edited or foreign
    # report) is not honoured, so a FAIL listed as waived is still a FAIL.
    listed = {str(w) for w in doc.get('waived') or ()}
    waived = {c.get('id') for c in doc['checks'] if c.get('blocking') and c.get('status') == 'UNKNOWN' and c.get('id') in listed}
    ending = _horizon(horizon, doc.get('generated_at'))

    areas, fix, unchecked = [], [], []
    for name, _prefixes, ok_text, fail_text, unknown_text, action in AREAS:
        checks = grouped[name]
        blocking = [c for c in checks if c.get('blocking') and c.get('id') not in waived]
        if any(c.get('status') == 'FAIL' for c in blocking):
            state, says = 'fix', fail_text
        elif any(c.get('status') not in SETTLED for c in blocking):
            state, says = 'unchecked', unknown_text
        elif not checks:
            state, says = 'unchecked', unknown_text
        elif any(c.get('blocking') and c.get('id') in waived for c in checks):
            # Ready by the preflight's rule, but nobody checked it: say so rather than the all-clear sentence.
            state, says = 'accepted', unknown_text + ' (accepted without checking)'
        else:
            state, says = 'ok', ok_text
        says = says.format(**ending)
        warnings = [c for c in checks if c.get('status') == 'WARN']
        entry = {
            'area': name, 'state': state, 'says': says,
            'details': [{'id': c.get('id'), 'status': c.get('status'), 'reason': c.get('reason')}
                        for c in sorted(checks, key=lambda c: (ORDER.get(c.get('status'), 9), str(c.get('id'))))
                        if c.get('status') != 'PASS'],
        }
        if state != 'ok':
            entry['do'] = action
        if warnings and state in ('ok', 'accepted'):
            entry['note'] = f'{len(warnings)} thing(s) to keep an eye on; see the details'
        areas.append(entry)
        (fix if state == 'fix' else unchecked if state == 'unchecked' else []).append(entry)

    games_ok = areas[0]['state'] in ('ok', 'accepted')
    verdict = doc.get('verdict')
    stale = None
    if now is not None:
        age = _age_hours(doc.get('generated_at'), now)
        if age is None:
            stale = 'the saved check has no readable time'
        elif age > max_age_h:
            stale = f'the saved check is {int(age)} hours old; run it again'
        elif age < -0.1:
            stale = 'the saved check is dated in the future; run it again'
    if fix:
        headline = f'{len(fix)} thing{"s" if len(fix) != 1 else ""} to fix before leaving home'
        ready = False
    elif stale:
        headline, ready = f'Not confirmed: {stale}', None
    elif unchecked or verdict != 'READY':
        n = len(unchecked)
        headline = f'Not confirmed: {n} thing{"s" if n != 1 else ""} could not be checked' if n else 'Not confirmed'
        ready = None
    else:
        headline = 'READY FOR PARTY'
        ready = True
    return {
        'schema': SCHEMA,
        'from': {'schema': PREFLIGHT_SCHEMA, 'generated_at': doc.get('generated_at'), 'verdict': verdict,
                 'host': doc.get('host')},
        'ready': ready,
        'headline': headline,
        'horizon_days': horizon,
        'areas': areas,
        'waived': sorted(waived),
        # The preflight prepends its own Wi-Fi gate result to this list; the Wi-Fi area already says it.
        'phones_still_to_try': [u for u in doc.get('physically_unverified') or () if not str(u).startswith('Wi-Fi qualification:')],
        'offline_note': ('Phones keep no copy that counts: a phone that has never joined, or has cleared its '
                         'browser, still gets every game from the box. ' if games_ok else
                         'Phones keep no copy that counts and get every game from the box, so until the games line '
                         'above is OK they cannot be counted on. ')
                        + 'Reading this needed no Internet.',
    }


def render_text(ready_doc):
    mark = {'ok': 'OK ', 'fix': 'FIX', 'unchecked': ' ? ', 'accepted': ' ~ '}
    lines = [ready_doc['headline'], '']
    for a in ready_doc['areas']:
        lines.append(f'  [{mark[a["state"]]}] {a["says"]}')
        if a.get('do'):
            lines.append(f'        What to do: {a["do"]}')
        if a.get('note'):
            lines.append(f'        {a["note"]}')
    if ready_doc['waived']:
        lines += ['', 'Accepted without checking: ' + ', '.join(ready_doc['waived'])]
    if ready_doc['phones_still_to_try']:
        lines += ['', 'Only a real phone can show these:'] + [f'  - {u}' for u in ready_doc['phones_still_to_try']]
    details = [d for a in ready_doc['areas'] for d in a['details']]
    if details:
        lines += ['', 'Details for whoever helps you:'] + [f'  {d["status"]:7} {d["id"]}: {d["reason"]}' for d in details]
    return '\n'.join(lines) + '\n'


EXIT = {True: 0, False: 1, None: 3}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('preflight', help='an avrana.preflight/v0 JSON file, or - for standard input')
    ap.add_argument('--json', action='store_true', help='print the Party Ready JSON instead of the text')
    args = ap.parse_args(argv)
    try:
        text = sys.stdin.read() if args.preflight == '-' else open(args.preflight, encoding='utf-8').read()
        result = summarize(json.loads(text), now=_now())
    except (OSError, ValueError) as e:
        print(f'party-ready: {e}', file=sys.stderr)
        return 2
    sys.stdout.write(json.dumps(result, indent=2) + '\n' if args.json else render_text(result))
    return EXIT[result['ready']]


if __name__ == '__main__':
    sys.exit(main())
