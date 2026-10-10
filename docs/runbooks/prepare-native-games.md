# Runbook: prepare an appliance for native games (ADR 0016 section 9 phase 2, AVR-304)

Status: **PROPOSED procedure, NOT RUN on the appliance** (2026-10-07). Written from source. A Linux CI
runner with real systemd rehearses the whole sequence on a disposable host
(`experiments/native-game/prepare-proof.sh`); that proves the mechanism, not the Pi. Running any step
on the Pi is an owner action: nothing in CI, in an agent's task or in this document authorizes it.
**Nothing in this repository runs `ops/prepare-native-games` on the Pi.**

What it does: one command, run as root, brings an appliance that already has
[ADR 0016 phase 1](service-users-migration.md) to the state [`provision-game`](provision-game.md)
needs, can be run again without changing anything, checks what it did, and can be reversed. It
replaces three hand steps (a unit file, a socket unit, a line of `party-core.json`) with one command
that keeps the earlier files first. It creates no user or group, downloads nothing, touches no nginx,
DNS or certificate file, and provisions no game.

| What | Before | After |
|---|---|---|
| `/etc/systemd/system/avrana-party-core.service` | the earlier unit: no `ExecReload=`, no `Wants=` of the socket unit | the repository's `deploy/party-core/avrana-party-core.service`: `ExecReload=/bin/kill -HUP $MAINPID` (what `systemctl reload` sends, a `SIGHUP`), and it wants and follows the socket unit |
| `/etc/systemd/system/avrana-party-core.socket` | none | the repository's `deploy/party-core/avrana-party-core.socket`, installed, enabled and listening: `/run/avrana-party/internal.sock`, `avrana-party:avrana-games 0660` |
| `/etc/avrana-party/party-core.json` | no `registry` key | `"registry": "/etc/avrana-party/games.d"` added as one member; **every other byte of the file is as it was** (key order, spelling, layout, mode and owner). A different `registry` value is replaced where it stands |
| `/var/backups/avrana-party/native-games-<UTC>/` | none | the before-state: the unit and `party-core.json` the run replaced, and a `state.json` (digests, never content) |
| Party Core | running without the socket | restarted when it has to be (see "Will it restart Party Core?"), so that it is handed the socket |

## Before (an owner action, not done by this command)

1. [ADR 0016 phase 1](service-users-migration.md) is applied: the user `avrana-party` and the groups
   `avrana-front` and `avrana-games`. Without them the command refuses, says which are missing, and
   changes nothing (a dry run refuses too). It never creates a user or a group.
2. The release that carries this command is deployed with [`ops/deploy.sh`](deploy.md), and the
   command is run **from that release**, `/opt/avrana-party/current`. It installs the two unit files from
   that tree as root, so it refuses a tree anyone but root can write (a checkout in a home directory):
   "a unit that root installs comes only from root-owned code".
3. `/etc/avrana-party/party-core.json` exists and is valid JSON. The command never creates it, and
   refuses (nothing changed) a file it cannot edit one member of with certainty: not JSON, not UTF-8,
   not an object, or `"registry"` named twice.
4. Pick a moment with no game running. If the run has to restart Party Core it ends the party: members
   join again and a game session cannot survive it, so the command **refuses while a game session is
   running** and tells you to wait until the party is back at Party Home. Read the plan with
   `--dry-run` first.

## Commands

Run from the deployed tree, as root:

```bash
ssh -t party "sudo /opt/avrana-party/current/ops/prepare-native-games --dry-run"
ssh -t party "sudo /opt/avrana-party/current/ops/prepare-native-games"
ssh -t party "sudo /opt/avrana-party/current/ops/prepare-native-games --reverse [BACKUP_DIR]"
```

`ops/prepare-native-games` runs `python3 -m avrana.ops.prepare_native_games` from its own tree. The dry run
prints every file and unit it would change, every `systemctl` it would run, where it would keep the
before-state, and **whether it would restart Party Core**, and changes nothing. A real run prints the same
plan first (the restart statement comes before the first change), keeps the before-state, applies, then
prints its checks and the exact command that reverses it.

Exit status: `0` done, nothing to change, or a dry run; `1` refused or failed before anything was changed
(the reason is on stderr, ending "nothing was changed"); `2` usage; `3` the host was changed and a step or
check after that failed ("NOT complete": run it again to finish, or reverse).

### Will it restart Party Core?

A process is handed a socket only as it starts, and systemd will not start or restart a socket unit while
the service it triggers is running. So Party Core is **stopped, the socket made ready, and Party Core
started again**, never `systemctl restart`. It is decided from the host as it is:

| Party Core | The command |
|---|---|
| running and not holding the socket (it started before the socket unit was listening: always so on the earlier host) | restarts it, and says so first. Refused while a game session is running. A "no session" answer is asked again after 6 s (Party Core caches its status for 5 s) |
| running and holding the socket; only the `registry` key is missing | `systemctl reload` (a `SIGHUP`): no restart |
| running and holding it; only the service unit or a comment of the socket unit differs | no restart; it keeps the unit it started with until its next restart |
| running and holding it; the socket unit's directives differ | restarts it: the socket is restarted and Party Core has to take the new one |
| stopped or failed | left as it is, never started by this command; it takes the socket and the registry when it next starts |
| starting or stopping | refused ("not settled"); run it again in a moment |

Party Core is asked on loopback, never through a proxy, with the first of `hosts` as its Host header, as
`provision-game` asks it. Only "nobody is listening" means no party; a timeout, an error or an answer it
cannot read refuses. Between the stop and the start the run holds off `SIGHUP`, `SIGINT` and `SIGTERM` (a
dropped SSH session, Ctrl-C), so it cannot be ended there with Party Core stopped; if a step in that
window fails, Party Core is started again and the message says where it stands.

### A second run

Nothing is decided from what an earlier run did. A host already prepared gets "nothing to change", no
`daemon-reload`, no restart, no new before-state. A run that stopped half way is finished by running it
again: it adds to the before-state the earlier run kept, so a reverse still goes back to how the host was
before the first change.

## Check afterwards

The command prints its own checks (the installed files are the repository's, systemd has loaded
`ExecReload=`, the socket is enabled and listening, `internal.sock` is a socket with the right owner,
group and mode, the key is in the file, Party Core holds the socket and answers). By hand:

```bash
systemctl is-active avrana-party-core avrana-party-core.socket          # active, active
systemctl is-enabled avrana-party-core.socket                           # enabled
stat -c '%F %a %U:%G' /run/avrana-party/internal.sock                   # socket 660 avrana-party:avrana-games
systemctl show -p CanReload --value avrana-party-core                   # yes
sudo systemctl reload avrana-party-core && systemctl is-active avrana-party-core   # a reload, not a restart
grep -n '"registry"' /etc/avrana-party/party-core.json
sudo /opt/avrana-party/current/ops/prepare-native-games                 # "nothing to change"
```

Then a real `sudo /opt/avrana-party/current/ops/provision-game <slug>` is no longer refused for a
missing `registry` key, and its last step, `systemctl reload avrana-party-core.service`, works (a dry run
of `provision-game` never made the registry check; the real run did). On a phone over the Party Wi-Fi,
open Party Home and join again: the party was restarted. Record the output in a dated finding;
[SYSTEM](../SYSTEM.md) changes only from that evidence.

## Reverse

```bash
sudo /opt/avrana-party/current/ops/prepare-native-games --reverse --dry-run
sudo /opt/avrana-party/current/ops/prepare-native-games --reverse                 # the newest before-state not yet reversed
sudo /opt/avrana-party/current/ops/prepare-native-games --reverse /var/backups/avrana-party/native-games-<UTC>
```

**Refused while any native game is provisioned** (a registry entry or an `avrana-game@<slug>` unit):
a reverse would take away what the game needs. Remove each first with `provision-game <slug> --remove`
([provision-game](provision-game.md)); the dry run is refused too.

It puts the kept unit and `party-core.json` back byte for byte, with their earlier mode and owner,
removes the socket unit file if there was none before, disables and stops the socket unit (if the run
enabled it), removes the socket node systemd leaves behind, and runs `daemon-reload`. What it
overwrites is first kept in `replaced/` of the before-state, and it says when a file was changed after
this command wrote it. **It never restarts Party Core**: that keeps running as it is until its next
restart, still holding the socket it was handed (which no longer has a path), and `systemctl reload` is
refused again, as on the earlier host. The one exception is a Party Core that is `failed` when you
reverse (the likely reason to): it is reset and started again, on the earlier files.

A reverse needs only root and the before-state, not phase 1. A second one says there is nothing to
reverse. It leaves the phase 1 identities, the `avrana-game@` template units and
`/etc/avrana-party/games.d`.

## When it stops half way

"NOT complete" names the step that failed, whether Party Core is running, and both ways on: the same
command again, or the reverse command with the before-state's directory. A Party Core the run had stopped
is started again; if that fails the message says it is stopped, and `journalctl -u avrana-party-core -n
50` says why. The run never edits a file it cannot restore: the kept copy is written before the first
change.

## Not in this step

nginx, DNS, certificates and `games.avrana.net` (AVR-226 step 4); provisioning any game
([provision-game](provision-game.md), AVR-236; Checkers, AVR-238); users and groups (phase 1, AVR-256);
the clean-target rebuild inventory (`avrana.ops.rebuild`); keeping the installed Party Core unit in step
with later releases (`ops/deploy.sh` does not).

## Rehearsal

`python3 -m unittest discover -s tests/unit -p test_prepare_native_games.py` runs it on a scratch
directory with a recording stand-in for `systemctl` (`--root DIR` with `AVRANA_SYSTEMCTL` names a simulated
host; `AVRANA_BACKUP_ROOT` and `AVRANA_PARTY_CORE_URL` move the before-state and the status query).
Real systemd: `sudo AVRANA_PREPARE_PROOF=1 bash experiments/native-game/prepare-proof.sh`, run by the
`Service trust proof` workflow (job `prepare-native-games`) on a disposable runner, **never the Pi**:
a phase 1 host with the earlier unit, the run, `provision-game` of the stand-in with a full session, the
reverse refused with a game provisioned and done after its removal.

## Related

[ADR 0016](../adr/0016-service-identities-and-local-trust-boundary.md) (sections 4, 8, 9),
[provision-game](provision-game.md), [service-users-migration](service-users-migration.md),
[party-core-deploy](party-core-deploy.md), [`deploy/README.md`](../../deploy/README.md),
`deploy/party-core/avrana-party-core.{service,socket}`.
