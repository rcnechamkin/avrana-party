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
    return re.findall(r'^\s*location\s+([^{]+?)\s*\{', block, re.M)


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

    def test_port_80_is_unchanged(self):
        self.assertIn('listen 80 default_server;', self.http)
        self.assertEqual(locations(self.http), ['= /hotspot-detect.html', '/arcade/', '/'])
        probe = location_body(self.http, '= /hotspot-detect.html')
        self.assertIn('return 200 "' + APPLE_SUCCESS.replace('\n', '\\n') + '";', probe)
        self.assertIn('add_header Cache-Control "no-store" always;', probe)
        self.assertNotIn('return 30', self.http.replace('return 200', ''))  # no redirects on HTTP

    def test_party_is_https_only(self):
        self.assertEqual(locations(self.https), ['= /party', '= /party/api/origin.json', '/party/api/',
                                                 '/party/', '/arcade/', '/'])
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
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({'upstream': label, 'path': self.path,
                               'proto': self.headers.get('X-Forwarded-Proto'),
                               'upgrade': self.headers.get('Upgrade')}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
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
        cls.p80, cls.p443 = free_port(), free_port()
        site = (cls.site
                .replace('listen 80 default_server;', f'listen 127.0.0.1:{cls.p80} default_server;')
                .replace('listen [::]:80 default_server;', '')
                .replace('listen 443 ssl;', f'listen 127.0.0.1:{cls.p443} ssl;')
                .replace('listen [::]:443 ssl;', '')
                .replace('/etc/avrana-party/tls/current/fullchain.pem', str(tmp / 'cert.pem'))
                .replace('/etc/avrana-party/tls/current/privkey.pem', str(tmp / 'key.pem'))
                .replace('http://127.0.0.1:8096', f'http://127.0.0.1:{cls.lan.server_port}')
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

    def request(self, method, path, body=None, origin='https://party.avrana.net'):
        conn = http.client.HTTPSConnection('127.0.0.1', self.p443, context=self.tls, timeout=10)
        conn.sock = self.tls.wrap_socket(socket.create_connection(('127.0.0.1', self.p443), timeout=10),
                                         server_hostname='party.avrana.net')
        headers = {'Host': 'party.avrana.net'}
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

    def test_https_apps_still_proxied(self):
        lan = json.loads(self.get('/', https=True)[1])
        self.assertEqual((lan['upstream'], lan['proto']), ('lan', 'https'))
        self.assertEqual(json.loads(self.get('/arcade/', https=True)[1])['upstream'], 'arcade')


if __name__ == '__main__':
    unittest.main()
