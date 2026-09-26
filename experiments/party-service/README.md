# Party service + dev front door — experiment (not production)

The smallest **real** version of ROADMAP F2a (one dev origin), F3 (server-issued device identity)
and F4 (a party service), built on the reference model in `../party-model/`. Stdlib Python only;
nothing here touches live nginx, production ports, or the live LAN Games service.

| Piece | File | What it proves |
|---|---|---|
| Device identity | `identity.py` | Tokens are server-issued (`token_urlsafe(32)`), stored only as SHA-256, sent only in an `HttpOnly; SameSite=Lax; Path=/party/` cookie named `avrana_dev_device` (dev name, so it can never overwrite a production cookie). Forged, malformed or revoked values get a **new** token, never the presented one. |
| Party service | `service.py` | One party per appliance; **Join (a POST) is the only way to become a presence** — viewing the page or opening the event stream never joins; reload/wake re-attaches the same presence; host + succession after grace; stale `if_version` refused; an ended party refuses host actions and the next Join starts a new party. The **rules are the model's** (`../party-model`, 53 tests): this layer adds cookies, transport, per-viewer views and a timer thread. |
| Dev front door | `front.py` | One origin for party + games: `/party/…` served here; everything else proxied to the games server (HTTP and WebSocket), **with the `Cookie` header stripped** so games never see device tokens (ADR 0003 §2.4). Host header allowlisted (DNS-rebinding guard); POSTs need an allowed `Origin` (CSRF). |
| Service games | `runtimes.py` | A game with `runtime.start: "service"` (PS1 titles) is **started by the party**: the host picks it, Party Home shows "Starting …" (+ host Cancel), seated phones move only once the process answers, the front door proxies exactly `/ps1/<title>/` and `/ps1/<title>/ws` to it (never `/stats`, never cookies), and End game / a switch / Cancel / party end stop it; a crash brings everyone home. One emulator at a time. Spawns and stops run on one long-lived thread per runtime (Linux `PR_SET_PDEATHSIG` fires when the *spawning thread* exits). |
| Seat tickets v1 (F5) | `seat_ticket.py` | Per-launch random key in the game's environment; a seated phone's own view carries `me.seat_ticket` (`v1.<slot>.<exp>.<game>.<hmac>`, 5 min); the game (PS1 party mode) gives exactly that slot. Spectators and observers get no ticket. |
| HUD chat prototype | `prototypes/hud-chat.html` | Frontend only, fake messages: how default Party chat could sit on a game (2–4 fading lines, tap for the feed, system lines distinct, a game override example). Design: `docs/design/COMMUNICATION.md` (branch `docs/party-platform`). |
| Party Home | `index.html` | The consumer path: name (remembered on the phone) → *Join the party* → players as avatars (host crowned, away dimmed, all with text) → the host picks a **game card** and presses one Start button; others see "Waiting for Ana to pick a game"; one screen each for starting (host can cancel), "<game> is on" (*Back to the game* / host *End the game for everyone*) and ended. Rename, handing over, ending the party, leaving and the activity log sit behind one disclosure; refusals are friendly sentences; no machinery words (tested). Dark by default, light on request; 44 px targets; reduced motion honoured. **Staying live:** the page owns its one event stream: any failure (including an HTTP error, which ends an EventSource for good) shows "Reconnecting…" and retries after 1, 2, 4, 8, then every 15 s; the party's `ping` (every 10 s) feeds a 25 s silence watchdog; coming back to the page replaces a stream whose ping is overdue (always after a bfcache return); after 15 s it says it can't reach the party and offers *Try again*. After Join it opens a fresh stream, which the party binds to the Join. |

## Run it

```bash
# laptop, party only (no games):
python experiments/party-service/front.py --port 8190
# → http://127.0.0.1:8190/party/

# on the Pi (dev only, in ~/avrana-lab, never the deploy checkout), in front of the BLUFF dev server:
python3 front.py --port 8190 --upstream 127.0.0.1:8196 --host 10.42.0.1:8190
# phones on the Avrana Party Wi-Fi: http://10.42.0.1:8190/party/  (games at http://10.42.0.1:8190/games/bluff/)

# with PS1 titles (Pi worktree ~/avrana-lab/party-svc; the PS1 code is the dev checkout's ps1/):
python3 front.py --port 8190 --host 10.42.0.1:8190 --ps1 /home/cody/avrana-lab/avrana-party-docs/ps1 --devices ""
```

Real-phone runbook: `docs/runbooks/ps1-bomberman-party-test.md` (branch `docs/party-platform`);
the arcade should be stopped for it (CPU).

With `--upstream`, the game catalog is **derived from the games server's own `/api/games`**
(manifest v0, `../manifests/`), so the host can start exactly the games that server serves
(BLUFF, WORD RUSH, …); it retries in the background while the games server is still starting.
Without an upstream a two-entry demo catalog is used. **Verified on the Pi 2026-09-24** in front of the
BLUFF dev server (`playtest-readiness`): 30 games derived, HTTP and a WebSocket join through the
front door, Host allowlist 421, Join over HTTP, and neither the token nor the cookie reached the
games server's log.

Device hashes persist in `dev-data/devices.json` (0600, git-ignored) so phones keep their identity
across restarts; the **party itself is memory-only** (whether a party survives a reboot is OPEN).
Reset one phone: its "forget me" POST (`/party/dev/forget-me`) or clear site data. Reset all:
`--reset-devices`. `--dev-commands` enables `/party/dev/reset-party` for automated tests — never
use it for a playtest (any guest could end the party).

## Tests

```bash
python experiments/party-service/test_party_service.py        # 33 tests, ~20 s, binds 127.0.0.1 only (run on the Pi too)
PW_FROM=<main checkout> node experiments/party-service/e2e-ps1-party.mjs http://10.0.0.142:8190   # the PS1 slice on the Pi
npx playwright test -c experiments/party-service/playwright.config.ts   # 11 tests × Chromium (Pixel 7) + WebKit (iPhone 13), ~45 s each
```

With a different pre-installed Chromium (Claude Code Cloud: `/opt/pw-browsers`), set
`PW_CHROMIUM_EXECUTABLE` to it and add `--project=chromium`.

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

`reconnect.spec.ts` covers staying live. Its scripted tests run the real page with a stand-in
EventSource (browser semantics: an HTTP error leaves it CLOSED) and Playwright's clock:
- normal connect;
- a server error → "Reconnecting…" → the exact backoff → live again;
- waking (visible, online, bfcache) replaces a dead stream but not a fresh one;
- the silence watchdog and the open timeout;
- never more than one stream through a pile-up of reconnects;
- the stalled message with *Try again*.

Its real tests use the front door and the browser's own EventSource:
- a stream that ends, then two 502s, recovers by itself (the previous page stayed on
  "Reconnecting…");
- a joined player on a quiet stream stays live, here and host for 27 s on two streams (this
  proves the ping reaches the page and the Join is bound).

The server test checks that the ping is a dispatchable event, not a comment. Each fix was checked
to fail its tests without it.

**Not proven here:** a real phone locking, sleeping and waking on the Party Wi-Fi (visibility and
bfcache are simulated events), Wi-Fi roaming, and nginx in front of the service. Those need a
phone and the Pi.

## Not done (deliberately)

The LAN Games fork bridge (F5 for BLUFF and friends: they still use their own `wc-token` identity; seat tickets exist for PS1 only), single-use tickets, profiles and
PINs, persistence of the party, TV/screen presences in the UI, votes, chat, teams, the live nginx
layout (F2b), and any production deployment. Proxy limits: HTTP/1.0 framing to the client (the
connection closes after each response), whole-request upload bodies (≤ 16 MB), no gzip rewriting.
