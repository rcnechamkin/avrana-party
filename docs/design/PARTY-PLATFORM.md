# Avrana Party platform: what it is and how it fits together

Status: **canonical design direction, reconciled 2026-10-01.** Party Core, Party Home,
session integration and authoritative navigation are implemented. ADR 0011 is accepted and
merged in Party PR #34 / Games PR #13; deployment and Tier 3 phone validation remain AVR-212.
See [SYSTEM](../SYSTEM.md) for verified production, which may lag source. This is the hub;
ADRs 0002/0003 define platform/identity invariants and ADRs 0006–0011 define implemented sessions,
pregame and console behavior. Broader profiles, teams, votes, progression, moderation and
third-party installation below remain design direction unless explicitly marked implemented.
Linear owns live sequencing; [ROADMAP](../ROADMAP.md) owns strategic direction.

**Architecture reconciliation 2026-10-02.** ADRs [0012](../adr/0012-limited-mode-party-survives-https-loss.md)
(Full/Limited Mode), [0013](../adr/0013-party-and-game-browser-origins.md) (Party origin vs game
origin) and [0014](../adr/0014-native-games-isolated-lan-games-retired.md) (isolated native games;
LAN Games retired) are accepted direction and **not implemented**. Sections below say
"**Current**" for what source/production does today and "**Target**" for the accepted
architecture. Until the migrations land and are verified, one HTTPS origin, the LAN Games fork
and HTTPS-only Party Home remain the deployed reality ([SYSTEM](../SYSTEM.md)).

Read this before designing anything a player touches: a game, a lobby, a login, a chat, a stat.
It is written for someone arriving months from now with no other context.

| Document | Covers |
|---|---|
| **this file** | thesis, principles, locked decisions, concepts, roles, social layer, security summary, open questions |
| `PARTY-LIFECYCLE.md` | state machines (party, presence, host, seat), awkward-state rules, timers |
| `GAME-INTEGRATION.md` | capability manifest v0, runtime vs grant, the party contract, what today's code duplicates |
| `NATIVE-GAMES.md` | "the phone is not just a controller", hook strategy, reusable primitives, fairness, accessibility |
| `PERSONAL-VIEWPORTS.md` | per-phone crops of one shared split-screen stream |
| `ONBOARDING.md` | tap/scan to join, party address, no-app baseline, party LAN vs upstream internet |
| `GAME-INSTALLATION.md` | open installation without a store, trust tiers, emulator profiles |
| `FULL-MODE.md` | the deployed HTTPS shell and the accepted Full Mode / Limited Mode target |
| `docs/findings/2026-09-24-product-differentiation.md` | why anyone would choose this; where it loses; what to prove first |

---

## 1. The thesis

Avrana Party is **a portable local multiplayer platform whose games plug into a shared Avrana
Party system**. It is not a ROM box, not a LAN Games front end, not a Raspberry Pi project and not
a phone game launcher.

> **The game may change. The party does not.**

Technically, that sentence means: **the Party is a long-lived object that outlives every game
session.** A browser with an Avrana profile automatically gains or resumes presence on the canonical
Party/game surfaces, without normal Join or Leave buttons (ADR 0011). Members and host belong to Party Core; richer personas, persistent seating, teams, queue and
progression remain broader platform design. Chat and local launch history use shared adapters. A game is a session the
party starts and ends. A finished round holds its results until the host chooses Play again or
Party Home; host End returns everyone home. Party identity carries forward, while the next
setup chooses Play or Watch and the game binds its roster — no manual re-join or navigation. (Whether the party
also survives an appliance *reboot* is still open: §16.)

Avrana owns the **party lifecycle, profiles, guests, device recognition, presence, seats, roles,
personas, host and admin authority, synchronized navigation, reconnect, spectators, teams, chat,
voting, stats provenance, achievements and game capability metadata.** Games plug into those
where appropriate.

Avrana is also the **only owner and writer of the durable record**: persistent cross-session
results, history, stats, person/profile attribution and provenance. Games decide what happened in
a round and report it; they are **isolated consumers of platform services** (identity for the
session, tickets, navigation, results intake), not co-owners of the platform's state
([ADR 0014](../adr/0014-native-games-isolated-lan-games-retired.md)).

### What this is not

- **Not a universal gameplay framework.** Rules, state, rendering, netcode and turn logic stay with
  each game. The platform provides *services around* games through a small contract
  (`GAME-INTEGRATION.md`). That is why the roadmap still says "no universal gameplay framework".
- **Not a social network and not cloud accounts.** Local to the appliance, offline, no sign-up.
- **Not a store.** Open installation, no marketplace (`GAME-INSTALLATION.md`).
- **Not captive-portal-dependent and not app-dependent.** Wi-Fi plus a normal browser is the
  baseline (`ONBOARDING.md`).

### Who V1.0 is for

The first real V1.0 is for the owner. Its job is to prove **"can this whole product experience
actually work and be fun?"** A possible later path — working prototype → polished demonstrator →
crowdfunding → appliance for backers — must not distort the immediate roadmap, but the
architecture should avoid obvious dead ends for it (open formats, stable ids, no hard-coded
single-user assumptions, a clean admin/host split).

---

## 2. Product principles

Durable. A design that breaks one needs an explicit, recorded reason.

1. **The game may change. The party does not.**
2. **Browser-first.** The browser is the whole product surface; the captive portal is optional
   convenience, never an architectural dependency.
3. **Guest-first.** Profiles enhance play but are never required. Anonymous guests always work.
4. **Avrana owns player identity; games consume it.**
5. **Device identity is not human identity.** "I recognize this browser" never means "this is Cody".
6. **Seats bind sessions, profiles and controllers temporarily.**
7. **Admin authority is separate from Party Host authority.**
8. **Navigation is synchronized across the party.**
9. **Games plug into shared social, session and progression systems.**
10. **Offline-first.**
11. **Never claim what a game or the platform cannot actually observe.**
12. **No game should reinvent profiles, chat, reconnect, teams, spectators or session lifecycle.**
13. **Reduce social friction; never add account or setup friction.**
14. **The phone is not just a controller.** It is each player's private, dynamic surface; native
    games should use it (`NATIVE-GAMES.md`).
15. **One appliance, one party, one active activity.** Not a multi-tenant game server, and in
    Standard Mode not a room of simultaneous side games (ADR 0011, ADR 0014). A future Developer
    Mode may relax this for technical users without shaping Standard Mode.
16. **TV optional.** The core experience works on phones alone; a game may require a TV.
17. **No app required.** Wi-Fi + a normal browser; an app may only add convenience.
18. **Open, not a store.** Anyone may install Avrana-compatible games; trust is the appliance
    owner's decision.
19. **Trusted HTTPS is preferred, never required.** Losing the certificate degrades individual
    capabilities (Limited Mode); it does not disable the Party
    ([ADR 0012](../adr/0012-limited-mode-party-survives-https-loss.md)).
20. **Game code is not Party code.** The trusted Party shell and game clients are separate browser
    trust domains; playing a game never gives its JavaScript Party, member or admin authority
    ([ADR 0013](../adr/0013-party-and-game-browser-origins.md)).
21. **Party owns the durable record; games report.** Results, history, stats and profile
    attribution are written only by the platform.

---

## 3. Locked product decisions (2026-09-24)

| Question | Decision |
|---|---|
| Multiple simultaneous parties? | **No.** One appliance hosts one active party. |
| Is a TV mandatory? | **No.** Games may still declare `tv_required`, `tv_optional` or `no_tv_needed`. Target settings include bars, airplanes, cruise ships, hotels, airports, travel, noisy places and players who are apart but nearby. |
| What if the host disappears? | **Host migration.** Reconnect grace, then another eligible player; voluntary transfer anytime; a returning old host doesn't take it back. Keep the selection rule simple. |
| Late joiners? | **Spectator by default.** A game may opt into next-round admission, join-in-progress, deal-in or open-seat filling (manifest `late_join`). |
| Physical seating (rows, table position, left neighbour)? | **Not a platform concept.** A game may define its own spatial idea if it truly helps. |
| A proprietary game store? | **No.** Open installation; no marketplace, payments, reviews or DRM. |
| A native app? | **Not required.** Optional later for onboarding or hardware. |
| Captive portal? | **Not required.** Optional glue only. |
| Phones forming one big distributed display? | **Experimental only** (§14). |

### 3.1 Decisions added 2026-10-02 (accepted direction; implementation tracked in Linear)

| Question | Decision | Record |
|---|---|---|
| Does the Party need a valid trusted certificate? | **No.** Full Mode (trusted HTTPS) is preferred; Limited Mode keeps membership, presence, host authority, navigation, game selection and compatible play. HTTPS-only features degrade individually and visibly. The `Secure` cookie is never weakened; Limited Mode gets an explicit identity model. | ADR 0012 |
| Do the Party shell and games share a browser origin? | **No (target).** A trusted Party origin owns device identity, the Party API, membership/presence, host/platform controls and profile/system surfaces. A game origin receives only session-scoped authority (tickets). | ADR 0013 |
| Is LAN Games the native-game runtime? | **No.** It was MVP infrastructure. Standalone LAN Games is not a product mode; `wc-token` player admission retires; the code remains donor/reference material. | ADR 0014 |
| How do native games run? | As **independent platform consumers**: own process, own service identity and secrets, generic routing from a game registry, one provisioning path, one canonical manifest, no game-specific Party Core logic. | ADR 0014 |
| Who owns results and history? | **Party.** Games determine and report structured, versioned results; Party alone writes the persistent cross-session record. The wire schema is AVR-237, not yet designed. | ADR 0006 amendment, ADR 0014 |
| Simultaneous activities? | **Not in Standard Mode.** One appliance, one Party, one active activity. Developer Mode, if ever, is separate. | ADR 0011 amendment |
| What is a person? | **Device identity is not human identity, and a browser-stored name/avatar is not durable identity.** Persistent facts about a person require an explicit, optional, server-side Profile. | ADR 0003 amendment |
| Ticket cryptography? | **Symmetric HMAC, single-use; reconnect fetches a fresh ticket.** Public-key signatures are reserved for package/update provenance. | ADR 0003 / 0006 amendments |
| Native-game validation order? | **BLUFF** (first Avrana-native vertical slice, done in product terms) → **Checkers** (first clean proof outside the LAN Games runtime) → **Spades** (teams, private hands, reconnect, scoring, richer results). SDK/package formats freeze only after these. | ADR 0014 |

---

## 4. The product surface: browser-first, offline-first

```
Join the Avrana Wi-Fi  →  open the party address  →  the browser is the player's complete interface
```

Over time the browser handles identity/profile selection, Party Home/setup, navigation, controller
UI, WebRTC video, WebSocket input, chat, private information, voting, achievements and stats,
profile settings and reconnection. Onboarding details, the party address and the party-LAN vs
optional-upstream model are in `ONBOARDING.md`.

- **One canonical *Party* origin.** Party identity lives in exactly one browser origin. A
  different host name (`10.42.0.1` vs `party.local`) gets a separate cookie jar; a different port
  (`:8198`) shares cookies but has separate localStorage and a different Origin. Either way a player
  can look like two devices — two presences, two seats, two votes. Cookies ignore ports, so a dev
  instance on another port of the same host receives production cookies. That is why Party
  identity is never spread across origins and never recovered across them.
- **Trusted Party origin:** `https://party.avrana.net`, browser-trusted and resolved by Party DNS,
  has been live since 2026-09-25 (ADR 0004). Avrana-owned pages live under `/party/` on 443. The
  Party cookie is `Secure`. It owns device identity, the Party API, membership and presence, host
  and platform controls, and profile/system surfaces.
- **Game origin (Target, ADR 0013).** Game clients are served from a separate browser origin
  (near-term preference: a separate hostname on the appliance under the existing certificate and
  Party DNS model). A game origin receives only game/session-scoped authority — Party-issued
  participant/session tickets — and its JavaScript cannot act as the member against Party, host or
  admin APIs. Stronger sandboxing for untrusted community games is a later tier.
  **Current:** integrated games and the arcade are still served from the Party origin; the earlier
  statement that "everything a player uses is served from one origin" is superseded as a target
  and remains true only as a description of today's deployment.
- **Full Mode and Limited Mode (Target, ADR 0012).** Trusted HTTPS is Full Mode and stays the
  default. When it is unavailable, the Party remains usable in a visibly degraded Limited Mode:
  membership, presence, host authority, synchronized navigation, game selection and compatible
  play continue; secure-context features degrade per capability and per seat. Limited Mode has its
  own explicit identity/continuity model; the `Secure` cookie is not weakened.
  **Current:** `/party/` is HTTPS-only; `http://10.42.0.1` serves captive probes and the legacy
  LAN Games hub. HTTP, HTTPS and hostname variants are separate origins; do not invent
  cross-origin identity recovery.
- Deployed Full Mode features (offline copy, keep-awake, capability probe) and the accepted
  Full/Limited target contract are in `FULL-MODE.md`.
- **Captive portal = convenience.** Never select a profile, trust a device or run a game inside the
  captive-portal mini-browser.
- **Per-player accessibility is free here:** every player has a private UI, so larger text,
  handedness, contrast, motion and haptics can change for one person only (`NATIVE-GAMES.md` §7).

---

## 5. Core concepts

Do not collapse "player" into one object. Identifier rules are in ADR 0003.

| Concept | What it is | Lifetime | Key |
|---|---|---|---|
| **Party** | The persistent unit people join: members, host, *seating* (who holds which game slot, carried from one game to the next — never physical position), current game, queue, teams, chat. Exactly one active per appliance. | From automatic presence until ended (current Core is memory-only; reboot survival OPEN) | `party_id` |
| **Device** | A recognized browser installation. | Months; revocable | server-issued random token in a cookie (hash stored) |
| **Profile** | The optional, durable, **server-side** human identity: name, avatar, preferences, history, stats, achievements. The only thing persistent facts about a person may attach to. Not yet built; the browser-stored name/avatar used for presence today is a display value, not a Profile (ADR 0003 amendment 2026-10-02). | Until deleted/merged | `profile_id` |
| **Guest** | A participant with no saved profile ("Player 3", renamed "Megan"). | The party | `presence_id` |
| **Presence** | A profile or guest participating in the party, from one device at a time (possibly several tabs; a profile moving to a new phone closes the old phone's connections). Proposed: a TV joins as a *screen* presence (sees the public view; never host, seat or voter). | The party | `presence_id` |
| **Seat** | A temporary binding: presence → a player/controller slot in the current game session. | One game session; the party's *seating* (who holds which slot) carries forward | `seat_id` |
| **Game session** | One launch of one game by the party. | Until the game ends | `game_session_id` |
| **Role** | Host, Player, Spectator (party roles); Admin (appliance role); game-specific roles. | Varies | — |
| **Persona** | A temporary display identity: profile *Cody*, tonight *Admiral Worm*, in BLUFF *Definitely Not The Duke*. | Party or game | on the presence |
| **Device trust** | Whether a device may pick a saved profile without its PIN. | Until revoked | device↔profile link |
| **Team** | A named group of presences above any single game. | The party | `team_id` |

```
 Device (browser, cookie) ──recognizes──▶ Profile(s) it may offer ("Welcome back")
      │
      └─opens─▶ Presence in THE Party  (profile or guest, with a persona)
                    │
                    ├─ Role in the party: Host? Player? Spectator?
                    ├─ Team membership (optional)
                    └─ Seat in the current game session ──▶ the game's controller/player slot
```

**Invariants (ADR 0003):** device token ≠ device id ≠ profile id ≠ presence id ≠ seat id ≠
controller number. They map to each other; they are never the same value. Ids are opaque and
authorize nothing; only credentials resolved on the server do; names never do.

**What a game sees:** a secret **game key** scoped to (game session, participant) plus the persona
to display — never a device token or profile secret. Where the seat is bound depends on the game
(LAN Games at its countdown; PS1 and the arcade at connect) — see `GAME-INTEGRATION.md`.

**Live identity vs durable identity.** Device, Presence and Seat are *live* Party identity: they
say who is here tonight. Profile is *durable* identity: it says who a person is across nights.
They stay separate concepts. Until a Profile entity exists, nothing persistent is stored about a
person, and cross-session history is not attributed to a browser's display name.

### 5.1 State model review (2026-09-26, PROPOSED)

This review compared the party model (`experiments/party-model/party_model.py`) with Colyseus,
boardgame.io, Couch Kit, Hotspot Arcade, AirConsole and Jackbox
(`docs/findings/2026-09-26-architecture-sprint.md`). None of them models a party, so Avrana keeps
owning this layer.

The principle: **store facts, derive roles.**
- A role that can be derived (Player, Spectator) is never stored.
- A role that must be unique (Party Host) is a pointer on its container (`host_presence_id`).
- Appliance roles (Owner, Admin, Developer) bind to admin sessions, never to a presence, and never
  appear in party state.

| Entity | What it adds to the table above |
|---|---|
| **Person** | not stored: the system can't observe a human. The UI says "player" |
| **Connection** | a transport, of kind `party_stream`, `party_socket` or `game_socket`. It authorizes nothing. Presence liveness is **derived** from all of a presence's party-attached connections (plus games reporting the seat live), not from the party stream alone |
| **InputBinding** | `seat → source` (a connection, an appliance pad or, later, a companion) with an epoch; "newest tab wins" is the highest epoch. Only a Seat has one, so spectators' input is dropped by construction |
| **Surface** (presentation) | a visual output: `private_phone`, `public_screen` or `personal_viewport`, with scope public, a presence or a seat. **A TV is a public Surface with no Presence**, so it can never be host, seat or voter by construction. **A Personal Viewport is a Surface bound to a seat**; how it is produced (crop, dedicated stream, browser renderer, private panel) is the Game Contract's `presentation.viewport` |
| **Seat** | adds a `generation` per slot. A refill of the same slot is a new seat with a new generation, and seat tickets must carry it (see gap 1) |

**Roles:**
- Owner: physical or SSH access.
- Admin: PIN session.
- Developer: a mode the owner enables.
- Party Host: a pointer on the Party.
- Player: a presence with a Seat in the current game session.
- Spectator: a presence without one.

Capability evaluation uses only the derived game role (`evaluate_seat(game, caps, role)`,
`contracts/README.md`).

**Gaps found in branch code** (verified on scratch copies, not fixed here):
1. Seat ticket v1 binds a *slot*, so the previous occupant's unexpired ticket still works after a
   refill. Fix: ticket v2 carries the game session and seat generation.
2. `input_connection()` returns a connection for a spectator.
3. Liveness counts only the party stream, so players inside a game page without `party.js` look
   gone after 300 s.

**Pure invariants worth adding to the model's tests:**
- (1) and (2) above.
- Released seat ids and keys never reappear.
- `nav.target` changes only with `nav.seq`.
- No viewer's view contains another viewer's ticket or key.
- Every non-acting viewer gets the same public view.
- The client accepts a view only if its `(party_id, version)` is monotonic.
- A per-verb `if_version` table (host verbs require it).
- No credential ever appears in a URL.

---

## 6. Guest-first and saved profiles

Current source uses the existing local name/Gaze avatar profile for automatic Party presence,
including join/resume on load, Core restart and profile save. This local profile is not a cloud
account or the richer persistent profile/trust system below, and it is **not durable human
identity**: it is a browser-stored display value. Without a profile or Party Core, standalone
access still works in current source; standalone LAN Games play is retiring as a product mode
(ADR 0014). The following describes the broader guest/profile design, whose prerequisite is an
explicit optional server-side Profile entity.

- Joining never requires a profile. Default names are **Player 1, Player 2, Player 3**; a guest can
  rename immediately (*Player 3 → Megan*).
- Later: **"Save Megan as a profile?"** If saved, the history Megan gathered as a guest links to the
  new profile with its provenance. Wording: **Save Player**, **Save Profile**, **Keep this player** —
  never "Create Account".
- **Player profile PIN: optional. System Admin PIN: required.**
- A remembered device means *"I recognize this browser"*. A recognized phone shows
  `Welcome back [Cody] [Audrey] [Someone else] [Guest]`. The device token is random and
  server-issued; **never** MAC addresses or fingerprinting.
- A PIN-less profile runs on the honour system (the UI says so); if its owner is already present, a
  second device needs a trusted device (or the PIN, if set) to take it.
- **Lifecycle:** guest→profile promotion · many devices per profile and many profiles per device ·
  aliases/personas · recent players · trusted-device revocation · deletion ("Deleted player" keeps
  others' records true) · admin-only merge (moves history, never access) · export/import without
  secrets · QR pairing with a short-lived single-use code. Stable opaque ids; no cloud identity.
- **Settings categories** (not a UI spec): identity (name, avatar, aliases); access (optional PIN,
  trusted devices); controls (handedness, layout, button size, haptics); accessibility (text size,
  contrast, reduced motion, colour-safe palettes); privacy (stats visibility, playtime, rivalry
  history, recent games); social (chat/whisper preferences, later mute/block); gameplay (per-game
  preferences, favourite games); cosmetics (frames, badges, showcase — later). LAN Games' per-device
  sound/haptics/motion/contrast preferences are the seed.

---

## 7. Admin vs Party Host

Entirely separate. A host can never escalate to admin.

| | **System Admin** | **Party Host** |
|---|---|---|
| What | Persistent privileged appliance identity | Temporary, disposable role inside the party |
| Credential | **PIN required** (no default); v0 is an SSH command-line tool, a PIN-protected web admin comes later (§13) | None |
| Powers | Network, updates, storage, game installation and trust, profile management (merge, delete, reset PINs), **moderation defaults**, kick and revoke/clear guest identities | Select/start games; game rules; pause/restart/end; manage spectators; remove/reassign seats; moderate party chat; rematch/next game; run votes; kick from the current party |
| Cannot | — | Touch profiles, devices, PINs, installation or admin settings; see other players' hidden game state |

- **Host is disposable** (`PARTY-LIFECYCLE.md`): reconnect grace, then succession to another
  eligible member (current Core: earliest-joined member who is here or playing); proposed voluntary
  transfer; a returning old host is an ordinary player; no "claim host" action.
- Normal players always keep authority over their own profile, controls, avatar/persona and
  accessibility preferences.
- **Moderation is configurable, not hard-coded.** The admin eventually sets defaults such as:
  profanity filtering, profile visibility, custom avatar uploads, guest naming rules, whispers, chat
  availability, kicking for the current party, whether persistent profiles can be created, and
  whether saved profiles are shown to guests. A simple preset pair may bundle them — without any
  enterprise role system:
  - **Friends / Private party** (default): the Wi-Fi password is the only gate; no join code in v0.
    **Network reachability is the practical root of admission** in this mode: a browser that can
    reach the Party on the appliance's network and holds a name is admitted. That is a deliberate
    product choice for private parties, not an oversight, and it holds in Limited Mode too.
  - **Public / Demo party (future distinct admission mode):** stronger admission can later require
    explicit host approval, a PIN or a QR code. New presences wait for **host admission** (covers strangers, kick
    evasion and duplicate presences); an optional short party code in the QR's URL fragment with a
    typed fallback; the admin (over SSH in v0) picks the first host, also after idle or reboot; no
    web admin on the guest Wi-Fi. This future mode does not restore a normal Join ceremony.
- **Kick ≠ ban.** A kick removes a presence from the current party and says so publicly. Because a
  private tab is a new device, it is not a ban; only the Wi-Fi password or Public-mode admission
  keeps someone out.

---

## 8. The Party, Party Home and synchronized navigation

Party Core exposes one authoritative `location = {at: home | setup | game | results, game,
session}` (ADR 0011). It is derived from committed navigation and session state, not a second
client-owned state machine. Only the host moves the Party. The internal idle state may still be
named `lobby`; the product location is `home`.

**Party Home is implemented** at `/party/`: roster/host, profile, catalog, Party Chat and shared
library. In current source it also owns the full-screen setup scene: choose Play or Watch, read
How to play, and wait for host-only Start. Queue/votes, teams and richer party stats remain future
concepts, not current Home features.

**Authoritative follow is implemented.** `party-mode.js` supplies `destination(view, here)`;
Party Home, `party-follow.js` on game pages and the arcade apply it on load, reconnect and every
change with `location.replace`. Home/setup render on Party Home; game/results render on the
named game's page. A phone asleep through a move follows the current location on wake.

Normal flow has no Join or Leave button. Profile-backed presence resumes automatically.
During a round, Party Home cannot be browsed and another game cannot be opened. A standalone
title may remain open while the Party is home, then follows when the host moves the Party.
Followers do not get optional detour prompts or Rejoin offers. Host controls live in the game's
chrome; a game's own completion holds results until the host selects Play again or Party Home.
Host End goes home. Failed launches resolve to home; intent alone is not navigation authority.

**One active activity (Standard Mode).** `location` is singular by design: one appliance, one
Party, one activity at a time. Simultaneous games or tables are not a Standard Mode feature and
do not shape Party Core, routing or results (ADR 0011 amendment 2026-10-02). The "standalone title
may remain open while the Party is home" behaviour above is LAN Games compatibility in deployed
source and retires with standalone LAN Games (ADR 0014).

AVR-128 navigation, ADR 0010 pregame and AVR-134 Party-managed arcade lifecycle are already
recorded as deployed. ADR 0011's console presentation/follow changes are merged source ahead
of verified production; AVR-212 owns deployment and phone proof. PS1 remains experimental.

---

## 9. Seats, spectators and teams

These are seat/grace design requirements, not a claim of a complete platform seat layer.
BLUFF preserves its session participant identity. AVR-130 arcade controller reservations merged
in PR #35 during this reconciliation: stable session-local slots, neutral input on disconnect,
60-second grace and explicit controller release. Published findings do not verify deployment
or real-phone acceptance. Controller release does not remove Party presence. See `PARTY-LIFECYCLE.md`.

- **Seats** support disconnect grace, **neutral input while disconnected**, reclaim on reconnect,
  game-specific slot assignment, and team membership. A disconnected or away seat is never "free";
  only a released seat can be refilled (new seat id, new key). Every connection resolves to one
  presence; a controller slot takes input from one connection (the newest tab).
- **Late joiners spectate by default**; games opt into more via `late_join`.
- **Spectators** are a first-class role, not a failed player slot: they see the shared stream or
  public state, chat, optionally vote (party setting, off by default proposed), and can be promoted
  within the game's policy. The server rejects their input.
- **Teams** live above the individual game (Team Purple: Cody, Audrey · Team Orange: Nick, Megan).
  Compatible games reuse them and report team results; others don't participate. **Never fake a
  team result.** Party score example: Bomberman → Purple, BLUFF → Orange, Worms → Purple = 2–1.
- Physical seating is not modelled (§3).

---

## 10. Social layer

- **Chat channels:** public party chat, team chat, private whispers, game-defined channels, and
  **system events** (`SYSTEM: Audrey is now Host.`) — a separate server-only message type rendered
  in its own element, backed by the name rule in §13 (normalization, no look-alike alphabets, no
  reserved words, duplicates numbered) so no player name can pass for it. The host moderates party
  chat within the admin's defaults.
- **Private player panel:** hidden roles, cards, inventory, secret objectives, private prompts, votes
  and decisions on each phone, alongside the shared public view (phones or an optional TV). Private
  data is filtered on the server, never hidden with CSS (`NATIVE-GAMES.md`).
- **Queue and voting:** coordinate what to play next — valuable when players are apart and can't
  talk. Anyone nominates; the party votes; **the host decides** (votes are advisory — see §13 on
  why ballot stuffing is possible and accepted for Friends parties). Public or hidden votes; spectator
  voting per party setting. The list filters itself by player count, TV requirement, control model,
  session length and capability (manifests). Modes: **casual queue**, **vote round** (timed),
  **playlist**. Early completion when every eligible voter present has voted. **Votes belong to
  party presence**, never browser connections: refresh, reconnect or a second tab never adds one.

---

## 11. Progression: stats, achievements, history

| Provenance | Meaning | Example |
|---|---|---|
| `authoritative_game_event` | The game reported it | BLUFF winner, eliminations |
| `platform_observed` | The platform saw it | Cody held Bomberman slot 2 for 14 minutes |
| `manually_recorded` | A person entered it (only if ever supported) | "Purple won Worms", typed by the host |

- **Party is the owner and only writer** of persistent cross-session results, history, stats,
  person/profile attribution and provenance. A game determines its own outcome and reports a
  structured, versioned result; Party validates, attributes and stores it. **Current:** the v0
  `ended` report carries only `completed`/`abandoned` and nothing is persisted; the result
  envelope is AVR-237 and its schema is not designed yet. Game-local scoreboards are a game's
  own presentation, never the platform's record.
- Native games can report authoritative events; **emulated games produce no results** unless a
  per-game adapter exists; hot-seat games can't even attribute turns. **Participation is never a
  win.** Flags that change meaning travel with results: bot seats, autopilot, forfeits, abandoned
  games. Community games carry a `community` **trust-tier** label beside their provenance (not a fourth
  provenance value; ADR 0003).
- **Achievements:** platform (N games, N titles, N people, tournaments), game-defined, and
  social/party (wins across games in one party, team feats, rivalry milestones); may unlock local
  cosmetics; no monetization; only from stats whose provenance supports them.
- **History and rivalries:** games played together, recent players, frequent teammates, trustworthy
  head-to-heads, party-night recaps, favourites. Local history from shared play — not a social
  network.

---

## 12. Games and the platform (summary)

A game touches the platform through three separate things — **capabilities** (the manifest: what
the game is), a **runtime request** (how its code runs) and a **grant** (what the appliance allows)
— and joins the party through four optional pieces: a seat-ticket handshake (first WebSocket
message, bound to one game), an event sink with provenance, the implemented `party-follow.js` client (ADR 0011), and host
checks. Without them a game keeps working as today. Everything is in `GAME-INTEGRATION.md`; native
game design is in `NATIVE-GAMES.md`; installation is in `GAME-INSTALLATION.md`.

**Target (ADR 0014): games are isolated consumers of platform services.** Each native game is an
independent process with its own service identity, secrets and state, reached through generic
routing from a runtime-readable game registry, provisioned through one path, described by one
canonical manifest from which catalogue and runtime metadata derive, and served from the game
origin (ADR 0013). Party Core carries no game-specific logic. **Current:** BLUFF and the donor
titles run inside the LAN Games fork's single process on the Party origin; that fork is retiring
as a runtime and remains donor/reference code.

**Validation order:** BLUFF is the first Avrana-native game and vertical slice. Checkers is the
first deliberately simple proof that a game can live outside the LAN Games runtime on the new
boundary. Spades then pressure-tests teams, private hands, reconnect, scoring and richer results.
SDK, package (`.avrgame`) and provider abstractions are frozen only after those proofs.

**Hook strategy:** the platform should eventually demonstrate three kinds of hook, not one title:
native Jackbox-like games with no TV; native action/arcade games designed around Avrana; and
emulated multiplayer (including **Personal Viewports**, `PERSONAL-VIEWPORTS.md`). BLUFF is an early
native testbed, not the product.

---

## 13. Security model (proportionate)

Threats: mischievous guests on the same Wi-Fi (impersonation, stat spoiling, double voting, host
grabbing); cookie sniffing on an open or shared-password network; web pages on a phone that also
has mobile data; and — once open installation exists — **a malicious or buggy game**. Anyone with
SD-card or SSH access is an admin by design. Future profile/admin parameters are suggestions to confirm when built.

**Transport boundary (Friends parties):** canonical Full Mode and integrated game traffic on
`https://party.avrana.net` is TLS-protected. Legacy plain HTTP remains exposed to traffic
inspection/alteration by peers on a shared-password network; do not extend that accepted legacy
risk to HTTPS credentials or hidden state. The Wi-Fi must not be open. Client isolation
(`wifi.ap-isolation`) is a possible extra control and a live change requiring owner approval.
**Limited Mode (Target, ADR 0012)** runs the Party without trusted TLS; it therefore carries its
own credential (never the `Secure` device cookie), says so visibly, and grants no admin or
elevated authority. What hidden-information games may do in Limited Mode is part of AVR-225.

**Browser trust boundary (Target, ADR 0013):** the Party origin and the game origin are separate
trust domains. Path-scoped `HttpOnly` cookies keep the device token from game *servers* but not
from same-origin game *JavaScript*, which today can call `/party/api/` as the viewer. The target
removes that: game pages hold tickets only. **Current:** one origin; treat every game page as able
to act as the member until the split lands.

**MUST before profiles ship**
- Server-issued device token (`secrets.token_urlsafe(32)`) in an `HttpOnly; SameSite=Lax` cookie
  scoped to the party path (e.g. `Path=/party/`), and nginx strips the `Cookie` header on every game
  location, so **game servers never receive device tokens** (path scoping keeps cookies from
  servers, not from same-origin JavaScript). Store only its SHA-256; revoke = delete. It unlocks the
  "Welcome back" picker; it never grants admin or skips the admin PIN; on a device the owner chose
  to trust, it skips that profile's PIN.
- One canonical HTTPS *Party* origin (`https://party.avrana.net`, §4; games move to a separate
  origin under ADR 0013); nginx allowlists the app's
  host names (also defeats DNS rebinding), while the default server keeps answering the
  captive-portal probe paths exactly as today (returning 444 only for everything else).
- Origin checks on every WebSocket upgrade and POST to party and admin endpoints once identity
  rides on a cookie; GET never mutates. On canonical Party/game surfaces, a browser with an
  Avrana profile automatically calls the guarded `join` POST on load/resume; no normal Join or
  Leave UI. Page rendering and socket opens alone do not authorize membership. Captive probes
  remain separate and do not select profiles or participate in the Party.
- Authorization only from server-resolved ids; never from names or client-sent ids.
- **Admin:** v0 has **no web admin** — administration is an SSH command-line tool (V1.0 is for the
  owner), so there is nothing for a guest to brute-force or cross-site-request. A later web admin:
  PIN required (no default, ≥ 6 digits, set over SSH); runs on its **own port** (a separate origin,
  so party-page JavaScript can't read its anti-CSRF token and exact Origin checks reject it);
  `frame-ancestors 'none'`; a short backoff capped at ~60 s so a guest can't lock the owner out all
  night; off on the guest Wi-Fi in Public/Demo mode; recovery = delete the PIN file over SSH/SD;
  an SSH `login` command can always issue a one-time link. PIN hash with `hashlib.scrypt` in its own
  0600 file owned by the party service's **own system user** (a unit change needing approval).
- Host ≠ Admin; system messages are a separate server-only type rendered in their own element.
- **Names** (display values only): NFKC-normalize; strip control/format characters (zero-width,
  bidi overrides); collapse spaces; 1–16 characters; no mixing of look-alike alphabets (Latin,
  Cyrillic, Greek); reject anything that is or starts with a reserved word (SYSTEM, Admin, Host,
  Avrana, Moderator), compared on a casefolded letters-and-digits key; duplicates get " 2"; render
  names as text inside `<bdi>`. (Checked in `experiments/party-model`.)
- Votes per round per presence; one controlling connection per seat; spectator input rejected.
- Seat tickets bound to one game (audience). For **sandboxed** third-party games, verify them with
  per-game keys or sockets; built-in LAN Games modules share one process, so that process is their
  real boundary (below).
- Dev instances use a **different cookie name** and never the production host (cookies are keyed by
  name, host and path — not port — so a same-named dev cookie would overwrite production's).

**SHOULD** — optional profile PIN (4–6 digits; scrypt is kept but a short PIN can be cracked
offline in seconds, so file ownership is the real control; the UI says "don't reuse your bank or
phone PIN"); backoff only on **untrusted** devices (trusted ones skip the PIN, so the owner is never
locked out; the owner sees failed attempts); a PIN or honour-system pick lasts this party only
unless "Trust this phone" is ticked; a profile moving to another phone notifies the old phone and
posts a system event. QR pairing with single-use 3-minute codes in the URL fragment, confirmed on
the issuing phone (a photographed QR is not enough), fragment cleared after use. Tokens never in a
URL path or query string or in logs. SQLite with WAL and regular backups (power-loss history).
Store only names, avatars (re-encoded to PNG/JPEG), preferences and stats.

**Honest limits.** Device tokens are free (a private tab is a new device), so: a **kick removes a
presence and says so publicly — it is not a ban**; one person can hold several presences, so a vote
can be stuffed — eligibility freezes when a round opens and **the host decides**, so votes stay
advisory; that is accepted for Friends parties. Only the Wi-Fi password — or host admission in
Public/Demo mode (§7) — keeps someone out. **Built-in games are not isolated from each other
today:** the LAN Games fork is one process, so any module could read any game's keys; this is
acceptable only because built-in code is trusted. It is the deployed state, not the target:
ADR 0014 gives each native game its own process, identity and key. Beyond the shared process,
every appliance service also shares one Unix user today, so key file modes and loopback-only
routes do not separate services at all; ADR 0016 defines the boundary that will.

**For untrusted games (later; a stronger tier on top of ADR 0013's origin split):** no untrusted in-process code; every response under an untrusted
game's path gets `Content-Security-Policy: sandbox allow-scripts` and `nosniff`, inside a platform
frame that exposes no host verbs over `postMessage`; game endpoints authenticate by ticket and
accept the sandbox's `null` Origin, while party and admin endpoints reject it; sandboxed games are
second-class (no localStorage, harder fullscreen and audio unlock). Server processes are isolated
with systemd sandboxing and no network (`GAME-INSTALLATION.md`).

**Known gaps today:** the arcade's `/stats` is reachable through nginx and shows peer IPs; PS1's
localhost-only `/stats` check will stop working once PS1 sits behind nginx; PS1 sends its token in
the URL (`?token=`), which nginx would log — *fixed on branch `experiment/ps1-title-profiles`
(token in a `hello` message), not merged*.

**Deliberately not doing** — ~~TLS on guests' phones~~ (superseded: browser-trusted HTTPS is LIVE,
ADR 0004; still no private CA on phones), JWTs, token rotation schedules, encrypted
databases, Argon2 dependencies, device fingerprinting, email recovery, CAPTCHAs.

---

## 14. Experimental and future concepts (not MVP)

- **Distributed phone display:** several phones together showing parts of one larger picture.
  Interesting; not built, not planned.
- **Native companion app:** only for onboarding/hardware conveniences (programmatic Wi-Fi join, NFC
  Wi-Fi on iPhone, background reconnect). Never required.
- **BLE discovery/proximity:** only if genuinely useful later (needs an app on iOS).
- **Optional upstream internet** (Ethernet, Wi-Fi client uplink, tether): makes onboarding easier;
  the party must never depend on it (`ONBOARDING.md`).
- **Personal Viewport auto-detection** (menus, player count, layout via title adapters, emulator or
  memory inspection, video analysis): after a manual PoC proves the idea.
- **Emulated-game result adapters:** per-title, only where results can be observed honestly.

---

## 15. Historical integration baseline (2026-09-24)

The following predates Party Core and ADRs 0006–0011; it is historical gap analysis, not current
status. Current source is described in §8; deployed evidence lives in SYSTEM.
Audit with file references: `GAME-INTEGRATION.md` §4. At that date: identity, reconnect, presence,
seats, spectators, late join, navigation and launch each exist **separately** in two or more places
(LAN Games core, BLUFF, WORDCLASH, the arcade, PS1) with different semantics — at least five grace
behaviours, four token validators, five late-join policies — and **no host authority, no party, no
admin, no cross-game stats**. The LAN Games registry is a proto-manifest; PS1's slot table is the
closest thing to a platform Seat; BLUFF's presence model is the closest thing to platform Presence.

---

## 16. Open questions

**Closed on 2026-09-24:** multiple parties (no) · TV mandatory (no; games may require one) · late
join (spectator by default; games may override) · host loss (migration) · physical seating (not
core) · proprietary store (no) · native app required (no) · captive portal required (no).

**Still open:**
1. Exact party URL/origin layout (`/` = Party Home? LAN Games under a prefix?) — a live nginx change.
   *Partly decided 2026-09-26 (ADR 0004 D1):* the canonical origin is `https://party.avrana.net`, and
   Avrana pages are under `/party/`. Still open: whether `/` becomes Party Home, an HTTP doorway, and
   what the QR code carries.
2. ~~Device-token migration from LAN Games' client-minted `wc-token` without breaking the live service.~~
   *Decided 2026-10-02 (ADR 0014):* `wc-token` player admission retires with standalone LAN Games;
   there is no migration to a future player identity. Re-homing avatars/chat keyed by it is open.
3. Whether a party survives an appliance reboot (options in `PARTY-LIFECYCLE.md`).
4. Broader host transfer policy; current Core already selects the earliest-joined eligible member.
5. Third-party game sandbox/trust model (`GAME-INSTALLATION.md`). *Partly decided 2026-10-02:* the
   Party/game origin split (ADR 0013) and per-game process isolation (ADR 0014) apply to all games;
   the community sandbox tier on top remains open.
6. Upstream-internet architecture (`ONBOARDING.md`).
7. Packaging format for third-party games (`.avrgame`): deliberately unfrozen until Checkers and
   Spades prove the native boundary (ADR 0014).
8. Exact onboarding path across iOS and Android (needs the real-phone tests in `ONBOARDING.md`).
9. Exact Personal Viewport metadata format.
10. How hot-seat emulation attributes results (probably: it doesn't).
11. Final V1 hardware (power, battery, enclosure, display for QR codes).
12. Confirming the proposed TV "screen" presence (player navigation is settled by ADR 0011); whether a kick
    should ever reach beyond the current party (v0: this party only — `PARTY-LIFECYCLE.md`); spectator nominating;
    party teams vs in-game teams; whether an admin PIN exists before any web
    admin (§13); whether a hot-seat setting may give one device several presences
    (ADR 0003 allows it, the model forbids it); what `ps1-bomberman` declares for `late_join`;
    name length/Unicode (LAN Games caps names at 14 ASCII characters);
    profile database location and backups; admin surface on the guest Wi-Fi vs home LAN only;
    host-less kiosk parties.
13. *Added 2026-10-02:* the Limited Mode identity/continuity model (AVR-225); the game hostname(s)
    and the host-control/heartbeat transport across origins (AVR-226); the result envelope
    (AVR-237); the registry format and provisioning path (AVR-236); how chat, avatars and library
    keys leave the LAN Games donor (AVR-228).

---

## Glossary

| Term | Meaning |
|---|---|
| **BLUFF** | Working title of the first native Avrana game: a Coup-inspired hidden-role card game. Currently built as a LAN Games module in the Avrana Party Games fork; it moves to the isolated native boundary as LAN Games retires (ADR 0014) |
| **Checkers / Spades** | Planned validation games (ADR 0014): Checkers is the first clean platform-boundary proof after BLUFF, not the first native game; Spades is the richer pressure test. Neither exists yet |
| **LAN Games** | The retired-upstream (BEACNpool, MIT) browser party-game server (~28 games); Avrana maintains a fork, still deployed. MVP infrastructure, retiring as an Avrana runtime; kept as donor/reference code (ADR 0014) |
| **Full Mode / Limited Mode** | The Party over trusted HTTPS / the same Party when trusted HTTPS is unavailable, with capabilities degraded individually and visibly (ADR 0012; Limited Mode is not implemented) |
| **Standard Mode / Developer Mode** | The consumer product: one appliance, one Party, one active activity / a possible future mode for technical users that may relax that, kept outside the consumer architecture |
| **Party origin / game origin** | The trusted browser origin for Party surfaces and identity / the separate origin game clients are served from, holding tickets only (ADR 0013; target, not deployed) |
| **Avrana Party Games** | Avrana's fork of LAN Games, where native games such as BLUFF are developed (also called "the fork" or "the games fork" — same repo) |
| **Party Home** | Implemented at `/party/`: roster/host/catalog and, in ADR 0011 source, the Party-owned full-screen setup; runtime revision in SYSTEM |
| **Hub** | Today's LAN Games start page (`/`) with its game tiles — a legacy standalone surface still deployed alongside Party Home; not a product mode and retiring (ADR 0014) |
| **Lobby** | A single game's pre-game waiting room (ready/start), inside that game; Core’s idle `lobby` label maps to the `home` location (`PARTY-LIFECYCLE.md`) |
| **Screen presence** | A TV joined to the party that sees the public view (proposed); never host, seat or voter. "TV view" means what it shows |
| **WORDCLASH, FIFTH SIGNAL, …** | Individual LAN Games titles (WORDCLASH has its own room engine) |
| **Arcade** | The live Gauntlet II stream: one RetroArch → one hardware H.264 encode → WebRTC to phones |
| **PS1 stream** | Shared-stream PlayStation experiment (`ps1-emulation`, title profiles on `experiment/ps1-title-profiles`); bounded supervised evidence in dated findings, no production promotion |
| **Multitap** | A PlayStation adapter that gives one controller port four pads; how 4-player PS1 games get their players |
| **`hello`** | The first WebSocket message a LAN Games client sends; where identity enters a game today |
| **`wc-token`** | LAN Games' browser-held identity token (client-mintable today); retiring as player admission, never a future player identity (ADR 0014) |
| **Game key** | The secret per-(game session, participant) key the platform gives a game instead of any device identity (ADR 0003) |
| **Grant** | The appliance's record of what an installed game may do (trust tier, permissions, assigned path) — decided by the admin, never by the game |
| **Fork cutover** | Replacing the live LAN Games service with the fork plus the party bridge (completed in production 2026-09-27; future updates remain owner-approved) |
| **N2, N4, N5, F1–F8** | Historical roadmap item numbers (retired as a live queue) (N2 = the BLUFF playtest, N4 = PS1, N5 = the platform, F = its foundations) |
| **AP** | The Wi-Fi access point the phones join (the Pi's internal radio, `wlan0`, at `10.42.0.1`) |
| **E1–E8, L1/L2** | Event numbers in the BLUFF playtest runbook; the server (L1) and radio (L2) layers of the load-test plan |
| **PoC** | Proof of concept (an experiment, never production) |
| **PMF** | Wi-Fi Protected Management Frames (an AP security setting some phones dislike) |
| **`party.avrana`** | A test-only name for `10.42.0.1` in the laptop's hosts file (Playwright E2E); unrelated to the machine `avrana` |

---

## References

ADRs `docs/adr/0002-party-platform.md`, `docs/adr/0003-ids-and-keys.md`,
[0012](../adr/0012-limited-mode-party-survives-https-loss.md),
[0013](../adr/0013-party-and-game-browser-origins.md),
[0014](../adr/0014-native-games-isolated-lan-games-retired.md) · strategic roadmap `docs/ROADMAP.md` · BLUFF
lifecycle/security precedent `docs/findings/2026-09-23-bluff-multi-agent-pass.md` · PS1 slots
`ps1/README.md`, `ps1/stream_ps1.py` (branch `ps1-emulation`) · arcade `arcade/README.md` ·
simulations `experiments/party-model/`, `experiments/viewports/` (branch `experiment/party-sim`).
