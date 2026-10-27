# Draft ADR 0018 — Shared Party activity, the in-round Party panel and universal setup

- **Status:** DRAFT ADR, pending owner approval. NOT accepted and not source authority; nothing here is built, merged or deployed.
- **Date:** 2026-10-26. Revised the same day after the owner's direction (§1.1). The owner approved the direction ("Yes"),
  but the document stays a draft until it is merged as an accepted ADR.
- **Revision 3 (2026-10-26, owner item 9):** the round runs inside a **Party play shell**. The top-level page stays on
  `/party/` and the game fills it in a cross-origin frame. The FAB is drawn by the shell itself, not by a frame inside the
  game. This replaces "the game is the top-level page" (D2, D5, D6, §4). It is gated by a real-phone proof (§4, stage
  S0b) and keeps today's top-level game plus layer frame as the fallback.
- **Linear:**
  - AVR-705: this decision.
  - AVR-762: the console and viewport proof, [#258](https://github.com/rcnechamkin/avrana-party/pull/258).
  - AVR-701/AVR-700: select then launch, voluntary Ready.
  - AVR-702: browse during setup.
  - AVR-703/AVR-468: now *the Party panel (FAB) during a round, plus reconnect/restore*.
  - AVR-88: next-game suggestions.
  - AVR-84: activity and notifications.
  - AVR-62: game permissions.
  - AVR-21/AVR-763: durable continuity, ADR 0019.
- **Where it lives and why:** `docs/adr/` admits only accepted decisions (`tools/repo-check.py`). So, like the hosted
  staging decision before its acceptance, this draft lives here. On acceptance it moves to
  `docs/adr/0018-shared-party-activity.md`, and the amendments in §6 are applied then.
- **Companion:** [reconciliation](2026-10-26-adr-0018-reconciliation.md). It covers:
  - how a round works today;
  - conflicts, with file:line references;
  - the retain/adapt/replace matrix;
  - the security regression list;
  - acceptance criteria;
  - the staged migration.
- **Separate workstream:** durable continuity (ADR 0019) is not designed here; §7 lists what this decision needs from it.

## 1. Context

The owner approved a product contract (AVR-705) for the offline-first console: phones join the appliance Wi-Fi and play
in browsers, with no internet, app, account or TV. One appliance is one Party and holds one active game.

Accepted source authority is narrower than that contract in three places:

1. **No setup for games without a pregame.** [ADR 0011](../../adr/0011-party-console-model.md) decision 1 sends those
   games straight to the round, with the roster fixed at the Host's tap.
2. **A full-screen, unbrowsable setup.** ADR 0011 decision 4.
3. **Mandatory Play/Watch.** [ADR 0010](../../adr/0010-party-pregame.md) decision 1 requires an explicit answer from
   every member who is here before the Host may Start.

### 1.1 Owner direction (2026-10-26, relayed from the owner in chat)

1. On the ADR 0018 direction: "Yes".
2. "When people are 'leaving the game to look at the menu,' they're not actually leaving the game to go back to the
   Party Menu. The FAB that we're working on will just show a few options for other games for them to vote on for the
   next game. The FAB will never completely take over the entire screen. ... No players should be able to actually go
   back to the Party Home Menu while in game."
3. "The FAB should be a one-stop-shop for actual Party controls including party, chat, menus, quick settings, etc."
4. Keep the vanilla JS console (no Svelte rewrite).

Owner answers to the draft's open questions (2026-10-26, relayed from the owner in chat):

5. **Guest Leave.** "Whatever you think is the better design choice." The orchestrator's decision: keep the accepted
   AVR-580 flow (D5).
6. **Host controls in the FAB.** "Yes for now. We may reevaluate how we integrate the menu later though."
7. **Games without the layer.** "Go with your recommended idea. We want the FAB as a constant throughout the entire
   system."
8. **Undetectable cover.** "Sure. I feel like eventually we really should make it required for every game though. If
   the game wants to hide the FAB, that's an option, but it'll still be accessible via a drawer or something."

Owner direction, revision 3 (2026-10-26, relayed from the owner in chat):

9. **No browser chrome in the installed app.** On an iPhone with the Party installed to the Home Screen, starting Tanks
   showed iOS's out-of-scope browser bar (close, URL, back, share, reload, open in Safari). The owner: "I'd want to
   eliminate these things whenever I start a new game in the PWA", and approved making the Party shell the plan.
   - Cause: the manifest's `"scope": "/party/"` (`web/party/manifest.json`) cannot include another origin, so a
     top-level navigation to the game origin leaves the app. iOS has no cross-origin scope extension.
   - So the top-level document must stay inside `/party/` for the whole round, and the game must keep its own origin
     (ADR 0013). The only design that satisfies both is a Party page that frames the game.

The kickoff's wording, "a player can open Home/Party/Library/Me during gameplay", is therefore **narrowed by owner
direction**. During a round the Party surface is the FAB's bounded panel, never a navigation away from the game.

## 2. Decision (draft)

**D1. One Party, one activity.** One appliance runs one Party, with at most one active Standard Mode game session.

- Only the Party Host selects, starts, ends or switches the game.
- A guest's browser, a direct game URL, a stale tab, a reconnect or a deep link cannot start or switch a game, or open
  a second session.

This restates ADR 0011's 2026-10-02 amendment and ADR 0014 decision 10.

**D2. Shared activity versus what one phone shows.**

- **The shared Party activity** is the authoritative state, `home | setup | game | results`, together with the selected
  game, the session, roles and the Host. It lives in Party Core, and only the Host moves it (PARTY-LIFECYCLE R1/R2).
- **Outside a round** (`home`, `setup`), a member's phone may show any Party view: Home, Library, Party or Me. They are
  all the same `/party/` document.
- **During a round** (`game`, `results`), the phone shows the Party play shell: a `/party/` page whose content is the
  game, full screen, in a frame (D5). The phone follows Host moves exactly as today (ADR 0011 decision 3, kept for
  rounds), by the shell changing or dropping its game frame instead of the browser navigating to another origin. The
  member's only Party surface is the FAB panel (D5). There is no personal navigation to Party Home, Library or Me in a
  round.

Neither browsing nor the panel ever moves, pauses, cancels or advances the shared activity, or changes a role or seat.

No per-device view state is stored in Core in a way that advances the Party `version` that Host actions compare
(`if_version`). That would make the Host's next tap stale, the race behind #208/#218. The same rule covers D4's member
intent toggles: Host lifecycle verbs compare a lifecycle version that member intent does not advance, and Core
recomputes the fill at apply time. The exact split is designed in stage S2.

**D3. Universal setup.** Every selected game enters a Party-owned setup before the Host's Start, including games
started directly today. The lifecycle is **Select → Party Setup → Host Start → automatic entry**, with no second lobby,
join code or identity pick afterwards (ADR 0010 decision 5 and GAME-UX Rule 4.6 are kept).

In setup, the Party enforces, from the Game Contract:

- eligibility: presence, Limited Mode and device capability (`seatLimits`/`evaluateSeat`);
- `players.min`/`players.max`;
- the required decisions the game declares;
- the `spectators` policy.

Eligible members enter the round automatically. The setup is on Party Home and is not a full-screen trap: during setup,
members may move between Party Home's views and come back to it (AVR-702).

**D4. Role assignment: default Play intent, claims, Host reassign, deterministic fill.**

- **Default.** Every eligible member defaults to *Play intent*. That is an intention, not an owned seat.
- **Opting out.** **Watch**, or **Not playing this round** for games with `spectators: "none"`, is a legitimate,
  non-blocking opt-out from the fill (GAME-UX Rule 4.4/4.4a kept).
- **Claims.** Explicit seat claims are granted in server receipt order.
- **Host reassign.** Before Start the Host may reassign any seat. It is versioned and visible to everyone.
- **At Start,** seats fill from claims and Host assignments first, then Play-intent members in stable join order, up
  to `players.max`.
- **Overflow** becomes spectators only where `spectators` allows it. Otherwise those members stay Party members who are
  not playing this round.
- **Start is refused** only below `players.min` or for a missing required decision, never because someone has not
  answered.
- **The freeze.** At Start the roster freezes (ADR 0010 decision 2). A role or a secret is never escalated by the panel,
  Host status, a deep link, a reload, a reconnect or a second tab. Host status grants lifecycle verbs, never
  game-private information.

**D5. The Party play shell and the in-round Party panel (the FAB).**

- **The shell (owner item 9).** During a round the top-level document is a Party page inside the manifest scope, for
  example `/party/play`. It holds:
  - the game, full screen, in one frame on the game's registered origin;
  - the FAB and its panel, as ordinary Party DOM above that frame;
  - the one Party socket, the wake lock (`keep-awake.js`), and the ticket path that `bridge.html` provides today.
- **The game keeps its own origin.** The frame is
  `sandbox="allow-scripts allow-same-origin allow-forms allow-pointer-lock"`, with no `allow-top-navigation` and no
  `allow-popups`, plus `allow="autoplay; fullscreen; screen-wake-lock; gamepad"`. A game cannot navigate the Party, open
  windows, read Party cookies or storage, or draw outside its frame.
- **The game stays visible and authoritative.** Its server stays authoritative for timers, AFK, autopilot, grace and
  forfeit, and the Party adds no game timer. No design depends on a game running in a hidden or background frame: the
  game frame is never `display:none`, off-screen or zero-sized while a round is on.
- **The page owns the viewport.** Inside a frame the game's own `<meta viewport>` is ignored and the safe-area insets may
  read as zero. So the shell sets `viewport-fit=cover`, sizes the frame to the dynamic viewport, and passes the safe-area
  insets to the game as a versioned bridge value. The phone proof (§4) settles whether the frame spans the full screen or
  only the safe area.
- **Following and navigation.** `destination()` still decides where the phone belongs. On a Host move the shell swaps
  or drops its game frame, or returns to Party Home in the same document. The game's existing `navigate {to:'party'}`
  becomes a message to the shell. A game never navigates the top-level page.
- **The FAB is shell DOM, not a frame.** The layer UI (`web/party/lib/layer-app.js`, `layer.js`) is mounted directly by
  the shell. Its states are the same as today's:
  - closed button;
  - parked edge tab;
  - a **bounded panel**: for example a bottom sheet in portrait and a side sheet in landscape, with the exact bounds set
    in design (S4).
- **Touches.** The FAB root is `pointer-events:none` and only its button, tab and sheet take touches. Every touch outside
  them reaches the game frame, with no frame resizing.
  - Dragging the button uses pointer capture on the button.
  - The edge tab opens on a tap, never on an inward swipe, because that swipe is Android's Back gesture.
  - Positions are clamped to the safe areas and kept per orientation.
- **The panel never covers the whole viewport.** The game stays visible beside the sheet. The shell tells the game
  `{open}` and `{closed}` so it can release held joysticks or pause its own input. Shared timers keep running.
- **Panel contents** ("a one-stop-shop"):
  - Party: people and presence;
  - chat (ADR 0017);
  - next-game suggestions (D8);
  - quick settings: per-device preferences only, never Party state;
  - typed notifications;
  - Host controls: End, switch, Party Home for everyone, hand over hosting, each with confirmation (D6).
- **Notifications don't steal a gesture.** While a finger is down on the game, a toast waits until it lifts. During an
  active round, chat messages and suggestions update the badge only, with no toast. The keyboard never opens unless the
  member taps the chat field.
- **Panel accessibility:**
  - while open, the sheet is `role="dialog" aria-modal="true"` and focus is trapped in it;
  - Escape, Close or a tap on the visible game closes it, and focus returns to the game frame;
  - the FAB is the last landmark in the shell, so a screen reader reaches the game first;
  - a "Move menu" control cycles the corner for players who cannot drag;
  - reduced motion and 200% text are supported;
  - it works on small viewports, in landscape, with safe-area insets, and with the keyboard and IME over chat.
- **Typed notices** (`your_turn`, `host_started`, `round_over`, plus Party events) carry deadlines on the server clock
  and are worded only by the Party. A game's notice travels **game server → Party Core**, server to server beside the
  session protocol's `ended`, as a typed event (kind, game, participant, deadline). It is never free text, and never
  sent through the bridge. The panel and the button's badge show these notices.
- **The FAB is a constant, system-wide control (owner item 7).** It is present on every Party page and over every Party
  game. In the shell it needs no adoption by the game. The contract amendment is in §6.
- **A game may minimise the FAB, but never remove it (owner item 8).** A game may ask for the parked edge tab through a
  versioned bridge word. The player may park it too. In the shell a game has no way to hide or cover it.
- **Leave during a round (owner item 5).** The accepted AVR-580 flow stays:
  - Leave starts in the FAB and is confirmed on Party Home, never in a game-coverable frame.
  - It is the single sanctioned exit from a round to Party Home, because it is quitting the Party, not browsing.
  - The Host's Leave and hand-over also stay as AVR-580 and the 2026-10-18 amendment describe.
  - In the shell, Party Home is the same document, so the confirmation no longer leaves the installed app.
- **Restore is the reconnect path, not a browsing mechanism.** A reload, a sleep, an OS tab eviction or a network loss
  returns the phone to the same participant and role with a fresh single-use ticket, and the game resends the full seat
  state on `hello`: private state only to its own seat. #258's R evidence covers this path.
  - On return the shell re-requests the wake lock, and the game re-unlocks its audio on the next tap. A bfcache restore
    is treated as a reconnect.
- **Fallback: the top-level game (today's model).** Kept, behind the same flag, until S0b passes and every Party game
  works framed:
  - A game page opened top-level during a Party round (a stale tab, a deep link, a game not yet adapted) goes to the
    shell, unless the shell flag is off or the game is marked not frameable.
  - In fallback, the FAB is today's layer frame inside the game. The coverable-frame rules in D6 apply to it, and it
    shows the out-of-scope browser bar in an installed app.
- **Limited Mode** stays same-origin (ADR 0012). The shell frames the same-origin game, so the browser gives it no
  isolation from the shell. That is the accepted LIMITED-MODE D5 weakness, unchanged.

**D6. Origin, bridge and shell boundaries.**

- **Separate origins and bridge rules stay** as today ([ADR 0013](../../adr/0013-party-and-game-browser-origins.md)):
  - a game never reads Party or Admin cookies, and never calls member, host or admin endpoints as the viewer;
  - every bridge message is restricted by source window, registered origin, a closed verb set, the bound session, the
    member's role at the moment of the verb (re-checked by Core), and the exact recipient (never `"*"` for data);
  - tickets stay bound to the session and an opaque per-session participant, are refused for another game or during
    setup, are origin-checked, and die at End, switch or lobby.
- **In the shell the bridge points up, not down.** The game's shim talks to `window.parent`. The shell accepts a message
  only when `event.source` is its own game frame's window and `event.origin` is that game's registered origin. It
  answers to that exact origin over a dedicated `MessageChannel`. The verbs are today's closed set (ticket, public view,
  `navigate` word) plus `fab.park` and the insets value.
- **Framing headers.**
  - The game origin sends `frame-ancestors` naming only the Party origin (today it is not framed at all).
  - The shell page sends `frame-ancestors 'none'` and a `frame-src` listing only the registered game origins.
  - `bridge.html` and `layer.html` stay frameable by the game origin only while the fallback exists, then are retired.
- **Host controls live in the FAB, by owner direction.** In the shell they are no longer coverable: the game cannot
  restyle, cover, shrink, hide or remove shell DOM, or move it under a tap. So the shell gets the full Host controls
  without the ADR 0013 D3 "coverable" limit.
- **Mitigations (required in every mode):**
  1. **Hold to confirm for destructive Host verbs.** End, switch, Party Home for everyone and hand-over open a
     confirmation inside the panel, completed by about an 800 ms press-and-hold (or an explicit two-step). Each phone
     then shows a short "the Host is ending the game" banner before the change.
  2. **Core decides.** Every state-changing verb is idempotent, Core-authorized at apply time (host re-check) and
     carries `if_version`. A misdirected, replayed or stale tap acts at most once, and only for the current Host. A
     hand-over commits and advances the version (`transfer_host` → `_commit`), so a deposed Host's queued confirmation
     is refused.
- **Fallback only (top-level game, layer frame).** The frame is an element in the game's DOM, so the old risks remain.
  The game can cover, restyle, shrink, hide or remove it. #258 showed a covering element taking a tap, and
  IntersectionObserver v2 could not detect it.
  - The box self-check and the layer↔bridge heartbeat **detect accidents only**: a removed, hidden, zero-sized or
    starved frame. They are not a security boundary. `opacity:0`, a cover or a timed move over an intact frame cannot be
    detected. On a mismatch, destructive verbs are refused and the condition is recorded for the Host. A missing
    heartbeat never ends a game, because a sleeping phone also stops beating.
  - The residual risk is accepted by the owner for owner-installed games only (owner items 6 and 8).
  - **A future community or untrusted tier runs only in the shell, never in fallback.**
- **Required negative tests** before rollout:
  - in the shell, a game cannot cover, hide, move or take a tap from the FAB, cannot navigate the top-level page, and
    cannot open a popup;
  - the shell ignores a message from any window other than its game frame, or from any origin other than the
    registered one;
  - a destructive Host verb needs the hold-to-confirm step in every mode;
  - in fallback, a removed, hidden or zero-sized frame is detected and destructive verbs are refused;
  - a replayed, stale or deposed-Host verb is refused by Core;
  - cross-role secrecy, focus and announcements across the frame.

**D7. The selected game is always visible.** While a game is selected, in setup, on or holding results, a member
anywhere on Party Home sees a subtle, persistent, non-blocking indicator of it, with the way back to the setup. During
a round the FAB's badge and panel carry the same information. Both are announced politely, never assertively.

**D8. Next-game suggestions (voting without binding), in the FAB.**

- Each connected member may hold one nomination at a time.
- Approvals are public and named. The list sorts deterministically: approval count descending, then the earliest
  nomination's receipt order.
- Suggestions are visible during rounds.
- The Host decides independently: no binding vote, queue, auto-launch or threshold.
- The list is snapshotted through the intermission and cleared when the Host next selects a game.
- Suggestions are memory-only until ADR 0019 provides durable state, and a restart clears them, said plainly.
- Approving and nominating are low-stakes and need no confirmation. They are still Core-authorized and idempotent.

**D9. Game-specific play, Party-owned trust.** Game art, play UI and results stay game-specific. The FAB, Host controls,
the indicator, notifications and system cues are Party-owned and drawn on the Party origin. There is no generic rules
engine.

**D10. Delivery discipline.**

- Protocol changes are versioned, with paired PRs and contract vectors.
- Every stage has a proof tier.
- Rollout is reversible, default-off and owner-gated.
- Unrun phone or hardware checks are reported as NOT RUN.
- The console stays vanilla JS, by owner direction. `// @ts-check` with JSDoc and a keyed-list helper are recommended
  (#258); Svelte is rejected by the owner.

## 3. What this keeps

- Host authority and succession.
- One activity.
- The protocol states.
- `nav` moves only on committed transitions.
- **ADR 0011 decision 3's following during rounds.**
- The role freeze.
- Held results.
- Host-only End.
- BLUFF's refused lobby verbs.
- Single-use session tickets with no device or member id (ADR 0006).
- Separate origins and `__Host-avrana_device` (ADR 0013).
- Limited Mode's same-origin first-party exception (ADR 0012).
- LAN Games retirement (ADR 0014).
- ADR 0015.
- ADR 0017.
- AVR-580 Leave semantics, subject to the open question in §7.

## 4. Shell versus top-level game: the shell, gated by a phone proof (revision 3)

**Resolution:**

- The round runs in the Party play shell (D5). The game is framed and keeps its own origin. The FAB is shell DOM.
- The top-level game with the layer frame stays as the fallback until stage S0b passes and every Party game works
  framed.
- Restore-from-server is kept as the reconnect path only.

**Why the earlier "not planned" no longer holds.** #258 listed three objections to a Party page framing the game:

1. **"It needs a new game-origin `frame-ancestors`."** True, and it is a small header change, now part of S4a.
2. **"The game frame cannot be usefully sandboxed."** It cannot be isolated from its own origin, and does not need to
   be. The sandbox still does useful work: it removes top navigation and popups, so a game cannot leave the Party or
   cover it.
3. **"rAF behaviour depends on the engine."** It does for *hidden* frames (0 fps on Chromium, 61 on WebKit), and D5
   never hides the game frame. #258's WebKit numbers came from Playwright WebKit on Windows. That build was slow even
   with the game top-level (20 rAF/s, against 13 with the game framed and occluded), so it says nothing about iOS Safari.

The owner's requirement (item 9) is only met by this shape. It also removes the coverable FAB, the frame-sizing touch
dead zones and the cross-site cookie question, all at once.

**What is not yet known.** Nothing here has run on a phone. **Stage S0b** is a real-phone proof: an iPhone with the
Party installed to the Home Screen, plus an Android phone, against the Pi or the hosted VM. Tanks runs framed in a shell
prototype. Each item passes or fails:

1. **No browser chrome.** No out-of-scope bar appears when the round starts, during it, on a switch, or on return to
   Party Home.
2. **Frame rate.** Once the player has touched the game, its frame rate in the frame is within 2 fps of the same game
   top-level. It stays there after the FAB is opened and closed. Low Power Mode is off, and the iOS version is recorded.
3. **Two thumbs.** While one thumb holds a joystick, the other thumb taps and drags the FAB 50 times. No joystick track
   is dropped, and no dead zone appears outside the button.
4. **Audio and wake.** The game's audio starts on the first tap. The screen stays awake for 5 minutes of passive play,
   and both survive a sleep and wake.
5. **Viewport.** Safe areas, notch and home bar are handled in portrait and landscape. Nothing is under the Dynamic
   Island.
6. **Keyboard.** A text field inside the game (Best Guess) and the FAB chat field both stay visible above the keyboard,
   and the page is not left panned after it closes.
7. **Back.** Android Back and the iOS edge swipe do not navigate the game frame's history or leave the round.
8. **Reconnect.** A reload or OS eviction returns to the same seat inside the shell.

**Reversal conditions.** For a game that fails item 2, 3 or 7 and cannot be fixed by the game or the shell, that game
stays on the fallback, and the installed app shows the browser bar for it. The owner is told which games are affected.
A community or untrusted game is never allowed the fallback.

**Earlier evidence still used** ([#258](https://github.com/rcnechamkin/avrana-party/pull/258), `e240e35`; loopback
fixtures, Chromium and WebKit on Windows; phones and Pi NOT RUN):

- **The game keeps running under the panel.** In both shapes the game's socket kept 0 missed server ticks while the
  panel was open.
- **The cover risk is real for a frame inside the game.** A transparent game element took a tap meant for the drawer
  (test 10). That is the fallback's risk, and the shell removes it.
- **Restore is correct.** The same participant and role came back with a fresh ticket, the old one was refused as
  `replayed`, and no private frame reached a spectator. It was 230–650 ms on loopback. This is used for reconnect.

## 5. Consequences (if accepted)

**Party Core (Python):**

- `_open_session` enters `setup` for every game.
- `setup_status` no longer blocks on unanswered members, and fills instead of refusing over the maximum.
- New verbs: claim, release, Host reassign, nominate, approve.
- Late admission honours `spectators`.
- A new internal game → Core route for typed game events.

None of this is game logic.

**Console** (`web/party/`):

- the setup scene becomes leavable within Party Home;
- the D7 indicator;
- **a new play shell** (`/party/play`, in the manifest scope): the game frame, the bridge pointing up (D6), the wake
  lock, following by swapping the frame, and the insets value;
- the layer UI is mounted as shell DOM, with a bounded sheet, hold-to-confirm, tap-to-open edge tab, safe-area clamping,
  "Move menu", and gesture-safe toasts;
- the panel gains suggestions, quick settings, notices and the full Host controls;
- in fallback only: the layer frame's bounded `open`, box check and heartbeat (accidents only);
- `bridge.js` logic shared by the shell and, in fallback, `bridge.html`.

`destination()` keeps deciding where a phone belongs during rounds. The shell acts on it without leaving `/party/`.

**Games:**

- a paired change for the typed-event route;
- `spectators: "none"` handling;
- **the shim learns the framed mode:** detect a Party parent, talk to `window.parent`, take the insets value, ask for
  `fab.park`, and send a top-level Party-round page to the shell;
- every game origin sends `frame-ancestors` naming the Party origin;
- each game is checked framed (S0b items 2, 3, 5–7). A game that fails stays on the fallback.

**nginx and devserver:** the game-origin `frame-ancestors`; the shell's `frame-src` and `frame-ancestors 'none'`.

**Machine contracts:** Party Core reads `spectators`. Named-seat claims need a contract extension, not defined here.

**Proof:** nothing here is phone-verified or on the Pi.

## 6. Required amendments (not applied)

These are made only in the PR that accepts this ADR.

**ADR 0010:**

- Decision 1: replace the mandatory Play/Watch answer and the `unresolved` refusal with D4.
- Keep decisions 2, 3, 5 and 6.
- Decision 4: add "superseded also by ADR 0018 D3".

**ADR 0011:**

- Decision 1: every Host selection goes to `setup`; delete "→ game for a game without a pregame".
- Decision 3: **kept for rounds.** Narrow its setup consequence: during `setup` a member may move between Party Home's
  views (the same document) and return to the setup.
- Decision 4: "full-screen scene" becomes "the setup of the selected game, which members may leave within Party Home".
  Play/Watch wording follows ADR 0010 as amended.
- Decision 3: also record that during a round the phone is on the Party play shell, which follows by changing its game
  frame, not by navigating to the game origin.
- Decision 5 and the 2026-10-16 amendment: the floating Party button is drawn by the play shell and opens a **bounded
  panel, never full screen**, and the game stays visible. The panel holds people, chat, suggestions, quick settings,
  notices and the Host's End, switch, Party Home and hand-over, each with hold-to-confirm (D6).
- Keep decisions 2, 6 and 7 and the Leave, guest-exit and succession amendments, subject to the §7 question.

**ADR 0013:**

- No change to separate origins or cookies.
- Add: during a round the Party origin frames the game origin (the play shell). The game origin's `frame-ancestors`
  names only the Party origin. The shell's bridge accepts only its own frame's window and the registered origin.
- Note that game notices go server to server, never through the bridge.
- D3's "coverable" limit applies **only to the fallback** layer frame. There, the owner widens it "for now" to the full
  Host controls *with D6 mitigations*, for owner-installed games only (`layer.js:126-139` `actions(crossOrigin)`).
- Community or untrusted games run only in the shell.

**ADR 0014:** no change.

**GAME-UX-CONTRACT:**

- Rule 3.2: delete "A game without a pregame has no briefing".
- The "MUST NOT be visible in it" paragraph becomes: the setup stays focused but is leavable within Party Home.
- Rule 3.3: **kept** (no normal route back to Party Home in a round). Add that the Party panel is the in-round Party
  surface.
- Rule 3.6: allow the FAB, its bounded panel and typed notices.
- Rule 4.3 and the "More want to play than fit" bullet: replace with D4.
- The phase table: add the FAB column for Play and Results.

**PARTY-LIFECYCLE:**

- Delete `home --> game` and `results --> game` for direct titles.
- An arrival during setup defaults to Play intent.
- Late joiners are qualified by `spectators`.

**PARTY-GAMES-CONTRACT, GAME-UX-CONTRACT and Games `DEVELOPING-A-GAME` (owner item 7):**

- Every Party game **must run framed in the play shell**: no top navigation, no popups, no dependence on its own
  viewport meta or safe-area insets, insets taken from the bridge, joysticks released on `{open}`.
- The FAB is **required** and is supplied by the shell. A game may only ask for the edge tab (`fab.park`).
- The FAB is also present on Party pages.
- Each game adopts the framed mode in its own Games PR. Until it does, it runs on the fallback, where it must mount the
  layer (`layer.mounted_by` lists it) and keep the frame above its content.

**PARTY-GAMES-CONTRACT and machine contracts:**

- the framed-mode bridge words (`fab.park`, insets) and the shell handshake, versioned with vectors;
- in fallback only, the layer digest bump for the bounded geometry;
- the typed-event route;
- `party_config.py` derives `spectators`.

**Core docstring:** "Not here (deliberately): … votes … seat assignment" changes.

## 7. Dependencies, owner decisions and what is not decided

- **ADR 0019 (AVR-21/AVR-763).** Suggestions surviving a restart, and the selected game or setup surviving a Core
  restart, wait for it. Until then the Party is memory-only.
- **Decided (owner, 2026-10-26; §1.1 items 5–8):**
  - Guest Leave keeps AVR-580: it starts in the FAB and is confirmed on top-level Party Home, the single sanctioned
    exit.
  - The ADR 0013 D3 widening is accepted "for now", for owner-installed games only, and is revisitable. After
    revision 3 it applies only to the fallback.
  - The FAB is required system-wide.
  - Undetectable cover is accepted as residual risk, with minimise-to-tab as the floor. After revision 3 this applies
    only to the fallback.
- **Decided (owner, 2026-10-26; §1.1 item 9):** no browser chrome in the installed app; the play shell is the plan,
  gated by S0b.
- **Decided (owner, 2026-10-26: "Go with your own recommendations"):**
  - Revision 3 is accepted as the direction (this draft stays in proposals until the accepting ADR PR).
  - During an active round, chat and suggestions update the badge only, with no toast, and the keyboard opens only on a
    tap (D5). Both stay in the FAB.
  - Hold-to-confirm (about 800 ms) for destructive Host verbs, plus the short banner on every phone (D6).
- **Not decided here:**
  - the Watch / Not playing wording;
  - voluntary Ready (AVR-700);
  - an idle-selection timeout;
  - the seat-claim UI and named-seat contract;
  - notification templates (AVR-84);
  - motion tiers (#249);
  - mid-round Quit & Spectate (D5b);
  - the panel's exact bounds and the quick-settings list.
