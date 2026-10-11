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
        self.http, self.https = server_blocks(SITE)[:2]      # the third is the game origin (AVR-319)

    def test_repository_copies_are_identical(self):
        self.assertEqual(SITE, (REPO_ROOT / 'arcade' / 'nginx-site').read_text(encoding='utf-8'))

    def test_game_rules_are_the_source_copies_and_native_games_are_https_only(self):
        native = (REPO_ROOT / 'deploy/games/nginx-native-games.location').read_text(encoding='utf-8')
        legacy = (REPO_ROOT / 'deploy/games/nginx-legacy-lan-games.location').read_text(encoding='utf-8')
        plain = (REPO_ROOT / 'deploy/games/nginx-games-plain-http.location').read_text(encoding='utf-8')
        for block in server_blocks(SITE)[:2]:
            self.assertEqual(block.count(legacy), 1)
        self.assertEqual((self.https.count(native), self.https.count(plain)), (1, 0))
        self.assertEqual((self.http.count(native), self.http.count(plain)), (0, 1))
        # the control-path refusal comes before the rule that proxies to a socket
        self.assertLess(self.https.index('/avrana/ {'), self.https.index('proxy_pass http://unix:/run/avrana-games/'))
        # plain HTTP has no rule that reaches a native game: no socket, no slug capture
        http_rules = '\n'.join(line for line in self.http.splitlines() if not line.lstrip().startswith('#'))
        self.assertNotRegex(http_rules, r'avrana-games|native_game|unix:')
        self.assertNotIn('proxy_pass', plain)
        # the shared rules name no title and no other upstream; the legacy exception is a file of its own
        self.assertNotRegex(native, r'bluff|expo|8096|127\.0\.0\.1')
        self.assertNotIn('avrana-games', legacy)
        self.assertNotRegex(SITE.replace(legacy, ''), r'location\s+[^{]*/games/[^{]*(bluff|expo)')
        self.assertNotRegex(SITE, r'location\s+[^{(]*/games/[a-z]')
        # nginx reads no game registry (its location is AVR-236's to decide) and tests no file:
        # the only filesystem path in the game rules is the socket directory, and only in proxy_pass
        rules = '\n'.join(line for line in (native + legacy).splitlines() if not line.lstrip().startswith('#'))
        self.assertEqual(re.findall(r'/(?:etc|run|var|srv|home|usr|opt|tmp)/[^\s;:]*', rules),
                         ['/run/avrana-games/$native_game.sock'])
        self.assertNotIn('if (', native + legacy)
        self.assertNotIn('try_files', native + legacy)
        # nothing hands a request over to another server: no named location, no error_page
        self.assertNotIn('location @', SITE)
        self.assertNotIn('error_page', SITE)
        self.assertNotIn('proxy_intercept_errors', SITE)
        self.assertNotIn('proxy_next_upstream', SITE)
        for block in server_blocks(SITE):
            self.assertEqual(location_body(block, '/games/').split(), ['return', '404;'])

    GAMES = ['~ "^/games/(bluff|expo)(/(?!avrana/)|$)"', '~ ^/games/[^/]+/avrana/',
             '~ "^/games/(?<native_game>[a-z][a-z0-9_-]{0,39})/"', '/games/', '= /games']

    HUB = ['= /', '^~ /shared/hub.html']

    def test_port_80_keeps_the_captive_probe_and_serves_no_native_game(self):
        self.assertIn('listen 80 default_server;', self.http)
        self.assertEqual(locations(self.http), ['= /hotspot-detect.html', '/arcade/', self.GAMES[0], '/games/', '= /games',
                                                *self.HUB, '/'])
        probe = location_body(self.http, '= /hotspot-detect.html')
        self.assertIn('return 200 "' + APPLE_SUCCESS.replace('\n', '\\n') + '";', probe)
        self.assertIn('add_header Cache-Control "no-store" always;', probe)
        self.assertNotIn('return 30', self.http.replace('return 200', ''))  # no redirects on HTTP
        # the root of each origin is nginx's own answer, not the hub: a link on HTTP, Party Home on HTTPS
        root = location_body(self.http, '= /')
        self.assertIn('default_type text/html;', root)
        self.assertRegex(root, r"return 200 '[^']*<a href=\"https://party\.avrana\.net/party/\">[^']*';")
        self.assertEqual(location_body(self.https, '= /').split(), ['return', '302', '/party/;'])
        for block in server_blocks(SITE)[:2]:
            self.assertEqual(location_body(block, '^~ /shared/hub.html').split(), ['return', '404;'])
            self.assertNotIn('proxy_pass', location_body(block, '= /'))

    def test_party_is_https_only(self):
        self.assertEqual(locations(self.https), ['= /party', '= /party/api/origin.json', '/party/api/',
                                                 '= /party/bridge.html', '= /party/catalog.json', '/party/', '/arcade/', *self.GAMES, *self.HUB, '/'])
        from avrana.contracts import game             # the slug nginx accepts is a Game Contract id
        self.assertIn(game.ID.pattern.strip('^$'), self.GAMES[2])
        self.assertFalse(any('/party' in loc for loc in locations(self.http)))

    def test_the_catalog_is_an_appliance_local_file_before_the_release_file_and_nothing_else(self):
        """AVR-337: one exact location, two fixed files tried in order, no request-derived path."""
        body = location_body(self.https, '= /party/catalog.json')
        self.assertEqual(re.findall(r'try_files\s+([^;]+);', body),
                         ['/var/lib/avrana-party/catalog/catalog.json /var/www/avrana-party/web/current/catalog.json =404'])
        self.assertNotRegex(body, r'\$')
        self.assertNotIn('proxy_pass', body)
        self.assertNotIn('/party/catalog.json', self.http)                       # plain HTTP serves no Party shell, overlay included
        # the overlay directory is the module's default
        from avrana.ops import catalog_overlay
        self.assertIn(catalog_overlay.DEFAULT_DIR + '/' + catalog_overlay.FILE_NAME, body)
        self.assertIn(catalog_overlay.DEFAULT_BASE, body)

    def test_shell_headers_match_the_dev_server(self):
        body = location_body(self.https, '/party/')
        headers = dict(re.findall(r'add_header\s+(\S+)\s+"([^"]*)"\s+always;', body))
        self.assertEqual(headers, SHELL_HEADERS)
        # the catalog Party Home reads has the same headers (AVR-337)
        body = location_body(self.https, '= /party/catalog.json')
        self.assertEqual(dict(re.findall(r'add_header\s+(\S+)\s+"([^"]*)"\s+always;', body)), SHELL_HEADERS)
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
                               'forwarded_for': self.headers.get('X-Forwarded-For'),
                               'upgrade': self.headers.get('Upgrade'),
                               'cookie': self.headers.get('Cookie')}).encode()
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
                               'upgrade': self.headers.get('Upgrade'),
                               'cookie': self.headers.get('Cookie')}).encode()
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
        cls.p80, cls.p443, cls.pgames = free_port(), free_port(), free_port()
        (tmp / 'native.location').write_text(
            (REPO_ROOT / 'deploy/games/nginx-native-games.location').read_text(encoding='utf-8')
            .replace('/run/avrana-games/', f'{tmp}/games/'))
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
                .replace('/var/www/avrana-party/web/current/', f'{tmp}/web/current/')
                .replace('/var/lib/avrana-party/catalog/', f'{tmp}/overlay/'))
        site += (f'\nserver {{\n    listen 127.0.0.1:{cls.pgames};\n    server_name games.avrana.net;\n'
                 f'    include {tmp}/native.location;\n}}\n')
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
        for path, label in (('/shared/shared.css', 'lan'), ('/generate_204', 'lan'), ('/party/', 'lan'),
                            ('/arcade/stats', 'arcade')):
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

    def test_the_catalog_is_the_overlay_when_there_is_one_and_the_release_file_when_there_is_not(self):
        """AVR-337: /party/catalog.json answers from the appliance-local overlay if it exists, else from
        the release tree; the same headers either way; nothing else changes."""
        release = (self.tmp / 'web' / 'current' / 'catalog.json').read_bytes()
        overlay = self.tmp / 'overlay' / 'catalog.json'
        self.assertFalse(overlay.exists())
        res, body = self.get('/party/catalog.json', https=True)
        self.assertEqual((res.status, body), (200, release))
        for key, value in SHELL_HEADERS.items():
            self.assertEqual(res.getheader(key), value, key)
        self.assertEqual(res.getheader('Content-Type'), 'application/json')
        effective = json.dumps({'schema': 'avrana.catalog/v0', 'games': [{'id': 'effective'}], 'labels': {}}).encode()
        overlay.parent.mkdir()
        try:
            overlay.write_bytes(effective)
            res, body = self.get('/party/catalog.json', https=True)
            self.assertEqual((res.status, body), (200, effective))
            for key, value in SHELL_HEADERS.items():
                self.assertEqual(res.getheader(key), value, key)
            self.assertEqual(res.getheader('Content-Type'), 'application/json')
            self.assertEqual(self.get('/party/catalog.json?v=1', https=True)[1], effective)
            # the neighbours are untouched: they never see the overlay
            self.assertIn(b'<title>Avrana Party</title>', self.get('/party/', https=True)[1])
            self.assertEqual(self.get('/party/overlay/catalog.json', https=True)[0].status, 404)
            self.assertEqual(self.get('/party/catalog.json/', https=True)[0].status, 404)
        finally:
            overlay.unlink()
            overlay.parent.rmdir()
        self.assertEqual(self.get('/party/catalog.json', https=True)[1], release)

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
        before_native, before_lan = len(self.native.seen), self.lan_paths()
        for path in ('/games/demo/avrana/session/v0/launch', '/games/demo/avrana/', '/games/bluff/avrana/session/v0/end',
                     '/games/Demo/avrana/x'):
            res, _ = self.get(path, https=True)
            self.assertEqual(res.status, 404, path)
            res, body = self.request('POST', path, body={})
            self.assertEqual(res.status, 404, path)
            self.assertNotIn(b'upstream', body, path)         # nginx answered, no process did
        self.assertEqual((len(self.native.seen), self.lan_paths()), (before_native, before_lan))

    DEVICE_COOKIES = '__Host-avrana_device=host-token; avrana_device=legacy-token; theme=dark'

    def test_no_game_server_on_the_party_host_receives_the_device_cookie(self):
        """AVR-314 / ADR 0003 section 4 / ADR 0013: a game process behind nginx sees no Cookie
        header at all (neither device cookie name, nor any other), on every location that proxies
        to one. The upstream stubs report the Cookie header they received."""
        extra = {'Cookie': self.DEVICE_COOKIES}
        legacy_cookie = {'Cookie': 'avrana_device=legacy-token'}
        for path in ('/games/bluff/?avrana=1', '/games/expo/ws', '/games/bluff', '/shared/shared.css', '/api/venue',
                     '/games/demo/play?seat=2', '/games/demo/ws'):
            for headers in (extra, legacy_cookie):
                res, body = self.request('GET', path, extra=headers)
                got = json.loads(body)
                self.assertEqual(res.status, 200, path)
                self.assertIn(got['upstream'], ('lan', 'native'), path)
                self.assertIsNone(got['cookie'], (path, headers))
                self.assertEqual(got['proto'], 'https', path)             # the other headers still go
                res, body = self.request('POST', path, body={'x': 1}, extra=headers)
                self.assertIsNone(json.loads(body)['cookie'], (path, headers))
        # a WebSocket upgrade keeps Upgrade and Connection and still loses the cookie
        res, body = self.request('GET', '/games/demo/ws', extra=dict(extra, Upgrade='websocket', Connection='Upgrade'))
        got = json.loads(body)
        self.assertEqual((got['upgrade'], got['cookie']), ('websocket', None))
        # the same on plain HTTP, where the two legacy games and the shared assets are served
        for path in ('/games/bluff/', '/games/expo/ws', '/shared/shared.css'):
            conn = http.client.HTTPConnection('127.0.0.1', self.p80, timeout=5)
            conn.request('GET', path, headers={'Host': 'party.local', 'Cookie': self.DEVICE_COOKIES})
            got = json.loads(conn.getresponse().read())
            conn.close()
            self.assertEqual(got['upstream'], 'lan', path)
            self.assertIsNone(got['cookie'], path)
        # and in the block that takes the shared native rules from the include file
        conn = http.client.HTTPConnection('127.0.0.1', self.pgames, timeout=5)
        conn.request('GET', '/games/demo/play', headers={'Host': 'games.avrana.net', 'Cookie': self.DEVICE_COOKIES})
        got = json.loads(conn.getresponse().read())
        conn.close()
        self.assertEqual((got['upstream'], got['cookie']), ('native', None))

    def test_the_arcade_process_receives_no_cookie(self):
        """AVR-318 / ADR 0003 section 4: the arcade server (stream.py, port 8097) reads no cookie,
        in HTTP or in the socket handshake (its seat comes from a ticket in the hello message), so
        /arcade/ sends it no Cookie header, in the HTTPS and in the port 80 block, with the
        upgrade headers intact. The Party API, in the same server block, still gets the cookie."""
        extra = {'Cookie': self.DEVICE_COOKIES}
        for path in ('/arcade/', '/arcade/stats', '/arcade/ws?audio=0'):
            res, body = self.request('GET', path, extra=extra)
            got = json.loads(body)
            self.assertEqual((res.status, got['upstream']), (200, 'arcade'), path)
            self.assertIsNone(got['cookie'], path)
            self.assertEqual(got['proto'], 'https', path)                 # the other headers still go
            res, body = self.request('POST', path, body={'x': 1}, extra=extra)
            self.assertIsNone(json.loads(body)['cookie'], path)
        res, body = self.request('GET', '/arcade/ws', extra=dict(extra, Upgrade='websocket', Connection='Upgrade'))
        got = json.loads(body)
        self.assertEqual((got['upgrade'], got['cookie']), ('websocket', None))
        for path in ('/arcade/', '/arcade/stats'):                         # the port 80 block
            conn = http.client.HTTPConnection('127.0.0.1', self.p80, timeout=5)
            conn.request('GET', path, headers={'Host': 'party.local', 'Cookie': self.DEVICE_COOKIES})
            got = json.loads(conn.getresponse().read())
            conn.close()
            self.assertEqual(got['upstream'], 'arcade', path)
            self.assertIsNone(got['cookie'], path)
        conn = http.client.HTTPConnection('127.0.0.1', self.p80, timeout=5)
        conn.request('GET', '/arcade/ws', headers={'Host': 'party.local', 'Cookie': self.DEVICE_COOKIES,
                                                   'Upgrade': 'websocket', 'Connection': 'Upgrade'})
        got = json.loads(conn.getresponse().read())
        conn.close()
        self.assertEqual((got['upgrade'], got['cookie']), ('websocket', None))

    def test_the_party_api_still_receives_the_device_cookie(self):
        """The counterpart of the test above: the cookie is cleared for games, not for the Party."""
        res, body = self.request('POST', '/party/api/join', {'name': 'Cookie Check'})
        self.assertEqual(res.status, 200, body)
        name = json.loads(body)['me']['name']
        pair = res.getheader('Set-Cookie').split(';')[0]
        self.assertTrue(pair.startswith('__Host-avrana_device='), pair)
        res, body = self.request('GET', '/party/api/state', extra={'Cookie': pair})
        self.assertEqual(json.loads(body)['me']['name'], name)          # the party read the cookie
        res, body = self.request('GET', '/party/api/state')
        self.assertIsNone(json.loads(body)['me'])

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

    def test_port_80_serves_no_native_game_and_only_the_two_legacy_games(self):
        """Plain HTTP reaches no native game, provisioned or not, and has no generic LAN Games
        answer for a game path: BLUFF and EXPO by name, everything else nginx's own 404."""
        for path in ('/games/bluff/', '/games/expo/ws', '/games/bluff'):
            got = json.loads(self.get(path)[1])
            self.assertEqual((got['upstream'], got['proto']), ('lan', 'http'), path)
        before, seen = self.lan_paths(), len(self.native.seen)
        for path in ('/games/demo/', '/games/demo/play?ticket=aps0.secret.sig', '/games/demo/ws', '/games/checkers/',
                     '/games/nosuchgame/play', '/games/Demo/', '/games/', '/games', '/games/x/../demo/play',
                     '/games/demo/avrana/session/v0/launch', '/games/bluff/avrana/session/v0/end'):
            for method in ('GET', 'POST'):
                conn = http.client.HTTPConnection('127.0.0.1', self.p80, timeout=5)
                conn.request(method, path, body=b'{}' if method == 'POST' else None, headers={'Host': 'party.local'})
                res = conn.getresponse()
                body = res.read()
                conn.close()
                self.assertEqual(res.status, 404, (method, path))
                self.assertNotIn(b'upstream', body, path)
        self.assertEqual((self.lan_paths(), len(self.native.seen)), (before, seen))

    def test_the_lan_games_hub_page_is_not_served_on_either_port(self):
        before = self.lan_paths()
        for path in ('/', '/?from=qr', '//', '/x/..'):
            res, body = self.get(path, host='party.local')
            self.assertEqual((res.status, res.getheader('Location'), res.getheader('Cache-Control'),
                              res.getheader('Content-Type')), (200, None, 'no-store', 'text/html'), path)
            self.assertIn(b'<a href="https://party.avrana.net/party/">', body)
            res, body = self.get(path, https=True)
            self.assertEqual(res.status, 302, path)
            self.assertTrue(res.getheader('Location').endswith('/party/'), path)
        res, body = self.request('POST', '/', body={})
        self.assertEqual(res.status, 302)
        for https in (False, True):
            for path in ('/shared/hub.html', '/shared/./hub.html', '/shared/%68ub.html', '/shared/hub.html/',
                         '/shared/hub.html/.', '/shared/hub.html%2f', '/shared//hub.html?x=1'):
                res, body = self.get(path, https=https)
                self.assertEqual(res.status, 404, path)
                self.assertNotIn(b'upstream', body, path)
            # what BLUFF and EXPO load from the root still reaches the runtime
            for path in ('/shared/hubnet.js', '/avatars/a.png', '/api/venue', '/chat/ws'):
                self.assertEqual(json.loads(self.get(path, https=https)[1])['upstream'], 'lan', path)
        asked = self.lan_paths()[len(before):]
        self.assertNotIn('/', asked)
        self.assertFalse([p for p in asked if 'hub.html' in p])

    def games_origin(self, path):
        conn = http.client.HTTPConnection('127.0.0.1', self.pgames, timeout=5)
        conn.request('GET', path, headers={'Host': 'games.avrana.net'})
        res = conn.getresponse()
        body = res.read()
        conn.close()
        return res, body

    def test_the_shared_rules_load_unchanged_in_another_server_block(self):
        """The include file as a later games.avrana.net block will take it: with `include`, with no
        legacy exception and no catch-all. Every title is native or nothing there."""
        res, body = self.games_origin('/games/demo/play?seat=1')
        got = json.loads(body)
        self.assertEqual((res.status, got['upstream'], got['path'], got['host']),
                         (200, 'native', '/games/demo/play?seat=1', 'games.avrana.net'))
        before, seen = self.lan_paths(), len(self.native.seen)
        for path, status in (('/games/demo/avrana/session/v0/launch', 404), ('/games/bluff/', 502),
                             ('/games/expo/ws', 502), ('/games/Demo/', 404), ('/games/', 404)):
            res, body = self.games_origin(path)
            self.assertEqual(res.status, status, path)
            self.assertNotIn(b'upstream', body, path)
        self.assertEqual((self.lan_paths(), len(self.native.seen)), (before, seen))

    def test_a_path_under_games_that_names_no_slug_is_a_404_from_nginx(self):
        before, seen = self.lan_paths(), len(self.native.seen)
        for path in ('/games', '/games/', '/games/Demo/', '/games/1demo/', '/games/demo.sock/', '/games/' + 'a' * 41 + '/',
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
        for path in ('/games/bluff/?avrana=1', '/games/expo/ws', '/games/bluff/shared.js', '/api/venue'):
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

    def test_near_miss_control_spellings_for_the_legacy_games_reach_that_runtime_as_proxied_requests(self):
        """Documented pass-throughs, as above: none is the control path the runtime routes (the
        exact lower-case /games/<slug>/avrana/...), and each arrives with the proxy headers, which
        its control routes refuse (Games tests/test_party_session.py
        test_launch_route_refuses_anything_not_local_and_unproxied)."""
        for path in ('/games/bluff/Avrana/session/v0/launch', '/games/expo/AVRANA/session/v0/end', '/games/bluff/avrana'):
            res, body = self.request('POST', path, body={})
            got = json.loads(body)
            self.assertEqual((got['upstream'], got['path']), ('lan', path), path)
            self.assertTrue(got['forwarded_for'], path)
        # the exact control path, in every spelling nginx normalises, never does
        before = self.lan_paths()
        for path in ('/games/bluff/avrana/', '/games/bluff//avrana/session/v0/launch', '/games/expo/%61vrana/session/v0/end',
                     '/games/bluff/x/../avrana/session/v0/launch'):
            res, body = self.request('POST', path, body={})
            self.assertEqual(res.status, 404, path)
        self.assertEqual(self.lan_paths(), before)

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
        lan = json.loads(self.get('/api/venue', https=True)[1])
        self.assertEqual((lan['upstream'], lan['proto']), ('lan', 'https'))
        self.assertEqual(json.loads(self.get('/arcade/', https=True)[1])['upstream'], 'arcade')


    # ---- AVR-319: the game origin, through real nginx ----------------------------------------
    def on(self, host, path, method='GET', extra=None, body=None):
        return self.request(method, path, body=body, extra=dict({'Host': host}, **(extra or {})))

    def test_the_game_origin_serves_a_native_game_page_and_clears_the_cookie(self):
        for method in ('GET', 'POST'):
            res, payload = self.on('games.avrana.net', '/games/demo/play?seat=1', method,
                                   {'Cookie': self.DEVICE_COOKIES}, body={'x': 1} if method == 'POST' else None)
            got = json.loads(payload)
            self.assertEqual((res.status, got['upstream'], got['path'], got['host'], got['proto']),
                             (200, 'native', '/games/demo/play?seat=1', 'games.avrana.net', 'https'))
            self.assertIsNone(got['cookie'])
        res, payload = self.on('games.avrana.net', '/games/demo/ws',
                               extra={'Upgrade': 'websocket', 'Connection': 'Upgrade', 'Cookie': self.DEVICE_COOKIES})
        got = json.loads(payload)
        self.assertEqual((got['upgrade'], got['cookie']), ('websocket', None))

    def test_the_game_origin_refuses_the_party_and_the_arcade_and_reaches_no_other_upstream(self):
        lan, arcade, native = len(self.lan.seen), len(self.arcade.seen), len(self.native.seen)
        for path in ('/party', '/party/', '/party/index.html', '/party/bridge.html', '/party/api/state',
                     '/party/api/origin.json', '/party/api/bridge', '/party/api/session/ticket', '/party/sw.js',
                     '/arcade', '/arcade/', '/arcade/stats', '/', '/index.html', '/api/venue', '/shared/shared.css',
                     '/shared/hub.html', '/games', '/games/', '//party/api/state', '/party/../party/api/state',
                     '/games/demo/avrana/session/v0/launch'):
            for method in ('GET', 'POST'):
                res, payload = self.on('games.avrana.net', path, method, {'Cookie': self.DEVICE_COOKIES},
                                       body={'x': 1} if method == 'POST' else None)
                self.assertEqual(res.status, 404, (method, path))
                self.assertNotIn(b'upstream', payload, path)
                self.assertIsNone(res.getheader('Set-Cookie'), path)
        self.assertEqual((len(self.lan.seen), len(self.arcade.seen), len(self.native.seen)), (lan, arcade, native))

    def test_the_bridge_page_on_the_party_host_may_be_framed_by_the_game_origin_only(self):
        res, payload = self.on('party.avrana.net', '/party/bridge.html')
        self.assertEqual(res.status, 200)
        self.assertEqual(payload, (self.tmp / 'web' / 'current' / 'bridge.html').read_bytes())
        self.assertEqual(res.msg.get_all('Content-Security-Policy'), [BRIDGE_CSP])      # one policy, not two
        for key, value in SHELL_HEADERS.items():
            if key != 'Content-Security-Policy':
                self.assertEqual(res.getheader(key), value, key)
        self.assertIsNone(res.getheader('X-Frame-Options'))
        for path in ('/party/', '/party/index.html', '/party/diag/', '/party/lib/bridge.js'):   # nothing else is frameable
            res, _ = self.on('party.avrana.net', path)
            self.assertEqual(res.status, 200, path)
            self.assertIn("frame-ancestors 'none'", res.getheader('Content-Security-Policy'), path)

    def test_neither_host_sends_hsts_or_a_service_worker_scope_header(self):
        for host, path in (('party.avrana.net', '/party/'), ('party.avrana.net', '/party/sw.js'),
                           ('party.avrana.net', '/party/bridge.html'), ('party.avrana.net', '/'),
                           ('games.avrana.net', '/games/demo/play'), ('games.avrana.net', '/party/'),
                           ('games.avrana.net', '/')):
            res, _ = self.on(host, path)
            self.assertIsNone(res.getheader('Strict-Transport-Security'), (host, path))
            self.assertIsNone(res.getheader('Service-Worker-Allowed'), (host, path))

    def test_an_unknown_host_is_never_served_by_the_game_origin_block(self):
        """The game block is chosen by the exact name, never by default: another Host on the same
        port gets the Party block (the default), which serves /party/, not the game block's refusal."""
        for host in ('games.avrana.net.example', 'xgames.avrana.net', 'avrana.net', 'other.example'):
            res, _ = self.on(host, '/party/')
            self.assertEqual(res.status, 200, host)
            self.assertIn("frame-ancestors 'none'", res.getheader('Content-Security-Policy'), host)
        self.assertEqual(self.on('GAMES.avrana.net', '/party/')[0].status, 404)    # host names are not case-sensitive

    def test_a_certificate_that_names_only_the_party_host_still_loads_and_serves_the_game_block(self):
        """The test certificate has the single SAN party.avrana.net, as an appliance with the one-name
        certificate does: nginx -t passed in setUpClass and the game block answers. Only a browser
        refuses the name, which is why game_origins is set after the certificate."""
        out = subprocess.run(['openssl', 'x509', '-in', str(self.tmp / 'cert.pem'), '-noout', '-ext', 'subjectAltName'],
                             capture_output=True, text=True).stdout
        self.assertIn('DNS:party.avrana.net', out)
        self.assertNotIn('games.avrana.net', out)
        self.assertEqual(self.on('games.avrana.net', '/games/demo/play')[0].status, 200)


# ---- AVR-319: the game origin (games.avrana.net), static rules ---------------------------------
BRIDGE_CSP = SHELL_HEADERS['Content-Security-Policy'].replace(
    "frame-ancestors 'none'", 'frame-ancestors https://games.avrana.net')


class GameOriginStaticRules(unittest.TestCase):
    def setUp(self):
        blocks = server_blocks(SITE)
        self.assertEqual(len(blocks), 3)
        self.party, self.games = blocks[1], blocks[2]

    def test_the_game_origin_is_its_own_https_block_that_is_never_the_default(self):
        self.assertIn('server_name games.avrana.net;', self.games)
        self.assertNotIn('party.avrana.net', self.games)
        self.assertIn('listen 443 ssl;', self.games)
        self.assertNotIn('default_server', self.games)
        for key in ('ssl_certificate ', 'ssl_certificate_key ', 'ssl_protocols '):
            line = re.search(r'^\s*' + key + r'.*$', self.party, re.M).group(0)
            self.assertIn(line, self.games)

    def test_the_game_origin_serves_native_games_and_refuses_everything_else(self):
        native = (REPO_ROOT / 'deploy/games/nginx-native-games.location').read_text(encoding='utf-8')
        self.assertEqual(self.games.count(native), 1)
        self.assertEqual(locations(self.games), ['^~ /party', '^~ /arcade', *StaticRules.GAMES[1:], '/'])
        for name in ('^~ /party', '^~ /arcade', '/'):       # a catch-all that is not nginx's default root
            self.assertEqual(location_body(self.games, name).split(), ['return', '404;'])
        rules = '\n'.join(l for l in self.games.splitlines() if not l.lstrip().startswith('#'))
        self.assertEqual(re.findall(r'proxy_pass\s+(\S+);', rules),
                         ['http://unix:/run/avrana-games/$native_game.sock:$request_uri'])
        self.assertNotRegex(rules, r'8096|8097|8191|alias|root |auth_request|add_header|bluff|expo')
        self.assertIn('proxy_set_header Cookie "";', rules)

    def test_no_hsts_and_no_service_worker_scope_header_in_any_block(self):
        for block in server_blocks(SITE):
            self.assertNotRegex(block, r'(?i)add_header\s+(Strict-Transport-Security|Service-Worker-Allowed)')

    def test_only_the_bridge_page_may_be_framed_and_only_by_the_game_origin(self):
        body = location_body(self.party, '= /party/bridge.html')
        headers = dict(re.findall(r'add_header\s+(\S+)\s+"([^"]*)"\s+always;', body))
        self.assertEqual(headers, dict(SHELL_HEADERS, **{'Content-Security-Policy': BRIDGE_CSP}))
        self.assertIn('alias /var/www/avrana-party/web/current/bridge.html;', body)
        self.assertEqual(self.party.count('frame-ancestors https://games.avrana.net'), 1)    # in that location only
        self.assertEqual(self.party.count("frame-ancestors 'none'"), 2)                      # every other Party page: /party/ and the catalog (AVR-337)
        self.assertNotIn('frame-ancestors', self.games)
        self.assertNotIn('X-Frame-Options', SITE)


if __name__ == '__main__':
    unittest.main()
