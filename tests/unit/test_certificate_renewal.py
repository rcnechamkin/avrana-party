"""Automatic certificate renewal as the repository ships it (AVR-31): the tracked units, the
renewal and install scripts, and the expiry record that lets health see a root-only certificate.

Tier 1. systemd is never started and lego never runs here: that the timer fires, that lego renews
and that nginx reloads on the appliance is the owner's checklist (docs/runbooks/party-https.md,
'Automatic renewal: enable, verify, recover'), not something this file proves."""
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from avrana.ops import status

ROOT = Path(__file__).resolve().parents[2]


def text(path):
    return (ROOT / path).read_text(encoding='utf-8')


class TrackedUnits(unittest.TestCase):
    def test_the_service_runs_the_installed_renewal_script_as_a_bounded_oneshot(self):
        unit = text('ops/avrana-party-certificate.service')
        self.assertRegex(unit, r'(?m)^Type=oneshot$')
        self.assertRegex(unit, r'(?m)^ExecStart=/usr/local/libexec/avrana-party/renew-party-certificate\.sh$')
        self.assertRegex(unit, r'(?m)^TimeoutStartSec=\d+min$')      # a hung lego ends and shows as failed
        self.assertNotRegex(unit, r'(?m)^User=')                     # root: it writes /etc/avrana-party/tls (ADR 0016)

    def test_the_timer_is_daily_catches_up_after_downtime_and_targets_the_service(self):
        unit = text('ops/avrana-party-certificate.timer')
        self.assertRegex(unit, r'(?m)^OnCalendar=\*-\*-\* \d\d:\d\d:\d\d$')
        self.assertRegex(unit, r'(?m)^Persistent=true$')             # an off appliance renews on the next boot
        self.assertRegex(unit, r'(?m)^RandomizedDelaySec=')
        self.assertRegex(unit, r'(?m)^Unit=avrana-party-certificate\.service$')
        self.assertRegex(unit, r'(?m)^WantedBy=timers\.target$')

    def test_status_treats_only_the_timer_as_optional_and_watches_it(self):
        self.assertIn('avrana-party-certificate.timer', status.DEFAULT_CONFIG['units'])
        self.assertEqual(status.DEFAULT_CONFIG['optional_units'], ['avrana-party-certificate.timer'])


class Scripts(unittest.TestCase):
    def test_a_failed_lego_or_install_fails_the_unit_and_never_touches_current(self):
        renew = text('ops/renew-party-certificate.sh')
        self.assertIn('set -euo pipefail', renew)
        lego = renew.index('renew --days 30')
        install = renew.index('install-party-certificate.sh')
        self.assertLess(lego, install)                               # lego first; its failure stops here (set -e)
        for line in renew.splitlines():
            if 'lego' in line and 'renew --days' in line or 'install-party-certificate.sh' in line:
                self.assertNotIn('|| true', line)
        self.assertNotIn('current', renew[lego:install].replace('"$current/fullchain.pem"', ''))

    def test_the_installer_validates_before_switching_and_restores_on_a_bad_nginx(self):
        install = text('ops/install-party-certificate.sh')
        order = [install.index(s) for s in ('-checkhost party.avrana.net', '-checkend', 'openssl verify',
                                            'Certificate and private key do not match',
                                            'mv -Tf "$next_link" "$current"',
                                            'nginx -t', 'systemctl reload nginx')]
        self.assertEqual(order, sorted(order))
        self.assertIn('previous certificate restored', install)
        self.assertIn('Certificate is already installed', install)   # idempotent: a second run changes nothing

    def test_both_installer_exits_that_succeed_write_the_expiry_record(self):
        install = text('ops/install-party-certificate.sh')
        self.assertIn(f"expiry_record={status.CERTIFICATE_RECORD}", install)
        self.assertEqual(install.count('record_expiry "$certificate"'), 2)
        self.assertLess(install.rindex('record_expiry "$certificate"'), install.index('Installed certificate release'))
        self.assertGreater(install.index('systemctl reload nginx'), install.index('record_expiry() {'))


def _git_bash():
    if os.name != 'nt':
        return shutil.which('bash')
    # Windows has WSL's bash.exe on PATH, which is not a shell to trust here: Git Bash only by name.
    return os.environ.get('AVRANA_POSIX_BASH')


@unittest.skipUnless(_git_bash() and shutil.which('openssl'), 'needs a POSIX bash and openssl (Linux CI)')
class ExpiryRecord(unittest.TestCase):
    """The shell function itself, with a real certificate, in a scratch directory."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:prime256v1',
                        '-nodes', '-days', '30', '-subj', '/CN=party.avrana.net',
                        '-keyout', str(self.dir / 'k.pem'), '-out', str(self.dir / 'c.pem')],
                       check=True, capture_output=True)
        src = text('ops/install-party-certificate.sh')
        self.function = re.search(r'^record_expiry\(\) \{.*?^\}$', src, re.M | re.S).group(0)

    def run_function(self, record):
        script = (f'expiry_record={Path(record).as_posix()}\n{self.function}\n'
                  f'record_expiry {(self.dir / "c.pem").as_posix()}\necho exit=$?')
        return subprocess.run([_git_bash(), '-c', script], capture_output=True, text=True)

    def test_the_record_is_what_status_reads_and_is_world_readable(self):
        record = self.dir / 'certificate-not-after'
        out = self.run_function(record)
        self.assertIn('exit=0', out.stdout, out.stderr)
        if os.name != 'nt':
            self.assertEqual(record.stat().st_mode & 0o777, 0o644)
        self.assertFalse(list(self.dir.glob('certificate-not-after.next.*')))
        got = status.Probes(certificate_record=str(record)).certificate_not_after(str(self.dir / 'missing.pem'))
        self.assertAlmostEqual(got.timestamp(), datetime.now(timezone.utc).timestamp() + 30 * 86400, delta=3 * 86400)
        self.assertNotIn('PRIVATE', record.read_text())

    def test_an_unwritable_record_is_reported_and_does_not_fail_the_install(self):
        out = self.run_function(self.dir / 'no-such-directory' / 'certificate-not-after')
        self.assertIn('exit=0', out.stdout)
        self.assertIn('expiry record could not be written', out.stderr)


if __name__ == '__main__':
    unittest.main()
