"""The time floor and time state (AVR-79 R2-R4): what this appliance may believe about today's date offline.

    python3 -m avrana.ops.timefloor status            # the time state, read only, as the operator
    sudo python3 -m avrana.ops.timefloor record       # raise the floor to now if NTP is synchronised

PROTOTYPE for docs/design/proposals/2026-10-26-offline-clock-policy.md (owner decision D2 is open). Nothing
installs a timer, a boot step or a status field: this is the pure logic and a manual command.

The floor is one UTC instant in a root-owned file: the latest time this unit has trusted. It only ever moves
forward (R1), by a synchronised NTP clock or, later, by a verified signed `issued` time (R5); one step may
move it at most `FORWARD_CAP` past the previous floor unless the caller says NTP agreed twice (D4). A
phone's time, a request header or a browser clock can never reach it: nothing here takes one.

The time state (R3) is `synced` (NTP synchronised this boot and not behind the floor), `floor` (not
synchronised; the clock is at least the floor, so time is a lower bound) or `unknown` (no readable floor, or
the clock is more than a day behind the floor: a rollback or a damaged file). `judge` is R4: in `synced` an
expiry is decided normally; in `floor` only an item already valid at the floor and not yet expired by it is
accepted, with "time not verified"; in `unknown` nothing that needs freshness is accepted.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

FLOOR_PATH = '/var/lib/avrana-party/time-floor'
FORWARD_CAP = timedelta(days=30)
SKEW = timedelta(days=1)
SYNCED, FLOOR, UNKNOWN = 'synced', 'floor', 'unknown'


def _iso(dt):
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _parse(text):
    try:
        value = datetime.fromisoformat(str(text).strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    return value if value.tzinfo else None


def read_floor(path=FLOOR_PATH):
    """The floor, or None when the file is missing, unreadable or not one aware ISO instant."""
    try:
        text = Path(path).read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return None
    return _parse(text) if len(text) < 64 else None


def write_floor(path, instant):
    """Atomically replace the floor file (same directory, then rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.time-floor-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(_iso(instant) + '\n')
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def advance(floor, candidate, agreed_twice=False, cap=FORWARD_CAP):
    """The floor after trusting `candidate` (a synchronised clock, or a verified `issued` time).
    Never backwards; at most `cap` past the previous floor unless NTP agreed twice (D4)."""
    if candidate is None:
        return floor
    if floor is None:
        return candidate
    if candidate <= floor:
        return floor
    if not agreed_twice and candidate - floor > cap:
        return floor + cap
    return candidate


def time_state(now, floor, synced):
    """{state, floor, reason} for this clock, floor and NTP state (R3)."""
    if floor is None:
        return {'state': UNKNOWN, 'floor': None, 'reason': 'no time floor recorded'}
    if now < floor - SKEW:
        return {'state': UNKNOWN, 'floor': _iso(floor),
                'reason': f'the clock is more than a day behind the time floor ({_iso(floor)})'}
    if synced:
        return {'state': SYNCED, 'floor': _iso(floor), 'reason': 'NTP synchronised'}
    return {'state': FLOOR, 'floor': _iso(floor),
            'reason': 'not synchronised: the date is at least the floor and may be behind'}


def judge(valid_from, valid_until, state, now, floor):
    """R4 for one item with a validity window: (accepted, words)."""
    if state == SYNCED:
        if valid_from is not None and now < valid_from:
            return False, 'not valid yet'
        if valid_until is not None and now >= valid_until:
            return False, 'expired'
        return True, 'valid'
    if state == FLOOR and floor is not None:
        if valid_until is not None and floor >= valid_until:
            return False, 'expired (certainly: it ended before the time floor)'
        if valid_from is not None and floor < valid_from:
            return False, 'cannot tell whether it is valid yet: time not verified'
        return True, 'valid as far as the time floor shows; time not verified'
    return False, 'cannot tell: the date on this box is not trusted'


def ntp_synchronised(runner=subprocess.run):
    """True or False from timedatectl, or None when it cannot be asked."""
    try:
        out = runner(['timedatectl', 'show', '-p', 'NTPSynchronized', '--value'],
                     capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    value = out.stdout.strip().lower()
    return True if value == 'yes' else False if value == 'no' else None


def record(path=FLOOR_PATH, now=None, synced=None, agreed_twice=False):
    """Raise the floor to now if NTP is synchronised (R2); returns (old, new). Writes nothing otherwise."""
    now = now or datetime.now(timezone.utc)
    synced = ntp_synchronised() if synced is None else synced
    old = read_floor(path)
    if not synced:
        return old, old
    new = advance(old, now, agreed_twice)
    if new != old:
        write_floor(path, new)
    return old, new


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--floor', default=FLOOR_PATH, help=f'the floor file (default {FLOOR_PATH})')
    sub = ap.add_subparsers(dest='command', required=True)
    sub.add_parser('status', help='print the time state as JSON (read only)')
    sub.add_parser('record', help='raise the floor to now if NTP is synchronised (root)')
    a = ap.parse_args(argv)
    now = datetime.now(timezone.utc)
    if a.command == 'record':
        try:
            old, new = record(a.floor, now)
        except OSError as e:
            print(f'timefloor: cannot write {a.floor}: {e}', file=sys.stderr)
            return 1
        print(f'floor {_iso(old) if old else "none"} -> {_iso(new) if new else "none"}'
              + ('' if new != old else ' (unchanged: not synchronised, or not ahead)'))
        return 0
    synced = ntp_synchronised()
    doc = dict(time_state(now, read_floor(a.floor), bool(synced)), now=_iso(now),
               ntp='unavailable' if synced is None else ('yes' if synced else 'no'))
    print(json.dumps(doc, indent=2))
    return {SYNCED: 0, FLOOR: 1, UNKNOWN: 3}[doc['state']]


if __name__ == '__main__':
    sys.exit(main())
