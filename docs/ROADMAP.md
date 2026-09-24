# Avrana Party — Roadmap

Last updated: 2026-09-24 (platform direction; N5). This is the working plan for the next several milestones.
If it disagrees with an older document, this file and the newest dated `docs/findings/`
entry govern.

---

## Documentation source of truth: the repository, for now

**BookStack still exists** (shelf *Avrana Party*, http://10.0.0.218:6875/shelves/avrana-party),
and it may return as the main project wiki. **But its API/MCP connection is currently
unreliable**: it failed during the 2026-09-19 and 2026-09-20 sessions, and repair attempts
have been volatile and expensive.

Until further notice:

- **Treat the documentation in this Git repository as the working source of truth.**
  Record decisions, findings and progress here (`docs/ROADMAP.md`, `docs/findings/`,
  `docs/adr/`, `CLAUDE-HANDOFF.md`).
- **Do not try to repair BookStack or its MCP** unless the owner explicitly asks.
- Development must never be blocked on BookStack.
- When BookStack is reliable again, reconcile the repo docs back into it.
  `docs/bookstack-update-2026-09-20.md` is an example of a paste-ready hand-off.

---

## Where the project stands

Avrana Party is a portable local-multiplayer appliance: a Raspberry Pi 4 hosts games, and
phones join its Wi-Fi. Game runtimes in view:

| Runtime | Status | Role |
|---|---|---|
| **LAN Games** (`/home/cody/LAN-Games`, `party.local/`, port 8096) | **Live.** 28 browser-native games; lobby, identity, reconnect, per-player views, bots. Upstream (BEACNpool) **retired it in Sept 2026**. It is MIT-licensed and still runs, but gets no updates. | Existing native web-game platform, and the **foundation for new Avrana games** |
| **Avrana Party Games** (fork of LAN Games; dev clone `~/avrana-lab/avrana-party-games/` on `party`; public repo `rcnechamkin/avrana-party-games` not yet created) | **In development**, isolated on port 8196 | Source of Avrana's native games |
| **Arcade streaming** (`arcade/`, `party.local/arcade/`) | **Live prototype.** Gauntlet II via RetroArch + MAME 2010, one shared encode, WebRTC to phones; two iPhones verified. | Traditional/emulated games. **Preserved; not being redesigned.** |

The open arcade work in `CLAUDE-HANDOFF.md` (under-voltage, audio-ratchet fix verification,
recovery gap) stays open and is independent of the game work below.

### Product direction (accepted 2026-09-24): one party, many games

Avrana Party is **not** "a Pi that hosts a bunch of games". It is **a unified local multiplayer
platform whose games plug into a shared Avrana Party system**:

> **The game may change. The party does not.**

Avrana owns identity, session, social, progression, navigation and player management; games
consume those services. Browser-first, guest-first, offline-first; the captive portal is only a
convenience. The runtimes above are the first *consumers* of that platform, not separate products.

Read **`docs/design/PARTY-PLATFORM.md`** (concepts, principles, integration contract, security)
and **`docs/adr/0002-party-platform.md`** (the decision). Phasing is in **N5** below.

---

## The first native game: a Coup-inspired Avrana bluffing card game

**Target (decided 2026-09-23):** an **Avrana-native social bluffing/card game**, using
*Coup* as the mechanical reference. That means:
- hidden role cards
- bluffing about the abilities you hold
- challenging a claim
- blocking actions and challenging the block
- losing influence
- a shared currency
- strong player-to-player interaction, short turns and social deduction

It is **not a Coup clone.** The eventual game gets its own rules, identity, presentation and
assets. No proprietary artwork, branded names or card text are copied.

**Why Coup:** VirtualTabletop's library game named "Diplomacy" turned out to be a Coup-style
game. That's close to what the owner actually wants to explore. The VTT version encodes
only components and a table layout, with no rules automation. Its mechanics are summarised
in `docs/findings/2026-09-23-vtt-coup-reference.md`.

### Decisions

1. **The phone is the complete game client, not a controller.** Each phone shows the shared
   table (all players, coins, remaining influence, revealed cards, whose turn, the pending
   claim), its **own** hidden cards, its available actions, prompts that need its response,
   and a concise event feed. No third screen is required.
2. **The server is authoritative, and private state is filtered at the network layer.** A
   client never receives another player's hidden cards, including cards drawn during an
   exchange. Hiding them with CSS or JavaScript alone doesn't count.
3. **Built as a clean LAN Games module** in the Avrana Party Games fork. It reuses LAN Games'
   identity, reconnect, per-player state views, lobby/ready flow and WebSocket pushes. (This is
   the baseline only; the party platform, N5, later replaces the identity and the lobby/start
   flow through the seat-ticket bridge.)
4. **Baseline first, redesign later.** The first playable loop uses the standard Coup-like
   ruleset as a **temporary mechanical baseline**, with **original working role names** and
   plain placeholder presentation. Its purpose is to prove the whole interaction model:
   hidden roles, claims, challenges, blocks, challenge-the-block, losing influence,
   currency, elimination and winning. Once it plays cleanly on phones, mechanics and the
   game's identity (theme, role names) get deliberately redesigned.
5. **Don't generalise gameplay early.** No universal gameplay framework. *Platform* contracts
   (identity, party, seats, navigation, chat, stats; see N5) grow only when two consumers need
   them, starting from seams the runtimes already share (`session.join`, the lobby lifecycle,
   controller slots). BLUFF must not grow its own chat, profiles or teams; those belong to the
   platform.

### Lessons carried over from the abandoned Diplomacy prototype
- Server-authoritative game state; the client only renders it.
- **Differential masking tests:** prove another player's payload is byte-identical before
  and after a player's private actions. Substring checks are unsound.
- A protocol-level WebSocket check against a running instance, not just unit tests.
- Never let malformed client input raise; accept only choices the server offered.
- Multiple synchronised mobile clients, with reconnect-safe sessions.
- Isolated development: a separate clone, venv and port (`LANGAMES_PORT=8196`), never the
  live `avranaparty-games` service or its venv.

---

## NOW

### N1. Repository docs are the working source of truth — **DONE (2026-09-22)**

### N2. Smallest playable baseline game — **AUTOMATED CRITERIA MET; REAL-PHONE TEST PENDING**
A clean LAN Games module (`games/bluff/`, working title **BLUFF**) in
`~/avrana-lab/avrana-party-games/` (local only, not published), run on port 8196.

Status (2026-09-23, after a six-workstream review: rules audit, mobile UX, lifecycle,
security, simulator, code quality):
- Criteria 1–7 are met in automated testing. That covers ~1,190 tests (rules/fuzz, security
  matrix, lifecycle with a fake clock, and the upstream suite), protocol-level privacy and
  attack scripts, and a full-game simulator with a rules oracle (2–6 players, adversarial,
  timeouts; 0 violations). Phone-size Chromium screenshots cover 2–6 players.
- A phone lifecycle was added:
  - reconnect keeps the seat;
  - a passive autopilot plays for away seats;
  - an empty table pauses, and is abandoned after 5 min (a newcomer may take over after
    60 s);
  - players can Leave game or End game.
- **Still open:** real-iPhone Safari testing, and the known limitations listed in
  `games/bluff/README.md` in that repo.

Developer notes, architecture and test commands: `games/bluff/README.md`.

**Success criteria:**
1. Two to six phones join one game. Each sees its own two hidden cards, and only its own.
2. All phones show the same public table: coins, influence remaining, revealed cards, turn,
   pending claim and event feed.
3. The complete interaction loop works: Income, Foreign Aid, a forced Coup at 10+ coins,
   the five role actions, challenge, block, challenge-the-block, choosing which card to
   lose, exchange, elimination and a winner.
4. Response windows can't stall the game. Everyone passes, or a short timer auto-passes.
5. Differential tests and a protocol-level check prove no client ever receives another
   player's hidden cards or exchange draws.
6. Hold-still test bots let one person drive a full game.
7. Runs on the Pi alongside the live services with no changes to them.

### N3. Preserve existing Avrana functionality (standing rule)
No changes to nginx, dnsmasq/captive portal, NetworkManager/AP, systemd units, the live LAN
Games service or venv, RetroArch/arcade or telemetry without an explicit proposal that
states the blast radius.

*(N4, "PS1 on one shared stream", lives on branch `ps1-emulation` until that branch is merged.)*

### N5. Party platform — **design DONE (2026-09-24); F1–F8 open; build starts after N2**

Design: `docs/design/PARTY-PLATFORM.md`. Decision: `docs/adr/0002-party-platform.md`.

**Rule for now:** documents only. Do **not** touch BLUFF's identity code or the live services
before the N2 real-phone playtest; the playtest must measure the game, not a moving platform.
Add these observations to the playtest instead, because they set the platform's timers and
defaults: how people got into the game, what happened on sleep and reload, any lost seats,
confusion about who starts, whether anyone wanted chat.

**Where the party layer lives (recommended):** a separate small party service on the **same
origin** as everything else (e.g. `party.local/party/`), plus a thin bridge in the Avrana Party
Games fork (the `hello` handshake and the lifecycle push in `core/net.py`, and one line in
`web/hubnet.js` to load `party.js`; WORDCLASH has its own room engine and needs its own bridge or
stays legacy). A separate service lets the party outlive any one game
server and keeps the arcade/PS1 independent of LAN Games. Cost: one more process (~30 MB) and a
systemd unit + nginx location, which need owner approval (N3). Building it inside the fork remains
the fallback.

#### FOUNDATIONAL (design now; build after N2, in this order)

Things whose absence would force rework later. Keep this list short.

| # | Item | Done when |
|---|---|---|
| F1 | **IDs and keys ADR:** opaque server-issued ids for party, device, presence, seat (profile reserved); names never authorize; map today's `wc-token`, PS1 slot token and arcade slot onto seats | ADR merged with an "id → what it authorizes" table |
| F2a | **Single origin, dev:** a dev-only front (e.g. the party service proxying the fork on 8196) that puts party + games under one host and a `/party/` namespace, without touching live nginx | The vertical slice runs on one origin |
| F2b | **Single origin, live** (with the fork cutover): canonical `party.local`, `/party/` namespace, PS1 behind nginx, app Host allowlist while the default server keeps answering captive-portal probes; `10.42.0.1` redirects only after `party.local` is verified to resolve on iPhone and Android | Every runtime reachable under one host (owner-approved nginx change) |
| F3 | **Device token:** server-issued, HttpOnly SameSite=Lax cookie, hashed at rest; Origin checks on WebSocket/POST (on the F2a origin first) | Survives reload and sleep on iPhone Safari; a client cannot mint one |
| F4 | **Party service:** one Party per appliance (v0), party socket, versioned snapshot + append-only event log | A reconnecting phone gets the current party state in one message |
| F5 | **Presence + Seat + seat ticket v1:** guests as "Player N" with rename; seat = party × game session × slot with grace and same-presence takeover; the fork bridge substitutes a per-seat key at `session.join` | Fabricated tokens cannot take seats; a reload keeps the same seat |
| F6 | **Host authority:** host is a presence; voluntary transfer; grace then succession; no "claim host"; Host ≠ Admin | Host-only actions rejected for others; a sleeping host is succeeded and returns as a player |
| F7 | **Manifest v0:** derived from the LAN Games registry; static JSON for BLUFF, arcade, PS1 titles | One API lists every runtime with players, TV need and control model |
| F8 | **Event record with provenance** (draft envelope in `docs/design/PARTY-PLATFORM.md` §14) | Every lifecycle event carries provenance; emulated games can only emit `platform_observed` unless a per-game adapter exists |

Critical path: dev origin (F2a) → device token → party state → presence → seats + host →
navigation. The live cutover (F2b) comes later, together with the fork cutover.

#### NEAR-TERM (after the foundations)

- **First vertical slice — "the party follows the host":** the party service on a dev port behind
  a dev-only single-origin front (never the live nginx), BLUFF plus one other fork game, three real
  phones. Done when: phones open one URL and appear as Player 1–3 (one renames); the first presence
  is host; the host picks BLUFF and every phone enters it seated, without tapping; at game end
  everyone returns to Party Home; the host picks the second game and the same people get seats; a
  phone locked for 2 minutes wakes into its own seat; a reload creates no second seat; fabricated
  tokens get no seat; a sleeping host is succeeded and returns as a player; a late fourth phone
  becomes a spectator. **Excluded:** profiles, PINs, chat, voting, teams, stats computation,
  achievements, arcade/PS1, TV view, QR pairing, captive portal, live nginx, live LAN Games.
- **Server-only system events** ("SYSTEM: Audrey is now Host."); client-sent "SYSTEM" rejected.
- **Spectator role** as a presence with no seat (late joiners, overflow).
- **Admin PIN** (no default; set over SSH or a one-time code on the TV; scrypt; global backoff;
  recovery by deleting a file over SSH). Required before profiles or any destructive control.
- **Fork cutover + live single origin (F2b):** the fork plus bridge replaces the live LAN Games
  service and nginx gets the single-origin layout (owner-approved; full regression run of all
  games; captive-portal probes verified unchanged).
- **Emulated-game activation** (after the power fix, N4): PS1 accepts a seat ticket; the party
  service starts the stream, waits for readiness, then broadcasts navigation.

#### MID-TERM

Profiles v1 ("Keep this player", name/avatar/persona, "Welcome back" picker, admin-only delete) ·
queue and voting (casual queue + timed vote rounds; votes per presence per round; spectator voting
off by default (proposed); host decides) · party chat (public channel + system events; replaces BLUFF-local
chat ideas) · stats v1 and party recap (participation is `platform_observed`; wins only from
authoritative events) · teams (cross-game scoring only for games whose manifest reports team
results) · the private player panel contract, extracted from BLUFF only when a second native game
needs it.

#### LONG-TERM / OPTIONAL

Achievements and cosmetics · party history and rivalries · optional profile PIN · device trust and
revocation UI · QR pairing · profile merge/export/import · whispers and team chat · the full
profile-settings categories · playlists and tournaments · result adapters for emulated games ·
several parties per appliance.

#### UX risks the phasing is designed around

Forced navigation interrupting someone (seated players follow; others get a banner and a "Go"
button) · absent or sleeping host (grace, succession, system event) · phones sleeping (snapshot on
wake, seat grace, BLUFF autopilot; timers from N2 data) · refresh creating duplicate seats or votes
(keys per presence) · spectators swinging votes (off by default) · the captive-portal browser's
throwaway cookie jar (it only says "open party.local") · two guests named "Cody" (ids authorize,
names don't) · slow emulator start ("Starting…", host can cancel) · setup friction ("Keep this
player?" only after the first game).

---

## NEXT (after the baseline plays cleanly on real phones)

- **Deliberate redesign** of the game's mechanics and identity: an original theme, role
  names, abilities and rules text.
- Mobile UX polish: large touch targets, clear response prompts, turn and pending-claim
  clarity, a readable event history.
- Player-count range and balance (the VTT reference also scales to 7–10 players).
- Reconnect/rejoin verified on real phones (sleep, reload, network drop).
- Publish `rcnechamkin/avrana-party-games` once the owner creates the repository and approves.
  A verified full backup exists on the laptop (`~/avrana-party-games.git`, 2026-09-23). Push
  `main` only, never `abandoned/classic-diplomacy`.
- **Platform foundations F1–F8 and the first vertical slice** (N5).

## LATER / EXPERIMENTAL

- **Chat / social messaging** is now a *platform* feature (N5 mid-term: party chat, then team
  chat and whispers). BLUFF should consume it rather than build its own.
- Original art and assets, animations and sound.
- ~~Integrate into the main Avrana launcher / `party.local` hub~~ — superseded by the platform's
  single origin (F2a dev, F2b live) and synchronized navigation (N5 vertical slice).
- An optional shared TV/table view (spectator only; must never show hidden cards). Proposed: in
  platform terms this is the spectator role (N5 near-term).
- VirtualTabletop as a separate generic tabletop runtime. Its HTTP endpoints are
  unauthenticated (`PUT /state/:room`, `POST /quit`), so it must be fenced first.
- Additional native Avrana web games.
- Heavier streamed games (Moonlight/Sunshine or similar) for the arcade runtime.
- Reconcile repo docs back into BookStack once its integration is reliable.

## Explicitly not doing

- Repairing BookStack (unless asked)
- **A universal gameplay framework or engine.** Avrana provides *platform services around* games
  (identity, party, seats, navigation, chat, stats) through a small versioned contract: a
  manifest, a seat ticket, an event record and the `party.js` follow client. Rules, state,
  rendering and turn logic stay with each game. (See `docs/design/PARTY-PLATFORM.md` §1.)
- Cloud accounts, email sign-up, or anything that needs the internet
- An iframe shell or a single-page rewrite that absorbs every game (iframes may return later
  only for overlays such as chat on same-origin games; see ADR 0002)
- Copying Coup's branding, art or card text
- Removing or redesigning the arcade path
- **Classic map-based Diplomacy** (see below)

---

## Abandoned experiments

### Classic Diplomacy / `diplomacy/diplomacy` — ABANDONED (2026-09-23)

Classic map-based Diplomacy was pursued from a misunderstanding of the target. **It is not
the goal.** Don't continue it.

What exists, kept for reference only:
- Engine validation on the Pi:
  `docs/findings/2026-09-22-diplomacy-engine-on-pi.md`, `experiments/diplomacy/`
- A local prototype commit `e88120d` on branch **`abandoned/classic-diplomacy`** in
  `~/avrana-lab/avrana-party-games/`. **Never pushed; do not push or integrate it.**
- The spike venv `~/avrana-lab/diplomacy-spike/`, which is disposable.

The AGPL-3.0 obligations discussed for that work applied **only because of the
`diplomacy/diplomacy` engine**. The new game uses no AGPL code, so it can stay MIT like
upstream LAN Games.

---

## Dependencies, constraints and open questions

- **Licensing:**
  - Avrana Party Games keeps upstream's MIT `LICENSE` unchanged, plus a `NOTICE.md`.
  - The Sora and JetBrains Mono fonts bundled upstream are SIL OFL 1.1; their licence texts
    are added beside the fonts.
  - LAN Games' chess games depend on python-chess (GPL-3.0+) at runtime; it is not bundled.
  - Game mechanics aren't copyrightable, but names, art and text are. Keep everything
    original. This is not legal advice.
- **LAN Games is upstream-retired.** Avrana owns its maintenance.
- **Pi power.** Recurring under-voltage is still open (see handoff). A card game is light,
  but don't load-test it and the arcade at the same time until power is fixed.
- **Test path.** Client-facing tests run from a device on the *Avrana Party* Wi-Fi
  (`10.42.0.1`), not the Pi's home-LAN address.
- **Workflow (2026-09-24).** Laptop → GitHub → Pi. Edit and commit on the laptop; push feature
  branches and test them in the Pi dev checkout (`~/avrana-lab/avrana-party-docs`, fast-forward
  only); merge to `main` on the laptop and `git pull --ff-only` in `/home/cody/avrana-party` to
  deploy. The Pi is a deploy/test target, not a development workstation, and should eventually be
  pull-only from GitHub. Experiments live under `~/avrana-lab/` on the Pi, never inside the deploy
  checkout or live service directories.
