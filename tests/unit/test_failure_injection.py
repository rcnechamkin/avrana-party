"""Failure injection with real processes (AVR-33): Party Core and games die, hang and come back.

TIER: T2-process. Party Core runs as its own OS process (`python -m avrana.party.service`, the
production entry point) and every game is its own OS process (tests/fixtures/failure/game_process.py),
all on loopback. Kills are real (Popen.kill: SIGKILL on Linux), a freeze is SIGSTOP (POSIX only),
and a hang is a process that accepts connections and never answers.

SYNTHETIC, said plainly: the game processes are stand-ins that speak the real session protocol, not
BLUFF, the Games server or the arcade (the arcade's slot is the same stand-in with the arcade's game
id and a short link timeout). Nothing here is systemd: restarts are this file starting the process
again, as `Restart=` would. Appliance recovery (units, nginx, the network) is the owner's
(docs/runbooks/service-recovery.md); none of it is proven here.

What every scenario checks besides its own point: Party Core keeps answering other phones quickly
while a game is dead or silent, the host keeps authority, and no session is left orphaned at a game
once the host starts again.

Known limitations these tests pin (owner decisions, not bugs to fix here; see the session-probe
proposal, docs/design/proposals/2026-10-12-session-probe.md section 5):
  * with close_lost_game off (the default), a game that restarted keeps the party "active" and
    refuses every Party ticket until the host ends the round: followers bounce between Party Home
    and the game (GameProcessDies.test_a_restarted_game_...);
  * the lost-game check is a TCP connect, so a game that is wedged but still listening is never
    counted as lost (LostGameCheck.test_a_wedged_game_...).
"""
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from avrana.party import core, protocol, sessions

from test_party_service import HOST, ORIGIN, Phone

REPO = Path(__file__).resolve().parents[2]
GAME_PROCESS = REPO / 'tests' / 'fixtures' / 'failure' / 'game_process.py'
QUICK = 1.0                 # s: a state read while a game is failing must stay this fast
ARCADE_TIMEOUT = 6          # s: the arcade's link timeout here (25 on the appliance, the same code path)
END_BOUND = sessions.END_LINK_TIMEOUT + 3.0


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def wait_for(predicate, timeout, what):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError(f'timed out waiting for {what}')


def answers(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.2):
            return True
    except OSError:
        return False


class GameProc:
    """One stand-in game process. `restart()` is a crash and a new process: it holds no session."""

    def __init__(self, tmp, game, key_file):
        self.game, self.key_file, self.port = game, key_file, free_port()
        self.hang_file = Path(tmp) / f'{game}.hang'
        self.proc = None

    def start(self):
        self.proc = subprocess.Popen([sys.executable, str(GAME_PROCESS), '--port', str(self.port), '--key-file',
                                      str(self.key_file), '--game', self.game, '--hang-file', str(self.hang_file)],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.proc.stdout.readline()                                  # 'ready' once bound
        wait_for(lambda: answers(self.port), 10, f'{self.game} to listen')

    def kill(self):
        if self.proc and self.proc.poll() is None:
            if os.name == 'posix':
                os.kill(self.proc.pid, signal.SIGCONT)               # a frozen process dies too
            self.proc.kill()
            self.proc.wait(timeout=10)
        if self.proc and self.proc.stdout:
            self.proc.stdout.close()

    def restart(self):
        self.kill()
        self.start()

    def hang(self, on=True):
        if on:
            self.hang_file.write_text('wedged')
        elif self.hang_file.exists():
            self.hang_file.unlink()

    def signal(self, sig):
        os.kill(self.proc.pid, sig)

    def _req(self, method, path, body=None):
        import http.client
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        conn.request(method, path, body=json.dumps(body).encode() if body is not None else None,
                     headers={'Content-Type': 'application/json'})
        r = conn.getresponse()
        out = json.loads(r.read() or b'{}')
        conn.close()
        return r.status, out

    def held(self):
        return self._req('GET', '/__test__/held')[1]['sid']

    def hello(self, ticket):
        """A phone arriving with a Party ticket: (accepted, refusal reason)."""
        status, out = self._req('POST', '/__test__/hello', {'ticket': ticket})
        return status == 200, out.get('reason')


class PartyProc:
    """Party Core as the appliance runs it, from its own config file; the device store is a file, so
    cookies survive a restart and the party (memory-only, ADR 0006) does not."""

    def __init__(self, tmp, games, close_lost_game):
        self.tmp, self.port = Path(tmp), free_port()
        self.config = self.tmp / 'party-core.json'
        self.config.write_text(json.dumps({
            'hosts': [HOST], 'origins': [ORIGIN], 'secure_cookie': True,
            'devices': str(self.tmp / 'devices.json'),
            'session_recovery': {'close_lost_game': close_lost_game},
            'games': games,
        }), encoding='utf-8')
        self.log = open(self.tmp / 'party-core.log', 'ab')
        self.proc = None

    def start(self):
        self.proc = subprocess.Popen([sys.executable, '-m', 'avrana.party.service', '--config', str(self.config),
                                      '--port', str(self.port)], cwd=str(REPO), stdout=self.log, stderr=self.log)
        wait_for(lambda: self.proc.poll() is None and answers(self.port), 15, 'Party Core to listen')

    def kill(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=10)

    def threads(self):
        """Party Core's thread count (Linux), or None."""
        try:
            for line in Path(f'/proc/{self.proc.pid}/status').read_text().splitlines():
                if line.startswith('Threads:'):
                    return int(line.split()[1])
        except OSError:
            return None
        return None


class Rig(unittest.TestCase):
    close_lost_game = False

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='avr33-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        key = protocol.new_key()
        games = {}
        self.games = {}
        for game, extra in (('bluff', {}), ('arcade-gauntlet2', {'timeout': ARCADE_TIMEOUT})):
            key_file = Path(self.tmp) / f'{game}.key'
            protocol.write_key(str(key_file), key)
            g = GameProc(self.tmp, game, key_file)
            self.games[game] = g
            self.addCleanup(g.kill)
            self.addCleanup(g.hang, False)
            games[game] = {'url': f'http://127.0.0.1:{g.port}', 'key_file': str(key_file), **extra}
        for g in self.games.values():
            g.start()
        self.party = PartyProc(self.tmp, games, self.close_lost_game)
        self.addCleanup(self.party.log.close)
        self.addCleanup(self.party.kill)
        self.party.start()
        self.phones = {name: Phone(self.party.port) for name in ('Ana', 'Ben', 'Cat')}
        for name, phone in self.phones.items():
            status, _, _ = phone.post('join', {'name': name})
            self.assertEqual(status, 200)

    # ---- what phones do and see ---------------------------------------------------------------------
    def view(self, name):
        status, v, _ = self.phones[name].state()
        self.assertEqual(status, 200)
        return v

    def quick(self, name='Ben'):
        """A state read is answered within QUICK seconds; returns the view."""
        started = time.monotonic()
        v = self.view(name)
        took = time.monotonic() - started
        self.assertLess(took, QUICK, f'{name} waited {took:.2f}s for /party/api/state')
        return v

    def seen(self, name):
        v = self.view(name)
        s = v['session'] or {}
        return v['state'], v['location']['at'], v['nav']['to'], s.get('state'), s.get('outcome'), s.get('reason')

    def host(self):
        return next(m['name'] for m in self.view('Ben')['members'] if m['host'])

    def act(self, name, path, body=None):
        v = self.view(name)
        return self.phones[name].post(path, {**(body or {}), 'if_version': v['version']})

    def launch(self, game='bluff', name='Ana'):
        """The host's Start, through the game's pregame when it has one (BLUFF does, AVR-129):
        everyone chooses Play, then the host starts the round. Returns the host's last answer."""
        status, v, _ = self.act(name, 'session/launch', {'game': game})
        if status == 200 and v['state'] == 'setup':
            for member in self.phones.values():
                self.assertEqual(member.post('session/choice', {'choice': 'player'})[0], 200)
            status, v, _ = self.act(name, 'session/start')
        return status, v

    def launched(self, game='bluff'):
        status, v = self.launch(game)
        self.assertEqual((status, v['state']), (200, 'active'), v)
        return v['session']['id']

    def ticket(self, name, game='bluff'):
        return self.phones[name].post('session/ticket', {'game': game})

    def timed(self, fn):
        started = time.monotonic()
        out = fn()
        return out, time.monotonic() - started

    def while_running(self, fn, probe_every=0.3):
        """Run a host action on a thread; meanwhile Ben's state reads must stay quick. Returns the
        action's result and how long it took."""
        box = {}

        def run():
            box['out'], box['took'] = self.timed(fn)

        t = threading.Thread(target=run, daemon=True)
        t.start()
        reads = 0
        while t.is_alive():
            self.quick('Ben')
            reads += 1
            t.join(probe_every)
        self.assertNotIn('error', box, box)
        return box['out'], box['took'], reads

    def everyone_home(self):
        for name in self.phones:
            state, at, nav, *_ = self.seen(name)
            self.assertEqual((state, at, nav), ('lobby', 'home', 'home'), name)


class GameProcessDies(Rig):
    """A game process is killed during play, and comes back or not. close_lost_game off (the default)."""

    def test_a_killed_game_leaves_party_core_responsive_and_the_host_recovers_the_party(self):
        sid = self.launched()
        self.games['bluff'].kill()
        self.assertEqual(self.quick()['state'], 'active')                   # Party Core cannot tell yet
        status, _, _ = self.ticket('Ben')
        self.assertEqual(status, 200)                                       # still sends phones there
        (status, v, _), took = self.timed(lambda: self.act('Ana', 'session/end'))
        self.assertEqual(status, 200)
        self.assertLess(took, END_BOUND)
        self.everyone_home()
        self.assertEqual(self.host(), 'Ana')
        # Start while the game is still down fails cleanly: home, a reason, nothing left launching.
        status, v = self.launch()
        self.assertEqual(status, 200)
        self.assertEqual((v['state'], v['session']['state']), ('lobby', 'ended'), v)
        self.assertTrue(v['session'].get('detail'))
        # The game comes back (systemd's Restart=): the next Start works and the game holds only it.
        self.games['bluff'].start()
        new = self.launched()
        self.assertNotEqual(new, sid)
        self.assertEqual(self.games['bluff'].held(), new)

    def test_a_restarted_game_refuses_party_tickets_until_the_host_ends_the_round(self):
        """KNOWN LIMITATION (owner decision): the party still says active and nav still says game,
        while the restarted game refuses each ticket: the follower bounce. The host's End is the way
        out; with close_lost_game on a dead game is closed, but a restarted one answers."""
        self.launched()
        self.games['bluff'].restart()
        for name in ('Ben', 'Cat'):
            status, body, _ = self.ticket(name)
            self.assertEqual(status, 200)
            self.assertEqual(self.games['bluff'].hello(body['ticket']), (False, 'session'))
            self.assertEqual(self.seen(name)[:3], ('active', 'game', 'game'))
        status, _, _ = self.act('Ana', 'session/end')
        self.assertEqual(status, 200)
        self.everyone_home()
        self.assertEqual(self.ticket('Ben')[0], 409)                        # no ticket for an ended round


class Unresponsive(Rig):
    """A game that accepts connections and never answers: a wedged runtime."""

    def test_a_wedged_game_never_holds_up_other_phones_and_the_hosts_end_is_bounded(self):
        old = self.launched()
        self.games['bluff'].hang()
        (status, v, _), took, reads = self.while_running(lambda: self.act('Ana', 'session/end'))
        self.assertEqual(status, 200)
        self.assertLess(took, END_BOUND)
        self.assertGreater(reads, 1)
        self.everyone_home()                                                 # home before the game answered
        # The game wakes and handles the End that waited for it: nothing is left orphaned there.
        self.games['bluff'].hang(False)
        wait_for(lambda: self.games['bluff'].held() is None, 10, 'the late End to land')
        new = self.launched()
        self.assertNotEqual(new, old)
        self.assertEqual(self.games['bluff'].held(), new)

    @unittest.skipUnless(os.name == 'posix', 'SIGSTOP is POSIX')
    def test_a_frozen_game_process_sigstop_is_the_same(self):
        self.launched()
        self.games['bluff'].signal(signal.SIGSTOP)
        try:
            (status, _, _), took, _ = self.while_running(lambda: self.act('Ana', 'session/end'))
        finally:
            self.games['bluff'].signal(signal.SIGCONT)
        self.assertEqual(status, 200)
        self.assertLess(took, END_BOUND)
        self.everyone_home()

    def test_a_wedged_arcade_fails_its_start_within_its_timeout_and_is_told_to_end(self):
        """The arcade slot (its own game id and link timeout). A Start that times out goes home with
        a reason, and the runtime is told to end (AVR-134), so it holds nothing once it wakes."""
        arcade = self.games['arcade-gauntlet2']
        arcade.hang()
        threading.Timer(ARCADE_TIMEOUT + 2.0, arcade.hang, args=(False,)).start()   # wakes after the link gave up
        (status, v), took, _ = self.while_running(lambda: self.launch('arcade-gauntlet2'))
        self.assertEqual(status, 200)
        self.assertLess(took, ARCADE_TIMEOUT + END_BOUND)
        self.assertEqual((v['state'], v['session']['state']), ('lobby', 'ended'), v)
        wait_for(lambda: not arcade.hang_file.exists(), 10, 'the arcade to wake')
        wait_for(lambda: arcade.held() is None, 15, 'the arcade to hold no session')
        self.everyone_home()


class DependencyUnavailable(Rig):
    def test_a_game_down_at_start_fails_cleanly_and_a_delayed_recovery_starts_normally(self):
        self.games['bluff'].kill()
        (status, v), took = self.timed(self.launch)
        self.assertEqual(status, 200)
        self.assertLess(took, END_BOUND)
        self.assertEqual((v['state'], v['session']['state']), ('lobby', 'ended'), v)
        self.quick()
        time.sleep(1.0)                                                     # the service comes back later
        self.games['bluff'].start()
        sid = self.launched()
        self.assertEqual(self.games['bluff'].held(), sid)
        status, body, _ = self.ticket('Ben')
        self.assertEqual(self.games['bluff'].hello(body['ticket']), (True, None))


class RepeatedFailures(Rig):
    def test_five_crash_and_restart_cycles_leave_one_host_one_session_and_no_thread_growth(self):
        before = self.party.threads()
        sids, versions = [], []
        for _ in range(5):
            sids.append(self.launched())
            self.games['bluff'].restart()
            status, v, _ = self.act('Ana', 'session/end')
            self.assertEqual(status, 200)
            versions.append(v['version'])
            self.everyone_home()
            self.assertEqual(self.host(), 'Ana')
        last = self.launched()
        self.assertEqual(len(set(sids + [last])), 6)
        self.assertEqual(versions, sorted(versions))
        self.assertEqual(self.games['bluff'].held(), last)
        after = self.party.threads()
        if before is not None:
            self.assertLessEqual(after, before + 4, (before, after))

    def test_starts_against_a_crash_looping_game_each_fail_cleanly(self):
        self.games['bluff'].kill()
        for _ in range(5):
            status, v = self.launch()
            self.assertEqual(status, 200)
            self.assertEqual(v['state'], 'lobby', v)
            self.quick()
        self.everyone_home()
        self.assertEqual(self.host(), 'Ana')


class PartyCoreDies(Rig):
    def test_a_killed_party_core_comes_back_clean_and_the_next_start_replaces_the_games_orphan(self):
        old = self.launched()
        stale = self.view('Ana')['version']
        self.party.kill()
        self.party.start()                                                  # systemd's Restart=
        v = self.view('Ben')
        self.assertIsNone(v['me'])                                          # the party is memory-only
        # The old host's request against the old party is refused, not applied.
        status, _, _ = self.phones['Ana'].post('session/end', {'if_version': stale})
        self.assertNotEqual(status, 200)
        for name in ('Ben', 'Ana', 'Cat'):                                  # Ben rejoins first: host
            self.assertEqual(self.phones[name].post('join', {'name': name})[0], 200)
        self.assertEqual(self.host(), 'Ben')
        self.assertEqual(self.games['bluff'].held(), old)                   # the game's orphan
        status, v = self.launch(name='Ben')
        self.assertEqual((status, v['state']), (200, 'active'), v)
        self.assertEqual(self.games['bluff'].held(), v['session']['id'])


class LostGameCheck(Rig):
    """close_lost_game on (C-08 decides whether the appliance turns it on)."""
    close_lost_game = True

    def poll_tickets(self, seconds, name='Ben'):
        """A follower asking for a ticket about every 2 s, as bouncing phones do; returns the last view."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.ticket(name)
            v = self.quick(name)
            if v['state'] != 'active':
                return v
            time.sleep(2.1)
        return self.view(name)

    def test_a_killed_game_is_closed_for_everyone_after_a_few_misses(self):
        self.launched()
        self.games['bluff'].kill()
        v = self.poll_tickets(20)
        self.assertEqual((v['state'], v['session']['outcome'], v['session']['reason']), ('lobby', 'abandoned', 'game_lost'), v)
        self.everyone_home()
        self.assertEqual(self.host(), 'Ana')

    def test_a_wedged_game_that_still_listens_is_never_counted_as_lost(self):
        """KNOWN GAP (contract decision): the check is a TCP connect, which a wedged process still
        accepts. Ticket requests stay quick (one check at a time, outside the lock); the host's End
        remains the way out."""
        self.launched()
        self.games['bluff'].hang()
        v = self.poll_tickets(12)
        self.assertEqual(v['state'], 'active')
        (status, _, _), took, _ = self.while_running(lambda: self.act('Ana', 'session/end'))
        self.assertEqual(status, 200)
        self.assertLess(took, END_BOUND)
        self.everyone_home()


if __name__ == '__main__':
    unittest.main()
