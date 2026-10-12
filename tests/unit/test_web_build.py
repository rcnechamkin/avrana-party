"""Tier 1: the Full Mode web shell build, precache list and install script."""
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from avrana import REPO_ROOT, WEB_DIR
from avrana.web import build

JARGON = re.compile(r'\b(seat|session|runtime|server|websocket|presence|manifest|launch(ing)?|backend|token|slot)\b', re.I)


PNG = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89'
       b'\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82')


class ShellFiles(unittest.TestCase):
    def test_source_tree_is_consistent(self):
        self.assertEqual(build.check_tree(WEB_DIR), [])

    def test_every_shell_file_is_precached(self):
        precached = set(build.shell_list((WEB_DIR / 'sw.js').read_text(encoding='utf-8')))
        files = {p.relative_to(WEB_DIR).as_posix() for p in WEB_DIR.rglob('*') if p.is_file()}
        # The HTTP doorway (ADR 0012) is never in the offline copy: it exists for plain HTTP, where
        # there is no service worker, and its one job is to ask the network.
        doorway = {'doorway/index.html', 'doorway/doorway.js', 'lib/doorway.js'}
        # The owner's game covers (AVR-306) are ignored by Git and never precached; a developer
        # may have some here. Only the index that lists them is a shell file.
        files = {f for f in files if not f.startswith('covers/') or f == 'covers/index.json'}
        self.assertIn('covers/index.json', precached)
        self.assertEqual(files - precached - {'sw.js'} - doorway, set(), 'add new shell files to SHELL in sw.js')
        self.assertEqual(precached & doorway, set())
        self.assertNotIn('sw.js', precached)
        self.assertFalse(any(p.startswith('api/') for p in precached))

    def test_pages_use_no_inline_script_or_style(self):
        # nginx sends a CSP without 'unsafe-inline'.
        for page in WEB_DIR.rglob('*.html'):
            text = page.read_text(encoding='utf-8')
            self.assertNotRegex(text, r'<script(?![^>]*\bsrc=)[^>]*>', page.name)
            self.assertNotIn('style=', text, page.name)
            self.assertNotRegex(text, r'\son[a-z]+=', page.name)

    def test_guest_page_has_no_machinery_words(self):
        text = re.sub(r'<[^>]+>', ' ', (WEB_DIR / 'index.html').read_text(encoding='utf-8'))
        self.assertIsNone(JARGON.search(text))
        # app.js, the frame's sentences (lib/frame.js: who is here, the Party control's name) and
        # the Library's (lib/library.js: headings, filter words, what a title means on this phone)
        for name, quotes in (('app.js', "'"), ('lib/frame.js', "'`"), ('lib/library.js', "'`")):
            source = (WEB_DIR / name).read_text(encoding='utf-8')
            for quote in quotes:
                for literal in re.findall(quote + '([^' + quote + '\\n]{12,})' + quote, source):
                    if ' ' in literal:  # sentences only, not identifiers or selectors
                        self.assertIsNone(JARGON.search(literal), f'{name}: {literal}')


class NoCredentialsInUrls(unittest.TestCase):
    # ADR 0003: credentials never appear in URLs (nginx logs query strings).
    PATTERN = re.compile(r'''[?&](token|ticket|key|secret|reconnectionToken|_authToken)=|'''
                         r'''searchParams\.(set|append)\(\s*['"](token|ticket|key|secret)''', re.I)

    def test_shipped_pages_and_scripts(self):
        files = [p for p in list(WEB_DIR.rglob('*')) + list((REPO_ROOT / 'arcade').glob('*.html'))
                 if p.suffix in ('.html', '.js')]
        self.assertTrue(files)
        for path in files:
            self.assertIsNone(self.PATTERN.search(path.read_text(encoding='utf-8')), path)


class Build(unittest.TestCase):
    def test_stamp_and_kill_switch(self):
        sw = (WEB_DIR / 'sw.js').read_text(encoding='utf-8')
        stamped = build.stamp(sw, 'abc123')
        self.assertIn("const BUILD = 'abc123';", stamped)
        self.assertIn('const ENABLED = true;', stamped)
        self.assertIn('const ENABLED = false;', build.stamp(sw, 'abc123', service_worker=False))
        with self.assertRaises(build.BuildError):
            build.stamp(sw.replace("const BUILD = 'dev';", ''), 'x')

    def test_symlinks_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'src'
            import shutil
            shutil.copytree(WEB_DIR, src)
            (src / 'leak').symlink_to('/etc/hostname')
            self.assertTrue(any('symlink' in p for p in build.check_tree(src)))
            with self.assertRaises(build.BuildError):
                build.build(Path(tmp) / 'out', 'x', source=src)

    def test_build_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            version = build.build(out, 'b1', commit='f' * 40)
            self.assertEqual(version['build'], 'b1')
            self.assertTrue(version['serviceWorker'])
            self.assertEqual(json.loads((out / 'version.json').read_text())['commit'], 'f' * 40)
            self.assertIn("const BUILD = 'b1';", (out / 'sw.js').read_text())
            self.assertEqual(build.check_tree(out), [])
            with self.assertRaises(build.BuildError):
                build.build(out, 'b2')  # never overwrite a release
            with self.assertRaises(build.BuildError):
                build.build(Path(tmp) / 'bad', 'bad id!')
        # the source tree stays untouched
        self.assertIn("const BUILD = 'dev';", (WEB_DIR / 'sw.js').read_text())


class InstallScript(unittest.TestCase):
    def run_script(self, dest, *args, covers=None):
        # never the machine's own /srv/avrana/covers: a folder the test names, or one that is not there
        env = dict(os.environ, AVRANA_WEB_ROOT=str(dest), AVRANA_ALLOW_DIRTY='1',
                   AVRANA_COVERS_DIR=str(covers if covers is not None else Path(dest).parent / 'no-covers'))
        return subprocess.run(['bash', str(REPO_ROOT / 'ops' / 'install-party-web.sh'), *args], cwd=REPO_ROOT,
                              env=env, capture_output=True, text=True, timeout=60)

    def test_install_kill_and_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'web'
            first = self.run_script(dest, str(REPO_ROOT))
            self.assertEqual(first.returncode, 0, first.stderr)
            current = dest / 'current'
            self.assertTrue(current.is_symlink())
            v1 = json.loads((current / 'version.json').read_text())
            self.assertTrue(v1['serviceWorker'])
            self.assertEqual(len(v1['build']), 12)
            killed = self.run_script(dest, '--kill', str(REPO_ROOT))
            self.assertEqual(killed.returncode, 0, killed.stderr)
            self.assertIn('const ENABLED = false;', (current / 'sw.js').read_text())
            self.assertFalse(json.loads((current / 'version.json').read_text())['serviceWorker'])
            back = self.run_script(dest, '--rollback')
            self.assertEqual(back.returncode, 0, back.stderr)
            self.assertIn('const ENABLED = true;', (current / 'sw.js').read_text())
            releases = sorted(p for p in (dest / 'releases').iterdir() if not p.name.startswith('.'))
            self.assertEqual(len(releases), 2)
            self.assertEqual(current.resolve(), releases[0].resolve())
            self.assertFalse(any(p.name.startswith('.build') for p in (dest / 'releases').iterdir()))

    def test_only_committed_files_are_published(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'repo'
            subprocess.run(['git', 'clone', '-q', str(REPO_ROOT), str(repo)], check=True)
            (repo / 'web' / 'party' / '.env').write_text('SECRET=1')            # git-ignored
            (repo / 'web' / 'party' / 'notes.txt').write_text('draft')          # untracked
            (repo / 'web' / 'party' / 'host').symlink_to('/etc/hostname')       # untracked symlink
            (repo / 'web' / 'party' / 'covers' / 'bluff.png').write_bytes(PNG)  # git-ignored: the checkout is not the covers folder
            dest = Path(tmp) / 'web'
            out = self.run_script(dest, str(repo))
            self.assertEqual(out.returncode, 0, out.stderr)
            published = {p.name for p in (dest / 'current').rglob('*')}
            self.assertFalse({'.env', 'notes.txt', 'host', 'bluff.png'} & published, published)
            self.assertIn('index.html', published)
            self.assertEqual(json.loads((dest / 'current' / 'covers' / 'index.json').read_text())['covers'], {})

    def test_covers_come_only_from_the_named_folder_and_only_as_pictures(self):
        with tempfile.TemporaryDirectory() as tmp:
            covers = Path(tmp) / 'covers'
            covers.mkdir()
            (covers / 'bluff.png').write_bytes(PNG)
            (covers / 'expo.jpg').write_bytes(b'<script>alert(1)</script>')     # not a picture
            (covers / 'Not A Game.png').write_bytes(PNG)                        # not a game's name
            (covers / 'ps1-worms.png').symlink_to('/etc/hostname')              # never followed
            (covers / 'notes').mkdir()
            (covers / 'notes' / 'arcade-gauntlet2.png').write_bytes(PNG)        # not looked in
            dest = Path(tmp) / 'web'
            out = self.run_script(dest, str(REPO_ROOT), covers=covers)
            self.assertEqual(out.returncode, 0, out.stderr)                     # a bad cover never fails an install
            release = dest / 'current' / 'covers'
            self.assertEqual({p.name for p in release.rglob('*')}, {'index.json', 'bluff.png'})
            self.assertEqual(json.loads((release / 'index.json').read_text())['covers'], {'bluff': 'covers/bluff.png'})
            self.assertEqual((release / 'bluff.png').read_bytes(), PNG)
            self.assertFalse((release / 'bluff.png').is_symlink())
            for name in ('expo.jpg', 'Not A Game.png', 'ps1-worms.png'):
                self.assertIn(f'cover left out: {name}', out.stderr)
            # the next release is built from the folder as it then is; going back restores the covers of that release
            (covers / 'bluff.png').unlink()
            again = self.run_script(dest, str(REPO_ROOT), covers=covers)
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertEqual(json.loads((dest / 'current' / 'covers' / 'index.json').read_text())['covers'], {})
            back = self.run_script(dest, '--rollback')
            self.assertEqual(back.returncode, 0, back.stderr)
            self.assertEqual(json.loads((dest / 'current' / 'covers' / 'index.json').read_text())['covers'], {'bluff': 'covers/bluff.png'})

    def test_refuses_a_dirty_checkout_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'repo'
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            (repo / 'untracked').write_text('x')
            env = dict(os.environ, AVRANA_WEB_ROOT=str(Path(tmp) / 'web'))
            env.pop('AVRANA_ALLOW_DIRTY', None)
            out = subprocess.run(['bash', str(REPO_ROOT / 'ops' / 'install-party-web.sh'), str(repo)],
                                 env=env, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn('uncommitted', out.stderr)


if __name__ == '__main__':
    unittest.main()
