"""The game registry: which games this appliance runs and where Party Core reaches each one.

Two sources, read together and replaced together:

  * the `games` object of party-core.json, as before: games reached over loopback TCP (`url`),
    which today are BLUFF and EXPO in the LAN Games fork and the arcade;
  * a registry directory (`registry` in party-core.json), one file per game, `<id>.json`:

        {"id": "checkers", "socket": "/run/avrana-games/checkers.sock",
         "key_file": "/etc/avrana-party/game-keys/checkers.key", "timeout": 5}

    A native game is reached over its Unix socket (ADR 0016 §4). The directory is root-owned and
    world-readable and holds no secret: an entry names a key file, never a key. Party Core reads
    it and never writes it; provisioning (AVR-236) owns it.

`build` turns both into what Party Core runs on: per-game facts from the Game Contracts
(avrana.contracts.party_config, so an entry with no contract is refused) and one GameEndpoint per
game. It is all or nothing: any problem raises RegistryError naming every offending game, and the
caller keeps what it had. `apply` swaps a running service onto a new set without touching the
party: members, host and device identities are not part of the registry.

Stdlib only. The Unix-socket transport itself is avrana.party.sessions.
"""
import json
import logging
from pathlib import Path
import re

from avrana.contracts import party_config
from avrana.party import protocol, sessions

log = logging.getLogger('avrana.party.registry')
GAME_ID = re.compile(r'^[a-z][a-z0-9_-]{0,39}$')
ENTRY_KEYS = {'id', 'socket', 'key_file', 'timeout'}


class RegistryError(ValueError):
    """The registry cannot be used. `problems` lists every reason, each starting with a game id."""

    def __init__(self, problems):
        super().__init__('; '.join(problems))
        self.problems = list(problems)


def read_directory(directory):
    """{game id: entry} from a registry directory, or RegistryError. A missing directory is an
    empty registry: an appliance with no native game has none."""
    entries, problems = {}, []
    root = Path(directory)
    if not root.is_dir():
        return {}
    for path in sorted(root.glob('*.json')):
        name = path.stem
        try:
            entry = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as e:
            problems.append(f'{name}: {path.name} is unreadable ({type(e).__name__})')
            continue
        if not isinstance(entry, dict):
            problems.append(f'{name}: {path.name} must hold one JSON object')
            continue
        game_id = entry.get('id')
        if not isinstance(game_id, str) or not GAME_ID.match(game_id):
            problems.append(f'{name}: {path.name} has no valid "id"')
            continue
        if game_id != name:
            problems.append(f'{game_id}: its entry must be named {game_id}.json, not {path.name}')
        if game_id in entries:
            problems.append(f'{game_id}: registered twice')
        for key in sorted(set(entry) - ENTRY_KEYS):
            problems.append(f'{game_id}: unknown key {key!r}')
        sock = entry.get('socket')
        if not isinstance(sock, str) or not sock.startswith('/'):
            problems.append(f'{game_id}: "socket" must be an absolute path')
        if not isinstance(entry.get('key_file'), str) or not entry['key_file']:
            problems.append(f'{game_id}: "key_file" is required')
        timeout = entry.get('timeout')
        if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                                    or not 0 < timeout <= 120):
            problems.append(f'{game_id}: "timeout" must be seconds between 0 and 120')
        entries[game_id] = entry
    if problems:
        raise RegistryError(problems)
    return entries


def build(config_games, directory=None, contracts=None, read_key=protocol.read_key):
    """(games, endpoints) for Party Core from party-core.json's `games` and the registry
    directory. Raises RegistryError, having changed nothing, when a game is registered twice,
    has no Game Contract, disagrees with its contract, or its key cannot be read."""
    config_games = config_games or {}
    if not isinstance(config_games, dict):
        raise RegistryError(['games: an object keyed by game id'])
    native = read_directory(directory) if directory else {}
    problems = [f'{g}: registered twice (party-core.json and the registry directory)'
                for g in sorted(set(native) & set(config_games))]
    merged = dict(config_games)
    merged.update({g: {k: v for k, v in e.items() if k != 'id'} for g, e in native.items()})
    games = {}
    try:
        games = party_config.resolve(merged, contracts)
    except party_config.ConfigError as e:
        problems += e.problems
    endpoints = {}
    for game_id, entry in merged.items():
        if not isinstance(entry, dict) or not entry.get('key_file') or not (entry.get('url') or entry.get('socket')):
            continue                                  # a game with no server here (catalogue only)
        try:
            key = read_key(entry['key_file'])
        except (OSError, ValueError) as e:
            # never the key or the file's content: the game and the kind of failure are enough
            problems.append(f'{game_id}: its key file cannot be used ({type(e).__name__})')
            continue
        endpoints[game_id] = sessions.GameEndpoint(
            game_id, entry.get('url') or sessions.unix_base(game_id), key, entry.get('timeout'),
            socket_path=entry.get('socket'))
    if problems:
        raise RegistryError(problems)
    return games, endpoints


def apply(service, endpoints, games, new_endpoints):
    """Put a running service on a new registry. `endpoints` is the one dict the game link and the
    session routes share; it is updated in place. The party itself is untouched. Refused, with
    nothing changed, if it would remove the game whose session is running."""
    with service.lock:
        live = service.core.party.session
        if live is not None and live.state != 'ended' and live.game_id not in games:
            raise RegistryError([f'{live.game_id}: has a session running, so it cannot be removed now'])
        service.core.games = dict(games)
        endpoints.clear()
        endpoints.update(new_endpoints)
        service.core._commit()                        # phones see the new game list
        service._notify()


def reload(service, endpoints, config_path, contracts=None):
    """Re-read party-core.json's `games` and the registry directory and apply them. True when the
    new registry is in force. A refusal keeps the previous registry and is logged, naming every
    offending game."""
    try:
        with open(config_path, encoding='utf-8') as f:
            conf = json.load(f)
        games, new = build(conf.get('games', {}), conf.get('registry'), contracts)
        before = set(endpoints)
        apply(service, endpoints, games, new)
    except RegistryError as e:
        for problem in e.problems:
            log.error('registry reload refused: %s', problem)
        return False
    except (OSError, ValueError) as e:
        log.error('registry reload refused: the config is unreadable (%s)', type(e).__name__)
        return False
    log.info('registry reloaded: %d games (added %s, removed %s)', len(games),
             sorted(set(new) - before) or 'none', sorted(before - set(new)) or 'none')
    return True
