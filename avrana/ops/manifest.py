"""The deployment manifest: runtime-owned truth about what was deployed (avrana.deployment/v0).

    python3 -m avrana.ops.manifest write --out /var/lib/avrana-party/deployment.json \
        --party /home/cody/avrana-party --games /home/cody/avrana-party-games \
        --web-root /var/www/avrana-party/web [--allow-dirty] [--restarted UNIT ...]
    python3 -m avrana.ops.manifest validate /var/lib/avrana-party/deployment.json
    python3 -m avrana.ops.manifest smoke /var/lib/avrana-party/deployment.json passed|failed

Written by ops/deploy.sh after the checkouts are at their intended commits; read by
/party/api/status, the smoke checks and tools/reconcile.py. The deployed system is authoritative
about what runs on it: documentation (SYSTEM) is updated *from* this file, never the other way.

Schema (docs/design/DEPLOYMENT-MANIFEST.md):
    schema         "avrana.deployment/v0"
    deployed_at    ISO 8601 UTC
    deployed_by    login name of the operator (never a secret)
    tool           {"name": "ops/deploy.sh", "party_sha": <sha the tool ran from>}
    party, games   {"sha", "short", "dirty", "untracked", "ref", "checkout"}; dirty = tracked files
                   modified; untracked = count of untracked, non-ignored files (recorded, not refused)
    web_release    {"path", "build", "commit"} from the installed version.json, or null
    contract       {"party_games", "party_session", "lan_launch"}
    restarted      [unit names restarted by this deployment]
    smoke          {"status": "pending"|"passed"|"failed"|"skipped", "at": ISO 8601} or null
"""
import argparse
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from avrana.contracts import party_games

SCHEMA = 'avrana.deployment/v0'
DEFAULT_PATH = '/var/lib/avrana-party/deployment.json'
SHA = re.compile(r'^[0-9a-f]{40}$')
SMOKE_STATES = ('pending', 'passed', 'failed', 'skipped')


class ManifestError(ValueError):
    pass


def utcnow():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _git(checkout, *args):
    out = subprocess.run(['git', '-C', str(checkout), *args], check=True, capture_output=True,
                         timeout=30)
    return out.stdout.decode('utf-8', 'replace').strip()


def observe_checkout(checkout):
    """{"sha", "short", "dirty", "ref", "checkout"} for a Git checkout; raises ManifestError."""
    checkout = Path(checkout)
    try:
        sha = _git(checkout, 'rev-parse', 'HEAD')
        lines = [l for l in _git(checkout, 'status', '--porcelain').splitlines() if l.strip()]
        ref = _git(checkout, 'rev-parse', '--abbrev-ref', 'HEAD')
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
        raise ManifestError(f'{checkout}: not a readable git checkout ({type(e).__name__})')
    if not SHA.match(sha):
        raise ManifestError(f'{checkout}: unexpected HEAD {sha!r}')
    untracked = sum(1 for l in lines if l.startswith('??'))
    return {'sha': sha, 'short': sha[:12], 'dirty': len(lines) > untracked, 'untracked': untracked,
            'ref': None if ref == 'HEAD' else ref, 'checkout': str(checkout)}


def observe_web_release(web_root):
    """The installed shell release: resolve `current`, read its version.json. None when absent."""
    current = Path(web_root) / 'current'
    if not current.exists():
        return None
    try:
        path = current.resolve()
        version = json.loads((path / 'version.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'path': str(current), 'build': None, 'commit': None}
    return {'path': str(path), 'build': version.get('build'), 'commit': version.get('commit')}


def build(party, games, web_release=None, *, restarted=(), deployed_by=None, tool_sha=None,
          contract=None, now=None):
    return {
        'schema': SCHEMA,
        'deployed_at': now or utcnow(),
        'deployed_by': deployed_by or os.environ.get('SUDO_USER') or _login(),
        'tool': {'name': 'ops/deploy.sh', 'party_sha': tool_sha or party['sha']},
        'party': dict(party),
        'games': dict(games),
        'web_release': web_release,
        'contract': contract or party_games.versions(),
        'restarted': list(restarted),
        'smoke': {'status': 'pending', 'at': None},
    }


def _login():
    try:
        return getpass.getuser()
    except Exception:  # no passwd entry inside a sandbox
        return 'unknown'


def validate(doc):
    """A list of human-readable problems; empty when the manifest is well formed."""
    errors = []
    if not isinstance(doc, dict):
        return ['manifest is not a JSON object']
    if doc.get('schema') != SCHEMA:
        errors.append(f'schema must be {SCHEMA}')
    if not _iso(doc.get('deployed_at')):
        errors.append('deployed_at must be an ISO 8601 UTC timestamp')
    if not isinstance(doc.get('deployed_by'), str) or not doc.get('deployed_by'):
        errors.append('deployed_by must be a non-empty string')
    tool = doc.get('tool')
    if not isinstance(tool, dict) or not isinstance(tool.get('name'), str) or not SHA.match(str(tool.get('party_sha', ''))):
        errors.append('tool must carry name and the 40-hex party_sha it ran from')
    for repo in ('party', 'games'):
        r = doc.get(repo)
        if not isinstance(r, dict) or not SHA.match(str(r.get('sha', ''))):
            errors.append(f'{repo}.sha must be a 40-hex commit')
            continue
        if r.get('short') != r['sha'][:12]:
            errors.append(f'{repo}.short must be the first 12 characters of sha')
        if not isinstance(r.get('dirty'), bool):
            errors.append(f'{repo}.dirty must be a boolean')
        if 'untracked' in r and (not isinstance(r['untracked'], int) or isinstance(r['untracked'], bool) or r['untracked'] < 0):
            errors.append(f'{repo}.untracked must be a non-negative integer')
        if not isinstance(r.get('checkout'), str):
            errors.append(f'{repo}.checkout must be a path string')
    web = doc.get('web_release')
    if web is not None and (not isinstance(web, dict) or not isinstance(web.get('path'), str)):
        errors.append('web_release must be null or carry a path')
    contract = doc.get('contract')
    if not isinstance(contract, dict) or set(contract) != {'party_games', 'party_session', 'lan_launch'}:
        errors.append('contract must name party_games, party_session and lan_launch')
    if not isinstance(doc.get('restarted'), list) or not all(isinstance(u, str) for u in doc['restarted']):
        errors.append('restarted must be a list of unit names')
    smoke = doc.get('smoke')
    if smoke is not None and (not isinstance(smoke, dict) or smoke.get('status') not in SMOKE_STATES
                              or (smoke.get('at') is not None and not _iso(smoke['at']))):
        errors.append(f'smoke must be null or {{status: {"|".join(SMOKE_STATES)}, at}}')
    for key in ('privkey', 'token', 'password', 'secret'):
        if key in json.dumps(doc).lower():
            errors.append(f'manifest text must not contain {key!r}')
    return errors


def _iso(value):
    if not isinstance(value, str) or not value.endswith('Z'):
        return False
    try:
        datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return False
    return True


def write(path, doc):
    """Atomic write (0644 on POSIX) after validation."""
    errors = validate(doc)
    if errors:
        raise ManifestError('; '.join(errors))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.new')
    temporary.write_text(json.dumps(doc, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    if os.name == 'posix':
        os.chmod(temporary, 0o644)
    os.replace(temporary, path)
    return path


def read(path):
    """The manifest, None when the file does not exist, ManifestError when it is malformed."""
    path = Path(path)
    try:
        if not path.exists():
            return None
        doc = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise ManifestError(f'{path}: unreadable ({type(e).__name__})')
    errors = validate(doc)
    if errors:
        raise ManifestError(f'{path}: ' + '; '.join(errors))
    return doc


def record_smoke(path, status, now=None):
    doc = read(path)
    if doc is None:
        raise ManifestError(f'{path}: no manifest to update')
    if status not in SMOKE_STATES:
        raise ManifestError(f'smoke status must be one of {SMOKE_STATES}')
    doc['smoke'] = {'status': status, 'at': now or utcnow()}
    return write(path, doc)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='command', required=True)
    w = sub.add_parser('write', help='observe the checkouts and write the manifest')
    w.add_argument('--out', default=DEFAULT_PATH)
    w.add_argument('--party', required=True, help='production Party checkout')
    w.add_argument('--games', required=True, help='production Games checkout')
    w.add_argument('--web-root', default='/var/www/avrana-party/web')
    w.add_argument('--restarted', nargs='*', default=[])
    w.add_argument('--allow-dirty', action='store_true', help='record, rather than refuse, a dirty checkout')
    w.add_argument('--tool-sha', default=None, help='the Party commit ops/deploy.sh ran from')
    v = sub.add_parser('validate', help='exit 1 when the manifest is malformed')
    v.add_argument('path', nargs='?', default=DEFAULT_PATH)
    s = sub.add_parser('smoke', help='record the smoke result')
    s.add_argument('path')
    s.add_argument('status', choices=SMOKE_STATES)
    args = ap.parse_args(argv)
    try:
        if args.command == 'write':
            party, games = observe_checkout(args.party), observe_checkout(args.games)
            for name, repo in (('party', party), ('games', games)):
                if repo['dirty'] and not args.allow_dirty:
                    raise ManifestError(f'{name} checkout {repo["checkout"]} has uncommitted changes; '
                                        'deploy a clean reviewed commit or pass --allow-dirty')
            doc = build(party, games, observe_web_release(args.web_root), restarted=args.restarted,
                        tool_sha=args.tool_sha)
            write(args.out, doc)
            print(json.dumps({'written': str(args.out), 'party': party['short'],
                              'games': games['short'], 'dirty': party['dirty'] or games['dirty']}))
        elif args.command == 'validate':
            doc = read(args.path)
            if doc is None:
                raise ManifestError(f'{args.path}: no deployment manifest (nothing deployed with ops/deploy.sh yet)')
            print(f'{args.path}: valid {SCHEMA}, party {doc["party"]["short"]}, games {doc["games"]["short"]}')
        else:
            record_smoke(args.path, args.status)
            print(f'{args.path}: smoke {args.status}')
    except ManifestError as e:
        print(f'deployment manifest: {e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
