# Runbook: experimental SDK physical acceptance (Checkers, Hello Party, Tanks)

Status: **PROPOSED owner-run procedure, NOT RUN on the appliance** (2026-10-13).

Written from source and `--help` output, never run on the Pi, on arm64 or on a phone. Every step below is
`NOT RUN`. **Agents never deploy, never run a step here and cannot close it**; each command on the Pi is an
owner action. The package format and the Node runtime are EXPERIMENTAL ([AVRGAME-PACKAGE](../design/AVRGAME-PACKAGE.md)).
This file links the procedures it depends on instead of repeating them: [deploy](deploy.md),
[install-game](install-game.md) (read its trust section first: installing a package runs third-party code),
[prepare-native-games](prepare-native-games.md), [game-origin](game-origin.md),
[checkers-acceptance](checkers-acceptance.md), [offline-acceptance](offline-acceptance.md) (its "Rules that
apply to every test" apply here, including what makes a run void).

Record each step as `PASS`, `FAIL` or `NOT RUN` with what was seen. `<id>` is the installed id of a game
(`install-game list`); its unit is `avrana-game@<id>.service`.

## 0. Preconditions (owner)

| # | Step | Pass when | Result |
|---|---|---|---|
| 0.1 | Deploy Party and Games `main` **after Party PRs #118, #119, #120 and Games PRs #64-#67 have merged**, with [deploy](deploy.md). Then `curl -s https://party.avrana.net/party/api/status \| python3 -m json.tool` | `summary.state` is `ok`; record the Party and Games SHAs it reports: Party ____ Games ____ | NOT RUN |
| 0.2 | nginx site file. `ops/deploy.sh` installs the target commit's `avrana-party.nginx` itself (deploy.md, step 3a) **unless it was run with `--skip-nginx-site`**; then install it by hand as in [game-origin](game-origin.md) step 3. Either way: `cmp /home/cody/avrana-party/avrana-party.nginx /etc/nginx/sites-available/avrana-party && sudo nginx -t` | `cmp` prints nothing, `nginx -t` passes, and `nginx_site.status` in `/party/api/status` is `match`. The service-worker rule of PR #118 (step 6) lives in this file | NOT RUN |
| 0.3 | [prepare-native-games](prepare-native-games.md), the game origin ([game-origin](game-origin.md) "Verify"), and install-game.md "Before" items 3, 4 and 6 (`/opt/avrana-games`, `"packages"` in `party-core.json`, the catalog location) | each runbook's own check passes | NOT RUN |
| 0.4 | Phones: at least one iPhone (Safari) and one Android (Chrome), four in total. Record model, OS and browser version of each | recorded: ____ | NOT RUN |

## 1. Node runtime (needed by Tanks only)

On another machine with internet: download `https://nodejs.org/dist/v22.22.2/node-v22.22.2-linux-arm64.tar.xz`
and check `sha256sum node-v22.22.2-linux-arm64.tar.xz` prints
`e9e1930fd321a470e29bb68f30318bf58e3ecb4acb4f1533fb19c58328a091fe` (the pin in `avrana/avrgame/node_pin.py`).
Copy it to the Pi (`scp`). Nothing is downloaded on the Pi.

| # | Command (on the Pi) | Pass when | Result |
|---|---|---|---|
| 1.1 | `sudo /opt/avrana-party/current/ops/install-node-runtime install node-v22.22.2-linux-arm64.tar.xz --dry-run` | prints `node 22.22.2 (arm64): would install node-v22.22.2-linux-arm64.tar.xz (sha256 e9e1930fd321...) at /opt/avrana-runtimes/node-22.22.2`; nothing created | NOT RUN |
| 1.2 | the same without `--dry-run` | first line `node 22.22.2 (arm64): installed from node-v22.22.2-linux-arm64.tar.xz (sha256 e9e1930fd321...)`; exit 0 | NOT RUN |
| 1.3 | `/opt/avrana-party/current/ops/install-node-runtime verify` | `node 22.22.2 (arm64): installed and unchanged (/opt/avrana-runtimes/node-22.22.2/bin/node)` | NOT RUN |
| 1.4 | `ls -la /opt/avrana-runtimes/node-22.22.2 /opt/avrana-runtimes/node-22.22.2/bin` | root-owned; only `bin/node`, `LICENSE`, `avrana-runtime.json`; no npm | NOT RUN |

## 2. Build inputs and install

Packages are built on the laptop and carried over by `scp`; record `sha256sum` of each file at build time
and again on the Pi.

- **Hello Party:** built as offline-acceptance B-05 and install-game.md describe (`python -m avrana.avrgame pack <recipe>`,
  under an id that does not shadow `contracts/games/hello.json`). sha256 ____
- **Checkers:** per [checkers-acceptance](checkers-acceptance.md) and Games PRs #64-#67; if those deliver it as
  a `.avrgame` file, install it as below, otherwise it stays provisioned as that runbook says. sha256 ____
- **Tanks:** built by `colyseus-tanks/build.mjs` in the Games repository; its command line and output name are
  **per Games PR #66/#67** (not visible from Party; do not guess flags). sha256 ____

| # | Command, once per package | Pass when | Result |
|---|---|---|---|
| 2.1 | `sudo /opt/avrana-party/current/ops/install-game install FILE.avrgame --grant party_roster --dry-run` | exit 0; it names the runtime (`node` for Tanks) and what would change | NOT RUN |
| 2.2 | the same without `--dry-run` | `<id>: installed <version>` first; exit 0 | NOT RUN |
| 2.3 | `/opt/avrana-party/current/ops/install-game list` and `/opt/avrana-party/current/ops/install-game verify <id>` | the id is listed with tier `community`; verify exits 0 | NOT RUN |
| 2.4 | `/opt/avrana-party/current/ops/catalog-overlay check` and `... catalog-overlay show`; then Party Home on a phone | not stale; a row and a tile for each package | NOT RUN |
| 2.5 | `systemctl show avrana-game@<id>.service -p MemoryMax -p TasksMax -p CPUQuotaPerSecUSec -p DynamicUser -p PrivateNetwork -p RestrictAddressFamilies -p CapabilityBoundingSet -p StateDirectory -p Restart` | record the lines. Expect `MemoryMax=268435456`, `TasksMax=64`, `CPUQuotaPerSecUSec=1s`, `DynamicUser=yes`, `PrivateNetwork=yes`, `RestrictAddressFamilies=AF_UNIX`, empty `CapabilityBoundingSet=` and `StateDirectory=`, `Restart=on-failure` | NOT RUN |
| 2.6 | Tanks only: `systemctl show avrana-game@<id>.service -p ExecStart -p UnsetEnvironment` | `argv[]=/opt/avrana-runtimes/node-22.22.2/bin/node --max-old-space-size=192 <entry>.mjs`; `UnsetEnvironment=NODE_OPTIONS NODE_PATH` | NOT RUN |

## 3. Play matrix (real phones, offline)

Unplug the Ethernet uplink first, as offline-acceptance A-01 arranges; phones on the Party Wi-Fi only.
Run every row for **each of Checkers, Hello Party and Tanks**, first with **2 phones, then with 4** (players up
to the game's maximum, the rest watching), with the iPhone and the Android both playing at least once.
Fill one cell per game and phone count: `PASS`, `FAIL` (what happened, which phone) or `NOT RUN`.

| # | Check | Checkers 2 / 4 | Hello 2 / 4 | Tanks 2 / 4 |
|---|---|---|---|---|
| 3.1 | Launch from Party Home; the address bar shows the game origin, no certificate warning | | | |
| 3.2 | Admission: every phone is seated or watching, with its Party name | | | |
| 3.3 | Play to completion; the result is shown in Party on every phone | | | |
| 3.4 | Second launch after the first ended: a fresh session, nothing left from the first | | | |
| 3.5 | Host End mid-game: every phone returns to Party; the process stops by itself | | | |
| 3.6 | Reload one phone mid-game: same seat, same state | | | |
| 3.7 | Lock one phone for 30 s, unlock: it resumes in its seat | | | |
| 3.8 | Airplane mode on for 15 s, off: it reconnects without a manual reload (note if one was needed) | | | |
| 3.9 | Back to Party from the going screen (AVR-339): the control appears and works | | | |

**Tanks specifics** (record each): touch controls in portrait ____ and landscape ____; the WebSocket stays
connected through nginx for a whole round (no reconnect banner; `journalctl -u avrana-game@<id>.service -b`
afterwards shows no drop) ____; frame-rate impression and any stutter, per phone ____; audio plays after the
first touch, on iPhone and Android ____.

## 4. Measurements

Read **once per checkpoint** from the Pi's console or one SSH session, never in a loop and never during the
seconds being judged for latency: once at idle (game launched, nobody moving) and once during 4-phone play.

```
systemctl show avrana-game@<id>.service -p MemoryCurrent -p TasksCurrent -p CPUUsageNSec
timeout 5 vcgencmd get_throttled
```

| Game | idle: Memory / Tasks / CPU ns | 4 phones: Memory / Tasks / CPU ns | `get_throttled` (expect `0x0`) | input latency, subjective |
|---|---|---|---|---|
| Checkers | NOT RUN | NOT RUN | | |
| Hello Party | NOT RUN | NOT RUN | | |
| Tanks | NOT RUN | NOT RUN | | |

**Fail:** Tanks `MemoryCurrent` at or above 268435456 (256M) at either checkpoint, a restart of its unit
during play (`systemctl show ... -p NRestarts` not 0: the cgroup killed it and `Restart=on-failure` acted), or
`get_throttled` other than `0x0`. The 192 MiB V8 heap cap is a first value; these are its first real numbers.

## 5. Cache and update

| # | Step | Pass when | Result |
|---|---|---|---|
| 5.1 | Warm relaunch of each game on every phone | it opens; note anything slower or staler than the first launch | NOT RUN |
| 5.2 | On one phone clear the site data of the Party and game origins, then relaunch | it loads again from the Pi, offline (eviction is normal; a reload must be enough) | NOT RUN |
| 5.3 | Keep one phone on the old game page. Build the package again with one client file changed; upgrade is not implemented, so `sudo .../ops/install-game remove <id>` then `install ... --grant party_roster` with the new file | the phone holding the old page shows **"This game was updated."** with a Reload control (behaviour per PR #118/#120); Reload gives the new file | NOT RUN |
| 5.4 | Roll back: `remove <id>`, install the original file; `install-game verify <id>`; `sha256sum` matches step 2 | the original client is served; the prompt appears again on a phone holding the changed page | NOT RUN |

## 6. Service-worker rule (PR #118)

`curl -sk -H 'Service-Worker: script' https://<game origin>/games/hello/hello.mjs -o /dev/null -w '%{http_code}'`
(replace `hello` with the installed id and a script it serves). **Pass:** `403`; the same request without the
header answers `200`. Result: NOT RUN

## 7. Clock after a cold boot without network (AVR-465)

Power the Pi off, leave Ethernet unplugged, power on. Record `timedatectl` and `date -u` (offline-acceptance
A-21). Join with two phones and launch Hello Party. **Pass:** the first ticket is admitted at once. AVR-465
prunes the ticket ledger by a high-water clock, so a clock that stepped **backwards** since the last run delays
admission until it passes the old mark: record the delay, if any, and both clock readings. Result: NOT RUN

## 8. Teardown and rollback

| # | Command | Pass when | Result |
|---|---|---|---|
| 8.1 | `sudo /opt/avrana-party/current/ops/install-game remove <id> --dry-run`, then without it, for each package | exit 0; refused while a session of that game is live (end it first) | NOT RUN |
| 8.2 | `/opt/avrana-party/current/ops/install-game list`; `systemctl status avrana-game@<id>.service avrana-game@<id>.socket`; `.../ops/catalog-overlay show`; Party Home | not listed; no unit or socket; no row; no tile | NOT RUN |
| 8.3 | `sudo /opt/avrana-party/current/ops/install-node-runtime remove --dry-run`, then without it | `node 22.22.2: removed /opt/avrana-runtimes/node-22.22.2`. Refused while a Node package is installed, or while a file in `/etc/avrana-party/packages.d` cannot be read as a record | NOT RUN |
| 8.4 | `curl -s https://party.avrana.net/party/api/status \| python3 -m json.tool` | `summary.state` is `ok`; first-party games unaffected | NOT RUN |

**Rollback path.** Packages and the runtime come off as above and leave Party as it was. To go back to the
previous Party and Games commits use deploy.md ("Going back by hand" and the rollback options); it restores the
older site file too. If a package tile is missing afterwards: `sudo /opt/avrana-party/current/ops/catalog-overlay refresh`.

## Record

Date ____, owner ____, Party SHA ____, Games SHA ____, phones ____. Put the outcome in a dated finding under
`docs/findings/`; this file stays the procedure and stays `NOT RUN` until that finding exists.
