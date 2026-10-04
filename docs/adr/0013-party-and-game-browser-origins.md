# ADR 0013 — Party shell and game clients have separate browser trust origins

Status: **accepted (direction, and mechanisms D1–D5 on 2026-10-03) · step 1 in source · not deployed** · Date: 2026-10-02
Amends the one-origin implementation assumption of [ADR 0002](0002-party-platform.md) and
[ADR 0004](0004-full-mode-contracts-and-providers.md) D1 (see §Affected prior assumptions).
Design and rollout belong to
[AVR-226](https://linear.app/avranakern/issue/AVR-226/decide-trusted-party-shell-versus-game-page-browser-origin-boundary);
Linear owns sequencing. Nothing in this ADR is deployed: today every Party, game and arcade page is
served from `https://party.avrana.net` ([SYSTEM](../SYSTEM.md)).
Context: [ADR 0003](0003-ids-and-keys.md), [ADR 0006](0006-party-session-protocol.md),
[GAME-INSTALLATION](../design/GAME-INSTALLATION.md) ("Browser side — the real risk"),
[PARTY-PLATFORM](../design/PARTY-PLATFORM.md) §13, [ADR 0014](0014-native-games-isolated-lan-games-retired.md).

## Context

ADR 0002 proposed "a separate small party service on the same origin as everything else" and ADR
0004 D1 made that origin `https://party.avrana.net`, with Party pages under `/party/` and the
games and arcade under other paths of the same host. Path-scoped, `HttpOnly` cookies keep the
device token away from game *servers* (nginx strips it) and from `document.cookie`, but not from
game *JavaScript*: any script on the origin can `fetch('/party/api/…', {credentials: 'include'})`
and the browser attaches the cookie. ADR 0003 §Consequences and PARTY-PLATFORM §13 recorded that
limit and deferred it to "sandboxed third-party games (later)".

The 2026-10-02 review treated that deferral as the wrong default. Game code is already a third
party in practice: the Games repository has independent CI and release cadence, BLUFF ships with
~30 donor titles of varying provenance, and Checkers and Spades will be written as independent
platform consumers (ADR 0014). A game page that can act as the viewer against host or (later)
admin APIs makes every game bug a Party bug.

## Decision

1. **Origin is part of the trust boundary.** The browser's same-origin policy is the isolation
   mechanism Avrana relies on between the Party shell and game clients. Two trust domains:

   | | **Trusted Party origin** | **Game origin(s)** |
   |---|---|---|
   | Serves | Party Home, setup scene, profile and system surfaces, diagnostics, `/party/api/` | game pages, game assets, game WebSockets |
   | Holds | device identity (`avrana_device`), Party membership and presence, host and platform controls | only game/session-scoped authority: Party-issued participant/session tickets (ADR 0006) and the game's own derived `game_token` |
   | May call | Party API as the member | its own game server; a narrow, explicitly designed Party surface for games (below), never member/host/admin APIs as the viewer |

2. **Game JavaScript gains no Party authority by being played.** A game page cannot present the
   member's device cookie, cannot call host verbs, cannot read Party state beyond what the Party
   deliberately publishes to games, and cannot reach a future web admin. The only authority a
   game origin holds is what a Party-issued ticket carries for one participant in one session.
3. **The Party talks to games through designed seams, not shared cookies.** Host controls during
   a round (ADR 0011 §5: End, Play again, Party Home) and presence heartbeats from game pages (ADR
   0006 D2) today rely on same-origin `fetch`. Under this decision they move to one of: a Party-
   owned frame or overlay served from the Party origin; a `postMessage` bridge exposing an
   explicit, host-verified verb set; or ticket-scoped endpoints that authorize by ticket, not by
   cookie. AVR-226 chooses; the invariant is that the game origin never holds the member cookie.
4. **Near-term mechanism: separate hostnames on the appliance.** The preferred first step is a
   second hostname (for example a `games.`-style name) under the existing certificate and Party
   DNS model, so cookies, storage, service workers and `Origin` checks separate by construction.
   Alternatives (a separate port, `Content-Security-Policy: sandbox`) remain available where a
   hostname is impractical, with the caveats GAME-INSTALLATION already records: a port is not a
   cookie boundary; a sandbox gives a `null` origin and second-class browser features.
5. **Community sandboxing is a later strengthening, not this decision.** Untrusted community games
   may need the stronger tier (CSP sandbox, platform frame, no `localStorage`) that GAME-
   INSTALLATION sketches. This ADR establishes the Party/game split for *all* games, trusted ones
   included; it does not freeze the community sandbox.
6. **Cross-origin identity recovery stays forbidden.** A player on the game origin is identified
   to the game by ticket and `game_token`, never by reading Party storage. The Party never infers
   identity from the game origin's storage either (PARTY-PLATFORM §4 already says so for scheme and
   hostname variants).

## Affected prior assumptions

- **ADR 0002**, "Original proposed mechanisms": "a separate small party service on the same origin
  as everything else". The *service* placement stands; the assumption that games share that
  browser origin does not. ADR 0002 "Consequences": "A single origin requires an nginx change" is
  historical; the dated amendment in ADR 0002 points here.
- **ADR 0004 D1**: "integrated games and arcade share that origin" (as PARTY-PLATFORM §4 restates
  it). The canonical *Party* origin stands; games move off it.
- **ADR 0006 D3**: "A game page may still call `/party/api/…`, which does [carry the cookie]".
  That remains true of the deployed v0 and becomes the thing this ADR removes.
- **ADR 0011 §5**: `window.AvranaParty` host controls inside game chrome are implemented by
  same-origin calls today; the *product* decision (host controls live in the game's chrome, one
  location, the game owns the viewport) is unchanged; the transport changes under decision 3.
- **PARTY-PLATFORM §4** "One canonical origin. Everything a player uses is served from one origin":
  superseded as stated; see that document's reconciled text.
- **GAME-INSTALLATION** "The single origin still holds identity; untrusted pages hold none":
  generalized from untrusted pages to all game pages.
- **LAN-GAMES-PROVIDER** "Return is fixed `/party/` on the same origin": return targets become
  cross-origin navigations to the Party origin; still no arbitrary return URL.

## Consequences

- Party DNS, the certificate's name set and nginx server blocks change when AVR-226 lands: an
  owner-approved live change, not implied by this ADR. The committed nginx files must stay
  byte-identical (AGENTS).
- The arcade phone page, the Games integration script (`avrana-integration.js`, `party-follow.js`)
  and BLUFF's host chrome are the three current consumers of same-origin Party calls; each needs a
  designed replacement before cutover. Standalone LAN Games play is not a constraint (ADR 0014).
- Tier 2 tests gain a second hostname in the simulated Party; Tier 3 proves real-phone cookie and
  storage separation.
- Browser-level second-class effects (fullscreen, audio unlock, `localStorage`) that ADR 0002
  listed against iframes apply only if the frame or sandbox options are chosen, not to the
  hostname option.

## Deliberately open

A mechanism proposal for every item below, with the decisions it needs, is in
[BROWSER-ORIGINS](../design/BROWSER-ORIGINS.md) (2026-10-03, proposed, not accepted).

The game hostname(s) and whether each game gets its own; the exact host-control and heartbeat
transport; how Limited Mode (ADR 0012) names and reaches the two origins over plain HTTP; the
community sandbox tier.

## Amendment (2026-10-03): mechanisms decided (AVR-226)

The owner accepted the five recommendations of [BROWSER-ORIGINS](../design/BROWSER-ORIGINS.md) §5.
They settle what "Deliberately open" above left open; nothing above is otherwise changed.

| # | Decision |
|---|---|
| D1 | One shared game origin now. The bridge is keyed by origin, so one origin per game later is configuration, not redesign. |
| D2 | A Party-owned, invisible bridge frame is the only seam between a game page and the Party, with the closed verb set `ticket`, `view`, `navigate`, `end`, `home`, `playAgain` (`avrana.party-bridge/v1`). |
| D3 | The device cookie becomes `__Host-avrana_device` with `Path=/`. For one release the earlier `avrana_device` cookie is still read, and a phone that presents only it is handed the new one. |
| D4 | The game host name is `games.avrana.net`. |
| D5 | This work precedes Checkers (AVR-238). |

What is in source after step 1 (Party only; no deployment effect while nginx serves one origin):
`web/party/bridge.html` and `lib/bridge.js`; the reference shim `web/party/bridge/shim.js` for
game repositories to vendor; the contract's vectors (`contracts/vectors/party-bridge.v1.json`);
Party Core's `game_origins` configuration, `GET /party/api/bridge`, the origin-checked ticket
route, the `__Host-` cookie with dual read, and a refusal of any Party API request a browser
marks as coming from another origin (`Sec-Fetch-Site`).

Still to do, in order: the paired Games change (vendor the shim); the arcade page; then the
owner-only live changes (certificate name, dnsmasq record, nginx server block and the
`frame-ancestors` header for `bridge.html`) and the real-phone validation in BROWSER-ORIGINS §4.
The bridge is not relied on for field testing until that validation has passed.
