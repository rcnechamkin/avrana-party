"""Local cross-repository harness. Real donor routes/sockets, simulated arcade.
Never a deployment server; binds loopback and needs an explicit games checkout.

--party-session also runs Party Core v0 and the session protocol in-process behind
/party/api/ (tests/provider/party_harness.py, AVR-23). --bind adds one more listening
address for a supervised real-phone check on a lab port (docs/runbooks/bluff-party-reconnect.md);
the launch route still needs loopback, so 127.0.0.1 is always bound too.

--game-origin (with --party-session) serves the Party and the games under two host names of one
site, as ADR 0013 deploys them: http://party.avrana.test:<port> is the Party (shell, /party/api/,
the bridge frame) and http://games.avrana.test:<port> is the game origin, which answers nothing
under /party/. The games server is told the Party's origin (AVRANA_PARTY_ORIGIN) and Party Core
registers the game origin (game_origins). The browser maps *.avrana.test to loopback
(playwright.provider.config.ts). Plain HTTP: no `__Host-` cookie and no HTTPS here.
"""
import argparse
from pathlib import Path
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--games', required=True)
parser.add_argument('--port', type=int, default=8182)
parser.add_argument('--party-session', action='store_true')
parser.add_argument('--bind', default='127.0.0.1')
parser.add_argument('--game-origin', action='store_true')
args = parser.parse_args()
PARTY_HOST, GAMES_HOST = f'party.avrana.test:{args.port}', f'games.avrana.test:{args.port}'
if args.game_origin:
    import os
    os.environ['AVRANA_PARTY_ORIGIN'] = f'http://{PARTY_HOST}'       # what the games server tells its pages
platform = Path(__file__).resolve().parents[2]
games = Path(args.games).resolve()
sys.path.insert(0, str(games))
sys.path.insert(1, str(platform))
if args.party_session:
    import party_harness
    party_key, party_port = party_harness.prepare_keys()   # before the donor reads its env
import asyncio
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
import server as donor
import uvicorn
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from avrana.web.devserver import SHELL_HEADERS
from ops.export_avrana_catalog import export
import json

# Fail before starting if the checked-out donor and committed snapshot disagree.
pinned = json.loads((platform / 'contracts/catalogs/lan-games.json').read_text(encoding='utf-8'))
if export(pinned['source']['commit']) != pinned:
    raise SystemExit('cross-repository metadata drift; review and synchronize the export')

@donor.app.get('/party/api/origin.json')
async def origin():
    return JSONResponse({'schema': 'avrana.origin/v0', 'scheme': 'http', 'serverAddr': '127.0.0.1', 'tls': ''})

@donor.app.get('/arcade/stats')
async def arcade():
    return JSONResponse({'players': 0, 'max_players': 4, 'emulator_running': True})

@donor.app.middleware('http')
async def shell_headers(request, call_next):
    path = request.url.path
    if args.game_origin and request.headers.get('host') == GAMES_HOST and path.startswith('/party'):
        return JSONResponse({'error': 'not_found'}, status_code=404)   # the game origin serves no Party
    response = await call_next(request)
    if path.startswith('/party/'):
        response.headers.update(SHELL_HEADERS)
        if args.game_origin and path == '/party/bridge.html':
            # the one Party page a game origin may frame (nginx sends this on the appliance)
            response.headers['Content-Security-Policy'] = SHELL_HEADERS['Content-Security-Policy'].replace(
                "frame-ancestors 'none'", f'frame-ancestors http://{GAMES_HOST}')
    return response

if args.party_session:
    public = {args.bind} - {'127.0.0.1'}
    if args.game_origin:
        party_harness.attach(donor.app, party_key, args.port, public | {'party.avrana.test'}, party_port,
                             game_origins={f'http://{GAMES_HOST}': '*'})
    else:
        party_harness.attach(donor.app, party_key, args.port, public, party_port)

donor.app.mount('/party', StaticFiles(directory=platform / 'web/party', html=True))
if args.bind == '127.0.0.1':
    uvicorn.run(donor.app, host='127.0.0.1', port=args.port, log_level='warning')
else:
    import socket
    listeners = []
    for host in ('127.0.0.1', args.bind):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, args.port))
        listeners.append(sock)
    uvicorn.Server(uvicorn.Config(donor.app, log_level='warning')).run(sockets=listeners)
