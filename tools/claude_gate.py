#!/usr/bin/env python3
"""Claude Code PreToolUse hook: an early, friendly gate for the actions AGENTS.md reserves for
the owner.

CI and repository policy are the real enforcement (docs/WORKFLOW.md); nothing depends on this
hook. It only turns a merge, force-push, history rewrite or production command into an explicit
question to the person at the keyboard ("ask": they may approve it, and an unattended session
cannot), and adds a reminder when a contract file, a generated file or a historical document is
about to be edited. Codex and humans follow AGENTS.md directly.

    echo '{"tool_name": "Bash", "tool_input": {"command": "git push --force"}}' | python tools/claude_gate.py

Always exits 0. Output is Claude Code's hookSpecificOutput: permissionDecision "ask" with the
reason, or additionalContext for a reminder. Reads are never touched.
"""
import json
import os
import re
import sys

BLOCK = [
    (r'\bgit\s+push\b[^|;&]*\s(--force|-f|--force-with-lease)\b', 'force-push is forbidden (AGENTS.md: never rewrite history)'),
    # Bringing origin/main into a branch is the prescribed way to sync (never rebase or force-push);
    # merging anything else locally is asked about.
    (r'\bgit\s+merge\b(?![^|;&]*\borigin/main\b)(?![^|;&]*--(abort|continue)\b)', 'merging locally is not how changes land: open a PR; merges are the owner\'s decision'),
    (r'\bgh\s+pr\s+merge\b', 'merging a PR is the owner\'s decision (AGENTS.md)'),
    (r'\bgit\s+rebase\b', 'rebasing rewrites history on a shared branch; prefer a new commit'),
    (r'\bgit\s+(reset\s+--hard|checkout\s+--\s|restore\s+--source)\b.*\bmain\b', 'rewriting main locally is forbidden'),
    (r'\bgit\s+push\b[^|;&]*\s--delete\b', 'deleting remote branches is a separate owner operation'),
    (r'\bssh\s+(-\S+\s+)*\S*party\b[^|;&]*\b(sudo|systemctl|deploy\.sh|git\s+pull|install-party-web|nginx|certbot|nmcli)\b',
     'production changes on the Pi need an explicit owner deployment instruction (docs/runbooks/deploy.md)'),
    (r'\bops/deploy\.sh\b(?![^|;&]*--dry-run)(?![^|;&]*--help)', 'ops/deploy.sh deploys production; only the owner runs it (a --dry-run is fine)'),
    (r'\bsudo\s+(systemctl|nginx|nmcli|certbot|install|cp|tee|bash)\b', 'sudo against services/config is an owner action'),
]
CONTRACT_FILES = ('avrana/party/protocol.py', 'avrana/party/sessions.py', 'contracts/party-games.v0.json',
                  'contracts/vectors/party-session.v0.json', 'contracts/catalogs/lan-games.json',
                  'avrana/contracts/lan_catalog.py', 'core/party_protocol.py', 'provider/avrana-contract.json',
                  'provider/catalog.json', 'tests/vectors/party-session.v0.json', 'deploy/avrana-party-session.conf')
HISTORICAL = ('docs/archive/', 'docs/findings/')
GENERATED = ('web/party/styles.css', 'web/party/lib/icons.js', 'web/party/lib/avatars.js', 'web/party/catalog.json',
             'graphify-public/', 'context/graphify/')


def normalize(path):
    return path.replace('\\', '/')


def repo_relative(path):
    """The path relative to its checkout root (the nearest ancestor holding .git: a directory in a
    clone, a file in a worktree). A path outside any checkout falls back to the part after the
    last directory named like one of the two repositories."""
    parts = path.split('/')
    for i in range(len(parts) - 1, 0, -1):
        if os.path.exists('/'.join(parts[:i]) + '/.git'):
            return '/'.join(parts[i:])
    for i in range(len(parts) - 1, -1, -1):
        if parts[i].startswith('avrana-party'):
            return '/'.join(parts[i + 1:])
    return path


def evaluate(payload):
    """(decision, message): decision is 'ask', 'warn' or 'ok'."""
    tool = payload.get('tool_name', '')
    inp = payload.get('tool_input', {}) or {}
    if tool == 'Bash':
        command = inp.get('command', '') or ''
        for pattern, reason in BLOCK:
            if re.search(pattern, command):
                return 'ask', f'{reason}. Approve only if this is your explicit decision for this action.'
        return 'ok', ''
    if tool in ('Edit', 'Write', 'MultiEdit', 'NotebookEdit'):
        path = normalize(inp.get('file_path', '') or inp.get('notebook_path', '') or '')
        rel = repo_relative(path)
        if any(rel.startswith(h) for h in HISTORICAL):
            # editing an EXISTING finding or archive needs intent (CI: the historical-edit label);
            # writing a new dated finding is how evidence is added and is never questioned.
            if os.path.exists(path):
                return 'warn', (f'{rel} is a historical document (evidence, not current architecture). Edit it only '
                                'with explicit intent; the PR needs the `historical-edit` label. Prefer a new dated '
                                'finding or the canonical document.')
        if any(rel.endswith(c) or rel == c for c in CONTRACT_FILES):
            return 'warn', (f'{rel} is part of the Party <-> Games contract. A change here needs the paired change in the '
                            'other repository (same avr-N branch), updated declarations/digests, and '
                            'tools/contract_check.py passing (docs/design/PARTY-GAMES-CONTRACT.md).')
        if any(rel.startswith(g) or rel == g for g in GENERATED):
            return 'warn', f'{rel} is generated (docs/GENERATED.md): edit the source and regenerate instead.'
    return 'ok', ''


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    decision, message = evaluate(payload)
    if decision == 'ask':
        print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'ask',
                                                 'permissionDecisionReason': f'Avrana gate: {message}'}}))
    elif decision == 'warn':
        print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'additionalContext': f'Avrana gate: {message}'}}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
