# Onboarding ("tap to join") and connectivity

Status: **research and recommendations (2026-09-24). No networking has been changed.** Every item
that would change nginx, dnsmasq, NetworkManager, Avahi, connectivity-check handling or Wi-Fi
security needs the owner's explicit approval (ROADMAP N3). Platform facts are from web sources
listed at the end and are version-dependent; the test list below is how to confirm them.

## The goal and the principles

```
power on Avrana → tap / scan → join the Avrana Wi-Fi → open the REAL browser → join the party
```

- **No-app baseline:** Wi-Fi + a normal web browser. An optional app may later improve onboarding
  or hardware integration; it must never be required (guests, strangers, travel, demos).
- **The captive portal is optional glue.** The real product is a normal browser at the party
  address. Never select a profile, trust a device or run a game inside a captive-portal
  mini-browser (it has its own cookie jar and closes itself).

## What is true today (read from the repo)

- **iPhones join silently** (observed only with home internet behind the Pi; offline it is
  *expected*, not tested): nginx answers Apple's connectivity probe with Apple's "Success" page,
  so iOS shows no captive popup; `portal/index.html` is no longer served anywhere.
- **Android gets a 404** (observed 2026-09-24): its probe hostnames resolve to the Pi and
  `/generate_204` falls through to LAN Games, which answers `404 {"detail":"Not Found"}` — neither
  success nor a login page, so **no sign-in popup is expected**. Today Android's parallel HTTPS probe
  still reaches Google through the Pi's NAT; truly offline, expect "Connected, no internet". Windows
  and Firefox probes also get 404. Full audit, and a reversible offline test mode:
  `docs/findings/2026-09-24-party-network-and-offline-mode.md`.
- **The party Wi-Fi is WPA2-Personal** on 5 GHz channel 149 (so the join QR is `WIFI:T:WPA;…`).
- **Test blind spots:** the Playwright tests use `party.avrana`, which resolves only through this
  laptop's hosts file; and the Pi currently shares its home-network internet with Avrana clients,
  so **every phone test so far had internet behind it**. Onboarding must be judged truly offline.

## Mechanisms by platform

| Mechanism | iOS | Android | App needed? | Reliability |
|---|---|---|---|---|
| Wi-Fi QR (`WIFI:T:WPA;S:…;P:…;;`) | Camera (iOS 11+) shows "Join" | Android 10+ Wi-Fi settings scanner; many cameras | no | high |
| Link QR (`http://10.42.0.1/`) | Camera opens the browser | Camera/Lens opens the browser | no | high, after joining |
| One QR that joins Wi-Fi **and** opens a page | not possible | not possible | — | — |
| NFC tag with a URL | iPhone XS+, URL must be the first record, phone unlocked | opens the browser | no | medium |
| NFC tag with Wi-Fi credentials (`application/vnd.wfa.wsc`) | ignored without an app | native "Connect?" prompt (verify on current phones) | iOS: yes | Android: medium |
| Captive-portal popup | mini-browser, own cookies; "Use Without Internet"; no reliable hand-off to Safari | "Sign in" notification, WebView | no | only good for pointing people elsewhere |
| Standard captive-portal API (DHCP option 114, RFC 8910) | iOS 14+ | Android 11+ | — | needs HTTPS with a valid certificate: not usable offline |
| Typing `party.local` (mDNS) | Safari: yes | since a late-2021 system update on many Android 12+ phones; older phones fail | no | iOS high, Android medium |
| Typing `http://10.42.0.1` | yes | yes (see mobile-data caveat) | no | high |
| A name answered by the Pi's own DNS | probably | fails with strict Private DNS or a VPN | no | medium; a live change |
| Web NFC / Web Bluetooth | not available | Chrome only, HTTPS only | — | unusable over plain HTTP |
| Native app | can join Wi-Fi programmatically; can read NFC Wi-Fi tags | can join Wi-Fi programmatically | yes | high, but must be installed |

## Recommended no-app flow

1. The device (printed card; the TV or a small e-ink screen when present) shows **two** codes:
   **① Join Wi-Fi** and **② Open the party**; plus two NFC spots (an Android-only Wi-Fi tag and a
   URL tag that works on both).
2. Scan ① → Join. Fallbacks: Android's Wi-Fi-settings QR icon, the Android NFC spot, or the name and
   password printed on the card.
3. If Android asks "No internet — stay connected?", tap **Yes** (the card says so).
4. Scan ② or tap the URL tag: it opens the real browser at `http://10.42.0.1/`, which works
   whatever the phone's name resolution does. Fallback: type `party.local` (Safari) or
   `http://10.42.0.1` anywhere.
5. Troubleshooting lines on the card: confirm you're on "Avrana Party"; pause any VPN; on Android,
   turn off mobile data; in Chrome/Firefox on iPhone, allow "Local Network".

## The party address (proposal only; nothing changed)

- **One canonical origin, or one phone becomes two presences.** A QR code that carries the IP plus
  people typing `party.local` would give each phone two cookie jars (two presences, two seats, two
  votes) — see `PARTY-PLATFORM.md` §4.
- **Leading option: `http://10.42.0.1` is the canonical origin** (it always resolves; QR codes and
  NFC tags carry it), and `party.local` **redirects** to it for people who type the name. This keeps
  one cookie jar per phone without depending on mDNS. (Still OPEN; the alternative — `party.local`
  canonical, with the Pi's DNS also answering it for Androids without mDNS — needs Android
  verification first and a live DNS change.)
- iPhones only use mDNS for `.local`, so having the Pi's DNS also answer `party.local` shouldn't
  conflict in practice, though it bends the standard.
- Backup: `party.home.arpa` (RFC 8375's home-network name) works only via the Pi's DNS and is long.
- Avoid `avrana.party` (`.party` is a public TLD), `party.avrana` (phones can't resolve it; browsers
  treat it as a search), and `party.internal` (reserved since 2024; address-bar handling untested).
- On an iPhone that marks the Wi-Fi as "no internet", `.local` and the raw IP should keep working; a
  name answered only by the Pi's DNS might be looked up over mobile data and fail — test it.

## What only an app can do

Join the Wi-Fi programmatically and read NFC Wi-Fi tags on iPhone; keep the phone on a network with
no internet while mobile data carries other traffic; reconnect in the background; BLE proximity
"tap" (no Web Bluetooth on iOS). Costs: app-store accounts, special Apple entitlements, iOS's
local-network prompt, and an install that needs internet. BLE is deferred until it is genuinely
useful.

## What depends on the OS

Connectivity-check handling and "stay connected?" prompts; automatic switching to mobile data
(iPhone Wi-Fi Assist, Android "switch to mobile data", Samsung Intelligent Wi-Fi); whether Android
routes traffic over mobile data until the prompt is answered; `.local` on Android; Private DNS,
iCloud Private Relay, VPNs, and the local-network permission for non-Safari browsers on iPhone; the
NFC first-record rule; which browser the camera opens.

## Connectivity model: the party network vs optional upstream internet

```
            ┌───────────────────────── Party LAN (always) ──────────────────────────┐
 phones ──▶ │ Avrana Wi-Fi AP · DHCP · DNS · nginx · party service · games           │
            └───────────────────────────────────────────────────────────────────────┘
                              │  optional upstream (later; admin setting)
                              ▼
                  Ethernet · Wi-Fi client uplink · phone tether · or nothing
```

- **Offline-first:** the party depends only on the party LAN. Everything must work with no upstream.
- **Optional upstream (future, not configured):** with real internet behind Avrana, connectivity
  checks pass honestly (no prompts, phones keep internet, fewer auto-switches) — onboarding gets
  easier. The party must still survive the upstream dropping mid-game (phones may switch to mobile
  data; games must reconnect). Whether guests get internet through Avrana is an admin setting.
- Today the Pi *does* share its home connection with Avrana clients (NetworkManager shared mode),
  which is convenient at home but hides offline behaviour in tests.

## The device and the join card

- **Card:** network name, password, both QR codes, "then open <the party address>" (which address is canonical is open —
  `PARTY-PLATFORM.md` §16.1), NFC marks, the
  troubleshooting lines.
- **Screen:** a ≥ 2.9-inch e-ink panel fits both QR codes side by side; a 128×64 OLED is too small.
- **Per-party codes (Public/Demo mode only; not in v0):** the join link may carry a short
  **multi-use** code, valid for one party, in the URL fragment (never a device token) with a typed
  fallback — one printed QR serves many guests, so it can't be single-use. Changing the Wi-Fi
  password disconnects everyone: only between parties.
- **NFC:** cheap passive stickers, **locked** (or anyone can rewrite them). An NFC reader on the Pi
  adds nothing without an app.
- **Never identify phones by MAC address** — both OSes randomize it per network.

## Tests to run with real phones (truly offline, management access kept)

1. ~~What Android receives today~~ — **done 2026-09-24:** 404 (see the network findings). The
   offline phone checklist there covers the network half of tests 2 and 4 (not the QR scans).
2. iPhone: ① → ② → the party loads in Safari; do iMessage and mobile data still work?
3. Lab only, probe not faked: popup → "Use Without Internet" → do `party.local`, the IP and a
   Pi-DNS name each load?
4. Android on a Pixel, a Samsung and an Android 10/11 phone: does the camera scan ①; does the prompt
   appear; with mobile data on and the prompt ignored, does the IP load?
5. Chrome and Samsung Internet: `party.local` with and without `http://`.
6. Strict Private DNS, iCloud Private Relay, an always-on VPN.
7. Chrome/Firefox on iPhone: the local-network prompt, including "deny".
8. NFC: URL tag on an iPhone XS+; Wi-Fi tag on Android; both records in each order.
9. Does the camera open a non-default browser?
10. After screen lock, backgrounding, walking to the edge of range and back: still on Avrana?
11. mDNS with 8+ phones; does `party.local` return IPv6 addresses?
12. Time-to-party for a first-timer: card vs TV vs e-ink.

## Must NOT

Change nginx, dnsmasq, NetworkManager, Avahi, connectivity-check handling, or Wi-Fi security/password
without approval · put identity or games inside the captive popup · redirect the IP to
`party.local` before Android is verified · remove the `captive.g.aaplimg.com` rule · put device
tokens in QR/NFC links · rely on HTTPS-only features · judge onboarding at home with internet behind
the Pi · take `eth0` down during a remote session (since 2026-09-24 eth0 is the only management link) · ship unlocked NFC tags.

**Still uncertain:** Android's NFC Wi-Fi prompt on
current Samsung/Pixel; Android routing before the prompt is answered; Private Relay with Pi-DNS names;
address-bar handling of `.home.arpa` and `.internal`.

Sources: Apple "captive Wi-Fi" support note; iOS background NFC reading (GoToTags); Android NFC
basics; Android Wi-Fi NFC tags (nfcore.app); Android mDNS (Esper); Android captive-portal custom
tabs (AOSP); RFC 8910; Web NFC (Chrome); Chrome Local Network Access; `.internal` (Wikipedia);
Apple Private Relay network guidance. All as of 2026-09.
