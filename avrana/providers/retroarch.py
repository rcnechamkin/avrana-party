"""RuntimeProvider for RetroArch, extracted from arcade/stream.py.

RetroArch (GPL-3.0) runs as a separate child process: Avrana passes it a config, a pinned
libretro core and the content path, and never links to it. Its network command interface stays
off (it would listen on every interface without authentication); control goes through the
process lifecycle only. Cores, ROMs and BIOS files are never in this repository.
"""
import subprocess

from avrana.providers.base import ProviderInfo

INFO = ProviderInfo(
    id='retroarch', kind='runtime', offers=('runtime.retroarch',),
    implementation='RetroArch (GPL-3.0) as a child process; pinned libretro core (license per core)')


class RetroArchRuntime:
    info = INFO

    def __init__(self, *, config, core, content, executable='retroarch', verbose=True, popen=subprocess.Popen):
        self.config = config
        self.core = core
        self.content = content
        self.executable = executable
        self.verbose = verbose
        self._popen = popen
        self.process = None

    def command(self):
        cmd = [self.executable]
        if self.verbose:
            cmd.append('-v')
        return cmd + ['-c', str(self.config), '-L', str(self.core), str(self.content)]

    def start(self, *, stdout=None, stderr=subprocess.STDOUT):
        if self.running():
            raise RuntimeError('RetroArch is already running')
        self.process = self._popen(self.command(), stdout=stdout, stderr=stderr)
        return self.process

    def running(self):
        return self.process is not None and self.process.poll() is None

    def stop(self, timeout=5.0):
        """terminate, wait up to `timeout`, then kill: the arcade's shutdown, unchanged."""
        proc = self.process
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    def status(self):
        proc = self.process
        return {**self.info.describe(), 'running': self.running(),
                'exitCode': None if proc is None else proc.poll()}
