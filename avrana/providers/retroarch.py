"""RuntimeProvider for RetroArch, extracted from arcade/stream.py.

RetroArch (GPL-3.0) runs as a separate child process: Avrana passes it a config, a pinned
libretro core and the content path, and never links to it. Its network command interface stays
off (it would listen on every interface without authentication); control goes through the
process lifecycle only. Cores, ROMs and BIOS files are never in this repository.
"""
from pathlib import Path
import shutil
import subprocess

from avrana.providers.base import ProviderInfo

INFO = ProviderInfo(
    id='retroarch', kind='runtime', offers=('runtime.retroarch',),
    implementation='RetroArch (GPL-3.0) as a child process; pinned libretro core (license per core)')


# The directories RetroArch writes to, by config key, as names under the service's runtime directory.
WRITABLE = {'system_directory': 'system', 'savefile_directory': 'saves',
            'savestate_directory': 'saves', 'screenshot_directory': 'screenshots'}


def write_config(base, core_options, runtime):
    """<runtime>/retroarch.cfg: the committed config plus where this run may write.

    The committed config holds no paths: the service runs from a read-only release as a user
    with no home, so every writable location is under its runtime directory (the unit's state
    directory, or arcade/runtime for a hand-run prototype). The committed core options are
    copied there on every start, so the repository stays their source and RetroArch, which
    rewrites that file, never touches the release. Returns the path to pass as `-c`."""
    base, core_options, runtime = Path(base), Path(core_options), Path(runtime)
    for name in sorted(set(WRITABLE.values())):
        (runtime / name).mkdir(parents=True, exist_ok=True)
    options = runtime / core_options.name
    shutil.copyfile(core_options, options)
    lines = [f'{key} = "{runtime / name}"' for key, name in WRITABLE.items()]
    lines.append(f'core_options_path = "{options}"')
    text = base.read_text(encoding='utf-8')
    out = runtime / base.name
    out.write_text(text + ('' if text.endswith('\n') else '\n') + '\n'.join(lines) + '\n', encoding='utf-8')
    return out


class RetroArchRuntime:
    info = INFO

    def __init__(self, *, config, core, content, executable='retroarch', verbose=True, popen=subprocess.Popen,
                 prepare=None):
        self.config = config
        self.prepare = prepare      # called before each start; returns the config path to use
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
        if self.prepare is not None:
            self.config = self.prepare()
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
