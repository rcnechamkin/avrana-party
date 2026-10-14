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

from test_party_service import ServiceCase

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


def raw_server(script):
    """A TCP listener whose every connection is handled by script(conn) in its own thread: the
    game's side of the wire, byte by byte, with none of http.server's politeness."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(('127.0.0.1', 0))
    listener.listen(8)

    def accept():
        while True:
            try:
                conn, _ = listener.accept()
            except OSError:
                return

            def one(c=conn):
                try:
                    with c:
                        c.settimeout(15)
                        script(c)
                except OSError:
                    pass
            threading.Thread(target=one, daemon=True).start()
    threading.Thread(target=accept, daemon=True).start()
    return listener


def head(c):
    """Read the whole request, body included (a server that closes with a request unread resets
    the connection, and the client then never sees its answer)."""
    data = b''
    while b'\r\n\r\n' not in data:
        more = c.recv(4096)
        if not more:
            return
        data += more
    header, _, body = data.partition(b'\r\n\r\n')
    want = 0
    for line in header.split(b'\r\n'):
        if line.lower().startswith(b'content-length:'):
            want = int(line.split(b':')[1])
    while len(body) < want:
        more = c.recv(4096)
        if not more:
            return
        body += more


def drip_headers(interval, count=40):
    def script(c):
        head(c)
        c.sendall(b'HTTP/1.0 200 OK\r\n')
        for _ in range(count):
            c.sendall(b'X-Slow: yes\r\n')
            time.sleep(interval)
        c.sendall(b'Content-Length: 12\r\n\r\n{"ok": true}')
    return script


def drip_body(interval, count=40):
    def script(c):
        head(c)
        c.sendall(b'HTTP/1.0 200 OK\r\n\r\n')
        for _ in range(count):
            c.sendall(b' ')
            time.sleep(interval)
        c.sendall(b'{"ok": true}')
    return script


def stall_after_headers(c):
    head(c)
    c.sendall(b'HTTP/1.0 200 OK\r\nContent-Length: 12\r\n\r\n')
    time.sleep(12)


def stall_before_headers(c):
    head(c)
    time.sleep(12)


def redirect(c):
    head(c)
    c.sendall(b'HTTP/1.0 302 Found\r\nLocation: http://127.0.0.1:1/elsewhere\r\nContent-Length: 0\r\n\r\n')


class OverallDeadline(unittest.TestCase):
    """AVR-33/AVR-336: one deadline for the whole call, measured on the monotonic clock from before
    the request is sent. Every wait on the socket counts against it: a game that drips its headers,
    drips its body or stalls after its headers cannot hold a Party Core request thread for more
    than the link timeout (plus scheduling), whatever interval it sends at."""
    TIMEOUT = 0.5
    SLACK = 0.6

    def link(self, script, timeout=None):
        server = raw_server(script)
        self.addCleanup(server.close)
        url = f'http://127.0.0.1:{server.getsockname()[1]}/games/drip'
        return sessions.HttpGameLink({'drip': sessions.GameEndpoint('drip', url, KEY)},
                                     timeout=timeout or self.TIMEOUT)

    def bounded(self, script):
        link = self.link(script)
        started = time.monotonic()
        out = link.launch(Session, [])
        took = time.monotonic() - started
        self.assertLess(took, self.TIMEOUT + self.SLACK, f'launch held its caller for {took:.2f}s')
        return out

    def test_headers_dripped_faster_than_the_socket_timeout_are_still_cut_off(self):
        ok, detail = self.bounded(drip_headers(0.15))
        self.assertFalse(ok)
        self.assertTrue(detail)

    def test_headers_dripped_just_inside_the_socket_timeout_are_still_cut_off(self):
        self.assertFalse(self.bounded(drip_headers(0.4))[0])

    def test_a_body_dripped_just_inside_the_socket_timeout_is_cut_off(self):
        self.assertFalse(self.bounded(drip_body(0.4))[0])

    def test_a_stall_after_the_headers_is_cut_off(self):
        self.assertFalse(self.bounded(stall_after_headers)[0])

    def test_a_stall_before_any_header_is_cut_off(self):
        self.assertFalse(self.bounded(stall_before_headers)[0])

    def test_end_is_bounded_the_same_way(self):
        from unittest import mock
        with mock.patch.object(sessions, 'END_LINK_TIMEOUT', self.TIMEOUT):
            link = self.link(drip_headers(0.4), timeout=60.0)
            started = time.monotonic()
            self.assertFalse(link.end(Session))
            self.assertLess(time.monotonic() - started, self.TIMEOUT + self.SLACK)

    def test_a_redirect_is_not_followed(self):
        ok, _ = self.link(redirect).launch(Session, [])
        self.assertFalse(ok)

    @unittest.skipUnless(hasattr(socket, 'AF_UNIX'), 'Unix sockets only (the Linux runner)')
    def test_the_unix_link_has_the_same_overall_deadline(self):
        for script in (drip_headers(0.4), drip_body(0.4), stall_after_headers):
            with self.subTest(script=getattr(script, '__name__', 'drip')):
                path = os.path.join(tempfile.mkdtemp(), 'g.sock')
                listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                listener.bind(path)
                listener.listen(4)
                self.addCleanup(listener.close)

                def serve_one(l=listener, s=script):
                    while True:
                        try:
                            conn, _ = l.accept()
                        except OSError:
                            return
                        threading.Thread(target=serve_conn, args=(s, conn), daemon=True).start()
                threading.Thread(target=serve_one, daemon=True).start()
                link = sessions.HttpGameLink({'drip': sessions.GameEndpoint(
                    'drip', 'http://localhost/games/drip', KEY, socket_path=path)}, timeout=self.TIMEOUT)
                started = time.monotonic()
                self.assertFalse(link.launch(Session, [])[0])
                self.assertLess(time.monotonic() - started, self.TIMEOUT + self.SLACK)


def serve_conn(script, conn):
    """Run a game-side script on one accepted connection; the client cutting it off is expected."""
    try:
        script(conn)
    except OSError:
        pass
    finally:
        conn.close()


def says(status, body):
    def script(c):
        head(c)
        data = json.dumps(body).encode()
        c.sendall(b'HTTP/1.0 %d X\r\nContent-Length: %d\r\n\r\n' % (status, len(data)) + data)
    return script


def chunked(pieces, gap=0.0):
    def script(c):
        head(c)
        c.sendall(b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n')
        for piece in pieces:
            c.sendall(b'%x\r\n' % len(piece) + piece + b'\r\n')
            time.sleep(gap)
        c.sendall(b'0\r\n\r\n')
    return script


def close_delimited(body):
    def script(c):
        head(c)
        c.sendall(b'HTTP/1.0 200 OK\r\n\r\n' + body)       # no Content-Length: the close ends it
    return script


class WhatAGamesAnswerMeans(unittest.TestCase):
    """An answer that is not what the link expects is a failure, never an exception; and the two
    ways a body can be framed without a Content-Length are read correctly and stay bounded."""

    def link(self, script, timeout=2.0):
        server = raw_server(script)
        self.addCleanup(server.close)
        url = f'http://127.0.0.1:{server.getsockname()[1]}/games/drip'
        return sessions.HttpGameLink({'drip': sessions.GameEndpoint('drip', url, KEY)}, timeout=timeout)

    def test_an_answer_that_is_not_a_json_object_is_a_failed_launch(self):
        for body in ([], 'ok', 7, None):
            with self.subTest(body=body):
                self.assertFalse(self.link(says(200, body)).launch(Session, [])[0])

    def test_a_chunked_reply_is_read_whole_and_a_chunked_drip_is_cut_off(self):
        self.assertEqual(self.link(chunked([b'{"ok"', b': tr', b'ue}'])).launch(Session, []), (True, None))
        link = self.link(chunked([b' '] * 40, gap=0.2), timeout=0.5)
        started = time.monotonic()
        self.assertFalse(link.launch(Session, [])[0])
        self.assertLess(time.monotonic() - started, 1.1)

    def test_a_close_delimited_reply_is_read_whole_and_an_endless_one_is_refused(self):
        self.assertEqual(self.link(close_delimited(b'{"ok": true}')).launch(Session, []), (True, None))
        started = time.monotonic()
        ok, _ = self.link(close_delimited(b' ' * (sessions.MAX_REPLY_BYTES + 10) + b'{"ok": true}')).launch(Session, [])
        self.assertFalse(ok)
        self.assertLess(time.monotonic() - started, 1.5)


class Reachable(unittest.TestCase):
    """The connection check behind session_recovery.close_lost_game (AVR-33): a connection only."""

    def test_a_port_nobody_listens_on_is_not_reachable(self):
        with socket.socket() as probe:                # a port that was free a moment ago, no listener
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        link = sessions.HttpGameLink({'drip': sessions.GameEndpoint('drip', f'http://127.0.0.1:{port}', KEY)},
                                     timeout=1.0)
        self.assertFalse(link.reachable(Session))

    def test_a_listening_game_is_reachable(self):
        listener = raw_server(lambda c: None)
        self.addCleanup(listener.close)
        link = sessions.HttpGameLink({'drip': sessions.GameEndpoint(
            'drip', f'http://127.0.0.1:{listener.getsockname()[1]}', KEY)}, timeout=1.0)
        self.assertTrue(link.reachable(Session))

    def test_a_game_with_no_endpoint_is_not_reachable(self):
        self.assertFalse(sessions.HttpGameLink({}).reachable(Session))


class Stalling(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'
    seconds = 3.0

    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length') or 0))
        time.sleep(self.seconds)
        try:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok": true}')
        except OSError:
            pass

    def log_message(self, *a):
        pass


class AStuckGameDoesNotFreezeTheParty(ServiceCase):
    """A launch is stuck at its game. Other phones still get the party's state at once, and the
    service lock is free: the link call is made outside it (service.PartyService docstring)."""

    def make_link(self):
        self.game_server = serve(Stalling)
        self.addCleanup(self.game_server.shutdown)
        url = f'http://127.0.0.1:{self.game_server.server_address[1]}'
        return sessions.HttpGameLink({'bluff': sessions.GameEndpoint('bluff', url, KEY)}, timeout=5.0)

    def test_state_polls_from_other_phones_stay_fast_while_a_launch_is_stuck(self):
        ana, ben, cat = self.phone(), self.phone(), self.phone()
        for p, name in ((ana, 'Ana'), (ben, 'Ben'), (cat, 'Cat')):
            p.post('join', {'name': name})
        _, v, _ = ana.state()
        launching = threading.Thread(
            target=lambda: ana.post('session/launch', {'game': 'bluff', 'if_version': v['version']}))
        launching.start()
        try:
            deadline = time.monotonic() + 1.5
            while self.svc.core.party.session is None and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertEqual(self.svc.core.party.session.state, 'launching')
            for phone in (ben, cat, ben, cat, ana):
                started = time.monotonic()
                status, view, _ = phone.state()
                self.assertEqual((status, view['state']), (200, 'launching'))
                self.assertLess(time.monotonic() - started, 0.5, 'a stuck game froze /party/api/state')
            self.assertTrue(self.svc.lock.acquire(timeout=0.5), 'the service lock is held across a game call')
            self.svc.lock.release()
        finally:
            launching.join(timeout=10)


if __name__ == '__main__':
    unittest.main()
