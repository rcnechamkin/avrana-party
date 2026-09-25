#!/usr/bin/env python3
"""Summarise a PS1 latency log (stdlib only).

    latency-report.py FILE.jsonl [--phone IP] [--since HH:MM] [--until HH:MM]

FILE is $AVRANA_PS1_HOME/runtime/latency/<session>.jsonl (measure mode) or runtime/client-stats.jsonl
(always on; fewer stages). One line per phone per second, written by stream_ps1.py's log_client().

Stages (all ms). EXACT = one clock; EST = two clocks joined by the clock-offset estimate
(error <= half the best ping round trip, printed as "clock ±"):
  A  touch -> input sent          phone          EXACT
  B  input sent -> server got it   phone->Pi      EST (one-way uplink)
  C  server got it -> key injected Pi             EXACT
  E  frame captured -> shown       Pi->phone      EST (encode+send+jitter buffer+decode+render; measure mode)
  D  touch -> first frame captured after the injection is shown   EST-free (phone clock only; measure mode)
     D excludes the game's own reaction time (1-3 frames) and the panel's scan-out.
  ws_rtt   WebSocket ping round trip (JS on both ends)
  icmp     kernel ping Pi -> phone round trip (measure mode; the phone's OS answers even if its browser stalls)
Spike seconds (ws round trip or frame gap > 100 ms) are classified by what else happened that second.
"""
import argparse
import json
import time


def pct(values, q):
    v = sorted(values)
    return None if not v else v[min(len(v) - 1, int(q * len(v)))]


def row(name, values, label=''):
    v = [x for x in values if isinstance(x, (int, float))]
    if not v:
        return f'  {name:<9} (no samples)'
    p50, p95, p99 = pct(v, .5), pct(v, .95), pct(v, .99)
    return (f'  {name:<9} n={len(v):<6} p50={p50:<8.1f} p95={p95:<8.1f} p99={p99:<8.1f} max={max(v):<8.1f}'
            f' jitter(p95-p50)={p95 - p50:.1f}  {label}')


def hm(text):
    h, m = map(int, text.split(':'))
    return h * 60 + m


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('file')
    ap.add_argument('--phone', help='only this phone IP (ICE remote address)')
    ap.add_argument('--since'), ap.add_argument('--until')
    a = ap.parse_args()
    recs = []
    for line in open(a.file, encoding='utf-8'):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        ip = ((r.get('server') or {}).get('ice') or {}).get('remote')
        if a.phone and ip != a.phone:
            continue
        lt = time.localtime(r['t'])
        mins = lt.tm_hour * 60 + lt.tm_min
        if (a.since and mins < hm(a.since)) or (a.until and mins > hm(a.until)):
            continue
        r['_ip'] = ip
        recs.append(r)
    if not recs:
        print('no records')
        return
    recs = [r for r in recs if (r.get('client') or {}).get('vis', 'visible') == 'visible']
    ips = sorted({str(r['_ip']) for r in recs})
    print(f'{len(recs)} visible phone-seconds, phones {ips}, '
          f'{time.strftime("%H:%M:%S", time.localtime(recs[0]["t"]))} -> {time.strftime("%H:%M:%S", time.localtime(recs[-1]["t"]))}')
    st = {k: [] for k in ('A', 'B', 'C', 'D', 'E', 'rtt')}
    icmp, lag, gaps, clock, lost_s, icmp_lost = [], [], [], [], 0, 0
    for r in recs:
        c = r['client']
        for k in st:
            v = (c.get('lat') or {}).get(k)
            if isinstance(v, list):
                st[k] += v
        if not (c.get('lat') or {}).get('rtt') and (c.get('pingRtt') or {}).get('max') is not None:
            st['rtt'].append(c['pingRtt']['max'])                  # older logs: per-second max only
        srv = r.get('srv') or {}
        icmp += (srv.get('icmp') or {}).get('ok') or []
        icmp_lost += (srv.get('icmp') or {}).get('lost') or 0
        if (srv.get('loop_lag') or {}).get('max') is not None:
            lag.append(srv['loop_lag']['max'])
        if (c.get('present') or {}).get('gapMax') is not None:
            gaps.append(c['present']['gapMax'])
        if (c.get('clock') or {}).get('rtt') is not None:
            clock.append(c['clock']['rtt'] / 2)
        lost_s += 1 if (c.get('video') or {}).get('pktLostD') else 0
    print(f'clock offset error bound (median half-best-RTT): ±{pct(clock, .5) if clock else "?"} ms\n')
    print('Stages (ms; A, C exact; B, E estimated across clocks; D phone clock only):')
    labels = dict(A='touch->sent', B='sent->Pi (one-way)', C='Pi got->injected', E='captured->shown',
                  D='touch->post-inject frame shown', rtt='WebSocket round trip')
    for k in ('A', 'B', 'C', 'E', 'D', 'rtt'):
        print(row(k, st[k], labels[k]))
    print(row('icmp', icmp, f'kernel ping round trip, {icmp_lost} unanswered'))
    print(row('loop_lag', lag, 'server event loop, max per second'))
    print(row('gap_max', gaps, 'longest gap between shown frames, per second'))
    print(f'  seconds with video packet loss: {lost_s} of {len(recs)}')
    spikes = collections_counter = {'network': 0, 'server': 0, 'browser/phone': 0, 'unknown': 0}
    examples = []
    for i, r in enumerate(recs):
        c, srv = r['client'], r.get('srv') or {}
        ws = max((c.get('lat') or {}).get('rtt') or [(c.get('pingRtt') or {}).get('max') or 0])
        gap = (c.get('present') or {}).get('gapMax') or 0
        if ws <= 100 and gap <= 100:
            continue
        near = recs[max(0, i - 1):i + 2]
        ic = [x for n in near for x in ((n.get('srv') or {}).get('icmp') or {}).get('ok') or []]
        ic_lost = sum(((n.get('srv') or {}).get('icmp') or {}).get('lost') or 0 for n in near)
        lg = max([((n.get('srv') or {}).get('loop_lag') or {}).get('max') or 0 for n in near])
        if lg > 50:
            why = 'server'
        elif ic and (max(ic) > 100 or ic_lost):
            why = 'network'
        elif ic:
            why = 'browser/phone'
        else:
            why = 'unknown'
        spikes[why] += 1
        if len(examples) < 15:
            examples.append(f'    {time.strftime("%H:%M:%S", time.localtime(r["t"]))} ws_rtt_max={ws:.0f} gap_max={gap:.0f} '
                            f'icmp_max={max(ic) if ic else "-"} icmp_lost={ic_lost} loop_lag={lg:.0f} -> {why}')
    total = sum(spikes.values())
    print(f'\nSpike seconds (ws round trip or frame gap > 100 ms): {total} of {len(recs)}')
    for k, v in spikes.items():
        print(f'  {k:<14} {v}')
    print('\n'.join(examples))


if __name__ == '__main__':
    main()
