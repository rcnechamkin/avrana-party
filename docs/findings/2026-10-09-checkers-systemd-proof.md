# Native Checkers: real-systemd provisioning and phase 2 boundary proof

Observed 2026-10-09 (run time 2026-10-10 UTC) on the AVR-238 paired branches. Historical
engineering evidence from a disposable GitHub Actions runner (Ubuntu 24.04, real systemd, root),
not a deployment record, not the Pi, not a phone. Party head
`91da26fdab4367f7f18398f670714d8939df9129` (contains main `ffe2e1c`, with AVR-304); Games
`feat/avr-238-checkers` at `76ec4873bb6a53098b7e6eb9afe95defc67d442a`. Run:
<https://github.com/rcnechamkin/avrana-party/actions/runs/38024330627>, job `checkers`:
58 `CHECK PASS`, 0 `CHECK FAIL`.

This closes the gap the [2026-10-08 checkpoint](2026-10-08-checkers-party-integration.md) left
open ("Checkers provisioning under real systemd and `boundary --phase 2` with Checkers remain
pending"). The script is `experiments/native-game/checkers-proof.sh`; it refuses to run on a host
that already has an Avrana installation. The host is scaffolded by the script (identities, a
hand-written `party-core.json`, a copied release), not produced by `ops/deploy.sh`.

## What was run

The owner's path, in order: ADR 0016 phase 1 identities; Party Core on its earlier unit;
`ops/prepare-native-games` (AVR-304); `provision-game checkers` against the release tree's own
`contracts/appliances/avrana-pi4.json`, unmodified. No fixture stood in for the appliance file or
for the game: the Games checkout was installed root-owned at `/opt/avrana-party-games/current`
and the grant's command (`/usr/bin/python3 -m checkers`) ran from there.

## What it showed

- `provision-game checkers` is refused before `prepare-native-games`; afterwards a dry run changes
  nothing, the real run exits 0, and a second run changes nothing.
- `avrana-game@checkers` is socket-activated, runs as a dynamic non-root user, received
  `AVRANA_PARTY_ORIGIN`, and reads its key from the credential directory systemd made for it.
  Party Core picked the game up by reload, never by restart, and offers it from its contract.
- `boundary --phase 2` reported six rules, all met: `identity.groups`, `ipc.no_ip`,
  `hardening.native`, `ipc.socket.game` (each on `avrana-game@checkers.service`),
  `ipc.socket.party_internal` (`avrana-party-core.service`) and `groups.front`.
- A session through Party Core's public HTTP API and the game's Unix socket: two members seated,
  only the side to move was given moves, a device without a seat got no ticket, forged, altered
  and reused tickets were refused, a late member could watch but not move, and a fresh ticket
  mid-game returned the same seat and board.
- One game was played by legal moves to a natural end (36 plies, ending `captured`, seeded so it
  repeats). Party Core accepted the signed result and showed members the standings; the game logged one
  accepted result. A replayed `ended` was not tried.
- A second session was ended by the Host from Party: both members saw it ended, the game refused
  the old tickets and tokens, reported no result, and the process exited by its idle stop while
  its socket stayed.
- `provision-game checkers --remove` left no key, registry entry, socket, drop-in or state
  directory, and Party Core stopped offering the game.

## What the native path required that was not obvious

- `systemctl show -p LoadCredential` prints nothing on the runner's systemd, so the unit property
  cannot be asserted that way. The proof asserts the installed unit's `LoadCredential=` line and
  the file under `/run/credentials/avrana-game@checkers.service/`.
- That credential file is `root:root 0440` with an ACL for the dynamic user, not group-private.
  A check written against group mode fails; the boundary is the ACL.
- The only outside signal that a native game holds no session after a Host end is its idle exit.
  The game exposes no session count, and the proof did not add one.
- The proof job needs a Games branch carrying the same AVR number, or Games `main` with Checkers
  on it. After Games #54 merges it resolves to `main`; it does not run on Games-only changes.

## What it did not show

The Pi, its kernel or its resource limits; nginx, TLS, the game origin or production cookies
(loopback HTTP only); the Checkers page in any browser; a physical phone; key rotation for
Checkers (covered for the stand-in only); a resigned game. AVR-261 owns physical acceptance.
