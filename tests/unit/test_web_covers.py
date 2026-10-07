"""Owner-supplied game covers (AVR-306): what may pass from the covers folder into a release,
and what the dev server serves of it."""
import json
import subprocess
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

import threading

from avrana import WEB_DIR
from avrana.web import build, covers, devserver

PNG = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89'
       b'\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82')
JPEG = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00' + b'\x00' * 32
WEBP = b'RIFF\x24\x00\x00\x00WEBPVP8 ' + b'\x00' * 24
AVIF = b'\x00\x00\x00\x1cftypavif\x00\x00\x00\x00mif1avifmiaf' + b'\x00' * 16


class Kinds(unittest.TestCase):
    def test_a_picture_is_known_by_its_first_bytes(self):
        self.assertEqual([covers.kind(b) for b in (JPEG, PNG, WEBP, AVIF)], ['jpeg', 'png', 'webp', 'avif'])
        for junk in (b'', b'GIF89a', b'<svg xmlns="http://www.w3.org/2000/svg"/>', b'<!doctype html>', b'RIFF\x00\x00\x00\x00WAVE', b'\x00\x00\x00\x1cftypmp42'):
            self.assertIsNone(covers.kind(junk), junk)


class Folder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / 'covers'
        self.folder.mkdir()

    def put(self, name, data):
        (self.folder / name).write_bytes(data)

    def test_a_cover_is_a_picture_named_for_a_game(self):
        self.put('ps1-worms.jpg', JPEG)
        self.put('arcade-gauntlet2.png', PNG)
        self.put('expo.webp', WEBP)
        self.put('bluff.avif', AVIF)
        found, skipped = covers.scan(self.folder)
        self.assertEqual(skipped, [])
        self.assertEqual(covers.index(found), {'schema': 'avrana.covers/v0', 'covers': {
            'arcade-gauntlet2': 'covers/arcade-gauntlet2.png', 'bluff': 'covers/bluff.avif',
            'expo': 'covers/expo.webp', 'ps1-worms': 'covers/ps1-worms.jpg'}})

    def test_what_a_picture_is_decides_how_it_is_published_not_its_name(self):
        self.put('ps1-bomberman.jpg', WEBP)       # a WebP saved as .jpg, as pictures from the web often are
        self.put('arcade-gauntlet2.jpeg', AVIF)
        self.put('bluff.jpeg', JPEG)
        found, skipped = covers.scan(self.folder)
        self.assertEqual(skipped, [])
        self.assertEqual(found, {'ps1-bomberman': ('ps1-bomberman.jpg', 'ps1-bomberman.webp'),
                                 'arcade-gauntlet2': ('arcade-gauntlet2.jpeg', 'arcade-gauntlet2.avif'),
                                 'bluff': ('bluff.jpeg', 'bluff.jpg')})
        out = Path(self.tmp.name) / 'out'
        self.assertEqual(covers.install(out, self.folder), [])
        self.assertEqual({p.name for p in out.iterdir()}, {'index.json', 'ps1-bomberman.webp', 'arcade-gauntlet2.avif', 'bluff.jpg'})
        self.assertEqual((out / 'ps1-bomberman.webp').read_bytes(), WEBP)

    def test_everything_else_is_left_out_and_named(self):
        self.put('bluff.png', PNG)
        self.put('expo.jpg', b'<script>alert(1)</script>')
        self.put('page.html', b'<!doctype html>')
        self.put('vector.svg', b'<svg xmlns="http://www.w3.org/2000/svg"/>')
        self.put('Pong.png', PNG)
        self.put('ps1 worms.png', PNG)
        self.put('.hidden.png', PNG)
        self.put('big.png', PNG + b'\x00' * covers.MAX_BYTES)
        self.put('bluff.jpg', JPEG)               # a second cover for the same game
        self.put('index.json', b'{"covers": {"expo": "covers/../../etc/passwd"}}')   # never read
        (self.folder / 'originals').mkdir()
        (self.folder / 'originals' / 'expo.png').write_bytes(PNG)                     # not looked in
        found, skipped = covers.scan(self.folder)
        self.assertEqual(found, {'bluff': ('bluff.jpg', 'bluff.jpg')})                # the first by name
        left = {line.split(':')[0] for line in skipped}
        self.assertEqual(left, {'expo.jpg', 'page.html', 'vector.svg', 'Pong.png', 'ps1 worms.png', '.hidden.png', 'big.png', 'bluff.png'})
        self.assertIn('expo.jpg: it is not a JPEG, PNG, WebP or AVIF picture', skipped)
        self.assertIn('big.png: it is larger than 1024 KB', skipped)
        self.assertIn('bluff.png: bluff.jpg is already the cover for bluff', skipped)

    def test_the_whole_name_is_checked_and_a_strange_one_is_shown_quoted(self):
        self.assertIsNone(covers.NAME.fullmatch('bluff.png\n'))
        with self.assertRaisesRegex(covers.CoverError, 'its name is not'):
            covers.read(self.folder / 'bluff.png\n')          # refused by name, before the disk is asked
        self.assertEqual(covers.shown('bluff.png'), 'bluff.png')
        self.assertEqual(covers.shown('a\x1b[2Jb.png\n'), "'a\\x1b[2Jb.png\\n'")

    def test_a_file_that_cannot_be_read_is_left_out_and_never_fails_the_scan(self):
        self.put('bluff.png', PNG)
        self.put('expo.png', PNG)
        real = covers.os.fstat

        def fstat(fd):
            raise OSError(5, 'Input/output error')
        with mock.patch.object(covers.os, 'fstat', fstat):
            found, skipped = covers.scan(self.folder)
        self.assertEqual(found, {})
        self.assertEqual(skipped, ['bluff.png: it cannot be read (Input/output error)', 'expo.png: it cannot be read (Input/output error)'])
        self.assertIs(covers.os.fstat, real)

    def test_past_the_limit_a_file_is_not_opened(self):
        for i in range(covers.MAX_FILES + 3):
            self.put(f'game{i:03d}.png', PNG)
        opened = []
        real = covers.os.open

        def counting(path, *a, **kw):
            opened.append(Path(path).name)
            return real(path, *a, **kw)
        with mock.patch.object(covers.os, 'open', counting):
            found, skipped = covers.scan(self.folder)
        self.assertEqual((len(found), len(skipped), len(opened)), (covers.MAX_FILES, 3, covers.MAX_FILES))

    def test_a_link_is_never_followed(self):
        secret = Path(self.tmp.name) / 'secret.png'
        secret.write_bytes(PNG)
        try:
            (self.folder / 'bluff.png').symlink_to(secret)
        except OSError:
            self.skipTest('this host cannot make a symbolic link')
        found, skipped = covers.scan(self.folder)
        self.assertEqual(found, {})
        self.assertEqual(skipped, ['bluff.png: it is not a plain file (links are never followed)'])
        out = Path(self.tmp.name) / 'out'
        covers.install(out, self.folder)
        self.assertEqual({p.name for p in out.iterdir()}, {'index.json'})

    def test_no_more_than_the_limit(self):
        for i in range(covers.MAX_FILES + 2):
            self.put(f'game{i:03d}.png', PNG)
        found, skipped = covers.scan(self.folder)
        self.assertEqual(len(found), covers.MAX_FILES)
        self.assertEqual(len(skipped), 2)

    def test_a_missing_or_unreadable_folder_holds_nothing(self):
        for folder in (None, Path(self.tmp.name) / 'nowhere', self.folder / 'file-not-folder'):
            self.assertEqual(covers.scan(folder), ({}, []))
        self.put('file-not-folder', b'x')
        self.assertEqual(covers.scan(self.folder / 'file-not-folder'), ({}, []))

    def test_install_replaces_whatever_was_there(self):
        out = Path(self.tmp.name) / 'out'
        (out / 'originals').mkdir(parents=True)
        (out / 'originals' / 'x.png').write_bytes(PNG)
        (out / 'stale.png').write_bytes(PNG)
        (out / 'index.json').write_text('{"covers": {"stale": "covers/stale.png"}}')
        self.put('bluff.png', PNG)
        self.assertEqual(covers.install(out, self.folder), [])
        self.assertEqual({p.name for p in out.rglob('*')}, {'index.json', 'bluff.png'})
        self.assertEqual(json.loads((out / 'index.json').read_text())['covers'], {'bluff': 'covers/bluff.png'})


class Build(unittest.TestCase):
    def test_a_build_carries_checked_covers_and_their_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'covers'
            folder.mkdir()
            (folder / 'ps1-worms.jpg').write_bytes(WEBP)
            (folder / 'expo.png').write_bytes(b'nope')
            out, notes = Path(tmp) / 'out', []
            build.build(out, 'b1', covers=folder, notes=notes)
            self.assertEqual(notes, ['expo.png: it is not a JPEG, PNG, WebP or AVIF picture'])
            self.assertEqual({p.name for p in (out / 'covers').iterdir()}, {'index.json', 'ps1-worms.webp'})
            self.assertEqual(json.loads((out / 'covers' / 'index.json').read_text()),
                             {'schema': 'avrana.covers/v0', 'covers': {'ps1-worms': 'covers/ps1-worms.webp'}})
            self.assertEqual(build.check_tree(out), [])

    def test_a_build_with_no_covers_has_an_empty_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            build.build(out, 'b1', covers=Path(tmp) / 'nowhere')
            self.assertEqual([p.name for p in (out / 'covers').iterdir()], ['index.json'])
            self.assertEqual(json.loads((out / 'covers' / 'index.json').read_text())['covers'], {})

    def test_git_holds_no_cover_only_the_empty_index(self):
        # the folder is ignored, but `git add -f` would still take a picture: this says no
        try:
            listed = subprocess.run(['git', '-C', str(WEB_DIR.parents[1]), 'ls-files', '--', 'web/party/covers'],
                                    capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            self.skipTest('git is not here')
        if listed.returncode != 0:
            self.skipTest('this is not a Git checkout')
        self.assertEqual(listed.stdout.split(), ['web/party/covers/index.json'])

    def test_the_tracked_index_is_empty(self):
        # what Git holds names no cover: covers reach a release only through the covers folder
        self.assertEqual(json.loads((WEB_DIR / 'covers' / 'index.json').read_text(encoding='utf-8')),
                         {'schema': 'avrana.covers/v0', 'covers': {}})


class DevServer(unittest.TestCase):
    def serve(self, **kw):
        server = devserver.make_server(**kw)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f'http://127.0.0.1:{server.server_address[1]}'

    def get(self, url):
        try:
            with urllib.request.urlopen(url, timeout=5) as res:
                return res.status, res.headers.get('Content-Type'), res.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers.get('Content-Type'), exc.read()

    def test_it_serves_the_index_and_only_the_covers_it_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / 'ps1-bomberman.jpg').write_bytes(WEBP)
            (folder / 'expo.jpg').write_bytes(b'nope')
            (folder / 'notes.txt').write_bytes(b'private')
            base = self.serve(covers=folder)
            status, ctype, body = self.get(base + '/party/covers/index.json')
            self.assertEqual((status, ctype), (200, 'application/json'))
            self.assertEqual(json.loads(body)['covers'], {'ps1-bomberman': 'covers/ps1-bomberman.webp'})
            self.assertEqual(self.get(base + '/party/covers/ps1-bomberman.webp'), (200, 'image/webp', WEBP))
            for name in ('ps1-bomberman.jpg', 'expo.jpg', 'notes.txt', '../index.html', 'nothing.png'):
                self.assertEqual(self.get(base + '/party/covers/' + name)[0], 404, name)

    def test_under_test_controls_a_developers_own_covers_are_not_served(self):
        # browser tests run against --test-controls: what a developer keeps in web/party/covers/
        # must never change what they see
        base = self.serve(test_controls=True)
        self.assertEqual(json.loads(self.get(base + '/party/covers/index.json')[2]), {'schema': 'avrana.covers/v0', 'covers': {}})
        fixture = Path(__file__).resolve().parents[1] / 'fixtures' / 'covers'
        named = self.serve(test_controls=True, covers=fixture)
        self.assertEqual(json.loads(self.get(named + '/party/covers/index.json')[2])['covers'],
                         {'arcade-gauntlet2': 'covers/arcade-gauntlet2.png', 'ps1-worms': 'covers/ps1-worms.png'})
        self.assertEqual(self.get(named + '/party/covers/ps1-worms.png')[:2], (200, 'image/png'))


if __name__ == '__main__':
    unittest.main()
