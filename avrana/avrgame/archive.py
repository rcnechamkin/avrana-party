"""Reading and extracting an experimental .avrgame archive (a ZIP), as UNTRUSTED INPUT.

EXPERIMENTAL: names and limits may change. Nothing here executes, imports or evaluates anything
from an archive. `read` validates without extracting; `extract` unpacks into a new or empty
directory and writes files 0644 and directories 0755 whatever the archive says.
"""
import hashlib
import io
import os
import stat
import zipfile
import zlib
from dataclasses import dataclass

from . import common
from .common import MANIFEST_NAME, Problems, Refused, bytecode, clip, name_problem
from .manifest import client_index, parse, validate_manifest

CHUNK = 64 * 1024
ALLOWED_COMPRESSION = (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
_DAMAGE = (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError, OSError, ValueError)


@dataclass(frozen=True)
class PackageFile:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class Package:
    """A validated package, described without extracting it."""
    manifest: dict          # normalised avrgame.json (format, game, package, requires, server, client)
    game: dict              # the normalised Game Contract (what avrana.contracts.game.validate returns)
    id: str                 # game.id
    version: str            # package.version (display claim)
    sha256: str             # of the archive bytes
    size: int               # archive bytes
    files: tuple            # PackageFile entries, sorted by path; includes avrgame.json
    total_bytes: int        # sum of file sizes
    path: str = None        # where it was read from or written to, when known


def _limits():
    return common.MAX_FILES, common.MAX_FILE_BYTES, common.MAX_TOTAL_BYTES


def read_bytes(path):
    """The archive file's bytes, bounded; refuses a non-file or one over MAX_ARCHIVE_BYTES."""
    try:
        with open(path, 'rb') as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                raise Refused(f'{clip(str(path))}: not a regular file')
            data = f.read(common.MAX_ARCHIVE_BYTES + 1)
    except OSError as exc:
        raise Refused(f'{clip(str(path))}: cannot read ({type(exc).__name__})') from None
    if len(data) > common.MAX_ARCHIVE_BYTES:
        raise Refused(f'archive: larger than {common.MAX_ARCHIVE_BYTES} bytes')
    return data


def _entry_problem(info):
    """Why one ZIP entry is not acceptable, or None. Uses the raw name (zipfile rewrites the
    parsed name, and truncates at NUL, depending on platform)."""
    raw = info.orig_filename
    is_dir = raw.endswith('/')
    why = name_problem(raw[:-1] if is_dir else raw, 'entry')
    if why:
        return why
    shown = clip(raw)
    if info.flag_bits & 0x41:
        return f'entry {shown}: encrypted entries are not allowed'
    if info.compress_type not in ALLOWED_COMPRESSION:
        return f'entry {shown}: compression method {info.compress_type} is not allowed (stored or deflated only)'
    mode = info.external_attr >> 16
    kind = stat.S_IFMT(mode)
    if kind not in (0, stat.S_IFREG, stat.S_IFDIR) or (info.external_attr & 0x400):
        return f'entry {shown}: only regular files and directories are allowed (no links or devices)'
    if mode & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX):
        return f'entry {shown}: setuid, setgid and sticky bits are not allowed'
    if (kind == stat.S_IFDIR or info.external_attr & 0x10) != is_dir:
        return f'entry {shown}: file/directory type does not match its name'
    if is_dir and info.file_size:
        return f'entry {shown}: a directory with content'
    if not is_dir and bytecode(raw):
        return f'entry {shown}: Python bytecode is not reviewable source; ship .py files only'
    if info.file_size > common.MAX_FILE_BYTES:
        return f'entry {shown}: declares {info.file_size} bytes; a file may be at most {common.MAX_FILE_BYTES}'
    return None


def _stream(zf, info, limit_file, total_left):
    """(size, sha256 hex) of the ACTUAL bytes of an entry, refusing past either limit."""
    h = hashlib.sha256()
    n = 0
    try:
        with zf.open(info) as f:
            while True:
                chunk = f.read(CHUNK)
                if not chunk:
                    break
                n += len(chunk)
                if n > limit_file:
                    raise Refused(f'entry {clip(info.orig_filename)}: more than {limit_file} bytes once unpacked')
                if n > total_left:
                    raise Refused(f'archive: more than {common.MAX_TOTAL_BYTES} bytes once unpacked')
                h.update(chunk)
    except _DAMAGE as exc:
        raise Refused(f'entry {clip(info.orig_filename)}: damaged ({type(exc).__name__})') from None
    return n, h.hexdigest()


def _open_zip(data):
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError, OSError, NotImplementedError, EOFError):
        raise Refused('archive: not a valid ZIP file') from None
    return zf


def scan(data, vocab=None):
    """Validate archive bytes completely and return (Package, ZipFile). Raises Refused with every
    problem found before any content is streamed."""
    max_files, max_file, max_total = _limits()
    zf = _open_zip(data)
    infos = zf.infolist()
    problems = Problems()
    if len(infos) > max_files:
        raise Refused(f'archive: {len(infos)} entries; at most {max_files} are allowed')
    seen = {}
    folded = {}
    dir_spelling = {}
    files = []
    dirs = set()
    declared = 0
    for info in infos:
        why = _entry_problem(info)
        if why:
            problems.add(why)
            continue
        raw = info.orig_filename
        if raw in seen:
            problems.add(f'entry {clip(raw)}: duplicate name')
            continue
        seen[raw] = info
        key = raw.rstrip('/').lower()
        if key in folded and folded[key] != raw:
            problems.add(f'entry {clip(raw)}: differs only by case from {clip(folded[key])}')
        folded.setdefault(key, raw)
        parts = raw.rstrip('/').split('/')
        for i in range(1, len(parts)):
            spelled = '/'.join(parts[:i])
            first = dir_spelling.setdefault(spelled.lower(), spelled)
            if first != spelled:
                problems.add(f'entry {clip(raw)}: directory differs only by case from {clip(first)}')
            dirs.add(spelled.lower())
        if raw.endswith('/'):
            dirs.add(key)
        else:
            files.append(info)
            declared += info.file_size
    for info in files:
        if info.orig_filename.lower() in dirs:
            problems.add(f'entry {clip(info.orig_filename)}: is both a file and a directory')
    if declared > max_total:
        problems.add(f'archive: declares {declared} bytes unpacked; at most {max_total} are allowed')
    names = {i.orig_filename for i in files}

    manifest_info = seen.get(MANIFEST_NAME)
    manifest = None
    if manifest_info is None or manifest_info.orig_filename.endswith('/'):
        nested = [n for n in names if n.rsplit('/', 1)[-1].lower() == MANIFEST_NAME]
        problems.add(f'{MANIFEST_NAME}: missing at the archive root'
                     + (f' (found only at {clip(sorted(nested)[0])})' if nested else ''))
    elif problems:
        pass
    else:
        if manifest_info.file_size > common.MAX_MANIFEST_BYTES:
            problems.add(f'{MANIFEST_NAME}: larger than {common.MAX_MANIFEST_BYTES} bytes')
        else:
            try:
                raw_manifest = zf.read(manifest_info)
            except _DAMAGE as exc:
                raise Refused(f'{MANIFEST_NAME}: damaged ({type(exc).__name__})') from None
            if len(raw_manifest) > common.MAX_MANIFEST_BYTES:
                raise Refused(f'{MANIFEST_NAME}: larger than {common.MAX_MANIFEST_BYTES} bytes')
            try:
                manifest = validate_manifest(parse(raw_manifest), vocab)
            except Refused as exc:
                for p in exc.problems:
                    problems.add(p)
    if manifest is not None:
        index = client_index(manifest)
        if index not in names:
            problems.add(f'client.root: the package has no {clip(index)}')
    problems.raise_if_any()

    listing = []
    total = 0
    for info in sorted(files, key=lambda i: i.orig_filename):
        size, digest = _stream(zf, info, max_file, max_total - total)
        total += size
        listing.append(PackageFile(info.orig_filename, size, digest))
    package = Package(manifest=manifest, game=manifest['game'], id=manifest['game']['id'],
                      version=manifest['package']['version'], sha256=hashlib.sha256(data).hexdigest(),
                      size=len(data), files=tuple(listing), total_bytes=total)
    return package, zf


def read(path, vocab=None):
    """Validate a .avrgame file without extracting it; returns a Package or raises Refused."""
    package, zf = scan(read_bytes(path), vocab)
    zf.close()
    return _with_path(package, path)


inspect = read


def _with_path(package, path):
    return Package(**{**package.__dict__, 'path': os.fspath(path)})


def _check_dest(dest):
    if os.path.islink(dest):
        raise Refused('destination: is a symbolic link')
    if os.path.lexists(dest):
        if not os.path.isdir(dest):
            raise Refused('destination: exists and is not a directory')
        if os.listdir(dest):
            raise Refused('destination: must be new or empty')


def extract(path, dest, vocab=None):
    """Validate a .avrgame file, then unpack it into `dest`, which must not exist or be an empty
    directory. Files are written 0644 and directories 0755 (modes in the archive are ignored).
    On any failure what this call created is removed again. Returns the Package."""
    dest = os.fspath(dest)
    _check_dest(dest)
    package, zf = scan(read_bytes(path), vocab)
    created_files, created_dirs = [], []
    done = False
    try:
        if not os.path.lexists(dest):
            os.makedirs(dest)
            created_dirs.append(dest)
        base = os.path.realpath(dest)
        infos = {i.orig_filename: i for i in zf.infolist()}
        for entry in package.files:
            _write_one(zf, infos[entry.path], entry, base, created_files, created_dirs)
        done = True
    except OSError as exc:
        raise Refused(f'extract: {type(exc).__name__} while writing') from None
    finally:
        zf.close()
        if not done:
            for f in reversed(created_files):
                _quiet(os.remove, f)
            for d in reversed(created_dirs):
                _quiet(os.rmdir, d)
    return _with_path(package, path)


def _quiet(fn, arg):
    try:
        fn(arg)
    except OSError:
        pass


def _write_one(zf, info, entry, base, created_files, created_dirs):
    parts = entry.path.split('/')
    current = base
    for seg in parts[:-1]:
        current = os.path.join(current, seg)
        fresh = not os.path.lexists(current)
        if fresh:
            os.mkdir(current)
            created_dirs.append(current)
        st = os.lstat(current)
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            raise Refused(f'extract: {clip(entry.path)}: a parent is not a plain directory')
        if fresh:
            _quiet(lambda p: os.chmod(p, 0o755), current)
    target = os.path.join(current, parts[-1])
    real = os.path.realpath(os.path.dirname(target))
    if os.path.commonpath([base, real]) != base or os.path.realpath(target) != os.path.join(real, parts[-1]):
        raise Refused(f'extract: {clip(entry.path)}: resolves outside the destination')
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(target, flags, 0o644)
    created_files.append(target)
    h = hashlib.sha256()
    n = 0
    with os.fdopen(fd, 'wb') as out:
        try:
            with zf.open(info) as src:
                while True:
                    chunk = src.read(CHUNK)
                    if not chunk:
                        break
                    n += len(chunk)
                    if n > entry.size:
                        raise Refused(f'extract: {clip(entry.path)}: changed while unpacking')
                    h.update(chunk)
                    out.write(chunk)
        except _DAMAGE as exc:
            raise Refused(f'extract: {clip(entry.path)}: damaged ({type(exc).__name__})') from None
    if n != entry.size or h.hexdigest() != entry.sha256:
        raise Refused(f'extract: {clip(entry.path)}: changed while unpacking')
    _quiet(lambda p: os.chmod(p, 0o644), target)
