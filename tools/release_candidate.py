#!/usr/bin/env python3
"""Assemble, verify and rehearse a release candidate: one Party commit and one Games commit (AVR-699).

    python tools/release_candidate.py assemble --party-repo P --games-repo G --party REV --games REV --out DIR [--bundle]
    python tools/release_candidate.py verify MANIFEST --party-repo P --games-repo G
    python tools/release_candidate.py prereq MANIFEST --preflight PREFLIGHT.json [--status STATUS.json] [--max-age-min 60]
    python tools/release_candidate.py rehearse-rollback MANIFEST --party-repo P --games-repo G [--before-party SHA --before-games SHA]

Nothing here installs, deploys, restarts or touches the appliance. It is the paperwork and the rehearsal
that come BEFORE the owner runs ops/deploy.sh on the Pi:

  assemble          Resolve both revisions to full SHAs, record what each commit is (date, tree, whether it is on
                    origin/main, the SHA-256 of `git archive`), export both exact trees to a temporary directory and run
                    the existing tools/contract_check.py on THOSE trees, record the contract versions, the Party layer
                    digest Games pins against the one Party ships, the runtime pins and the package-lock digest, and
                    write release-candidate.json (avrana.release-candidate/v0) and release-candidate.md. With --bundle
                    it also writes party.bundle and games.bundle (git bundles of exactly each SHA's history) so the
                    candidate can be reproduced offline. It uses only refs that are already in the two repositories:
                    the operator runs `git fetch` first. It never touches the network.
  verify            Re-derive everything from the same two SHAs and report each difference from the manifest.
  prereq            Check the prerequisites of an intended installation, WITHOUT doing it: the candidate manifest, the
                    preflight document of the sibling track (python3 -m avrana.ops.preflight --json) and, optionally,
                    /party/api/status for the last known good. Prints CLEARED_FOR_OWNER or BLOCKED and, when cleared,
                    the exact owner commands (printed, never run).
  rehearse-rollback A non-destructive rehearsal of ops/deploy.sh --dry-run and --rollback --dry-run in a disposable
                    scratch root (throwaway clones, every AVRANA_* path inside it), then proves the scratch root and both
                    real repositories are unchanged. It says what it cannot reproduce.

Exit codes. assemble: 0 CANDIDATE_OK, 1 CANDIDATE_FLAGGED (the files are still written), 2 error (nothing written).
verify: 0 reproduced, 1 differences, 2 error. prereq: 0 only for CLEARED_FOR_OWNER, 1 for BLOCKED (also for a missing or
unreadable input; a cleared result is never printed then). rehearse-rollback: 0 no step failed, 1 a step failed, 2 the
rehearsal could not be set up. A usage error is 2 everywhere. Stdlib only.
"""
import argparse
import datetime
import getpass
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCHEMA = 'avrana.release-candidate/v0'
PREFLIGHT_SCHEMA = 'avrana.preflight/v0'
STATUS_SCHEMA = 'avrana.status/v0'
PREREQ_SCHEMA = 'avrana.release-prereq/v0'
REHEARSAL_SCHEMA = 'avrana.release-rehearsal/v0'
MANIFEST_NAME = 'release-candidate.json'
SUMMARY_NAME = 'release-candidate.md'
SHA_RX = re.compile(r'^[0-9a-f]{40}$')
LAYER_MOUNT = 'web/party/bridge/layer-mount.js'
BUNDLE_REF = 'refs/heads/release-candidate'
DEFAULT_DEPLOY_SCRIPT = '/home/cody/avrana-party/ops/deploy.sh'
REQUIRED_TOOLS = ('python3', 'git', 'nginx', 'openssl', 'curl', 'sudo')   # named by deploy/appliance-inventory.json
VERDICTS = ('CANDIDATE_OK', 'CANDIDATE_FLAGGED')
# Fields that differ between two honest assemblies of the same pair: never compared by `verify`.
VERIFY_IGNORED = ('generated_at', 'tool', 'bundles')
# Fields that move when origin/main moves on, without the candidate changing: a note, not a difference.
VERIFY_NOTE_ONLY = ('party.origin_main_sha', 'games.origin_main_sha')


class ReleaseError(Exception):
    """The tool cannot do what was asked; the message says why."""


# ---- small helpers ----------------------------------------------------------------------------
def utcnow():
    epoch = os.environ.get('SOURCE_DATE_EPOCH')           # lets a test (or a reproducible build) pin the clock
    if epoch and epoch.isdigit():
        return datetime.datetime.fromtimestamp(int(epoch), datetime.timezone.utc)
    return datetime.datetime.now(datetime.timezone.utc)


def iso(moment):
    return moment.replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def parse_time(text):
    if not isinstance(text, str) or not text:
        raise ValueError('no timestamp')
    moment = datetime.datetime.fromisoformat(text.strip().replace('Z', '+00:00'))
    return moment if moment.tzinfo else moment.replace(tzinfo=datetime.timezone.utc)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def sha256_normalized(path):
    """Line endings normalized, exactly as tools/contract_check.py digests a file."""
    return sha256_bytes(Path(path).read_bytes().replace(b'\r\n', b'\n'))


def posix(path):
    return Path(path).as_posix()


def write_text(path, text):
    Path(path).write_text(text, encoding='utf-8', newline='\n')


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def rmtree(path):
    def onerror(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    shutil.rmtree(path, onerror=onerror)


# ---- git --------------------------------------------------------------------------------------
def git_cmd(repo, *args):
    return ['git', '-c', 'core.autocrlf=false', '-c', 'core.safecrlf=false', '-c', 'core.quotepath=false',
            '-C', str(repo), *args]


def git_env():
    return dict(os.environ, GIT_OPTIONAL_LOCKS='0', GIT_TERMINAL_PROMPT='0')


def git(repo, *args, check=True, timeout=600):
    try:
        p = subprocess.run(git_cmd(repo, *args), capture_output=True, env=git_env(), timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ReleaseError(f'git {args[0] if args else ""} could not run in {repo} ({type(e).__name__})')
    if check and p.returncode != 0:
        err = p.stderr.decode('utf-8', 'replace').strip().splitlines()
        raise ReleaseError(f'git {args[0]} failed in {repo}: {err[-1] if err else "exit " + str(p.returncode)}')
    return p


def git_text(repo, *args):
    return git(repo, *args).stdout.decode('utf-8', 'replace').strip()


def check_repo(repo, what):
    repo = Path(repo)
    if not repo.is_dir():
        raise ReleaseError(f'{what} repository {repo} is not a directory')
    if git(repo, 'rev-parse', '--git-dir', check=False).returncode != 0:
        raise ReleaseError(f'{what} repository {repo} is not a git checkout')
    return repo


def resolve_commit(repo, rev):
    """The full 40-character SHA of a revision that is already in the repository (nothing is fetched)."""
    if not isinstance(rev, str) or not rev or rev.startswith('-'):
        raise ReleaseError(f'{rev!r} is not a revision')
    p = git(repo, 'rev-parse', '--verify', '--quiet', '--end-of-options', rev + '^{commit}', check=False)
    sha = p.stdout.decode().strip()
    if p.returncode != 0 or not SHA_RX.match(sha):
        raise ReleaseError(f'{rev!r} does not name a commit in {repo}; fetch it first (this tool never fetches)')
    return sha


def has_commit(repo, sha):
    return git(repo, 'cat-file', '-e', sha + '^{commit}', check=False).returncode == 0


def origin_main(repo):
    p = git(repo, 'rev-parse', '--verify', '--quiet', 'refs/remotes/origin/main^{commit}', check=False)
    sha = p.stdout.decode().strip()
    return sha if p.returncode == 0 and SHA_RX.match(sha) else None


def archive_digest(repo, sha):
    """SHA-256 and size of `git archive --format=tar <sha>`: the deterministic digest of the exact tree. Run with
    core.autocrlf=false (git_cmd): a Windows git with autocrlf=true would otherwise put CRLF into the archive."""
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(git_cmd(repo, 'archive', '--format=tar', sha), stdout=subprocess.PIPE, stderr=err,
                                env=git_env())
        h, size = hashlib.sha256(), 0
        for chunk in iter(lambda: proc.stdout.read(1 << 20), b''):
            h.update(chunk)
            size += len(chunk)
        proc.stdout.close()
        if proc.wait() != 0:
            err.seek(0)
            raise ReleaseError(f'git archive {sha[:12]} failed in {repo}: {err.read().decode("utf-8", "replace").strip()}')
    return h.hexdigest(), size


def export_tree(repo, sha, dest):
    """Unpack exactly the tracked files of a commit into `dest` (what ops/deploy.sh stages with git archive).
    Links are not created (none are tracked; a Windows checkout cannot always make them)."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(git_cmd(repo, 'archive', '--format=tar', sha), stdout=subprocess.PIPE, stderr=err,
                                env=git_env())
        try:
            with tarfile.open(fileobj=proc.stdout, mode='r|') as tf:
                for member in tf:
                    target = (root / member.name).resolve()
                    if member.name.startswith(('/', '\\')) or not (target == root or root in target.parents):
                        raise ReleaseError(f'{sha[:12]}: archive member {member.name!r} leaves the export directory')
                    if not (member.isfile() or member.isdir()):
                        continue
                    if hasattr(tarfile, 'data_filter'):
                        tf.extract(member, root, filter='data')
                    else:
                        tf.extract(member, root)
            for _ in iter(lambda: proc.stdout.read(1 << 20), b''):
                pass
        except (tarfile.TarError, OSError) as e:
            proc.kill()
            raise ReleaseError(f'cannot export {sha[:12]} from {repo} ({type(e).__name__}: {e})')
        finally:
            proc.stdout.close()
        if proc.wait() != 0:
            err.seek(0)
            raise ReleaseError(f'git archive {sha[:12]} failed in {repo}: {err.read().decode("utf-8", "replace").strip()}')
    return dest


def describe_commit(repo, requested, sha):
    fmt = git_text(repo, 'show', '-s', '--format=%cI%n%T%n%P%n%s', sha).split('\n')
    digest, size = archive_digest(repo, sha)
    main_sha = origin_main(repo)
    if main_sha is None:
        on_main = None
    else:
        on_main = git(repo, 'merge-base', '--is-ancestor', sha, main_sha, check=False).returncode == 0
    return {
        'requested': requested,
        'sha': sha,
        'short': sha[:12],
        'subject': fmt[3] if len(fmt) > 3 else '',
        'commit_date': fmt[0],
        'tree_sha': fmt[1],
        'parents': fmt[2].split() if len(fmt) > 2 and fmt[2] else [],
        'origin_main_sha': main_sha,
        'on_origin_main': on_main,
        'archive_sha256': digest,
        'archive_bytes': size,
    }


# ---- what the two exact trees say -------------------------------------------------------------
def run_contract_check(party_tree, games_tree):
    """tools/contract_check.py of the candidate Party tree, on the two exact trees (as ops/deploy.sh runs it)."""
    checker = party_tree / 'tools/contract_check.py'
    if not checker.is_file():
        return {'status': 'not_checkable', 'exit_code': None,
                'message': 'the Party commit predates tools/contract_check.py; the pair was not checked'}
    if not (games_tree / 'provider/avrana-contract.json').is_file():
        return {'status': 'not_checkable', 'exit_code': None,
                'message': 'the Games commit has no provider/avrana-contract.json; the pair was not checked'}
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    try:
        p = subprocess.run([sys.executable, '-I', 'tools/contract_check.py', '--party', str(party_tree),
                            '--games', str(games_tree)], cwd=party_tree, capture_output=True, env=env, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {'status': 'not_checkable', 'exit_code': None, 'message': f'the checker could not run ({type(e).__name__})'}
    out = p.stdout.decode('utf-8', 'replace').strip()
    err = p.stderr.decode('utf-8', 'replace').strip()
    if p.returncode == 0:
        last = out.splitlines()[-1] if out else ''
        return {'status': 'compatible', 'exit_code': 0, 'message': last}
    return {'status': 'incompatible', 'exit_code': p.returncode,
            'message': (err or out or f'exited {p.returncode}').splitlines()[-1][:600]}


def read_declaration(tree, rel):
    path = tree / rel
    if not path.is_file():
        return None, f'{rel} is not in the tree'
    try:
        doc = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        return None, f'{rel} is unreadable ({type(e).__name__})'
    return (doc, None) if isinstance(doc, dict) else (None, f'{rel} is not a JSON object')


def dig(doc, *keys):
    for key in keys:
        if not isinstance(doc, dict) or key not in doc:
            return None
        doc = doc[key]
    return doc


def contract_versions(pdecl, gdecl):
    pairs = {
        'party_games': (dig(pdecl, 'contract'), dig(gdecl, 'requires')),
        'session_protocol': (dig(pdecl, 'session_protocol', 'version'), dig(gdecl, 'session_protocol', 'version')),
        'result_schema': (dig(pdecl, 'result', 'schema'), dig(gdecl, 'result', 'schema')),
        'bridge_protocol': (dig(pdecl, 'bridge', 'protocol'), dig(gdecl, 'bridge', 'protocol')),
        'layer_protocol': (dig(pdecl, 'layer', 'protocol'), dig(gdecl, 'layer', 'protocol')),
        'launch_integration': (dig(pdecl, 'launch', 'integration'), dig(gdecl, 'launch', 'integration')),
    }
    return {k: {'party': p, 'games': g, 'match': (p == g) if p is not None and g is not None else None}
            for k, (p, g) in pairs.items()}


def layer_state(party_tree, pdecl, gdecl):
    """The digest of the Party layer mount Games pins against the one this Party commit ships."""
    declared = dig(pdecl, 'layer', 'reference_sha256')
    pinned = dig(gdecl, 'layer', 'vendored_sha256')
    rel = dig(pdecl, 'layer', 'reference') or LAYER_MOUNT
    mount = party_tree / rel if isinstance(rel, str) else None
    actual = sha256_normalized(mount) if mount is not None and mount.is_file() else None
    if gdecl is None:
        status = 'unknown'
    elif 'layer' not in gdecl:
        status = 'not_vendored'
    elif pinned is None or actual is None:
        status = 'incomplete'
    else:
        status = 'match' if pinned == actual else 'mismatch'
    return {'status': status, 'party_file': rel if isinstance(rel, str) else LAYER_MOUNT,
            'party_actual_sha256': actual, 'party_declared_sha256': declared, 'games_pinned_sha256': pinned}


def runtime_pins(party_tree):
    inventory, _ = read_declaration(party_tree, 'deploy/appliance-inventory.json')
    packages = {p.get('name'): p for p in (inventory or {}).get('packages', []) if isinstance(p, dict)}
    python_min = None
    m = re.search(r'(\d+\.\d+) or newer', str((packages.get('python3') or {}).get('why', '')))
    if m:
        python_min = m.group(1)
    node_version = None
    pin = party_tree / 'avrana/avrgame/node_pin.py'
    if pin.is_file():
        m = re.search(r"^VERSION\s*=\s*['\"]([^'\"]+)['\"]", pin.read_text(encoding='utf-8'), re.M)
        node_version = m.group(1) if m else None
    lock = party_tree / 'package-lock.json'
    return {
        'python_minimum': python_min,
        'node_runtime_version': node_version,
        'node_runtime_note': 'optional: only an EXPERIMENTAL .avrgame package that names the node interpreter needs it; '
                             'it is installed by the owner from a tarball (ops/install-node-runtime), never by a deploy',
        'required_tools': [{'name': n, 'why': (packages.get(n) or {}).get('why')} for n in REQUIRED_TOOLS
                           if n in packages or n in ('nginx', 'openssl')],
        'package_lock_sha256': sha256_file(lock) if lock.is_file() else None,
    }


def run_sbom(party_tree):
    if not (party_tree / 'tools/sbom.py').is_file():
        return {'status': 'not_checkable', 'message': 'tools/sbom.py is not in this Party commit'}
    try:
        p = subprocess.run([sys.executable, '-I', 'tools/sbom.py', '--check', '--root', str(party_tree)],
                           cwd=party_tree, capture_output=True, timeout=180,
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
    except (OSError, subprocess.TimeoutExpired) as e:
        return {'status': 'not_checkable', 'message': f'the inventory check could not run ({type(e).__name__})'}
    lines = (p.stdout.decode('utf-8', 'replace') + p.stderr.decode('utf-8', 'replace')).strip().splitlines()
    return {'status': 'ok' if p.returncode == 0 else 'failed', 'message': (lines[-1] if lines else '')[:300]}


def tool_identity():
    sha = dirty = None
    try:
        sha = git_text(REPO, 'rev-parse', 'HEAD')
        dirty = bool(git_text(REPO, 'status', '--porcelain', '--untracked-files=no'))
    except ReleaseError:
        pass
    return {'name': 'tools/release_candidate.py', 'party_sha': sha, 'dirty': dirty,
            'script_sha256': sha256_normalized(Path(__file__)), 'python': platform.python_version()}


# ---- the flags and the verdict ----------------------------------------------------------------
def make_flags(doc):
    flags = []

    def flag(fid, severity, reason):
        flags.append({'id': fid, 'severity': severity, 'reason': reason})

    for name in ('party', 'games'):
        side = doc[name]
        if side['on_origin_main'] is None:
            flag(f'{name}_origin_main_unknown', 'WARN',
                 f'the {name} repository has no origin/main ref, so it is unknown whether {side["short"]} is on it '
                 '(run git fetch origin there first)')
        elif side['on_origin_main'] is False:
            reason = f'{name} {side["short"]} is not an ancestor of origin/main ({side["origin_main_sha"][:12]}).'
            if name == 'party':
                reason += (' ops/deploy.sh refuses a Party commit that is not on origin/main unless the owner passes '
                           '--allow-branch (a supervised test); merge it first.')
            else:
                reason += ' Stage it on the Pi deliberately (docs/runbooks/games-fork-deploy.md); it is not the main line.'
            flag(f'{name}_not_on_origin_main', 'WARN', reason)
    check = doc['contract_check']
    if check['status'] == 'incompatible':
        flag('contract_incompatible', 'FAIL', 'tools/contract_check.py says the pair disagrees: ' + check['message'])
    elif check['status'] == 'not_checkable':
        flag('contract_not_checkable', 'WARN', check['message'])
    for key, row in doc['contracts'].items():
        if row['match'] is False:
            if key == 'party_games':
                flag('contract_version_mismatch', 'FAIL',
                     f'Party implements {row["party"]!r} but Games requires {row["games"]!r}')
            else:
                flag(f'{key}_mismatch', 'FAIL', f'{key}: Party declares {row["party"]!r}, Games declares {row["games"]!r}')
    layer = doc['layer']
    if layer['status'] == 'mismatch':
        flag('layer_digest_mismatch', 'FAIL',
             f'Games pins Party layer digest {layer["games_pinned_sha256"][:16]}... but this Party commit ships '
             f'{layer["party_file"]} with {layer["party_actual_sha256"][:16]}...; re-vendor with ops/vendor_party.py in Games')
    elif layer['status'] == 'incomplete':
        flag('layer_digest_incomplete', 'FAIL',
             f'Games pins a Party layer but {layer["party_file"]} is not in this Party commit (or Games pins no digest)')
    if layer['party_declared_sha256'] and layer['party_actual_sha256'] \
            and layer['party_declared_sha256'] != layer['party_actual_sha256']:
        flag('layer_declaration_drift', 'FAIL',
             f'contracts/party-games.v0.json declares layer digest {layer["party_declared_sha256"][:16]}... but '
             f'{layer["party_file"]} has {layer["party_actual_sha256"][:16]}...')
    rt = doc['runtime']
    if rt['package_lock_sha256'] is None:
        flag('package_lock_missing', 'WARN', 'package-lock.json is not in the Party commit')
    if rt['python_minimum'] is None:
        flag('python_minimum_unknown', 'WARN', 'deploy/appliance-inventory.json does not state a Python minimum')
    if rt['node_runtime_version'] is None:
        flag('node_pin_unknown', 'WARN', 'avrana/avrgame/node_pin.py does not state the pinned Node version')
    if doc['sbom']['status'] == 'failed':
        flag('sbom_inventory', 'WARN', 'tools/sbom.py --check failed: ' + doc['sbom']['message'])
    for note in doc.get('declaration_notes', []):
        flag('declaration_unreadable', 'WARN', note)
    return flags


def derive(party_repo, games_repo, party_rev, games_rev):
    """Everything a manifest says, derived from the two repositories now (no bundles, no files written)."""
    party_repo, games_repo = check_repo(party_repo, 'Party'), check_repo(games_repo, 'Games')
    party_sha, games_sha = resolve_commit(party_repo, party_rev), resolve_commit(games_repo, games_rev)
    party, games = describe_commit(party_repo, party_rev, party_sha), describe_commit(games_repo, games_rev, games_sha)
    work = Path(tempfile.mkdtemp(prefix='avrana-rc-trees-'))
    try:
        ptree, gtree = export_tree(party_repo, party_sha, work / 'party'), export_tree(games_repo, games_sha, work / 'games')
        pdecl, perr = read_declaration(ptree, 'contracts/party-games.v0.json')
        gdecl, gerr = read_declaration(gtree, 'provider/avrana-contract.json')
        notes = []
        if perr and (ptree / 'tools/contract_check.py').is_file():
            notes.append('Party: ' + perr)
        if gerr and (gtree / 'provider').is_dir():
            notes.append('Games: ' + gerr)
        doc = {
            'schema': SCHEMA,
            'generated_at': iso(utcnow()),
            'tool': tool_identity(),
            'digest_method': 'sha256 of `git -c core.autocrlf=false archive --format=tar <sha>` (the bytes ops/deploy.sh stages on Linux)',
            'party': party,
            'games': games,
            'contract_check': dict(run_contract_check(ptree, gtree),
                                   tool='tools/contract_check.py from the candidate Party tree, run on the two exact trees'),
            'contracts': contract_versions(pdecl, gdecl),
            'layer': layer_state(ptree, pdecl, gdecl),
            'runtime': runtime_pins(ptree),
            'sbom': run_sbom(ptree),
            'declaration_notes': notes,
            'bundles': None,
        }
    finally:
        rmtree(work)
    doc['flags'] = make_flags(doc)
    doc['verdict'] = 'CANDIDATE_FLAGGED' if doc['flags'] else 'CANDIDATE_OK'
    return doc


# ---- bundles ----------------------------------------------------------------------------------
def make_bundle(repo, sha, dest):
    """A git bundle of exactly this commit's history. A scratch bare repository borrows the source's objects
    (alternates, read-only), points one ref at the SHA and bundles that ref; the source repository is not written."""
    repo = Path(repo)
    common = git_text(repo, 'rev-parse', '--path-format=absolute', '--git-common-dir')
    scratch = Path(tempfile.mkdtemp(prefix='avrana-rc-bundle-'))
    try:
        bare = scratch / 'b.git'
        git(scratch, 'init', '--bare', '-q', str(bare))
        write_text(bare / 'objects/info/alternates', posix(Path(common) / 'objects') + '\n')
        git(bare, 'update-ref', BUNDLE_REF, sha)
        git(bare, 'symbolic-ref', 'HEAD', BUNDLE_REF)                # so that `git clone party.bundle` checks the SHA out
        git(bare, '-c', 'pack.threads=1', 'bundle', 'create', str(Path(dest).resolve()), 'HEAD', BUNDLE_REF)
    finally:
        rmtree(scratch)
    return bundle_record(dest, sha)


def bundle_heads(path):
    path = Path(path).resolve()
    p = subprocess.run(git_cmd(path.parent, 'bundle', 'list-heads', str(path)), capture_output=True,
                       env=git_env(), timeout=120)
    if p.returncode != 0:
        return None
    return [line.split(' ', 1) for line in p.stdout.decode().strip().splitlines()]


def bundle_holds(path, sha):
    """True when the bundle's only heads are HEAD and the release-candidate ref, both at exactly this SHA."""
    heads = bundle_heads(path)
    return heads is not None and sorted(heads) == sorted([[sha, 'HEAD'], [sha, BUNDLE_REF]])


def bundle_record(path, sha):
    path = Path(path)
    return {'file': path.name, 'sha256': sha256_file(path), 'bytes': path.stat().st_size, 'ref': BUNDLE_REF,
            'head': sha, 'verified_heads': bundle_holds(path, sha)}


# ---- assemble ---------------------------------------------------------------------------------
def render_summary(doc):
    p, g, c, lay, rt = doc['party'], doc['games'], doc['contract_check'], doc['layer'], doc['runtime']
    cv = doc['contracts']

    def where(side):
        return {True: 'on origin/main', False: 'NOT on origin/main', None: 'origin/main unknown'}[side['on_origin_main']]

    lines = [f'# Release candidate: Party {p["short"]} + Games {g["short"]}', '',
             f'Verdict: **{doc["verdict"]}**. Generated {doc["generated_at"]} by `{doc["tool"]["name"]}` '
             f'(Party {str(doc["tool"]["party_sha"])[:12]}). Schema `{doc["schema"]}`. '
             'This is paperwork: nothing was installed or deployed, and nothing here was run on the Pi.', '',
             '| | Party | Games |', '|---|---|---|',
             f'| commit | `{p["sha"]}` | `{g["sha"]}` |',
             f'| subject | {p["subject"]} | {g["subject"]} |',
             f'| commit date | {p["commit_date"]} | {g["commit_date"]} |',
             f'| tree | `{p["tree_sha"]}` | `{g["tree_sha"]}` |',
             f'| origin/main | {where(p)} | {where(g)} |',
             f'| git archive sha256 | `{p["archive_sha256"]}` | `{g["archive_sha256"]}` |', '',
             f'- Contract check (tools/contract_check.py on the two exact trees): **{c["status"]}**'
             + (f' - {c["message"]}' if c['message'] else ''),
             f'- Contract versions: Party implements `{cv["party_games"]["party"]}`, Games requires '
             f'`{cv["party_games"]["games"]}`; session `{cv["session_protocol"]["party"]}`, '
             f'result `{cv["result_schema"]["party"]}`, bridge `{cv["bridge_protocol"]["party"]}`, '
             f'layer `{cv["layer_protocol"]["party"]}`, launch `{cv["launch_integration"]["party"]}`',
             f'- Party layer ({lay["party_file"]}): **{lay["status"]}**; Games pins `{lay["games_pinned_sha256"]}`, '
             f'this Party ships `{lay["party_actual_sha256"]}`',
             f'- Runtime pins: Python {rt["python_minimum"]} or newer; optional Node runtime {rt["node_runtime_version"]}; '
             f'tools {", ".join(t["name"] for t in rt["required_tools"])}; package-lock.json sha256 `{rt["package_lock_sha256"]}`',
             f'- Third-party inventory (tools/sbom.py --check): {doc["sbom"]["status"]}', '']
    if doc.get('bundles'):
        lines.append('Offline reproduction (git bundles of exactly each SHA, ref `' + BUNDLE_REF + '`):')
        for name in ('party', 'games'):
            b = doc['bundles'][name]
            lines.append(f'- `{b["file"]}` sha256 `{b["sha256"]}` ({b["bytes"]} bytes)')
        lines.append('')
    lines += ['## Flags', '']
    if doc['flags']:
        lines += [f'- **{f["severity"]}** `{f["id"]}`: {f["reason"]}' for f in doc['flags']]
    else:
        lines.append('None.')
    lines += ['', 'Next: `verify` this manifest, take a preflight on the Pi, then `prereq`. '
              'See docs/runbooks/release-candidate.md.', '']
    return '\n'.join(lines)


def cmd_assemble(args):
    out = Path(args.out)
    manifest_path = out / MANIFEST_NAME
    if manifest_path.exists() and not args.force:
        raise ReleaseError(f'{manifest_path} exists; assemble into a new directory (or --force to replace it)')
    doc = derive(args.party_repo, args.games_repo, args.party, args.games)
    out.mkdir(parents=True, exist_ok=True)
    if args.bundle:
        doc['bundles'] = {'party': make_bundle(args.party_repo, doc['party']['sha'], out / 'party.bundle'),
                          'games': make_bundle(args.games_repo, doc['games']['sha'], out / 'games.bundle')}
        for name, b in doc['bundles'].items():
            if not b['verified_heads']:
                raise ReleaseError(f'{name}.bundle does not hold exactly {doc[name]["sha"]}')
    write_text(manifest_path, json.dumps(doc, indent=2) + '\n')
    write_text(out / SUMMARY_NAME, render_summary(doc))
    print(f'{manifest_path}: {doc["verdict"]} (party {doc["party"]["short"]}, games {doc["games"]["short"]})')
    for f in doc['flags']:
        print(f'  {f["severity"]} {f["id"]}: {f["reason"]}')
    for b in (doc['bundles'] or {}).values():
        print(f'  {b["file"]}: sha256 {b["sha256"]} ({b["bytes"]} bytes)')
    return 0 if doc['verdict'] == 'CANDIDATE_OK' else 1


# ---- verify -----------------------------------------------------------------------------------
def flatten(value, prefix=''):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            out.update(flatten(v, f'{prefix}.{k}' if prefix else k))
        return out
    if isinstance(value, list):
        if all(not isinstance(v, (dict, list)) for v in value):
            return {prefix: value}
        out = {}
        for i, v in enumerate(value):
            out.update(flatten(v, f'{prefix}[{i}]'))
        return out or {prefix: []}
    return {prefix: value}


def load_manifest(path):
    try:
        doc = load_json(path)
    except (OSError, ValueError) as e:
        raise ReleaseError(f'{path}: cannot read the manifest ({type(e).__name__})')
    if not isinstance(doc, dict) or doc.get('schema') != SCHEMA:
        raise ReleaseError(f'{path}: not a {SCHEMA} manifest')
    for name in ('party', 'games'):
        if not isinstance(doc.get(name), dict) or not SHA_RX.match(str(doc[name].get('sha', ''))):
            raise ReleaseError(f'{path}: {name}.sha is not a full 40-character SHA')
    return doc


def verify_manifest(manifest_path, party_repo, games_repo, bundle_dir=None):
    """(differences, notes): what the manifest says that the repositories no longer (or never) agreed with."""
    manifest = load_manifest(manifest_path)
    differences, notes = [], []
    fresh = derive(party_repo, games_repo, manifest['party']['sha'], manifest['games']['sha'])
    recorded, now = flatten(manifest), flatten(fresh)
    for key in sorted(set(recorded) | set(now)):
        if key.split('.')[0].split('[')[0] in VERIFY_IGNORED or key.endswith('.requested'):
            continue
        a, b = recorded.get(key, '<absent>'), now.get(key, '<absent>')
        if a != b:
            (notes if key in VERIFY_NOTE_ONLY else differences).append(f'{key}: manifest says {a!r}, re-derived {b!r}')
    for name, repo in (('party', party_repo), ('games', games_repo)):      # did the name used at assembly move?
        requested = manifest[name].get('requested')
        if isinstance(requested, str) and not SHA_RX.match(requested):
            try:
                if resolve_commit(repo, requested) != manifest[name]['sha']:
                    notes.append(f'{name}: {requested!r} now resolves to a different commit than the one recorded')
            except ReleaseError:
                notes.append(f'{name}: {requested!r} no longer resolves in this repository')
    directory = Path(bundle_dir) if bundle_dir else Path(manifest_path).resolve().parent
    for name in ('party', 'games'):
        rec = (manifest.get('bundles') or {}).get(name)
        if not rec:
            continue
        path = directory / rec['file']
        if not path.is_file():
            notes.append(f'{name}: bundle {rec["file"]} is not in {directory}; not checked')
            continue
        actual = sha256_file(path)
        if actual != rec['sha256']:
            differences.append(f'bundles.{name}.sha256: manifest says {rec["sha256"]!r}, {path.name} is {actual!r}')
        elif not bundle_holds(path, manifest[name]['sha']):
            differences.append(f'bundles.{name}: {path.name} does not hold exactly {manifest[name]["sha"]}')
    return differences, notes


def cmd_verify(args):
    differences, notes = verify_manifest(args.manifest, args.party_repo, args.games_repo, args.bundle_dir)
    for n in notes:
        print(f'note: {n}')
    if differences:
        print(f'NOT REPRODUCED: {len(differences)} difference(s) from {args.manifest}')
        for d in differences:
            print(f'  - {d}')
        return 1
    print(f'REPRODUCED: every field of {args.manifest} was re-derived from the two repositories and agrees')
    return 0


# ---- prereq -----------------------------------------------------------------------------------
def read_json_file(path, what):
    """(document, problem)"""
    path = Path(path)
    if not path.is_file():
        return None, f'{what} {path} is missing'
    try:
        return json.loads(path.read_text(encoding='utf-8')), None
    except (OSError, ValueError) as e:
        return None, f'{what} {path} cannot be read as JSON ({type(e).__name__})'


def deployed_sha(preflight, name):
    sha = dig(preflight, 'revisions', name, 'deployed_sha')
    return sha if isinstance(sha, str) and SHA_RX.match(sha) else None


def owner_commands(party, games, flags, script):
    base = f'sudo bash {script} --party {party} --games {games}'
    cmds = {
        'read_only_first': f'sudo bash {script} --status',
        'dry_run': base + ' --dry-run',
        'real_run': base,
        'real_run_with_cert_name_gate': base + ' --require-cert-names',
        'rollback_rehearsal': f'sudo bash {script} --rollback --dry-run',
        'rollback': f'sudo bash {script} --rollback',
        'notes': [
            'The owner runs these on the Pi, in this order. This tool printed them and ran none of them.',
            f'Take ops/deploy.sh from the target commit: git -C /home/cody/avrana-party show {party}:ops/deploy.sh '
            '(docs/runbooks/deploy.md, "First run").',
            'Add --require-cert-names to the real run only when this night uses native games on the game origin '
            '(field-test gate step 0.3 yes) and the certificate-name checks passed; otherwise run without it, and the '
            'deploy only warns (docs/runbooks/field-test-gate.md step 2).',
            'Read the dry run first: it needs sudo to check certificate names, never refuses on them, and changes nothing.',
            'After the real run: --status must show the new last known good; a run that dies or exits 2, 3 or 4 follows '
            'docs/runbooks/deploy.md "Which command next".',
        ],
    }
    if any(f.get('id') == 'party_not_on_origin_main' for f in flags if isinstance(f, dict)):
        cmds['notes'].append('The Party commit is NOT on origin/main: ops/deploy.sh will refuse it unless the owner adds '
                             '--allow-branch (a supervised test). This tool does not add it for you.')
    return cmds


def prereq(manifest_path, preflight_path, status_path=None, max_age_min=60, now=None, script=DEFAULT_DEPLOY_SCRIPT):
    now = now or utcnow()
    blocked, warnings, notes = [], [], []
    result = {'schema': PREREQ_SCHEMA, 'checked_at': iso(now), 'result': 'BLOCKED', 'manifest': None, 'preflight': None,
              'rollback_target': None, 'blocked_by': blocked, 'warnings': warnings, 'notes': notes,
              'physically_unverified': [], 'owner_commands': None}
    # 1. the candidate manifest
    manifest = None
    try:
        manifest = load_manifest(manifest_path)
    except ReleaseError as e:
        blocked.append(f'candidate manifest: {e}')
    if manifest is not None:
        flags = manifest.get('flags') if isinstance(manifest.get('flags'), list) else []
        result['manifest'] = {'path': str(manifest_path), 'party': manifest['party']['sha'], 'games': manifest['games']['sha'],
                              'verdict': manifest.get('verdict')}
        if manifest.get('verdict') not in VERDICTS:
            blocked.append(f'candidate manifest: verdict {manifest.get("verdict")!r} is not one of {", ".join(VERDICTS)}')
        for f in flags:
            if not isinstance(f, dict):
                continue
            line = f'{f.get("id")}: {f.get("reason")}'
            if f.get('severity') == 'FAIL':
                blocked.append(f'candidate is flagged FAIL - {line}')
            else:
                warnings.append(f'candidate flag WARN - {line}')
        if manifest.get('verdict') == 'CANDIDATE_FLAGGED' and not flags:
            blocked.append('candidate manifest: verdict CANDIDATE_FLAGGED but no flags are listed; assemble it again')
    # 2. the preflight document
    preflight, problem = read_json_file(preflight_path, 'preflight')
    if problem:
        blocked.append(f'preflight: {problem}; take one on the Pi with python3 -m avrana.ops.preflight --json')
    elif not isinstance(preflight, dict) or preflight.get('schema') != PREFLIGHT_SCHEMA:
        blocked.append(f'preflight: not a {PREFLIGHT_SCHEMA} document (schema {dig(preflight, "schema")!r})')
        preflight = None
    if preflight is not None:
        age = None
        try:
            age = (now - parse_time(preflight.get('generated_at'))).total_seconds() / 60.0
        except (ValueError, TypeError):
            blocked.append('preflight: generated_at is missing or not an ISO-8601 time, so it cannot be shown to be fresh')
        if age is not None:
            if age > max_age_min:
                blocked.append(f'preflight: stale, taken {age:.0f} minutes ago (limit {max_age_min:g}); take a new one')
            elif age < -5:
                blocked.append(f'preflight: generated_at is {-age:.0f} minutes in the future (clock skew); take a new one')
        verdict, overall = preflight.get('verdict'), preflight.get('overall')
        raw_checks = preflight.get('checks')
        checks = [c for c in raw_checks if isinstance(c, dict)] if isinstance(raw_checks, list) else []
        bad = [c for c in checks if c.get('blocking') and c.get('status') != 'PASS']
        failed = [c for c in checks if c.get('status') == 'FAIL' and c not in bad]
        result['preflight'] = {'path': str(preflight_path), 'generated_at': preflight.get('generated_at'),
                               'age_minutes': None if age is None else round(age, 1), 'verdict': verdict, 'overall': overall,
                               'blocking_checks': [c.get('id') for c in bad]}
        if verdict == 'READY':
            if overall not in ('PASS', 'WARN'):
                blocked.append(f'preflight: verdict READY but overall is {overall!r}; the document disagrees with itself')
            for c in bad:
                blocked.append(f'preflight: READY but blocking check {c.get("id")} is {c.get("status")} - {c.get("reason")}')
            for c in failed:
                blocked.append(f'preflight: READY but check {c.get("id")} is FAIL - {c.get("reason")}')
        elif verdict == 'NOT_READY':
            blocked.append('preflight: verdict NOT_READY')
            for c in bad or failed:
                blocked.append(f'preflight: blocking check {c.get("id")} ({c.get("category")}) is {c.get("status")} - {c.get("reason")}')
        elif verdict == 'UNKNOWN':
            blocked.append('preflight: verdict UNKNOWN - the appliance could not be assessed')
            for c in bad:
                blocked.append(f'preflight: check {c.get("id")} is {c.get("status")} - {c.get("reason")}')
        else:
            blocked.append(f'preflight: verdict {verdict!r} is not READY')
        warnings += [f'preflight check {c.get("id")}: {c.get("reason")}' for c in checks if c.get('status') == 'WARN']
        unverified = preflight.get('physically_unverified')
        if isinstance(unverified, list):
            result['physically_unverified'] = [str(u) for u in unverified]
        # 3. the candidate against what is deployed
        if manifest is not None:
            dp, dg = deployed_sha(preflight, 'party'), deployed_sha(preflight, 'games')
            if dp and dg and dp == manifest['party']['sha'] and dg == manifest['games']['sha']:
                notes.append('nothing to install: the candidate pair equals the deployed pair')
            elif dp is None or dg is None:
                notes.append('the deployed pair is not stated by the preflight (revisions.*.deployed_sha); '
                             'what the deploy changes is unknown until its dry run')
            else:
                changed = [n for n, d, c in (('Party', dp, manifest['party']['sha']), ('Games', dg, manifest['games']['sha']))
                           if d != c]
                notes.append(f'deployed pair: Party {dp[:12]}, Games {dg[:12]}; the deploy changes: {", ".join(changed)}')
    # 4. the rollback target
    if status_path is None:
        warnings.append('no --status given: the rollback target (last known good) was not checked; '
                        'save /party/api/status and pass it, or read it with ops/deploy.sh --status')
    else:
        status, status_problem = read_json_file(status_path, 'status')
        if status_problem is None and (not isinstance(status, dict) or status.get('schema') != STATUS_SCHEMA):
            status_problem = f'status {status_path} is not a {STATUS_SCHEMA} document'
        if status_problem:
            warnings.append(f'{status_problem}: the rollback target was not checked')
        else:
            lkg = status.get('last_known_good')
            if not (isinstance(lkg, dict) and SHA_RX.match(str(lkg.get('party_sha'))) and SHA_RX.match(str(lkg.get('games_sha')))):
                warnings.append('no last known good is recorded: ops/deploy.sh --rollback has no target, so a failed smoke '
                                'on this deploy can only be undone by deploying explicit SHAs (docs/runbooks/deploy.md)')
            else:
                result['rollback_target'] = {k: lkg.get(k) for k in ('party_sha', 'games_sha', 'smoke_at', 'recorded_at')}
                if preflight is not None:
                    dp, dg = deployed_sha(preflight, 'party'), deployed_sha(preflight, 'games')
                    if dp and dg and (dp, dg) != (lkg['party_sha'], lkg['games_sha']):
                        warnings.append('the last known good differs from the deployed pair, so --rollback returns to '
                                        f'Party {lkg["party_sha"][:12]} / Games {lkg["games_sha"][:12]}, not to what runs now')
    if not blocked:
        result['result'] = 'CLEARED_FOR_OWNER'
        result['owner_commands'] = owner_commands(manifest['party']['sha'], manifest['games']['sha'],
                                                  manifest.get('flags') or [], script)
    return result


def render_prereq(r):
    lines = [f'{r["result"]}  (checked {r["checked_at"]})']
    if r['manifest']:
        m = r['manifest']
        lines.append(f'candidate: Party {m["party"]}, Games {m["games"]} ({m["verdict"]})')
    if r['preflight']:
        p = r['preflight']
        lines.append(f'preflight: {p["verdict"]}/{p["overall"]}, taken {p["generated_at"]} ({p["age_minutes"]} min before this check)')
    for title, key in (('BLOCKED BY', 'blocked_by'), ('WARNINGS', 'warnings'), ('NOTES', 'notes')):
        if r[key]:
            lines.append(f'{title}:')
            lines += [f'  - {x}' for x in r[key]]
    if r['physically_unverified']:
        lines.append('NOT PROVEN (the preflight lists these as physically unverified; a clear result does not cover them):')
        lines += [f'  - {x}' for x in r['physically_unverified']]
    if r['rollback_target']:
        t = r['rollback_target']
        lines.append(f'rollback target (last known good): Party {t["party_sha"]}, Games {t["games_sha"]}')
    c = r['owner_commands']
    if c:
        lines += ['', 'OWNER COMMANDS (printed by this tool, never run by it):',
                  f'  {c["read_only_first"]}', f'  {c["dry_run"]}', f'  {c["real_run"]}',
                  '  # instead of the line above, when native games use the game origin (certificate-name gate):',
                  f'  {c["real_run_with_cert_name_gate"]}',
                  '  # rehearse, then if needed perform, the way back:',
                  f'  {c["rollback_rehearsal"]}', f'  {c["rollback"]}', '']
        lines += [f'  note: {x}' for x in c['notes']]
    else:
        lines += ['', 'No owner commands are printed: the prerequisites are not met.']
    return '\n'.join(lines)


def cmd_prereq(args):
    r = prereq(args.manifest, args.preflight, args.status, args.max_age_min,
               parse_time(args.now) if args.now else None, args.deploy_script)
    if args.json_out:
        write_text(args.json_out, json.dumps(r, indent=2) + '\n')
    print(json.dumps(r, indent=2) if args.json else render_prereq(r))
    return 0 if r['result'] == 'CLEARED_FOR_OWNER' else 1


# ---- rehearse-rollback ------------------------------------------------------------------------
NOT_REPRODUCED = (
    'root: nothing runs as root; file ownership, sudo -u and the root-only certificate directory are not exercised',
    'systemd: no unit is stopped, started or checked; the real run only restarts them after the commit point',
    'nginx: the site file is compared, never installed; nginx -t and the reload are not run',
    "the real /opt/avrana-party and /opt/avrana-party-games releases, the web release flip and the Pi's own checkouts",
    'the post-deploy smoke, the manifest write and the last-known-good record of a REAL deployment '
    '(the record here is seeded with avrana.ops.manifest to stand for the earlier deployment)',
    'a real rollback: only --rollback --dry-run is run; the "deployed" state is a throwaway checkout moved by this tool',
    'phones, Wi-Fi, the game origin certificate and anything physical',
)
ROOT_ONLY_RX = re.compile(r'run as root|needs root|root is needed|Permission denied|sudo: ', re.I)
PLAN_RX = re.compile(r'plan: party ([0-9a-f]{40}) -> ([0-9a-f]{40}) \(changed=(\d)\), '
                     r'games ([0-9a-f]{40}) -> ([0-9a-f]{40}) \(changed=(\d)\)')


def find_bash():
    found = shutil.which('bash')
    if sys.platform == 'win32':
        if found and 'system32' in found.lower().replace('/', '\\'):         # the WSL launcher is not Git Bash
            found = None
        if not found:
            git_exe = shutil.which('git')
            if git_exe:
                candidate = Path(git_exe).resolve().parent.parent / 'bin' / 'bash.exe'
                if candidate.is_file():
                    found = str(candidate)
    return found


def repo_state(repo):
    return {'head': git_text(repo, 'rev-parse', 'HEAD'),
            'branch': git(repo, 'symbolic-ref', '--quiet', '--short', 'HEAD', check=False).stdout.decode().strip() or None,
            'status': git(repo, 'status', '--porcelain=v1', '--untracked-files=all').stdout.decode('utf-8', 'replace')}


def tree_snapshot(root, skip=('origin', 'logs')):
    """Every file under root (not git internals, the scratch origins or this tool's own logs) with its digest."""
    snap = {}
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        dirnames[:] = sorted(d for d in dirnames if d != '.git' and not (d in skip and rel_dir == Path('.')))
        for d in dirnames:
            snap[(rel_dir / d).as_posix() + '/'] = 'dir'
        for f in sorted(filenames):
            snap[(rel_dir / f).as_posix()] = sha256_file(Path(dirpath) / f)
    return snap


def snapshot_diff(before, after):
    return (sorted(set(after) - set(before)), sorted(set(before) - set(after)),
            sorted(k for k in set(before) & set(after) if before[k] != after[k]))


def excerpt(text, limit=18):
    lines = [l.rstrip() for l in text.strip().splitlines() if l.strip()]
    if len(lines) > limit:
        lines = lines[:limit // 2] + [f'... ({len(lines) - limit} lines omitted)'] + lines[-(limit // 2):]
    return '\n'.join(lines)


def make_origin(origin, source_repo, main_sha, extra):
    """A scratch bare 'origin' holding just the history the rehearsal needs. It borrows the local source
    repository's objects (alternates, read-only) to point its refs, repacks them into itself and lets go of the
    borrowed store, so the scratch root stands alone and the source is only ever read."""
    common = git_text(source_repo, 'rev-parse', '--path-format=absolute', '--git-common-dir')
    git(origin.parent, 'init', '--bare', '-q', '-b', 'main', str(origin))
    write_text(origin / 'objects/info/alternates', posix(Path(common) / 'objects') + '\n')
    for branch, sha in (('main', main_sha), *extra.items()):
        git(origin, 'update-ref', f'refs/heads/{branch}', sha)
    git(origin, '-c', 'pack.threads=1', 'repack', '-a', '-d', '-q')
    (origin / 'objects/info/alternates').unlink()
    git(origin, 'rev-list', '--objects', '--quiet', 'refs/heads/main')          # complete without the borrowed store


def run_deploy(bash, script, args, env, cwd, timeout=300):
    p = subprocess.run([bash, posix(script), *args], capture_output=True, text=True, env=env, cwd=cwd, timeout=timeout,
                       errors='replace')
    return p.returncode, p.stdout, p.stderr


def rehearse(manifest_path, party_repo, games_repo, before_party=None, before_games=None, keep=False):
    manifest = load_manifest(manifest_path)
    party_repo, games_repo = check_repo(party_repo, 'Party'), check_repo(games_repo, 'Games')
    cand_p, cand_g = manifest['party']['sha'], manifest['games']['sha']
    for name, repo, sha in (('Party', party_repo, cand_p), ('Games', games_repo, cand_g)):
        if not has_commit(repo, sha):
            raise ReleaseError(f'the candidate {name} commit {sha} is not in {repo}; fetch it first')
    if bool(before_party) != bool(before_games):
        raise ReleaseError('give both --before-party and --before-games, or neither')
    if before_party:
        bp, bg = resolve_commit(party_repo, before_party), resolve_commit(games_repo, before_games)
        before_source = 'explicit (--before-party/--before-games)'
    else:
        try:
            bp, bg = git_text(party_repo, 'rev-parse', cand_p + '^1'), git_text(games_repo, 'rev-parse', cand_g + '^1')
        except ReleaseError:
            raise ReleaseError('a candidate commit has no parent; give --before-party and --before-games')
        before_source = 'the first parents of the candidate commits'
    if (bp, bg) == (cand_p, cand_g):
        raise ReleaseError('the before pair equals the candidate pair; there is nothing to roll back from')
    bash = find_bash()
    if bash is None:
        raise ReleaseError('bash is not available: ops/deploy.sh cannot be rehearsed here')
    steps = []

    def step(sid, title, status, detail='', out=''):
        steps.append({'id': sid, 'title': title, 'status': status, 'detail': detail, 'excerpt': excerpt(out) if out else ''})
        return status

    def done():
        return finish_rehearsal(manifest, bp, bg, before_source, steps, real_before, party_repo, games_repo)

    real_before = {'party': repo_state(party_repo), 'games': repo_state(games_repo)}
    scratch = Path(tempfile.mkdtemp(prefix='avrana-rc-rehearsal-')).resolve()
    try:
        for d in ('logs', 'tmp', 'state', 'shim', 'cand', 'origin'):
            (scratch / d).mkdir()
        logs = scratch / 'logs'
        # -- 1. throwaway clones with a local origin
        try:
            for name, repo, cand, before in (('party', party_repo, cand_p, bp), ('games', games_repo, cand_g, bg)):
                make_origin(scratch / 'origin' / f'{name}.git', repo, origin_main(repo) or cand,
                            {'rc-candidate': cand, 'rc-before': before})
                git(scratch, 'clone', '-q', '--no-hardlinks', str(scratch / 'origin' / f'{name}.git'), str(scratch / name))
                git(scratch / name, 'checkout', '-q', '--detach', before)
            cand_tree = export_tree(party_repo, cand_p, scratch / 'cand' / 'party')
            script = cand_tree / 'ops/deploy.sh'
            if not script.is_file():
                raise ReleaseError('the candidate Party commit has no ops/deploy.sh')
        except ReleaseError as e:
            step('setup', 'throwaway clones of both repositories with a local origin', 'FAIL', str(e))
            return done()
        step('setup', 'throwaway clones of both repositories with a local origin (no network); the candidate ops/deploy.sh exported',
             'PASS', 'checkouts detached at the before pair; the origins are local bare repositories inside the scratch root')
        # the python3 that deploy.sh calls (the Microsoft Store stub on Windows would fail): a shim in front of PATH
        shim = scratch / 'shim'
        write_text(shim / 'python3', f'#!/bin/sh\nexec "{posix(sys.executable)}" "$@"\n')
        os.chmod(shim / 'python3', 0o755)
        env = {k: v for k, v in os.environ.items() if not k.startswith('AVRANA_')}
        env.update({
            'PATH': str(shim) + os.pathsep + env.get('PATH', ''),
            'AVRANA_PARTY_CHECKOUT': posix(scratch / 'party'), 'AVRANA_GAMES_CHECKOUT': posix(scratch / 'games'),
            'AVRANA_WEB_ROOT': posix(scratch / 'web'), 'AVRANA_PARTY_RELEASES': posix(scratch / 'opt/avrana-party'),
            'AVRANA_GAMES_RELEASES': posix(scratch / 'opt/avrana-party-games'),
            'AVRANA_DEPLOYMENT_MANIFEST': posix(scratch / 'state/deployment.json'),
            'AVRANA_LAST_KNOWN_GOOD': posix(scratch / 'state/last-known-good.json'),
            'AVRANA_BACKUP_ROOT': posix(scratch / 'backups'), 'AVRANA_DEPLOY_LOCK': posix(scratch / 'state/deploy.lock'),
            'AVRANA_NGINX_SITE': posix(scratch / 'nginx/sites-available/avrana-party'),
            'AVRANA_NGINX_ENABLED': posix(scratch / 'nginx/sites-enabled/avrana-party'),
            'AVRANA_PARTY_CORE_URL': 'http://127.0.0.1:1', 'AVRANA_CHECKOUT_USER': getpass.getuser(),
            'AVRANA_DEPLOY_DETACH': '0', 'AVRANA_DEPLOY_PYTHON': posix(sys.executable),
            'TMPDIR': posix(scratch / 'tmp'), 'TMP': str(scratch / 'tmp'), 'TEMP': str(scratch / 'tmp'),
            'PYTHONDONTWRITEBYTECODE': '1', 'GIT_TERMINAL_PROMPT': '0',
        })
        # -- 2. seed a last-known-good record for the before pair with the appliance's own manifest tool
        tooling = cand_tree if (cand_tree / 'avrana/ops/manifest.py').is_file() else REPO
        state = posix(scratch / 'state')
        seed = [['write', '--out', f'{state}/deployment.json', '--party', posix(scratch / 'party'), '--games',
                 posix(scratch / 'games'), '--web-root', posix(scratch / 'web')],
                ['smoke', f'{state}/deployment.json', 'passed'],
                ['last-known-good', 'record', f'{state}/deployment.json', f'{state}/last-known-good.json']]
        seed_out = ''
        for sub in seed:
            p = subprocess.run([sys.executable, '-m', 'avrana.ops.manifest', *sub], cwd=tooling, capture_output=True,
                               text=True, errors='replace', env=env, timeout=120)
            seed_out += f'$ python -m avrana.ops.manifest {sub[0]}\n{p.stdout}{p.stderr}'
            if p.returncode != 0:
                step('seed-last-known-good', 'seed a last-known-good record for the before pair', 'FAIL',
                     f'avrana.ops.manifest {sub[0]} exited {p.returncode}', seed_out)
                return done()
        lkg = json.loads((scratch / 'state/last-known-good.json').read_text(encoding='utf-8'))
        ok = (lkg.get('party_sha'), lkg.get('games_sha')) == (bp, bg)
        step('seed-last-known-good', 'seed a last-known-good record for the before pair', 'PASS' if ok else 'FAIL',
             f'the record names Party {str(lkg.get("party_sha"))[:12]} / Games {str(lkg.get("games_sha"))[:12]}'
             + ('' if tooling == cand_tree else " (avrana.ops.manifest is this tool's own: the candidate predates it)"), seed_out)
        if not ok:
            return done()

        def run_step(sid, title, args, checks_of, deploy_args_text):
            before_snap = tree_snapshot(scratch)
            rc, out, err = run_deploy(bash, script, args, env, cand_tree)
            text = out + (('\n[stderr]\n' + err) if err.strip() else '')
            write_text(logs / f'{sid}.log', text)
            if rc != 0 and ROOT_ONLY_RX.search(text):
                return step(sid, title, 'NOT_REPRODUCED',
                            f'exit {rc}: the script needs something only root (or the Pi) has here; not faked', text)
            problems = [] if rc == 0 else [f'exit status {rc}, expected 0']
            problems += [msg for good, msg in checks_of(out) if not good]
            added, gone, changed = snapshot_diff(before_snap, tree_snapshot(scratch))
            if added or gone or changed:
                problems.append(f'the scratch root changed: added {added[:5]} removed {gone[:5]} changed {changed[:5]}')
            return step(sid, title, 'FAIL' if problems else 'PASS',
                        '; '.join(problems) or deploy_args_text + ' exit 0, the plan is as expected, the scratch root is unchanged', text)

        # -- 3. the candidate's own ops/deploy.sh --dry-run
        off_main = manifest['party'].get('on_origin_main') is False
        args = ['--party', cand_p, '--games', cand_g, '--dry-run'] + (['--allow-branch'] if off_main else [])

        def forward_checks(out):
            m = PLAN_RX.search(out)
            return [(bool(m) and (m.group(1), m.group(2), m.group(4), m.group(5)) == (bp, cand_p, bg, cand_g),
                     'the plan does not go from the before pair to the candidate pair'),
                    ('dry run: nothing changed' in out, 'the output does not end with "dry run: nothing changed"')]
        run_step('deploy-dry-run', 'ops/deploy.sh ' + ' '.join(a if len(a) != 40 else a[:12] for a in args), args,
                 forward_checks, 'the candidate pair is planned from the before pair;')
        # -- 4. stand in for "the candidate was deployed": the scratch checkouts move to it (scratch only)
        for name, sha in (('party', cand_p), ('games', cand_g)):
            git(scratch / name, 'checkout', '-q', '--detach', sha)
        step('simulate-deployed', 'move the scratch checkouts to the candidate pair (stands for a finished deployment)', 'PASS',
             'scratch only; the last-known-good record still names the before pair')

        # -- 5. the same script's --rollback --dry-run
        def rollback_checks(out):
            t, m = re.search(r'target is party ([0-9a-f]{40}), games ([0-9a-f]{40})', out), PLAN_RX.search(out)
            return [(bool(t) and (t.group(1), t.group(2)) == (bp, bg), 'the rollback did not resolve to the before pair'),
                    (bool(m) and (m.group(1), m.group(2), m.group(4), m.group(5)) == (cand_p, bp, cand_g, bg),
                     'the rollback plan does not go from the candidate pair to the before pair'),
                    ('dry run: nothing changed' in out, 'the output does not end with "dry run: nothing changed"')]
        run_step('rollback-dry-run', 'ops/deploy.sh --rollback --dry-run', ['--rollback', '--dry-run'], rollback_checks,
                 'the rollback target is the before pair;')
        made = [d for d in ('backups', 'web', 'opt', 'nginx') if (scratch / d).exists()]
        leftover_tmp = [p.name for p in (scratch / 'tmp').iterdir()]
        step('no-side-effects', 'no backup directory, web release, /opt release, nginx file, journal or temporary file was left',
             'FAIL' if made or leftover_tmp else 'PASS',
             ('left behind: ' + ', '.join(made + leftover_tmp)) if made or leftover_tmp
             else 'only the seeded state/ files exist, and the temporary directory is empty')
        return done()
    finally:
        if keep:
            print(f'scratch root kept: {scratch}', file=sys.stderr)
        else:
            rmtree(scratch)


def finish_rehearsal(manifest, bp, bg, before_source, steps, real_before, party_repo, games_repo):
    after = {'party': repo_state(party_repo), 'games': repo_state(games_repo)}
    moved = [n for n in ('party', 'games') if after[n] != real_before[n]]
    steps.append({'id': 'real-repositories-unchanged',
                  'title': 'both real repositories have the same HEAD, branch and status as before the rehearsal',
                  'status': 'FAIL' if moved else 'PASS',
                  'detail': ('changed: ' + ', '.join(moved)) if moved else
                  f'Party {after["party"]["head"][:12]} on {after["party"]["branch"]}, '
                  f'Games {after["games"]["head"][:12]} on {after["games"]["branch"]}',
                  'excerpt': ''})
    failed = [s for s in steps if s['status'] == 'FAIL']
    partial = [s for s in steps if s['status'] == 'NOT_REPRODUCED']
    return {'schema': REHEARSAL_SCHEMA, 'generated_at': iso(utcnow()),
            'candidate': {'party': manifest['party']['sha'], 'games': manifest['games']['sha']},
            'before': {'party': bp, 'games': bg, 'source': before_source},
            'steps': steps, 'cannot_reproduce': list(NOT_REPRODUCED),
            'verdict': 'REHEARSAL_FAILED' if failed else ('REHEARSAL_PARTIAL' if partial else 'REHEARSAL_PASSED')}


def render_rehearsal(r):
    lines = [f'{r["verdict"]}  (generated {r["generated_at"]})',
             f'candidate: Party {r["candidate"]["party"]}, Games {r["candidate"]["games"]}',
             f'before:    Party {r["before"]["party"]}, Games {r["before"]["games"]} ({r["before"]["source"]})', '']
    for s in r['steps']:
        lines.append(f'[{s["status"]}] {s["id"]}: {s["title"]}')
        if s['detail']:
            lines.append(f'    {s["detail"]}')
        if s['excerpt']:
            lines += ['    | ' + l for l in s['excerpt'].splitlines()]
    lines += ['', 'NOT REPRODUCED by this rehearsal (needs the Pi, root or a person):']
    lines += [f'  - {x}' for x in r['cannot_reproduce']]
    return '\n'.join(lines)


def cmd_rehearse(args):
    report = rehearse(args.manifest, args.party_repo, args.games_repo, args.before_party, args.before_games, args.keep)
    if args.json_out:
        write_text(args.json_out, json.dumps(report, indent=2) + '\n')
    print(render_rehearsal(report))
    return 1 if report['verdict'] == 'REHEARSAL_FAILED' else 0


# ---- command line -----------------------------------------------------------------------------
def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='command', required=True)
    a = sub.add_parser('assemble', help='record and check one Party commit and one Games commit')
    a.add_argument('--party-repo', required=True)
    a.add_argument('--games-repo', required=True)
    a.add_argument('--party', required=True, metavar='REV', help='a revision already in the Party repository')
    a.add_argument('--games', required=True, metavar='REV', help='a revision already in the Games repository')
    a.add_argument('--out', required=True, metavar='DIR')
    a.add_argument('--bundle', action='store_true', help='also write party.bundle and games.bundle')
    a.add_argument('--force', action='store_true', help='replace an existing release-candidate.json')
    v = sub.add_parser('verify', help='re-derive a manifest and report every difference')
    v.add_argument('manifest')
    v.add_argument('--party-repo', required=True)
    v.add_argument('--games-repo', required=True)
    v.add_argument('--bundle-dir', default=None, help='where the bundles are (default: beside the manifest)')
    r = sub.add_parser('prereq', help='check the prerequisites of an intended installation (does not install)')
    r.add_argument('manifest')
    r.add_argument('--preflight', required=True, metavar='PREFLIGHT.json')
    r.add_argument('--status', default=None, metavar='STATUS.json', help='saved /party/api/status (avrana.status/v0)')
    r.add_argument('--max-age-min', type=float, default=60.0)
    r.add_argument('--deploy-script', default=DEFAULT_DEPLOY_SCRIPT, help='path of ops/deploy.sh on the Pi, for the printed commands')
    r.add_argument('--json', action='store_true', help='print the JSON document instead of the text report')
    r.add_argument('--json-out', default=None, metavar='FILE', help='also write the JSON document')
    r.add_argument('--now', default=None, metavar='ISO8601',
                   help='evaluate as of this UTC time instead of the clock (tests, reproducible demonstrations)')
    b = sub.add_parser('rehearse-rollback', help='ops/deploy.sh --dry-run and --rollback --dry-run in a disposable root')
    b.add_argument('manifest')
    b.add_argument('--party-repo', required=True)
    b.add_argument('--games-repo', required=True)
    b.add_argument('--before-party', default=None)
    b.add_argument('--before-games', default=None)
    b.add_argument('--json-out', default=None, metavar='FILE')
    b.add_argument('--keep', action='store_true', help='keep the scratch root (for debugging)')
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return {'assemble': cmd_assemble, 'verify': cmd_verify, 'prereq': cmd_prereq,
                'rehearse-rollback': cmd_rehearse}[args.command](args)
    except ReleaseError as e:
        if args.command == 'prereq':          # a prerequisite that cannot be read is never a clearance
            print(f'BLOCKED\n  - {e}')
            return 1
        print(f'release_candidate: {e}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
