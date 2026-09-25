# Network: topology, checks, offline mode (canonical)

The `tools/avrana-offline`, `tools/avrana-topology-check`, and `tools/radio-watch`
helpers referenced below remain on the `docs/party-platform` branch. They are
absent from production `main`; review the exact script before using it on the Pi.

This is the **single source of truth for the Pi's networking**. Status labels: **VERIFIED** (read on
the Pi, with date), **PROPOSED** (not applied), **OPEN** (owner decision). Older documents that
describe `wlan1` as the party AP are historical (the USB adapter was removed on 2026-09-24).

## Topology (since 2026-09-24)

```
 Home LAN (router 10.0.0.1)
     │
   eth0  10.0.0.142/24 — upstream + management (SSH alias `party`)
     │
 Raspberry Pi 4 "party"
     │
   wlan0  internal Broadcom radio (brcmfmac) as an ACCESS POINT
     │    SSID "Avrana Party", WPA2-Personal, 5 GHz channel 149, 20 MHz
     │    10.42.0.1/24 — NetworkManager profile "Avrana Party Internal" (ipv4.method shared)
     │
 phones (DHCP 10.42.0.10–254 from NetworkManager's dnsmasq)
```

- **No USB Wi-Fi.** `wlan1` does not exist. The old profile "Avrana Party" (bound to `wlan1`) is
  kept but has autoconnect **off**.
- **eth0 is the only management path from home.** The internal radio can't be a home-Wi-Fi client
  and the AP at the same time (reliably). Fallback: join the party Wi-Fi and `ssh 10.42.0.1`
  (sshd listens on all addresses; offline mode leaves that alone). **Never take eth0 down during a
  remote session.**
- **The party address stays `10.42.0.1`** (runbooks, QR codes, URLs and docs use it).
- Phones get IPv4 only (profile `ipv6.method ignore`; link-local IPv6 exists).

## Verified facts (2026-09-24, boot 0d18f4ca after the owner's reboot at 11:16)

| Fact | Value |
|---|---|
| Default route | `default via 10.0.0.1 dev eth0` (metric 100); the party subnet is on `wlan0` (metric 600) |
| AP | `wlan0` type AP, ssid "Avrana Party", channel 149 (5745 MHz), 20 MHz |
| AP profile | "Avrana Party Internal": interface `wlan0`, mode `ap`, band `a`, channel 149, `wpa-psk`/`rsn`, PMF default, `ipv4.method shared`, `ipv4.addresses 10.42.0.1/24`, `ipv6.method ignore`, autoconnect **yes**, priority **0** |
| DHCP/DNS | NM's dnsmasq: `--listen-address=10.42.0.1 --dhcp-range=10.42.0.10,10.42.0.254,3600`, lease file `/var/lib/NetworkManager/dnsmasq-wlan0.leases`, drop-in dir holds only `avrana-captive.conf` |
| Listeners | nginx :80, LAN Games :8096, arcade 127.0.0.1:8097, dnsmasq 10.42.0.1:53 + DHCP :67, mDNS :5353, sshd :22, iperf3 :5201, beszel-agent :45876 |
| Clients | 2 phones associated during the power runs |
| Persistence | this state came up by itself after a reboot (11:16). **Caveat:** the `eth0` profile file was rewritten at 11:33, after that boot, so the latest eth0 settings have not yet been proven across a reboot |
| Permissions | the SSH user cannot modify NetworkManager (polkit `auth`): every change below is owner-run with `sudo` |

The captive-portal answers, nginx routes and the `.local` leak behave as before; the details and
the old-topology audit are in `docs/findings/2026-09-24-party-network-and-offline-mode.md`
(historical for interface names: read `wlan1` there as today's `wlan0`, and "Pi's own `wlan0`" as
today's `eth0`).

## Check it (read-only, no sudo, ~2 s)

```bash
scp tools/avrana-topology-check party:avrana-lab/ && ssh party avrana-lab/avrana-topology-check
```

Prints PASS / FAIL / WARN / INFO lines and exits with the number of FAILs: `wlan1` absent, `wlan0`
is the internal radio in AP mode holding only `10.42.0.1/24` under "Avrana Party Internal", the
upstream path is `eth0`, exactly one AP profile autoconnects, DNS listens only on `10.42.0.1`, the
DHCP range, the live nginx site and captive DNS file equal the repo, the captive-probe DNS and HTTP
answers, and that `nftables.service` is not enabled (so offline mode can't persist). **Don't run it
during a power measurement.**

## Boot determinism — PROPOSED (owner, sudo)

Three home-Wi-Fi **client** profiles still have autoconnect on at the same priority (0) as the AP,
and two are bound to `wlan0`. NetworkManager picks the highest priority, then the most recently
used; the AP won at the last boot, but if the AP ever fails to start (regulatory domain, firmware,
under-voltage) or a client profile is used once, `wlan0` can come up as a home-Wi-Fi client instead
— **no party network**. Make it deterministic (reversible; never type Wi-Fi passwords or network
names into chat or the repo — use UUIDs):

```bash
sudo tar -C /etc/NetworkManager -czf /root/nm-conns-$(date +%Y%m%dT%H%M).tgz system-connections   # backup (contains passwords: keep in /root)
nmcli -f NAME,UUID,TYPE,AUTOCONNECT,AUTOCONNECT-PRIORITY connection show                         # note the client UUIDs
sudo nmcli connection modify "Avrana Party Internal" connection.autoconnect-priority 100
sudo nmcli connection modify uuid <home-client-uuid> connection.autoconnect no                     # each client profile
```

Undo: set the priority back to `0` and each client's autoconnect back to `yes`. Trade-off: if the AP
fails, `wlan0` stays idle instead of joining home Wi-Fi (deterministic; eth0 still manages the Pi).
After applying, reboot once and run the topology check again.

## Offline mode — dev tool (owner, sudo)

`tools/avrana-offline on [30min|2h] | off | status`. While ON, party clients reach the Pi
(`10.42.0.1`: pages, DHCP, DNS, mDNS) but **nothing beyond it** — not the internet, not the home LAN
— and dnsmasq stops forwarding their DNS upstream. The Pi's own traffic and eth0 management are
untouched.

- One runtime nftables table (`inet avrana_offline`), a marker file `/run/avrana-offline`, and a
  transient systemd timer that removes both after the chosen time (dead-man revert). Nothing under
  `/etc`; gone after `off` or a reboot; never `nft flush ruleset`.
- Refuses to run if `wlan0` doesn't hold `10.42.0.1/24`, or if dnsmasq runs as root or shares its
  user with another process (the DNS rule matches dnsmasq by user id).
- Run it from a copy of the repo (`sudo ~/path/to/tools/avrana-offline on 30min`).

**Verify (Pi):** `tools/avrana-offline status` · `dig +time=3 +tries=1 @10.42.0.1 example.com` must
fail (record SERVFAIL / REFUSED / timeout) · `dig +short @10.42.0.1 captive.apple.com` = 10.42.0.1 ·
`curl -s -o /dev/null -w '%{http_code}' -H 'Host: captive.apple.com' http://10.42.0.1/hotspot-detect.html`
= 200 · `curl -sI -m5 https://example.com` from the Pi still works · with sudo, `status` shows the
counters rising while a phone tries to go online. Dead-man test: `on 2min`, wait, `status` = OFF.

**Why it matters today:** without it, party clients get the home internet **and can reach every
device on the home LAN** (NAT through eth0) — every phone test so far had internet behind it.

## Phone checklist (owner; offline mode ON) — not yet done

For each phone record model, OS version and the time of each step. Run 1 with mobile data OFF, run 2
ON; VPN off; note Android Private DNS / iCloud Private Relay.

1. Forget "Avrana Party", rejoin: exact popup/notification text; what Wi-Fi settings says; Android
   "Stay connected?" — what you tapped.
2. In the normal browser: `http://10.42.0.1/`, `party.local`, `http://party.local/`,
   `http://10.42.0.1/arcade/` — loads? how long?
3. `example.com` and `http://10.0.0.1/` (home router) — both must fail; record the error.
4. Lock 2 minutes, unlock: still on Avrana? does a game page reconnect?
5. iPhone: send an iMessage (fails quietly, or goes over mobile data in run 2?). Android run 2: does
   the IP load before and after answering the prompt?

**Expected (not proven on a device):** iOS shows no popup even offline (the Apple probe is answered
locally); Android shows "no internet" but no sign-in popup (its probe gets a 404).

## Capacity and radio risks (REPORTED / ASSUMED — measure, don't trust)

- The Pi 4's radio in AP mode is widely **reported** to top out around **8 stations** on the standard
  firmware (a "minimal" firmware is reported to allow ~19). Check which is active without sudo:
  `update-alternatives --display cyfmac43455-sdio.bin`. The 4/6/8-phone test is in
  `docs/runbooks/party-load-test.md`.
- 5 GHz only: 2.4 GHz-only devices can't join. Channel 149 is legal in the US/Canada, not in most of
  Europe/UK/Japan (a travel issue). If a phone fails to join, PMF on the AP is a reported culprit.
- Under-voltage now threatens the **AP itself** (it runs on the board). Power without the USB adapter:
  `docs/findings/` (2026-09-24 no-USB baseline).

## DNS determinism — PROPOSED (owner approval; changes a live dnsmasq drop-in)

Today dnsmasq forwards `.local` and other local-only names upstream (a leak, and a slow NXDOMAIN on
Androids without mDNS). A drop-in `avrana-local.conf` with `domain-needed`, `bogus-priv`,
`local=/local/`, `local=/avrana/`, `local=/home.arpa/` would answer them locally. Blast radius:
party clients only. Applying it re-activates the AP (clients drop for seconds). Not applied; the
party-address decision (`PARTY-PLATFORM.md` §16.1) comes first. `install-captive-dns.py` now
targets the profile "Avrana Party Internal" (override `AVRANA_AP_PROFILE`) and refuses to touch
anything if that profile isn't active.
