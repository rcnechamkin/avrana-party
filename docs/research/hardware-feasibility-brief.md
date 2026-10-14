# Hardware feasibility brief: requirements and validation matrix

- **Status:** Research and a preliminary requirements-and-validation matrix (2026-10-12). Direction and evidence only; **not a decision, not a vendor selection, not a contract**. Nothing here changes the prototype or selects hardware.
- **Date:** 2026-10-12
- **Sources:** Party `origin/main` `04c5844`; the dated findings cited per row; the read-only appliance capture of 2026-10-12 ([baseline](../findings/2026-10-12-deployed-baseline.md)); `origin/feat/avr-296-wifi-qualification` (PR #85) for the Wi-Fi measurements; three external pages, re-checked 2026-10-12 and labelled below.
- **Related:** Linear AVR-42 (platform requirements), AVR-43 (power, thermal, enclosure), AVR-301 (client capacity), AVR-315 (BLE owner control plane, design), AVR-423 (hardware security and owner-unlock feasibility), AVR-422 (owner-modifiable mode trust boundaries), AVR-82 (signed update chain), AVR-67 (A/B update spike), AVR-79 (clock policy). `docs/research/BLE-OWNER-CONTROL-PLANE-SPIKE.md`, [offline-acceptance](../runbooks/offline-acceptance.md).

Written for later discussions with hardware makers. It lists what the software needs and how each need
would be validated. Every number is labelled:

- **MEASURED**: in a dated repository document, cited with its conditions.
- **OBSERVED**: read from the appliance on 2026-10-12 (baseline), one reading.
- **EXTERNAL**: from a named outside page, **not measured here**; cited by URL.
- **ESTIMATE**: derived here from MEASURED inputs; the formula is shown.
- **UNKNOWN**: not in the repository or the sources; to be measured. No number is invented.

## 1. Current prototype and its measured limits

Raspberry Pi 4 Model B ("party", Debian 13, kernel 6.18.39+rpt-rpi-v8, OBSERVED). The internal Broadcom radio
(brcmfmac, BCM43455, firmware 7.45.265 per the 2026-10-06 finding) is the access point on `wlan0`. OBSERVED
2026-10-12: **5 GHz channel 36 (5180 MHz), 20 MHz**, regulatory country US with DFS-FCC, 1 station, firmware
alternative `cyfmac43455-sdio.bin` in auto mode pointing at the standard firmware. `docs/runbooks/network.md`
records channel 149 on 2026-09-24; the owner moved it to 36 on 2026-10-06. `eth0` is management and upstream.
WPA2-Personal; NetworkManager `ipv4.method shared` on 10.42.0.1/24. The USB Wi-Fi adapter (RTL8851BU) was
removed 2026-09-24 to resolve under-voltage.

| Area | Result | Conditions | Citation |
|---|---|---|---|
| Under-voltage with adapter, old PSU | live under-voltage on every boot; kernel about 14 to 18 dips/h on 2026-09-19 (23 in about 100 min); one brownout reset during PS1 streaming on 2026-09-23 | about 93 h, 5 boots | [new-psu-power-baseline](../findings/2026-09-24-new-psu-power-baseline.md) "History" |
| Under-voltage with adapter, new PSU | 9 dips in about 91 min (about 5.5/h); in the quiet run each episode read `0x50005` with ARM cut to 600 MHz and core 0.86 V; 7 of 9 dips within 2 s of an SSH session start | 2026-09-24 08:21 to 09:52 PDT | same file |
| No adapter, new PSU | 0 kernel dips, `get_throttled` `0x0` for 3 h 26 min (idle, light, 10 x 4-core 20 s bursts, about 24,300 pings at 50/s) | 2026-09-24 11:16 to 14:42 PDT, 2 phones associated, arcade stream process running | [no-usb-power-baseline](../findings/2026-09-24-no-usb-power-baseline.md) |
| PS1 + arcade + up to 5 viewers | 7 bounded runs of 5 to 10 min: all `0x0`, 0 dips, ARM 1800 MHz, max 54.0 C, load average up to 14.9 | 2026-09-24 evening; viewers were laptop Chromium over `eth0`, not phones or the Party Wi-Fi | [ps1-bomberman-party-slice](../findings/2026-09-24-ps1-bomberman-party-slice.md) |
| CPU temperature | 46.2 to 49.6 C idle; peak 56.9 C under all-core bursts; 54.0 C max in PS1 runs; no fan, only `cpu-thermal`; no thermal-throttle bits seen. OBSERVED 31.6 C idle on 2026-10-12 | open bench, no enclosure, ambient unknown | no-usb baseline; baseline finding |
| Arcade CPU | Gauntlet II uses about 1.4 to 1.7 cores with nobody playing | 2026-09-24 | PS1 slice finding |
| PS1 CPU | emulator about 1 to 1.2 cores; stream about 1.2 cores at 5 viewers; each viewer about 14% of a core (9.5% video, 4.5% audio); capture + encode about 20% total. Arcade + PS1 + stream exceed 4 cores, so PS1 is starved | 320x240, 20 ms audio frames | same |
| PS1 emulated speed with the arcade co-running | 640x480 / 5 viewers about 21 fps (about 35% speed); 640x480 / 1 viewer about 29 (about 49%); 320x240 / 5 viewers 35 to 44; emulator alone about full speed | in-game clock or RetroArch overlay | same |
| PS1 latency, real iPhone on the Party Wi-Fi | input round trip p50 6 ms, **p99 1.4 s, max 2.2 s**; frame gaps p95 0.6 s; stalls in about 16% of seconds; AP power save was ON (prime suspect; A/B not yet run) | 278 s, 2026-09-24 20:28 to 20:38 | [ps1-latency](../findings/2026-09-24-ps1-latency.md) |
| PS1 pipeline, wired simulation | capture-to-shown p99 32.5 ms; event-loop lag max 10 ms | laptop Chromium over `eth0` | same |
| Wi-Fi, one client, channel 149 vs 36 | ch149: idle p50 10.4 to 11.0 ms, p99 140 to 211 ms, tablet TX retries 30 to 36 per success, TCP uplink 1.75 Mbps. ch36: p50 5.8 to 6.0, p99 64 to 99 ms, retries 0.6 to 0.7, TCP uplink 49 Mbps. Neighbouring networks did not explain it; cause untested | one Samsung SM-T510 at arm's length, Pi alone, 400 pings at 200 ms, after a reboot | `origin/feat/avr-296-wifi-qualification:docs/findings/2026-10-06-wifi-channel-36-vs-149.md` (on that branch only) |
| Firmware mailbox wedge | before the 2026-10-06 reboot `vcgencmd get_throttled` hung and `Firmware transaction ... timeout` appeared; downlink about 1.7 Mbps, RTT 0.5 to 1.4 s; cleared by reboot; cause unknown | 2026-10-06 | same file |
| Client capacity | **UNKNOWN.** Two phones is the most ever recorded associated | | AVR-301 measures it |
| Server-side capacity (4 to 6 phones, BLUFF) | UNKNOWN on hardware; only simulated and Chromium suites exist (T1, T2) | | [TESTING](../TESTING.md) |
| Cold-boot inrush, long sessions, battery pack | **Not tested** | | no-usb baseline "Not tested" |
| Wall power in W or A | **UNKNOWN: no watt or ampere measurement exists in the repository** (flags, volts, clocks and temperatures through `vcgencmd` only) | | search of findings and telemetry |
| Storage | OBSERVED: `/` is ext4 on a 117 GB SD-class device (`/dev/mmcblk0p2`), 9% used | 2026-10-12 | baseline finding |
| Clock | OBSERVED: no RTC; `systemd-timesyncd` active; at the last boot the clock began about 37 h behind and stepped | 2026-10-12 | baseline finding |

Operational caveats that affect every measurement: a wedged firmware mailbox hides throttle state (2026-10-06);
SSH sessions are CPU bursts that triggered dips, so do not poll; `get_throttled` bits 16 to 19 are sticky, and the
authority is the kernel line count (`journalctl -k -b | grep -icE 'undervoltage|voltage normalis'`, 2 lines = 1 dip).

## 2. Single-radio limitations

- **One radio for the AP and the upstream.** The internal radio cannot reliably be a home-Wi-Fi client and the
  AP at once (network.md). Today the Pi uses `eth0` as upstream. A field unit with no Ethernet has **no upstream
  path at all** while serving; that matches the product promise, but remote management and updates then need
  another path (owner app and BLE, AVR-315, or a second radio).
- **Concurrent dual-band AP.** I could not verify the claim that the CYW43455 cannot serve two bands at once: the
  Infineon community page returned HTTP 403 on 2026-10-12. **Dropped. UNKNOWN.**
- **Client-count limit.** The repository gives only "reported around 8 stations on standard firmware, about 19 on a
  minimal firmware", with no source (`network.md`, `party-load-test.md`; the architecture audits repeat "near 8").
  EXTERNAL, re-read 2026-10-12: one DietPi forum post reports a limit of **7 simultaneous clients on a Raspberry
  Pi 3B+** (same Cypress chip family) that went away after switching to the minimal firmware, after which the author
  connected 11 devices; the author says the new limit is unknown and "19" is an assumption from a GitHub document
  (<https://dietpi.com/forum/t/wifi-hotspot-number-of-clients-limited/18401>). That is a forum report on another
  board. **Treat the Pi 4 limit as UNKNOWN; AVR-301 measures it** (before: `update-alternatives --display cyfmac43455-sdio.bin`,
  read-only; OBSERVED standard firmware on 2026-10-12).
- **Channel and regulatory.** OBSERVED: country US, DFS-FCC; the phy line reads "country 99: DFS-UNSET". Non-DFS
  channels 36 to 48 and 149 to 165 are allowed, 52 to 144 are DFS (2026-10-06 finding). Channel 149 is legal in the
  US and Canada but not in most of Europe, the UK or Japan (network.md). As configured (band `a`) the AP is 5 GHz
  only, so 2.4 GHz-only phones cannot join. DFS radar-detect and vacate behaviour on this firmware is UNKNOWN. A
  retail product needs the radio module's certification for each region and a country lock: a requirement, not
  measured.
- **Observability on brcmfmac in AP mode.** `iw station dump` gives only `tx failed`; `iw survey dump` is empty (no
  channel utilisation); the client-side retry counter showed an extreme false value (129 retries per success on a
  clean run, per `docs/runbooks/wifi-qualification.md` on PR #85).
- **Power save.** AP power save was reported `on` (2026-09-24-ps1-latency); the effect on latency has not been A/B tested.

## 3. External travel-router or AP and host/AP separation

What must stay true for the software (from `avrana-party.nginx`, `avrana-captive.conf`,
[party-https](../runbooks/party-https.md), [LIMITED-MODE](../design/LIMITED-MODE.md), ADR 0012 and 0013):

1. Phones resolve `party.avrana.net` (and `games.avrana.net`) to the host on the Party network only (dnsmasq
   host-records; public DNS has no record). Any AP must hand out DHCP with the host as DNS, or do the host-record
   itself.
2. Probe hostnames (`captive.apple.com`, `captive.g.aaplimg.com`, `connectivitycheck.gstatic.com`,
   `clients3.google.com`, `www.msftconnecttest.com`, `msftconnecttest.com`, `detectportal.firefox.com`) must resolve
   to the host, and the host answers Apple's `/hotspot-detect.html` with the literal Success (owner decision
   2026-09-18, no popup). A router with its own captive logic would change this.
3. Trusted HTTPS on a real hostname: Let's Encrypt through DNS-01, served by nginx on the host at 443. Today an
   expired or invalid certificate ends Full Mode; ADR 0012 Limited Mode (a plain-HTTP fallback) is accepted but
   **not deployed**.
4. Every phone talks to the host, never to another phone, so client isolation between phones is acceptable; host
   reachability on 80 and 443 is mandatory.
5. The host keeps a stable address (10.42.0.1 is hard-coded in runbooks, QR cards, DNS records and checks).
6. Time: the host has no RTC and nothing in the repository sets the clock (inventory U10; AVR-79 open). A separate
   AP with its own clock does not fix the host's clock for Party tickets.

| Option | Pros | Cons and risks | What to measure |
|---|---|---|---|
| A. Keep the internal radio as the AP (today) | zero extra parts; a proven boot path | station limit unmeasured; weak antenna; the radio's load on the 5 V rail; no survey or ACS | AVR-301 table; A/B channels with two devices (AVR-300); power-save A/B |
| B. Travel router in AP mode, Pi on its LAN port | better antennas and likely more clients; takes the radio off the Pi's rail | one more device and power input; DHCP, DNS and captive behaviour must be reproduced (DNS = host); boot ordering; a second failure mode | client count, RTT and loss against option A with the same phones, boot-to-joinable time, whether probes behave identically, power of both |
| C. Pi + USB Wi-Fi adapter on a powered hub | the adapter was already used | it caused under-voltage on the 5 V rail; USB complexity | only if powered separately; same matrix |
| D. Integrated board with a better radio (retail) | one enclosure | not measured; certification | the requirements in section 9 |

No recommendation to change production. The 2026-10-06 finding itself lists "a small travel router in AP mode fed
by the Pi over Ethernet" as an option to decide only after a second-client test.

## 4. Power

- **MEASURED:** under-voltage behaviour only (section 1). EXTERNAL: the Raspberry Pi documentation lists the Pi 4
  Model B power input as "USB-C power; 5 V at 3 A (15W)" (<https://www.raspberrypi.com/documentation/computers/raspberry-pi.html>,
  re-read 2026-10-12). That page does not state USB Power Delivery behaviour; **UNKNOWN**.
- **Brown-out behaviour. MEASURED:** a dip cuts the ARM clock to 600 MHz and core to 0.86 V; a severe dip reset
  the board (2026-09-23 during PS1 streaming). With the adapter attached the cause was margin on the 5 V rail; the
  cable and PSU were not isolated (new-psu finding "Does not show").
- **Battery sizing formula** (inputs unmeasured, kept as variables):
  `runtime_h = battery_Wh x converter_efficiency / measured_W`, with `measured_W` read at the 5 V input of the Pi
  with an inline USB meter (UNKNOWN; offline-acceptance A-23), `converter_efficiency` the pack's 5 V conversion
  (UNKNOWN; EXTERNAL datasheet) and `battery_Wh` the rated energy. For a duty mix use
  `measured_W = P_idle f_idle + P_load f_load`, `f_idle + f_load = 1`. Target runtime is not defined in the
  repository (ROADMAP line 154 lists "battery runtime" as something to measure; `PARTY-PLATFORM.md` lists battery as
  an open V1 hardware item, line 663). The product-differentiation finding notes that several airlines ban in-flight
  power-bank use (its own sources were not individually verified); cell chemistry certification is a retail concern
  and is not researched here.
- **USB-C PD for a retail unit.** Requirement: tolerate a PD source without depending on PD negotiation by the SBC,
  or add a PD sink controller; minimum input voltage and ride-through TBD.
- **Hold-up.** Whether the unit must survive a brief supply interruption without filesystem damage is UNKNOWN (no
  pull test yet; offline-acceptance A-18).

## 5. Thermal expectations for an enclosure

- MEASURED: open air, no fan, peak 56.9 C (all-core bursts) and 54.0 C (PS1 runs), ambient unknown, no thermal
  throttle bits. EXTERNAL, re-read 2026-10-12: the Raspberry Pi documentation says that between 80 C and 85 C the
  Arm cores are progressively throttled, with a hard limit of 85 C and no soft limit defined for the Pi 4. The
  findings cite about 30 C of headroom to 80 C.
- ESTIMATE: remaining margin without an enclosure is about 23 to 26 C to 80 C (80 minus 56.9 or 54.0) at unknown
  ambient. With an enclosure `delta_T = P_dissipated x R_th_enclosure`; both are UNKNOWN (no watt data), so no number
  is given.
- Sustained enclosed thermal runs (hours, warm ambient, such as a bar table) are **not done**. An enclosure also
  affects antenna placement (AVR-43); a metal enclosure must not shield the AP radio.

## 6. Constraints for future BLE owner management (AVR-315 on this radio)

- EXTERNAL, re-read 2026-10-12: the Raspberry Pi documentation lists the Pi 4 Model B with "Bluetooth 5, Bluetooth
  Low Energy (BLE)" and 2.4/5 GHz dual-band 802.11ac Wi-Fi; the page does not name the chip. Whether Bluetooth and
  Wi-Fi share one front end and antenna on this board, and how the firmware arbitrates, is **UNVERIFIED** here. The
  effect of BLE advertising or GATT on AP latency with several clients is **UNKNOWN**: no measurement.
- `docs/research/BLE-OWNER-CONTROL-PLANE-SPIKE.md` (a proposal; nothing built) limits BLE to commands, status and
  small messages, with bulk staging over Wi-Fi. That limits airtime pressure but does not remove a coexistence risk.
- Measure before committing: run the 1 to 10 client latency test (AVR-301) with and without an active BLE connection
  and advertising; record RTT p99 and retries; also whether BLE stays usable while the AP is busy, and whether the
  host's BlueZ stack and the radio firmware coexist for hours.
- Requirement: BLE management must not depend on the Wi-Fi AP being healthy (a recovery path when `wlan0` fails,
  such as the firmware mailbox fault of 2026-10-06).

## 7. Appendix: future compatibility options (not replacements for the appliance-first model)

| Option | Why it does not replace the appliance |
|---|---|
| Wi-Fi Aware (NAN) | needs OS and app support on both ends; ordinary browser guests cannot use it. Platform support is not researched here |
| Wi-Fi Direct | needs an app or OS pairing UI; browser-only guests cannot join |
| Phone-hosted Party | a phone cannot serve guests from a browser page, and background and battery limits apply; not researched here |

All three need a native app on at least one side; the promise says "ordinary phones, no guest app". The owner app
is a separate decision (AVR-45, AVR-315).

## 8. Security and update hardware needs (requirements only)

| Need | Why | Linear |
|---|---|---|
| Secure or verified boot chain | signed official firmware against an owner-modifiable mode | AVR-423, AVR-422 |
| Device identity key held in hardware (secure element, TPM or OTP) | per-device identity, owner pairing, signed releases | AVR-423, AVR-315 |
| Hardware-backed storage for the TLS private key and game keys | today the keys are `0600` files on the SD card (`/etc/avrana-party/tls`, game keys) | AVR-423 |
| A/B storage with rollback and power-fail safety | signed updates; a spike on spare media | AVR-82 (signed update chain), AVR-67 (A/B spike) |
| Reproducible image and rebuild | no image today ([architecture-review](../findings/2026-10-02-architecture-review.md): "no A/B, no reproducible install"); the rebuild runbook is proposed and not run | AVR-32, AVR-67 |
| Storage endurance and power-fail tolerance for logs | the SD card is the only storage; the journal is volatile today (OBSERVED), telemetry files are bounded | AVR-29, AVR-30 |
| Battery-backed RTC | no RTC today; the clock affects tickets and diagnostics; `rtc: true or false` was proposed as a grant field | AVR-79, AVR-42 |

## 9. Validation matrix

| # | Requirement | Target / threshold | How to measure | Current evidence | Status | Prototype improvement vs retail requirement |
|---|---|---|---|---|---|---|
| R1 | No under-voltage in normal use | 0 kernel dips and `0x0` over a multi-hour party | `pi-throttle-check.sh`, kernel count read once at the end; no SSH polling | 3 h 26 min clean idle and burst, 2026-09-24 (no adapter) | measured (limited) | prototype: adapter out, better PSU and cable; retail: power tree designed for the peak with margin |
| R2 | Cold-boot power inrush | no dip within 60 s over 5 cold boots | per-second sampler from boot | not tested | unknown | both |
| R3 | Supply power | idle W and loaded W at the 5 V input | inline USB meter: idle, 4 phones, BLUFF, arcade, PS1 (A-23) | none | unknown | retail |
| R4 | Battery runtime | TBD (owner) | formula in section 4 with R3 inputs (A-24) | none | unknown | retail |
| R5 | CPU headroom for the appliance workload | TBD: 4 phones in BLUFF plus arcade idle under a stated CPU share | `top` or Beszel during A-11 | arcade alone 1.4 to 1.7 cores idle; PS1 starved when co-running | measured (arcade, PS1), unknown (BLUFF on hardware) | prototype: stop the arcade for PS1; retail: size cores for the chosen game set |
| R6 | Video encode for streamed games | N streams at 320x240 or 640x480 at 60 fps | stream stats | each viewer about 14% of a core; capture + encode about 20% | measured (software) | retail: hardware encoder or drop streaming. Whether the Pi 5 has a hardware H.264 encoder is **UNKNOWN**: the repository calls it unverified and the Raspberry Pi page read on 2026-10-12 does not say |
| R7 | Thermal in an enclosure | die under 80 C sustained at warm ambient | enclosed soak, hours, logs of `vcgencmd measure_temp` | open-bench peak 56.9 C | estimated (margin only) | retail |
| R8 | Wi-Fi single-client latency | provisional gate: idle p95 under 80 ms and p99 under 150 ms (WARN above), loss under 0.5% | `wifilab.py gate` (PR #85) | ch36 p99 64 to 99 ms, ch149 p99 140 to 211 ms (one tablet) | measured (one device) | prototype: choose by measurement; retail: antenna and radio specification |
| R9 | Client capacity | six clients (responsive action) and eight (lightweight Party games); ceiling TBD | `wifilab.py multi --counts 1,2,4,6,8,10` with real devices (C-05) | none | unknown | prototype: firmware alternative; retail: a radio with a documented station limit |
| R10 | Four real phones through a game | 4 phones, no intervention | friend-ready AVR-12 and AVR-27 (A-10, A-11) | none | unknown | both |
| R11 | Offline cold boot to joinable | AP and Party Home reachable; time TBD | stopwatch (A-01) | AP self-start after a reboot with `eth0`, 2026-09-24 | unknown (offline) | retail: a boot-to-joinable target. "Power-on to first game under 3 min" appears only as a differentiation target in the product-differentiation finding, not as a requirement |
| R12 | Power-loss recovery | AP and Party Home back with no command | pull-power test (A-18) | none | unknown | retail: power-fail-safe storage |
| R13 | Regulatory and channel | legal in each sales region | `iw reg get`, certification | US observed (DFS-FCC) | unknown | retail: region SKUs |
| R14 | BLE coexistence | no RTT p99 regression with BLE active | AVR-301 with and without BLE | none | unknown | retail |
| R15 | Time without an RTC | tickets and logs sane after an offline cold start | A-21 | observed unplanned 37 h step, effect unobserved (baseline) | unknown | retail: RTC (AVR-79 options in offline-acceptance "Clock policy") |
| R16 | Secure boot, identity, key storage, A/B | the requirement list in section 8 | design review AVR-423, AVR-82, AVR-67 | none (SD, `0600` files) | unknown | retail |
| R17 | Wi-Fi station observability | per-station retry and channel utilisation | AP firmware capability | brcmfmac gives `tx failed` only; the survey is empty | measured (limitation) | retail: an AP stack with survey and ACS |

## 10. Cheapest next measurements on the existing prototype

None changes the production radio configuration; each is owner-run.

1. Inline USB power meter between PSU and Pi: idle, 4 phones, BLUFF, arcade (R3, R4; no software change).
2. Read-only configuration facts, most already captured on 2026-10-12: `iw reg get`, `iw dev wlan0 info`,
   `update-alternatives --display cyfmac43455-sdio.bin`, `iw dev wlan0 get power_save`, `timedatectl`.
3. Cold-boot sampling: 5 cold boots with a per-second throttle sampler, watching the first 60 s (R2).
4. Offline cold boot with Ethernet out (A-01 to A-09; R11).
5. Four-phone session with `tools/radio-watch` and the topology check (R10; first real station-count evidence).
6. Single-device channel comparison with `wifilab.py gate` (needs PR #85; the channel is observed, not changed) and a
   second device (AVR-300) to separate board from tablet.
7. Enclosed thermal soak: the Pi in a cardboard or plastic box with a running arcade stream for 2 h, logging
   temperature (no software change).
8. A power-pull test (A-18) with fresh backups.
9. Later and only with owner approval: AP power-save A/B (`iw dev wlan0 set power_save off` is a runtime setting
   that reverts on reboot, but it is a network change).

## Sources

Repo: `docs/findings/2026-09-24-{new-psu-power-baseline,no-usb-power-baseline,ps1-bomberman-party-slice,ps1-latency,party-network-and-offline-mode,product-differentiation}.md`; `docs/findings/2026-10-02-architecture-{audits,review}.md`; `docs/findings/2026-10-12-deployed-baseline.md`; `docs/runbooks/{network,party-load-test,party-https}.md`; `docs/design/LIMITED-MODE.md`; `deploy/appliance-inventory.json`; `avrana-party.nginx`; `avrana-captive.conf`; `docs/research/BLE-OWNER-CONTROL-PLANE-SPIKE.md`; `docs/ROADMAP.md`. On PR #85 only: `docs/runbooks/wifi-qualification.md`, `docs/findings/2026-10-06-wifi-channel-36-vs-149.md`.

External, re-read 2026-10-12 (not measured here): Raspberry Pi documentation <https://www.raspberrypi.com/documentation/computers/raspberry-pi.html> (Pi 4 Model B: 5 V at 3 A; throttling 80 to 85 C; Bluetooth 5 and BLE; read characters 0 to 100,000 of 275,764; PD, chip name, operating range and Pi 5 encoder not stated in the part read); DietPi forum <https://dietpi.com/forum/t/wifi-hotspot-number-of-clients-limited/18401> (Pi 3B+, 7-client limit, minimal firmware, 11 devices; "19" unverified by the author). **Dropped:** the Infineon community thread on concurrent dual-band AP (HTTP 403, not verified).
