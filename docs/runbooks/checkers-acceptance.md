# Runbook: native Checkers real-device acceptance (AVR-261)

Status: **PROPOSED owner-run procedure, NOT RUN on the appliance** (2026-10-07).
This packet prepares [AVR-261](https://linear.app/avranakern/issue/AVR-261/play-checkers-on-real-phones-over-the-pis-wi-fi).
CI, Chromium and disposable-host systemd evidence do not prove Raspberry Pi or phone readiness.
No command here has been executed on the Pi as part of this sprint. An agent cannot close AVR-261.

## Release gate and run record

Fill these fields from the final implementation report **before** deployment; blank fields block the run.

| Field | Value |
|---|---|
| Exact tested Party SHA | Pending final sprint verification; not verified by this packet |
| Exact tested Games SHA | Pending final sprint verification; not verified by this packet |
| Linux CI and cross-repo contract run URLs | Pending final sprint verification |
| Final-head independent review evidence | Pending final sprint verification |
| Deployment date and operator | Not run |
| Actual deployed Party/Games SHAs (`/party/api/status`) | Not run |
| iPhone model, iOS and Safari versions | Not run |
| Android model, Android and Chrome versions | Not run |
| Phase-1, bootstrap, phase-2 and phone evidence | Not run |

Owner merge prerequisites: reviewed AVR-304 Party [PR #92](https://github.com/rcnechamkin/avrana-party/pull/92),
reviewed AVR-238 paired Party integration and Games [PR #54](https://github.com/rcnechamkin/avrana-party-games/pull/54),
and green Linux/cross-repo CI at the exact compatible heads. Follow the final paired PRs' merge order and
[CROSS-REPO](../CROSS-REPO.md). PR #92 is an unmerged prerequisite until GitHub says otherwise;
an integration worktree that includes it is not `main`. Revalidate the merged release pair if its tree differs.
Do not use deployment override flags to bypass a dirty checkout, live session or unmerged target.

Accepted architecture is [ADR 0013](../adr/0013-party-and-game-browser-origins.md),
[ADR 0014](../adr/0014-native-games-isolated-lan-games-retired.md) and
[ADR 0016](../adr/0016-service-identities-and-local-trust-boundary.md).
Use [SYSTEM](../SYSTEM.md) and live status for deployed facts. This run is Full Mode;
Limited Mode physical acceptance is explicitly outside AVR-261. It does not freeze a package,
SDK or top-level game presentation requirement (AVR-37/38 and AVR-83/292 own those decisions).

## Read-only preflight and rollback preparation

Run read-only checks on the appliance, recording only sanitized evidence. From the **target Party
release** when available (otherwise a reviewed staging tree), validate the live config against its contracts:

```bash
python3 -m avrana.contracts.party_config --check /etc/avrana-party/party-core.json
systemctl is-active avrana-party-core avranaparty-games avranaparty-arcade nginx
sudo python3 -m avrana.ops.boundary --phase 1
getent hosts party.avrana.net games.avrana.net
openssl x509 -in /etc/avrana-party/tls/current/fullchain.pem -noout -dates -ext subjectAltName
curl -s https://party.avrana.net/party/api/status
```

**Gauntlet hazard:** an old `games.arcade-gauntlet2.max_players: 2` in the live config disagrees
with the four-player contract. The checker fails and names that disagreement without dumping the config.
Do not restart into that mismatch. The owner must back up the config and remove obsolete contract-derived
player limits, leaving its URL, key path and timeout intact, then rerun the checker against the target
four-player contract. Do not solve this by reducing the contract or replacing the live config with an example.
The checker validates game metadata; separately confirm `hosts`, `origins`, `game_origins`, `registry`,
device-store path and status paths against the origin/provisioning runbooks without publishing the file.

Before changing anything, record the current SHAs, code/web release links and deployment manifest as in
[deploy](deploy.md). Keep root-only backups of the edited config, installed units/drop-ins, nginx site,
DNS settings and certificate links. Keep keys and runtime data out of Git and shared evidence. Retain
the deploy, service-user migration and native bootstrap backup paths; each reverses a different layer.
Review their reverse procedures against the actual host before proceeding. `ops/deploy.sh` rolls back
code/web releases; it does not undo identities, provisioning, config, DNS, TLS or installed units.

## Owner installation sequence

1. With no game running, stage both exact reviewed commits and follow [deploy](deploy.md), including
   its first-run procedure if the installed checkout predates the deploy tooling. Inspect its dry run
   before the real run. Record the backup path, smoke verdict and actual deployed SHAs.
2. Apply [service-users migration](service-users-migration.md) only if phase 1 has not been applied.
   Check the three credential sources, including EXPO, and root-owned releases/core/virtualenv first.
   Review installed units without exporting secret environment values. Record migration backup path,
   arcade core checksum, phase-1 boundary verdict and BLUFF/EXPO/Gauntlet launch checks. Migration is
   a separate consequential appliance operation; a dry run is not proof of runtime compatibility.
3. Apply [prepare-native-games](prepare-native-games.md) from the deployed root-owned Party release:

   ```bash
   sudo /opt/avrana-party/current/ops/prepare-native-games --dry-run
   sudo /opt/avrana-party/current/ops/prepare-native-games
   sudo /opt/avrana-party/current/ops/prepare-native-games
   ```

   Inspect the announced restart first; members may need to rejoin even with no game running. The
   repeated run should report nothing to change. Keep the printed reverse command. Check the
   internal socket (`avrana-party:avrana-games`, mode `0660`), enabled socket unit, `CanReload=yes`
   and registry path using that runbook. A provisioning dry run does not establish that an actual
   provision can reload Party Core or pass the real root-owned runtime path check.
4. Complete the coupled game-origin cutover described in
   [BROWSER-ORIGINS section 4](../design/BROWSER-ORIGINS.md#4-order-of-work-once-decided): trusted TLS
   covering both hostnames; LAN DNS for `games.avrana.net`; reviewed nginx game server/routing and
   `frame-ancestors https://games.avrana.net` on the Party bridge only; Party `game_origins`; and
   `AVRANA_PARTY_ORIGIN=https://party.avrana.net` for the legacy Games and arcade providers. The
   native provisioner derives that origin from the single usable `origins` entry. Bootstrap does
   none of this. If a reviewed cutover configuration is unavailable, stop this step and keep AVR-261
   blocked; inventing live routing is not acceptance. Install matching reviewed nginx/web artifacts,
   test with `nginx -t` before owner reload, and verify both phones trust both names without warnings.
   Keep the two repository nginx files generated and byte-identical. No Checkers-specific route,
   weakened Secure cookie, HSTS or broader service-worker scope is part of this procedure.
5. From `/opt/avrana-party/current`, provision through the existing installation path:

   ```bash
   sudo python3 -m avrana.ops.provision_game checkers --dry-run
   sudo python3 -m avrana.ops.provision_game checkers
   sudo python3 -m avrana.ops.provision_game checkers
   systemctl is-active avrana-game@checkers.socket
   ```

   Follow [provision-game](provision-game.md) for refusal/failure handling. Confirm the reviewed
   appliance grant points to the root-owned Games release. Keep the key private. Do not add Checkers
   to a parallel installer or hand-edit the runtime registry. Reconciliation preserves key/state,
   still enables the socket and reloads Party Core, and does not restart a running game.
6. Launch Checkers from Party Home to activate its process, then run from the deployed Party tree:

   ```bash
   sudo python3 -m avrana.ops.boundary --phase 2
   systemctl is-active avrana-game@checkers.service avrana-game@checkers.socket
   python3 -m avrana.ops.smoke
   ```

   Record every boundary rule; the phase-2 checker needs the game running to inspect loaded units.
   A passing verdict describes this host at this time. Refusals or unmet rules block acceptance.

## Physical acceptance: iPhone Safari and Android Chrome

Use two distinct devices on the Pi's own Wi-Fi, no internet dependency and no installed player app.
Record date, models, OS/browser versions and status/deployment SHAs with each run.

| Scenario | Required observation and evidence |
|---|---|
| Join and launch | Both join Party Home; host chooses Checkers; each receives a distinct seat and reaches the game origin. No certificate warning. |
| Boundary and presence | Bridge loads from Party origin without CSP refusal; host controls only for host; presence stays current. Game-origin requests hold no Party device cookie. If inspected, redact tickets/tokens/cookies. |
| Legal play | Alternate legal moves; other phone receives the board update. Exercise compulsory capture and kinging; an illegal move cannot change authoritative state. |
| Reload/lock | Reload one phone during a round, then lock it for at least a minute. It rejoins the same seat and current board; repeat on the other phone. |
| Disconnect/reconnect | Temporarily disconnect one phone from Wi-Fi, reconnect to the Pi and resume the same seat/board. Old round credentials do not enter a subsequent round. |
| Complete match | Play a full legal match to a finish; both return to Party Home and see the recorded result. Record sanitized result evidence, not client claims or signing material. |
| Host End | Start another round; host ends it mid-play; both return to correct Party Home state. Guest cannot end or impersonate a seated player. |
| Spectator | With an additional browser/device if available, late join observes only permitted state and cannot move as a player. Record if this extra scenario was not run. |
| Subsequent launch | Launch a fresh Checkers round after completion/Host End; no lingering session or reused seat authority. |
| Regression | Afterwards launch and end BLUFF and Gauntlet II; verify Gauntlet's four-player admission with four participants when available. Check EXPO, Party Home/Library, presence and arcade controller UI. Record participant count and any untested path. |

Also perform the real-phone bridge checks in [BROWSER-ORIGINS](../design/BROWSER-ORIGINS.md), including
Safari with default tracking prevention and private browsing. Ordinary-mode success does not prove
those cases. Never weaken browser policy to conceal a failed bridge. Existing Limited Mode is a
regression concern, but this packet supplies no Limited Mode native-Checkers physical evidence.

## Failure, cleanup and issue update

Stop play on a failing gate. Capture the exact step, exit status, time, deployed SHAs and sanitized
error. Inspect relevant `journalctl` output locally for Party Core and `avrana-game@checkers`; do not
attach raw logs, credentials, player telemetry or runtime data. Each physical defect gets a separate
scoped issue with evidence; fixing it is outside AVR-261. Recheck status after cleanup.

End live rounds from Party Home before removal. If reverting the trial, use the existing reverse path:
`sudo python3 -m avrana.ops.provision_game checkers --remove` (consider documented `--keep-state`);
then bootstrap reverse with its recorded backup path, which refuses while any native game remains.
Only reverse phase-1 migration with its own backup and runbook. Restore origin/config/TLS/DNS/nginx
changes using their separately retained backups; use deploy's printed prior SHA pair for code rollback.
Do not delete keys or state by hand, prune unknown worktrees, or assume code rollback reverses system setup.

Post the acceptance matrix, boundary output, run date/devices and actual deployed SHA pair to AVR-261.
Update [SYSTEM](../SYSTEM.md) only from observed deployment evidence. Keep AVR-261 open until its
human criteria pass; CI or browser simulation never closes it. Checkers findings inform AVR-37/38;
package freeze still needs four-human BLUFF evidence and owner approval.
