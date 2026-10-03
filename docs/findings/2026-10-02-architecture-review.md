# Finding: first-principles architecture and technology-stack review (2026-10-02)

Status: **review and recommendation, not a decision.** Nothing here changes an ADR, a Linear
issue or a deployment. Written against GitHub `main` `ae102f8` (plus the `.work-avr213-games`
checkout of the Games fork), ADRs 0001–0011, the design index, SYSTEM, dated findings, the
committed Graphify graph report (built from `ae102f8`), and live Linear on 2026-10-02 (222
issues; the Avrana Party project's open set is summarised in §1.6). The Pi was not touched.

Every claim is tagged. **[E]** evidence read in source, config, a dated finding or Linear.
**[I]** inference from that evidence. **[R]** recommendation. A recommendation never rests on an
untagged inference; where I could not verify something it says so.

The question asked is not "does the code work" but "is the design right for what Avrana is
trying to become": a portable, offline, no-app, no-TV party appliance that one day ships to
people who are not the owner.

---

## 1. The system as it exists today, in plain English

### 1.1 The box

[E] One Raspberry Pi 4 running Debian 13. Its internal Broadcom radio (`wlan0`) is the party
access point: SSID "Avrana Party", WPA2, 5 GHz channel 149, `10.42.0.1/24`, run by
NetworkManager in shared mode, which also runs a dnsmasq for DHCP and DNS. Ethernet (`eth0`,
`10.0.0.142`) is the only management path and also gives party phones NAT access to the home
LAN and the internet. Avahi announces `party.local`. There is no RTC, no battery, no enclosure.
([network runbook](../runbooks/network.md), [SYSTEM](../SYSTEM.md))

[E] dnsmasq answers the captive-probe hostnames of Apple, Google, Microsoft and Firefox with
`10.42.0.1` and has one real `host-record`: `party.avrana.net → 10.42.0.1`. Public DNS has no
record for that name. ([avrana-captive.conf](../../avrana-captive.conf))

### 1.2 The front door

[E] nginx has two servers. Port 80 (default server, any host): returns Apple's literal
`Success` for `/hotspot-detect.html` so iPhones never see a captive popup; proxies `/arcade/`
to the arcade and everything else to the LAN Games server. Port 443 (`party.avrana.net` only,
Let's Encrypt certificate issued by manual DNS-01 on 2026-09-25, valid to 2026-12-25, renewal
timer **staged but not enabled**): serves the static Party shell under `/party/` with a strict
CSP, proxies `/party/api/` to Party Core on loopback, and proxies `/arcade/` and `/` as on
port 80. No HSTS by decision. ([avrana-party.nginx](../../avrana-party.nginx),
[party-https runbook](../runbooks/party-https.md), ADR 0004)

### 1.3 Three services, three Python web stacks, one Unix user

| Service | Stack | State | Listens | Runs as |
|---|---|---|---|---|
| **Party Core** `avrana-party-core` | Python stdlib `http.server.ThreadingHTTPServer`, one global lock, 1 s timer thread | memory-only party; hashed device tokens in `devices.json` | `127.0.0.1:8191` | `cody` |
| **Games** `avranaparty-games` (private fork of retired LAN Games) | FastAPI + uvicorn + `websockets`, one process, ~30 game modules + WORDCLASH sub-app + chat + avatars | memory; avatars/chat media on disk; old venv | `:8096` (all interfaces) | `cody` |
| **Arcade** `avranaparty-arcade` | aiohttp + GStreamer (`webrtcbin`, `v4l2h264enc`) + Xvfb + PulseAudio null sink + RetroArch (MAME 2010) + uinput pads | memory; logs | `127.0.0.1:8097` (phones via nginx) and `127.0.0.1:8098` (Party control, never proxied) | `cody` |

[E] All three units run as the same user `cody` from the production git checkout in
`/home/cody`; Party Core and the arcade are hardened with `ProtectSystem=strict`,
`NoNewPrivileges` and friends; the Games unit template in the fork is not. Deployment is "fast-
forward the checkout, run owner sudo scripts". ([deploy/party-core](../../deploy/party-core/),
[arcade unit](../../arcade/avranaparty-arcade.service), [party-core deploy
runbook](../runbooks/party-core-deploy.md))

### 1.4 The Party model

[E] Party Core (`avrana/party/core.py`, 696 lines, pure and synchronous) owns: one party per
appliance; members keyed by a server-issued device id; presence derived from "any authenticated
request in the last 45 s"; a single host with 30 s grace and deterministic succession; exactly
one game session at a time with states `setup → launching → active → ending → ended`; a
committed navigation sequence and a derived `location` (`home | setup | game | results`) that
only the host moves; versioned host actions (`if_version`). It deliberately does not own:
persistence across restart, kicks, votes, profiles, teams, seats, results.

[E] Identity is layered as ADR 0003 prescribes, but only three layers exist in code: the
**device** (256-bit token in cookie `avrana_device; Path=/party/; HttpOnly; Secure;
SameSite=Lax`, ~400 days, SHA-256 stored), the **member** (one per device per party) and the
**participant** (random id per member per session, the only identity a game ever sees). The
"profile" that makes presence automatic (ADR 0011) is a **name and avatar id in the phone's
localStorage**, shared with LAN Games' `wc-name` key. There is no server-side profile, PIN,
trust link or pairing. ([identity.py](../../avrana/party/identity.py),
[party-follow.js](../../web/party/lib/party-follow.js), [profile.js](../../web/party/lib/profile.js))

### 1.5 Party ↔ game protocol

[E] `avrana.party-session/v0`: every token and message is `aps0.<b64url(canonical JSON)>.
<b64url(HMAC-SHA256)>` with `v, typ, iss, aud, sid, iat, exp`. One random 32-byte key per game
in a 0600 file, held by Party Core and that game's server. Party → game: signed `launch`
(roster of `{participant, name, role}`, 30 s, nonce) and `end`, over loopback HTTP. Party →
browser → game: a 120 s bearer `ticket` fetched with the cookie and sent only as the first
WebSocket message. Game → party: signed `ended` to an `/internal/` route that accepts loopback
only and refuses proxy headers. Replay guard by nonce. The game derives a stable per-(session,
participant) secret where LAN Games used `wc-token`. The protocol file is stdlib-only and
vendored unchanged into the Games fork, pinned by shared test vectors.
([protocol.py](../../avrana/party/protocol.py), ADR 0006)

[E] The arcade implements the game side as a "managed runtime": RetroArch and the encode run
only between `launch` and `end`; Party Core's switch is end-then-launch so two heavy runtimes
never overlap (ADR 0008/0009). Controller slots in Party mode come only from tickets and are
reserved 60 s across disconnects (PR #35, AVR-130, deployment unverified).

### 1.6 The browser

[E] `/party/` is static ES modules (no bundler), Tailwind 4 + daisyUI 5 generated CSS, Lucide
icons, DiceBear avatars. A service worker scoped to `/party/`, network-first with a 4 s
navigation timeout, caches only the shell and never `/party/api/`; three kill switches. A
capability probe (`avrana.capabilities/v0`) feeds a per-seat evaluator that exists twice
(Python and JS) and is pinned by shared vectors. Party state arrives by one long poll
(`GET /party/api/state?since=V&wait=20`; nginx read timeout 40 s), which is also the heartbeat.
Every canonical page applies `destination(view, here)` with `location.replace`; game pages load
`party-follow.js` by dynamic import, only in a secure context, and expose `window.AvranaParty`
to the game's own chrome. LAN game clients (`hubnet.js`, 813 lines) still carry the legacy
`wc-token` for standalone play, avatar upload and chat, and ask Party Core for a ticket before
each socket when launched with `?avrana=1`.

[E] Linear's open Avrana Party set (2026-10-02) is dominated by P4 research/design backlog
(`.avrgame`, SDK, courier, trust, viewports: roughly 60 issues) plus a small P2/P3 set of real
proofs and hardening: AVR-212 (phone-verify ADR 0011), AVR-12 (four phones), AVR-27 (offline
BLUFF acceptance), AVR-10 (offline cold boot), AVR-11 (onboarding), AVR-31 (cert renewal),
AVR-33 (restart/crash), AVR-216–222 (hostile-audit hardening: long-poll exhaustion, fan-out
under lock, wall-clock jumps, catalog corruption, cross-repo CI, legacy LAN attack surface).

[I] In one sentence: **Avrana today is a well-reasoned party coordinator (Party Core) bolted
onto two inherited runtimes (a retired LAN Games server and a GStreamer arcade stream) on one
Pi, reachable through a public-certificate trick on a private network, with the browser as the
only client.** The coordinator is the deliberate part; most of the rest is inherited or
convenient.

---

## 2. Technology and protocol review, choice by choice

Each entry answers the eight questions compactly: problem · prototype fit · appliance fit ·
assumptions · what breaks · alternatives · migration cost · nature (deliberate / convenience /
legacy).

### 2.1 Product boundary: one appliance, one party, Party owns identity, games own rules

- Problem: unify five per-game identity/lobby/reconnect systems into one party. [E] ADR 0002.
- Prototype: right. Appliance: right. This is the thesis and it is sound.
- Assumes one host moves everyone, friends-party trust, no multi-tenant.
- Breaks if a venue wants two tables (explicitly rejected) or if games need to drive navigation.
- Alternatives considered in ADR 0002 are adequately rejected.
- Migration cost of reversing: total. Nature: **deliberate**. Freeze it.

### 2.2 Raspberry Pi 4 as the appliance

- Problem: cheap, available, GPIO/HDMI, hardware H.264 encoder.
- Prototype: fine. Appliance: **poor**, and the docs already say so (GAME-PLATFORM-ARCHITECTURE
  "the current Pi is a prototype platform").
- Assumes: a V4L2 M2M H.264 encoder (`/dev/video11`), ~4 cores, an AP-capable radio, SD-card
  storage, no RTC, 5 V/3 A USB-C power.
- What breaks: [E] under-voltage history; [E] PS1 + arcade + stream exceed 4 cores; [E] the
  internal radio is reported to cap near 8 stations; [I] **the Raspberry Pi 5 has no hardware
  H.264 encoder**, so the obvious next board breaks the entire streaming path as built (verify
  against current Pi 5 documentation before planning; this is well known but I did not re-check
  it in this session). No RTC means offline cold boots start with a wrong clock unless
  fake-hwclock saves it.
- Alternatives: Pi CM4/CM5 carrier with external radio and RTC; Rockchip (RK3588 has MPP
  encoders); x86 mini-PC (QuickSync) for a field-test unit; or redefine central streaming as
  optional so the SoC choice is freed.
- Migration cost: low for Party Core and the games server (portable Python); **high for the
  arcade/PS1 streaming path** unless the `PresentationProvider` boundary is kept honest.
- Nature: **convenience that is becoming legacy**. Hardware abstraction exists on paper (ADR
  0004 D4) but `v4l2h264enc`, `ximagesrc`, Xvfb and `/dev/uinput` are concrete in `stream.py`.

### 2.3 Linux service layout: three units, one user, run-from-checkout

- Problem: get three processes supervised.
- Prototype: acceptable. Appliance: **not acceptable**.
- Assumes: the owner is the operator; a git checkout is the release artifact; `cody` owning
  every key file is isolation enough.
- What breaks: [E] the "0600, readable by the party service and that game only" key story in
  ADR 0006 is **nominal**: all three services share one uid, so any process can read every key,
  `devices.json`, `venue.json` (holds the Wi-Fi password) and the avatar store. [E] Deployment
  requires owner sudo and a sequence of scripts; rollback is manual per component; there is no
  image, no A/B, no reproducible install (AVR-32, AVR-67 open).
- Alternatives: one uid per service (or `DynamicUser`) with keys in per-service
  `CredentialsDirectory`; unix sockets instead of loopback TCP; an image-based install with A/B
  rollback (Rugix spike already identified).
- Migration cost: low now (units and paths), moderate later once more services exist.
- Nature: **convenience**. The hardening flags on Party Core and the arcade show intent; the
  shared user undoes it.

### 2.4 Networking topology, NAT, offline behaviour

- Problem: phones must reach the box with no infrastructure.
- Prototype: fine. Appliance: partially wrong.
- Assumes: NetworkManager shared mode is the AP stack; the home LAN is behind the Pi.
- What breaks: [E] every phone test so far had internet behind it, hiding real offline
  behaviour (Android never "validates" the network, iOS fakes success). [E] `.local` queries
  leak upstream; Avahi advertises `party.local` on the home LAN too. [E] The AP radio's power
  save was on and is the prime suspect for 1–2 s stalls in the PS1 playtest. [E] Three home
  Wi-Fi client profiles still autoconnect at the AP's priority, so a boot can come up as a
  client with no party network (PROPOSED fix, not applied). [I] NetworkManager owning dnsmasq
  means every DNS change bounces the AP.
- Alternatives: hostapd + a dedicated dnsmasq owned by Avrana (NM only for the uplink); for an
  appliance, a dedicated AP radio with its own power budget and 2.4 + 5 GHz; regulatory domain
  from a setting, not a hard-coded channel 149.
- Migration cost: low (config), but every change is a live-network owner step today.
- Nature: **convenience/legacy** (it is what NetworkManager gave for free).

### 2.5 Wi-Fi/AP strategy

- [E] Internal Broadcom radio, 5 GHz only, channel 149, WPA2-PSK, reported ~8 station ceiling,
  no client isolation. Fine for the owner's living room.
- [I] For a shipping appliance this is the single hardware decision that bounds the product:
  party size, latency stability, legality abroad and battery life all follow from the radio.
  A USB radio was removed because it caused under-voltage, which is a power-design problem, not
  an argument for the internal chip.
- [R] Treat "which radio, how powered" as a hardware decision to make before any field test.
  Measure the real client ceiling (AVR-12) before promising more than four players.

### 2.6 DNS and captive-portal behaviour

- Problem: join Wi-Fi without a popup, open a browser, land on the party.
- Prototype: good. Appliance: good, with one caveat.
- [E] The "no popup, just connect" decision (ADR context, 2026-09-18) is deliberate and correct:
  captive mini-browsers have their own cookie jar and close themselves. Android's 404 is
  accidental but harmless; RFC 8910 is unusable offline because it needs valid HTTPS.
- What breaks: [I] answering Android's `/generate_204` with 204 would make phones believe they
  have internet and stop using mobile data, which may hurt; the finding correctly defers that.
- Nature: **deliberate**. Keep. The QR/onboarding address question (HTTP IP vs HTTPS name) is
  still open and should be closed by the real-phone test, not by design.

### 2.7 HTTPS: public certificate for a private address, resolved by local DNS

This is the most consequential technology choice in the system, so it gets more space.

- Problem: secure context on phones (Wake Lock, service worker, `Secure` cookie, future
  WebCodecs/WebGPU) with no app and no private CA.
- Prototype: **excellent**, and already live. Appliance: **fragile** in four independent ways.
- Assumes: (a) the phone resolves `party.avrana.net` through the party's DNS; (b) the
  certificate is valid; (c) the box gets internet, a Cloudflare token and a working `lego`
  within the renewal window; (d) Avrana controls `avrana.net` forever.
- What breaks:
  - [I] (a) fails under Android Private DNS, iOS iCloud Private Relay, any always-on VPN or
    DNS-over-HTTPS browser setting; the phone looks up the name publicly, gets NXDOMAIN, and the
    party does not exist. Unverified on real phones (ONBOARDING test 6).
  - [E] (b)/(c): the renewal timer is not enabled; the cert expires 2026-12-25; Let's Encrypt
    lifetimes drop to 64 days (2027-02) and 45 days (2028-02), so **offline Full Mode runway
    shrinks to about six weeks** of no internet. The "drawer for a year" scenario in
    OFFLINE-TRUST-AND-RECOVERY is the normal case for a party box.
  - [E] Because the Party cookie is `Secure` and the Party page is HTTPS-only (ADR 0004 D1),
    **an expired certificate does not just lose Wake Lock; it loses Party Core, identity,
    presence and the console model entirely**. Plain HTTP falls back to the legacy LAN Games
    hub with client-minted tokens, which is the pre-Avrana product. The docs frame HTTPS as an
    enhancement; the implementation has made it a dependency.
  - [I] (d) A fleet cannot share one private key (the design doc already says so); per-device
    subdomains need an Avrana-run DNS/ACME service, which is the first piece of cloud
    infrastructure the "no cloud" product would depend on, if only at manufacture and renewal.
- Alternatives: (1) keep HTTPS as the preferred origin but make Party Core work on the HTTP
  origin too with a non-`Secure` cookie, accepting that HTTP and HTTPS are two devices (the
  cost is a one-time re-presence, not a lost party); (2) per-device `<id>.party.avrana.net`
  certificates issued by an Avrana service and delivered by a companion app or the box's own
  uplink, with a device keypair for recovery (the design direction already written); (3) a
  private CA installed via an optional app (rejected, rightly, as the baseline).
- Migration cost: (1) is cheap now (a config flag and an origin allowlist) and becomes expensive
  once profiles, stats and pairing bind to the HTTPS identity. (2) is a product decision with
  ongoing operational cost.
- Nature: **deliberate (D1), but its consequence for identity is accidental**. ADR 0004 says
  "HTTP is not a recovery path for the Party page". That sentence should be revisited now.

### 2.8 nginx as the single reverse proxy

- Problem: one origin, TLS termination, path routing, captive answers.
- Prototype: right. Appliance: right.
- [E] Two byte-identical copies of the site file (`avrana-party.nginx`, `arcade/nginx-site`),
  enforced by CI. [E] `/arcade/stats` is public and shows peer IPs. [E] nginx forwards
  `X-Forwarded-For` to Party Core but not to the arcade on 8097, which is why 8098 exists.
- [R] Keep nginx. Delete the duplicate file (it is pure legacy; `deploy/README.md` keeps it only
  because scripts reference the path). Add a Host allowlist on 443 (DNS rebinding) and a small
  public summary endpoint so `/arcade/stats` can be made internal.
- Nature: **deliberate**, with one **legacy** wart.

### 2.9 Party Core architecture (pure core + thin HTTP service)

- Problem: an authoritative, testable party state machine.
- Prototype: **strong**. The pure core with injected clock, fuzzed invariants (`nav.seq` never
  goes back; nobody seated in setup) and timers applied at request time (R4) is the best-built
  part of the system. Appliance: the core is right; the service around it is not (2.10).
- Assumes: one lock serialises everything; one party fits in memory; a restart is acceptable.
- What breaks: [E] Party Core restart = new party; every phone silently re-joins via automatic
  presence, but the live game session is orphaned: the Games room still believes it is in a
  party session until the host's next action (`on_launch` replaces it). [I] No startup
  reconciliation exists between the three processes; recovery is "the host presses something".
- [R] Persist a party snapshot on every commit (option B in PARTY-LIFECYCLE) and reconcile
  with game servers on start. This is a few hundred lines and removes the most common
  real-world failure (power blip) from the "lost party" column.
- Nature: **deliberate**. Keep the pure core even if everything around it changes.

### 2.10 Python runtime choices: stdlib `http.server` + threads (Party Core), FastAPI/uvicorn (Games), aiohttp (arcade)

- Problem: three codebases, three origins of code (new, inherited, inherited).
- Prototype: acceptable. Appliance: converge.
- [E] Party Core uses `ThreadingHTTPServer`: one thread per in-flight long poll, held up to
  25 s, no concurrency bound (AVR-218), no request timeouts beyond nginx's. It is loopback-only
  behind nginx, so it is survivable for eight phones. [E] Games: one asyncio loop for 30 games,
  WebSocket fan-out inside the room lock (AVR-217). [E] Arcade: asyncio plus GStreamer threads
  plus `run_coroutine_threadsafe`, with a watchdog added after a silent encoder stall.
- Assumes: Python 3.11+ on the Pi (system interpreter for Party Core and arcade, an old venv for
  Games); the GIL is not the bottleneck (it is not; the encoder and emulator are).
- What breaks: [I] three failure models and three logging/health conventions make operations
  disproportionately complex for one appliance; nothing shares a health or metrics shape.
- Alternatives: one asyncio stack (aiohttp or Starlette) for Party Core when the long poll is
  revisited, keeping `core.py` untouched; or fold Party Core into the Games process (rejected
  in ADR 0002 because the party would die with the games process; that reasoning still holds).
- Migration cost: low for Party Core's service layer (383 lines), zero for the core.
- Nature: stdlib server = **convenience** (explicitly "no dependency"); FastAPI = **legacy**
  (inherited); aiohttp = **convenience** (what GStreamer examples use).

### 2.11 Long poll as the party transport

- Problem: ordered, resumable state to phones through nginx and a service worker, with
  nothing new to deploy (ADR 0007 §4).
- Prototype: **right**; it survived iOS sleep/wake better than sockets would and needed no
  nginx change. Appliance: acceptable up to a dozen phones; revisit only with evidence.
- Assumes: state is small enough to resend whole on every version bump (chat was already noted
  as the exception in COMMUNICATION.md); phones are few.
- What breaks: [E] every join, rename, choice or presence flip bumps the version and wakes
  every poll with a full view; `if_version` is party-wide so a host action can be `stale`
  because a phone woke (PARTY-LIFECYCLE open item). [I] Adding chat, teams or votes to this
  view multiplies traffic by members squared.
- Alternatives: SSE for push (same origin, still proxy-friendly), WebSocket for games only.
- Migration cost: low; the client already isolates it in `party-client.js`.
- Nature: **deliberate**, and correctly reversible. Do not put chat on it.

### 2.12 FastAPI/uvicorn/WebSocket game server (LAN Games fork)

- Problem: inherited; it is where 30 games and BLUFF live.
- Prototype: fine. Appliance: **the biggest unresolved legacy decision in the system.**
- [E] One process imports every game at startup; one import error stops all games; any module
  sees every session; the standalone path still trusts a browser-minted `wc-token`; any client
  can clear chat; the registry is a proto-manifest; `core/session.py` and `core/net.py` are,
  in effect, the Game SDK v0 that the roadmap says does not exist.
- Assumes: the owner curates the 30 titles; built-in code is trusted; the fork stays
  maintainable without upstream.
- What breaks: [I] any third-party game in this process is full compromise; any attempt to
  sandbox requires a different execution model, so the fork cannot be the community-game host.
  [E] The product-differentiation finding already rates "28 games" as a count, not quality.
- Alternatives: (a) shrink the fork to a curated provider of a handful of titles and build the
  SDK as a separate-process reference; (b) promote `core/session.py` + `GameBinding` +
  `GameSide` into the SDK and run each new game as its own process using the same code.
- Migration cost: (b) is cheaper than it looks because `GameBinding` already isolates sockets
  from rules; (a) is mostly deletion.
- Nature: **accidental legacy that is quietly becoming the platform**. Decide on purpose.

### 2.13 Browser-first, PWA shell, service worker

- Problem: no app; survive a Wi-Fi hiccup without a browser error page.
- Prototype: **right and restrained**. Network-first, narrow scope, no identity cached, three
  kill switches, tested against real nginx. Appliance: right.
- Assumes: phones return to the same origin; Safari does not evict the worker.
- What breaks: [E] Safari evicts worker storage after about 7 days (noted in ADR 0004). [I] The
  same WebKit policy caps **script-written localStorage at 7 days without interaction** for a
  site not installed to the home screen, and the Avrana "profile" lives in localStorage. The
  server-set HttpOnly cookie is exempt. So the likely failure between two parties a fortnight
  apart on an iPhone is: same device, forgotten name and avatar, prompted to pick one, and a
  new member name. Not fatal, but it contradicts "the party remembers you". Verify on a real
  iPhone (this is documented WebKit behaviour, not tested here).
- [R] Treat the phone as having **no durable storage**; the only durable identity is the
  server-side device record, which can carry the last name and avatar.
- Nature: **deliberate**. Keep exactly as is.

### 2.14 Browser compatibility assumptions

- [E] Known and documented: no element fullscreen, orientation lock or vibration on iPhone;
  Wake Lock from iOS 16.4 (tab) / 18.4 (home-screen); H.264 decode assumed but unrecorded on a
  phone; `location.replace` back-button behaviour untested; background tabs throttle timers.
- [I] The console model depends on three browser behaviours that are weakest on iOS: a long
  poll resuming after wake (handled via `visibilitychange`), `location.replace` from a page
  the user did not interact with (allowed, but history semantics differ), and WebRTC in a tab
  that was backgrounded (stream must be re-negotiated; the arcade already retries).
- [R] The design already says "degrade silently". Make one rule explicit: **no gameplay
  feature may require Wake Lock, fullscreen, vibration, or the phone staying awake**. Every
  deadline is server-side and every reconnection is automatic. BLUFF already behaves this way.

### 2.15 Identity, presence, host authority, session ownership

- [E] Presence as request liveness (not sockets) is the right call for phones. Host as a
  pointer with grace and deterministic succession is right. Participant ids per session are
  right. Versioned host actions are right.
- [I] Weak points: (1) identity is really "a cookie plus a localStorage name" and the name is
  what the party displays; a cleared browser is a new person, a renamed profile is the same
  device; (2) the device store grows one entry per cookieless `join` forever (bounded by use,
  but a hostile phone can mint thousands); (3) one person with two tabs is one member, but one
  person with two browsers is two members and can watch their own hand as a spectator (ADR
  0010 accepts this for friends).
- [R] Freeze the layering and the rule "names never authorise". Leave profile storage,
  pairing and PIN open, but decide **where the durable name lives** (server, keyed by device)
  before building any history or stats.

### 2.16 Party ↔ game session protocol v0 and its trust model

- Problem: let the party admit exactly the right people into a game it did not write, and learn
  honestly when the game ends.
- Prototype: **very good**. Typed tokens with audience, session binding, expiry, nonces,
  loopback-only inbound, vendored single-file reference with cross-repo vectors, 15 s/30 s/60 s
  bounds everywhere, and failure handling that never starts a game on top of one that may be
  running. Appliance: the **shape** is right; three properties need a v1.
- Assumes: symmetric keys are fine because both ends are on one box and trusted; the game
  server is the only holder of its key; loopback means "us"; both ends share one clock.
- What breaks:
  - [E] Tickets are bearer, not single-use and not bound to the connection; a copied ticket
    takes a seat for up to 120 s (accepted in ADR 0006; AVR-52 open).
  - [E] All built-in games share one process and one uid, so "per-game key" isolates nothing
    today; it only starts to mean something when a game is a separate process under its own
    user, which is exactly the community-game case.
  - [I] Loopback-as-trust and `127.0.0.1:8098` break the moment a game runs in a container, a
    network namespace (the `PrivateNetwork=yes` isolation the installation design wants) or
    another host. Unix sockets with `SO_PEERCRED` give the same guarantee and survive all three.
  - [I] `iat`/`exp` in wall-clock seconds on a box with no RTC: both ends share the clock so the
    protocol holds, but a clock jump mid-session (NTP after an offline boot) can expire every
    outstanding ticket and nonce at once. Monotonic clocks cannot be shared across processes,
    so the fix is tolerance and resync, not a different clock (AVR-79, AVR-221).
- Alternatives: asymmetric keys (unnecessary on one box; useful only if tickets must be
  verifiable by code the party does not trust with a shared secret, which is the third-party
  case: a game that holds a symmetric key can mint tickets for its own sessions, which a game
  that holds only the party's public key cannot); unix sockets for party ↔ game; single-use
  tickets with a server-side "spent" set.
- Migration cost: low; the envelope is versioned and the game-side seam is one class.
- Nature: **deliberate**. Freeze the shape (typed, audience-bound, session-bound, expiring,
  never in URLs); keep the key kind and transport reversible.

### 2.17 Localhost server-to-server communication

- [E] Party → game over `http://127.0.0.1:PORT` with signed bodies; game → party on an
  `/internal/` path that nginx never forwards, guarded by remote address and absence of proxy
  headers.
- [I] This is three defences stacked where one strong one would do, and all three assume one
  host. It is fine today. The "works because it is one Pi" risk is that someone later adds a
  Docker network or a second box and the guards silently stop meaning what they mean.
- [R] Move to unix sockets when the first non-builtin game runtime appears; nothing before.

### 2.18 State ownership and consistency

- [E] Party Core owns party, members, host, session, nav. Games own rules, seats, hands, timers.
  Arcade owns slots and the stream. Browser owns the profile name. Six files describe the game
  list (Games registry → `provider/catalog.json` → `contracts/catalogs/lan-games.json` →
  `contracts/games/*.json` + `contracts/appliances/*.json` → `web/party/catalog.json`), and
  `party-core.json` repeats `min_players`, `max_players`, `pregame`, `late_join` by hand.
- [I] Consistency across processes is "last signed message wins" with timeouts; there is no
  reconciliation on restart and no health check that compares what the three processes believe.
  The hidden coupling is in configuration, not code: a contract change that is not copied into
  `party-core.json` is a silent mismatch.
- [R] Generate `party-core.json`'s game block from the contracts and grants (the catalog
  compiler already has everything). Add a startup reconcile: Party Core asks each game server
  "what session do you think is running" and ends anything it does not know.

### 2.19 Reconnect and recovery semantics

- [E] Good: ticket re-fetch yields the same participant; games own grace and autopilot; the
  arcade reserves slots 60 s; the follower waits for `online` before navigating; the arcade
  exits on fatal error and on silent encoder stall so systemd restarts it; Party Core rollback
  on failed launch.
- [I] Gaps: a Party Core restart during a round (above); a Games restart during a round (the
  party still says `active`, tickets are minted, the game refuses them with `session` until
  the host ends); a phone that reloads mid-switch lands by `location`, which is correct.
- Nature: **deliberate**, with the restart cases as known open items (AVR-21, AVR-33).

### 2.20 Offline clock and time

- [E] Pi 4 has no RTC. Tokens, messages, game deadlines (`time.time()` in `core/session.py`
  and `net.py`) and certificate validity all use wall-clock time. Phones compute a server
  clock offset for deadlines (good).
- [I] On an offline cold boot the clock is whatever fake-hwclock saved; a later NTP step can
  jump it by hours. Server-to-server tokens survive because both ends jump together; a game
  deadline set before the jump fires immediately or never; the renewal timer's decisions are
  off by the error.
- [R] Lifecycle timers on `time.monotonic()` with a wall-clock projection only for display
  (AVR-221); a stated clock policy (AVR-79). Consider an RTC on any hardware after the Pi 4.

### 2.21 Game provider / plugin model (contracts, grants, providers)

- Problem: say what a game is, how it runs and what the box allows, without a framework.
- Prototype: **over-specified for two real runtime kinds**, but not harmful. The three-way
  split (capabilities / runtime request / grant) and "the package describes, the appliance
  decides" are the right invariants. Appliance: the invariants are right; the vocabulary will
  change.
- [E] Game Contract v0 has ordered presentations with viewport kinds, per-seat fallbacks,
  requested permissions, package and extension blocks; the capability vocabulary has a dual
  implementation pinned by vectors; the appliance profile lists providers with status; three
  `typing.Protocol` provider boundaries exist of which `RuntimeProvider` and `InputProvider`
  have one live adapter each and `PresentationProvider` is "documented, not built".
- [I] This is the one place the project designed for the fifth game before the second. The cost
  is maintenance of two evaluators and a catalog pipeline, not architecture risk; the schema is
  versioned and the IDs are stable, which is what matters.
- [R] Freeze: stable game IDs, the three-way split, grant-side keys rejected in contracts.
  Keep reversible: everything inside `presentations`, the vocabulary, the appliance-profile
  shape. Do not add fields until a second consumer needs them (the project's own rule).

### 2.22 Future `.avrgame` packaging and SDK

- [E] Nothing built. ~20 Linear backlog items (AVR-37/38/39/41/57–62/72/77/78/135/139/143).
  Two candidate second native games exist as Linear projects (The Team II adaptation, Avrana
  Game) but neither has code.
- [I] The real SDK seed already exists and is not where the docs point: `protocol.py`'s
  `GameSide` (the party contract), `core/session.py` + `core/net.py` (rules/transport split,
  per-viewer `state_for`, deadline generations, bots) and `hubnet.js` (reconnect, ticket, clock
  offset). A package format without a process boundary is a tarball.
- [R] Do not draft `.avrgame` v0 yet. First decide the **execution boundary** for a non-builtin
  game (2.26). Then build The Team II as the first game that runs **outside** the LAN Games
  process using extracted `core/` code. The format falls out of what that game needed.

### 2.23 Browser-native vs server-side game execution

- [E] Every game today is server-authoritative with a thin browser client; BLUFF filters
  private state per viewer on the server; there is no browser-local WASM or lockstep game.
- [I] This is correct for hidden-information party games and for an appliance with a weak SoC
  and strong phones: the box does coordination, phones do rendering. The GAME-PLATFORM
  document's "cheapest viable execution path" scheduler is a good principle and a premature
  mechanism.
- [R] Keep server-authoritative as the only supported model until a game needs otherwise.
  Browser-local execution (emulation on phones) is research (M5), not platform.

### 2.24 Emulator and streaming architecture

- [E] RetroArch (MAME 2010, non-commercial core licence) under Xvfb software GL (~1.2 cores),
  `ximagesrc` at 60 fps, one `v4l2h264enc` encode, one Opus encode, fan-out to per-phone
  `webrtcbin` transports inside the Python process; ~14% of a core per viewer; input via uinput
  pads at 20 Hz snapshots with 300 ms staleness release. The arcade and PS1 cannot run together.
  Latency unmeasured except the PS1 playtest (6 ms median input RTT, p99 1.4 s from Wi-Fi
  stalls).
- Prototype: a genuine achievement and the only working "no TV" stream on a Pi I know of in
  Python. Appliance: **not a product path on this hardware**, and the differentiation finding
  already says emulation should not be the headline: user-supplied ROMs, non-commercial core
  licences, CPU ceiling, one encoder.
- Assumes: one encoder context; H.264 decode in every phone browser; the phone's Wi-Fi link
  behaves.
- What breaks: hardware change (2.2); more than ~5 viewers; any second heavy runtime.
- Alternatives already catalogued (Selkies/pixelflux spike S3, gst-wayland-display S1). All
  keep the same shape: one encode, fan-out, WebRTC.
- [R] Keep the arcade as the owner's power-user feature and the proving ground for the
  `PresentationProvider` seam. Do not let any Party Core concept depend on it. Decide
  "streaming is optional for the product" explicitly so the SoC choice is not hostage to it.
- Nature: **deliberate prototype**, honestly labelled.

### 2.25 WebRTC

- [E] Same-origin WebSocket signalling, host ICE candidates only (no STUN/TURN), PLI → keyframe,
  bounded leaky appsrc queues, per-second client stats.
- [I] WebRTC is the only sub-100 ms video path available to iOS Safari without an app; WebSocket
  + MSE adds a second or more; WebTransport/WebCodecs are not on iOS. The choice is correct and
  stable. GStreamer `webrtcbin` in-process is the fragile part (seen: silent stall, GIL plus
  GStreamer threads), not WebRTC.
- [R] Keep WebRTC. If the stream is ever re-platformed, move the media process out of the
  Python control process (the S3 spike does this).

### 2.26 Security isolation for untrusted games

- [E] None exists. Every game page shares the `party.avrana.net` origin with Party Home; the
  device cookie is HttpOnly and path-scoped so a game page cannot *read* it, but a game page's
  JavaScript can `fetch('/party/api/session/end', …)` **as the viewer**, passing the Origin
  check, because it *is* the origin. It can also read the localStorage profile and `wc-token`.
  GAME-INSTALLATION.md describes the fix (CSP `sandbox`, a platform frame, a separate origin)
  and correctly calls the browser side "the real risk".
- [I] The cheapest durable fix is a **second hostname for game pages** (for example
  `games.party.avrana.net`), added as a SAN on the same certificate and answered by the same
  local DNS: separate cookie jar, separate localStorage, exact Origin checks on Party and admin
  endpoints reject it, and game pages need no CSP sandbox gymnastics. This is cheap now and
  expensive after profiles, stats and chat bind to the single origin. It also conflicts with
  "one canonical origin, or one phone becomes two presences"; the resolution is that game pages
  never *are* a presence: they hold a ticket, not the device cookie, which is already the
  protocol's intent.
- [R] Decide the origin strategy for untrusted pages before the second native game. Server
  side, the systemd template unit per game with `DynamicUser`, `PrivateNetwork` and a unix
  socket is the right design and is already written down.

### 2.27 Persistence and reboot continuity

- [E] Party: memory. Games: memory (sessions, chat) plus avatar/media files. Arcade: memory.
  Device store: JSON, atomic replace. No SQLite anywhere yet. Under-voltage resets were the
  dominant failure before 2026-09-24.
- [I] The decision "does a party survive a reboot" (open since ADR 0003) is the one open
  decision with the highest ratio of user-visible value to engineering cost. Option B (snapshot
  on change, resume if fresh) costs one file write per commit.
- [R] Decide B now. Keep game session state ephemeral (the game owns its own recovery).

### 2.28 Observability, operations, update and recovery

- [E] journald bounds, logrotate rules, Beszel agent, a throttle sampler, `/stats` on the
  arcade, `state` on Party Core, structured findings for every deploy. Deploys are owner-run
  sudo scripts in a documented order; rollback is per component; the certificate renewal timer
  is not enabled.
- [I] Proportionate for one owner; not a product. There is no health endpoint that says "the
  party is ready" across all three services, no appliance-level self-test, no image, no A/B,
  and the system interpreter and an "old venv" are both release dependencies.
- [R] Enable renewal now (AVR-31). For a field-test unit: image-based install with A/B
  (Rugix spike), one `avrana-health` summary, and a "Party Ready" page (AVR-86) that checks
  AP, DNS, cert runway, services, clock and disk.

### 2.29 GitHub / Linear / Graphify / docs-manifest workflow

- [E] Two private repos with cross-repo vectors and drift tests; 11 ADRs in ten days; a docs
  manifest with classes and authority scopes; a repo-check script; Graphify graphs, receipts
  and a PreToolUse reminder; Linear with 222 issues and milestones M0–M10; every document
  carries a "reconciled 2026-10-01" banner and status prose.
- [I] This is a governance system sized for a team of agents, which is what it is for. The
  authority table in AGENTS.md is genuinely good. The costs: documents are long and
  repetitive because status reconciliation is written into prose rather than one table;
  Graphify adds a tool, a venv and receipts for a repo of ~14k lines where grep is instant (it
  was not even installed in the Python that ran this review); the manifest and byte-identical
  nginx copy are CI rules that protect against mistakes nobody would otherwise make.
- [R] Keep ADRs, Linear-as-queue, SYSTEM-as-deployed-truth and dated findings. Make Graphify
  optional and stop treating it as a required pre-search step. Move status banners into
  SYSTEM and the manifest, and let design docs describe design.

### 2.30 Extensibility toward community games

- [I] The invariants are in place (IDs, grants, tiers, "no in-process untrusted code"). The
  mechanisms that would make it real are all missing and all depend on the two decisions above
  (execution boundary, origin). The roadmap's own rule applies: build the second game first.

### 2.31 Hardware scalability and commercial constraints

- [I] Nothing in Party Core, the protocol, the shell or the Games server constrains hardware.
  Everything in the arcade/PS1 path does. The AP radio and power design constrain party size and
  portability more than any software choice. Licensing (MAME core, GPL RetroArch as a separate
  process, MIT LAN Games) is handled correctly for a prototype; the non-commercial core cannot
  ship.

---

## 3. Verdicts

### 3.1 Strong fits (keep, and build on)

- One appliance, one party; Party owns identity/presence/host/navigation; games own rules.
- Party Core as a pure, clock-injected state machine with versioned host actions.
- Presence as request liveness; host grace and deterministic succession; participant ids per
  session.
- `avrana.party-session/v0` envelope shape: typed, audience-bound, session-bound, expiring,
  nonce-guarded, never in URLs; the vendored single-file game side with cross-repo vectors.
- Server-authoritative games with per-viewer filtering; BLUFF's masking discipline.
- The console model: one `location`, only the host moves it, phones follow with
  `location.replace`.
- No captive popup; Apple probe answered locally; HTTP port 80 kept stable.
- nginx as the one front door; strict CSP on the shell; network-first service worker with
  kill switches; "degrade silently" for every secure-context feature.
- WebRTC for the stream; one encode fanned out; the Party-managed runtime lifecycle.
- Three-way manifest/runtime/grant split with grant-side keys rejected in contracts.
- The authority table in AGENTS.md; ADRs; Linear as the only queue; dated findings.

### 3.2 Acceptable prototype compromises (fine now, replace with evidence)

- Raspberry Pi 4, SD card, no RTC, no enclosure.
- Internal Broadcom radio as the AP; NetworkManager shared mode; NAT to the home LAN.
- Python stdlib `ThreadingHTTPServer` and the long poll for Party Core.
- Loopback TCP with proxy-header refusal for server-to-server; symmetric per-game keys.
- Bearer, non-single-use 120 s tickets.
- Memory-only party; `devices.json`; no database.
- Profile = localStorage name + avatar.
- Run-from-git-checkout deployment with owner sudo scripts; system Python; the Games venv.
- The LAN Games fork as the only game host; `core/session.py` as the de facto SDK.
- GStreamer `webrtcbin` inside the Python control process; Xvfb software GL.
- Dual-language capability evaluator; the catalog pipeline across six files.
- Graphify, the docs manifest and the duplicated nginx file.

### 3.3 Should probably be replaced or changed before productization

1. **HTTPS as a hard dependency of the Party layer** (the `Secure`-only cookie and HTTPS-only
   `/party/`): make Party Core reachable on the HTTP origin too, or accept and document that an
   expired certificate ends the product.
2. **Certificate lifecycle**: manual issuance, disabled renewal, a zone-wide token on the box,
   one hostname. A fleet needs per-device identity and certificates issued by something Avrana
   runs, plus a courier path.
3. **One Unix user for all services and loopback-as-trust**: per-service users, credentials
   directories, unix sockets.
4. **The LAN Games monolith as the game host**: shrink it to a curated provider or extract its
   core as the SDK and run new games as separate processes. Not both by accident.
5. **Single origin for trusted shell and game pages**: a second hostname (SAN) for game pages.
6. **Memory-only party**: snapshot and resume.
7. **Wall-clock lifecycle timers** on a box with no RTC.
8. **Checkout-based deployment**: image with A/B rollback.
9. **Pi 4-specific streaming** (`v4l2h264enc`, Xvfb): keep behind `PresentationProvider`, and
   decide whether central streaming is a product feature at all.
10. **Six places that describe the game list**, one of them hand-maintained
    (`party-core.json`).

### 3.4 Decisions to freeze now

- The identity layering and the rule that identifiers authorise nothing and names never do
  (ADR 0003).
- One party per appliance; host-authoritative location; presence is automatic with a profile;
  no Join/Leave ceremony (ADR 0011).
- Party owns membership, host, session, navigation; games own rules, seats, timers, results
  (ADR 0006 D1).
- The session-protocol shape: typed tokens, audience and session binding, expiry, nonces,
  tickets only in the first WebSocket message, never in URLs, `ended` only from the game server.
- Games receive a participant id and a per-session secret, never a device token or member id.
- Capabilities / runtime request / grant are separate; the appliance decides; stable game IDs.
- Port 80 captive behaviour; no HSTS; no private CA on phones; no app required; no TV required.
- Server-authoritative games with per-viewer filtering as the only supported model for
  hidden-information games.
- Phones have no durable storage: anything that must be remembered lives on the box.

### 3.5 Decisions to keep deliberately reversible

- Party Core's transport (long poll vs SSE vs WebSocket) and server library.
- Symmetric HMAC vs asymmetric or socket-credential verification; loopback TCP vs unix sockets.
- Ticket lifetime and single-use semantics.
- The hostname and certificate strategy (so long as 3.3 item 1 is decided).
- The LAN Games fork's role.
- Everything inside Game Contract `presentations`, the capability vocabulary and the appliance
  profile shape.
- GStreamer/`v4l2h264enc`/Xvfb; the arcade's control port.
- Tailwind/daisyUI, DiceBear, Lucide (presentation only).
- Graphify, the docs manifest, repo-check scope.
- Party persistence format (JSON snapshot now; SQLite if history ever exists).

### 3.6 The ten most consequential assumptions

1. A publicly trusted certificate for a private address, resolved by the party's own DNS,
   works on guests' phones (no Private DNS, Private Relay, VPN, DoH) and is renewed within a
   shrinking window. [E] partly verified on one phone at home; [I] fails in several common
   configurations.
2. The Party layer may be HTTPS-only. [E] It is; [I] this makes the whole product expire with
   the certificate.
3. The phone keeps the device cookie and the localStorage profile between parties. [I] The
   cookie survives; the profile likely does not on iOS after 7 idle days.
4. The Pi 4's internal radio carries a party. [E] Reported ~8 stations; stalls observed; never
   measured with four active phones.
5. Loopback and a shared user are a trust boundary. [E] They are the only boundary; [I] it
   stops meaning anything with containers or a second host.
6. A restart may start a new party. [E] By design; [I] power loss is the most likely real
   failure and it loses the evening's state.
7. Wall-clock time is trustworthy for tokens, deadlines and renewal on a box with no RTC.
8. One hardware encoder, one emulator at a time, software GL headroom, H.264 decode on every
   phone. [E] Measured for 1–5 viewers; [I] not portable past the Pi 4.
9. Built-in games are trusted and may share a process, an origin and the user's identity
   context with the shell. [E] True today; [I] blocks any third-party game.
10. Auto-navigation, long-poll wake and WebRTC re-negotiation behave on real iOS Safari and
    Android Chrome through sleep, lock and back. [E] Unverified (AVR-212, AVR-27, AVR-11).

### 3.7 The ten most important future architecture decisions

1. Does the Party survive the loss of Full Mode (HTTP origin identity), and how?
2. How does a fleet get device identity and certificates (per-device subdomain, Avrana-run
   ACME/DNS, courier), and does Avrana accept running that service?
3. Party persistence across restart and reboot (option B).
4. The execution boundary for non-builtin games: separate process + unix socket + per-game user.
5. The origin strategy for game pages versus the shell (second hostname).
6. The hardware platform after the Pi 4, and whether central streaming is a product feature.
7. The LAN Games fork: curated provider, SDK donor, or both explicitly.
8. Party Core's transport and the convergence of three Python stacks into one.
9. Update and recovery model: image, A/B, signed releases.
10. The AP radio and power architecture: dedicated radio, dual band, regulatory domain, battery.

### 3.8 Five areas currently overengineered

1. **Capability engine and Game Contract v0 breadth**: a dual-language evaluator with shared
   vectors, ordered presentations, viewport kinds, package and extension blocks, for two runtime
   kinds and one presentation that is "documented, not built".
2. **Documentation governance**: manifest classes and authority scopes, repo-check, reconciled
   status prose in every file, Graphify receipts and a pre-search hook, for a 14k-line repo with
   one owner.
3. **Personal Viewports metadata and geometry** before a split-screen title exists; the finding
   itself says stage C needs a different game.
4. **Layered communication design** (four layers, policies, channels) over a donor chat that is
   one global room with a client-declared name and an unauthenticated clear.
5. **Deployment tooling spread**: root installers, `ops/`, `deploy/`, `telemetry/`, `arcade/`
   scripts and a duplicated nginx file, each with its own runbook, for three services.

### 3.9 Five areas currently underengineered

1. **Party continuity**: no snapshot, no restart reconciliation between the three processes.
2. **Party Core's service layer**: unbounded long-poll threads, no request timeouts of its own,
   full-view resend on every version bump, party-wide `if_version`.
3. **Durable identity**: the display identity lives in phone storage that iOS may evict; the
   device store grows unbounded; no server-side name/avatar.
4. **HTTPS lifecycle**: renewal off, no runway tracking, no HTTP path for the Party, one
   hostname, zone-wide token planned.
5. **Process isolation and health**: one user for every key and secret, loopback as trust, no
   cross-service health or self-test, no image or rollback.

### 3.10 The most dangerous "works because it is one Pi" assumptions

- `127.0.0.1` means "us": the `/internal/` route, the arcade's 8098 control port, the Games
  launch/end routes and `party_url()` all reject anything but loopback. Fine until a container,
  a network namespace or a second box.
- All services share uid `cody`, so "0600 key readable by two services" is really "readable
  by everything".
- Both protocol ends share one clock; `iat`/`exp` tolerance is 5 s.
- `10.42.0.1` is hard-coded in the arcade (`PARTY_ADDRESS`), QR codes, docs and tests.
- nginx forwards `X-Forwarded-For` on some locations and not others, and the services depend
  on that difference.
- One encoder, one emulator, one Xvfb: "one Party activity" (ADR 0008) is partly a resource
  rule dressed as a product rule, which is fine, but it hides that the product rule would
  survive better hardware while the resource rule would relax.
- The Games server listens on all interfaces on 8096; only the absence of a firewall rule and
  the assumption that nginx is the front door keep it from being a second origin.
- Production is a git checkout under `/home/cody`, and services read `index.html` from it on
  every request, so a `git pull` is a partial deploy.

---

## 4. Recommended target architectures

### 4.1 Current prototype (now to the first measured party night)

Change nothing structural. Close the time bombs and prove the thesis:

- Enable certificate renewal with a narrowly delegated `_acme-challenge` zone (AVR-31; the
  substrate matrix already warns against a zone-wide token). Decide before 2026-11-25.
- Decide and implement party snapshot/resume (option B) and a startup reconcile with game
  servers.
- Move lifecycle timers to monotonic time (AVR-221); write the clock policy (AVR-79).
- Apply the proposed NetworkManager boot determinism and run the AP power-save A/B.
- Run the Tier 3 proofs that every ADR defers: AVR-212, AVR-12, AVR-27, AVR-10, AVR-11. Record
  a real `/party/diag/` report from an iPhone and an Android phone. Test Private DNS and
  Private Relay against `party.avrana.net`. Test the 7-day iOS storage question.
- Do not start `.avrgame`, the capability scheduler, Companion or the viewport metadata.
- Delete the duplicate nginx file; generate `party-core.json`'s game block.

### 4.2 Field-test appliance (a handful of units in other people's hands)

- **Hardware**: a board with a hardware encoder *or* a decision that streaming is optional; a
  dedicated, separately powered AP radio (dual band, country code from settings); RTC; a
  battery design measured to 5.1 V/3 A under load; an enclosure.
- **OS and deployment**: read-only root image with A/B rollback (Rugix spike), signed releases,
  one install path, one `avrana-health` and a "Party Ready" page (AVR-86, AVR-74).
- **Services**: one user per service, `CredentialsDirectory` for keys, unix sockets between
  Party Core and game servers; Party Core's service layer on one asyncio stack with bounded
  concurrency, the pure core unchanged; Games server bound to loopback only.
- **Identity and trust**: Party Core available on the HTTP origin as a degraded but complete
  mode (or the explicit decision not to); server-side name and avatar per device; certificate
  runway tracked and shown; renewal automatic whenever an uplink appears.
- **Games**: the LAN Games fork curated to a shelf of titles the owner would defend (AVR-155);
  one second native game built as a separate process from extracted `core/` code, admitted by
  the existing protocol over a unix socket, with its pages on a second hostname. That is the
  SDK v0, by construction rather than specification.
- **Network**: hostapd + Avrana-owned dnsmasq, client isolation on, offline by default with an
  explicit "share internet" setting, the four captive probes answered as today.
- **Observability**: journald bounds as now, plus a support bundle and a per-party summary
  (joins, moves, failures) kept locally.

### 4.3 Eventual consumer product

- **Identity and trust**: a device keypair provisioned at manufacture; per-device hostname and
  certificate issued by an Avrana service when online or via the companion courier; the
  companion app optional and never required for play; HTTP always a complete play path, HTTPS
  the preferred one. The box, not the phone, remembers people.
- **Execution**: every non-first-party game is a sandboxed process (own user, no network, unix
  socket) with pages on an isolated origin; packages signed (TUF-style metadata, offline-
  verifiable), installed and rolled back by the appliance; results and stats carry provenance
  and trust tier. First-party games may share a process only if they are built and released
  with the platform.
- **Party Core**: the same state machine, persisted, on a robust async runtime (Python is
  fine if the service layer is rewritten; a compiled runtime is justified only if the
  appliance SoC is weak), with SSE or WebSocket push and an event/result sink.
- **Media**: central streaming only where the hardware has an encoder; otherwise phones render.
  If kept, the media process is separate from control and speaks the same provider contract.
- **Operations**: OTA images with rollback and consent for product-changing updates; automatic
  security restoration (clock, certificate) without prompts; a self-test on boot; opt-in
  telemetry.
- **Hardware**: a radio chosen for station count and latency under load; RTC; battery with
  measured runtime; regulatory configuration; a small status display for the join codes.

---

## 5. What this review did not do

It did not run anything on the Pi, a phone or the AP. It did not benchmark alternatives. It
did not re-verify third-party facts (Pi 5 encoder, WebKit storage eviction, Let's Encrypt
lifetimes) beyond what the repository already cites; each is marked [I] and should be checked
before it drives a purchase or an ADR. It did not review game rules or UI quality. It did not
read the Games fork beyond `server.py`, `core/net.py`, `core/party_session.py`, `hubnet.js` and
`avrana-integration.js`.
