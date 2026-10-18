# The Party's Control Center during a game: decisions needed

- **Status:** **DECIDED by the owner (2026-10-16, AVR-83 / AVR-292); one sub-question open (D5b).**
  Nothing here is built. §0 records the decisions; §3 is revised to match them. §2 and §4 keep
  the brief as it was put to the owner.
- **Reads with:** [ADR 0011](../../adr/0011-party-console-model.md) (decision 5: the game owns the
  viewport), [ADR 0013](../../adr/0013-party-and-game-browser-origins.md) (origins, the bridge),
  [ADR 0012](../../adr/0012-limited-mode-party-survives-https-loss.md) (Limited Mode),
  [host escape](2026-10-15-host-escape.md) (who can draw what during a round), [MESSAGING](../MESSAGING.md),
  [GAME-UX-CONTRACT](../GAME-UX-CONTRACT.md).

## 0. Decisions taken (owner, 2026-10-16)

| # | Decision |
|---|---|
| D1 + D2 | **A floating Party button that behaves like iOS AssistiveTouch**, not a fixed reserved corner. Tap opens the Party drawer. Long-press, then drag, moves it anywhere on screen; let go and it settles on the nearest side edge. Throw it into a side edge and it **tucks away** to a small tab with an arrow (as a collapsed picture-in-picture video does on iPhone); tap the tab to bring the button back. Replaces the 56 × 56 reserved corner: the player moves the button off whatever it covers. ADR 0011 decision 5 is amended (see its 2026-10-16 amendment). |
| D3 | **B now** (the Party-origin bridge frame draws the button and the drawer). **A maybe later**, after looking at how other games handle chat over play. |
| D4 | Chat during a game: yes, **inside the drawer only**; no toasts or overlay over play; the unread count on the button is the only interruption. |
| D5 | The Host gets **End for everyone, Bring everyone back, hand over hosting, and Quit & Spectate during a round** (both confirmed). **D5b is open:** what happens to a Host's seat when they quit mid-round (§0.1). |
| D6 | Limited Mode: the same design, first-party games only (a same-origin frame, as ADR 0012 accepts). |
| D7 | Arcade (Gauntlet II): the same button over the stream page, after the Pi measures its cost. |

### 0.1 D5b: quitting mid-round (needs one more answer)

Hand over hosting already works mid-round (`POST /party/api/host`; Party Core allows it to anyone
who is here). Quit & Spectate does not: Party Core refuses it during a round (`round_on`), because
ADR 0010 says roles never change during a round. Allowing it changes two things:

1. **The seat.** The game owns seats. Recommended: the quitting Host's seat is handled as the
   game already handles a player who leaves (BLUFF's per-player forfeit); hosting passes by
   succession at once.
2. **What they then see.** In BLUFF a Party spectator gets the omniscient view (every hand). A
   player who quits mid-round and becomes a spectator could read the remaining players' hands
   aloud. Recommended: **they keep their own player view (forfeited) until the round ends**, and
   are a spectator from the next round, which is what Quit & Spectate already does at results.

Alternatives: let them become a full spectator at once (leaks private state mid-round), or only
allow hand over hosting mid-round (no seat change). The recommendation needs a Party Core change
(lift `round_on` for this one verb, keep the role) and a Games change (forfeit on that signal).

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

## 3. Design as decided (B now)

- **The Party button.** 48 × 48 CSS px, Party-rendered inside the Party layer frame, translucent dark
  like AssistiveTouch, showing the Party mark and the unread count. It floats above the game; it
  starts on the right edge, a third of the way down, inside `env(safe-area-inset-*)`.
- **Tap** (or Enter / Space) opens the Party drawer. **Long-press** (about 400 ms, with a small
  scale-up as the cue) then **drag** moves it. On release it settles on the nearer left or right
  edge, kept clear of the safe areas, the notch and the home indicator. A quick fling toward an
  edge, or a drop past it, **tucks it away**: it slides mostly off screen and leaves a 24 × 60 px
  tab with a chevron. Tap the tab to bring the button back. Position and tucked state are kept per
  phone (Party-origin storage), so the button is where the player left it in the next round.
- **Mechanics.** The frame tracks the finger in `screenX/screenY`, which do not jump as the frame
  itself moves, and asks the page to move the frame (`drag {x, y}`, then `place`); the page may
  only place the frame where asked, clamped inside the viewport. The button sets `touch-action: none` and
  `-webkit-touch-callout: none`, so a long-press opens no Safari callout or text selection.
- **Accessibility.** A drag has a non-drag equivalent (WCAG 2.5.7): the drawer has **Move button
  to the other side** and **Tuck button away**, and the tucked tab is a real button named "Show
  the Party button". The button's name carries the unread count. It honours reduced motion: no
  slide or fling animation.
- **The drawer.** Opening moves focus into the frame's dialog (`aria-modal`); the game gets
  the document event `avrana-party-layer` `{open: true}` so it can stop taking keys and
  announcements; closing returns focus to the button and sends `{open: false}`. The game is dimmed, not resized, and keeps its state.
- **What it holds, by role.**
  - Everyone: the Party and the game on now; people, with the Host named in words; the Party's
    chat (read with the Party credential inside the Party-origin frame, never passed to the game);
    connection state.
  - Host: End for everyone; Bring everyone back; Hand over hosting (pick someone here); Quit &
    Spectate (D5b decides its mid-round meaning). All confirmed.
  - Player-private game state never enters the frame.
- **Its own frame and protocol, not bridge v2 (as built, AVR-292).** The layer is a second,
  visible Party-origin frame, `/party/layer.html`, mounted by `web/party/bridge/layer-mount.js`
  (one import-free file a game can vendor, like `shim.js`; same-origin pages get it from
  `party-follow.js` with `layer: true` or `<html data-avrana-party-layer>`). Protocol
  `avrana.party-layer/v1`: frame → page `ready`, `place {mode: button|tab|open, side, y}`,
  `drag {x, y}`, `hide` (not a member: nothing over the game); page → frame
  `viewport {w, h, insets}`. No view, name or message text crosses. On a page of another origin
  (which owns the frame element and could hide it under a lure), the Host is offered only End and
  Bring everyone back, which bridge v1 already gives a game page; Hand over hosting and Stop
  hosting stay on same-origin pages until the owner widens D3 beyond first-party games.
  Bridge v1 and its frozen vectors are untouched, so a game that does not mount the layer, or
  stops mounting it, is exactly as before. The frame is sandboxed (`allow-scripts
  allow-same-origin allow-forms`: it cannot navigate the game page); it answers only a page on
  the Party's own origin or one Party Core registers for that game. nginx and the devserver let
  `layer.html` alone be framed by `'self'` and the game origin.
- **A game on its own origin (as built, AVR-292 follow-up).** `contracts/party-games.v0.json` now
  has an optional `layer` block (protocol, reference file, SHA-256, frame) checked by
  `tools/contract_check.py`: a games repository may vendor `layer-mount.js` byte for byte (by
  convention as `web/avrana-party-layer.js`) and declare it as `layer.vendored`; a mismatch is
  named, and a repository with no `layer` block is unaffected (declaring the block is what opts a copy in to being checked), so rollback is a game that stops
  calling `mountPartyLayer({ partyOrigin, game })`. The page decides when to mount (a member in this
  game's round, as `party-follow.js` does for same-origin pages) and calls `stop()` otherwise. The
  frame still loads from the Party origin with the phone's own credential; the page holds none
  (`tests/offline/bridge.spec.ts`, Tier 2). **Not built:** the Games side (the SDK export and
  `comply` do not yet vendor the file) and any installed `.avrgame` that mounts it; the real
  cookie behaviour of a framed Party page under Safari's tracking prevention is Tier 3
  ([device validation](../../runbooks/party-layer-device-validation.md), 7.7).
- **A top-layer dialog hides the button.** A page's `<dialog>.showModal()` puts it in the top layer
  and makes the Party frame inert. A game that mounts the layer opens its own dialogs without the
  top layer and keeps the table inert, the focus trapped and Escape working itself (BLUFF:
  `games/bluff/web/modal.js`), and leaves `aria-modal` off so a screen reader can still reach the
  Party button.
- **What games must do (GAME-UX-CONTRACT amendment).** Keep the frame above their own content
  (no element over it, no element full screen that hides it), and put nothing under the default
  position that cannot also be reached once the player moves the button. No reserved corner.
- **Limited Mode.** Same design; a same-origin frame, first-party games only.
- **Conformance.** The kit's `comply --boot` checks the button is visible and tappable during play.
- **A (Party as the top document)** stays a later option, revisited after looking at how other
  games handle chat over play.

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

## 5. Build order

1. Party (AVR-292, built): the layer frame and its mount, the button/drawer UI (drag, tuck, the
   non-drag actions, reusing `party-chat.js` and the people list), Host actions with a
   confirmation (End, Bring everyone back, Hand over; Stop hosting and watch at setup or
   results only). Tests: `tests/offline/party-layer.test.mjs`, `party-follow.test.mjs`,
   `tests/party/party-layer.spec.ts` (tap, long-press drag, tuck, position kept, keyboard,
   320 × 568, unread, Host-only actions).
2. Party Core, once D5b is answered: Quit & Spectate during a round.
3. Games: BLUFF and EXPO opt in (`layer: true` to `startPartyFollow`), keep the frame on top and
   handle `avrana-party-layer`; a mid-round quit as a forfeit (D5b). Not a contract change for
   bridge v1, so the Games PR can follow the Party PR.
4. Arcade, after the Pi measures the frame's cost to the stream.
5. Phones: iPhone Safari and Android Chrome on the Pi with the WAN cable out (Tier 3): drag,
   long-press without callouts, tuck, safe areas, VoiceOver and TalkBack.
