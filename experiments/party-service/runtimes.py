"""Launchers for 'service' games (manifest runtime.start = "service"): a process the party starts
when the host picks the game, waits for, routes to, and stops when the game ends. Dev only.

One runtime at a time (one appliance = one party = one emulator). The party service asks for the
game it wants (`want`); this module never decides policy. Stdlib only.

PS1: `stream_ps1.py <profile> --host 127.0.0.1 --port P --capture WxH` from a PS1 checkout. It
binds its port only after RetroArch and the encoder are up, so "the port answers" = ready. The
front door proxies exactly two paths to it (the page and its WebSocket), never /stats.
"""
import ctypes
import http.client
import os
import queue
import signal
import subprocess
import sys
import threading
import time

READY_TIMEOUT_S = 60.0
STOP_TIMEOUT_S = 15.0
PROFILE_ALLOWED = 'abcdefghijklmnopqrstuvwxyz0123456789_-'


def _die_with_parent():
    """The runtime must not outlive the party service (Linux; a no-op elsewhere)."""
    try:
        ctypes.CDLL('libc.so.6', use_errno=True).prctl(1, signal.SIGTERM)   # PR_SET_PDEATHSIG
    except OSError:
        pass


class Runtime:
    """One managed process. `command(game)` builds its argv; `prefix(game)` is its public path."""
    base = '/runtime/'                           # every public path of this runtime starts here

    def __init__(self, port, log_dir=None, ready_timeout=READY_TIMEOUT_S):
        self.port = port
        self.log_dir = log_dir
        self.ready_timeout = ready_timeout
        self.lock = threading.Lock()
        self.proc = None
        self.game_id = None
        self.ready = False
        self.stopping = False
        # Every spawn and stop runs on this one long-lived thread: the kernel's parent-death signal
        # (PR_SET_PDEATHSIG) fires when the SPAWNING THREAD exits, so spawning from a short-lived
        # thread would kill the emulator at once. It also serialises start/stop.
        self.jobs = queue.Queue()
        threading.Thread(target=self._worker, daemon=True, name=f'runtime-{port}').start()

    def _worker(self):
        while True:
            fn, done = self.jobs.get()
            try:
                fn()
            except Exception as e:                 # a failed job must not kill the worker
                print('runtime:', type(e).__name__, e, flush=True)
            finally:
                done.set()

    def _call(self, fn):
        if threading.current_thread().name == f'runtime-{self.port}':
            return fn()
        done = threading.Event()
        self.jobs.put((fn, done))
        done.wait()

    # subclasses
    def handles(self, game):
        raise NotImplementedError

    def command(self, game):
        raise NotImplementedError

    def prefix(self, game):
        return game['href']

    def upstream_path(self, rest):
        """Map the path after the prefix to the runtime's own path, or None to refuse it."""
        raise NotImplementedError

    # lifecycle
    def start(self, game, on_ready, on_fail):
        """Start `game` (stopping any other first); exactly one of on_ready() / on_fail(reason) is
        called later, unless stop() cancelled it first (then neither). Blocks while stopping."""
        self._call(lambda: self._start(game, on_ready, on_fail))

    def _start(self, game, on_ready, on_fail):
        self._stop(None)
        error = None
        with self.lock:
            log = None
            if self.log_dir:
                os.makedirs(self.log_dir, exist_ok=True)
                log = open(os.path.join(self.log_dir, f"{game['id']}.log"), 'w')
            kw = dict(stdout=log or subprocess.DEVNULL, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
            if sys.platform != 'win32':
                kw.update(start_new_session=True, preexec_fn=_die_with_parent)
            try:
                self.proc = subprocess.Popen(self.command(game), **kw)
                self.game_id, self.ready, self.stopping = game['id'], False, False
                self._prefix = self.prefix(game)
                proc = self.proc
            except (OSError, ValueError) as e:
                error = f'could not start: {getattr(e, "strerror", None) or e}'
            finally:
                if log:
                    log.close()
        if error:                                # callbacks never run under this lock
            return on_fail(error)
        threading.Thread(target=self._wait_ready, args=(proc, game['id'], on_ready, on_fail), daemon=True).start()

    def _answers(self):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=1)
        try:
            c.request('GET', '/')
            return c.getresponse().status == 200
        except OSError:
            return False
        finally:
            c.close()

    def _wait_ready(self, proc, game_id, on_ready, on_fail):
        deadline = time.monotonic() + self.ready_timeout
        while time.monotonic() < deadline:
            with self.lock:
                if self.proc is not proc or self.stopping:
                    return                                     # cancelled: the caller already knows
            if proc.poll() is not None:
                with self.lock:
                    if self.proc is proc:
                        self.proc, self.game_id = None, None
                return on_fail(f'exited during start (code {proc.returncode})')
            if self._answers():
                with self.lock:
                    if self.proc is not proc or self.stopping:
                        return
                    self.ready = True
                return on_ready()
            time.sleep(0.25)
        with self.lock:
            if self.proc is not proc or self.stopping:
                return
        self.stop(game_id)
        on_fail(f'not ready after {int(self.ready_timeout)} s')

    def running(self):
        """(game_id, ready) of the live process, or (None, False)."""
        with self.lock:
            if self.proc is None or self.proc.poll() is not None:
                return None, False
            return self.game_id, self.ready

    def crashed(self, game_id):
        """True once if the READY runtime for `game_id` exited on its own."""
        with self.lock:
            if (self.proc is not None and self.game_id == game_id and self.ready and not self.stopping
                    and self.proc.poll() is not None):
                self.proc, self.game_id, self.ready = None, None, False
                return True
            return False

    def stop(self, only=None):
        """Stop the runtime (blocking, up to STOP_TIMEOUT_S). With `only`, stop it only while it
        still runs that game, so a late stop can never kill the game started after it."""
        self._call(lambda: self._stop(only))

    def _stop(self, only):
        with self.lock:
            if only is not None and self.game_id != only:
                return
            proc, self.stopping = self.proc, True
            self.proc, self.game_id, self.ready = None, None, False
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()                     # stream_ps1.py stops RetroArch, Xvfb, Pulse itself
            proc.wait(STOP_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            if sys.platform != 'win32':
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
            proc.wait()

    def route(self, path):
        """('127.0.0.1', port, upstream_path) when `path` belongs to the ready runtime; None when
        it isn't this runtime's; 'unavailable' when it is but the game isn't running/ready."""
        prefix = getattr(self, '_prefix', None)
        game_id, ready = self.running()
        if not path.startswith(self.base):
            return None
        if not (prefix and game_id and ready and path.startswith(prefix)):
            return 'unavailable'
        rest = path[len(prefix):]
        up = self.upstream_path(rest)
        return ('127.0.0.1', self.port, up) if up is not None else 'unavailable'


class PS1Runtime(Runtime):
    base = '/ps1/'

    def __init__(self, ps1_dir, port=8198, capture='320x240', python=sys.executable, **kw):
        super().__init__(port, **kw)
        self.ps1_dir, self.capture, self.python = ps1_dir, capture, python

    def handles(self, game):
        rt = game.get('runtime') or {}
        return rt.get('type') == 'emulator_profile' and game.get('href', '').startswith(self.base)

    def command(self, game):
        profile = game['runtime']['profile']
        if not profile or any(ch not in PROFILE_ALLOWED for ch in profile):
            raise ValueError(f'bad profile {profile!r}')
        return [self.python, '-X', 'faulthandler', os.path.join(self.ps1_dir, 'stream_ps1.py'), profile,
                '--host', '127.0.0.1', '--port', str(self.port), '--capture', self.capture]

    def upstream_path(self, rest):
        path, _, query = rest.partition('?')
        if path == '':
            return '/'                           # the phone page
        if path == 'ws' and not query:
            return '/ws'                         # its WebSocket (the token travels in the hello)
        return None                              # never /stats or anything else
