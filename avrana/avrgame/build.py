"""Building an experimental .avrgame archive deterministically, and the developer build recipe.

EXPERIMENTAL: names may change. The recipe (`avrgame.build.json`) is a developer convenience; it
is not inside the archive and not part of the package contract.

Determinism: the manifest first, then every other file sorted by path; fixed timestamps
(1980-01-01), fixed permissions (files 0644, no directory entries), forward slashes, deflate at a
fixed level. The same inputs give the same bytes with the same zlib; `compress=False` (stored)
gives the same bytes on every platform.
"""
import io
import os
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from avrana.contracts import strictjson

from . import archive, common
from .common import (MANIFEST_NAME, RECIPE_FORMAT, RECIPE_NAME, Problems, Refused, bytecode, clip,
                     name_problem)
from .manifest import parse, validate_manifest

FIXED_TIME = (1980, 1, 1, 0, 0, 0)
FILE_ATTR = (stat.S_IFREG | 0o644) << 16
_REPARSE = 0x400


@dataclass(frozen=True)
class Recipe:
    path: Path
    root: Path
    manifest: Path
    include: tuple


def _plain(path, what):
    """lstat that refuses links (symlinks, and Windows junctions/reparse points)."""
    try:
        st = os.lstat(path)
    except OSError:
        raise Refused(f'{what}: does not exist or cannot be read') from None
    if stat.S_ISLNK(st.st_mode) or getattr(st, 'st_file_attributes', 0) & _REPARSE:
        raise Refused(f'{what}: symbolic links are refused')
    return st


def _relative_ok(value, what, problems):
    if (not isinstance(value, str) or not value or '\\' in value or value.startswith('/')
            or ':' in value or any(ord(c) < 32 for c in value)):
        problems.add(f'{what}: a relative "/"-separated path')
        return False
    return True


def load_recipe(path):
    """Read and validate an avrgame.build.json (strict; unknown keys refused)."""
    path = Path(path)
    try:
        doc = strictjson.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError):
        raise Refused(f'{clip(str(path))}: recipe cannot be read') from None
    except ValueError as exc:
        raise Refused(f'{clip(str(path))}: recipe is not strict JSON ({clip(str(exc), 100)})') from None
    problems = Problems()
    if not isinstance(doc, dict):
        raise Refused('recipe: must be a JSON object')
    for key in sorted(set(doc) - {'recipe', 'manifest', 'root', 'include'}):
        problems.add(f'recipe: unknown key {clip(key)}')
    if doc.get('recipe') != RECIPE_FORMAT:
        problems.add(f'recipe.recipe: must be {RECIPE_FORMAT!r}')
    manifest = doc.get('manifest', MANIFEST_NAME)
    root = doc.get('root', '.')
    for key, value in (('manifest', manifest), ('root', root)):
        _relative_ok(value, f'recipe.{key}', problems)
    include = doc.get('include')
    if not isinstance(include, list) or not 1 <= len(include) <= 200:
        problems.add('recipe.include: a list of 1-200 paths relative to root')
        include = []
    for i, item in enumerate(include):
        why = name_problem(item, f'recipe.include[{i}]')
        if why:
            problems.add(why)
    problems.raise_if_any()
    base = path.resolve().parent
    return Recipe(path=path, root=(base / root), manifest=(base / manifest), include=tuple(include))


def _collect(root, includes, problems, skip=None):
    """{archive name: path on disk} for the includes (directories recursive)."""
    out = {}
    root = Path(root)
    for item in includes:
        why = name_problem(item, f'include {clip(str(item))}')
        if why:
            problems.add(why)
            continue
        start = root / item
        try:
            st = _plain(start, f'include {clip(item)}')
        except Refused as exc:
            problems.add(exc.problems[0])
            continue
        if stat.S_ISREG(st.st_mode):
            out[item] = start
        elif stat.S_ISDIR(st.st_mode):
            _walk(start, item, out, problems)
        else:
            problems.add(f'include {clip(item)}: not a regular file or directory')
    if skip:
        # The manifest is added once, as avrgame.json; a copy of it in an included directory is dropped.
        out = {k: v for k, v in out.items() if os.path.realpath(v) != skip}
    return out


def _walk(directory, prefix, out, problems):
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        problems.add(f'include {clip(prefix)}: cannot list directory')
        return
    for name in names:
        # Not part of a package: hidden files, bytecode caches, the recipe itself.
        if name.startswith('.') or name == '__pycache__' or name == RECIPE_NAME or name.endswith(('.pyc', '.pyo')):
            continue
        rel = f'{prefix}/{name}'
        child = Path(directory) / name
        try:
            st = _plain(child, f'path {clip(rel)}')
        except Refused as exc:
            problems.add(exc.problems[0])
            continue
        if stat.S_ISDIR(st.st_mode):
            _walk(child, rel, out, problems)
        elif stat.S_ISREG(st.st_mode):
            out[rel] = child
        else:
            problems.add(f'path {clip(rel)}: not a regular file or directory')


def build_bytes(source_root, manifest_path, includes, compress=True):
    """The archive bytes, validated exactly as `read` validates an archive. Writes nothing."""
    problems = Problems()
    try:
        _plain(manifest_path, 'manifest')
        manifest_bytes = Path(manifest_path).read_bytes()
    except OSError:
        raise Refused('manifest: cannot be read') from None
    manifest = validate_manifest(parse(manifest_bytes))     # raises with every manifest problem
    files = _collect(source_root, includes, problems, os.path.realpath(manifest_path))
    if MANIFEST_NAME in files:
        problems.add(f'{MANIFEST_NAME}: comes from the manifest path; do not include another one at the root')
    if len(files) + 1 > common.MAX_FILES:
        problems.add(f'{len(files) + 1} files; at most {common.MAX_FILES} are allowed')
    for name in sorted(files):
        if bytecode(name):
            problems.add(f'{clip(name)}: Python bytecode is not reviewable source; ship .py files only')
    problems.raise_if_any()
    entries = [(MANIFEST_NAME, manifest_bytes)]
    total = len(manifest_bytes)
    for name in sorted(files):
        try:
            size = os.lstat(files[name]).st_size
            if size > common.MAX_FILE_BYTES:
                problems.add(f'{clip(name)}: {size} bytes; a file may be at most {common.MAX_FILE_BYTES}')
                continue
            with open(files[name], 'rb') as f:
                data = f.read(common.MAX_FILE_BYTES + 1)
        except OSError:
            problems.add(f'{clip(name)}: cannot be read')
            continue
        total += len(data)
        if total > common.MAX_TOTAL_BYTES:
            problems.add(f'files total more than {common.MAX_TOTAL_BYTES} bytes')
            break
        entries.append((name, data))
    problems.raise_if_any()
    buf = io.BytesIO()
    method = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
    with zipfile.ZipFile(buf, 'w') as zf:
        for name, data in entries:
            info = zipfile.ZipInfo(name, FIXED_TIME)
            info.compress_type = method
            info.create_system = 3
            info.external_attr = FILE_ATTR
            zf.writestr(info, data, compress_type=method, compresslevel=9 if compress else None)
    data = buf.getvalue()
    archive.scan(data)[1].close()     # the same validation a reader applies
    return data


def _write_atomic(data, out_path):
    out_path = os.fspath(out_path)
    directory = os.path.dirname(os.path.abspath(out_path))
    fd, tmp = tempfile.mkstemp(prefix='.avrgame-', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        os.replace(tmp, out_path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return out_path


def pack(source_root, manifest_path, includes, out_path, compress=True):
    """Build `out_path` from `includes` (paths relative to `source_root`, directories recursive)
    and the manifest at `manifest_path` (stored as avrgame.json). Validates before writing and
    writes atomically. Returns the Package of the written archive."""
    data = build_bytes(source_root, manifest_path, includes, compress)
    return archive.read(_write_atomic(data, out_path))


def recipe_build(recipe_path, compress=True):
    """The archive bytes a recipe describes (nothing is written)."""
    r = load_recipe(recipe_path)
    return build_bytes(r.root, r.manifest, r.include, compress)


def pack_recipe(recipe_path, out_path=None, compress=True):
    """Pack from a recipe. Default output: `<id>-<version>.avrgame` in the current directory.
    Returns the Package (its `path` says where)."""
    r = load_recipe(recipe_path)
    data = build_bytes(r.root, r.manifest, r.include, compress)
    package, zf = archive.scan(data)
    zf.close()
    if out_path is None:
        out_path = f'{package.id}-{package.version}.avrgame'
    return archive.read(_write_atomic(data, out_path))


def validate_recipe(recipe_path, compress=True):
    """Validate the package a recipe would build, without writing it. Returns its Package."""
    package, zf = archive.scan(recipe_build(recipe_path, compress))
    zf.close()
    return package
