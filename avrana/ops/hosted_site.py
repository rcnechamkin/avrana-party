"""The hosted staging nginx site, rendered from the appliance's (docs/design/HOSTED-STAGING.md).

    python3 -m avrana.ops.hosted_site            # rewrite deploy/hosted/avrana-party.hosted.nginx
    python3 -m avrana.ops.hosted_site --check    # exit 1 when the committed file is not what this renders

Hosted staging is the same Party behind a different edge: an access gateway ends TLS and reaches nginx
over plain HTTP on loopback through an outbound tunnel. The hosted site is therefore not a second,
hand-kept configuration but a rendering of `avrana-party.nginx`, so every Party and game-origin rule
(headers, CSP, cookie stripping, the native-game socket rules, the catalog, package art when it is
there) is the appliance's own, byte for byte. Only the edge changes:

- the port 80 server (captive probes, plain-HTTP clients, the LAN Games hub) is not rendered;
- each HTTPS server listens on the loopback edge without TLS: no certificate lines;
- server names: party.avrana.net -> the Party host, games.avrana.net -> the game host, everywhere
  (frame-ancestors included);
- `X-Forwarded-Proto` is always https (the browser's scheme; `$scheme` would say http behind the tunnel,
  and a game that builds its CSP from it would allow ws: instead of wss:);
- origin.json says "network": "hosted" and carries no address (`$server_addr` would be the VM's);
- what does not exist hosted is left out of the Party server: /arcade/ (hardware), and, unless
  --legacy-lan-games, the LAN Games runtime routes (BLUFF/EXPO and the root proxy to 127.0.0.1:8096),
  whose root location becomes a 404 like the game origin's;
- an unknown Host is answered 404 by a default server, never by the Party.

Each rule is a text transformation that must match exactly what it expects; a source that no longer
has a shape this module relies on is refused (RenderError), never rendered approximately.
"""
import argparse
from pathlib import Path
import re
import sys

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / 'avrana-party.nginx'
OUT = REPO / 'deploy' / 'hosted' / 'avrana-party.hosted.nginx'
APPLIANCE_PARTY_HOST = 'party.avrana.net'
APPLIANCE_GAME_HOST = 'games.avrana.net'
PARTY_HOST = 'avrana.party'
GAME_HOST = 'games.avrana.party'
LISTEN = '127.0.0.1:8080'
HOSTNAME = re.compile(r'^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$')
LISTEN_RE = re.compile(r'^127\.0\.0\.1:\d{1,5}$')
ORIGIN_JSON = ("""return 200 '{"schema":"avrana.origin/v0","network":"hosted","scheme":"https",""" +
               """"serverAddr":"hosted","tls":"edge","http":"$server_protocol"}';""")
LEGACY_LOCATIONS = ('~ "^/games/(bluff|expo)(/(?!avrana/)|$)"', '/')
HARDWARE_LOCATIONS = ('/arcade/',)


class RenderError(ValueError):
    pass


def server_blocks(text):
    """[(start, end)] of the top-level `server { ... }` blocks, by brace matching (a quoted regular
    expression's braces are balanced, as in the Game Contract id pattern)."""
    spans, depth, start = [], 0, None
    for m in re.finditer(r'server\s*\{|\{|\}', text):
        tok = m.group(0)
        if tok.startswith('server') and depth == 0:
            start, depth = m.start(), 1
        elif tok == '{' and start is not None:
            depth += 1
        elif tok == '}' and start is not None:
            depth -= 1
            if depth == 0:
                spans.append((start, m.end()))
                start = None
    return spans


def _leading_comment(text, start):
    """Where the comment lines directly above `start` (the block's own explanation) begin."""
    lines = text[:start].split('\n')
    i = len(lines) - 1                          # the partial line the block starts on
    while i > 0 and lines[i - 1].lstrip().startswith('#'):
        i -= 1
    return len('\n'.join(lines[:i])) + (1 if i else 0)


def _location_span(block, name):
    """(start, end) of `location <name> { ... }` in a server block, with the comment lines above it."""
    m = re.search(r'^[ \t]*location\s+' + re.escape(name) + r'\s*\{', block, re.M)
    if not m:
        raise RenderError(f'the source has no location {name}')
    depth, i = 1, m.end()
    while depth:
        if i >= len(block):
            raise RenderError(f'location {name} is not closed')
        depth += {'{': 1, '}': -1}.get(block[i], 0)
        i += 1
    if block[i:i + 1] == '\n':
        i += 1
    return _leading_comment(block, m.start()), i


def _drop_location(block, name):
    a, b = _location_span(block, name)
    return block[:a] + block[b:]


def _replace_once(block, old, new, what):
    if block.count(old) != 1:
        raise RenderError(f'{what}: expected exactly one {old!r}, found {block.count(old)}')
    return block.replace(old, new)


def _edge(block, listen, host, appliance_host):
    block = re.sub(r'^[ \t]*listen[^;]*;\n', '', block, flags=re.M)
    block = re.sub(r'^[ \t]*ssl_[a-z_]+[^;]*;\n', '', block, flags=re.M)
    block = _replace_once(block, f'    server_name {appliance_host};\n',
                          f'    listen {listen};\n    server_name {host};\n', f'server {appliance_host}')
    return block


def render(source, party_host=PARTY_HOST, game_host=GAME_HOST, listen=LISTEN, legacy_lan_games=False):
    for name, value in (('party host', party_host), ('game host', game_host)):
        if not HOSTNAME.match(value):
            raise RenderError(f'{name} {value!r} is not a lowercase DNS name')
    if party_host == game_host:
        raise RenderError('the Party and the game origin must be different hosts (ADR 0013)')
    if not LISTEN_RE.match(listen):
        raise RenderError(f'listen {listen!r}: the hosted edge listens on loopback only (127.0.0.1:<port>)')
    spans = server_blocks(source)
    if len(spans) != 3:
        raise RenderError(f'expected three server blocks (port 80, the Party, the game origin), found {len(spans)}')
    blocks = [source[a:b] for a, b in spans]
    if 'listen 80 default_server;' not in blocks[0]:
        raise RenderError('the first server block is not the port 80 default server')
    party, games = blocks[1], blocks[2]
    if f'server_name {APPLIANCE_PARTY_HOST};' not in party or f'server_name {APPLIANCE_GAME_HOST};' not in games:
        raise RenderError('the second and third server blocks are not the Party and the game origin')

    party = _edge(party, listen, party_host, APPLIANCE_PARTY_HOST)
    games = _edge(games, listen, game_host, APPLIANCE_GAME_HOST)
    origin = re.search(r"return 200 '\{\"schema\":\"avrana\.origin/v0\"[^\n]*';", party)
    if not origin:
        raise RenderError('the Party server has no origin.json answer')
    party = party.replace(origin.group(0), ORIGIN_JSON)
    for name in HARDWARE_LOCATIONS:
        party = _drop_location(party, name)
    if not legacy_lan_games:
        for name in LEGACY_LOCATIONS:
            party = _drop_location(party, name)
        party = party.rstrip()
        if not party.endswith('}'):
            raise RenderError('the Party server does not end with its closing brace')
        party = (party[:-1].rstrip('\n') + '\n\n    # Hosted: no LAN Games runtime and no static root; anything not routed above is 404.\n'
                 '    location / {\n        return 404;\n    }\n}')

    out = []
    for block in (party, games):
        block = block.replace('$scheme', 'https')
        block = block.replace(APPLIANCE_GAME_HOST, game_host).replace(APPLIANCE_PARTY_HOST, party_host)
        block = re.sub(r'\n{3,}', '\n\n', block)
        if re.search(r'\bssl\b|listen\s+(?:\[::\]:)?(?:80|443)\b', block):
            raise RenderError('a rendered server still names TLS or a public port')
        out.append(block)

    header = (
        '# GENERATED by `python3 -m avrana.ops.hosted_site` from avrana-party.nginx. Do not edit: change the\n'
        '# appliance site (or the renderer) and render again; tests/unit/test_hosted_site.py checks it.\n'
        '# Hosted staging (docs/design/HOSTED-STAGING.md): the access gateway ends TLS and its tunnel connector\n'
        f'# reaches this site over plain HTTP on {listen}. Nothing here listens on another address.\n'
        f'# LAN Games runtime routes (BLUFF/EXPO): {"included" if legacy_lan_games else "not rendered"}.\n\n'
        '# Any Host that is not the Party or the game origin: refused, never the Party.\n'
        'server {\n'
        f'    listen {listen} default_server;\n'
        '    server_name _;\n'
        '    location / {\n'
        '        return 404;\n'
        '    }\n'
        '}\n\n')
    return header + '\n\n'.join(out) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--check', action='store_true', help='exit 1 if the committed file differs from a fresh render')
    ap.add_argument('--source', default=str(SOURCE))
    ap.add_argument('--out', default=str(OUT))
    ap.add_argument('--party-host', default=PARTY_HOST)
    ap.add_argument('--game-host', default=GAME_HOST)
    ap.add_argument('--listen', default=LISTEN)
    ap.add_argument('--legacy-lan-games', action='store_true', help='also route BLUFF/EXPO to the LAN Games runtime')
    a = ap.parse_args(argv)
    try:
        text = render(Path(a.source).read_text(encoding='utf-8'), a.party_host, a.game_host, a.listen, a.legacy_lan_games)
    except RenderError as e:
        print(f'hosted_site: {e}', file=sys.stderr)
        return 2
    out = Path(a.out)
    if a.check:
        if not out.exists() or out.read_text(encoding='utf-8') != text:
            print(f'hosted_site: {out} is not what avrana-party.nginx renders; run python3 -m avrana.ops.hosted_site', file=sys.stderr)
            return 1
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
