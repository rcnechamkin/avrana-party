"""tools/claude_gate.py: owner-reserved commands become a question, contract/generated/historical
edits get a reminder, everything else passes (the Claude convenience layer; CI is the enforcement)."""
import importlib.util
import json
import os
import subprocess
import sys
import unittest

from avrana import REPO_ROOT

spec = importlib.util.spec_from_file_location('claude_gate', REPO_ROOT / 'tools/claude_gate.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def bash(command):
    return gate.evaluate({'tool_name': 'Bash', 'tool_input': {'command': command}})


def edit(path, branch='feat/avr-1-x'):
    return gate.evaluate({'tool_name': 'Edit', 'tool_input': {'file_path': path}}, branch=branch)


class Gate(unittest.TestCase):
    def test_owner_reserved_commands_ask_with_a_reason(self):
        for command, needle in [
            ('git push --force origin main', 'force-push'),
            ('git push -f', 'force-push'),
            ('gh pr merge 42 --squash', 'owner'),
            ('git merge feature', 'PR'),
            ('git rebase -i HEAD~3', 'rewrites history'),
            ('ssh party "sudo bash /home/cody/avrana-party/ops/deploy.sh --party x --games y"', 'owner deployment'),
            ('sudo bash ops/deploy.sh --party a --games b', 'owner'),
            ('sudo systemctl restart avrana-party-core', 'owner action'),
        ]:
            decision, message = bash(command)
            self.assertEqual(decision, 'ask', command)
            self.assertIn(needle, message)

    def test_ordinary_and_read_only_commands_pass(self):
        for command in ['git status', 'git push -u origin feat/avr-1-x', 'git fetch origin', 'npm run check:repo',
                        'bash ops/deploy.sh --party a --games b --dry-run', 'bash ops/deploy.sh --help',
                        'python -m unittest', 'gh pr create --title x', 'git merge --ff-only origin/main',
                        'git merge --no-edit origin/main', 'git merge --abort',
                        'ssh party "git -C /home/cody/avrana-party log -1"']:
            self.assertEqual(bash(command)[0], 'ok', command)

    def test_contract_and_generated_edits_warn(self):
        decision, message = edit(str(REPO_ROOT / 'avrana' / 'party' / 'protocol.py'))
        self.assertEqual(decision, 'warn')
        self.assertIn('paired change', message)
        decision, message = edit(r'C:\Users\x\Projects\avrana-party-games\core\party_protocol.py')
        self.assertEqual(decision, 'warn')
        decision, message = edit(str(REPO_ROOT / 'web' / 'party' / 'styles.css'))
        self.assertEqual(decision, 'warn')
        self.assertIn('generated', message)
        self.assertEqual(edit(str(REPO_ROOT / 'avrana' / 'party' / 'core.py'))[0], 'ok')

    def test_paths_resolve_relative_to_the_checkout_whatever_it_is_called(self):
        self.assertEqual(gate.repo_relative(gate.normalize(str(REPO_ROOT / 'web' / 'party' / 'styles.css'))),
                         'web/party/styles.css')
        # a checkout nested in directories that repeat the repository name (GitHub Actions' layout)
        self.assertEqual(gate.repo_relative('/nowhere/avrana-party/avrana-party/avrana/party/protocol.py'),
                         'avrana/party/protocol.py')
        self.assertEqual(gate.repo_relative('/nowhere/avrana-party.wt-x/docs/findings/a.md'), 'docs/findings/a.md')

    def test_existing_historical_documents_warn_and_new_ones_do_not(self):
        existing = next((REPO_ROOT / 'docs' / 'findings').glob('*.md'))
        decision, message = edit(str(existing))
        self.assertEqual(decision, 'warn')
        self.assertIn('historical-edit', message)
        self.assertEqual(edit(str(REPO_ROOT / 'docs' / 'findings' / '2099-01-01-new-finding.md'))[0], 'ok')

    def test_decision_records_and_deployment_files_warn_that_the_owner_merges_them(self):
        existing = next((REPO_ROOT / 'docs' / 'adr').glob('0*.md'))
        decision, message = edit(str(existing))
        self.assertEqual(decision, 'warn')
        self.assertIn('amendment', message)
        # a new decision record is how a decision is proposed and is never questioned
        self.assertEqual(edit(str(REPO_ROOT / 'docs' / 'adr' / '9999-a-new-decision.md'))[0], 'ok')
        for path in ['ops/deploy.sh', 'deploy/README.md', 'avrana-party.nginx', 'arcade/nginx-site']:
            decision, message = edit(str(REPO_ROOT / path))
            self.assertEqual(decision, 'warn', path)
            self.assertIn('not a deployment', message)
        # the contract reminder wins for a file that is both
        self.assertIn('paired change', edit(str(REPO_ROOT / 'deploy' / 'avrana-party-session.conf'))[1])

    def test_an_existing_test_edited_on_a_fix_branch_warns_and_other_cases_do_not(self):
        existing = str(REPO_ROOT / 'tests' / 'unit' / 'test_claude_gate.py')
        decision, message = edit(existing, branch='fix/avr-9-something')
        self.assertEqual(decision, 'warn')
        self.assertIn('failing test first', message)
        self.assertEqual(edit(existing, branch='feat/avr-9-something')[0], 'ok')
        self.assertEqual(edit(existing, branch='')[0], 'ok')                      # unknown branch never blocks
        # adding the test that reproduces the bug is the point of a fix branch
        self.assertEqual(edit(str(REPO_ROOT / 'tests' / 'unit' / 'test_brand_new.py'), branch='fix/avr-9-x')[0], 'ok')

    def test_the_branch_is_read_from_the_checkout_that_holds_the_file(self):
        self.assertIsInstance(gate.current_branch(str(REPO_ROOT / 'tools' / 'claude_gate.py')), str)
        self.assertEqual(gate.current_branch('/nowhere/at/all/file.py'), '')

    def test_hook_protocol_exit_codes(self):
        python = sys.executable
        env = dict(os.environ)
        asked = subprocess.run([python, str(REPO_ROOT / 'tools/claude_gate.py')],
                               input=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': 'git push --force'}}),
                               capture_output=True, text=True, env=env)
        self.assertEqual(asked.returncode, 0)                    # never a hard block: a person decides
        out = json.loads(asked.stdout)['hookSpecificOutput']
        self.assertEqual(out['permissionDecision'], 'ask')
        self.assertIn('force-push', out['permissionDecisionReason'])
        warned = subprocess.run([python, str(REPO_ROOT / 'tools/claude_gate.py')],
                                input=json.dumps({'tool_name': 'Write', 'tool_input': {'file_path': str(REPO_ROOT / 'contracts/party-games.v0.json')}}),
                                capture_output=True, text=True, env=env)
        self.assertEqual(warned.returncode, 0)
        self.assertIn('additionalContext', warned.stdout)
        quiet = subprocess.run([python, str(REPO_ROOT / 'tools/claude_gate.py')],
                               input=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': 'git status'}}),
                               capture_output=True, text=True, env=env)
        self.assertEqual((quiet.returncode, quiet.stdout), (0, ''))
        garbage = subprocess.run([python, str(REPO_ROOT / 'tools/claude_gate.py')], input='not json',
                                 capture_output=True, text=True, env=env)
        self.assertEqual((garbage.returncode, garbage.stdout), (0, ''))   # a broken payload never blocks work


if __name__ == '__main__':
    unittest.main()
