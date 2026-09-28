# ADR 0006 — Party Core v0 and the party ↔ game session protocol v0

Status: **proposed** (implemented and tested on review branches `fix/party-core-v0` and
`fix/party-session-protocol-v0`; not deployed; no game implements the game side yet).
Date: 2026-09-27. Builds on ADR 0002 (party platform), ADR 0003 (ids and keys), ADR 0005 (LAN
provider launch) and `docs/findings/2026-09-27-party-bluff-boundary.md` (branch
`docs/party-bluff-seam`).

## Context

Nothing authoritative runs in production. "Players" are LAN Games connections holding a
browser-minted `wc-token`, which is at once device, person, seat key and reconnect credential
(ADR 0003). The first real party (Party Home → BLUFF → Party Home, four phones, offline) needs:
- one party that decides who is in;
- a way to admit exactly those people into a game;
- a way to learn, from the game server itself, that the game is over.

`experiment/party-service` proved most of the pieces, but it tied presence to Party Home's event
stream, so opening a game looked like leaving the party.

## Decision

### D1. Ownership

| Party (Avrana) owns | The game owns |
|---|---|
| device identity, membership, party-level names, presence | rules, turns, timers, teams, scores, results |
| host, succession, versioned host actions | seats and seat layout (it seats the roster its way) |
| game selection, launch, **who may enter** (roster, roles) | bots and autopilot |
| the session id and each member's participant id | in-game disconnect behaviour (grace, pause, abandon) |
| completion orchestration, end-for-everyone, return | private views and what each viewer sees |

Game concepts do not move into Party Core because BLUFF happens to use them.

### D2. Presence is liveness, and playing is not leaving

- **Membership** ends only on an explicit Leave.
- **Presence** is `here` while any authenticated party request arrived within 45 s: Party Home's
  long poll, a heartbeat from a game page, or a ticket fetch. Otherwise it is `away`.
- **Playing:** a member holding a place in the active session is `playing`. A host who is
  playing keeps the role (no succession mid-game). The party never runs its own copy of the
  game's disconnect timers.
- **Host:** host grace (30 s past the liveness window), then deterministic succession to the
  earliest-joined member who is here. It is vacant if nobody is here. A returning old host does
  not take the role back.

### D3. Device identity

- A server-issued 256-bit token, stored hash-only.
- Cookie `avrana_device; Path=/party/; HttpOnly; Secure; SameSite=Lax`, issued **only** by an
  explicit Join.
- Game pages' own requests (`/games/…`) never carry it. A game page may still call
  `/party/api/…`, which does.
- Forged or unknown values are never adopted.

### D4. One game session at a time

- States: `launching → active → ending → ended`. Outcomes: `completed`, `abandoned`,
  `ended_by_host`, `launch_failed`.
- At launch the party fixes the roster from members who are here: players up to the game's
  maximum, then spectators. Late members are admitted as spectators (v0).
- Each member gets a random **participant id** that exists only in that session and survives
  their reconnects. Games never see device ids or member ids.

### D5. The protocol is `avrana.party-session/v0`, a wire contract

**Envelope:**
- Format: `aps0.<b64url(canonical JSON)>.<b64url(HMAC-SHA256)>`.
- Every payload carries `v`, `typ`, `iss`, `aud`, `sid`, `iat` and `exp`.
- A token of one type is never accepted as another.

**Keys:**
- One random 32-byte key per game, provisioned by the appliance as a 0600 file.
- No PKI: one appliance, local services.

**Messages:**

| Message | Path | Carries | Checks |
|---|---|---|---|
| launch | party → game, `POST {game}/avrana/session/v0/launch` | `sid`, roster of exactly `{participant, name, role}` | 30 s expiry, nonce (replay refused) |
| ticket | party → browser → game | `sid`, `pid`, `role` | 120 s expiry; audience = game; must match the game's running session |
| end | party → game, `POST {game}/avrana/session/v0/end` | `sid` | the game returns to a non-running state; tickets for that session die |
| ended | game → party, `POST /internal/party-session/v0/ended` | `sid`, `completed` or `abandoned` | no results in v0 |

**Tickets:**
- Fetched with `POST /party/api/session/ticket`: cookie plus Origin check, `no-store`.
- Sent **only** as the first WebSocket message, `{"t":"hello","ticket":…}`. Never in a URL.

**Reconnect:** a new ticket for the same member and session carries the same participant id. The
game derives `game_token(key, sid, pid)`, a stable secret it may use where LAN Games used
`wc-token`. The game never needs the device identity.

**The "ended" report:**
- It is only accepted from the loopback address, with no proxy headers, and properly signed.
- The party checks it against the current session. A stale, replayed or unknown session is
  refused, so an old report can never end, or bring back, a newer session.
- **A browser cannot forge completion:** it has neither the key nor a route.

**The reference implementation:**
- `avrana/party/protocol.py` is stdlib-only with no `avrana` imports, so a game repository can
  vendor that one file. Its `GameSide` class is the whole game-side seam.
- The vectors in `contracts/vectors/party-session.v0.json` pin the format across repositories.

### D6. Three things that are not the protocol

- Party Core's Python API is internal and may change.
- LAN Games' `GameSession` class is one game-side implementation.
- A future native-game SDK (`.avrgame`) would **wrap** this protocol. Nothing of that SDK exists,
  and this ADR does not design it.

## Threat assumptions and residual risk

- **Trusted:** the appliance, its local services, and whoever holds `sudo`.
- **Not trusted:** every browser, including a phone's own page. Guests share the Party Wi-Fi.
- **Symmetric keys.** A game server can mint tickets for its own sessions, and can say "ended"
  for its own session only. Built-in LAN modules share one process, so their keys are per process
  in practice. That is acceptable only for trusted built-in code.
- **Stolen tickets.** A ticket copied off a phone within its 120 s lifetime could take that
  participant's place: it is a bearer credential, as `wc-token` is today but shorter-lived. v0
  does not bind tickets to a connection or make them single-use.
- **The party is memory-only.** A reboot or restart starts a new party; device identities
  survive. Reboot survival stays OPEN (`PARTY-LIFECYCLE.md`).
- **Not proven:** real phones, real nginx in front of `/party/api/`, and iOS sleep/wake timing.
  These are hardware checks (Tier 3).

## Consequences

- Next: the games server implements `GameSide`, for BLUFF first:
  - the two routes;
  - ticket admission at hello, with the browser-minted token path off for party sessions;
  - `ended` at completion and at abandonment;
  - a party heartbeat from integrated game pages, which is optional because a player in the
    game already counts as `playing`.
- Deployment needs an owner-approved `location /party/api/` on the 443 server (never
  `/internal/`), a systemd unit, and the key files.
- **Deferred:**
  - results, scores and the event sink;
  - single-use or connection-bound tickets;
  - party persistence;
  - votes, kicks and profiles;
  - more late-join policies than spectator;
  - automatic navigation (the fixed return to `/party/` stays);
  - PS1 and service runtimes;
  - `.avrgame` and the SDK.
