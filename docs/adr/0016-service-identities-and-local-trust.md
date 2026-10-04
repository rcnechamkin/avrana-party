# ADR 0016 — Service identities and the local trust boundary

Status: **accepted (direction, ADR 0014) · proposed (this boundary)** · not implemented · Date: 2026-10-03
Makes [ADR 0014](0014-native-games-isolated-lan-games-retired.md) decisions 3, 4 and 6 concrete
([AVR-227](https://linear.app/avranakern/issue/AVR-227/define-field-test-service-identities-and-inter-service-trust-boundary)).
Building it is [AVR-236](https://linear.app/avranakern/issue/AVR-236/build-generic-native-game-registry-routing-and-provision-game-path);
isolation for untrusted community games is [AVR-69](https://linear.app/avranakern/issue/AVR-69/define-community-game-execution-isolation-and-trust-tiers)
and is not decided here. Context: [ADR 0003](0003-ids-and-keys.md), [ADR 0006](0006-party-session-protocol.md),
[ADR 0009](0009-arcade-party-provider.md), [SYSTEM](../SYSTEM.md).
Machine-checkable form: `contracts/service-boundary.v1.json`, checked by `python3 -m avrana.ops.boundary`.

## Context: what is true today

Observed read-only on the Pi on 2026-10-03 (systemd 257, Debian 13):

| Fact | Today |
|---|---|
| Party Core, LAN Games (BLUFF and EXPO inside it) and the arcade | all run as `cody` (uid 1000) |
| `cody` | the owner's SSH login, a member of `sudo` and `adm`, owner of both source checkouts |
| Session keys `/etc/avrana-party/game-keys/*.key` | `0600 cody`, directory `0700 cody` |
| Party Core state `/var/lib/avrana-party-core` | `0700 cody` |
| LAN Games state `…/avrana-party-games/data` | `0775 cody` |
| Party Core | `127.0.0.1:8191`: the public API and the internal `ended` route on one listener |
| LAN Games | `0.0.0.0:8096` (the loopback default from Games PR #18 is not deployed) |
| Arcade | `127.0.0.1:8097` (stream), `127.0.0.1:8098` (control) |
| Unit hardening | Party Core has `ProtectSystem=strict` and friends; the other two have none |

So today:

- **A `0600` key is not a boundary.** Every service is the file's owner. Any of them can read
  every game's key, and so mint tickets and `ended` reports for any game.
- **Loopback is not an identity.** `127.0.0.1` says "a process on this machine", not which one.
  Party's internal route trusts loopback plus the absence of proxy headers; any local process
  satisfies both.
- **No service is contained.** Each runs as the account that owns the code all of them execute
  and that can become root. A compromise of any one is a compromise of the appliance.

This was reasonable for a prototype in the owner's hands. It is recorded here so that no document
is read as claiming more. The signatures in ADR 0006 still do their job against browsers and the
network; they do not separate local services from each other.

## Decision

### 1. One identity per service; the operator runs nothing

| Identity | Runs | Notes |
|---|---|---|
| `avrana-party` | Party Core | the only reader of every game key |
| `avrana-game-<slug>` | one native game service each | one user and one group of the same name per game |
| `avrana-lan-games` | the legacy LAN Games process, while it exists | BLUFF and EXPO share it; see §7 |
| `avrana-arcade` | the arcade stream and its emulator | needs `input`, `video`, `render`, `audio`; its own trust and data (ROMs, saves) |
| `www-data` | nginx | the front door; unchanged |
| the operator (`cody`) | nothing | SSH and `sudo` only; owns no file a service can write |

All service identities are static system users with no login shell, no home, no password and no
membership of `sudo` or `adm`. They are declared in `sysusers.d`, one file per identity, so they
are created the same way on first install, reinstall and reboot.

`DynamicUser=` was considered and not chosen: its uid can change between starts, which makes
socket group ownership and peer checks harder for no gain on a single-purpose appliance.

### 2. Code is read-only to every service

A service cannot write the code it or any other service executes. Code directories are owned by
root (or the operator) and not writable by any service identity; units use
`ProtectSystem=strict` and write only to their own state and runtime directories.

### 3. Keys: on disk for root only, handed to exactly two services

- `/etc/avrana-party/game-keys/<slug>.key` is `root:root 0600` in a `root:root 0700` directory.
  No service identity can read the directory.
- systemd delivers keys as credentials: Party Core's unit loads the whole directory; a game's
  unit loads only its own file (`LoadCredential=party-session.key:…/<slug>.key`). Each service
  sees its credentials in a private, read-only, memory-backed directory.
- So a game's key is readable by Party Core and that game, and by nothing else that is not root.
- Rotation is: replace the file, restart Party Core and that game. Keys are appliance data: a
  code rollback does not touch them.

A group-readable key file (`root:avrana-game-<slug> 0640`, with `avrana-party` in every game
group) would also work with plain permissions. Credentials are preferred because no long-lived
service identity then owns or can list key material.

### 4. Local IPC is by Unix socket, and the socket is the identity

Path sockets only (never the abstract namespace), under `/run/avrana/`, in directories created by
systemd so a service cannot widen its own exposure:

| Socket | Owner : group, mode | Who can connect | Carries |
|---|---|---|---|
| `/run/avrana/party/api.sock` | `avrana-party : www-data`, 0660 | nginx | the public `/party/api/` |
| `/run/avrana/party/game/<slug>.sock` | `avrana-party : avrana-game-<slug>`, 0660 | that game | game → party (`ended`) |
| `/run/avrana/game/<slug>/control.sock` | `avrana-game-<slug> : avrana-party`, 0660 | Party Core | party → game (`launch`, `end`) |
| `/run/avrana/game/<slug>/public.sock` | `avrana-game-<slug> : www-data`, 0660 | nginx | the game's pages and WebSocket |

- **Party knows which game is calling by which socket accepted the connection.** A report that
  arrives on `game/bluff.sock` is accepted only for game `bluff`; its signed `iss` must agree.
  Where the kernel offers it (`SO_PEERCRED`), Party also checks that the peer uid is that game's
  identity and refuses otherwise.
- **A game knows a control message is from Party** because only `avrana-party` can open
  `control.sock`. Control routes are not served on `public.sock` at all, so "no proxy headers"
  stops being a security test.
- **Party's internal route leaves TCP.** There is no internal route on `127.0.0.1`.
- Native game units get `RestrictAddressFamilies=AF_UNIX`: a native game has no IP networking at
  all, in or out. Whatever needs the network is a platform service, not a game.

The messages are unchanged: the same HTTP paths, bodies and signed tokens as ADR 0006, over a
different transport.

### 5. State belongs to one service

| Path | Owner, mode | Purpose |
|---|---|---|
| `/var/lib/avrana-party-core/` | `avrana-party`, 0700 | device store |
| `/var/lib/avrana-game/<slug>/` | `avrana-game-<slug>`, 0700 | that game's durable state, if any |
| `/run/avrana/party/`, `/run/avrana/game/<slug>/` | as §4 | sockets; recreated at every boot |
| LAN Games `data/` | `avrana-lan-games`, 0700 | avatars, chat media (legacy) |
| arcade runtime, saves | `avrana-arcade`, 0700 | emulator state; ROM and core directories read-only |

Each is a systemd `StateDirectory` / `RuntimeDirectory`, so ownership and mode are reasserted at
every start.

### 6. Signatures stay

OS isolation answers "which local service is this". It answers nothing about browsers, and it is
one misconfiguration away from failing silently. Everything in ADR 0006 and ADR 0015 remains
required:

- **Tickets** cross the browser. No OS control applies to them. Signature, audience, session
  binding, expiry and single use all stay.
- **`launch`, `end`, `ended`** stay signed, session-bound, time-bound and replay-guarded. The
  socket says who may speak; the signature says what was said, for which session, and that the
  speaker holds that game's key. Either alone is insufficient: a wrongly routed socket or a
  leaked key is then one failure, not a breach.
- **The result envelope** keeps its own checks.

### 7. Migration from the shared-user prototype

| Phase | What changes | What it buys | Needs |
|---|---|---|---|
| 0 | nothing; this ADR and SYSTEM say what is true | no false assurance | done |
| 1 | Party Core, LAN Games and the arcade move to `avrana-party`, `avrana-lan-games`, `avrana-arcade`; keys become root-owned credentials; code becomes read-only to services; state directories are re-owned; LAN Games binds loopback | a compromised service is no longer the operator or root, cannot rewrite code, and cannot read another service's state. Party's key set is no longer readable by the arcade, nor the arcade's key by LAN Games | unit and ownership changes on the Pi by the owner; no application change |
| 2 | native games (Checkers first) are provisioned on the §3–§5 model; Party Core gains Unix-socket listeners and Unix-socket game endpoints; nginx routes `/games/<slug>/` to `public.sock` generically | local IPC identity; per-game key and state isolation that the OS enforces | AVR-236 |
| 3 | LAN Games is retired and the arcade's control port moves to a socket; Party Core closes `127.0.0.1:8191` | no trust rests on loopback anywhere | AVR-228, AVR-222 |

Honest limits until phase 3: BLUFF and EXPO share the LAN Games process, so their two keys are
one boundary, not two (ADR 0003 already says this). Legacy services keep loopback TCP, so between
phases 1 and 3 their control and report routes are protected by the message signature only.

### 8. Reboot, reinstall, rollback

- **Reboot:** `/run/avrana` is empty; systemd recreates runtime directories and sockets with the
  declared ownership before the services start. Nothing depends on a previous run.
- **Reinstall:** identities come from `sysusers.d`, directories from unit directives, keys from
  provisioning. Provisioning is idempotent: it creates what is missing and never overwrites a
  key unless asked to rotate.
- **Rollback of code:** identities, keys, sockets and state are appliance data, not release
  content. A release must not change ownership or regenerate keys.
- **Removing a game:** provisioning removes its unit instance, registry entry, key, runtime
  directory and (on request) state, then its user. A stale key with no registered game is an
  error the checker reports.

### 9. What a different isolation mechanism must preserve

If native games later run in containers, user namespaces or another sandbox, three things in this
ADR stop holding and one must be re-established:

| Assumption here | Why it breaks | What must still be true |
|---|---|---|
| peer uid identifies the game | uids are remapped inside a user namespace | Party identifies the game by the channel it arrived on |
| a filesystem path is shared | mount namespaces differ | each game is given exactly its own two channels (for example by bind-mounting its sockets) |
| loopback reaches Party | `127.0.0.1` inside a network namespace is the container's own | no trust was placed on loopback |
| credentials directory | container secret mounts differ | a game receives only its own key, read-only |

The transport contract a replacement must meet: **for each game, one channel only that game can
use to reach Party, and one channel only Party can use to reach that game.** The Party↔game
protocol does not change, because it never depended on the transport for meaning.

## The twelve questions

1. **Users and groups.** `avrana-party`, one `avrana-game-<slug>` per native game,
   `avrana-lan-games`, `avrana-arcade`, plus the existing `www-data`. Each has a group of the same
   name. No shared "games" group.
2. **Who runs as what.** §1.
3. **Who reads a game's key.** Root, Party Core and that game. §3.
4. **How Party talks to a game.** HTTP over `/run/avrana/game/<slug>/control.sock`. §4.
5. **Socket ownership.** §4 table.
6. **Can a compromised game read another game's secret or state?** No: keys are not on disk for
   it, other credentials directories and state directories belong to other uids, and it cannot
   open another game's sockets. It can do what any guest's phone can: talk to nginx.
7. **Can a game call Party's internal endpoint because it is on the Pi?** No. The endpoint is not
   on TCP; a game can open only its own report socket, and a report there is accepted only for
   that game and only with that game's signature.
8. **Filesystem access.** Read: its own code, its credentials. Write: its state and runtime
   directories. Nothing else. §2 and §5.
9. **Provisioning.** §"Inputs for AVR-236".
10. **Reboot, reinstall, rollback.** §8.
11. **Signatures still required.** All of them. §6.
12. **What containers would break.** §9.

## Inputs for AVR-236

`provision-game <slug>` creates or reconciles, in this order, and is safe to re-run:

1. `sysusers.d/avrana-game-<slug>.conf`: the user and group.
2. the key: `root:root 0600`, never overwritten except by an explicit rotate.
3. the unit instance `avrana-game@<slug>.service` and its socket unit: `User=`, both sockets with
   the §4 ownership, `LoadCredential=` for its own key, `StateDirectory=avrana-game/<slug>`,
   `RestrictAddressFamilies=AF_UNIX`, `NoNewPrivileges=yes`, `ProtectSystem=strict`,
   `ProtectHome=yes`, `PrivateTmp=yes`, `PrivateDevices=yes`.
4. Party's report socket for that game, and the registry entry that names the game's sockets
   (replacing `url` and `key_file` in `party-core.json`).
5. nothing in nginx: one generic location maps `/games/<slug>/` to that game's `public.sock`.

Party Core needs: a Unix-socket listener for the public API; one report listener per registered
game with the channel-to-game binding and the peer check; a game link that speaks HTTP over a
Unix socket; keys read from its credentials directory.

AVR-236 should verify early that nginx can proxy to a Unix socket whose path contains the request's
slug, and that the game framework can serve two listening sockets; if either cannot, the fallback
is one socket per game with Party and nginx in one group and the control routes gated by peer uid,
which keeps every property above except the separation of control from public traffic.

`python3 -m avrana.ops.boundary` reports each rule of this ADR as met or not on a host. It is
read-only. Its verdict on the Pi today is recorded in `tests/fixtures/boundary/`. AVR-236 is done
with this boundary when the native-game rules pass for a provisioned game.

## Not decided here

- Untrusted or community game isolation (system-call filters, resource limits, network policy
  beyond `AF_UNIX`, package signing): AVR-69.
- The provisioning command's syntax, the registry's file format, the exact unit text: AVR-236.
- The browser-origin split (ADR 0013) and Limited Mode listeners (ADR 0012), which add listeners
  but do not change who may connect to them.
- Whether phase 1 is carried out before LAN Games is retired, or skipped in favour of going
  straight to phases 2 and 3. That is an owner decision; the recommendation is to do phase 1
  before the appliance leaves the owner's hands, because it removes the path from any service to
  root.
