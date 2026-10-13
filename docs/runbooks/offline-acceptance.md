# Runbook: owner offline acceptance (AVR-10, AVR-11, AVR-12, AVR-27, AVR-29, AVR-31, AVR-33, AVR-79, AVR-212, AVR-296, AVR-301, AVR-43)

Status: **PROPOSED owner-run procedure, NOT RUN on the appliance** (2026-10-12).

Core promise: **power on one Avrana appliance, connect ordinary phones, start playing. No internet, no
guest app, no external display, no technical intervention.** This runbook is the reproducible way to
find out, with real hardware and real phones, how far that promise holds. It was reviewed against
`origin/main` Party `04c5844` and the read-only capture in
[the 2026-10-12 baseline](../findings/2026-10-12-deployed-baseline.md). Every test below is `NOT RUN`.
Nothing here is evidence. Nothing in CI, in an agent's task or in this document authorizes running a step
on the appliance; every physical step is an owner action, and an agent cannot close any listed issue.

What this adds to [friend-ready-acceptance](friend-ready-acceptance.md) (PR #98) is breadth: that packet
is one deploy-and-test sitting with record sheets, backups and rollback. **This runbook does not repeat
its record sheets or its deploy, backup and rollback steps; it links to them.** Where a test here says
"friend-ready step N" it means that packet's step. Where a script's `--help` disagrees with this file,
the script wins. Network facts: [network](network.md). Procedures it relies on:
[deploy](deploy.md), [party-https](party-https.md), [logs-and-retention](logs-and-retention.md),
[games-fork-deploy](games-fork-deploy.md), [provision-game](provision-game.md),
[install-game](install-game.md), [prepare-native-games](prepare-native-games.md),
[game-origin](game-origin.md), [service-users-migration](service-users-migration.md).

## Rules that apply to every test

- **Evidence tiers** (see [TESTING](../TESTING.md)): T1 unit, T2 real process or browser, T3 physical
  appliance, T4 real iPhone or Android. Every test here is T3, and the phone tests are T4. A merged PR is
  not a deployment; a `curl` is not a phone test; a green CI run is not appliance evidence.
- **Nothing in the base procedure changes the Pi's configuration.** The base tests only read, reboot,
  restart a unit, or cut power. Three kinds of step are marked and kept out of the base tests:
  `OWNER INSTALL` (changes the Pi; needs `sudo`; has its own reverse), `OWNER DECISION` (the owner must
  decide before it is allowed) and `LAB` (needs a tool or branch that is not installed). **No test
  instructs a Wi-Fi channel change.** Recording the channel is acceptance (A-22); changing it is a
  separate owner decision (Linear AVR-299).
- **`sudo` is always said out loud.** The SSH user (`cody`) has no passwordless sudo, so a `sudo` step is
  typed by the owner with a terminal (`ssh -t`). No secret ever goes on a command line.
- **No SSH polling during measured steps** (power, throttle, load): an SSH session start is a CPU burst
  that triggered under-voltage dips on 2026-09-24
  ([new-psu-power-baseline](../findings/2026-09-24-new-psu-power-baseline.md)). Read once at each
  checkpoint.
- **Read the pins at run time.** Do not trust any SHA written in a document. Record the Party and Games
  SHAs from `/party/api/status` in the run header (see "Revision rule").
- **Never record or paste:** Wi-Fi names or passwords, keys, cookies, tickets, device ids, lease files,
  raw nginx logs, TLS or NetworkManager backups, a raw journal. Read an excerpt first and redact. Keep raw
  files on the Pi or the laptop, outside Git.
- **Stop conditions** are those of friend-ready-acceptance ("Stop conditions"): a certificate warning on any
  phone, `vcgencmd get_throttled` other than `0x0` during a measured step, any use of `--skip-smoke`,
  `--force-busy`, `--allow-dirty` or `--allow-branch`; this runbook adds: an access point that is not up
  within 5 minutes of power-on.
- **Where commands run.** `LAPTOP` = a laptop joined to the Party Wi-Fi (or on the home LAN where a test
  says so). `PI` = on the Pi: from the laptop as `ssh 10.42.0.1 '...'` while the Party Wi-Fi is the path, or
  `ssh party '...'` (alias for `10.0.0.142`, `eth0`) while the Ethernet cable is plugged in. Offline tests
  unplug `eth0`, so the alias stops working: use `10.42.0.1`. On Windows use `python`, never `python3`.

## Revision rule

Each test has a **Revision** field:

| Revision | Meaning |
|---|---|
| **DEPLOYED** | Meaningful on what runs today without a deploy: Party `c59f1c8`, Games `a448972`, deployed 2026-10-06, read from `/party/api/status` on 2026-10-12 ([baseline](../findings/2026-10-12-deployed-baseline.md)). Re-read the SHAs at run time. |
| **MAIN** | Needs an owner deployment of `origin/main` first (Party `04c5844`, Games `2ee23e6` on 2026-10-12; main was 120 Party commits ahead of the Pi). Do not run before; record "not run: not deployed". |
| **PR #N** | Needs that pull request deployed. Named in the test. PRs #85, #108, #109 and #110 merged into main on 2026-10-12 after this procedure was written (Party main `14a0278`, Games `282c620`): tests that name them now need only an owner deployment of that main or later, and where a step says a file exists only on a PR's branch, it is on main. |

The ADR 0011 console model **is** in the deployed revision: `git merge-base --is-ancestor ff32bb4 c59f1c8`
is true (checked 2026-10-12; `ff32bb4` is the merge of PR #34, committed 2026-09-29 19:28 PDT). Phone
proof of it is still missing (A-14).

`ops/deploy.sh` never installs the nginx site file or the dnsmasq drop-in (friend-ready step 3). On
2026-10-12 the installed nginx site was byte-identical to the deployed checkout's `avrana-party.nginx`,
and therefore lacks the 120 lines main added. Before any test that depends on routing, run (read-only):

```bash
# PI: do the installed network files equal the deployed checkout's? (no sudo)
cmp /etc/nginx/sites-available/avrana-party /home/cody/avrana-party/avrana-party.nginx && echo nginx-same
cmp /etc/NetworkManager/dnsmasq-shared.d/avrana-captive.conf /home/cody/avrana-party/avrana-captive.conf && echo dns-same
```

## Starting facts (read-only, 2026-10-12, not a test result)

From [the baseline](../findings/2026-10-12-deployed-baseline.md). They are the state the tests start from,
and every one must be re-read at run time.

| Fact | Value on 2026-10-12 |
|---|---|
| AP | `wlan0` AP, channel **36** (5180 MHz), 20 MHz; the 2026-09-24 table in `docs/runbooks/network.md` says 149 (dated note added there) |
| Clock | `systemd-timesyncd` enabled and active; no RTC; no `fake-hwclock`, no `chrony`; at the last boot the clock began about 37 h behind and stepped when NTP answered |
| Journal | volatile (`Storage=volatile` from the Raspberry Pi OS drop-in); one boot in the journal |
| NetworkManager | 1 wifi profile autoconnect yes (priority 100), 3 wifi profiles autoconnect no, 1 ethernet autoconnect yes (priority 100) |
| Certificate | served certificate valid 2026-09-26 to 2026-12-25 (Let's Encrypt); status block says `unavailable`; renewal timer not installed |
| Service users | not migrated: `User=cody` |

## Sessions

| Session | Precondition | Tests |
|---|---|---|
| **A: no deploy** | The appliance as it is: Party `c59f1c8`, Games `a448972`. | A-01 to A-26 |
| **B: after deploying main** | Owner has deployed `origin/main` (friend-ready steps 1 to 4), service-user migration and game origin done where a test says so. | B-01 to B-08 |
| **C: after named PRs** | The PR named in the test is merged **and** deployed. | C-01 to C-08 |

Sessions are independent: a physical sitting can do all of A in one evening; B and C are separate
deployments. Do the destructive-feeling tests last within a session (power interruption, reboot).

### Run header (fill once per session)

- [ ] Date / place / operator / observer: ____
- [ ] Party SHA and Games SHA (from `curl --noproxy '*' -s https://party.avrana.net/party/api/status | python -m json.tool`, fields `party.deployed_sha` and `games.deployed_sha`; `dirty` must be false): ____
- [ ] Phones: model, OS version, browser and version for each; mobile data OFF, VPN OFF, Android Private DNS off or Automatic, iCloud Private Relay off, date and time set automatically: ____
- [ ] `iw dev wlan0 info | grep -E 'type|channel'` (record, never change): ____
- [ ] `vcgencmd get_throttled` (run as `timeout 5 vcgencmd get_throttled`; a hang is itself a FAIL of A-09) is `0x0`, and `journalctl -k -b | grep -icE 'undervoltage|voltage normalis'` is 0: ____
- [ ] Fresh backups taken (friend-ready step 1): ____
- [ ] Stop conditions read and accepted: ____

### Results tables (fill in; `NOT RUN` until a person runs it)

**Session A**

| ID | Date | Operator | Party / Games SHA | Result | Evidence file | Notes |
|---|---|---|---|---|---|---|
| A-01 Offline cold boot | | | | NOT RUN | | |
| A-02 Services and status after offline boot | | | | NOT RUN | | |
| A-03 DHCP lease per phone | | | | NOT RUN | | |
| A-04 DNS offline | | | | NOT RUN | | |
| A-05 Captive probes, Pi side | | | | NOT RUN | | |
| A-06 Captive portal and first onboarding, iPhone | | | | NOT RUN | | |
| A-07 Captive portal and first onboarding, Android | | | | NOT RUN | | |
| A-08 HTTPS and certificate as phones see it | | | | NOT RUN | | |
| A-09 Power and throttle through the boot | | | | NOT RUN | | |
| A-10 Four phones associate and stay up | | | | NOT RUN | | |
| A-11 Four phones through a full game | | | | NOT RUN | | |
| A-12 Phone sleep, Wi-Fi toggle, host out of range | | | | NOT RUN | | |
| A-13 Host succession | | | | NOT RUN | | |
| A-14 Console model on real phones | | | | NOT RUN | | |
| A-15 Gauntlet II on a real phone | | | | NOT RUN | | |
| A-16 Restart each service | | | | NOT RUN | | |
| A-17 Full reboot mid-party | | | | NOT RUN | | |
| A-18 Power interruption (idle, mid-game, during a join) | | | | NOT RUN | | |
| A-19 Diagnostics survive a reboot | | | | NOT RUN | | |
| A-20 A phone with a wrong clock | | | | NOT RUN | | |
| A-21 The Pi with a wrong clock after an offline boot | | | | NOT RUN | | |
| A-22 Record the actual AP channel | | | | NOT RUN | | |
| A-23 Power consumption | | | | NOT RUN | | |
| A-24 Battery runtime | | | | NOT RUN | | |
| A-25 Game process failure today (LAN Games and BLUFF) | | | | NOT RUN | | |
| A-26 Games bundle staging, offline | | | | NOT RUN | | |

**Session B**

| ID | Date | Operator | Party / Games SHA | Result | Evidence file | Notes |
|---|---|---|---|---|---|---|
| B-01 Native game lifecycle (Checkers) | | | | NOT RUN | | |
| B-02 Checkers on two phones, iPhone and Android | | | | NOT RUN | | |
| B-03 Native game process failure (Checkers unit) | | | | NOT RUN | | |
| B-04 Restart the native units and Party Core's socket | | | | NOT RUN | | |
| B-05 `.avrgame` install, list, verify, remove (Hello Party) | | | | NOT RUN | | |
| B-06 Offline software upgrade: Games bundle switch | | | | NOT RUN | | |
| B-07 Offline software upgrade: Party (known gap) | | | | NOT RUN | | |
| B-08 Service-user migration leaves the party working | | | | NOT RUN | | |

**Session C**

| ID | Date | Operator | PR deployed | Result | Evidence file | Notes |
|---|---|---|---|---|---|---|
| C-01 Certificate expiry visible in status | | | #108 | NOT RUN | | |
| C-02 Renewal timer: install, safe run, enable | | | #108 | NOT RUN | | |
| C-03 Installed package appears in Party Home | | | catalog overlay branch | NOT RUN | | |
| C-04 Wi-Fi gate on the channel in use | | | #85 | NOT RUN | | |
| C-05 Client capacity 1 to N | | | #85 | NOT RUN | | |
| C-06 Pi health check states | | | #85 (AVR-297 install) | NOT RUN | | |
| C-07 Quiet host keeps the seat; stale nginx detected | | | #109, #110 | NOT RUN | | |
| C-08 Game process failure after session-recovery work | | | none; behaviour exists only on an unmerged branch | NOT RUN | | |

---

# Session A: no deploy needed (Party `c59f1c8`, Games `a448972`)

## A-01 Offline cold boot: the access point and Party Home come up unaided

- **Serves:** AVR-10 (and AVR-79 for the clock). **Revision:** DEPLOYED.
- **Prerequisites:** fresh backups; no session live; a laptop and two phones on hand; `eth0` is the only
  management path from home, so SSH from home is lost until the cable goes back (network.md: never take
  `eth0` down during a remote session).
- **Steps:**
  1. PI, before: `nmcli -f NAME,UUID,TYPE,AUTOCONNECT,AUTOCONNECT-PRIORITY connection show`;
     `timedatectl`; `date -u`; `timeout 5 vcgencmd get_throttled`;
     `journalctl -k -b | grep -icE 'undervoltage|voltage normalis'`; `journalctl --list-boots`.
     Record the laptop's own `date -u` at the same moment.
  2. PI: `sudo poweroff` (type the sudo password: `ssh -t party 'sudo poweroff'`). Wait for the green light
     to stop. **Unplug the Ethernet cable.** Wait 30 seconds. Apply power. Start a stopwatch. Touch nothing:
     no keyboard, no screen, no SSH.
  3. LAPTOP: watch for the SSID "Avrana Party". Note the stopwatch time it appears.
  4. LAPTOP joined to it, once: `ssh 10.42.0.1 'ip -br addr; ip route; nmcli -t -f GENERAL.CONNECTION device show wlan0; iw dev wlan0 info | head -8'`
     and `ssh 10.42.0.1 'ping -c1 -W3 1.1.1.1 >/dev/null 2>&1 && echo UPSTREAM-PRESENT || echo no-upstream'`.
  5. Open `https://party.avrana.net/party/` on the laptop and note the stopwatch time Party Home is shown.
- **Expect:** SSID visible; `wlan0` type AP at `10.42.0.1/24`; no default route; the ping fails
  (`no-upstream`); Party Home loads.
- **Evidence to capture:** stopwatch times (SSID, Party Home); the command output with addresses left in
  (they are private) but no Wi-Fi password; the profile name that `nmcli` reports for `wlan0`; a photo of
  any phone error.
- **Pass / fail:** PASS: SSID visible within 5 minutes with no intervention, `wlan0` is the AP, no
  upstream, Party Home loads. FAIL: `wlan0` came up as a client of a home Wi-Fi, no SSID within 5 minutes,
  or Party Home does not load. Only one of the four wifi profiles autoconnects on 2026-10-12, which is
  the opposite of the boot race `network.md` warns about; a FAIL here means that observation was wrong
  for this boot, so record the profile table.
- **Earlier evidence:** the AP came up by itself after the owner's reboot at 11:16 on 2026-09-24
  (network.md "Verified facts"), with `eth0` present and the `eth0` profile rewritten after that boot
  ([party-network-and-offline-mode](../findings/2026-09-24-party-network-and-offline-mode.md)). The
  unrecorded reboot at 2026-10-09 22:59 PDT was with Ethernet present and is not an offline proof
  ([baseline](../findings/2026-10-12-deployed-baseline.md)). A cold boot without a cable: never.
- **Status:** `NOT RUN`.

## A-02 Services and status after the offline boot

- **Serves:** AVR-10. **Revision:** DEPLOYED.
- **Prerequisites:** A-01 done; the Pi has not been touched since.
- **Steps:** LAPTOP: `ssh 10.42.0.1 'systemctl is-active avrana-party-core avranaparty-games avranaparty-arcade nginx NetworkManager'`;
  `curl --noproxy '*' -s https://party.avrana.net/party/api/status | python -m json.tool`.
- **Expect:** all `active`; status `summary.state` `ok` (with the note that the certificate timer is not
  installed); `party.deployed_sha`, `games.deployed_sha` equal the pins in the header; `party_core.members`
  0 and `session` null (a rebooted Party Core starts an empty party by design).
- **Evidence:** the JSON (it carries no secret; check before pasting).
- **Pass / fail:** PASS if all of the above. FAIL: any unit not active, or `summary.state` other than `ok`.
- **Earlier evidence:** Party Core's SIGKILL recovery and restart, 2026-09-29, Party `6bd5af4`
  ([party-core-deploy](../findings/2026-09-29-party-core-deploy.md)). Self-start of all units after a cold
  boot with no upstream: never. The 2026-10-09 boot left all units active with Ethernet present
  (baseline).
- **Status:** `NOT RUN`.

## A-03 DHCP lease per phone

- **Serves:** AVR-10, AVR-12. **Revision:** DEPLOYED. (The DHCP service is NetworkManager's dnsmasq; no Party
  code is involved.)
- **Steps:** each phone forgets and rejoins "Avrana Party". On the phone note its IP, gateway and DNS. PI,
  once afterwards: `wc -l < /var/lib/NetworkManager/dnsmasq-wlan0.leases` (count only; do not paste the
  file; if it is not readable without sudo, use `sudo` and say so in the record).
- **Expect:** each phone has `10.42.0.x` (range 10.42.0.10 to 10.42.0.254), gateway and DNS `10.42.0.1`;
  the lease count rises by one per phone; no IPv6 (the profile says `ipv6.method ignore`).
- **Pass / fail:** PASS: every phone has a lease within about 10 seconds of joining. FAIL: a phone has a
  self-assigned address or no DNS.
- **Earlier evidence:** range read 2026-09-24 (network.md); a laptop held `10.42.0.46` on 2026-09-28
  ([bluff-party-reconnect](../findings/2026-09-28-bluff-party-reconnect.md)), with `eth0` up. Offline
  lease on a phone: never.
- **Status:** `NOT RUN`.

## A-04 DNS answers offline

- **Serves:** AVR-10. **Revision:** DEPLOYED, but the installed dnsmasq drop-in may differ from main (run the
  `cmp` above and record it).
- **Steps (LAPTOP on the Party Wi-Fi):** `nslookup party.avrana.net 10.42.0.1` (expect `10.42.0.1`);
  `nslookup games.avrana.net 10.42.0.1` (`10.42.0.1` only if the installed drop-in is current; otherwise
  record the actual answer); `nslookup example.com 10.42.0.1` (must not return a public address: record
  SERVFAIL, REFUSED or timeout); and for each of `captive.apple.com`, `connectivitycheck.gstatic.com`,
  `clients3.google.com`, `www.msftconnecttest.com`, `detectportal.firefox.com`:
  `nslookup <name> 10.42.0.1` (expect `10.42.0.1`). With `dig` available the same checks are
  `dig +short @10.42.0.1 <name>`.
- **Pass / fail:** PASS as expected. FAIL: a probe name resolves to a public address (a phone would then
  believe it has internet or send the probe nowhere).
- **Earlier evidence:** probe answers read 2026-09-24 with upstream present, so external-name failure was
  never observed; the `party.avrana.net` host-record was added and a phone check passed 2026-09-25
  ([party-https](party-https.md)). Offline external-name behaviour: never.
- **Status:** `NOT RUN`.

## A-05 Captive probes, Pi side

- **Serves:** AVR-10, AVR-11. **Revision:** DEPLOYED (installed nginx equals `c59f1c8`'s file).
- **What nginx does** (read from `avrana-party.nginx`, the port 80 `default_server`): `/hotspot-detect.html`
  returns 200 with Apple's literal "Success" for any Host. Every other probe path (`/generate_204`,
  `/gen_204`, `/connecttest.txt`, `/redirect`, `/ncsi.txt`, `/success.txt`) falls to `location /`, which
  proxies to the Games server on `127.0.0.1:8096`, a 404 JSON `{"detail":"Not Found"}` on 2026-09-24. `GET /`
  returns a one-link page (not a redirect). Port 443 serves only `party.avrana.net` (and `games.avrana.net`
  on main's file); an HTTPS probe to an intercepted name would see a certificate for a different name and fail.
- **Steps (LAPTOP on the Party Wi-Fi):**
  `curl --noproxy '*' -s -i -H 'Host: captive.apple.com' http://10.42.0.1/hotspot-detect.html`;
  `curl --noproxy '*' -s -o /dev/null -w '%{http_code}\n' -H 'Host: connectivitycheck.gstatic.com' http://10.42.0.1/generate_204`;
  `curl --noproxy '*' -s -i http://10.42.0.1/`.
- **Expect:** 200 "Success"; 404 (record the actual value); 200 with a link to
  `https://party.avrana.net/party/`.
- **Pass / fail:** PASS if as written. FAIL otherwise: record, do not fix in the session.
- **Earlier evidence:** read 2026-09-24 (party-network-and-offline-mode); not re-read since.
- **Status:** `NOT RUN`.

## A-06 Captive portal and first onboarding, iPhone

- **Serves:** AVR-11. **Revision:** DEPLOYED. **Prerequisites:** mobile data OFF; the phone has never joined
  this network (or has forgotten it); the Ethernet cable is out.
- **Steps:** Settings, Wi-Fi, Avrana Party; enter the password from the card; watch what appears (a sheet,
  a notification, nothing); open Safari to `https://party.avrana.net/party/` (type `https://`); set a name
  and avatar; reach Party Home. Do not install anything. Time each step. Repeat once with mobile data ON.
- **Expect (an expectation, not evidence):** no captive-portal sheet, because the Apple probe is answered
  "Success"; the phone marks the network usable; with mobile data on, Wi-Fi Assist may route some traffic
  over cellular.
- **Evidence:** a screen recording that does not show the password; iOS and Safari versions; exact text of
  any sheet; the count of observer interventions (friend-ready "What counts as developer intervention").
- **Pass / fail:** PASS: Party Home reached with no app, no internet, and no explanation from the observer.
  FAIL: a sheet that cannot be dismissed, a certificate warning, or the phone silently staying off the
  network.
- **Earlier evidence:** an iPhone on the Party Wi-Fi saw BLUFF in Party Home and launched it from its tile on
  2026-09-28, Party `3724b34`, Games `c6199be`, device model not recorded
  ([bluff-party-home](../findings/2026-09-28-bluff-party-home.md)). The finding does not say whether the
  Pi had an upstream then; by the 2026-09-24 topology it had (`eth0`). Offline and unprimed: never.
- **Status:** `NOT RUN`.

## A-07 Captive portal and first onboarding, Android

- **Serves:** AVR-11. **Revision:** DEPLOYED. As A-06 on Android Chrome.
- **Additionally record:** whether the phone says "Connected, no internet" or "Stay connected?", what was
  tapped, whether `https://party.avrana.net/party/` loads before and after answering, and whether the phone
  moves traffic to mobile data (turn mobile data ON for a second pass).
- **Expect (not evidence):** the `/generate_204` probe gets 404 (neither success nor portal), so Android
  shows "no internet" and no sign-in page, and may prefer cellular until the prompt is answered. With an
  upstream present Android's parallel HTTPS probe could succeed through NAT; offline both fail.
- **Pass / fail:** PASS: join succeeds and the page loads after the prompt is answered once. FAIL: a
  sign-in page appears and cannot be dismissed, or the phone stays off the network.
- **Earlier evidence:** none on a person's Android on the appliance. An Android tablet was driven by `adb`
  for latency on 2026-10-06, not for onboarding.
- **Status:** `NOT RUN`.

## A-08 HTTPS and the certificate as phones see it

- **Serves:** AVR-10. **Revision:** DEPLOYED.
- **Steps:** on every phone open `https://party.avrana.net/party/`; then `http://10.42.0.1/` (expect the
  one-link page). LAPTOP, no sudo and no root file read:
  `echo | openssl s_client -connect 10.42.0.1:443 -servername party.avrana.net 2>/dev/null | openssl x509 -noout -issuer -dates`
  and `curl --noproxy '*' -s https://party.avrana.net/party/api/origin.json` (expect `"scheme":"https"` and
  `"serverAddr":"10.42.0.1"`). Do **not** read `/etc/avrana-party/tls/current/fullchain.pem`: that directory
  is root-only and reading it needs `sudo`.
- **Pass / fail:** PASS: no warning on any phone; record `notAfter` and the days left; the status check
  degrades the summary below 21 days (about 2026-12-04). FAIL: a warning page. Do not tap through it.
- **Note:** ADR 0004's HTTPS-only `/party/` is partly superseded by ADR 0012 (Limited Mode), which is
  not deployed: a phone whose HTTPS fails has no fallback (friend-ready decision D6).
- **Earlier evidence:** a phone check passed 2026-09-25 (party-https "Deployment evidence"); laptop Wi-Fi
  validation was open then. Since the 2026-10-06 deploy: never on a phone. Served certificate on
  2026-10-12 via `openssl s_client` over `eth0`: notBefore 2026-09-26, notAfter 2026-12-25 (baseline).
- **Status:** `NOT RUN`.

## A-09 Power and throttle through the boot

- **Serves:** AVR-10, AVR-43. **Revision:** DEPLOYED.
- **Steps:** at the start of A-01 and at the end of the sitting (two SSH reads, nothing in between):
  `ssh -t 10.42.0.1 'timeout 5 vcgencmd get_throttled; journalctl -k -b | grep -icE "undervoltage|voltage normalis"; sudo tail -n 5 /var/log/avrana/pi-throttle.jsonl'`
  (`sudo` for the telemetry file).
- **Pass / fail:** PASS: `0x0` and 0 kernel lines (two lines make one dip). FAIL: any dip, or
  `get_throttled` does not answer within 5 seconds (a wedged firmware mailbox; see C-06).
- **Earlier evidence:** 0 dips over 3 h 26 min on 2026-09-24 with no USB adapter
  ([no-usb-power-baseline](../findings/2026-09-24-no-usb-power-baseline.md)); **cold-boot inrush was listed
  "not tested"**. The 2026-10-06 wedged mailbox hid the throttle state until a reboot
  (`origin/feat/avr-296-wifi-qualification:docs/findings/2026-10-06-wifi-channel-36-vs-149.md`). One idle
  reading `0x0`, 31.6 C on 2026-10-12 (baseline).
- **Status:** `NOT RUN`.

## A-10 Four phones associate and stay up

- **Serves:** AVR-12. **Revision:** DEPLOYED.
- **Prerequisites:** at least one iPhone and one Android among the four; the Ethernet cable out for the
  offline version (and one pass with it in is allowed, labelled).
- **Setup** (adds two files under `~/avrana-lab` on the Pi; changes no service): LAPTOP in the repository,
  `scp tools/radio-watch tools/avrana-topology-check 10.42.0.1:avrana-lab/`. Run the topology check
  **before** any phone joins, not during a power measurement: `ssh 10.42.0.1 '~/avrana-lab/avrana-topology-check'`
  (prints PASS, FAIL, WARN; the exit status is the number of FAILs).
- **Steps:** start detached: `ssh 10.42.0.1 'setsid -f ~/avrana-lab/radio-watch 1500 10 ~/avrana-lab/accept-radio.jsonl </dev/null >/dev/null 2>&1'`.
  Join the four phones one at a time with a stopwatch. Use Party Home, Library and a game's detail page for
  15 minutes; lock and unlock one phone; walk one to the edge of the room and back. Afterwards, once:
  `iw dev wlan0 station dump | grep -c '^Station'`; `wc -l < /var/lib/NetworkManager/dnsmasq-wlan0.leases`;
  `journalctl -u NetworkManager -u avrana-party-core --since "<start>" --no-pager | grep -iE 'deauth|disassoc|timeout|dhcp' | head -40`;
  `timeout 5 vcgencmd get_throttled`.
- **Expect / pass:** four stations associated at the same time; each phone reaches Party Home on the first or
  second attempt; no unexplained deauthentication; no phone silently on mobile data. Record the **observed**
  maximum, not a reported one.
- **Fail:** a phone cannot join while three are connected (a possible station limit; see C-05), or a
  deauthentication storm.
- **Earlier evidence:** two phones associated during the 2026-09-24 power runs; no capacity claim. Four
  phones: never.
- **Status:** `NOT RUN`.

## A-11 Four phones through a full game

- **Serves:** AVR-27, AVR-12. **Revision:** DEPLOYED (BLUFF, served by Games `a448972`).
- **Prerequisites:** A-10 passed or in progress; at least one Android and one iPhone among four distinct
  people (the observer does not drive any phone); upstream unplugged.
- **Steps:** friend-ready step 8, the four-human BLUFF observer script, unchanged: the Host launches BLUFF
  from Party Home, everyone plays to a result, one phone locks for 15 to 20 seconds mid-round, and the party
  returns to a sane Home. Record intervention counts using friend-ready's table.
- **Expect:** all four reach the game; the lock/wake phone keeps its seat; a result appears; Home is sane.
- **Pass / fail:** friend-ready AVR-27 criteria (the record sheet there is the record). FAIL: a phone
  stranded outside Avrana, a seat lost, or an intervention the observer could not avoid.
- **Earlier evidence:** none with four humans. Chromium four-phone tests (T2) exist and say nothing about
  phones.
- **Status:** `NOT RUN`.

## A-12 Phone sleep, Wi-Fi off and on, host out of range

- **Serves:** AVR-12, AVR-23. **Revision:** DEPLOYED.
- **Steps (each on an iPhone and an Android, during A-11 or a lobby with the Host and a guest):**
  1. Lock the phone 15 to 20 seconds; unlock.
  2. Lock for 60 seconds; unlock.
  3. Wi-Fi off 10 seconds, then on.
  4. **The host's phone** walks out of range (or Wi-Fi off) for about 20 seconds (inside the 45 s liveness
     window), then for about 2 minutes (past the 45 s window plus the 30 s host grace); then returns.
  5. Reload the page.
  Record, per phone, the seat, name, whether Party Home shows the member as `here`, and whether the phone is
  still on the Avrana network.
- **Expect:** same seat and identity after 1 to 3 and after the short absence in 4, with no manual re-join.
  After the 2-minute absence the Host role has moved (A-13). If Party Core was restarted the party is empty
  by design (the party is memory-only; the device identities persist in `devices.json`). Count that as a fail
  only if the restart was not deliberate.
- **Pass / fail:** PASS as written. FAIL: a returning phone appears as a watcher, a stranded page, or a
  manual re-join was needed.
- **Earlier evidence:** an iPhone with Safari on the Pi lab harness at `http://10.42.0.1:8190` over the Party
  Wi-Fi on 2026-09-28: a 15 s lock, Wi-Fi off about 10 s, and a host-ends-while-locked all passed (Games
  `0ddc6cb`, device model and iOS version not recorded;
  [bluff-party-reconnect](../findings/2026-09-28-bluff-party-reconnect.md)). The production HTTPS path and
  Android: never.
- **Status:** `NOT RUN`.

## A-13 Host succession

- **Serves:** AVR-12. **Revision:** DEPLOYED for the behaviour; **PR #109** changes what counts as the host
  being present (a host action refreshes presence). Record which was deployed.
- **Steps:** with three phones present and a known join order, turn the host's phone's Wi-Fi off for 2
  minutes (longer than 45 s liveness plus 30 s grace, `docs/design/PARTY-LIFECYCLE.md`). Watch the other
  phones' Party Home. Turn Wi-Fi back on.
- **Expect (design, from PARTY-LIFECYCLE):** the earliest-joined eligible member present becomes host; the
  returning old host does not take the role back; a host who is playing in a game keeps the role.
- **Pass / fail:** PASS: exactly one host at every moment shown on every phone and the role moved as
  described. FAIL: no host, two hosts, or the old host regains the role.
- **Earlier evidence:** logic is covered by unit and Chromium tests (T1, T2). Real phones: never.
- **Status:** `NOT RUN`.

## A-14 Console model on real phones

- **Serves:** AVR-212. **Revision:** DEPLOYED (the ADR 0011 merge is an ancestor of `c59f1c8`).
- **Steps (two or more phones, one iPhone and one Android):** the Host moves the location (home, setup, game,
  results); every phone follows; the host-only Party Home action from results; End sends everyone home; a guest
  cannot end; reload and lock mid-state.
- **Pass / fail:** PASS: every phone shows the same location within a few seconds, recorded per phone. FAIL:
  a phone that does not follow or a guest that can end.
- **Earlier evidence:** the console model was verified server-side on 2026-09-29; the 2026-10-06 redesign
  acceptance used Chromium only ([slice 1](../findings/2026-10-06-ux-redesign-slice-1-acceptance.md)). Phone
  proof: never.
- **Status:** `NOT RUN`.

## A-15 Gauntlet II on a real phone

- **Serves:** AVR-92. **Revision:** DEPLOYED.
- **Steps (production HTTPS Party flow):** Play, a picture appears; touch controls; sound controls;
  reconnect and an explicit Leave; browser Back does not strand the phone outside Avrana; note any encoder
  stall and its recovery. Do not run it during a power measurement: the arcade uses about 1.4 to 1.7 cores
  with nobody playing.
- **Earlier evidence:** the stall watchdog and Party-launch fixes were deployed 2026-09-29
  ([gauntlet-launch](../findings/2026-09-29-gauntlet-launch.md); the failing symptom was a real iPhone on
  2026-09-28). The repaired launch on a phone: never.
- **Status:** `NOT RUN`.

## A-16 Restart each service

- **Serves:** AVR-33. **Revision:** DEPLOYED. **OWNER DECISION** (each restart briefly interrupts that
  service); only with no live game and an empty party.
- **Steps:** for each of `avranaparty-games`, `avranaparty-arcade`, `nginx`, then `avrana-party-core`:
  `ssh -t 10.42.0.1 'sudo systemctl restart <unit>'`; after about 10 seconds
  `systemctl is-active <unit>`; `python3 -m avrana.ops.smoke` (from `/home/cody/avrana-party`); and the
  status JSON. For `avrana-party-core` also `systemctl show -p NRestarts,ActiveEnterTimestamp avrana-party-core`.
  Do **not** restart `NetworkManager` (it drops the access point and every phone).
- **Expect:** each unit active again; unrelated units untouched; status `ok`; Party Core comes back with an
  empty party (memory-only) and the same device identities.
- **Pass / fail:** PASS: as written and phones can re-enter Party Home. FAIL: a unit does not return or an
  unrelated service stops.
- **Earlier evidence:** Party Core clean restart, SIGKILL recovery, rollback and roll-forward on 2026-09-29,
  Party `6bd5af4` ([party-core-deploy](../findings/2026-09-29-party-core-deploy.md)). Games, arcade and nginx
  deliberate restarts under acceptance: never.
- **Status:** `NOT RUN`.

## A-17 Full appliance reboot mid-party

- **Serves:** AVR-33, AVR-10. **Revision:** DEPLOYED. **OWNER DECISION.**
- **Prerequisites:** four phones joined and in a lobby (no game running), upstream unplugged.
- **Steps:** note the time; `ssh -t 10.42.0.1 'sudo reboot'`; start a stopwatch; touch nothing; watch each
  phone.
- **Expect (design, not evidence):** the access point returns; phones that remember the network rejoin (some
  may jump to a saved home Wi-Fi: the 2026-10-06 finding saw a tablet do exactly that when the AP dropped); the
  party is empty and members must re-enter; Party Home loads.
- **Pass / fail:** PASS: within 5 minutes of power-on the access point is up and a phone reaches Party Home
  and can start a new game with no command on the Pi. Record how long each phone took to rejoin. FAIL: the AP
  does not return or `wlan0` is a client.
- **Earlier evidence:** none for a deliberate mid-party reboot.
- **Status:** `NOT RUN`.

## A-18 Power interruption: idle, mid-game, during a join

- **Serves:** AVR-10, AVR-33. **Revision:** DEPLOYED. **OWNER DECISION and the only deliberately unclean
  test here.** It can damage the SD card or the files below; take friend-ready step 1 backups first.
- **Three cases, each followed by the same checks:** (a) pull the power lead while idle; (b) pull it
  mid-game with four phones in BLUFF; (c) pull it while a fifth device is in the middle of joining (after its
  first page load, before it has a seat). Wait 10 seconds, reapply, stopwatch, touch nothing.
- **Checks afterwards (read-only):**
  ```bash
  # PI, after the boot
  journalctl --list-boots                                    # volatile journal: only the new boot may be listed (A-19)
  journalctl -k -b | grep -iE 'ext4|mmc|I/O error' | head    # filesystem complaints
  python3 -c "import json,os;p='/var/lib/avrana-party-core/devices.json';d=json.load(open(p));print('devices',len(d),oct(os.stat(p).st_mode&0o777))"
  ls -A /var/lib/avrana-party-core/ | grep -c '^\.devices-'   # leftover temporary files from an interrupted write
  cd /home/cody/avrana-party && python3 -m avrana.ops.manifest validate /var/lib/avrana-party/deployment.json && echo manifest-ok
  python3 -m avrana.ops.smoke
  ```
  (`devices.json` is read as `cody`, who owns it; the command prints a count and a mode, never a hash.)
- **Expect:** the AP and Party Home return unaided; `devices.json` parses as an object and is mode `600`;
  the manifest validates; no `ext4` or `mmc` errors. The party and the game session are **gone** (memory-only);
  phones must re-enter.
- **Pass / fail:** PASS: as expected and a phone can start a new game with no command on the Pi.
  FAIL: the AP does not return; `devices.json` unreadable or empty; `manifest validate` fails; a filesystem
  error. On the deployed code an unreadable `devices.json` makes Party Core refuse to start (the loader raises);
  PR #109 sets such a file aside instead. **Do not corrupt the file deliberately in production**; that case is
  covered by unit tests (T1) in #109.
- **Why these files:** `devices.json` is written by a temporary file and `os.replace` (the old or the new
  file survives) but the deployed code does not `fsync` before the rename; the manifest likewise. PR #109 adds
  the `fsync`. Whether an unflushed rename can leave an empty file after a real power cut on this card is
  **UNKNOWN**; this test is how to find out.
- **Earlier evidence:** one brownout reset happened during PS1 streaming on the old PSU on 2026-09-23
  ([new-psu-power-baseline](../findings/2026-09-24-new-psu-power-baseline.md)); no deliberate pull.
- **Status:** `NOT RUN`.

## A-19 Diagnostics survive a reboot (AVR-29)

- **Serves:** AVR-29. **Revision:** DEPLOYED. **Expected result today: FAIL**, because the journal is volatile
  ([baseline](../findings/2026-10-12-deployed-baseline.md)). The test is the deliberate proof that was missing.
- **Steps:** before A-01: `ssh party 'logger -t avrana-accept "marker before reboot $(date -u +%FT%TZ)"; journalctl --list-boots | tail -2; ls -A /var/log/journal | head -3; journalctl --disk-usage'`.
  After A-01 or A-17: `ssh 10.42.0.1 'journalctl --list-boots | tail -3; journalctl -b -1 -t avrana-accept; journalctl -b -1 -k | tail -3; sudo tail -n 3 /var/log/avrana/pi-throttle.jsonl'`.
- **Expect today:** `--list-boots` shows one boot, `-b -1` finds nothing: the marker and the previous boot's
  kernel lines are gone. The telemetry file in `/var/log/avrana` survives (it is a file, not the journal).
  Whether rsyslog keeps copies under `/var/log` (`ForwardToSyslog=yes`) was not checked: `ls -l /var/log/syslog`
  after the reboot answers it.
- **Pass / fail:** PASS (the AVR-29 acceptance): the previous boot's kernel, service and marker lines are
  present and `journalctl --disk-usage` is within the 256 MB bound. FAIL: any gap. **A FAIL is the expected
  result until `Storage=persistent` is installed** (an owner change on the Pi, not part of this test).
- **Earlier evidence:** none of a reboot proof. `logs-and-retention.md` once recorded the journal as
  persistent; the effective setting is `Storage=volatile`.
- **Status:** `NOT RUN`.

## A-20 A phone with a wrong clock

- **Serves:** AVR-79, AVR-10. **Revision:** DEPLOYED.
- **What is true:** browser TLS validates the certificate against the **phone's** clock, not the Pi's. A
  phone clock before 2026-09-26 or after 2026-12-25 makes the served certificate "not yet valid" or "expired".
- **Steps:** on one phone only, turn off automatic date and time and set the date to 2026-09-01; open
  `https://party.avrana.net/party/`; record the browser's warning text; set it to 2027-01-15 and repeat; set
  the clock back to **automatic** and confirm Party Home loads. (This changes a setting on the owner's phone;
  nothing on the Pi.) Do not tap through a warning.
- **Expect (not evidence):** a certificate warning in both cases; no way into Party Home (no Limited Mode
  fallback is deployed). Join and DHCP still work.
- **Pass / fail:** PASS when the behaviour is recorded and the phone recovers when the clock is automatic.
  This is a characterization, not a promise: record whether the observer could explain the failure.
- **Earlier evidence:** never. [LIMITED-MODE](../design/LIMITED-MODE.md) section 2 records the expectation
  ("Certificate expired or not yet valid (no RTC, wrong clock): browser warning page").
- **Status:** `NOT RUN`.

## A-21 The Pi with a wrong clock after an offline boot

- **Serves:** AVR-79. **Revision:** DEPLOYED. Read "Clock policy" first.
- **Steps:**
  1. After A-01 (Ethernet still out), LAPTOP: `ssh 10.42.0.1 'date -u; timedatectl; journalctl -b -u systemd-timesyncd --no-pager | tail -5'` and the laptop's own `date -u`. Record the offset in minutes.
  2. Run a short game (A-11 or any lobby plus a launch): everything minted and checked inside one boot uses
     one clock.
  3. `OWNER DECISION`, optional, with a throwaway party only: with phones in a lobby, plug the Ethernet
     cable back in so NTP answers and the clock steps. Watch Party Home and the Party Core journal for the
     step: `ssh party 'journalctl -u avrana-party-core --since "-10 min" --no-pager | grep -iE "clock|expired" | head'`.
- **Expect (INFERENCE from the baseline, to be confirmed):** with no upstream the clock stays at the value
  timesyncd saved when the Pi last ran (so the offset equals the time the Pi was off), not 1970; Party works
  because tokens are minted and checked on one clock; log timestamps are wrong. At step 3 a tab whose ticket
  was minted before the step may be refused as `clock` (clock moved backward) or `expired` (forward) and a
  fresh request succeeds once the clock is stable.
- **Pass / fail:** PASS when the offset is recorded and Party works through steps 1 and 2. A refusal at step
  3 that does not recover within a minute is a FAIL and AVR-79 evidence.
- **Earlier evidence:** an unplanned instance: at the boot of 2026-10-09 22:59 PDT the clock began about
  37 hours behind and stepped forward while Party Core was already running
  ([baseline](../findings/2026-10-12-deployed-baseline.md)). Its effect on phones was not observed.
- **Status:** `NOT RUN`.

## A-22 Record the actual AP channel (record only)

- **Serves:** AVR-296 (record), AVR-299 (decision, separate). **Revision:** DEPLOYED.
- **Steps (read-only, no sudo):** `iw dev wlan0 info | grep -E 'type|channel'`; `iw reg get | head -4`;
  `iw dev wlan0 get power_save`; `update-alternatives --display cyfmac43455-sdio.bin | head -3`.
- **Pass / fail:** PASS when the channel is written in the run header and every phone-test record. **This test
  never changes the channel**: every later phone test is channel-dependent, and the 2026-10-06 measurements
  (one tablet, one Pi) found channel 149 much worse than 36 (p99 140 to 211 ms against 64 to 99 ms, tablet TX
  retries 30 to 36 against 0.6 to 0.7 per success). Which channel to run is an owner decision (AVR-299).
- **Earlier evidence:** observed on channel 36, 20 MHz on 2026-10-12; `docs/runbooks/network.md` says 149 in its
  2026-09-24 table; the owner moved it to 36 on 2026-10-06.
- **Status:** `NOT RUN`.

## A-23 Power consumption (inline USB meter)

- **Serves:** AVR-43, AVR-42. **Revision:** DEPLOYED. No watt or ampere measurement exists in the repository.
- **Prerequisites:** a USB-C inline power meter between the PSU and the Pi (a physical change, easily
  reversed); the Pi is shut down cleanly to fit it; the meter's Wh counter reset.
- **Steps:** for each state, let it settle for 2 minutes, then record the meter's volts, amps and watts every
  30 seconds for 5 minutes (a photo or video of the display), reading the Pi **only** at the start and at
  the end of the whole sitting:
  1. Idle, no phones (AP up, Party Core idle).
  2. Idle with four phones associated, on Party Home.
  3. Four phones in a browser game (BLUFF).
  4. Arcade: Gauntlet II with players.
  5. PS1: **lab only** (the PS1 slice runs from the Pi's dev checkout, not the deployed appliance; see
     [ps1-bomberman-party-test](ps1-bomberman-party-test.md)). Mark "not applicable" unless the owner runs
     the lab.
  Before the first state and after the last: `journalctl -k -b | grep -icE 'undervoltage|voltage normalis'`
  and `timeout 5 vcgencmd get_throttled`.
- **Record:** table of state, V, A, W (min, mean, max), temperature if read, dips before and after.
  Inputs, not conclusions: `P_idle_W`, `P_4phones_W`, `P_game_W`, `P_arcade_W`.
- **Pass / fail:** no pass threshold exists (R3 in the
  [hardware brief](../research/hardware-feasibility-brief.md)). FAIL only if the measurement itself caused a
  dip (adding an SSH session mid-state is the usual cause).
- **Status:** `NOT RUN`.

## A-24 Battery runtime

- **Serves:** AVR-43. **Revision:** DEPLOYED. The target runtime is not defined in the repository
  (ROADMAP line 154 only lists "battery runtime" as something to measure).
- **Inputs, to fill in:** `battery_Wh` = ____ (rated; note the pack's model); `converter_efficiency` = ____
  (the pack's 5 V conversion, from its datasheet or a measurement with the meter at pack output); `measured_W`
  = ____ (from A-23, state as stated).
- **Formula:** `runtime_h = battery_Wh x converter_efficiency / measured_W`, computed per state. Write the
  arithmetic out.
- **Optional measured run (OWNER DECISION):** power the Pi from the pack in state 3 of A-23 and **shut down
  cleanly** with `sudo poweroff` at a planned time (for example at 60 percent of the computed runtime); read the
  meter's Wh counter and extrapolate. **Do not run a pack to cutoff**: that is an unclean power loss (A-18).
- **Pass / fail:** none; the result is the computed and the extrapolated figures with their inputs.
- **Status:** `NOT RUN`.

## A-25 Game process failure today (LAN Games and BLUFF)

- **Serves:** AVR-33. **Revision:** DEPLOYED. **OWNER DECISION**; a throwaway party only. The native game
  process (Checkers) is not on the appliance yet: that is B-03.
- **Steps:** with four phones in a BLUFF round, `ssh -t 10.42.0.1 'sudo systemctl kill -s KILL avranaparty-games; sleep 5; systemctl is-active avranaparty-games'`.
  Watch every phone for two minutes. Then the status JSON and
  `journalctl -u avranaparty-games -u avrana-party-core --since "-5 min" --no-pager | tail -40`.
- **What should be seen today (a reading of the source, to be confirmed here):** systemd restarts the games
  service (`Restart=on-failure`); the BLUFF page loses its WebSocket and tries to reconnect; the Games server
  restarts empty, so the round is lost. Whether Party Core's session leaves `active` by itself is **UNKNOWN**:
  the only source paths that close a session are the game reporting `abandoned`, the host ending it, or the 60 s
  launch timeout; Party Core does not poll a game's liveness in the code read. Record what each phone shows
  and what the Host can do (End must work and return everyone home).
- **Pass / fail:** PASS: the service returns, no unrelated service is touched, and the Host can end the stale
  session and start another. FAIL: the Host cannot recover without a command on the Pi.
- **Expected after the AVR-33 follow-up:** no branch carries game-process-failure handling today. The brief's
  branch name `fix/avr-33-session-recovery` does not exist; PR #109
  (`fix/avr-33-party-recovery-hardening`) changes presence for a quiet host and the handling of a damaged
  device store, not a dead game process. Anything about an automatic session end on game death is a future
  change and must not be assumed.
- **Status:** `NOT RUN`.

## A-26 Games bundle staging with no internet

- **Serves:** AVR-33 (operations), AVR-82/AVR-32 (update path). **Revision:** DEPLOYED. The Games fork reaches
  the Pi as a `git bundle`, because the Pi's GitHub key reads only the Party repository.
- **Steps (stage only, no sudo, no effect on the live service; games-fork-deploy.md section 1):** LAPTOP, in a
  Games checkout (read from `origin/main`, never from a stale working branch):
  `git fetch origin && git bundle create avrana-party-games.bundle origin/main && git bundle verify avrana-party-games.bundle`;
  `scp avrana-party-games.bundle 10.42.0.1:`; PI: `git bundle verify ~/avrana-party-games.bundle` and then
  `rm ~/avrana-party-games.bundle`. Do not switch the running service in this test (that is the "Switch"
  step and a deployment: B-06).
- **Pass / fail:** PASS: the bundle verifies on the Pi with the Ethernet cable out. This shows only that the
  carrier works offline; it proves nothing about applying it.
- **Earlier evidence:** the bundle path was used for the first fork deployment on 2026-09-27
  ([production-deploy](../findings/2026-09-27-production-deploy.md)).
- **Status:** `NOT RUN`.

---

# Session B: after deploying main

**Prerequisite found 2026-10-12 (read-only):** the certificate the Pi serves names `party.avrana.net` only
([baseline](../findings/2026-10-12-deployed-baseline.md)). Native games that run on the game origin
(`games.avrana.net`, for example Checkers in B-01 and B-02) will show a certificate-name error on phones
until the two-name certificate is issued and installed per [game-origin](game-origin.md). Do that before
this session, or record B-01 and B-02 as `NOT RUN: game-origin certificate missing`.

Preconditions: the owner has deployed `origin/main` Party and Games with explicit full SHAs (friend-ready
steps 2 and 3, which also cover the nginx site file and its cookie rule), and, for B-01 to B-04, applied the
service-user migration, `prepare-native-games` and the game origin (friend-ready step 4, runbooks
service-users-migration, prepare-native-games, game-origin). None of that is done on the appliance today.

## B-01 Native game lifecycle: provision, appear, launch, end, remove (Checkers)

- **Serves:** AVR-236, AVR-238, AVR-261. **Revision:** MAIN.
- **Steps:** `sudo python3 -m avrana.ops.provision_game checkers --dry-run` then without `--dry-run` (from
  `/opt/avrana-party/current`, provision-game.md); a phone's Party Home lists Checkers; the Host launches it;
  it is ended from Party Home; then `--remove`. Between each, `systemctl status avrana-game@checkers.socket`
  and the status JSON.
- **Expect:** a second provision run says "nothing to change"; after `--remove` there is no key, registry
  entry, socket, drop-in or state directory and Party Home stops offering it.
- **Pass / fail:** friend-ready step 7 and the AVR-261 record table. **Earlier evidence:** a disposable
  Ubuntu runner with real systemd did all of this (T2, run 38024330627, 58 checks;
  [checkers-systemd-proof](../findings/2026-10-09-checkers-systemd-proof.md)); never on the Pi.
- **Status:** `NOT RUN`.

## B-02 Checkers on two phones

- **Serves:** AVR-261. **Revision:** MAIN. One iPhone and one Android. Follow friend-ready step 7 and its
  record table; this runbook adds nothing.
- **Status:** `NOT RUN`.

## B-03 Native game process failure (Checkers unit)

- **Serves:** AVR-33. **Revision:** MAIN. **OWNER DECISION**; throwaway party.
- **Steps:** with a Checkers session of two phones, `ssh -t 10.42.0.1 'sudo systemctl kill -s KILL avrana-game@checkers.service; sleep 3; systemctl is-active avrana-game@checkers.service avrana-game@checkers.socket'`.
  Watch both phones for two minutes; try a move; then the Host presses End.
- **What should be seen today (a reading of the unit and source):** the template unit has
  `Restart=on-failure`, so systemd starts a new process; the process keeps no session state across the
  restart (the game is in memory), so the old tickets and the board are gone; Party Core is told nothing about
  a death. The socket stays. The Host must be able to end the dead session. **Exactly what each phone shows
  is not known: record it.**
- **Expected after the AVR-33 follow-up, not current:** a change that makes Party Core notice a dead game and
  end or recover the session would change this. No such change exists on any branch I found (see A-25). Do not
  describe it as current.
- **Pass / fail:** PASS: unit and socket active, others untouched, the Host can end and start again.
- **Status:** `NOT RUN`.

## B-04 Restart the native units and Party Core's internal socket

- **Serves:** AVR-33. **Revision:** MAIN. **OWNER DECISION**; no live session.
- **Steps:** `sudo systemctl reload avrana-party-core` (a reload, not a restart; provision-game does this);
  then `sudo systemctl restart avrana-game@checkers.socket avrana-game@checkers.service`; then the full restart
  of `avrana-party-core` together with its socket (stop the socket as well as the service, per provision-game
  "Maintenance"). After each: status JSON, `python3 -m avrana.ops.smoke`, and a phone launching Checkers.
- **Pass / fail:** every unit returns, games are still offered after a reload without a restart.
- **Status:** `NOT RUN`.

## B-05 `.avrgame` install, list, verify, remove (Hello Party)

- **Serves:** AVR-39, AVR-38. **Revision:** MAIN. **EXPERIMENTAL**; read the trust section of install-game.md
  first: installing a package makes the appliance run third-party code.
- **Prerequisites:** install-game.md "Before": phase 1, prepare-native-games, an empty root-owned
  `/opt/avrana-games`, `"packages"` in `/etc/avrana-party/party-core.json`. The package is built on the laptop
  (`python -m avrana.avrgame pack <recipe>`) and carried to the Pi by `scp`; no network is used.
- **Steps:** `sudo /opt/avrana-party/current/ops/install-game install hello.avrgame --dry-run`, then with
  `--grant party_roster`; `install-game list`; `install-game verify hello`; then `install-game remove hello`.
  (The reference id `hello` cannot be installed on a tree that carries `contracts/games/hello.json`; see
  install-game.md. Use the renamed game that document describes.)
- **Expect:** list and verify succeed; remove leaves nothing; Party Core is reloaded, never restarted.
- **Not covered here:** the tile in Party Home (C-03). On main the installed package has no tile and no
  navigation on a phone.
- **Earlier evidence:** a disposable-runner proof, 78 checks (install-game.md). Never on a device.
- **Status:** `NOT RUN`.

## B-06 Offline software upgrade: the Games bundle switch

- **Serves:** AVR-82, AVR-32. **Revision:** MAIN (a deployment). **OWNER DECISION** and a real deployment.
- **Steps:** A-26 for staging, then games-fork-deploy.md sections 2 and 3 with the new SHA. The runbook documents
  the first clone (`git clone` from the bundle); how to apply a **second** bundle to the existing clone is not
  documented there (`ops/deploy.sh` runs `git fetch --all || true` on the Games clone "may come from a
  bundle"). Write the exact command used. UNTESTED.
- **Pass / fail:** the Games SHA in status equals the bundle's, smoke passes, rollback by the runbook works.
- **Status:** `NOT RUN`.

## B-07 Offline software upgrade: Party (known gap)

- **Serves:** AVR-82, AVR-32. **Revision:** MAIN.
- **Known gap:** `ops/deploy.sh` runs `git fetch --quiet origin` in the Party checkout and refuses a commit it
  cannot fetch ("is not fetchable"), so **Party has no offline upgrade path today**; the Pi's GitHub key is
  what it fetches with. Nothing in the repository carries Party code to an appliance without GitHub.
- **What the test would be once a path exists:** with the Ethernet cable out, carry the release to the Pi
  (bundle or an artifact), apply it with a verified full SHA, and check: smoke passes, status SHA equals the
  release, rollback restores the previous release, phones keep their identities. Until then this is a gap, not
  a test; record it as `NOT RUN: no path`.
- **Status:** `NOT RUN`.

## B-08 Service-user migration leaves the party working

- **Serves:** AVR-256 (ADR 0016 phase 1). **Revision:** MAIN. Follow friend-ready step 4b and its phone checks
  (BLUFF, EXPO and Gauntlet II each launch and end from Party Home after the migration). The migration has
  never run on any host; the arcade's hardening has not met RetroArch. **Status:** `NOT RUN`.

---

# Session C: after named pull requests

## C-01 Certificate expiry visible in `/party/api/status`

- **Serves:** AVR-31. **Revision:** PR #108 (`fix/avr-31-certificate-renewal`), deployed.
- **Why it is not visible today:** the status service cannot read the root-only certificate directory, so
  `certificate.status` is `unavailable` with `not_after` null while the served certificate is valid to
  2026-12-25 ([baseline](../findings/2026-10-12-deployed-baseline.md)). PR #108 reads an expiry record,
  `/etc/avrana-party/certificate-not-after`, written by the installer and the renewal service.
- **Steps:** after deploying #108 and running the install in C-02: the status JSON `certificate` block and
  `summary`.
- **Expect:** `status` `ok`, `days_left` near the real figure (2026-12-25 minus today), the timer `active`.
  The summary degrades below 21 days (`expiring`).
- **Pass / fail:** PASS when `days_left` agrees with the `openssl s_client` reading of A-08 to within a day.
- **Status:** `NOT RUN`.

## C-02 Renewal timer: install, safe run, enable

- **Serves:** AVR-31. **Revision:** PR #108. **OWNER INSTALL** (changes the Pi; `sudo`; needs a Cloudflare
  token typed by the owner). This is the only repeatable install-and-verify for the timer; it links the
  procedure and does not copy it.
- **The procedure** is the section "Automatic renewal: enable, verify, recover" of `docs/runbooks/party-https.md`.
  That section exists only on PR #108's branch (`origin/fix/avr-31-certificate-renewal`); **it requires #108**
  and is not on main. Read it there. Do its steps 1 to 5 in order. The token goes into a root-only file typed
  by the owner in an editor; it is never on a command line, in chat or in Git.
- **What this runbook adds around it (read-only):**
  1. **Before:** record `systemctl list-timers --all | grep -i certificate` (empty today), the status
     `certificate` block, `/usr/local/bin/lego --version` ("lego version dev linux/arm64" on 2026-10-12: a
     development build, so the release is UNKNOWN), `date -u` and `timedatectl` (a correct clock matters: see
     Clock policy), `readlink /etc/avrana-party/tls/current` and the A-08 `openssl` dates.
  2. **Safe run:** party-https step 4 starts the service once. The certificate is not within 30 days of its end
     (the renewal command is `renew --days 30`; the first action is about 2026-11-25), so lego orders nothing.
     Expect `Result=success`, `ExecMainStatus=0`, and `Certificate is already installed` in the journal.
  3. **After enabling:** `systemctl list-timers avrana-party-certificate.timer` shows a NEXT time within about
     26 hours (the timer runs at 04:00 plus up to 2 hours of random delay, `Persistent=true`); the status block
     is `ok`; `readlink` and the served `notAfter` are unchanged.
  4. **Reverse:** `sudo systemctl disable --now avrana-party-certificate.timer` (the certificate stays valid
     until it ends). The party-https section has the rollback of the certificate itself.
  5. **Do not** force a renewal early: `lego renew --days 90` orders a real certificate and counts against
     Let's Encrypt's limits.
- **First real renewal** happens by itself between 30 and 21 days before the end. Record the journal and
  status on the first days of that window (2026-11-25 onward for the current certificate). Whether the `dev`
  lego build can renew is untested.
- **Pass / fail:** PASS: safe run succeeds, timer active, status `ok`. FAIL: any unit failure; the installed
  certificate is untouched on failure (per the section).
- **Status:** `NOT RUN`.

## C-03 Installed package appears in Party Home

- **Serves:** AVR-337, AVR-338. **Revision:** the branches `feat/avr-337-installed-catalog-overlay` and
  `test/avr-338-packaged-hello-browser-on-overlay`, not on main (23 and 22 commits ahead of `04c5844` on
  2026-10-12; no open pull request found). Until a catalog that includes the package is served, a package
  installed on main is provisioned and offered by Party Core but has no tile.
- **Steps (once deployed):** B-05 install; the phone's Party Home shows the tile; launch; end; remove; the
  tile disappears.
- **Status:** `NOT RUN`.

## C-04 Wi-Fi gate on the channel in use

- **Serves:** AVR-296, AVR-300. **Revision:** PR #85 (`feat/avr-296-wifi-qualification`); laptop-side only,
  nothing is installed on the Pi for this test. Read `docs/runbooks/wifi-qualification.md` and
  `tools/wifi-lab/README.md` **on that branch**; they are not on main.
- **Needs:** `adb` on the laptop, **an adb-attached Android** joined to the Avrana SSID (USB only for adb), the
  `party` ssh alias (key auth) which resolves over `eth0` (so the Ethernet cable is **in** for this test; it
  is not an offline test), and nobody playing (the tool generates load).
- **Does not need** the AP-control helper.
- **Commands (laptop, repository root, from the README):**
  ```bash
  python tools/wifi-lab/wifilab.py health                        # Pi hardware health, bounded
  python tools/wifi-lab/wifilab.py --set expect_channel=36 gate  # about 2-3 min; refuses to run if the AP is on another channel
  python tools/wifi-lab/wifilab.py baseline --label accept --trials 3
  python tools/wifi-lab/wifilab.py loaded --label accept --seconds 30
  python tools/wifi-lab/wifilab.py report --write
  ```
  Use the channel actually observed in A-22 for `expect_channel`; the option only guards, it changes
  nothing. (Where `--set` goes on the command line, and whether it applies to `gate`, is what
  `python tools/wifi-lab/wifilab.py --help` says; the README gives only the example `--set expect_channel=36`.) `gate` exits 0 PASS, 1 WARN, 2 FAIL (2 also means it could not run). With two Androids attached it
  refuses to guess: `--device SERIAL` or `--all-devices`.
- **Never run** `ap set`, `ap restore`, `qualify` or `ap-recover` as part of acceptance: they change the
  production radio. They need the restricted AP-control helper (AVR-298), which is **not installed** and is
  not installed by this runbook.
- **Pass / fail:** the verdict as the tool prints it; thresholds are provisional (idle p95 and p99 warn above
  80 and 150 ms), derived from one tablet. Retry ratios are informational only.
- **Earlier evidence:** one Samsung tablet, 2026-10-06: channel 36 p99 64 to 99 ms against channel 149 p99
  140 to 211 ms.
- **Status:** `NOT RUN`.

## C-05 Client capacity 1 to N

- **Serves:** AVR-301, AVR-12. **Revision:** PR #85. Targets from the Linear issue (owner, 2026-10-07):
  highlight six clients (responsive action) and eight (lightweight Party games). No ceiling is defined.
- **Needs:** as C-04, plus the real devices. Real-device steps are measured from **adb-attached Androids**;
  phones that are only associated (iPhones, other Androids) add stations but are not measured (a reading of
  the README; `--help` wins). Synthetic TCP clients from the laptop are labelled by path (`avrana-subnet` or
  `other-path`) and are not evidence about Wi-Fi clients unless on the Avrana subnet.
- **Before:** `update-alternatives --display cyfmac43455-sdio.bin` (read-only; "auto, standard" on
  2026-10-12) and `iw list | grep -i -E 'max.*(sta|client)'`; `iw dev wlan0 station dump | grep -c '^Station'`
  at every step.
- **Command:** `python tools/wifi-lab/wifilab.py multi --counts 1,2,4,6,8,10` with the devices joined as each
  step asks; record RTT p50, p95, p99, loss, reconnects, Pi temperature, load and health per step.
- **Pass / fail:** the knee is identified or the uncertainty is bounded and written as a dated finding. No
  threshold exists: TBD by the owner. The "about 8 stations" figure in network.md is **reported, not
  measured**; the only outside source found is one forum report of a 7-client limit on a Pi 3B+ that went away
  with the minimal firmware ([hardware brief](../research/hardware-feasibility-brief.md)).
- **Status:** `NOT RUN`.

## C-06 Pi health check states

- **Serves:** AVR-297. **Revision:** PR #85. **OWNER INSTALL** (`sudo bash telemetry/install-pi-health-check.sh`
  on the Pi after merge and pull; installs a service and a timer, never reboots or restarts anything). Not part
  of the base acceptance. After install: `journalctl -u pi-health-check -n 5` and `cat /run/avrana/pi-health.json`;
  expect `HEALTHY` on a healthy boot (states are `HEALTHY`, `DEGRADED`, `POWER_THROTTLE_DETECTED`,
  `FIRMWARE_MAILBOX_SUSPECT`, `UNKNOWN`). No safe negative test exists.
- **Status:** `NOT RUN`.

## C-07 A quiet host keeps the seat; a stale nginx site is detected

- **Revision:** PR #109 for the first, PR #110 for the second (merge #110 after #108). They are covered by
  unit tests (T1). Physical check for #109: the host's phone idle but present for two minutes keeps the host
  role (compare A-13). For #110: after deploying it, `python3 -m avrana.ops.smoke` and the status JSON report
  a stale nginx site file (today's installed file differs from main's). **Status:** `NOT RUN`.

## C-08 Game process failure after session-recovery work

- **Serves:** AVR-33. **Revision:** needs branch `fix/avr-33-session-recovery` merged and deployed, with
  `session_recovery.close_lost_game` set to `true` in the Party Core configuration (it is `false` by
  default; with it off the behaviour is A-25's). Not merged, not deployed, owner decision pending.
- **Prerequisites:** four phones in a party, a game running, a shell on the Pi with sudo.
- **Steps:** stop the game's unit and keep it down (`sudo systemctl stop <unit>`, and mask or stop its
  socket if it is socket-activated, otherwise the next connection restarts it); on a follower phone go back
  to the game twice within ten seconds.
- **Expected after that work:** within about ten seconds of the third failed attempt every phone is on
  Party Home, `/party/api/state` shows the session ended with outcome `abandoned` and `reason: game_lost`,
  and the host can start another game without pressing End. A game that is only restarted (it answers but
  has forgotten the session) is NOT closed: the host must press End, which now succeeds.
- **Evidence:** screen recording of one follower and the host; `curl` of `/party/api/state` before and
  after; `journalctl -u avrana-party-core` lines for the close.
- **Pass:** all phones home without host action, no phone left on a dead game page. **Fail:** any phone
  bouncing between Party Home and the game, or a healthy game closed.
- **Status:** `NOT RUN`.

---

# Clock policy

**Only what is true is stated; options are not decisions.** The owner decision is Linear AVR-79.

## What the repository configures

Searches of `origin/main` for `timesyncd`, `fake-hwclock`, `chrony`, `hwclock`, `timedatectl` and `RTC`
found no configuration and no installer step. The only mentions are: a comment in `avrana/party/protocol.py`
(both ends share one wall clock; the appliance has no RTC, so an NTP step after an offline boot can move it);
`deploy/appliance-inventory.json` item U10 ("Nothing in the repository configures or checks time", confirm
with `timedatectl; systemctl status systemd-timesyncd`); ADR 0006 ("The clock policy itself (NTP steps, no
RTC) is AVR-79"); `docs/design/LIMITED-MODE.md` section 2; and the architecture audits, which recommend a
persisted floor as the cheaper course (a recommendation, not implemented). The
branches read (#85, #108, #109) add nothing about time.

## What the Pi has (read-only, 2026-10-12, [baseline](../findings/2026-10-12-deployed-baseline.md))

`systemd-timesyncd` enabled and active (a Raspberry Pi OS default; the repository does not install it);
`timedatectl` reports "System clock synchronized: yes", "RTC time: n/a"; `fake-hwclock` and `chrony` not
found; `/etc/fake-hwclock.data` absent; `/sys/class/rtc` empty; `/var/lib/systemd/timesync/clock` exists with
a mtime a couple of minutes before the capture. At the last boot the clock began about 37 hours behind true
time and stepped forward when NTP answered. **Inference, not observed:** the starting value was timesyncd's
saved clock from when the Pi last ran, so an offline boot starts at about the time of last sync or shutdown,
not at 1970, and does not step.

## What breaks with a wrong Pi clock

- **Party tickets and tokens** carry `iat` and `exp` in wall-clock seconds, minted and checked on the Pi
  (`avrana/party/protocol.py`). `unseal` tolerates 5 seconds of future `iat`. A backward step beyond that is
  refused as `clock`; a forward step past `exp` reads `expired`. A ticket minted after the step verifies, so
  a retry succeeds once the clock is stable. In-flight tickets at the moment of a step can be refused.
- **Logs and the manifest:** journal and telemetry timestamps, and `deployed_at` in the deployment manifest,
  carry the wrong time; correlating a phone's report with the Pi's log is harder.
- **Certificate renewal scheduling:** `OnCalendar` and lego's "days left" read the wall clock. A clock far behind
  hides an approaching expiry; a clock far ahead could renew early (an inference from `renew --days 30`; do not
  test it). The status endpoint's `days_left` is computed from the Pi's clock too.
- **`lego` and TLS to Let's Encrypt and Cloudflare** need a correct clock and an upstream. They are not part of
  an offline party.

## What does not break

- **Phones' TLS validation** uses each phone's own clock (A-20). The Pi's wrong clock does not make the
  served certificate look expired to a phone with an automatic clock.
- **Party Core's own timers** (liveness window, host grace, launch timeout, idle) use the monotonic clock
  (`time.monotonic` in `avrana/party/service.py`), so a wall-clock step does not shorten or extend them.

## Open decision AVR-79: options, not decisions

| Option | What it would do | What it would not do | Cost (estimate, unmeasured) |
|---|---|---|---|
| Persisted floor (fake-hwclock style) | Save the time periodically and at shutdown; restore it at boot so the clock never starts earlier than it last ran. `systemd-timesyncd` already appears to do this with its saved-clock file; the choice is whether to rely on it, or make the floor explicit and checked | Make the clock correct after a long power-off with no upstream (it is still late by the off time) | A package or a unit; no hardware |
| RTC module | A battery-backed clock keeps real time across power-off | Anything without the hardware and a kernel overlay; a retail unit needs it designed in | Hardware, an overlay, a battery; changes the enclosure |
| Phone-supplied time hint | A joining phone reports its clock, and the Host or the Pi could take it as a hint | It would need trust rules (any phone can lie), a host-only gate and an owner decision; nothing is designed | New protocol and trust design |

The cheapest next measurement is already in this runbook: the offset in A-21. A-20 and A-21 together say how
visible the problem is to a person. None of these options is chosen here.

---

# Known gaps this runbook does not close

- No test can run as written without an owner and real phones; **every status is `NOT RUN`**.
- Party has no offline upgrade path (B-07).
- Certificate expiry is not visible in status until #108 (C-01).
- The journal is volatile until `Storage=persistent` is installed (A-19).
- The unmerged branches named in Session C are unmerged; their behaviour is not described as current anywhere above.
- `docs/runbooks/network.md` still carries the 149 channel in its 2026-09-24 table; the channel statement
  there now points at the dated note.
