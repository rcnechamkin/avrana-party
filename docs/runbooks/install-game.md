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
contract requested them; the entry path is always `/games/<id>/`; the command is a runtime name
mapped by the appliance (`python3` becomes `/usr/bin/python3`; `node` becomes the pinned build under
`/opt/avrana-runtimes/`, when the owner installed it) with the package's arguments, run in the
staged tree. Nothing is fetched, built or run at install for either runtime: no `npm install`, no install script. Publisher, license and source are **unverified claims** shown as such (`list`); there is no
signature, publisher identity or provenance yet (AVR-58).

**What an installed package can and cannot do** (from [`deploy/games/avrana-game@.service`](../../deploy/games/avrana-game@.service) and ADR 0016; the unit is the only protection):

- **Can:** run arbitrary code as a throwaway `DynamicUser=` (its Python and whatever it ships); read any world-readable file on the host, including the install records (they hold no secret); connect to Party Core's internal Unix socket (`AVRANA_PARTY_SOCKET`, group `avrana-games`; authenticated by the game's own key only, so it can also flood it); keep state in its own `StateDirectory=` (`0700`, no disk quota) when `persistent_storage` is granted; receive, in every launch, the roster of the session (participant id, display name, role) and sign results for its own session.
- **Cannot:** connect to another game's socket (`/run/avrana-games/<id>.sock` is `root:avrana-front` `0660` and a package is not in `avrana-front`; `package-proof.sh` runs the connect with that identity and sees it refused, while Party Core's internal socket accepts it); open IP sockets (`RestrictAddressFamilies=AF_UNIX`); write its own code (the staged tree is root-owned and `ProtectSystem=strict` is implied by `DynamicUser=`); read other games' private state or keys (each game gets only its own key as a credential; state directories are `0700` per dynamic user); see home directories or devices (`ProtectHome`, `PrivateDevices`).
- **Community-tier ceilings (AVR-336; provisional values, to be revisited with measurements on a real game and the Pi, owner decision 2026-10-10):** the package's drop-in adds `MemoryMax=256M`, `TasksMax=64`, `CPUQuota=100%`, an empty `CapabilityBoundingSet=`, `PrivateNetwork=yes` (no abstract-namespace sockets of the host; path sockets such as Party's still work), `ProtectProc=invisible`, `ProtectClock`, `ProtectHostname`, `LockPersonality`, `RestrictRealtime` and `RestrictNamespaces`. First-party units are unchanged. A ceiling that is too low kills the package's process, not the host.
- **State directory follows the grant (AVR-336).** A community unit has its `StateDirectory=` (`0700`, from the template) only when `persistent_storage` was requested and granted; otherwise the drop-in resets it (`StateDirectory=`), so the unit has no `$STATE_DIRECTORY` and no persistent directory (`package-proof.sh` checks both cases on a real systemd). `/tmp` is `PrivateTmp` (implied by `DynamicUser=`): private to the unit and discarded when it stops. No game or gamekit in use reads `$STATE_DIRECTORY` (Hello Party requests only `party_roster`).
- **NOT limited today:** `SystemCallFilter=` is **deferred** (owner decision 2026-10-10) until an arm64 run on the Pi with a real game proves a filter; no disk quota (a granted state directory, or `/tmp` while the unit runs, can fill the disk); and **granted permissions are not enforced by Party Core at launch**, so the installer fails closed instead: it refuses `--grant` of any permission the sandbox cannot provide (everything except `persistent_storage` and `party_roster`), and requires `party_roster` (above). `persistent_storage` is enforced by the unit as described.
- The hidden path options (`--games-root`, `--visible-root`, `--records-dir`, `--lock-file`, ...) exist for tests and rehearsals. They are for root only and must never be pointed at a directory a package or a non-root user can write.

In more detail, what the template unit ([`deploy/games/avrana-game@.service`](../../deploy/games/avrana-game@.service))
confines: a throwaway Unix user that owns nothing, `StateDirectory=` (only with `persistent_storage` granted) as the only persistent place it is
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
6. For the package to have a tile on a phone (AVR-337): `avrana-party.nginx` deployed with its exact
   `location = /party/catalog.json` (an owner deploy of the nginx site; `nginx -t`, reload), and
   `/var/lib/avrana-party` present (`ops/deploy.sh` makes it, root, `0711`; `install-game` creates the
   `catalog/` directory below it, `0755`). Without the nginx deploy the install still works and the
   catalog file is written, but nothing serves it. The web release (`/var/www/avrana-party/web/current`)
   must exist: the effective catalog is the release's `catalog.json` plus the package rows.

7. **Only for a package whose runtime is `node`** (`install-game install --dry-run` says so; AVR-68,
   EXPERIMENTAL, optional): the pinned Node build. On another machine, download the official tarball for
   the appliance's architecture (`node-v<version>-linux-arm64.tar.xz` for the Pi; the version and its
   SHA-256 are in `avrana/avrgame/node_pin.py`), copy it to the appliance, then, offline:

   ```
   sudo /opt/avrana-party/current/ops/install-node-runtime install node-v<version>-linux-arm64.tar.xz --dry-run
   sudo /opt/avrana-party/current/ops/install-node-runtime install node-v<version>-linux-arm64.tar.xz
        /opt/avrana-party/current/ops/install-node-runtime verify
   ```

   It refuses any file whose SHA-256 is not the pin, downloads nothing, and leaves
   `/opt/avrana-runtimes/node-<version>/` (root; `bin/node`, `LICENSE`, `avrana-runtime.json`; no npm).
   Reverse: `sudo ops/install-node-runtime remove` (refused while a package runs on it). An appliance
   without it runs Python packages exactly as before and refuses a Node package with a message naming
   this step. Not run on the Pi or on arm64.

## Commands (root unless noted)

```
sudo /opt/avrana-party/current/ops/install-game install FILE.avrgame [--grant PERM ...] [--dry-run]
sudo /opt/avrana-party/current/ops/install-game remove ID [--keep-state] [--dry-run]
     /opt/avrana-party/current/ops/install-game list [--json]
     /opt/avrana-party/current/ops/install-game verify ID
sudo /opt/avrana-party/current/ops/catalog-overlay refresh   # rewrite (or remove) the effective catalog
     /opt/avrana-party/current/ops/catalog-overlay check|show   # stale? / print what it would serve
```

Exit 0 done, 1 refused or failed (reason on stderr, never a key), 2 usage. Always `--dry-run` first: it
runs every check that changes nothing and prints what would change.

`install` refuses, before writing anything: not root; an archive that fails validation (hostile entries,
bad hashes, unsupported `format` or `requires`: compatibility fails closed); an id that is a first-party
game, reserved, already installed (any version: "remove it first"; upgrade and rollback are not
implemented, AVR-58 and AVR-60), or already provisioned by other means; a runtime that is missing (a `node` package without step 7) or
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
| `/var/lib/avrana-party/catalog/catalog.json` | the **effective catalog** (`root`, `0644`): the release catalog plus a row per installed package, appended after the first-party rows; absent when no package is installed |
| `/etc/avrana-party/game-keys/<id>.key`, `games.d/<id>.json`, `avrana-game@<id>.service.d/exec.conf`, `avrana-game@<id>.socket` | what `provision-game` makes for any native game |

Install and remove then regenerate the effective catalog. **Fail closed:** if it cannot be written (no
release catalog, a full disk) the install is undone and exits 1; a failed regeneration removes the overlay,
so the appliance serves the committed catalog (no package tile) until `catalog-overlay refresh` works.
A new web release or a rollback (`ops/install-party-web.sh`) regenerates it too, so a deploy never hides
new first-party games. `ops/deploy.sh` does the same on every path that moves the web release: after the web install of a
deployment, the nested `--rollback`/`--auto-rollback` and `--recover` (using the code release that is running, because the
target commit may predate the overlay), and when a failed or interrupted run puts the earlier web release back. Where the overlay
cannot be regenerated it is removed, with a `WARNING: catalog:` line in the log: warning only, the deployment, rollback,
manifest and smoke are unaffected, and the first-party catalog is served until `sudo ops/catalog-overlay refresh`.

**After a rollback to a commit that predates the overlay** (no `avrana/ops/catalog_overlay.py` in it) there is no code
to regenerate it: the overlay is removed, the first-party catalog is served, and installed packages have no tile (they
stay installed; the log says `WARNING: catalog:`). The next forward deploy brings the tiles back. To bring them back
sooner, run the tool of any newer code release, which finds the live web release by itself:
`sudo /opt/avrana-party/releases/<newer sha>/ops/catalog-overlay refresh`. That works only while such a release still
exists: `ops/deploy.sh --keep` prunes old code releases after a passed smoke, so use one that is listed in
`/opt/avrana-party/releases/`, or wait for the next forward deploy.

**Concurrent installs.** `ops/deploy.sh` waits up to 30 seconds, once, for a running `install-game` before it refreshes
the catalog (lock order: the deploy lock, then the install lock; `install-game` never takes the deploy lock). On a
deployment that wait happens with the units stopped, so a running install delays it by at most 30 seconds; after a
failed or interrupted run the file is removed at once and the site file and units are put back first, and only then does
the refresh wait. A refresh also repeats itself (at most three times) when the release catalog changed while it ran. An
install that was in flight during a web switch can still publish the previous release's catalog for a short window (a
switch after its last check and before it returns); the deploy's own refresh, which waits for that install, replaces it
within its wait. Until then phones are served that install's catalog, or the first-party catalog when it was removed. If
the wait runs out, the overlay is removed with a `WARNING: catalog:` line that names the reason.

**Known limit.** Neither `/party/api/status`, the smoke checks nor the deployment manifest look at the effective
catalog: an overlay that disagrees with the install records (by hand edit, a failed refresh that could not remove it)
shows only in `ops/catalog-overlay check`, which `ops/install-party-web.sh` runs as a warning after it refreshes and an
operator can run at any time. This is deliberate for now (owner decision 2026-10-10: warning only); status integration is
not part of AVR-337. If a refresh fails the overlay is removed and the web install prints a loud warning (it never fails
the deploy). The warning is output only: it never changes the exit status of the web install, the deploy, smoke, the
deployment manifest or `/party/api/status`, and it is silent when no package records and no overlay exist.
`catalog-overlay check` can also be run by hand at any time.

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

## Upgrade note: records from before the roster rule (AVR-336)

A record whose `permissions_granted` lacks `party_roster` is no longer read by Party Core (it logs
`install record refused` and leaves that game out). `install-game list` shows it as `REFUSED <id>: ...` and
`install-game verify <id>` reports it, both with the remedy: `install-game remove <id>`, then install the
package again with `--grant party_roster`. No package has been installed on an appliance yet, so this is a
precaution. The rule is an owner decision of 2026-10-10 for the experimental format, to be revisited before any freeze (AVR-37): see [AVRGAME-PACKAGE](../design/AVRGAME-PACKAGE.md).

## Reverse

`install-game remove ID` (units, key, registry entry, socket, state, record, staged files, one more Party
reload). It leaves nothing for that id. The shared template units stay (other games use them).

## Limitations (known, deliberate)

- Not run on the Pi. No upgrade, rollback, signing, repository or permission prompts.
- The committed `web/party/catalog.json` is never changed by an install. A package's tile comes from the
  effective catalog above (see [AVRGAME-PACKAGE](../design/AVRGAME-PACKAGE.md)), and only once the nginx
  location is deployed; it shows the game's kind icon, not the package's own `web/icon.svg` (custom package
  icons are deferred and the CSP is not relaxed: owner decision 2026-10-10).
- The community-tier ceilings are provisional values, to be revisited with measurements; there is no syscall filter (deferred) and no disk quota; the tree is only as trustworthy as the person who installed it.
