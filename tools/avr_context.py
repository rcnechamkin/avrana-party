#!/usr/bin/env python3
"""Everything an agent needs before `Implement AVR-N`, from the deterministic sources.

    python3 tools/avr_context.py AVR-230 [--games ../avrana-party-games] [--status-url URL]

Prints: the Linear issue (title, state, description sections) when LINEAR_API_KEY is set or the
`linear` MCP is suggested otherwise; the matching branches in both repositories (local and
remote, by the avr-N token); open PRs naming the issue (via `gh` when logged in); the deployed
build from /party/api/status when reachable; and the canonical documents to read. Read only.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REPOS = {'party': ('rcnechamkin/avrana-party', ROOT), 'games': ('rcnechamkin/avrana-party-games', None)}
ISSUE_QUERY = '''query Issue($id: String!) { issue(id: $id) { identifier title url state { name type }
  description branchName labels { nodes { name } } relations { nodes { type relatedIssue { identifier } } } } }'''
SECTIONS = ('Outcome', 'Acceptance Criteria', 'Out of Scope', 'Repositories', 'Tests Required', 'Dependencies', 'Open Decisions')


def git(repo, *args):
    try:
        return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, timeout=30).stdout.decode().strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return ''


def branches(repo, token):
    local = [b.strip('* ').strip() for b in git(repo, 'branch', '--list').splitlines()]
    remote = [b.strip() for b in git(repo, 'branch', '-r').splitlines()]
    rx = re.compile(rf'(^|[/-]){token}([-/]|$)', re.I)
    return [b for b in local + remote if rx.search(b)]


def prs(slug, token):
    if not shutil.which('gh'):
        return None
    try:
        out = subprocess.run(['gh', 'pr', 'list', '--repo', slug, '--state', 'all', '--search', token, '--json',
                              'number,title,state,headRefName,url', '--limit', '20'], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode:
        return None
    rows = json.loads(out.stdout or '[]')
    return [r for r in rows if re.search(rf'\b{token}\b', f'{r["title"]} {r["headRefName"]}', re.I)]


def linear(identifier):
    key = os.environ.get('LINEAR_API_KEY')
    if not key:
        return None
    body = json.dumps({'query': ISSUE_QUERY, 'variables': {'id': identifier}}).encode()
    req = urllib.request.Request('https://api.linear.app/graphql', data=body,
                                 headers={'Content-Type': 'application/json', 'Authorization': key})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())['data']['issue']
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        return None


def sections(description):
    found = {}
    for name in SECTIONS:
        m = re.search(rf'^##\s*{re.escape(name)}\s*$\n(.*?)(?=^##\s|\Z)', description or '', re.M | re.S)
        found[name] = m[1].strip() if m else None
    return found


def status(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.loads(r.read().decode())
    except (urllib.error.URLError, OSError, ValueError):
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('issue', help='AVR-N')
    ap.add_argument('--games', default=str(ROOT.parent / 'avrana-party-games'))
    ap.add_argument('--status-url', default='https://party.avrana.net/party/api/status')
    args = ap.parse_args(argv)
    m = re.fullmatch(r'(?i)avr-?(\d+)', args.issue.strip())
    if not m:
        print('expected an issue id like AVR-230', file=sys.stderr)
        return 2
    identifier, token = f'AVR-{int(m[1])}', f'avr-{int(m[1])}'
    print(f'# Context for {identifier}\n')
    issue = linear(identifier)
    if issue is None:
        print('## Linear\nLINEAR_API_KEY not set or issue unreadable: read the issue through the Linear MCP '
              f'(get_issue {identifier}). Treat it as the desired delta, not an architecture reference.\n')
    else:
        print(f'## Linear: {issue["title"]}\nState: {issue["state"]["name"]}  Labels: '
              f'{", ".join(l["name"] for l in issue["labels"]["nodes"]) or "none"}  {issue["url"]}')
        secs = sections(issue.get('description'))
        for name, text in secs.items():
            print(f'\n### {name}\n{text if text else "(section missing: ask for it before starting)"}')
        open_decisions = secs.get('Open Decisions')
        if open_decisions and open_decisions.lower() not in ('none', 'none.', '-'):
            print('\n**Open Decisions is not empty: this issue is not Ready for Agent until Cody resolves them.**')
        print()
    games = Path(args.games)
    print('## Branches (by avr-N token)')
    for name, (slug, repo) in REPOS.items():
        repo = repo or games
        if repo and (repo / '.git').exists():
            found = branches(repo, token)
            print(f'- {name} ({repo}): {", ".join(found) if found else "none"}')
        else:
            print(f'- {name}: no checkout at {repo}')
    print('\n## Pull requests')
    for name, (slug, _) in REPOS.items():
        rows = prs(slug, token)
        if rows is None:
            print(f'- {name}: gh unavailable; check https://github.com/{slug}/pulls?q={token}')
        else:
            print(f'- {name}: ' + (', '.join(f'#{r["number"]} {r["state"]} {r["headRefName"]}' for r in rows) or 'none'))
    print('\n## Deployed build')
    doc = status(args.status_url)
    main_sha = git(ROOT, 'rev-parse', 'origin/main')
    if doc is None:
        print(f'- {args.status_url} unreachable (the Pi is only on the Party LAN): read docs/SYSTEM.md for the last verified state')
    else:
        for name in ('party', 'games'):
            r = doc.get(name, {})
            print(f'- {name}: deployed {str(r.get("deployed_sha") or r.get("checkout_sha"))[:12]}'
                  + (f' (origin/main {main_sha[:12]})' if name == 'party' and main_sha else '')
                  + (' MISMATCH with manifest' if r.get('mismatch') else ''))
        print(f'- summary: {doc.get("summary", {}).get("state")} {doc.get("summary", {}).get("reasons")}')
    print('\n## Read next\n- AGENTS.md (this repo), docs/WORKFLOW.md, the source and tests the issue names,\n'
          '  then only the canonical docs/ADRs they cite; docs/CROSS-REPO.md when both repositories change.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
