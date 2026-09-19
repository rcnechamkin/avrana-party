"""Install the isolated prototype, preserving the existing nginx site."""
from pathlib import Path
from datetime import datetime, timezone
import shutil
import subprocess

base = Path(__file__).resolve().parent
target = Path('/etc/nginx/sites-available/avrana-party')
backup = base.parent / 'backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
backup.mkdir()
shutil.copy2(target, backup / 'avrana-party')
print('nginx backup:', backup, flush=True)
shutil.copyfile(base / 'nginx-site', target)
try:
    subprocess.run(['nginx', '-t'], check=True)
    subprocess.run(['systemctl', 'reload', 'nginx'], check=True)
except BaseException:
    shutil.copy2(backup / 'avrana-party', target)
    subprocess.run(['nginx', '-t'], check=True)
    subprocess.run(['systemctl', 'reload', 'nginx'], check=True)
    raise
shutil.copyfile(base / 'avrana-uinput.conf', '/etc/modules-load.d/avrana-uinput.conf')
shutil.copyfile(base / 'avranaparty-arcade.service', '/etc/systemd/system/avranaparty-arcade.service')
subprocess.run(['systemctl', 'daemon-reload'], check=True)
subprocess.run(['systemctl', 'enable', '--now', 'avranaparty-arcade.service'], check=True)
shutil.copyfile(base / 'nginx-site', base.parent / 'avrana-party.nginx')
