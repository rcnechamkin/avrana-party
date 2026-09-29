"""Every persistent log and telemetry file the appliance writes has a bound (AVR-30).

Tier 1 pins the retention files to what they must cover. Tier 2 runs the real logrotate on the
telemetry rule (skipped where logrotate is not installed, e.g. Windows, unless
AVRANA_REQUIRE_LOGROTATE=1, which CI sets); the arcade's own stats log
rotation is tests/unit/test_arcade_stream.py ClientStatsLog. The inventory and disk-pressure notes
are docs/runbooks/logs-and-retention.md.
"""
import configparser
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from avrana import REPO_ROOT

ROTATE = (REPO_ROOT / 'telemetry' / 'avrana-telemetry.logrotate').read_text(encoding='utf-8')
JOURNALD = REPO_ROOT / 'deploy' / 'journald' / 'avrana-journald.conf'
INSTALLER = (REPO_ROOT / 'telemetry' / 'install-pi-throttle-check.sh').read_text(encoding='utf-8')
SERVICE = (REPO_ROOT / 'telemetry' / 'pi-throttle-check.service').read_text(encoding='utf-8')
RUNBOOK = (REPO_ROOT / 'docs' / 'runbooks' / 'logs-and-retention.md').read_text(encoding='utf-8')
LOGROTATE = shutil.which('logrotate') or ('/usr/sbin/logrotate' if os.path.exists('/usr/sbin/logrotate') else None)


def rules(text):
    body = '\n'.join(line for line in text.splitlines() if not line.strip().startswith('#'))
    return re.findall(r'^(\S+)\s*\{(.*?)^\}', body, re.M | re.S)


class Retention(unittest.TestCase):
    def test_telemetry_rule_covers_exactly_the_sampler_output(self):
        (path, body), = rules(ROTATE)
        target = re.search(r'--append\s+(\S+)', SERVICE).group(1)
        self.assertEqual(path, target)                    # the file the timer appends to
        self.assertNotIn('*', path)                       # never baseline.jsonl or other evidence
        directives = {line.split()[0]: line.split()[1:] for line in body.strip().splitlines()}
        self.assertEqual(directives['rotate'], ['8'])
        self.assertEqual(directives['maxsize'], ['10M'])
        self.assertIn('compress', directives)
        self.assertIn('missingok', directives)
        self.assertNotIn('copytruncate', directives)       # the sampler reopens with >> each run

    def test_installer_installs_the_rule(self):
        self.assertIn('install -m 0644 "$SCRIPT_DIR/avrana-telemetry.logrotate" /etc/logrotate.d/avrana-telemetry',
                      INSTALLER)

    def test_journald_caps_are_explicit(self):
        conf = configparser.ConfigParser()
        conf.optionxform = str
        conf.read_string(JOURNALD.read_text(encoding='utf-8'))
        journal = dict(conf['Journal'])
        self.assertEqual(set(journal), {'SystemMaxUse', 'SystemKeepFree', 'RuntimeMaxUse', 'MaxFileSec'})
        self.assertNotIn('Storage', journal)               # persistence is AVR-29's decision
        self.assertRegex(journal['SystemMaxUse'], r'^\d+M$')

    def test_runbook_lists_every_bounded_source(self):
        for name in ('pi-throttle.jsonl', 'client-stats.jsonl', 'emulator.log', 'webrtc-stats-sample',
                     'pulse.log', 'chatmedia', 'avatars', 'devices.json', 'journal', 'nginx'):
            self.assertIn(name, RUNBOOK, name)


@unittest.skipUnless((LOGROTATE and os.name == 'posix') or os.environ.get('AVRANA_REQUIRE_LOGROTATE') == '1',
                     'logrotate is not installed')
class RealLogrotate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.log = self.tmp / 'pi-throttle.jsonl'
        # The rule as shipped, pointed at a temp file; `create` without an owner (not root here).
        conf = (ROTATE.replace('/var/log/avrana/pi-throttle.jsonl', str(self.log))
                .replace('create 0644 root root', 'create 0644'))
        (self.tmp / 'rule.conf').write_text(conf, encoding='utf-8')

    def run_logrotate(self):
        return subprocess.run([LOGROTATE, '-s', str(self.tmp / 'state'), str(self.tmp / 'rule.conf')],
                              capture_output=True, text=True)

    def test_past_maxsize_it_rotates_and_the_sampler_can_append_again(self):
        self.log.write_bytes(b'{"t":0}\n' * (11 * 1024 * 1024 // 8))
        r = self.run_logrotate()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.tmp / 'pi-throttle.jsonl.1').exists())
        self.assertEqual(self.log.stat().st_size, 0)       # recreated, empty
        with self.log.open('a') as f:                      # what the sampler's >> does
            f.write('{"t":1}\n')
        self.assertEqual(self.log.read_text(), '{"t":1}\n')

    def test_a_small_file_is_left_alone(self):
        self.log.write_text('{"t":0}\n')
        self.assertEqual(self.run_logrotate().returncode, 0)
        self.assertFalse((self.tmp / 'pi-throttle.jsonl.1').exists())


if __name__ == '__main__':
    unittest.main()
