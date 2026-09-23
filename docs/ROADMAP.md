# Avrana Party — Roadmap

Last updated: 2026-09-22. This is the working plan for the next several milestones.
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
phones join its Wi-Fi and act as clients or controllers. Three game runtimes are in view:

| Runtime | Status | Role |
|---|---|---|
| **LAN Games** (`/home/cody/LAN-Games`, `party.local/`, port 8096) | **Live.** 28 browser-native games; lobby, identity, bots, TV views. Upstream (BEACNpool) **retired it in Sept 2026**. It is MIT-licensed and still runs, but gets no updates. Source is *not* in this repo. | Existing native web-game platform |
| **Arcade streaming** (`arcade/`, `party.local/arcade/`) | **Live prototype.** Gauntlet II via RetroArch + MAME 2010, one shared encode, WebRTC to phones; two iPhones verified. | Traditional/emulated games. **Preserved; not being redesigned.** |
| **Classic Diplomacy** (new) | **Engine validated on the Pi** (2026-09-22). No game code yet. | First purpose-built Avrana native game |

The open arcade work in `CLAUDE-HANDOFF.md` (under-voltage, audio-ratchet fix verification,
recovery gap) stays open and is independent of the Diplomacy work below.

---

## Key decisions and findings (2026-09-22)

1. **Classic, map-based Diplomacy is the primary native-game target.** It will be a
   **purpose-built Avrana web game backed by the
   [`diplomacy/diplomacy`](https://github.com/diplomacy/diplomacy) engine**, not a
   VirtualTabletop game.
2. **VirtualTabletop's library game named "Diplomacy" is actually *Coup*.** It has Coup
   metadata (BGG 131357, Rikki Tahta), a Duke/Assassin/Captain/Contessa/Ambassador/
   Inquisitor deck, and no map, units or orders. **Do not use it as a basis for Diplomacy.**
   VirtualTabletop (GPL-3.0) remains a possible *separate, later* runtime for generic
   tabletop and card games.
3. **The engine works on the actual Pi**: Python 3.13.5 on aarch64, 12/12 validation checks,
   521/521 of the engine's own tests including 160 DATC cases, and adjudication in about
   4 ms. See `docs/findings/2026-09-22-diplomacy-engine-on-pi.md`.
4. **Illegal orders are never accepted, but the engine doesn't always say so cleanly.**
   Most are silently dropped with a message in `game.error`, and free text can raise an
   exception. **The phone UI must offer only engine-generated legal orders, and must always
   show back what the engine actually accepted.**
5. **The engine's bundled web UI and network server are not used.** The UI is React 16 on a
   2019 Create React App toolchain and desktop-oriented; the server has its own accounts and
   protocol. We import `diplomacy.Game` in-process. Its SVG maps are reusable.
6. **Negotiation stays human.** No chat, AI negotiation or diplomacy logic unless the owner
   asks later.
7. **Don't generalise early.** Diplomacy is the proving ground. No universal Avrana game
   framework until Diplomacy shows which abstractions are actually useful.
8. **Every phone is a complete game client, not a controller.** Think of a polished mobile
   board game, not a remote for a TV. Each phone shows the **full public board** and has
   **private controls for its own power**. Diplomacy must be fully playable with only
   *Avrana Party device + phones*. A shared TV is an **optional, later** spectator view,
   not part of the core architecture.
9. **The server is authoritative and masks private state at the API boundary.** A client
   receives only public state plus *its own* power's orders and readiness. Another
   power's pending orders are **never sent** to it; hiding them in the UI alone doesn't
   count.

### Product model

```
 Phone (France)                  Phone (Germany)
 ┌──────────────────────┐        ┌──────────────────────┐
 │  FULL PUBLIC MAP     │        │  FULL PUBLIC MAP     │   same synchronised
 │  units, centres,     │        │  units, centres,     │   public state
 │  year/phase, results │        │  year/phase, results │
 ├──────────────────────┤        ├──────────────────────┤
 │ FRANCE: own units,   │        │ GERMANY: own units,  │   private: only this
 │ legal orders, review,│        │ legal orders, review,│   power's orders and
 │ edit, ready          │        │ edit, ready          │   readiness
 └──────────┬───────────┘        └───────────┬──────────┘
            └──── Avrana Diplomacy service ──┘   (authoritative; per-player masking)
                          │
                  diplomacy/diplomacy  (rules, adjudication, game state)
```

UX direction to evaluate prototype decisions against (not built yet): touch-first, with
pan/zoom on the map and direct taps on units and provinces. Examples: *Tap Army Paris →
Move → Burgundy*; *Tap Army Marseille → Support → Army Paris → Burgundy*. The engine's
legal-order set constrains every choice; players never type Diplomacy notation. Don't
reproduce the physical board literally, and don't assume a desktop.

---

## NOW

### N1. Repository docs become the working source of truth — **DONE (2026-09-22)**
This file; the BookStack caveat above; `CLAUDE.md` updated to match.

### N2. Validate `diplomacy/diplomacy` directly on the Pi — **DONE (2026-09-22)**
Isolated venv at `~/avrana-lab/diplomacy-spike/` (outside the repo and every live
service). Script: `experiments/diplomacy/validate_engine.py`. Results:
`docs/findings/2026-09-22-diplomacy-engine-on-pi.md`.

### N3. Choose where the Diplomacy game is hosted — **OWNER DECISION PENDING**
Both options import `diplomacy.Game` in-process. Neither involves VirtualTabletop.

Both options are "an Avrana Diplomacy service" in the product model above. The question is
only whether it's built on LAN Games' server plumbing or written from scratch.

- **A. A LAN Games game module (recommended).** LAN Games already provides the plumbing:
  - **server-side personalised state:** `state_for(token)` → `game_state(viewer_token)`,
    documented in its guide as security-critical masking, so each phone receives only
    public state plus its own power's orders
  - WebSocket plumbing with a per-game lock
  - secret-token identity (token → public pid) with reconnect hooks
    (`game_player_left` / `game_player_back`)
  - lobby, ready and GO flow
  - a "reject bad input, never raise" convention

  Its chess game already wraps an external rules library the same way. A Diplomacy module
  is roughly one `game.py` wrapping `diplomacy.Game`, plus a mobile web client, and it lands
  naturally in the existing `party.local` hub later. **Dependency:** the upstream is retired
  and its source is not in this repo, so Avrana changes need a home (fork `LAN-Games` under
  the owner's account, or vendor it).
- **B. A standalone small Python service.** It's independent of LAN Games and has clean
  licence isolation, but it has to rebuild identity, lobby, WebSockets, per-player masking
  and reconnect itself.

### N4. Prove the smallest Avrana-native Diplomacy game loop
Build it in an **isolated instance** on its own port, never inside the live
`avranaparty-games` service or its venv. Standard map, 7 powers, no styling work.

Two independent mobile browser clients connect to the same game as different powers.
**No TV or third screen is involved.** Ugly is fine.

**Success criteria:**
1. Phone A joins as one power; phone B joins as another.
2. Both show the **same current public board and state**: the map, all units, supply
   centres, year and phase.
3. Each shows **only its own** order-entry interface.
4. Order choices come **only from the engine's legal-order set**. No typed notation.
5. Each can review and modify its orders before marking ready, and sees the orders the
   engine actually accepted.
6. **One player's pending orders can't be obtained through another player's client.**
   Check this at the protocol level by inspecting WebSocket payloads, not just the UI.
7. Once the phase is ready to resolve, the Pi calls `process()`.
8. Both clients receive the resulting public state and update consistently, live.
9. The next movement, retreat or build phase proceeds through the same model.
10. Runs on the Pi alongside the live services with no changes to them.

Seven humans aren't needed. Extra test clients (or scripted/"hold" powers) can stand in
for the remaining powers to reach an adjudicable state.

Prototype map rendering: the simplest route is the engine's own
`render(incl_orders=False)` SVG, which renders the **public** state only (~80 ms on the Pi,
~100 KB) and is sent to every client once per phase. Interactive, tappable map rendering
comes in *Next*.

### N5. Preserve existing Avrana functionality (standing rule)
No changes to nginx, dnsmasq/captive portal, NetworkManager/AP, systemd units, the live
LAN Games service or venv, RetroArch/arcade or telemetry without an explicit proposal that
states the blast radius. Integration into `party.local` is **Later**.

---

## NEXT (after N4 works on real phones)

- **Structured mobile order entry.** *Tap unit → action (Hold/Move/Support/Convoy) →
  destination or supported unit* → review list → submit. Choices always come from
  `get_all_possible_orders()`. Pending / submitted / accepted states are clearly shown.
- **Touch-friendly public map on every phone.** Pan/zoom, with direct taps on units and
  provinces. This likely means client-side rendering of the engine's province-ID SVG
  maps, driven by the public state, rather than a server-rendered picture.
- **Player/country assignment.** A phone knows its power automatically, and seat claiming
  is conflict-free.
- **Live state updates** over WebSocket, or whatever LAN Games' binding provides, with
  per-player masking at the server.
- **Public status on every phone:** supply-centre counts, resolved movements from the last
  phase, and who is ready. Readiness is public; order contents are not.
- **Retreat and build/disband phases** in the phone UI. The engine already supports them;
  verified on the Pi.
- **Save and rejoin**: persist with `to_saved_game_format` after every phase; a phone
  that reloads or drops returns to the same power.

## LATER / EXPERIMENTAL

- Integrate Diplomacy into the main Avrana launcher / `party.local` hub (touches live
  nginx or LAN Games: propose first).
- **Optional shared TV / public board.** For example, a "Show public board on TV" choice,
  or auto-detected HDMI. It is a spectator/table view of the map, phase/year, supply
  centres, resolved movements and public status. It's purely additive: Diplomacy never
  depends on it, and it must never show pending orders.
- Visual polish and movement animations.
- Phase deadlines/timers (optional; human negotiation pace first).
- **VirtualTabletop as a separate generic tabletop runtime.** A small proof first: self-host
  on the Pi, several phones, synchronised and private state. Its HTTP endpoints are
  **unauthenticated**: `PUT /state/:room` overwrites a room, and `POST /quit` exits the
  server. On the open party network it must be fenced before any real exposure.
- Additional native Avrana web games.
- Heavier streamed games (Moonlight/Sunshine or similar) for the arcade runtime.
- Reconcile repo docs back into BookStack once its integration is reliable.

## Explicitly not doing

Repairing BookStack (unless asked) · chat or AI negotiation · a universal game framework ·
using VirtualTabletop's "Diplomacy" (Coup) · removing or redesigning the arcade path.

---

## Dependencies, constraints and open questions

- **Licensing.**
  - `diplomacy/diplomacy` is **AGPL-3.0**. A server that imports it and is used over the
    network must offer its users the corresponding source, *including our Diplomacy game
    code*. Plan for that: keep the Diplomacy module in a source-available (AGPL-compatible)
    repo and add a "source" link on its pages. This is not legal advice; decide before
    anything is published.
  - LAN Games is MIT, which is compatible with inclusion in an AGPL work.
  - VirtualTabletop is GPL-3.0, with no network clause.
  - "Diplomacy" is a Hasbro trademark. Fine for private use; don't publish under that name.
- **Engine maintenance.** Upstream `main` has not changed since 2020-06-01 (`df1d089`).
  **Pin and vendor it.** There is one known future break:
  `datetime.utcfromtimestamp()` is deprecated (`diplomacy/utils/common.py:32`).
- **LAN Games is upstream-retired.** If option A is chosen, Avrana owns its maintenance.
- **Pi power.** Recurring under-voltage is still open (see handoff). Diplomacy is light
  (~4 ms adjudication, ~80 ms SVG render), so it's not a blocker, but keep the arcade and
  Diplomacy from being load-tested at the same time until power is fixed.
- **Test path.** Client-facing tests run from a device on the *Avrana Party* Wi-Fi
  (`party.avrana`, 10.42.0.1), not the Pi's home-LAN address.
- **Workflow.** Edit and commit off-Pi, push to `origin/main`, then `git pull --ff-only`
  in `/home/cody/avrana-party` on `party`. Experiments live under `~/avrana-lab/` on the
  Pi, never inside the deploy checkout or live service directories.
