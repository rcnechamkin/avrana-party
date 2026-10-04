# Runbook: move the services off the operator account (ADR 0016 phase 1, AVR-256)

Status: **PROPOSED procedure, NOT RUN** (2026-10-03). Written from source and from the Pi's facts
recorded read-only on 2026-10-03; never executed on any host. Only `--dry-run` is exercised by
tests. Running it is an owner deployment: nothing in CI, in an agent's task or in this document
authorizes it. Until it has been run, [SYSTEM](../SYSTEM.md) is right that every service runs as
`cody`.

What it does: Party Core, the arcade and the LAN Games fork each get their own system user
(`avrana-party`, `avrana-arcade`, `avrana-lan-games`), run root-owned code under `/opt`, and the
key store belongs to Party Core alone. Why: [ADR 0016](../adr/0016-service-identities-and-local-trust-boundary.md)
§9; owner decision 4 on AVR-227. On 2026-10-03 the Pi met 6 of the 25 phase-1 rules.

## Before

1. Party and Games `main` both carry the key loader that accepts a systemd credential (AVR-253)
   and the Games half of AVR-256 (the fork's unit and drop-in under `deploy/`). The script refuses
   otherwise.
2. Deploy those commits with [`ops/deploy.sh`](deploy.md). That builds
   `/opt/avrana-party/current` and `/opt/avrana-party-games/current`; the services still run from
   the checkouts as `cody`, so this step changes nothing a phone can see.
3. Every key a unit will be handed exists in `/etc/avrana-party/game-keys/`: `arcade-gauntlet2.key`,
   `bluff.key` and `expo.key`. On 2026-10-03 the Pi had the first two and **no `expo.key`**. A
   unit whose `LoadCredential=` source is missing does not start, so the script refuses until
   each exists. Before the migration the key store still belongs to the operator account, so:
   `sudo AVRANA_PARTY_KEY_OWNER=cody bash ops/provision-party-game-key.sh expo` (the migration
   re-owns it with the others).
4. No party in progress.
5. Read the reverse section below against the Pi as it is.

### To verify against the Pi before migration

The games service's unit exists only on the appliance and is in no repository. The Games
repository's `deploy/avranaparty-games.service` was reconstructed from
[games-fork-deploy](games-fork-deploy.md) ("Before-state", read 2026-09-27) and from
`tests/fixtures/boundary/pi-2026-10-03.json`. Those records do not show the following, so
compare with `systemctl cat avranaparty-games avranaparty-arcade avrana-party-core` first and
carry over anything the installed units have that the new ones lack:

| Not shown by the records | What the new unit says |
|---|---|
| The games unit's `[Unit]` section (`After=`, `Wants=`) | `After=network.target` |
| Its `RestartSec=` | `3` |
| Any `Environment=` in the unit itself (for example `LANGAMES_HOST`, `LANGAMES_PORT`) | Python's two and `LANGAMES_HOST=127.0.0.1` (AVR-272; also the server's default from Games `11811ff`). On 2026-10-03 the Pi's listener was `0.0.0.0:8096`, so the migration **changes it to loopback**, which ADR 0016 phase 1 requires; nginx already reaches it on loopback |
| Its `WantedBy=` | `multi-user.target` |
| Whether the installed drop-ins differ from the ones in source | the drop-ins in source replace them |
| Drop-ins the source does not have (the Pi has `avranaparty-games.service.d/avrana-fork.conf`, which sets `ExecStart` and `WorkingDirectory` to the operator's checkout and would override the new unit) | the script records every such drop-in of the three units in the backup, removes it, and `--reverse` puts it back |
| Whether `data/` holds anything (`venue.json`, avatars, chat media) | copied to `/var/lib/avrana-lan-games` as found |
| That systemd on the Pi mounts `BindPaths=` onto the release's `data/` under `ProtectSystem=strict` | relies on `data/.gitkeep` being in the release |
| The arcade unit's installed form (it was installed by `arcade/install-service.py` from an earlier revision of the file) | see "Never validated anywhere" below |

## Run

```bash
ssh -t party "sudo bash /opt/avrana-party/current/ops/migrate-service-users.sh --dry-run"
ssh -t party "sudo bash /opt/avrana-party/current/ops/migrate-service-users.sh"
```

The dry run prints every command and changes nothing. The real run prints the directory holding
the before-state (`/var/backups/avrana-party/service-users-<UTC>/`): keep that path, the reverse
needs it.

| Step | What happens |
|---|---|
| 1 | Refuses unless both releases exist and only root can write them, both carry AVR-253, the Games release has its phase-1 unit, the arcade core and the fork's virtualenv are present, and no session is live |
| 2 | Copies the installed unit files and drop-ins, and the owners of the key store and the device store, to the backup directory |
| 3 | Creates groups `avrana-front`, `avrana-games`; users `avrana-party`, `avrana-arcade`, `avrana-lan-games` (system, no login shell, no home); adds `www-data` and `avrana-party` to `avrana-front`; adds `avrana-arcade` to `input`, `video`, `render` |
| 4 | Stops the three services. Re-owns `/etc/avrana-party/game-keys` (0700, keys 0600) and `/var/lib/avrana-party-core` to `avrana-party`. Copies the arcade's libretro core from the checkout to `/opt/avrana-arcade/cores/` and the fork's virtualenv to `/opt/avrana-party-games/venv`, both root-owned; **nothing is downloaded**. Copies the fork's `data/` to `/var/lib/avrana-lan-games`, and the arcade's `runtime/saves` and `runtime/system` (MAME nvram, high scores) from the checkout to `/var/lib/avrana-arcade`. Removes drop-ins of the previous units that the releases do not carry (kept in the backup). Installs the units and drop-ins from the releases. Starts the services |
| 5 | Runs `python3 -m avrana.ops.boundary --phase 1` and prints the verdict; exits 2 if a service is not active or a rule is not met |

**Record the arcade core's checksum.** Step 4 prints `arcade core sha256: <hash>`. The core is
built on the appliance and is not in Git, so this line is the only record of which binary the
arcade now runs. Copy it into the dated finding for this run and compare:

```bash
sha256sum /opt/avrana-arcade/cores/mame2010_libretro.so
```

The script fails, before changing anything, if the core is not at
`/home/cody/avrana-party/arcade/cores/mame2010_libretro.so` (override:
`AVRANA_ARCADE_CORE_SOURCE`).

## Check

1. `sudo python3 -m avrana.ops.boundary --phase 1` (from `/opt/avrana-party/current`): 25 of 25.
2. `python3 -m avrana.ops.smoke` passes.
3. On a phone, over the Party Wi-Fi: BLUFF, EXPO and Gauntlet II each launch and end from Party
   Home. Gauntlet II needs the closest look (below).
4. `systemctl show avranaparty-arcade -p User -p MainPID` and `journalctl -u avranaparty-arcade -n 50`
   show no permission error.

**Never validated anywhere:** the arcade unit's hardening (`ProtectSystem=strict`,
`ProtectHome=yes`, `PrivateTmp`, `NoNewPrivileges`) with RetroArch, Xvfb, PulseAudio and uinput
running as a user without a home (the config RetroArch reads is written into the state directory at each start, with every writable path under it, so nothing points at the operator's home); `/srv/avrana/roms/arcade/gaunt2.zip` being readable by
`avrana-arcade`; the copied virtualenv. If Gauntlet II does not start, read its journal first;
the likely causes are those three. A hardening line that has to be relaxed is a finding to
record and a rule (`hardening.base`) that will then fail, not something to hide.

Also never run: the games unit's `IPAddressDeny=any` / `IPAddressAllow=localhost` (AVR-272, owner
decision 2026-10-04). After the migration check `systemctl show -p IPAddressDeny -p IPAddressAllow
avranaparty-games` and the journal for a warning that the filter is unsupported; BLUFF and EXPO
must still open from `/party/`, and a game must still reach Party Core (start and end a session).

## Reverse

```bash
ssh -t party "sudo bash /opt/avrana-party/current/ops/migrate-service-users.sh --reverse /var/backups/avrana-party/service-users-<UTC>"
```

Stops the services, puts the recorded unit files and drop-ins back (removes the ones that did not
exist before), copies the fork's `data/` back to its checkout, re-owns the key store, the device
store and that `data/` to their recorded owners, reloads systemd and starts the services. A
service that does not start is reported and the others are still started. The arcade then
runs its core from the checkout again, where the original was never moved. The users, the two
groups, `/opt/avrana-arcade` and `/opt/avrana-party-games/venv` stay: they grant nothing and a
second migration reuses them. No data format changes in either direction.

Not reversed automatically: `www-data` stays a member of `avrana-front` (a group that owns
nothing yet).

## After

Update [SYSTEM](../SYSTEM.md) ("Who the services run as"), the key-owner lines of
[party-core-deploy](party-core-deploy.md) and [arcade-party-provider](arcade-party-provider.md),
the log paths in [logs-and-retention](logs-and-retention.md) (the arcade's move to
`/var/lib/avrana-arcade`), and write a dated finding with the checker output, the core's sha256
and the phone checks. `ops/provision-party-game-key.sh` then creates keys for `avrana-party`
without an override. The first native game is provisioned only after this (AVR-236).
