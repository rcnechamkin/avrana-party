"""tools/avr_context.py: the read-only context helper for `Implement AVR-N` (no network in tests)."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from avrana import REPO_ROOT

spec = importlib.util.spec_from_file_location('avr_context', REPO_ROOT / 'tools/avr_context.py')
ctx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ctx)

DESCRIPTION = """## Outcome

One paragraph.

## Acceptance Criteria

- a
- b

## Out of Scope

Nothing else.

## Repositories

avrana-party

## Tests Required

unit

## Dependencies

AVR-1

## Open Decisions

Which colour?
"""


class Sections(unittest.TestCase):
    def test_every_standard_section_is_found(self):
        found = ctx.sections(DESCRIPTION)
        self.assertEqual(list(found), list(ctx.SECTIONS))
        self.assertEqual(found['Outcome'], 'One paragraph.')
        self.assertEqual(found['Acceptance Criteria'], '- a\n- b')
        self.assertEqual(found['Open Decisions'], 'Which colour?')

    def test_missing_sections_are_none_not_invented(self):
        found = ctx.sections('## Problem\n\nOld template.\n')
        self.assertTrue(all(v is None for v in found.values()))
        self.assertTrue(all(v is None for v in ctx.sections(None).values()))


class Branches(unittest.TestCase):
    def test_branches_pair_by_the_avr_token_only(self):
        with tempfile.TemporaryDirectory() as temp:
            env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@x', GIT_COMMITTER_NAME='t',
                       GIT_COMMITTER_EMAIL='t@x', GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
            def git(*args):
                subprocess.run(['git', '-C', temp, *args], check=True, capture_output=True, env=env)
            git('init', '-q', '-b', 'main')
            Path(temp, 'f').write_text('x')
            git('add', 'f')
            git('commit', '-q', '-m', 'x')
            for name in ('fix/avr-13-seat', 'feat/avr-130-arcade', 'cnechamkin/avr-13-other', 'chore/tidy'):
                git('branch', name)
            self.assertEqual(sorted(ctx.branches(temp, 'avr-13')), ['cnechamkin/avr-13-other', 'fix/avr-13-seat'])
            self.assertEqual(ctx.branches(temp, 'avr-130'), ['feat/avr-130-arcade'])
            self.assertEqual(ctx.branches(temp, 'avr-999'), [])


class Cli(unittest.TestCase):
    def run_main(self, *args, env=None):
        out, err = io.StringIO(), io.StringIO()
        saved = os.environ.pop('LINEAR_API_KEY', None)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = ctx.main(list(args))
        finally:
            if saved is not None:
                os.environ['LINEAR_API_KEY'] = saved
        return code, out.getvalue(), err.getvalue()

    def test_rejects_something_that_is_not_an_issue_id(self):
        code, _, err = self.run_main('workflow')
        self.assertEqual(code, 2)
        self.assertIn('AVR-230', err)

    def test_without_credentials_or_the_pi_it_says_so_and_never_guesses(self):
        original = ctx.prs
        ctx.prs = lambda slug, token: None                      # as if gh were not installed
        try:
            code, out, _ = self.run_main('avr-230', '--status-url', 'http://127.0.0.1:1/party/api/status',
                                         '--games', str(REPO_ROOT / 'no-such-checkout'))
        finally:
            ctx.prs = original
        self.assertEqual(code, 0)
        self.assertIn('# Context for AVR-230', out)
        self.assertIn('LINEAR_API_KEY not set', out)
        self.assertIn('gh unavailable', out)
        self.assertIn('unreachable', out)
        self.assertIn('no checkout at', out)
        self.assertNotIn('deployed ', out.split('## Deployed build')[1].split('## Read next')[0].replace('last verified', ''))


if __name__ == '__main__':
    unittest.main()
