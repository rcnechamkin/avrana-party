# Party service + dev front door — experiment (not production)

The smallest **real** version of ROADMAP F2a (one dev origin), F3 (server-issued device identity)
and F4 (a party service), built on the reference model in `../party-model/`. Stdlib Python only;
nothing here touches live nginx, production ports, or the live LAN Games service.

| Piece | File | What it proves |
|---|---|---|
| Device identity | `identity.py` | Tokens are server-issued (`token_urlsafe(32)`), stored only as SHA-256, sent only in an `HttpOnly; SameSite=Lax; Path=/party/` cookie named `avrana_dev_device` (dev name, so it can never overwrite a production cookie). Forged, malformed or revoked values get a **new** token, never the presented one. |
| Party service | `service.py` | One party per appliance; **Join (a POST) is the only way to become a presence** — viewing the page or opening the event stream never joins; reload/wake re-attaches the same presence; host + succession after grace; stale `if_version` refused; an ended party refuses host actions and the next Join starts a new party. The **rules are the model's** (`../party-model`, 53 tests): this layer adds cookies, transport, per-viewer views and a timer thread. |
| Dev front door | `front.py` | One origin for party + games: `/party/…` served here; everything else proxied to the games server (HTTP and WebSocket), **with the `Cookie` header stripped** so games never see device tokens (ADR 0003 §2.4). Host header allowlisted (DNS-rebinding guard); POSTs need an allowed `Origin` (CSRF). |
| Party Home | `index.html` | Join, people list with live updates (Server-Sent Events), rename, leave; host tools (start a game for everyone, end game, hand over, end party); synchronized navigation — seated players follow a new transition once, anyone who came back on purpose gets a banner + Go. Also the first accessible reference component (see `docs/design/ACCESSIBILITY.md` on `docs/party-platform`). |

## Run it

```bash
# laptop, party only (no games):
python experiments/party-service/front.py --port 8190
# → http://127.0.0.1:8190/party/

# on the Pi (dev only, in ~/avrana-lab, never the deploy checkout), in front of the BLUFF dev server:
python3 front.py --port 8190 --upstream 127.0.0.1:8196 --host 10.42.0.1:8190
# phones on the Avrana Party Wi-Fi: http://10.42.0.1:8190/party/  (games at http://10.42.0.1:8190/games/bluff/)
```

With `--upstream`, the game catalog is **derived from the games server's own `/api/games`**
(manifest v0, `../manifests/`), so the host can start exactly the games that server serves
(BLUFF, WORD RUSH, …). Without an upstream a two-entry demo catalog is used.

Device hashes persist in `dev-data/devices.json` (0600, git-ignored) so phones keep their identity
across restarts; the **party itself is memory-only** (whether a party survives a reboot is OPEN).
Reset one phone: its "forget me" POST (`/party/dev/forget-me`) or clear site data. Reset all:
`--reset-devices`. `--dev-commands` enables `/party/dev/reset-party` for automated tests — never
use it for a playtest (any guest could end the party).

## Tests

```bash
python experiments/party-service/test_party_service.py        # 22 tests, ~13 s, binds 127.0.0.1 only
npx playwright test -c experiments/party-service/playwright.config.ts   # 2 tests × Chromium (Pixel 7) + WebKit (iPhone 13)
```

From a worktree without `node_modules`, use the main checkout's:
`NODE_PATH=<repo>/node_modules <repo>/node_modules/.bin/playwright test -c …`.

Unit tests cover identity (entropy, hash-only storage, forged/revoked tokens, cookie attributes),
security boundaries (Host allowlist, Origin on POST, negative Content-Length, no token or device id
in any body), presence vs page load, succession after grace, an unclaimed Join timing out, stream
close/reopen keeping the presence, party end, idle end, leave/rejoin, dev commands off by default,
cookie stripping on proxied game paths, the WebSocket tunnel, and a regression test (mutation-checked)
that a timer change applied while describing the state still wakes every other stream. The browser
tests drive two phones through the real page (join, live update, host-only tools, follow into a
game, banner-not-yank on return, leave) and an accessibility smoke check (names, labels, ≥ 44 px
targets, no sideways scroll at 375 px, `lang`).

## Not done (deliberately)

Seat tickets and the fork bridge (F5: games still use their own `wc-token` identity), profiles and
PINs, persistence of the party, TV/screen presences in the UI, votes, chat, teams, the live nginx
layout (F2b), and any production deployment. Proxy limits: HTTP/1.0 framing to the client (the
connection closes after each response), whole-request upload bodies (≤ 16 MB), no gzip rewriting.
