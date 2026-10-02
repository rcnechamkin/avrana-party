"""Offline fixtures for derived context. No real API key, model API or product runtime."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
import urllib.error

MODULE = Path(__file__).resolve().parents[2] / 'tools/graphify_context.py'
spec = importlib.util.spec_from_file_location('context_tool', MODULE)
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


def md5(data):
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        self.cfg = {
            'schema_version': 1, 'repository': 'rcnechamkin/avrana-party',
            'graphify_version': c.GRAPHIFY_VERSION, 'extraction': 'local-ast',
            'linear_team_id': 'synthetic-team', 'linear_project_ids': ['synthetic-project'],
            'linear_max_age_seconds': 21600, 'max_file_bytes': 100000,
            'extensions': ['.py', '.md', '.json'],
            'exclude': ['graphify-out/*', 'graphify-public/*', '.graphify-context/*', 'context/graphify/*']}
        self.write('.graphify.json', json.dumps(self.cfg))
        self.write('.gitignore', '/graphify-out/\n/graphify-public/\n/.graphify-context/\n.env*\n')
        self.write('AGENTS.md', '# Rules\nLinear is authoritative. Graphify is derived.\n')
        self.write('docs/decision.md', '# Accepted decision\nStatus: accepted\n')
        self.write('source.py', 'def sample():\n    return 1\n')
        subprocess.run(['git', '-C', str(self.root), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.root), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test', 'commit', '-qm', 'Fixture'], check=True)

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding='utf-8')
        return path

    def snapshot(self):
        return {'schema_version': 1, 'generated_warning': c.WARNING, 'authority': 'none',
                'synced_at': c.now(), 'team_id': 'synthetic-team', 'projects': [], 'issues': []}

    def runner(self, command, cwd, env):
        self.assertNotIn('--backend', command)
        self.assertNotIn('LINEAR_API_KEY', env)
        self.assertNotIn('OPENAI_API_KEY', env)
        if 'cluster-only' in command:
            self.assertIn('--no-label', command)
            self.assertIn('--no-viz', command)
            return
        self.assertIn('--code-only', command)
        corpus = Path(command[command.index('extract') + 1])
        build = Path(command[command.index('--out') + 1])
        self.assertFalse(list(corpus.rglob('*.md')))
        manifest = {p.relative_to(corpus).as_posix(): {'ast_hash': md5(p.read_bytes())}
                    for p in corpus.rglob('*') if p.is_file()}
        c.write_json(build / 'manifest.json', manifest)
        c.write_json(build / 'graph.json', {'nodes': [{'id': 'sample', 'source_file': 'source.py'}], 'edges': []})
        (build / 'GRAPH_REPORT.md').write_text('# Derived report\n', encoding='utf-8')

    def refresh(self, architecture=False, runner=None):
        return c.refresh(self.root, self.root, architecture, sync=lambda *_: self.snapshot(),
                         runner=runner or self.runner, installed_version=c.GRAPHIFY_VERSION)

    def test_ast_needs_no_model_key_and_never_extracts_docs(self):
        with patch.dict(os.environ, {'LINEAR_API_KEY': '', 'OPENAI_API_KEY': ''}):
            self.refresh(True)
        self.assertEqual([], c.stale_reasons(self.root, self.root, True))
        self.assertTrue(c.semantic_reasons(self.root, self.root))

    def test_private_snapshot_and_ttl(self):
        with patch.dict(os.environ, {'LINEAR_API_KEY': 'fixture-only', 'OPENAI_API_KEY': 'fixture-only'}, clear=False):
            self.refresh()
        self.assertEqual([], c.stale_reasons(self.root, self.root))
        future = datetime.now(timezone.utc) + timedelta(hours=7)
        self.assertIn('Linear snapshot expired or clock invalid', c.stale_reasons(self.root, self.root, clock=future))
        self.write('.graphify-context/linear.json', '{}')
        self.assertIn('generated Linear snapshot missing or edited', c.stale_reasons(self.root, self.root))

    def test_missing_key_invalidates_previous_graph(self):
        with patch.dict(os.environ, {'LINEAR_API_KEY': 'fixture-only'}, clear=False):
            self.refresh()
        with patch.dict(os.environ, {'LINEAR_API_KEY': '', 'OPENAI_API_KEY': ''}):
            with self.assertRaisesRegex(c.ContextError, 'LINEAR_API_KEY'):
                self.refresh()
        self.assertTrue(c.stale_reasons(self.root, self.root))

    def test_code_doc_add_delete_and_config_changes_detected(self):
        with patch.dict(os.environ, {'LINEAR_API_KEY': '', 'OPENAI_API_KEY': ''}):
            self.refresh(True)
        before = c.inputs(self.root, self.root)[3]
        self.write('source.py', 'def changed():\n    return 2\n')
        self.assertNotEqual(before, c.inputs(self.root, self.root)[3])
        self.assertTrue(c.stale_reasons(self.root, self.root, True))
        before = c.semantic_inputs(self.root, self.root)[2]
        self.write('docs/decision.md', '# Amended decision\n')
        self.assertNotEqual(before, c.semantic_inputs(self.root, self.root)[2])
        self.write('new.py', 'VALUE = 2\n')
        self.assertIn('new.py', c.inputs(self.root, self.root)[1])
        (self.root / 'source.py').unlink()
        self.assertNotIn('source.py', c.inputs(self.root, self.root)[1])

    def test_output_tampering_and_version_detected(self):
        self.refresh(True)
        self.write('graphify-public/graph.json', '{}')
        self.assertIn('derived output missing or changed', c.stale_reasons(self.root, self.root, True))
        with self.assertRaisesRegex(c.ContextError, 'installed version differs'):
            c.refresh(self.root, self.root, True, installed_version='wrong')

    def test_failed_extraction_cannot_publish_ready(self):
        def incomplete(command, root, env):
            self.runner(command, root, env)
            build = Path(command[command.index('--out') + 1])
            c.write_json(build / 'manifest.json', {})
        with self.assertRaisesRegex(c.ContextError, 'incomplete'):
            self.refresh(True, incomplete)
        self.assertTrue(c.stale_reasons(self.root, self.root, True))

    def test_changes_during_extraction_cannot_publish_ready(self):
        def racing(command, root, env):
            self.runner(command, root, env)
            self.write('source.py', 'NEW = 4\n')
        with self.assertRaisesRegex(c.ContextError, 'Inputs changed'):
            self.refresh(True, racing)

    def test_semantic_host_session_acceptance_and_staleness(self):
        c.prepare_semantic(self.root, self.root)
        corpus = self.root / '.graphify-context/semantic-input'
        build = corpus / 'graphify-out'
        manifest = {p.relative_to(corpus).as_posix(): {'semantic_hash': md5(p.read_bytes())}
                    for p in corpus.rglob('*.md')}
        c.write_json(build / 'manifest.json', manifest)
        c.write_json(build / 'graph.json', {'nodes': [{'id': 'decision', 'source_file': 'docs/decision.md'}], 'edges': []})
        c.accept_semantic(self.root, self.root)
        self.assertFalse(c.semantic_reasons(self.root, self.root))
        self.write('docs/decision.md', '# New decision\n')
        self.assertTrue(c.semantic_reasons(self.root, self.root))
        with self.assertRaisesRegex(c.ContextError, 'changed during'):
            c.accept_semantic(self.root, self.root)

    def test_semantic_partial_session_rejected(self):
        c.prepare_semantic(self.root, self.root)
        c.write_json(self.root / '.graphify-context/semantic-input/graphify-out/manifest.json', {})
        with self.assertRaisesRegex(c.ContextError, 'incomplete'):
            c.accept_semantic(self.root, self.root)

    def test_private_linear_semantics_never_publish_shared_products(self):
        c.write_json(self.root / '.graphify-context/linear.json', self.snapshot())
        c.prepare_semantic(self.root, self.root, True)
        corpus = self.root / '.graphify-context/semantic-work-input'
        build = corpus / 'graphify-out'
        manifest = {p.relative_to(corpus).as_posix(): {'semantic_hash': md5(p.read_bytes())}
                    for p in corpus.rglob('*.md')}
        c.write_json(build / 'manifest.json', manifest)
        c.write_json(build / 'graph.json', {'nodes': [{'id': 'work', 'source_file': 'LINEAR-CONTEXT.md'}], 'edges': []})
        c.accept_semantic(self.root, self.root, True)
        self.assertFalse((self.root / 'context/graphify').exists())
        self.assertFalse(c.semantic_reasons(self.root, self.root, True))
        snapshot = self.snapshot()
        snapshot['issues'] = [{'identifier': 'TEST-CHANGED'}]
        c.write_json(self.root / '.graphify-context/linear.json', snapshot)
        self.assertTrue(c.semantic_reasons(self.root, self.root, True))

    def test_semantic_fingerprint_is_portable_across_checkout_line_endings(self):
        original = c.semantic_inputs(self.root, self.root)[2]
        path = self.root / 'docs/decision.md'
        path.write_bytes(path.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
        self.assertEqual(original, c.semantic_inputs(self.root, self.root)[2])
        path.write_bytes(path.read_bytes() + b'New decision.\r\n')
        self.assertNotEqual(original, c.semantic_inputs(self.root, self.root)[2])

    def test_shared_graph_side_effects_cannot_be_committed(self):
        self.write('context/graphify/cache/last_query_stamp', 'synthetic timestamp')
        subprocess.run(['git', '-C', str(self.root), 'add', '--force',
                        'context/graphify/cache/last_query_stamp'], check=True)
        with self.assertRaisesRegex(c.ContextError, 'caches stay local'):
            c.check_config(self.root, self.root)

    def test_nonportable_semantic_sources_rejected(self):
        c.prepare_semantic(self.root, self.root)
        corpus = self.root / '.graphify-context/semantic-input'
        build = corpus / 'graphify-out'
        c.write_json(build / 'manifest.json', {p.relative_to(corpus).as_posix():
                     {'semantic_hash': md5(p.read_bytes())} for p in corpus.rglob('*.md')})
        c.write_json(build / 'graph.json', {'nodes': [{'id': 'x', 'source_file': '/private/source.md'}]})
        with self.assertRaisesRegex(c.ContextError, 'nonportable'):
            c.accept_semantic(self.root, self.root)

    def test_secret_and_historical_inputs_excluded(self):
        self.write('.env', 'not-a-real-secret')
        self.write('docs/manifest.json', json.dumps({'documents': [
            {'path': 'AGENTS.md', 'class': 'canonical'},
            {'path': 'docs/decision.md', 'class': 'decision'},
            {'path': 'docs/old.md', 'class': 'archived'}]}))
        self.write('docs/old.md', '# Old\n')
        files = c.inputs(self.root, self.root)[1]
        self.assertNotIn('.env', files)
        self.assertNotIn('docs/old.md', files)
        self.assertIn('docs/decision.md', files)

    def test_hooks_preserve_prior_guards_and_are_idempotent(self):
        hook = self.write('.git/hooks/post-commit', '#!/bin/sh\n# existing guard\nexit 0\n')
        c.install_hooks(self.root, self.root)
        c.install_hooks(self.root, self.root)
        content = hook.read_text(encoding='utf-8')
        self.assertEqual(1, content.count('# avrana-derived-context-hook'))
        self.assertIn('# existing guard\nexit 0', content)
        self.assertLess(content.index('# avrana-derived-context-hook'), content.index('exit 0'))

    def test_refresh_lock(self):
        with c.lock(self.root):
            with self.assertRaisesRegex(c.ContextError, 'already running'):
                with c.lock(self.root):
                    pass

    def test_claude_guard_never_blocks_when_config_missing(self):
        (self.root / '.graphify.json').unlink()
        self.assertEqual(0, c.main(['--repo', str(self.root), 'guard']))

    def test_linear_pagination_order_read_only_and_scope(self):
        calls = []
        def request(query, variables, token):
            calls.append((query, variables))
            self.assertTrue(query.startswith('query '))
            self.assertNotIn('mutation', query)
            if 'ContextProject' in query:
                return {'project': {'id': 'synthetic-project', 'name': 'Fixture', 'url': 'https://linear.app/example/project/fixture', 'updatedAt': c.now(), 'priority': 2, 'state': 'started'}}
            suffix = '2' if variables['after'] else '1'
            return {'issues': {'nodes': [{'id': suffix, 'identifier': 'TEST-' + suffix,
                'title': 'Synthetic task', 'url': 'https://linear.app/example/issue/TEST-' + suffix,
                'updatedAt': c.now(), 'priority': 2, 'state': {'name': 'Started', 'type': 'started'},
                'project': {'id': variables['project']}}],
                'pageInfo': {'hasNextPage': suffix == '1', 'endCursor': suffix}}}
        result = c.synchronize(self.cfg, 'fixture-only', request)
        self.assertEqual(['TEST-1', 'TEST-2'], [i['identifier'] for i in result['issues']])
        self.assertEqual('1', calls[-1][1]['after'])
        self.assertIn('DO NOT EDIT', c.linear_markdown(result))
        self.assertEqual('none', result['authority'])

    def test_linear_repeated_cursor_rejected(self):
        def request(query, variables, token):
            if 'ContextProject' in query:
                return {'project': {'id': 'synthetic-project'}}
            return {'issues': {'nodes': [], 'pageInfo': {'hasNextPage': True, 'endCursor': 'same'}}}
        with self.assertRaisesRegex(c.ContextError, 'pagination'):
            c.synchronize(self.cfg, 'fixture-only', request)

    def test_graphql_partial_error_and_mutation_rejected(self):
        opener = lambda *_args, **_kwargs: io.BytesIO(b'{"data": {}, "errors": [{"message": "synthetic"}]}')
        with self.assertRaisesRegex(c.ContextError, 'incomplete data'):
            c.graphql('query Fixture { teams { nodes { id } } }', {}, 'fixture-only', opener)
        with self.assertRaisesRegex(c.ContextError, 'queries only'):
            c.graphql('mutation Update {}', {}, 'fixture-only', opener)

    def test_http_rate_limit_retry_is_bounded(self):
        calls = []
        def opener(*args, **kwargs):
            calls.append(1)
            raise urllib.error.HTTPError('https://api.linear.app/graphql', 429, 'fixture', {'Retry-After': '1'}, None)
        with self.assertRaisesRegex(c.ContextError, 'HTTP 429'):
            c.graphql('query Fixture {}', {}, 'fixture-only', opener, lambda *_: None)
        self.assertEqual(3, len(calls))


if __name__ == '__main__':
    unittest.main()
