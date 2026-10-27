"""The hosted staging nginx site (avrana.ops.hosted_site, docs/design/HOSTED-STAGING.md).

The hosted site is a rendering of avrana-party.nginx, never a second hand-kept file: these tests hold
it to the appliance's rules location by location, so a change to the Pi site either reaches hosted
staging unchanged or fails here."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from avrana.ops import hosted_site as hs

REPO_ROOT = Path(__file__).resolve().parents[2]
SITE = (REPO_ROOT / 'avrana-party.nginx').read_text(encoding='utf-8')
HOSTED = (REPO_ROOT / 'deploy' / 'hosted' / 'avrana-party.hosted.nginx').read_text(encoding='utf-8')

# Party PR #143 (AVR-466, DRAFT, deploy gated): the package-art location as that PR adds it to the Party block.
PKGART = '''    location ~ "^/party/pkgart/(?<art_game>[a-z][a-z0-9_-]{0,39})/(?<art_file>[0-9a-f]{16}\\.(webp|png|jpg))$" {
        alias /var/lib/avrana-party/catalog/art/$art_game/$art_file;
        types { image/webp webp; image/png png; image/jpeg jpg; }
        default_type application/octet-stream;
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Content-Security-Policy "default-src 'none'; sandbox" always;
        add_header Referrer-Policy "same-origin" always;
    }

'''


def blocks(text):
    return [text[a:b] for a, b in hs.server_blocks(text)]


def locations(block):
    return re.findall(r'^\s*location\s+((?:"[^"]*"|[^{"])+?)\s*\{', block, re.M)


def body(block, name):
    a, b = hs._location_span(block, name)
    inner = block[a:b]
    return inner[inner.index('{', inner.index('location')) + 1:inner.rstrip().rindex('}')]


def hosted_form(text):
    """What the renderer may change inside a location: the names, the scheme, and the access headers it
    clears after every proxy_pass."""
    text = (text.replace('$scheme', 'https').replace(hs.APPLIANCE_GAME_HOST, hs.GAME_HOST)
            .replace(hs.APPLIANCE_PARTY_HOST, hs.PARTY_HOST))
    return re.sub(r'^([ \t]*)(proxy_pass [^;]*;\n)', lambda m: m.group(1) + m.group(2) + ''.join(
        f'{m.group(1)}proxy_set_header {h} "";\n' for h in hs.ACCESS_HEADERS), text, flags=re.M)


class Committed(unittest.TestCase):
    def test_the_committed_file_is_what_the_appliance_site_renders(self):
        self.assertEqual(HOSTED, hs.render(SITE), 'run: python3 -m avrana.ops.hosted_site')
        self.assertEqual(hs.main(['--check']), 0)


class Rules(unittest.TestCase):
    def setUp(self):
        self.default, self.party, self.games = blocks(HOSTED)
        _, self.pi_party, self.pi_games = blocks(SITE)

    def test_three_servers_all_on_the_loopback_edge_without_tls(self):
        for block in (self.default, self.party, self.games):
            self.assertEqual(re.findall(r'^\s*listen\s+([^;]+);', block, re.M)[0].split()[0], '127.0.0.1:8080')
            self.assertNotRegex(block, r'\bssl|listen\s+(\[::\]:)?(80|443)\b|\$scheme|\$server_addr')
        self.assertIn('default_server', self.default)
        self.assertEqual(re.findall(r'server_name\s+([^;]+);', HOSTED), ['_', 'avrana.party', 'games.avrana.party'])
        self.assertEqual(locations(self.default), ['/'])
        self.assertIn('return 404;', self.default)

    def test_no_appliance_name_hardware_or_lan_games_runtime(self):
        self.assertNotIn('avrana.net', HOSTED)
        self.assertNotIn('8096', HOSTED)
        self.assertNotIn('8097', HOSTED)
        self.assertNotIn('/arcade/', locations(self.party))
        self.assertNotIn('hotspot-detect', HOSTED)
        self.assertEqual(body(self.party, '/').strip(), 'return 404;')

    def test_every_other_party_location_is_the_appliances_own(self):
        dropped = {'/arcade/', *hs.LEGACY_LOCATIONS}
        legacy = [f'^~ /games/{g}/' for g in hs.LEGACY_GAMES]
        expected = [n for n in locations(self.pi_party) if n not in dropped] + legacy + ['/']
        self.assertEqual(locations(self.party), expected + ['^~ /__gate/'])   # the password gate's form, last
        for name in legacy:
            self.assertEqual(body(self.party, name).strip(), 'return 404;', name)
        for name in expected[:-1 - len(legacy)]:
            if name == '= /party/api/origin.json':
                continue
            self.assertEqual(body(self.party, name), hosted_form(body(self.pi_party, name)), name)

    def test_the_game_origin_is_the_appliances_own(self):
        self.assertEqual(locations(self.games), locations(self.pi_games))
        for name in locations(self.pi_games):
            self.assertEqual(body(self.games, name), hosted_form(body(self.pi_games, name)), name)

    def test_no_access_assertion_or_token_reaches_party_core_or_a_game(self):
        passes = re.findall(r'^[ \t]*proxy_pass [^;]*;\n((?:[ \t]*proxy_set_header Cf-[^;]*;\n)*)', HOSTED, re.M)
        self.assertEqual(len(passes), len(re.findall(r'proxy_pass ', HOSTED)))
        for cleared in passes:
            self.assertEqual(re.findall(r'proxy_set_header (\S+) "";', cleared), list(hs.ACCESS_HEADERS))

    def test_frames_name_the_hosted_game_origin(self):
        self.assertIn('frame-ancestors https://games.avrana.party"', body(self.party, '= /party/bridge.html'))
        self.assertIn("frame-ancestors 'self' https://games.avrana.party\"", body(self.party, '= /party/layer.html'))

    def test_the_forwarded_scheme_is_https_and_cookies_never_reach_a_game(self):
        for block in (self.party, self.games):
            protos = re.findall(r'X-Forwarded-Proto\s+([^;]+);', block)
            self.assertTrue(protos)
            self.assertEqual(set(protos), {'https'})
        for name in ('~ "^/games/(?<native_game>[a-z][a-z0-9_-]{0,39})/"',):
            for block in (self.party, self.games):
                self.assertIn('proxy_set_header Cookie "";', body(block, name))

    def test_origin_json_says_hosted_and_carries_no_address(self):
        b = body(self.party, '= /party/api/origin.json')
        self.assertIn('"network":"hosted"', b)
        self.assertIn('"schema":"avrana.origin/v0"', b)
        self.assertNotIn('$server_addr', b)
        self.assertIn('no-store', b)

    def test_internal_and_control_paths_are_never_proxied(self):
        for block in (self.party, self.games):
            self.assertFalse([n for n in locations(block) if 'internal' in n])
        self.assertIn('proxy_pass http://127.0.0.1:8191;', body(self.party, '/party/api/'))
        self.assertEqual(body(self.games, '~ ^/games/[^/]+/avrana/').strip(), 'return 404;')


class Rendering(unittest.TestCase):
    def test_package_art_from_pr_143_passes_through_to_the_party_and_never_the_game_origin(self):
        anchor = '    location /party/ {\n'
        self.assertEqual(SITE.count(anchor), 1)
        with_art = SITE.replace(anchor, PKGART + anchor) if 'pkgart' not in SITE else SITE
        _, party, games = blocks(hs.render(with_art))
        names = locations(party)
        art = [n for n in names if 'pkgart' in n]
        self.assertEqual(len(art), 1)
        self.assertLess(names.index(art[0]), names.index('/party/'))
        self.assertIn('alias /var/lib/avrana-party/catalog/art/$art_game/$art_file;', party)
        self.assertNotIn('pkgart', games)

    def test_legacy_lan_games_routes_only_when_asked(self):
        _, party, _ = blocks(hs.render(SITE, legacy_lan_games=True))
        self.assertIn('~ "^/games/(bluff|expo)(/(?!avrana/)|$)"', locations(party))
        self.assertIn('proxy_pass http://127.0.0.1:8096;', body(party, '/'))
        self.assertNotIn('/arcade/', locations(party))          # the arcade is never hosted
        self.assertIn('LAN Games runtime routes (BLUFF/EXPO): included', hs.render(SITE, legacy_lan_games=True))

    def test_other_names_and_ports_render(self):
        text = hs.render(SITE, party_host='staging.example.org', game_host='games.staging.example.org', listen='127.0.0.1:9090')
        self.assertIn('server_name staging.example.org;', text)
        self.assertIn('frame-ancestors https://games.staging.example.org"', text)
        self.assertNotIn('8080', text)

    def test_refusals(self):
        for kwargs in ({'party_host': 'Avrana.Party'}, {'game_host': 'games'}, {'party_host': 'x.party', 'game_host': 'x.party'},
                       {'listen': '0.0.0.0:8080'}, {'listen': '8080'}, {'listen': '10.0.0.5:80'},
                       {'gate_listen': '127.0.0.1:8080'}, {'gate_listen': '0.0.0.0:8081'}, {'game_host': 'games.other.org'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(hs.RenderError):
                hs.render(SITE, **kwargs)
        for broken in (SITE.replace('server_name games.avrana.net;', 'server_name games.example;'),
                       SITE.replace('    location /arcade/ {', '    location /arcadex/ {', 1).replace('    location /arcade/ {', '    location /arcadey/ {'),
                       SITE.split('# The game origin (ADR 0013')[0],
                       SITE.replace('"schema":"avrana.origin/v0"', '"schema":"x"')):
            with self.assertRaises(hs.RenderError):
                hs.render(broken)


class Gate(unittest.TestCase):
    """The password gate (avrana/ops/hosted_gate.py): the tunnel's port is gated, the VM-local one is not."""
    def setUp(self):
        self.default, self.party, self.games = blocks(HOSTED)

    def test_every_server_listens_on_both_ports_and_the_two_named_servers_are_gated(self):
        for block in (self.default, self.party, self.games):
            self.assertEqual([l.split()[0] for l in re.findall(r'^\s*listen\s+([^;]+);', block, re.M)],
                             [hs.LISTEN, hs.GATE_LISTEN])
        for block in (self.party, self.games):
            self.assertIn('    if ($avrana_gate_closed) {\n        return 302 https://avrana.party/__gate/;\n    }\n', block)

    def test_the_gate_opens_only_for_the_token_and_never_shuts_the_form_or_the_local_port(self):
        head = HOSTED.split('server {', 1)[0]
        self.assertIn('map $cookie_avrana_gate $avrana_gate_cookie {\n    default 0;\n    include /etc/avrana-party/gate*.map;\n}', head)
        rules = re.search(r'map "\$server_port:\$avrana_gate_cookie:\$host\$uri" \$avrana_gate_closed \{(.*?)\}', head, re.S).group(1)
        closed = []
        for line in rules.strip().splitlines():
            key, value = line.strip().rstrip(';').rsplit(' ', 1)
            closed.append((key.strip('"'), value))
        self.assertEqual(closed, [('default', '0'), ('~^8081:0:[^/]*/__gate/', '0'),
                                  (r'~^8081:0:games\.avrana\.party/games/[a-z0-9][a-z0-9_-]*/(api/|onboarding\.json$)', '0'),
                                  ('~^8081:0:', '1')])

        def is_closed(port, cookie_ok, uri, host='avrana.party'):
            key = f'{port}:{cookie_ok}:{host}{uri}'
            for pattern, value in closed[1:]:
                if re.search(pattern[1:], key):
                    return value == '1'
            return False
        self.assertTrue(is_closed(8081, 0, '/party/'))
        self.assertTrue(is_closed(8081, 0, '/games/checkers/', 'games.avrana.party'))
        self.assertTrue(is_closed(8081, 0, '/games/checkers/app.mjs', 'games.avrana.party'))
        self.assertTrue(is_closed(8081, 0, '/games/checkers/onboarding.json.map', 'games.avrana.party'))
        self.assertTrue(is_closed(8081, 0, '/games/checkers/api/party', 'avrana.party'))
        self.assertTrue(is_closed(8081, 0, '/party/api/state', 'games.avrana.party'))
        # game clients fetch these with credentials 'omit': the game's own seat check answers them
        self.assertFalse(is_closed(8081, 0, '/games/checkers/api/party', 'games.avrana.party'))
        self.assertFalse(is_closed(8081, 0, '/games/colyseus-tanks/api/redeem', 'games.avrana.party'))
        self.assertFalse(is_closed(8081, 0, '/games/coup/onboarding.json', 'games.avrana.party'))
        self.assertTrue(is_closed(8081, 0, '/__gatex'))
        self.assertFalse(is_closed(8081, 0, '/__gate/'))
        self.assertFalse(is_closed(8081, 1, '/party/'))
        self.assertFalse(is_closed(8080, 0, '/party/'))

    def test_the_form_is_rate_limited_and_only_on_the_party_host(self):
        self.assertIn('limit_req_zone $server_port zone=avrana_gate:1m rate=30r/m;', HOSTED)
        gate = body(self.party, '^~ /__gate/')
        self.assertIn('limit_req zone=avrana_gate burst=10 nodelay;', gate)
        self.assertIn('proxy_pass http://unix:/run/avrana-gate/gate.sock;', gate)
        self.assertNotIn('__gate', self.games.replace('return 302 https://avrana.party/__gate/;', ''))


NGINX = shutil.which('nginx') or ('/usr/sbin/nginx' if os.path.exists('/usr/sbin/nginx') else None)


@unittest.skipUnless(NGINX, 'nginx is not installed here (the remote Linux run has it)')
class RealNginx(unittest.TestCase):
    def test_nginx_accepts_the_rendered_site(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / 'hosted.conf'
            site.write_text(HOSTED, encoding='utf-8')
            conf = Path(tmp) / 'nginx.conf'
            conf.write_text(f'pid {tmp}/nginx.pid;\nerror_log {tmp}/error.log;\nevents {{}}\nhttp {{\n'
                            f'  access_log off;\n  client_body_temp_path {tmp};\n  proxy_temp_path {tmp};\n'
                            f'  fastcgi_temp_path {tmp};\n  uwsgi_temp_path {tmp};\n  scgi_temp_path {tmp};\n'
                            f'  include {site};\n}}\n', encoding='utf-8')
            r = subprocess.run([NGINX, '-t', '-c', str(conf), '-p', tmp], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == '__main__':
    unittest.main()
