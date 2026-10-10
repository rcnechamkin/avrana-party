# Party and game browser origins: mechanisms (AVR-226)

Status: **ACCEPTED mechanisms (owner, 2026-10-03). Steps 1 to 3 of §4 are in source; nothing is deployed.** The direction is
accepted in [ADR 0013](../adr/0013-party-and-game-browser-origins.md), whose amendment of
2026-10-03 records the owner's decisions D1 to D5 (§5). The text below is the design as proposed
and accepted; "As built" notes say where step 1 differs. Linear: AVR-226. Related:
[ADR 0006](../adr/0006-party-session-protocol.md), [ADR 0011](../adr/0011-party-console-model.md),
[ADR 0014](../adr/0014-native-games-isolated-lan-games-retired.md), [LIMITED-MODE](LIMITED-MODE.md),
[GAME-INSTALLATION](GAME-INSTALLATION.md).

Tags: **[E]** read in source or config on `main` at `b4c470d` and Games `main` at `f8f9148`;
**[I]** inference; **[R]** recommendation.

## 1. What is true today

- [E] One origin, `https://party.avrana.net`, serves Party Home, every game page and the arcade
  page (`avrana-party.nginx`).
- [E] Game pages run Party code in their own page: Games `avrana-integration.js` and
  `arcade/index.html` do `import('/party/lib/party-follow.js')`. That module long-polls
  `/party/api/state` with the member's cookie, publishes `window.AvranaParty`, and performs the
  host verbs (`end`, `goHome`, `playAgain`).
- [E] Game pages fetch their own tickets: `POST /party/api/session/ticket` with
  `credentials: 'same-origin'` (Games `hubnet.js`, `arcade/index.html`). Since PR #42 tickets are
  single-use, so every reconnect needs a new one.
- [E] Party Core checks `Origin` against an allow-list on every POST and checks `Host` on every
  request. GET `/party/api/state` has no Origin check and touches the caller's presence.
- [E] The cookie has no `Domain` attribute, so it is host-only: it is sent only to
  `party.avrana.net`. `__Host-avrana_device` is `Path=/`, so the path does not keep it from game
  *servers* on the same host: nginx clearing the `Cookie` header does (section 3.3, AVR-314).
- [E] The certificate names one host. `ops/renew-party-certificate.sh` passes one `--domains`.
- [E] The strict Content-Security-Policy applies to `/party/` only, and includes
  `frame-ancestors 'none'`.

## 2. Three browser facts that shape the design

1. **A sibling host name is still the same *site*.** `games.avrana.net` and `party.avrana.net`
   share the registrable domain `avrana.net`. `SameSite=Lax` restricts *cross-site* requests
   only. So a script on the game origin that calls `fetch('https://party.avrana.net/party/api/…',
   {credentials: 'include'})` **does** make the browser attach `avrana_device`. What stops it is
   not the cookie but two other controls: Party Core's `Origin` allow-list (for POST) and the
   absence of CORS headers (the game cannot read a response). [I] The separate host name is a
   real boundary only because those two controls exist. They become load-bearing and need tests.
2. **A sibling host can plant cookies for its parent or its siblings.** A page on
   `games.avrana.net` may set `avrana_device=…; Domain=avrana.net`. The browser then sends *two*
   cookies named `avrana_device` to `party.avrana.net`. Until PR #49 (refuse a request that
   carries two device cookies) Party Core took the first. The same trick works today from any game page with a more specific
   `Path`. [R] Two defences, both cheap: refuse a request that carries the name twice (PR #49), and rename the cookie to `__Host-avrana_device`, which browsers refuse to accept
   with a `Domain` attribute or from a non-secure origin. The `__Host-` prefix requires `Path=/`,
   which is safe once game servers no longer share the host.
3. **Storage, service workers and `localStorage` are per origin.** [I] The game origin starts
   empty: no `wc-name`, no avatar, no Party profile. That is the intent. Display names already
   reach a game through the launch roster, not through shared storage.

## 3. Proposal

### 3.1 Host names

[R] One game host name beside the Party one, both served by the appliance and both on one
certificate:

| Origin | Serves | Holds |
|---|---|---|
| `https://party.avrana.net` | Party Home, setup, diagnostics, `/party/api/`, the bridge page | `__Host-avrana_device` |
| `https://games.avrana.net` | every game page, game assets, game WebSockets, the arcade page | nothing durable; tickets in memory |

Needs: a second `--domains` on the certificate (DNS-01, same account), a second `host-record` in
dnsmasq, a second nginx `server` block. All three are owner-approved live changes.

One shared game origin isolates games from the Party but not from each other. One host per game
(`bluff.games.avrana.net`) isolates them from each other too, at the price of a wildcard
certificate and a wildcard DNS answer. [R] Start with one shared game origin for first-party
games, and build the bridge (§3.2) so that it keys on the calling origin. Per-game hosts are then a
configuration change when the community tier arrives. **Decision D1.**

### 3.2 The seam: a Party-owned bridge frame

ADR 0013 decision 3 lists three candidate transports. This proposes the `postMessage` bridge,
because it is the only one that also solves ticket refresh and presence.

- The game page embeds one invisible frame: `https://party.avrana.net/party/bridge.html`. The
  frame is Party code on the Party origin. The browser sends it the device cookie, because the
  frame is same-site.
- The frame runs what `party-follow.js` runs today: the long poll, presence, and the "where is
  the party" decision. Presence therefore continues while a game is open, and it is the Party's
  own code that keeps it, not the game's.
- The frame talks to its parent only by `postMessage`, and only to a parent whose origin is the
  registered origin of the game the Party is currently running. Any other parent gets silence.
- The game page loads a small shim from **its own** origin (vendored into Games, like
  `party_protocol.py`) that wraps the messages as today's `window.AvranaParty`.

The verb set, complete:

| Verb | Direction | Who may | What it can affect |
|---|---|---|---|
| `ticket` | game → bridge → game | any member in the running session | returns a ticket for this game and this session only |
| `view` | bridge → game | pushed | host name, whether I am host, location, round state. No member ids, no device ids |
| `navigate` | bridge → game | pushed | "the party is elsewhere, go to this Party URL" (a fixed Party-origin URL, never one the game supplies) |
| `end`, `home`, `playAgain` | game → bridge | the host only, checked by Party Core as now | the session this game is running |

[I] What a hostile game can do with that: end or leave its own round, and ask for tickets to
itself. It can already do both without the bridge, by reporting `ended` from its server. It cannot
launch another game, transfer the host, rename a member, read the roster beyond what its launch
message already carried, or reach a future admin surface.

Party Core changes: the ticket route requires the `game` the bridge passes, derived from the
parent's origin, instead of trusting a page to name its own game. `frame-ancestors` on
`bridge.html` lists the game origins instead of `'none'`. Nothing in the session protocol changes.

**As built (step 1).** The contract is `avrana.party-bridge/v1`
(`contracts/vectors/party-bridge.v1.json`). A game page says `hello {game}` once; the frame binds
to that origin and game if Party Core's `game_origins` registers the origin for the game
(`GET /party/api/bridge`), and is silent otherwise. The bridge sends the ticket route
`{game, origin}`, where `origin` is what the browser reported for the page; Party Core refuses an
origin not registered for that game (`bad_game_origin`). `view` carries no id of any kind.
`navigate` carries the word `party`, never a URL; the shim goes to the Party origin it was
configured with. One control was added beyond the proposal: Party Core refuses every API
request that a browser marks `Sec-Fetch-Site: same-site` or `cross-site`, so a game page's own
requests are refused even for `GET`, which the `Origin` allow-list does not cover.

Alternatives considered:

- **A visible Party-owned overlay for host controls.** Keeps host verbs out of game script
  entirely, but breaks ADR 0011 §5 (host controls live in the game's own chrome) and still needs a
  second mechanism for tickets.
- **Ticket-authorised endpoints.** The game calls the Party with a ticket instead of a cookie.
  Makes the single-use, 120-second ticket a long-lived session credential in all but name, and the
  game still needs a first ticket from somewhere.
- **Passing the ticket in the URL fragment at launch.** Violates "tickets never appear in a URL"
  and does nothing for reconnects.

**Decision D2.**

### 3.3 The cookie

[R] `__Host-avrana_device; Path=/; Secure; HttpOnly; SameSite=Lax`, issued alongside the old name
for one release so that phones in the room keep their member, then the old name is no longer
read. **Decision D3.**

Who keeps this cookie from game *servers* (AVR-314; the cookie no longer has the party path,
so path scoping does not):

- **Before the game origin is deployed:** nginx. Each game-server location of the site file on
  the Party host (BLUFF and EXPO, the native-game rule, the LAN Games catch-all, on HTTPS and on
  the port 80 block) sets `proxy_set_header Cookie "";`, so a game process receives no `Cookie`
  header at all. This is in the repository's site file; it holds on the Pi only after the owner
  deploys it. `/arcade/` (both blocks) is cleared too since AVR-318: the arcade process reads no
  cookie, in HTTP or in the socket handshake (its seat is a ticket in the `hello` message), so
  it receives no device cookie, like the game servers, and needs nothing from the browser's cookie jar.
- **After the game origin is deployed:** the separate origin. A browser never sends a
  `__Host-` cookie of the Party host to the game host, so game requests carry none. The nginx
  rule stays as a second layer on the Party host.

### 3.4 Returning to the Party

[R] A return is a top-level navigation to a fixed Party URL. The game never supplies it. The
bridge's `navigate` message carries one of a closed set (`/party/`), as LAN-GAMES-PROVIDER already
requires for same-origin returns.

### 3.5 Limited Mode

Over plain HTTP on an IP literal there is no second host name. See
[LIMITED-MODE](LIMITED-MODE.md) §3.8: first-party games stay same-origin there, and an untrusted
tier is unavailable.

## 4. Order of work once decided

1. Party: `bridge.html`, the shim's message contract with vectors, Origin-keyed ticket route, the
   `__Host-` cookie with dual read. All testable in Tier 1 and 2 with a simulated second host. No
   deployment effect while nginx still serves one origin.
2. Games (paired PR): vendor the shim, switch `hubnet.js` and BLUFF's host chrome to it, keep
   same-origin behaviour as a fallback while the second host does not exist.
3. Arcade page: same shim.
4. Certificate SAN, dnsmasq record, nginx server block. Owner-approved live change.
5. Tier 3 on real phones: the cookie is not attached to game-origin requests; the bridge frame is
   not blocked by Safari; reconnect fetches a fresh ticket; the host's End works from BLUFF.

Step 1 is done in source (AVR-226): Tier 1 tests for the bridge, the shim and Party Core, and a
Tier 2 run in Chromium with two host names of one site (`tests/offline/bridge.spec.ts`).

**As built (steps 2 and 3).** Nothing changes on the appliance until step 4: every page decides
from its own server's configuration, and that configuration is unset.

- *How a page knows where the Party is.* Its own server tells it, and nothing else can: the games
  server answers `GET /api/avrana` with `partyOrigin`, and the arcade's `stats` carries
  `party_origin`, both from `AVRANA_PARTY_ORIGIN` (an origin and nothing else, or it is ignored;
  documented and unset in both drop-ins). Unset, or equal to the page's own origin, the page keeps
  the same-origin path it has today (the Party's module in the page, the ticket fetched with the
  cookie). Set to another origin, the page uses the bridge and never calls the Party API. The
  origin is never read from the address, a link or a message. Only an answer decides: a server
  that says nothing (a timeout, an error, a 5xx) has not said "same origin", so the page asks
  again, each request bounded, until it is told. A games server from before the route (404) is an
  answer: same origin.
- *Games.* `web/avrana-party-bridge.js` is the shim, vendored unchanged and pinned by digest in
  both contract declarations (`bridge`), with the vectors. `avrana-integration.js` publishes the
  same `window.AvranaParty` a same-origin page has (BLUFF's host chrome and every other game's
  fallback End are unchanged code) and `AvranaIntegration.party`; `hubnet.js` takes its ticket
  from the bridge before every connect and reads the session id from the ticket it was handed,
  since a view carries no id.
- *Arcade.* `arcade/index.html` does the same with the shim served by the arcade itself
  (`/arcade/party-bridge.js`, and `keep-awake.js`, since a page cannot import across origins).
- *The shim* now holds a request made before the frame has loaded and sends it after `hello`
  (a game client connects as soon as it runs).
- *Proof.* Tier 1 in both repositories; Tier 2 in Chromium with two host names of one site: the
  real BLUFF page and games server against the real Party Core (`tests/provider/game-origin.spec.ts`:
  seats by ticket, reload and reconnect keep the seat, only the host ends, a stranger gets no
  seat, the page holds no cookie and sends the Party API nothing), and the real arcade page
  (`tests/offline/bridge.spec.ts`). Not shown: Safari, HTTPS, the `__Host-` cookie, nginx.

What step 4 must set together, or not at all: the certificate name, the dnsmasq record, the
`games.avrana.net` server block (with `frame-ancestors https://games.avrana.net` on
`/party/bridge.html` only), `game_origins` in Party Core's configuration, and
`AVRANA_PARTY_ORIGIN=https://party.avrana.net` in the games and arcade drop-ins.

### What step 5 must validate on a real iPhone (owner)

The question is not whether a `party.avrana.net` frame inside a `games.avrana.net` page is
first-party or same-site: WebKit documents host names under one registrable domain as the same
site. The real-phone test validates this implementation. It is the owner's, it needs step 4
first, and **the bridge is not relied on for field testing until it has passed**. Nothing below
has been run on a phone.

On an iPhone (Safari) and an Android phone (Chrome), joined to the Party Wi-Fi, with a round on:

1. **The frame loads.** The game page shows no error; Web Inspector shows `bridge.html` loaded
   from `party.avrana.net` with status 200 and no `frame-ancestors` refusal.
2. **The Party cookie reaches the frame.** The game page's host controls appear for the host and
   not for a guest; a guest's phone shows as present in Party Home on another phone.
3. **`postMessage` works both ways.** The game connects (it got a ticket); after a reload it
   connects again (a fresh ticket).
4. **The game origin holds nothing.** In Web Inspector, `games.avrana.net` has no cookie and no
   Party entries in local storage.
5. **The sandbox does not break the frame.** With `sandbox="allow-scripts allow-same-origin"` the
   frame still polls (presence stays "here" for several minutes with the game open).
6. **Navigation.** The host's End takes every phone to Party Home; a host switch to another game
   takes every phone there by way of Party Home, with no stuck page.
7. **Sleep and wake.** Lock the phone for a minute during a round and unlock: the page is where
   the party is, and the game reconnects.
8. **Private browsing, and "Prevent Cross-Site Tracking" on (the default).** Repeat 1 to 3.
9. **The old cookie.** A phone that joined before the change keeps its member after it (one
   release of dual read), and afterwards holds `__Host-avrana_device`.
10. **Direct calls fail.** From the game page's console, `fetch('https://party.avrana.net/party/api/state', {credentials: 'include'})` is refused.

Record the phone models, OS versions and the result of each line in a dated finding.

## 5. Decisions (accepted by the owner, 2026-10-03)

| # | Decision | Accepted |
|---|---|---|
| D1 | One shared game origin, or one per game | one shared now; bridge keyed by origin so per-game is a config change |
| D2 | Transport for tickets, presence and host controls | the bridge frame with the closed verb set in §3.2 |
| D3 | Rename the cookie to `__Host-avrana_device` with `Path=/` | yes, with one release of dual read |
| D4 | The game host name | `games.avrana.net` (a sibling; a name nested under `party.` gains nothing) |
| D5 | Order relative to Checkers (AVR-238) | before it, so the first clean native game is born on the game origin |

## 6. Not proposed

A CSP `sandbox` tier (later, for community games); iframes for the games themselves; any change to
tickets, keys or the session protocol; a per-game service worker policy.
