"""The capability vocabulary: one list of names for games, the appliance and the browser probe.

Data: contracts/capabilities.v0.json. Device capabilities are observed in the guest's browser;
runtime capabilities are offered by the appliance's providers. A name means the same thing
everywhere, so a Game Contract can only require names that exist here.
"""
import re
from dataclasses import dataclass

from avrana import CONTRACTS_DIR
from avrana.contracts import strictjson

VOCABULARY_SCHEMA = 'avrana.capability-vocabulary/v0'
PROBES = ('presence', 'functional', 'permission')
NAME = re.compile(r'^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$')
_TEXT_LIMIT = 160


@dataclass(frozen=True)
class Vocabulary:
    device: dict      # name -> {probe, summary, label, missing}
    runtime: dict     # name -> {summary, label, missing}

    def label(self, name):
        entry = self.device.get(name) or self.runtime.get(name)
        return entry['label'] if entry else name

    def missing(self, name):
        entry = self.device.get(name) or self.runtime.get(name)
        return entry['missing'] if entry else f'{name} is not available.'


def check(doc):
    """Problems in a vocabulary document (empty list = valid)."""
    problems = []
    if not isinstance(doc, dict):
        return ['vocabulary: must be an object']
    if doc.get('schema') != VOCABULARY_SCHEMA:
        problems.append(f'vocabulary: schema must be {VOCABULARY_SCHEMA!r}')
    unknown = set(doc) - {'schema', 'note', 'device', 'runtime'}
    if unknown:
        problems.append(f'vocabulary: unknown keys {sorted(unknown)}')
    for scope, required in (('device', {'probe', 'summary', 'label', 'missing'}),
                            ('runtime', {'summary', 'label', 'missing'})):
        entries = doc.get(scope)
        if not isinstance(entries, dict) or not entries:
            problems.append(f'vocabulary.{scope}: must be a non-empty object')
            continue
        for name, entry in entries.items():
            where = f'vocabulary.{scope}.{name}'
            if not NAME.match(name):
                problems.append(f'{where}: bad name')
            if scope == 'runtime' and '.' not in name:
                problems.append(f'{where}: runtime names are namespaced (runtime., input., presentation.)')
            if not isinstance(entry, dict) or set(entry) != required:
                problems.append(f'{where}: keys must be exactly {sorted(required)}')
                continue
            if scope == 'device' and entry['probe'] not in PROBES:
                problems.append(f'{where}.probe: one of {PROBES}')
            for key in required - {'probe'}:
                value = entry[key]
                if not isinstance(value, str) or not value.strip() or len(value) > _TEXT_LIMIT:
                    problems.append(f'{where}.{key}: 1-{_TEXT_LIMIT} characters')
    overlap = set(doc.get('device') or {}) & set(doc.get('runtime') or {})
    if overlap:
        problems.append(f'vocabulary: names in both scopes {sorted(overlap)}')
    return problems


def load(path=None):
    doc = strictjson.load_path(path or CONTRACTS_DIR / 'capabilities.v0.json')
    problems = check(doc)
    if problems:
        raise ValueError('; '.join(problems))
    return Vocabulary(device=doc['device'], runtime=doc['runtime'])
