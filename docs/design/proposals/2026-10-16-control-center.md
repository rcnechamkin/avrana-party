# The Party's Control Center during a game: decisions needed

- **Status:** **PROPOSED (2026-10-16, AVR-83 / AVR-292).** A decision brief. Nothing here is built.
  It asks the owner for the decisions AVR-83 says must come before the permanent in-game
  presentation, and recommends one answer to each.
- **Reads with:** [ADR 0011](../../adr/0011-party-console-model.md) (decision 5: the game owns the
  viewport), [ADR 0013](../../adr/0013-party-and-game-browser-origins.md) (origins, the bridge),
  [ADR 0012](../../adr/0012-limited-mode-party-survives-https-loss.md) (Limited Mode),
  [host escape](2026-10-15-host-escape.md) (who can draw what during a round), [MESSAGING](../MESSAGING.md),
  [GAME-UX-CONTRACT](../GAME-UX-CONTRACT.md).

## 1. Where things stand

| Piece | State |
|---|---|
| Party room (chat) on Party pages | Built for review (AVR-54 branch). Party Core owns sender, order and limits. |
| Party drawer on Party pages: people, Host tag, chat, unread | Built (people since AVR-283; chat and unread on the AVR-54 branch). |
| Host's way out of a full-screen game | Built (AVR-476 part 1): Back reaches Party Home, which offers Return / Bring everyone back. |
| Anything Party-drawn over a running game | **Not built.** Needs the decisions below. |
| Bridge | v1: an invisible Party-origin frame with five verbs; no roster, no messages (deliberately). |

The host-escape audit settled one fact that bounds every option: **while the game page is the
top-level document, nothing the Party draws is out of the game's reach.** The game owns the
viewport and can cover, hide or full-screen over any frame.

## 2. The shapes, briefly

| | A. Party is the top document; the game is a full-viewport frame | B. The bridge frame becomes a small visible Party control | C. A contract rule only |
|---|---|---|---|
| What the player sees | A Party control the game cannot cover | A Party-rendered pill in a reserved corner; tapping it grows the frame into the drawer | The game's own button |
| Trust | Strongest | The Party renders it and its clicks cannot be forged or read by the game; the game can still cover it | The game's |
| Cost | Largest: ADR 0011 D5 and ADR 0013 rewritten, every game's full screen, Limited Mode, iOS frame quirks | Moderate: bridge v2 (show, grow, shrink), the vendored shim, one paired Games PR per game | Small |
| Game state while open | Preserved (frame stays) | Preserved (page never navigates) | n/a |

## 3. Recommended design (B now, A later)

- **Invocation.** One pill, 44 × 44 CSS px, Party-rendered inside the bridge frame, docked
  **top-right inside `env(safe-area-inset-top/right)`**. It shows the Party mark and the unread
  count. Tap or Enter opens; Escape, the drawer's Close, a tap outside, or the phone's Back closes.
- **Geometry the game keeps clear.** A 56 × 56 region top-right, inside the safe area, during
  play (GAME-UX-CONTRACT amendment). Opening the drawer covers the lower part of the screen like
  today's drawer (a sheet up to 86 dvh); the game is dimmed, not resized, and keeps its state.
- **Focus and screen readers.** Opening moves focus into the frame's dialog (`aria-modal`), the
  game page gets a bridge event `layer: open` so it can stop taking keys and announcements;
  closing returns focus to the pill and sends `layer: closed`. A game that ignores the events
  still works; it just may keep animating under the sheet.
- **What it holds, by role.**
  - Everyone: the Party and the game on now; people, with the Host named in words; the Party's
    chat (the same room, read with the Party credential inside the Party-origin frame, never
    passed to the game); connection state ("Reconnecting…" from the frame's own polls).
  - Host: End the round for everyone, and Bring everyone back (both confirmed, both Party Core
    verbs that exist today). Nothing else.
  - Not offered: a personal "leave the round" (ADR 0011 has none; AVR-132's Quit & Spectate stays
    at setup and results only). Player-private game state never enters the frame.
- **Bridge v2.** New verbs `layer.mount {corner}`, `layer.grow`, `layer.shrink` from the frame to
  the shim, and events `layer.open` / `layer.closed` to the game; capability word
  `party-layer/1` in the handshake. A game without it keeps v1 behaviour, so a rollback of either
  side is compatible.
- **Limited Mode.** First-party pages are same-origin there (ADR 0012 D5), so the frame is a
  same-origin frame and the game page could reach into it. Accept that for first-party games, as
  ADR 0012 does for everything else on Limited; never offer it to a third-party game in Limited.
- **Conformance.** The kit's `comply --boot` checks that the pill is hit-testable during play.
- **A (Party as the top document)** stays AVR-83's longer design, revisited if a third-party game
  or a native-app host needs the stronger guarantee.

## 4. Decisions for the owner

| # | Decision | Recommended | Alternatives | Consequence of the recommendation |
|---|---|---|---|---|
| D1 | Amend ADR 0011 decision 5 so the Party reserves one control region during play | Yes, top-right 56 × 56 inside the safe area | Reserve nothing (C only); A | Every first-party game keeps that corner clear; BLUFF and EXPO need a layout check |
| D2 | Geometry and invocation | §3: one 44 px pill, top-right, safe area; sheet up to 86 dvh | Bottom edge; a pull-down from the top edge | The top edge is where the shell's own control already sits; a bottom pill collides with game controls on both BLUFF and EXPO |
| D3 | Trust shape | B now, A later | A now; C only | Party-rendered and unforgeable, but coverable: acceptable for first-party games plus the conformance check |
| D4 | Chat during a game | Yes, in the drawer only: no toasts or HUD over play | No chat during games; toasts | The unread count on the pill is the only interruption; a game-declared "no chat now" is deferred (MESSAGING decision 9) |
| D5 | What the Host gets | End for everyone, Bring everyone back | Also hand over hosting; also Quit & Spectate mid-round | No lifecycle change: both verbs exist and are phase-safe |
| D6 | Limited Mode | Same design, same-origin frame, first-party only | No layer on Limited | Weaker isolation on Limited, as already accepted by ADR 0012 |
| D7 | Arcade (Gauntlet II) | Same pill, frame over the stream page | Arcade excluded in 1.0 | Arcade stream performance must be measured on the Pi with the frame visible |

## 5. Once decided, the build order

1. Party: bridge v2 frame UI (pill and drawer, reusing `party-chat.js` and the drawer's people
   list), vectors and hashes, ADR amendments. Tests: both bridge-vector suites, focus, a 320 × 568
   phone, unread, Host-only controls, a follower's 403.
2. Games: the vendored shim with `layer.*`, BLUFF and EXPO keeping the corner clear and handling
   `layer.open`, one paired PR, one merge set.
3. Arcade, measured on the Pi.
4. Phones: iPhone Safari and Android Chrome on the Pi with the WAN cable out (Tier 3).
