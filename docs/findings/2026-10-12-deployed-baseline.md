# Deployed baseline, read-only capture (AVR-214)

Dated evidence, observed 2026-10-12 (UTC). Historical observation, not a deployment record, not
physical acceptance and not a live queue. **Nothing was deployed, restarted, installed or changed to
produce it.** Authority for what runs on the Pi is [SYSTEM](../SYSTEM.md); this file is the evidence
SYSTEM now cites.

## How it was captured, and its limits

Two captures by the orchestrator (Gru), both read-only, from a laptop on the home LAN over `eth0`
(`10.0.0.142`):

1. **Status endpoint, 2026-10-12T00:06Z, no SSH.** `GET https://party.avrana.net/party/api/status`
   (schema `avrana.status/v0`), plus the served certificate through
   `openssl s_client -connect 10.0.0.142:443 -servername party.avrana.net`. A second read the same
   day returned the same SHAs and `summary` `ok`.
2. **Shell facts, 2026-10-12T04:00Z to 04:03Z (2026-10-11 21:00 to 21:03 PDT), `ssh party`, no sudo.**
   Non-root commands only: `date -u`, `uptime`, `/etc/os-release`, `uname -r`, `timedatectl`,
   `systemctl is-enabled/is-active`, `ls /sys/class/rtc`, `journalctl --disk-usage`,
   `journalctl --list-boots`, `journalctl -b -u systemd-timesyncd`, `systemd-analyze cat-config
   systemd/journald.conf`, `iw dev wlan0 info`, `iw reg get`, `iw dev wlan0 station dump` (count only),
   `nmcli -t -f TYPE,AUTOCONNECT,AUTOCONNECT-PRIORITY connection show`, `vcgencmd get_throttled` and
   `measure_temp`, `/usr/local/bin/lego --version`, `systemctl show avrana-party-core`, `cmp` and a
   truncated `sha256sum` of the installed nginx site, `df -h /`, `findmnt /`, directory entry counts
   and `update-alternatives --display cyfmac43455-sdio.bin`.

Limits. The status endpoint is a report by Party Core, not a shell audit. The shell facts are one
reading each at one moment. **Not captured** (root-only or not asked): certificate files on disk,
dnsmasq files, NetworkManager profile names, lease files, anything needing sudo. No physical
acceptance of any kind happened: no phone, no reboot, no power interruption. Tier: T3 read-only
observation of the appliance; none of it is T4 (no real phone).

## 1. Status endpoint (2026-10-12T00:06Z)

| Field | Value |
|---|---|
| Deployment | `deployed_at` 2026-10-06T21:10:48Z by `ops/deploy.sh`; smoke passed at 2026-10-06T21:10:51Z; restarted `avrana-party-core`, `avranaparty-arcade`, `avranaparty-games` |
| Party | `deployed_sha` = `checkout_sha` = `c59f1c819de169b55d0bdadde34ae5cec57fc74a`; dirty false; untracked 0; mismatch false |
| Games | `deployed_sha` = `checkout_sha` = `a4489729e1d0522a302b0475a7631ed90c219812`; dirty false; untracked 0; mismatch false |
| Web release | build `c59f1c819de1`, commit equals the Party SHA |
| Contract | `party_games` `avrana.party-games/v0`, `party_session` `avrana.party-session/v0`, `lan_launch` `avrana.lan-launch/v1`, Games advertises `avrana.lan-launch/v1` |
| Services | `avrana-party-core`, `avranaparty-games`, `avranaparty-arcade`, `nginx`, `NetworkManager`: active. `avrana-party-certificate.timer`: **not-installed** |
| Certificate (status block) | `not_after` null, `days_left` null, `status` `unavailable` |
| Party Core | ok; uptime 151648 s; members 0; session null |
| Games provider | ok; compatible true |
| Arcade | idle; 0 of 2 players; `party_managed` true; emulator not running |
| Summary | `ok`, with the note "avrana-party-certificate.timer is not installed (optional)" |

The served certificate (`openssl s_client`, not the status block): issuer Let's Encrypt (CN `YE1`),
notBefore 2026-09-26T00:11:17Z, notAfter 2026-12-25T00:11:16Z.

**The status block says `unavailable` while the certificate is valid.** `avrana/ops/status.py` reads
`/etc/avrana-party/tls/current/fullchain.pem`, a root-only directory, from inside an unprivileged
service, so `not_after` is `None` "by design" (comment in `certificate_not_after`). Certificate
expiry is therefore **not visible in `/party/api/status` on the deployed revision**. The expiry
record that fixes this (`/etc/avrana-party/certificate-not-after`) is on Party PR #108 only; see
[offline-acceptance](../runbooks/offline-acceptance.md) test C1.

## 2. Shell facts (2026-10-12T04:00Z to 04:03Z)

| Area | Observed |
|---|---|
| OS | Debian GNU/Linux 13 (trixie), kernel `6.18.39+rpt-rpi-v8`. Hostname in the journal: `RaspberryPi` |
| Boot | `uptime -s` 2026-10-09 22:59:03 PDT; up 1 day 22:01 at capture; load 0.00 |
| Disk | `/` ext4 `rw,noatime` on `/dev/mmcblk0p2`, 117G, 9.1G used (9%). `/opt/avrana-party/releases`: 4 entries. `/var/backups/avrana-party`: 4 `deploy-*` entries |
| Units | `avrana-party-core`, `avranaparty-games`, `avranaparty-arcade`, `nginx`: all `enabled`. `avrana-party-core`: `User=cody`, `Restart=on-failure`, so the ADR 0016 service-user migration is **not applied** on the appliance |
| nginx | `/etc/nginx/sites-available/avrana-party` is byte-identical (`cmp`) to `/home/cody/avrana-party/avrana-party.nginx` at the deployed checkout `c59f1c8`; sha256 begins `87086e5c1e312572`. It therefore differs from `main`'s file wherever `main` changed it (main's file has 120 more lines than `c59f1c8`'s) |
| lego | `/usr/local/bin/lego --version`: "lego version dev linux/arm64" (a development build string; no release number) |
| Throttle and temperature | `vcgencmd get_throttled` `0x0`; `measure_temp` 31.6 C; 0 kernel under-voltage lines this boot (idle, one station) |
| Wi-Fi AP | `wlan0` type AP, **channel 36 (5180 MHz), width 20 MHz**; 1 station associated. Regulatory: country US, DFS-FCC (global); phy "country 99: DFS-UNSET". Firmware alternative `cyfmac43455-sdio.bin`: auto mode, pointing at `cyfmac43455-sdio-standard.bin` |
| NetworkManager profiles | types and autoconnect only: 1 wifi profile autoconnect yes priority 100; 3 wifi profiles autoconnect **no** priority 0; 1 ethernet autoconnect yes priority 100. Which profile is the AP was not read by name; `wlan0` is in AP mode |

### Clock

| Item | Observed |
|---|---|
| `timedatectl` | RTC time n/a; System clock synchronized: yes; NTP service: active; timezone America/Los_Angeles |
| Services | `systemd-timesyncd` enabled and active. `fake-hwclock` and `chrony`: not found. `/etc/fake-hwclock.data` absent. `/sys/class/rtc` empty (no RTC) |
| Saved clock file | `/var/lib/systemd/timesync/clock` exists, 0 bytes, mtime 2026-10-11 21:01 PDT (timesyncd's saved-clock file) |
| The only boot in the journal | FIRST ENTRY "Thu 2026-10-08 09:47:52 PDT"; `systemd-timesyncd` logged "Initial clock synchronization to Fri 2026-10-09 22:59:40.825846 PDT" |
| Party Core | `ActiveEnterTimestamp=Thu 2026-10-08 09:48:03 PDT` (read on the wrong clock). The status endpoint's uptime of 151648 s at 2026-10-12T00:06Z independently puts its start at about 2026-10-09 22:59 PDT |

Direct reading: at this boot the system clock began about 37 hours behind true time and stepped
forward when NTP answered (the Ethernet upstream was present). Party Core was started **before** the
step.
INFERENCE, not observed: the pre-sync time is the timesyncd saved clock from when the Pi last ran,
so the Pi was off, or without sync, for about 37 hours before this boot; on a boot with no upstream
the clock would stay at that saved value (not 1970), and no NTP step would follow.
This boot (2026-10-09 22:59 PDT) is not recorded in any repository finding. It is an unrecorded
reboot observed after the fact: afterwards the services listed above were enabled and active, with
Ethernet present. **It is not an offline cold-boot proof.** Policy consequences are in
[offline-acceptance](../runbooks/offline-acceptance.md), "Clock policy".

### Journal (AVR-29)

| Item | Observed |
|---|---|
| Effective configuration | `/usr/lib/systemd/journald.conf.d/40-rpi-volatile-storage.conf` sets `Storage=volatile` (the Raspberry Pi OS default drop-in). `/etc/systemd/journald.conf.d/avrana.conf` sets `SystemMaxUse=256M`, `SystemKeepFree=1G`, `RuntimeMaxUse=64M`, `MaxFileSec=1week` and does **not** set `Storage`. `/usr/lib/systemd/journald.conf.d/syslog.conf` sets `ForwardToSyslog=yes` |
| Size | `journalctl --disk-usage`: 11.4M |
| Directories | `/var/log/journal` exists (directory dated Jun 17; its contents are not journal files for this boot); `/run/log/journal/<machine-id>` present |
| Boots | `journalctl --list-boots` shows exactly one boot (index 0) |

Conclusion supported by this evidence: **the journal is volatile on the appliance today.** Logs from
before 2026-10-09 22:59 PDT are gone. Whether rsyslog writes persistent files under `/var/log`
because of `ForwardToSyslog=yes` was **not checked**. A deliberate reboot proof (marker line, reboot,
read it back) remains **NOT RUN**. The repository's `deploy/journald/avrana-journald.conf` does not
set `Storage` either (it says the choice is AVR-29's), so the installed file and the repository file
agree on that point; neither makes the journal persistent.

### Power and thermal

Read at capture: `0x0`, 31.6 C, 0 under-voltage lines, one station, idle. This is a single idle
sample and adds nothing to the 2026-09-24 baselines.

## 3. Three-way state: deployed, main, unmerged

Nothing in the middle or right columns is running on the appliance. Evidence tier for the middle
column is T1 unit and T2 CI/Chromium on a Linux runner; for the right column, T1 unit, loopback, or
Linux CI **on manual dispatch only**. Both repositories are private and pull-request CI is currently
red for every PR on AVR-428 (unauthenticated cross-repository reads; the secret
`AVRANA_CROSS_REPO_READ_TOKEN` does not exist yet), so the cross-repo contract and the
`checkers`/`package` proof jobs have **not run** anywhere on these revisions: read that as "not
run", never "pass".

| | DEPLOYED (Pi, read 2026-10-12) | origin/main (Party `04c5844`, Games `2ee23e6`) | UNMERGED WORK |
|---|---|---|---|
| Party | `c59f1c8` (merge of PR #83, committed 2026-10-06 13:28 PDT); includes the ADR 0011 console model (`git merge-base --is-ancestor ff32bb4 c59f1c8` is true, checked 2026-10-12) | 120 commits ahead of `c59f1c8` (`git rev-list --count c59f1c8..origin/main`), 17 merged PRs (a selection) including #84 provision-game, #87 game origin navigation, #92 prepare-native-games, #94 native Checkers, #95 device cookie never sent to game servers, #96 arcade receives no Cookie, #100 game origin deployable, #101 `.avrgame` packages (experimental), #103 package hardening, #98 friend-ready packet. Not deployed | see list below |
| Games | `a448972` | `2ee23e6` (not inspected line by line here) | Games #61 `fix/avr-428-ci-private-repo-auth` (63296b8) |
| nginx site on the Pi | equals `c59f1c8`'s file | 120 more lines, never installed by `ops/deploy.sh` | none |
| Certificate renewal | timer not installed; expiry not visible in status | units and scripts on main (`ops/`); status reader unchanged | #108 |
| Service users (ADR 0016) | not applied: `User=cody` | tooling on main (`ops/migrate-service-users.sh`, `prepare-native-games`, `provision-game`); never run on the Pi | none |
| Native games, game origin, packages | not present on the Pi | in source on main | `feat/avr-337-installed-catalog-overlay` and `test/avr-338-packaged-hello-browser-on-overlay` (installed-package tile in Party Home; not on main, no open PR found 2026-10-12) |
| AP channel | 36 (observed) | `docs/runbooks/network.md` still names 149 | #85 documents the channel policy |
| Journal | volatile (observed) | repository drop-in leaves `Storage=` to the OS default | none |

Unmerged work (all **not merged, not deployed**; evidence tier T1 unit, loopback, or Linux CI on
dispatch; none has phone or Pi evidence):

| Ref | Branch | What it changes |
|---|---|---|
| Party #108 | `fix/avr-31-certificate-renewal` (5599e72) | status reads an expiry record so the certificate is visible; renewal runbook section "Automatic renewal: enable, verify, recover"; the renewal service and installer get small changes |
| Party #109 | `fix/avr-33-party-recovery-hardening` (a3edbb0) | a host action counts as presence; a damaged `devices.json` is set aside and no longer stops Party Core; device store and manifest are fsynced before rename |
| Party #110 | `fix/avr-271-nginx-web-deploy-unit` (cf06a0d) | status and smoke detect a stale nginx site file or a web build from another commit. Must merge after #108 (one-line conflict in `avrana/ops/status.py`) |
| Party #111 and Games #61 | `fix/avr-428-ci-private-repo-auth` (009be3c / 63296b8) | CI reads the now-private repositories with read-only deploy keys; the secret is not yet created |
| Party #85 | `feat/avr-296-wifi-qualification` (fe2fe67) | `tools/wifi-lab` qualification harness, Pi health check, restricted AP-control helper, channel policy; none installed. Based on `c59f1c8`; was CONFLICTING with main |
| Party #86 | `docs/avr-53-messaging-architecture` | messaging proposal for owner review (docs); conflicting |
| Party #106, #107, #112 | drafts | design foundation (AVR-424), Flutter owner-app experiment (AVR-424), Home and Library coherence (AVR-429); UI-team work, not touched here |
| Unreleased | `fix/avr-336-bounded-game-replies` (b898de3) | bounds what Party Core reads from a game's launch or end reply |
| Unreleased | `fix/avr-336-deploy-contract-check` (7e2cc57) | runs the Party/Games contract checker before a deploy |

## 4. Deployment history gaps found while reconciling SYSTEM

- Party `a32b7b4` (merge of PR #29, 2026-09-29 20:00 PDT) was the checkout when the AVR-130 finding
  read the Pi before-state ([2026-10-02-avr130-deploy](2026-10-02-avr130-deploy.md)); no finding
  records the deployment that put it there.
- That finding is "DEPLOYMENT STAGED, awaiting the owner's sudo step" and records no after-state. No
  dated finding records the deployments between 2026-09-29 and 2026-10-06, nor the 2026-10-06 deployment
  of `c59f1c8`/`a448972`. For the last one the only evidence is the deployment manifest as reported by
  the status endpoint (section 1).
- The reboot at 2026-10-09 22:59 PDT is unrecorded (section 2, "Clock").

## What this does not establish

No phone, no offline boot, no power cut, no certificate renewal, no channel or capacity measurement.
Every item in [offline-acceptance](../runbooks/offline-acceptance.md) is `NOT RUN`.
