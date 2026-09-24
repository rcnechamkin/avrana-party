from pathlib import Path
from datetime import datetime, timezone
import os
import shutil
import subprocess

# The NetworkManager profile that runs the party AP. Since 2026-09-24 the AP is the Pi's internal
# Wi-Fi (wlan0) in profile "Avrana Party Internal"; the old USB-adapter profile "Avrana Party"
# (wlan1) is kept only as a disabled leftover. Override with AVRANA_AP_PROFILE if it changes.
AP_PROFILE = os.environ.get('AVRANA_AP_PROFILE', 'Avrana Party Internal')

base = Path(__file__).resolve().parent
source = base / 'avrana-captive.conf'
target = Path('/etc/NetworkManager/dnsmasq-shared.d/avrana-captive.conf')
subprocess.run(['dnsmasq', '--test', '--conf-file=' + str(source)], check=True)
active = subprocess.run(['nmcli', '-g', 'GENERAL.STATE', 'connection', 'show', AP_PROFILE],
                        capture_output=True, text=True)
if active.returncode != 0 or 'activated' not in active.stdout:
    raise SystemExit(f'AP profile {AP_PROFILE!r} is not active; nothing changed')
backup = base / 'backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
backup.mkdir(parents=True)
shutil.copy2(target, backup / target.name)
print('Backup:', backup, flush=True)
try:
    shutil.copyfile(source, target)
    subprocess.run(['dnsmasq', '--test', '--conf-file=/dev/null',
                    '--conf-dir=/etc/NetworkManager/dnsmasq-shared.d'], check=True)
    subprocess.run(['nmcli', '--wait', '20', 'connection', 'down', AP_PROFILE], check=True)
    subprocess.run(['nmcli', '--wait', '30', 'connection', 'up', AP_PROFILE], check=True)
except BaseException:
    shutil.copy2(backup / target.name, target)
    subprocess.run(['nmcli', '--wait', '20', 'connection', 'down', AP_PROFILE])
    subprocess.run(['nmcli', '--wait', '30', 'connection', 'up', AP_PROFILE], check=True)
    raise
