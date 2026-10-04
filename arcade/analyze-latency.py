#!/usr/bin/env python3
"""Summarize a phone session from runtime/client-stats.jsonl.

Each line is one 1 Hz report the phone posted back over the control WebSocket,
paired with the server-side WebRTC view. Prints medians/p95 over the window so
we talk about distributions, not lifetime counters. Not an input-to-photon
number: name what each metric is.
"""
import json
import os
import sys
from pathlib import Path

LOG = Path(os.environ.get('AVRANA_ARCADE_RUNTIME') or Path(__file__).resolve().parent / 'runtime') / 'client-stats.jsonl'


def pct(values, q):
    data = sorted(v for v in values if v is not None)
    if not data:
        return None
    return round(data[min(len(data) - 1, int(q * len(data)))], 2)


def col(rows, *path):
    out = []
    for row in rows:
        node = row
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
        if isinstance(node, (int, float)):
            out.append(node)
    return out


def main():
    if not LOG.exists():
        sys.exit('No client-stats.jsonl yet; connect a phone and play first.')
    rows = [json.loads(line) for line in LOG.read_text().splitlines() if line.strip()]
    if len(sys.argv) > 1:  # optional: last N seconds only
        cutoff = rows[-1]['t'] - float(sys.argv[1])
        rows = [r for r in rows if r['t'] >= cutoff]
    clients = [r['client'] for r in rows if r.get('client')]
    print(f'{len(rows)} reports over {rows[-1]["t"] - rows[0]["t"]:.0f}s '
          f'from {sorted({r["addr"] for r in rows})}')
    paths = {r.get('path') for r in rows}
    print(f'network path (server-observed ICE): {paths}  '
          f'<- must be "avrana" for the AP, "other" means home Wi-Fi/cell')

    def show(label, values, unit=''):
        if values:
            print(f'  {label:24} p50 {pct(values,.5)}{unit}  p95 {pct(values,.95)}{unit}  '
                  f'max {pct(values,1)}{unit}  (n={len(values)})')

    print('\nVIDEO as the phone actually saw it:')
    show('decoded fps', col(clients, 'video', 'decoded'), '/s')
    show('jitter buffer delay', col(clients, 'video', 'jitterBufMs'), 'ms')
    show('decode time/frame', col(clients, 'video', 'decodeMs'), 'ms')
    show('processing delay', col(clients, 'video', 'procMs'), 'ms')
    show('dropped frames', col(clients, 'video', 'dropped'), '/s')
    show('packets lost', col(clients, 'video', 'pktLostD'), '/s')
    show('nack sent', col(clients, 'video', 'nack'), '/s')
    show('pli sent', col(clients, 'video', 'pli'), '/s')
    show('receive bitrate', col(clients, 'video', 'kbps'), 'kbps')
    print('\nPRESENTATION cadence (requestVideoFrameCallback gaps):')
    show('frame gap', col(clients, 'present', 'gapP50'), 'ms')
    show('frames >100ms late', col(clients, 'present', 'over100'), '/s')
    print('\nCONTROL path (WebSocket):')
    show('input ack RTT p50', col(clients, 'ackRtt', 'p50'), 'ms')
    show('input ack RTT p95', col(clients, 'ackRtt', 'p95'), 'ms')
    show('ping RTT', col(clients, 'pingRtt', 'p50'), 'ms')
    print('\nNETWORK (ICE candidate pair, client view):')
    show('pair RTT', [v * 1000 for v in col(clients, 'pair', 'rtt')], 'ms')
    print('\nSERVER RTCP (round-trip / loss the Pi received from the phone):')
    servers = [r['server'] for r in rows if r.get('server')]
    show('RR rtt video', [v * 1000 for v in col(servers, 'rr_video', 'rtt')], 'ms')
    show('RR jitter video', [v * 1000 for v in col(servers, 'rr_video', 'jitter')], 'ms')
    show('appsrc queue video', col(servers, 'queue', 'video'), ' buf')


if __name__ == '__main__':
    main()
