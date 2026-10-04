#!/usr/bin/env python3
"""Audit supplied gaunt2 archive against the inspected MAME 2010 driver."""
import hashlib
import json
import os
from pathlib import Path
import re
from zipfile import ZipFile

root = Path(__file__).resolve().parent
source = root / 'evidence/mame2010-gauntlet.c'
rom = Path('/srv/avrana/roms/arcade/gaunt2.zip')
block = source.read_text().split('ROM_START( gaunt2 )', 1)[1].split('ROM_END', 1)[0]
entries = []
for line in block.splitlines():
    match = re.search(r'ROM_LOAD\w*\(\s*"([^"]+)"\s*,\s*0x[0-9a-f]+\s*,\s*(0x[0-9a-f]+)\s*,\s*CRC\((\w+)\) SHA1\((\w+)\)', line)
    if match:
        name, size, crc, sha1 = match.groups()
        entries.append(dict(name=name, size=int(size, 16), crc=crc, sha1=sha1))
    elif 'ROM_CONTINUE' in line:
        size = re.search(r'ROM_CONTINUE\(\s*0x[0-9a-f]+\s*,\s*(0x[0-9a-f]+)', line)
        entries[-1]['size'] += int(size[1], 16)
assert len(entries) == 26, 'Unexpected driver definition; inspect before proceeding'
with ZipFile(rom) as archive:
    assert archive.testzip() is None
    for entry in entries:
        data = archive.read(entry['name'])
        entry['ok'] = (len(data) == entry['size'] and
                       archive.getinfo(entry['name']).CRC == int(entry['crc'], 16) and
                       hashlib.sha1(data).hexdigest() == entry['sha1'])
report = dict(core='MAME 2010 / MAME 0.139', rom=str(rom),
              rom_sha256=hashlib.sha256(rom.read_bytes()).hexdigest(),
              driver_sha256=hashlib.sha256(source.read_bytes()).hexdigest(), entries=entries)
# As a service the code tree is read-only: the report goes to the unit's runtime directory.
out = Path(os.environ.get('AVRANA_ARCADE_RUNTIME') or root / 'evidence')
(out / 'gaunt2-mame2010-audit.json').write_text(json.dumps(report, indent=2) + '\n')
print(f"{sum(e['ok'] for e in entries)}/26 files match name, size, CRC and SHA-1")
raise SystemExit(0 if all(e['ok'] for e in entries) else 1)
