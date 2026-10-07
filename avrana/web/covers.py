"""Owner-supplied game covers (AVR-306): box art the owner has a copy of, never committed.

A cover is one image file named for the game it stands for, in one folder:

    <game id>.jpg | .jpeg | .png | .webp | .avif

On a development machine the folder is web/party/covers/ (ignored by Git, served by the dev
server). On the appliance it is /srv/avrana/covers, beside the owner's ROM, and
ops/install-party-web.sh copies it into each web release. It is the one thing in a release that
does not come from a commit, so what may pass is narrow: a regular file (never a link), a game-id
name, at most MAX_BYTES, whose first bytes are a JPEG, PNG, WebP or AVIF picture. Anything else
is left out and named; a bad or missing folder never fails a build.

A picture saved from somewhere is often not what its name says (a WebP called .jpg). What it is
decides: it is published as <game id>.<the extension of what it really is>, so it is always
served as its true type.

The shell reads covers/index.json ({"schema": "avrana.covers/v0", "covers": {id: path}}), which
the build and the dev server write from the same scan, so a page never has to guess at a file.
"""
import json
import os
import re
import shutil
import stat
from pathlib import Path

SCHEMA = 'avrana.covers/v0'
NAME = re.compile(r'^([a-z][a-z0-9_-]{0,39})\.(jpg|jpeg|png|webp|avif)$')   # the id: avrana.contracts.game.ID
MAX_BYTES = 1024 * 1024
MAX_FILES = 64
EXTENSION = {'jpeg': 'jpg', 'png': 'png', 'webp': 'webp', 'avif': 'avif'}
TYPES = {'jpg': 'image/jpeg', 'png': 'image/png', 'webp': 'image/webp', 'avif': 'image/avif'}


class CoverError(ValueError):
    pass


def kind(head):
    """The picture type these first bytes are, or None."""
    if head[:3] == b'\xff\xd8\xff':
        return 'jpeg'
    if head[:8] == b'\x89PNG\r\n\x1a\n':
        return 'png'
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'webp'
    if head[4:8] == b'ftyp' and head[8:12] in (b'avif', b'avis'):
        return 'avif'
    return None


def read(path):
    """One cover, checked as it is read: (its bytes, the name it is published under).
    CoverError says why it is not one."""
    path = Path(path)
    match = NAME.match(path.name)
    if not match:
        raise CoverError('its name is not <game id>.jpg, .jpeg, .png, .webp or .avif')
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            raise CoverError('it is not a plain file (links are never followed)')
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0)
        fd = os.open(path, flags)
    except OSError as exc:
        raise CoverError(f'it cannot be read ({exc.strerror or exc})') from None
    with os.fdopen(fd, 'rb') as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise CoverError('it is not a plain file (links are never followed)')
        data = handle.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise CoverError(f'it is larger than {MAX_BYTES // 1024} KB')
    what = kind(data)
    if what is None:
        raise CoverError('it is not a JPEG, PNG, WebP or AVIF picture')
    return data, f'{match.group(1)}.{EXTENSION[what]}'


def scan(folder):
    """What a covers folder holds: ({game id: (file name, published name)}, [why each other file
    was left out]). A folder that is missing or cannot be listed holds nothing; a folder inside
    it is not looked in."""
    found, skipped = {}, []
    if folder is None:
        return found, skipped
    folder = Path(folder)
    try:
        entries = sorted(folder.iterdir())
    except OSError:
        return found, skipped
    for path in entries:
        if path.name == 'index.json' or (path.is_dir() and not path.is_symlink()):
            continue
        try:
            _, published = read(path)
        except CoverError as exc:
            skipped.append(f'{path.name}: {exc}')
            continue
        game = NAME.match(path.name).group(1)
        if game in found:
            skipped.append(f'{path.name}: {found[game][0]} is already the cover for {game}')
        elif len(found) >= MAX_FILES:
            skipped.append(f'{path.name}: there are already {MAX_FILES} covers')
        else:
            found[game] = (path.name, published)
    return found, skipped


def index(found):
    """The document the shell reads."""
    return {'schema': SCHEMA, 'covers': {game: f'covers/{published}' for game, (_, published) in sorted(found.items())}}


def install(out, folder):
    """Make `out` a release's covers directory: checked copies of what `folder` holds, and
    index.json. Whatever was in `out` goes. Returns why each file left out was left out."""
    out = Path(out)
    if out.is_symlink() or out.is_file():
        out.unlink()
    elif out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    found, skipped = scan(folder)
    kept = {}
    for game, (name, _) in found.items():
        try:
            data, published = read(Path(folder) / name)   # read again: what is published is what was checked
        except CoverError as exc:
            skipped.append(f'{name}: {exc}')
            continue
        (out / published).write_bytes(data)
        kept[game] = (name, published)
    (out / 'index.json').write_text(json.dumps(index(kept), indent=2) + '\n', encoding='utf-8')
    return skipped
