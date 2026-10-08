"""Generic disposable native process for provider tests; never a systemd substitute.

The parent owns a listening Unix socket, as socket activation does. A child gets fd 3 and the
runtime command from its appliance grant. No game imports, title-specific launcher or TCP game
listener. This proves subprocess/socket integration only, never systemd isolation.
"""
import atexit
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading

from avrana.contracts import appliance, vocabulary
from avrana.party import protocol, sessions

LAUNCHER = """import os, sys
os.dup2(int(sys.argv[1]), 3); os.set_inheritable(3, True)
os.environ.update(LISTEN_PID=str(os.getpid()), LISTEN_FDS='1')
os.execv(sys.argv[2], sys.argv[2:])
"""


class NativeRuntime:
    def __init__(self, platform, games, slug, party_origin):
        if os.name != 'posix' or not hasattr(socket, 'AF_UNIX'):
            raise RuntimeError('native provider tests require POSIX Unix sockets')
        profile = appliance.load(Path(platform) / 'contracts/appliances/avrana-pi4.json', vocabulary.load())
        grant = appliance.grants(profile)[slug]
        runtime = grant['runtime']
        # The test checkout stands in for the owner-installed root-owned Games release.
        self.command = [sys.executable, *runtime['command'][1:]]
        self.games, self.slug = Path(games), slug
        self.tmp = tempfile.TemporaryDirectory(prefix='avn-', dir='/tmp')
        self.path = str(Path(self.tmp.name) / 'game.sock')
        self.party_path = str(Path(self.tmp.name) / 'party.sock')
        keys = Path(self.tmp.name) / 'keys'
        keys.mkdir()
        self.key = protocol.new_key()
        protocol.write_key(str(keys / f'{slug}.key'), self.key)
        self.env = dict(os.environ, AVRANA_PARTY_KEYS=str(keys), AVRANA_PARTY_SOCKET=self.party_path,
                        AVRANA_PARTY_ORIGIN=party_origin, PYTHONDONTWRITEBYTECODE='1')
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.bind(self.path)
        self.socket.listen(128)
        self.proc = None
        self.lock = threading.RLock()
        self.closed = False
        atexit.register(self.close)

    @property
    def endpoint(self):
        return sessions.GameEndpoint(self.slug, sessions.unix_base(self.slug), self.key, socket_path=self.path)

    def start(self):
        with self.lock:
            if self.closed:
                raise RuntimeError('native runtime is closed')
            if self.proc is None or self.proc.poll() is not None:
                self.proc = subprocess.Popen(
                    [sys.executable, '-c', LAUNCHER, str(self.socket.fileno()), *self.command],
                    pass_fds=(self.socket.fileno(),), env=self.env, cwd=self.games,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def request(self, method, target, body=None, headers=None, timeout=35):
        self.start()
        conn = sessions.UnixHTTPConnection(self.path, timeout)
        try:
            conn.request(method, target, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, response.getheaders(), response.read()
        finally:
            conn.close()

    def stop_process(self):
        with self.lock:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait(timeout=5)

    def close(self):
        with self.lock:
            if self.closed:
                return
            # Serialize with activation so teardown cannot leave a new orphan child behind.
            self.closed = True
            self.stop_process()
            self.socket.close()
            self.tmp.cleanup()


class ActivatedLink(sessions.HttpGameLink):
    """Emulate socket activation before any normal Party request to this test socket."""
    def __init__(self, endpoints, runtime):
        super().__init__(endpoints)
        self.runtime = runtime

    def _post(self, url, message, timeout=None, socket_path=None):
        if socket_path == self.runtime.path:
            self.runtime.start()
        return super()._post(url, message, timeout=timeout, socket_path=socket_path)
