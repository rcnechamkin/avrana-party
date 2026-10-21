"""Redaction and privacy validation for field-session evidence (AVR-697).

Two halves that are tested against each other:

    scrub_text / scrub_json   what goes INTO a field-session package: every string passes through
                              the rules below before it is written
    validate_members          what a finished package is checked against before it is exported, and
                              again by `fieldsession validate`: any hit refuses the package

What must never leave the appliance in a package (docs/runbooks/field-session.md):
credentials and private keys (PEM blocks, game keys, `Authorization`, bearer/basic tokens),
membership cookies (`__Host-avrana_device`, `avrana_device`, `avrana_limited`) and device tokens,
per-member or per-device identifiers (`member-…`, `device-…`), device addresses (IPv4 other than
loopback and the Party AP, IPv6, MAC), e-mail addresses, quoted text (player names and chat land in
logs as quoted strings) and whole log lines that talk about chat. SHAs are kept only in the
structured fields that name a revision (SHA_KEYS); anywhere else a long hex string is redacted,
because game keys are 64 hex characters too.
"""
import json
import re

RULES_VERSION = 'avrana.redaction/v1'
REDACTED = '[redacted]'
ALLOWED_ADDRESSES = {'127.0.0.1', '10.42.0.1', '0.0.0.0', '10.42.0.0', '255.255.255.0'}
# Structured fields whose value is a revision or a public digest, not a secret (status, manifest).
SHA_KEYS = {'sha', 'short', 'deployed_sha', 'checkout_sha', 'commit', 'party_sha', 'games_sha', 'sha256',
            'nginx_site_sha256', 'archive_sha256', 'tree_sha', 'tool_sha', 'party', 'games', 'web_commit'}
SHA_VALUE = re.compile(r'[0-9a-f]{7,64}')
# Field names whose values are dropped whatever they hold.
SECRET_KEY = re.compile(r'(?i)(^|_|-)(token|secret|password|passwd|cookie|authorization|auth|key|ticket|nonce|'
                        r'signature|credential|session_key|sid|device|member|name|nickname|text|message_text|chat|'
                        r'peer|address|ip|mac|user_agent|ua|email)($|_|-)')
# Keys that look secret by the pattern but hold no secret (counts, states, unit names).
SAFE_KEYS = {'members', 'name', 'unit', 'game', 'state', 'members_count', 'key_file'}

_RULES = [
    ('pem', re.compile(r'-----BEGIN [A-Z0-9 ]+-----.*?(?:-----END [A-Z0-9 ]+-----|\Z)', re.S)),
    ('authorization', re.compile(r'(?i)\b(?:proxy-)?authorization\s*[:=]\s*[^\r\n]*')),
    ('bearer', re.compile(r'(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}')),
    ('cookie_header', re.compile(r'(?i)\b(?:set-)?cookie\s*[:=]\s*[^\r\n]*')),
    ('membership_cookie', re.compile(r'(?:__Host-)?avrana_(?:device|limited)\s*=\s*[^;\s,"\']*')),
    ('secret_assignment', re.compile(r'(?i)\b([a-z_-]*(?:token|secret|password|passwd|key|ticket|nonce|signature|sid))'
                                     r'(\s*[:=]\s*)("[^"]*"|\'[^\']*\'|[^\s,;&]+)')),
    ('identifier', re.compile(r'\b(?:member|device|guest|seat)-[0-9a-f]{8,}\b')),
    ('email', re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')),
    ('mac', re.compile(r'\b[0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5}\b')),
    # Full form (six or more groups) or compressed with '::'; a clock time such as 18:00:00 is neither.
    ('ipv6', re.compile(r'(?i)(?<![0-9a-f:])(?:(?:[0-9a-f]{1,4}:){5,7}[0-9a-f]{1,4}|'
                        r'(?:[0-9a-f]{1,4}:){1,6}:(?:[0-9a-f]{1,4}(?::[0-9a-f]{1,4}){0,5})?|'
                        r'::(?:[0-9a-f]{1,4}:){0,5}[0-9a-f]{1,4})(?![0-9a-f:])')),
    ('ipv4', re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')),
    ('long_hex', re.compile(r'(?<![0-9a-fA-F])[0-9a-fA-F]{32,}')),
    ('base64_token', re.compile(r'(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{22,}={0,2}(?![A-Za-z0-9_-])')),
    ('quoted', re.compile(r'"[^"\r\n]{1,200}"|\'[^\'\r\n]{2,200}\'|“[^”\r\n]{1,200}”')),
]
# A log line that talks about chat is dropped whole: its content is someone's conversation.
CHAT_LINE = re.compile(r'(?i)\bchat\b|\bsaid\b|\bmessage text\b')


def _benign(rule, found):
    """A match that is not what the rule is for: the AP or loopback address, a version number, or a
    word-like run: a session id or slug (fewer than three capitals) or a CamelCase name such as
    ConnectionRefusedError (letters only, under 30). A 43-character token_urlsafe value escapes with a
    probability far below 1e-6 (tests/unit/test_fieldsession.py measures it)."""
    if rule == 'ipv4':
        return found in ALLOWED_ADDRESSES or not all(0 <= int(p) <= 255 for p in found.split('.'))
    if rule == 'base64_token':
        upper, lower = sum(c.isupper() for c in found), sum(c.islower() for c in found)
        return upper < 3 or lower < 3 or (found.rstrip('=').isalpha() and len(found) < 30)
    return False


def _replace(rule, match):
    if _benign(rule, match.group(0)):
        return match.group(0)
    if rule == 'secret_assignment':
        return f'{match.group(1)}{match.group(2)}{REDACTED}'
    return f'[{rule}]'


def scrub_text(text, limit=500):
    """`text` with every rule applied, bounded to `limit` characters."""
    if not isinstance(text, str):
        text = str(text)
    for rule, pattern in _RULES:
        text = pattern.sub(lambda m, r=rule: _replace(r, m), text)
    return text if len(text) <= limit else text[:limit] + '…'


def scrub_json(value, key=None, limit=500):
    """A JSON-like value with secret-named fields dropped and every other string scrubbed."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            name = str(k)
            if name not in SAFE_KEYS and name not in SHA_KEYS and SECRET_KEY.search(name):
                if isinstance(v, (int, float, bool)) or v is None:
                    out[name] = v if isinstance(v, bool) or v is None else REDACTED
                else:
                    out[name] = REDACTED
                continue
            out[name] = scrub_json(v, name, limit)
        return out
    if isinstance(value, list):
        return [scrub_json(v, key, limit) for v in value]
    if isinstance(value, str):
        if key in SHA_KEYS and SHA_VALUE.fullmatch(value):
            return value
        return scrub_text(value, limit)
    return value


def scrub_log_line(text, limit=300):
    """A journal message, or None when the whole line must go (chat)."""
    if CHAT_LINE.search(text or ''):
        return None
    return scrub_text(text, limit)


# ---- validation ------------------------------------------------------------------------------------

_FORBIDDEN = [(name, pattern) for name, pattern in _RULES if name not in ('quoted', 'secret_assignment')] + [
    ('secret_assignment', re.compile(r'(?i)\b[a-z_-]*(?:token|secret|password|passwd|ticket|nonce|signature)\s*[:=]\s*'
                                     r'(?!\[redacted\]|null|None|false|true|0\b)["\']?[^\s"\',;&\]]{4,}')),
]
_QUOTED = dict(_RULES)['quoted']
# Members holding log lines, where a line about chat must not appear at all (operator notes may say "chat").
LOG_MEMBERS = ('journal.jsonl',)


def _strings(value, key=None):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(v, str(k))
            yield None, str(k)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v, key)
    elif isinstance(value, str):
        yield key, value


def violations_in_text(text, forbid_terms=(), log=False, quoted=False):
    """[(rule, offset)] for every forbidden pattern found. The offending text itself is never returned.
    `log`: a log line (chat and quoted text forbidden); `quoted`: a stored string (quoted text forbidden,
    because every stored string was scrubbed, so quotes in one mean it was not)."""
    hits = [('chat', m.start()) for m in CHAT_LINE.finditer(text)] if log else []
    if log or quoted:
        hits += [('quoted', m.start()) for m in _QUOTED.finditer(text)]
    for rule, pattern in _FORBIDDEN:
        for m in pattern.finditer(text):
            if _benign(rule, m.group(0)):
                continue
            hits.append((rule, m.start()))
    lowered = text.lower()
    for term in forbid_terms:
        term = term.strip().lower()
        if len(term) >= 2 and re.search(r'(?<![a-z0-9])' + re.escape(term) + r'(?![a-z0-9])', lowered):
            hits.append(('forbidden_term', lowered.index(term)))
    return hits


def violations_in_json(doc, forbid_terms=(), log=False):
    hits = []
    for key, s in _strings(doc):
        if key in SHA_KEYS and SHA_VALUE.fullmatch(s):
            continue
        hits += [(rule, 0) for rule, _ in violations_in_text(s, forbid_terms, log, quoted=key is not None)]
    return hits


def validate_members(members, forbid_terms=(), max_bytes=None, allowed_names=None):
    """[{member, rule, count}] for a package given as {name: bytes}. Empty means clean."""
    problems = []
    total = sum(len(b) for b in members.values())
    if max_bytes is not None and total > max_bytes:
        problems.append({'member': '*', 'rule': 'size', 'count': total})
    for name, data in sorted(members.items()):
        if allowed_names is not None and not allowed_names(name):
            problems.append({'member': name, 'rule': 'unexpected_member', 'count': 1})
            continue
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            problems.append({'member': name, 'rule': 'not_utf8', 'count': 1})
            continue
        hits = []
        if name.endswith('.json'):
            try:
                hits = violations_in_json(json.loads(text), forbid_terms)
            except ValueError:
                problems.append({'member': name, 'rule': 'not_json', 'count': 1})
                continue
        elif name.endswith('.jsonl'):
            for line in text.splitlines():
                if not line.strip():
                    continue
                try:
                    hits += violations_in_json(json.loads(line), forbid_terms, name in LOG_MEMBERS)
                except ValueError:
                    problems.append({'member': name, 'rule': 'not_json', 'count': 1})
        else:
            hits = violations_in_text(text, forbid_terms)
        counts = {}
        for rule, _ in hits:
            counts[rule] = counts.get(rule, 0) + 1
        problems += [{'member': name, 'rule': rule, 'count': n} for rule, n in sorted(counts.items())]
    return problems
