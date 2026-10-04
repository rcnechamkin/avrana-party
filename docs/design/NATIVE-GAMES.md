# Native Avrana games: the phone is not just a controller

Status: design principles and recommended primitives (2026-09-24). Nothing here is built beyond
what LAN Games/BLUFF already contain. Context: `PARTY-PLATFORM.md`, `GAME-INTEGRATION.md`.

Reconciled 2026-10-02: LAN Games is retiring as an Avrana runtime and is donor/reference code
([ADR 0014](../adr/0014-native-games-isolated-lan-games-retired.md)); there is no Avrana SDK yet. Transport wording below is aligned with the
deployed HTTPS origin (ADR 0004) and the accepted Full/Limited Mode direction ([ADR 0012](../adr/0012-limited-mode-party-survives-https-loss.md)).
Game UX primitives are otherwise unchanged by that reconciliation.

## 1. The principle

The smartphone in each player's hand is a **private, dynamic player surface**, not a gamepad.
It can be a controller, a personal screen, a private card hand, a secret role, a private
objective, an inventory, a map, a drawing canvas, a trivia buzzer, a text box, a ballot, an
auction paddle, a steering wheel, a touch puzzle, a team back-channel, a chat, later a private
audio endpoint — and it can be accessibility-customized per person without touching anyone else.

A game that only puts a D-pad and buttons on the phone is using the least interesting part of the
platform. D-pad games are fine, and emulation stays valuable (see Personal Viewports), but a
**native** Avrana game should start from the question:

> **What can this player's private touchscreen do that a normal shared-screen game cannot?**

And because the TV is optional, a native game must be fully playable on phones alone. The TV,
when present, is one more *public* viewer.

### Designer checklist (answer before building)

1. What does each player know that the others don't? If nothing, why phones?
2. What does my phone show when it is **not** my turn? (Idle phones sleep and people drift.)
3. Does every public moment work on phones alone — tested with **no TV connected**?
4. Which inputs need a private touchscreen (text, drawing, secret choice, wager)?
5. Is every private field filtered per viewer **on the server**, and covered by the leak test?
6. Is every timed moment set by a server deadline, and safe after a phone sleeps and wakes?
7. Is speed scored? If so, is Wi-Fi lag compensated — or should speed not count?
8. Does every control have an accessible alternative that sends **the same value**?
9. What is anonymous, and to whom (other players / host / logs)?
10. What official results and stats does the game report (and with what provenance)?

## 2. Hook strategy: several showcases, not one game

No single title defines the product. The platform should eventually demonstrate three hooks:

1. **Native, Jackbox-like, no TV:** private prompts, drawing, trivia, voting, hidden information,
   dynamic interfaces, social interaction.
2. **Native action / arcade** designed around Avrana: e.g. a kart racer, a Gauntlet-like co-op, a
   beat-'em-up — where each phone is a controller *and* a private status/map screen.
3. **Emulated multiplayer:** Worms, Bomberman, split-screen classics (with Personal Viewports),
   retro party experiences, with legally user-supplied content where required.

BLUFF (the Coup-inspired card game) is the first Avrana-native game and remains an early native
**testbed** for hidden information, private views and lifecycle. It does not by itself define the
product. The platform boundary is then validated by Checkers (the first deliberately simple game
built outside the LAN Games runtime) and Spades (teams, private hands, reconnect, scoring, richer
results) — ADR 0014.

## 3. Where shared code belongs: four homes

| Home | What | Owned by |
|---|---|---|
| **Party service** | identity, presence, seats, host, navigation, votes on *what to play*, chat, stats/events, accessibility preferences | the platform, across games |
| **Game SDK** | shared server code that runs *inside* the game's own process. **Does not exist yet.** LAN Games' `core/session.py` is not the SDK: it is donor code containing useful patterns (session lifecycle, per-viewer state, timers) from which public SDK/runtime primitives may later be extracted, once Checkers and Spades show what two independent games actually share | shared library, game-run |
| **Client UI kit** | optional phone widgets a game may use | shared library, game-used |
| **Game logic** | rules, scoring, tallies, tie-breaks, answer matching, turn order, role dealing, real-time loops | each game |

Standardize **the frame around a player moment**: who may act, until when, who sees what, how it
is revealed, what is recorded. Leave the moment itself to the game.

### 3.1 The LAN Games fork: what is a donor, what is legacy (AVR-228, 2026-10-04)

[ADR 0014](../adr/0014-native-games-isolated-lan-games-retired.md) retires the fork as a runtime
and keeps it as donor and reference code. This table says which parts are which, read from Games
`main` (`5cd0bac`). It **identifies candidates; it freezes nothing**: no SDK exists, and none is
declared until Checkers (AVR-238) and Spades show what two independent games actually share
(ADR 0014 decision 12). "Candidate" means "read this before writing your own", not "import this".

| In the fork | Classification | What carries forward, and what does not |
|---|---|---|
| `core/party_protocol.py`, `core/party_result.py` | **Already the public boundary**, not LAN Games code | Vendored byte-identical from Party (`avrana/party/protocol.py`, `result.py`; ADRs 0006, 0015). Every native game vendors the same two files |
| `core/party_session.py` | **Extraction candidate** (game-side runtime) | Key loading, the local-and-unproxied guard, and the `ended` delivery policy (one report, bounded retries, at-most-once at Party). Its `GAMES` list and its coupling to `server.py` routes stay behind |
| `core/session.py` (`GameSession`) | **Pattern donor** | The phase envelope; one `(deadline, gen)` timer on the monotonic clock; `fx`; per-viewer `state_for` with a separate spectator view; `party_start`, `take_outcome`, `game_result`. **Not carried:** token-keyed `Player` identity, the game's own ready/countdown lobby, bot seating as a base-class concern |
| `core/net.py` (`GameBinding`) | **Pattern donor** | One lock per room; a personalized push after every mutation; ticket admission at `hello`; a fresh room per launch; `ended` exactly once. **Not carried:** the browser-minted-token watch path, standalone admission, and anything that knows a particular game (ADR 0014 Context) |
| `core/duel.py` (`DuelSession`) | **Pattern donor**, narrow | Two-seat turn plumbing, resign/draw/takeback courtesy. Checkers decides whether any of it is worth sharing; one consumer is not evidence |
| `core/ws_limit.py`, `core/events.py` | **Extraction candidates**, small | Outbound backlog bound for a socket that stops reading; one structured log line per lifecycle event with no tokens. Useful to any game server on the same stack |
| `web/hubnet.js` | **Pattern donor** (client) | Reconnect with a fresh Party ticket; server-clock offset. **Not carried:** `wc-*` localStorage identity, manifest/icon injection, the hub's toasts and chrome |
| `web/avrana-integration.js`, `avrana-integration.css` | **Legacy compatibility** | Same-origin Party calls from game pages (with Party's `party-follow.js`). Replaced by the designed seam of [ADR 0013](../adr/0013-party-and-game-browser-origins.md), not ported |
| `games/<slug>/` rules and clients (BLUFF, EXPO, the ~28 donor titles) | **Game logic donor**, per title | A title moves only by being re-homed behind the native boundary as its own process (BLUFF, then Classics adaptations chosen one at a time). Nothing moves in bulk |
| `server.py`, `games/registry.py`, `provider/`, `ops/export_avrana_catalog.py` | **Legacy runtime** | The monolith host, its registry and the `avrana.lan-catalog/v1` export. Superseded by the game registry and canonical manifest (AVR-229, AVR-236); they stop with the runtime |
| `web/hub.html`, `hub.js`, `sw.js`, `offline.html`, `app.webmanifest`, `brand.js`, `brag.js` | **Legacy runtime** | The standalone hub and its service worker: not a supported product mode (AVR-222) |
| `core/chat.py`, `core/chatmedia.py`, `core/avatars.py`, `core/looks.py` | **Legacy compatibility, pending a Party-owned replacement** | Chat, photo avatars and the Gaze mapping still run here. Each needs a Party-owned home or an explicit decision to drop it before the monolith can stop (ADR 0014 Consequences); none becomes game SDK |
| `core/venue.py`, `data/venue.json` | **Legacy runtime** | Per-venue branding and the Wi-Fi join details. Onboarding is Party's ([ONBOARDING](ONBOARDING.md)); a game never holds network credentials |
| `games/wordclash` (mounted sub-app) | **Legacy runtime** | Shows that a separately written app can sit behind the hub; not a model for the native boundary |

**In source since AVR-259, not deployed:** the fork's other titles are no longer part of the
product. The appliance grants only BLUFF and EXPO from that runtime, Party Home's catalog offers
no other LAN Games title, and nginx sends only `/games/bluff/` and `/games/expo/` there, by name,
on both server blocks. Every other slug under `/games/` is a native game's socket or an error
from nginx; nothing falls back to the fork. The catalog snapshot
(`contracts/catalogs/lan-games.json`) still describes all of the fork's titles: it is the
Party-Games contract and supplies BLUFF's and EXPO's display text and launch target. The site
file and the web build of one commit are deployed together, never one without the other.

Three rules follow, and they are the reason the split is drawn this way:

- **Authority that Party now owns is never donor material.** Identity, admission, lobby, seating
  of the roster, navigation, chat and durable results are Party's (§3, ADR 0006 D1). Fork code
  that does those things is legacy even when it is well written.
- **A pattern is promoted only on repeated evidence.** A row above becomes shared code when a
  second independent game needs the same thing, not before (AVR-41's "promoted only with repeated
  evidence").
- **Community or untrusted game code never runs in a shared process**, the monolith included; it
  is out of process by definition ([GAME-INSTALLATION](GAME-INSTALLATION.md) trust tiers,
  ADR 0014 decision 3, AVR-69).

## 4. Primitives, in the order worth standardizing

The LAN Games fork already contains at least six hand-written copies of "collect sealed answers,
close when everyone is in", four different "is everyone here?" rules, and no drawing, ranked vote
or anonymous answer at all.

1. **Presence and eligibility (party service).** here → reconnecting (grace) → away, per
   presence, not per socket (BLUFF's model). When a response window opens, the eligible set is
   frozen. Replaces the four divergent checks. The platform reports presence; the *game* decides
   what autopilot does.
2. **Response window (SDK).** Open: `prompt_id`, kind, eligible set, opens-at, deadline,
   visibility (sealed / live / anonymous), min/max answers. Answer: `prompt_id` + value; reject
   stale/closed ids, ineligible players, late answers (small in-flight allowance) and duplicates
   (except editable-until-locked). The public view shows **who has answered, never what**. Closes
   at the deadline or when every eligible player answered. It returns sealed answers and nothing
   more — scoring stays in the game. *(Evidence: only BLUFF checks a prompt id today; in trivia a
   late pick for question 3 can score on question 4.)*
3. **Clock and transitions (SDK; the pattern exists in LAN Games donor code).** One authoritative deadline in absolute server
   time; a scheduled `at` so every phone flips to the next beat together; full state on wake.
4. **Private per-viewer views + a leak test (SDK + CI).** The game supplies one view per viewer
   kind (seat, spectator, public); the platform ships an every-phase × every-viewer leak test and
   a check that broadcast events carry no private fields.
5. **Public table view (UI kit + a manifest rule).** Every native game renders its public view on
   phones; a TV is just one more public viewer. Reveals are server-timed.
6. **Event sink (party service).** Results, stats and achievements with provenance, and flags for
   bots, autopilot turns and forfeits. The game determines and reports; Party is the only writer
   of the persistent record (the result envelope is AVR-237, not yet designed).
7. **Per-player accessibility (party service + UI kit).** Move today's per-device preferences
   (motion, contrast, haptics, sound in `hubnet.js`) onto the presence/profile and hand them over
   with the seat. Widgets apply text size, contrast, motion, handedness, haptics and colour-safe
   palettes. Alternative controls must send the **same value** (FIFTH SIGNAL's tilt and touch pad
   both send the same `{x,y}`).
8. **Buzzer arbiter (SDK + UI kit).** See fairness below.

**UI kit widgets** (optional, no contract): choice list, single ballot, numeric keypad, text entry
(16 px, length cap, shared sanitizing), wager, hold-to-peek role card, countdown ring,
"who has answered" ticks.

### Deliberately NOT standardized

- **Server-described UI component trees.** That is the universal game engine the owner ruled out.
  The server says *what is being asked*; the game's own page (or a kit widget) draws it.
- **Game rules:** scoring, tallies and tie rules, answer matching, team agreement, turn order,
  role dealing, real-time loops.
- **Drawing canvas, ranked votes, anonymous-reveal screens** — build each inside the first game
  that needs it; extract when a second game needs it too.

## 5. Fairness

- **Buzzers.** Today the server takes whichever press it processes first, so Wi-Fi power-save lag
  (tens to hundreds of ms) often decides the winner. Better: announce the buzzer opening ~1 s
  early in server time so phones arm together; each phone measures *reaction* time on a monotonic
  clock; the server collects presses for a short window after the first and picks the fastest
  plausible reaction; reject impossible times; short lockout for early presses; seeded random for
  near-ties, and say so on screen; keep sockets awake with pings while armed. A cheater can fake
  reaction times, but the plausibility window bounds the gain.
- **Sleeping phones.** Screen Wake Lock needs a secure context: in Full Mode (trusted HTTPS) the
  shell can keep a screen on during play, and in Limited Mode or on any plain-HTTP page it cannot
  (ADR 0012); iOS doesn't vibrate either way. Design as if nothing can wake a sleeping phone. The
  server never extends one phone's deadline; slack comes from presence ("everyone's in" counts
  only eligible, present players). Give idle players something to look at.

## 6. Privacy and anonymity

- **Filter on the server only**: never hide with CSS, never leave private data in the page, never
  put private fields in broadcast events. Limit: this stops other *browsers*; network secrecy
  depends on the transport. In **Full Mode** Party and integrated game traffic runs over the
  browser-trusted `https://party.avrana.net` origin (live since 2026-09-25, ADR 0004), so peers on
  the Wi-Fi cannot read hidden roles. On **plain HTTP** — the legacy hub today, and Limited Mode
  when it exists (ADR 0012) — WPA2 does **not** protect guests from each other: anyone with the
  Wi-Fi password can read and alter the traffic, hidden roles included. That is an accepted risk
  for friends parties (`PARTY-PLATFORM.md` §13) and must be visible to players; AP client
  isolation is a cheap extra. *(The 2026-09-24 text said the party network was plain HTTP and that
  offline phones could not easily have HTTPS; browser-trusted HTTPS has since shipped.)*
- **Side channels:** show identical screens to everyone not acting; push state to every socket on
  every change; no role-specific sounds or vibrations others could notice.
- **Anonymity levels** (each game states which it offers): *to other players* (no author in anyone
  else's data, shuffled reveal order, no per-answer timestamps; only the author's own view marks
  their answer), *to host/TV/spectators* (the host is just a player), *to logs/stats* (totals
  only). Never *to the appliance* — an admin with SSH can read memory. Say "anonymous to other
  players", not "anonymous". With fewer than three players anonymity is arithmetic; warn.

## 7. Accessibility is a platform advantage

Because every player has a private UI, per-player accommodations — larger text or controls,
left/right handedness, reduced motion, high contrast, alternative layouts, colour-safe palettes,
haptic preferences — can apply to one person without changing anyone else's screen. This is hard
on a shared TV and natural here. Build it into the UI kit and the presence preferences, not into
each game.
