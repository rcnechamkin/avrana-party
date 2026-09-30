"""Party Core v0 + the session protocol (ADR 0006) inside the provider harness (AVR-23).

Test only, never a deployment server. `server.py --party-session` calls prepare_keys() before it
imports the games server (which reads $AVRANA_PARTY_KEYS and $AVRANA_PARTY_URL at import: both or
neither) and attach() after, so one origin serves everything a phone touches, the way nginx will
on the appliance:

    /party/api/...        -> a real avrana.party.service on 127.0.0.1:<ephemeral>, proxied with
                             the browser's Host, Origin and Cookie plus X-Forwarded-For
    /games/bluff/...      -> the real games server (its launch and end routes are reached over
                             loopback, unproxied, exactly like HttpGameLink on the Pi; it reports
                             `ended` straight to the party service's loopback port)
    /party/               -> the real shell (server.py's static mount)

Harness-only routes (loopback callers only):
    POST /__harness__/party/reset[?pregame=1]   a fresh party; ?pregame=1: BLUFF runs the Party's
                                     pregame, as in production (AVR-129) (tests are independent; the games server's room
                                     is replaced by the next launch anyway)
    GET  /__harness__/party-lab      a bare Join / Launch / Open page (the protocol checks predate
                                     Party Home's own Join and host start, AVR-127)

The key lives in a temporary directory that is deleted at exit; it is never printed.
"""
import atexit
import http.client
import os
import shutil
import socket
import tempfile
import threading
import time

import anyio
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from avrana.party import core, identity, protocol, service, sessions

GAME = 'bluff'
SECOND = 'chess'
MAX_PLAYERS = 6
LOOPBACK = ('127.0.0.1', '::1')
FORWARD = ('host', 'cookie', 'origin', 'content-type', 'content-length')
RETURN = ('content-type', 'cache-control', 'set-cookie', 'x-content-type-options')


def prepare_keys():
    """Create a throwaway key for BLUFF, reserve the party service's loopback port and point the
    games server at both (as deploy/avrana-party-session.conf does on the appliance). Returns
    (key, party_port)."""
    keys = tempfile.mkdtemp(prefix='avrana-party-keys-')
    atexit.register(shutil.rmtree, keys, True)
    key = protocol.new_key()
    protocol.write_key(os.path.join(keys, f'{GAME}.key'), key)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        party_port = probe.getsockname()[1]
    os.environ['AVRANA_PARTY_KEYS'] = keys
    os.environ['AVRANA_PARTY_URL'] = f'http://127.0.0.1:{party_port}'
    return key, party_port


def attach(app, key, port, public_hosts, party_port):
    """Run the party service beside `app` and route /party/api/ to it. `public_hosts` are the
    host names phones use for this origin (127.0.0.1 always included)."""
    hosts = {f'{h}:{port}' for h in {'127.0.0.1', *public_hosts}}
    # A second party game with no game side attached here: it proves Party Home takes its party
    # games from Party Core (nothing is BLUFF-specific), and its start fails readably.
    games = service.load_games({GAME: {'max_players': MAX_PLAYERS}, SECOND: {'max_players': 2}})
    # AVR-129: BLUFF as production configures it: the Party's pregame (Play or Watch, host start)
    pregame = service.load_games({GAME: {'max_players': MAX_PLAYERS, 'min_players': 2, 'pregame': True},
                                  SECOND: {'max_players': 2}})
    endpoints = {GAME: sessions.GameEndpoint(GAME, f'http://127.0.0.1:{port}/games/{GAME}', key)}
    svc = service.PartyService(identity.DeviceStore(None), games, sessions.HttpGameLink(endpoints))
    cfg = service.Config(hosts, {f'http://{h}' for h in hosts}, secure_cookie=False)
    extra, internal = sessions.routes(svc, endpoints)
    party = service.make_server(svc, cfg, host='127.0.0.1', port=party_port, extra_routes=extra,
                                internal_routes=internal)
    stop = threading.Event()
    threading.Thread(target=party.serve_forever, daemon=True).start()
    threading.Thread(target=svc.run_timer, args=(stop,), daemon=True).start()
    atexit.register(stop.set)
    # long polls hold a thread for up to 25 s: give them their own pool, not the app's shared one
    threads = anyio.CapacityLimiter(64)

    def forward(method, target, headers, body, client):
        conn = http.client.HTTPConnection('127.0.0.1', party_port, timeout=35)
        h = {k: v for k, v in headers.items() if k in FORWARD}
        h['X-Forwarded-For'] = h['X-Real-IP'] = client     # what nginx adds on the appliance
        try:
            conn.request(method, target, body=body or None, headers=h)
            r = conn.getresponse()
            data = r.read()
            out = [(k, v) for k, v in r.getheaders() if k.lower() in RETURN]
            return r.status, out, data
        finally:
            conn.close()

    async def party_api(request: Request):
        body = await request.body()
        target = request.url.path + (f'?{request.url.query}' if request.url.query else '')
        client = request.client.host if request.client else ''
        status, headers, data = await anyio.to_thread.run_sync(
            forward, request.method, target, dict(request.headers), body, client, limiter=threads)
        response = Response(data, status_code=status)
        for k, v in headers:
            response.headers.append(k, v)
        return response

    def loopback(request):
        return request.client is not None and request.client.host in LOOPBACK

    async def reset(request: Request):
        if not loopback(request):
            return JSONResponse({'error': 'not_found'}, status_code=404)
        chosen = pregame if request.query_params.get('pregame') == '1' else games
        with svc.lock:
            svc.core = core.PartyCore(time.monotonic, chosen)
            svc._notify()
        return JSONResponse({'ok': True})

    async def lab(request: Request):
        return HTMLResponse(LAB_PAGE, headers={'Cache-Control': 'no-store'})

    app.add_api_route('/party/api/{rest:path}', party_api, methods=['GET', 'POST'],
                      include_in_schema=False)
    app.add_api_route('/__harness__/party/reset', reset, methods=['POST'], include_in_schema=False)
    app.add_api_route('/__harness__/party-lab', lab, methods=['GET'], include_in_schema=False)
    return svc


LAB_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Party lab</title>
<style>
  body { font: 18px/1.4 system-ui, sans-serif; margin: 16px; max-width: 32rem; }
  button, input, a.button { font: inherit; padding: .6rem 1rem; margin: .25rem 0; }
  a.button { display: inline-block; border: 1px solid; text-decoration: none; }
  pre { white-space: pre-wrap; background: #eee; padding: .5rem; }
</style></head>
<body>
<h1>Party lab (test harness)</h1>
<p>Not the Party app: a bare page for the session protocol check.</p>
<p><input id="name" placeholder="Your name" maxlength="16" autocomplete="off">
   <button id="join">Join</button></p>
<p><button id="launch">Launch BLUFF (host)</button> <button id="end">End game (host)</button></p>
<p><a class="button" href="/games/bluff/?avrana=1">Open BLUFF</a></p>
<pre id="out">Loading...</pre>
<script>
"use strict";
let view = null, acted = 0;
const out = document.getElementById("out");
async function call(path, body) {
  const res = await fetch("/party/api/" + path, body === undefined ? { cache: "no-store" } : {
    method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) out.textContent = res.status + " " + (data.message || data.error || "");
  return res.ok ? data : null;
}
function show(v) {
  if (!v) return;
  view = v;
  const s = v.session;
  out.textContent = [
    "me: " + (v.me ? v.me.name + (v.me.host ? " (host)" : "") : "not joined"),
    "members: " + v.members.map((m) => m.name + " [" + m.presence + "]").join(", "),
    "game: " + (s ? s.game + " " + s.state + (s.outcome ? " " + s.outcome : "") +
                (s.my_role ? ", you are a " + s.my_role : "") +
                (s.detail ? " (" + s.detail + ")" : "") : "none"),
  ].join("\\n");
}
async function act(path, body) {
  acted++;                  // a poll sent before or during this (e.g. before the cookie) is stale
  const v = await call(path, body);
  acted++;
  show(v);
}
document.getElementById("join").onclick = () =>
  act("join", { name: document.getElementById("name").value });
document.getElementById("launch").onclick = () =>
  act("session/launch", { game: "bluff", if_version: view && view.version });
document.getElementById("end").onclick = () =>
  act("session/end", { if_version: view && view.version });
(async function poll() {
  for (;;) {
    const seen = acted;
    const q = view ? "?since=" + view.version + "&wait=20" : "";
    const v = await call("state" + q).catch(() => null);
    if (v && seen === acted) show(v);
    else if (!v) await new Promise((r) => setTimeout(r, 2000));
  }
})();
</script>
</body></html>
"""
