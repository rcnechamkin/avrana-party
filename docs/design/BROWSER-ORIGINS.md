# Party and game browser origins: mechanisms (proposal for AVR-226)

Status: **PROPOSED (2026-10-03). Design only; nothing here is built or deployed.** The direction is
accepted in [ADR 0013](../adr/0013-party-and-game-browser-origins.md); this document proposes the
mechanisms that ADR leaves "deliberately open" and lists the decisions the owner must make. Until
those are recorded in ADR 0013, nothing below is authoritative. Linear: AVR-226. Related:
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
  `party.avrana.net`. Its `Path=/party/` keeps it from game *servers* on the same host.
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

Step 5 has one known risk to prove early. [I] Safari's tracking prevention treats frames by
registrable domain, so a `party.avrana.net` frame inside a `games.avrana.net` page should count
as first-party. That is unverified on a real iPhone, and the whole seam depends on it.

## 5. Decisions required

| # | Decision | Recommendation |
|---|---|---|
| D1 | One shared game origin, or one per game | one shared now; bridge keyed by origin so per-game is a config change |
| D2 | Transport for tickets, presence and host controls | the bridge frame with the closed verb set in §3.2 |
| D3 | Rename the cookie to `__Host-avrana_device` with `Path=/` | yes, with one release of dual read |
| D4 | The game host name | `games.avrana.net` (a sibling; a name nested under `party.` gains nothing) |
| D5 | Order relative to Checkers (AVR-238) | before it, so the first clean native game is born on the game origin |

## 6. Not proposed

A CSP `sandbox` tier (later, for community games); iframes for the games themselves; any change to
tickets, keys or the session protocol; a per-game service worker policy.
