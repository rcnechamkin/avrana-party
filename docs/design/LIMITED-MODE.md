# Limited Mode mechanisms (AVR-225)

Status: **ACCEPTED mechanisms (owner, 2026-10-03). Steps 1 and 2 of §5 are in source; nothing is deployed.** The direction is
accepted in [ADR 0012](../adr/0012-limited-mode-party-survives-https-loss.md), whose amendment of
2026-10-03 records the owner's decisions D1 to D6 (§4). The text below is the design as proposed
and accepted; "As built" notes say where steps 1 and 2 differ. Linear: AVR-225. Related: [ADR 0013](../adr/0013-party-and-game-browser-origins.md)
and [BROWSER-ORIGINS](BROWSER-ORIGINS.md) (two origins), [FULL-MODE](FULL-MODE.md) (the deployed
shell), [OFFLINE-TRUST-AND-RECOVERY](../OFFLINE-TRUST-AND-RECOVERY.md).

Tags: **[E]** read in source or config on `main` at `b4c470d`; **[I]** inference; **[R]**
recommendation.

## 1. What is true today

- [E] The port-80 nginx server answers captive probes, proxies `/arcade/` to the arcade and
  proxies everything else to the LAN Games hub. It has no `/party/` and no `/party/api/`
  (`avrana-party.nginx`). Only the 443 server for `party.avrana.net` serves them.
- [E] Party Core issues one credential: `avrana_device; Path=/party/; HttpOnly; Secure;
  SameSite=Lax`, about 400 days, stored as a SHA-256 in `devices.json` (`identity.py`).
- [E] Party Core accepts a request only for a configured `Host`, and a POST only from a
  configured `Origin` (`service.py`). Production lists one of each.
- [E] nginx already passes `X-Forwarded-Proto $scheme` to Party Core, which does not read it.
- [E] Game pages and the arcade page load `/party/lib/party-follow.js` only when
  `window.isSecureContext` is true (`arcade/index.html`, Games `avrana-integration.js`).
- [E] The shell registers its service worker only in a secure context (`web/party/lib/shell.js`),
  and Wake Lock is probed, not assumed (`keep-awake.js`).
- [E] The Party lives in memory. A Party Core restart forgets every member (`core.py`).
- [E] Party DNS answers `party.avrana.net` locally (`avrana-captive.conf`). The appliance is also
  reachable as `party.local` (mDNS) and `10.42.0.1`.

## 2. How a phone ends up without trusted HTTPS

| Cause | `https://party.avrana.net` | `http://party.avrana.net` | `http://10.42.0.1` |
|---|---|---|---|
| Certificate expired or not yet valid (no RTC, wrong clock) | browser warning page | works | works |
| Phone uses Private DNS, a VPN or iCloud Private Relay | name does not resolve to the box | does not resolve | works |
| Guest typed the name without `https://` | never tried | works | works |
| Old browser cannot build the chain | warning page | works | works |

[I] Two consequences follow. A warning page is not ours, so a phone can never be *redirected* out
of broken HTTPS; it must *start* somewhere that works. And only the IP literal survives every
row, because the DNS-override row breaks every name.

## 3. Proposal

### 3.1 One HTTP doorway that every phone starts from

[R] The port-80 default server serves a small static doorway at `/`. It does one thing: it tries
`fetch('https://party.avrana.net/party/api/origin.json', {mode: 'no-cors'})`. That request
succeeds only when DNS, the certificate and the clock are all fine. On success the doorway
navigates to Full Mode. On failure, or after a short timeout, it navigates to Limited Mode. The
QR code on the box and the captive landing both point at the doorway.

This answers two of ADR 0012's open items: the QR code carries the doorway, and `/` stops being
the LAN Games hub (already implied by ADR 0014).

**As built (step 2).** The page is `web/party/doorway/index.html` with `lib/doorway.js`. Its two
destinations are attributes of the page itself (`https://party.avrana.net/party/` and
`http://10.42.0.1/party/`); it takes nothing from its address or query. The test request is
`no-cors`, without credentials, and gives up after 3.5 seconds. Step 3 must serve the page with
its own `Content-Security-Policy`: the shell's `connect-src 'self'` would block the one request it
makes, so that location needs `connect-src 'self' https://party.avrana.net`. It is not in the
offline copy. The Limited Mode banner links back to it ("Check for the full version").

### 3.2 One canonical Limited Mode origin

Every distinct host name is a distinct origin with its own cookies, so three HTTP names would make
one phone three devices. [R] Pick one canonical Limited Mode origin and make the other HTTP names
redirect to it. Two candidates:

- `http://10.42.0.1` survives every cause in §2. It is ugly and it ties the origin to the AP
  subnet, which is already fixed in the appliance.
- `http://party.avrana.net` reads well and keeps one host name across modes, but fails for the
  DNS-override row, which is one of the triggers ADR 0012 names.

Recommendation: the IP literal. **Decision D1.**

### 3.3 A separate, short-lived credential

[R] A second cookie, never the first one with a flag removed:

| | Full Mode | Limited Mode |
|---|---|---|
| Name | `avrana_device` | `avrana_limited` |
| Flags | `HttpOnly; Secure; SameSite=Lax; Path=/party/` | `HttpOnly; SameSite=Lax; Path=/party/` |
| Lifetime | about 400 days | the party: 12 hours, and it dies with a Party Core restart |
| Store | `devices.json`, hashed | memory only, a separate table |
| Accepted on | the HTTPS listener only | the HTTP listener only |

[I] Keeping the Limited store in memory is a feature. Anything sent over plain HTTP on a
shared-password Wi-Fi can be read by another guest, so the credential should be worthless the next
day. Each store only ever resolves its own cookie, so a Limited token presented as `avrana_device`
is unknown, and the reverse.

**As built (step 1).** As the table says, except that since ADR 0013 the Full Mode cookie is
`__Host-avrana_device; Path=/`. `avrana_limited` keeps `Path=/party/`, so it is sent to the Party
API and never to a game server on the same origin. `identity.LimitedStore` holds a hash of each
token with its expiry; a restart or 12 hours ends it.

### 3.4 How Party Core knows the mode

Two options:

- **A second loopback listener.** Party Core listens on `127.0.0.1:8191` (Full) and
  `127.0.0.1:8192` (Limited), sharing one `PartyService`. The port-80 nginx server proxies to the
  second. The mode is a property of the socket and cannot be forged by a header.
- **`X-Forwarded-Proto`.** One listener, mode read from the header nginx already sends. Smaller
  change, but it makes a proxy header load-bearing in a service whose internal routes
  deliberately refuse proxy headers.

Recommendation: the second listener. **Decision D2.**

**As built (step 1).** `party-core.json` may carry
`"limited": {"hosts": ["10.42.0.1"], "origins": ["http://10.42.0.1"], "port": 8192}`. Absent (as in
production), there is no second listener. An origin that is not `http://`, or one shared with
Full Mode, is refused at start. The Limited listener serves no game-to-party route and no bridge
origin (D5). Every view says `"mode": "full"` or `"mode": "limited"`.

### 3.5 Identity and continuity

The server cannot prove that an HTTP visitor is the same phone as an HTTPS member, because the
`Secure` cookie is never sent over HTTP. Four models:

| Model | Same member after a mode switch? | Cost |
|---|---|---|
| **A. New device.** A Limited visitor joins as a new member; the UI says so. | No. The old member goes away after the usual 45 s. | None. This is the floor ADR 0012 already requires. |
| **B. Twin cookie.** In Full Mode the server also sets `avrana_limited`, mapped to the same device. | Yes, silently. | The twin is sent in clear the first time the phone makes any plain-HTTP request to that host while still in Full Mode. It turns a possible exposure into a routine one. Only works if both modes share a host name, which D1 argues against. |
| **C. Host-approved reclaim.** A Limited member taps "That's me" on an away member; the host confirms on their own phone. | Yes, with one tap from the host. | A new Party Core verb and a small UI. The host is a human check that the server cannot fake. |
| **D. Pairing code.** A Full Mode phone shows a code that the Limited phone types. | Yes. | Useless for the common case: when the certificate has expired, no phone is in Full Mode. |

Recommendation: ship **A** first, add **C** when real parties show that people care about keeping
a seat across the switch, reject **B** and **D**. **Decision D3.**

[I] Model A is less harsh than it sounds, because a certificate expiry hits every phone at once.
The Party itself is already memory-only, so the realistic event is "everyone joins again by name",
which takes seconds.

### 3.6 Authority in Limited Mode

- [R] Host verbs work in Limited Mode. ADR 0012 decision 2 requires it.
- [R] No admin surface, no PIN entry and no profile claiming over HTTP. None exists today, so this
  is a rule for later work.
- [I] A guest on the Wi-Fi can read a Limited cookie off the air and act as that member,
  including a host. PARTY-PLATFORM §13 already accepts this for plain HTTP among friends.
- A party can be mixed: some phones in Full Mode, some in Limited. [R] Show the mode beside each
  member, and when the host role moves by succession prefer a Full Mode member who is here. Never
  move it from a Limited host who is here. **Decision D4.**

### 3.7 What degrades, per seat

| Capability | Limited Mode |
|---|---|
| Join, presence, host, navigation, setup, launch | work |
| BLUFF and other `browser_native` games over `ws://` | work |
| Arcade stream (WebRTC receive) | [I] should work: receiving needs no secure context. Unverified on phones |
| Screen Wake Lock | unavailable; say "keep your screen on" |
| Service worker and the offline copy | unavailable |
| A game whose contract requires `secure_context` | that seat watches or is told why |
| Padlock and "connection is secure" | absent; the shell says the connection is not private |

**As built (step 2).** The Capability Engine already decides this per seat: on a plain-HTTP
origin `secure_context`, `wake_lock` and `service_worker` are "no". The banner lists what is
missing on this phone and names the installed games it cannot play. In a round's setup, a phone
that cannot play the game has Play disabled and the reason shown, and may still choose Watch.
Not yet: a game page in Limited Mode does not follow the party, because game pages and the arcade
page load the follower only in a secure context (a paired change with Games).

### 3.8 The second origin in Limited Mode

ADR 0013 wants game pages on their own origin. Over HTTP with an IP literal there are no
subdomains, and a second port is not a cookie boundary. [R] In Limited Mode, first-party games
stay same-origin behind path scoping, as they are today, and any future untrusted tier is
unavailable in Limited Mode. Say so in the shell. **Decision D5.**

### 3.9 What the shell shows

One banner, plain words: the connection is not private, what is missing on this phone, and that
the owner restores it by renewing the certificate. It never imitates a padlock and never hides a
browser warning.

## 4. Decisions (accepted by the owner, 2026-10-03)

| # | Decision | Accepted |
|---|---|---|
| D1 | Canonical Limited Mode origin | `http://10.42.0.1`; other HTTP names redirect to it |
| D2 | How Party Core learns the mode | a second loopback listener |
| D3 | Continuity across a mode switch | new device now (A); host-approved reclaim later (C); never a twin cookie |
| D4 | Mixed-mode parties | allowed; mode shown per member; succession prefers Full Mode |
| D5 | Game origin in Limited Mode | same origin for first-party games; no untrusted tier |
| D6 | Does `/` become the doorway now, or only when LAN Games retires (AVR-222, AVR-228)? | with the Limited Mode rollout |

## 5. Rollout

Steps 1 and 2 are in source (AVR-225). Steps 3 and 4 are the owner's and have not happened.

1. Party Core: the Limited store, cookie and listener, behind config that production does not set.
   Unit and service tests. No deployment effect. **Done in source**
   (`tests/unit/test_party_limited_mode.py`).
2. Shell: mode in the view, the banner, per-seat degradation, the doorway page. Tier 1 and 2 tests
   with a simulated second scheme. **Done in source** (`tests/offline/limited-mode.test.mjs`;
   `tests/offline/limited.spec.ts`, Chromium, where `limited.avrana.test` is a real non-secure
   origin served by the dev server's Limited listener).
3. nginx port-80 `/party/` and `/party/api/` blocks plus the doorway. Owner-approved live change;
   both tracked site files stay byte-identical.
4. Tier 3 on real phones: an expired certificate, a wrong clock, Private DNS on Android, iCloud
   Private Relay on iOS.

AVR-31 (certificate renewal) stays required regardless. Limited Mode is the recovery path, not a
reason to let the certificate lapse.

## 6. Not proposed

Dropping `Secure` from `avrana_device`; a private CA; an app as the recovery route; persisting
Limited credentials; any change to the session protocol (tickets and keys are unaffected by the
browser scheme).
