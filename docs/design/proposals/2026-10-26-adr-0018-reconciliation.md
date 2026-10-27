# ADR 0018 reconciliation: today's round, conflicts, reuse, security, proof and staging

- **Status:** companion to DRAFT ADR 0018, pending owner approval. NOT accepted; an audit, not source authority. Nothing is changed by it.
- **Date:** 2026-10-26; revised the same day for the owner direction recorded in draft ADR §1.1.
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


## 2. Exact conflicts with the approved contract (as narrowed by the owner, 2026-10-26)

| # | Accepted text or code (main) | Conflicts with | Ref |
|---|---|---|---|
| C1 | "start a game (→ setup, or → game for a game without a pregame)" | universal setup (D3) | ADR 0011 d1, l.35-36; GAME-UX Rule 3.2 l.103-105; PARTY-LIFECYCLE l.77,81; `core.py:631-642` |
| C2 | Forced following: "Every member page is where the party is — always" | **largely retained.** The owner affirms that no one goes to Party Home in a game, so it stays for rounds. Only the setup consequence narrows (C3). | ADR 0011 d3, l.43-50; Rules 3.1 and 3.3; `party-mode.js:110-124`; `party-follow.js:206-223`; `bridge.js:104-106`; `app.js:1168-1180` |
| C3 | "The setup is the Party's own full-screen scene"; library, chat row and "This phone" MUST NOT be visible | setup leavable within Party Home (D3) | ADR 0011 d4, l.51-61; GAME-UX Rule 3.2 para (l.110-116); `app.js:1127,1183` `show('scene')` |
| C4 | "Every member who is here chooses Play or Watch"; Start refused while `unresolved` | default Play intent (D4) | ADR 0010 d1, l.19-27; GAME-UX Rule 4.3 (l.212-229); `core.py:657-659,700-701`; PARTY-LIFECYCLE l.190 |
| C5 | More players than fit → Start refused (`player_count`), with no allocation rule | claims, Host reassign, deterministic fill, overflow (D4) | GAME-UX Rule 4.3 bullet 2; `core.py:662-663` |
| C6 | Late or overflow members always become spectators; Core ignores `spectators` | overflow only where the game allows it (D4); Rule 4.4a | `core.py:636-641,1007-1015`; `party_config.py` |
| C7 | Layer `open` mode is the full viewport | the panel never covers the whole screen (D5, owner item 2) | `web/party/bridge/layer-mount.js:41` `layerBox`; `layer-app.js` `show()` |
| C8 | Over a game origin the Host gets only End and Party Home in the frame (the D3 "coverable" limit) | the full Host controls in the FAB (owner item 3) with D6 mitigations | `layer.js:126-139` `actions(crossOrigin)`; ADR 0011 amendment 2026-10-18 l.175-177; ADR 0013 D3 |
| C9 | Core docstring: "Not here (deliberately): … votes … seat assignment" | suggestions (D8), claims (D4) | `core.py:66-67` |
| C10 | ADR 0010 d4: the setup panel on every game page | already superseded by ADR 0011; the text is stale | ADR 0010 l.37-44 |
| C11 | AVR-580 guest exit confirms Leave on top-level Party Home | "No players should be able to actually go back to the Party Home Menu while in game" | ADR 0011 amendment 2026-10-18; `layer.js:146-150` `exitOffered`. **Decided (owner, 2026-10-26):** keep AVR-580 as the single sanctioned exit (draft ADR D5). |

These need **no change**: ADR 0013's origins (D3 is widened, see C8), ADR 0014, ADR 0015, ADR 0017, the one-activity
amendment, held results, Host-only End, and ADR 0011 decision 3's following during rounds.

## 3. Concept K and draft PRs: retain / adapt / replace

| Item | State | Class | Why |
|---|---|---|---|
| #195, #196, #197, #199, #200, #201 (Concept K) | main, Pi | reusable | presentation, shell, Featured and Select, tabs, motion and docs |
| #198 K-4 K1 briefing | main, Pi | needs change | drop mandatory Play/Watch (C4); make it leavable within Party Home (C3) |
| Party layer (`layer-mount.js`, `layer-app.js`, AVR-292) | main | **adapt: it becomes the FAB** | bounded sheet instead of full viewport (C7); adds suggestions, quick settings, notices and the full Host controls with in-frame confirmation; tamper heartbeat; more games opt in |
| #247 select then launch (AVR-701/700), `ea2c4b8` | draft, docs | needs change | universal setup, yes; unify its `select`/`choose` kinds under D4 |
| #248 browse during setup (AVR-702), `a193503` | draft, docs | needs change; **kept** | setup is on Party Home, so browsing there is consistent with the owner; drop "an unanswered browsing member blocks Start" |
| #225 Home during a round (AVR-703), `d0637f8` | draft, code | **not pursued (owner, 2026-10-26)** | no Party Home in a round. It also bumped `version` for everyone through `_commit()`. AVR-703/AVR-468 become "the FAB during a round, plus reconnect/restore". |
| #258 console proof (AVR-762), `e240e35` | draft, experiment | evidence; done | Owner kept vanilla JS (Svelte rejected). The adopted model is its M strategy over a top-level game, with a bounded FAB. R is kept for reconnect. M-embed is not planned. |
| #249 motion tiers (AVR-704) | draft, docs | reusable | GAME-UX Rule 11.5 |
| #241 activity and notifications (AVR-84) | draft, docs | reusable, needs change | Typed, closed, server-filtered events are right. Game notices go game server → Party Core (D5), not bridge v2. They are shown in the FAB. |
| #252 activity feed prototype | draft, code | reusable | wire in at S5 |
| #236 continuity (AVR-21) | draft, docs | dependency | ADR 0019; suggestions and setup surviving a restart wait for it |
| #220 lifecycle bounds | draft, code | reusable, orthogonal | |
| #218 #208 end retry | draft, code | done; keep | the stale-version race that D2 avoids widening |

**Material contradictions with the approved direction:**

- **On main, and on the Pi via c0d8863:** C1, C3–C7.
- **In PRs:**
  - #225 (now not pursued);
  - #248's blocking rule;
  - #247's retained mandatory Play/Watch.

## 4. Mounted versus restore: resolved

By owner direction the game stays mounted as the top-level page, and the FAB is a bounded overlay. Restore is the
reconnect path only. The evidence is in draft ADR §4: #258 measured 61 rAF/s on Chromium and 14 rAF/s on WebKit with
0 missed ticks under the open layer, plus the cover-test result and restore correctness.

## 5. Security regression list (a new console, FAB or bridge can break these)

| # | Invariant | Guarding test today |
|---|---|---|
| S1 | Device cookie is `__Host-`, `Path=/`, `HttpOnly`, `Secure`, `SameSite=Lax`; a planted second cookie mints nothing | `tests/unit/test_party_service.py` (`test_join_issues_a_production_cookie`, `test_two_device_cookies_are_no_identity_and_mint_nothing`, `test_the_host_cookie_wins_over_an_old_cookie_planted_beside_it`) |
| S2 | Party API refuses cross-site browser requests (`Sec-Fetch-Site`, the Origin allow-list), even GETs; no CORS | `test_party_service.py` (`test_a_post_from_the_game_origin_is_refused_with_the_members_own_cookie`, `test_a_browser_request_from_another_origin_gets_nothing_even_a_get`); `tests/provider/game-origin.spec.ts` "cannot use the Party as itself" |
| S3 | nginx strips `Cookie` to game servers and the arcade | `tests/unit/test_nginx_site.py` |
| S4 | Only `bridge.html` and `layer.html` are frameable, and only by the game origin (the layer also by `'self'`); every other Party page has `frame-ancestors 'none'`; `form-action 'self'` | `tests/offline/bridge.spec.ts`; `tests/party/party-layer.spec.ts` "layer.html may be framed by …"; `test_nginx_site.py`. **No test** asserts `form-action`. |
| S5 | Frame sandboxes: bridge `allow-scripts allow-same-origin`; layer adds only `allow-forms`; neither has top navigation | `party-bridge.test.mjs`; `party-layer.test.mjs` "the mount frames the layer page" |
| S6 | The bridge listens only to `window.parent`, binds the first registered origin and game, replies to the bound origin only, and ignores malformed messages; the shim trusts only its own frame and origin | `party-bridge.test.mjs` l.118-185, 370 |
| S7 | Layer messages are forged-proof both ways; the content-free `ready` to `"*"` (`layer-app.js:44,425`) never carries data | `game-origin-layer.spec.ts` "forged layer messages move nothing"; `party-layer.test.mjs` l.189. **No test** pins the `"*"` post as content-free. |
| S8 | A game page sees no ids, no member names but the Host's, and no result summary | `party-bridge.test.mjs` |
| S9 | `navigate` carries a word, never a URL; the return is fixed | `party-bridge.test.mjs` l.246, 362 |
| S10 | **Coverable FAB (C8).** A covering element cannot complete a destructive Host verb (End, switch, Party Home for everyone, hand-over), because each needs an in-frame second step | today: `party-layer.spec.ts` "the Host ends the round from the layer, after a confirmation; Cancel changes nothing", and `game-origin-layer.spec.ts` l.165 (asked first). **No test** with a covering game element, and none for hand-over and switch over a game origin, since they are not offered there today. |
| S11 | Tickets are single-use, last 120 s, are origin-checked for the game, and die at end, switch or lobby | `test_party_protocol.py` (replay); `test_party_session_flow.py` l.240, 264-301, 456-518 |
| S12 | Reconnect (reload, sleep, network) gets a fresh ticket for the same participant and never reuses one | `game-origin.spec.ts` "a reload … same seat and hand with a fresh ticket", "a dropped socket … never as a watcher" |
| S13 | Deep links: a page naming another game gets no ticket; setup gets `409 setup`; a non-member gets nothing | `test_party_session_flow.py` l.230, 256; `game-origin.spec.ts` l.198 |
| S14 | Spectator private state; `spectators: "none"` honoured at late admission | Games `tests/test_bluff_party_pregame.py`. **No Party-side test**, and **no test** for `spectators: "none"` (C6). |
| S15 | Host status grants verbs, not secrets; the game re-asks the Host claim at the action | `test_party_session_flow.py` l.168, 187 |
| S16 | Limited Mode: same origin, the Limited credential, no bridge | `test_party_limited_mode.py`, `tests/offline/limited.spec.ts`, `party-follow.test.mjs`. Accepted weakness: LIMITED-MODE D5. |
| S17 | Same-origin BLUFF and EXPO (the deployed shape) can call the Party API as the viewer | accepted interim; **no test** stops new features depending on it |
| S18 | Panel state, suggestions and intent toggles never advance the version that Host actions compare | **no test** |
| S19 | Panel accessibility: focus trapped in the bounded panel, Escape returns focus to the game, game keys paused while open | `game-origin-layer.spec.ts` l.420, 441; `party-layer.spec.ts` l.427 (full-viewport drawer today). **No test** for a bounded sheet. |
| S20 | **Tamper detection:** a removed, hidden, zero-sized or starved layer frame is noticed (box self-check, layer↔bridge heartbeat), and destructive verbs are refused while it is | **no test** (new) |
| S22 | **FAB floor:** during a Party round a game cannot `hide` the FAB or remove it without detection; minimised, it stays a reachable edge tab from which the drawer opens | partly: `party-layer.spec.ts` parking and tab tests. **No test** that a game cannot hide or remove it. |
| S21 | State-changing FAB verbs are idempotent and Core-authorized with `if_version`; a replayed or stale tap acts at most once | partly: `test_party_core.py` host checks, the #218 stale retry. **No test** for suggestions or hand-over idempotence from the frame. |

## 6. Acceptance criteria (FAB during a round; restore for reconnect)

Each criterion is pass or fail, with recorded revisions. Unrun hardware is reported as NOT RUN.

1. **The game stays top-level and visible.** Opening the panel never navigates away from the game, and never covers the
   whole viewport, in portrait or landscape and on small phones. The game's socket keeps receiving with 0 missed
   server ticks.
2. **Panel contents.** People, chat, suggestions (nominate, named approvals, deterministic order), quick settings,
   notices and the Host controls, all inside the bounded panel.
3. **No shared-state effect.** Opening, closing or using the panel moves no other phone, `location` or `nav`, and does
   not advance the lifecycle version. A Host action right after a guest's suggestion or panel use is not refused as
   stale.
4. **Game authority.** The timer and AFK outcome with the panel open matches one with the panel closed. No design relies
   on a hidden frame.
5. **Notices.** `your_turn`, `host_started` and `round_over` arrive as Party-worded typed notices with server-clock
   deadlines, from game server → Core. The game supplies no text.
6. **Coverable-frame mitigations.** Negative tests S10, S20 and S21 pass: a covering element cannot complete a
   destructive verb; tampering is detected and verbs are refused; replays and stale taps are refused.
7. **Reconnect.** A reload, sleep or network loss returns the same participant and role with a fresh ticket (the old one
   refused), and the server resends the seat state, private state only to its seat (S12, S14).
8. **Accessibility.** Focus is trapped in the panel, and Escape or Close returns it to the game. Reduced motion, 200%
   text, safe areas, and the keyboard and IME over chat all work.
9. **The FAB is constant.** It is present on every Party game and on Party pages. A game can minimise it only to the
   edge tab, which stays reachable; the drawer opens from it, and `hide` is refused during a round (S22).
10. **Limited Mode.** The same-origin FAB works with the Limited credential and degrades visibly.
11. **Phones.** iOS Safari and Android Chrome on the appliance Wi-Fi: panel open and close timing, game frame rate and
    ticks with the panel open, orientation, IME, audio and wake lock after reconnect, and memory on a low-end phone.
    NOT RUN until physically run.

The console technology is settled: the owner kept vanilla JS and rejected Svelte (#258 evidence).

## 7. Staged migration (smallest reversible stages)

| Stage | Core | Console | Games | Flag / gate |
|---|---|---|---|---|
| S0 | none | none | none | owner accepts ADR 0018 (§6 amendments applied) |
| S1 universal setup | `_open_session` → `setup` for every game | the K1 briefing for every game | update the one-tap drivers | `universal_setup` off; paired driver PR |
| S2 default intent and fill | no blocking on unanswered members; claims, reassign, fill, `spectators`; a lifecycle version not advanced by intent | Watch / Not playing opt-out; claim and reassign UI | "not playing" for `spectators: "none"` | `seat_intent` off; contract and vector update |
| S3 browse during setup | none | #248 adapted (no blocking); the briefing becomes a dismissible sheet within Party Home; D7 indicator | none | client flag |
| S4 bounded FAB panel | nominate and approve (memory-only until ADR 0019); idempotent, `if_version` on Host verbs | bounded sheet replacing full-viewport `open` (`layerBox`); focus trap within the panel; Escape returns focus to the game; reduced motion, 200% text, small viewports and landscape, safe areas; suggestions; quick settings (per device); full Host controls with in-frame confirmation; box self-check and layer↔bridge heartbeat; S10/S19/S20/S21 tests | vendored `layer-mount.js` digest bump (paired PR); **the layer becomes required: every Party game adopts it in its own Games PR**; minimise-to-tab floor; S22 test | `fab_panel` off; owner accepts the ADR 0013 D3 widening for owner-installed games (AVR-62) |
| S5 typed notices | #252 feed wired; internal game → Core typed-event route, authenticated like `ended` | notices in the FAB panel and badge | send typed events server to server | `activity` off; paired PRs |
| S6 suggestions durable | restart recovery | none | none | after ADR 0019 only |
| S7 iframe-embedded mounted | none | none | none | **not planned** (#258) |
| S8 default on | none | flip flags after Tier 3 phone proof | none | owner gate per flag |

Superseded: the earlier S4 "Home during a round via restore" (owner, 2026-10-26). Restore stays only as the reconnect
path, which already exists on main.

Every stage keeps the previous behaviour with its flag off, and changes no deployed Pi state without the owner.
