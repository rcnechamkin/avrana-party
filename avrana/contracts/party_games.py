"""The Party <-> Games contract declaration (contracts/party-games.v0.json).

Party *implements* this contract; Games *requires* one (provider/avrana-contract.json in the
games repository). The declaration is data: tools/contract_check.py proves it against the code of
both repositories, and the deployment manifest and /party/api/status report the version so a
running appliance states which boundary it serves. Nothing here is a protocol implementation.
"""
import json

from avrana import CONTRACTS_DIR

PATH = CONTRACTS_DIR / 'party-games.v0.json'
REQUIRED = ('contract', 'session_protocol', 'result', 'bridge', 'routes', 'launch', 'environment', 'catalog')


class ContractError(ValueError):
    pass


def load(path=PATH):
    try:
        doc = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise ContractError(f'{path}: unreadable contract declaration ({type(e).__name__})')
    missing = [k for k in REQUIRED if k not in doc]
    if missing:
        raise ContractError(f'{path}: missing {", ".join(missing)}')
    if not isinstance(doc['contract'], str) or not doc['contract'].startswith('avrana.party-games/v'):
        raise ContractError(f'{path}: contract id must be avrana.party-games/vN')
    return doc


def versions(doc=None):
    """The identifiers a running appliance reports (never file hashes: those are CI's business)."""
    doc = doc or load()
    return {'party_games': doc['contract'],
            'party_session': doc['session_protocol']['version'],
            'lan_launch': doc['launch']['integration']}
