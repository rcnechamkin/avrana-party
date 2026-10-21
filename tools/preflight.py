#!/usr/bin/env python3
"""Run the appliance preflight from the laptop, with the laptop's latest Wi-Fi qualification result.

    python tools/preflight.py --ssh party                       # report; exit 0 READY, 1 NOT_READY, 3 UNKNOWN
    python tools/preflight.py --ssh party --horizon-days 7 --out test-results/preflight
    python tools/preflight.py --ssh party --wifi-gate tools/wifi-lab/results/<stamp>_gate_XXXX/gate.json
    python tools/preflight.py --ssh party --no-wifi             # no gate result: wifi.gate is UNKNOWN, said so

The checks themselves are `python3 -m avrana.ops.preflight` on the Pi (docs/runbooks/preflight.md):
this only carries them over the operator's existing SSH login (the `party` alias tools/wifi-lab
already uses; key auth, BatchMode, nothing typed), streams the newest local
tools/wifi-lab/results/*_gate_*/gate.json to it on standard input, and saves the JSON and a
Markdown copy locally. The wifi-lab results stay on the laptop otherwise (they hold MACs and
device names); only the gate document travels, and only to the Pi.

The appliance runs the preflight from its deployed code release (/opt/avrana-party/current) unless
--remote-dir names another tree, e.g. the operator's checkout before this tool is deployed.
"""
import argparse
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from avrana.ops import preflight  # noqa: E402

DEFAULT_RESULTS = ROOT / 'tools' / 'wifi-lab' / 'results'
DEFAULT_REMOTE_DIR = '/opt/avrana-party/current'


def remote_command(remote_dir, args):
    flags = ['--json', '--wifi-gate', '-', '--horizon-days', str(args.horizon_days),
             '--wifi-max-age-h', str(args.wifi_max_age_h)]
    for check_id in args.waive:
        flags += ['--waive', check_id]
    return f'cd {shlex.quote(remote_dir)} && exec python3 -m avrana.ops.preflight ' + ' '.join(map(shlex.quote, flags))


def gate_text(args):
    """(text to stream, local description)."""
    if args.no_wifi:
        return '', 'not supplied (--no-wifi)'
    path = Path(args.wifi_gate) if args.wifi_gate else preflight.newest_gate(DEFAULT_RESULTS)
    if path is None:
        return '', f'none found under {DEFAULT_RESULTS}'
    try:
        if path.is_dir():
            path = preflight.newest_gate(path)
            if path is None:
                return '', f'none found under {args.wifi_gate}'
        return path.read_text(encoding='utf-8'), str(path)
    except OSError as e:
        return '', f'{path} unreadable ({e.strerror})'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--ssh', default='party', help='ssh destination (default: the `party` alias)')
    ap.add_argument('--remote-dir', default=DEFAULT_REMOTE_DIR, help=f'Party tree on the Pi (default {DEFAULT_REMOTE_DIR})')
    ap.add_argument('--wifi-gate', metavar='PATH', help='a gate.json or results directory (default: the newest local one)')
    ap.add_argument('--no-wifi', action='store_true', help='send no gate result')
    ap.add_argument('--wifi-max-age-h', type=float, default=preflight.WIFI_GATE_MAX_AGE_H)
    ap.add_argument('--horizon-days', type=int, default=0)
    ap.add_argument('--waive', action='append', default=[], metavar='CHECK_ID')
    ap.add_argument('--out', default=str(ROOT / 'test-results' / 'preflight'))
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--timeout', type=float, default=180.0)
    args = ap.parse_args(argv)
    text, described = gate_text(args)
    print(f'wifi-lab gate: {described}', file=sys.stderr)
    cmd = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', args.ssh, remote_command(args.remote_dir, args)]
    try:
        p = subprocess.run(cmd, input=text, capture_output=True, text=True, timeout=args.timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f'preflight: could not run over ssh ({type(e).__name__}); the appliance state is UNKNOWN', file=sys.stderr)
        return 3
    try:
        doc = json.loads(p.stdout)
    except ValueError:
        tail = (p.stderr or p.stdout).strip().splitlines()[-3:]
        hint = ' (is avrana.ops.preflight deployed? try --remote-dir /home/cody/avrana-party)' \
            if 'No module named' in (p.stderr or '') else ''
        print(f'preflight: no result from {args.ssh} (exit {p.returncode}){hint}: ' + ' | '.join(tail), file=sys.stderr)
        return 3
    doc.setdefault('notes', []).append(f'run from the laptop over ssh {args.ssh}; wifi-lab gate {described}')
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = doc['generated_at'].replace(':', '').replace('-', '')
    (out / f'preflight-{stamp}.json').write_text(json.dumps(doc, indent=2) + '\n', encoding='utf-8')
    (out / f'preflight-{stamp}.md').write_text(preflight.render_markdown(doc), encoding='utf-8')
    sys.stdout.write(json.dumps(doc, indent=2) + '\n' if args.json else preflight.render_text(doc))
    print(f'saved {out / f"preflight-{stamp}.json"}', file=sys.stderr)
    return preflight.EXIT.get(doc.get('verdict'), 3)


if __name__ == '__main__':
    sys.exit(main())
