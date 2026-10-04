# ADR 0016 — Field-test service identities and the local trust boundary

Status: **accepted · not implemented · not deployed** · Date: 2026-10-03
The direction (each native game is its own process with its own service identity, secrets and
state; local IPC prefers Unix sockets) was accepted on 2026-10-02 in
[ADR 0014](0014-native-games-isolated-lan-games-retired.md) decisions 3, 4 and 6, which left
"service manager details" open. This ADR is the
[AVR-227](https://linear.app/avranakern/issue/AVR-227/define-field-test-service-identities-and-inter-service-trust-boundary)
mechanism, accepted by the owner on 2026-10-03 (the decisions below). Nothing here is built or
deployed: every Avrana service on the Pi still runs as the operator account `cody`
([SYSTEM](../SYSTEM.md)). Consumers:
[AVR-236](https://linear.app/avranakern/issue/AVR-236/build-generic-native-game-registry-routing-and-provision-game-path)
(registry, routing, `provision-game`),
[AVR-238](https://linear.app/avranakern/issue/AVR-238/prove-checkers-as-the-first-clean-native-game-platform-consumer-after)
(Checkers), [AVR-228](https://linear.app/avranakern/issue/AVR-228/retire-lan-games-as-the-avrana-runtime-preserve-it-only-as)
(LAN Games retirement). Context: [ADR 0003](0003-ids-and-keys.md), [ADR 0006](0006-party-session-protocol.md),
[ADR 0009](0009-arcade-party-provider.md), [ADR 0013](0013-party-and-game-browser-origins.md),
the [2026-10-02 review](../findings/2026-10-02-architecture-review.md) §2.3, §2.16, §2.17 and
[audits](../findings/2026-10-02-architecture-audits.md) §1.3, §1.6.

## Context: what is true today

Verified in source on `main` (2026-10-03) and against facts recorded read-only on the Pi the
same day (`tests/fixtures/boundary/pi-2026-10-03.json`; nothing on the Pi was changed).

- **One uid.** `avrana-party-core`, `avranaparty-games` and `avranaparty-arcade` all run as
  `User=cody`, the owner's login account, from git checkouts in `/home/cody` that `cody` owns.
- **Every key is every service's key.** `/etc/avrana-party/game-keys/` is `0700 cody` with
  `0600 cody` files. Party Core reads each `key_file`; the Games and arcade drop-ins both set
  `AVRANA_PARTY_KEYS` to that whole directory. Any of the three processes can read every game's
  key, Party Core's device store (`/var/lib/avrana-party-core`), the fork's `data/venue.json`
  (Wi-Fi password) and avatar store, and can rewrite the code the other two execute. "Per-game
  0600 key" (ADR 0006 D5) is therefore nominal: the uid is the only boundary and it is shared.
- **Loopback is the only local gate.** Party → game (`http://127.0.0.1:8096/games/<slug>/…`,
  `:8098` for the arcade) and game → Party (`/internal/…` on `127.0.0.1:8191`) are accepted when
  the peer address is loopback and no proxy header is present, then verified by HMAC. Loopback
  means "any process on this host", so with shared keys the caller is identified by nothing.
- The signatures themselves are sound (typed, audience- and session-bound, expiring, nonce-guarded).
  What they lack is a key that only two parties can read.

That was a reasonable prototype. It is not a boundary to hand to a field tester, and it cannot be
what the second native game is built on.

## Owner decisions (2026-10-03)

Recorded on AVR-227 after two proposals for this ADR were reconciled. They settle the questions
this mechanism left to the owner.

1. The reconciled design in this document is the one to carry forward.
2. For the field test, Party Core tells native games apart **by signature alone**. A per-game
   channel enforced by the OS is deferred to the untrusted tier (AVR-69); §4 states what that
   costs.
3. The key-loader change in §3 is approved as a paired Party and Games change ahead of
   everything else ([AVR-253](https://linear.app/avranakern/issue/AVR-253/let-protocolread-key-accept-a-systemd-loadcredential-key-file-without)).
4. Party Core, the LAN Games fork and the arcade **leave the `cody` account before the field
   test**. This does not wait for LAN Games to retire (§9 phase 1).
5. Party Core's public API **stays on loopback TCP** for the field test.

## Decision

### 1. What is promised for the first field-test appliance

The unit of trust is **the systemd service identity**. For an appliance that leaves the owner's
hands:

1. A defect in, or compromise of, one native game process cannot read another game's key or
   state, Party Core's device store, any other service's secrets, the TLS private key or Wi-Fi
   credentials; cannot change any code or unit that runs on the appliance; cannot speak to
   another game's socket; and cannot present itself to Party Core as a different game.
2. No local caller is trusted because of its address. A local peer is admitted by filesystem
   permission on a Unix socket, and authenticated as a specific game by a key only that game and
   Party Core can read.
3. The operator's login account runs no service and owns no secret a service uses.

**Not promised**, and stated so nobody assumes it:

- anything against `root`, whoever holds `sudo`, or physical access (the storage is unencrypted);
- containment of deliberately hostile game code: kernel attack surface, resource exhaustion and
  the stronger sandbox tier are [AVR-69](https://linear.app/avranakern/issue/AVR-69/define-community-game-execution-isolation-and-trust-tiers).
  Field-test games are first-party code that may be *buggy*, not *adversarial*;
- isolation between modules inside the legacy LAN Games process (it is one trust unit);
- protection from a compromised Party Core (it holds every game key by design) or nginx;
- what a game can do with its own authority: mint tickets for its own session, end its own
  session, misreport its own result (Party validates the envelope, [ADR 0015](0015-game-result-envelope.md));
- anything in the browser: that boundary is ADR 0013.

### 2. Service identities

| Service | Unit | Identity | Why this kind |
|---|---|---|---|
| Party Core | `avrana-party-core.service` | static system user `avrana-party` | owns long-lived files outside systemd-managed directories (the key store) and needs a stable group membership |
| Arcade (managed runtime, ADR 0009) | `avranaparty-arcade.service` | static system user `avrana-arcade`, supplementary `input`, `video`, `render` | device access is granted by group; it is the only service with those groups |
| LAN Games fork (legacy, retiring) | `avranaparty-games.service` | static system user `avrana-lan-games`, if the runtime is present at all | see §7; deleted with the runtime |
| Each native game | `avrana-game@<slug>.service` + `avrana-game@<slug>.socket` (one template) | **`DynamicUser=yes`**: systemd allocates a distinct uid per running instance | games come and go; a game needs no file outside its own directories and no group of its own |
| nginx | distribution unit | `root` master, `www-data` workers (unchanged) | front door |
| Certificate renewal, deploy, provisioning | one-shots | `root` | they create identities and write secrets |
| Operator | — | `cody` (login, `sudo`) | runs no service |

**Every native game gets its own service identity**, and gets it without `provision-game` creating
a Unix user: the template instance *is* the identity. Two static groups express the two local
permissions that exist:

- `avrana-front` — "may connect to a game's socket". Members: `www-data`, `avrana-party`.
- `avrana-games` — "may connect to Party Core's internal socket". Supplementary group of every
  `avrana-game@` instance (and of a legacy runtime that is moved onto the socket). It grants
  nothing else: no file or directory other than that socket is owned by it.

Invariants that hold for every row: no service runs as a login account; no service identity can
write code, units, the registry, grants or contracts (all root-owned, read-only to services); a
service executes only root-owned code outside any home directory. Where the code is installed is
[AVR-32](https://linear.app/avranakern/issue/AVR-32/make-fresh-appliance-install-and-rebuild-reproducible)'s
layout decision; the root-owned release tree `ops/install-party-web.sh` already builds for the
shell is the precedent.

### 3. Secrets, state and directories

| Object | Path | Owner : group, mode | Who may read | Who may write |
|---|---|---|---|---|
| Per-game session key (source of truth) | `/etc/avrana-party/game-keys/<slug>.key`, directory `0700` | `avrana-party`, `0600` | Party Core | provisioning (`root`). Party Core's own identity *could* rewrite or replace a key, and must not: see below |
| A game's copy of **its own** key | `$CREDENTIALS_DIRECTORY/<slug>.key` (`LoadCredential=`), exists only while the unit runs | systemd | that unit only | nobody |
| Party device store | `/var/lib/avrana-party-core/` (`StateDirectory`, `0700`) | `avrana-party` | Party Core | Party Core |
| A native game's persistent state | `$STATE_DIRECTORY` = `/var/lib/avrana-games/<slug>` (`StateDirectory=avrana-games/%i`, `0700`) | that instance's uid | that game | that game |
| A native game's scratch | private `/tmp` (`PrivateTmp`), discarded on stop | that instance | that game | that game |
| Game registry, grants, `party-core.json`, contracts, units | AVR-236 chooses the path | `root`, world-readable, no secrets | any service | provisioning / deploy (`root`) |
| Code | AVR-32 chooses the path | `root`, world-readable | any service | deploy (`root`) |
| TLS private key | `/etc/avrana-party/tls/` | `root` | nginx master | renewal (`root`) |
| Legacy `data/` (avatars, chat media, `venue.json`) | bound from `/var/lib/avrana-lan-games` | `avrana-lan-games` | the legacy runtime | the legacy runtime |
| Deployment manifest | `/var/lib/avrana-party/deployment.json` | `root`, world-readable | Party Core (status) | deploy (`root`) |

**The credential model.** Party Core is the authority that issues sessions, so it owns the key
store and reads it directly (which also lets a registry reload pick up a new game without a
restart). Every *other* holder of a key receives exactly its own through `LoadCredential=`:
systemd reads the source as root at unit start and exposes a private, memory-backed copy to that
unit alone. A game never has filesystem access to the key directory. The cost of a Party-owned
store is that the file permissions do not stop Party Core's identity from rewriting or replacing a
key; nothing in Party Core writes there, and it is already the trust root for every key (§1). A
`root`-owned file readable through a group is not an alternative: `read_key` refuses plain group
access, before and after AVR-253. The existing interface is
kept: a unit sets `AVRANA_PARTY_KEYS=%d` and names the credential `<slug>.key`, so
`avrana.party.managed.configure` and the fork's `party_session.load_sides` find "a directory of
`<slug>.key` files" exactly as today.

- Native game: `LoadCredential=%i.key:/etc/avrana-party/game-keys/%i.key`.
- Arcade: `LoadCredential=arcade-gauntlet2.key:…`.
- Legacy LAN Games: one `LoadCredential=` per Party game it still hosts (`bluff`, `expo`).

**One code prerequisite, confirmed by the proof below.** systemd grants the service read access to
a credential file with a POSIX ACL, so the file is owned by root and its mode reads as `0440`;
`protocol.read_key` refuses any key readable by group or other, and refused it in the proof run.
The loader must accept exactly that case and keep refusing a key with real group or other access.
That is a paired change to `protocol.py` and its vendored copy in the Games repository, with both
contract digests updated: [AVR-253](https://linear.app/avranakern/issue/AVR-253/let-protocolread-key-accept-a-systemd-loadcredential-key-file-without),
approved by the owner and required before any unit uses `LoadCredential=`. It changes no wire
format.

Rejected for key delivery: a second on-disk copy per game (two files drift on rotation); a shared
group on the key file (`read_key` rightly refuses it, and a group is not "exactly two readers");
environment variables (visible in unit files and `/proc`).

### 4. Local IPC

| Path | Transport | Created by; owner : group, mode | Who can connect | Authenticated by |
|---|---|---|---|---|
| nginx → native game (pages, WebSocket) | **Unix socket** `/run/avrana-games/<slug>.sock` | the socket unit; `root : avrana-front`, `0660` | nginx, Party Core | nothing local; the browser presents a Party ticket (ADR 0006) |
| Party Core → native game (`launch`, `end`) | the same socket | — | — | HMAC with that game's key; the game refuses these routes when a proxy header is present, and the generic nginx route refuses `/games/<slug>/avrana/` outright |
| native game → Party Core (`ended`, result) | **Unix socket** `/run/avrana-party/internal.sock` | Party Core's socket unit; `avrana-party : avrana-games`, `0660` | game instances | HMAC with the reporting game's key; Party matches it to the current session |
| nginx → Party Core (`/party/api/`) | TCP loopback `127.0.0.1:8191` (unchanged) | — | any local process | the member's cookie and Origin, as for any phone |
| Party Core ↔ arcade control, legacy LAN Games | TCP loopback `:8098`, `:8096` (unchanged) | — | any local process | HMAC with a key that is now readable by two identities only |

Where Unix sockets are **required**: every native game's listener, and the game-facing internal
endpoint of Party Core. A native game has no TCP port, so nothing is allocated per title, and it
runs with `RestrictAddressFamilies=AF_UNIX`: it has no IP socket at all, cannot reach the
remaining loopback listeners and cannot open a port on the Party Wi-Fi.

Where TCP loopback **stays**: `/party/api/` behind nginx (it is the public API; a local caller
gains nothing a phone lacks), the arcade (it needs IP for WebRTC and is not being rebuilt here)
and the legacy fork (no investment in a retiring runtime). Each may move to a socket when its unit
is next changed; none has to for the field test, because the key each depends on is no longer
shared. Until the arcade and the fork leave TCP, Party Core's `/internal/` route also remains on
`:8191`, where it is protected by the signature only.

How the two layers divide the work, which is why both stay:

- **Socket permissions answer "which class of peer may speak here at all"**: only the front door
  and Party reach a game; only games reach Party's internal endpoint. This is enforced by the
  kernel, not by an address check, and it is unaffected by a container or network namespace
  because a path socket lives in the filesystem.
- **The signature answers "which game is this"**. Dynamic uids are not stable, so Party does not
  map a peer uid to a game; the per-game key, now private to that game, does it. It also covers
  what an OS identity cannot: tickets travel through a browser, and nginx and Party share a game's
  socket. Party checks the message's issuer (`iss`) against the key that verified it.

What signature-only identification costs, accepted for the field test: every native game can
connect to Party's internal socket, so **a game whose key leaks can be impersonated to Party by
any other local game**. With first-party games that hold only their own key this needs a key
disclosure first. The upgrade path, when untrusted games arrive (AVR-69), is the transport
contract a sandbox must provide: *per game, one channel only that game can use to reach Party,
and one only Party can use to reach it*. Nothing in the wire protocol changes when that is added.
Because nginx and Party share a game's socket, the game tells control traffic from public traffic
itself; one generic nginx rule that refuses `/games/<slug>/avrana/` keeps control paths from ever
being proxied.

Rejected: `SO_PEERCRED` as the authentication of a game (needs stable uids and peer-credential
plumbing in three web stacks for no gain over a private key); a second, Party-only control socket
per game (kernel-enforced separation of `launch`/`end` from web traffic, but doubles every game's
listeners; revisit under AVR-69); games binding their own sockets (the game would need membership
of `avrana-front`, which would let it reach every other game).

**Party Core gets no authority over systemd.** No polkit rule, no `sudo`. A game's process starts
by socket activation on the first connection (Party's `launch`, or a page request) and stops
itself when idle; enabling, disabling and removing units is provisioning's job, as root. This is
also what makes "runs only while active" (ADR 0014 Consequences) cost nothing to operate.

### 5. The native-game unit (field-test baseline)

The template that AVR-236 writes carries at least:

```ini
# avrana-game@.socket
[Socket]
ListenStream=/run/avrana-games/%i.sock
SocketUser=root
SocketGroup=avrana-front
SocketMode=0660

# avrana-game@.service
[Service]
DynamicUser=yes
SupplementaryGroups=avrana-games
StateDirectory=avrana-games/%i
StateDirectoryMode=0700
LoadCredential=%i.key:/etc/avrana-party/game-keys/%i.key
Environment=AVRANA_PARTY_KEYS=%d
RestrictAddressFamilies=AF_UNIX
ProtectHome=yes
PrivateDevices=yes
UMask=0077
Restart=on-failure
```

`DynamicUser=yes` already implies `ProtectSystem=strict`, `PrivateTmp`, `NoNewPrivileges`,
`RemoveIPC` and `RestrictSUIDSGID`. The kernel-protection flags Party Core's unit already uses
(`ProtectKernelTunables`, `ProtectKernelModules`, `ProtectControlGroups`) belong here too.
`ExecStart`, the working directory, the environment name for Party's socket path and resource
ceilings (`MemoryMax`, `TasksMax`, `CPUQuota`) are AVR-236's, the last from measurement of a real
game (AVR-238), not guessed here.

What a game process is handed, as a **field-test runtime convention, not an SDK**: its listening
socket as file descriptor 3 (`LISTEN_FDS`), its key in `$CREDENTIALS_DIRECTORY`, its state in
`$STATE_DIRECTORY`, and the path of Party's internal socket. uvicorn (`--fd`), aiohttp (`sock=`)
and the standard library all accept an inherited socket. This may change before `.avrgame`.

### 6. Options weighed against this appliance

| Option | Verdict | Reason here |
|---|---|---|
| Static dedicated user per platform service | **adopt** (Party Core, arcade, legacy) | three fixed services; they own files or device groups that outlive a run |
| Static dedicated user per game | reject | `provision-game` would create and delete Unix users; removal leaves orphaned uids and files; a game needs no stable uid once keys are credentials and sockets are systemd's |
| `DynamicUser=` per game | **adopt** | identity with no provisioning state; hardening implied; nothing to reconcile on removal |
| `DynamicUser=` for Party Core / arcade | reject | Party owns the key store outside a state directory; the arcade needs fixed device groups and a udev rule |
| `LoadCredential=` | **adopt** for every non-Party key holder | exactly-one-reader delivery of a secret that has two legitimate holders |
| `CredentialsDirectory` / encrypted credentials (`SetCredentialEncrypted`, TPM) | defer | the Pi 4 has no TPM; the threat it answers (offline disk read) is physical access, not promised |
| Unix sockets with ownership and mode | **adopt** where listed in §4 | removes ports, makes the peer class explicit, survives namespaces |
| TCP loopback | **keep** where listed in §4 | impractical or pointless to change for the field test |
| `PrivateNetwork=yes` for games | defer to AVR-69 | a network namespace is not needed for the promise in §1; `RestrictAddressFamilies=AF_UNIX` already removes IP. The design is compatible with it (proof check 4) |
| System-call filters, `MemoryDenyWriteExecute`, per-game cgroup ceilings beyond a basic cap | defer to AVR-69 / AVR-238 | hostile-code hardening; values need measurement |
| Containers, per-game images | reject for now | no requirement they answer that the above does not |

### 7. LAN Games while it retires

The fork is one process hosting BLUFF, EXPO and the donor titles; nothing can isolate those from
each other, and nothing here tries. It is **one trust unit with one identity**
(`avrana-lan-games`) that receives only the keys of the Party games it hosts and can read nothing
of Party Core's. Its writable `data/` is bound from its own state directory
(`StateDirectory=avrana-lan-games`, `BindPaths=`), so its code can be read-only without a fork
change. It keeps TCP loopback (Games `main` already binds `127.0.0.1` by default) and gets no
socket, no template and no further hardening. When AVR-228 removes it from normal operation, its
user, state directory, drop-ins and its `LoadCredential=` lines go with it; a game that leaves
the monolith for a native process gets a **new** key from `provision-game` rather than inheriting
one the monolith held.

Whether a field-test appliance ships with the fork at all is AVR-228's sequencing. This ADR holds
either way.

### 8. Lifecycle: restart, rotation, removal, rebuild

| Event | Preserved | Replaced or removed |
|---|---|---|
| Game process restarts or crashes (`Restart=on-failure`) | key, state directory, socket (held by systemd, so nginx sees no refusal) | the uid may change; systemd re-owns the state directory. The in-memory session is the game's to recover or abandon (AVR-33) |
| Party Core restarts | device store, keys | the party (memory-only, ADR 0006); a running game's session is orphaned and ends by the existing rules |
| `provision-game <slug>` run again (reconcile) | key, state | registry entry, grant and units are rewritten to match the manifest; idempotent |
| Key rotation (same command, explicit flag) | state | the key file; then restart the game unit and have Party reload. Refused while that game has an active session |
| `provision-game --remove <slug>` | nothing by default | socket and service units stopped and disabled, registry entry, grant, key file, runtime socket, and the state directory. An explicit keep-state option may retain the state directory; it is inert without a key and is re-owned if the slug is provisioned again |
| Rollback to an earlier Party or Games SHA (`ops/deploy.sh`) | identities, groups, keys, state: they belong to the installation, not to a release | code only. A SHA that predates socket support cannot serve a native game; the registry entry stays and the game is unavailable until rolled forward |
| Rebuild from scratch (AVR-32) | the device store, if the owner restores it | keys are **regenerated**, never backed up or imaged: they protect only live sessions, and the party is memory-only |

Keys are never in Git, an image, a backup, a log or a unit file.

### 9. Migration from the shared-user prototype

Nothing below is performed by AVR-227. Each phase is an owner-approved deployment with its own
runbook and reverse; each leaves a working appliance. The phases are the ones
`contracts/service-boundary.v1.json` names and `python3 -m avrana.ops.boundary --phase N` checks.

**Phase 1, before the field test (owner decision 4): the three existing services leave the
operator account.** It does not wait for LAN Games to retire.

- Prerequisites: the key-loader change (AVR-253) merged in both repositories and deployed; code
  each service can read without belonging to `cody` (the checkouts under `/home/cody` are the
  obstacle; layout is AVR-32).
- Create `avrana-party`, `avrana-arcade`, `avrana-lan-games` and the groups `avrana-front`,
  `avrana-games`. Re-own the key store and the device store to `avrana-party`. Set each unit's
  `User=`. The Games and arcade drop-ins switch from the shared key directory to `LoadCredential=`
  + `AVRANA_PARTY_KEYS=%d`. Bind the fork's `data/` from its own state directory. Deploy the
  loopback listener already on Games `main`.
- After it: a game key has exactly two readers, no service can write code or reach `sudo`, and
  §1 item 3 holds. On 2026-10-03 the Pi met 6 of the 25 phase-1 rules.

**Phase 2: native games arrive through AVR-236**: template units, sockets, Party's internal
socket, the generic nginx route, `provision-game`. Checkers (AVR-238) is the first consumer.

**Phase 3: the legacy identity is deleted** with the runtime (AVR-228).

Reverse of phase 1: restore the previous unit files and drop-ins and re-own the two directories to
`cody`. No data format changes, so the reverse loses nothing.

## What AVR-236 consumes

| Question | Answer |
|---|---|
| Which identity does `provision-game` create or assign? | none: it enables `avrana-game@<slug>.socket`; `DynamicUser=` is the identity. It never creates a Unix user or group per game |
| Where is the game's socket, and who owns it? | `/run/avrana-games/<slug>.sock`, created by the socket unit, `root:avrana-front 0660` |
| Where is the secret, and who may read it? | `/etc/avrana-party/game-keys/<slug>.key`, `avrana-party 0600` in a `0700` directory; Party Core reads it, the game receives a private copy by `LoadCredential=`, nobody else |
| Where is persistent and runtime state? | `$STATE_DIRECTORY` (`/var/lib/avrana-games/<slug>`, `0700`, the instance's uid); private `/tmp`; logs to the journal |
| What must cleanup and reprovision remove or keep? | §8 |
| What must Party Core gain? | an HTTP client for a Unix socket; an `/internal/` listener on `/run/avrana-party/internal.sock` (the loopback one stays for the arcade and the fork); a registry reload that reads a new key |
| What must the game side gain? | serve an inherited socket; treat "arrived on the Unix socket without proxy headers" as the local check that `client is loopback` is today; post `ended` to a Unix socket |
| What must nginx gain? | one generic route by slug to `/run/avrana-games/<slug>.sock` that sets the proxy headers, and one generic rule that refuses `/games/<slug>/avrana/`; `www-data` in `avrana-front` |
| What must it prove? | Tier 2: real nginx routing by slug to a Unix socket; a Unix-socket variant of the cross-repo session test; `provision-game` reconcile, rotate and remove leave the state in §8 |
| When is it done with this boundary? | when the phase-2 rules of `python3 -m avrana.ops.boundary` pass on a host with a provisioned game |

The wire contract is untouched: `avrana.party-session/v0`, its messages, tickets, replay rules and
the result envelope are exactly as ADRs 0006 and 0015 state. Only the address a message is sent to
changes, and only for native games.

## Amendments to earlier documents

- **ADR 0014** "Deliberately open: service manager details": decided here.
- **ADR 0006 D5** "one random 32-byte key per game, provisioned by the appliance as a 0600 file":
  stands; this ADR says whose file it is and how the game obtains its copy. **"`ended` is only
  accepted from the loopback address, with no proxy headers"** describes the deployed v0
  transport and remains true for the arcade and the fork; for native games the equivalent is
  "only on Party Core's internal socket". **Threat assumptions, "Trusted: the appliance, its local
  services"**: narrowed by §1 — local services are distinct identities, each trusted only with
  its own key.
- **ADR 0015** "accepted only from loopback" / "a loopback connection to a route nginx never
  forwards": the same deployed transport; a native game's result arrives on the internal socket.
  **LIMITED-MODE**'s proposed second loopback listener for nginx → Party Core is unaffected
  (`/party/api/` stays on TCP loopback).
- **ADR 0009** and `deploy/arcade/avrana-party-session.conf` ("the arcade keeps its unit, user and
  groups"): accurate for what is deployed; phase 1 changes the user.
- **GAME-INSTALLATION** "Isolation that is cheap on a Pi": its `DynamicUser` + Unix-socket sketch
  is adopted as the baseline for all native games; `PrivateNetwork`, system-call filters and
  resource ceilings remain its stronger tier.

## Evidence and what is not yet proven

- Source reading of both repositories at `main` on 2026-10-03 (Party `5b63b07`, Games `42ee69b`).
- [`experiments/service-trust/proof.sh`](../../experiments/service-trust/proof.sh), run by the
  `Service trust proof` workflow on 2026-10-04 (GitHub run 37167416763; Ubuntu 24.04, systemd 255,
  x86_64), 9 of 9 checks passed: a dynamic identity cannot read the key store but reads its own
  key through `LoadCredential=`; one game's state directory is closed to another; socket group
  ownership admits the intended peers and refuses the others; a game with
  `RestrictAddressFamilies=AF_UNIX` and a private network namespace still reaches Party's internal
  socket and has no IP socket; and the boundary checker's collector reads a dynamic-user unit
  named like a native game as this ADR describes it. Observed: the credential file is `0440 root`
  and `read_key` refuses it (§3); `systemctl show` cannot print `LoadCredential`, so the collector
  reads the unit text.
- [`contracts/service-boundary.v1.json`](../../contracts/service-boundary.v1.json) states the
  identities, key ownership and sockets above as data; `avrana/ops/boundary.py` judges a host
  against it, read-only, and `tests/unit/test_ops_boundary.py` shows a host built to this ADR
  passes and each single departure is caught. The Pi's facts, collected read-only on 2026-10-03,
  meet 6 of 25 phase-1 rules: every service is `cody`, the keys are `cody`'s, and the games
  server listens on `0.0.0.0:8096` (the loopback default on Games `main` is not deployed).
- That is Tier 2 evidence about systemd on Ubuntu. **Not proven, and requiring the Pi** (owner,
  Tier 3): the same checks on Debian 13 / arm64; the permissions of `/home/cody` and where service
  code will live; nginx workers picking up `avrana-front`; the arcade under a new user (uinput,
  Xvfb, encoder devices, RetroArch's writable home); socket activation of a real game.

## Deliberately deferred

Community and untrusted game execution, its sandbox tier and resource policy (AVR-69); encrypted
credentials and storage encryption; moving `/party/api/`, the arcade or the fork to Unix sockets;
a Party-only control socket and a per-game report channel (the sandbox transport contract in §4); peer-credential checks; a web admin's identity; the registry
format and path, CLI syntax and unit `ExecStart` (AVR-236); the install layout (AVR-32); the SDK
and `.avrgame`.
