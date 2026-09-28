# Party Core → BLUFF boundary, and where `.avrgame` attaches later (2026-09-27)

Status: **PROPOSED** (architecture survey; read-mostly; nothing built or deployed). This proposes the
smallest boundary for the next vertical slice. It is not a decision: the slice's PR (or an ADR
beside it) decides. Sources: `main` @ `a2a5682`; games fork `main` @ `3a6c472`; branch
`experiment/party-service` @ `eb3844f`; read-only reads on the Pi.

The question: what must the production Party Core → BLUFF slice fix now, so that a future
`.avrgame` + public SDK can attach later without building that platform today?

Short answer: **fix a small wire protocol, not a Python API.** The protocol has four messages:
launch, a ticket in the WebSocket hello, a server-to-server "ended" report, and "end for
everyone". Everything else stays where it is.

## 1. Evidence classes (don't collapse them)

| Thing | Class | Evidence |
|---|---|---|
| Live games runtime = upstream BEACNpool LAN-Games `5da1764` (retired upstream), port 8096; **no BLUFF**, no `avranaIntegration` in `/api/games` | **Production** | Pi, 2026-09-27 |
| `/party/` shell (catalog, profile adapter over `wc-*`, library over `lg-*`, one Party Chat) | **Production** at `459d4cd` (PR #5) | Pi release dir + `version.json` |
| LAN provider catalog + direct `?avrana=1` launch + fixed `/party/` return (platform PR #7, games PR #1) | **Implemented, not deployed** | `main` `a2a5682`; fork `3a6c472` |
| BLUFF (rules, private views, presence grace, pause/abandon, spectators, leak and hostile-client tests) | **Implemented, not deployed** | fork `games/bluff/`, `tests/*bluff*` |
| Party service: server-issued device cookie, Join-only presence, host + succession, `if_version`, PS1 launch, seat tickets v1, Party Home reconnect | **Experimental** | `experiment/party-service` (tests pass there; PS1 E2E on the Pi 2026-09-24) |
| Party lifecycle rules (R1–R6, timers, awkward states) | **Test-model-only** | `experiments/party-model/` (52–53 tests, 300-seed fuzz) |
| Game integration (ticket single-use, event sink, `party.js` follow client), native-game primitives | **Design-only** | `docs/design/GAME-INTEGRATION.md`, `NATIVE-GAMES.md`, `PARTY-LIFECYCLE.md` |
| `.avrgame`, SDK, AvrGameProvider | **Proposed** (this file) | — |

**Nothing Party-authoritative runs in production.** "Players" there are LAN-Games connections
holding a client-minted `wc-token`.

## 2. What BLUFF actually owns today (fork `main`)

- **Identity:** `core/net.py` accepts any well-formed token from the client's `hello`
  (`hubnet.js` keeps it in `localStorage["wc-token"]`, minting one if missing). The same token keys
  seats, avatar uploads (`x-wc-token`) and chat. It is a client-forgeable bearer credential, and
  the game sees it. One device can fill all 6 lobby seats with invented tokens (BLUFF README).
- **Membership/seats:** `GameSession` locks `participants` at the 3-2-1 countdown from connected,
  ready tokens. BLUFF seats up to 6 and fills the rest with bots.
- **Start:** hostless. Any ready player presses start. There is no host concept in any LAN game.
- **Presence and reconnect:** per token. here → reconnecting → away after 30 s (prompts) or 60 s
  (own turn), then a passive autopilot. The table pauses when every seated human is gone, can be
  taken over after 60 s, and is abandoned after 5 min. The same token resumes the same seat.
- **Private views:** `game_state(viewer)` on the server. `None` = spectator/TV (public). A
  differential leak test and a frame whitelist prove it.
- **Actions:** game protocol over `/games/bluff/ws`; each prompt has a `step` so stale answers are
  rejected.
- **Completion:** `end_game()` → shared `game_end` (20 s) → `to_lobby()`. The winner lives only in
  `g["winner"]`. **Nothing leaves the process**: no result or completion event exists.
- **Storage:** process memory only; one table per server; a restart loses it.

## 3. Cross-game evidence (Checkers, Spades, Buzzboard)

We promote something only when structurally different games agree:

| Finding | Evidence | Consequence |
|---|---|---|
| Every LAN game shares one lifecycle envelope: lobby → countdown (participants locked) → game phases → `game_end` → lobby | `core/session.py`; Spades, `DuelSession` (Checkers), Buzzboard, BLUFF | A **completion signal** hooked at `end_game` / abandon-to-lobby in `core/` covers all 30 titles. Generalize it. |
| Results differ in shape: BLUFF winner token; Spades `winner_team`; Checkers colour/draw; Buzzboard scores | each `g["result"]` | **Don't standardize results or scores yet.** `ended{reason}` only. |
| Disconnect policy differs: Spades autopilots at once; Duel autopilots; BLUFF waits 30/60 s and pauses when empty; Buzzboard has its own rules | `game_player_left/back` in each | The platform **reports** presence; the game **decides** what happens. Keep BLUFF's timers in BLUFF. |
| Viewer kinds are seat / spectator / public, and a TV is just a public watcher | `state_for(token or None)`; Buzzboard `tv.js` connects with `watch:true` | A viewer-role concept (player / spectator) is sound. No TV concept is needed for BLUFF. |
| Seat layouts are game-specific: 2 + bench, 4 in teams, 6 + bots, everyone | Duel, Spades, BLUFF, Buzzboard | **Party admits a roster; the game seats it.** Bots never enter the Party roster. |
| In-game start is always "a ready player starts" | all | Party Host = select, launch, end for everyone. **The in-game start moment stays in the game.** |

## 4. Ownership seam

Classes: **MUST** = stabilize for Party→BLUFF now · **SHOULD** = let it shape the boundary, don't
build more than needed · **DEFER** = safe to ignore now · **BLOCKED** = needs evidence or an owner
call.

| Concept | Today | Owner (recommended) | Class |
|---|---|---|---|
| Device identity | client `wc-token` (prod); HttpOnly device cookie (exp.) | Avrana | **MUST**: the game never sees it |
| Party membership | none in prod; Join-only presence (exp.) | Avrana | **MUST** |
| Player identity (name, avatar) | shared `wc-*` keys via the `/party/` adapter (prod) | Avrana; passed to the game as display data | SHOULD (reuse existing keys, ADR 0005) |
| Presence (party-level) | exp. service | Avrana | **MUST** (Party Home needs it) |
| Presence (in-game, socket-level) | BLUFF | game | DEFER any change |
| Seats | game locks participants at countdown | Party admits the roster; game seats it | **MUST**: only admitted participants may play |
| Host authority | none (hostless games) | Avrana: select, launch, end for everyone | **MUST** (launch/end only) |
| Spectators | game watch sockets | Party decides player vs spectator at launch; the game renders | SHOULD |
| Reconnect | same token → same seat (BLUFF) | Party re-issues a ticket for the **same** participant | **MUST** |
| Game selection | `/party/` catalog (prod) | Avrana | **MUST** (exists) |
| Game launch | direct URL (not deployed) | Avrana creates the session | **MUST** |
| Game start (the 3-2-1) | game | game | DEFER |
| Game completion | stays in process | game reports `ended{reason}` to Avrana | **MUST** |
| Runtime termination | n/a for an in-process module | Avrana ends the session; the game resets its room | **MUST** (end for everyone) |
| Return to Party Home | fixed `/party/` link (not deployed) | Avrana; the game offers the link on its end screen | **MUST** (manual return); auto-follow SHOULD |
| Private views | game, server-side | game | DEFER (already right) |
| Actions/messages | game protocol | game; Avrana only defines the first message | **MUST** (hello only) |
| Persistent game storage | none | game-owned; platform boundary later | DEFER |
| Capability negotiation | `contracts/capabilities.v0.json` + evaluator (prod shell) | Avrana | DEFER (BLUFF needs nothing new) |
| Results, stats, achievements, event sink | none | Avrana sink, game claims | DEFER |
| Party survives reboot | undecided (A/B/C, `PARTY-LIFECYCLE.md`) | Avrana | BLOCKED (owner call; ephemeral is fine for the slice) |
| Per-game chat, votes, teams | — | — | DEFER |

## 5. The minimum Party → BLUFF interface (proposed)

It is a versioned **wire contract**, so a later SDK can wrap it in any language. It is not a new
capability name (those come only from `contracts/capabilities.v0.json`).

1. **Launch (Party, host action).** Party creates a session:
   `{session_id, game_id:"bluff", roster:[{participant_id, display_name, avatar, role}]}`.
   `participant_id` is opaque and per session, never a device id. The Party updates its own state
   (`launching → in_game`); BLUFF is always on, so it is ready at once.
2. **Ticket in the hello.** The player's page reads its ticket from the Party (a `/party/…` API;
   same origin, so the device cookie goes to the Party only). It sends
   `{"t":"hello", "ticket": …}` as the first WebSocket message, never in a URL. The ticket is
   **MAC-signed** (a keyed hash both sides can check) with a per-game key. It carries the audience
   `bluff`, `session_id`, `participant_id`, the role and an expiry: the PS1 `seat_ticket` v1 shape
   plus the session id. BLUFF verifies it and derives the game token from `(session, participant)`,
   so the rules code keeps working on "a token". For party sessions, **the client-token path is
   off**: an unticketed socket is a watcher.
3. **Reconnect.** A slept or reloaded phone gets a fresh ticket for the same participant, hence the
   same derived token. BLUFF's existing same-token resume then works unchanged, and its grace
   timers stay its own.
4. **Ended (game → Party, server-to-server).** At `end_game` or abandon, the games server sends
   `{session_id, reason: completed|abandoned}`, signed with the same key, over loopback. **Never via
   the browser** (spoofable). The Party marks a crash itself (`crashed`) when the runtime
   disappears. No winner or score in v0.
5. **End for everyone (Party → game).** A signed call to the game, which moves the room back to its
   lobby and treats that session's tickets as dead.
6. **Return.** The end screen's fixed **Back to Party** (from PR #7) takes phones to Party Home,
   which shows the session as over. The follow client (automatic navigation) is SHOULD, not MUST.

Honest limit (unchanged from `GAME-INTEGRATION.md` §3.1): LAN modules share one process, so the key
is per process there. That is acceptable only for trusted built-in code.

Implementation home (for the slice, not now): the ticket check and the ended/end hooks belong in
the fork's `core/net.py` / `core/session.py`, enabled per game (BLUFF first), with `hubnet.js`
sending the ticket in integrated mode. That makes the lift to other titles a flag, not a rewrite.

## 6. Where `.avrgame` attaches later (sketch only)

| Seam | Today's anchor | Later |
|---|---|---|
| Package boundary | `games/<slug>/` (server + `web/`) + `contracts/games/<id>.json` | one package directory/archive holding the same three parts; the format is deferred |
| Stable identity | Game Contract `id` (+ `lan-<slug>` aliases, ADR 0003/0005) | the same id space, plus a publisher namespace the appliance grants |
| Manifest | Game Contract v0: describes and requests, never grants | Game Contract vN; grants stay in the appliance profile |
| Lifecycle contract | §5 (this file) | the SDK wraps §5; the in-process `GameSession` becomes one binding of it, not *the* SDK |
| SDK/API compatibility | `avrana.game/v0`, `avrana.lan-launch/v1` version-gating | a session-protocol version declared by the package and checked at install/launch |
| Browser client | every presentation is `browser_native` for players | a hard package rule: players need only a browser |
| Capabilities / permissions | `capabilities.v0.json`; `runtime.permissions` requested; the appliance grants | unchanged model |
| Validation / compliance | `avrana/contracts/game.py`; BLUFF's leak test, frame whitelist, hostile client, lifecycle probe | a compliance suite grown from BLUFF's tests, run against any package |
| Runtime isolation | `lan_games_module` (in-process, trusted only) | `process` runtime over a unix socket with per-game keys; the sandbox is deferred |
| Discovery | contracts + appliance grants → compiled catalog | an AvrGameProvider feeding the same catalog |
| Legacy coexistence | LanGamesProvider (`lan-catalog/v1`, `lan-launch/v1`) | stays, as a sibling provider speaking the same §5 protocol |

Emulation stays outside `.avrgame` (a separate provider and runtime).

## 7. Risks that could make a public SDK hard

1. **Declaring `GameSession` "the SDK".** It is Python, in-process and trusted-only. Define the
   boundary as §5's protocol; keep `GameSession` as one implementation of it.
2. **Enshrining `wc-token` as the game identity.** It is client-minted and game-visible. Party
   sessions must use derived, per-session participant tokens.
3. **Completion via the browser** (e.g. `/party/?result=…`). Spoofable; §5.4 is server-to-server.
4. **Deploy ordering.** `main`'s `/party/` (PR #7) disables LAN launches ("Games update needed")
   unless the games runtime advertises `avrana.lan-launch/v1`. Production's runtime does not.
   Deploy the fork runtime first or together (ADR 0005 already says so).
5. **Two lobbies** (Party Home, then BLUFF's ready/countdown). Acceptable for the slice. Whether
   party sessions auto-start is a later UX call; don't hard-code either answer into the protocol.
6. **Stale rooms.** BLUFF has one room per server. A new `session_id` must reset a leftover room,
   and tickets for an old session must fail.
7. **Promoting BLUFF's timers or seat model into the Party** (§3 shows other games differ).

## 8. Explicitly deferred

`.avrgame` archive format, signing/PKI, community portal, marketplace, developer accounts,
updater, public CLI, generalized sandbox, mobile app, emulator packaging, N64, dynamic Personal
Viewports, custom hardware, commercial packaging, broad observability, the results/stats sink,
per-game chat, votes, teams, capability negotiation beyond v0, and migrating the LAN catalog.
