"""A persistent, bounded journal (AVR-29): the drop-in and its owner-run installer.

Tier 1 pins the drop-in. Tier 2 runs the installer against a simulated host (AVRANA_JOURNALD_ROOT)
with stand-ins for systemctl and journalctl, and with the real systemd-analyze where it exists, so
the configuration precedence is systemd's own ordering, not this file's guess. Nothing here starts
journald or reboots anything: that the journal survives a reboot on the Pi is the owner's test
(docs/runbooks/logs-and-retention.md, "Prove it survives a reboot"), and no test result stands in
for it.
"""
import configparser
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from avrana import REPO_ROOT

CONF = REPO_ROOT / 'deploy' / 'journald' / 'avrana-journald.conf'
SCRIPT = REPO_ROOT / 'deploy' / 'journald' / 'install-persistent-journal.sh'
RUNBOOK = (REPO_ROOT / 'docs' / 'runbooks' / 'logs-and-retention.md').read_text(encoding='utf-8')
RPI_DROPIN = '40-rpi-volatile-storage.conf'
MACHINE_ID = '0123456789abcdef0123456789abcdef'


def journal_section():
    conf = configparser.ConfigParser()
    conf.optionxform = str
    conf.read_string(CONF.read_text(encoding='utf-8'))
    return dict(conf['Journal'])


def posix_bash():
    if os.name != 'nt':
        return shutil.which('bash')
    return os.environ.get('AVRANA_POSIX_BASH')      # Git Bash by explicit path; never WSL's bash.exe


REAL_ANALYZE = shutil.which('systemd-analyze') if os.name == 'posix' else None


class DropIn(unittest.TestCase):
    def test_storage_is_persistent_and_every_bound_is_kept(self):
        self.assertEqual(journal_section(), {
            'Storage': 'persistent', 'SystemMaxUse': '256M', 'SystemKeepFree': '1G',
            'RuntimeMaxUse': '64M', 'MaxFileSec': '1week'})

    def test_the_installed_name_sorts_after_the_raspberry_pi_os_drop_in(self):
        # journald reads drop-ins from /etc, /run and /usr/lib in one list sorted by file name;
        # a later file wins. The installed name must sort after Raspberry Pi OS's.
        installed = 'avrana.conf'
        self.assertIn(f'/etc/systemd/journald.conf.d/{installed}', SCRIPT.read_text(encoding='utf-8'))
        self.assertEqual(sorted([installed, RPI_DROPIN, '10-other.conf', 'syslog.conf']),
                         ['10-other.conf', RPI_DROPIN, installed, 'syslog.conf'])
        self.assertGreater(installed, RPI_DROPIN)

    def test_the_rebuild_inventory_installs_the_same_file_and_flushes(self):
        inventory = (REPO_ROOT / 'deploy' / 'appliance-inventory.json').read_text(encoding='utf-8')
        self.assertIn('"source": "party:deploy/journald/avrana-journald.conf"', inventory)
        self.assertIn('["journalctl", "--flush"]', inventory)

    def test_the_runbook_has_the_procedure_the_tradeoff_and_the_reboot_proof(self):
        for words in ('install-persistent-journal.sh preflight', 'install-persistent-journal.sh install',
                      'install-persistent-journal.sh verify', 'install-persistent-journal.sh rollback',
                      'journalctl --list-boots', 'journalctl -b -1', 'logger -t avrana-journal',
                      'SD-card writes', 'SystemMaxUse', 'NOT RUN'):
            self.assertIn(words, RUNBOOK, words)


# A stand-in for `systemd-analyze cat-config --root=R systemd/journald.conf` where the real one is
# missing (Windows): main file, then drop-ins from etc, run and usr/lib, one per name (etc wins),
# sorted by name. The Linux runs use the real binary instead.
FAKE_ANALYZE = r'''#!/usr/bin/env bash
root=${2#--root=}
[[ $1 == cat-config ]] || exit 1
for f in "$root/etc/systemd/journald.conf" "$root/usr/lib/systemd/journald.conf"; do
  [[ -f $f ]] && { echo "# ${f#$root}"; cat "$f"; break; }
done
declare -A seen
for d in etc run usr/lib; do
  for f in "$root/$d/systemd/journald.conf.d/"*.conf; do
    [[ -f $f ]] || continue
    b=$(basename "$f"); [[ -n ${seen[$b]:-} ]] && continue; seen[$b]=$f
  done
done
for b in $(printf '%s\n' "${!seen[@]}" | LC_ALL=C sort); do
  f=${seen[$b]}; echo; echo "# ${f#$root}"; cat "$f"
done
'''

STUB_SYSTEMCTL = r'''#!/usr/bin/env bash
echo "systemctl $*" >>"$AVRANA_TEST_CALLS"
case $1 in --version) echo 'systemd 257 (stand-in)';; is-active) echo inactive; exit 3;; esac
exit 0
'''

# `journalctl --flush` stands for journald switching to the card: it creates the persistent system
# journal and removes the runtime one under /run. It does not read the configuration itself (the
# script's effective-value check is what is under test); AVRANA_TEST_NO_FLUSH=1 simulates a journald
# that did not switch.
STUB_JOURNALCTL = r'''#!/usr/bin/env bash
echo "journalctl $*" >>"$AVRANA_TEST_CALLS"
case $1 in
  --flush)
    [[ ${AVRANA_TEST_NO_FLUSH:-} == 1 ]] && exit 0
    mid=$(cat "$AVRANA_JOURNALD_ROOT/etc/machine-id")
    mkdir -p "$AVRANA_JOURNALD_ROOT/var/log/journal/$mid"
    : >"$AVRANA_JOURNALD_ROOT/var/log/journal/$mid/system.journal"
    rm -rf "$AVRANA_JOURNALD_ROOT/run/log/journal/$mid";;
  --disk-usage) echo 'Archived and active journals take up 11.4M in the file system.';;
esac
'''


@unittest.skipUnless(posix_bash(), 'needs a POSIX bash (Linux, or AVRANA_POSIX_BASH=Git Bash on Windows)')
class Installer(unittest.TestCase):
    def setUp(self):
        if os.environ.get('AVRANA_REQUIRE_SYSTEMD_ANALYZE') == '1' and not REAL_ANALYZE:
            self.fail('AVRANA_REQUIRE_SYSTEMD_ANALYZE=1 but systemd-analyze is not installed')
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / 'host'
        self.bin = self.tmp / 'bin'
        self.calls = self.tmp / 'calls.log'
        self.bin.mkdir()
        stubs = {'systemctl': STUB_SYSTEMCTL, 'journalctl': STUB_JOURNALCTL}
        if not REAL_ANALYZE:
            stubs['systemd-analyze'] = FAKE_ANALYZE
        for name, body in stubs.items():
            path = self.bin / name
            path.write_text(body, encoding='utf-8', newline='\n')
            path.chmod(0o755)
        # A Raspberry Pi OS host as observed on 2026-10-12: the volatile drop-in, the syslog drop-in,
        # and the size-only avrana.conf installed by AVR-30.
        (self.root / 'etc/systemd/journald.conf.d').mkdir(parents=True)
        (self.root / 'usr/lib/systemd/journald.conf.d').mkdir(parents=True)
        (self.root / 'var').mkdir()
        runtime = self.root / f'run/log/journal/{MACHINE_ID}'          # volatile: this boot's journal is in RAM
        runtime.mkdir(parents=True)
        (runtime / 'system.journal').write_bytes(b'')
        (self.root / 'etc/machine-id').write_text(MACHINE_ID + '\n', encoding='utf-8')
        (self.root / 'etc/systemd/journald.conf').write_text('[Journal]\n#Storage=auto\n#SystemMaxUse=\n', encoding='utf-8')
        (self.root / f'usr/lib/systemd/journald.conf.d/{RPI_DROPIN}').write_text('[Journal]\nStorage=volatile\n', encoding='utf-8')
        (self.root / 'usr/lib/systemd/journald.conf.d/syslog.conf').write_text('[Journal]\nForwardToSyslog=yes\n', encoding='utf-8')
        self.size_only = '[Journal]\nSystemMaxUse=256M\nSystemKeepFree=1G\nRuntimeMaxUse=64M\nMaxFileSec=1week\n'
        self.dest = self.root / 'etc/systemd/journald.conf.d/avrana.conf'
        self.dest.write_text(self.size_only, encoding='utf-8', newline='\n')

    def run_script(self, *args, script=None, **env):
        path = self.bin.as_posix() if os.name != 'nt' else '/' + self.bin.as_posix().replace(':', '', 1)
        full = {**os.environ, 'AVRANA_JOURNALD_ROOT': self.root.as_posix(), 'AVRANA_TEST_CALLS': self.calls.as_posix(), **env}
        script = (script or SCRIPT).as_posix()
        return subprocess.run([posix_bash(), '-c', f'PATH="{path}:$PATH" exec bash "{script}" "$@"', 'x', *args],
                              capture_output=True, text=True, env=full)

    def calls_made(self):
        return self.calls.read_text(encoding='utf-8').splitlines() if self.calls.exists() else []

    def restarts(self):
        return [c for c in self.calls_made() if c == 'systemctl restart systemd-journald']

    def test_preflight_reads_the_volatile_host_and_changes_nothing(self):
        before = self.dest.read_bytes()
        out = self.run_script('preflight')
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn('effective Storage: volatile', out.stdout)
        self.assertIn('differs from this release', out.stdout)
        self.assertLess(out.stdout.index(RPI_DROPIN), out.stdout.index('avrana.conf'))   # systemd's order
        self.assertEqual(self.dest.read_bytes(), before)
        self.assertEqual(self.restarts(), [])

    def test_verify_fails_on_the_volatile_host(self):
        out = self.run_script('verify')
        self.assertNotEqual(out.returncode, 0)
        self.assertIn('NOT OK: effective Storage=volatile', out.stdout)

    def test_install_overrides_the_volatile_drop_in_keeps_a_backup_and_verifies(self):
        out = self.run_script('install')
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertEqual(self.dest.read_bytes(), CONF.read_bytes())
        self.assertIn('ok: effective Storage=persistent', out.stdout)
        self.assertIn('ok: bounded (SystemMaxUse=256M, SystemKeepFree=1G)', out.stdout)
        self.assertEqual(self.restarts(), ['systemctl restart systemd-journald'])
        self.assertIn('journalctl --flush', self.calls_made())
        backups = list((self.root / 'var/backups/avrana-party').glob('journald-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / 'avrana.conf').read_text(encoding='utf-8'), self.size_only)
        # The Raspberry Pi OS file is untouched: the override is by order, not by editing it.
        self.assertEqual((self.root / f'usr/lib/systemd/journald.conf.d/{RPI_DROPIN}').read_text(), '[Journal]\nStorage=volatile\n')

    def test_a_second_install_changes_nothing_and_does_not_restart_journald(self):
        self.assertEqual(self.run_script('install').returncode, 0)
        self.calls.unlink()
        out = self.run_script('install')
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn('Already installed', out.stdout)
        self.assertEqual(self.restarts(), [])
        self.assertEqual(len(list((self.root / 'var/backups/avrana-party').glob('journald-*'))), 1)

    def test_a_failed_verification_puts_the_previous_file_back(self):
        out = self.run_script('install', AVRANA_TEST_NO_FLUSH='1')
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn('Verification failed; putting the previous file back', out.stdout)
        self.assertEqual(self.dest.read_text(encoding='utf-8'), self.size_only)
        self.assertEqual(len(self.restarts()), 2)                       # once to apply, once to restore

    def test_rollback_restores_the_size_only_file_and_deletes_no_log(self):
        self.assertEqual(self.run_script('install').returncode, 0)
        journal = self.root / f'var/log/journal/{MACHINE_ID}/system.journal'
        self.assertTrue(journal.exists())
        out = self.run_script('rollback')
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertEqual(self.dest.read_text(encoding='utf-8'), self.size_only)
        self.assertIn('effective Storage now: volatile', out.stdout)
        self.assertTrue(journal.exists())
        self.assertNotEqual(self.run_script('verify').returncode, 0)

    def test_rollback_after_a_first_install_on_a_host_without_the_file_removes_it(self):
        self.dest.unlink()
        self.assertEqual(self.run_script('install').returncode, 0)
        self.assertEqual(self.run_script('rollback').returncode, 0)
        self.assertFalse(self.dest.exists())

    def test_rollback_without_a_backup_refuses(self):
        out = self.run_script('rollback')
        self.assertEqual(out.returncode, 1)
        self.assertIn('nothing to roll back to', out.stderr)

    def test_a_later_drop_in_that_sets_storage_again_is_caught(self):
        (self.root / 'etc/systemd/journald.conf.d/zz-local.conf').write_text('[Journal]\nStorage=volatile\n', encoding='utf-8')
        out = self.run_script('install')
        self.assertEqual(out.returncode, 1, out.stdout)
        self.assertIn('NOT OK: effective Storage=volatile', out.stdout)
        self.assertEqual(self.dest.read_text(encoding='utf-8'), self.size_only)

    def test_usage_and_a_bad_root_are_refused(self):
        self.assertEqual(self.run_script('nonsense').returncode, 2)
        for root in ('/', '//', '/.', self.tmp.as_posix() + '/missing'):
            self.assertEqual(self.run_script('preflight', AVRANA_JOURNALD_ROOT=root).returncode, 2, root)

    def test_installed_but_never_activated_is_activated_by_install_without_a_backup(self):
        self.dest.write_bytes(CONF.read_bytes())                         # e.g. a rebuild without --activate
        self.assertNotEqual(self.run_script('verify').returncode, 0)     # still writing to /run
        out = self.run_script('install')
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn('has not switched yet', out.stdout)
        self.assertEqual(self.restarts(), ['systemctl restart systemd-journald'])
        self.assertIn('journalctl --flush', self.calls_made())
        self.assertFalse((self.root / 'var/backups/avrana-party').exists())

    def test_a_system_journal_left_from_earlier_does_not_pass_while_journald_is_volatile(self):
        self.dest.write_bytes(CONF.read_bytes())
        old = self.root / f'var/log/journal/{MACHINE_ID}'
        old.mkdir(parents=True)
        (old / 'system.journal').write_bytes(b'')                       # stale; /run still has this boot's
        out = self.run_script('verify')
        self.assertNotEqual(out.returncode, 0)
        self.assertIn('still keeps a runtime journal under /run', out.stdout)

    def test_rollback_steps_back_one_install_at_a_time(self):
        # Two releases of the drop-in installed one after the other, then two rollbacks.
        release = self.tmp / 'release'
        release.mkdir()
        script = release / 'install-persistent-journal.sh'
        shutil.copy(SCRIPT, script)
        shutil.copy(CONF, release / 'avrana-journald.conf')
        self.assertEqual(self.run_script('install', script=script).returncode, 0)
        v1 = (release / 'avrana-journald.conf').read_bytes()
        (release / 'avrana-journald.conf').write_bytes(v1 + b'# a later release' + bytes([10]))
        out = self.run_script('install', script=script)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        first = self.run_script('rollback', script=script)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(self.dest.read_bytes(), v1)
        self.assertIn('effective Storage now: persistent', first.stdout)   # said as it is, not "volatile"
        second = self.run_script('rollback', script=script)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(self.dest.read_text(encoding='utf-8'), self.size_only)
        self.assertIn('effective Storage now: volatile', second.stdout)
        third = self.run_script('rollback', script=script)
        self.assertEqual(third.returncode, 1)
        self.assertIn('nothing to roll back to', third.stderr)


if __name__ == '__main__':
    unittest.main()
