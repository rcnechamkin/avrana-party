# Draft ADR 0018 — Shared Party activity, the in-round Party panel and universal setup

- **Status:** DRAFT ADR, pending owner approval. NOT accepted and not source authority; nothing here is built, merged or deployed.
- **Date:** 2026-10-26. Revised the same day after the owner's direction (§1.1). The owner approved the direction ("Yes"),
  but the document stays a draft until it is merged as an accepted ADR.
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
- **During a round** (`game`, `results`), the game page stays the top-level, visible page. The phone follows Host moves
  exactly as today (ADR 0011 decision 3, kept for rounds). The member's only Party surface is the FAB panel (D5). There
  is no personal navigation to Party Home, Library or Me in a round.

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

**D5. The in-round Party panel (the FAB).**

- **The game stays mounted and visible.** During a round the game is the top-level page. Its server stays authoritative
  for timers, AFK, autopilot, grace and forfeit, and the Party adds no game timer. No design depends on a game running
  in a hidden or background frame.
- **One Party entry point.** The Party's in-round surface is the existing Party layer (`web/party/bridge/layer-mount.js`,
  `web/party/lib/layer-app.js`): a Party-origin frame with a floating button that opens a **bounded panel**.
- **The panel never covers the whole viewport.**
  - Today's `open` mode is full-viewport (`layerBox`, `layer-mount.js:41`), and **must change** to a bounded sheet. For
    example, a bottom sheet in portrait and a side sheet in landscape, with the exact bounds set in design (S4).
  - The game stays visible beside the sheet, and the frame is only the sheet's box, so a touch outside the sheet
    reaches the game.
  - The game hears `avrana-party-layer {open}` and may pause its own input.
- **Panel contents** ("a one-stop-shop"):
  - Party: people and presence;
  - chat (ADR 0017);
  - next-game suggestions (D8);
  - quick settings: per-device preferences only, never Party state;
  - typed notifications;
  - Host controls: End, switch, Party Home for everyone, hand over hosting, each with confirmation (D6).
- **Panel accessibility:**
  - focus is trapped within the panel;
  - Escape or Close returns focus to the game;
  - reduced motion and 200% text are supported;
  - it works on small viewports, in landscape, with safe-area insets, and with the keyboard and IME over chat.
- **Typed notices** (`your_turn`, `host_started`, `round_over`, plus Party events) carry deadlines on the server clock
  and are worded only by the Party. A game's notice travels **game server → Party Core**, server to server beside the
  session protocol's `ended`, as a typed event (kind, game, participant, deadline). It is never free text, and never
  sent through the bridge. The panel and the button's badge show these notices.
- **The FAB is a constant, system-wide control (owner item 7).** It is required on every Party game and present on
  Party pages too. Each game adopts it in its own Games PR, and the contract amendment is in §6.
- **A game may minimise the FAB, but never remove it (owner item 8).**
  - The floor is today's edge `tab` mode (`layer-mount.js`, `TAB`), an always-reachable drawer handle.
  - During a Party round only the Party frame may send `hide`, and only for a phone that is not a member. A game cannot
    request it.
  - A game that wants it out of the way asks for the tab, through a versioned layer word or the player's own park
    action.
  - Removing or hiding the frame anyway is tampering (D6).
- **Leave during a round (owner item 5).** The accepted AVR-580 flow stays:
  - Leave starts in the FAB and is confirmed on top-level Party Home, never in the coverable frame.
  - It is the single sanctioned exit from a round to Party Home, because it is quitting the Party, not browsing.
  - The Host's Leave and hand-over also stay as AVR-580 and the 2026-10-18 amendment describe.
- **Restore is the reconnect path, not a browsing mechanism.** A reload, a sleep, an OS tab eviction or a network loss
  returns the phone to the same participant and role with a fresh single-use ticket from `bridge.html`, and the game
  resends the full seat state on `hello`: private state only to its own seat. #258's R evidence covers this path.
  - On return the phone has obligations: re-unlock audio, request the wake lock again (`keep-awake.js`), and treat a
    bfcache restore as a reconnect.

**D6. Origin, bridge and layer boundaries; the coverable panel.**

- **Separate origins and bridge rules stay** as today ([ADR 0013](../../adr/0013-party-and-game-browser-origins.md)):
  - a game never reads Party or Admin cookies, and never calls member, host or admin endpoints as the viewer;
  - every bridge message is restricted by source window, registered origin, a closed verb set, the bound session, the
    member's role at the moment of the verb (re-checked by Core), and the exact recipient (never `"*"` for data);
  - tickets stay bound to the session and an opaque per-session participant, are refused for another game or during
    setup, are origin-checked, and die at End, switch or lobby.
- **Host controls live in the FAB, by owner direction.** This supersedes this draft's earlier recommendation to confirm
  trusted verbs only on top-level Party pages.
- **The risk.** The layer frame is an element in the game's DOM. A game can cover, restyle, shrink, hide or remove it.
  #258 showed a covering element taking a tap, and IntersectionObserver v2 could not detect it.
- **Mitigations (required):**
  1. **In-frame confirmation for every destructive Host verb.** End, switch, Party Home for everyone and hand-over use
     a second step inside the Party frame: today's confirm pattern (`layer-app.js` `ACTION_WORDS`) or a two-tap. A
     single stolen tap can never complete one.
  2. **Core decides.** Every state-changing verb is idempotent, Core-authorized at apply time (host re-check) and
     carries `if_version`, so a misdirected or replayed tap acts at most once, and only for the current Host.
  3. **Best-effort tamper detection.**
     - The panel frame reports the box it expects and compares it with what it measures in its own window (size,
       `visualViewport`, resize).
     - A Party-internal heartbeat between the layer frame and the bridge frame (both on the Party origin) lets the
       bridge notice a layer that was removed, hidden, zero-sized or starved.
     - On a mismatch the panel refuses destructive verbs, and the Party records the condition, telling the Host on
       Party Home after the round.
     - `opacity:0` or a cover over an intact frame cannot be detected from inside it. This is stated, not hidden.
  4. **Residual risk, accepted by the owner for owner-installed games (owner items 6 and 8).** A malicious installed
     game can still deny or misdirect taps, and a cover or `opacity:0` over an intact frame stays undetectable. The
     owner accepts this because games are owner-installed and permissioned (AVR-62).
     - Host controls in the FAB are "for now" and may be revisited.
     - A future community or untrusted tier gets **no Host verbs** in the FAB.
- **Required negative tests** before rollout:
  - a covering element cannot complete a destructive Host verb (it needs the in-frame second step);
  - a removed, hidden or zero-sized frame is detected and destructive verbs are refused;
  - a game cannot `hide` the FAB during a Party round: a minimised FAB stays a reachable edge tab, and the drawer opens
    from it;
  - a replayed or stale verb is refused by Core;
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

## 4. Mounted versus restore: resolved by owner direction (was open for AVR-762)

**Resolution:**

- The game stays mounted as the top-level page.
- The FAB is a bounded overlay drawn by a Party frame over it.
- No hidden-frame dependency is introduced.
- Restore-from-server is kept as the reconnect path only.

**Evidence** ([#258](https://github.com/rcnechamkin/avrana-party/pull/258), `e240e35`; loopback fixtures, Chromium and
WebKit on Windows; phones and Pi NOT RUN):

- **The top-level game keeps running under the layer.** With the layer drawer open over the top-level game, it ran at
  61 rAF/s with 0 missed ticks on Chromium, and 14 rAF/s with 0 missed ticks on WebKit. Opening took 18 ms (Chromium)
  and 60 ms (WebKit) at p50.
- **The cover risk is real.** A transparent game element took a tap meant for the drawer (test 10). D6 mitigates it.
- **Restore is correct.** The same participant and role came back with a fresh ticket, the old one was refused as
  `replayed`, and no private frame reached a spectator. It was 230–650 ms on loopback. This is used for reconnect.
- **Not planned:** a Party page that frames the game (#258 M-embed). It needs a new game-origin `frame-ancestors`, the
  game frame cannot be usefully sandboxed, and rAF behaviour depends on the engine (a hidden iframe ran at 0 fps on
  Chromium and 61 on WebKit).

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
- the layer's `open` mode becomes a bounded sheet;
- the panel gains suggestions, quick settings, notices and the full Host controls with in-frame confirmation;
- tamper heartbeat and box check;
- `bridge.js` slimmed for the ticket path.

`destination()` and `party-follow.js` keep following during rounds.

**Games:**

- a paired change for the typed-event route;
- `spectators: "none"` handling;
- any layer-protocol change: a bounded `open` geometry in the vendored `layer-mount.js` changes its pinned digest, so it
  is a paired PR;
- more games opting into the layer, because today only BLUFF and EXPO do, so Tanks and Checkers have no FAB.

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
- Decision 5 and the 2026-10-16 amendment: the floating Party button opens a **bounded panel, never full screen**, and
  the game stays visible. The panel holds people, chat, suggestions, quick settings, notices and the Host's End, switch,
  Party Home and hand-over, each confirmed in the frame (D6).
- Keep decisions 2, 6 and 7 and the Leave, guest-exit and succession amendments, subject to the §7 question.

**ADR 0013:**

- No change to the decision.
- Note that game notices go server to server, never through the bridge.
- **Widen D3's accepted "coverable" limit:** over a game origin, the panel may offer the full Host controls *with D6
  mitigations*, instead of only End and Party Home (`layer.js:126-139` `actions(crossOrigin)`).
- Community or untrusted games keep the narrow set.

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

- The Party layer (FAB) is **required** for every Party game. `provider/avrana-contract.json` `layer.mounted_by` lists
  every Party game, not only BLUFF and EXPO.
- A game keeps the frame above its content.
- A game may only minimise the FAB to the edge tab, never remove or hide it.
- The FAB is also present on Party pages.
- Each game adopts it in its own Games PR.

**PARTY-GAMES-CONTRACT and machine contracts:**

- the layer digest bump for the bounded geometry (and a minimise word, if one is added);
- the typed-event route;
- `party_config.py` derives `spectators`.

**Core docstring:** "Not here (deliberately): … votes … seat assignment" changes.

## 7. Dependencies, owner decisions and what is not decided

- **ADR 0019 (AVR-21/AVR-763).** Suggestions surviving a restart, and the selected game or setup surviving a Core
  restart, wait for it. Until then the Party is memory-only.
- **Decided (owner, 2026-10-26; §1.1 items 5–8):**
  - Guest Leave keeps AVR-580: it starts in the FAB and is confirmed on top-level Party Home, the single sanctioned
    exit.
  - The ADR 0013 D3 widening is accepted "for now", for owner-installed games only, and is revisitable.
  - The FAB is required system-wide.
  - Undetectable cover is accepted as residual risk, with minimise-to-tab as the floor.
- **Not decided here:**
  - the Watch / Not playing wording;
  - voluntary Ready (AVR-700);
  - an idle-selection timeout;
  - the seat-claim UI and named-seat contract;
  - notification templates (AVR-84);
  - motion tiers (#249);
  - mid-round Quit & Spectate (D5b);
  - the panel's exact bounds and the quick-settings list.
