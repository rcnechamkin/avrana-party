"""Tier 1: the Full Mode web shell build, precache list and install script."""
import json
import os
import re
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from avrana import REPO_ROOT, WEB_DIR
from avrana.web import build

JARGON = re.compile(r'\b(seat|session|runtime|server|websocket|presence|manifest|launch(ing)?|backend|token|slot)\b', re.I)


class ShellFiles(unittest.TestCase):
    def test_source_tree_is_consistent(self):
        self.assertEqual(build.check_tree(WEB_DIR), [])

    def test_every_shell_file_is_precached(self):
        precached = set(build.shell_list((WEB_DIR / 'sw.js').read_text(encoding='utf-8')))
        files = {p.relative_to(WEB_DIR).as_posix() for p in WEB_DIR.rglob('*') if p.is_file()}
        self.assertEqual(files - precached - {'sw.js'}, set(), 'add new shell files to SHELL in sw.js')
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
        app = (WEB_DIR / 'app.js').read_text(encoding='utf-8')
        for literal in re.findall(r"'([^'\n]{12,})'", app):
            if ' ' in literal:  # sentences only, not identifiers or selectors
                self.assertIsNone(JARGON.search(literal), literal)


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
    def run_script(self, dest, *args):
        env = dict(os.environ, AVRANA_WEB_ROOT=str(dest), AVRANA_ALLOW_DIRTY='1')
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
            time.sleep(1.1)  # release directories are named by the second
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
