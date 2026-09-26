# Architecture sprint: audit, substrate verification, Cloud-tested foundations

Date: 2026-09-26. Starting `main`: `d092ffda28bcb99976afc348ac2a24ca5d7b959e` (PR #2, party HTTPS).
Branch: `claude/dreamy-carson-sja5mq`. It merges PR #1's branch (`claude/kind-mayer-ay6dqi`, still open) as its CI base.

Where things are recorded:
- decisions: `docs/adr/0004-full-mode-contracts-and-providers.md`;
- substrate classifications: the matrix at the top of `docs/AVRANA-OPEN-SOURCE-SUBSTRATE.md`;
- the web shell: `docs/design/FULL-MODE.md`.

Labels:
- **TESTED**: run in Claude Code Cloud, on Linux x86-64.
- **CODE**: read in source.
- **UPSTREAM**: read in an upstream repository, licence or release on 2026-09-26.
- **INFERRED**: reasoning.
- **OPEN**: not yet known.

**Nothing below was run on the Pi or a phone.**

## TESTED in Cloud

Toolchain: Node 22.22.2, Python 3.11.15, nginx 1.24.0 (Ubuntu package, installed only for the test),
OpenSSL 3.0.13, and Chromium 141.0.7390.37 (the pre-installed Playwright build, launched through
`PW_CHROMIUM_EXECUTABLE`). No new npm or Python dependency.

| Suite | Result |
|---|---|
| `python3 -m unittest discover -s tests/unit` (with `AVRANA_REQUIRE_NGINX=1`) | 57 pass |
| `node --test 'tests/offline/*.test.mjs'` | 41 pass |
| `npx playwright test -c playwright.offline.config.ts` (2 Chromium projects) | 32 pass |
| `npx playwright test tests/soak-metrics.spec.ts` (PR #1 lane) | 10 pass |
| `python3 -m avrana.contracts.catalog --check`; `cmp avrana-party.nginx arcade/nginx-site` | clean |

What the runs showed:

- **Real nginx with the committed site, stand-in upstreams and a self-signed certificate:**
  - HTTP: the Apple probe still returns the literal `Success` with `no-store`.
  - HTTP: `/`, the Android probe path and even `/party/` still go to the LAN Games upstream.
  - HTTPS: `/party/` serves the shell with CSP, `no-cache`, `nosniff` and `Referrer-Policy`;
    `/party/api/origin.json` reports `https` and TLS 1.2 or 1.3; `/` and `/arcade/` are still proxied.
- **Offline copy, in Chromium:**
  - The worker registers with scope `/party/` and never controls `/`.
  - With `context.setOffline(true)`, a reload is served from the saved copy and shows "Can’t reach
    the party".
  - When the phone is back online the page recovers without a tap, from the `online` event.
  - So Playwright's offline mode does apply to service-worker fetches in this Chromium. This
    answers audit E's open question for Chromium only.
- **This Chromium build lists no H.264 in `RTCRtpReceiver.getCapabilities('video')`.** It reports
  "Not on this phone" for the arcade unless the test pins H.264.
  - That is the correct result for a browser without H.264.
  - Real iPhone Safari and Android Chrome are expected to list it (INFERRED), but that is **OPEN
    until a phone's `/party/diag/` report is recorded**.
- **The uinput adapter matches the original arcade code.** Over 200+ random snapshots it creates
  the same device and writes the same events in the same order as the pre-extraction `Pad` code.
  A stubbed-GStreamer run of `arcade/stream.py` startup, `/stats` and cleanup drives both providers.
  **The arcade was not streamed**; that needs the Pi.

## Repository audit (CODE unless marked)

- **The arcade labels every phone "other network" on `main`.** `arcade/stream.py` `ap_addresses()`
  still reads `wlan1`, but the AP moved to `wlan0` on 2026-09-24.
  - So the arcade page shows every phone the "connected through your home network" banner.
  - The fix is on `fix/arcade-ap-interface` (3 tests, clean merge) and is **not merged**. Merging
    it was out of scope for this sprint, so it stays a separate owner step.
- **HTTPS blockers on experiment branches** (not on `main`):
  - `experiments/party-service/service.py:325` accepts only `http://` Origins for POSTs, so every
    Join or host action gets 403 on the HTTPS origin.
  - `ps1/stream_ps1.py:549` accepts only an `http://` Origin, so the WSS upgrade gets 403.
  - `identity.py:107` sets the device cookie without `Secure`.
  - `main`'s arcade already accepts `https://`.
- **Mixed content: none.** Every served page builds WS and fetch URLs from `location`.
- **Security spots:**
  - `/arcade/stats` is public through nginx and includes peer IPs. The live harness reads it.
  - The arcade and PS1 Origin==Host check is not a DNS-rebinding defence. nginx has no Host allowlist.
  - The arcade has no input rate limit.
  - The dev `DeviceStore` issues and persists a token for every cookieless request, with no cap.
- **Reliability:** `Stream.watch()` returns on a fatal error without exiting the process, so systemd
  never restarts the arcade (research B).
- **Duplication:**
  - Slot and seat logic exists four times (arcade, PS1, party model, viewport PoC), with grace times
    of 0, 30, 60 + 300 and none.
  - Seat-ticket verification is copied on two branches.
  - The WebRTC peer setup and pipeline are near-copies between arcade and PS1; PS1 monkey-patches
    `arcade/stream.py`.
- **Docs written before HTTPS:** `PARTY-PLATFORM.md` §4, §13 and §16.1, and `ONBOARDING.md`. They
  are now annotated to point at ADR 0004.

## Party-engine research (UPSTREAM + scratch runs of branch code)

- **No framework models a party.** Colyseus, boardgame.io, Couch Kit, Hotspot Arcade, AirConsole and
  Jackbox all model one game session. Avrana owns the party layer, and the Python model is the base.
- **Three gaps in `experiment/party-service` code**, verified on scratch copies:
  - Seat ticket v1 binds a *slot*: after a release and refill, the old ticket still grants that slot.
  - `input_connection()` returns a connection for a spectator.
  - Presence liveness counts only the party event stream, so players inside a game page without
    `party.js` look gone after 300 s.
- **State model review:** `docs/design/PARTY-PLATFORM.md` §5.1. In short:
  - Person is not stored.
  - Connection, InputBinding and Surface are separate entities.
  - A TV is a public Surface with no Presence.
  - Roles are derived facts or pointers, never stored per presence.
- Colyseus memory, measured on x86 (not the Pi): about 88–91 MB RSS, against about 23 MB for the
  Python front.

## Runtime and network research (UPSTREAM)

- **Corrections to the substrate doc** (the details are in its matrix):
  - Wolf gives each client its own encode, publishes amd64-only images and has no V4L2 encoder.
  - Gamescope is BSD-2-Clause and rejected on the Pi 4.
  - "Moonlight-Web" is two GPL-3.0 projects.
  - InputPlumber has no network input.
  - Selkies 2.0 + pixelflux 2.1 now have a Pi 4 V4L2 M2M encoder and shared-encode fan-out: this
    is spike S3.
  - openNDS would bring the captive popup back, so it is rejected as a runtime.
  - RAUC is LGPL-2.1.
- **Certificate runway:**
  - The live Let's Encrypt certificate expires on **2026-12-25**, and renewal becomes eligible
    around **2026-11-25**. Automatic renewal is still off.
  - Let's Encrypt's default lifetime drops to 64 days on 2027-02-10 and to 45 days on 2028-02-16.
    Offline Full Mode therefore caps at those runways, which makes the HTTP recovery origin and the
    app path core product paths.
  - The planned Cloudflare token would be zone-wide. Delegate `_acme-challenge` by CNAME to a
    validation-only zone, or wait for DNS-PERSIST-01.
  - Check `lego --version` on the Pi: v5 breaks `ops/renew-party-certificate.sh`.
- **Service worker and an expired certificate** (INFERRED from the Fetch spec and Chromium source,
  not device-tested):
  - An installed worker can still serve the cached page without a TLS handshake.
  - First visits, hard reloads, worker updates and every live `fetch` or `wss` call fail.
- **Browser support** (MDN BCD):
  - iOS Safari Wake Lock: 16.4 in a tab, 18.4 in Home Screen apps.
  - iPhone has no element fullscreen, orientation lock or vibration.
  - `navigator.onLine` says nothing about whether the Pi is reachable.

## Not proven (Tier 3, for the owner)

- The shell on a real iPhone and Android phone over the real certificate and Party DNS.
- Whether the wake lock actually holds during arcade play.
- Real-Wi-Fi offline-copy behaviour.
- Party DNS under Private DNS, iCloud Private Relay or a VPN.
- The refactored arcade streaming on the Pi, and every hardware spike (S1–S6, Rugix, Wasmtime).
- Nothing was deployed.
