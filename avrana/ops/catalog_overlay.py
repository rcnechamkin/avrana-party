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
- No valid package, no overlay file: `refresh` removes it, so the appliance serves exactly the
  committed catalog.
- Written atomically: a hidden temporary file in the same directory, flushed and fsynced, made 0644,
  renamed, and the directory fsynced. Same inputs, same bytes (no timestamp). A reader sees the old
  file or the new one, never a part. If anything goes wrong while refreshing, the overlay is
  removed before the error is raised: absent and regenerable, never stale or half-written.
- The overlay is derived from the release catalog, so a new release or a rollback of the web shell
  makes it stale. `ops/install-party-web.sh` runs `refresh` after it switches `current`, and `check`
  says whether it is current.

Everything that touches the host is an argument, so the tests run in scratch directories.
"""
import argparse
import json
import os
import secrets
import sys
from pathlib import Path

from avrana import CONTRACTS_DIR
from avrana.avrgame import installed
from avrana.contracts import appliance as appliance_mod
from avrana.contracts import catalog, strictjson, vocabulary

DEFAULT_DIR = '/var/lib/avrana-party/catalog'
FILE_NAME = 'catalog.json'
DEFAULT_BASE = '/var/www/avrana-party/web/current/catalog.json'
MAX_BASE_BYTES = 4 * 1024 * 1024


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


def effective(base_path, records_dir, games_root=installed.DEFAULT_GAMES_ROOT, owner=installed._DEFAULT,
              appliance_path=catalog.DEFAULT_APPLIANCE, games_dir=None, strict_modes=None, repo_contracts=None):
    """(text, listed, problems). `text` is the effective catalog, or None when no package is to be
    listed (the release catalog is then served as it is). `listed` is the package ids in it."""
    doc = _base(base_path)
    vocab = vocabulary.load()
    repo = repo_contracts if repo_contracts is not None else catalog.load_contracts(games_dir or CONTRACTS_DIR / 'games', vocab)
    found = installed.load(str(records_dir), repo, vocab, games_root=games_root, owner=owner, strict_modes=strict_modes)
    problems = list(found.problems)
    appliance = appliance_mod.load(appliance_path, vocab)
    taken = {row.get('id') for row in doc['games'] if isinstance(row, dict)}
    rows, labels = [], {}
    for pid in sorted(found.records):
        if pid in taken or pid in repo:
            problems.append(f'{pid}: the catalog already has a game with this id; the package is not listed')
            continue
        try:
            one = catalog.build(vocab, appliance, {**repo, pid: found.contracts[pid]}, extra_grants={pid: found.grants[pid]})
        except ValueError as exc:
            problems.append(f'{pid}: not listed: {exc}')
            continue
        rows.append(next(g for g in one['games'] if g['id'] == pid))
        labels.update({k: v for k, v in one['labels'].items() if k not in doc['labels']})
    if not rows:
        return None, [], problems
    doc['games'] = [*doc['games'], *rows]
    doc['labels'] = {**doc['labels'], **{k: labels[k] for k in sorted(labels)}}
    return strictjson.dumps(doc), [row['id'] for row in rows], problems


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
    os.makedirs(path.parent, mode=0o755, exist_ok=True)
    tmp = path.with_name(f'.{path.name}.{secrets.token_hex(4)}.tmp')
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0)
                     | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'wb') as f:
            f.write(text.encode('utf-8'))
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


def refresh(out_dir, base_path, records_dir, **kw):
    """Make the overlay match the install records: write it, or remove it when no package is to be
    listed. Returns (listed ids, problems). On any failure the overlay is removed first and the
    error raised as OverlayError: the appliance then serves the release catalog, and `refresh`
    can be run again."""
    target = Path(out_dir) / FILE_NAME
    try:
        text, listed, problems = effective(base_path, records_dir, **kw)
        if text is None:
            remove(target)
        else:
            write_atomic(target, text)
        return listed, problems
    except BaseException as exc:
        try:
            remove(target)
        except OSError as gone:
            raise OverlayError(f'the effective catalog failed ({exc}) and {target} could not be removed ({gone}); '
                               'remove it by hand') from exc
        if isinstance(exc, OverlayError):
            raise
        if isinstance(exc, Exception):
            raise OverlayError(f'the effective catalog could not be produced ({type(exc).__name__}: {exc}); '
                               f'{target} was removed, so the release catalog is served') from exc
        raise


def check(out_dir, base_path, records_dir, **kw):
    """[] when the overlay is exactly what `refresh` would write now (including: absent when no
    package is to be listed); otherwise what is wrong."""
    target = Path(out_dir) / FILE_NAME
    text, _, _ = effective(base_path, records_dir, **kw)
    have = target.read_text(encoding='utf-8') if target.is_file() else None
    if have == text:
        return []
    if text is None:
        return [f'{target} exists but no installed package is to be listed: run refresh']
    if have is None:
        return [f'{target} is missing: run refresh']
    return [f'{target} is stale (the release catalog or an install record changed): run refresh']


def after_change(layout, base_path=DEFAULT_BASE, out_dir=DEFAULT_DIR, owner=installed._DEFAULT, **kw):
    """For install-game, after a change to the install records. Returns the lines to show; raises
    OverlayError (overlay already removed) when it cannot be written."""
    listed, problems = refresh(out_dir, base_path, layout.records_dir, games_root=layout.root_text(), owner=owner, **kw)
    lines = [f'catalog: the effective catalog lists {", ".join(listed)}' if listed
             else 'catalog: no package is listed; the release catalog is served as it is']
    return lines + [f'catalog: {p}' for p in problems]


def publish_or_undo(layout, base_path, out_dir, owner, package_id, undo, **kw):
    """After a successful install of `package_id`: write the effective catalog. If that fails the
    install is not left half done: `undo(package_id)` removes the package again (a game nobody can
    see on a phone is worse than none), the overlay is refreshed once more for the packages that
    remain, and OverlayError says what happened. Fail closed."""
    try:
        return after_change(layout, base_path, out_dir, owner, **kw)
    except OverlayError as exc:
        try:
            undo(package_id)
        except Exception as bad:
            raise OverlayError(f'{exc}; and removing {package_id} again failed ({type(bad).__name__}); '
                               f'run "install-game remove {package_id}"') from exc
        try:
            after_change(layout, base_path, out_dir, owner, **kw)
        except OverlayError:
            pass                                    # the overlay is absent; the release catalog is served
        raise OverlayError(f'{exc}; {package_id} was removed again, nothing is left installed') from exc


def main(argv=None, out=None, err=None):
    out, err = out or sys.stdout, err or sys.stderr
    ap = argparse.ArgumentParser(prog='catalog-overlay', description=__doc__.split('\n')[0])
    ap.add_argument('command', choices=('refresh', 'check', 'show'))
    ap.add_argument('--base', default=DEFAULT_BASE, help='the release catalog.json (default: the served release)')
    ap.add_argument('--out-dir', default=DEFAULT_DIR)
    ap.add_argument('--records-dir', default=installed.DEFAULT_RECORDS_DIR)
    ap.add_argument('--games-root', default=installed.DEFAULT_GAMES_ROOT)
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
            wrong = check(a.out_dir, a.base, a.records_dir, **kw)
            for item in wrong:
                print(f'catalog-overlay: {item}', file=err)
            if not wrong:
                print('catalog-overlay: current', file=out)
            return 1 if wrong else 0
        if os.name == 'posix' and os.geteuid() != 0:
            print('catalog-overlay: refresh must run as root (use sudo)', file=err)
            return 1
        listed, problems = refresh(a.out_dir, a.base, a.records_dir, **kw)
        print('catalog-overlay: lists ' + (', '.join(listed) if listed else 'no package (overlay removed)'), file=out)
        for p in problems:
            print(f'catalog-overlay: {p}', file=err)
        return 0
    except OverlayError as exc:
        print(f'catalog-overlay: {exc}', file=err)
        return 1
    except (OSError, ValueError) as exc:
        print(f'catalog-overlay: failed: {type(exc).__name__}: {exc}', file=err)
        return 1


if __name__ == '__main__':
    sys.exit(main())
