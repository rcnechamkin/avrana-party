# Avrana Party portal

## Inspected state — 2026-09-18

- nginx, avranaparty-games, avahi-daemon, and NetworkManager are active and enabled.
- Avrana Party autoconnects in AP/shared mode on wlan1, currently 10.42.0.1/24.
- eth0 is disconnected; wlan0 is connected and is the current default route.
- party.local resolves to 10.42.0.1 using Avahi.
- DNS at 10.42.0.1 answers captive.apple.com with 10.42.0.1.
- The existing /hotspot-detect.html route already returns valid portal HTML with status 200.
- The launcher returns 200, /health reports healthy, and /chat/ws upgrades with 101 through nginx.

## Prepared change

The mobile landing page is entirely local, with embedded CSS and no JavaScript,
fonts, or external dependencies. Its ordinary same-window Play link leads to
http://party.local/. It does not attempt to launch Safari automatically.

The existing exact nginx probe location is retained, adding no-store, disabling
ETag, and ignoring If-Modified-Since so repeat probes receive the page body.
See https://nginx.org/en/docs/http/ngx_http_core_module.html#if_modified_since
and https://nginx.org/en/docs/http/ngx_http_headers_module.html#add_header.
Other game routes, DNS, NetworkManager, Avahi, and systemd are unchanged.

## Install

Run locally on the Pi:

```sh
sudo python3 /home/cody/avrana-party/install-portal.py
```

The installer saves originals in a timestamped backups directory, installs both
files, runs nginx -t, and reloads nginx. On failure it restores the originals.
The owner installed the change successfully. Post-install verification confirmed
both live files match these sources, normal and conditional Apple probes return
200 with the complete landing page and Cache-Control: no-store, the launcher and
health endpoint return 200, and the WebSocket proxy upgrades with 101. All four
services remain active. Backup: backups/20260919T032818520554Z.
The physical iPhone and fully offline acceptance checks remain pending.

## Follow-up: iPhone still displayed Success

A packet capture at 20:31 on September 18 proved the phone queried
captive.g.aaplimg.com directly and fetched /hotspot-detect.html with Host:
captive.apple.com from Apple's public server. The response was Apple's Success
HTML. The original address-only DNS rule also leaked public CNAME/AAAA answers.

Installed avrana-captive.conf now intercepts
both captive.apple.com and captive.g.aaplimg.com, with local= rules preventing
upstream AAAA/HTTPS resolution for those two names. This follows dnsmasq's
documented address/local behavior: https://thekelleys.org.uk/dnsmasq/docs/dnsmasq-man.html

The installer install-captive-dns.py validated the configuration, backed up the
original to backups/20260919T033200228715Z, and reactivated only Avrana Party.
wlan0 remained connected. Both A answers now point to 10.42.0.1; AAAA/HTTPS
queries return NOERROR with no answers. Portal HTTP remains 200. A fresh iPhone
visual confirmation after this DNS fix is still needed.

## Acceptance checks after installation

1. Request http://10.42.0.1/hotspot-detect.html with Host: captive.apple.com.
   Expect 200, Content-Type text/html, Cache-Control no-store, the Avrana page,
   and no Apple Success response. Repeat with If-Modified-Since set in the future;
   expect 200 with the page body, not 304.
2. Join Avrana Party on the iPhone. If it remembers the old connection and no
   popup appears, forget that Wi-Fi network and rejoin.
3. Confirm the new landing page appears, tap Let's play, and play a game.
   Specifically test name entry, room joining, and reconnecting after screen lock.
4. If the captive assistant cannot play reliably, use the displayed Safari
   fallback while remaining connected to Avrana Party.
5. Verify with two phones, then four. An HTTP/WebSocket check alone does not
   establish that games work correctly inside the iPhone captive assistant.
6. Schedule a full offline test with management access available. Ethernet is
   already disconnected, but wlan0 still provides internet, so that alone does
   not constitute an offline test. Do not disable wlan0 during a remote session.

Reboot behavior was reported working by the owner; this change does not modify
startup configuration. A fresh reboot and fully offline phone test remain to be
observed. Only the existing Apple probe is handled specially; other intercepted
platform probe paths still need separate testing before claiming support.
