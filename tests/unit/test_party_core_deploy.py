"""The Party Core deployment package (AVR-51): deploy/party-core/*, ops/provision-party-game-key.sh.

Tier 1 checks the templates against the code and contracts they must agree with. Tier 2 runs real
nginx with the proposed /party/api/ block spliced into the committed site and the real party
service behind it, and re-runs every existing real-nginx check on that site, so adding the block
is shown not to change what is live. Skipped without nginx unless AVRANA_REQUIRE_NGINX=1 (CI).
The Pi, the real certificate and phones stay Tier 3 (docs/runbooks/party-core-deploy.md).
"""
import http.client
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import tempfile
import threading
import time
import unittest

from avrana import REPO_ROOT
from avrana.party import identity, protocol, service
import test_nginx_site as base
from test_nginx_site import SITE, location_body, locations, server_blocks

DEPLOY = REPO_ROOT / 'deploy' / 'party-core'
CONFIG = json.loads((DEPLOY / 'party-core.example.json').read_text(encoding='utf-8'))
UNIT = (DEPLOY / 'avrana-party-core.service').read_text(encoding='utf-8')
BLOCK = (DEPLOY / 'nginx-party-api.location').read_text(encoding='utf-8')
ANCHOR = re.search(r'\n    location = /party/api/origin\.json \{.*?\n    \}\n', SITE, re.S)


def with_party_api(site, port=8191):
    """The committed site with the proposed block after the origin.json location (443 server)."""
    block = BLOCK.replace('http://127.0.0.1:8191', f'http://127.0.0.1:{port}')
    return site[:ANCHOR.end()] + '\n' + block + site[ANCHOR.end():]


def directives(text):
    return [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith('#')]


class Templates(unittest.TestCase):
    def test_config_loads_and_matches_the_https_origin(self):
        games = service.load_games(CONFIG['games'])
        self.assertEqual(set(CONFIG['hosts']), {'party.avrana.net'})            # nginx: Host $host
        self.assertEqual(set(CONFIG['origins']), {'https://party.avrana.net'})
        self.assertIs(CONFIG['secure_cookie'], True)
        self.assertTrue(CONFIG['devices'].startswith('/var/lib/avrana-party-core/'))  # StateDirectory
        self.assertIn('StateDirectory=avrana-party-core', UNIT)
        appliance = json.loads((REPO_ROOT / 'contracts/appliances/avrana-pi4.json').read_text(encoding='utf-8'))
        granted = {g['game']: g['entry'] for g in appliance['installed']}
        for gid, entry in CONFIG['games'].items():
            contract = json.loads((REPO_ROOT / f'contracts/games/{gid}.json').read_text(encoding='utf-8'))
            self.assertEqual(games[gid]['max_players'], contract['players']['max'], gid)
            self.assertEqual(entry['url'], f'http://127.0.0.1:8096{granted[gid].rstrip("/")}', gid)
            self.assertEqual(entry['key_file'], f'/etc/avrana-party/game-keys/{gid}.key', gid)

    def test_unit_runs_the_service_on_loopback_port_8191_without_secrets(self):
        self.assertRegex(UNIT, r'(?m)^ExecStart=/usr/bin/python3 -m avrana\.party\.service '
                               r'--config /etc/avrana-party/party-core\.json --port 8191$')
        self.assertRegex(UNIT, r'(?m)^User=cody$')
        self.assertRegex(UNIT, r'(?m)^WorkingDirectory=/home/cody/avrana-party$')
        self.assertRegex(UNIT, r'(?m)^NoNewPrivileges=yes$')
        self.assertNotRegex(UNIT, r'(?im)^Environment=.*(key|token|secret)')
        self.assertEqual(service.make_server.__defaults__[0], '127.0.0.1')      # loopback bind

    def test_block_forwards_only_the_party_api(self):
        lines = directives(BLOCK)
        self.assertEqual(lines[0], 'location /party/api/ {')
        self.assertIn('proxy_pass http://127.0.0.1:8191;', lines)             # no URI: path kept
        self.assertNotIn('internal', ' '.join(lines))
        self.assertIn('proxy_set_header Host $host;', lines)
        self.assertIn('proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;', lines)
        timeout = int(re.search(r'proxy_read_timeout (\d+)s;', BLOCK).group(1))
        self.assertGreater(timeout, service.MAX_WAIT + 5)                    # long poll + slack
        size = re.search(r'client_max_body_size (\d+)k;', BLOCK).group(1)
        self.assertEqual(int(size) * 1024, service.MAX_BODY)
        self.assertNotRegex(BLOCK, r'add_header\s+(Strict-Transport-Security|Service-Worker-Allowed)')
        self.assertNotRegex(BLOCK, r'(?i)hsts')

    def test_block_is_proposed_not_committed_to_the_site(self):
        # The owner-approved deploy adds it to both tracked copies and the live site together.
        self.assertNotIn('location /party/api/ {', SITE)
        _, https = server_blocks(with_party_api(SITE))
        self.assertEqual(locations(https), ['= /party', '= /party/api/origin.json', '/party/api/',
                                            '/party/', '/arcade/', '/'])
        http_block, _ = server_blocks(with_party_api(SITE))
        self.assertEqual(http_block, server_blocks(SITE)[0])                  # port 80 untouched
        self.assertIn('proxy_pass http://127.0.0.1:8191;', location_body(https, '/party/api/'))


@unittest.skipUnless(os.name == 'posix' and shutil.which('bash'), 'needs bash and POSIX modes')
class KeyScript(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dir = os.path.join(self.tmp, 'game-keys')
        import getpass
        self.env = dict(os.environ, AVRANA_PARTY_KEY_DIR=self.dir, AVRANA_PARTY_KEY_OWNER=getpass.getuser())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_script(self, *args):
        return subprocess.run(['bash', str(REPO_ROOT / 'ops/provision-party-game-key.sh'), *args],
                              env=self.env, capture_output=True, text=True)

    def test_creates_a_private_key_the_protocol_reads_and_never_prints_it(self):
        r = self.run_script('bluff')
        self.assertEqual(r.returncode, 0, r.stderr)
        path = os.path.join(self.dir, 'bluff.key')
        self.assertEqual(stat.S_IMODE(os.stat(self.dir).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        key = protocol.read_key(path)
        self.assertEqual(len(key), 32)
        self.assertNotIn(key.hex(), r.stdout + r.stderr)
        self.assertEqual(os.listdir(self.dir), ['bluff.key'])                 # no temp file left

    def test_refuses_to_overwrite_and_bad_slugs(self):
        self.assertEqual(self.run_script('bluff').returncode, 0)
        before = open(os.path.join(self.dir, 'bluff.key')).read()
        again = self.run_script('bluff')
        self.assertEqual(again.returncode, 1)
        self.assertEqual(open(os.path.join(self.dir, 'bluff.key')).read(), before)
        for bad in ('', '../x', 'Bluff', 'a/b'):
            self.assertEqual(self.run_script(bad).returncode, 2, bad)


class ProposedSiteWithPartyCore(base.RealNginx):
    """Every existing real-nginx check, on the site with the proposed block, plus the real party
    service behind /party/api/ (inherits RealNginx's skip rule)."""

    @classmethod
    def setUpClass(cls):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            cls.party_port = probe.getsockname()[1]
        games = service.load_games({'bluff': {'max_players': 6}})
        svc = service.PartyService(identity.DeviceStore(None), games)
        cfg = service.Config(CONFIG['hosts'], CONFIG['origins'], CONFIG['secure_cookie'])
        cls.party = service.make_server(svc, cfg, port=cls.party_port)
        threading.Thread(target=cls.party.serve_forever, daemon=True).start()
        cls.site = with_party_api(SITE, cls.party_port)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.party.shutdown()

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

    def test_state_and_join_through_nginx(self):
        res, body = self.request('GET', '/party/api/state')
        self.assertEqual(res.status, 200)
        self.assertEqual(res.getheader('Cache-Control'), 'no-store')
        view = json.loads(body)
        self.assertIsNone(view['me'])
        res, body = self.request('POST', '/party/api/join', {'name': 'Robin'})
        self.assertEqual(res.status, 200, body)
        cookie = res.getheader('Set-Cookie')
        for part in ('HttpOnly', 'Secure', 'Path=/party/', 'SameSite=Lax'):
            self.assertIn(part, cookie)
        self.assertEqual(json.loads(body)['me']['name'], 'Robin')
        res, _ = self.request('POST', '/party/api/join', {'name': 'Mallory'}, origin='https://evil.test')
        self.assertEqual(res.status, 403)

    def test_long_poll_outlives_a_short_wait(self):
        version = json.loads(self.request('GET', '/party/api/state')[1])['version']
        started = time.monotonic()
        res, body = self.request('GET', f'/party/api/state?since={version}&wait=2')
        self.assertEqual(res.status, 200)
        self.assertGreaterEqual(time.monotonic() - started, 1.5)
        self.assertEqual(json.loads(body)['version'], version)

    def test_origin_json_stays_with_nginx_and_internal_never_reaches_the_party(self):
        origin = json.loads(self.request('GET', '/party/api/origin.json')[1])
        self.assertEqual(origin['schema'], 'avrana.origin/v0')
        lan = json.loads(self.request('GET', '/internal/party-session/v0/ended')[1])
        self.assertEqual(lan['upstream'], 'lan')                      # the games hub, not the party
        res, body = self.request('GET', '/party/api/internal/party-session/v0/ended')
        self.assertEqual((res.status, json.loads(body)['error']), (404, 'not_found'))


if __name__ == '__main__':
    unittest.main()
