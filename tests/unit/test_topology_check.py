"""tools/avrana-topology-check: the games runtime listener block (AVR-272).

The script only runs on the appliance and is never run here. Its :8096 block is cut out between
its two marker comments and run under bash with `ss`, `ip` and `curl` replaced by shell functions,
so the decision it makes (loopback only; no answer on the Wi-Fi or management address) is tested
without a network. Whether the stand-ins print what the real tools print is not tested."""
import os
import shutil
import subprocess
import unittest

from avrana import REPO_ROOT

SCRIPT = REPO_ROOT / 'tools/avrana-topology-check'
TEXT = SCRIPT.read_text(encoding='utf-8')
START, END = '# -- games runtime listener (AVR-272) --\n', '# -- end games runtime listener --\n'
BASH = shutil.which('bash')

PRELUDE = r"""
set -u
F=0; ADDR=10.42.0.1
pass(){ echo "PASS $*"; }; fail(){ echo "FAIL $*"; F=$((F+1)); }; warn(){ echo "WARN $*"; }
ss(){ printf '%s' "$LISTENERS"; }
ip(){ echo "2: eth0    inet 10.0.0.142/24 brd 10.0.0.255 scope global eth0"; }
curl(){ local url=${!#}; case " $ANSWERS " in *" $url "*) return ${CURL_RC:-0};; *) return ${REFUSED_RC:-7};; esac; }
"""


def listener(address):
    return f'LISTEN 0      128    {address}:8096       0.0.0.0:*\n'


class Text(unittest.TestCase):
    def test_the_block_is_there_once_and_before_the_exit(self):
        self.assertEqual((TEXT.count(START), TEXT.count(END)), (1, 1))
        self.assertLess(TEXT.index(START), TEXT.index(END))
        self.assertLess(TEXT.index(END), TEXT.rindex('exit $(('))

    def test_it_stays_read_only(self):
        block = TEXT[TEXT.index(START):TEXT.index(END)]
        for word in ('sudo', 'systemctl', 'nft ', 'kill', ' -X ', '--data', ' -d '):
            self.assertNotIn(word, block)


@unittest.skipUnless(os.name == 'posix' and BASH, 'needs bash')
class Block(unittest.TestCase):
    def run_block(self, listeners, answers='', **more):
        block = TEXT[TEXT.index(START):TEXT.index(END)]
        env = dict(os.environ, LISTENERS=listeners, ANSWERS=answers, **more)
        r = subprocess.run([BASH, '-c', PRELUDE + block + '\necho "FAILS $F"\n'], env=env, text=True,
                           capture_output=True, timeout=30)
        self.assertEqual((r.returncode, r.stderr), (0, ''))
        return r.stdout.splitlines()

    def test_the_whole_script_parses(self):
        r = subprocess.run([BASH, '-n', str(SCRIPT)], capture_output=True, text=True, timeout=30)
        self.assertEqual((r.returncode, r.stderr), (0, ''))

    def test_loopback_only_passes(self):
        for listeners in (listener('127.0.0.1'), listener('127.0.0.1') + listener('[::1]')):
            out = self.run_block(listeners)
            self.assertEqual(out, ['PASS games runtime (:8096) listens on loopback only',
                                   'PASS games runtime does not answer on 10.42.0.1:8096',
                                   'PASS games runtime does not answer on 10.0.0.142:8096',
                                   'FAILS 0'])

    def test_the_deployed_all_interfaces_listener_fails_three_times(self):
        """What the appliance did on 2026-10-03: 0.0.0.0:8096, reachable on both addresses."""
        out = self.run_block(listener('0.0.0.0'), 'http://10.42.0.1:8096/ http://10.0.0.142:8096/')
        self.assertEqual(out, ['FAIL games runtime (:8096) listens on 0.0.0.0 (must be loopback only)',
                               'FAIL games runtime answers on 10.42.0.1:8096 (reachable from the LAN; curl exit 0)',
                               'FAIL games runtime answers on 10.0.0.142:8096 (reachable from the LAN; curl exit 0)',
                               'FAILS 3'])

    def test_an_accepted_connection_without_an_http_answer_is_still_reachable(self):
        """curl 52 (empty reply) and 56 (reset) mean the port accepted; only 7 proves it did not."""
        for rc in ('52', '56', '22'):
            out = self.run_block(listener('127.0.0.1'), 'http://10.42.0.1:8096/', CURL_RC=rc)
            self.assertEqual(out[1], f'FAIL games runtime answers on 10.42.0.1:8096 (reachable from the LAN; curl exit {rc})')
            self.assertEqual(out[-1], 'FAILS 1')
        out = self.run_block(listener('127.0.0.1'), REFUSED_RC='28')            # a timeout proves nothing
        self.assertEqual(out[1:], ['WARN games runtime probe on 10.42.0.1:8096 timed out (not proven unreachable; run again)',
                                   'WARN games runtime probe on 10.0.0.142:8096 timed out (not proven unreachable; run again)',
                                   'FAILS 0'])

    def test_any_other_address_fails(self):
        for address in ('*', '[::]', '10.42.0.1', '10.0.0.142'):
            out = self.run_block(listener('127.0.0.1') + listener(address))
            self.assertEqual(out[0], f'FAIL games runtime (:8096) listens on {address} (must be loopback only)')
            self.assertEqual(out[-1], 'FAILS 1')

    def test_one_reachable_address_is_one_failure(self):
        out = self.run_block(listener('127.0.0.1'), 'http://10.0.0.142:8096/')
        self.assertEqual(out[1:], ['PASS games runtime does not answer on 10.42.0.1:8096',
                                   'FAIL games runtime answers on 10.0.0.142:8096 (reachable from the LAN; curl exit 0)',
                                   'FAILS 1'])

    def test_no_listener_is_a_warning_not_a_failure(self):
        out = self.run_block('')
        self.assertEqual(out[0], 'WARN nothing listens on :8096 (games runtime not running?)')
        self.assertEqual(out[-1], 'FAILS 0')


if __name__ == '__main__':
    unittest.main()
