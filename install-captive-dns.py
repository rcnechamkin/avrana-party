from pathlib import Path
from datetime import datetime, timezone
import shutil
import subprocess

base = Path(__file__).resolve().parent
source = base / 'avrana-captive.conf'
target = Path('/etc/NetworkManager/dnsmasq-shared.d/avrana-captive.conf')
subprocess.run(['dnsmasq', '--test', '--conf-file=' + str(source)], check=True)
backup = base / 'backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
backup.mkdir()
shutil.copy2(target, backup / target.name)
print('Backup:', backup, flush=True)
try:
    shutil.copyfile(source, target)
    subprocess.run(['dnsmasq', '--test', '--conf-file=/dev/null',
                    '--conf-dir=/etc/NetworkManager/dnsmasq-shared.d'], check=True)
    subprocess.run(['nmcli', '--wait', '20', 'connection', 'down', 'Avrana Party'], check=True)
    subprocess.run(['nmcli', '--wait', '30', 'connection', 'up', 'Avrana Party'], check=True)
except BaseException:
    shutil.copy2(backup / target.name, target)
    subprocess.run(['nmcli', '--wait', '20', 'connection', 'down', 'Avrana Party'])
    subprocess.run(['nmcli', '--wait', '30', 'connection', 'up', 'Avrana Party'], check=True)
    raise
