# Party ↔ Games contract (`avrana.party-games/v0`)

Status: **implemented on main (AVR-233)**; a declaration of behavior that already exists, not a
new protocol. The semantics live in [ADR 0006](../adr/0006-party-session-protocol.md) (session
protocol), [ADR 0005](../adr/0005-lan-games-provider-launch.md) and
[LAN-GAMES-PROVIDER](LAN-GAMES-PROVIDER.md) (launch integration, catalog snapshot), and
[GAME-INTEGRATION](GAME-INTEGRATION.md) §3. This page explains how compatibility became
machine-testable.

**Scope: the boundary as implemented today.** v0 describes Party and the LAN Games fork as they
run now: one browser origin (hence the fixed `/party/` return path), the `avrana.lan-launch/v1`
integration and the fork's catalog export. It is not the target architecture.
[ADR 0013](../adr/0013-party-and-game-browser-origins.md) (separate game origin) and
[ADR 0014](../adr/0014-native-games-isolated-lan-games-retired.md) (isolated native games; LAN
Games retiring) are accepted and not implemented; when that work changes the boundary, the
declarations change with it through the procedure below. Nothing here makes a LAN Games module
the path for a new native game.

## The two declarations

| Repository | File | Says |
|---|---|---|
| Party | [`contracts/party-games.v0.json`](../../contracts/party-games.v0.json) | what Party **implements** |
| Games | `provider/avrana-contract.json` | what Games **requires** |

Both name the same components:

- **session protocol**: version `avrana.party-session/v0`, prefix `aps0`, the SHA-256 of the
  reference file (`avrana/party/protocol.py`, vendored unchanged as `core/party_protocol.py` in
  Games) and of the shared test vectors;
- **routes**: the party's ticket route, the party's loopback `ended` route, the game's launch
  and end routes under `/games/<slug>/`;
- **launch integration**: `avrana.lan-launch/v1`, the `avrana=1` marker, the fixed `/party/`
  return path, advertised at `/api/games`;
- **environment**: `AVRANA_PARTY_KEYS` and `AVRANA_PARTY_URL`, set by the games service drop-in;
- **catalog**: Party's imported snapshot `contracts/catalogs/lan-games.json` must equal Games'
  `provider/catalog.json` (Party side only; Games lists which games have a party side).

## The checker

[`tools/contract_check.py`](../../tools/contract_check.py) (stdlib, no network, executes nothing
from either repository):

1. proves Party's declaration against Party's constants and file digests;
2. proves Games' declaration against Games' constants, mounted routes, exporter and drop-in;
3. compares the two: same contract version, identical protocol file and vectors, same routes,
   launch and environment names, identical catalog snapshot.

Every failure names the drifted component and the file to change. It runs in Party's
`Cross-repo contract` workflow and Games' `cross-repo` job, each against the other repository's
matching `avr-N` branch ([CROSS-REPO](../CROSS-REPO.md)), alongside the executable boundary test
(`tests/test_party_session_cross_repo.py` in Games, which may not skip in CI), and locally:

```sh
python3 tools/contract_check.py --games ../avrana-party-games
```

## Changing the contract

1. Change the code and tests on both sides on paired `avr-N` branches.
2. Re-vendor `protocol.py` and the vectors into Games when the protocol changed; update both
   declarations' digests (the tests in both repositories print the expected values).
3. Bump `contract` / `requires` to `avrana.party-games/v1` only when a Games built against v0
   would no longer work against the new Party. Additive, backwards-compatible changes keep v0.
4. The deployment manifest and `/party/api/status` report the version Party implements; the
   status document also reports what the running games server advertises.

## Not declared here

Player identity (Party never sends device or member ids to a game), chat transport, the shared
`wc-name` display-name key, service worker scopes. They are platform ownership rules in
[PARTY-PLATFORM](PARTY-PLATFORM.md) and [LAN-GAMES-ASSIMILATION](LAN-GAMES-ASSIMILATION.md),
enforced by tests on each side, not a cross-repository interface version.
