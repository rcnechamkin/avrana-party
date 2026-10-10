# External-game porting checklist

- **Status:** Proposal (engineering handoff checklist). Not validated by any port; no port is authorized. Do not describe it as a working porting tool.
- **Date:** 2026-10-10
- **Sources:** Linear AVR-59 (owner note 2026-10-08), AVR-38, AVR-143, AVR-238, AVR-316; Checkers findings (Games `docs/findings/2026-10-07-checkers-native-findings.md`, abbreviated `F-games` below; Party `docs/findings/2026-10-08-checkers-party-integration.md`); `docs/runbooks/provision-game.md`.
- **Related:** `docs/research/DEVELOPER-FRICTION-AUDIT.md`, `docs/research/MISSING-PUBLIC-ABSTRACTIONS.md`, `docs/runbooks/add-a-game.md`

This is a **proposed engineering handoff checklist**, per AVR-59 ("a proposed engineering handoff guide may exist before the
SDK does; do not call it a working porting tool until proven"). It is not validated by a single port. No port is authorized
(AVR-59 owner note 2026-10-08: no production change, port or asset redistribution). It assumes Checkers' native path
(merged to Party `main` `defd4a2` and Games `main` `fb711d9`) and should be reconciled with the Linear document "Authorized-game porting handoff, engineering blueprint" attached to AVR-59 (not reviewed while preparing this note).
References: `F-games` = Games `docs/findings/2026-10-07-checkers-native-findings.md`; `P:` = Party main.

## 0. Gate before any work

- [ ] Written permission or a licence that allows adaptation, testing and any distribution. Permission to port or to run a private test is **not** permission to redistribute commercially (AVR-143, AVR-316): record separately what is granted for porting, for testing, and for open or commercial redistribution, including assets, dependencies and ROMs; DRM-free executable is not source or permission (AVR-59). Asset licences audited separately (AGPL and separately licensed art: AVR-59 OpenFront note).
- [ ] An owner-assigned Linear issue exists; no new game is a Party 1.0 blocker by being on a list.
- [ ] Work in the Games repo (or the game's own repo), **never** a per-title change in Party Core (AVR-38, AVR-238).
- [ ] The result must remain installable through the single appliance-side validate/install path, with or without any commercial storefront (AVR-143, AVR-316). Do not add a game-specific installer.

## 1. Classify

- [ ] Architecture: server-authoritative Node/Python backend + browser client (Colyseus Tanks, Checker-Bomberman type), peer-to-peer, single-page local game, native/emulated (out of scope: separate adapter, `kind: emulated`/PS1 profile).
- [ ] Who computes what: authoritative state on the appliance; presentation and local prediction on the phone (AVR-38). Note anything that needs WebGL/WebGPU/WASM/Workers/secure context: these are **capabilities** to declare in `presentations[].requires/optional.device`, not assumptions (`contracts/README.md:90-104`).
- [ ] Players: min/max, hotseat, bots, spectators, late join (`late_join`, `spectators` in the Game Contract). Late joiners hold tickets not on the launch roster (F11).
- [ ] Hidden information: list every datum a phone must not see; the server must never send it (F-"private projection").
- [ ] Phone constraints: touch input only, small viewport, battery/wake lock, no keyboard, reconnects on Wi-Fi blips; perf budget unknown on the Pi (AVR-138, 301).

## 2. Remove source platform assumptions

- [ ] Accounts, login, cookies, local/session storage keyed to a site identity, matchmaking, lobbies, rooms, chat, friends, ads/analytics, telemetry, CDN or Google font fetches: no internet at play time. Replace with Party-provided session: the launch roster supplies `{participant, name, role}`; a game never sees member or device ids.
- [ ] No third-party scripts/fonts/images at runtime (offline). Vendor with licence notices.
- [ ] No navigation away from the game and no direct Party API/cookies: only the Party bridge (`avrana-party-bridge.js`, verbs `ticket view navigate end home playAgain`; ADR 0013). Do not assume the page is the top-level document or set `frame-ancestors 'none'` without understanding it (F-D1 note).
- [ ] Replace the game's own "game over, play again, back to menu" with the Host's Play again / Party Home through the bridge; phones move only when Party moves them (UX 12.4).

## 3. Server side (native process)

- [ ] Runs as `python3 -m x` or other command from root-owned directory, no root, no state outside `$STATE_DIRECTORY`, no IP sockets, no DNS (`AF_UNIX` only), no writes beyond what the unit allows. Check any dependency that opens a socket at import or construct time (F1: `http.server` creates an `AF_INET` socket on construction).
- [ ] Serve on **fd 3** (`LISTEN_FDS=1`, `LISTEN_PID`); read key from `$AVRANA_PARTY_KEYS/<id>.key`; Party socket `$AVRANA_PARTY_SOCKET`; origin `$AVRANA_PARTY_ORIGIN` for the page. Never log key, ticket, token or request lines.
- [ ] Implement routes: signed `launch` and `end` (Party Core only, refuse anything carrying a proxy header, by presence), ticket redeem, state/poll, input. Reuse `core/party_protocol.py` and `core/party_result.py` byte for byte (pinned digests), as Checkers does; do not reimplement signing.
- [ ] Per-seat views; strict bounded JSON (size limit, no duplicate keys, string types, lone surrogates, non-ASCII token compared as UTF-8 bytes); every input validated by the server rules, not by the UI.
- [ ] Reconnect: same participant -> same seat/token; fresh ticket after reload; page survives link blips (poll with backoff) and a seat that no longer exists.
- [ ] End of game: build `avrana.game-result/v1` (standings per participant, `mode`, `data_schema`+`data`, <2048 bytes), call `GameSide.ended`, post signed `ended` to the Party socket, retry within the 30 s message life, treat a 4xx after a lost reply as ambiguous (F5). Accept `end` after own `ended` (F3).
- [ ] Idle: exit cleanly when no session and nothing pending; socket activation restarts you (F7).
- [ ] Set a build id that changes when behavior changes (F6).

## 4. Client side

- [ ] Phone-first layout, 44 px targets, no colour-only cues, announced prompts (`docs/design/ACCESSIBILITY.md`, per add-a-game.md).
- [ ] Obtain Party's origin from your own server's `api/party` route, embed the bridge frame, request a ticket, trade it for a seat. Show only actions currently legal for this seat.
- [ ] Results screen: "who won" cannot be fetched after `ended` on reload (F4); decide what the page shows and tell the owner.
- [ ] Rules/onboarding: write `onboarding.json` v0 (premise, `ack`, facts, sections); every number in the text pinned to the rules by a test (F13). A rules control in play is the game's own for now.
- [ ] Icon and cover: licensed or original (AVR-294); generic `icon.svg` is acceptable.

## 5. Contract and provisioning

- [ ] `contracts/games/<id>.json` (`avrana.game/v0`): strict, no unknown keys, `runtime.type: external`, `start: service`, requested `permissions` minimal, honest `presentations`, `private_player_ui`, `package` display fields. No grant, tier, URL, health check in the contract.
- [ ] Grant (owner): `entry` `/games/<id>/`, `permissions_granted` <= requested, `runtime{command, working_directory}` absolute, root-owned.
- [ ] `python3 -m avrana.contracts.catalog --check`; `provision_game <id> --dry-run` (owner/CI host only).
- [ ] Install on a **disposable** Linux host first; `boundary --phase 2` (owner action; no checker for Checkers yet).

## 6. Verification (record each, with evidence, not claims)

- [ ] Rules pinned by tests; each fails on a scratch mutation (AVR-312 pattern).
- [ ] Per-seat privacy test for every phase and for spectators/anonymous.
- [ ] Real-process test over Unix socket; address-family filter test; `ended` accepted by Party's own result check.
- [ ] Two real browser contexts through Party: seat, play, reload, Host End; offline (no upstream).
- [ ] Real iOS/Android phones over the Pi's Wi-Fi: owner acceptance (AVR-261 pattern). Performance at N phones: AVR-301/138.
- [ ] Record: game-specific changes vs reusable gaps vs unavoidable manual work; SDK gaps to `MISSING-PUBLIC-ABSTRACTIONS.md` and the findings note. Failed feasibility is recorded honestly.

## 7. Do not

Hard-code Party addresses, use a Party cookie, share a process with another game, add a per-title branch in Party Core, bundle unlicensed assets, claim "SDK-compatible" or ".avrgame ready" (neither exists), or run provisioning on the production Pi without the owner.
