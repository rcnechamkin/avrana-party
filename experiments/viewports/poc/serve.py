#!/usr/bin/env python3
"""Personal Viewports proof of concept — a tiny standard-library server (NOT production).

Serves one page that shows a shared four-quadrant source and crops it to the viewer's seat.
Geometry comes from ../viewport_geometry.py (the tested test vectors), so the browser only
applies numbers the Python tests already pin down.

    python serve.py [--port 8765] [--host 0.0.0.0]

Endpoints (all JSON unless noted):
  GET  /                      the page (index.html)
  GET  /time                  {"ms": server epoch ms}  — clock sync, so phones draw the same frame
  GET  /layouts               {"keys": [...], "default": "4"}
  GET  /layout?key=4&seat=2   crop for that seat: rect, aspect, css, orientation
  POST /claim   {"client": "<random id>", "layout": "4"}   -> {"seat": n, "layout": ...}
  POST /release {"client": "<random id>"}                  -> {"released": [seats freed]}
  GET  /state                 who holds which seat (ids truncated)
  WebRTC signalling for the shared source (?role=source page → every ?source=rtc viewer):
  POST /rtc/offer  {"client", "sdp"}   a viewer's offer (non-trickle: ICE already gathered)
  GET  /rtc/offers?since=N             the source page polls for offers newer than N
  POST /rtc/answer {"client", "sdp"}   the source's answer
  GET  /rtc/answer?client=ID           the viewer polls for its answer ({"sdp": null} until ready)

Seat assignment mirrors the party-model rules at toy scale: a client id (random, kept in the
browser's localStorage) always gets its own seat back; a new id gets the lowest free seat;
when all seats of the layout are taken the viewer watches the full frame (spectator).
"""
import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import viewport_geometry as vg  # noqa: E402

# The synthetic source is a 640x480 square-pixel 4:3 frame, like today's PS1/arcade capture.
PROFILE = {
    'v': 0, 'grid': [640, 480], 'content': [0, 0, 640, 480], 'aspect': '4:3', 'inset': 2,
    'layouts': {
        '2h': {'seats': {'1': [0, 0, 640, 240], '2': [0, 240, 640, 240]}},
        '2v': {'seats': {'1': [0, 0, 320, 480], '2': [320, 0, 320, 480]}},
        '3': {'seats': {'1': [0, 0, 640, 240], '2': [0, 240, 320, 240], '3': [320, 240, 320, 240]}},
        '4': {'seats': {'1': [0, 0, 320, 240], '2': [320, 0, 320, 240],
                        '3': [0, 240, 320, 240], '4': [320, 240, 320, 240]}},
    },
}
DEFAULT_LAYOUT = '4'
CLIENT_ID_MAX = 64
SDP_MAX = 64 * 1024          # a LAN-only SDP with host candidates is a few KB
RTC_MAX = 32                 # offers/answers kept (oldest dropped): a demo, not a service


def layout_for(key, seat):
    rects = vg.seat_rects(PROFILE, key)
    if seat not in rects:
        raise KeyError(seat)
    rect = rects[seat]
    aspect = vg.crop_aspect(rect, PROFILE)
    css = vg.css_crop(rect)
    return {'key': key, 'seat': seat, 'seats': len(rects),
            'rect': [float(v) for v in rect], 'aspect': float(aspect),
            'aspect_text': f'{aspect.numerator}:{aspect.denominator}',
            'orientation': vg.orientation(aspect),
            'css': {k: float(v) for k, v in css.items()}}


class Seats:
    """client id -> seat, per layout key. Thread-safe; in memory only."""

    def __init__(self):
        self.lock = threading.Lock()
        self.by_layout = {}          # key -> {client: seat}

    def claim(self, client, key):
        n = len(PROFILE['layouts'][key]['seats'])
        with self.lock:
            held = self.by_layout.setdefault(key, {})
            if client in held:
                return held[client]
            free = sorted(set(range(1, n + 1)) - set(held.values()))
            if not free:
                return None              # all seats taken: watch the full frame
            held[client] = free[0]
            return free[0]

    def release(self, client):
        """Leave: give up this client's seat in EVERY layout. Returns the seats freed."""
        with self.lock:
            return [held.pop(client) for held in self.by_layout.values() if client in held]

    def snapshot(self):
        with self.lock:
            return {k: {c[:6] + '…': s for c, s in v.items()} for k, v in self.by_layout.items()}


SEATS = Seats()


class Signals:
    """In-memory offer/answer exchange between viewers and the one source page."""

    def __init__(self):
        self.lock = threading.Lock()
        self.seq = 0
        self.offers = {}             # client -> (seq, sdp)
        self.answers = {}            # client -> sdp

    def offer(self, client, sdp):
        with self.lock:
            self.seq += 1
            self.offers[client] = (self.seq, sdp)
            self.answers.pop(client, None)              # a new offer invalidates the old answer
            while len(self.offers) > RTC_MAX:
                self.offers.pop(min(self.offers, key=lambda c: self.offers[c][0]))

    def offers_since(self, n):
        with self.lock:
            return [{'client': c, 'n': q, 'sdp': sdp}
                    for c, (q, sdp) in sorted(self.offers.items(), key=lambda kv: kv[1][0]) if q > n]

    def answer(self, client, sdp):
        with self.lock:
            if client not in self.offers:
                return False
            self.answers[client] = sdp
            while len(self.answers) > RTC_MAX:
                self.answers.pop(next(iter(self.answers)))
            return True

    def answer_for(self, client):
        with self.lock:
            return self.answers.get(client)


SIGNALS = Signals()


class Handler(BaseHTTPRequestHandler):
    server_version = 'viewport-poc'
    timeout = 10                          # a slow/idle connection can't hold a thread forever

    def log_message(self, fmt, *args):      # quiet; the page shows what matters
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self, limit=4096):
        n = int(self.headers.get('Content-Length') or 0)
        if not 0 <= n <= limit:           # a negative length would make read() unbounded
            raise ValueError('bad body length')
        data = json.loads(self.rfile.read(n) or b'{}')
        return data if isinstance(data, dict) else {}

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if url.path in ('/', '/index.html'):
            with open(os.path.join(HERE, 'index.html'), 'rb') as f:
                body = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif url.path == '/time':
            self._json({'ms': time.time() * 1000})
        elif url.path == '/layouts':
            self._json({'keys': sorted(PROFILE['layouts']), 'default': DEFAULT_LAYOUT})
        elif url.path == '/layout':
            try:
                key = q.get('key', [DEFAULT_LAYOUT])[0]
                self._json(layout_for(key, int(q.get('seat', ['0'])[0])))
            except (KeyError, ValueError, vg.LayoutError):
                self._json({'error': 'no such layout/seat'}, 404)
        elif url.path == '/state':
            self._json(SEATS.snapshot())
        elif url.path == '/rtc/offers':
            try:
                since = int(q.get('since', ['0'])[0])
            except ValueError:
                return self._json({'error': 'bad since'}, 400)
            self._json({'offers': SIGNALS.offers_since(since)})
        elif url.path == '/rtc/answer':
            self._json({'sdp': SIGNALS.answer_for(q.get('client', [''])[0])})
        else:
            self._json({'error': 'not found'}, 404)

    def do_POST(self):
        url = urlparse(self.path)
        try:
            data = self._body(SDP_MAX + 1024 if url.path.startswith('/rtc/') else 4096)
        except (ValueError, RecursionError):  # JSONDecodeError is a ValueError
            return self._json({'error': 'bad request'}, 400)
        client = str(data.get('client', ''))[:CLIENT_ID_MAX]
        if len(client) < 8:
            return self._json({'error': 'client id required'}, 400)
        if url.path == '/claim':
            key = str(data.get('layout', DEFAULT_LAYOUT))
            if key not in PROFILE['layouts']:
                return self._json({'error': 'no such layout'}, 404)
            self._json({'seat': SEATS.claim(client, key), 'layout': key})
        elif url.path == '/release':
            self._json({'released': SEATS.release(client)})
        elif url.path in ('/rtc/offer', '/rtc/answer'):
            sdp = data.get('sdp')
            if not isinstance(sdp, str) or not sdp.startswith('v=0') or len(sdp) > SDP_MAX:
                return self._json({'error': 'bad sdp'}, 400)
            if url.path == '/rtc/offer':
                SIGNALS.offer(client, sdp)
                self._json({'ok': True})
            elif SIGNALS.answer(client, sdp):
                self._json({'ok': True})
            else:
                self._json({'error': 'no such offer'}, 404)
        else:
            self._json({'error': 'not found'}, 404)


def make_server(host='127.0.0.1', port=0):
    return ThreadingHTTPServer((host, port), Handler)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--host', default='0.0.0.0', help='0.0.0.0 so phones on the same Wi-Fi can open it')
    ap.add_argument('--port', type=int, default=8765)
    args = ap.parse_args()
    srv = make_server(args.host, args.port)
    print(f'Personal Viewports PoC on http://{args.host}:{args.port}/  (Ctrl-C to stop)')
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
