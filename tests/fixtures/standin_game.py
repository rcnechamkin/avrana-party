"""A stand-in native game for tests (AVR-258). Not a product game and not an SDK.

It is the smallest process that behaves as ADR 0016 says a native game does: it serves the
listening Unix socket it INHERITS (sd_listen_fds: LISTEN_PID, LISTEN_FDS, file descriptor 3), it
holds only its own key (a directory of `<id>.key` named by AVRANA_PARTY_KEYS, as a unit's
credentials directory would be), and it reports to the party's internal Unix socket. The session
logic is the reference `protocol.GameSide`.

    POST /games/<id>/avrana/session/v0/launch   {"message": …}   party -> game
    POST /games/<id>/avrana/session/v0/end      {"message": …}   party -> game
    POST /games/<id>/hello                      {"ticket": …}    stands for the WebSocket hello
    POST /games/<id>/test/finish                {"outcome", "winner"}   test control: report `ended`

The two control routes refuse a request that carries a proxy header: nginx and the party share
this socket, and only the party sends none.

    python standin_game.py --activate FD     # tests: become a socket-activated service on FD
"""
import http.server
import json
import os
from pathlib import Path
import socket
import socketserver
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from avrana.party import protocol, result, service, sessions  # noqa: E402

GAME = os.environ.get('STANDIN_GAME', 'standin')
PROXY_HEADERS = ('X-Forwarded-For', 'X-Real-IP', 'Forwarded')


def report(party_socket, message):
    conn = sessions.UnixHTTPConnection(party_socket, 5)
    try:
        conn.request('POST', sessions.ENDED_ROUTE, body=json.dumps({'message': message}).encode(),
                     headers={'Content-Type': 'application/json', 'Host': 'localhost'})
        r = conn.getresponse()
        return r.status, json.loads(r.read() or b'{}')
    finally:
        conn.close()


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--activate':
        # What systemd does for a socket-activated unit: the socket is fd 3 and the two
        # variables name this very process. Then become the service.
        os.dup2(int(sys.argv[2]), 3)
        os.set_inheritable(3, True)
        os.environ.update(LISTEN_PID=str(os.getpid()), LISTEN_FDS='1')
        os.execv(sys.executable, [sys.executable, __file__])
    fds = service.listen_fds()
    if fds != [3]:
        raise SystemExit('standin game: expected one inherited socket (LISTEN_FDS=1)')
    key = protocol.read_key(os.path.join(os.environ['AVRANA_PARTY_KEYS'], f'{GAME}.key'))
    side = protocol.GameSide(key, GAME)
    party_socket = os.environ['STANDIN_PARTY_SOCKET']
    base = f'/games/{GAME}'

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def address_string(self):
            return 'unix'

        def _reply(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
            proxied = any(self.headers.get(h) for h in PROXY_HEADERS)
            try:
                if self.path in (base + sessions.LAUNCH_PATH, base + sessions.END_PATH):
                    if proxied:
                        return self._reply(404, {'ok': False})
                    if self.path.endswith('/launch'):
                        side.on_launch(body['message'])
                    else:
                        side.on_end(body['message'])
                    return self._reply(200, {'ok': True})
                if self.path == base + '/hello':
                    token, role = side.admit(body['ticket'])
                    return self._reply(200, {'ok': True, 'role': role, 'token': token})
                if self.path == base + '/test/finish':
                    players = [r['participant'] for r in side.roster if r['role'] == 'player']
                    outcome, made = body.get('outcome', 'completed'), None
                    if outcome == 'completed':
                        made = result.build(GAME, 'standin-1', 'competitive',
                                            [{'participant': p, 'standing': 'won' if p == body.get('winner') else 'lost'}
                                             for p in players], players,
                                            data_schema='standin.result/v1', data={'rounds': 1})
                    status, answer = report(party_socket, side.ended(outcome, result=made))
                    return self._reply(200, {'ok': status == 200, 'party_status': status, 'party': answer})
            except protocol.Invalid as e:
                return self._reply(403, {'ok': False, 'message': str(e)})
            return self._reply(404, {'ok': False})

    server_cls = type('StandinServer', (socketserver.ThreadingMixIn, socketserver.UnixStreamServer),
                      {'daemon_threads': True})
    server = server_cls(None, H, bind_and_activate=False)
    server.socket.close()
    server.socket = socket.socket(fileno=3)
    server.serve_forever()


if __name__ == '__main__':
    main()
