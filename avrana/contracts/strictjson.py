"""Strict JSON for contracts: duplicate keys and NaN/Infinity are errors, not surprises."""
import json


class StrictJSONError(ValueError):
    pass


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise StrictJSONError(f'duplicate key {key!r}')
        out[key] = value
    return out


def _constant(name):
    raise StrictJSONError(f'{name} is not valid JSON')


def loads(text):
    try:
        return json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    except json.JSONDecodeError as exc:
        raise StrictJSONError(str(exc)) from None


def load_path(path):
    with open(path, encoding='utf-8') as f:
        return loads(f.read())


def dumps(value):
    """Deterministic output for generated files (sorted keys only where order carries no meaning
    is the caller's job; this keeps insertion order and a trailing newline)."""
    return json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n'
