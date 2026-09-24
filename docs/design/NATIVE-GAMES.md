# Native Avrana games: the phone is not just a controller

Status: design principles and recommended primitives (2026-09-24). Nothing here is built beyond
what LAN Games/BLUFF already contain. Context: `PARTY-PLATFORM.md`, `GAME-INTEGRATION.md`.

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

BLUFF (the Coup-inspired card game) remains an early native **testbed** for hidden information,
private views and lifecycle. It does not by itself define the product.

## 3. Where shared code belongs: four homes

| Home | What | Owned by |
|---|---|---|
| **Party service** | identity, presence, seats, host, navigation, votes on *what to play*, chat, stats/events, accessibility preferences | the platform, across games |
| **Game SDK** | shared server code that runs *inside* the game's own process (LAN Games' `core/session.py` already is this) | shared library, game-run |
| **Client UI kit** | optional phone widgets a game may use | shared library, game-used |
| **Game logic** | rules, scoring, tallies, tie-breaks, answer matching, turn order, role dealing, real-time loops | each game |

Standardize **the frame around a player moment**: who may act, until when, who sees what, how it
is revealed, what is recorded. Leave the moment itself to the game.

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
3. **Clock and transitions (SDK, mostly built).** One authoritative deadline in absolute server
   time; a scheduled `at` so every phone flips to the next beat together; full state on wake.
4. **Private per-viewer views + a leak test (SDK + CI).** The game supplies one view per viewer
   kind (seat, spectator, public); the platform ships an every-phase × every-viewer leak test and
   a check that broadcast events carry no private fields.
5. **Public table view (UI kit + a manifest rule).** Every native game renders its public view on
   phones; a TV is just one more public viewer. Reveals are server-timed.
6. **Event sink (party service).** Results, stats and achievements with provenance, and flags for
   bots, autopilot turns and forfeits.
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
- **Sleeping phones.** Over plain HTTP there is no Wake Lock and iOS doesn't vibrate, so nothing
  can wake a sleeping phone. The server never extends one phone's deadline; slack comes from
  presence ("everyone's in" counts only eligible, present players). Give idle players something
  to look at.

## 6. Privacy and anonymity

- **Filter on the server only**: never hide with CSS, never leave private data in the page, never
  put private fields in broadcast events. Limit: this stops other *browsers*, not a Wi-Fi
  eavesdropper; on an open plain-HTTP network, hidden roles travel unencrypted. Real secrecy on the
  network needs WPA2 on the party LAN (or HTTPS later).
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
