"""Build the Full Mode web catalog from game contracts and the appliance profile.

    python3 -m avrana.contracts.catalog            # writes web/party/catalog.json
    python3 -m avrana.contracts.catalog --check    # exit 1 if the committed file is stale (CI)

The catalog is what the browser needs to decide per seat without knowing the appliance: each
game's presentations already carry whether the appliance can serve them (runtime capability), so
the page only compares device capabilities. Output is deterministic (no timestamps) so CI can
check that the committed file matches its sources.
"""
import argparse
import sys
from pathlib import Path

from avrana import CONTRACTS_DIR, WEB_DIR
from avrana.contracts import appliance as appliance_mod
from avrana.contracts import game as game_mod
from avrana.contracts import strictjson, vocabulary, lan_catalog, provider_metadata
from avrana.contracts.evaluate import compile_presentations

CATALOG = 'avrana.catalog/v0'
DEFAULT_APPLIANCE = CONTRACTS_DIR / 'appliances' / 'avrana-pi4.json'
DEFAULT_OUT = WEB_DIR / 'catalog.json'


def load_contracts(directory, vocab):
    contracts = {}
    for path in sorted(Path(directory).glob('*.json')):
        contract = game_mod.load(path, vocab)
        contracts[contract['id']] = contract
    # The default appliance catalog includes the audited legacy donor library.
    # Custom --games directories remain self-contained.
    if Path(directory).resolve() == (CONTRACTS_DIR / 'games').resolve():
        donor = lan_catalog.load(CONTRACTS_DIR / 'catalogs' / 'lan-games.json', vocab)
        for cid, c in donor.items():
            if cid in contracts:
                if cid != 'bluff':
                    raise ValueError('duplicate donor/game contract ids')
                # Keep BLUFF's explicit hand/spectator/capability contract; public
                # display metadata and player counts come from its provider.
                contracts[cid].update({k: c[k] for k in ('name', 'summary', 'players')})
                contracts[cid].setdefault('extensions', {})['net.avrana.catalog'] = c['extensions']['net.avrana.catalog']
            else:
                contracts[cid] = c
    return contracts


def build(vocab, appliance, contracts, include=('live',)):
    runtime = appliance_mod.runtime_capabilities(appliance, include)
    grants = appliance_mod.grants(appliance)
    unknown = sorted(set(grants) - set(contracts))
    if unknown:
        raise ValueError(f'installed games without a contract: {unknown}')
    donor_launches = (lan_catalog.launch_targets(CONTRACTS_DIR / 'catalogs' / 'lan-games.json', vocab)
                     if any(c.get('extensions', {}).get('net.avrana.catalog', {}).get('integration')
                            for c in contracts.values()) else {})
    games = []
    for cid, c in contracts.items():
        grant = grants.get(cid)
        presentations = compile_presentations(c, runtime)
        playable = any(p['available'] and 'player' in p['roles'] for p in presentations)
        if grant and not playable:
            raise ValueError(f'{cid} is installed but the appliance cannot present it to players')
        if grant:
            extra = sorted(set(grant.get('permissions_granted', [])) - set(c['runtime']['permissions']))
            if extra:
                raise ValueError(f'{cid}: granted {extra} that its contract never requested')
        entry = {
            'id': cid, 'name': c['name'], 'kind': c['kind'], 'players': c['players'],
            'screen': c['screen'], 'input': c['input'], 'late_join': c['late_join'],
            'spectators': c['spectators'], 'private_player_ui': c['private_player_ui'],
            'fallback': c['fallback'], 'installed': grant is not None,
            'entry': grant['entry'] if grant else None,
            'health': grant.get('health') if grant else None,
            'playableHere': playable, 'presentations': presentations,
        }
        meta = c.get('extensions', {}).get('net.avrana.catalog', {})
        entry['provider'] = meta.get('provider', 'arcade' if cid.startswith('arcade-') else
                                     'lan-games' if c['runtime']['type'] == 'lan_games_module' else 'retroarch')
        if entry['provider'] == 'retroarch-ps1':
            entry['providerMetadata'] = provider_metadata.ps1(c)
        provider_target = donor_launches.get(cid) if meta.get('integration') else None
        if provider_target:
            entry['launchTarget'] = provider_target
        if grant and provider_target and grant['entry'] != provider_target:
            raise ValueError(f'{cid}: installed path disagrees with authoritative launch target')
        entry['status'] = meta.get('status', 'current' if grant else 'not_installed')
        for key in ('legacySlug', 'icon', 'category', 'hardwareValidationRequired',
                    'description', 'solo', 'art', 'accent', 'playersLabel', 'integration'):
            if key in meta:
                entry[key] = meta[key]
        if 'summary' in c:
            entry['summary'] = c['summary']
        games.append(entry)
    games.sort(key=lambda g: (not g['installed'], g['name'].lower(), g['id']))
    have = set(runtime)
    collections = [{'id': col['id'], 'name': col['name'], 'summary': col.get('summary', ''),
                    'entry': col['entry'], 'available': all(r in have for r in col['requires'])}
                   for col in appliance.get('collections') or []]
    used_device = sorted({n for g in games for p in g['presentations']
                          for n in p['requires']['device'] + p['optional']['device']})
    return {
        'schema': CATALOG,
        'appliance': {'id': appliance['id'], 'name': appliance['name']},
        'providers': [{'id': p['id'], 'kind': p['kind'], 'status': p['status'], 'offers': p['offers']}
                      for p in appliance['providers']],
        'runtime': runtime,
        'labels': {n: {'label': vocab.label(n), 'missing': vocab.missing(n)}
                   for n in sorted(set(used_device) | set(vocab.device) | have)},
        'games': games,
        'collections': collections,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--appliance', default=str(DEFAULT_APPLIANCE))
    ap.add_argument('--games', default=str(CONTRACTS_DIR / 'games'))
    ap.add_argument('--out', default=str(DEFAULT_OUT))
    ap.add_argument('--include-experiments', action='store_true',
                    help='also count experiment providers (lab builds only; never the committed catalog)')
    ap.add_argument('--check', action='store_true', help='exit 1 if --out differs from a fresh build')
    args = ap.parse_args(argv)
    vocab = vocabulary.load()
    appliance = appliance_mod.load(args.appliance, vocab)
    contracts = load_contracts(args.games, vocab)
    include = ('live', 'experiment') if args.include_experiments else ('live',)
    text = strictjson.dumps(build(vocab, appliance, contracts, include))
    out = Path(args.out)
    if args.check:
        current = out.read_text(encoding='utf-8') if out.exists() else ''
        if current != text:
            print(f'{out} is stale: run python3 -m avrana.contracts.catalog', file=sys.stderr)
            return 1
        print(f'{out} is up to date ({len(contracts)} contracts)')
        return 0
    out.write_text(text, encoding='utf-8', newline='\n')
    print(f'wrote {out} ({len(contracts)} contracts)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
