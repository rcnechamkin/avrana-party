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
- **result envelope** ([ADR 0015](../adr/0015-game-result-envelope.md)): schema
  `avrana.game-result/v1`, carried as `ended.result`; the SHA-256 of the reference file
  (`avrana/party/result.py`, vendored unchanged as `core/party_result.py` in Games) and of its
  vectors. Games also lists which games report a result (`result.reported_by`), and the checker
  requires each of them to be a party-side game that defines `game_result()`;
- **bridge** ([ADR 0013](../adr/0013-party-and-game-browser-origins.md),
  [BROWSER-ORIGINS](BROWSER-ORIGINS.md)): protocol `avrana.party-bridge/v1`; the SHA-256 of the
  shim a game page loads from its own origin (`web/party/bridge/shim.js`, vendored unchanged as
  `web/avrana-party-bridge.js` in Games) and of its vectors. Both repositories declare it; a
  games declaration without it is refused;
- **routes**: the party's ticket route, the party's loopback `ended` route, the game's launch
  and end routes under `/games/<slug>/`;
- **reply limit** (Party-side behaviour declared here, **not** in `contracts/party-games.v0.json`):
  Party reads at most 64 KiB of a game's reply to `launch` or `end`
  (`avrana.party.sessions.MAX_REPLY_BYTES`) and gives each call one deadline, measured on the
  monotonic clock from before the connection is made: the link timeout (the grant's `timeout`, else
  5 s; an `end` waits at most `END_LINK_TIMEOUT`, 12 s). Every wait on the socket, the headers'
  included, is cut to what is left of it, so a game cannot hold a Party Core request thread longer
  by dripping bytes. An over-limit, late, redirected or non-object reply is a failed launch or end.
  See [Reply limit: what it asks of a game](#reply-limit-what-it-asks-of-a-game) below.
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
3. compares the two: same contract version, identical protocol file and vectors, same result
   schema with an identical reference file and vectors, an identical bridge shim and vectors,
   same routes, launch and environment names, identical catalog snapshot.

Every failure names the drifted component and the file to change. It runs in Party's
`Cross-repo contract` workflow and Games' `cross-repo` job, each against the other repository's
matching `avr-N` branch ([CROSS-REPO](../CROSS-REPO.md)), alongside the executable boundary test
(`tests/test_party_session_cross_repo.py` in Games, which may not skip in CI), and locally:

```sh
python3 tools/contract_check.py --games ../avrana-party-games
```

## Changing the contract

1. Change the code and tests on both sides on paired `avr-N` branches.
2. Re-vendor `protocol.py`, `result.py`, the bridge shim and their vectors into Games when any changed;
   update both declarations' digests (the tests in both repositories print the expected values).
3. Bump `contract` / `requires` to `avrana.party-games/v1` only when a Games built against v0
   would no longer work against the new Party. Additive, backwards-compatible changes keep v0.
4. The deployment manifest and `/party/api/status` report the version Party implements; the
   status document also reports what the running games server advertises.

## Reply limit: what it asks of a game

**What a Games or SDK author must now guarantee (AVR-336, AVR-33).** The answer to `launch` and to
`end` is one JSON object of at most 64 KiB, complete within the link timeout (the game's grant
`timeout`, default 5 s; for `end`, 12 s). A game that starts something heavy on `launch` (the
arcade) has a longer grant timeout, not a longer allowance for size. Do not put diagnostics,
tracebacks or captured process output in the answer: `{"ok": true}` or `{"ok": false, "message":
"one readable line"}`. Party Core treats anything else, and any `3xx`, as a failed call. How a refusal of an `end`
is read is an observed convention, below.

**Is it a contract requirement?** It is declared Party-side behaviour, not a machine-checked
requirement, and it stays out of `contracts/party-games.v0.json` for now.

- *Additive?* Yes, as far as the checkers go. `tools/contract_check.py` reads named keys of each
  declaration and compares named keys across them; an extra top-level `limits` block in Party's
  JSON was run against Games `origin/main` (2ee23e6) and the deployed a448972 and both stayed
  `compatible`. `avrana/contracts/party_games.py` and the status document read named keys too.
- *Why not add it anyway?* Nothing in Games would check it: Games' declaration has no field for a
  limit, so the number would be declared by Party and obeyed or not by each game, with no test on
  the other side. A limit that is declared on both sides, with a Games-side test, is a paired
  change (a field in Games' `provider/avrana-contract.json` and a check in `contract_check.py`).
  That belongs with the optional `state` probe proposal
  ([proposals/2026-10-12-session-probe.md](proposals/2026-10-12-session-probe.md)), which needs a
  paired Games change for the same reason.
- *Old Games, new Party:* unchanged; the limit is behaviour Party already applies to every reply.
  *New Games, old Party:* a game that keeps inside the limit works with a Party that has none.

**Measured headroom** (real calls, T1/T2, Games `origin/main` 2ee23e6 with this Party branch; the
Windows host has no Unix sockets, so these are the same handlers without the socket):

| Game | launch ok | launch refused | end ok | end, session not held |
|---|---|---|---|---|
| BLUFF (Games server) | 11 B | 43 B | 11 B | 42 B |
| Checkers | 12 B | 55 B (one player) | 12 B | 57 B |
| Hello Party | 12 B | 58 B (bad message) | 12 B | 57 B |
| Managed provider (arcade, PS1) | 12 B | 58 B (forged message) | 12 B | 12 B (idle: answered ok) |

Every reply is under 60 bytes, a thousandth of the limit. The one reply that could exceed it was
the managed runtime's start failure, which carried the runtime's exception text: a 200 KB text
produced a 200 054 byte reply; capped at 200 characters (`managed.MAX_WHY`) the same failure is a 254 byte reply.

## Session recovery switches and an observed convention (AVR-33)

Three keys under `session_recovery` in `party-core.json` (the example file spells all of them out).
Each is a boolean; anything else, or another key, stops the service at startup.

| Key | Default | What it does |
|---|---|---|
| `end_orphan_on_start` | **false** | Party Core keeps a small durable record (`active-session.json` beside `devices.json`, or the path in `session_record`; `""`/false there means no record at all) of the sessions it started and has not seen the game reset. At startup it sends each game the signed `end` for them, five tries two seconds apart, then drops the entry. It stops a game (and the arcade/PS1 runtime) that a restarted Party Core would otherwise leave running. With it off nothing is written or sent. |
| `close_lost_game` | **false** | When a phone asks for a ticket to the ACTIVE session, Party checks that a connection to the game is accepted (at most one check per 2 s, waiting as long as a launch would: the grant's `timeout`, else 5 s). Three failed checks inside a sliding 10 s window with no success between close the session: outcome `abandoned`, `nav` home, tickets and seats released. A success clears the count; a miss older than the window no longer counts. With it off no check is made, nothing closes, and the key below does not exist. |
| `end_not_held_is_ended` | **true** | An `end` the game refuses with the reason token below counts as ended, so the host's End and switch work after the game restarted. false: only `{"ok": true}` confirms, as before. |

Why the first two are off: they change what the appliance does to a running game, and the owner
has not decided. With both off the branch behaves as `fix/avr-33-bounded-link` does.

**Observed convention (not a declared field of v0).** `end_not_held_is_ended` reads exactly these
two refusals, matched on the structured token and never on free text:

- `{"ok": false, "message": "Refused.", "reason": "session"}` with status 403 or 409: `avrana/party/managed.py` lines 88, 111 and 114 (the arcade and PS1 runtime), `avrana/games/standin/game.py` line 155, Checkers `checkers/server.py` line 171 (Games `origin/main` 2ee23e6; the reason is `str(Invalid)`, which is `session` when the session is not the one held).
- `{"ok": false, "error": "bad_message:session"}` with status 403: Games `server.py` line 185 (2ee23e6).

Both come from the shared `Invalid("session")` of the vendored protocol code. A game that rewords its
refusal silently reverts to the old behaviour (End unconfirmed, a switch refused); nothing fails.

**`session.reason` on `/party/api/state`.** An additive key of `session`, present only when
`close_lost_game` is on: `"game_lost"` after the closure above, `null` for every other close. With
the switch off the key does not exist. The current shell ignores it (`web/party/app.js` has no
branch for it; the phone simply goes home because `location` and `nav` do). The UI contract for
showing "the game stopped" is AVR-339; see
[proposals/2026-10-12-session-probe.md](proposals/2026-10-12-session-probe.md) section 4.

**Side effect of the connection check.** For a socket-activated native game
(`deploy/games/avrana-game@.socket`) systemd accepts the connection while the process is down and
starts the unit. That process holds no session, so it answers and refuses tickets: the session is
not closed and this is the restarted-game case, not a lost game. The check finds a game whose
socket is gone or whose unit cannot start. It does not find one that restarted; only the proposed
`state` probe would.

## Not declared here

Player identity (Party never sends device or member ids to a game), chat transport, the shared
`wc-name` display-name key, service worker scopes. They are platform ownership rules in
[PARTY-PLATFORM](PARTY-PLATFORM.md) and [LAN-GAMES-ASSIMILATION](LAN-GAMES-ASSIMILATION.md),
enforced by tests on each side, not a cross-repository interface version.
