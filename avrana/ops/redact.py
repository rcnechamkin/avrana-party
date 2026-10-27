"""Redaction and privacy validation for field-session evidence (AVR-697).

Two halves that are tested against each other:

    scrub_text / scrub_json   what goes INTO a field-session package: every string (and every JSON key)
                              passes through the rules below before it is written
    validate_members          what a finished package is checked against before it is exported, and
                              again by `fieldsession validate`: any hit refuses the package

What must never leave the appliance in a package (docs/runbooks/field-session.md):
credentials and private keys (PEM blocks, game keys, `Authorization`, bearer/basic tokens, password,
PSK, PIN and similar assignments), membership cookies (`__Host-avrana_device`, `avrana_device`,
`avrana_limited`) and device tokens, per-member or per-device identifiers (`member-…`, `device-…`),
device addresses (IPv4 other than loopback and the Party AP, IPv6, MAC), e-mail addresses, quoted text
(player names and chat land in logs as quoted strings), whole log lines that talk about chat, and the
values of fields named like a secret or a person (`token`, `cookie`, `nickname`, `playerName`, ...).

Hex digests are kept only at the JSON paths that name a revision or a public file digest (`allowed_digest`):
a 40-character commit under `deployed_sha`, `revisions.party` and the like, a 64-character sha256 only
under `nginx_site.sha256`, `nginx_site_sha256` and a package manifest's `files.<name>.sha256`. Anywhere
else 24 or more hex characters are redacted, because game keys are 64 hex characters too.
"""
import json
import re
import unicodedata

RULES_VERSION = 'avrana.redaction/v4'
REDACTED = '[redacted]'
ALLOWED_ADDRESSES = {'127.0.0.1', '10.42.0.1', '0.0.0.0', '10.42.0.0', '255.255.255.0'}
# Keys whose value is a commit (40 hex, or a 12-character short form) wherever they appear.
COMMIT_KEYS = {'deployed_sha', 'checkout_sha', 'party_sha', 'games_sha', 'commit', 'web_commit', 'tool_sha'}
REVISION_PARENTS = {'revisions', 'revisions_at_start', 'revisions_at_stop'}
HEX = re.compile(r'[0-9a-f]+')
# Field names whose values are dropped whatever they hold (matched on the snake_case form of the key).
SECRET_KEY = re.compile(r'(^|_|-)(token|secret|password|passwd|passphrase|psk|pwd|pin|cookie|authorization|auth|key|'
                        r'ticket|nonce|signature|credential|session_key|sid|device|device_id|member_id|nickname|'
                        r'name|player|player_name|display_name|user|username|text|message_text|chat|peer|address|ip|mac|'
                        r'user_agent|ua|email|phone)($|_|-)')
# Keys the pattern would catch that hold no secret: unit and check names, game ids, states, file paths.
SAFE_KEYS = {'unit', 'game', 'state', 'key_file'}
# Keys that hold a count: kept only while they are a number.
COUNT_KEYS = {'members', 'members_count', 'players', 'max_players'}

_RULES = [
    ('pem', re.compile(r'-----BEGIN [A-Z0-9 ]+-----.*?(?:-----END [A-Z0-9 ]+-----|\Z)', re.S)),
    ('authorization', re.compile(r'(?i)\b(?:proxy-)?authorization\s*[:=]\s*[^\r\n]*')),
    ('bearer', re.compile(r'(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}')),
    ('cookie_header', re.compile(r'(?i)\b(?:set-)?cookie\s*[:=]\s*[^\r\n]*')),
    ('membership_cookie', re.compile(r'(?:__Host-)?avrana_(?:device|limited)\s*=\s*[^;\s,"\']*')),
    ('secret_assignment', re.compile(r'(?i)\b([a-z_-]*(?:token|secret|password|passwd|passphrase|psk|pwd|pin|key|'
                                     r'ticket|nonce|signature|sid))(\s*[:=]\s*)("[^"]*"|\'[^\']*\'|[^\s,;&]+)')),
    # A PIN said in words, with no ':' or '=' ("Admin PIN 482915", "the passcode is 7391"): the word stays.
    ('pin', re.compile(r'(?i)(\b(?:pin|passcode)(?:[-_ ]?code)?\b(?:\s+(?:is|was|code|number|no\.?))?[\s:#]*)'
                       r'\d{4,8}(?!\d)')),
    ('identifier', re.compile(r'\b(?:member|device|guest|seat)-[0-9a-f]{8,}\b')),
    ('email', re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')),
    # Written out to dodge scrapers: "name (at) example (dot) com", "name [at] example.com".
    ('email', re.compile(r'(?i)[A-Za-z0-9._%+-]+\s*[\[(]\s*at\s*[\])]\s*[A-Za-z0-9-]+'
                         r'(?:\s*(?:[\[(]\s*dot\s*[\])]|\.)\s*[A-Za-z0-9-]+)+')),
    ('mac', re.compile(r'(?<![0-9A-Fa-f:-])[0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5}(?![0-9A-Fa-f:-])')),
    ('mac', re.compile(r'(?<![0-9A-Fa-f.])[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}(?![0-9A-Fa-f.])')),   # Cisco style
    # Twelve hex digits with no separators are a MAC only after a word that says so; elsewhere they may be a
    # short commit, which a log line keeps.
    ('mac_bare', re.compile(r'(?i)(\b(?:mac|bssid|sta|station|hwaddr|ether|lladdr)\b[\s:=]*)[0-9a-f]{12}(?![0-9a-f])')),
    # IPv4 before IPv6: in an IPv4-mapped address (`::ffff:10.42.0.57`, as dual-stack servers log a phone) the
    # IPv6 rule would take `::ffff:10` alone and leave `.42.0.57` behind. Not only at word boundaries:
    # `sta_10.42.0.57` is an address too. A dot next to it is punctuation unless a digit is on its far side
    # (AVR-738 review: "from 10.42.0.57." and "...10.42.0.57" were kept whole, by the validator too); a dotted run
    # of five or more numbers is a version, not an address.
    ('ipv4', re.compile(r'(?<!\d)(?<!\d\.)(?:\d{1,3}\.){3}\d{1,3}(?!\d)(?!\.\d)')),
    # Full form (six or more groups) or compressed with '::'; a clock time such as 18:00:00 is neither.
    ('ipv6', re.compile(r'(?i)(?<![0-9a-f:])(?:(?:[0-9a-f]{1,4}:){5,7}[0-9a-f]{1,4}|'
                        r'(?:[0-9a-f]{1,4}:){1,6}:(?:[0-9a-f]{1,4}(?::[0-9a-f]{1,4}){0,5})?|'
                        r'::(?:[0-9a-f]{1,4}:){0,5}[0-9a-f]{1,4})(?![0-9a-f:])')),
    ('long_hex', re.compile(r'(?<![0-9a-fA-F])[0-9a-fA-F]{24,}')),
    ('base64_token', re.compile(r'(?<![A-Za-z0-9_+/-])[A-Za-z0-9_+/-]{22,}={0,2}(?![A-Za-z0-9_+/-])')),
    # A single quote only counts as one when it is not an apostrophe ("Core's", "didn't").
    ('quoted', re.compile(r'"[^"\r\n]{1,1000}"|(?<![A-Za-z])\'[^\'\r\n]{2,1000}\'(?![A-Za-z])|'
                          r'“[^”\r\n]{1,1000}”|‘[^’\r\n]{2,1000}’')),
]
# A log line that talks about chat is dropped whole: its content is someone's conversation.
CHAT_LINE = re.compile(r'(?i)chat|\bsaid\b|message text')


def _benign(rule, found):
    """A match that is not what the rule is for: the AP or loopback address, a version number, or a
    word-like run: a path or slug (fewer than three capitals), or a CamelCase name such as
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
    if rule == 'pin':
        return f'{match.group(1)}{REDACTED}'
    if rule == 'mac_bare':
        return f'{match.group(1)}[mac]'
    return f'[{rule}]'


def scrub_text(text, limit=500):
    """`text` with every rule applied, then bounded to `limit` characters. Scrubbing first means no
    secret fragment survives the cut; a cut through a `[marker]` drops the marker's start."""
    if not isinstance(text, str):
        text = str(text)
    text = unicodedata.normalize('NFKC', text)       # full-width digits and dots are digits and dots
    for rule, pattern in _RULES:
        text = pattern.sub(lambda m, r=rule: _replace(r, m), text)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if cut.rfind('[') > cut.rfind(']'):
        cut = cut[:cut.rfind('[')]
    return cut + '…'


def _snake(key):
    return re.sub(r'(?<=[a-z0-9])(?=[A-Z])', '_', str(key)).lower()


def secret_field(key):
    """True when a field of this name must not carry a value (camelCase is read as snake_case)."""
    name = str(key)
    return name not in SAFE_KEYS and name not in COUNT_KEYS and name not in COMMIT_KEYS and bool(SECRET_KEY.search(_snake(name)))


def allowed_digest(path, value):
    """True when `value` is a revision or public digest at a JSON path that names one (see the module doc)."""
    if not isinstance(value, str) or not HEX.fullmatch(value) or not path:
        return False
    key = path[-1]
    parent = path[-2] if len(path) > 1 else None
    grandparent = path[-3] if len(path) > 2 else None
    if key in COMMIT_KEYS or (key in ('party', 'games') and parent in REVISION_PARENTS):
        return len(value) in (12, 40)
    if key in ('sha', 'short') and parent in ('party', 'games') and grandparent == 'deployment':
        return len(value) == (40 if key == 'sha' else 12)
    if (key == 'sha256' and parent == 'nginx_site') or key == 'nginx_site_sha256':
        return len(value) == 64
    if key == 'sha256' and grandparent == 'files':
        return len(value) == 64
    return False


def scrub_json(value, path=(), limit=500):
    """A JSON-like value: secret-named fields replaced, keys and every other string scrubbed."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            name = scrub_text(str(k), 120)
            if secret_field(name):
                out[name] = v if v is None or isinstance(v, bool) else REDACTED
            elif name in COUNT_KEYS and not isinstance(v, (int, float)) and v is not None:
                out[name] = REDACTED
            else:
                out[name] = scrub_json(v, path + (name,), limit)
        return out
    if isinstance(value, list):
        return [scrub_json(v, path, limit) for v in value]
    if isinstance(value, str):
        return value if allowed_digest(path, value) else scrub_text(value, limit)
    return value


def scrub_log_line(text, limit=300):
    """A journal message, or None when the whole line must go (chat)."""
    if CHAT_LINE.search(unicodedata.normalize('NFKC', text or '')):
        return None
    return scrub_text(text, limit)


# ---- validation ------------------------------------------------------------------------------------

_FORBIDDEN = [(name, pattern) for name, pattern in _RULES if name not in ('quoted', 'secret_assignment')] + [
    ('secret_assignment', re.compile(r'(?i)\b[a-z_-]*(?:token|secret|password|passwd|passphrase|psk|pwd|pin|ticket|'
                                     r'nonce|signature)\s*[:=]\s*(?!\[redacted\]|null|None|false|true|0\b)'
                                     r'["\']?[^\s"\',;&\]]{4,}')),
]
_QUOTED = dict(_RULES)['quoted']
# Members holding log lines, where a line about chat must not appear at all (operator notes may say "chat").
LOG_MEMBERS = ('journal.jsonl',)


def violations_in_text(text, forbid_terms=(), log=False, quoted=False):
    """[(rule, offset)] for every forbidden pattern found. The offending text itself is never returned.
    `log`: a log line (chat and quoted text forbidden); `quoted`: a stored string (quoted text forbidden,
    because every stored string was scrubbed, so quotes in one mean it was not)."""
    text = unicodedata.normalize('NFKC', text)
    hits = [('chat', m.start()) for m in CHAT_LINE.finditer(text)] if log else []
    if log or quoted:
        hits += [('quoted', m.start()) for m in _QUOTED.finditer(text)]
    for rule, pattern in _FORBIDDEN:
        for m in pattern.finditer(text):
            if not _benign(rule, m.group(0)):
                hits.append((rule, m.start()))
    folded = text.casefold()
    for term in forbid_terms:
        term = unicodedata.normalize('NFKC', term.strip()).casefold()
        if term and (len(term) >= 2 or not term.isascii()):
            m = re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)', folded)
            if m:
                hits.append(('forbidden_term', m.start()))
    return hits


def violations_in_json(doc, forbid_terms=(), log=False, path=()):
    """Hits in every key and string of a JSON value, including a secret-named field that holds a value."""
    hits = []
    if isinstance(doc, dict):
        for k, v in doc.items():
            name = str(k)
            hits += [(rule, 0) for rule, _ in violations_in_text(name, forbid_terms, quoted=True)]
            if secret_field(name) and not (v is None or isinstance(v, bool) or v == REDACTED):
                hits.append(('secret_field', 0))
                continue
            if name in COUNT_KEYS and not (v is None or isinstance(v, (int, float)) or v == REDACTED):
                hits.append(('secret_field', 0))
                continue
            hits += violations_in_json(v, forbid_terms, log, path + (name,))
    elif isinstance(doc, list):
        for v in doc:
            hits += violations_in_json(v, forbid_terms, log, path)
    elif isinstance(doc, str) and not allowed_digest(path, doc):
        hits += [(rule, 0) for rule, _ in violations_in_text(doc, forbid_terms, log, quoted=True)]
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
