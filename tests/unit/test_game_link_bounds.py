"""What Party Core accepts back from a game server (AVR-336 follow-up, Tier 1: loopback sockets).

A native game from a package is third-party code at the community tier. Party Core asks it to
launch and to end over HTTP (TCP or a Unix socket) and must stay up whatever it answers: a reply
is bounded in size and in time, however the game sends it.

    python -m unittest discover -s tests/unit -p test_game_link_bounds.py
"""
import http.server
import json
import os
import socket
import tempfile
import threading
import time
import unittest

from avrana.party import sessions

KEY = b'k' * 32


class Session:
    id = 'sess-1'
    game_id = 'drip'


def serve(handler_cls):
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler_cls)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class Huge(http.server.BaseHTTPRequestHandler):
    """A well-formed, valid JSON reply that is far larger than any launch answer."""
    protocol_version = 'HTTP/1.0'

    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length') or 0))
        body = json.dumps({'ok': True, 'message': 'x' * (6 * 1024 * 1024)}).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass

    def log_message(self, *a):
        pass


class Drip(http.server.BaseHTTPRequestHandler):
    """Sends spaces slowly (each arrives well inside the per-read timeout), then a valid ok reply."""
    protocol_version = 'HTTP/1.0'
    seconds = 4.0

    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length') or 0))
        self.send_response(200)
        self.end_headers()
        end = time.monotonic() + self.seconds
        try:
            while time.monotonic() < end:
                self.wfile.write(b' ')
                self.wfile.flush()
                time.sleep(0.1)
            self.wfile.write(b'{"ok": true}')
        except OSError:
            pass

    def log_message(self, *a):
        pass


class GameLinkBounds(unittest.TestCase):
    def link(self, server, timeout=1.0):
        url = f'http://127.0.0.1:{server.server_address[1]}/games/drip'
        link = sessions.HttpGameLink({'drip': sessions.GameEndpoint('drip', url, KEY)}, timeout=timeout)
        self.addCleanup(server.shutdown)
        return link

    def test_a_reply_larger_than_the_limit_is_a_failed_launch_not_buffered(self):
        ok, detail = self.link(serve(Huge)).launch(Session, [])
        self.assertFalse(ok)
        self.assertTrue(detail)

    def test_a_reply_that_trickles_past_the_deadline_is_a_failed_launch(self):
        started = time.monotonic()
        ok, detail = self.link(serve(Drip), timeout=1.0).launch(Session, [])
        self.assertFalse(ok, 'a game that drips its answer must not hold Party Core past the link timeout')
        self.assertLess(time.monotonic() - started, 3.0)

    @unittest.skipUnless(hasattr(socket, 'AF_UNIX'), 'Unix sockets only (the Linux runner)')
    def test_the_unix_link_is_bounded_the_same_way(self):
        path = os.path.join(tempfile.mkdtemp(), 'g.sock')
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(path)
        listener.listen(4)
        self.addCleanup(listener.close)

        def answer():
            while True:
                try:
                    conn, _ = listener.accept()
                except OSError:
                    return
                with conn:
                    conn.recv(65536)
                    body = json.dumps({'ok': True, 'message': 'x' * (6 * 1024 * 1024)}).encode()
                    try:
                        conn.sendall(b'HTTP/1.0 200 OK\r\nContent-Length: %d\r\n\r\n' % len(body) + body)
                    except OSError:
                        pass
        threading.Thread(target=answer, daemon=True).start()
        link = sessions.HttpGameLink({'drip': sessions.GameEndpoint(
            'drip', 'http://localhost/games/drip', KEY, socket_path=path)}, timeout=1.0)
        ok, _ = link.launch(Session, [])
        self.assertFalse(ok)

    def test_a_normal_reply_still_works(self):
        class Fine(Huge):
            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length') or 0))
                body = b'{"ok": true}'
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        self.assertEqual(self.link(serve(Fine)).launch(Session, []), (True, None))


if __name__ == '__main__':
    unittest.main()
