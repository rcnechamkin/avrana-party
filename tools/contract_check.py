#!/usr/bin/env python3
"""Prove the Party <-> Games contract declarations against both code bases, and each other.

    python3 tools/contract_check.py                         # Party side only (this checkout)
    python3 tools/contract_check.py --games ../avrana-party-games   # both sides and cross-checks
    python3 tools/contract_check.py --party PARTY --games GAMES     # from anywhere (CI)

Party declares what it implements in contracts/party-games.v0.json. Games declares what it
requires in provider/avrana-contract.json. Each declaration is checked against the constants and
files in its own repository (so a declaration cannot drift from code), then the two are compared
(so the repositories cannot drift from each other). Every failure names the component that
drifted and the file to fix. Stdlib only; no network; nothing is executed from either repository.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


class Drift(Exception):
    pass


def sha256_normalized(path):
    """Line endings normalized, so Windows checkouts agree with Linux CI (matches the games tests)."""
    return hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def constant(path, name):
    """A string constant `NAME = '...'` from a Python file, without importing it."""
    text = path.read_text(encoding='utf-8')
    m = re.search(r'^' + re.escape(name) + r'\s*=\s*([\'"])(.*?)\1', text, re.M)
    if not m:
        raise Drift(f'{path}: cannot find constant {name}')
    return m[2]


def load(path, what):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise Drift(f'{what}: {path} unreadable ({type(e).__name__})')


def expect(actual, declared, component, where):
    if actual != declared:
        raise Drift(f'{component} drifted: {where} declares {declared!r} but code has {actual!r}')


def check_bridge(root, b, key, where):
    """The bridge shim (ADR 0013): the file a game page loads from its own origin, and the vectors
    that pin its messages. `key` is 'reference' in Party and 'vendored' in a games repository."""
    shim = root / b[key]
    if f"PROTOCOL = '{b['protocol']}'" not in shim.read_text(encoding='utf-8'):
        raise Drift(f'bridge protocol drifted: {where} declares {b["protocol"]!r} but {b[key]} does not')
    expect(sha256_normalized(shim), b[key + '_sha256'], 'bridge shim file digest', where)
    expect(sha256_normalized(root / b['vectors']), b['vectors_sha256'], 'bridge vectors digest', where)
    expect(load(root / b['vectors'], 'bridge vectors').get('protocol'), b['protocol'],
           'bridge vectors protocol', b['vectors'])


# ---- Party ------------------------------------------------------------------------------------
def check_party(party):
    decl_path = party / 'contracts/party-games.v0.json'
    d = load(decl_path, 'Party contract declaration')
    where = 'contracts/party-games.v0.json'
    sp = d['session_protocol']
    protocol = party / sp['reference']
    expect(constant(protocol, 'VERSION'), sp['version'], 'session protocol version', where)
    expect(constant(protocol, 'PREFIX'), sp['prefix'], 'session protocol prefix', where)
    expect(sha256_normalized(protocol), sp['reference_sha256'], 'session protocol file digest', where)
    expect(sha256_normalized(party / sp['vectors']), sp['vectors_sha256'], 'session protocol vectors digest', where)
    res = d['result']
    reference = party / res['reference']
    expect(constant(reference, 'SCHEMA'), res['schema'], 'result schema', where)
    expect(sha256_normalized(reference), res['reference_sha256'], 'result reference file digest', where)
    expect(sha256_normalized(party / res['vectors']), res['vectors_sha256'], 'result vectors digest', where)
    expect(load(party / res['vectors'], 'result vectors').get('schema'), res['schema'],
           'result vectors schema', res['vectors'])
    if "payload['result']" not in protocol.read_text(encoding='utf-8'):
        raise Drift(f'result carriage drifted: {where} declares {res["carried_by"]!r} but '
                    f'{sp["reference"]} does not carry a result in `ended`')
    check_bridge(party, d['bridge'], 'reference', where)
    if not (party / 'web/party' / d['bridge']['frame'].removeprefix('/party/')).is_file():
        raise Drift(f'bridge frame drifted: {where} declares {d["bridge"]["frame"]!r} but web/party has no such page')
    sessions = party / 'avrana/party/sessions.py'
    r = d['routes']
    expect(constant(sessions, 'TICKET_ROUTE'), r['party_ticket'], 'party ticket route', where)
    expect(constant(sessions, 'ENDED_ROUTE'), r['party_ended'], 'party ended route', where)
    expect(constant(sessions, 'HOST_ROUTE'), r['party_host'], 'party host route', where)
    expect(constant(sessions, 'LAUNCH_PATH'), r['game_launch'], 'game launch route', where)
    expect(constant(sessions, 'END_PATH'), r['game_end'], 'game end route', where)
    lan = (party / 'avrana/contracts/lan_catalog.py').read_text(encoding='utf-8')
    if d['launch']['integration'] not in lan:
        raise Drift(f'launch integration drifted: {where} declares {d["launch"]["integration"]!r}; '
                    'avrana/contracts/lan_catalog.py does not mention it')
    snapshot = load(party / d['catalog']['snapshot'], 'Party catalog snapshot')
    expect(snapshot.get('source', {}).get('integration'), d['launch']['integration'],
           'catalog snapshot integration', d['catalog']['snapshot'])
    for env in d['environment'].values():
        if env not in (party / 'deploy/arcade/avrana-party-session.conf').read_text(encoding='utf-8') and \
                env not in (party / 'docs/runbooks/party-core-deploy.md').read_text(encoding='utf-8'):
            raise Drift(f'environment drifted: {where} declares {env} but no Party deployment file mentions it')
    return d


# ---- Games ------------------------------------------------------------------------------------
def check_games(games):
    decl_path = games / 'provider/avrana-contract.json'
    d = load(decl_path, 'Games contract declaration')
    where = 'provider/avrana-contract.json'
    sp = d['session_protocol']
    vendored = games / sp['vendored']
    expect(constant(vendored, 'VERSION'), sp['version'], 'vendored protocol version', where)
    expect(sha256_normalized(vendored), sp['vendored_sha256'], 'vendored protocol file digest', where)
    expect(sha256_normalized(games / sp['vectors']), sp['vectors_sha256'], 'vendored vectors digest', where)
    res = d['result']
    vendored_result = games / res['vendored']
    expect(constant(vendored_result, 'SCHEMA'), res['schema'], 'vendored result schema', where)
    expect(sha256_normalized(vendored_result), res['vendored_sha256'], 'vendored result file digest', where)
    expect(sha256_normalized(games / res['vectors']), res['vectors_sha256'], 'vendored result vectors digest', where)
    if 'bridge' not in d:
        raise Drift(f'{where} declares no bridge: a games repository vendors the bridge shim (ADR 0013) '
                    'and declares it with its vectors')
    check_bridge(games, d['bridge'], 'vendored', where)
    for slug in res['reported_by']:
        if slug not in d['party_side_games']:
            raise Drift(f'result reporters drifted: {where} lists {slug!r} under result.reported_by '
                        'but not under party_side_games')
        game = games / 'games' / slug / 'game.py'
        if not game.exists() or 'def game_result(' not in game.read_text(encoding='utf-8'):
            raise Drift(f'result reporters drifted: {where} says {slug!r} reports results but '
                        f'games/{slug}/game.py defines no game_result()')
    session = games / 'core/party_session.py'
    r = d['routes']
    expect(constant(session, 'ENDED_PATH'), r['party_ended'], 'games ended route', where)
    expect(constant(session, 'HOST_PATH'), r['party_host'], 'games host route', where)
    server = (games / 'server.py').read_text(encoding='utf-8')
    for key, route in (('game_launch', r['game_launch']), ('game_end', r['game_end'])):
        if f'"/games/{{slug}}{route}"' not in server and f"'/games/{{slug}}{route}'" not in server:
            raise Drift(f'{key} drifted: {where} declares {route!r} but server.py does not mount /games/{{slug}}{route}')
    exporter = games / 'ops/export_avrana_catalog.py'
    expect(constant(exporter, 'INTEGRATION'), d['launch']['integration'], 'launch integration', where)
    env = d['environment']
    expect(constant(session, 'KEYS_ENV'), env['keys_dir'], 'keys environment variable', where)
    conf = (games / 'deploy/avrana-party-session.conf').read_text(encoding='utf-8')
    for name in env.values():
        if f'Environment={name}=' not in conf:
            raise Drift(f'environment drifted: {where} declares {name} but deploy/avrana-party-session.conf does not set it')
    return d


# ---- across -----------------------------------------------------------------------------------
def check_cross(party, games, p, g):
    if g['requires'] != p['contract']:
        raise Drift(f'contract version drifted: Games requires {g["requires"]!r}, Party implements {p["contract"]!r}')
    ps, gs = p['session_protocol'], g['session_protocol']
    if gs['version'] != ps['version']:
        raise Drift(f'session protocol version drifted: Games {gs["version"]!r} vs Party {ps["version"]!r}')
    if gs['vendored_sha256'] != ps['reference_sha256']:
        raise Drift('session protocol drifted: core/party_protocol.py (Games) is not byte-identical to '
                    'avrana/party/protocol.py (Party); re-vendor both files and update both declarations')
    if gs['vectors_sha256'] != ps['vectors_sha256']:
        raise Drift('session protocol vectors drifted between tests/vectors/ (Games) and contracts/vectors/ (Party)')
    pr, gr = p['result'], g['result']
    if gr['schema'] != pr['schema'] or gr['carried_by'] != pr['carried_by']:
        raise Drift(f'result schema drifted: Games {gr["schema"]!r} via {gr["carried_by"]!r} vs '
                    f'Party {pr["schema"]!r} via {pr["carried_by"]!r}')
    if gr['vendored_sha256'] != pr['reference_sha256']:
        raise Drift('result envelope drifted: core/party_result.py (Games) is not byte-identical to '
                    'avrana/party/result.py (Party); re-vendor the file and update both declarations')
    if gr['vectors_sha256'] != pr['vectors_sha256']:
        raise Drift('result vectors drifted between tests/vectors/ (Games) and contracts/vectors/ (Party)')
    pb, gb = p['bridge'], g['bridge']
    if gb['protocol'] != pb['protocol']:
        raise Drift(f'bridge protocol drifted: Games {gb["protocol"]!r} vs Party {pb["protocol"]!r}')
    if gb['vendored_sha256'] != pb['reference_sha256']:
        raise Drift(f'bridge shim drifted: {gb["vendored"]} (Games) is not byte-identical to '
                    f'{pb["reference"]} (Party); re-vendor the file and update both declarations')
    if gb['vectors_sha256'] != pb['vectors_sha256']:
        raise Drift('bridge vectors drifted between tests/vectors/ (Games) and contracts/vectors/ (Party)')
    for key in ('party_ticket', 'party_ended', 'party_host', 'game_launch', 'game_end'):
        if p['routes'][key] != g['routes'][key]:
            raise Drift(f'route {key} drifted: Party {p["routes"][key]!r} vs Games {g["routes"][key]!r}')
    if p['launch'] != g['launch']:
        raise Drift(f'launch contract drifted: Party {p["launch"]} vs Games {g["launch"]}')
    if p['environment'] != g['environment']:
        raise Drift(f'environment names drifted: Party {p["environment"]} vs Games {g["environment"]}')
    party_snapshot = load(party / p['catalog']['snapshot'], 'Party catalog snapshot')
    games_snapshot = load(games / p['catalog']['source_path'], 'Games catalog snapshot')
    if party_snapshot != games_snapshot:
        raise Drift(f'catalog snapshot drifted: {p["catalog"]["snapshot"]} (Party) differs from '
                    f'{p["catalog"]["source_path"]} (Games); copy the reviewed Games export to Party and run '
                    'python -m avrana.contracts.catalog')


def run(party, games=None):
    p = check_party(party)
    print(f'Party implements {p["contract"]} ({p["session_protocol"]["version"]}, '
          f'{p["result"]["schema"]}, {p["bridge"]["protocol"]}, {p["launch"]["integration"]}): OK')
    if games is None:
        print('Games checkout not given: cross-repository checks NOT run (pass --games)')
        return
    g = check_games(games)
    print(f'Games requires {g["requires"]}: OK against its code')
    check_cross(party, games, p, g)
    print('Party <-> Games contract: compatible')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--party', default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument('--games', default=None)
    args = ap.parse_args(argv)
    try:
        run(Path(args.party).resolve(), Path(args.games).resolve() if args.games else None)
    except Drift as e:
        print(f'CONTRACT DRIFT: {e}', file=sys.stderr)
        return 1
    except (KeyError, TypeError) as e:
        print(f'CONTRACT DRIFT: a declaration is missing a field ({e})', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
