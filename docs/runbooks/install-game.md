# Runbook: install an EXPERIMENTAL `.avrgame` package (AVR-39)

Status: **EXPERIMENTAL procedure, NOT RUN on the appliance** (2026-10-10). Written from source.

Rehearsed on a disposable CI runner (real systemd): https://github.com/rcnechamkin/avrana-party/actions/runs/38082213316 (commit 44275a1, 78 checks) (`experiments/native-game/package-proof.sh`,
the `package` job of `service-trust-proof.yml`). That proves the mechanism with a test game on Ubuntu;
never on the Pi, never with real phones. Running any step on the Pi is an owner action: nothing in CI,
in an agent's task or in this document authorizes it. The package format ([AVRGAME-PACKAGE](../design/AVRGAME-PACKAGE.md)) is not an
SDK and is not v0, stable or frozen; the names below may change.

What it does: `install-game` takes one validated `.avrgame` file, stages its files into a root-owned
tree, records what it did, and then hands the game to the **same** provisioning path first-party native
games use (`provision-game`: key, registry entry, socket-activated unit instance, drop-in, Party Core
reload). It adds no second way to start a game.

## Trust: valid is not trusted

Validation only checks bytes. **Installing a package makes this appliance run third-party code**, as an
isolated systemd `DynamicUser=` instance, as root's explicit decision. The package cannot grant itself
anything: tier is always `community`; permissions are granted only by `--grant` and only when the
contract requested them; the entry path is always `/games/<id>/`; the command is an interpreter name
mapped by the appliance (`python3` becomes `/usr/bin/python3`) with the package's arguments, run in the
staged tree. Publisher, license and source are **unverified claims** shown as such (`list`); there is no
signature, publisher identity or provenance yet (AVR-58).

**What an installed package can and cannot do** (from [`deploy/games/avrana-game@.service`](../../deploy/games/avrana-game@.service) and ADR 0016; the unit is the only protection):

- **Can:** run arbitrary code as a throwaway `DynamicUser=` (its Python and whatever it ships); read any world-readable file on the host, including the install records (they hold no secret); connect to Party Core's internal Unix socket (`AVRANA_PARTY_SOCKET`, group `avrana-games`; authenticated by the game's own key only, so it can also flood it); keep state in its own `StateDirectory=` (`0700`, no disk quota); receive, in every launch, the roster of the session (participant id, display name, role) and sign results for its own session.
- **Cannot:** connect to another game's socket (`/run/avrana-games/<id>.sock` is `root:avrana-front` `0660` and a package is not in `avrana-front`; `package-proof.sh` runs the connect with that identity and sees it refused, while Party Core's internal socket accepts it); open IP sockets (`RestrictAddressFamilies=AF_UNIX`); write its own code (the staged tree is root-owned and `ProtectSystem=strict` is implied by `DynamicUser=`); read other games' private state or keys (each game gets only its own key as a credential; state directories are `0700` per dynamic user); see home directories or devices (`ProtectHome`, `PrivateDevices`).
- **Community-tier ceilings (AVR-336, conservative and not measured on a real game or the Pi):** the package's drop-in adds `MemoryMax=256M`, `TasksMax=64`, `CPUQuota=100%`, an empty `CapabilityBoundingSet=`, `PrivateNetwork=yes` (no abstract-namespace sockets of the host; path sockets such as Party's still work), `ProtectProc=invisible`, `ProtectClock`, `ProtectHostname`, `LockPersonality`, `RestrictRealtime` and `RestrictNamespaces`. First-party units are unchanged. A ceiling that is too low kills the package's process, not the host; the owner may tune them once a real game is measured.
- **NOT limited today:** no `SystemCallFilter=` beyond what `DynamicUser=` implies (a filter that is right for Python on both x86-64 and the Pi's arm64 has not been proved: an owner decision), no disk quota for `StateDirectory=` or `/tmp`, and **granted permissions are not enforced by Party Core at launch**. Because of that the installer fails closed instead: it refuses `--grant` of any permission the sandbox cannot provide (everything except `persistent_storage` and `party_roster`), and refuses a package that does not request `party_roster` or an install without `--grant party_roster`, since Party Core hands every game the roster whatever was granted. `persistent_storage` is also given regardless (every package unit has a state directory), so leaving it ungranted withholds nothing; the install says so.
- The hidden path options (`--games-root`, `--visible-root`, `--records-dir`, `--lock-file`, ...) exist for tests and rehearsals. They are for root only and must never be pointed at a directory a package or a non-root user can write.

In more detail, what the template unit ([`deploy/games/avrana-game@.service`](../../deploy/games/avrana-game@.service))
confines: a throwaway Unix user that owns nothing, `StateDirectory=` as the only writable place it is
given (`0700`), only its own key as a credential, `RestrictAddressFamilies=AF_UNIX` (no IP socket),
`ProtectHome`, `PrivateDevices`, `ProtectKernel*`, `UMask=0077`; ADR 0016 notes that `DynamicUser=yes` also
implies `ProtectSystem=strict`, `PrivateTmp`, `NoNewPrivileges` and `RestrictSUIDSGID`. What it does
**not** confine: CPU, memory and process count (no `MemoryMax`, `TasksMax` or `CPUQuota` yet; the
ceilings need a measured real game), a game that burns the Pi's CPU starves every other service on it; the
game can read what is world-readable on the host, and it can reach Party Core's internal Unix socket and
its own socket. The sandbox, not the package, is the only protection. The "granted permissions" are
recorded and shown; **Party Core does not enforce them at launch today** (it hands every game the launch
roster whatever was granted), so `party_roster` not being granted does not stop the roster arriving.

**The reference id `hello` cannot be installed as a package on a tree that carries the test fixture `contracts/games/hello.json`:** the installer refuses to shadow a repository contract (the CI proof deletes that fixture from its copied tree on purpose). A developer installs their own renamed game. **Validation cannot prove a package starts.** It checks bytes, the manifest and that the `-m` module exists in the package; the only gate is running it: the Games walkthrough's packaged-conformance step, and the real-systemd proof.

## Before (owner actions, not done by this command)

1. [ADR 0016 phase 1](service-users-migration.md), and [`ops/prepare-native-games`](prepare-native-games.md)
   (as for any native game: [provision-game](provision-game.md)).
2. The game origin the page needs ([game-origin](game-origin.md)) if the deployment uses one.
3. `/opt/avrana-games`: **an empty directory, root-owned, `0755`, with every ancestor root-owned and not
   writable by group or others.** The installer never creates it and refuses a root that fails
   `provision-game`'s own root-owned-code rule.
4. Party Core's `/etc/avrana-party/party-core.json` names the install records directory:
   `"packages": "/etc/avrana-party/packages.d"` (absent = the feature is off and Party Core behaves
   exactly as before). `install-game` refuses to run when the key is missing, and never edits the file.
5. The deployed code tree has `ops/install-game` (this change); run it from there.

## Commands (root unless noted)

```
sudo /opt/avrana-party/current/ops/install-game install FILE.avrgame [--grant PERM ...] [--dry-run]
sudo /opt/avrana-party/current/ops/install-game remove ID [--keep-state] [--dry-run]
     /opt/avrana-party/current/ops/install-game list [--json]
     /opt/avrana-party/current/ops/install-game verify ID
```

Exit 0 done, 1 refused or failed (reason on stderr, never a key), 2 usage. Always `--dry-run` first: it
runs every check that changes nothing and prints what would change.

`install` refuses, before writing anything: not root; an archive that fails validation (hostile entries,
bad hashes, unsupported `format` or `requires`: compatibility fails closed); an id that is a first-party
game, reserved, already installed (any version: "remove it first"; upgrade and rollback are not
implemented, AVR-58 and AVR-60), or already provisioned by other means; an interpreter that is missing or
not root-owned; a games root that is not trusted; a leftover from an interrupted run (see below).
`--grant` names a permission the operator allows; the grant is requested ∩ allowed. Party Core does not
enforce grants at launch, so the installer fails closed (AVR-336): it refuses `--grant` of a permission the
sandbox cannot provide (all but `persistent_storage` and `party_roster`), and it refuses a package that does not
request `party_roster`, or an install without `--grant party_roster`, because the roster reaches every game
regardless. Other requested-but-ungranted permissions, and a grant the package never requested, are said in the
output and do not stop the install.

## What install leaves

| Where | What |
|---|---|
| `/opt/avrana-games/<id>/<version>-<sha12>/` | the package files, `root:root`, directories `0755`, files `0644`, no links |
| `/etc/avrana-party/packages.d/<id>.json` | the install record (`root`, `0644`, no secret): id, version, archive sha256, per-file sha256, the validated Game Contract, the grant, the publisher/license claims |
| `/etc/avrana-party/game-keys/<id>.key`, `games.d/<id>.json`, `avrana-game@<id>.service.d/exec.conf`, `avrana-game@<id>.socket` | what `provision-game` makes for any native game |

Party Core is **reloaded, never restarted**: at reload it reads the records again, re-validates each, and
gets the game's contract from the record. A record that fails validation is refused by itself and
logged (`install record refused: <id>: ...`); the repository's games and the other packages keep working.

## Failure and repair

Install is all or nothing. Each step is recorded as it begins and a failure undoes them in reverse
(provisioning removed, record deleted, tree deleted, Party Core reloaded), then reports the original
failure. If the undo itself fails, the message says so; run `remove ID`. A crash (power, `kill -9`) can
leave a partial state: a staging directory (cleaned by the next install), a tree without a record, a
record without a tree, or a provisioned game without a record. `remove ID` clears any of them and is safe
to repeat; `install` refuses to guess. `remove` deletes the staged files first and the install record LAST, so every interrupted state keeps the evidence that the id is a package; it clears an id only on that evidence (a record, a tree of the shape this installer makes, or a drop-in running from it) and **never a first-party game: for an id of the repository it requires a genuine install record**, so a stray `/opt/avrana-games/<id>` directory cannot make it deprovision one. A hang-up, TERM or Ctrl-C during `install` unwinds it like a failure. A lock file (`/run/avrana-install-game.lock`) stops two runs
interleaving. `remove` is refused while the game has a session (end it from Party Home), never touches a
first-party game, and with `--keep-state` leaves the game's `/var/lib/avrana-games/<id>`.

## Reverse

`install-game remove ID` (units, key, registry entry, socket, state, record, staged files, one more Party
reload). It leaves nothing for that id. The shared template units stay (other games use them).

## Limitations (known, deliberate)

- Not run on the Pi. No upgrade, rollback, signing, repository or permission prompts.
- The phone's Party Home lists games from a **static, generated `web/party/catalog.json`**. Installing a
  package does not change it, so on an appliance today a package is *provisioned and offered by Party
  Core* but has **no tile and no navigation** in the phone UI until a catalog that includes it is served.
  `python3 -m avrana.contracts.catalog --packages DIR --out FILE` generates one; where it is served from
  is an owner decision (see [AVRGAME-PACKAGE](../design/AVRGAME-PACKAGE.md)).
- The community-tier ceilings are conservative defaults, not measured on a real game; there is no syscall filter and no disk quota; the tree is only as trustworthy as the person who installed it.
