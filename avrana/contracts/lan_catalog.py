"""Normalize the legacy donor's public metadata into Game Contract v0.

No routes or grants come from donor JSON. The appliance owns installation; this
module only describes known titles. The snapshot deliberately excludes live state.
"""
import re

from avrana.contracts import game, strictjson

SLUG = re.compile(r'^[a-z][a-z0-9_-]{0,35}$')
FIELDS = {'slug', 'title', 'icon', 'summary', 'min_p', 'max_p', 'tv', 'category'}

V1_FIELDS = FIELDS | {'id', 'description', 'launch', 'solo', 'art', 'accent', 'playersLabel'}

def parse(doc, vocab):
    if not isinstance(doc, dict) or set(doc) != {'schema', 'source', 'games'}:
        raise ValueError('LAN catalog: expected schema, source, games')
    if doc['schema'] not in {'avrana.lan-catalog/v0', 'avrana.lan-catalog/v1'} or not isinstance(doc['source'], dict):
        raise ValueError('LAN catalog: unsupported schema/source')
    if not re.fullmatch(r'[0-9a-f]{40}', doc['source'].get('commit', '')):
        raise ValueError('LAN catalog: source commit required')
    if not isinstance(doc['games'], list) or len(doc['games']) > 100:
        raise ValueError('LAN catalog: bounded games list required')
    v1 = doc['schema'] == 'avrana.lan-catalog/v1'
    if v1 and (not re.fullmatch(r'[0-9a-f]{64}', doc['source'].get('registrySha256', ''))
               or doc['source'].get('integration') != 'avrana.lan-launch/v1'):
        raise ValueError('LAN catalog: export provenance/integration required')
    contracts = {}
    for row in doc['games']:
        if not isinstance(row, dict) or set(row) != (V1_FIELDS if v1 else FIELDS):
            raise ValueError('LAN catalog: unexpected metadata fields')
        slug = row['slug']
        if not isinstance(slug, str) or not SLUG.fullmatch(slug):
            raise ValueError('LAN catalog: invalid slug')
        cid = 'bluff' if v1 and slug == 'bluff' else 'lan-' + slug
        if v1 and (row['id'] != cid or row['launch'] != f'/games/{slug}/'):
            raise ValueError('LAN catalog: invalid canonical identity/direct target')
        if v1 and (type(row['solo']) is not bool or not isinstance(row['description'], str)
                   or not 1 <= len(row['description']) <= 2000):
            raise ValueError('LAN catalog: invalid description/solo')
        if cid in contracts:
            raise ValueError('LAN catalog: duplicate slug')
        for key, maximum in (('title', 80), ('summary', 240), ('icon', 16), ('category', 24)):
            value = row[key]
            if not isinstance(value, str) or not 1 <= len(value) <= maximum:
                raise ValueError(f'LAN catalog: invalid {key}')
        if v1:
            if not isinstance(row['playersLabel'], str) or not 1 <= len(row['playersLabel']) <= 100:
                raise ValueError('LAN catalog: invalid player label')
            if row['art'] is not None and (not isinstance(row['art'], str) or not 1 <= len(row['art']) <= 32):
                raise ValueError('LAN catalog: invalid art')
            if row['accent'] is not None and (not isinstance(row['accent'], str)
                    or not re.fullmatch(r'#[0-9a-fA-F]{6}', row['accent'])):
                raise ValueError('LAN catalog: invalid accent')
        if type(row['tv']) is not bool:
            raise ValueError('LAN catalog: tv must be boolean')
        # Only claims present in the registry: no invented spectator/late-join/private-hand facts.
        doc_game = {
            'contract': game.CONTRACT, 'id': cid, 'name': row['title'],
            'summary': row['summary'], 'kind': 'native',
            'players': {'min': row['min_p'], 'max': row['max_p']},
            'screen': 'tv_required' if row['tv'] else 'no_tv_needed',
            'input': {'model': 'browser_native'},
            'late_join': 'spectator_only', 'spectators': 'none', 'private_player_ui': False,
            'runtime': {'type': 'lan_games_module', 'start': 'always_on', 'permissions': []},
            'presentations': [{
                'id': 'phone', 'method': 'browser_native', 'roles': ['player'],
                'requires': {'device': ['websocket'], 'runtime': ['runtime.lan_games']},
                'optional': {'device': ['storage.local']},
            }],
            'fallback': 'explain',
            'extensions': {'net.avrana.catalog': {
                'provider': 'lan-games', 'legacySlug': slug,
                'icon': row['icon'], 'category': row['category'],
                'status': 'current', 'requirementsReview': True,
            }},
        }
        if v1:
            doc_game['extensions']['net.avrana.catalog'].update({
                'description': row['description'],
                'solo': row['solo'], 'art': row['art'], 'accent': row['accent'],
                'playersLabel': row['playersLabel'], 'integration': 'avrana.lan-launch/v1',
            })
        contracts[cid] = game.validate(doc_game, vocab)
    return contracts


def load(path, vocab):
    return parse(strictjson.load_path(path), vocab)

def launch_targets(path, vocab):
    """Provider routes stay outside Game Contracts and never grant installation."""
    doc = strictjson.load_path(path)
    parse(doc, vocab)
    if doc['schema'] != 'avrana.lan-catalog/v1':
        return {}
    return {row['id']: row['launch'] for row in doc['games']}
