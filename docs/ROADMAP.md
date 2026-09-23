# Avrana Party — Roadmap

Last updated: 2026-09-23. This is the working plan for the next several milestones.
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
   identity, reconnect, per-player state views, lobby/ready flow and WebSocket pushes.
4. **Baseline first, redesign later.** The first playable loop uses the standard Coup-like
   ruleset as a **temporary mechanical baseline**, with **original working role names** and
   plain placeholder presentation. Its purpose is to prove the whole interaction model:
   hidden roles, claims, challenges, blocks, challenge-the-block, losing influence,
   currency, elimination and winning. Once it plays cleanly on phones, mechanics and
   identity get deliberately redesigned.
5. **Don't generalise early.** No universal Avrana game framework until this game shows
   which abstractions are actually useful.

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

### N2. Smallest playable baseline game — **IN PROGRESS**
A clean LAN Games module in `~/avrana-lab/avrana-party-games/`, run on port 8196.

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

---

## NEXT (after the baseline plays cleanly on real phones)

- **Deliberate redesign** of mechanics and identity: an original theme, role names,
  abilities and rules text.
- Mobile UX polish: large touch targets, clear response prompts, turn and pending-claim
  clarity, a readable event history.
- Player-count range and balance (the VTT reference also scales to 7–10 players).
- Reconnect/rejoin verified on real phones (sleep, reload, network drop).
- Publish `rcnechamkin/avrana-party-games` once the owner creates the fork and approves.

## LATER / EXPERIMENTAL

- **LAN Games-style chat / social messaging** in the game. Social interaction is central to
  bluffing games, and LAN Games already has a chat system. Not part of the first prototype.
- Original art and assets, animations and sound.
- Integrate into the main Avrana launcher / `party.local` hub. That touches live nginx or
  LAN Games, so propose it first.
- An optional shared TV/table view (spectator only; must never show hidden cards).
- VirtualTabletop as a separate generic tabletop runtime. Its HTTP endpoints are
  unauthenticated (`PUT /state/:room`, `POST /quit`), so it must be fenced first.
- Additional native Avrana web games.
- Heavier streamed games (Moonlight/Sunshine or similar) for the arcade runtime.
- Reconcile repo docs back into BookStack once its integration is reliable.

## Explicitly not doing

- Repairing BookStack (unless asked)
- A universal game framework
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
- **Workflow.** Edit and commit off-Pi (or in a separate clone), push to `origin/main`, then
  `git pull --ff-only` in `/home/cody/avrana-party` on `party`. Experiments live under
  `~/avrana-lab/` on the Pi, never inside the deploy checkout or live service directories.
