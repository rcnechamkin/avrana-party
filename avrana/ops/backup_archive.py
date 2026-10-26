"""The owner backup file (avrana.backup/v1): writing it, and reading one as untrusted input (AVR-81).

PROTOTYPE for docs/design/proposals/2026-10-26-owner-backup-and-restore.md sections 3 and 8 (owner decisions
open). Only the file format: it collects nothing from a device and restores nothing. Without encryption
(decision D2), so the Wi-Fi passphrase class cannot be written at all.

A backup is a tar archive of `manifest.json` plus one member per entry. Each entry has a class, a logical
name (never an absolute path the archive chooses), a size and a SHA-256. Only owner state (class `O`) is
ever stored: release files are rebuilt (`R`), device secrets are never copied (`S`), ephemeral state is left
behind (`E`), and the owner's Wi-Fi passphrase (`O-secret`) needs the encrypted form, which is not built.

`read` treats the file as hostile and refuses, with nothing returned, on: a member that is not a regular
file (links, devices, directories), a name with `..`, a leading `/` or odd characters, a member not in the
manifest or an entry with no member, a wrong size or hash, an unknown or forbidden class, an entry or a
whole archive over its bound, and a schema it does not know (a backup from a future version).
"""
import hashlib
import io
import json
import re
import tarfile

SCHEMA = 'avrana.backup/v1'
STORED = ('O',)
KNOWN = ('R', 'O', 'O-secret', 'S', 'E')
NAME = re.compile(r'^[a-z0-9][a-z0-9._-]{0,63}(/[a-z0-9][a-z0-9._-]{0,63}){0,4}$')
MAX_ENTRY = 8 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024
MAX_ENTRIES = 512
MANIFEST = 'manifest.json'


class Refused(ValueError):
    pass


def _check_entry(cls, name, size):
    if cls not in KNOWN:
        raise Refused(f'{name!r}: unknown class {cls!r}')
    if cls not in STORED:
        raise Refused(f'{name!r}: class {cls} is never stored in a backup')
    if not isinstance(name, str) or not NAME.match(name) or '..' in name.split('/'):
        raise Refused(f'not a logical name: {name!r}')
    if size > MAX_ENTRY:
        raise Refused(f'{name!r}: more than {MAX_ENTRY} bytes')


def build(entries, versions, packages=(), created='1970-01-01T00:00:00Z'):
    """The backup bytes. `entries` is [(class, logical name, bytes)]; `versions` {party, games, web};
    `packages` the package list (id, version, sha256, grants). Deterministic for the same input."""
    if len(entries) > MAX_ENTRIES:
        raise Refused(f'more than {MAX_ENTRIES} entries')
    seen, manifest_entries, total = set(), [], 0
    for cls, name, data in entries:
        _check_entry(cls, name, len(data))
        if name in seen or name == MANIFEST:
            raise Refused(f'{name!r} appears twice')
        seen.add(name)
        total += len(data)
        manifest_entries.append({'class': cls, 'name': name, 'size': len(data),
                                 'sha256': hashlib.sha256(data).hexdigest()})
    if total > MAX_TOTAL:
        raise Refused(f'more than {MAX_TOTAL} bytes in all')
    manifest = {'schema': SCHEMA, 'created': created, 'versions': dict(versions),
                'packages': list(packages), 'entries': sorted(manifest_entries, key=lambda e: e['name'])}
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w', format=tarfile.PAX_FORMAT) as tar:
        for name, data in [(MANIFEST, json.dumps(manifest, sort_keys=True, indent=1).encode())] + \
                sorted(((n, d) for _, n, d in entries), key=lambda x: x[0]):
            info = tarfile.TarInfo('files/' + name if name != MANIFEST else MANIFEST)
            info.size, info.mtime, info.mode, info.uid, info.gid = len(data), 0, 0o600, 0, 0
            tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


def read(data):
    """(manifest, {logical name: bytes}) of a backup, or Refused. Nothing is written anywhere."""
    if len(data) > MAX_TOTAL + 1024 * 1024:
        raise Refused('the file is too large to be a backup')
    try:
        tar = tarfile.open(fileobj=io.BytesIO(data), mode='r:')
        members = tar.getmembers()
    except (tarfile.TarError, EOFError, OSError):
        raise Refused('not a backup file (not a tar archive)') from None
    if len(members) > MAX_ENTRIES + 1:
        raise Refused(f'more than {MAX_ENTRIES} entries')
    files, manifest = {}, None
    for m in members:
        if not m.isreg():
            raise Refused(f'{m.name!r}: not a regular file')
        if m.size > max(MAX_ENTRY, 4 * 1024 * 1024):
            raise Refused(f'{m.name!r}: too large')
        if m.name == MANIFEST:
            raw = tar.extractfile(m).read()
            try:
                manifest = json.loads(raw)
            except ValueError:
                raise Refused('manifest.json is not JSON') from None
            continue
        if not m.name.startswith('files/'):
            raise Refused(f'{m.name!r}: outside files/')
        name = m.name[len('files/'):]
        if name in files:
            raise Refused(f'{name!r} appears twice')
        files[name] = tar.extractfile(m).read()
    if not isinstance(manifest, dict):
        raise Refused('no manifest.json')
    if manifest.get('schema') != SCHEMA:
        raise Refused(f'unknown backup schema {manifest.get("schema")!r} (from a newer version?)')
    entries = manifest.get('entries')
    if not isinstance(entries, list):
        raise Refused('manifest has no entry list')
    total, listed = 0, set()
    for e in entries:
        if not isinstance(e, dict):
            raise Refused('a manifest entry is not an object')
        name, size = e.get('name'), e.get('size')
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise Refused(f'{name!r}: bad size')
        _check_entry(e.get('class'), name, size)
        if name in listed:
            raise Refused(f'{name!r} listed twice')
        listed.add(name)
        body = files.get(name)
        if body is None:
            raise Refused(f'{name!r}: listed but missing')
        if len(body) != size or hashlib.sha256(body).hexdigest() != e.get('sha256'):
            raise Refused(f'{name!r}: size or hash differs from the manifest')
        total += size
    extra = set(files) - listed
    if extra:
        raise Refused(f'members not in the manifest: {sorted(extra)[:3]}')
    if total > MAX_TOTAL:
        raise Refused(f'more than {MAX_TOTAL} bytes in all')
    return manifest, files
