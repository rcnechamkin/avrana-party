"""Mutation tests: governance regressions must fail without policing historical prose."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('repo_check', REPO / 'tools/repo-check.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class RepositoryIntegrity(unittest.TestCase):
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

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')
        self.files.add(path)

    def check(self):
        self.write('docs/manifest.json', json.dumps(self.manifest))
        return checker.check_repository(self.root, self.files)

    def entry(self, path):
        return next(e for e in self.manifest['documents'] if e['path'] == path)

    def test_current_repository_passes(self):
        self.assertEqual([], self.check())

    def test_archive_cannot_be_promoted(self):
        entry = self.entry('docs/archive/handoffs/2026-09-25-claude-log.md')
        entry.update({'class': 'canonical', 'status': 'current', 'authority': 'reference'})
        self.assertTrue(any('archive namespace' in e for e in self.check()))

    def test_research_and_proposal_cannot_gain_authority(self):
        self.entry('docs/research/REFERENCE-IMPLEMENTATIONS.md')['canonical_for'] = 'references'
        self.entry('docs/design/COMMUNICATION.md')['authority'] = 'scoped-contract'
        errors = self.check()
        self.assertTrue(any('non-authoritative class' in e for e in errors))
        self.assertTrue(any('proposal/experiment' in e for e in errors))

    def test_linear_cannot_be_shadowed(self):
        self.entry('README.md')['canonical_for'] = 'live-work'
        self.assertTrue(any('forbidden authority' in e for e in self.check()))

    def test_status_change_requires_metadata_review(self):
        path = 'docs/adr/0011-party-console-model.md'
        text = (self.root/path).read_text(encoding='utf-8').replace('Status: **accepted;', 'Status: **proposed;')
        self.write(path, text)
        self.assertTrue(any('status marker' in e for e in self.check()))

    def test_invalid_dates_and_unclassified_docs_fail(self):
        self.entry('docs/findings/2026-09-29-avr129-deploy.md')['observed'] = '2026-02-30'
        self.write('docs/new-guide.md', '# Unclassified\n')
        errors = self.check()
        self.assertTrue(any('invalid ISO date' in e for e in errors))
        self.assertTrue(any('missing from manifest' in e for e in errors))

    def test_links_images_references_and_fragments(self):
        self.write('docs/README.md', '# Map\n[missing](missing.md)\n![image](missing.png)\n'
                   '[ref][lost]\n[wrong](TESTING.md#no-such-heading)\n'
                   '[ok](TESTING.md?view=1#lan-games-provider-cross-repository-tests)\n')
        errors = self.check()
        self.assertEqual(2, sum('relative link does not resolve' in e for e in errors))
        self.assertEqual(1, sum('undefined reference' in e for e in errors))
        self.assertEqual(1, sum('heading fragment' in e for e in errors))

    def test_fences_code_and_historical_language_are_not_policed(self):
        path = 'docs/archive/handoffs/2026-09-25-claude-log.md'
        self.write(path, '# Historical log\nNext action: deploy the old branch.\n'
                   '```md\n[example](missing.md)\n```\n`[example](missing.md)`\n'
                   '[valid][map]\n[map]: ../../README.md\n')
        self.assertEqual([], self.check())

    def test_paths_cannot_escape_repository(self):
        self.entry('README.md')['path'] = '../outside.md'
        self.assertTrue(any('missing or unsafe' in e for e in self.check()))

    def test_generated_provenance_is_required(self):
        self.manifest['generated'][0]['sources'] = ['missing-source.css']
        self.assertTrue(any('generated source missing' in e for e in self.check()))

    def test_generated_mapping_cannot_be_removed(self):
        self.manifest['generated'].pop(0)
        self.assertTrue(any('known generated output missing' in e for e in self.check()))

    def test_malformed_metadata_is_reported_without_content(self):
        self.entry('README.md')['status'] = {'private': 'do not print this'}
        errors = self.check()
        self.assertTrue(any('must be strings' in e for e in errors))
        self.assertNotIn('do not print this', str(errors))

    def test_directory_is_not_a_document(self):
        self.entry('README.md')['path'] = 'docs'
        self.assertTrue(any('document path missing or unsafe' in e for e in self.check()))

    def test_missing_agent_authority_is_reported(self):
        del self.entry('CLAUDE.md')['authority']
        self.assertTrue(any('agent layer' in e for e in self.check()))

    def test_conflicts_nginx_drift_and_root_handoffs_fail(self):
        self.write('NEW-HANDOFF.md', '# Next task\n')
        self.write('arcade/nginx-site', '# changed\n')
        self.write('avrana/__init__.py', '<<<<<<< branch\n')
        errors = self.check()
        for rule in ['root handoff', 'nginx copies differ', 'conflict marker']:
            self.assertTrue(any(rule in e for e in errors), rule)

    def test_duplicate_json_keys_fail(self):
        self.write('docs/manifest.json', '{"schema_version":1,"schema_version":1}')
        self.assertEqual(['docs/manifest.json: invalid manifest JSON/schema'],
                         checker.check_repository(self.root, self.files))

    def test_agent_layer_cannot_be_a_second_handbook(self):
        self.write('CLAUDE.md', '# Claude\n' + 'Independent truth\n' * 50)
        self.assertTrue(any('agent layer' in e for e in self.check()))


if __name__ == '__main__':
    unittest.main()
