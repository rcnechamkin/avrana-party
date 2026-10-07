# Runbook: provision a native game (ADR 0016 sections 3 to 5 and 8, AVR-236)

Status: **PROPOSED procedure, NOT RUN on the appliance** (2026-10-06). Written from source. A Linux CI
runner with real systemd rehearses the whole lifecycle with a test-only stand-in game
(`experiments/native-game/proof.sh`); that proves the mechanism, not the Pi. Running any step on the
Pi is an owner action: nothing in CI, in an agent's task or in this document authorizes it. **Nothing in
this repository runs `provision-game` on the Pi, and no product game has a `runtime` grant yet**
(Checkers, AVR-238, is the first). Until one does, the command refuses every real game.

What it does: makes a game from this repository a native game of this appliance with one command,
run as root. A native game runs as its own `DynamicUser=` instance of the shared template
`avrana-game@.service`, behind its own Unix socket, with its own key handed over as a systemd
credential. The command creates no Unix user or group, never restarts Party Core (it asks it to
reload), and never prints a key.

## Before (an owner deployment, not done by this command)

1. [ADR 0016 phase 1](service-users-migration.md) is applied: the user `avrana-party`, the groups
   `avrana-front` (members `avrana-party` and `www-data`) and `avrana-games`, and
   `/etc/avrana-party/game-keys` (`0700`, `avrana-party`). The command refuses without them.
2. **Reinstall Party Core's service unit first**: `deploy/party-core/avrana-party-core.service` gained
   `ExecReload=` (what `systemctl reload` sends: a `SIGHUP`) and `Wants=` the socket unit, and the
   installed copy on an older appliance has neither. Without `ExecReload=` every provision and
   rotation fails at its last step, `systemctl reload avrana-party-core.service`, and the command
   says so (exit 1, "no ExecReload="). Install it, `systemctl daemon-reload`, and only then provision.
   Party Core runs from a root-owned release tree (`/opt/avrana-party/current`, built by
   [`ops/deploy.sh`](deploy.md)), with its game-facing socket unit installed and enabled
   (`deploy/party-core/avrana-party-core.socket`) and `"registry": "/etc/avrana-party/games.d"` in
   `/etc/avrana-party/party-core.json`. Without the `registry` key Party Core never sees a
   provisioned game, and the command says so and refuses. Rotation asks Party Core on
   loopback whether the game has a session, naming the first entry of Party Core's `hosts`.
3. The game's code is under a root-owned path (a release tree, never a home directory), and its
   Game Contract is in `contracts/games/<slug>.json`. The command checks this before it writes
   anything: the grant's `command[0]` and `working_directory`, and every directory above each (a
   symbolic link is followed, and where it leads is checked too), must exist, belong to root (uid 0)
   and be writable by neither group nor others. Otherwise it refuses and names the path: "a native
   game runs only root-owned code (ADR 0016 section 2)". The grant's paths may not contain `.`,
   `..` or `//`. A dry run does not make this check.
   What the check does not do: it looks at the path as written and at where it finally leads, not
   at a link in the middle of a chain of links, and it does not look inside the working directory.
   A release tree staged by `ops/deploy.sh` (one `current` link, files written by root) satisfies
   both; anything else is the operator's to keep root-owned.
4. The appliance profile (`contracts/appliances/avrana-pi4.json`) has a grant for the game with a
   `runtime`: `{"command": ["/usr/bin/python3", "-m", "..."], "working_directory": "/opt/..."}`.
   A grant without `runtime` is refused: there would be nothing to start.

## Commands

Run from the deployed tree, as root (`ops/provision-game` is the same thing):

```bash
cd /opt/avrana-party/current
sudo python3 -m avrana.ops.provision_game <slug> --dry-run     # what would change; changes nothing
sudo python3 -m avrana.ops.provision_game <slug>               # provision, or reconcile to match the grant
sudo python3 -m avrana.ops.provision_game <slug> --rotate      # replace the key
sudo python3 -m avrana.ops.provision_game <slug> --remove [--keep-state]
```

Exit status: 0 done, 1 refused or failed (the reason is on stderr; it never names a key), 2 usage.

## What each leaves

| Command | Keeps | Writes or replaces |
|---|---|---|
| `<slug>` (first run) | | the key (`0600 avrana-party`), the registry entry (`games.d/<slug>.json`), the two shared template units if missing or different, the exec drop-in (`avrana-game@<slug>.service.d/exec.conf`, from the grant's `runtime`); enables and starts `avrana-game@<slug>.socket`; asks Party Core to reload |
| `<slug>` again (reconcile) | key, state | registry entry, templates and drop-in rewritten to match; a second run prints "nothing to change" and writes nothing. It still enables the socket and asks Party Core to reload, **every run**: if a run failed half way (files written, then `systemctl` failed), run it again and it finishes. A running game is **not** restarted: it keeps the old command until it next stops |
| `--rotate` | state | the key; stops the game so its next start loads the new one; asks Party Core to reload. **Refused while the game has a session** (it asks Party Core; wait for the round to end) |
| `--remove` | the shared template units | stops and disables the units; removes the registry entry, the drop-in, the key, the runtime socket and the state directory (`--keep-state` keeps it; it is inert without a key). Asks Party Core to reload again as the last step, also when nothing was left, so a second `--remove` repairs a Party Core that kept the game. **Refused while the game has a session**, as `--rotate` is: end it from Party Home first. Works for a game whose contract is already gone, and needs neither the contracts nor ADR 0016 phase 1, only root |

The game's process and socket: `/run/avrana-games/<slug>.sock` (`root:avrana-front 0660`, held by
systemd), state in `/var/lib/avrana-games/<slug>`, its key only as a credential. Party Core is
reloaded (`systemctl reload`, a `SIGHUP`), never restarted, so the party survives.

`--rotate` and `--remove` ask Party Core on loopback whether that game has a session. Only "nobody is
listening" (connection refused) means no party and lets them go on; a timeout (10 s), another
error or an answer they cannot read refuses, because Party Core may be there and busy. A non-root
`--dry-run` that cannot read the key store (`/etc/avrana-party/game-keys` is `0700`) says "needs
root to read the key store": run it with `sudo`.

**Maintenance.** To stop Party Core, stop `avrana-party-core.socket` as well as
`avrana-party-core.service`: a game's report arrives on that socket and starts the service again.
While Party Core is stopped the command still provisions, rotates and removes: there is nothing to
reload, and Party Core reads the registry when it starts. A reload that fails while Party Core is
running is still a failure.

## Verify

```bash
sudo python3 -m avrana.ops.boundary --phase 2      # the game must be running: it checks loaded units
systemctl status avrana-game@<slug>.socket
```

Phase 2 asks six things of a running native game and Party Core: its groups, no IP networking,
hardening, the game's socket, Party Core's internal socket and the members of `avrana-front`. A
passing run is evidence about that host at that moment, not about the game.

## Reverse

`provision_game <slug> --remove`. It leaves the template units and Party Core's socket unit in
place (other games use them) and the phase 1 identities (they belong to the installation, not a
game). Rolling back Party or Games code with `ops/deploy.sh` does not touch any of this.

## Related

[ADR 0016](../adr/0016-service-identities-and-local-trust-boundary.md) (sections 3 to 5, 8),
[`deploy/README.md`](../../deploy/README.md), `deploy/games/avrana-game@.*`,
`ops/provision-party-game-key.sh` (the legacy and arcade keys, not native games).
