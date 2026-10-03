"""Documentation metadata rules added for the agent workflow (AVR-234): `supersedes`,
`last_verified`, archive citations from current documents, the historical-edit gate and the
informational staleness report. Same mutation style as test_repo_check.py."""
from datetime import date, timedelta
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_repo_check import REPO, checker

ARCHIVE = 'docs/archive/handoffs/2026-09-25-claude-log.md'


class Metadata(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = checker.repo_files(REPO)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.files = set(type(self).files)
        for path in self.files:
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / path, target)
        self.manifest = json.loads((self.root / 'docs/manifest.json').read_text(encoding='utf-8'))

    def entry(self, path):
        return next(e for e in self.manifest['documents'] if e['path'] == path)

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')
        self.files.add(path)

    def check(self):
        self.write('docs/manifest.json', json.dumps(self.manifest))
        return checker.check_repository(self.root, self.files)

    def test_valid_supersedes_and_last_verified_pass(self):
        self.entry('docs/WORKFLOW.md')['supersedes'] = [ARCHIVE]
        self.entry('docs/WORKFLOW.md')['last_verified'] = date.today().isoformat()
        self.assertEqual([], self.check())

    def test_supersedes_must_name_an_archived_manifest_document(self):
        self.entry('docs/WORKFLOW.md')['supersedes'] = ['docs/nowhere.md']
        self.assertTrue(any('supersedes unknown document' in e for e in self.check()))
        self.entry('docs/WORKFLOW.md')['supersedes'] = ['docs/TESTING.md']
        self.assertTrue(any('still classified current' in e for e in self.check()))
        self.entry('docs/WORKFLOW.md')['supersedes'] = 'docs/TESTING.md'
        self.assertTrue(any('non-empty list' in e for e in self.check()))

    def test_last_verified_is_a_past_iso_date_and_staleness_never_fails(self):
        self.entry('docs/WORKFLOW.md')['last_verified'] = (date.today() + timedelta(days=1)).isoformat()
        self.assertTrue(any('last_verified' in e for e in self.check()))
        self.entry('docs/WORKFLOW.md')['last_verified'] = '2020-01-01'
        self.assertEqual([], self.check())
        rows = checker.staleness(self.root, 30)
        self.assertIn(('docs/WORKFLOW.md', '2020-01-01, %d days ago' % (date.today() - date(2020, 1, 1)).days), rows)
        self.assertTrue(any(why == 'never recorded' for _, why in rows))

    def test_current_document_citing_an_archive_as_authority_fails(self):
        self.write('docs/WORKFLOW.md', '# Workflow\nFollow [the plan](archive/handoffs/2026-09-25-claude-log.md).\n')
        errors = self.check()
        self.assertTrue(any('cites an archived document without labelling it as history' in e for e in errors), errors)
        self.write('docs/WORKFLOW.md', '# Workflow\nThe historical [handoff](archive/handoffs/2026-09-25-claude-log.md) is preserved.\n')
        self.assertEqual([], self.check())

    def test_archived_documents_may_cite_each_other_freely(self):
        self.write(ARCHIVE, '# Old\nSee [the other](../publication/README.md) plan.\n')
        self.assertFalse(any('cites an archived' in e for e in self.check()))


class HistoricalGate(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@x', GIT_COMMITTER_NAME='t',
                        GIT_COMMITTER_EMAIL='t@x', GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
        self.git('init', '-q', '-b', 'main')
        for path in ('docs/archive/old.md', 'docs/findings/2026-01-01-thing.md', 'docs/SYSTEM.md'):
            (self.repo / path).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / path).write_text('# one\n')
        self.git('add', '.')
        self.git('commit', '-q', '-m', 'base')
        self.base = self.git('rev-parse', 'HEAD')
        self.git('checkout', '-q', '-b', 'topic')

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.repo), *args], check=True, capture_output=True,
                              env=self.env).stdout.decode().strip()

    def commit(self, message='change'):
        self.git('add', '-A')
        self.git('commit', '-q', '-m', message)

    def test_new_findings_and_current_doc_edits_are_free(self):
        (self.repo / 'docs/findings/2026-10-03-new.md').write_text('# new\n')
        (self.repo / 'docs/SYSTEM.md').write_text('# two\n')
        self.commit()
        self.assertEqual([], checker.historical_edits(self.repo, self.base))

    def test_modifying_or_deleting_history_is_flagged(self):
        (self.repo / 'docs/archive/old.md').write_text('# rewritten as current\n')
        (self.repo / 'docs/findings/2026-01-01-thing.md').unlink()
        self.commit()
        touched = checker.historical_edits(self.repo, self.base)
        self.assertEqual(sorted(touched), [('D', 'docs/findings/2026-01-01-thing.md'), ('M', 'docs/archive/old.md')])

    def test_a_move_counts_as_an_intentional_edit(self):
        self.git('mv', 'docs/archive/old.md', 'docs/archive/older.md')
        self.commit()
        touched = checker.historical_edits(self.repo, self.base)
        self.assertEqual([status for status, _ in touched], ['R'])


if __name__ == '__main__':
    unittest.main()
