"""tools/ci_verdict.py: which lanes a pull request needs and when the verdict fails (AVR-305)."""
import importlib.util
import itertools
from pathlib import Path
import re
import unittest

from avrana import REPO_ROOT

spec = importlib.util.spec_from_file_location('ci_verdict', REPO_ROOT / 'tools/ci_verdict.py')
cv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cv)

OK, F, C, S, N = cv.SUCCESS, cv.FAILURE, cv.CANCELLED, cv.SKIPPED, cv.NOT_RUN
DOCS = ['docs/README.md']
PLATFORM = ['avrana/party/sessions.py']


class Scope(unittest.TestCase):
    def test_the_five_areas_of_the_issue_are_platform_paths(self):
        for p in ('avrana/x.py', 'contracts/party-games.v0.json', 'deploy/arcade/a.conf', 'ops/provision-game',
                  'experiments/native-game/proof.sh'):
            self.assertTrue(cv.is_platform_path(p), p)

    def test_the_rest_of_the_old_workflow_filter_is_kept(self):
        for p in ('ops/install-game', 'web/party/app.js', 'avrana-party.nginx', 'tests/package/a',
                  '.github/workflows/service-trust-proof.yml', 'tests/fixtures/appliances/x.json'):
            self.assertTrue(cv.is_platform_path(p), p)

    def test_other_paths_are_not(self):
        for p in ('docs/TESTING.md', 'README.md', 'tests/unit/test_x.py', 'ops/deploy.sh', 'avrana-party.nginx.bak',
                  'avranax/a.py', 'ops/provision-game2', 'web/src/party.css', 'tools/ci_verdict.py'):
            self.assertFalse(cv.is_platform_path(p), p)

    def test_windows_separators_and_dot_prefix(self):
        self.assertTrue(cv.is_platform_path(chr(92).join(['avrana', 'party', 'a.py'])))
        self.assertTrue(cv.is_platform_path('./deploy/x'))

    def test_empty_change_touches_nothing(self):
        self.assertFalse(cv.touches_platform([]))

    def test_one_platform_path_among_docs_is_enough(self):
        self.assertTrue(cv.touches_platform(DOCS + ['deploy/a']))

    def test_list_matches_the_workflow_it_replaced(self):
        text = (REPO_ROOT / '.github/workflows/service-trust-proof.yml').read_text(encoding='utf-8')
        listed = re.findall(r"^#\s+- '([^']+)'$", text, re.M)
        self.assertEqual(tuple(listed), cv.PLATFORM_PATHS)


class Decide(unittest.TestCase):
    def test_docs_only_with_both_always_lanes_green(self):
        self.assertEqual(cv.decide(DOCS, OK, OK, S, N), (True, []))
        self.assertEqual(cv.decide(DOCS, OK, OK, N, ''), (True, []))

    def test_platform_change_needs_the_proof_and_native_game(self):
        self.assertTrue(cv.decide(PLATFORM, OK, OK, OK, OK)[0])
        for trust, native in ((S, OK), (N, OK), (OK, S), (OK, N), (OK, ''), (S, S), (F, OK), (OK, F), (C, OK), (OK, C)):
            with self.subTest(trust=trust, native=native):
                self.assertFalse(cv.decide(PLATFORM, OK, OK, trust, native)[0])

    def test_always_lanes_must_succeed_on_every_change(self):
        for paths in (DOCS, PLATFORM, []):
            for lane in (0, 1):
                for bad in (F, C, S, N):
                    r = [OK, OK]
                    r[lane] = bad
                    with self.subTest(paths=paths, lane=lane, bad=bad):
                        ok, reasons = cv.decide(paths, r[0], r[1], OK, OK)
                        self.assertFalse(ok)
                        self.assertEqual(len(reasons), 1)

    def test_a_proof_that_ran_anyway_and_failed_fails_a_docs_change(self):
        for bad in (F, C):
            self.assertFalse(cv.decide(DOCS, OK, OK, bad, N)[0])
            self.assertFalse(cv.decide(DOCS, OK, OK, N, bad)[0])
            self.assertFalse(cv.decide(DOCS, OK, OK, OK, bad)[0])

    def test_a_proof_that_ran_anyway_and_passed_is_fine(self):
        self.assertTrue(cv.decide(DOCS, OK, OK, OK, OK)[0])

    def test_every_combination_against_the_rule(self):
        results = (OK, F, C, S, N)
        for paths, combo in itertools.product((DOCS, PLATFORM), itertools.product(results, repeat=4)):
            off, cross, trust, native = combo
            platform = paths is PLATFORM
            expect = off == OK and cross == OK
            for r in (trust, native):
                expect = expect and (r == OK or (not platform and r in (S, N)))
            with self.subTest(paths=paths, combo=combo):
                self.assertEqual(cv.decide(paths, *combo)[0], expect)

    def test_reasons_name_the_lane(self):
        ok, reasons = cv.decide(PLATFORM, F, OK, S, N)
        self.assertFalse(ok)
        text = '\n'.join(reasons)
        for name in ('Offline checks', 'Service trust proof', 'native-game'):
            self.assertIn(name, text)
        self.assertNotIn('Cross-repo', text)

    def test_an_unknown_result_fails(self):
        self.assertFalse(cv.decide(DOCS, 'weird', OK, N, N)[0])

    def test_case_and_blanks_are_normalised(self):
        self.assertTrue(cv.decide(DOCS, 'Success', ' success ', '', None)[0])


class Workflows(unittest.TestCase):
    def read(self, name):
        return (REPO_ROOT / '.github/workflows' / name).read_text(encoding='utf-8')

    def test_lanes_are_reusable_and_do_not_run_twice_on_pull_requests(self):
        for name in ('offline-checks.yml', 'cross-repo.yml', 'service-trust-proof.yml'):
            on = self.read(name).split('\njobs:')[0]
            self.assertIn('workflow_call:', on, name)
            self.assertNotRegex(on, r'(?m)^  pull_request:', name)

    def test_the_verdict_workflow_has_one_fixed_name_and_always_runs(self):
        text = self.read('ci-verdict.yml')
        self.assertIn('name: CI verdict\n', text)
        self.assertIn('    name: CI verdict\n', text)
        self.assertRegex(text, r'(?m)^  pull_request:\s*$')
        self.assertNotRegex(text, r'(?m)^\s+paths:')
        self.assertIn('if: ${{ always() }}', text)


if __name__ == '__main__':
    unittest.main()
