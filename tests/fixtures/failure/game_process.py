"""A stand-in game server as its own OS process, for failure injection (AVR-33).

SYNTHETIC: it is not BLUFF, the Games server or the arcade. It speaks the real session protocol
(ADR 0006) through the reference GameSide, on its own loopback port, so a test can kill it
(SIGKILL), freeze it (SIGSTOP) or make it hang, and Party Core meets a real dead or silent process,
not a stopped thread. A new process holds no session, as a restarted game does.

    python game_process.py --port N --key-file K --game G [--hang-file F]

Routes: the protocol's launch and end (one at a time, in arrival order); test-only
POST /__test__/hello {ticket} (a phone arriving with a Party ticket) and GET /__test__/held (the
session it holds). While --hang-file exists, every
request is accepted and never answered (a wedged runtime that still listens).
"""
import argparse
import http.server
import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from avrana.party import protocol, sessions                    # noqa: E402
from avrana.party.protocol import Invalid                       # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, required=True)
    ap.add_argument('--key-file', required=True)
    ap.add_argument('--game', required=True)
    ap.add_argument('--hang-file')
    args = ap.parse_args()
    side = protocol.GameSide(protocol.read_key(args.key_file), args.game)
    # Launch and end are handled one at a time, in arrival order, as every shipped runtime does
    # (avrana.party.managed holds a lock; the Games server and the gamekit run one event loop).
    # Party Core's rollback of a failed Start relies on it: its `end` lands after the late launch.
    protocol_lock = threading.Lock()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def hang(self):
            while args.hang_file and os.path.exists(args.hang_file):
                time.sleep(0.05)

        def reply(self, status, out):
            data = json.dumps(out).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self.hang()
            if self.path == '/__test__/held':
                return self.reply(200, {'sid': side.sid})
            self.reply(404, {})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
            if self.path in (sessions.LAUNCH_PATH, sessions.END_PATH):
                with protocol_lock:
                    self.hang()
                    return self.handle_post(body)
            self.hang()
            self.handle_post(body)

        def handle_post(self, body):
            try:
                if self.path == sessions.LAUNCH_PATH:
                    side.on_launch(body['message'])
                elif self.path == sessions.END_PATH:
                    side.on_end(body['message'])
                elif self.path == '/__test__/hello':
                    side.admit(body['ticket'])
                else:
                    raise Invalid('route')
                self.reply(200, {'ok': True})
            except Invalid as e:
                self.reply(403, {'ok': False, 'message': 'Refused.', 'reason': str(e)})

    server = http.server.ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.daemon_threads = True
    print('ready', flush=True)
    server.serve_forever(poll_interval=0.05)


if __name__ == '__main__':
    main()
