#!/usr/bin/env python3
"""Capture a live arcade streaming window for later comparison.

Read-only: it polls the existing `/stats` endpoint (which already carries each
phone's self-reported WebRTC stats in peers[].client) and counts kernel
under-voltage dips over the same window. It does NOT touch the WebRTC/emulator
stack. Run it on `party` around a real multi-phone session:

    python3 arcade/capture-load.py --seconds 180

Then play. It prints a live per-slot line each second and, at the end, a summary
(per-slot medians + under-voltage dips during the window) and writes a JSONL log.

The per-slot summary is computed only over samples where players >= --min-players
(default 2), so idle head/tail before the phones connect don't skew it.
"""
import argparse, json, statistics, subprocess, sys, time, urllib.request
from datetime import datetime, timezone

DIP_RE = 'undervoltage|voltage normalis'


def dips_since(iso):
    """Authoritative under-voltage dip count since `iso` (no sudo; cody is in adm)."""
    try:
        out = subprocess.run(['journalctl', '-k', '--since', iso, '--no-pager'],
                             capture_output=True, text=True, timeout=15).stdout
        n = sum(1 for ln in out.splitlines()
                if any(w in ln.lower() for w in ('undervoltage', 'voltage normalis')))
        return n // 2  # each dip = one "detected" + one "normalised"
    except Exception as e:
        return f'err:{e}'


def vc(arg):
    try:
        return subprocess.run(['vcgencmd'] + arg.split(), capture_output=True,
                              text=True, timeout=5).stdout.strip()
    except Exception:
        return '?'


def get_stats(url):
    with urllib.request.urlopen(url, timeout=4) as r:
        return json.load(r)


def slot_line(p):
    c = p.get('client') or {}
    v = c.get('video') or {}
    pair = c.get('pair') or {}
    rtt = pair.get('rtt')
    rtt_ms = round(rtt * 1000) if isinstance(rtt, (int, float)) else '?'
    return (f"P{p.get('slot')} fps={v.get('fps','?')} loss={v.get('pktLostD','?')} "
            f"rtt={rtt_ms}ms jb={v.get('jitterBufMs','?')}ms kbps={v.get('kbps','?')} "
            f"frz={v.get('freezes','?')}")


def med(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(statistics.median(xs), 1) if xs else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seconds', type=int, default=180)
    ap.add_argument('--interval', type=float, default=1.0)
    ap.add_argument('--min-players', type=int, default=2)
    ap.add_argument('--url', default='http://127.0.0.1:8097/stats')
    ap.add_argument('--out', default=None)
    a = ap.parse_args()

    start_iso = datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')
    stamp = datetime.now().strftime('%Y%m%dT%H%M%S')
    out = a.out or f'{__import__("os").path.expanduser("~")}/avrana-captures/2p-{stamp}.jsonl'
    __import__('os').makedirs(__import__('os').path.dirname(out), exist_ok=True)

    print(f"# capture start {start_iso}  seconds={a.seconds}  url={a.url}")
    print(f"# throttled={vc('get_throttled')}  {vc('measure_temp')}  log={out}")
    print(f"# play now — summarising samples with players>={a.min_players}\n")

    samples = []
    t0 = time.monotonic()
    with open(out, 'w') as f:
        while time.monotonic() - t0 < a.seconds:
            ts = datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')
            try:
                s = get_stats(a.url)
                s['_ts'] = ts
                s['_temp'] = vc('measure_temp')
                s['_throttled'] = vc('get_throttled')
                f.write(json.dumps(s) + '\n'); f.flush()
                samples.append(s)
                peers = s.get('peers') or []
                line = ' | '.join(slot_line(p) for p in sorted(peers, key=lambda p: p.get('slot', 0)))
                el = int(time.monotonic() - t0)
                print(f"T+{el:>3}s players={s.get('players')} {s.get('_temp')} "
                      f"{s.get('_throttled')} | {line or '(no peers)'}")
            except Exception as e:
                print(f"T+{int(time.monotonic()-t0):>3}s stats error: {e}")
            time.sleep(a.interval)

    dips = dips_since(start_iso)
    loaded = [s for s in samples if (s.get('players') or 0) >= a.min_players]
    print(f"\n===== SUMMARY =====")
    print(f"window: {len(samples)} samples, {len(loaded)} with players>={a.min_players}")
    print(f"under-voltage dips during window: {dips}")
    if loaded:
        ages = [s.get('capture_age_ms', {}).get('video', {}).get('p50') for s in loaded]
        print(f"server capture_age video p50 (median): {med(ages)} ms")
        by_slot = {}
        for s in loaded:
            for p in (s.get('peers') or []):
                by_slot.setdefault(p.get('slot'), []).append(p)
        for slot in sorted(by_slot):
            ps = by_slot[slot]
            g = lambda k: [(p.get('client') or {}).get('video', {}).get(k) for p in ps]
            rtts = [(p.get('client') or {}).get('pair', {}).get('rtt') for p in ps]
            rtts = [r * 1000 for r in rtts if isinstance(r, (int, float))]
            print(f"  P{slot}: fps med={med(g('fps'))}  jitterBuf med={med(g('jitterBufMs'))}ms  "
                  f"pair-rtt med={med(rtts)}ms  lossD med={med(g('pktLostD'))}  "
                  f"kbps med={med(g('kbps'))}  freezes max={max([x for x in g('freezes') if isinstance(x,(int,float))] or [0])}")
    else:
        print(f"(no samples reached players>={a.min_players} — start the phones during the window)")
    print(f"\nlog: {out}")


if __name__ == '__main__':
    main()
