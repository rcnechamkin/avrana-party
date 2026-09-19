"""Install the two portal files, preserving originals and rolling back on failure."""
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess

base = Path(__file__).resolve().parent
pairs = [
    (base / 'portal/index.html', Path('/var/www/avrana-portal/index.html')),
    (base / 'avrana-party.nginx', Path('/etc/nginx/sites-available/avrana-party')),
]
backup = base / 'backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
backup.mkdir()
for source, target in pairs:
    shutil.copy2(target, backup / target.name)
print(f'Backup: {backup}', flush=True)
try:
    for source, target in pairs:
        shutil.copyfile(source, target)
    subprocess.run(['nginx', '-t'], check=True)
    subprocess.run(['systemctl', 'reload', 'nginx'], check=True)
except BaseException:
    for source, target in pairs:
        shutil.copy2(backup / target.name, target)
    subprocess.run(['nginx', '-t'], check=True)
    subprocess.run(['systemctl', 'reload', 'nginx'], check=True)
    raise
print('Portal installed; nginx reloaded. Network and game services untouched.')
