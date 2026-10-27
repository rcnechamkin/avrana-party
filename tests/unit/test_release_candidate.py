"""tools/release_candidate.py (AVR-699): assemble, verify, prereq and rehearse-rollback, against throwaway git
repositories. Nothing here touches the network, the appliance or the real repositories."""
import contextlib
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

from avrana import REPO_ROOT

TOOL = REPO_ROOT / 'tools/release_candidate.py'
sys.path.insert(0, str(REPO_ROOT / 'tools'))
import release_candidate as rc                      # noqa: E402

BASH = rc.find_bash()
UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 10, 21, 12, 0, 0, tzinfo=UTC)
LAYER = b'// layer mount\nconst LAYER_PROTOCOL = "l1";\n'
LAYER_SHA = hashlib.sha256(LAYER).hexdigest()
OTHER_SHA = hashlib.sha256(b'a different layer mount').hexdigest()
STUB_CHECKER = '''import json, pathlib, sys
games = pathlib.Path(sys.argv[sys.argv.index("--games") + 1])
d = json.loads((games / "provider/avrana-contract.json").read_text())
if d.get("stub_exit"):
    print("CONTRACT DRIFT: the stub says the pair disagrees", file=sys.stderr)
    sys.exit(d["stub_exit"])
print("Party <-> Games contract: compatible")
'''
GIT_ENV = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@x', GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@x',
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)


class Repo:
    """A throwaway checkout whose origin is a local bare repository (so origin/main exists)."""

    def __init__(self, root, name, with_origin=True):
        self.path = Path(root) / name
        self.clock = 0
        if with_origin:
            origin = Path(root) / f'{name}-origin.git'
            self.run('init', '-q', '--bare', '-b', 'main', str(origin), cwd=root)
            self.run('clone', '-q', str(origin), str(self.path), cwd=root)
            self.run('checkout', '-q', '-b', 'main')
        else:
            self.path.mkdir()
            self.run('init', '-q', '-b', 'main')

    def run(self, *args, cwd=None):
        env = dict(GIT_ENV)
        self.clock += 1
        env['GIT_COMMITTER_DATE'] = env['GIT_AUTHOR_DATE'] = rc.iso(datetime.datetime(2026, 1, 1, tzinfo=UTC)
                                                                    + datetime.timedelta(seconds=self.clock))
        p = subprocess.run(['git', *args], cwd=cwd or self.path, check=True, capture_output=True, env=env)
        return p.stdout.decode().strip()

    def commit(self, files, message='c'):
        for rel, data in files.items():
            target = self.path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data if isinstance(data, bytes) else data.encode())
        self.run('add', '-A')
        self.run('commit', '-q', '-m', message)
        return self.sha()

    def sha(self, rev='HEAD'):
        return self.run('rev-parse', rev)

    def push(self):
        self.run('push', '-q', '-u', 'origin', 'main')


def party_files(layer=LAYER, checker=STUB_CHECKER, extra=None):
    files = {
        'contracts/party-games.v0.json': json.dumps({
            'contract': 'avrana.party-games/v0',
            'session_protocol': {'version': 'avrana.party-session/v0'},
            'result': {'schema': 'avrana.game-result/v1'},
            'bridge': {'protocol': 'avrana.party-bridge/v1'},
            'layer': {'protocol': 'l1', 'reference': 'web/party/bridge/layer-mount.js',
                      'reference_sha256': hashlib.sha256(layer).hexdigest()},
            'launch': {'integration': 'avrana.lan-launch/v1'}}),
        'web/party/bridge/layer-mount.js': layer,
        'tools/contract_check.py': checker,
        'deploy/appliance-inventory.json': json.dumps({'packages': [
            {'name': 'python3', 'why': 'Party Core and the ops tooling (3.11 or newer)'},
            {'name': 'nginx', 'why': 'ports 80 and 443'}, {'name': 'openssl', 'why': 'certificate checks'},
            {'name': 'git', 'why': 'checkouts'}]}),
        'avrana/avrgame/node_pin.py': "VERSION = '22.22.2'\n",
        'package-lock.json': '{"lockfileVersion": 3}\n',
    }
    files.update(extra or {})
    return files


def games_files(pinned=LAYER_SHA, stub_exit=0, requires='avrana.party-games/v0', layer=True):
    decl = {'requires': requires, 'stub_exit': stub_exit,
            'session_protocol': {'version': 'avrana.party-session/v0'}, 'result': {'schema': 'avrana.game-result/v1'},
            'bridge': {'protocol': 'avrana.party-bridge/v1'}, 'launch': {'integration': 'avrana.lan-launch/v1'}}
    if layer:
        decl['layer'] = {'protocol': 'l1', 'vendored_sha256': pinned}
    return {'provider/avrana-contract.json': json.dumps(decl)}


class Base(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='avrana-rc-test-'))
        self.addCleanup(rc.rmtree, self.root)

    def pair(self, party_extra=None, games=None, deploy_script=None, two_commits=False):
        """(party, games) repositories, one or two commits each, all pushed to their origin."""
        party, games_repo = Repo(self.root, 'party'), Repo(self.root, 'games')
        extra = dict(party_extra or {})
        if deploy_script is not None:
            extra['ops/deploy.sh'] = deploy_script
        files, gfiles = party_files(extra=extra), games if games is not None else games_files()
        party.commit(files, 'party one')
        games_repo.commit(gfiles, 'games one')
        if two_commits:
            party.commit({'marker': 'two\n'}, 'party two')
            games_repo.commit({'marker': 'two\n'}, 'games two')
        party.push()
        games_repo.push()
        return party, games_repo

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = rc.main([str(a) for a in args])
        return code, out.getvalue(), err.getvalue()

    def assemble(self, party, games, name='out', *extra, party_rev='HEAD', games_rev='HEAD'):
        out = self.root / name
        code, stdout, stderr = self.cli('assemble', '--party-repo', party.path, '--games-repo', games.path,
                                        '--party', party_rev, '--games', games_rev, '--out', out, *extra)
        manifest = json.loads((out / 'release-candidate.json').read_text(encoding='utf-8')) \
            if (out / 'release-candidate.json').exists() else None
        return code, manifest, out, stdout + stderr


class Assemble(Base):
    def test_a_compatible_pair_is_a_clean_candidate(self):
        party, games = self.pair()
        code, m, out, text = self.assemble(party, games)
        self.assertEqual(code, 0, text)
        self.assertEqual((m['schema'], m['verdict'], m['flags']), ('avrana.release-candidate/v0', 'CANDIDATE_OK', []))
        for name, repo in (('party', party), ('games', games)):
            side = m[name]
            self.assertEqual(side['sha'], repo.sha())
            self.assertRegex(side['sha'], r'^[0-9a-f]{40}$')
            self.assertEqual(side['tree_sha'], repo.sha('HEAD^{tree}'))
            self.assertRegex(side['commit_date'], r'^2026-01-01T00:\d\d:\d\d(Z|\+00:00)$')
            self.assertTrue(side['on_origin_main'])
            self.assertEqual(side['requested'], 'HEAD')
        self.assertEqual(m['contract_check']['status'], 'compatible')
        self.assertEqual(m['contracts']['party_games'], {'party': 'avrana.party-games/v0', 'games': 'avrana.party-games/v0', 'match': True})
        self.assertEqual((m['layer']['status'], m['layer']['games_pinned_sha256'], m['layer']['party_actual_sha256']),
                         ('match', LAYER_SHA, LAYER_SHA))
        self.assertEqual(m['runtime']['python_minimum'], '3.11')
        self.assertEqual(m['runtime']['node_runtime_version'], '22.22.2')
        self.assertEqual(m['runtime']['package_lock_sha256'], hashlib.sha256(b'{"lockfileVersion": 3}\n').hexdigest())
        self.assertIn('nginx', [t['name'] for t in m['runtime']['required_tools']])
        self.assertIn('openssl', [t['name'] for t in m['runtime']['required_tools']])
        self.assertIsNone(m['bundles'])
        self.assertRegex(m['generated_at'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$')
        self.assertEqual(m['tool']['name'], 'tools/release_candidate.py')
        self.assertTrue(m['tool']['party_sha'] is None or re.match(r'^[0-9a-f]{40}$', m['tool']['party_sha']))
        self.assertEqual(m['manifest_sha256'], rc.seal(m))
        summary = (out / 'release-candidate.md').read_text(encoding='utf-8')
        self.assertIn('CANDIDATE_OK', summary)
        self.assertIn(party.sha(), summary)

    def test_a_pair_the_checker_rejects_is_flagged_with_its_message(self):
        party, games = self.pair(games=games_files(stub_exit=1))
        code, m, _, text = self.assemble(party, games)
        self.assertEqual(code, 1, text)
        self.assertEqual(m['verdict'], 'CANDIDATE_FLAGGED')
        self.assertEqual(m['contract_check']['status'], 'incompatible')
        self.assertIn('the stub says the pair disagrees', m['contract_check']['message'])
        self.assertEqual(m['contract_check']['exit_code'], 1)
        flag = next(f for f in m['flags'] if f['id'] == 'contract_incompatible')
        self.assertEqual(flag['severity'], 'FAIL')

    def test_the_real_contract_checker_is_the_one_that_runs(self):
        real = (REPO_ROOT / 'tools/contract_check.py').read_text(encoding='utf-8')
        party, games = self.pair(party_extra={'tools/contract_check.py': real})
        code, m, _, text = self.assemble(party, games)
        self.assertEqual(m['contract_check']['status'], 'incompatible', text)      # the fixture is not a real tree
        self.assertIn('CONTRACT DRIFT', m['contract_check']['message'])
        self.assertEqual(code, 1)

    def test_a_pair_that_predates_the_checker_is_not_checkable_and_only_warned(self):
        party = Repo(self.root, 'party')
        party.commit({k: v for k, v in party_files().items() if k != 'tools/contract_check.py'})
        party.push()
        games = Repo(self.root, 'games')
        games.commit(games_files())
        games.push()
        code, m, _, _ = self.assemble(party, games)
        self.assertEqual(m['contract_check']['status'], 'not_checkable')
        self.assertEqual([(f['id'], f['severity']) for f in m['flags']], [('contract_not_checkable', 'WARN')])
        self.assertEqual(code, 1)

    def test_a_layer_digest_that_games_pins_and_party_does_not_ship_is_a_fail(self):
        party, games = self.pair(games=games_files(pinned=OTHER_SHA))            # the stub checker is content with the pair
        code, m, _, _ = self.assemble(party, games)
        self.assertEqual(code, 1)
        self.assertEqual(m['contract_check']['status'], 'compatible')
        self.assertEqual(m['layer']['status'], 'mismatch')
        self.assertEqual((m['layer']['games_pinned_sha256'], m['layer']['party_actual_sha256']), (OTHER_SHA, LAYER_SHA))
        flag = next(f for f in m['flags'] if f['id'] == 'layer_digest_mismatch')
        self.assertEqual(flag['severity'], 'FAIL')
        self.assertEqual(m['verdict'], 'CANDIDATE_FLAGGED')

    def test_a_games_repository_that_vendors_no_layer_is_not_flagged_for_it(self):
        party, games = self.pair(games=games_files(layer=False))
        code, m, _, _ = self.assemble(party, games)
        self.assertEqual((code, m['layer']['status'], m['flags']), (0, 'not_vendored', []))

    def test_party_declaring_another_layer_digest_than_it_ships_is_drift(self):
        stale = json.loads(party_files()['contracts/party-games.v0.json'])
        stale['layer']['reference_sha256'] = OTHER_SHA
        party, games = self.pair(party_extra={'contracts/party-games.v0.json': json.dumps(stale)})
        _, m, _, _ = self.assemble(party, games)
        self.assertIn('layer_declaration_drift', [f['id'] for f in m['flags']])

    def test_contract_versions_that_differ_are_a_fail(self):
        party, games = self.pair(games=games_files(requires='avrana.party-games/v1'))
        _, m, _, _ = self.assemble(party, games)
        self.assertEqual(m['contracts']['party_games']['match'], False)
        self.assertEqual(next(f for f in m['flags'] if f['id'] == 'contract_version_mismatch')['severity'], 'FAIL')

    def test_a_commit_off_origin_main_is_flagged_not_refused(self):
        party, games = self.pair()
        party.run('checkout', '-q', '-b', 'topic')
        topic = party.commit({'topic': 'x\n'}, 'topic')
        code, m, _, text = self.assemble(party, games, party_rev=topic)
        self.assertEqual(code, 1, text)
        self.assertFalse(m['party']['on_origin_main'])
        flag = next(f for f in m['flags'] if f['id'] == 'party_not_on_origin_main')
        self.assertEqual(flag['severity'], 'WARN')
        self.assertIn('--allow-branch', flag['reason'])
        self.assertEqual([f for f in m['flags'] if f['severity'] == 'FAIL'], [])

    def test_a_repository_with_no_origin_main_is_flagged_as_unknown(self):
        party = Repo(self.root, 'party')
        party.commit(party_files())
        party.push()
        games = Repo(self.root, 'games', with_origin=False)
        games.commit(games_files())
        _, m, _, _ = self.assemble(party, games)
        self.assertIsNone(m['games']['on_origin_main'])
        self.assertIn('games_origin_main_unknown', [f['id'] for f in m['flags']])

    def test_the_archive_digest_is_the_digest_of_git_archive_and_is_deterministic(self):
        party, games = self.pair()
        _, first, _, _ = self.assemble(party, games, 'one')
        (party.path / 'web/party/bridge/layer-mount.js').write_bytes(b'edited in the working tree only\n')
        _, second, _, _ = self.assemble(party, games, 'two')
        self.assertEqual(first['party']['archive_sha256'], second['party']['archive_sha256'])
        self.assertEqual(first['games']['archive_sha256'], second['games']['archive_sha256'])
        archive = subprocess.run(['git', '-c', 'core.autocrlf=false', '-C', str(party.path), 'archive', '--format=tar', party.sha()],
                                 check=True, capture_output=True).stdout
        self.assertEqual(first['party']['archive_sha256'], hashlib.sha256(archive).hexdigest())
        self.assertEqual(first['party']['archive_bytes'], len(archive))
        party.run('checkout', '-q', '--', '.')
        other = party.commit({'marker': 'changes the tree\n'})
        _, third, _, _ = self.assemble(party, games, 'three', party_rev=other)
        self.assertNotEqual(third['party']['archive_sha256'], first['party']['archive_sha256'])

    def test_the_digest_does_not_depend_on_the_users_autocrlf_setting(self):
        party, games = self.pair()
        plain = rc.archive_digest(party.path, party.sha())
        config = self.root / 'gitconfig'
        config.write_text('[core]\n\tautocrlf = true\n', encoding='utf-8')
        with unittest.mock.patch.dict(os.environ, {'GIT_CONFIG_GLOBAL': str(config), 'GIT_CONFIG_SYSTEM': os.devnull}):
            self.assertEqual(rc.archive_digest(party.path, party.sha()), plain)
        self.assertIn('core.autocrlf=false', self.assemble(party, games, 'o')[1]['digest_method'])

    def test_the_digest_does_not_depend_on_tar_umask_or_an_inherited_git_dir(self):
        party, games = self.pair()
        plain = rc.archive_digest(party.path, party.sha())
        config = self.root / 'gitconfig'
        config.write_text('[tar]\n\tumask = 0077\n', encoding='utf-8')
        with unittest.mock.patch.dict(os.environ, {'GIT_CONFIG_GLOBAL': str(config), 'GIT_CONFIG_SYSTEM': os.devnull}):
            self.assertEqual(rc.archive_digest(party.path, party.sha()), plain)
        # GIT_DIR from a hook or `rebase --exec` would otherwise point every `git -C party` at the Games repository
        with unittest.mock.patch.dict(os.environ, {'GIT_DIR': str(games.path / '.git'), 'GIT_WORK_TREE': str(games.path)}):
            self.assertEqual(rc.archive_digest(party.path, party.sha()), plain)
            self.assertEqual(rc.resolve_commit(party.path, 'HEAD'), party.sha())

    def test_a_failed_bundle_leaves_no_half_written_files(self):
        party, games = self.pair()
        real = rc.make_bundle

        def games_fails(repo, sha, dest):
            if Path(dest).name == 'games.bundle':
                raise rc.ReleaseError('simulated failure')
            return real(repo, sha, dest)
        with unittest.mock.patch.object(rc, 'make_bundle', games_fails):
            code, manifest, out, text = self.assemble(party, games, 'out', '--bundle')
        self.assertEqual(code, 2, text)
        self.assertIsNone(manifest)
        self.assertEqual(sorted(p.name for p in out.iterdir()) if out.exists() else [], [])

    def test_the_trees_come_from_the_commits_not_from_the_working_tree(self):
        party, games = self.pair(games=games_files(stub_exit=1))
        (games.path / 'provider/avrana-contract.json').write_text(json.dumps(
            json.loads(games_files()['provider/avrana-contract.json'])), encoding='utf-8')           # edited, uncommitted
        _, m, _, _ = self.assemble(party, games)
        self.assertEqual(m['contract_check']['status'], 'incompatible')

    def test_bundles_hold_exactly_each_sha_and_are_in_the_manifest(self):
        party, games = self.pair(two_commits=True)
        refs_before = (party.run('for-each-ref'), games.run('for-each-ref'))
        code, m, out, text = self.assemble(party, games, 'out', '--bundle', party_rev='HEAD~1', games_rev='HEAD')
        self.assertEqual(code, 0, text)
        self.assertEqual((party.run('for-each-ref'), games.run('for-each-ref')), refs_before)      # sources untouched
        for name, repo, sha in (('party', party, party.sha('HEAD~1')), ('games', games, games.sha())):
            b = m['bundles'][name]
            path = out / b['file']
            self.assertEqual(b['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual((b['head'], b['ref'], b['verified_heads']), (sha, 'refs/heads/release-candidate', True))
            heads = subprocess.run(['git', 'bundle', 'list-heads', str(path)], capture_output=True, check=True).stdout.decode()
            self.assertEqual(sorted(heads.split()), sorted([sha, sha, 'HEAD', 'refs/heads/release-candidate']))
            clone = self.root / f'clone-{name}'
            subprocess.run(['git', 'clone', '-q', str(path), str(clone)], check=True, capture_output=True, env=GIT_ENV)
            self.assertEqual(subprocess.run(['git', '-C', str(clone), 'rev-parse', 'HEAD'], capture_output=True).stdout.decode().strip(), sha)
        self.assertEqual(rc.verify_manifest(out / 'release-candidate.json', party.path, games.path), ([], []))

    def test_unresolvable_revisions_and_existing_output_are_errors_that_write_nothing(self):
        party, games = self.pair()
        code, manifest, out, text = self.assemble(party, games, 'bad', party_rev='deadbeef')
        self.assertEqual(code, 2)
        self.assertIsNone(manifest)
        self.assertIn('does not name a commit', text)
        self.assertFalse(out.exists())
        code, *_ = self.assemble(party, games, 'twice')
        self.assertEqual(code, 0)
        code, _, _, text = self.assemble(party, games, 'twice')
        self.assertEqual(code, 2)
        self.assertIn('exists', text)
        code, *_ = self.assemble(party, games, 'twice', '--force')
        self.assertEqual(code, 0)
        with self.assertRaises(rc.ReleaseError):
            rc.resolve_commit(party.path, '--output=x')

    def test_it_never_reaches_for_the_network(self):
        source = TOOL.read_text(encoding='utf-8')
        self.assertNotRegex(source, re.compile(r'^\s*(import|from)\s+(urllib|socket|http|requests|ssl|ftplib|smtplib)\b', re.M))
        self.assertEqual(re.findall(r"'(fetch|pull|push|ls-remote)'", source), [])


class Verify(Base):
    def test_an_unchanged_candidate_is_reproduced(self):
        party, games = self.pair()
        _, _, out, _ = self.assemble(party, games)
        code, text, _ = self.cli('verify', out / 'release-candidate.json', '--party-repo', party.path, '--games-repo', games.path)
        self.assertEqual(code, 0, text)
        self.assertIn('REPRODUCED', text)

    def test_a_changed_sha_is_a_difference(self):
        party, games = self.pair(two_commits=True)
        _, m, out, _ = self.assemble(party, games)
        path = out / 'release-candidate.json'
        m['party']['sha'] = party.sha('HEAD~1')                    # the manifest now names another real commit
        path.write_text(json.dumps(m), encoding='utf-8')
        code, text, _ = self.cli('verify', path, '--party-repo', party.path, '--games-repo', games.path)
        self.assertEqual(code, 1, text)
        self.assertIn('NOT REPRODUCED', text)
        self.assertIn('party.tree_sha', text)
        self.assertIn('party.archive_sha256', text)
        self.assertNotIn('party.sha:', text)                       # re-derived from that SHA, so it agrees with itself

    def test_a_sha_the_repository_lacks_is_an_error(self):
        party, games = self.pair()
        _, m, out, _ = self.assemble(party, games)
        m['games']['sha'] = 'f' * 40
        (out / 'release-candidate.json').write_text(json.dumps(m), encoding='utf-8')
        code, _, err = self.cli('verify', out / 'release-candidate.json', '--party-repo', party.path, '--games-repo', games.path)
        self.assertEqual(code, 2)
        self.assertIn('does not name a commit', err)

    def test_every_recorded_fact_is_checked(self):
        party, games = self.pair()
        _, m, out, _ = self.assemble(party, games)
        for edit, expected in (
                (lambda d: d['party'].__setitem__('archive_sha256', '0' * 64), 'party.archive_sha256'),
                (lambda d: d['games'].__setitem__('commit_date', 'then'), 'games.commit_date'),
                (lambda d: d['layer'].__setitem__('games_pinned_sha256', OTHER_SHA), 'layer.games_pinned_sha256'),
                (lambda d: d['runtime'].__setitem__('package_lock_sha256', '1' * 64), 'runtime.package_lock_sha256'),
                (lambda d: d['contract_check'].__setitem__('status', 'incompatible'), 'contract_check.status'),
                (lambda d: d.__setitem__('flags', [{'id': 'x', 'severity': 'WARN', 'reason': 'y'}]), 'flags[0].id')):
            doc = json.loads(json.dumps(m))
            edit(doc)
            path = out / 'edited.json'
            path.write_text(json.dumps(doc), encoding='utf-8')
            code, text, _ = self.cli('verify', path, '--party-repo', party.path, '--games-repo', games.path)
            self.assertEqual(code, 1, expected)
            self.assertIn(expected, text)

    def test_generated_at_and_the_tool_are_not_differences(self):
        party, games = self.pair()
        _, m, out, _ = self.assemble(party, games)
        m['generated_at'] = '2020-01-01T00:00:00Z'
        m['tool']['party_sha'] = 'a' * 40
        (out / 'release-candidate.json').write_text(json.dumps(m), encoding='utf-8')
        code, text, _ = self.cli('verify', out / 'release-candidate.json', '--party-repo', party.path, '--games-repo', games.path)
        self.assertEqual(code, 1)                                  # an edit, however harmless, breaks the seal
        self.assertIn('manifest_sha256', text)
        m['manifest_sha256'] = rc.seal(m)
        (out / 'release-candidate.json').write_text(json.dumps(m), encoding='utf-8')
        code, text, _ = self.cli('verify', out / 'release-candidate.json', '--party-repo', party.path, '--games-repo', games.path)
        self.assertEqual(code, 0, text)                            # ... but those fields are not compared

    def test_origin_main_moving_on_is_a_note_not_a_difference(self):
        party, games = self.pair()
        _, _, out, _ = self.assemble(party, games)
        party.commit({'later': 'x\n'}, 'later')
        party.push()
        code, text, _ = self.cli('verify', out / 'release-candidate.json', '--party-repo', party.path, '--games-repo', games.path)
        self.assertEqual(code, 0, text)
        self.assertIn('note: party.origin_main_sha', text)

    def test_a_moved_name_is_a_note(self):
        party, games = self.pair(two_commits=True)
        _, _, out, _ = self.assemble(party, games, party_rev='HEAD')
        party.run('reset', '-q', '--hard', 'HEAD~1')
        code, text, _ = self.cli('verify', out / 'release-candidate.json', '--party-repo', party.path, '--games-repo', games.path)
        self.assertEqual(code, 0, text)
        self.assertIn("'HEAD' now resolves to a different commit", text)

    def test_a_tampered_or_missing_bundle_is_a_difference(self):
        party, games = self.pair()
        _, _, out, _ = self.assemble(party, games, 'out', '--bundle')
        manifest = out / 'release-candidate.json'
        self.assertEqual(self.cli('verify', manifest, '--party-repo', party.path, '--games-repo', games.path)[0], 0)
        (out / 'games.bundle').write_bytes((out / 'games.bundle').read_bytes() + b'x')
        code, text, _ = self.cli('verify', manifest, '--party-repo', party.path, '--games-repo', games.path)
        self.assertEqual(code, 1)
        self.assertIn('bundles.games.sha256', text)
        (out / 'games.bundle').unlink()
        (out / 'party.bundle').unlink()
        code, text, _ = self.cli('verify', manifest, '--party-repo', party.path, '--games-repo', games.path)
        self.assertEqual(code, 1, text)
        self.assertIn('bundles.party', text)
        self.assertIn('--no-bundles', text)
        code, text, _ = self.cli('verify', manifest, '--party-repo', party.path, '--games-repo', games.path, '--no-bundles')
        self.assertEqual(code, 0, text)
        self.assertIn('not checked (--no-bundles)', text)

    def test_a_file_that_is_not_a_manifest_is_an_error(self):
        party, games = self.pair()
        bad = self.root / 'bad.json'
        bad.write_text('{"schema": "something/else"}', encoding='utf-8')
        code, _, err = self.cli('verify', bad, '--party-repo', party.path, '--games-repo', games.path)
        self.assertEqual(code, 2)
        self.assertIn('avrana.release-candidate/v0', err)


PARTY = 'a' * 40
GAMES = 'b' * 40
OLD_PARTY = 'c' * 40
OLD_GAMES = 'd' * 40


def fake_manifest(flags=None, verdict=None, seal=True, **changes):
    """A complete, sealed manifest whose flags and verdict follow from its facts (as assemble writes it). A change
    is given as section__field=value; flags and verdict, when given, override what the facts say."""
    doc = {'schema': rc.SCHEMA, 'generated_at': rc.iso(NOW),
           'party': {'sha': PARTY, 'short': PARTY[:12], 'on_origin_main': True, 'origin_main_sha': PARTY},
           'games': {'sha': GAMES, 'short': GAMES[:12], 'on_origin_main': True, 'origin_main_sha': GAMES},
           'contract_check': {'status': 'compatible', 'exit_code': 0, 'message': 'compatible'},
           'contracts': {'party_games': {'party': 'avrana.party-games/v0', 'games': 'avrana.party-games/v0', 'match': True}},
           'layer': {'status': 'match', 'party_file': rc.LAYER_MOUNT, 'party_actual_sha256': LAYER_SHA,
                     'party_declared_sha256': LAYER_SHA, 'games_pinned_sha256': LAYER_SHA},
           'runtime': {'package_lock_sha256': '0' * 64, 'python_minimum': '3.11', 'node_runtime_version': '22.22.2'},
           'sbom': {'status': 'ok', 'message': ''}, 'declaration_notes': [], 'bundles': None}
    for path, value in changes.items():
        *keys, last = path.split('__')
        target = doc
        for key in keys:
            target = target[key]
        target[last] = value
    doc['flags'] = rc.make_flags(doc) if flags is None else list(flags)
    doc['verdict'] = verdict or ('CANDIDATE_FLAGGED' if doc['flags'] else 'CANDIDATE_OK')
    if seal:
        doc['manifest_sha256'] = rc.seal(doc)
    return doc


def fake_preflight(age_min=5, verdict='READY', overall='PASS', checks=None, deployed=(OLD_PARTY, OLD_GAMES), **extra):
    doc = {'schema': 'avrana.preflight/v0', 'generated_at': rc.iso(NOW - datetime.timedelta(minutes=age_min)),
           'mode': 'appliance', 'waived': [], 'verdict': verdict, 'overall': overall,
           'revisions': {'party': {'deployed_sha': deployed[0]}, 'games': {'deployed_sha': deployed[1]}},
           'checks': checks if checks is not None else [
               {'id': 'disk', 'category': 'storage', 'status': 'PASS', 'blocking': True, 'reason': 'ok'}],
           'physically_unverified': ['iPhone Safari join', 'Wi-Fi under load']}
    doc.update(extra)
    return doc


def fake_status(lkg=(OLD_PARTY, OLD_GAMES), deployed=(OLD_PARTY, OLD_GAMES), age_min=1):
    return {'schema': 'avrana.status/v0', 'generated_at': rc.iso(NOW - datetime.timedelta(minutes=age_min)),
            'party': {'deployed_sha': deployed[0]}, 'games': {'deployed_sha': deployed[1]},
            'last_known_good': None if lkg is None else {'party_sha': lkg[0], 'games_sha': lkg[1],
                                                         'smoke_at': '2026-10-06T10:00:00Z', 'recorded_at': '2026-10-06T10:00:01Z'}}


class Prereq(Base):
    def run_prereq(self, manifest=None, preflight='default', status='default', **kw):
        mpath = self.root / 'm.json'
        mpath.write_text(json.dumps(manifest if manifest is not None else fake_manifest()), encoding='utf-8')
        ppath = self.root / 'p.json'
        if preflight == 'default':
            preflight = fake_preflight()
        if isinstance(preflight, (dict, list)):
            ppath.write_text(json.dumps(preflight), encoding='utf-8')
        elif preflight is not None:
            ppath.write_text(preflight, encoding='utf-8')
        spath = None
        if status == 'default':
            status = fake_status()
        if status is not None:
            spath = self.root / 's.json'
            spath.write_text(json.dumps(status) if not isinstance(status, str) else status, encoding='utf-8')
        return rc.prereq(mpath, ppath, spath, now=NOW, **kw)

    def assertBlocked(self, r, *needles):
        self.assertEqual(r['result'], 'BLOCKED', r)
        self.assertIsNone(r['owner_commands'])
        text = rc.render_prereq(r)
        self.assertNotIn('CLEARED', text)
        self.assertNotIn('sudo bash', text)
        for needle in needles:
            self.assertIn(needle, ' | '.join(r['blocked_by']))
        self.assertTrue(r['blocked_by'])

    def test_a_ready_fresh_preflight_and_a_clean_candidate_are_cleared_with_the_owner_commands(self):
        r = self.run_prereq()
        self.assertEqual(r['result'], 'CLEARED_FOR_OWNER', r)
        self.assertEqual(r['blocked_by'], [])
        c = r['owner_commands']
        self.assertEqual(c['dry_run'], f'sudo bash /home/cody/avrana-party/ops/deploy.sh --party {PARTY} --games {GAMES} --dry-run')
        self.assertEqual(c['real_run'], f'sudo bash /home/cody/avrana-party/ops/deploy.sh --party {PARTY} --games {GAMES}')
        self.assertTrue(c['real_run_with_cert_name_gate'].endswith('--require-cert-names'))
        self.assertTrue(c['rollback_rehearsal'].endswith('--rollback --dry-run'))
        text = rc.render_prereq(r)
        self.assertLess(text.index('--dry-run'), text.index(c['real_run'] + '\n'))
        self.assertIn('never run by it', text)
        self.assertIn('--require-cert-names', text)
        self.assertEqual(r['rollback_target']['party_sha'], OLD_PARTY)
        self.assertIn('iPhone Safari join', r['physically_unverified'])
        self.assertIn('NOT PROVEN', text)
        self.assertIn('deployed pair', ' '.join(r['notes']))

    def test_a_missing_preflight_blocks(self):
        self.assertBlocked(self.run_prereq(preflight=None), 'preflight', 'missing')

    def test_an_unparseable_preflight_blocks(self):
        self.assertBlocked(self.run_prereq(preflight='{not json'), 'cannot be read as JSON')
        self.assertBlocked(self.run_prereq(preflight=''), 'cannot be read as JSON')

    def test_a_preflight_of_another_schema_blocks(self):
        self.assertBlocked(self.run_prereq(preflight=fake_preflight(schema='avrana.preflight/v1')), 'avrana.preflight/v0')
        self.assertBlocked(self.run_prereq(preflight=['READY']), 'avrana.preflight/v0')
        doc = fake_preflight()
        del doc['schema']
        self.assertBlocked(self.run_prereq(preflight=doc), 'avrana.preflight/v0')

    def test_a_stale_or_undated_preflight_blocks(self):
        self.assertBlocked(self.run_prereq(preflight=fake_preflight(age_min=61)), 'stale')
        self.assertEqual(self.run_prereq(preflight=fake_preflight(age_min=59))['result'], 'CLEARED_FOR_OWNER')
        self.assertEqual(self.run_prereq(preflight=fake_preflight(age_min=61), max_age_min=120)['result'], 'CLEARED_FOR_OWNER')
        self.assertBlocked(self.run_prereq(preflight=fake_preflight(age_min=-30)), 'in the future')
        self.assertBlocked(self.run_prereq(preflight=fake_preflight(generated_at='yesterday')), 'generated_at')
        naive = rc.iso(NOW - datetime.timedelta(minutes=5)).rstrip('Z')          # no zone: not silently UTC
        self.assertBlocked(self.run_prereq(preflight=fake_preflight(generated_at=naive)), 'with a zone')
        doc = fake_preflight()
        del doc['generated_at']
        self.assertBlocked(self.run_prereq(preflight=doc), 'generated_at')

    def test_not_ready_blocks_and_lists_the_blocking_checks(self):
        checks = [{'id': 'disk', 'category': 'storage', 'status': 'PASS', 'blocking': True, 'reason': 'ok'},
                  {'id': 'cert_names', 'category': 'tls', 'status': 'FAIL', 'blocking': True, 'reason': 'games.avrana.net not covered'},
                  {'id': 'clock', 'category': 'time', 'status': 'WARN', 'blocking': False, 'reason': 'drift'}]
        r = self.run_prereq(preflight=fake_preflight(verdict='NOT_READY', overall='FAIL', checks=checks))
        self.assertBlocked(r, 'NOT_READY', 'cert_names', 'games.avrana.net not covered')
        self.assertNotIn('disk', ' '.join(r['blocked_by']))
        self.assertEqual(r['preflight']['blocking_checks'], ['cert_names'])

    def test_unknown_blocks(self):
        checks = [{'id': 'nginx', 'category': 'web', 'status': 'UNKNOWN', 'blocking': True, 'reason': 'not run as root'}]
        r = self.run_prereq(preflight=fake_preflight(verdict='UNKNOWN', overall='UNKNOWN', checks=checks))
        self.assertBlocked(r, 'UNKNOWN', 'nginx')
        self.assertBlocked(self.run_prereq(preflight=fake_preflight(verdict='MAYBE')), 'not READY')
        self.assertBlocked(self.run_prereq(preflight=fake_preflight(verdict=None)), 'not READY')

    def test_a_ready_document_that_contradicts_itself_does_not_clear(self):
        failing = [{'id': 'smoke', 'category': 'runtime', 'status': 'FAIL', 'blocking': True, 'reason': 'down'}]
        self.assertBlocked(self.run_prereq(preflight=fake_preflight(checks=failing)), 'smoke')
        self.assertBlocked(self.run_prereq(preflight=fake_preflight(overall='FAIL')), 'disagrees with itself')
        unknown = [{'id': 'smoke', 'category': 'runtime', 'status': 'UNKNOWN', 'blocking': True, 'reason': '?'}]
        self.assertBlocked(self.run_prereq(preflight=fake_preflight(checks=unknown)), 'smoke')
        warn = [{'id': 'clock', 'category': 'time', 'status': 'WARN', 'blocking': False, 'reason': 'drift'}]
        r = self.run_prereq(preflight=fake_preflight(overall='WARN', checks=warn))
        self.assertEqual(r['result'], 'CLEARED_FOR_OWNER')
        self.assertTrue(any('clock' in w for w in r['warnings']))

    def test_only_a_real_appliance_preflight_with_checks_clears(self):
        self.assertBlocked(self.run_prereq(preflight=fake_preflight(mode='local')), 'mode')
        doc = fake_preflight()
        del doc['mode']
        self.assertBlocked(self.run_prereq(preflight=doc), 'mode')
        self.assertBlocked(self.run_prereq(preflight=fake_preflight(checks=[])), 'no checks')

    def test_a_waived_unknown_and_a_blocking_warn_clear_but_say_so(self):
        clock = {'id': 'pi.clock', 'category': 'pi', 'status': 'UNKNOWN', 'blocking': True, 'reason': 'not synced'}
        r = self.run_prereq(preflight=fake_preflight(overall='WARN', checks=[clock], waived=['pi.clock']))
        self.assertEqual(r['result'], 'CLEARED_FOR_OWNER', r['blocked_by'])
        self.assertTrue(any('WAIVED' in w and 'pi.clock' in w for w in r['warnings']))
        self.assertBlocked(self.run_prereq(preflight=fake_preflight(overall='WARN', checks=[clock])), 'pi.clock')
        failing = dict(clock, status='FAIL')
        self.assertBlocked(self.run_prereq(preflight=fake_preflight(checks=[failing], waived=['pi.clock'])), 'pi.clock')
        appliance = dict(clock, id='serving.appliance')
        self.assertBlocked(self.run_prereq(preflight=fake_preflight(checks=[appliance], waived=['serving.appliance'])),
                           'can never be waived')
        warn = {'id': 'tls.horizon', 'category': 'tls', 'status': 'WARN', 'blocking': True, 'reason': '5 days left'}
        r = self.run_prereq(preflight=fake_preflight(overall='WARN', checks=[warn]))
        self.assertEqual(r['result'], 'CLEARED_FOR_OWNER', r['blocked_by'])
        odd = dict(warn, status='MAYBE')
        self.assertBlocked(self.run_prereq(preflight=fake_preflight(checks=[odd])), 'tls.horizon')

    def test_a_flagged_candidate_with_a_fail_flag_blocks_and_one_with_only_warnings_does_not(self):
        mismatch = {'layer__status': 'mismatch', 'layer__games_pinned_sha256': OTHER_SHA}
        self.assertBlocked(self.run_prereq(manifest=fake_manifest(**mismatch)), 'layer_digest_mismatch')
        r = self.run_prereq(manifest=fake_manifest(party__on_origin_main=False))
        self.assertEqual(r['result'], 'CLEARED_FOR_OWNER', r['blocked_by'])
        self.assertTrue(any('party_not_on_origin_main' in w for w in r['warnings']))
        self.assertTrue(any('--allow-branch' in n for n in r['owner_commands']['notes']))
        self.assertBlocked(self.run_prereq(manifest=fake_manifest(flags=[], verdict='CANDIDATE_OK', **mismatch)),
                           'layer_digest_mismatch', 'its own facts')
        self.assertBlocked(self.run_prereq(manifest=fake_manifest(flags=[], verdict='CANDIDATE_FLAGGED')), 'no flags')
        self.assertBlocked(self.run_prereq(manifest=fake_manifest(verdict='LGTM')), 'verdict')

    def test_a_manifest_edited_after_assembly_does_not_clear(self):
        incompatible = {'contract_check': {'status': 'incompatible', 'exit_code': 1, 'message': 'CONTRACT DRIFT'}}
        m = fake_manifest(**incompatible)
        m['verdict'], m['flags'] = 'CANDIDATE_OK', []                       # the review's repro: hand-cleared
        self.assertBlocked(self.run_prereq(manifest=m), 'seal', 'did not show the pair compatible', 'its own facts')
        m['manifest_sha256'] = rc.seal(m)                                     # even re-sealed: the facts still say no
        self.assertBlocked(self.run_prereq(manifest=m), 'did not show the pair compatible', 'contract_incompatible')
        unsealed = fake_manifest(seal=False)
        self.assertBlocked(self.run_prereq(manifest=unsealed), 'seal')
        incomplete = fake_manifest()
        del incomplete['layer']
        incomplete['manifest_sha256'] = rc.seal(incomplete)
        self.assertBlocked(self.run_prereq(manifest=incomplete), 'incomplete')

    def test_an_unchecked_pair_needs_an_explicit_acceptance_and_a_rejected_one_never_clears(self):
        unchecked = fake_manifest(contract_check={'status': 'not_checkable', 'exit_code': None, 'message': 'predates it'})
        self.assertBlocked(self.run_prereq(manifest=unchecked), 'did not show the pair compatible')
        r = self.run_prereq(manifest=unchecked, accept_unchecked=True)
        self.assertEqual(r['result'], 'CLEARED_FOR_OWNER', r['blocked_by'])
        self.assertTrue(any('--accept-unchecked' in w for w in r['warnings']))
        rejected = fake_manifest(contract_check={'status': 'incompatible', 'exit_code': 1, 'message': 'drift'})
        self.assertBlocked(self.run_prereq(manifest=rejected, accept_unchecked=True), 'did not show the pair compatible')

    def test_with_both_repositories_the_manifest_is_re_derived(self):
        party, games = self.pair()
        code, m, out, text = self.assemble(party, games)
        self.assertEqual(code, 0, text)
        args = dict(party_repo=party.path, games_repo=games.path)
        r = self.run_prereq(manifest=m, **args)
        self.assertEqual(r['result'], 'CLEARED_FOR_OWNER', r['blocked_by'])
        self.assertTrue(r['manifest']['reverified'])
        m['layer']['party_actual_sha256'] = '9' * 64                        # consistent, re-sealed, and false
        m['manifest_sha256'] = rc.seal(m)
        self.assertBlocked(self.run_prereq(manifest=m, **args), 'does not reproduce', 'layer.party_actual_sha256')
        r = self.run_prereq(manifest=fake_manifest())
        self.assertFalse(r['manifest']['reverified'])
        self.assertTrue(any('not re-derived' in w for w in r['warnings']))

    def test_a_manifest_that_cannot_be_used_blocks(self):
        self.assertBlocked(self.run_prereq(manifest={'schema': 'other'}), 'avrana.release-candidate/v0')
        short = fake_manifest()
        short['party']['sha'] = 'abc'
        self.assertBlocked(self.run_prereq(manifest=short), 'party.sha')
        r = rc.prereq(self.root / 'absent.json', self.root / 'absent-too.json', None, now=NOW)
        self.assertBlocked(r, 'candidate manifest', 'preflight')

    def test_the_deployed_pair_is_noted(self):
        r = self.run_prereq(preflight=fake_preflight(deployed=(PARTY, GAMES)), status=None)
        self.assertEqual(r['result'], 'CLEARED_FOR_OWNER')
        self.assertIn('nothing to install', ' '.join(r['notes']))
        r = self.run_prereq(preflight=fake_preflight(deployed=(PARTY, OLD_GAMES)), status=None)
        self.assertNotIn('nothing to install', ' '.join(r['notes']))
        self.assertIn('changes: Games', ' '.join(r['notes']))
        r = self.run_prereq(preflight=fake_preflight(deployed=(None, None)), status=None)
        self.assertIn('not stated', ' '.join(r['notes']))

    def test_no_last_known_good_warns_that_rollback_has_no_target(self):
        for status in (fake_status(lkg=None), None):
            r = self.run_prereq(status=status)
            self.assertEqual(r['result'], 'CLEARED_FOR_OWNER', r['blocked_by'])
            self.assertIsNone(r['rollback_target'])
            self.assertTrue(any('--rollback has no target' in w for w in r['warnings']), (status, r['warnings']))

    def test_without_status_the_rollback_target_comes_from_the_preflight(self):
        doc = fake_preflight()
        doc['revisions']['last_known_good'] = {'party_sha': OLD_PARTY, 'games_sha': OLD_GAMES}
        r = self.run_prereq(preflight=doc, status=None)
        self.assertEqual(r['result'], 'CLEARED_FOR_OWNER', r['blocked_by'])
        self.assertEqual((r['rollback_target']['party_sha'], r['rollback_target']['source']), (OLD_PARTY, 'the preflight'))

    def test_a_status_that_is_unusable_stale_or_of_another_deployment_blocks(self):
        for status in ('{broken', {'schema': 'other'}):
            self.assertBlocked(self.run_prereq(status=status), '--status')
        self.assertBlocked(self.run_prereq(status=fake_status(age_min=600)), 'status: stale')
        self.assertBlocked(self.run_prereq(status=fake_status(age_min=-30)), 'status: generated_at')
        self.assertBlocked(self.run_prereq(status=fake_status(deployed=('e' * 40, OLD_GAMES))), 'disagree', 'party')
        r = self.run_prereq(status=fake_status())
        self.assertEqual((r['result'], r['rollback_target']['source']), ('CLEARED_FOR_OWNER', '--status'))

    def test_a_last_known_good_that_is_not_the_deployed_pair_is_noted(self):
        r = self.run_prereq(status=fake_status(lkg=('e' * 40, 'f' * 40)))
        self.assertTrue(any('last known good differs' in w for w in r['warnings']))

    def test_the_command_line_exit_codes(self):
        def run(preflight_doc):
            (self.root / 'm.json').write_text(json.dumps(fake_manifest()), encoding='utf-8')
            if preflight_doc is not None:
                (self.root / 'p.json').write_text(json.dumps(preflight_doc), encoding='utf-8')
            return subprocess.run([sys.executable, '-I', str(TOOL), 'prereq', str(self.root / 'm.json'), '--preflight',
                                   str(self.root / 'p.json'), '--now', rc.iso(NOW), '--json-out', str(self.root / 'o.json')],
                                  capture_output=True, text=True)
        p = run(fake_preflight())
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue(p.stdout.startswith('CLEARED_FOR_OWNER'))
        self.assertEqual(json.loads((self.root / 'o.json').read_text())['result'], 'CLEARED_FOR_OWNER')
        for doc in (fake_preflight(verdict='NOT_READY', overall='FAIL'), fake_preflight(age_min=500)):
            p = run(doc)
            self.assertEqual(p.returncode, 1)
            self.assertTrue(p.stdout.startswith('BLOCKED'))
            self.assertNotIn('CLEARED', p.stdout)
        (self.root / 'p.json').unlink()
        p = run(None)
        self.assertEqual(p.returncode, 1)
        self.assertNotIn('CLEARED', p.stdout)
        self.assertEqual(json.loads((self.root / 'o.json').read_text())['result'], 'BLOCKED')
        self.assertEqual(subprocess.run([sys.executable, '-I', str(TOOL), 'prereq'], capture_output=True).returncode, 2)

    def test_the_staleness_check_cannot_be_switched_off_and_a_clock_override_is_announced(self):
        (self.root / 'm.json').write_text(json.dumps(fake_manifest()), encoding='utf-8')
        (self.root / 'p.json').write_text(json.dumps(fake_preflight(age_min=50)), encoding='utf-8')
        base = ['prereq', self.root / 'm.json', '--preflight', self.root / 'p.json']
        for bad in (['--max-age-min', 'nan'], ['--max-age-min', 'inf'], ['--max-age-min', '-5'], ['--max-age-min', '0'],
                    ['--now', 'yesterday'], ['--now', '2026-10-21T12:00:00']):
            with self.subTest(bad=bad), self.assertRaises(SystemExit) as stop, \
                    contextlib.redirect_stderr(io.StringIO()):
                rc.main([str(a) for a in base + bad])
            self.assertEqual(stop.exception.code, 2)
        code, out, _ = self.cli(*base, '--max-age-min', '10', '--now', rc.iso(NOW))
        self.assertEqual(code, 1)
        self.assertIn('stale', out)
        code, out, _ = self.cli(*base, '--now', rc.iso(NOW))
        self.assertEqual(code, 0, out)
        self.assertIn('CLOCK OVERRIDDEN', out.splitlines()[0])
        with self.assertRaises(rc.ReleaseError):
            rc.prereq(self.root / 'm.json', self.root / 'p.json', max_age_min=float('nan'))

    def test_the_committed_fixtures_behave_as_the_demonstration_says(self):
        fixtures = REPO_ROOT / 'tests/fixtures/release_candidate'
        (self.root / 'm.json').write_text(json.dumps(fake_manifest()), encoding='utf-8')
        now = '2026-10-21T22:45:00Z'
        code, out, _ = self.cli('prereq', self.root / 'm.json', '--preflight', fixtures / 'preflight-ready.json',
                                '--status', fixtures / 'status-last-known-good.json', '--now', now)
        self.assertEqual(code, 0, out)
        self.assertIn('CLEARED_FOR_OWNER', out)
        self.assertIn('c59f1c819de169b55d0bdadde34ae5cec57fc74a', out)
        code, out, _ = self.cli('prereq', self.root / 'm.json', '--preflight', fixtures / 'preflight-not-ready.json', '--now', now)
        self.assertEqual(code, 1, out)
        self.assertTrue(out.startswith('BLOCKED'))
        self.assertIn('no_live_session', out)
        self.assertIn('nginx_config', out)
        code, out, _ = self.cli('prereq', self.root / 'm.json', '--preflight', fixtures / 'preflight-ready.json',
                                '--now', '2026-10-22T01:00:00Z')                  # the same document, three hours later
        self.assertEqual(code, 1, out)
        self.assertIn('stale', out)

    def test_json_output_is_the_same_document(self):
        (self.root / 'm.json').write_text(json.dumps(fake_manifest()), encoding='utf-8')
        (self.root / 'p.json').write_text(json.dumps(fake_preflight(verdict='NOT_READY', overall='FAIL')), encoding='utf-8')
        code, out, _ = self.cli('prereq', self.root / 'm.json', '--preflight', self.root / 'p.json', '--now', rc.iso(NOW), '--json')
        self.assertEqual(code, 1)
        doc = json.loads(out)
        self.assertEqual((doc['schema'], doc['result']), ('avrana.release-prereq/v0', 'BLOCKED'))


DEPLOY_SCRIPT = (REPO_ROOT / 'ops/deploy.sh').read_text(encoding='utf-8')
# A stub must name every path the rehearsal overrides, or the rehearsal refuses to run it (a real-path guard).
HONOURS = ': ' + ' '.join(f'"${{{v}:-}}"' for v in rc.REQUIRED_OVERRIDES) + '\n'


def stub(body):
    return '#!/usr/bin/env bash\n' + HONOURS + body


@unittest.skipUnless(BASH, 'bash is not available: ops/deploy.sh cannot be rehearsed here')
class RehearseRollback(Base):
    def rehearse(self, out, *extra):
        report = self.root / 'rehearsal.json'
        code, text, err = self.cli('rehearse-rollback', out / 'release-candidate.json', '--party-repo', self.party.path,
                                   '--games-repo', self.games.path, '--json-out', report, *extra)
        return code, text + err, json.loads(report.read_text(encoding='utf-8')) if report.exists() else None

    def state(self):
        return {r.path.name: (r.sha(), r.run('status', '--porcelain'), r.run('for-each-ref')) for r in (self.party, self.games)}

    def build(self, script, extra=None):
        self.party, self.games = self.pair(party_extra=extra, deploy_script=script, two_commits=True)
        _, _, out, text = self.assemble(self.party, self.games)
        return out

    def test_the_candidates_real_deploy_script_plans_the_candidate_and_rolls_back_to_the_before_pair(self):
        out = self.build(DEPLOY_SCRIPT)
        before = self.state()
        code, text, report = self.rehearse(out)
        self.assertEqual(code, 0, text)
        self.assertEqual(report['verdict'], 'REHEARSAL_PASSED', text)
        self.assertEqual({s['id']: s['status'] for s in report['steps']},
                         {'setup': 'PASS', 'seed-last-known-good': 'PASS', 'deploy-dry-run': 'PASS', 'simulate-deployed': 'PASS',
                          'rollback-dry-run': 'PASS', 'no-side-effects': 'PASS', 'real-repositories-unchanged': 'PASS'})
        self.assertEqual(report['before']['party'], self.party.sha('HEAD~1'))
        self.assertEqual(report['before']['games'], self.games.sha('HEAD~1'))
        self.assertEqual(report['before']['source'], 'the first parents of the candidate commits')
        dry = next(s for s in report['steps'] if s['id'] == 'deploy-dry-run')
        self.assertIn('dry run: nothing changed', dry['excerpt'])
        self.assertIn(self.party.sha(), dry['excerpt'])
        roll = next(s for s in report['steps'] if s['id'] == 'rollback-dry-run')
        self.assertIn(self.party.sha('HEAD~1'), roll['excerpt'])
        self.assertTrue(any('root' in x for x in report['cannot_reproduce']))
        self.assertTrue(any('systemd' in x for x in report['cannot_reproduce']))
        self.assertIn('NOT REPRODUCED', text)
        self.assertEqual(self.state(), before)                         # the real repositories: HEAD, status, refs

    def test_an_explicit_before_pair_is_used(self):
        out = self.build(DEPLOY_SCRIPT)
        code, text, report = self.rehearse(out, '--before-party', self.party.sha('HEAD~1'), '--before-games', self.games.sha('HEAD~1'))
        self.assertEqual(code, 0, text)
        self.assertEqual(report['before']['source'], 'explicit (--before-party/--before-games)')
        code, _, _ = self.rehearse(out, '--before-party', self.party.sha('HEAD~1'))
        self.assertEqual(code, 2)

    def test_a_deploy_script_that_fails_is_a_failed_rehearsal_not_a_pass(self):
        out = self.build(stub('echo "something is wrong" >&2\nexit 3\n'))
        code, text, report = self.rehearse(out)
        self.assertEqual(code, 1, text)
        self.assertEqual(report['verdict'], 'REHEARSAL_FAILED')
        self.assertEqual({s['id']: s['status'] for s in report['steps']}['deploy-dry-run'], 'FAIL')
        self.assertIn('something is wrong', text)

    def test_a_deploy_script_that_wants_root_is_not_reproduced_rather_than_faked(self):
        out = self.build(stub('echo "deploy: run as root (sudo); services and the web root need it" >&2\nexit 1\n'))
        code, text, report = self.rehearse(out)
        self.assertEqual(code, 3, text)                                # partial is not a pass
        self.assertEqual(report['verdict'], 'REHEARSAL_PARTIAL')
        statuses = {s['id']: s['status'] for s in report['steps']}
        self.assertEqual((statuses['deploy-dry-run'], statuses['rollback-dry-run']), ('NOT_REPRODUCED', 'NOT_REPRODUCED'))

    def test_a_script_that_plans_the_wrong_pair_fails(self):
        wrong = stub('echo "plan: party %s -> %s (changed=1), games %s -> %s (changed=1)"\n'
                     'echo "dry run: nothing changed"\n' % ('1' * 40, '2' * 40, '3' * 40, '4' * 40))
        out = self.build(wrong)
        code, text, report = self.rehearse(out)
        self.assertEqual(code, 1, text)
        step = next(s for s in report['steps'] if s['id'] == 'deploy-dry-run')
        self.assertEqual(step['status'], 'FAIL')
        self.assertIn('does not go from the before pair to the candidate pair', step['detail'])

    def test_a_script_that_changes_the_scratch_root_fails(self):
        meddling = stub('mkdir -p "$AVRANA_BACKUP_ROOT"\necho x > "$AVRANA_BACKUP_ROOT/deploy.journal"\n'
                        'echo "dry run: nothing changed"\n')
        out = self.build(meddling)
        code, text, report = self.rehearse(out)
        self.assertEqual(code, 1, text)
        self.assertIn('the scratch root changed', next(s for s in report['steps'] if s['id'] == 'deploy-dry-run')['detail'])

    def test_it_stays_inside_its_scratch_root(self):
        out = self.build(stub('env | grep "^AVRANA_" | sort\necho "dry run: nothing changed"\n'))
        _, _, report = self.rehearse(out)
        env_lines = next(s for s in report['steps'] if s['id'] == 'deploy-dry-run')['excerpt']
        scratch_names = set(re.findall(r'avrana-rc-rehearsal-\w+', env_lines))
        self.assertEqual(len(scratch_names), 1, env_lines)
        for line in env_lines.splitlines():
            if line.startswith('| '):
                line = line[2:]
            if re.match(r'AVRANA_(PARTY_CHECKOUT|GAMES_CHECKOUT|WEB_ROOT|PARTY_RELEASES|GAMES_RELEASES|DEPLOYMENT_MANIFEST|'
                         r'LAST_KNOWN_GOOD|BACKUP_ROOT|DEPLOY_LOCK|NGINX_SITE|NGINX_ENABLED)=', line):
                self.assertIn(next(iter(scratch_names)), line)

    def test_a_failure_whose_log_only_mentions_root_is_a_failure(self):
        # the review's repro: deploy.sh dies after its "root is needed" certificate note
        out = self.build(stub('echo "[12:00:00Z] nginx site: could not check x against y (unreadable here? root is needed)"\n'
                              'echo "Permission denied" >&2\nexit 1\n'))
        code, text, report = self.rehearse(out)
        self.assertEqual(code, 1, text)
        self.assertEqual(report['verdict'], 'REHEARSAL_FAILED')
        self.assertEqual({s['id']: s['status'] for s in report['steps']}['deploy-dry-run'], 'FAIL')

    def test_the_deploy_lock_that_flock_creates_is_not_a_change(self):
        # deploy.sh opens its lock with `exec 9>` wherever flock exists (the Pi, CI); Git Bash has no flock
        out = self.build(stub('exec 9>"$AVRANA_DEPLOY_LOCK"\nexec bash "$(dirname "$0")/deploy-real.sh" "$@"\n'),
                         extra={'ops/deploy-real.sh': DEPLOY_SCRIPT})
        code, text, report = self.rehearse(out)
        self.assertEqual(code, 0, text)
        self.assertEqual(report['verdict'], 'REHEARSAL_PASSED', text)

    def test_a_script_that_ignores_a_path_override_is_not_run(self):
        out = self.build('#!/usr/bin/env bash\ntouch "$TMPDIR/ran"\necho "dry run: nothing changed"\n')
        code, text, report = self.rehearse(out)
        self.assertEqual(code, 1, text)
        steps = {s['id']: s for s in report['steps']}
        self.assertEqual(steps['setup']['status'], 'FAIL')
        self.assertIn('does not read AVRANA_PARTY_CHECKOUT', steps['setup']['detail'])
        self.assertNotIn('deploy-dry-run', steps)

    def test_an_inherited_git_dir_does_not_redirect_the_rehearsal(self):
        out = self.build(DEPLOY_SCRIPT)
        with unittest.mock.patch.dict(os.environ, {'GIT_DIR': str(self.games.path / '.git'), 'http_proxy': 'http://127.0.0.1:9'}):
            code, text, report = self.rehearse(out)
        self.assertEqual(code, 0, text)
        self.assertEqual(report['verdict'], 'REHEARSAL_PASSED', text)

    def test_a_missing_candidate_commit_is_an_error(self):
        out = self.build(DEPLOY_SCRIPT)
        manifest = json.loads((out / 'release-candidate.json').read_text(encoding='utf-8'))
        manifest['games']['sha'] = 'e' * 40
        (out / 'release-candidate.json').write_text(json.dumps(manifest), encoding='utf-8')
        code, text, _ = self.rehearse(out)
        self.assertEqual(code, 2)
        self.assertIn('not in', text)


if __name__ == '__main__':
    unittest.main()
