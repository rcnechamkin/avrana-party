# Avrana Party

A portable, self-contained local multiplayer appliance. A Raspberry Pi 4 hosts
the games; phones join its Wi-Fi ("Avrana Party") and act as screens and
controllers. Core play needs no internet, accounts or app installs.

This is separate from the Avrana Homelab media server (host `avrana`); do not
confuse them. Detailed technical context is in `CLAUDE-HANDOFF.md`, and the
arcade prototype is documented in `arcade/README.md`.

## Repo contents

| Path | Purpose |
|---|---|
| `portal/index.html` | Captive-portal landing page (live copy: `/var/www/avrana-portal/index.html`) |
| `avrana-party.nginx` | nginx site: portal probe, `/arcade/`, LAN Games proxy |
| `avrana-captive.conf` | Captive DNS rules (live: `/etc/NetworkManager/dnsmasq-shared.d/`) |
| `install-portal.py`, `install-captive-dns.py` | Installers kept for provenance and recovery; do not rerun blindly |
| `arcade/` | Gauntlet II streaming prototype and its service and install files |

The LAN Games server source is not in this repo. It lives on the Pi at
`/home/cody/LAN-Games` (service `avranaparty-games`, port 8096).

## URLs

- `http://party.local/` : LAN Games
- `http://party.local/arcade/` : Gauntlet II streaming prototype
- `http://party.local/hotspot-detect.html` : captive-portal landing page

## Current state (read-only inspection of the Pi, 2026-09-19)

- nginx, NetworkManager, avahi-daemon, avranaparty-games and avranaparty-arcade
  are active and enabled. The Pi had been up about 50 minutes and the arcade
  service had started at boot with 0 restarts.
- `Avrana Party` is an AP on `wlan1` (5 GHz, channel 149 per the NetworkManager
  profile) in shared mode at 10.42.0.1/24, autoconnect. `wlan0` is the home
  Wi-Fi / management link and default route. `eth0` has no active connection.
  `party.local` is advertised by Avahi.
- The live nginx site, portal HTML, captive DNS config and arcade unit match their
  sources in this repo.
- Portal: the Apple probe returns 200 with `Cache-Control: no-store`, and both
  `captive.apple.com` and `captive.g.aaplimg.com` resolve to 10.42.0.1 via the AP's
  DNS. The owner confirmed the portal works on an iPhone.
- Arcade: 2 player slots enabled (`MAX_PLAYERS = 2`). P1 is verified for basic
  gameplay and streaming on a real iPhone.

## Not yet verified / open

- Input-to-photon latency and gameplay performance have **not** been formally
  measured.
- Two-phone behavior is **not** verified, even though 2 slots are enabled.
- Service startup after boot is verified. Phone-side behavior after boot and a
  true offline test (wlan0 currently provides internet) are **not** verified.
- **Power:** `vcgencmd get_throttled` read `0x50000` about 50 minutes after boot,
  meaning under-voltage and throttling have occurred. This is an open
  hardware/power issue.
- Platform probes other than Apple's (Android, Microsoft, Firefox) are intercepted
  but their captive flows are untested.
- The Pi checkout has no git remote, so there is no defined deploy method yet.

## Portal install and history

Run locally on the Pi:

```sh
sudo python3 /home/cody/avrana-party/install-portal.py
```

The installer saves originals in a timestamped `backups/` directory, installs
the portal HTML and nginx site, runs `nginx -t`, reloads nginx, and restores the
originals on failure.

The mobile landing page is entirely local: embedded CSS, no JavaScript, fonts or
external dependencies. Its ordinary same-window Play link goes to
`http://party.local/`; it does not try to launch Safari automatically. The exact
nginx probe location adds `no-store`, disables ETag and ignores
If-Modified-Since so repeat probes get the page body. See
https://nginx.org/en/docs/http/ngx_http_core_module.html#if_modified_since and
https://nginx.org/en/docs/http/ngx_http_headers_module.html#add_header.

Captive DNS: `avrana-captive.conf` intercepts **both** `captive.apple.com` and
`captive.g.aaplimg.com`, with `local=` rules that stop upstream AAAA/HTTPS
answers for those names. A packet capture on 2026-09-18 showed the iPhone querying
`captive.g.aaplimg.com` directly and receiving Apple's real Success page through
upstream internet, which is why both names are required. Do not remove either.
See https://thekelleys.org.uk/dnsmasq/docs/dnsmasq-man.html.

| Date | Change | Backup |
|---|---|---|
| 2026-09-18/19 | Landing page and probe caching headers installed | `backups/20260919T032818520554Z` |
| 2026-09-18/19 | Captive DNS alias fix installed (`install-captive-dns.py`) | `backups/20260919T033200228715Z` |

## Portal acceptance checks

1. Request `http://10.42.0.1/hotspot-detect.html` with `Host: captive.apple.com`.
   Expect 200, `Content-Type: text/html`, `Cache-Control: no-store`, the Avrana
   page, and no Apple Success response. Repeat with a future `If-Modified-Since`;
   expect 200 with the page body, not 304.
2. Join Avrana Party on the iPhone. If it remembers the old connection and no
   popup appears, forget that Wi-Fi network and rejoin.
3. Confirm the landing page appears, tap Let's play, and play a game. Test name
   entry, room joining and reconnecting after screen lock.
4. If the captive assistant cannot play reliably, use the displayed Safari
   fallback while remaining connected to Avrana Party.
5. Verify with two phones, then four. An HTTP/WebSocket check alone does not
   establish that games work inside the iPhone captive assistant.
6. Schedule a full offline test with management access available. Do not disable
   `wlan0` during a remote session.
