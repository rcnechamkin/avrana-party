"""The game origin's repository pieces other than the nginx site file (AVR-319): the local DNS
record, the certificate scripts, the party-core.json check and the runbook's commands.

The nginx block has its own tests (test_nginx_site.py, real nginx on Linux CI). Nothing here
touches an appliance: it reads the committed files and runs the scripts' syntax and the
certificate-name check on throwaway certificates."""
import contextlib
import io
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from avrana import REPO_ROOT
from avrana.contracts import party_config

CAPTIVE = (REPO_ROOT / 'avrana-captive.conf').read_text(encoding='utf-8')
RUNBOOK = REPO_ROOT / 'docs/runbooks/game-origin.md'
EXAMPLE = json.loads((REPO_ROOT / 'deploy/party-core/party-core.example.json').read_text(encoding='utf-8'))
BASH = shutil.which('bash')
OPENSSL = shutil.which('openssl')


class LocalDns(unittest.TestCase):
    def test_both_names_resolve_to_the_appliance_address_and_only_there(self):
        records = dict(re.findall(r'^host-record=([^,\s]+),(\S+)$', CAPTIVE, re.M))
        self.assertEqual(records, {'party.avrana.net': '10.42.0.1', 'games.avrana.net': '10.42.0.1'})
        # the record is a host-record: an exact name, not an address=/domain/ rule that would also
        # capture every name below it
        self.assertNotRegex(CAPTIVE, r'address=/(party|games)\.avrana\.net/')

    def test_the_installer_copies_the_file_whole_and_names_no_host_itself(self):
        script = (REPO_ROOT / 'install-captive-dns.py').read_text(encoding='utf-8')
        self.assertIn("source = base / 'avrana-captive.conf'", script)
        self.assertNotIn('avrana.net', script)

    @unittest.skipUnless(shutil.which('dnsmasq'), 'dnsmasq is not installed')
    def test_dnsmasq_accepts_the_file(self):
        subprocess.run(['dnsmasq', '--test', '--conf-file=' + str(REPO_ROOT / 'avrana-captive.conf')],
                       check=True, capture_output=True)


class CertificateScripts(unittest.TestCase):
    renew = (REPO_ROOT / 'ops/renew-party-certificate.sh').read_text(encoding='utf-8')
    install = (REPO_ROOT / 'ops/install-party-certificate.sh').read_text(encoding='utf-8')

    def code(self, text):
        return '\n'.join(l for l in text.splitlines() if not l.lstrip().startswith('#'))

    def cert(self, path, sans):
        subprocess.run([OPENSSL, 'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:prime256v1',
                        '-nodes', '-days', '1', '-subj', '/CN=party.avrana.net', '-addext', 'subjectAltName=' + sans,
                        '-keyout', str(path) + '.key', '-out', str(path)], check=True, capture_output=True)

    def renew_run(self, installed, fresh=None):
        """The real renewal script on a scratch tree, with stand-ins for lego and the installer that
        record what they were given. `installed` is the SANs of /etc/avrana-party/tls/current."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'current').mkdir()
            (root / 'state/certificates').mkdir(parents=True)
            nl = chr(10)
            (root / 'cloudflare.env').write_text(nl.join(['CF_DNS_API_TOKEN=x', 'ACME_EMAIL=a@example.net', '']))
            self.cert(root / 'current/fullchain.pem', installed)
            self.cert(root / 'state/certificates/party.avrana.net.crt', fresh or installed)
            (root / 'lego').write_text(nl.join(['#!/usr/bin/env bash', 'echo "$@" > ' + (root / 'lego.args').as_posix(), '']))
            (root / 'install-party-certificate.sh').write_text(nl.join([
                '#!/usr/bin/env bash', 'echo "require=${AVRANA_REQUIRE_GAME_NAME:-}" > ' + (root / 'install.env').as_posix(), '']))
            for stub in ('lego', 'install-party-certificate.sh'):
                (root / stub).chmod(0o755)
            text = (self.renew
                    .replace('credentials=/etc/avrana-party/cloudflare.env', 'credentials=' + (root / 'cloudflare.env').as_posix())
                    .replace('lego=/usr/local/bin/lego', 'lego=' + (root / 'lego').as_posix())
                    .replace('state=/var/lib/avrana-party/lego', 'state=' + (root / 'state').as_posix())
                    .replace('current=/etc/avrana-party/tls/current', 'current=' + (root / 'current').as_posix()))
            self.assertEqual(text.count(root.as_posix()), 4)
            (root / 'renew.sh').write_text(text)
            run = subprocess.run([BASH, str(root / 'renew.sh')], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            return ((root / 'lego.args').read_text().split(), (root / 'install.env').read_text().strip())

    @unittest.skipUnless(BASH and OPENSSL, 'bash and openssl are needed')
    def test_a_one_name_appliance_renews_exactly_as_before(self):
        args, installer = self.renew_run('DNS:party.avrana.net')
        self.assertEqual(re.findall(r'--domains (\S+)', ' '.join(args)), ['party.avrana.net'])
        self.assertEqual(installer, 'require=')

    @unittest.skipUnless(BASH and OPENSSL, 'bash and openssl are needed')
    def test_a_two_name_appliance_asks_for_both_names_and_makes_the_installer_require_them(self):
        args, installer = self.renew_run('DNS:party.avrana.net,DNS:games.avrana.net')
        self.assertEqual(re.findall(r'--domains (\S+)', ' '.join(args)), ['party.avrana.net', 'games.avrana.net'])
        self.assertEqual(installer, 'require=1')

    def test_a_renewal_that_comes_back_without_the_name_is_refused_before_anything_changes(self):
        """The installer is what refuses it (the renewal script exports the requirement, above): its
        name check comes before the first write, so `current` is not touched."""
        code = self.code(self.install)
        self.assertLess(code.index('AVRANA_REQUIRE_GAME_NAME'), code.index('install -d'))
        self.assertLess(code.index('AVRANA_REQUIRE_GAME_NAME'), code.index('mv -Tf'))

    def test_the_installer_requires_the_party_name_and_only_notes_a_missing_game_name(self):
        code = self.code(self.install)
        self.assertLess(code.index('-checkhost party.avrana.net'), code.index('-checkhost games.avrana.net'))
        self.assertRegex(code, r"AVRANA_REQUIRE_GAME_NAME:-\} == 1 \]\];\s+then\s+echo 'Certificate does not name games.avrana.net' >&2\s+exit 1")
        self.assertIn('Note: this certificate does not name games.avrana.net', code)
        self.assertIn('set -euo pipefail', code)

    @unittest.skipUnless(BASH, 'bash is not installed')
    def test_the_scripts_parse(self):
        for name in ('renew-party-certificate.sh', 'install-party-certificate.sh'):
            subprocess.run([BASH, '-n', str(REPO_ROOT / 'ops' / name)], check=True)

    @unittest.skipUnless(OPENSSL, 'openssl is not installed')
    def test_the_name_check_tells_a_one_name_certificate_from_a_two_name_one(self):
        """The exact pipeline the installer runs, on throwaway certificates."""
        line = re.search(r'^if ! (openssl x509 .*grep -q .does match.); then$', self.install, re.M).group(1)
        with tempfile.TemporaryDirectory() as tmp:
            for sans, covered in (('DNS:party.avrana.net', False),
                                  ('DNS:party.avrana.net,DNS:games.avrana.net', True)):
                subprocess.run([OPENSSL, 'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:prime256v1',
                                '-nodes', '-days', '1', '-subj', '/CN=party.avrana.net',
                                '-addext', 'subjectAltName=' + sans, '-keyout', f'{tmp}/k.pem', '-out', f'{tmp}/c.pem'],
                               check=True, capture_output=True)
                found = subprocess.run([OPENSSL, 'x509', '-in', f'{tmp}/c.pem', '-noout', '-checkhost',
                                        'games.avrana.net'], capture_output=True, text=True).stdout
                self.assertEqual('does match' in found, covered, found)
        self.assertIn('-checkhost games.avrana.net', line)


class PartyCoreGameOrigins(unittest.TestCase):
    BASE = {'hosts': ['party.avrana.net'], 'origins': ['https://party.avrana.net']}

    def problems(self, **extra):
        return party_config.check_game_origins(dict(self.BASE, **extra))

    def test_the_game_origin_of_the_runbook_is_accepted(self):
        self.assertEqual(self.problems(game_origins={'https://games.avrana.net': ['checkers']}), [])
        self.assertEqual(self.problems(game_origins={'https://games.avrana.net': '*'}), [])
        self.assertEqual(self.problems(), [])                      # none configured: no game has a game origin

    def test_what_party_core_would_refuse_or_misread_is_named(self):
        for bad in (['https://games.avrana.net'],                  # a list: the natural mistake
                    {'https://games.avrana.net/': ['checkers']}, {'https://Games.avrana.net': ['checkers']},
                    {'games.avrana.net': ['checkers']}, {'https://games.avrana.net': []},
                    {'https://games.avrana.net': ['Checkers']}, {'https://games.avrana.net': 'checkers'},
                    {'https://party.avrana.net': ['checkers']}, {'https://games.avrana.net:443': ['checkers']}):
            self.assertTrue(self.problems(game_origins=bad), bad)

    def test_check_fails_on_a_bad_game_origin_and_passes_on_a_good_one(self):
        def run(conf):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'party-core.json'
                path.write_text(json.dumps(conf))
                err = io.StringIO()
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                    return party_config.main(['--check', str(path)]), err.getvalue()
        good = dict(EXAMPLE, game_origins={'https://games.avrana.net': ['checkers']})
        self.assertEqual(run(good), (0, ''))
        code, err = run(dict(EXAMPLE, game_origins=['https://games.avrana.net']))
        self.assertEqual(code, 1)
        self.assertIn('game_origins: an object', err)

    def test_the_example_config_has_no_game_origin_until_an_owner_sets_one(self):
        """A fresh install must not send phones to a host that has no certificate name yet."""
        self.assertNotIn('game_origins', EXAMPLE)

    def test_provision_game_keeps_telling_games_the_party_origin(self):
        from avrana.ops import provision_game
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'party-core.json'
            path.write_text(json.dumps(dict(EXAMPLE, game_origins={'https://games.avrana.net': ['checkers']})))
            self.assertEqual(provision_game.party_origin(str(path)), 'https://party.avrana.net')


class Runbook(unittest.TestCase):
    text = RUNBOOK.read_text(encoding='utf-8') if RUNBOOK.exists() else ''

    def test_it_exists_is_proposed_and_says_it_was_not_run(self):
        self.assertTrue(self.text)
        self.assertRegex(self.text, r'(?m)^Status: \*\*PROPOSED[^\n]*NOT RUN on the appliance')

    def test_its_party_core_snippet_passes_the_check_it_tells_the_owner_to_run(self):
        block = re.search(r'```json\n(.*?)```', self.text, re.S).group(1)
        conf = json.loads(block)
        self.assertEqual(party_config.check_game_origins(dict(EXAMPLE, **conf)), [])
        self.assertEqual(list(conf), ['game_origins'])

    def test_every_script_it_names_exists_and_the_two_sites_it_installs_are_identical(self):
        for rel in sorted(set(re.findall(r'\b((?:ops|deploy|docs)/[A-Za-z0-9_./-]+\.(?:sh|py|md|conf|nginx))\b', self.text))):
            self.assertTrue((REPO_ROOT / rel).exists(), rel)
        self.assertEqual((REPO_ROOT / 'avrana-party.nginx').read_bytes(), (REPO_ROOT / 'arcade/nginx-site').read_bytes())

    def test_it_is_linked_from_the_documents_that_used_to_say_the_origin_was_not_deployable(self):
        for rel in ('docs/runbooks/prepare-native-games.md', 'docs/runbooks/provision-game.md',
                    'docs/design/BROWSER-ORIGINS.md', 'docs/README.md'):
            self.assertIn('game-origin.md', (REPO_ROOT / rel).read_text(encoding='utf-8'), rel)
        self.assertIn('docs/runbooks/game-origin.md', (REPO_ROOT / 'docs/manifest.json').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
