"""Local cross-repository harness. Real donor routes/sockets, simulated arcade.
Never a deployment server; binds loopback and needs an explicit games checkout.

--party-session also runs Party Core v0 and the session protocol in-process behind
/party/api/ (tests/provider/party_harness.py, AVR-23). --bind adds one more listening
address for a supervised real-phone check on a lab port (docs/runbooks/bluff-party-reconnect.md);
the launch route still needs loopback, so 127.0.0.1 is always bound too.
"""
import argparse
from pathlib import Path
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--games', required=True)
parser.add_argument('--port', type=int, default=8182)
parser.add_argument('--party-session', action='store_true')
parser.add_argument('--bind', default='127.0.0.1')
args = parser.parse_args()
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
    return JSONResponse({'players': 0, 'max_players': 2, 'emulator_running': True})

@donor.app.middleware('http')
async def shell_headers(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith('/party/'):
        response.headers.update(SHELL_HEADERS)
    return response

if args.party_session:
    public = {args.bind} - {'127.0.0.1'}
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
