"""tools/reconcile.py with fake Linear/GitHub/status records: every check classifies drift as
actionable, informational or not-run, and unavailable data is never reported as passing."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from avrana import REPO_ROOT

spec = importlib.util.spec_from_file_location('reconcile', REPO_ROOT / 'tools/reconcile.py')
reconcile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reconcile)


def issue(ident, state_name, state_type, title='t'):
    return {'identifier': ident, 'title': title, 'state': {'name': state_name, 'type': state_type}}


def pr(number, head, state='open', merged=False, title='', body=''):
    return {'number': number, 'head': {'ref': head}, 'state': 'closed' if merged else state,
            'merged_at': '2026-10-01T00:00:00Z' if merged else None, 'title': title or head, 'body': body}


class Checks(unittest.TestCase):
    def setUp(self):
        self.report = reconcile.Report()

    def texts(self, kind):
        return [r['text'] for r in getattr(self.report, kind)]

    def test_issue_ids_are_normalized(self):
        self.assertEqual(reconcile.issue_ids('fix/avr-130-x', 'See AVR-0130 and avr-7'), {'AVR-130', 'AVR-7'})

    def test_linear_versus_prs(self):
        issues = [issue('AVR-1', 'Done', 'completed'), issue('AVR-2', 'In Progress', 'started'),
                  issue('AVR-3', 'Done', 'completed'), issue('AVR-4', 'In Review', 'started')]
        pulls = {'party': [pr(10, 'fix/avr-2-thing', merged=True), pr(11, 'feat/avr-3-x', state='open'),
                           pr(12, 'docs/avr-4-y', merged=True), pr(13, 'chore/avr-99-z', state='open')]}
        reconcile.check_linear_vs_prs(self.report, issues, pulls)
        actionable = self.texts('actionable')
        self.assertTrue(any('AVR-2' in t and 'merged' in t for t in actionable))         # merged but still In Progress
        self.assertTrue(any('AVR-3' in t and 'still open' in t for t in actionable))     # Done with an open PR
        self.assertFalse(any('AVR-4' in t for t in actionable))                          # In Review is fine
        info = self.texts('informational')
        self.assertEqual(sum('no merged PR' in t for t in info), 1)                      # one line, not one per issue
        self.assertTrue(any('AVR-1' in t and 'no merged PR' in t and 'AVR-2' not in t for t in info))
        self.assertTrue(any('AVR-99' in t for t in info))

    def test_prs_without_issue_and_orphan_branches(self):
        pulls = {'party': [pr(20, 'chore/tidy'), pr(21, 'fix/avr-5-a', merged=True)]}
        branches = {'party': [{'name': n} for n in ('main', 'chore/tidy', 'fix/avr-5-a', 'old/forgotten',
                                                      'experiment/party-sim', 'docs/party-platform')]}
        reconcile.check_prs_without_issue(self.report, pulls)
        reconcile.check_orphan_branches(self.report, branches, pulls, retained={'docs/party-platform'})
        info = self.texts('informational')
        self.assertTrue(any('party#20' in t and 'no AVR' in t for t in info))
        self.assertTrue(any('fix/avr-5-a' in t and 'merged' in t for t in info))
        self.assertTrue(any('old/forgotten' in t and 'no open PR' in t for t in info))
        self.assertFalse(any('experiment/party-sim' in t or 'docs/party-platform' in t or 'chore/tidy' in t and 'no open PR' in t for t in info))
        self.assertEqual(self.texts('actionable'), [])

    def test_deployment_against_main(self):
        status = {'deployment': {'deployed_at': 'x'}, 'party': {'deployed_sha': 'a' * 40, 'mismatch': False, 'dirty': False},
                  'games': {'deployed_sha': 'b' * 40, 'mismatch': True, 'dirty': True},
                  'summary': {'state': 'degraded', 'reasons': ['nginx is failed']},
                  'certificate': {'status': 'expiring', 'days_left': 3}, 'games_provider': {'compatible': False}}
        reconcile.check_deployment(self.report, status, {'party': 'a' * 40, 'games': 'c' * 40})
        actionable = ' '.join(self.texts('actionable'))
        for needle in ('games: the production checkout differs', 'uncommitted', 'nginx is failed', 'expiring', 'different launch integration'):
            self.assertIn(needle, actionable)
        self.assertTrue(any('games: deployed' in t and 'differs from main' in t for t in self.texts('informational')))
        self.assertFalse(any('party: deployed' in t for t in self.texts('informational')))

    def test_missing_manifest_is_actionable_and_missing_status_is_not_run(self):
        reconcile.check_deployment(self.report, {'party': {}, 'games': {}, 'summary': {}}, {})
        self.assertTrue(any('no deployment manifest' in t for t in self.texts('actionable')))
        reconcile.check_deployment(reconcile.Report(), None, {})   # nothing to say without data

    def test_report_markdown_separates_the_three_kinds(self):
        self.report.action('a', 'fix me')
        self.report.info('b', 'fyi')
        self.report.skip('c', 'no key')
        md = self.report.markdown()
        self.assertIn('## Actionable drift (1)', md)
        self.assertIn('## Informational (1)', md)
        self.assertIn('## Checks that could not run (1)', md)
        self.assertEqual(self.report.as_dict()['not_run'], [{'check': 'c', 'text': 'no key'}])


class Cli(unittest.TestCase):
    def test_no_network_run_writes_the_report_and_marks_skips(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'report'
            with contextlib.redirect_stdout(io.StringIO()):
                code = reconcile.main(['--no-network', '--out', str(out)])
            self.assertEqual(code, 0)
            doc = json.loads(out.with_suffix('.json').read_text(encoding='utf-8'))
            self.assertEqual(doc['schema'], 'avrana.reconcile/v0')
            skipped = {r['check'] for r in doc['not_run']}
            self.assertTrue({'linear-vs-prs', 'deployment', 'contract-cross'} <= skipped)
            self.assertTrue(any(r['check'] == 'docs-integrity' for r in doc['informational'] + doc['actionable']))
            self.assertIn('# Avrana drift reconciliation', out.with_suffix('.md').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
