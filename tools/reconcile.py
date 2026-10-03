#!/usr/bin/env python3
"""Deterministic drift reconciliation across Linear, GitHub, the repositories and the deployed Pi.

    python3 tools/reconcile.py --games ../avrana-party-games --out reconcile-report
    python3 tools/reconcile.py --status-url https://party.avrana.net/party/api/status   # on the Party LAN

Runs weekly in GitHub Actions (.github/workflows/reconcile.yml) and on demand. No LLM: every
check is a comparison of records. The report (Markdown + JSON) separates three kinds of line:

    ACTIONABLE     drift that someone should resolve (a Done issue with no merged PR, ...)
    INFORMATIONAL  state worth knowing that is not wrong by itself (open PRs without an issue, ...)
    NOT RUN        checks that could not run here (no Linear key, Pi unreachable, ...)

A check that could not run is never reported as passing. Linear is read only (same GraphQL scope
as tools/graphify_context.py); GitHub is read through `gh` when available or the public REST API.
Nothing is written to Linear or GitHub: connecting the report to a pinned Linear maintenance
issue is documented in docs/WORKFLOW.md as a later step. Exit code 0 always: drift is a report,
not a build failure.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REPOS = {'party': 'rcnechamkin/avrana-party', 'games': 'rcnechamkin/avrana-party-games'}
LINEAR_TEAM = 'ed238b1d-b7ff-4f8b-b871-33b285a30fe1'
LINEAR_PROJECTS = ['59f36e2a-3b03-448c-9d2c-624078364def', 'ab4faaab-53ba-4e91-993f-3d563dc818fc']
AVR = re.compile(r'\bAVR-(\d+)\b', re.I)
ACTIVE_STATES = {'started', 'unstarted'}          # In Progress / In Review / Todo
RETAINED_PREFIXES = ('experiment/', 'docs/party-platform', 'ps1-emulation', 'local/')


class Report:
    def __init__(self):
        self.actionable, self.informational, self.not_run = [], [], []

    def action(self, check, text):
        self.actionable.append({'check': check, 'text': text})

    def info(self, check, text):
        self.informational.append({'check': check, 'text': text})

    def skip(self, check, why):
        self.not_run.append({'check': check, 'text': why})

    def as_dict(self):
        return {'schema': 'avrana.reconcile/v0', 'generated_at': now(),
                'actionable': self.actionable, 'informational': self.informational, 'not_run': self.not_run}

    def markdown(self):
        out = ['# Avrana drift reconciliation', '', f'Generated {now()}. Deterministic comparisons only; '
               'a check that could not run is listed as NOT RUN, never as passing.', '']
        for title, rows in (('Actionable drift', self.actionable), ('Informational', self.informational),
                            ('Checks that could not run', self.not_run)):
            out += [f'## {title} ({len(rows)})', '']
            out += [f'- **{r["check"]}**: {r["text"]}' for r in rows] or ['- none']
            out.append('')
        return '\n'.join(out)


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


# ---- sources ----------------------------------------------------------------------------------
class GitHub:
    """Read-only. `gh` when logged in (private repos, higher limits), else the public REST API."""

    def __init__(self, token=None):
        self.token = token or os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')

    def _api(self, path):
        req = urllib.request.Request(f'https://api.github.com{path}',
                                     headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'avrana-reconcile'})
        if self.token:
            req.add_header('Authorization', f'Bearer {self.token}')
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode('utf-8'))

    def pulls(self, repo, state='all', limit=200):
        rows, page = [], 1
        while len(rows) < limit:
            batch = self._api(f'/repos/{repo}/pulls?state={state}&per_page=100&page={page}&sort=updated&direction=desc')
            rows += batch
            if len(batch) < 100:
                break
            page += 1
        return rows[:limit]

    def branches(self, repo):
        rows, page = [], 1
        while True:
            batch = self._api(f'/repos/{repo}/branches?per_page=100&page={page}')
            rows += batch
            if len(batch) < 100:
                return rows
            page += 1

    def main_sha(self, repo):
        return self._api(f'/repos/{repo}/branches/main')['commit']['sha']


LINEAR_QUERY = '''query Reconcile($project: ID!, $team: ID!, $after: String) {
  issues(first: 100, after: $after, includeArchived: false,
    filter: {project: {id: {eq: $project}}, team: {id: {eq: $team}}}) {
    nodes { identifier title updatedAt completedAt state { name type } }
    pageInfo { hasNextPage endCursor }
  }
}'''


def linear_issues(token):
    issues = []
    for project in LINEAR_PROJECTS:
        after = None
        while True:
            body = json.dumps({'query': LINEAR_QUERY, 'variables': {'project': project, 'team': LINEAR_TEAM, 'after': after}}).encode()
            req = urllib.request.Request('https://api.linear.app/graphql', data=body,
                                         headers={'Content-Type': 'application/json', 'Authorization': token})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode('utf-8'))
            if data.get('errors'):
                raise RuntimeError('Linear returned errors')
            page = data['data']['issues']
            issues += page['nodes']
            if not page['pageInfo']['hasNextPage']:
                break
            after = page['pageInfo']['endCursor']
    return issues


def http_json(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode('utf-8'))


# ---- checks -----------------------------------------------------------------------------------
def issue_ids(*texts):
    found = set()
    for text in texts:
        for m in AVR.finditer(text or ''):
            found.add(f'AVR-{int(m[1])}')
    return found


def check_linear_vs_prs(report, issues, pulls_by_repo):
    """Done issues need a merged PR somewhere; merged PRs should not leave their issue active."""
    merged, open_prs = {}, {}
    for repo, pulls in pulls_by_repo.items():
        for pr in pulls:
            ids = issue_ids(pr.get('title'), pr.get('body'), (pr.get('head') or {}).get('ref'))
            target = merged if pr.get('merged_at') else (open_prs if pr.get('state') == 'open' else None)
            if target is None:
                continue
            for i in ids:
                target.setdefault(i, []).append(f'{repo}#{pr["number"]}')
    by_id = {i['identifier']: i for i in issues}
    lonely = sorted((i['identifier'] for i in issues if i['state']['type'] == 'completed' and i['identifier'] not in merged),
                    key=lambda ident: int(ident.split('-')[1]))
    if lonely:
        report.info('done-without-pr', f'{len(lonely)} Done issue(s) have no merged PR naming them: {", ".join(lonely)} '
                    '(normal for research, validation and ops issues; drift for an implementation issue)')
    for ident, prs in merged.items():
        issue = by_id.get(ident)
        if issue and issue['state']['type'] in ACTIVE_STATES and issue['state']['name'] in ('Todo', 'In Progress'):
            report.action('merged-but-active', f'{ident} has merged PR(s) {", ".join(prs)} but is still {issue["state"]["name"]}; '
                          'move it to In Review (or Done with evidence)')
    for ident, prs in open_prs.items():
        issue = by_id.get(ident)
        if issue and issue['state']['type'] == 'completed':
            report.action('open-pr-on-done-issue', f'{ident} is Done but PR(s) {", ".join(prs)} are still open')
        if issue is None:
            report.info('pr-unknown-issue', f'PR(s) {", ".join(prs)} name {ident}, which is not in the configured Linear projects')


def check_prs_without_issue(report, pulls_by_repo):
    for repo, pulls in pulls_by_repo.items():
        for pr in pulls:
            if pr.get('state') != 'open':
                continue
            if not issue_ids(pr.get('title'), pr.get('body'), (pr.get('head') or {}).get('ref')):
                report.info('pr-without-avr', f'{repo}#{pr["number"]} "{pr["title"]}" has no AVR reference '
                            '(expected for docs/chores; add one when it implements an issue)')


def check_orphan_branches(report, branches_by_repo, pulls_by_repo, retained):
    for repo, branches in branches_by_repo.items():
        heads = {(p.get('head') or {}).get('ref') for p in pulls_by_repo.get(repo, []) if p.get('state') == 'open'}
        merged_heads = {(p.get('head') or {}).get('ref') for p in pulls_by_repo.get(repo, []) if p.get('merged_at')}
        for b in branches:
            name = b['name']
            if name == 'main' or name in heads or name in retained or name.startswith(RETAINED_PREFIXES):
                continue
            if name in merged_heads:
                report.info('merged-branch-remains', f'{repo}: branch {name} was merged and can be deleted')
            else:
                report.info('branch-without-pr', f'{repo}: branch {name} has no open PR')


def check_deployment(report, status_doc, main_shas):
    if status_doc is None:
        return
    dep = status_doc.get('deployment')
    if not dep:
        report.action('no-deployment-manifest', 'the appliance has no deployment manifest; the next release should go through ops/deploy.sh')
    for name in ('party', 'games'):
        repo = status_doc.get(name, {})
        deployed = repo.get('deployed_sha') or repo.get('checkout_sha')
        main = main_shas.get(name)
        if repo.get('mismatch'):
            report.action('checkout-differs', f'{name}: the production checkout differs from the deployment manifest')
        if repo.get('dirty'):
            report.action('dirty-checkout', f'{name}: the production checkout has uncommitted changes')
        if deployed and main and deployed != main:
            report.info('deployed-behind-main', f'{name}: deployed {deployed[:12]} differs from main {main[:12]} (merged is not deployed)')
    summary = status_doc.get('summary', {})
    if summary.get('state') == 'degraded':
        report.action('appliance-degraded', '; '.join(summary.get('reasons', [])) or 'degraded')
    cert = status_doc.get('certificate', {})
    if cert.get('status') in ('expiring', 'expired'):
        report.action('certificate', f'certificate {cert["status"]} ({cert.get("days_left")} days left)')
    if status_doc.get('games_provider', {}).get('compatible') is False:
        report.action('contract-mismatch-live', 'the running games server advertises a different launch integration than Party implements')


def run_local(report, games):
    """Repository-side checks: docs integrity and the contract (both deterministic scripts)."""
    r = subprocess.run([sys.executable, str(ROOT / 'tools/repo-check.py')], capture_output=True, text=True, cwd=ROOT)
    if r.returncode:
        report.action('docs-integrity', 'tools/repo-check.py fails on this checkout: ' + r.stderr.strip().splitlines()[-1])
    else:
        report.info('docs-integrity', 'repository integrity OK')
    args = ['--games', str(games)] if games else []
    r = subprocess.run([sys.executable, str(ROOT / 'tools/contract_check.py'), *args], capture_output=True, text=True, cwd=ROOT)
    if r.returncode:
        report.action('contract', r.stderr.strip())
    elif games:
        report.info('contract', 'Party <-> Games declarations compatible')
    else:
        report.skip('contract-cross', 'no Games checkout given (--games); only the Party side was checked')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--games', help='a Games checkout for the cross-repository contract check')
    ap.add_argument('--status-url', help='the appliance status endpoint (reachable only on the Party LAN)')
    ap.add_argument('--out', default='reconcile-report', help='write <out>.md and <out>.json')
    ap.add_argument('--no-network', action='store_true', help='repository checks only')
    args = ap.parse_args(argv)
    report = Report()
    run_local(report, args.games)
    main_shas, pulls, branches = {}, {}, {}
    if args.no_network:
        for check in ('linear-vs-prs', 'prs-without-issue', 'orphan-branches', 'deployment'):
            report.skip(check, '--no-network')
    else:
        gh = GitHub()
        try:
            for name, repo in REPOS.items():
                pulls[name] = gh.pulls(repo)
                branches[name] = gh.branches(repo)
                main_shas[name] = gh.main_sha(repo)
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            report.skip('github', f'GitHub unreachable or refused ({type(e).__name__}); PR/branch checks not run')
            pulls, branches = {}, {}
        token = os.environ.get('LINEAR_API_KEY')
        issues = None
        if not token:
            report.skip('linear-vs-prs', 'LINEAR_API_KEY not set; Linear <-> PR checks not run')
        else:
            try:
                issues = linear_issues(token)
            except (urllib.error.URLError, OSError, ValueError, RuntimeError, KeyError) as e:
                report.skip('linear-vs-prs', f'Linear unreachable or refused ({type(e).__name__})')
        if pulls:
            if issues is not None:
                check_linear_vs_prs(report, issues, pulls)
            check_prs_without_issue(report, pulls)
            try:
                retained = {b['name'] for b in json.loads((ROOT / 'docs/branches.json').read_text(encoding='utf-8'))['branches']}
            except (OSError, ValueError, KeyError):
                retained = set()
            check_orphan_branches(report, branches, pulls, retained)
        status_doc = None
        if args.status_url:
            try:
                status_doc = http_json(args.status_url)
            except (urllib.error.URLError, OSError, ValueError) as e:
                report.skip('deployment', f'status endpoint unreachable ({type(e).__name__}); deployed-version checks not run')
        else:
            report.skip('deployment', 'no --status-url (the Pi is only reachable on the Party LAN); deployed-version checks not run')
        check_deployment(report, status_doc, main_shas)
    out = Path(args.out)
    out.with_suffix('.md').write_text(report.markdown(), encoding='utf-8')
    out.with_suffix('.json').write_text(json.dumps(report.as_dict(), indent=2) + '\n', encoding='utf-8')
    print(report.markdown())
    return 0


if __name__ == '__main__':
    sys.exit(main())
