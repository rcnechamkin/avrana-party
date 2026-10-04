"""Party Core's per-game metadata, derived from the Game Contracts (AVR-229; ADR 0014 decision 7).

    python3 -m avrana.contracts.party_config --check deploy/party-core/party-core.example.json
    python3 -m avrana.contracts.party_config --show  deploy/party-core/party-core.example.json

Party Core needs four facts about a game: the fewest and the most players of a round, what a
member who arrives late may do, and whether the Party runs the pregame (ADR 0010). They used to be
typed by hand into `/etc/avrana-party/party-core.json` beside the contract that already states
them. Now there is one source per field:

    min_players, max_players   contract `players.min` / `players.max`
    late_join                  contract `late_join`
    pregame                    contract `extensions["net.avrana.party"].pregame` (default false)

The Party Core config keeps only what the appliance owns: where the game server is (`url`), its
key file and the link `timeout`. A config that still repeats a derived field is accepted only when
it says the same thing as the contract; a difference is an error that names the field, so a stale
copy can never silently win. A configured game without a contract is an error.

The contracts are the ones the browser catalog is built from (catalog.load_contracts), so Party
Home and Party Core cannot disagree about a game.
"""
import argparse
import json
import sys

from avrana import CONTRACTS_DIR

EXTENSION = 'net.avrana.party'
EXTENSION_KEYS = {'pregame'}
DERIVED = ('min_players', 'max_players', 'late_join', 'pregame')
APPLIANCE_KEYS = {'url', 'socket', 'key_file', 'timeout'}     # where the game is; never facts about it


class ConfigError(ValueError):
    """The Party Core game config disagrees with the contracts. `problems` lists every reason."""

    def __init__(self, problems):
        super().__init__('; '.join(problems))
        self.problems = list(problems)


def party_extension(contract):
    """The validated `net.avrana.party` extension of a contract ({} when absent)."""
    cid = contract.get('id')
    ext = contract.get('extensions', {}).get(EXTENSION, {})
    if not isinstance(ext, dict):
        raise ConfigError([f'{cid}: extensions[{EXTENSION!r}] must be an object'])
    problems = [f'{cid}: extensions[{EXTENSION!r}]: unknown key {key!r}'
                for key in sorted(set(ext) - EXTENSION_KEYS)]
    if 'pregame' in ext and type(ext['pregame']) is not bool:
        problems.append(f'{cid}: extensions[{EXTENSION!r}].pregame: true or false')
    if problems:
        raise ConfigError(problems)
    return ext


def metadata(contract):
    """What Party Core needs to know about one game, from its (normalised) contract."""
    return {'min_players': contract['players']['min'], 'max_players': contract['players']['max'],
            'late_join': contract['late_join'],
            'pregame': bool(party_extension(contract).get('pregame', False))}


def load_contracts(directory=None):
    """{game id: contract}: the same merged set the browser catalog is built from."""
    from avrana.contracts import catalog, vocabulary
    return catalog.load_contracts(directory or CONTRACTS_DIR / 'games', vocabulary.load())


def resolve(entries, contracts=None):
    """Party Core's games for a config's `games` object: {id: {'id', min_players, max_players,
    late_join, pregame}}. Raises ConfigError naming every problem."""
    if not isinstance(entries, dict):
        raise ConfigError(['games: an object keyed by game id'])
    contracts = load_contracts() if contracts is None else contracts
    games, problems = {}, []
    for game_id, entry in entries.items():
        contract = contracts.get(game_id)
        if contract is None:
            problems.append(f'{game_id}: no Game Contract (contracts/games/{game_id}.json)')
            continue
        if not isinstance(entry, dict):
            problems.append(f'{game_id}: an object')
            continue
        try:
            meta = metadata(contract)
        except ConfigError as e:
            problems += e.problems
            continue
        for key in sorted(set(entry) - APPLIANCE_KEYS - set(DERIVED)):
            problems.append(f'{game_id}: unknown key {key!r}')
        for key in DERIVED:
            if key in entry and entry[key] != meta[key]:
                problems.append(f'{game_id}.{key}: the config says {entry[key]!r} but the contract '
                                f'says {meta[key]!r}; remove it from the config (the contract decides)')
        games[game_id] = {'id': game_id, **meta}
    if problems:
        raise ConfigError(problems)
    return games


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', metavar='CONFIG',
                      help='exit 1 if the config disagrees with the contracts')
    mode.add_argument('--show', metavar='CONFIG', help='print the games Party Core would run')
    args = ap.parse_args(argv)
    path = args.check or args.show
    with open(path, encoding='utf-8') as f:
        conf = json.load(f)
    try:
        games = resolve(conf.get('games', {}))
    except ConfigError as e:
        for problem in e.problems:
            print(f'{path}: {problem}', file=sys.stderr)
        return 1
    if args.show:
        json.dump(games, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write('\n')
    else:
        print(f'{path}: {len(games)} game(s) agree with their contracts')
    return 0


if __name__ == '__main__':
    sys.exit(main())
