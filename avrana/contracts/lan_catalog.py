"""Normalize the legacy donor's public metadata into Game Contract v0.

No routes or grants come from donor JSON. The appliance owns installation; this
module only describes known titles. The snapshot deliberately excludes live state.
"""
import re

from avrana.contracts import game, strictjson

SLUG = re.compile(r'^[a-z][a-z0-9_-]{0,35}$')
FIELDS = {'slug', 'title', 'icon', 'summary', 'min_p', 'max_p', 'tv', 'category'}


def parse(doc, vocab):
    if not isinstance(doc, dict) or set(doc) != {'schema', 'source', 'games'}:
        raise ValueError('LAN catalog: expected schema, source, games')
    if doc['schema'] != 'avrana.lan-catalog/v0' or not isinstance(doc['source'], dict):
        raise ValueError('LAN catalog: unsupported schema/source')
    if not re.fullmatch(r'[0-9a-f]{40}', doc['source'].get('commit', '')):
        raise ValueError('LAN catalog: source commit required')
    if not isinstance(doc['games'], list) or len(doc['games']) > 100:
        raise ValueError('LAN catalog: bounded games list required')
    contracts = {}
    for row in doc['games']:
        if not isinstance(row, dict) or set(row) != FIELDS:
            raise ValueError('LAN catalog: unexpected metadata fields')
        slug = row['slug']
        if not isinstance(slug, str) or not SLUG.fullmatch(slug):
            raise ValueError('LAN catalog: invalid slug')
        cid = 'lan-' + slug
        if cid in contracts:
            raise ValueError('LAN catalog: duplicate slug')
        for key, maximum in (('title', 80), ('summary', 240), ('icon', 16), ('category', 24)):
            value = row[key]
            if not isinstance(value, str) or not 1 <= len(value) <= maximum:
                raise ValueError(f'LAN catalog: invalid {key}')
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
        contracts[cid] = game.validate(doc_game, vocab)
    return contracts


def load(path, vocab):
    return parse(strictjson.load_path(path), vocab)
