# Draft ADR 0018 — Shared Party activity, personal viewports and universal setup

- **Status:** DRAFT ADR, pending owner approval. NOT accepted and not source authority; nothing here is built, merged or deployed.
- **Date:** 2026-10-26. **Linear:** AVR-705 (this decision), AVR-762 (console and viewport proof, the open decision in §4),
  AVR-701/AVR-700 (select then launch, voluntary Ready), AVR-702 (browse during setup), AVR-703 (Home during a round),
  AVR-468, AVR-88 (next-game suggestions), AVR-84 (activity and notifications), AVR-21/AVR-763 (durable continuity, ADR 0019).
- **Where it lives and why:** `docs/adr/` admits only accepted decisions (`tools/repo-check.py`: an ADR is class
  `decision` with `accepted-portions` authority, and a `proposed` document may hold no authority). So, like the hosted
  staging decision before its acceptance, this draft lives here. On approval it moves to
  `docs/adr/0018-shared-party-activity.md` with an accepted status marker, and the amendments in §6 are applied then.
- **Companion:** [reconciliation](2026-10-26-adr-0018-reconciliation.md): how a round works today, the conflict list with
  file:line references, the retain/adapt/replace matrix for Concept K and the draft PRs, the security regression list,
  the acceptance criteria for the AVR-762 proof, and the staged migration.
- **Separate workstream:** durable continuity (ADR 0019, AVR-21/AVR-763) is not decided or designed here; §7 lists only
  what this decision needs from it.

## 1. Context

The owner approved a product contract (AVR-705) for the offline-first console: phones join the appliance Wi-Fi and play
in browsers, with no internet, app, account or TV. One appliance is one Party and holds one active game.

Accepted source authority says something narrower in four places:

1. **A common forced viewport.** [ADR 0011](../../adr/0011-party-console-model.md) decision 3: every member page is
   where the Party is, always, moved with `location.replace`; "Party Home cannot be browsed" during a round.
2. **No setup for games without a pregame.** ADR 0011 decision 1 sends those games straight to the round, with the
   roster fixed at the Host's tap.
3. **A full-screen, unbrowsable setup.** ADR 0011 decision 4 describes it.
4. **Mandatory Play/Watch.** [ADR 0010](../../adr/0010-party-pregame.md) decision 1 requires an explicit Play or Watch
   from every member who is here, and refuses Start until they all answer.

The approved contract keeps everything else these ADRs protect: Host authority, a single activity, the role freeze at
Start, held results, separate origins and the retirement of LAN Games. The reconciliation lists every affected line.

## 2. Decision (draft)

**D1. One Party, one activity.** One appliance runs one Party, with at most one active Standard Mode game session.
Only the Party Host selects, starts, ends or switches the game. A guest's browser, a direct game URL, a stale tab, a
reconnect or a deep link cannot start a game, switch it or open a second session. This restates ADR 0011's 2026-10-02
amendment and ADR 0014 decision 10, unchanged.

**D2. Shared activity versus personal viewport.** Two separate things:

- **The shared Party activity** is the Party's authoritative state: `home | setup | game | results`, plus the selected
  game, the session, roles and the Host. It lives in Party Core and only the Host moves it (R1/R2 of PARTY-LIFECYCLE
  unchanged).
- **A personal viewport** is what one phone is looking at: Home, Party, Library, Me, the game, or an overlay. It belongs
  to that phone.

Browsing never moves, pauses, cancels or advances the shared activity, and never changes anyone's role or seat. A
personal viewport change MUST NOT advance the Party `version` that host actions compare (`if_version`). Otherwise one
guest's browsing makes the Host's next tap stale, the race behind #208/#218.

The same goes for D4's member intent toggles (Play, Watch, Ready). Host lifecycle verbs should compare a lifecycle
version that member intent does not advance, and Core recomputes the fill at apply time. Claims and Host reassignment
still race under receipt order and stay versioned against each other. The exact split is a design item for stage S2.

**D3. Universal setup.** Every selected game enters a Party-owned setup before the Host's Start, including games
started directly today (no pregame). There is one lifecycle: **Select → Party Setup → Host Start → automatic entry**.
After Start there is no second lobby, join code or identity pick (ADR 0010 decision 5 / GAME-UX Rule 4.6 kept).

In setup, the Party enforces, from the Game Contract:

- eligibility (presence, Limited Mode and device capability, i.e. `seatLimits`/`evaluateSeat`);
- `players.min` and `players.max`;
- the required decisions the game declares (Host options, if AVR-678 is accepted);
- the `spectators` policy.

Eligible members enter the round automatically when it starts. The setup is a state of the selected game, shown on the
Party origin. It is not a full-screen trap: members may browse during it (D5).

**D4. Role assignment: default Play intent, claims, Host reassign, deterministic fill.**

- **Default.** Every eligible member defaults to *Play intent*. That is an intention, not an owned seat.
- **Opting out.** A member may say **Watch** (or **Not playing this round** when the game declares `spectators: "none"`).
  That is a legitimate, non-blocking choice (GAME-UX Rule 4.4/4.4a kept). Opting out removes them from the automatic
  fill.
- **Claims.** A member may explicitly claim a seat (or a declared seat or slot, where the game has them). Claims are
  granted in server receipt order, under Party Core's one lock.
- **Host reassign.** Before Start the Host may reassign any seat. Every reassignment is versioned (`if_version`) and
  visible to everyone.
- **At Start**, seats fill in this order: explicit claims and Host assignments first, then Play-intent members in stable
  join order (the order of `Party.members`) up to `players.max`.
- **Overflow.** Members beyond capacity become spectators only where the game's `spectators` policy allows it.
  Otherwise they stay Party members who are not playing this round (Rule 4.4a state).
- **Start is refused** only for a reason the Party enforces: below `players.min`, or a required decision missing. It is
  never refused because someone has not answered.
- **The freeze.** At Start the roster freezes for the round (ADR 0010 decision 2 kept). A role or a secret can never be
  escalated by browsing, Host status, a deep link, a reload, a reconnect or a second tab:
  - a returning phone gets the role its member already holds;
  - a member who arrives late, or with no role, gets only what the game's `late_join`/`spectators` policy allows;
  - Host status grants lifecycle verbs, never game-private information.

**D5. Independent browsing during setup and play.**

- **What a member may do.** During setup or a round, a member may open Home, Library, Party, Me, notifications or
  suggestions. They keep their membership and their seat authority (PARTY-LIFECYCLE R3: an away seat is never free).
- **Back to Game.** One clear **Back to Game** returns them to the same authorized, scoped session: the same
  participant, the same role and a fresh single-use ticket.
- **The game keeps authority** over its timers, AFK, autopilot, grace and forfeit. The Party adds no game timer.
- **No hidden-frame guarantee.** No design may rely on a game executing in a hidden or background frame. The game
  server is authoritative for everything a phone missed while away.
- **What the Party owns** in this mode: the typed attention and notices ("your turn", "round over", "the Host started")
  and the floating trusted controls. How the game viewport is kept while browsing is the open decision in §4.
- **If R is chosen (§4.1),** these rules apply:
  1. **Browsing is client-held.** A phone-held browse override (e.g. `sessionStorage`, keyed by the Party move,
     `moveKey`) is applied at the call sites on Party Home (`app.js` `onPartyView`, around `app.js:1168-1170`). Same-origin
     game pages, Limited Mode included, apply it too wherever they would otherwise re-route a browsing phone.
     `destination()` itself stays the pure follower rule: it drives the bridge's `navigate` and every follower redirect
     (`party-mode.js:110-124`, `bridge.js:104-106`, `party-follow.js:206-223`). No per-device viewport is stored in Core
     state that bumps `version`, so #225's `visit_home`/`back_to_game` Core verbs are unnecessary.
  2. **Leaving the game uses only existing words, never a URL.** The preferred path, which needs no Games change for shim
     games:
     - the drawer in the layer frame signals the bridge frame through a Party-origin-internal channel (both are
       Party-origin frames in the same page);
     - the bridge pushes its existing v1 `navigate {to:'party'}`;
     - the shim goes to its configured `partyOrigin + '/party/'` (`shim.js:36,89-90`).

     That channel must be shown to work on iOS Safari (storage and channel partitioning), and must be unreachable from
     the game page. Fallbacks are a versioned layer word, or a Core per-device marker that leaves `version` alone. Games
     with no layer (today Tanks, Checkers) have no way to Party Home but the browser's Back. That is an open gap: either
     the layer opt-in widens, or a guest on such a game cannot browse.
  3. **Back to Game** is a plain navigation to the game entry that the Party's own `location` names (today's
     `goToRound`/`addressOf`, `app.js:1199-1213`). It is offered
     only while `location.at` is `game` or `results` for the same session. After End, a switch or a new session it
     disappears or names the new round.
  4. **The returning page** gets a fresh single-use ticket from the small `bridge.html`, never from the console or
     layer frame, which keeps it off the larger page on the critical path. Make `bridge.js` smaller: it imports
     `party-follow.js` only for `profileIdentity` (`bridge.js:30`). The game resends the full seat state on
     `hello`, with the private state only to its own seat, and only the policy-allowed view to anyone else.
  5. **Typed notices** `your_turn`, `host_started` and `round_over` carry deadlines on the server clock. The game
     supplies no text. Under R no game page is loaded while a member browses, so a game's notice travels **game server
     → Party Core**, server to server (beside the session protocol's `ended`). It is a typed event (kind, game, the
     member's participant, server-clock deadline) that Party Core maps to the member and delivers in the Party view.
     It never goes through the bridge.
  6. **Phone obligations on return:** audio re-unlock, a renewed wake-lock request (`keep-awake.js`), a bfcache
     restore treated as a reconnect with a fresh ticket, and Safari's dropped background socket recovered by the same
     path.

**D6. Origin and bridge boundaries unchanged.**

- **Separate origins.** The Party shell and game clients keep separate origins ([ADR 0013](../../adr/0013-party-and-game-browser-origins.md)).
  A game page never reads Party or Admin cookies and never calls member, host or admin endpoints as the viewer.
- **Every bridge message is restricted by:**
  - source window;
  - origin (registered for the game);
  - a closed verb set;
  - the bound session;
  - the member's role at the moment of the verb (re-checked by Party Core);
  - the exact recipient origin (never `"*"` for anything that carries data).
- **Versioned changes.** R itself needs no new bridge verb: it uses v1 `navigate` and v1 `ticket`, plus the game's
  obligation to resend the full seat state on `hello`. Any new verb is a versioned bridge change (`avrana.party-bridge/v2`
  or an additive, negotiated v1 extension), with contract vectors in both repositories.
- **Trusted verbs stay top-level (recommended).** Host verbs, Leave confirmation and suggestion approvals are only ever
  confirmed on top-level Party pages. A mounted frame over a game page is coverable (#258 test 10; IntersectionObserver
  v2 cannot detect a cover), so it carries only the indicator, the way to the Party, people and chat.

  This narrows the owner's accepted D3 "coverable for first-party games", which today lets the Host confirm End and Party
  Home inside the frame over a game origin (`layer.js:126-139`). The narrowing is an owner decision, listed in §6.
- **Tickets stay as they are today:**
  - bound to the session and an opaque per-session participant;
  - refused for another game or during setup;
  - `{game, origin}` checked against the registered game origins;
  - dead at End, switch or lobby.
- **Required negative tests** before any rollout: cross-role secrecy, click interception and covering of trusted
  controls, and accessibility (focus and announcements across the frame boundary). The reconciliation §5 lists them.

**D7. The selected game is always visible.** While a game is selected, being set up, on, or holding results, every member
who is browsing elsewhere sees a subtle, persistent, non-blocking indicator of it (game, phase, their role) with the way
back. It never covers content or traps focus, and it is announced politely, never assertively.

**D8. Next-game suggestions (voting without binding).**

- **Nominations.** Each connected member may hold one nomination at a time.
- **Approvals.** Approvals are public and named. The list is sorted deterministically: approval count descending, then
  the earliest nomination's receipt order.
- **Visibility.** Suggestions are visible during rounds.
- **Host independence.** The Host decides independently. There is no binding vote, queue, auto-launch or threshold.
- **Snapshot.** At the round's end the list is snapshotted through the intermission (results), and cleared when the
  Host next selects a game.
- **Restart.** Recoverable across a Party Core restart before it is resolved, **only once ADR 0019 provides durable Party
  state**. Until then suggestions are memory-only and a restart clears them, said plainly.

**D9. Game-specific play, Party-owned trust.** Game art, play UI and results presentation stay game-specific. Trusted
chrome (Host controls, Leave, End, the selected-game indicator), notifications, attention and system cues are Party-owned
and drawn on the Party origin. There is no generic rules engine: games declare capacity, spectator access and private-
information policy, and enforce their own rules on a trusted server behind their adapters.

**D10. Delivery discipline.**

- Every cross-repo protocol change is versioned, with paired Party and Games PRs and contract vectors.
- Every stage has a proof tier (unit, browser simulation, cross-origin project, Linux, real phones).
- Rollout is reversible, behind a default-off flag, and owner-gated (reconciliation §7).
- Unrun hardware or phone checks are reported as NOT RUN.

## 3. What this keeps

- Host authority and succession.
- One activity.
- The `setup → launching → active → ending → ended` protocol states.
- `nav` moves only on committed transitions.
- Roles freeze at Start.
- Held results (ADR 0011 decision 1, Rule 12.1).
- Host-only End (Rule 12.3).
- BLUFF's refused lobby verbs.
- Tickets are single-use, session-scoped and carry no device or member id (ADR 0006).
- Separate origins and the `__Host-avrana_device` cookie (ADR 0013 D3).
- Limited Mode's same-origin first-party exception (ADR 0012, LIMITED-MODE D5).
- LAN Games retirement (ADR 0014).
- The result envelope (ADR 0015).
- Party-owned messaging (ADR 0017).
- AVR-580 Leave semantics.

## 4. Open decision: mounted game viewport versus server-state restore (AVR-762)

Two ways to keep a game "underneath" while a member browses. **This ADR does not choose. AVR-762 decides it on measured
evidence, and the owner approves.**

| | **Restore on return** | **Mounted** |
|---|---|---|
| What happens | The game page is unloaded while browsing. Back to Game reloads it, asks for a fresh ticket, and the game server re-sends the seat's state. | The game client stays loaded (for example a sandboxed game-origin frame under a Party-origin top-level console, or an equivalent) while Party surfaces are shown over or beside it. |
| Today's code | Nearest: [#225](https://github.com/rcnechamkin/avrana-party/pull/225), and every reload or reconnect (`game-origin.spec.ts` "a reload ... returns the same seat and hand") | Nearest: the Party layer (a Party frame over a top-level game page), inverted. |

**Proposed decision criteria** (all must hold for mounted; otherwise restore):

1. **Restore is mandatory regardless.** Sleep, reload, OS tab eviction and Wi-Fi loss already need it. Mounted can only be
   an optimization on top of a working restore path, never a replacement.
2. **No security regression.** Mounted passes every item of the reconciliation §5 list:
   - cookie containment;
   - frame sandbox flags;
   - CSP `frame-ancestors`/`form-action`;
   - origin and source checks;
   - no click interception of trusted controls;
   - spectator and private-state secrecy;
   - Limited Mode fallback.
   The topology mounted would introduce (the Party framing the game origin) needs game-origin `frame-ancestors` and a
   game-frame sandbox. Those are new owner-approved live changes.
3. **Measured benefit on real phones.** Mounted beats restore on return-to-interactive for at least one representative
   realtime or WASM client by a margin the owner accepts (proposed: at least 1 s at p50 on the reference Android and iPhone
   over appliance Wi-Fi). It also holds no more than an owner-accepted memory ceiling on the low-end reference phone, and
   shows no thermal or battery penalty while browsing.
4. **Platform behaviour proven.** On iOS Safari and Android Chrome: audio unlock, fullscreen, wake lock, keyboard, IME and
   orientation inside the mounted frame, and storage behaviour, are all measured. Background-frame throttling is
   documented, and no correctness depends on frame execution (D5).
5. **Reversible.** Mounted ships behind a flag, with restore as the automatic fallback per game and per phone.

### 4.1 Evidence from AVR-762 and the recommended option (still the owner's decision)

The proof is [draft PR #258](https://github.com/rcnechamkin/avrana-party/pull/258) (`e240e35`,
`experiments/console-proof/REPORT.md`). It ran fixture servers on loopback, with Chromium, and with WebKit on Windows.
No phone, Pi or real game was involved; those remain an owner hardware gate and are NOT RUN.

**What it found:**

- **Restore (R) met criteria 1, 3, 6 and 10 on fixtures.** Back to Game returned the same participant and role with a
  fresh ticket, and the old ticket was refused as `replayed`. The server timer had the same outcome as for a locked
  phone. There was no private frame for a spectator, before or after browsing. The R round trip took 230–650 ms on
  loopback.
- **Mounted for browsing failed the cover test.** A transparent game element over the drawer took the Back to Game tap.
  It also keeps the console resident in the game's page.
- **A Party page embedding the game** needed a new game-origin `frame-ancestors`, could not usefully sandbox the game
  frame, and showed engine-dependent rAF: a hidden iframe got 0 fps on Chromium and 61 fps on WebKit.

**Recommended (not decided):**

- Use **R for browsing**.
- Keep today's mounted Party layer **only for surfaces with no trusted verbs** (people, chat, notices).
- Put Host actions, Leave confirmation and suggestion approvals only on top-level Party pages.

The console technology question is separate (vanilla JS with `@ts-check` and a keyed-list helper is recommended) and
does not affect this ADR.

**Cross-reviews (#258 by A, #257 by B) found three things:**

- **Leaving the game.** The layer protocol has no `navigate`, and the bridge's `navigate` follows Core's view. B showed
  a path with no Games change: a Party-internal signal from the layer frame to the bridge frame, then v1 `navigate`
  (D5 rule 2). It is unproven on iOS. The fallbacks are a versioned layer word or a Core marker that does not bump
  `version`.
- **Game notices under R** must go game server → Party Core (D5 rule 5), not through bridge v2.
- **The fixture's ticket shortcuts must not be copied.** Its tickets have no session binding, use member ids, carry no
  origin check, and can be minted for any game.

Both are carried into D5/D6 and §6.

## 5. Consequences (if accepted)

**Party Core (Python):**

- `_open_session` enters `setup` for every game.
- `setup_status` stops blocking on unanswered members, and caps by fill instead of refusing over `max`.
- New verbs: claim, release, Host reassign, suggestions.
- Late admission honours `spectators`.
- A personal "away from the game" marker, if one is needed, does not bump `version`.

None of this is game logic: Core still never runs rules.

**Console** (`web/party/`):

- `destination()` stops forcing guests between Home and the game during setup and play.
- A Back to Game control, the selected-game indicator and suggestions UI are added.
- `party-follow.js` and the bridge's `navigate` become Host-move notifications, not forced redirects for browsing members.

**Games:** no change for restore at the launch roster level (launch still carries a roster at Start). A paired change
for any new bridge verb, for honouring `spectators: "none"` late admission, and, only if chosen, for the mounted topology.

**Machine contracts:**

- `avrana.game/v0` already carries `players`, `late_join`, `spectators` and `private_player_ui`; Party Core starts reading
  `spectators`.
- Seat or slot claims beyond "a player" need a contract extension (`extensions["net.avrana.party"]`), which this ADR does
  not define.

**Tests:** see the reconciliation §5 and §6.

**Proof:** nothing in this ADR is phone-verified, and no part of it is on the Pi.

## 6. Required amendments (not applied)

These edits are made only when the owner accepts this ADR, in the same PR that moves it to `docs/adr/`. Nothing below has
been changed.

**ADR 0010:**

- Decision 1: replace "Every member who is here chooses **Play this round** or **Watch this round**" and the `unresolved`
  refusal with D4: default Play intent, optional Watch or Not playing, claims, Host reassign, deterministic fill. Keep
  host-only Start, `min_players`/`max_players` and the launch roster shape.
- Keep decisions 2 (roles change only at setup), 3 (game pages wait during setup), 5 and 6.
- Decision 4: already superseded by ADR 0011; add "and by ADR 0018 D3/D5".

**ADR 0011:**

- Decision 1: delete "or → game for a game without a pregame" and "start a game (→ setup, ...)" becomes "→ setup, for
  every game".
- Decision 3: replace "Every member page is where the party is — always ... Party Home cannot be browsed and no other game
  can be opened during a round" with this: a Host move (setup opened, Start, End, switch, results, Party Home) is
  delivered to every phone. A member who is not browsing follows it. A member who is browsing sees the selected-game
  indicator and is not moved, except that Start brings every seated member to the round unless they are browsing, and
  then they get a notice plus Back to Game. No other game can be opened (D1).
- Decision 4: "full-screen scene" becomes "the setup of the selected game, which members may leave to browse and return
  to". Play/Watch wording per ADR 0010 as amended.
- Decision 5: "the game owns the viewport during a round" is kept for the game's own viewport. The Party additionally
  owns the floating control, the indicator and typed notices (it already carries the 2026-10-16 amendment).
- Keep decisions 2, 6 and 7 and every amendment's Leave, guest-exit and succession rules.
- Remove the 2026-10-18 sentence "A guest on such a page has no way to Party Home during the round": D5 gives one.

**ADR 0013:** no change to the decision. Add a note: R uses only bridge v1 (`navigate`, `ticket`); game notices go
server to server (game → Party Core), never through the bridge.

- **If the Party-internal leave signal fails on iOS,** `avrana.party-layer/v1` gains one fixed-word `navigate` instead.
  That is a versioned layer change: the shared `contracts/party-games.v0.json` and Games `provider/avrana-contract.json`
  both pin the layer digest, so it needs a paired PR.
- **Narrowing D3:** the 2026-10-16 layer amendment and `layer.js` `actions()` lose End and Party Home over a game origin.
  The Host confirms them on top-level Party pages. A Party-origin page framing the game origin (the rejected M-embed in #258) would need its own owner-approved CSP
and sandbox amendment to the D2 seam ("the only seam").

**ADR 0014:** no change. Its decision 10 (Developer Mode separate) and the LAN Games retirement stand; D1 restates the
one-activity rule.

**GAME-UX-CONTRACT:**

- Rule 3.1: "moves every member's page" becomes "moves the Party activity; member pages follow unless browsing (D5)".
- Rule 3.2: delete "A game without a pregame has no briefing"; every game has a setup.
- The paragraph "the library, chat row and 'This phone' MUST NOT be visible in it": the setup screen stays focused, but
  members may navigate away.
- Rule 3.3: replace with the D5 browsing rule and Back to Game.
- Rule 3.5: reconnect lands in the Party's current activity *or* the phone's own viewport if it was browsing, never in a
  different role.
- Rule 3.6: allow the indicator and typed notices.
- Rule 4.3: replace "every member who is here answers ... refuses until everyone has answered", and the "*More want to
  play than fit*" bullet, with D4.
- Rule 4.4 point 4 is kept and satisfied by default intent plus free opt-out.
- The phase table: add the browsing column.

**PARTY-LIFECYCLE:**

- State diagram: delete `home --> game: host launches a direct title` and `results --> game: host relaunches a direct
  title`; every selection goes `home --> setup`. "All member surfaces follow the authoritative location" becomes
  "member surfaces follow Host moves unless browsing".
- Awkward-states rows "Arrival during setup/launch" and "A phone sleeps during setup/start": an arrival defaults to Play
  intent.
- Locked decision "Late joiners are spectators by default" stays, qualified by `spectators`.

**PARTY-GAMES-CONTRACT:** bump when the bridge changes, adding the new protocol, shim digest and vectors to
`contracts/party-games.v0.json` and Games `provider/avrana-contract.json`. Declare that Party Core reads `spectators`.

**Machine contracts:**

- `contracts/vectors/party-bridge.v1.json`: a v2 file or additive vectors.
- `avrana/contracts/party_config.py`: derive `spectators`.
- Game Contract extension for seat or slot claims: undefined, to be designed when a game needs named seats.

**Core docstring:** the `avrana/party/core.py` module docstring ("Not here (deliberately): ... votes ... seat
assignment") and the PARTY-LIFECYCLE "Still open" list.

## 7. Dependencies and what is not decided

- **ADR 0019 (AVR-21/AVR-763): durable continuity.** D8's "recoverable across restart" and any restore of the selected game
  or setup after a Core restart depend on it. Until it exists, the Party is memory-only (`core.py` docstring;
  [#236](https://github.com/rcnechamkin/avrana-party/pull/236) option A).
- **AVR-762:** mounted versus restore (§4; evidence in §4.1 and #258, R recommended, owner to decide); whether the console stays vanilla JS or moves to Svelte. That choice is
  orthogonal to this ADR.
- **Not decided here:**
  - the exact wording of Watch and Not playing;
  - whether voluntary Ready (AVR-700) appears;
  - an idle-selection timeout (#247 proposes 10 min);
  - the seat-claim UI and named-seat contract;
  - notification priorities and templates (AVR-84, #241);
  - the motion tier values (#249);
  - mid-round Quit & Spectate (Control Center D5b, still open).
