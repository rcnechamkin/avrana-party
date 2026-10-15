"""The EFFECTIVE game catalog: the release's catalog plus a row for each installed `.avrgame`
package (AVR-337, EXPERIMENTAL, not deployed).

    python3 -m avrana.ops.catalog_overlay refresh     # write, or remove, the overlay (root)
    python3 -m avrana.ops.catalog_overlay check       # exit 1 when the overlay is not what refresh would write
    python3 -m avrana.ops.catalog_overlay show        # print the effective catalog; write nothing

Party Home reads `/party/catalog.json`. The release tree's file is generated, committed and never
rewritten. When a package is installed, this module writes the effective catalog to an
appliance-local file that nginx serves instead of the release file (the `= /party/catalog.json`
location of avrana-party.nginx); with no package installed that file does not exist and the
release catalog is served byte for byte. Nothing here executes or evaluates anything from a package.

The rules, each tested:

- The document is the release catalog (the file nginx would otherwise serve, parsed and written
  again) with each installed package's row appended, in id order, after every first-party row.
  A first-party row is never replaced, shadowed, moved or edited; a package whose id is already in
  the catalog is skipped. Device labels a package row needs are added only when absent.
- A package is listed only when its install record is valid (avrana.avrgame.installed) and the
  catalog builder (avrana.contracts.catalog.build) accepts its row. A record that is refused, or a
  row the builder rejects, drops that package alone and is reported; the others stay.
- Package artwork (AVR-466 phase C, experimental): for each listed package the staged manifest is re-read
  (the install record is unchanged), its `artwork.cover` and `artwork.icon` are re-hashed against the record
  and re-validated by avrana.avrgame.artwork, and the valid ones are copied, content-addressed, to
  `<out dir>/art/<id>/<16 hex of sha256>.<ext>` (nginx serves them at /party/pkgart/, a separate and
  separately approved deploy step); the row gains `images: {cover|icon: {url, w, h}}`. A damaged image is
  dropped alone (the game stays listed, a warning is reported) and never undoes an install. Banner and
  screenshots are validated at install and neither copied nor listed. Files no listed row names are pruned.
- No valid package, no overlay file: `refresh` removes it, so the appliance serves exactly the
  committed catalog.
- Written atomically: a hidden temporary file in the same directory, flushed and fsynced, made 0644,
  renamed, and the directory fsynced. Same inputs, same bytes (no timestamp). A reader sees the old
  file or the new one, never a part. If anything goes wrong while refreshing, the overlay is
  removed before the error is raised: absent and regenerable, never stale or half-written.
- `refresh` repeats (at most MAX_BASE_MOVES times) when the release catalog changed while it ran. An install
  that read the old release can still publish the old release's overlay if the switch comes after its last
  check and before it returns; the deploy's own refresh (`refresh --wait N` waits up to N seconds for a running
  install-game) replaces it within that wait, and until then phones are served that overlay, or the release
  catalog when it was removed.
- The overlay is derived from the release catalog, so a new release or a rollback of the web shell
  makes it stale. `ops/install-party-web.sh` runs `refresh` after it switches `current`, `ops/deploy.sh`
  (`settle_catalog`) refreshes or removes it after every move of the web release it makes, including its
  rollbacks, and `check` says whether it is current.

Everything that touches the host is an argument, so the tests run in scratch directories.
"""
import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import sys
import unicodedata
from pathlib import Path

from avrana import CONTRACTS_DIR
from avrana import avrgame
from avrana.avrgame import artwork, installed
from avrana.contracts import appliance as appliance_mod
from avrana.contracts import catalog, strictjson, vocabulary

DEFAULT_DIR = '/var/lib/avrana-party/catalog'
FILE_NAME = 'catalog.json'
DEFAULT_BASE = '/var/www/avrana-party/web/current/catalog.json'
MAX_BASE_BYTES = 4 * 1024 * 1024
MAX_BASE_MOVES = 3          # a refresh repeats at most this often when the release catalog moves under it
MAX_OVERLAY_BYTES = 5 * 1024 * 1024
MAX_ROW_BYTES = 4096
ART_DIR_NAME = 'art'                 # <out dir>/art/<id>/<digest>.<ext>
ART_URL_PREFIX = '/party/pkgart'     # the public path nginx maps to that directory
ART_ROLES = ('cover', 'icon')        # banner and screenshots are validated, not served (D11)
ART_EXTENSIONS = {'webp': 'webp', 'png': 'png', 'jpeg': 'jpg'}
MAX_NAME, MAX_SUMMARY, MAX_STRING = 60, 400, 200
# The only keys of a package's row. Everything else the builder copies from the contract's free-form
# extensions (provider, status, legacySlug, integration, icon, art, accent, category, description,
# playersLabel, launchTarget, artwork, ...) is package-controlled and dropped.
ROW_KEYS = ('id', 'name', 'kind', 'players', 'screen', 'input', 'late_join', 'spectators', 'private_player_ui',
            'fallback', 'installed', 'entry', 'health', 'playableHere', 'presentations', 'summary')


_IGNORABLE = re.compile('[͏ᅟᅠ᠋-᠏ㅤ︀-️ﾠ󠄀-󠇯]')


def _fold(text):
    """NFKC, case folded, whitespace collapsed, with invisible marks and fillers dropped (categories
    Mn, Me, Cf and the default-ignorable fillers). Confusable letters (Cyrillic or Greek look-alikes)
    are NOT folded: a documented residual."""
    text = unicodedata.normalize('NFKC', str(text)).casefold()
    text = ''.join(c for c in text if unicodedata.category(c) not in ('Mn', 'Me', 'Cf'))
    return ' '.join(_IGNORABLE.sub('', text).split())


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v)


def package_row(row, pid, taken_names, images=None):
    """The row a package may have: an allowlist of the builder's keys, the fields that say what it
    is forced (native, /games/<id>/, installed, community), every string and the row bounded, and a
    display name that cannot pass for a first-party game's. ValueError says why not."""
    out = {k: row[k] for k in ROW_KEYS if k in row}
    out.update({'id': pid, 'installed': True, 'entry': f'/games/{pid}/', 'provider': 'native', 'status': 'current',
                'tier': 'community'})
    if images:
        out['images'] = images           # appliance-set, never read from the contract (the builder's keys are an allowlist)
    name = out.get('name')
    if not isinstance(name, str) or not name.strip() or not name.isprintable() or len(name) > MAX_NAME:
        raise ValueError(f'the display name must be 1 to {MAX_NAME} printable characters')
    if isinstance(out.get('summary'), str) and (len(out['summary']) > MAX_SUMMARY or not out['summary'].isprintable()):
        raise ValueError(f'the summary is longer than {MAX_SUMMARY} characters or not printable')
    for text in _strings({k: v for k, v in out.items() if k not in ('name', 'summary')}):
        if len(text) > MAX_STRING:
            raise ValueError(f'a text in the row is longer than {MAX_STRING} characters')
    if not _fold(name):
        raise ValueError('the display name is empty once invisible characters are removed')
    if _fold(name) in taken_names or _fold(pid) in taken_names:
        raise ValueError(f'the display name {name!r} is, or is easily mistaken for, the name of a first-party game')
    if len(json.dumps(out, ensure_ascii=False).encode('utf-8')) > MAX_ROW_BYTES:
        raise ValueError(f'the row is larger than {MAX_ROW_BYTES} bytes')
    return out


# ---- package artwork (AVR-466 phase C, experimental) -------------------------------------------------------------

class _Damaged(Exception):
    """One staged file cannot be used as it is. The sentence says why."""


def _read_plain(path, limit):
    """The bytes of a plain file of at most `limit` bytes (never a link), or _Damaged."""
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        raise _Damaged('is missing or not a plain file') from None
    with os.fdopen(fd, 'rb') as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise _Damaged('is not a plain file')
        data = f.read(limit + 1)
    if len(data) > limit:
        raise _Damaged(f'is larger than {limit} bytes')
    return data


def _disk_dir(root, games_root, disk_root):
    prefix = str(games_root).replace('\\', '/').rstrip('/') + '/'
    if not root.startswith(prefix):
        raise _Damaged(f'the staged tree {root} is not under {prefix}')
    return Path(disk_root).joinpath(*root[len(prefix):].split('/'))


def package_art(rec, games_root, disk_root):
    """(images, files, problems) for one install record. `images` is {role: {url, w, h}} for the cover and
    icon that are still exactly what was installed and still valid; `files` maps '<id>/<digest>.<ext>' to the
    bytes to serve; `problems` are `<id>: artwork ...` sentences for what was left out. The staged manifest
    is re-read and the images are re-hashed against the record and re-checked by avrana.avrgame.artwork. A
    damaged image is dropped alone; nothing here raises."""
    images, files, problems = {}, {}, []
    known = {path: (size, digest) for path, size, digest in rec.files}
    try:
        base = _disk_dir(rec.root, games_root, disk_root)
    except _Damaged as exc:
        return images, files, [f'{rec.id}: artwork not shown: {exc}']

    def load(name, limit):
        if name not in known:
            raise _Damaged('is not in the install record')
        size, digest = known[name]
        if size > limit:
            raise _Damaged(f'is {size} bytes, more than the {limit} allowed')
        data = _read_plain(base.joinpath(*name.split('/')), limit)
        if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
            raise _Damaged('changed since it was installed')
        return data

    try:
        manifest = avrgame.validate_manifest(avrgame.parse_manifest(load(avrgame.MANIFEST_NAME, avrgame.MAX_MANIFEST_BYTES)))
    except _Damaged as exc:
        return images, files, [f'{rec.id}: artwork not shown: the staged manifest {exc}']
    except Exception as exc:
        return images, files, [f'{rec.id}: artwork not shown: the staged manifest cannot be read ({type(exc).__name__})']
    block = manifest.get('artwork') or {}
    for role in ART_ROLES:
        if role not in block:
            continue
        path = block[role]
        try:
            data = load(path, artwork.COVER_LIMITS[0] if role == 'cover' else artwork.ICON_LIMITS[0])
            wrong, _ = artwork.file_problems({role: path}, {path: len(data)}, lambda name: data)
            if wrong:
                raise _Damaged('; '.join(wrong))
            kind, width, height, _ = artwork.inspect_image(path, data)
        except _Damaged as exc:
            problems.append(f'{rec.id}: artwork {role} not shown: {exc}')
            continue
        except Exception as exc:
            problems.append(f'{rec.id}: artwork {role} not shown: cannot be checked ({type(exc).__name__})')
            continue
        name = f'{hashlib.sha256(data).hexdigest()[:16]}.{ART_EXTENSIONS[kind]}'
        images[role] = {'url': f'{ART_URL_PREFIX}/{rec.id}/{name}', 'w': width, 'h': height}
        files[f'{rec.id}/{name}'] = data
    return images, files, problems


def _same_file(path, data):
    try:
        return _read_plain(path, len(data)) == data
    except _Damaged:
        return False


def _write_art(art_dir, rel, data):
    """Copy one validated image to <art dir>/<id>/<name>, atomically; a file already there with these bytes stays."""
    path = Path(art_dir) / rel
    if _same_file(path, data):
        return
    for directory in (Path(art_dir), path.parent):
        if not directory.is_dir():
            os.makedirs(directory, mode=0o755, exist_ok=True)
            os.chmod(directory, 0o755)
    write_atomic(path, data)


def _art_present(art_dir):
    """Every non-directory entry under the art directory, as '<id>/<name>' (a link or a stray file included)."""
    found = set()
    root = Path(art_dir)
    if not root.is_dir():
        return found
    for top in os.scandir(root):
        if top.is_dir(follow_symlinks=False):
            for item in os.scandir(top.path):
                found.add(f'{top.name}/{item.name}')
        else:
            found.add(top.name)
    return found


def prune_art(art_dir, keep):
    """Remove everything under the art directory that is not in `keep` ('<id>/<name>'), the empty id
    directories, and the directory itself when nothing is left."""
    root = Path(art_dir)
    if not os.path.lexists(root):
        return
    if root.is_symlink() or not root.is_dir():
        root.unlink()
        return
    for top in sorted(os.scandir(root), key=lambda e: e.name):
        if not top.is_dir(follow_symlinks=False):
            os.unlink(top.path)
            continue
        for item in os.scandir(top.path):
            if f'{top.name}/{item.name}' in keep and item.is_file(follow_symlinks=False):
                continue
            if item.is_dir(follow_symlinks=False):
                shutil.rmtree(item.path)
            else:
                os.unlink(item.path)
        if not os.listdir(top.path):
            os.rmdir(top.path)
    if not os.listdir(root):
        os.rmdir(root)
    _fsync_dir(root.parent)


class OverlayError(Exception):
    """The effective catalog could not be produced. The overlay file is already gone."""


def _base(path):
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise OverlayError(f'the release catalog {path} cannot be read ({type(exc).__name__})') from exc
    if len(raw) > MAX_BASE_BYTES:
        raise OverlayError(f'the release catalog {path} is larger than {MAX_BASE_BYTES} bytes')
    try:
        doc = strictjson.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError) as exc:
        raise OverlayError(f'the release catalog {path} is not valid JSON ({exc})') from exc
    if not isinstance(doc, dict) or doc.get('schema') != catalog.CATALOG or not isinstance(doc.get('games'), list) \
            or not isinstance(doc.get('labels'), dict):
        raise OverlayError(f'{path} is not an {catalog.CATALOG} document')
    return doc


def _effective(base_path, records_dir, games_root=installed.DEFAULT_GAMES_ROOT, owner=installed._DEFAULT,
               appliance_path=catalog.DEFAULT_APPLIANCE, games_dir=None, strict_modes=None, repo_contracts=None,
               disk_root=None, art_dir=None, write_art=False):
    """(text, listed, problems, art). `art` maps '<id>/<name>' to the bytes of every image the rows name.
    With `write_art` (refresh) each image is copied under `art_dir` first, and one that cannot be copied is
    dropped from its row (a problem, not a failure)."""
    doc = _base(base_path)
    vocab = vocabulary.load()
    repo = repo_contracts if repo_contracts is not None else catalog.load_contracts(games_dir or CONTRACTS_DIR / 'games', vocab)
    found = installed.load(str(records_dir), repo, vocab, games_root=games_root, owner=owner, strict_modes=strict_modes)
    problems = list(found.problems)
    appliance = appliance_mod.load(appliance_path, vocab)
    taken = {row.get('id') for row in doc['games'] if isinstance(row, dict)}
    names = {_fold(x) for row in doc['games'] if isinstance(row, dict) for x in (row.get('id'), row.get('name')) if x}
    rows, labels, art = [], {}, {}
    for pid in sorted(found.records):
        if pid in taken or pid in repo:
            problems.append(f'{pid}: the catalog already has a game with this id; the package is not listed')
            continue
        try:
            one = catalog.build(vocab, appliance, {**repo, pid: found.contracts[pid]}, extra_grants={pid: found.grants[pid]})
            images, files, art_problems = package_art(found.records[pid], games_root, disk_root or games_root)
            row = package_row(next(g for g in one['games'] if g['id'] == pid), pid, names, images)
        except ValueError as exc:
            problems.append(f'{pid}: not listed: {exc}')
            continue
        problems.extend(art_problems)
        if write_art:
            for rel in sorted(files):
                try:
                    _write_art(art_dir, rel, files[rel])
                except OSError as exc:
                    problems.append(f'{pid}: artwork not shown: {rel} could not be copied ({type(exc).__name__})')
                    for role in [r for r, v in row['images'].items() if v['url'].endswith('/' + rel)]:
                        del row['images'][role]
                    if not row['images']:
                        del row['images']
                    files = {k: v for k, v in files.items() if k != rel}
        art.update(files)
        names.add(_fold(row['name']))
        rows.append(row)
        labels.update({k: v for k, v in one['labels'].items() if k not in doc['labels']})
    if not rows:
        return None, [], problems, {}
    doc['games'] = [*doc['games'], *rows]
    doc['labels'] = {**doc['labels'], **{k: labels[k] for k in sorted(labels)}}
    text = strictjson.dumps(doc)
    if len(text.encode('utf-8')) > MAX_OVERLAY_BYTES:
        raise OverlayError(f'the effective catalog would be larger than {MAX_OVERLAY_BYTES} bytes')
    return text, [row['id'] for row in rows], problems, art


def effective(base_path, records_dir, **kw):
    """(text, listed, problems). `text` is the effective catalog, or None when no package is to be
    listed (the release catalog is then served as it is). `listed` is the package ids in it. Nothing is written."""
    text, listed, problems, _ = _effective(base_path, records_dir, **kw)
    return text, listed, problems


def _fsync_dir(path):
    if os.name != 'posix':
        return                      # Windows cannot flush a directory handle; the real tool runs on Linux
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_atomic(path, text):
    path = Path(path)
    existed = path.parent.is_dir()
    os.makedirs(path.parent, mode=0o755, exist_ok=True)
    if not existed:
        os.chmod(path.parent, 0o755)         # the directory made here only; the umask must not narrow it
    tmp = path.with_name(f'.{path.name}.{secrets.token_hex(4)}.tmp')
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0)
                     | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'wb') as f:
            f.write(text if isinstance(text, bytes) else text.encode('utf-8'))
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    finally:
        if tmp.exists():
            tmp.unlink()


def remove(path):
    """True when a file was removed. Leftover hidden temporary files of a crashed write go too."""
    path = Path(path)
    gone = False
    if os.path.lexists(path):
        os.unlink(path)
        _fsync_dir(path.parent)
        gone = True
    if path.parent.is_dir():
        for stale in path.parent.glob(f'.{path.name}.*.tmp'):
            stale.unlink()
    return gone


def _digest(path):
    """A digest of the release catalog, read with the same bound as _base; None when it cannot be read."""
    try:
        with open(path, 'rb') as f:
            raw = f.read(MAX_BASE_BYTES + 1)
    except OSError:
        return None
    return hashlib.sha256(raw).hexdigest()


def refresh(out_dir, base_path, records_dir, **kw):
    """Make the overlay match the install records: write it, or remove it when no package is to be
    listed. Returns (listed ids, problems). On any failure the overlay is removed first and the
    error raised as OverlayError: the appliance then serves the release catalog, and `refresh`
    can be run again."""
    target = Path(out_dir) / FILE_NAME
    try:
        for _ in range(MAX_BASE_MOVES):
            seen = _digest(base_path)
            art_dir = Path(out_dir) / ART_DIR_NAME
            text, listed, problems, art = _effective(base_path, records_dir, art_dir=art_dir, write_art=True, **kw)
            if text is None:
                remove(target)
            else:
                write_atomic(target, text)
            prune_art(art_dir, set(art))          # the art of a removed package, a superseded image, a stray file
            if _digest(base_path) == seen:
                return listed, problems
            # The web release moved while this ran (a deploy switched `current`): what was just written was
            # derived from the release that is no longer served. Derive it again, from the one that is.
        raise OverlayError('the release catalog kept changing while the effective catalog was written')
    except BaseException as exc:
        try:
            remove(target)
            try:
                prune_art(Path(out_dir) / ART_DIR_NAME, set())      # no overlay advertises it any more
            except OSError:
                pass                                                 # content-addressed and harmless; the next refresh prunes
        except OSError as gone:
            raise OverlayError(f'the effective catalog failed ({exc}) and {target} could not be removed ({gone}); '
                               'remove it by hand') from exc
        if isinstance(exc, OverlayError):
            raise
        if isinstance(exc, Exception):
            raise OverlayError(f'the effective catalog could not be produced ({type(exc).__name__}: {exc}); '
                               f'{target} was removed, so the release catalog is served') from exc
        raise


def _art_wrong(art_dir, art):
    """What differs between the art directory and the images the effective catalog names."""
    present = _art_present(art_dir)
    wrong = [f'{art_dir / rel} is missing or changed: run refresh' for rel in sorted(art)
             if rel not in present or not _same_file(art_dir / rel, art[rel])]
    wrong += [f'{art_dir / rel} is not named by any listed package: run refresh' for rel in sorted(present - set(art))]
    return wrong


def check(out_dir, base_path, records_dir, problems_out=None, **kw):
    """[] when the overlay is exactly what `refresh` would write now (including: absent when no
    package is to be listed); otherwise what is wrong."""
    target = Path(out_dir) / FILE_NAME
    text, _, problems, art = _effective(base_path, records_dir, **kw)
    if problems_out is not None:
        problems_out.extend(problems)         # packages left out of the overlay and why (not a staleness)
    have = target.read_text(encoding='utf-8') if target.is_file() else None
    wrong = _art_wrong(Path(out_dir) / ART_DIR_NAME, art)
    if wrong:
        return wrong
    if have == text:
        return []
    if text is None:
        return [f'{target} exists but no installed package is to be listed: run refresh']
    if have is None:
        return [f'{target} is missing: run refresh']
    return [f'{target} is stale (the release catalog or an install record changed): run refresh']


def _apply(layout, base_path, out_dir, owner, **kw):
    listed, problems = refresh(out_dir, base_path, layout.records_dir, games_root=layout.root_text(), owner=owner,
                               disk_root=layout.games_root, **kw)
    lines = [f'catalog: the effective catalog lists {", ".join(listed)}' if listed
             else 'catalog: no package is listed; the release catalog is served as it is']
    return listed, problems, lines + [f'catalog: {p}' for p in problems]


def after_change(layout, base_path=DEFAULT_BASE, out_dir=DEFAULT_DIR, owner=installed._DEFAULT, **kw):
    """For install-game, after a change to the install records. Returns the lines to show; raises
    OverlayError (overlay already removed) when it cannot be written."""
    return _apply(layout, base_path, out_dir, owner, **kw)[2]


def best_effort(layout, base_path, out_dir, owner, **kw):
    """After a remove that did not finish: bring the overlay in step with the records as they are
    now, and say nothing if that fails either (the overlay is then absent, and the original failure
    is what the operator must see)."""
    try:
        _apply(layout, base_path, out_dir, owner, **kw)
    except Exception:
        pass


def publish_or_undo(layout, base_path, out_dir, owner, package_id, undo, **kw):
    """After a successful install of `package_id`: write the effective catalog. If that fails, or
    the package itself cannot be listed (its row is refused: a game nobody can see on a phone is
    worse than none), the install is not left half done: `undo(package_id)` removes it again, the
    overlay is refreshed once more for the packages that remain, and OverlayError says what
    happened. Fail closed."""
    try:
        listed, problems, lines = _apply(layout, base_path, out_dir, owner, **kw)
        if package_id in listed:
            return lines
        why = '; '.join(p for p in problems if p.startswith(f'{package_id}:')) or f'{package_id} is not listed'
        failure = OverlayError(why)
    except OverlayError as exc:
        failure = exc
    try:
        undo(package_id)
    except Exception as bad:
        raise OverlayError(f'{failure}; and removing {package_id} again failed ({type(bad).__name__}); '
                           f'run "install-game remove {package_id}"') from failure
    try:
        _apply(layout, base_path, out_dir, owner, **kw)
    except OverlayError:
        pass                                    # the overlay is absent; the release catalog is served
    raise OverlayError(f'{failure}; {package_id} was removed again, nothing is left installed') from failure


def main(argv=None, out=None, err=None):
    out, err = out or sys.stdout, err or sys.stderr
    ap = argparse.ArgumentParser(prog='catalog-overlay', description=__doc__.split('\n')[0])
    ap.add_argument('command', choices=('refresh', 'check', 'show'))
    ap.add_argument('--base', default=DEFAULT_BASE, help='the release catalog.json (default: the served release)')
    ap.add_argument('--out-dir', default=DEFAULT_DIR)
    ap.add_argument('--records-dir', default=installed.DEFAULT_RECORDS_DIR)
    ap.add_argument('--games-root', default=installed.DEFAULT_GAMES_ROOT)
    ap.add_argument('--lock-file', default='/run/avrana-install-game.lock', help=argparse.SUPPRESS)
    ap.add_argument('--wait', type=float, default=0, metavar='SECONDS',
                    help='refresh: wait up to this long for a running install-game instead of refusing (default: do not wait)')
    a = ap.parse_args(argv)
    kw = {'games_root': a.games_root}
    try:
        if a.command == 'show':
            text, _, problems = effective(a.base, a.records_dir, **kw)
            for p in problems:
                print(f'catalog-overlay: {p}', file=err)
            out.write(text if text is not None else Path(a.base).read_text(encoding='utf-8'))
            return 0
        if a.command == 'check':
            notes = []
            wrong = check(a.out_dir, a.base, a.records_dir, notes, **kw)
            for item in notes:
                print(f'catalog-overlay: warning: {item}', file=err)
            for item in wrong:
                print(f'catalog-overlay: {item}', file=err)
            if not wrong:
                print('catalog-overlay: current', file=out)
            return 1 if wrong else 0
        if os.name == 'posix' and os.geteuid() != 0:
            print('catalog-overlay: refresh must run as root (use sudo)', file=err)
            return 1
        from avrana.ops import install_game      # the same lock as install and remove (taken here, never inside them)
        with install_game.locked(a.lock_file, wait=a.wait):
            listed, problems = refresh(a.out_dir, a.base, a.records_dir, **kw)
        print('catalog-overlay: lists ' + (', '.join(listed) if listed else 'no package (overlay removed)'), file=out)
        for p in problems:
            print(f'catalog-overlay: {p}', file=err)
        return 0
    except OverlayError as exc:
        print(f'catalog-overlay: {exc}', file=err)
        return 1
    except Exception as exc:                  # includes the lock being held (install_game.Refused)
        print(f'catalog-overlay: failed: {type(exc).__name__}: {exc}', file=err)
        return 1


if __name__ == '__main__':
    sys.exit(main())
