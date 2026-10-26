# ADR 0018 reconciliation: today's round, conflicts, reuse, security, proof and staging

- **Status:** companion to DRAFT ADR 0018, pending owner approval. NOT accepted; an audit, not source authority. Nothing is changed by it.
- **Date:** 2026-10-26.
- **Read against:** Party `origin/main` 8a7e578, which includes Concept K PRs #195–#201 (merged 2026-10-22), and Games
  `origin/main` 08e0027. The draft PRs were read at the heads listed in §3.
- **Decision text:** [draft ADR 0018](2026-10-26-adr-0018-shared-party-activity.md).

**What each label means:**

| Label | Means |
|---|---|
| **main** | merged source |
| **draft** | only on a draft PR branch |
| **accepted** | accepted ADR or contract text |
| **proposed** | an unmerged proposal |
| **Pi** | the orchestrator reports Party c0d8863 (which includes Concept K) running there; [SYSTEM](../../SYSTEM.md) still records c59f1c8 and has not been reconciled |
| **phones** | **nothing in this document is verified on a real phone**; no recorded evidence was found |

## 1. How a round works today (main)

**Selecting and setting up.**

- The Host taps a tile on Party Home (`tileMode` → `start`, `web/party/lib/party-mode.js:130-136`). That calls
  `POST /party/api/session/launch` → `PartyCore.launch` (`avrana/party/core.py:600-608`).
- **For a pregame game** (BLUFF, EXPO, Courting), `_open_session` (`core.py:616-630`) sets the session to `setup` and
  commits `nav → game`, so `location.at = setup`. `destination()` (`party-mode.js:110-124`, lines 115-119) sends every
  member page to `/party/`, and Party Home draws the full-screen briefing (`app.js:1181-1186`, `show('scene')`).
  - Each member here must answer Play or Watch (`choose`, `core.py:666-683`).
  - Start is refused while anyone is unanswered or the player count is outside min/max (`setup_status`,
    `core.py:648-664`; `start_round`, `core.py:685-703`).
- **For any other game** (Checkers, Hello, Best Guess, Tanks), `_open_session` builds the roster at the tap
  (`core.py:631-642`): members here, in join order, up to `max_players`; the rest are spectators. The session goes
  straight to `launching`. There is no setup.

**Entering the round.**

- When the game accepts (`launch_accepted`, `core.py:705-715`), `location.at = game`. Party Home's `onPartyView`
  (`app.js:1153-1191`) shows "Taking you to …" and leaves with `location.replace`.
  - The Host leaves with `location.assign`, keeping a history entry for the way out (AVR-476, `app.js:1211-1213`).
- `addressOf`/`gameAddress` pick the game origin if Party Core registers one (`game-origins.js`). Limited Mode stays
  same-origin (`party-follow.js:51-57`, `limited.js`).

**On the game page.** There are two paths, chosen by the Games integration script (Games
`web/avrana-integration.js:40-68,200-235`) from the game server's `/api/avrana` `partyOrigin`.

- **Same origin** (the Party origin; the committed nginx serves `/games/` there, and per Party memory BLUFF and EXPO are
  still on the Party origin):
  - The page imports the Party's `party-follow.js`. It joins with the device cookie, follows `destination()` with
    `location.replace` on every view (`party-follow.js:193-230`), and publishes `window.AvranaParty`.
  - The game's JavaScript runs on the Party origin, so it *could* call `/party/api/*` with the member's cookie
    (`Sec-Fetch-Site: same-origin` passes). This is the accepted interim that ADR 0013 removes.
- **Game origin** (`games.avrana.net`):
  - The page vendors `shim.js`, which embeds the invisible `party/bridge.html`
    (`sandbox="allow-scripts allow-same-origin"`, `shim.js:67-75`).
  - The bridge (`web/party/lib/bridge.js`) binds to a registered origin and game, follows the Party with the cookie in
    its own Party-origin frame, pushes a `publicView` with no ids (`bridge.js:61-75`), and sends `navigate {to:'party'}`
    whenever `destination()` says the page is elsewhere (`bridge.js:99-107`). The shim then goes to `partyOrigin + '/party/'`
    (`shim.js:89-90`).

**Seat and ticket.**

- Before each socket connect or reconnect, the page asks for a ticket: same-origin `POST /party/api/session/ticket` with
  the cookie, or through the bridge, which adds `{game, origin}` and is checked against `game_origins`
  (`avrana/party/sessions.py:305-329`).
- `participant_for` (`core.py:972-992`) refuses during setup (`409 setup`) and for a game that is not on. It late-admits
  a member with no place as a **spectator**, whatever the game's `spectators` policy (`_late_admit`, `core.py:1007-1015`).
- The ticket is single-use, lasts 120 s and carries `jti`, `pid`, `role` and `host` (`protocol.py:112,311-330`). A reload
  gets the same participant and a fresh ticket.

**What the Party layer can do over a game page.**

- Games that opt in (Games `LAYER_GAMES = ['bluff','expo']`) mount `party/layer.html`
  (`sandbox="allow-scripts allow-same-origin allow-forms"`, `layer-mount.js:53-64`) as a 48 px fixed frame at the top
  z-index.
- The frame reads the Party with the member's cookie and draws people, chat, Leave and the Host's actions. The page only
  places it (`avrana.party-layer/v1`).
- Over another origin, the Host is offered only End and Party Home (`layer.js:126-139`), because the page owns the frame
  and could cover it (the D3 "coverable" limit).
- A guest gets only "Leave Party…", confirmed on top-level Party Home (AVR-580).
- No guest can reach Home during a round (ADR 0011 2026-10-18 amendment).

**Credentials by origin.**

| Origin | Holds | Notes |
|---|---|---|
| Party | `__Host-avrana_device`: `Path=/; Secure; HttpOnly; SameSite=Lax` (`identity.py:218-222`) | The legacy `avrana_device; Path=/party/` is still read for one release. The comment in `party-follow.js:24` ("Path=/party/") is stale. |
| Limited listener | `avrana_limited` (`identity.py:227-230`) | |
| Game | no Party cookie; only tickets and the game's own `game_token` | nginx strips `Cookie` toward game servers (ADR 0013, 2026-10-10 amendment). |

## 2. Exact conflicts with the approved contract

| # | Accepted text or code (main) | Conflicts with | Ref |
|---|---|---|---|
| C1 | "start a game (→ setup, or → game for a game without a pregame)" | universal setup (D3) | ADR 0011 d1, l.35-36; GAME-UX Rule 3.2 l.103-105; PARTY-LIFECYCLE l.77,81; `core.py:631-642` |
| C2 | "Every member page is where the party is — always … `location.replace` … Party Home cannot be browsed and no other game can be opened during a round" | personal viewport, browse during play (D2/D5) | ADR 0011 d3, l.43-50; GAME-UX Rules 3.1 (l.92-95), 3.3 (l.133-136); `party-mode.js:110-124`; `party-follow.js:206-223`; `bridge.js:104-106`; `app.js:1168-1180` |
| C3 | "The setup is the Party's own full-screen scene"; library, chat row and "This phone" MUST NOT be visible | browse during setup (D5) | ADR 0011 d4, l.51-61; GAME-UX Rule 3.2 para (l.110-116); `app.js:1127,1183` `show('scene')` |
| C4 | "Every member who is here chooses Play or Watch"; Start refused while `unresolved` | default Play intent (D4) | ADR 0010 d1, l.19-27; GAME-UX Rule 4.3 (l.212-229); `core.py:657-659,700-701`; PARTY-LIFECYCLE l.190 |
| C5 | More players than fit → Start refused (`player_count`), no allocation rule | claims in receipt order, Host reassign, deterministic fill, overflow to spectators (D4) | GAME-UX Rule 4.3 bullet 2; `core.py:662-663` |
| C6 | Late or overflow members always become spectators; Core ignores the contract's `spectators` | overflow to spectators only where the game allows (D4); Rule 4.4a (accepted, not built) | `core.py:636-641,1007-1015`; `avrana/contracts/party_config.py` (no `spectators`) |
| C7 | "the game owns the viewport … page shows no Party prose"; platform overlay in play needs an ADR amendment | selected-game indicator, typed notices (D5/D7) | ADR 0011 d5 l.62-67; GAME-UX Rule 3.6 l.158-167 (partly lifted by the 2026-10-16 layer amendment) |
| C8 | "A guest on such a page has no way to Party Home during the round" | Home during a round (D5) | ADR 0011 amendment 2026-10-18, l.177-178 |
| C9 | Core docstring: "Not here (deliberately): … votes … seat assignment" | suggestions (D8), claims (D4) | `core.py:66-67` |
| C10 | ADR 0010 d4: the setup panel on every game page (`party-follow.js`) | already superseded by ADR 0011; text stale | ADR 0010 l.37-44 |

These need **no change**: ADR 0013 (origins), ADR 0014 (LAN Games retired, Developer Mode separate), ADR 0015, ADR 0017,
the ADR 0011 one-activity amendment, held results, and Host-only End.

## 3. Concept K and draft PRs: retain / adapt / replace

| Item | State | Class | Why |
|---|---|---|---|
| #195 K-1 tokens, glass, motion tiers | main, Pi | reusable | presentation only |
| #196 K-2 shell, glass bar, Me | main, Pi | reusable | the bar is the personal-viewport navigation D5 needs; `show('scene')` hiding it is the C3 part |
| #197 K-3 Home K0, Featured, Select for Party | main, Pi | reusable | "Select" maps to D3 Select |
| #198 K-4 K1 briefing, K3 Just played | main, Pi | needs change | the briefing must drop mandatory Play/Watch (C4) and allow leaving (C3) |
| #199 K-5 Party and Me tabs, Make host | main, Pi | reusable | |
| #200 K-6 motion 200 ms / 600 behind flag | main, Pi | reusable | values decided by #249 |
| #201 K-7 docs, Actual vs Proposal | main, Pi | reusable | update the table when D3–D5 land |
| #247 select then launch (AVR-701/700), `ea2c4b8` | draft, docs | needs change | Universal setup is right, and so are "no direct start" and non-gating Ready. It keeps two setup kinds (`select` without choice vs `choose` with mandatory Play/Watch); D4 unifies them under default intent. |
| #248 browse during setup (AVR-702), `a193503` | draft, docs | needs change | The client-only browse and pinned selection row fit D5/D7. Its "a browsing member who has not chosen still blocks Start" contradicts D4 and goes. |
| #225 Home during a round (AVR-703), `d0637f8`, `proposals.home_in_round` default off | draft, code | needs change; candidate restore prototype | It moves only this device (good) and has Back to game without End on Home (good). But `visit_home`/`back_to_game` call `_commit()`, so they bump the Party `version` for everyone (the Host's `if_version` goes stale, the #208 pattern; violates D2), and keep personal viewport in authoritative Core state. It conflicts with ADR 0011 d3/d5 by design. Cross-origin, Linux and phones not run. |
| #249 motion tiers (AVR-704), `d4c8ed2` | draft, docs | reusable, independent | GAME-UX Rule 11.5 only |
| #241 activity and notifications (AVR-84), `b8d55e7` | draft, docs | reusable | The typed, closed, server-filtered events are the "typed attention/notices" of D5/D9. Game notices via bridge v2 match D6. |
| #252 activity feed prototype, `920b3c8` | draft, code, uncalled | reusable | pure `Feed`; wire in at stage S6 |
| #236 continuity (AVR-21), `bbfcee5` | draft, docs | dependency, not this ADR | Belongs to ADR 0019. D8 restart recovery waits on it. |
| #220 lifecycle bounds (AVR-260), `551584a` | draft, code | reusable, orthogonal | launch and end timeouts only |
| #218 #208 end retry, `3db14b2` | draft, code | done (independent fix); keep | It is the same stale-version race D2 must avoid creating more of. |

**Material contradictions with the approved direction:**

- **On main:** C1–C6 are the shipped, accepted behaviour, and they are on the Pi through c0d8863.
- **In PRs:**
  - #225's version-bumping personal-viewport state;
  - #248's "unanswered browsing member blocks Start";
  - #247's retained mandatory Play/Watch for pregame games.

## 4. Mounted versus restore

See the draft ADR §4 for the criteria. Main has neither as a browsing feature: every reload or reconnect already uses
restore (a fresh ticket, the same participant), and #225 is a restore prototype.

## 5. Security regression list (a new console or bridge can break these)

| # | Invariant | Guarding test today |
|---|---|---|
| S1 | Device cookie is `__Host-`, `Path=/`, `HttpOnly`, `Secure`, `SameSite=Lax`; a planted second cookie mints nothing | `tests/unit/test_party_service.py` (`test_join_issues_a_production_cookie`, `test_two_device_cookies_are_no_identity_and_mint_nothing`, `test_the_host_cookie_wins_over_an_old_cookie_planted_beside_it`) |
| S2 | Party API refuses cross-site browser requests (`Sec-Fetch-Site`, Origin allow-list), even GETs; no CORS | `test_party_service.py` (`test_a_post_from_the_game_origin_is_refused_with_the_members_own_cookie`, `test_a_browser_request_from_another_origin_gets_nothing_even_a_get`); `tests/provider/game-origin.spec.ts` "cannot use the Party as itself" |
| S3 | nginx strips `Cookie` to game servers and the arcade | `tests/unit/test_nginx_site.py` |
| S4 | Only `bridge.html` and `layer.html` are frameable, and only by the game origin (layer: also `'self'`); every other Party page `frame-ancestors 'none'`; `form-action 'self'` | `tests/offline/bridge.spec.ts` "every other Party page still refuses to be framed"; `tests/party/party-layer.spec.ts` "layer.html may be framed by …"; `test_nginx_site.py`. **No test** asserts `form-action`. |
| S5 | Bridge frame sandbox `allow-scripts allow-same-origin` (no top navigation, popups or forms); layer adds only `allow-forms` | `tests/offline/party-bridge.test.mjs` "the shim embeds the Party bridge, sandboxed"; `party-layer.test.mjs` "the mount frames the layer page" |
| S6 | Bridge listens only to `window.parent`, binds the first registered origin and game, replies to the bound origin only, ignores malformed messages; the shim trusts only its own frame and origin | `party-bridge.test.mjs` (tests at l.118-185, 370) |
| S7 | Layer messages are forged-proof both ways | `game-origin-layer.spec.ts` "forged layer messages move nothing"; `party-layer.test.mjs` l.189. **Gap:** `layer-app.js:44,425` posts a content-free `ready` to `"*"`. Harmless today; a new console must never put data in a `"*"` post. **No test** pins it. |
| S8 | A game page sees no ids, no member names but the Host's, no result summary | `party-bridge.test.mjs` "a game page is shown a view with no id", "Party member result summaries never cross" |
| S9 | `navigate` carries a word, never a URL; return is fixed `partyOrigin + '/party/'` | `party-bridge.test.mjs` l.246, 362 |
| S10 | Clickjacking: over a cross-origin page the Host is offered only End and Party Home; Leave and hand-over are confirmed on top-level Party pages | `party-layer.test.mjs` "only the host is offered host actions"; `game-origin-layer.spec.ts` l.165, 187, 269; `guest-exit.test.mjs`. **No test** for a game element *covering* the layer frame (an overlay lure) or an `opacity:0` frame. A Back to Game or suggestions control in the frame inherits this. |
| S11 | Tickets are single-use, 120 s, origin-checked for the game; old tickets die at end, switch or lobby | `tests/unit/test_party_protocol.py` (replay), `test_party_session_flow.py` (l.240, 264-301, 456-518) |
| S12 | Ticket replay across browse/return: Back to Game must fetch a fresh ticket for the same participant, never reuse one | `game-origin.spec.ts` "a reload … returns the same seat and hand with a fresh ticket", "a dropped socket … never as a watcher". **No test** for a browse-then-return cycle. |
| S13 | Deep-link escalation: a page naming another game gets no ticket; setup gets `409 setup`; a non-member gets nothing | `test_party_session_flow.py` `test_a_page_naming_another_game_gets_no_ticket_and_starts_nothing`, `test_no_ticket_without_membership_or_a_game`; `game-origin.spec.ts` l.198 |
| S14 | Spectator private state: only spectator tickets get the spectator view; players get only their own hand; spectator sockets demote at session end | Games `tests/test_bluff_party_pregame.py`. **No Party-side test**, and **no test** that late admission respects `spectators: "none"` (C6; today it admits a spectator). |
| S15 | Host status grants verbs, not secrets; the game re-asks the Host claim at the action | `test_party_session_flow.py` l.168, 187 |
| S16 | Limited Mode: games stay same-origin with the Limited credential; no bridge; plain HTTP never sets a Full cookie | `tests/unit/test_party_limited_mode.py`, `tests/offline/limited.spec.ts`, `party-follow.test.mjs`. Accepted weakness: same-origin game JS can act as the member there (LIMITED-MODE D5). |
| S17 | Same-origin BLUFF and EXPO on the Party origin (deployed shape) can call the Party API as the viewer | accepted interim (ADR 0013 step order); **no test** prevents a new feature from depending on it |
| S18 | Personal-viewport state must not bump `version` (stale Host actions) | **no test** |
| S19 | Accessibility across the frame: focus enters and leaves the drawer, Escape returns, game keys paused while open | `game-origin-layer.spec.ts` l.420, 441; `party-layer.spec.ts` l.427. **No test** for the selected-game indicator or Back to Game announcements. |

## 6. Acceptance criteria for the AVR-762 proof

Each is pass or fail with recorded revisions. Unrun hardware is reported as NOT RUN.

1. **Restore path.** A seated player opens Home, Library, Party and Me during a round. Back to Game returns them to the
   same participant id and role, with a fresh ticket (the old `jti` refused on replay). The game state is resent by the
   server. Shown for a turn-based client and a realtime/WASM client.
2. **No shared-state effect.** Browsing changes no other phone's page, the Party `location`/`nav`, or the Party
   `version`. A Host action issued during a guest's browse is not refused as stale.
3. **Game authority.** The AFK, timer and autopilot outcome while browsing matches a locked phone of the same duration.
   The Party adds no timer. Nothing depends on a hidden or background frame executing; it is measured, not assumed.
4. **Notices.** "Your turn", "the Host started", "round over" reach a browsing member as Party-owned typed notices. The
   game supplies no free text.
5. **Indicator (D7).** The selected-game indicator is visible on every personal view, is non-blocking, takes no focus,
   is announced politely, and works at 200% text and with reduced motion.
6. **Containment.** Every row of §5 passes, including new negative tests:
   - S10: a covering element over trusted controls cannot trigger Host verbs (they stay confirm-on-Party or uncoverable);
   - S12: the browse-and-return replay;
   - S14: cross-role secrecy, where a spectator, a Host who is not seated, a deep link and a second tab never receive a
     player's private state;
   - S18.
7. **Mounted only.** If a mounted variant is proposed: the game frame's sandbox flags and the game-origin
   `frame-ancestors` are stated, no Party cookie or storage is readable from it, and a game frame cannot navigate the
   top-level Party page.
8. **Limited Mode** (plain HTTP, same origin) keeps working with restore and degrades visibly.
9. **Phones.** iOS Safari and Android Chrome, on the appliance Wi-Fi: cold and warm offline load, background/foreground,
   orientation, touch and keyboard, IME, audio unlock and wake lock, measured return-to-interactive (p50/p95), and memory
   on a low-end phone. Each is NOT RUN until physically run.
10. **The vanilla versus Svelte comparison** uses identical Concept K layouts and fully static offline bundles, and
    changes no Core lifecycle, origin or bridge rule.
11. **The decision report** names the revisions, the measurements, the chosen viewport model against the draft ADR §4
    criteria, and the rollback route.

## 7. Staged migration (smallest reversible stages)

| Stage | Core | Console | Games | Flag / gate |
|---|---|---|---|---|
| S0 | none | none | none | owner accepts ADR 0018 (§6 amendments applied) |
| S1 universal setup | `_open_session` → `setup` for every game; select-kind setup from #247 | the K1 briefing for every game | none (launch roster unchanged); update the drivers that assume one-tap launch | `universal_setup` off; paired Games driver PR |
| S2 default intent and fill | `setup_status` no longer blocks on unanswered; claims, Host reassign, fill, overflow by `spectators`; late admission honours `spectators` | Watch / Not playing as opt-out; claim and reassign UI | honour "not playing" (no ticket) for `spectators: "none"` | `seat_intent` off; contract and vector update |
| S3 browse during setup | none | #248 adapted (no blocking); D7 indicator | none | client flag |
| S4 Home during a round (restore) | per-device browse marker that does **not** bump `version` (or none: a client-only viewport) | Back to Game, indicator, `destination()` no longer forces browsing guests | none if the bridge `navigate` semantics are unchanged; else bridge v2 | `home_in_round` off (from #225, reworked) |
| S5 typed notices | #252 feed wired; party, member and host events | notices UI | game notices: bridge v2 and AVR-62 permission | `activity` off; paired PRs |
| S6 suggestions | nominations and approvals, memory-only | suggestions UI | none | `suggestions` off; restart recovery only after ADR 0019 |
| S7 mounted viewport (only if AVR-762 chooses it) | none | Party-origin console framing the game origin | `frame-ancestors`, frame-safe clients | owner-approved live CSP change; per-game flag, restore fallback |
| S8 default on | none | flip the flags after Tier 3 phone proof | none | owner gate per flag |

Every stage keeps the previous behaviour with its flag off, and changes no deployed Pi state without the owner.
