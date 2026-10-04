"""The nginx site: static rules (Tier 1) and a real nginx run with stand-in upstreams (Tier 2).

The Tier 2 half starts nginx with the committed site on high ports, a throwaway self-signed
certificate, the built web shell, two fake upstreams and the real party service (AVR-51), then
checks what phones would get on HTTP (captive probe, hub, arcade: unchanged) and HTTPS (/party/
shell, headers, origin JSON, the party API through /party/api/). It
is skipped when nginx is not installed unless AVRANA_REQUIRE_NGINX=1 (CI sets it). It proves the
config and its semantics, not the Pi: live DNS, the real certificate and phones stay Tier 3.
"""
import http.client
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from avrana import REPO_ROOT
from avrana.party import identity, service
from avrana.web import build
from avrana.web.devserver import SHELL_HEADERS

SITE = (REPO_ROOT / 'avrana-party.nginx').read_text(encoding='utf-8')
APPLE_SUCCESS = '<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>\n'


def server_blocks(text):
    """Top-level server { ... } blocks, by brace matching."""
    blocks, depth, start = [], 0, None
    for match in re.finditer(r'server\s*\{|\{|\}', text):
        token = match.group(0)
        if token.startswith('server') and depth == 0:
            start, depth = match.start(), 1
        elif token == '{' and start is not None:
            depth += 1
        elif token == '}' and start is not None:
            depth -= 1
            if depth == 0:
                blocks.append(text[start:match.end()])
                start = None
    return blocks


def locations(block):
    # a quoted regular expression may hold braces of its own
    return re.findall(r'^\s*location\s+((?:"[^"]*"|[^{"])+?)\s*\{', block, re.M)


def location_body(block, name):
    start = re.search(r'^\s*location\s+' + re.escape(name) + r'\s*\{', block, re.M)
    depth, i = 1, start.end()
    while depth:
        depth += {'{': 1, '}': -1}.get(block[i], 0)
        i += 1
    return block[start.end():i - 1]


class StaticRules(unittest.TestCase):
    def setUp(self):
        self.http, self.https = server_blocks(SITE)

    def test_repository_copies_are_identical(self):
        self.assertEqual(SITE, (REPO_ROOT / 'arcade' / 'nginx-site').read_text(encoding='utf-8'))

    def test_native_games_block_is_the_source_copy_on_https_only(self):
        block = (REPO_ROOT / 'deploy/games/nginx-native-games.location').read_text(encoding='utf-8')
        self.assertEqual(SITE.count(block), 1)
        http_block, https = server_blocks(SITE)
        self.assertIn(block, https)
        self.assertNotIn('avrana-games', http_block)
        # one rule for every native title: the only location that names a game is the retiring
        # runtime's own two Party games
        self.assertEqual(SITE.count('location ~ ^/games/(bluff|expo)(/|$) {'), 1)
        self.assertNotRegex(SITE, r'location\s+[^{(]*/games/[a-z]')
        self.assertEqual(SITE.count('/run/avrana-games/'), 2)                    # the comment and the rule
        # nginx reads no game registry (its location is AVR-236's to decide) and tests no file
        self.assertNotIn('games.d', SITE)
        rule = location_body(https, '~ "^/games/(?<native_game>[a-z][a-z0-9_-]{0,39})/"')
        self.assertNotIn('if (', rule)
        self.assertNotIn('8096', rule)
        # nothing hands a request over to another server: no named location, no error_page
        self.assertNotIn('location @', SITE)
        self.assertNotIn('error_page', SITE)
        self.assertEqual(location_body(https, '/games/').split(), ['return', '404;'])
        self.assertNotIn('proxy_intercept_errors', SITE)
        self.assertNotIn('proxy_next_upstream', SITE)
        # the control-path refusal comes before the rule that proxies
        self.assertLess(https.index('/avrana/ {'), https.index('proxy_pass http://unix:/run/avrana-games/'))

    def test_port_80_is_unchanged(self):
        self.assertIn('listen 80 default_server;', self.http)
        self.assertEqual(locations(self.http), ['= /hotspot-detect.html', '/arcade/', '/'])
        probe = location_body(self.http, '= /hotspot-detect.html')
        self.assertIn('return 200 "' + APPLE_SUCCESS.replace('\n', '\\n') + '";', probe)
        self.assertIn('add_header Cache-Control "no-store" always;', probe)
        self.assertNotIn('return 30', self.http.replace('return 200', ''))  # no redirects on HTTP

    def test_party_is_https_only(self):
        self.assertEqual(locations(self.https), ['= /party', '= /party/api/origin.json', '/party/api/',
                                                 '/party/', '/arcade/', '~ ^/games/[^/]+/avrana/',
                                                 '~ ^/games/(bluff|expo)(/|$)',
                                                 '~ "^/games/(?<native_game>[a-z][a-z0-9_-]{0,39})/"',
                                                 '/games/', '/'])
        from avrana.contracts import game             # the slug nginx accepts is a Game Contract id
        self.assertIn(game.ID.pattern.strip('^$'), locations(self.https)[7])
        self.assertFalse(any('/party' in loc for loc in locations(self.http)))

    def test_shell_headers_match_the_dev_server(self):
        body = location_body(self.https, '/party/')
        headers = dict(re.findall(r'add_header\s+(\S+)\s+"([^"]*)"\s+always;', body))
        self.assertEqual(headers, SHELL_HEADERS)
        self.assertNotRegex(SITE, r'add_header\s+Service-Worker-Allowed')
        self.assertNotRegex(SITE, r'add_header\s+Strict-Transport-Security')  # expiry must stay escapable


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def upstream(label):
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.path)
            if self.headers.get('Content-Length'):
                self.rfile.read(int(self.headers['Content-Length']))
            body = json.dumps({'upstream': label, 'path': self.path,
                               'proto': self.headers.get('X-Forwarded-Proto'),
                               'upgrade': self.headers.get('Upgrade')}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_POST = do_GET

        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.seen = seen
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def native_game(path):
    """A stand-in native game listening on a Unix socket, as systemd would hand it one. It records
    every request it sees, so a test can prove that a request never reached it."""
    import socketserver
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.path)
            body = json.dumps({'upstream': 'native', 'path': self.path, 'host': self.headers.get('Host'),
                               'proto': self.headers.get('X-Forwarded-Proto'),
                               'forwarded_for': self.headers.get('X-Forwarded-For'),
                               'upgrade': self.headers.get('Upgrade')}).encode()
            if self.headers.get('Content-Length'):
                self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(502 if 'own502' in self.path else 418 if 'own418' in self.path else 200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        do_POST = do_GET

        def address_string(self):
            return 'unix'

        def log_message(self, *args):
            pass

    class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True
    server = Server(str(path), Handler)
    server.seen = seen
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def silent_game(path):
    """A stand-in native game that accepts a connection, reads the request and closes without
    answering: a game that crashes mid-request."""
    import socketserver
    seen = []

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.settimeout(2)
            try:
                seen.append(self.request.recv(65536))
            except OSError:
                pass

    class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True
    server = Server(str(path), Handler)
    server.seen = seen
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def websocket_game(path):
    """A stand-in native game that completes a WebSocket handshake (101) and echoes every byte
    back, so a test can prove frames travel both ways through the rule."""
    import base64
    import hashlib
    import socketserver

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.settimeout(5)
            head = b''
            while b'\r\n\r\n' not in head:
                chunk = self.request.recv(4096)
                if not chunk:
                    return
                head += chunk
            headers = {k.strip().lower(): v.strip() for k, v in
                       (line.split(':', 1) for line in head.decode('latin-1').split('\r\n')[1:] if ':' in line)}
            if headers.get('upgrade', '').lower() != 'websocket' or 'sec-websocket-key' not in headers:
                self.request.sendall(b'HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n')
                return
            accept = base64.b64encode(hashlib.sha1(
                (headers['sec-websocket-key'] + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
            self.request.sendall(('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                                  f'Sec-WebSocket-Accept: {accept}\r\n\r\n').encode())
            try:
                while True:
                    data = self.request.recv(4096)
                    if not data:
                        return
                    self.request.sendall(data)
            except OSError:
                return

    class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True
    server = Server(str(path), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


NGINX = shutil.which('nginx') or ('/usr/sbin/nginx' if os.path.exists('/usr/sbin/nginx') else None)


@unittest.skipUnless(NGINX or os.environ.get('AVRANA_REQUIRE_NGINX') == '1', 'nginx is not installed')
class RealNginx(unittest.TestCase):
    site = SITE                          # a subclass may test a proposed change to the site

    @classmethod
    def setUpClass(cls):
        # The real party service behind /party/api/, configured as on the appliance
        # (deploy/party-core/party-core.example.json), with no game servers attached.
        svc = service.PartyService(identity.DeviceStore(None), service.load_games({'bluff': {'max_players': 6}}))
        cfg = service.Config(['party.avrana.net'], ['https://party.avrana.net'], secure_cookie=True)
        cls.party = service.make_server(svc, cfg, port=free_port())
        threading.Thread(target=cls.party.serve_forever, daemon=True).start()
        cls.tmp = Path(tempfile.mkdtemp())
        tmp = cls.tmp
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:prime256v1',
                        '-nodes', '-days', '1', '-subj', '/CN=party.avrana.net',
                        '-addext', 'subjectAltName=DNS:party.avrana.net',
                        '-keyout', str(tmp / 'key.pem'), '-out', str(tmp / 'cert.pem')],
                       check=True, capture_output=True)
        build.build(tmp / 'web' / 'current', 'nginxtest')
        cls.lan, cls.arcade = upstream('lan'), upstream('arcade')
        (tmp / 'games').mkdir()                      # stands in for /run/avrana-games
        cls.native = native_game(tmp / 'games' / 'demo.sock')
        cls.silent = silent_game(tmp / 'games' / 'silent.sock')
        cls.echo = websocket_game(tmp / 'games' / 'echo.sock')
        # demo, silent and echo listen; dead is a socket nobody listens on; no other slug has one.
        cls.dead = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        cls.dead.bind(str(tmp / 'games' / 'dead.sock'))          # bound, never listening
        cls.p80, cls.p443 = free_port(), free_port()
        site = (cls.site
                .replace('listen 80 default_server;', f'listen 127.0.0.1:{cls.p80} default_server;')
                .replace('listen [::]:80 default_server;', '')
                .replace('listen 443 ssl;', f'listen 127.0.0.1:{cls.p443} ssl;')
                .replace('listen [::]:443 ssl;', '')
                .replace('/etc/avrana-party/tls/current/fullchain.pem', str(tmp / 'cert.pem'))
                .replace('/etc/avrana-party/tls/current/privkey.pem', str(tmp / 'key.pem'))
                .replace('http://127.0.0.1:8096', f'http://127.0.0.1:{cls.lan.server_port}')
                .replace('/run/avrana-games/', f'{tmp}/games/')
                .replace('http://127.0.0.1:8097/', f'http://127.0.0.1:{cls.arcade.server_port}/')
                .replace('http://127.0.0.1:8191', f'http://127.0.0.1:{cls.party.server_port}')
                .replace('/var/www/avrana-party/web/current/', f'{tmp}/web/current/'))
        (tmp / 'site.conf').write_text(site)
        mime = '/etc/nginx/mime.types'
        types = f'include {mime};' if os.path.exists(mime) else (
            'types { text/html html; text/css css; application/javascript js; application/json json; '
            'image/svg+xml svg; }')
        for d in ('body', 'proxy', 'fastcgi', 'uwsgi', 'scgi'):
            (tmp / d).mkdir()
        (tmp / 'nginx.conf').write_text(f"""
pid {tmp}/nginx.pid;
error_log {tmp}/error.log;
events {{}}
http {{
  {types}
  default_type application/octet-stream;
  access_log off;
  client_body_temp_path {tmp}/body; proxy_temp_path {tmp}/proxy; fastcgi_temp_path {tmp}/fastcgi;
  uwsgi_temp_path {tmp}/uwsgi; scgi_temp_path {tmp}/scgi;
  include {tmp}/site.conf;
}}
""")
        check = subprocess.run([NGINX, '-t', '-p', str(tmp), '-e', str(tmp / 'error.log'), '-c', str(tmp / 'nginx.conf')],
                               capture_output=True, text=True)
        if check.returncode != 0:
            raise AssertionError(check.stderr)
        cls.proc = subprocess.Popen([NGINX, '-p', str(tmp), '-e', str(tmp / 'error.log'), '-c', str(tmp / 'nginx.conf'),
                                     '-g', 'daemon off; master_process off;'],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                socket.create_connection(('127.0.0.1', cls.p443), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.05)
        cls.tls = ssl.create_default_context(cafile=str(tmp / 'cert.pem'))

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)
        cls.proc.stderr.close()
        cls.lan.shutdown()
        cls.native.shutdown()
        cls.silent.shutdown()
        cls.echo.shutdown()
        cls.dead.close()
        cls.arcade.shutdown()
        cls.party.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def get(self, path, *, https=False, host='party.avrana.net'):
        if https:
            conn = http.client.HTTPSConnection('127.0.0.1', self.p443, context=self.tls, timeout=5)
            conn.sock = self.tls.wrap_socket(socket.create_connection(('127.0.0.1', self.p443), timeout=5),
                                             server_hostname='party.avrana.net')
        else:
            conn = http.client.HTTPConnection('127.0.0.1', self.p80, timeout=5)
        conn.request('GET', path, headers={'Host': host})
        res = conn.getresponse()
        body = res.read()
        conn.close()
        return res, body

    def test_http_captive_probe_and_apps_unchanged(self):
        res, body = self.get('/hotspot-detect.html', host='captive.apple.com')
        self.assertEqual((res.status, body.decode()), (200, APPLE_SUCCESS))
        self.assertEqual(res.getheader('Cache-Control'), 'no-store')
        for path, label in (('/', 'lan'), ('/generate_204', 'lan'), ('/party/', 'lan'), ('/arcade/stats', 'arcade')):
            res, body = self.get(path, host='party.local')
            self.assertEqual(json.loads(body)['upstream'], label, path)
        self.assertEqual(json.loads(self.get('/arcade/stats', host='party.local')[1])['path'], '/stats')

    def test_https_shell(self):
        res, body = self.get('/party/', https=True)
        self.assertEqual(res.status, 200)
        self.assertIn(b'<title>Avrana Party</title>', body)
        for key, value in SHELL_HEADERS.items():
            self.assertEqual(res.getheader(key), value, key)
        res, body = self.get('/party/sw.js', https=True)
        self.assertEqual(res.status, 200)
        self.assertRegex(res.getheader('Content-Type'), r'(application|text)/javascript')
        self.assertEqual(res.getheader('Cache-Control'), 'no-cache')
        self.assertIsNone(res.getheader('Service-Worker-Allowed'))
        self.assertIn(b"const BUILD = 'nginxtest';", body)
        res, _ = self.get('/party/catalog.json', https=True)
        self.assertEqual(res.getheader('Content-Type'), 'application/json')
        res, body = self.get('/party/diag/', https=True)
        self.assertEqual(res.status, 200)
        self.assertIn(b'Diagnostics', body)
        res, _ = self.get('/party/lib/keep-awake.js', https=True)  # imported by the arcade page
        self.assertEqual(res.status, 200)
        self.assertRegex(res.getheader('Content-Type'), r'(application|text)/javascript')
        res, _ = self.get('/party', https=True)
        self.assertEqual(res.status, 301)
        self.assertTrue(res.getheader('Location').endswith('/party/'))
        self.assertEqual(self.get('/party/api/nothing', https=True)[0].status, 404)
        self.assertEqual(self.get('/party/missing.js', https=True)[0].status, 404)

    def test_origin_endpoint(self):
        res, body = self.get('/party/api/origin.json', https=True)
        self.assertEqual(res.getheader('Cache-Control'), 'no-store')
        origin = json.loads(body)
        self.assertEqual(origin['schema'], 'avrana.origin/v0')
        self.assertEqual(origin['scheme'], 'https')
        self.assertEqual(origin['serverAddr'], '127.0.0.1')
        self.assertRegex(origin['tls'], r'^TLSv1\.[23]$')

    def request(self, method, path, body=None, origin='https://party.avrana.net', extra=None):
        conn = http.client.HTTPSConnection('127.0.0.1', self.p443, context=self.tls, timeout=10)
        conn.sock = self.tls.wrap_socket(socket.create_connection(('127.0.0.1', self.p443), timeout=10),
                                         server_hostname='party.avrana.net')
        headers = dict({'Host': 'party.avrana.net'}, **(extra or {}))
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers.update({'Origin': origin, 'Content-Type': 'application/json'})
        conn.request(method, path, body=data, headers=headers)
        res = conn.getresponse()
        payload = res.read()
        conn.close()
        return res, payload

    def test_party_state_and_join_through_nginx(self):
        res, body = self.request('GET', '/party/api/state')
        self.assertEqual(res.status, 200)
        self.assertEqual(res.getheader('Cache-Control'), 'no-store')
        self.assertIsNone(json.loads(body)['me'])
        res, body = self.request('POST', '/party/api/join', {'name': 'Robin'})
        self.assertEqual(res.status, 200, body)
        cookie = res.getheader('Set-Cookie')
        self.assertTrue(cookie.startswith('__Host-avrana_device='), cookie)   # ADR 0013 D3
        for part in ('HttpOnly', 'Secure', 'Path=/;', 'SameSite=Lax'):
            self.assertIn(part, cookie)
        self.assertNotIn('Domain', cookie)
        self.assertEqual(json.loads(body)['me']['name'], 'Robin')
        res, _ = self.request('POST', '/party/api/join', {'name': 'Mallory'}, origin='https://evil.test')
        self.assertEqual(res.status, 403)

    def test_party_long_poll_outlives_a_short_wait(self):
        version = json.loads(self.request('GET', '/party/api/state')[1])['version']
        started = time.monotonic()
        res, body = self.request('GET', f'/party/api/state?since={version}&wait=2')
        self.assertEqual(res.status, 200)
        self.assertGreaterEqual(time.monotonic() - started, 1.5)
        self.assertEqual(json.loads(body)['version'], version)

    def test_internal_routes_never_reach_the_party(self):
        lan = json.loads(self.request('GET', '/internal/party-session/v0/ended')[1])
        self.assertEqual(lan['upstream'], 'lan')                      # the games hub, not the party
        res, body = self.request('GET', '/party/api/internal/party-session/v0/ended')
        self.assertEqual((res.status, json.loads(body)['error']), (404, 'not_found'))

    def test_a_native_game_is_reached_on_its_own_socket_by_slug(self):
        """AVR-259 / ADR 0016 section 4: /games/<slug>/ goes to /run/avrana-games/<slug>.sock."""
        res, body = self.get('/games/demo/play?seat=2', https=True)
        got = json.loads(body)
        self.assertEqual((res.status, got['upstream'], got['path']), (200, 'native', '/games/demo/play?seat=2'))
        self.assertEqual((got['host'], got['proto']), ('party.avrana.net', 'https'))
        self.assertTrue(got['forwarded_for'])              # the game can tell a proxied request
        res, body = self.request('GET', '/games/demo/ws', extra={'Upgrade': 'websocket', 'Connection': 'Upgrade'})
        self.assertEqual(json.loads(body)['upgrade'], 'websocket')

    def test_control_paths_are_refused_before_any_game(self):
        before_native, before_lan = len(self.native.seen), None
        for path in ('/games/demo/avrana/session/v0/launch', '/games/demo/avrana/', '/games/bluff/avrana/session/v0/end',
                     '/games/Demo/avrana/x'):
            res, _ = self.get(path, https=True)
            self.assertEqual(res.status, 404, path)
            res, body = self.request('POST', path, body={})
            self.assertEqual(res.status, 404, path)
            self.assertNotIn(b'upstream', body, path)         # nginx answered, no process did
        self.assertEqual(len(self.native.seen), before_native)

    def test_the_two_party_games_of_the_retiring_runtime_answer_as_before(self):
        """BLUFF and EXPO are routed to the LAN Games runtime by name (ADR 0016 section 7)."""
        before = len(self.native.seen)
        for path in ('/games/bluff/?avrana=1', '/games/expo/ws', '/games/bluff/shared.js', '/games/bluff', '/games/expo'):
            got = json.loads(self.get(path, https=True)[1])
            self.assertEqual((got['upstream'], got['path'], got['proto']), ('lan', path, 'https'), path)
            res, body = self.request('POST', path, body={'x': 1})
            self.assertEqual(json.loads(body)['upstream'], 'lan', path)       # the method and body go with it
        self.assertEqual(len(self.native.seen), before)

    def test_a_slug_that_is_not_provisioned_is_refused_and_never_reaches_lan_games(self):
        """No fallback: a slug with no socket is not a game. The LAN Games runtime has titles of
        its own at these very names (checkers, spades); a request for one is not sent to it."""
        before = self.lan_paths()
        for path in ('/games/checkers/', '/games/spades/play?avrana=1', '/games/nosuchgame/', '/games/bluffer/',
                     '/games/expo2/ws'):
            res, body = self.get(path, https=True)
            self.assertEqual(res.status, 502, path)
            self.assertNotIn(b'upstream', body, path)             # nginx's own page, no process's
            res, body = self.request('POST', path, body={'ticket': 'aps0.secret.sig'})
            self.assertEqual(res.status, 502, path)
        self.assertEqual(self.lan_paths(), before)

    def test_port_80_has_no_native_route_and_still_sends_every_game_path_to_lan_games(self):
        """Pinned on purpose: the plain-HTTP block is unchanged by AVR-259. What it should do once
        LAN Games retires is AVR-228's and the owner's to decide."""
        before = len(self.native.seen)
        for path in ('/games/checkers/', '/games/demo/play', '/games/bluff/'):
            got = json.loads(self.get(path)[1])
            self.assertEqual((got['upstream'], got['path']), ('lan', path), path)
        self.assertEqual(len(self.native.seen), before)

    def test_a_path_under_games_that_names_no_slug_is_a_404_from_nginx(self):
        before, seen = self.lan_paths(), len(self.native.seen)
        for path in ('/games/', '/games/Demo/', '/games/1demo/', '/games/demo.sock/', '/games/' + 'a' * 41 + '/',
                     '/games/demo', '/games/BLUFF/'):
            res, body = self.get(path, https=True)
            self.assertEqual(res.status, 404, path)
            self.assertNotIn(b'upstream', body, path)
        self.assertEqual((self.lan_paths(), len(self.native.seen)), (before, seen))

    def test_no_request_names_a_socket_outside_the_games_directory(self):
        (self.tmp / 'outside.sock').touch()
        before = len(self.native.seen)
        for path in ('/games/../outside/', '/games/..%2Foutside/', '/games/demo%2F..%2F..%2Foutside/', '/games/Demo/',
                     '/games/demo.sock/', '/games/' + 'a' * 41 + '/', '/games/1demo/', '/games/demo/../../outside/',
                     '/games/demo%2e%2e/', '/games/%2e%2e/outside/'):
            res, body = self.get(path, https=True)
            self.assertNotIn(b'"native"', body, path)
        self.assertEqual(len(self.native.seen), before)
        log = (self.tmp / 'error.log').read_text()
        self.assertNotIn('outside.sock', log)
        # nginx never built a socket path from anything but a slug: every path it tried to connect
        # to is directly inside the games directory
        for tried in re.findall(r'unix:(\S+?\.sock)', log):
            self.assertRegex(tried, re.escape(str(self.tmp / 'games')) + r'/[a-z][a-z0-9_-]{0,39}\.sock$', tried)

    def test_a_path_that_normalises_to_a_slug_reaches_that_game_and_only_that_game(self):
        """nginx matches the normalised path, so these name `demo` and nothing else. That is the
        game's own socket inside the directory: not a traversal."""
        for path in ('/games//demo/', '/games/./demo/', '/games/x/../demo/', '/games/%64emo/'):
            res, body = self.get(path, https=True)
            got = json.loads(body)
            self.assertEqual((got['upstream'], got['path']), ('native', path), path)
        # and a control path spelled any of those ways is still refused by nginx itself
        before = len(self.native.seen)
        for path in ('/games//demo/avrana/session/v0/launch', '/games/demo//avrana/session/v0/launch',
                     '/games/demo/%61vrana/session/v0/end', '/games/demo/x/../avrana/session/v0/launch',
                     '/games/demo/./avrana/'):
            res, body = self.request('POST', path, body={})
            self.assertEqual(res.status, 404, path)
            self.assertNotIn(b'upstream', body, path)
        self.assertEqual(len(self.native.seen), before)

    def test_a_502_from_the_game_itself_is_the_games_answer(self):
        res, body = self.get('/games/demo/own502', https=True)
        self.assertEqual((res.status, json.loads(body)['upstream']), (502, 'native'))

    def lan_paths(self):
        return list(self.lan.seen)

    def test_a_game_that_is_down_is_a_502_and_is_never_answered_by_lan_games(self):
        """A native slug is never handed to the LAN Games runtime: not when its socket refuses
        the connection, and not when it has no socket at all."""
        before = self.lan_paths()
        for path in ('/games/dead/play', '/games/gone/play'):
            res, body = self.get(path, https=True)
            self.assertEqual(res.status, 502, path)
            self.assertNotIn(b'upstream', body, path)             # nginx's own page, no process's
            res, body = self.request('POST', path, body={'ticket': 'aps0.secret.sig'})
            self.assertEqual(res.status, 502, path)
        self.assertEqual(self.lan_paths(), before)                # nothing was replayed anywhere

    def test_a_game_that_takes_a_request_and_dies_is_a_502_and_the_request_goes_nowhere_else(self):
        """The body of a request a native game accepted (it may carry a Party ticket) is never
        sent to another server."""
        before, seen = self.lan_paths(), len(self.silent.seen)
        res, body = self.request('POST', '/games/silent/join', body={'ticket': 'aps0.secret.sig'},
                                 extra={'Cookie': '__Host-avrana_device=device-secret'})
        self.assertEqual(res.status, 502)
        self.assertNotIn(b'upstream', body)
        self.assertGreater(len(self.silent.seen), seen)           # the game did receive it
        self.assertIn(b'aps0.secret.sig', b''.join(self.silent.seen[seen:]))
        self.assertEqual(self.lan_paths(), before)
        self.assertFalse([p for p in self.native.seen if 'silent' in p])

    def test_lan_games_traffic_never_tries_a_socket_and_logs_no_error(self):
        """Requests for the retiring runtime's two Party games go straight there: nginx attempts
        no socket and writes nothing to its error log."""
        log = self.tmp / 'error.log'
        size = log.stat().st_size
        for path in ('/games/bluff/?avrana=1', '/games/expo/ws', '/games/bluff/shared.js', '/'):
            self.assertEqual(json.loads(self.get(path, https=True)[1])['upstream'], 'lan', path)
        self.assertEqual(log.read_text()[size:], '')

    def test_a_418_from_a_game_is_the_games_answer(self):
        before = self.lan_paths()
        res, body = self.get('/games/demo/own418', https=True)
        self.assertEqual((res.status, json.loads(body)['upstream']), (418, 'native'))
        self.assertEqual(self.lan_paths(), before)

    def test_spellings_the_refusal_does_not_match_reach_the_game_as_ordinary_proxied_requests(self):
        """Documented pass-throughs. The refusal matches the normalised path, case-sensitively;
        the game is sent the request line as written. Neither spelling below is a control path
        to a game (a game routes the exact path /games/<slug>/avrana/...), and both arrive with
        the proxy headers, which a game's control routes refuse (tests/unit/test_party_managed.py
        test_only_local_unproxied_json_reaches_the_runtime; Games tests/test_party_session.py
        test_launch_route_refuses_anything_not_local_and_unproxied)."""
        for path in ('/games/demo/AVRANA/session/v0/launch', '/games/demo/Avrana/session/v0/end'):
            res, body = self.request('POST', path, body={})
            got = json.loads(body)
            self.assertEqual((res.status, got['upstream'], got['path']), (200, 'native', path), path)
            self.assertTrue(got['forwarded_for'], path)
        # A fragment mark in the request line: whatever nginx makes of it, the exact control path
        # never reaches the game.
        before = len(self.native.seen)
        self.request('POST', '/games/demo/x#/../avrana/session/v0/launch', body={})
        for path in self.native.seen[before:]:
            self.assertFalse(path.startswith('/games/demo/avrana/'), path)

    def test_a_websocket_through_the_rule_carries_frames_both_ways(self):
        """A real upgrade: the game answers 101 and bytes sent after it come back."""
        import base64
        raw = self.tls.wrap_socket(socket.create_connection(('127.0.0.1', self.p443), timeout=10),
                                   server_hostname='party.avrana.net')
        try:
            key = base64.b64encode(os.urandom(16)).decode()
            raw.sendall(('GET /games/echo/ws HTTP/1.1\r\nHost: party.avrana.net\r\nUpgrade: websocket\r\n'
                         f'Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
            head = b''
            while b'\r\n\r\n' not in head:
                chunk = raw.recv(4096)
                self.assertTrue(chunk, head)
                head += chunk
            self.assertTrue(head.startswith(b'HTTP/1.1 101'), head)
            self.assertIn(b'sec-websocket-accept', head.lower())
            rest = head.split(b'\r\n\r\n', 1)[1]
            for frame in (b'\x81\x85\x00\x00\x00\x00hello', b'\x82\x83\x00\x00\x00\x00\x01\x02\x03'):
                raw.sendall(frame)
                while len(rest) < len(frame):
                    chunk = raw.recv(4096)
                    self.assertTrue(chunk)
                    rest += chunk
                self.assertEqual(rest[:len(frame)], frame)
                rest = rest[len(frame):]
        finally:
            raw.close()

    def test_https_apps_still_proxied(self):
        lan = json.loads(self.get('/', https=True)[1])
        self.assertEqual((lan['upstream'], lan['proto']), ('lan', 'https'))
        self.assertEqual(json.loads(self.get('/arcade/', https=True)[1])['upstream'], 'arcade')


if __name__ == '__main__':
    unittest.main()
