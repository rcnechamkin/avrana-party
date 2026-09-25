# Party network: what phones get today, and a reversible offline test mode

> **Historical for interface names (2026-09-24, later that day):** the USB Wi-Fi adapter was removed
> and the AP moved to the Pi's internal radio. Read `wlan1` below as today's `wlan0`, and the "Pi's
> own `wlan0`" upstream as today's `eth0`. The offline-mode recipe below targets `wlan1` and would
> **not** block anything now — use `tools/avrana-offline` instead. Current, canonical network facts:
> `docs/runbooks/network.md`. The captive-probe, DNS and nginx observations below still apply.

Date: 2026-09-24, Pi uptime ~31 min on the new PSU (boot b90bd6d2). **Read-only audit; nothing was
changed.** `sudo -n` is refused, so the nftables ruleset and the DHCP lease file were not read.
Live nginx site and captive DNS drop-in are byte-identical to `main` (`cmp`).

Labels: **OBSERVED** = read on the Pi · **INFERRED** = follows from observations, not proven ·
**EXPECTED** = each OS's documented/known probe behaviour, not yet confirmed on a phone.

## OBSERVED

**Party AP.** `wlan1` = RTL8851BU USB adapter (`rtw89_8851bu`), AP mode. NetworkManager profile
"Avrana Party": bound to `wlan1`, autoconnect, SSID broadcast, **WPA2-Personal** (`wpa-psk`, RSN,
CCMP; PMF default), **5 GHz channel 149, 20 MHz**, `ipv4.method shared` (10.42.0.1/24),
`ipv6.method ignore` (clients get link-local IPv6 only). One iPhone associated: −48…−53 dBm,
VHT-MCS8 86.7 Mbit/s, 0 retries/failures. `wlan0` (onboard Wi-Fi) is a client of the home network
and holds the default route.

**DHCP/DNS.** NetworkManager's own dnsmasq 2.91 (runs as `nobody`; DHCP 10.42.0.10–254, 1 h
leases; drop-in dir holds only `avrana-captive.conf`). It has **no `--no-resolv`**, so it forwards
everything it doesn't answer to the ISP's resolvers via `wlan0`.

| Name queried at 10.42.0.1 | Answer |
|---|---|
| `captive.apple.com`, `captive.g.aaplimg.com` | 10.42.0.1, no AAAA |
| `connectivitycheck.gstatic.com`, `clients3.google.com`, `www.msftconnecttest.com`, `detectportal.firefox.com` | 10.42.0.1 **plus real public AAAA** (harmless today: clients have no IPv6 route) |
| `www.google.com`, `www.gstatic.com`, `www.msftncsi.com`, `example.com` | real addresses (not intercepted) |
| `party.local`, `party.avrana` | NXDOMAIN — and `party.local` was **forwarded upstream** (root SOA came back) |

**Routing.** `ip_forward=1`; NAT modules loaded; conntrack ≈ 90 entries. INFERRED: party clients
get the home internet through `wlan0` via NetworkManager's masquerade (consistent with shared mode;
ruleset unreadable without root).

**nginx** (port 80 only; nothing on 443 — connections refused at once):

| Probe | Response |
|---|---|
| Apple `/hotspot-detect.html` (both hosts) | **200** "Success" page, `no-store` |
| Android `/generate_204` (gstatic, clients3), `www.google.com/gen_204` | **404** JSON `{"detail":"Not Found"}` from LAN Games |
| Windows `/connecttest.txt`, `/redirect`, `www.msftncsi.com/ncsi.txt` | **404**, same |
| Firefox `/success.txt` | **404**, same |
| `10.42.0.1/`, `party.local/` | 200, LAN Games hub |

**Avahi** publishes `party.local` on **both** `wlan1` (10.42.0.1 + link-local IPv6) **and `wlan0`**
(the home LAN sees `party.local` = the Pi's home address). No `allow-interfaces`.

**Power save** reported `on` for both radios (`iw`); NetworkManager leaves it at default. On `wlan0`
this is real client power save (may add SSH latency); whether `rtw89` honours it in AP mode is
UNKNOWN.

## EXPECTED phone behaviour

| OS | Today (home internet behind the Pi) | Truly offline |
|---|---|---|
| **iOS** | "Success" → no popup, network marked working | **Same** — the answer is faked locally, so no warning; iMessage/apps fail quietly; Wi-Fi Assist may move traffic to mobile data |
| **Android** | HTTP probe gets 404 (neither success nor portal); the parallel **HTTPS** probe goes out through NAT and succeeds → validated | Both fail → "Connected, no internet" / "Stay connected?"; **no sign-in popup** (404 isn't a portal answer); with mobile data on, traffic may prefer cellular until the prompt is answered |
| **Windows** | expects "Microsoft Connect Test", gets 404 → probably "No internet" even today | "No internet" |
| **Firefox** | expects `success`, gets 404 → probably no portal banner | same |

**Consequence:** every phone test so far had internet behind it, which hides Android's offline
behaviour. The playtest must run in offline mode.

## Offline test mode (design only — not applied; the owner runs it, since it needs sudo)

Options considered: **A** block forwarding only (DNS still resolves, connections fail) · **B** drop
dnsmasq's upstream DNS by user id (dnsmasq is the only `nobody` process) · **C** a `no-resolv`
drop-in — **rejected**: persistent on disk and NetworkManager must re-activate the AP, kicking
every client. **Recommended: A + B in one temporary nftables table**:

```sh
sudo nft -f - <<'EOF'
table inet avrana_offline {
  chain fwd { type filter hook forward priority -10; policy accept;
    iifname "wlan1" oifname != "wlan1" counter reject with icmpx type no-route
    iifname != "wlan1" oifname "wlan1" counter drop }
  chain out { type filter hook output priority -10; policy accept;
    meta skuid "nobody" oifname != "wlan1" meta l4proto { udp, tcp } th dport 53 counter drop }
}
EOF
sudo systemd-run --on-active=2h /usr/sbin/nft delete table inet avrana_offline   # dead-man auto-revert
```

- **Disable:** `sudo nft delete table inet avrana_offline` (or reboot — the nftables service is
  disabled, so nothing reloads it). **Never `nft flush ruleset`**: it also wipes NetworkManager's NAT.
- **Scope:** only traffic crossing between `wlan1` and anything else, plus dnsmasq's upstream DNS.
  Untouched: the home network, the Pi's own `wlan0` traffic and DNS, SSH, DHCP, the local captive
  answers, mDNS, nginx on 10.42.0.1. Nothing is written to disk.
- dnsmasq's cache (150 entries) keeps answering until TTLs expire; optional
  `sudo kill -HUP $(cat /run/nm-dnsmasq-wlan1.pid)` clears it without dropping the AP.
- UNKNOWN: whether blocked-upstream dnsmasq answers SERVFAIL/REFUSED or lets clients time out (a
  truly offline appliance would answer REFUSED at once). Record which.

**Verify** (Pi): `dig +time=3 @10.42.0.1 example.com` fails (note how); `dig @10.42.0.1
captive.apple.com` → 10.42.0.1; `curl -H 'Host: captive.apple.com' http://10.42.0.1/hotspot-detect.html`
→ 200; `curl -sI https://example.com` from the Pi still works (`wlan0` intact); `sudo nft list table
inet avrana_offline` counters climb while a phone tries to go online. From a laptop — **only one
with a second (wired/tethered) link**, since joining Avrana takes it off the home network:
`Resolve-DnsName example.com -Server 10.42.0.1` fails, `curl.exe -m5 http://example.com` fails,
`curl.exe http://10.42.0.1/` → 200. Take the same readings before enabling, as a baseline.

## Phone checklist (owner, offline mode on)

Per phone: model, OS version, time of each step.

1. Run 1 mobile data **off**, run 2 **on**. VPN off. Note Android Private DNS and iPhone iCloud
   Private Relay settings.
2. Forget "Avrana Party", rejoin. Record any popup/notification (exact wording), what Wi-Fi settings
   says, and on Android whether "Stay connected?" appears and what was tapped.
3. In the normal browser: `http://10.42.0.1/`, `party.local` (bare, then with `http://`),
   `http://party.local/arcade/` — loads? how long?
4. `example.com` — record the exact error.
5. Lock 2 min, unlock: still on Avrana? does the game page reconnect?
6. iPhone: send an iMessage (fails quietly, or goes over mobile data in run 2?). Android run 2: does
   the IP load before and after answering the prompt?
7. Copy results into `docs/design/ONBOARDING.md`'s test list.

## Unknowns

NetworkManager's exact nftables tables (need root) · AP-mode power save on `rtw89` · dnsmasq's
blocked-upstream answer · whether phones use the link-local IPv6 address Avahi advertises on
`wlan1` · real Windows and Firefox verdicts.

## Observations worth an owner decision later (no change proposed now)

- `party.local` queries leak upstream (dnsmasq forwards `.local`); and Avahi advertises
  `party.local` on the home LAN too. Both are cosmetic today; they matter for the single-origin
  decision (`ONBOARDING.md`, F2b).
- Android's probe 404 is fine offline (no portal popup) but means Android never "validates" the
  network. Answering `/generate_204` with 204 would make Android treat the offline party network as
  having internet — which may *hurt* (phones stop using mobile data for everything else). Decide
  after the phone checklist, not before.
