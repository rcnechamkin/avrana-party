# Avrana Party platform: party, identity, seats

Status: **design direction (accepted 2026-09-24); nothing here is built unless marked EXISTS.**
Decision record: `docs/adr/0002-party-platform.md`. Sequencing: `docs/ROADMAP.md`, item **N5**
(foundational F1–F8, near-term vertical slice, mid-term, long-term).

This document is the reference for what Avrana Party *is* as a product and how its parts relate.
Read it before designing anything a player touches: a new game, a lobby, a login, a chat, a stat.
It is written for an engineer or agent arriving months from now with no other context.

---

## 1. The thesis

Avrana Party is **not** "a Pi that hosts a bunch of games". It is **a unified local multiplayer
platform whose games plug into a shared Avrana Party system.**

> **The game may change. The party does not.**

Avrana Party owns the **social, identity, session, progression, navigation and
player-management** layers. Games consume those services instead of reinventing them.

A group of people joins a *party* once. The party then moves from BLUFF to Bomberman to Worms to
Gauntlet, keeping the same people, names, seats, teams, host and running score. Nobody re-joins,
re-names or re-navigates for each title.

### What this is not

- **Not a universal gameplay framework.** The platform does not dictate how a game implements its
  rules, rendering or netcode. A LAN Games module, a streamed emulator and a future native game
  each keep their own engine. The platform provides *party services around* games
  (who is here, who sits where, who decides, what happens next, what counted). This is why
  `docs/ROADMAP.md` still says "no universal gameplay framework": both statements are true.
- **Not a social network, not cloud accounts.** Everything is local to the appliance and works
  offline. No email, no sign-up, no internet dependency.
- **Not captive-portal-dependent.** The captive portal is a convenience that opens the page for
  you. The product must work fully if it disappears.

---

## 2. Product principles

These are durable. A design that breaks one needs an explicit, recorded reason.

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

---

## 3. The product surface: browser-first, offline-first

```
Join the Avrana Wi-Fi  ->  open party.local  ->  the browser is the player's complete interface
```

The browser is responsible, over time, for: identity/profile selection, the party lobby, game
navigation, controller UI, WebRTC video, WebSocket input, chat, private information, voting,
achievements and stats, profile settings, and reconnection.

Consequences:

- **One canonical origin.** Everything a player uses is served from one host (e.g.
  `http://party.local/…`) through nginx. A different host name (`10.42.0.1` vs `party.local`)
  gets a separate cookie jar; a different port (`:8198`) shares cookies but gets separate
  localStorage and a different Origin. Either way a player can look like a different device on
  each game. Other names (`10.42.0.1`, the captive-portal mini-browser) redirect to the canonical
  host. Note that cookies ignore ports, so a dev instance on another port of the same host
  receives production cookies.
- **`party.local` must actually resolve.** Today it resolves only over mDNS (the AP's DNS has no
  record for it), and Android's `.local` support is uneven. Before `10.42.0.1` redirects to it,
  verify resolution on iPhone and Android, or add a DNS record in the AP's resolver (a live
  change; ask first).
- **Plain HTTP on a LAN.** Browsers treat it as a non-secure context. Designs must not depend on
  `Secure` cookies or secure-context-only Web APIs. No TLS on guests' phones (see §15).
- **Captive portal = convenience.** It may pop the page open. Never select a profile or trust a
  device inside the captive-portal mini-browser (it has its own cookie jar and closes itself).

---

## 4. Core concepts

Do not collapse "player" into one object. These are distinct on purpose.

| Concept | What it is | Lifetime | Key |
|---|---|---|---|
| **Party** | The persistent unit people join: host, members, seats, current game, queue, teams, chat. | One evening (survives game changes; ideally survives a reboot) | `party_id` |
| **Device** | A recognized browser installation. | Months; revocable | server-issued random token in a cookie (hash stored) |
| **Profile** | A persistent human identity: name, avatar, preferences, history, stats, achievements. | Indefinite; optional | `profile_id` (opaque UUID) |
| **Guest** | A participant with no saved profile ("Player 3", renamed "Megan"). | The party | `presence_id` |
| **Presence** | A profile or guest currently participating in a party, on one or more devices. | The party | `presence_id` |
| **Seat** | A temporary binding: presence → a player/controller slot in the current game. | One game session; the party's *seating* carries forward (§10) | `seat_id` (+ reclaim ticket) |
| **Role** | Host, Player, Spectator (party roles); Admin (appliance role); game-specific roles. | Varies | — |
| **Persona** | A temporary display identity: profile *Cody*, tonight *Admiral Worm*, in BLUFF *Definitely Not The Duke*. | Party or game | on the presence/seat |
| **Device trust** | Whether a device may pick a saved profile without its PIN. | Until revoked | device↔profile link |
| **Team** | A named group of presences above any single game. | The party | `team_id` |

```
 Device (browser, cookie) ──recognizes──▶ Profile(s) it may offer ("Welcome back")
      │
      └─opens─▶ Presence in a Party  (profile or guest, with a persona)
                    │
                    ├─ Role in the party: Host? Player? Spectator?
                    ├─ Team membership (optional)
                    └─ Seat in the current game  ──▶ game player/controller slot
```

### Which key does a game see?

A game receives a **seat key** (and the persona to display), never the device token and never
the profile's secrets. A game may keep keying its own state by whatever opaque string it is given.
Today every LAN Games game keys state by a per-device token; the platform substitutes a
per-seat key at the connect handshake (§14), so existing games need no internal changes.

---

## 5. Guest-first

- Joining never requires a profile. Default names are **Player 1, Player 2, Player 3**.
- A guest can rename immediately: *Player 3 → Megan*.
- Later, at any time: **"Save Megan as a profile?"** If saved, the stats and history Megan
  accumulated as a guest during this party move to the new profile (with their provenance).
- Wording: **Save Player**, **Save Profile**, **Keep this player**. Avoid "Create Account".
- Everything degrades gracefully to anonymous guests: no profile, no PIN, no device trust.

---

## 6. Saved profiles

**Identity:** persistent display name, avatar, aliases/personas.
**Access:** optional profile PIN; trusted devices; revoke/forget a device; many devices per
profile; many profiles per device.

- **Player profile PIN: optional.** **System Admin PIN: required.**
- A remembered device means *"I recognize this browser"*, not *"this browser is Cody"*. A
  recognized phone shows:

  ```
  Welcome back
  [Cody]  [Audrey]  [Someone else]  [Guest]
  ```
- The device token is random and server-issued. **Never** use Wi-Fi MAC addresses (phones
  randomize them) or device fingerprinting as identity.
- A profile without a PIN runs on the honour system, and the UI says so. If its owner is already
  present, a second device needs a trusted device (or the PIN, if one is set) to take it.

### Profile lifecycle

Guest → saved profile promotion · many devices per profile · many profiles per device · optional
PIN · aliases/personas · recent players · trusted-device revocation · deletion (history shows
"Deleted player" so others' records stay true) · duplicate merge (admin-only; moves history, never
access) · export/import (versioned JSON, no secrets) · QR pairing of a new device with a
short-lived single-use code (never exposes a permanent device token). Stable opaque IDs throughout
so data stays portable. No cloud identity.

### Profile settings (categories, not a UI spec)

| Category | Examples |
|---|---|
| Identity | name, avatar, aliases |
| Access | optional PIN, trusted devices, forget/revoke device |
| Controls | handedness, button layout and size, vibration/haptics, controller preferences |
| Accessibility | larger UI/text, high contrast, reduced motion, colorblind-friendly choices |
| Privacy | lifetime stats public to the party?, show/hide playtime, rivalry history, recent games |
| Social | chat/whisper preferences; mute/block later if needed |
| Gameplay | preferred seat where practical, per-game preferences, favorite games |
| Cosmetics | avatar frames, badges, achievement showcase, unlocked themes/icons (later) |

LAN Games already keeps sound, haptics, reduced-motion and contrast preferences in the browser;
those are the seed of the Controls/Accessibility categories.

---

## 7. Admin vs Party Host

These are **entirely separate**. A host can never escalate to admin.

| | **System Admin** | **Party Host** |
|---|---|---|
| What | Persistent privileged appliance identity | Temporary role inside one party |
| Credential | **PIN/password required** (no default) | None; no admin PIN |
| Powers | Network, updates, storage, profile management (merge, delete, reset PINs), dangerous system configuration | Select/start the game; change game rules; pause/restart/end; manage spectators; remove/reassign seats; moderate party chat; rematch/next-game; run voting |
| Cannot | — | Touch profiles, devices, PINs or admin settings; see other players' hidden game state |

- **Normal players** always keep authority over their **own** profile, controls, avatar/persona
  and accessibility preferences.
- **Transfer:** the host may hand the role to anyone present.
- **Disconnect:** the host gets a reconnect grace period, then **succession** (e.g. the
  longest-present connected player). A returning former host does **not** automatically take it
  back.
- There is no "claim host" action. Host changes only by voluntary transfer, succession, or admin
  override.

---

## 8. The Party

Players join a **party**, not individual games. (The tree below is illustrative, not a schema.)

```
Party
├── id
├── host              (presence_id)
├── state             lobby | launching | in_game | intermission
├── active_game       (manifest id + instance)
├── presences         (profile or guest, persona, devices, connected/away)
├── seats             (for the active game)
├── spectators
├── teams
├── queue             (nominations, votes, playlist)
├── votes             (per round, per presence)
├── chat / channels
├── nav               { seq, target }   ← what every browser should be showing
└── started_at
```

The party moves **BLUFF → Bomberman → Worms → Gauntlet** without anyone navigating manually.
One party per appliance is the default assumption (see Open questions).

### Party Home

Not just a launcher. Eventually it shows who is present, who is host, who is ready, who is
spectating, the current game, recent games, the queue and vote status, party stats and
reconnect state:

```
AVRANA PARTY
Cody      Host       Ready
Audrey               Ready
Nick                 Ready
Sam       Spectator

NOW PLAYING   Worms Armageddon
UP NEXT       Bomberman   4 votes
              BLUFF       2 votes
```

---

## 9. Synchronized navigation

Today (LAN Games) each person clicks into each game separately. That is wrong for this product.

```
Host selects Bomberman
  → authoritative party state changes (nav.seq += 1, nav.target = bomberman)
  → server broadcasts the transition
  → EVERY connected party browser follows automatically
  → profiles, personas, seats and roles persist
```

- **Mechanism (proposed):** top-level page navigation driven by a tiny shared `party.js` that
  holds one party WebSocket, knows the party's `nav.seq`, and navigates only to URLs listed in
  game manifests. Not an iframe shell (games assume they own the page: safe areas, fullscreen,
  audio unlock, iOS gestures), and not a single-page rewrite of every game.
- **"What is my party doing?"** A phone that slept, reloaded or lost Wi-Fi asks on wake and is
  taken to the current state. The nav sequence number makes this idempotent.
- **Emulated games need activation.** Selecting a streamed game means the party service first
  starts that game's stream service, waits until it reports ready, and only then broadcasts the
  navigation. Only one emulated game can run at a time on the Pi (one hardware encoder budget,
  CPU, power).
- **Detours.** A player who deliberately opened their profile or settings should get a prompt
  ("The party moved to Bomberman — Go"), not be yanked mid-edit. (Open question: exact policy.)

---

## 10. Seats

Seat is a first-class concept:

```
Device/browser session → party presence → seat → profile OR guest → controller/player slot → game
```

Seat states: `open → occupied → disconnected (grace; neutral input) → away (reserved; autopilot
or idle) → released | reassigned by host`.

Seats support: disconnect grace, **neutral input while disconnected** (release every button),
reclaim on reconnect (same presence, same seat), game-specific slot assignment, a spectator state
where no controller exists, and team membership.

One live connection per seat. A newer connection replaces the older one only if it belongs to the
same presence (same device, or the seat's reclaim ticket).

**Seats are per game session; seating is per party.** Each new game session gets fresh seats,
pre-filled from the party's current seating (who sits with whom, team, preferred slot) wherever
the next game's slots allow. That is how "existing seats persist" across BLUFF → Bomberman
without pretending a 6-seat card game and a 4-pad console share slot numbers.

**Already close to this today:** the PS1 stream's slot table (server-minted token per slot,
constant-time reclaim, one socket per token, 30 s grace, neutral input, spectators when full) and
BLUFF's presence/grace/autopilot model. See §16.

---

## 11. Teams

Where games support it, Avrana understands teams **above** the individual game:

```
Team Purple: Cody, Audrey        Team Orange: Nick, Megan

Bomberman → Purple wins   BLUFF → Orange wins   Worms → Purple wins
Party score: Purple 2 · Orange 1
```

Compatible games reuse the party's teams. Games that cannot meaningfully report team results do
not participate. **Never fake a team result.**

---

## 12. Social layer

### Chat and system events

Channels: **public party chat**, **team chat**, **private whispers**, **game-defined channels**,
**system events** (`SYSTEM: Audrey is now Host.` / `SYSTEM: Nick joined the party.`).
System events are a separate message type emitted only by the server; no player name can
impersonate them. The host moderates party chat.

### Private player panel

Native games may use a universal **private player panel** on the phone for hidden roles, cards,
private inventory, secret objectives, private prompts, votes and decisions. The shared public view
(TV or everyone's table view) and the private phone view coexist. BLUFF's per-viewer masked state
is the working example; private data is filtered on the server, never hidden with CSS.

### Spectators

A first-class role, not a failed player slot. Spectators see the shared stream or public state,
chat, optionally vote (party setting), and can join a later round or be promoted into a seat by the
party flow. They never receive controller ownership unless promoted. The server rejects their input.

### Queue and voting

Avrana helps the party decide what's next, which matters when players are physically apart
(several rows apart on a plane) and can't negotiate by talking.

- Anyone nominates; the party votes; **the host has final authority.**
- Votes public or hidden; spectator voting per party setting.
- The game list filters itself by current player count, TV/HDMI requirement, control model,
  approximate session length and platform capability (from manifests).
- Modes: **casual queue** (upvotes reorder), **vote round** (selected candidates, timed),
  **playlist** (a sequence with voting/reordering). A round may end early when all eligible voters
  have voted.
- **Votes belong to party presence, not to browser connections**: refreshing, reconnecting or a
  second tab never adds a vote. Eligibility is fixed when the round opens.

---

## 13. Progression: stats, achievements, history

### Stats need provenance

| Provenance | Meaning | Example |
|---|---|---|
| `authoritative_game_event` | The game itself reported it | BLUFF winner, eliminations, challenge outcomes |
| `platform_observed` | The platform saw it happen | Cody held Bomberman slot 2 for 14 minutes |
| `manually_recorded` | A person entered it (only if ever supported) | "Purple won Worms" typed by the host |

- **Native Avrana games** can report rich authoritative events.
- **Emulated games** (arcade, PS1): the platform always knows participation, session duration and
  controller ownership, but **not** results. Future per-game adapters might add more; until then,
  none.
- **Never claim a win or result from participation alone.** Hot-seat games (Worms on one pad)
  cannot even attribute turns to people.
- Record flags that change a result's meaning: bot seats, autopilot turns, wins by forfeit,
  abandoned games (never a win).

### Achievements

Platform achievements (played N games / N distinct titles / with N different people; tournament
participation), game achievements (defined by games that support them), and social/party
achievements (wins across several games in one party, team achievements, rivalry milestones).
They may unlock local cosmetics (frames, badges, icons, themes). No monetization. Achievements may
only be derived from stats whose provenance supports them.

### Party history and rivalries

Games played together, recent players, frequent teammates, head-to-head records where trustworthy,
party-night recaps, favorite games, session history. Local relationship history from shared play;
**not** a social network.

---

## 14. Game integration contract (draft)

A game joins the platform through **four small, optional pieces**. Without them it keeps working
exactly as it does today.

1. **Capability manifest** — what the game supports (below).
2. **Seat ticket handshake (v1)** — the party issues a short-lived ticket; the game page sends it
   as the **first WebSocket message** (never in the URL, which nginx would log); the game verifies it
   (localhost call to the party service, or an HMAC with a local key) and uses the ticket's seat key
   and persona instead of minting its own identity. No ticket → legacy behavior.
3. **Event sink** — the game (or a thin observer next to it) reports lifecycle events. Draft
   envelope (the one used everywhere in these docs; not frozen):
   `{v, party_id, game_id, instance, ts, kind, presence_id, seat_id, provenance, data}`, with kinds
   such as `session_started`, `session_ended{completed|abandoned}`, `seat_joined`, `seat_left`,
   `result`, `stat`. The sink rejects `result` events from a game whose manifest says
   `results: none`.
4. **`party.js` follow client** — included on the game page (for LAN Games, injected once by the
   shared `hubnet.js`) so the page follows party navigation and offers "Party Home".

Games must **not**: invent their own login or profile store, trust client-supplied names or ids
for authorization, key permanent records by device token, or depend on the party service being up
to run standalone.

### Capability manifest v0 (draft — do not freeze yet)

```json
{
  "manifest": 0,
  "id": "ps1-bomberman",
  "title": "Bomberman Party Edition",
  "kind": "emulated",
  "players": {"min": 1, "max": 4},
  "input": {"model": "controller_slots", "slots": 4},
  "video": "shared_stream",
  "screen": "tv_optional",
  "session_minutes": [5, 20],
  "profiles": "platform",
  "spectators": "watch",
  "teams": "none",
  "private_ui": false,
  "chat": "platform",
  "results": "none",
  "persistent_stats": "platform_observed",
  "achievements": false,
  "launch": {"mode": "service", "exclusive": "emulator"},
  "seat_handshake": "none",
  "follow": "none",
  "entry": "/ps1/"
}
```

`kind`: `native` | `lan_games` | `emulated`. `input.model`: `browser_native` | `controller_slots` |
`hotseat`. `screen`: `none` | `tv_optional` | `tv_required`. `session_minutes`: rough
[min, max] for the vote filter. `profiles`: `none` | `platform` (uses platform identity/persona).
`spectators`: `none` | `watch` | `participate` (spectator mechanics). `teams`: `none` | `in_game` |
`party`. `results`: `none` | `authoritative`. `launch.mode`: `always_on` | `service`. Field names
and enums are a draft; expect them to change when the first two consumers use them.

Drafts for today's titles (derived from the code, 2026-09-24):

| id | kind | players | input | video | spectators | private UI | results | launch |
|---|---|---|---|---|---|---|---|---|
| `bluff` | native (LAN Games module) | 1–6 (bots fill) | browser_native | none | watch (bounded, 6) | yes | authoritative | always_on |
| `arcade-gauntlet2` | emulated | 1–2 | controller_slots (2) | shared_stream | none (409 when full) | no | none | service (live) |
| `ps1-bomberman` | emulated | 1–4 | controller_slots (4, multitap port 2) | shared_stream | watch | no | none | service |
| `ps1-worms` | emulated | 1–4 people, 1 pad | hotseat (1 slot) | shared_stream | watch | no | none | service |
| LAN Games titles | lan_games | from `REGISTRY` `min_p`/`max_p` | browser_native | none | watch (watch sockets) | per game | none until a game adds a results hook | always_on |

LAN Games manifests should be **derived** from the existing registry entries (which already carry
min/max players, solo, tv, category and an `EXTERNAL` list), not hand-written for every game.

---

## 15. Security model (proportionate)

Threats: mischievous guests on the same Wi-Fi (impersonation, stat spoiling, double voting, host
grabbing), cookie sniffing on an open or shared-password network, and web pages on a phone that
also has mobile data. Anyone with SD-card or SSH access is an admin by design.

(Specific parameters below — key sizes, timeouts, hash settings — are suggestions to confirm
when built.)

**MUST before profiles ship**
- Server-issued device token: `secrets.token_urlsafe(32)` in an `HttpOnly; SameSite=Lax; Path=/`
  cookie (no `Secure`: impossible over HTTP); store only its SHA-256; revoke = delete the row. The
  token only unlocks the "Welcome back" picker; it never grants admin and never skips a PIN.
- One canonical host; nginx allowlists the app's host names (this also closes DNS rebinding
  against Origin checks). The default server must keep answering the captive-portal probe paths
  (e.g. `captive.apple.com/hotspot-detect.html`) exactly as today, and return 444 only for
  everything else. Regressing the probes breaks the live captive portal.
- Origin check on every WebSocket upgrade and POST once identity rides on a cookie; GET never mutates.
- Authorization only from server-resolved ids (`profile_id`, `presence_id`, `seat_id`), never from
  display names or client-sent ids.
- Admin PIN: no default, ≥ 6 digits; first set over SSH/console or via a one-time code shown on the
  TV (whoever reaches the Wi-Fi first must not be able to claim it). `hashlib.scrypt`, constant-time
  compare, global backoff (never a permanent lockout). Stored in its own 0600 file; recovery =
  delete that file over SSH or from the SD card. Admin sessions: short-lived, `SameSite=Strict`,
  separate path, anti-CSRF token.
- Host ≠ Admin (§7). System chat messages are server-only; reserve names like SYSTEM, Admin, Host.
- Votes keyed per round per presence. Seats: one live connection, same-presence takeover only,
  server rejects spectator input.

**SHOULD** — optional profile PIN (4–6 digits, scrypt) whose real protection is rate limiting that
cannot be used to lock the owner out (trusted devices skip it); QR pairing with single-use 3-minute
codes in the URL fragment; tokens never in URLs or logs; SQLite with WAL and regular backups
(the Pi has a history of under-voltage resets); store names, avatars, preferences and stats only.

**LATER** — guest→profile promotion, admin-only merge with a `merged_into` pointer, deletion as
"Deleted player", export without secrets, admin UI reachable only from the home LAN.

**Deliberately not doing** — TLS on guests' phones, JWTs, token rotation schedules, encrypted
databases, Argon2 dependencies, device fingerprinting, email recovery, CAPTCHAs.

Top pitfalls: trusting client-supplied identity; cookies without Origin checks and a host allowlist;
split origins creating phantom devices and double votes; lockouts that can be weaponized; secrets
leaking through URLs, logs, exports or host views.

---

## 16. What already exists (2026-09-24)

(`ps1/…` paths are on branch `ps1-emulation` until it is merged; LAN Games/BLUFF paths are in the
Avrana Party Games fork.)

| Concept | Today | Where |
|---|---|---|
| Device | **Partial.** LAN Games keeps a `wc-token` in localStorage that the *client* can mint; the server accepts any well-formed token. PS1 mints its own slot token. Arcade has none. | games fork `web/hubnet.js`, `core/net.py`; `ps1/stream_ps1.py` |
| Profile | **Partial, device-local.** Name, avatar, photo and preferences live in the browser; only the photo is stored server-side (by token hash). | `web/hubnet.js`, `core/avatars.py` |
| Presence | **Partial, per game.** `connected` flags; BLUFF has here/reconnecting/away/left/bot. | `core/session.py`, `games/bluff/game.py` |
| Seat | **Partial.** PS1 slot table is the closest match; BLUFF seats; LAN Games participants locked at start; arcade first-free slot freed instantly. | `ps1/stream_ps1.py`, `arcade/stream.py` |
| Roles | Player and Spectator only. **No Host, no Admin**: any ready player starts a game; anyone changes settings or clears chat. | `core/session.py`, `core/chat.py` |
| Party / synchronized nav | **Absent.** One room per game per process; each phone navigates itself; game end returns to that game's lobby. | `server.py`, `web/hub.js` |
| Reconnect / grace | Exists three different ways (LAN Games token reclaim, BLUFF 30/60 s + autopilot, PS1 30 s); arcade none. | as above |
| Spectators | Exist in LAN Games (watch sockets), BLUFF (bounded), PS1; not arcade. | as above |
| Private player surface | Exists as a per-game pattern (server-side masked state; BLUFF's `me` block). | `core/session.py`, BLUFF |
| Chat | One hub-wide in-memory room; client-asserted names ("SYSTEM" is spoofable); anyone can clear. | `core/chat.py` |
| Manifest | **Proto-manifest**: registry entries with min/max players, solo, tv, category; `EXTERNAL` list; served at `/api/games`. | `games/registry.py`, `server.py` |
| Stats, achievements, voting, teams across games, admin | **Absent** (per-game teams exist, e.g. Family Feud). | — |

### Known collisions with this design

1. The device token is the person key inside every LAN Games game, chat and avatars. Separation
   must happen at the handshake (substitute a seat key), not by rewriting games.
2. Client-mintable tokens contradict server-issued identity and one-vote-per-presence.
3. Each LAN Games game owns its own lobby/ready/start; anyone ready can start (no host authority).
4. Separate processes and origins: PS1 on `10.42.0.1:8198` directly; LAN Games owns `/`; the party
   layer has no URL namespace yet. Fixing this is an nginx change to a live system (needs approval).
5. Three different grace models.
6. LAN Games names are capped at 14 ASCII characters ("Definitely Not The Duke" would not fit).
7. LAN Games is upstream-retired code running live; every change is fork divergence.

### Smallest seams for attaching the platform later

- The LAN Games connect handshake (`hello` → `session.join(token, name, avatar)`) is the one place
  identity enters a game: accept an optional seat ticket there.
- `web/hubnet.js` is loaded by every LAN Games client: inject `party.js` once.
- **Exception: WORDCLASH** has its own room engine and does not load `hubnet.js`; it needs its own
  small bridge or stays legacy (no party integration) until someone needs it.
- `GameBinding.push_all` sees `game_start` / `game_end` / back-to-lobby: a read-only observer can
  emit lifecycle events.
- The registry + `EXTERNAL` list becomes manifest v0.
- PS1's `claim()` can validate a party-issued ticket instead of minting a token.

---

## 17. Open questions

1. Party service: a separate small service or part of the LAN Games fork? (See ROADMAP.)
2. URL layout for one origin (`/` = Party Home? LAN Games under a prefix?) — a live nginx change.
3. Migration from LAN Games' client-minted `wc-token` to a server-issued device cookie without
   breaking the live service.
4. One party per appliance, or several?
5. Forced-navigation policy when a player is mid-detour (settings, profile).
6. Does a party survive a Pi reboot or power loss? (Given the power history: it should.)
7. Hot-seat attribution (Worms): accept that turns can't be attributed, or add a manual step?
8. A shared TV/HDMI display: is it a special "screen" presence with no seat? (Proposed default:
   treat it as the spectator role, per ROADMAP N5.)
9. Whether spectators can nominate. (Proposed default for voting: off, per ROADMAP N5.)
10. Mapping party teams onto games with their own in-game teams.
11. Name length and Unicode (LAN Games truncates to 14 ASCII).
12. Profile database location, backup cadence and restore procedure on the SD card.
13. Admin surface on the guest Wi-Fi vs home LAN only.
14. Host-less parties (a kiosk/TV-driven party with no phone host).

---

## References

- ADR: `docs/adr/0002-party-platform.md`
- Roadmap and phasing: `docs/ROADMAP.md`
- BLUFF lifecycle/security precedent: `docs/findings/2026-09-23-bluff-multi-agent-pass.md`
- PS1 seats/slots precedent: `ps1/README.md`, `ps1/stream_ps1.py` (branch `ps1-emulation`)
- Arcade stream: `arcade/README.md`, `arcade/stream.py`
- LAN Games / BLUFF code: the Avrana Party Games fork (`games/registry.py`, `core/`, `web/hubnet.js`)
