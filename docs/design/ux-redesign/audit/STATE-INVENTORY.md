# State inventory for the UX/UI redesign: what the backend and the phone hold today

Status: **audit evidence (2026-10-05); inventory of source at avrana-party origin/main 578534f and avrana-party-games origin/main a448972, design input, not contract.**

Read-only inventory for the design phase of the
[UX/UI product brief](../../AVRANA-UX-UI-PRODUCT-BRIEF.md). It lists what Party Core, the catalog,
the phone and EXPO hold today, then checks each UX need of the brief against it. Nothing here was
run on a phone, a server or a test suite: every row is a reading of source and cites `file:line`.
Party paths are relative to this repository. Games paths are relative to the Games repository
export and are written as plain code spans. "Core" means `avrana/party/core.py`.

Three findings change the design conversation more than the rest:

- Party Core has **no chat, no notifications, no votes, no history and no favorites**. Chat on
  Party Home is the retiring LAN Games ChatHub with its own identity (section 5).
- The catalog has **no duration, genre vocabulary, social format, team or "classic" field**
  (section 3). Player count and display requirement exist.
- EXPO already publishes the current winner of an unfinished trick (`trick_leading`) and a full
  failure `cause` (section 8). No EXPO backend change is needed for the brief's section 25.

## 1. Party Core HTTP surface today

Guards on every phone route: allowed `Host` (`avrana/party/service.py:305`), same-origin
`Sec-Fetch-Site` when the browser sends it (`service.py:318-321`), and for POST an allowed
`Origin`, a JSON body of at most 8 KiB (`service.py:358-365`). Every answer is `no-store`
(`service.py:259`). Identity is the device cookie only (`avrana/party/identity.py:35-39`).
Host verbs carry `if_version` and are refused `stale` when the party moved (Core `:211-217`).
Refusal codes and HTTP statuses: `service.py:270-273`.

| Route | Method | Who may call | Returns or changes | Source |
|---|---|---|---|---|
| `/party/api/state?since=V&wait=S` | GET | anyone; no cookie gives an observer view with `me: null` | the caller's view (section 2); long poll up to 25 s; a member's poll is their heartbeat | `service.py:333-346`, `service.py:99-115`, Core `:334-348` |
| `/party/api/join` `{name, avatar}` | POST | anyone from an allowed origin; the only route that issues a cookie | creates or revives the member; the first member becomes host; idempotent | `service.py:436-455`, Core `:307-332` |
| `/party/api/heartbeat` | POST | member | "still here" from a page that is not Party Home | `service.py:382-384` |
| `/party/api/rename` `{name, avatar}` | POST | member | name (1 to 16 characters, de-duplicated) and bundled avatar id | `service.py:385-386`, Core `:350-358`, `:95-116` |
| `/party/api/leave` | POST | member | explicit leave; no UI calls it (ADR 0011 decision 2) | `service.py:387-388`, Core `:360-369` |
| `/party/api/host` `{to, if_version}` | POST | host | hands the role to a member who is here | `service.py:389-390`, Core `:371-378` |
| `/party/api/session/launch` `{game, if_version}` | POST | host | opens the session: `setup` for a pregame title, else `launching` with everyone here as players up to the maximum | `service.py:123-130`, Core `:389-420` |
| `/party/api/session/choice` `{choice}` | POST | member, only during `setup` | own `player` or `spectator` choice for the round | `service.py:397-398`, Core `:445-462` |
| `/party/api/session/start` `{if_version}` | POST | host | starts the round set up; refused `unresolved` or `player_count` with a sentence | `service.py:141-148`, Core `:464-482` |
| `/party/api/session/end` `{if_version}` | POST | host | ends or cancels the session for everyone | `service.py:201-211`, Core `:504-521` |
| `/party/api/session/switch` `{game, if_version}` | POST | host | ends the game that is on, then opens the next | `service.py:150-167`, Core `:523-570` |
| `/party/api/home` `{if_version}` | POST | host, only at `results` | results to Party Home for everyone | `service.py:132-139`, Core `:643-653` |
| `/party/api/session/ticket` `{game, origin}` | POST | member | a session ticket for the active round; `409 setup` or `no_game` otherwise; a late member is admitted as spectator | `avrana/party/sessions.py:143-165`, Core `:686-706` |
| `/party/api/bridge` | GET | anyone | `{schema, origins}`: which game origins the bridge frame serves | `service.py:331-332` |
| `/party/api/status` | GET | anyone, no cookie | `avrana.status/v0` (section 7), cached 5 s | `avrana/ops/status.py:284-302`, `docs/design/STATUS-ENDPOINT.md:17-18` |
| `/party/api/origin.json` | GET | anyone | answered by nginx, not Core: "the Pi answered" | `avrana-party.nginx:116`, `web/party/app.js:46-53` |
| `/internal/party-session/v0/ended`, `/host` | POST | a game server only (loopback or Unix socket, signed) | ends the session, optionally with a result; answers "is this participant the host" | `sessions.py:167-216`, `service.py:409-431` |

Not Party Core, but called by Party Home today from the LAN Games runtime at the origin root
(`avrana-party.nginx:231-234`): `/chat/ws` (`web/party/lib/party-chat.js:15`), `/api/games`
(`web/party/app.js:383`), `/api/avatar` (`web/party/lib/profile.js:91-102`), each game's
`health` path (`web/party/app.js:55-68`) and `/games/<slug>/onboarding.json`
(`web/party/app.js:267-273`). The catalog is a static file, `/party/catalog.json`
(`web/party/lib/catalog-load.js:12`), not an API.

There is no route for chat, notifications, suggestions, votes, favorites, history, results or
preferences (`service.py:8-25` is the whole list).

## 2. The party view a phone receives

Built by `PartyCore.view` (Core `:732-772`); the service adds `mode` (`service.py:343-346`).
"Public" means every caller gets the same value, including a phone that has not joined.

| Field | Meaning | Public | Source |
|---|---|---|---|
| `party` | party id; changes when a new party starts | yes | Core `:760` |
| `version` | integer, moves on every committed change; the long-poll cursor and `if_version` | yes | Core `:760`, `:197-200` |
| `state` | session state (`setup`, `launching`, `active`, `ending`) or `lobby` | yes | Core `:761` |
| `members[]` | everyone who has not left: `id`, `name`, `avatar` (bundled id or null), `mode` (`full` or `limited`), `presence` (`here`, `away`, `playing`), `host` | yes | Core `:739-741` |
| `host` | member id of the host, or null when vacant | yes | Core `:762` |
| `me` | `{id, name, host, mode}` or null; no avatar here, read it from `members` | per caller | Core `:763-765` |
| `session` | the current or most recent session, or null: `id`, `game`, `state`, `outcome`, `detail`, `players` (count of player roles) | yes | Core `:746-748`, `:178` |
| `session.my_role` | the caller's role in that session, or null | per caller | Core `:749` |
| `session.setup` | only while `state` is `setup`: `min`, `max`, `choices` (member id to `player` or `spectator`), `players`, `spectators`, `waiting` (member ids), `blocker` (sentence or null) | yes | Core `:750-758`, `:427-443` |
| `session.setup.mine` | the caller's own choice | per caller | Core `:759` |
| `nav` | `{seq, to, game, session, from}`: the committed move | yes | Core `:767`, `:672-677` |
| `location` | `{at, game, session}` with `at` one of `home`, `setup`, `game`, `results` | yes | Core `:655-669`, `:768` |
| `switching_to` | game id a host switch is moving to, or null | yes | Core `:769` |
| `games` | sorted ids of the games Core can start | yes | Core `:772` |
| `mode` | how this connection reached the party: `full` or `limited` | per connection | `service.py:343-346` |

Never in the view: device ids, other members' participant ids, tickets (Core `:733`); the
accepted result record (`docs/adr/0015-game-result-envelope.md:125-127`); any timestamp; any
list of earlier sessions (Core keeps one, `:178`). During an active round the view does not say
which members play and which watch: `presence` is `playing` for both (Core `:223-226`), only the
caller's `my_role` and the count `players` are sent; `choices` exists only in `setup`.

## 3. Game metadata available per game

One catalog entry is built from the Game Contract plus the appliance grant
(`avrana/contracts/catalog.py:99-126`). Line numbers in the example columns are
`web/party/catalog.json`.

| Field | Meaning and allowed values | BLUFF | EXPO | Gauntlet II (arcade) |
|---|---|---|---|---|
| `id`, `name` | identity and title | `bluff`, BLUFF (`:175-176`) | `expo`, EXPO (`:234-235`) | `arcade-gauntlet2`, Gauntlet II (`:292-293`) |
| `kind` | `native`, `emulated`, `other` (`avrana/contracts/game.py:25`) | native (`:177`) | native (`:236`) | emulated (`:294`) |
| `players` | `{min, max}` | 2 to 6 (`:178-181`) | 2 to 5 (`:237-240`) | 1 to 2 (`:295-298`) |
| `screen` | `no_tv_needed`, `tv_optional`, `tv_required` (`game.py:26`) | no_tv_needed (`:182`) | no_tv_needed (`:241`) | tv_optional (`:299`) |
| `input` | `model` (`browser_native`, `controller_slots`, `hotseat`), `slots`, `directions`, `buttons` (`game.py:27-28`) | browser_native (`:183-185`) | browser_native (`:242-244`) | controller_slots, 2 slots, dpad, 4 buttons (`:300-310`) |
| `late_join` | `spectator_only`, `next_round`, `supported` (`game.py:29`) | spectator_only (`:186`) | spectator_only (`:245`) | supported (`:311`) |
| `spectators` | `none`, `watch` (`game.py:30`) | watch (`:187`) | watch (`:246`) | none (`:312`) |
| `private_player_ui` | private hands on the phone | true (`:188`) | true (`:247`) | false (`:313`) |
| `fallback` | `explain`, `spectate` (`game.py:45`) | spectate (`:189`) | spectate (`:248`) | explain (`:314`) |
| `installed`, `entry`, `health` | appliance grant | true, `/games/bluff/`, none (`:190-192`) | true, `/games/expo/`, none (`:249-251`) | true, `/arcade/`, `/arcade/stats` (`:315-317`) |
| `playableHere`, `presentations[]` | per presentation: `method`, `roles`, `available`, `runtimeMissing`, required and optional device capabilities | one, phone_table (`:193-217`) | one, phone_table (`:252-276`) | one, phone_stream (`:318-343`) |
| `provider`, `status` | who runs it; `current`, `experimental`, `not_installed` | lan-games, current (`:218-220`) | lan-games, current (`:277-279`) | arcade, current (`:344-345`) |
| `summary` | one line, at most 140 characters (`game.py:152-153`) | "Claim anything. Get caught, lose a card." (`:230`) | "One crew. Every card matters." (`:289`) | "Two heroes, one dungeon. Every phone is a controller and a screen." (`:346`) |
| `artwork` | prepared SVG path from `contracts/artwork.json:4-8` | `art/lan-bluff.svg` (`:231`) | none | `art/kenney-sword.svg` (`:347`) |
| `description` | long text, donor rows only | present (`:224`) | present (`:283`) | none |
| `accent` | hex colour, donor rows only | `#e879f9` (`:227`) | `#65e5dd` (`:286`) | none |
| `icon` | emoji, donor rows only | present (`:222`) | present (`:281`) | none |
| `category` | free text up to 24 characters, donor rows only (`avrana/contracts/lan_catalog.py:46`) | "party" (`:223`) | "cards" (`:282`) | none |
| `playersLabel`, `solo` | donor lobby text; describes the standalone lobby, not a Party round (`catalog.py:66-70`) | "1–6 (+ test bots)", true (`:225-228`) | "2–5 players", false (`:284-287`) | none |
| `legacySlug`, `launchTarget`, `integration` | launch plumbing | (`:219-229`) | (`:278-288`) | none |

Notes that matter to design:

- For BLUFF and EXPO the catalog `name` and `summary` come from the Games catalog snapshot, not
  the contract file, and so does the whole `net.avrana.catalog` block
  (`catalog.py:66-71`). The snapshot's field set is closed (`lan_catalog.py:13`, `:33`).
- In the contract but **not copied to the catalog**: `accessibility` (`timing_pressure`,
  `audio_required`, `color_independent`, `reduced_motion_respected`, `text_scalable`;
  `contracts/games/bluff.json:38-42`, `contracts/games/expo.json:32-38`), `package`
  (`bluff.json:32-37`), `runtime`, and `extensions["net.avrana.party"].pregame`
  (`bluff.json:43-45`, `expo.json:39-41`; Gauntlet II has none). A phone cannot tell from the
  catalog whether a game has a Ready or Watch step; it learns it when `session.state` is `setup`.
- Rules text is not catalog data. A game may serve `onboarding.json` beside its entry
  (`avrana.onboarding/v0`: `title`, `premise`, `ack`, `facts`, `rules`;
  `games/bluff/web/onboarding.json:1-9`). BLUFF has one. **EXPO has none at a448972**
  (`games/expo/web/` holds no such file), so its setup scene falls back to the catalog `summary`
  (`web/party/app.js:322`, `docs/design/GAME-UX-CONTRACT.md:434-436`). Arcade titles have none.
- Catalog-wide: `labels` gives a plain sentence per device capability
  (`catalog.py:141-142`); `collections` is empty today (`catalog.py:130-132`).

### The brief's facets and filters against these fields

| Brief facet or filter | Backing field today | Verdict |
|---|---|---|
| Player count | `players.min`, `players.max` | exists; already a filter (`web/party/lib/catalog-view.js:20-27`) |
| Phone-only, TV-only, TV-enhanced; display requirement | `screen` | exists: `no_tv_needed`, `tv_required`, `tv_optional` |
| Arcade / Console | `kind` (`emulated`), `provider` (`arcade`, `retroarch-ps1`) | derivable |
| Controls and capabilities | `input`, `presentations[]`, `labels` | exists |
| Party | only the donor `category` value "party" on BLUFF | **no backing field** (free text on 2 of 5 games, no vocabulary) |
| Co-op, Competitive; social format | none in the catalog. `mode` (`competitive`, `cooperative`) exists only inside a finished round's result (`avrana/party/result.py:44`) | **no backing field** |
| Team-based, Free-for-all | none | **no backing field** |
| Classics | none | **no backing field** |
| Quick Games; duration range; approximate play time | none anywhere | **no backing field** |
| Gameplay genre or type | donor `category` only ("party", "cards") | **no backing field** with a vocabulary |
| Rules, Quick Start | not catalog data; `onboarding.json` per game (BLUFF only). A Quick Start block is a proposed, unbuilt `avrana.onboarding/v1` draft (`docs/design/GAME-UX-CONTRACT.md:438-492`) | partial |

## 4. Per-device client storage today

All on the Party origin unless noted. No `sessionStorage` and no IndexedDB data is used
(`web/party/lib/capabilities.js:107` only probes).

| Key or store | Holds | Source |
|---|---|---|
| `wc-name` (localStorage) | display name, up to 24 characters; Core receives the first 16 | `web/party/lib/profile.js:53`, `:75`; `web/party/app.js:201-205` |
| `wc-avatar` | bundled avatar id (`gaze-NN`) | `profile.js:53`, `:76` |
| `wc-pfp` | path of an uploaded photo; shown in chat only, Core accepts bundled ids only | `profile.js:54`, `:90-106`; Core `:114-116` |
| `wc-token` | the legacy chat and avatar-upload identity, generated in the browser | `profile.js:57-67`; `web/party/lib/party-chat.js:48` |
| `lg-favorites` | JSON list of favorited game keys (`avrana:<id>`) | `profile.js:79-84` |
| `lg-recent` | JSON list, newest first, at most 8 | `profile.js:85-87` |
| `lg-play-total` | count of games opened | `profile.js:55`, `:88` |
| the game's `ack.key` (for BLUFF `bluff-briefed`) | the acknowledged rules version | `web/party/app.js:278-286`; `games/bluff/web/onboarding.json:6` |
| `avrana.probe` | written and removed by the storage probe | `web/party/lib/capabilities.js:96-101` |
| cookie `__Host-avrana_device` (legacy `avrana_device`) | Full Mode device token; `HttpOnly`, never readable by the page | `avrana/party/identity.py:35-37`, `:175-181` |
| cookie `avrana_limited` | Limited Mode credential, 12 hours, memory-only on the server | `identity.py:39`, `:184-187` |
| Cache Storage `avrana-party-shell-<build>` | the offline copy of the shell; secure context only | `web/party/sw.js:18`; `web/party/lib/shell.js:9`, `:43` |
| game pages (same origin today): `wc-muted`, `lg-haptics`, `lg-motion` | sound, haptics and reduced effects, read by game pages only | `web/hubnet.js:78-86` |
| game pages: EXPO effects choice, BLUFF briefing key | per-game presentation choices | `games/expo/web/client.js:77`; `games/bluff/web/briefing.js:76-80` |

What is **not** stored: the Library tab (All, Favorites, Recently opened) lives in page memory
(`web/party/app.js:34`, `:565-572`); search text and the group-size filter are form values
(`web/party/app.js:392-394`). There is no stored view mode, sort or filter.

Two limits follow from origins. `lg-recent` is written only when a phone opens a non-Party tile
itself (`web/party/app.js:125-142`); a host start for everyone does not record it
(`web/party/app.js:176-198`). And storage is per origin: the Limited Mode origin
(`http://10.42.0.1`, `docs/design/LIMITED-MODE.md:71-72`) and the future game origin
(`docs/design/BROWSER-ORIGINS.md:49-51`) each start empty, so profile, favorites and recents do
not follow a phone there.

## 5. Chat, presence, notifications

| Capability | Server side today | Proposed only | In Limited Mode |
|---|---|---|---|
| Presence | Party Core: `here`, `away`, `playing`; 45 s liveness window; host grace 30 s; delivered in every view by long poll (Core `:60-61`, `:233-239`, `:288-290`; `service.py:99-115`) | nothing further | works: the same Core serves both listeners (`service.py:602-611`). A game page does not follow or heartbeat there yet (`docs/adr/0012-limited-mode-party-survives-https-loss.md:176-178`) |
| Member mode | `members[].mode`, set at join and kept (Core `:119-130`, `:739`) | host-approved reclaim after a mode switch (ADR 0012 D3) | each Limited phone is a new member |
| Chat | **Not in Party Core.** Party Home talks to the LAN Games ChatHub at `/chat/ws`: one global room, last 60 messages in memory, 400 characters, 6 messages per 4 s (`core/chat.py:23-25`); the name is whatever the client sends and any client can clear the room (`core/chat.py:80-85`, `:121-125`). Client: `web/party/lib/party-chat.js:13-90`; UI is one disclosure on Party Home only (`web/party/index.html:87-95`) | all of `docs/design/COMMUNICATION.md` (status PROPOSED, `:3`): Party-owned channels, server-stamped names, HUD and feed, game-declared policy | not designed. The Limited table does not mention chat (`docs/design/LIMITED-MODE.md:153-163`). The port-80 server still proxies the origin root to the games runtime with WebSocket upgrade (`avrana-party.nginx:76-90`), so it may connect; untested, and with a fresh `wc-token` |
| Chat identity | `wc-token` from the browser, hashed to a chat uid; unrelated to the Party member (`core/chat.py:30-37`) | sender stamped from Party presence (`COMMUNICATION.md:42-45`) | as above |
| Chat inside games | none: no Party chat on a game page; the integration bar is hidden in a Party (`web/avrana-integration.js:149`) | HUD over the game; mechanism across origins "not chosen" (`COMMUNICATION.md:59-67`) | none |
| Notifications | none. No event list, no unread count, no push. A client can compare two views (`web/party/lib/party-client.js:31-38` passes `previous`) | system lines in the chat feed (`COMMUNICATION.md:94-97`) | view diffs work the same |
| Sound and haptic cues | none in the shell; capabilities are probed only (`web/party/lib/capabilities.js:86`, `:115`) | none written | Web Audio and vibration need no secure context |
| Suggestions and votes | none; deliberately outside Core v0 (Core `:50-51`) | queue and advisory votes, "the host decides" (`docs/design/PARTY-PLATFORM.md:429-436`, direction per `:8-9`) | none |

Two cautions. `COMMUNICATION.md:27-30` describes "system messages ... over Server-Sent Events"
as existing; that was the experiment party service. Core at 578534f has no event list and no
event stream, only the versioned long poll. And the chat backend lives in the LAN Games runtime,
which is retiring (`AGENTS.md:96-99`); chat is outside the declared Party to Games contract
(`docs/design/PARTY-GAMES-CONTRACT.md:79-84`).

## 6. Results and history

| Question | Today | Source |
|---|---|---|
| Is the result envelope decided | yes: `avrana.game-result/v1`, accepted 2026-10-03, carried inside the signed `ended` message | `docs/adr/0015-game-result-envelope.md:3`, `:28-37`; `contracts/party-games.v0.json:14-22` |
| What Core keeps after a round | `session.result`: `schema`, `session`, `game {id, build, content}`, `outcome`, `mode`, `standings[] {participant, standing, rank, member}`, optional `data_schema` and `data`; or `result_refused` with a reason | Core `:154-155`, `:605-628` |
| For how long | in memory, on the one session object, until the next session replaces it or Core restarts. Nothing is written to disk | Core `:178`, `:405-408`, `:610-611`; ADR 0015 `:125-127` |
| Do phones see it | no: "the party view does not include the record" | ADR 0015 `:125-127`; Core `:746-749` |
| Which games report one | BLUFF only. EXPO defines no `game_result()` | `provider/avrana-contract.json:19`; `games/bluff/game.py:543-564`; ADR 0015 `:156-159` |
| When is a result refused | not `completed`, or the envelope fails its checks; the session still ends | Core `:612-620`; `avrana/party/result.py:100-167` |
| History, stats, retention, what phones see | undecided, owned by AVR-71 | ADR 0015 `:8-9`, `:165-171` |
| What the game shows | its own results screen, held until the host moves on | `docs/adr/0011-party-console-model.md:31-38`; Core `:655-669` |

**Can "Recently Played" be derived?** Party-wide: no. Core holds one session (current or most
recent), no list and no wall-clock time, and forgets everything on restart (Core `:50`, `:178`).
The view exposes only that one session's `game` and `outcome`. Per device: nearly. `lg-recent`
exists (section 4) but misses Party rounds. A phone sees every move in `location`
(Core `:768`), so recording the game when `location.at` becomes `game` is a frontend-only
change that yields a per-phone list. That list is "games this phone was taken to", not a
record of the Party.

## 7. Limited Mode and degraded state

| Signal the client has | Says | Source |
|---|---|---|
| `view.mode`, `me.mode`, `members[].mode` | whether this connection, and each member, is in Full or Limited Mode; from the listener, never a header | `service.py:343-346`; Core `:739`, `:763-764` |
| capability report | per device: `secure_context`, `wake_lock`, `service_worker`, WebRTC and so on, plus OS preferences (`reducedMotion`, `contrastMore`, `colorScheme`) | `web/party/lib/capabilities.js:17-22`, `:148-152` |
| seat evaluation | per game on this phone: `ready`, `limited`, `watch`, `unavailable`, with one plain sentence | `web/party/lib/evaluate.js:33-64`, `:70-86` |
| `/party/api/status` | `summary {state, reasons, notes}` (`ok`, `degraded`, `unknown`), `certificate {status, days_left}`, `services`, `games_provider`, `arcade`, `party_core`. Reasons are operator strings ("certificate expired", "arcade unreachable") | `avrana/ops/status.py:188-264`; `docs/design/STATUS-ENDPOINT.md:22-34` |
| `api/origin.json`, per-game `health`, `/api/games` | reachability; live "N of M playing" and "not running" per title, polled every 15 s | `web/party/app.js:32`, `:46-68`, `:378-389` |
| `session.outcome` `launch_failed` with `session.detail` | why a start failed, as a sentence | Core `:156`, `:274-282`, `:496-502` |

| Who sees what today | Audience | Source |
|---|---|---|
| Limited Mode banner: not private, what is missing on this phone, how it is restored | every Limited phone, about itself; not dismissible | `web/party/app.js:230-241`; `web/party/lib/limited.js:24-38`; `web/party/index.html:63-67` |
| "Limited" beside a member | everyone | `web/party/app.js:225-226`, `:252-253` |
| "Connected in Limited Mode" status line | that phone | `web/party/app.js:468-470` |
| Play disabled with a reason in a round's setup | that phone, in Limited Mode only | `web/party/app.js:336-341`; `limited.js:46-61` |
| Fit chip and sentence per game tile | each phone | `web/party/app.js:77-88`, `:122` |
| "This phone" disclosure | each phone | `web/party/app.js:413-431` |
| "X didn't start" with the reason | host only | `web/party/app.js:254-260` |
| status document | only the diagnostics page reads it; Party Home never does | `web/party/diag/diag.js:184-187`; `STATUS-ENDPOINT.md:61-63` |

There is no host-only notice mechanism and no dismissal state anywhere. The status endpoint
needs no identity, so "host-only" would be a presentation choice from `me.host`, not an access
rule. Limited Mode is in source and not deployed
(`docs/adr/0012-limited-mode-party-survives-https-loss.md:137-147`).

## 8. EXPO view

The socket state wraps the game view: `phase`, `deadline`, `settings`, `min_players`,
`players`, `you`, `party_round`, `party_host`, `game` (`core/session.py:469-492`), plus
`missions` and `recovery_error` (`games/expo/game.py:394-400`). The game view is
`Engine.view(seat)` (`games/expo/engine.py:1325-1384`) with adapter additions
(`games/expo/game.py:373-392`). The same split is documented in
`games/expo/docs/GAME_STATE.md:143-166`.

| Scope | Fields | Source |
|---|---|---|
| Public, every viewer | `stage`, `attempt`, `revision`, `mission`, `seats`, `captain`, `leader`, `turn`, `selector`, `controller`, `trick`, `trick_leading`, `last_trick`, `trick_number`, `planned_tricks`, `hand_counts`, `trick_counts`, `tasks[]`, `communication`, `exposures`, `shared_sonar`, `sonar_spent`, `tonoja`, `distress`, `attempts`, `result`, `expiry`, `away`, `log`, `proposal`, `resolving`, `cause`, `events`, `event_seq` | `games/expo/engine.py:1353-1371` |
| Public, added by the adapter | `expiry` as wall-clock, `lifecycle` (`host` or `crew`), `begin_at`, `lifecycle_reasons {begin, retry, next}`, `lifecycle_transitional`, `resolving.until` | `games/expo/game.py:380-391` |
| Private to the seat (`me`; null for spectators, TVs, watchers) | `seat`, `hand`, `legal_cards`, `play_reason`, `card_reasons`, `task_reasons`, `pass_task_reason`, `volunteer_reasons`, `offer_reason`, `offer_owner_reasons`, `predict_reasons`, `communication_options`, `may_pass_task`, `may_decline_volunteer`, `pass_locked` | `games/expo/engine.py:1372-1384` |
| Private elsewhere in the view | own secret `prediction` on a task until the result; own declaration in the currents mode; private fields of own events | `games/expo/engine.py:1331-1333`, `:1344-1346`, `:1302-1305` |
| Party spectators | the public view only; no hand ever | `games/expo/game.py:394-397` |

| The brief asks | In the server view | Field | Source |
|---|---|---|---|
| Current winner of an unfinished trick, authoritative and public | **yes** | `trick_leading`: the seat whose card is winning, or null (no card yet, trick resolving, attempt has a result, not in play). It is the engine's own `winner()` on the cards so far | `games/expo/engine.py:664-675`, `:1358`; `games/expo/docs/GAME_STATE.md:332-346` |
| Winner of the trick just resolved | yes | `last_trick {index, leader, winner, plays}`; `resolving {trick, until}` during the hold | `games/expo/engine.py:641`, `:659`, `:1358`; `games/expo/game.py:389-391` |
| Per-task status | yes | `tasks[] {id, text, difficulty, owner, status, state, eligible_owners, prediction_required, prediction_committed}`; `state` is `PENDING`, `ACTIVE`, `COMPLETED`, `FAILED` or `IMPOSSIBLE` | `games/expo/engine.py:1309-1323`, `:1335-1347` |
| Trick history | **no, by rule** | only `last_trick`, per-seat `trick_counts` and `trick_number` of `planned_tricks`. Earlier tricks are never sent: only the most recently won trick may be looked at again | `games/expo/engine.py:1289-1294`, `:1358-1360`; `games/expo/docs/GAME_STATE.md:153` |
| Result: success or failure | yes | `result {status, reason}`; `status` is `success` or `failed`, `reason` is the server's sentence | `games/expo/engine.py:512-516` |
| Result: cause, relevant task, triggering public action | yes, for a failure | `cause {kind, objective, failure, state, affected_seat, trigger_seat, trigger_controller, trigger_card, action, cards, trick, mission}`. `objective` is the task id or mission objective; `action` is the committed command the failure followed; trigger fields are null where nobody can honestly be named (a deadline, a condition unmet at the end) | `games/expo/engine.py:149-179`, `:519-522`; `games/expo/docs/GAME_STATE.md:458-474` |
| Result of a success | yes, without a cause | `cause` is null; the evidence is `result.reason`, each task's `state`, and the `MISSION_SUCCESS` event | `games/expo/engine.py:522-525` |

The presentation doc already binds the client to these words: who is winning is "the view's
`trick_leading`, the server's word" (`games/expo/docs/PRESENTATION.md:99`), and a failed
attempt "shows the server's `cause` ... and adds nothing" (`games/expo/docs/PRESENTATION.md:237`).
EXPO reports no result to the Party (section 6), which matters only if a Party surface, not the
game, is to show an EXPO outcome.

## 9. Need against have

Verdicts: **exists**; **derivable** (client-side from existing state); **device** (per-device
storage only, no backend); **new** (needs backend state or a contract field); **collision**
(needs an accepted decision amended; quoted in the next table).

| UX need from the brief | Verdict | Where, how, or the smallest change |
|---|---|---|
| Bottom navigation Home, Party, Library, System | derivable, with a collision during setup and rounds | All four are Party-origin surfaces while `location.at` is `home`. See collisions 1 and 2 for setup, rounds and results |
| Social layer: presence | exists | `members[]` with `presence`, `host`, `mode`, `avatar` (Core `:739-741`) |
| Social layer: chat on Party surfaces | exists, on a retiring backend | ChatHub at `/chat/ws` (section 5). Any chat that carries the Party member's identity, survives LAN Games retirement or reaches Limited Mode by design is **new**: the v1 of `docs/design/COMMUNICATION.md:111-116` |
| Social layer: notifications | derivable for joins, leaves, host changes, starts and ends (diff two views, `web/party/lib/party-client.js:31-38`); **new** for anything a view does not hold (chat unread across reloads, attention requests) | no server event list exists |
| Game suggestions and votes | new | Core state and routes; none exist (Core `:50-51`). Must stay advisory: see collision 5 |
| Compact Party HUD outside the Party page, inside the shell | exists | the same view on every Party-origin page |
| Party HUD over games | new plus collision | see collision 3 |
| Who plays and who watches, shown during a round | new, small | `choices` exists only in `setup`; add the roles (member id to role) to `session` while active. The roster's roles are already public at setup (Core `:754-755`) |
| Profile (name and avatar) that recedes after onboarding | device plus exists | localStorage `wc-name`, `wc-avatar`; Core `join` and `rename`. Name limits differ: 24 on the phone, 16 at Core (`web/party/app.js:201-205`). Uploaded photos never reach the Party roster (Core `:114-116`) |
| Host badge | exists | `members[].host`, `me.host`. Today's crown icon is presentation only (`web/party/app.js:224`, `:330`) |
| Ready / Watch per round | exists for pregame titles | `session.setup.choices`, `mine`, `waiting`, `blocker`; `POST session/choice`. Core has two answers, `player` and `spectator`; there is no separate "ready" state (Core `:72`, `:436-438`). Not available for titles without `pregame` (collision 4) |
| Library view modes (medium, large, compact, list) persisted per device | device | a new localStorage key; nothing is stored today (section 4) |
| Sort | device | sortable today by `name`, `players`, `installed`, per-device recency. No popularity or play count exists |
| Section: Recently Played | derivable per device (section 6); **new** if it must be the Party's shared list | per device: record on `location.at` becoming `game`. Party-wide: an in-memory list in Core, and durable history waits for AVR-71 (ADR 0015 `:165-171`) |
| Section: Favorites; non-hosts may favorite | device, exists | `lg-favorites` (`web/party/lib/profile.js:79-84`); no authority involved |
| Section: Great for Your Party | derivable | count members with `presence` `here` or `playing` against `players.min` and `players.max`; add `screen` and seat evaluation |
| Section: All Games | exists | `catalog.games` (`web/party/lib/catalog-view.js:17-19`) |
| Facets Phone-only, TV-only, TV-enhanced; filter by display requirement | exists | `screen` |
| Facet Arcade / Console | derivable | `kind`, `provider` |
| Filter by player count | exists | `players` |
| Facets Party, Co-op, Competitive, Team-based, Free-for-all, Classics, Quick Games; filters by duration, genre or type, social format | new | no field (section 3). Smallest change: optional library metadata per Game Contract inside `extensions`, which the schema already permits without a version bump ("Extensions go in `extensions` under a reverse-DNS key", `contracts/README.md:28`; `avrana/contracts/game.py:313-319`), copied into the catalog by `catalog.py`. It cannot ride in `net.avrana.catalog` for BLUFF and EXPO, because that block is replaced by the Games snapshot (`catalog.py:71`) whose field set is closed (`lan_catalog.py:13`, `:33`). The catalog is generated and CI-checked (`AGENTS.md:68-71`) |
| Incompatible games stay visible | exists | the catalog never filters by Party size; today's filter is the user's own (`catalog-view.js:20-27`) |
| Compatibility explanation at launch | derivable | Party size from `members`, range from `players`. What Core enforces differs by title: a pregame title refuses Start with a sentence (`player_count`, Core `:439-442`); a title without pregame is never refused, and members beyond the maximum become spectators silently (Core `:415-418`) |
| Per-phone Game Detail: artwork, title, short description, player range, display requirement | exists | `artwork` (3 of 5 titles; EXPO has none), `name`, `summary`, `players`, `screen` |
| Game Detail: approximate duration | new | same metadata change as the facets |
| Game Detail: rules | exists for BLUFF; content missing elsewhere | `onboarding.json` v0, fetched as a static file with no session needed (`web/party/app.js:267-273`). EXPO needs the file written (Games content, no contract change). After the game-origin cutover the fetch becomes cross-origin and needs a designed path |
| Game Detail: Quick Start | new | the `briefing` block of the proposed, unbuilt `avrana.onboarding/v1` (`docs/design/GAME-UX-CONTRACT.md:438-492`) |
| Party-wide briefing distinct from Game Detail (Ready / Watch, Host Start) | exists | `location.at` `setup` plus `session.setup`; `launch`, `choice`, `start`. Game Detail is then a page at `home` whose host action is the existing `session/launch`. A non-host cannot answer Ready before the host opens the briefing (`no_game`, Core `:452-454`), which is the distinction the brief wants |
| Host-only, dismissible degraded and Limited notices that state player impact | derivable plus device plus collision | signals exist (section 7); host-only from `me.host`; dismissal in localStorage; player-impact wording is a client mapping of `summary.reasons` and `certificate.status`, since no impact field exists. Limited Mode itself: collision 6 |
| System / Settings: diagnostics | exists | `/party/api/status`, `/party/diag/`, the capability report |
| System / Settings: per-device motion, sound, haptics, contrast | device, with a collision for game pages | OS preferences are already read (`capabilities.js:148-152`); stored choices are new localStorage keys. Reaching game pages: collision 7 |
| EXPO: current winner of an unfinished trick as authoritative public state | exists | `trick_leading` (section 8) |
| EXPO: result states success or failure, cause, relevant task, triggering public action | exists | `result`, `cause`, `tasks[].state`, `events` (section 8). Earlier tricks cannot be replayed in a result, by rule |

### Collisions with accepted decisions

| # | The brief's flow | Accepted decision it meets | What follows |
|---|---|---|---|
| 1 | Bottom navigation, Library and chat reachable "from briefings" (brief sections 7 and 11) | [ADR 0011](../../../adr/0011-party-console-model.md) decision 4: "The setup is the Party's own full-screen scene on Party Home". The game UX contract adds that in the briefing "the library, chat row and "This phone" MUST NOT be visible in it" (`docs/design/GAME-UX-CONTRACT.md:107-112`, labelled Implemented) | A persistent tab bar or chat drawer on the briefing needs that rule reworded and decision 4 read as "full-screen content", or the bar hidden in `setup`. Owner decision |
| 2 | Home, Library, Game Detail and System browsable at any time; Home offering "continue/resume" (brief sections 8 and 17) | ADR 0011 decision 3: "Every member page is where the party is — always." and "Party Home cannot be browsed and no other game can be opened during a round"; also "no offers, no banners, no "Rejoin", no memory of what the tab did" (`docs/adr/0011-party-console-model.md:43-50`) | Free browsing holds only while `location.at` is `home`. During `game` and `results` every phone is on the game page. A "Continue" button is an offer; the phone is moved instead. Settings mid-round would need the same amendment as collision 3 |
| 3 | Party presence and chat as an overlay during first-party and third-party games (brief sections 10.1 and 11) | ADR 0011 decision 5: "The game owns the viewport during a round. In a Party, the games' integration bar (and so Back to Party) is hidden for everyone; the page shows no Party prose." [ADR 0013](../../../adr/0013-party-and-game-browser-origins.md) decision 2: a game page "cannot read Party state beyond what the Party deliberately publishes to games", and amendment D2: "A Party-owned, invisible bridge frame is the only seam between a game page and the Party, with the closed verb set `ticket`, `view`, `navigate`, `end`, `home`, `playAgain`" | The bridge `view` carries no roster and no chat (`web/party/lib/bridge.js:60-75`). An in-game HUD needs ADR 0011 decision 5 amended and either a visible Party-origin surface or new bridge messages, which is a change to `avrana.party-bridge/v1`, its vectors and the vendored shim in both repositories (`contracts/party-games.v0.json:23-31`). The brief leaves HUD geometry undecided (its section 29), so this is a later decision, not a design-phase blocker |
| 4 | "Library → Game Detail / Briefing → Ready / Watch → Host Start → Game" for every title (brief section 17) | ADR 0011 decision 1: "start a game (→ setup, or → game for a game without a pregame)". [ADR 0010](../../../adr/0010-party-pregame.md) decision 1 applies the Play or Watch step only to "A Party Core game configured with `pregame: true`" | BLUFF and EXPO have the step. Gauntlet II and the PS1 titles go straight to the game with everyone here as a player (Core `:415-418`). Giving them a briefing is a per-game contract flag plus runtime support, not a shell change |
| 5 | Non-hosts suggest and vote (brief sections 11 and 17) | ADR 0011 decision 1: "Only the Party Host moves it" and "A follower's own actions never change it." | No conflict if suggestions are advisory, as the platform direction already says ("the host decides", `docs/design/PARTY-PLATFORM.md:431`). A vote that starts a game by itself would need the decision amended |
| 6 | Degraded and Limited notices "normally" host-only and dismissible (brief section 13.1) | [ADR 0012](../../../adr/0012-limited-mode-party-survives-https-loss.md) decision 4: "Limited Mode is visible and understandable. The shell says plainly that the connection is not secure, which conveniences are missing, and how Full Mode is restored ... It never pretends to be Full Mode"; amendment D4: "Each member's mode is visible to the party." | A Limited phone's own "this connection is not private" notice cannot be host-only, and hiding it for good after one tap sits badly with "never pretends". It can be compact. Appliance health (certificate expiring, a service down) is free to be host-only |
| 7 | Per-device preferences applied everywhere, favorites and profile that follow the player | ADR 0013 decision 4: separate hostnames "so cookies, storage, service workers and `Origin` checks separate by construction"; decision 6: "Cross-origin identity recovery stays forbidden." ADR 0012 amendment D3: "A phone that changes mode joins again as a new device." | Preferences, favorites and recents stored on the Party origin are invisible to game pages after the origin cutover and to the Limited origin. Game pages keep their own keys today (`web/hubnet.js:78-86`). Passing preferences to games means a new field on the bridge `view` message (a bridge contract change). OS-level reduced motion and contrast need nothing |
| 8 | Favorites, recents and preferences treated as part of "profile" | `AGENTS.md:84-87`: "a browser-stored name/avatar is not a durable Profile"; Party owns "library ... and durable results/history" | No conflict while these stay per-device conveniences and are not presented as a saved account. Server-side favorites would be Profile work, which is not built |

Not collisions, but worth knowing before drawing: a host's tap on a tile launches at once today
(`web/party/app.js:181-183`), so "artwork does not launch" is a frontend change over the same
`session/launch`; the origin separation of ADR 0013 and Limited Mode of ADR 0012 are accepted and
in source but not deployed (`AGENTS.md:93-100`), so today's single origin is what phones run.
