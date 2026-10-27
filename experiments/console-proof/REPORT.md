# AVR-762 console architecture proof

Status: **experiment (2026-10-26, AVR-762). Not production, not an accepted architecture; owner decision required.**

Read against Party `origin/main` 8a7e578 and Games `origin/main` 08e0027. Nothing under `web/`, Party Core,
nginx or the Pi was changed. This proof gives evidence for the open decision in draft ADR 0018 §4 (PR #257).

## Answers

- **A. Console technology: keep vanilla JS.** At this size, Svelte 5 + TypeScript was not materially better.
  Both builds passed the same tests on the same Concept K CSS. Their speeds differed in both directions by
  tens of milliseconds. Svelte's real gains were stable DOM identity, strict types and a11y checks at
  build time, and one bundled file instead of 17 requests.
  - Stable DOM identity mattered. Vanilla needed a hand-written focus keeper. On WebKit, vanilla's 2 s poll
    rebuilt the suggestion list and **lost a tap** on the button being replaced. The fix was to re-render
    only on change. Svelte's keyed DOM never had the bug. The same `replaceChildren` pattern exists in
    production `layer-app.js`, though its re-rendered rows have no buttons.
  - svelte-check flagged 2 `aria-pressed` type mismatches: strings where booleans were expected, harmless
    at runtime. Its costs are a build step, 84 toolchain packages,
  framework churn (TypeScript 7 already does not work with svelte-check 4.7) and a rewrite of about 8,300
  lines of working console code. Most of the gain is cheaper to get in vanilla: `// @ts-check` with JSDoc,
  a small keyed-list helper, and an optional esbuild bundle step for request count. **Revisit** when the
  console grows past the current shell (for example, many more stateful forms).
- **B. Game view while browsing: restore from the server (R).** Draft ADR 0018 §4 criterion 1 already
  makes restore mandatory. In this proof it was the only variant with no trusted-UI or engine-dependency
  weakness.
  - **Keep** today's mounted Party layer (a Party frame over a top-level game page) only for glanceable
    surfaces that carry no trusted verbs, such as people and chat.
  - **Do not build** a Party page that embeds the game in an iframe.

## What was built (the fixture boundary)

`experiments/console-proof/` has its own `package.json`. It adds nothing to the root runtime.

| Part | What it is |
|---|---|
| `server/party.mjs` | Fixture Party origin `http://party.cp.test:8370`. HttpOnly host-only device cookie, one Party, one location, a `version`, seats, Party-signed **single-use** seat tickets (nonce, 60 s, game-scoped), and a **FIXTURE** suggestions list (nominate plus named approvals, sorted by count; labelled in the UI "Preview: fixture data, not a voting backend"). Browser-marked cross-origin POSTs are refused. CSP: `frame-ancestors 'none'` everywhere except the layer page (Party and game origins). |
| `server/game.mjs` | Fixture game origin `http://games.cp.test:8371`. It is authoritative for two games. `rt`: realtime, 20 Hz WebSocket ticks, canvas, rAF and a WebGL context. `turn`: two seats, a private hand per seat (`PRIVATE-…`), and a turn timer the server enforces. It verifies tickets, refuses replay and holds revocations. It counts any Party cookie that arrives (`cookieLeaks`). |
| `server/proxy.mjs` | Loopback proxy so WebKit, which has no `--host-resolver-rules`, sees the same two host names. |
| `web/game/mount.js` | Game-side layer mount. It imports the vendored production `web/party/bridge/layer-mount.js` for protocol checks and geometry. It adds `ticket-request`/`ticket` and `navigate {to:'console'}` with a fixed target. Frame sandbox: `allow-scripts allow-same-origin allow-forms` (no top navigation). |
| `web/party-x/vanilla/` | The console built the way `layer-app.js` is: static markup, one state object, and `h()` re-renders. It uses the real `ui.js`, `icons.js`, `profile-ui.js`, `party-mode.js` (`roster`), `library.js` (`seatsPhrase`) and `layer.js` (`parseFromPage`). New: `suggestions.js` and `console.js`. `embed.html` is the iframe-embedded variant, used for probes only. |
| `svelte/` | Svelte 5 (runes) + TypeScript (strict) + Vite. A static offline build in `svelte/dist/`, with no CDN. It has the same surfaces, the same DOM ids and classes, and imports the same pure modules. `/party/styles.css` stays the shared, unbundled Concept K stylesheet for both. |
| Surfaces (both) | A floating Party control opens the console. It has Home, Party, Library and Me tabs, typed Party notices ("your turn" with a server-deadline countdown, and the top suggestion), the suggestions preview, a selected-game line (`role=status`, `aria-live=polite`) and a prominent **Back to Game**. |
| Strategies | **M**: the console opens as the layer drawer over the still-running top-level game page, and Back to Game closes it. **R**: the layer button sends `navigate`, the game page unloads, and the top-level Party console page loads. Back to Game goes to the game URL that the Party's own location names; the game page gets a fresh ticket and the server resends its state. **M-embed** (probes only): a Party page frames the game. |
| Limited Mode stand-in | The game files and socket are served by the Party origin under `/g/`. The socket proxy strips `Cookie`, as nginx does. |

**Real-game boundary: UNVERIFIED.**

- Real Tanks on Games main (08e0027) is the Python hubnet game. Its rAF only draws; the timer and state are
  the server's (`games/tanks/web/tanks.js:520-542`).
- `colyseus-tanks` exists only on `feat/avr-68-colyseus-tanks`.
- Tanks is not in Games' `LAYER_GAMES` (`bluff`, `expo`), so neither strategy can be driven on it without
  Games changes.
- The fixtures copy the relevant properties: server authority, a private hand, a server timer, ticket seats,
  rAF/canvas/WebGL and WebSocket. They are not a real game client.

## Reproduce (Windows 11; Git Bash)

```
cd experiments/console-proof
npm ci
npm run build && npm run check            # Svelte build + svelte-check (0 errors, 0 warnings)
npx playwright test -c tests/playwright.config.ts                       # all 10 projects
npx playwright test -c tests/playwright.config.ts --project=chromium-svelte-R
node server/start.mjs &                   # then, for the numbers:
python -m avrana.web.devserver --port 8380 --party &   # (repo root) baseline real console
BASELINE_URL=http://127.0.0.1:8380/party/ node tests/measure.mjs 20     # -> results/measure.json
```

The servers use ports 8370–8372, not 8182–8188. Browsers: Playwright 1.63, Chromium 153.0.8010.12 and
WebKit 26.6 (Windows build). Phone: 390x844, DPR 3, `isMobile` and `hasTouch`. On Chromium these are
applied by CDP `Emulation.setDeviceMetricsOverride`, not by the window size. **WebKit on Windows only
approximates iOS Safari:** it is a different port with no accelerated compositing and different
throttling.

## Baseline (main 8a7e578, before anything here)

| Suite | Result |
|---|---|
| `node --test tests/offline/*.test.mjs` | 316/316 pass |
| `playwright.party.config.ts`: `party-layer`, `home-k0`, `guest-journey`, `follow-origin` (ports 8384/8385) | 39/39 pass (5.5 min) |
| Real `/party/` load (devserver, Chromium phone, service worker blocked) | 35 requests, 441 KB raw / 150 KB gzip (JS 260 / 90 KB), load event 256 ms cold / 459 ms warm (median of 10), JS heap 1.4 MB, 1,701 DOM nodes |

## Measurements (localhost; medians of 20 unless noted)

| | Chromium vanilla | Chromium Svelte | WebKit vanilla | WebKit Svelte |
|---|---|---|---|---|
| Console page: requests / raw / gzip (incl. shared styles.css + font) | 17 / 210 KB / 77 KB | 5 / 187 KB / 69 KB | same | same |
| …of which JS raw / gzip | 81 KB / 30 KB | 60 KB / 23 KB | | |
| Console ready, cold / warm (median of 10) | 133 / 74 ms | 122 / 50 ms | 136 / 127 ms | 119 / 84 ms |
| JS heap: console page / game + open layer | 1.43 / 2.98 MB | 1.58 / 3.50 MB | n/a (no CDP) | n/a |
| **M** open console (tap to drawer painted, p50/p90) | 18 / 19 ms | 18 / 20 ms | 60 / 74 ms | 59 / 63 ms |
| **M** tab switch (to Library painted) | 8 ms | 25 ms | 57 ms | 131 ms |
| **M** Back to Game (p50/p90) | 13 / 14 ms | 13 / 14 ms | 58 / 72 ms | 121 / 136 ms |
| **M** ticks missed while open / reconnects | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| **R** open console (tap to Party page ready, p50/p90) | 85 / 123 ms | 55 / 79 ms | 139 / 174 ms | 87 / 108 ms |
| **R** Back to Game (tap to seated and state received, p50/p90) | 165 / 191 ms | 130 / 180 ms | 421 / 450 ms | 342 / 372 ms |
| **R** total away / ticks not received while away / new sockets per return | 304 ms / 6 / 1 | 228 ms / 5 / 1 | 648 ms / 12 / 1 | 501 ms / 10 / 1 |

Notes:

- **R's Back to Game critical path includes booting the Party layer frame**, because it supplies the
  ticket. Svelte's single bundle is faster on that path than vanilla's 17 modules, and that is the whole R
  gap between the two. In production the ticket comes from the small `bridge.html`, not the console, so
  the ticket frame must stay tiny.
- Svelte's slower tab switch comes from `{#if}` remounting each panel. Vanilla toggles `hidden`.
- All numbers are loopback with no Wi-Fi and no Pi, and are relative only.

## Strategy probes (does the game keep executing?)

From `tests/probes.spec.ts` → `results/probes-*.json`.

| Condition | Chromium rAF/s · ticks/s · missed | WebKit (Windows) rAF/s · ticks/s · missed |
|---|---|---|
| Game top-level, layer closed | 61 · 19 · 0 | 20 · 16 · 0 |
| **M**: layer drawer open over the top-level game (occluded, not hidden) | 61 · 18 · 0 | 14 · 17 · 0 |
| M-embed: game iframe under the console (occluded) | 53 · 18 · 0 | 13 · 17 · 0 |
| M-embed: game iframe `display:none` | 0 · 16 · 0 | 61 · 17 · 0 |
| M-embed: game iframe `visibility:hidden` | 61 · 17 · 0 | 61 · 17 · 0 |
| M-embed: game iframe moved off-screen | 0 · 17 · 0 | 0 · 17 · 0 |
| Background tab / CDP freeze (headless) | could not be produced: `visibilityState` stayed `visible` and freeze did not stop rAF | not produced |

Other probe results:

- **WebGL.** `WEBGL_lose_context` loss and restore while the drawer was open: 1 lost, 1 restored, and
  the game re-initialized on both engines.
- **Lifecycle on R.** Leaving the game fires `pagehide (persisted=false)` while `visible`. History Back
  and Back to Game are both fresh loads (`pageshow persisted=false`). The page held an open WebSocket and
  Playwright's Chromium runs with bfcache disabled, so bfcache is **not measured**. Do not rely on it.
- **Cover detection.** IntersectionObserver v2 `trackVisibility` inside the layer frame reported
  `isVisible=false` even when nothing covered it (Chromium headless) and is `unsupported` on WebKit. It
  is not a usable clickjacking guard today.
- **What this shows.** Whether a hidden game frame keeps animating depends on the engine and on how it is
  hidden. Chromium stops rAF for `display:none`; WebKit does not. Both stop it off-screen. Sockets kept
  delivering in every case. A mounted frame is not proof that the game runs. Only server authority makes
  the outcome independent of the client.

## Tests

From `tests/console.spec.ts`, 11 tests × {vanilla, svelte} × {M, R}, plus 4 probes per engine.

**Final full run: 95 passed, 1 failed (96 tests, 27 min).**

- **Chromium: 48/48.**
- **WebKit: 47/48.** The failure was `webkit-vanilla-R` turn-timer: the game page never became ready within
  10 s, and the trace teardown also timed out. The same WebKit-only hang appeared once in each of two
  earlier runs, in different tests and in both M and R. It resembles the WebKit "navigation hung" flake in
  `docs/TESTING.md` (AVR-339). WebKit is not a phone; the owner gate below covers this.

Earlier runs found real problems, which were fixed:

- **Harness problems (run 1, 10 WebKit failures).** Leaked admin pages, a 45 s timeout that was too short
  for WebKit, and a Limited-Mode server crash (`CRLF` undefined in the socket proxy).
- **A genuine vanilla bug (run 2).** On WebKit, a 2 s poll re-rendered the suggestion list and lost a tap.
  It is now fixed: re-render only on change, and redraw only the countdown each second.
- **Two test races (runs 2–3).** The poll targets were captured once.

| Complexity | Vanilla | Svelte 5 + TS |
|---|---|---|
| Console source (lines / files) | 223 / 3 (`index.html`, `console.js`, `suggestions.js`) | 279 / 10 (+43 config: `vite.config.ts`, `tsconfig.json`) |
| Shared by both | `rules.js` + `console.css` (86 lines); the real `web/party` modules reused (1,052 lines) | same |
| Build step | none | `vite build` (about 0.6 s) |
| Dev dependencies added | 0 | 84 packages (svelte 19, vite 52, plugin 8, svelte-check 14, typescript 1); `node_modules` 94 MB including Playwright |
| `npm audit` | n/a | 0 vulnerabilities (2026-10-26) |
| Type check | none (could add `// @ts-check`) | `svelte-check` strict: 0 errors, 0 warnings, after fixing 2 flagged |

The tests:

1. Ordinary browse (`rt` and `turn`). Same participant and role. R uses a fresh ticket. The first ticket
   is refused as `replayed`. A forged other-seat ticket is refused as `bad`. The Party `version` and
   `location` are unchanged. The other phone did not move. `cookieLeaks = 0`.
2. Reload with the console open.
3. A socket the server drops reconnects by itself with the same seat.
4. Expired ticket → renewed through the Party → own seat only.
5. Seat revoked by the Host while browsing → Back to Game shows a spectator and no `PRIVATE-` frame.
6. Spectator secrecy: no `PRIVATE-` frame before or after browsing (with a player as positive control).
7. The turn times out on the server while browsing, the same as with a closed page. The countdown follows
   the server deadline.
8. Keyboard. M: focus moves to Close, Tab is trapped, Escape closes and returns focus to the button.
   R: Back to Game is focused first, and focus lands on the game's `#stage`.
9. Reduced motion gives `transition-duration: 0s`. At 200% text the indicator is visible with no
   sideways scroll.
10. Click interception. **M is coverable**: a transparent game element over the drawer took the tap on
    Back to Game. The test asserts that the weakness exists. **R cannot be covered**: the console is a
    top-level Party page with no game document.
11. Limited Mode stand-in (same origin under `/g/`).

## Draft ADR 0018 reconciliation §6 criteria

| # | Criterion | Status | Evidence / gap |
|---|---|---|---|
| 1 | Back to Game: same participant and role, fresh ticket, old refused; turn-based and realtime | **MET** (fixtures) | test 1 on `rt` and `turn`; replay → `replayed`. Real game clients: UNVERIFIED |
| 2 | Browsing moves no one, no location/nav/version change | **MET** (fixture Core) | test 1. The fixture has no Host `if_version` verb; a Host action during a browse is not exercised (**PARTIAL**). Real Core: #225's `_commit()` bumps the version and must not |
| 3 | AFK/timer outcome matches a locked phone; nothing relies on a hidden frame | **MET** | test 7 and the probes. The hidden-frame behaviour differs by engine, which is why R does not rely on it |
| 4 | Party-owned typed notices; no game free text | **PARTIAL** | notices are `{kind, game, …}` and worded by the console (`rules.js attentionText`). "Host started" and "round over" kinds are not built |
| 5 | Selected-game indicator: polite, non-blocking, 200% text, reduced motion | **PARTIAL** | on every console view (`#where`, polite status, test 9). Not on the game page itself, which is the game's viewport (ADR 0011 d5) |
| 6 | Negative tests: covering element, replay, secrecy, no version bump | **MET** (fixtures) | tests 10, 1, 5, 6, 1. The cover test shows M fails it; R passes |
| 7 | If mounted: game-frame sandbox, frame-ancestors, no cookie/storage, no top navigation | **PARTIAL** | M-embed: game CSP `frame-ancestors http://party.cp.test:8370`; `cookieLeaks=0`. The game iframe in `embed.html` has **no sandbox** (it needs scripts plus its own origin storage). Not recommended |
| 8 | Limited Mode keeps working | **PARTIAL** | test 11 (stand-in, not `limited.js` or a real plain-HTTP listener); "degrades visibly" not built |
| 9 | iOS Safari / Android Chrome metrics | **NOT RUN: OWNER HARDWARE GATE** | below |
| 10 | Vanilla vs Svelte on identical Concept K layouts, static offline bundles | **MET** | same `/party/styles.css`, ids and classes. Screenshots matched by eye. `svelte/dist` has no network references |
| 11 | Decision report with measurements, chosen model and rollback | **MET** | this file |

## Tradeoffs (the 10 criteria)

| Criterion | Vanilla | Svelte 5 + TS | M (layer over game) | R (restore) |
|---|---|---|---|---|
| Functional and security correctness | all tests pass | all tests pass | passes, but **coverable**; trusted verbs must stay off it (D3) | passes; not coverable; one code path with reload, sleep and Wi-Fi loss |
| Real mobile compatibility | no build; any browser that runs today's console | same output browsers | depends on frame + iOS behaviour (UNVERIFIED) | top-level pages only (best-known path); UNVERIFIED on phones |
| Preserving authority | n/a | n/a | the game keeps running locally, but rAF in hidden frames is engine-dependent | the server is the only truth by construction |
| Maintainability | explicit DOM work: focus keeping, static tabs, render-only-on-change (a lost-tap bug was found and fixed); no types today (could add checkJs) | keyed DOM, strict types, a11y lint; plus a toolchain, Svelte 5 idioms and version pinning | two documents sharing a viewport; geometry protocol | simplest; needs ticket + resend on every game (already required) |
| Pi CPU/RAM/Wi-Fi | static files | static files; the build runs on a dev machine | none per browse | one page plus one socket per return (~210 KB uncached; less with the service worker); 1 hello + state resend |
| Guest device memory/graphics | 1.4 MB console heap | 1.6 MB | game + console resident (3.0–3.5 MB here; real games are much larger) | one document at a time (1.6–2.1 MB) |
| Offline and startup | 17 requests (no bundler) | 5 requests, 10% fewer gzip bytes | instant open (18 ms) | 230–650 ms away round trip on loopback; Wi-Fi adds RTTs (owner gate) |
| A11y and presentation | parity | parity, plus compile-time a11y | focus trap in a frame; the game can draw over it | the plain page model; focus to game `#stage` on return |
| Migration risk | none | rewrite of ~2,160 + ~6,100 lines, or two paradigms side by side | exists today (layer) | #225 already prototypes it (needs the version fix) |
| Independent developer support | plain ES modules, no tools | familiar component model, but more moving parts | games must opt in and keep the frame on top | games only need "reconnect with a fresh ticket and resend state", which they already do |

## Recommendation and rejected alternatives

- **Chosen: vanilla + R.**
  - The console stays plain ES modules.
  - Add `// @ts-check` and JSDoc types, plus a keyed-list helper that keeps node identity and focus. This
    covers the lost-tap class of bug.
  - An esbuild bundle step is an optional later optimization for the request count; it adds a build but
    no framework.
  - Browsing (Home, Library, suggestions, Me) is a top-level Party page. Back to Game reloads the game
    and restores it from the server.
- **Rejected: Svelte now.** It is real but modest technical gain, with a high rewrite risk and toolchain
  churn. Revisit if the console grows into many stateful forms, or if a typed vanilla layer proves
  insufficient.
- **Rejected: M for browsing.** It is fast, but coverable. It also keeps the whole console inside the
  game's page (more memory), and it would still need R for sleep and eviction (ADR 0018 §4.1).
- **Rejected: M-embed** (a Party page framing the game).
  - It needs a new live `frame-ancestors` change.
  - The game frame cannot be meaningfully sandboxed.
  - rAF stops or continues depending on the engine.
  - Iframe second-class effects (fullscreen, audio unlock, wake lock) go untested.
- **Kept: today's layer drawer** over a game, for people and chat without trusted verbs.

## What ADR 0018 must specify for R

- **Browse is client-only.** Store no per-device viewport in Core state that bumps `version`. #225's
  `visit_home`/`back_to_game` `_commit()` must go, or must not touch `version`.
  - `destination()` must stop forcing a browsing guest back to the game, using a client-held "browsing"
    flag.
  - Back to Game is a plain navigation to the game URL that the Party location names.
- **Leaving.** Use the existing bridge `navigate` verb with a fixed target, never a URL. The proof added
  `navigate {to:'console'}`.
  - Production needs one word, for example `to:'home'`, or the guest-exit path.
  - Never put data in the `"*"`-targeted `ready` post (S7).
- **Return.** Every game must reconnect with a **fresh single-use ticket** and resend the full seat state
  on `hello`, including the private hand only to its seat and a spectator view after revocation.
  - The **ticket frame must be tiny.** It is on the Back to Game critical path (measured above).
- **Notices.** Typed Party notices (`your_turn`, `host_started`, `round_over`) reach the console with
  deadlines on the server clock. The game supplies no text.
- **Trusted controls.** Host verbs, Leave and suggestions approvals stay on top-level Party pages, never
  only in a coverable frame (S10).

## Rollback route

- Everything is behind a client flag such as `home_in_round` (S4 in the reconciliation). With it off,
  `destination()` keeps ADR 0011 forced following, and the layer drawer stays as it is today.
- R adds no Core state, so turning it off leaves nothing to migrate.
- If a vanilla bundle step is ever added, removing it restores the unbundled modules.
- This experiment directory can be deleted outright.

## NOT RUN: OWNER HARDWARE GATE

Physical iPhone Safari, physical Android Chrome, the Pi access point and Wi-Fi: **NOT RUN.** Owner steps, on
the appliance Wi-Fi once R is behind a flag on a test build:

1. Use two phones (iPhone with current iOS Safari, a low-end Android with Chrome). Join the Party and start
   a turn-based game (Checkers) and a realtime one (Tanks).
2. On each phone, during a round: open the Party control → console → Home, Library and Me → Back to Game.
   Record tap-to-playable with a stopwatch or screen recording: 10 tries each, p50 and p95. Pass if
   p50 ≤ 1 s.
3. While on the console, let the turn timer run out. Confirm the outcome equals a locked phone of the same
   duration.
4. Lock the phone for 30 s on the console and on the game, then unlock. Confirm the same seat and no
   duplicate member.
5. Rotate while on the console and after returning. Check keyboard and IME in a console field, and that
   audio and wake lock still work after returning to the game.
6. Repeat 2 with the Pi's Wi-Fi under load: 4 phones in a realtime round.
7. Cold-start offline (service worker on): open Party Home with no prior cache, then again warm. Note the
   load time.
8. Low-end Android memory: `chrome://inspect` → memory on the game page before and after 10 browse/return
   cycles. Look for growth.

Also not run: Linux CI, the real Party Core and devserver with these consoles, a screen reader, and
`npm run test:party-browser` in full (only the four specs above).
