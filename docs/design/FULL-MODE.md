# Full Mode web shell: `https://party.avrana.net/party/`

Status reconciled 2026-10-01: **implemented on main and deployed** at verified Party release
`956b968` (2026-09-29). Foundation PR #3 and assimilation/provider integration are merged;
Party Core runs behind `/party/api/`. Current main adds ADR 0011 in PR #34 / Games #13;
deployment and Tier 3 phone proof remain AVR-212. [SYSTEM](../SYSTEM.md) owns exact revisions.
Decisions: ADRs 0004 and 0006–0011. Deployment procedure: `docs/runbooks/party-https.md`.

**Two things are described here and must not be confused (2026-10-02):**

- **Deployed/current behaviour** — everything from "What it is" through "Open" below. `/party/`
  is HTTPS-only; without the trusted origin a phone sees "Can't reach the party" and a link to
  the legacy HTTP hub. Nothing in this document claims otherwise.
- **Accepted architectural target** — the [Full Mode / Limited Mode contract](#accepted-target-full-mode--limited-mode-contract-adr-0012-not-deployed)
  at the end, decided in [ADR 0012](../adr/0012-limited-mode-party-survives-https-loss.md). Rollout steps 1 and 2 are in source (ADR 0012 amendment); it is not deployed; AVR-225 owns it.

## What it is

This is the first Avrana-owned page on the secure origin. It is static files under `/party/`,
served by nginx from the 443 server only, with no shell daemon, port or systemd unit. Party Core is a separate service behind
`/party/api/`; static delivery does not eliminate its authority. It uses the secure
context, but no page depends on it: every feature degrades silently.

| Page | For | What it shows |
|---|---|---|
| `/party/` | guests | "Connected to the party · 🔒 Secure"; the games installed on this Party box, each with what it will be like on **this phone** ("Works on this phone" / "Works, with limits" / "You can watch" / "Not on this phone" + one plain sentence) and its live state ("1 of 2 playing", "Full right now", "Not running right now"); individual browser titles alongside arcade and experimental PS1 metadata; the shared Avrana profile and Party Chat; favorites/history and search/group-size filters; a "This phone" disclosure (secure connection, saved offline, live video, keeping the screen on, sound, controllers, vibration) |
| `/party/` with Party Core (current source, ADR 0011) | members | Automatic presence with an Avrana profile, roster/host, home or Party-owned full-screen Play/Watch setup; host-only Start. No normal Join/Leave buttons. Authoritative location sends members to the round/held results; host controls live in the game. Without Core/profile, standalone catalog access remains supported |
| `/party/` while the Pi is out of reach | guests | "Can’t reach the party. Make sure this phone is on the Avrana Party Wi-Fi", Try again, and a link to the basic HTTP version; it recovers by itself when the phone is back online |
| `/party/diag/` (also `/party/#diag`) | owner, developers, agents | every capability with its status, evidence level and note; the seat evaluation for every game in the catalog (installed or not); the providers of this Party box; offline-copy state; deep checks (WebGPU adapter, DataChannel loopback); a keep-awake test; a copyable `avrana.diagnostics/v0` report; the user agent, labelled as never used for decisions |

Party Home uses the shell modules on HTTPS; the arcade phone page uses `lib/keep-awake.js`
and authoritative Party follow. PS1 adoption remains experiment work, not runtime promotion.

## Files

| File | Role |
|---|---|
| `web/party/index.html`, `app.js`, `styles.css` | the guest page; `styles.css` is **generated** from `web/src/party.css` (Tailwind CSS 4 + daisyUI 5 at build time; `npm run check:ui`), the prototype-era `avrana` theme in [UI-DESIGN-SYSTEM](../UI-DESIGN-SYSTEM.md): dark only, rem type, 48 px targets, one bundled font and no remote ones, no machinery words (tested) |
| `web/party/lib/icons.js` | **generated** Lucide subset (`npm run build:icons`) |
| `web/party/lib/party-mode.js`, `party-client.js` | Party mode (ADR 0011): pure decisions from the Party Core view (`destination`, `roster`, `setupPanel`); the `/party/api/state` long poll, automatic presence and the host's moves. Party Home renders home and a round's full-screen setup scene |
| `web/party/lib/party-follow.js` | The Party under a game page (ADR 0011): keeps a member's page where the party is, keeps the phone present, and lends the game shell the host's controls (`window.AvranaParty`); no Party UI on the game |
| `web/party/lib/capabilities.js` | probe → `avrana.capabilities/v0` report (names = `contracts/capabilities.v0.json`) |
| `web/party/lib/evaluate.js` | per-seat evaluation + one guest sentence (`explain`) |
| `web/party/lib/keep-awake.js` | Screen Wake Lock policy |
| `web/party/lib/shell.js` | service-worker registration, kill switch, description |
| `web/party/sw.js` | the worker (policy below) |
| `web/party/catalog.json` | **generated** by `python3 -m avrana.contracts.catalog` from contracts + the appliance profile; CI checks it is fresh |
| `web/party/version.json` | `dev` in the repo; the install step writes the commit and the service-worker switch |
| `avrana/web/build.py` | copies the shell, stamps the build id into `sw.js`, writes `version.json` |
| `avrana/web/devserver.py` | a simulated Party on 127.0.0.1 for development and Tier 2 tests |
| `ops/install-party-web.sh` | Pi install: release directories, an atomic `current` symlink, `--rollback`, `--kill` |

## nginx (443 block only)

- `location = /party`: 301 to `/party/`.
- `location = /party/api/origin.json`: nginx answers directly. The body is
  `{"schema":"avrana.origin/v0","scheme","serverAddr","tls","http"}` with `no-store`.
  - The page uses it to tell "the Pi answered" from "not on the Party Wi-Fi".
  - Diagnostics use `serverAddr` to show whether the phone reached `10.42.0.1` (the AP).
- `location /party/`: `alias /var/www/avrana-party/web/current/`.
  - `Cache-Control: no-cache`, `nosniff` and `Referrer-Policy: same-origin`.
  - A CSP with no inline script or style (tested), same-origin only.
  - Never `Service-Worker-Allowed` and never HSTS (both tested).

The dev server sends the same headers, and a test compares the two.

## Capability probe classes

| Class | When | Probes |
|---|---|---|
| sync, no side effects | every page load | secure context, service worker, Cache Storage, WebSocket, RTCPeerConnection + DataChannel presence, H.264 in `RTCRtpReceiver.getCapabilities('video')`, Web Audio, Gamepad presence, Wake Lock presence, `crypto.subtle`, a localStorage round trip, IndexedDB, a WebGL/WebGL2 context (then lost), element fullscreen, vibrate, `mediaDevices`, touch points |
| async, never prompting | every page load | `permissions.query` for camera and microphone (`prompt` stays `unknown`), `storage.persisted()` |
| on request (diagnostics) | "Run deep checks" | `navigator.gpu.requestAdapter()` (1.5 s timeout), a local DataChannel loopback (a failure is `unknown`, never `no`: WebKit hides host candidates) |
| inside a tap only | Play | `wakeLock.request('screen')` |
| never automatic | — | `getUserMedia`, `storage.persist()`, notifications |

**Context facts are not capabilities.** Display mode, visibility, online, viewport, orientation,
pointer and preferences are reported separately. The report never contains the user agent.

## Offline copy (service worker) policy

- **Scope** `/party/`. Registered with `updateViaCache: 'none'`, after first paint, never on the
  critical path.
- **Touched:** only same-origin GETs under `/party/`, for pages (navigations) and the shell files
  listed in `SHELL`. A test fails if a new file under `web/party/` isn't listed.
- **Never touched:** `/party/api/*`, `sw.js`, `Range` requests, non-GET methods, the hub `/`,
  `/arcade/`, `/ps1/`, WebSockets and WebRTC.
- **Network-first everywhere.**
  - Pages wait up to 4 s for the Pi, then fall back to the saved copy.
  - Shell files fall back only on a network error.
  - A fresh 200 refreshes the cache. The cache name is `avrana-party-shell-<build>`, and older
    ones are deleted on activate.
- **Kill switches:**
  - `version.json` `serviceWorker: false` makes the page unregister itself.
  - `ENABLED = false` in `sw.js` (`install-party-web.sh --kill`) builds a self-destruct worker: it
    deletes its caches, unregisters and reloads open pages.
  - "Remove offline copy" on the diagnostics page does it by hand.
- **Not a recovery mechanism.** With an expired certificate an installed worker may still render
  the page, but every live call fails, and first visits or hard reloads show the browser's
  certificate error. Safari also evicts worker storage after about 7 days without use.

## Keep-awake policy

- Request the wake lock only inside the tap that starts play; on the arcade, also once the call
  connects.
- The browser releases it when the page is hidden. Re-request it on `visibilitychange` to
  visible while play is still wanted.
- Release it on Leave, on a final failure and on page exit.
- Every failure is silent: the only effect is that the screen may dim.
- Screen Wake Lock needs a secure context. Per MDN BCD, iOS Safari supports it from 16.4 in a tab and
  from 18.4 in Home Screen apps.

## Arcade behavior and remaining reconnect gap

- The screen stays on during play.
- "Both controllers are in use" is shown only when `/arcade/stats` says the game is full.
  Otherwise the page says it "Can’t connect right now".
- A drop triggers "Reconnecting…" with up to five quiet retries, paused while the phone is locked.
- Stream disconnect is lower-level stream behavior, not ordinary Leave Party UI.
  ADR 0011 source keeps member pages at the authoritative Party location.
- The raw stats JSON is shown only with `#diag`.
- Every id and text the live suite relies on is kept (tested offline).
- **This goes live with the production fast-forward**, not with the shell deploy: `stream.py`
  serves `index.html` from the checkout on every request (runbook, "When the arcade changes go
  live").
- Party session tickets/navigation alone do not guarantee a controller slot. AVR-130 source
  merged in PR #35 during this reconciliation adds stable session-local reservations and
  60-second grace. Deployment/real-phone acceptance remains unverified by published findings.
  Preserve the broader seat grace/release requirements in `PARTY-LIFECYCLE.md`; PS1 remains an experiment.

## Tested where (source coverage; results need a dated run)

| Claim | Tier | Test |
|---|---|---|
| Captive HTTP unchanged; `/party/` HTTPS-only with the right headers; origin JSON; apps still proxied | 2 (real nginx, fake upstreams, self-signed cert) | `tests/unit/test_nginx_site.py` |
| Probe names = vocabulary; fake browsers (HTTP, iPhone-like, throwing APIs); no user agent in the report | 1 | `tests/offline/capabilities.test.mjs` |
| Evaluation = Python on 18 shared vectors; guest sentences free of machinery words | 1 | `tests/offline/evaluate.test.mjs`, `tests/unit/test_evaluate.py` |
| Worker policy, precache, activate, fallback, 4 s timeout, kill switch | 1 (VM) | `tests/offline/sw.test.mjs` |
| Page states, offline copy, recovery on `online`, scope never covers `/`, diagnostics, arcade reconnect/full/lock/Leave with fake signalling | 2 (Chromium, 127.0.0.1) | `tests/offline/*.spec.ts` |
| Build, precache completeness, CSP-safe pages, install/kill/rollback | 1 | `tests/unit/test_web_build.py` |
| **Real iPhone Safari and Android Chrome, the real certificate, Party DNS, actual wake lock, offline-copy behaviour with a real Wi-Fi drop** | **3, not done** | checklist in `docs/runbooks/party-https.md` |

Chromium was the only browser here. Playwright's WebKit on Linux is not iPhone Safari, so it was not
used as evidence.

## Open

- **Owner decisions:** the HTTP doorway page and the QR code URL (`ONBOARDING.md`).
- **To observe on real phones:**
  - how Party DNS behaves under Private DNS, iCloud Private Relay or a VPN;
  - whether Safari's 7-day eviction removes the offline copy between parties;
  - what an installed worker does with an expired certificate.
- **To decide:** PNG icons for iOS home screens (only an SVG icon ships today).
- **Depends on a public endpoint:** both the game card's live state and the arcade page's "full"
  check read the public `/arcade/stats`, which also shows players' IP addresses. If it is ever
  restricted (PS1 already limits its `/stats` to 127.0.0.1), add a small public summary
  (`players`, `max_players`, `running`) first. Live `tests/multiplayer.spec.ts` depends on the
  "full" wording.

## Accepted target: Full Mode / Limited Mode contract (ADR 0012; not deployed)

The deployed behaviour above treats trusted HTTPS as a precondition for Party Home. [ADR 0012](../adr/0012-limited-mode-party-survives-https-loss.md)
changes the target: **trusted HTTPS is the preferred Full Mode, and its loss must not disable the
Party.** The deployed HTTPS-only behaviour will evolve toward this contract; until a verified
deployment changes it, [SYSTEM](../SYSTEM.md) and the sections above remain the truth about
production.

| | **Full Mode** (deployed today) | **Limited Mode** (target) |
|---|---|---|
| Reached when | the browser trusts `https://party.avrana.net` | the certificate is expired or untrusted, Party DNS is bypassed, or the browser otherwise cannot establish trusted HTTPS |
| Party membership, presence, host authority and succession | yes | **yes** |
| Synchronized Party navigation (one location, ADR 0011) | yes | **yes** |
| Game selection, launch and play | yes | **yes, for compatible games**; a game whose contract requires a secure context is explained as unavailable for that seat, not hidden |
| Phone-only operation, no TV, no app, no Internet | yes | **yes** |
| Offline copy (service worker), Screen Wake Lock, secure-context-only browser APIs | yes, each silently optional | **degrade individually**: absent, with the capability report saying why |
| Device identity | `avrana_device` cookie, `Secure` | **an explicit Limited Mode identity/continuity model** (AVR-225); the `Secure` cookie is never weakened to work over HTTP |
| What the player is told | "Connected to the party · Secure" | a visible, plain-language degraded state: not secure, which conveniences are missing, how Full Mode returns |

Rules that carry over unchanged: capabilities are observed, never inferred from the user agent;
`unknown` is never `no`; a weak seat never downgrades the Party (ADR 0004 D2); no HSTS, so an
expired certificate stays escapable (ADR 0004 D1); the offline copy is a convenience, not the
recovery mechanism (ADR 0004 D5) — Limited Mode is.

Not decided here: the Limited Mode credential and how a phone keeps its member across a mode
switch; the HTTP doorway page; which hidden-information games are offered without TLS; how the
game origin ([ADR 0013](../adr/0013-party-and-game-browser-origins.md)) is reached in Limited Mode. The port-80 nginx change this needs is
an owner-approved deployment, not implied by this document.

Product ownership and donor compatibility: read [LAN Games assimilation](LAN-GAMES-ASSIMILATION.md)
(historical; LAN Games is retiring as a runtime, [ADR 0014](../adr/0014-native-games-isolated-lan-games-retired.md)).
