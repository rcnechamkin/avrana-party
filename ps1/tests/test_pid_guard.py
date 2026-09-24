"""tools/ps1-pid.sh and stop-ps1.sh must only ever act on a PROVEN PS1 RetroArch, never on
a stale or recycled PID (e.g. the live arcade's RetroArch, which has the same name).
Uses fake processes whose comm is "retroarch" in a temp AVRANA_PS1_HOME: no emulator, no
display, no load. Linux only (needs /proc); skips elsewhere.
  python3 ps1/tests/test_pid_guard.py"""
import os, subprocess, sys, tempfile, time

if not sys.platform.startswith('linux'):
    print('pid guard test skipped (needs Linux /proc)'); sys.exit(0)

PS1 = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
PID_TOOL, STOP = os.path.join(PS1, 'tools', 'ps1-pid.sh'), os.path.join(PS1, 'stop-ps1.sh')
home = tempfile.mkdtemp(prefix='ps1-guard-')
run = os.path.join(home, 'runtime'); os.makedirs(run)
env = dict(os.environ, AVRANA_PS1_HOME=home)
# A script's comm is its file name, so this process is "retroarch" to /proc and pgrep.
fake = os.path.join(home, 'retroarch')
with open(fake, 'w') as f:
    f.write('#!/bin/sh\nwhile :; do sleep 1; done\n')
os.chmod(fake, 0o755)
procs = []

def spawn(cfg, display=':77', xauth='/tmp/xauth-fake', cmd=None):
    p = subprocess.Popen(cmd or [fake, '-c', cfg], env=dict(env, DISPLAY=display, XAUTHORITY=xauth))
    procs.append(p); time.sleep(0.2); return p

def record(pid, line=None):
    if line is None:
        line = subprocess.run([PID_TOOL, '--record', str(pid)], env=env, capture_output=True,
                              text=True, check=True).stdout
    with open(os.path.join(run, 'retroarch.pid'), 'w') as f:
        f.write(line)

def files(display=':77', xauth='/tmp/xauth-fake'):
    for name, val in (('display', display), ('xauthority', xauth)):
        with open(os.path.join(run, name), 'w') as f:
            f.write(val + '\n')

def check(expect_rc, what):
    r = subprocess.run([PID_TOOL], env=env, capture_output=True, text=True)
    assert r.returncode == expect_rc, f'{what}: rc={r.returncode} want {expect_rc} ({r.stderr.strip()})'
    return r.stdout.strip()

def stop(expect_rc, what):
    r = subprocess.run([STOP], env=env, capture_output=True, text=True)
    assert r.returncode == expect_rc, f'{what}: stop rc={r.returncode} want {expect_rc} ({r.stderr.strip()})'

try:
    ours_cfg = os.path.join(run, 'retroarch.cfg')
    arcade = spawn('/home/cody/avrana-party/arcade/retroarch.cfg')   # the live arcade's twin
    boot = open('/proc/sys/kernel/random/boot_id').read().strip()
    start = subprocess.run([PID_TOOL, '--record', str(arcade.pid)], env=env, capture_output=True,
                           text=True).stdout.split()[1]

    check(1, 'no pid file'); stop(0, 'no pid file')
    files()
    record(arcade.pid);                                   check(2, 'arcade RetroArch (other cfg)')
    stop(1, 'arcade RetroArch');                          assert arcade.poll() is None, 'arcade was signalled!'
    record(arcade.pid, f'{arcade.pid}\n');                check(2, 'old one-field pid file')
    stop(1, 'old pid file');                              assert arcade.poll() is None, 'arcade was signalled!'
    record(arcade.pid, f'{arcade.pid} {start} not-this-boot\n'); check(1, 'pid file from another boot')
    stop(0, 'other boot');                                assert arcade.poll() is None, 'arcade was signalled!'
    record(arcade.pid, f'{arcade.pid} 1 {boot}\n');       check(1, 'recycled PID (start time differs)')
    stop(0, 'recycled PID');                              assert arcade.poll() is None, 'arcade was signalled!'
    record(arcade.pid, '* * *\n');                        check(2, 'glob characters are not expanded')
    record(arcade.pid, 'x 1 y\n');                        check(2, 'malformed pid file')

    other = spawn(None, cmd=['sleep', '30']); record(other.pid)
    check(2, 'process not named retroarch');              stop(1, 'not retroarch')
    assert other.poll() is None, 'non-retroarch process was signalled!'

    ps1 = spawn(ours_cfg); record(ps1.pid)
    assert check(0, 'genuine PS1 RetroArch') == str(ps1.pid)
    files(display=':99');                                 check(2, 'runtime/display is not its DISPLAY')
    files(xauth='/tmp/other');                            check(2, 'runtime/xauthority is not its XAUTHORITY')
    files();                                              check(0, 'files match again')
    os.remove(os.path.join(run, 'display')); os.remove(os.path.join(run, 'xauthority'))
    check(0, 'no display files (KMS mode)')
    files()
    stop(0, 'genuine PS1');                               ps1.wait(5)
    check(1, 'recorded PS1 RetroArch has exited')
    assert arcade.poll() is None, 'arcade was signalled!'
    print('pid guard OK')
finally:
    for p in procs:
        if p.poll() is None:
            p.kill(); p.wait()
