"""Statistics, environment capture and the report for the local performance harness (AVR-138).

Pure functions apart from environment(): no processes, no sockets, so tests/unit/test_perf_harness.py
can check them directly. party_perf.py does the measuring.

Percentiles use linear interpolation between closest ranks (the same as numpy's default and
statistics.quantiles(method='inclusive')): p50 of [1, 2, 3, 4] is 2.5. Small samples are reported
with their n so a p95 of five values is not read as a tail measurement.
"""
from __future__ import annotations

import math
import os
import platform
import statistics
import subprocess
import sys
from datetime import datetime, timezone

SCHEMA = 'avrana.perf-result/v1'


def percentile(values, q):
    """The q-th percentile (0..100) of values by linear interpolation; None for no values."""
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return None
    if not 0 <= q <= 100:
        raise ValueError('q must be within 0..100')
    pos = (len(xs) - 1) * q / 100.0
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return float(xs[lo])
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def summary(values, digits=3):
    """n, min, p50, p95, max, mean and sample stdev of values (None entries are dropped)."""
    xs = [float(v) for v in values if v is not None]
    if not xs:
        return {'n': 0}
    r = lambda v: None if v is None else round(v, digits)      # noqa: E731
    return {'n': len(xs), 'min': r(min(xs)), 'p50': r(percentile(xs, 50)), 'p95': r(percentile(xs, 95)),
            'max': r(max(xs)), 'mean': r(statistics.fmean(xs)),
            'stdev': r(statistics.stdev(xs)) if len(xs) > 1 else 0.0}


def across(repeats, field='p50', digits=3):
    """How one statistic varied across repeats: the per-repeat values, their median, min, max and
    coefficient of variation (stdev / mean). `repeats` is a list of summary() dicts."""
    vals = [s.get(field) for s in repeats if s and s.get(field) is not None]
    if not vals:
        return {'n': 0, 'values': []}
    mean = statistics.fmean(vals)
    sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
    # relative spread; undefined around a zero mean (growth deltas, idle CPU), where it would read as 0
    cv = 0.0 if sd == 0 else (round(sd / abs(mean), 3) if mean else None)
    return {'n': len(vals), 'values': [round(v, digits) for v in vals], 'median': round(statistics.median(vals), digits),
            'min': round(min(vals), digits), 'max': round(max(vals), digits), 'cv': cv}


def bounded(value, lo, hi, name):
    """value, refused outside lo..hi: benchmarks are opt-in and must stay bounded."""
    if not lo <= value <= hi:
        raise ValueError(f'{name} must be within {lo}..{hi}, got {value}')
    return value


def _git(root, *args):
    try:
        out = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def revision(root):
    """{commit, dirty} of a checkout, or None if it is not one (or git is missing)."""
    if root is None:
        return None
    commit = _git(root, 'rev-parse', 'HEAD')
    if commit is None:
        return None
    return {'commit': commit, 'dirty': bool(_git(root, 'status', '--porcelain', '--untracked-files=no'))}


def environment(party_root, games_root=None):
    """Where a result came from. Laptop numbers are not Pi numbers: the platform says which."""
    env = {'captured_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
           'os': platform.platform(), 'machine': platform.machine(), 'processor': platform.processor() or None,
           'python': sys.version.split()[0], 'logical_cpus': os.cpu_count(),
           'party': revision(party_root), 'games': revision(games_root)}
    try:
        import psutil
        env['psutil'] = psutil.__version__
        env['memory_total_mb'] = round(psutil.virtual_memory().total / 2**20)
        freq = psutil.cpu_freq()
        env['cpu_mhz_max'] = round(freq.max) if freq and freq.max else None
    except ImportError:
        env['psutil'] = None
    return env


def _cell(s, field='p50', unit=''):
    if not s or s.get('n', 0) == 0 or s.get(field) is None:
        return 'n/a'
    return f'{s[field]:g}{unit}'


def _spread(a):
    if not a or not a.get('n'):
        return 'n/a'
    cv = 'n/a' if a.get('cv') is None else f"{a['cv']:.2f}"
    return f"{a['median']:g} ({a['min']:g}-{a['max']:g}, cv {cv})"


def markdown(result):
    """A short human-readable comparison of one result document."""
    env, cfg = result['environment'], result['config']
    party = env.get('party') or {}
    games = env.get('games') or {}
    lines = [f"# Local performance run {env['captured_at']}", '',
             f"Evidence: **{result['evidence']}**. Not a Pi, not Wi-Fi, not a phone.", '',
             f"- Host: {env['os']}, {env['logical_cpus']} logical CPUs, Python {env['python']}",
             f"- Party: {party.get('commit', 'unknown')[:12]}{' (dirty)' if party.get('dirty') else ''}; "
             f"Games: {(games.get('commit') or 'not used')[:12]}{' (dirty)' if games.get('dirty') else ''}",
             f"- Repeats: {cfg['repeats']}; each value below is the median across repeats, "
             '(min-max across repeats, coefficient of variation)', '']
    for name, sc in result['scenarios'].items():
        lines.append(f'## {name}')
        lines.append('')
        if sc.get('skipped'):
            lines.append(f"Not measured: {sc['skipped']}")
            lines.append('')
            continue
        lines.append(sc.get('what', ''))
        lines.append('')
        lines.append(f"Evidence: {sc.get('evidence', 'unstated')}.")
        lines.append('')
        bound = cfg.get('client_bound_pct', 70.0)
        for i, run in enumerate(sc.get('runs', [])):
            if 'error' in run:
                lines.append(f"- **repeat {i + 1} failed:** {run['error']}")
            gen = (run.get('load_generator') or {}).get('cpu_pct_window')
            if gen is not None and gen > bound:
                lines.append(f"- repeat {i + 1}: this harness used {gen:g}% of a core; the result may be client-bound")
            for note in run.get('notes') or []:
                lines.append(f"- repeat {i + 1}: {note}")
            if run.get('poll_errors'):
                lines.append(f"- repeat {i + 1}: poll errors {run['poll_errors']}")
        if sc.get('errors'):
            lines.append('')
        lines.append('| metric | unit | median across repeats (range, cv) |')
        lines.append('|---|---|---|')
        for metric, a in sc.get('aggregate', {}).items():
            lines.append(f"| {metric} | {a.get('unit', '')} | {_spread(a)} |")
        lines.append('')
    return '\n'.join(lines) + '\n'
