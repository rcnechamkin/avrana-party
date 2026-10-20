#!/usr/bin/env python3
"""Local, repeatable performance measurements of Party Core and the Games server (AVR-138).

Opt-in and bounded: nothing runs it automatically. Every scenario starts fresh processes on loopback,
the way the appliance runs them (Party Core and the Games server are separate processes), measures
with a monotonic high-resolution clock (time.perf_counter), repeats, and writes one JSON document plus a short Markdown comparison.

    python tools/perf/party_perf.py [--games PATH_TO_GAMES_CHECKOUT] [--repeats 3] [--out DIR] [--quick]

Evidence, per scenario (also written into the result):
  idle, longpoll  REAL Party Core process (`python -m avrana.party.service --config`). SIMULATED phones:
                  Python HTTP clients on loopback that poll /party/api/state the way party-client.js
                  does (same wait). No browser, no nginx/TLS, no Wi-Fi.
  lifecycle       REAL Party Core + REAL Games server (server.py, uvicorn) processes; BLUFF through the
                  Party pregame, Start, tickets, WebSocket hello, a reconnect, End. Python WebSocket
                  clients stand in for phones.
  realtime        REAL Games server running dodgeball's real 30 Hz simulation, joined by Python
                  WebSocket clients that send 20 Hz input and ping. STANDALONE admission: dodgeball has
                  no Party contract, so this measures game-server overhead, not a Party session.
Laptop numbers are laptop numbers: none of this is a Pi, a phone or a radio measurement
(docs/runbooks/performance-measurement.md has the procedure for those).

Needs psutil for CPU/RSS/thread figures (absent: those fields are null and say why) and, for the two
Games scenarios, an interpreter with the Games requirements (fastapi, uvicorn, websockets).
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import random
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

PARTY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PARTY_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import perfstats                                   # noqa: E402
from avrana.party import protocol                  # noqa: E402

HOST = 'party.perf.test'
ORIGIN = 'https://party.perf.test'
NAMES = ['Ana', 'Ben', 'Cat', 'Dev', 'Eli', 'Fay', 'Gus', 'Hal', 'Ivy', 'Jo', 'Kim', 'Lu', 'Mo', 'Ned', 'Oz', 'Pia']
MAX_CLIENTS = len(NAMES)
SAMPLE_EVERY = 0.25                                 # s between process samples
MOVE_EVERY = 0.09                                   # s: dodgeball.js sends a changed joystick at most every 90 ms


def client_wait():
    """The long-poll wait the real Party page uses (web/party/lib/party-client.js WAIT_S)."""
    src = (PARTY_ROOT / 'web' / 'party' / 'lib' / 'party-client.js').read_text(encoding='utf-8')
    m = re.search(r'const WAIT_S = (\d+)', src)
    return int(m.group(1)) if m else 20


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def wait_until(pred, timeout, what):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if pred():
            return
        time.sleep(0.02)
    raise TimeoutError(f'timed out waiting for {what}')


def listening(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.2):
            return True
    except OSError:
        return False


# ---- process metrics ------------------------------------------------------------------------------

class Sampler:
    """CPU (% of one core), RSS and thread count of one process, sampled on a thread over a window.
    Without psutil every figure is None and `unavailable` says why."""

    def __init__(self, pid):
        try:
            import psutil
            self.proc = psutil.Process(pid)
            self.unavailable = None
        except ImportError:
            self.proc, self.unavailable = None, 'psutil not installed'
        self.cpu, self.rss, self.threads = [], [], []
        self._stop = threading.Event()
        self._t = None
        self._start = None
        self.gone = False

    def snapshot(self):
        """(rss MB, threads) now, or (None, None)."""
        if self.proc is None:
            return None, None
        return round(self.proc.memory_info().rss / 2**20, 2), self.proc.num_threads()

    def _cpu_seconds(self):
        t = self.proc.cpu_times()
        return t.user + t.system

    def start(self):
        if self.proc is None:
            return self
        self._start = (time.perf_counter(), self._cpu_seconds())
        self._stop.clear()

        def loop():
            last = self._start
            while not self._stop.wait(SAMPLE_EVERY):
                try:
                    now = (time.perf_counter(), self._cpu_seconds())
                    rss, threads = self.snapshot()
                except Exception:               # the process ended (a failed run): stop sampling
                    self.gone = True
                    return
                self.cpu.append(100.0 * (now[1] - last[1]) / max(now[0] - last[0], 1e-6))
                last = now
                self.rss.append(rss)
                self.threads.append(threads)

        self._t = threading.Thread(target=loop, daemon=True)
        self._t.start()
        return self

    def stop(self):
        """{cpu_pct_window, cpu_pct (per-interval summary), rss_mb, threads} for the window."""
        if self.proc is None:
            return {'unavailable': self.unavailable}
        self._stop.set()
        self._t.join()
        if self.gone:
            return {'unavailable': 'the process ended during the window'}
        end = (time.perf_counter(), self._cpu_seconds())
        window = 100.0 * (end[1] - self._start[1]) / max(end[0] - self._start[0], 1e-6)
        return {'cpu_pct_window': round(window, 2), 'cpu_pct': perfstats.summary(self.cpu, 2),
                'rss_mb': perfstats.summary(self.rss, 2), 'threads': perfstats.summary(self.threads, 1)}


# ---- the processes --------------------------------------------------------------------------------

class Stack:
    """Party Core (always) and the Games server (with --games) as separate loopback processes."""

    def __init__(self, games_root=None):
        self.tmp = Path(tempfile.mkdtemp(prefix='avrana-perf-'))
        self.games_root = games_root
        self.party_port = free_port()
        self.games_port = free_port()
        keys = self.tmp / 'keys'
        keys.mkdir()
        key = protocol.new_key()
        protocol.write_key(str(keys / 'bluff.key'), key)
        # BLUFF is always registered (its contract gives the pregame); without --games its url is a
        # port nothing listens on, which launch -> setup -> home never touches.
        config = {'hosts': [HOST], 'origins': [ORIGIN], 'secure_cookie': True,
                  'devices': str(self.tmp / 'devices.json'),
                  'games': {'bluff': {'url': f'http://127.0.0.1:{self.games_port}/games/bluff',
                                      'key_file': str(keys / 'bluff.key')}}}
        (self.tmp / 'party-core.json').write_text(json.dumps(config), encoding='utf-8')
        self.log = open(self.tmp / 'processes.log', 'ab')
        self.games = None
        if games_root is not None:
            env = dict(os.environ, AVRANA_PARTY_KEYS=str(keys), AVRANA_PARTY_URL=f'http://127.0.0.1:{self.party_port}',
                       LANGAMES_PORT=str(self.games_port), LANGAMES_HOST='127.0.0.1')
            self.games = subprocess.Popen([sys.executable, 'server.py'], cwd=str(games_root), env=env,
                                          stdout=self.log, stderr=self.log)
        self.party = subprocess.Popen([sys.executable, '-m', 'avrana.party.service', '--config',
                                       str(self.tmp / 'party-core.json'), '--port', str(self.party_port)],
                                      cwd=str(PARTY_ROOT), stdout=self.log, stderr=self.log)
        try:
            wait_until(lambda: self.party.poll() is None and listening(self.party_port), 20, 'Party Core')
            if self.games is not None:
                wait_until(lambda: self.games.poll() is None and listening(self.games_port), 60, 'the Games server')
        except Exception:
            self.stop()
            raise

    def stop(self):
        for p in (self.party, self.games):
            if p is not None and p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait(timeout=10)
        self.log.close()
        shutil.rmtree(self.tmp, True)


# ---- a phone --------------------------------------------------------------------------------------

class Phone:
    """One simulated phone: a cookie, Party HTTP calls (one connection each, as nginx's upstream
    does), and an optional long-poll loop. Counts requests and application bytes (status line,
    headers and body; no TCP/IP or TLS overhead)."""

    def __init__(self, stack, name):
        self.stack, self.name = stack, name
        self.cookie = None
        self.requests = 0
        self.bytes_in = 0
        self.bytes_out = 0
        self.version = 0
        self.received = []                       # (monotonic time, version) of each long-poll answer
        self.view = None
        self._poll = None
        self._stop = threading.Event()
        self.ws = None

    def req(self, method, path, body=None, timeout=40):
        conn = http.client.HTTPConnection('127.0.0.1', self.stack.party_port, timeout=timeout)
        headers = {'Host': HOST}
        if self.cookie:
            headers['Cookie'] = self.cookie
        data = None
        if method == 'POST':
            data = json.dumps(body or {}).encode()
            headers.update({'Origin': ORIGIN, 'Content-Type': 'application/json'})
        conn.request(method, path, body=data, headers=headers)
        r = conn.getresponse()
        raw = r.read()
        sc = r.getheader('Set-Cookie')
        if sc:
            self.cookie = sc.split(';')[0]
        conn.close()
        self.requests += 1
        self.bytes_out += len(f'{method} {path} HTTP/1.1\r\n') + sum(len(k) + len(v) + 4 for k, v in headers.items()) \
            + 2 + len(data or b'')
        self.bytes_in += len(str(r.msg)) + 17 + len(raw)
        out = json.loads(raw) if raw else None
        return r.status, out

    def post(self, path, body=None):
        return self.req('POST', '/party/api/' + path, body)

    def state(self, wait=0):
        status, v = self.req('GET', f'/party/api/state?since={self.version}&wait={wait}')
        if status == 200 and v:
            self.view = v
            self.version = max(self.version, v.get('version', 0))
        return status, v

    def act(self, path, body=None):
        """A versioned action, as the page sends it (if_version: the view it acted on)."""
        _, v = self.state()
        return self.post(path, {**(body or {}), 'if_version': v['version']})

    def start_polling(self, wait):
        def loop():
            while not self._stop.is_set():
                try:
                    status, v = self.req('GET', f'/party/api/state?since={self.version}&wait={wait}', timeout=wait + 10)
                except OSError:
                    if self._stop.is_set():
                        return
                    time.sleep(0.2)
                    continue
                if status == 200 and v:
                    self.view = v
                    if v.get('version', 0) > self.version:
                        self.version = v['version']
                        self.received.append((time.perf_counter(), self.version))
        self._poll = threading.Thread(target=loop, daemon=True)
        self._poll.start()

    def stop_polling(self):
        self._stop.set()

    def seen(self, version):
        """The monotonic time this phone's long poll first delivered `version` or newer, or None."""
        return next((t for t, v in self.received if v >= version), None)

    # -- the game side --
    def ticket(self, game='bluff'):
        status, body = self.post('session/ticket', {'game': game})
        if status != 200:
            raise RuntimeError(f'{self.name}: no ticket ({status} {body})')
        return body['ticket']

    def open_game(self, game='bluff'):
        """Ticket, WebSocket hello, first game state: the seconds it took."""
        from websockets.sync.client import connect
        started = time.perf_counter()
        ticket = self.ticket(game)
        self.ws = connect(f'ws://127.0.0.1:{self.stack.games_port}/games/{game}/ws', open_timeout=10)
        self.ws.send(json.dumps({'t': 'hello', 'ticket': ticket}))
        deadline = time.perf_counter() + 10
        while time.perf_counter() < deadline:
            m = json.loads(self.ws.recv(timeout=max(deadline - time.perf_counter(), 0.01)))
            if m.get('type') == 'state':
                return time.perf_counter() - started
            if m.get('kind') == 'invalid':
                raise RuntimeError(f'{self.name}: the game refused the ticket')
        raise TimeoutError(f'{self.name}: no game state')

    def close_game(self):
        if self.ws is not None:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None


def join_all(stack, n):
    phones = [Phone(stack, NAMES[i]) for i in range(n)]
    for p in phones:
        status, _ = p.post('join', {'name': p.name})
        if status != 200:
            raise RuntimeError(f'{p.name} could not join ({status})')
        p.state()
    return phones


def traffic(phones):
    return sum(p.requests for p in phones), sum(p.bytes_in for p in phones), sum(p.bytes_out for p in phones)


# ---- scenarios ------------------------------------------------------------------------------------

def scenario_idle(cfg, games_root):
    """Party Core alone, no phones, then with members long-polling and nothing happening."""
    stack = Stack(None)
    try:
        time.sleep(cfg['settle'])
        empty = Sampler(stack.party.pid).start()
        time.sleep(cfg['window'])
        empty = empty.stop()
        phones = join_all(stack, 8)
        for p in phones:
            p.start_polling(cfg['wait'])
        time.sleep(cfg['settle'])
        before = traffic(phones)
        waiting = Sampler(stack.party.pid).start()
        window = cfg['idle_poll_window']             # long enough to see each poll renew at least once
        time.sleep(window)
        waiting = waiting.stop()
        after = traffic(phones)
        for p in phones:
            p.stop_polling()
        return {'no_members': empty, 'eight_waiting': waiting, 'idle_poll_window_s': window,
                'idle_requests_per_client_per_min': round((after[0] - before[0]) / 8 / window * 60, 2),
                'idle_bytes_per_client_per_min': round((after[1] + after[2] - before[1] - before[2]) / 8 / window * 60)}
    finally:
        stack.stop()


def timed_post(phone, path, body=None):
    """A versioned host action: read the view (untimed), then the POST alone, timed as the button
    press is. Returns (status, view, milliseconds, t0)."""
    phone.state()
    payload = {**(body or {}), 'if_version': phone.version}
    t0 = time.perf_counter()
    status, v = phone.post(path, payload)
    return status, v, (time.perf_counter() - t0) * 1000.0, t0


def propagation(phones, target, t0, timeout=5.0):
    """Milliseconds from t0 until each phone's long poll delivered `target`; None for a phone that
    did not within `timeout`."""
    try:
        wait_until(lambda: all(p.seen(target) for p in phones), timeout, f'version {target} everywhere')
    except TimeoutError:
        pass
    return [None if p.seen(target) is None else (p.seen(target) - t0) * 1000.0 for p in phones]


def scenario_longpoll(cfg, games_root, n):
    """n phones long-polling; the host repeatedly moves the party (launch -> setup, then lobby): the
    POST's own latency, and the delay until each phone's long poll delivers the new version."""
    stack = Stack(None)
    try:
        phones = join_all(stack, n)
        host = phones[0]
        for p in phones:
            p.start_polling(cfg['wait'])
        time.sleep(cfg['settle'])
        sampler = Sampler(stack.party.pid).start()
        harness = Sampler(os.getpid()).start()
        before = traffic(phones)
        action_ms, propagate_ms, missed = [], [], 0
        for i in range(cfg['actions']):
            path, body = ('session/launch', {'game': 'bluff'}) if i % 2 == 0 else ('lobby', {})
            status, v, ms, t0 = timed_post(host, path, body)
            if status != 200:
                raise RuntimeError(f'{path}: {status} {v}')
            action_ms.append(ms)
            lat = propagation(phones, v['version'], t0)
            missed += sum(1 for x in lat if x is None)
            propagate_ms.extend(x for x in lat if x is not None)
            time.sleep(cfg['gap'])
        after = traffic(phones)
        cpu = sampler.stop()
        generator = harness.stop()
        for p in phones:
            p.stop_polling()
        updates = cfg['actions'] * n
        return {'clients': n, 'actions': cfg['actions'], 'host_action_ms': perfstats.summary(action_ms),
                'propagation_ms': perfstats.summary(propagate_ms), 'missed_deliveries': missed,
                'party_core': cpu, 'load_generator': generator,
                # includes the host's own untimed state reads before each action
                'requests_per_client_update': round((after[0] - before[0]) / updates, 3),
                'bytes_in_per_client_update': round((after[1] - before[1]) / updates, 1),
                'bytes_out_per_client_update': round((after[2] - before[2]) / updates, 1)}
    finally:
        stack.stop()


def scenario_lifecycle(cfg, games_root):
    """Four phones play BLUFF's way in and out `cycles` times: pregame, Start (Party Core launches
    the real Games server), each phone's ticket + WebSocket hello, one phone's reconnect, End and
    everyone home. Party Core and Games server memory and threads after every cycle."""
    stack = Stack(games_root)
    try:
        phones = join_all(stack, 4)
        host = phones[0]
        for p in phones:
            p.start_polling(cfg['wait'])
        party, games = Sampler(stack.party.pid), Sampler(stack.games.pid)
        growth = {'party_rss_mb': [], 'party_threads': [], 'games_rss_mb': [], 'games_threads': []}

        def mark():
            # the quiet point between rounds: the fewest threads over half a second, so a request
            # thread that happens to be running is not counted as growth
            for name, s in (('party', party), ('games', games)):
                snaps = []
                for _ in range(5):
                    snaps.append(s.snapshot())
                    time.sleep(0.1)
                rss = snaps[-1][0]
                threads = min((t for _, t in snaps if t is not None), default=None)
                growth[f'{name}_rss_mb'].append(rss)
                growth[f'{name}_threads'].append(threads)

        mark()
        start_ms, join_ms, reconnect_ms, end_ms, home_ms = [], [], [], [], []
        connected = []
        for _ in range(cfg['cycles']):
            status, v, _, _ = timed_post(host, 'session/launch', {'game': 'bluff'})
            if status != 200 or v['state'] != 'setup':
                raise RuntimeError(f'launch: {status} {v and v.get("state")}')
            for p in phones:
                status, _ = p.post('session/choice', {'choice': 'player'})
                if status != 200:
                    raise RuntimeError(f'{p.name} choice: {status}')
            status, v, ms, _ = timed_post(host, 'session/start')
            if status != 200 or v['state'] != 'active':
                raise RuntimeError(f'start: {status} {v and v.get("state")} {v and v.get("session")}')
            start_ms.append(ms)
            join_ms.extend(p.open_game() * 1000.0 for p in phones)
            # the lightweight game at rest with four phones on it
            ps, gs = Sampler(stack.party.pid).start(), Sampler(stack.games.pid).start()
            time.sleep(cfg['window'])
            connected.append({'party_core': ps.stop(), 'games_server': gs.stop()})
            # a phone that dropped comes back: a fresh state read, a fresh ticket, a new hello
            phones[1].close_game()
            t0 = time.perf_counter()
            phones[1].state()
            phones[1].open_game()
            reconnect_ms.append((time.perf_counter() - t0) * 1000.0)
            status, v, ms, t0 = timed_post(host, 'session/end')
            if status != 200:
                raise RuntimeError(f'end: {status}')
            end_ms.append(ms)
            home_ms.extend(x for x in propagation(phones, v['version'], t0) if x is not None)
            for p in phones:
                p.close_game()
            time.sleep(0.3)
            mark()
        for p in phones:
            p.stop_polling()
        delta = {k: (round(vals[-1] - vals[0], 2) if None not in (vals[0], vals[-1]) else None)
                 for k, vals in growth.items()}
        # after the first round: warm-up (imports, caches) is not a leak; a steady climb would be
        after_first = {k: (round(vals[-1] - vals[1], 2) if len(vals) > 2 and None not in (vals[1], vals[-1]) else None)
                       for k, vals in growth.items()}
        return {'cycles': cfg['cycles'], 'start_ms': perfstats.summary(start_ms), 'join_ms': perfstats.summary(join_ms),
                'reconnect_ms': perfstats.summary(reconnect_ms), 'end_ms': perfstats.summary(end_ms),
                'home_propagation_ms': perfstats.summary(home_ms), 'growth_series': growth, 'growth': delta,
                'growth_after_first_cycle': after_first,
                'connected_rest': connected}
    finally:
        stack.stop()


class RealtimeClient:
    """A standalone dodgeball player over WebSocket: counts frames and bytes, sends 20 Hz moves and
    measures ping -> pong round trips through the game server's loop."""

    def __init__(self, port, name):
        from websockets.sync.client import connect
        self.ws = connect(f'ws://127.0.0.1:{port}/games/dodgeball/ws', open_timeout=10, max_size=None)
        self.ws.send(json.dumps({'t': 'hello', 'name': name, 'token': secrets.token_urlsafe(12)}))
        self.msgs = 0
        self.states = 0
        self.bytes = 0
        self.rtt_ms = []
        self.pings = []
        self.phase = None
        self.counting = False
        self.closed = False
        self._lock = threading.Lock()
        self._t = threading.Thread(target=self._recv, daemon=True)
        self._t.start()

    def _recv(self):
        try:
            while True:
                raw = self.ws.recv()
                now = time.perf_counter()
                if '"phase"' in raw:
                    m = re.search(r'"phase":\s*"(\w+)"', raw)
                    if m:
                        self.phase = m.group(1)
                if '"pong"' in raw:
                    with self._lock:
                        if self.pings:
                            sent = self.pings.pop(0)
                            if self.counting:
                                self.rtt_ms.append((now - sent) * 1000.0)
                if self.counting:
                    self.msgs += 1
                    self.bytes += len(raw)
                    if raw.startswith('{"type": "state"'):
                        self.states += 1
        except Exception:
            self.closed = True

    def send(self, **msg):
        self.ws.send(json.dumps(msg))

    def ping(self):
        with self._lock:
            self.pings.append(time.perf_counter())
        self.send(t='ping')

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def scenario_realtime(cfg, games_root, n):
    """n dodgeball players on the real Games server: ready, start, 3-2-1, then `window` seconds of
    joystick input at the rate dodgeball.js sends while moving (about 11 Hz) and 4 Hz pings, while the
    server runs its 30 Hz simulation."""
    stack = Stack(games_root)
    clients = []
    try:
        clients = [RealtimeClient(stack.games_port, NAMES[i]) for i in range(n)]
        time.sleep(0.5)
        for c in clients:
            c.send(t='ready', ready=True)
        time.sleep(0.2)
        clients[0].send(t='start')
        try:
            wait_until(lambda: all(c.phase == 'play' for c in clients), 10, 'the play phase')
        except TimeoutError:
            pass
        play_seen = all(c.phase == 'play' for c in clients)
        stop = threading.Event()

        def drive(c):
            rnd = random.Random(id(c))
            next_ping = 0.0
            while not stop.is_set():
                try:
                    c.send(t='move', x=round(rnd.uniform(-1, 1), 3), y=round(rnd.uniform(-1, 1), 3))
                    if time.perf_counter() >= next_ping:
                        c.ping()
                        next_ping = time.perf_counter() + 0.25
                except Exception:
                    return
                stop.wait(MOVE_EVERY)

        for c in clients:
            c.counting = True
        drivers = [threading.Thread(target=drive, args=(c,), daemon=True) for c in clients]
        sampler = Sampler(stack.games.pid).start()
        harness = Sampler(os.getpid()).start()
        t0 = time.perf_counter()
        for d in drivers:
            d.start()
        time.sleep(cfg['window'])
        stop.set()
        elapsed = time.perf_counter() - t0
        for c in clients:
            c.counting = False
        cpu = sampler.stop()
        generator = harness.stop()
        for d in drivers:
            d.join(timeout=2)
        rtt = [x for c in clients for x in c.rtt_ms]
        return {'clients': n, 'play_seen': play_seen, 'phase_at_end': [c.phase for c in clients],
                'window_s': round(elapsed, 2),
                'frames_per_s_per_client': perfstats.summary([c.msgs / elapsed for c in clients], 2),
                'state_frames_per_s_per_client': perfstats.summary([c.states / elapsed for c in clients], 2),
                'kbytes_per_s_per_client': perfstats.summary([c.bytes / elapsed / 1024 for c in clients], 2),
                'ping_rtt_ms': perfstats.summary(rtt), 'games_server': cpu, 'load_generator': generator}
    finally:
        for c in clients:
            c.close()
        stack.stop()


# ---- aggregation ----------------------------------------------------------------------------------

def aggregate(runs, metrics):
    """{label: across-repeats spread} for (label, unit, dotted path) metrics over successful runs."""
    ok = [r for r in runs if 'error' not in r]
    out = {}
    for label, unit, path in metrics:
        a = perfstats.across([{'p50': _get(r, path)} for r in ok])
        a['unit'] = unit
        out[label] = a
    return out


EVIDENCE = {
    'idle': 'real Party Core process; simulated phones (Python HTTP long polls)',
    'longpoll': 'real Party Core process; simulated phones (Python HTTP long polls)',
    'lifecycle': 'real Party Core + real Games server (BLUFF); Python WebSocket clients',
    'realtime': 'real Games server, real dodgeball 30 Hz simulation; standalone admission (not a Party session); '
                'Python WebSocket clients',
}

METRICS = {
    'idle': [('Party Core CPU, no members', '% of one core', 'no_members.cpu_pct_window'),
             ('Party Core RSS, no members', 'MB', 'no_members.rss_mb.p50'),
             ('Party Core threads, no members', 'count', 'no_members.threads.p50'),
             ('Party Core CPU, 8 members waiting', '% of one core', 'eight_waiting.cpu_pct_window'),
             ('Party Core RSS, 8 members waiting', 'MB', 'eight_waiting.rss_mb.p50'),
             ('Party Core threads, 8 members waiting', 'count', 'eight_waiting.threads.p50'),
             ('idle long-poll requests', 'per client per min', 'idle_requests_per_client_per_min'),
             ('idle long-poll traffic', 'B per client per min', 'idle_bytes_per_client_per_min')],
    'longpoll': [('host action POST p50', 'ms', 'host_action_ms.p50'),
                 ('host action POST p95', 'ms', 'host_action_ms.p95'),
                 ('state propagation p50', 'ms', 'propagation_ms.p50'),
                 ('state propagation p95', 'ms', 'propagation_ms.p95'),
                 ('missed deliveries (>5 s)', 'count', 'missed_deliveries'),
                 ('Party Core CPU during actions', '% of one core', 'party_core.cpu_pct_window'),
                 ('Party Core threads during actions', 'count', 'party_core.threads.max'),
                 ('load generator CPU (this harness)', '% of one core', 'load_generator.cpu_pct_window'),
                 ('bytes in per client per update', 'B', 'bytes_in_per_client_update'),
                 ('requests per client per update', 'count', 'requests_per_client_update')],
    'lifecycle': [('Start (launch the game) p50', 'ms', 'start_ms.p50'),
                  ('ticket + hello + first state p50', 'ms', 'join_ms.p50'),
                  ('reconnect p50', 'ms', 'reconnect_ms.p50'),
                  ('End p50', 'ms', 'end_ms.p50'),
                  ('everyone home after End p95', 'ms', 'home_propagation_ms.p95'),
                  ('Games server CPU, 4 phones at rest', '% of one core', 'connected_rest.0.games_server.cpu_pct_window'),
                  ('Games server RSS', 'MB', 'growth_series.games_rss_mb.0'),
                  ('Party Core RSS growth over the cycles', 'MB', 'growth.party_rss_mb'),
                  ('Party Core thread growth', 'count', 'growth.party_threads'),
                  ('Games server RSS growth over the cycles', 'MB', 'growth.games_rss_mb'),
                  ('Games server thread growth', 'count', 'growth.games_threads'),
                  ('Party Core RSS growth after cycle 1', 'MB', 'growth_after_first_cycle.party_rss_mb'),
                  ('Games server RSS growth after cycle 1', 'MB', 'growth_after_first_cycle.games_rss_mb')],
    'realtime': [('messages received per client', 'per s', 'frames_per_s_per_client.p50'),
                 ('full state frames per client', 'per s', 'state_frames_per_s_per_client.p50'),
                 ('bytes received per client', 'KB/s', 'kbytes_per_s_per_client.p50'),
                 ('ping round trip p50', 'ms', 'ping_rtt_ms.p50'),
                 ('ping round trip p95', 'ms', 'ping_rtt_ms.p95'),
                 ('Games server CPU', '% of one core', 'games_server.cpu_pct_window'),
                 ('Games server RSS', 'MB', 'games_server.rss_mb.p50'),
                 ('load generator CPU (this harness)', '% of one core', 'load_generator.cpu_pct_window')],
}


def _get(d, path):
    """A dotted path into nested dicts and lists ('connected_rest.0.x'); None if absent."""
    for k in path.split('.'):
        if isinstance(d, list):
            try:
                d = d[int(k)]
            except (ValueError, IndexError):
                return None
        elif isinstance(d, dict) and k in d:
            d = d[k]
        else:
            return None
    return d



def run(cfg, games_root, only):
    plan = [('idle', lambda: scenario_idle(cfg, games_root), 'idle')]
    plan += [(f'longpoll_{n}_clients', (lambda n=n: scenario_longpoll(cfg, games_root, n)), 'longpoll')
             for n in cfg['clients']]
    plan.append(('lifecycle_bluff_4_phones', lambda: scenario_lifecycle(cfg, games_root), 'lifecycle'))
    plan += [(f'realtime_dodgeball_{n}_players', (lambda n=n: scenario_realtime(cfg, games_root, n)), 'realtime')
             for n in cfg['rt_clients']]
    scenarios = {}
    for name, fn, kind in plan:
        if only and kind not in only:
            continue
        if kind in ('lifecycle', 'realtime') and games_root is None:
            scenarios[name] = {'skipped': 'needs --games PATH (a Games checkout and its requirements)'}
            continue
        runs = []
        for i in range(cfg['repeats']):
            print(f'  {name} repeat {i + 1}/{cfg["repeats"]}', flush=True)
            started = time.perf_counter()
            try:
                r = fn()
            except Exception as e:                  # recorded, never silently dropped
                r = {'error': f'{type(e).__name__}: {e}'}
            r['duration_s'] = round(time.perf_counter() - started, 2)
            runs.append(r)
        scenarios[name] = {'evidence': EVIDENCE[kind], 'what': (globals()[f'scenario_{kind}'].__doc__ or '').strip(),
                           'runs': runs, 'errors': sum(1 for r in runs if 'error' in r),
                           'aggregate': aggregate(runs, METRICS[kind])}
    return scenarios


def config(args):
    quick = args.quick
    cfg = {'repeats': perfstats.bounded(args.repeats if args.repeats else (1 if quick else 3), 1, 10, 'repeats'),
           'settle': 0.5 if quick else 1.0,
           'window': perfstats.bounded(args.window or (1.0 if quick else 5.0), 0.5, 60, 'window'),
           'actions': perfstats.bounded(args.actions or (6 if quick else 30), 2, 200, 'actions'),
           'gap': 0.05,
           'idle_poll_window': 2.0 if quick else float(client_wait() + 2),
           'cycles': perfstats.bounded(args.cycles or (2 if quick else 5), 1, 20, 'cycles'),
           'wait': client_wait(),
           'clients': [perfstats.bounded(int(x), 1, MAX_CLIENTS, 'clients') for x in args.clients.split(',')],
           'rt_clients': [perfstats.bounded(int(x), 1, MAX_CLIENTS, 'rt-clients') for x in args.rt_clients.split(',')],
           'quick': quick}
    return cfg


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--games', type=Path, help='a Games checkout (enables lifecycle and realtime)')
    ap.add_argument('--repeats', type=int, help='fresh-process repeats per scenario (1-10; default 3, quick 1)')
    ap.add_argument('--window', type=float, help='seconds per sampling window (default 5, quick 1)')
    ap.add_argument('--actions', type=int, help='host actions per long-poll run (default 30, quick 6)')
    ap.add_argument('--cycles', type=int, help='launch/end cycles per lifecycle run (default 5, quick 2)')
    ap.add_argument('--clients', default='1,4,8', help='long-poll client counts (default 1,4,8)')
    ap.add_argument('--rt-clients', default='2,4,6', help='realtime player counts (default 2,4,6)')
    ap.add_argument('--only', help='comma-separated: idle,longpoll,lifecycle,realtime')
    ap.add_argument('--quick', action='store_true', help='a short smoke run (not a measurement)')
    ap.add_argument('--out', type=Path, default=Path('perf-results'), help='directory for the JSON and Markdown')
    args = ap.parse_args(argv)
    cfg = config(args)
    games_root = args.games.resolve() if args.games else None
    only = set(args.only.split(',')) if args.only else None
    print(f'AVR-138 local performance run: repeats={cfg["repeats"]} games={games_root or "not used"}', flush=True)
    result = {'schema': perfstats.SCHEMA,
              'evidence': 'local loopback simulation on one machine' + (' (quick smoke run)' if cfg['quick'] else ''),
              'environment': perfstats.environment(PARTY_ROOT, games_root), 'config': cfg,
              'scenarios': run(cfg, games_root, only)}
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime('%Y%m%dT%H%M%S')
    (args.out / f'perf-{stamp}.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    (args.out / f'perf-{stamp}.md').write_text(perfstats.markdown(result), encoding='utf-8')
    print(f'wrote {args.out / f"perf-{stamp}.json"} and .md', flush=True)
    errors = sum(s.get('errors', 0) for s in result['scenarios'].values())
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
