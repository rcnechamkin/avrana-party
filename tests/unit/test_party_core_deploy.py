"""The Party Core deployment package (AVR-51): deploy/party-core/*, ops/provision-party-game-key.sh.

Tier 1 checks the templates against the code and contracts they must agree with, and that the
committed site carries the nginx block verbatim. The real-nginx run with the real party service
behind that block is tests/unit/test_nginx_site.py (Tier 2). The Pi, the real certificate and
phones stay Tier 3 (docs/runbooks/party-core-deploy.md).
"""
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest

from avrana import REPO_ROOT
from avrana.party import protocol, service
from test_nginx_site import SITE, location_body, server_blocks

DEPLOY = REPO_ROOT / 'deploy' / 'party-core'
CONFIG = json.loads((DEPLOY / 'party-core.example.json').read_text(encoding='utf-8'))
UNIT = (DEPLOY / 'avrana-party-core.service').read_text(encoding='utf-8')
BLOCK = (DEPLOY / 'nginx-party-api.location').read_text(encoding='utf-8')


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

    def test_site_carries_the_block_verbatim_on_https_only(self):
        # deploy/party-core/nginx-party-api.location is the source copy of the committed block.
        self.assertEqual(SITE.count(BLOCK), 1)
        http_block, https = server_blocks(SITE)
        self.assertIn(BLOCK, https)
        self.assertNotIn('/party/api/ {', http_block)
        self.assertIn('proxy_pass http://127.0.0.1:8191;', location_body(https, '/party/api/'))
        self.assertLess(https.index('location = /party/api/origin.json'), https.index('location /party/api/ {'))


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


if __name__ == '__main__':
    unittest.main()
