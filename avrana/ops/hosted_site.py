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
- an unknown Host is answered 404 by a default server, never by the Party;
- the password gate (avrana/ops/hosted_gate.py; the owner's choice over Cloudflare Access, 2026-10-23): every
  server also listens on the gate port, where the tunnel connects. There a request without the gate cookie is
  sent to /__gate/ on the Party host, which the gate service answers. The VM-local port is not gated.

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
GATE_LISTEN = '127.0.0.1:8081'
GATE_SOCKET = '/run/avrana-gate/gate.sock'
GATE_MAPS = '/etc/avrana-party/gate*.map'      # a glob: with no password set it matches nothing and the gate stays shut
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


def _edge(block, listen, gate_listen, host, appliance_host, party_host):
    block = re.sub(r'^[ \t]*listen[^;]*;\n', '', block, flags=re.M)
    block = re.sub(r'^[ \t]*ssl_[a-z_]+[^;]*;\n', '', block, flags=re.M)
    block = _replace_once(block, f'    server_name {appliance_host};\n',
                          f'    listen {listen};\n    listen {gate_listen};\n    server_name {host};\n'
                          '    # The password gate: on the gate port (the tunnel\'s) no gate cookie means the password page.\n'
                          '    if ($avrana_gate_closed) {\n'
                          f'        return 302 https://{party_host}/__gate/;\n'
                          '    }\n', f'server {appliance_host}')
    return block


def _gate_location():
    return ('    # The password form and its check (avrana/ops/hosted_gate.py). Rate-limited for every client together:\n'
            '    # behind the tunnel every request comes from 127.0.0.1.\n'
            '    location ^~ /__gate/ {\n'
            '        limit_req zone=avrana_gate burst=10 nodelay;\n'
            '        client_max_body_size 4k;\n'
            f'        proxy_pass http://unix:{GATE_SOCKET};\n'
            '    }\n')


# Headers the access gateway adds or the harness sends (docs/design/HOSTED-STAGING.md §7): cleared at every proxy.
ACCESS_HEADERS = ('Cf-Access-Jwt-Assertion', 'Cf-Access-Authenticated-User-Email', 'Cf-Access-Client-Id',
                  'Cf-Access-Client-Secret')
LEGACY_GAMES = ('bluff', 'expo')


def render(source, party_host=PARTY_HOST, game_host=GAME_HOST, listen=LISTEN, legacy_lan_games=False,
           gate_listen=GATE_LISTEN):
    for name, value in (('party host', party_host), ('game host', game_host)):
        if not HOSTNAME.match(value):
            raise RenderError(f'{name} {value!r} is not a lowercase DNS name')
    if party_host == game_host:
        raise RenderError('the Party and the game origin must be different hosts (ADR 0013)')
    if not game_host.endswith('.' + party_host):
        raise RenderError('the game host must be a subdomain of the Party host: the gate cookie is set for the Party host')
    for value in (listen, gate_listen):
        if not LISTEN_RE.match(value):
            raise RenderError(f'listen {value!r}: the hosted edge listens on loopback only (127.0.0.1:<port>)')
    if listen == gate_listen:
        raise RenderError('the gate port and the VM-local port must differ')
    spans = server_blocks(source)
    if len(spans) != 3:
        raise RenderError(f'expected three server blocks (port 80, the Party, the game origin), found {len(spans)}')
    blocks = [source[a:b] for a, b in spans]
    if 'listen 80 default_server;' not in blocks[0]:
        raise RenderError('the first server block is not the port 80 default server')
    party, games = blocks[1], blocks[2]
    if f'server_name {APPLIANCE_PARTY_HOST};' not in party or f'server_name {APPLIANCE_GAME_HOST};' not in games:
        raise RenderError('the second and third server blocks are not the Party and the game origin')

    party = _edge(party, listen, gate_listen, party_host, APPLIANCE_PARTY_HOST, party_host)
    games = _edge(games, listen, gate_listen, game_host, APPLIANCE_GAME_HOST, party_host)
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
                 '    # ^~ wins over the native-game regex: a legacy game is refused, not a missing socket (502).\n'
                 + ''.join(f'    location ^~ /games/{g}/ {{\n        return 404;\n    }}\n' for g in LEGACY_GAMES)
                 + '    location / {\n        return 404;\n    }\n}')
    party = party.rstrip()
    party = party[:-1].rstrip('\n') + '\n\n' + _gate_location() + '}'

    out = []
    for block in (party, games):
        block = block.replace('$scheme', 'https')
        block = block.replace(APPLIANCE_GAME_HOST, game_host).replace(APPLIANCE_PARTY_HOST, party_host)
        block = re.sub(r'\n{3,}', '\n\n', block)
        # The access gateway's assertion and the harness's token stop at the edge: Party Core does not use
        # them, and a game server must not get a replayable sign-in or a tester's email.
        block = re.sub(r'^([ \t]*)(proxy_pass [^;]*;\n)',
                       lambda m: m.group(1) + m.group(2) + ''.join(
                           f'{m.group(1)}proxy_set_header {h} "";\n' for h in ACCESS_HEADERS),
                       block, flags=re.M)
        if re.search(r'\bssl\b|listen\s+(?:\[::\]:)?(?:80|443)\b', block):
            raise RenderError('a rendered server still names TLS or a public port')
        out.append(block)

    gate_port = gate_listen.rsplit(':', 1)[1]
    header = (
        '# GENERATED by `python3 -m avrana.ops.hosted_site` from avrana-party.nginx. Do not edit: change the\n'
        '# appliance site (or the renderer) and render again; tests/unit/test_hosted_site.py checks it.\n'
        '# Hosted staging (docs/design/HOSTED-STAGING.md): Cloudflare ends TLS and its tunnel connector reaches this\n'
        f'# site over plain HTTP on {gate_listen}, behind the password gate; {listen} is the VM-local, ungated port\n'
        '# (smoke, deploy checks). Nothing here listens on another address.\n'
        f'# LAN Games runtime routes (BLUFF/EXPO): {"included" if legacy_lan_games else "not rendered"}.\n\n'
        '# The password gate (avrana/ops/hosted_gate.py): the gate cookie must equal the token in gate.map, which\n'
        '# `hosted_gate set` writes. No password set: no map file, nothing matches, the gate stays shut.\n'
        'map $cookie_avrana_gate $avrana_gate_cookie {\n'
        '    default 0;\n'
        f'    include {GATE_MAPS};\n'
        '}\n'
        '# Open without the cookie: the form, and on the game origin each game\'s API, rules card and Colyseus\n'
        '# matchmaking (colyseus-tanks). Game clients fetch those with credentials \'omit\', so no cookie can ride\n'
        '# along; a game\'s API and matchmaking answer only a Party seat.\n'
        'map "$server_port:$avrana_gate_cookie:$host$uri" $avrana_gate_closed {\n'
        '    default 0;\n'
        f'    "~^{gate_port}:0:[^/]*/__gate/" 0;\n'
        f'    "~^{gate_port}:0:{re.escape(game_host)}/games/[a-z0-9][a-z0-9_-]*/(api/|onboarding\\.json$|matchmake/joinOrCreate/[a-z0-9_-]+$)" 0;\n'
        f'    "~^{gate_port}:0:" 1;\n'
        '}\n'
        'limit_req_zone $server_port zone=avrana_gate:1m rate=30r/m;\n\n'
        '# Any Host that is not the Party or the game origin: refused, never the Party.\n'
        'server {\n'
        f'    listen {listen} default_server;\n'
        f'    listen {gate_listen} default_server;\n'
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
    ap.add_argument('--gate-listen', default=GATE_LISTEN)
    ap.add_argument('--legacy-lan-games', action='store_true', help='also route BLUFF/EXPO to the LAN Games runtime')
    a = ap.parse_args(argv)
    try:
        text = render(Path(a.source).read_text(encoding='utf-8'), a.party_host, a.game_host, a.listen, a.legacy_lan_games,
                      a.gate_listen)
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
