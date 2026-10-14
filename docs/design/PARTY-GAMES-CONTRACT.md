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
"one readable line"}`. Party Core treats anything else, and any `3xx`, as a failed call.

**Is it a contract requirement?** It is declared Party-side behaviour, not a machine-checked
requirement, and it stays out of `contracts/party-games.v0.json` for now.

- *Additive?* Yes, as far as the checkers go. `tools/contract_check.py` reads named keys of each
  declaration and compares named keys across them; an extra top-level `limits` block in Party's
  JSON was run against Games `origin/main` (2ee23e6) and the deployed a448972 and both stayed
  `compatible`. `avrana/contracts/party_games.py` and the status document read named keys too.
- *Why not add it anyway?* Nothing in Games would check it: Games' declaration has no field for a
  limit, so the number would be declared by Party and obeyed or not by each game, with no test on
  the other side. A limit that is declared on both sides, with a Games-side test, is a paired
  change (a field in Games' `provider/avrana-contract.json` and a check in `contract_check.py`)
  and an owner decision; it is not added.
- *Old Games, new Party:* unchanged; the limit is behaviour Party already applies to every reply.
  *New Games, old Party:* a game that keeps inside the limit works with a Party that has none.
- *Name resolution* is outside the deadline: a game is only addressed by a loopback IP literal or
  a Unix socket path from the appliance's own grant, so no resolver is involved.

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

## One spelling per token (AVR-465)

**The rule.** In every `aps0.<payload>.<mac>` token, ticket or message, both parts are *canonical*
base64url: only `A-Z a-z 0-9 - _`, no padding, no whitespace, and the unused low bits of the last
character are zero. The test is one line in any language: decode the part, encode the bytes again
without padding, and require the same characters. A receiver refuses anything else as `encoding`,
before it checks the MAC. Nothing may tell two tokens apart by their characters: the single-use
ticket ledger is keyed on the SHA-256 of the **decoded payload bytes**, the message replay guard
on the payload's `nonce`.

**Why.** A 32-byte MAC is 43 base64url characters and the last one carries two unused bits. The
decoder ignored them, so every ticket had four spellings that verified, and the ledger, keyed on
the characters, admitted one ticket four times. The rule removes the spellings; the ledger key
removes the dependence on them, should a decoder ever be lenient again.

**What it is not.** The ticket format, the lifetimes and the HMAC construction are unchanged, and
every token an honest sender ever produced is still accepted (senders always wrote the canonical
spelling), so this stays inside `avrana.party-session/v0`: an old Games works with a new Party and
the reverse. The contract version does not move.

**Held by vectors.** `contracts/vectors/party-session.v0.json` now also carries `refused` (each
token must be refused with the named reason: respelled MAC, respelled payload with a correct MAC,
padding, the standard alphabet, whitespace, an impossible length, a character outside ASCII, on
tickets and on messages) and `replays` (open `first`, then `then` must be refused: the exact
replay as `replay`, the respelled replay as `encoding`). `tests/unit/test_party_protocol.py` here,
`tests/test_party_session.py` in Games and the JavaScript helper's `node --test` suite in Games
all run them, and `tools/contract_check.py` refuses a vector file without them.

**Numbers every language reads alike.** A payload is refused as `payload` when it holds `NaN`,
`Infinity`, a number too large to be finite, or an integer literal outside −(2^53−1) … 2^53−1,
anywhere in it; when its bytes start with a byte-order mark; or when it nests containers more
than 32 deep, the payload object included (parsers give up at different depths). The claims `iat` and `exp` must be
written as integer literals: `1700000000.0` and `1.7e9` are refused as `expired`. Python and
JavaScript disagreed on each of these before (one accepted what the other refused), and each is a
vector now. A finite fraction elsewhere in a payload (a result's game data) is allowed. The 8192
limit on a token counts characters (code points), not UTF-16 units.

**The ledger's time only moves forward.** A spent ticket is forgotten when the latest time the
ledger has been shown passes its `exp`, and a ticket whose `exp` is not after that time is refused
as `expired`. A wall clock that steps back therefore cannot make a forgotten ticket new again. The
cost is deliberate: after a backward step of S seconds a game refuses tickets minted on the new
time for up to S seconds, or until its next session. The ledger belongs to a session id: a new
session starts a new one, and a second launch of the same session keeps its tickets spent.
The message replay guard still forgets a nonce by the wall clock; a replay through that needs a
captured loopback message and a backward step inside the message's 30 seconds, and closing it the
same way would make Party Core refuse every game's reports after a backward step. Left as is.

**Audit of the rest of the protocol** (same question: is there a second spelling, and does anything
count by spelling?):

| Where | Finding | Result |
|---|---|---|
| Ticket ledger (`SpentTickets`) | keyed on the ticket's characters; four spellings each | **fixed**: canonical rule, and keyed on the decoded payload |
| `launch`, `end`, `ended`, `host` (`ReplayGuard`) | the same four spellings verified, but the guard is keyed on the signed `nonce` (exactly 24 lower-case hex characters), so a respelled message was already a `replay` | not exploitable; now refused as `encoding` like a ticket |
| `host_is` | no guard of its own: it must repeat the `sid`, `pid` and `nonce` of the one question it answers, all inside the MAC | not exploitable; canonical rule applies |
| Payload JSON (key order, whitespace, duplicate keys, escapes) | a receiver does not re-derive canonical JSON, but the MAC covers the characters of part 1, so only a holder of the game's key can write a variant, and a key holder can mint outright (ADR 0006, symmetric keys). Both guards read decoded content. A receiver that re-serialised would have to agree with every other language on number formatting | no change, deliberately |
| Non-ASCII in the payload part | reached the MAC as a `UnicodeEncodeError`, not a refusal (worked around in Games as AVR-320) | **fixed**: `encoding` |
| Ids (`sid`, `pid`, game id) | the patterns ended in `$`, which in Python also matches before a trailing newline: `session-…\n` passed in Python only. Signed content, and Party compares `iss` and `sid` exactly afterwards | not exploitable; **fixed** (`\Z`) so implementations agree |
| `iat`, `exp` | `true` counted as an integer in Python; `1.7e9` counted as one in JavaScript | **fixed**: integer literals only, in both |
| Numbers, byte-order mark | Python accepted `NaN`, `Infinity` and integers beyond 2^53 that JavaScript cannot hold; JavaScript stripped a byte-order mark Python refused | **fixed**: one rule, above |
| Token length | counted in characters by Python and in UTF-16 units by JavaScript, so one token was `encoding` to one and `shape` to the other | **fixed**: characters |
| Ledger pruning | by the wall clock, so a backward step revived a forgotten ticket | **fixed**: high-water time |
| Relaunch | any launch cleared the ledger, the same session's included | **fixed**: cleared for a new session id only |
| Case | base64url is case-sensitive by definition; nonces, ids and key files are lower-case only | nothing to fix |
| Game token (`game_token`) | derived from `sid` and `pid`, never from a ticket's characters | unaffected |

`avrana/party/result.py` had the same `$`: a build, content or data-schema tag followed by a
newline passed; those two patterns now end in `\Z`. Its game-id and participant patterns keep
`$` on purpose: the first is followed by an equality check, and the second drives the scan that
keeps a participant id outside the roster out of game data, which a stricter pattern would loosen.

## Session recovery: a game that stays down (AVR-33)

One key under `session_recovery` in `party-core.json` (spelled out in the example file). It is a
boolean; any other value, or any other key, stops the service at startup, so a typo never leaves a
switch silently at its default. Nothing here adds a message, a field or a route to the session
protocol: the check is a connection, and the closure uses the outcome v0 already has.

| Key | Default | What it does |
|---|---|---|
| `close_lost_game` | **false** | When a phone asks for a ticket to the ACTIVE session, Party checks that a connection to the game is accepted (at most one check per 2 s, waiting as long as a launch would: the grant's `timeout`, else 5 s). Three failed checks inside a sliding window with no success between close the session: outcome `abandoned`, `nav` home, tickets and seats released, and a best-effort signed `end` sent afterwards off the request thread. A miss is stamped when its check started. The window is 10 s, or 3 x the connect timeout + 2 s when that is longer (17 s at the default 5 s), so that three checks that each waited out a full timeout can still add up. A success clears the count; a miss older than the window no longer counts. With it off no check is made, nothing closes, and `session.reason` below does not exist. |

It is off because it changes what the appliance does to a running round, and the owner has not
decided to turn it on.

**What triggers the check.** Only a ticket request for the ACTIVE session, at most one check per 2 s.
Nothing runs on a timer, so one idle follower never triggers it. In practice a game page that cannot
reach its game keeps asking (each reconnect fetches a ticket) and a phone being sent into the game
asks too; three attempts a few seconds apart, from one phone or several, are enough. If nobody tries
to enter the game the session stays `active` until someone does or the host ends it (End, or the
host's way home, `POST /party/api/lobby`, which works whatever the game answers).

**`session.reason` on `/party/api/state`.** An additive key of `session`, present only when
`close_lost_game` is on: `"game_lost"` after the closure above, `null` for every other close. With
the switch off the key does not exist. The current shell ignores it (`web/party/app.js` has no
branch for it; the phone simply goes home because `location` and `nav` do). The UI contract for
showing "the game stopped" is AVR-339; see
[proposals/2026-10-12-session-probe.md](proposals/2026-10-12-session-probe.md) section 4.

**Side effect of the connection check.** For a socket-activated native game
(`deploy/games/avrana-game@.socket`) systemd accepts the connection while the process is down and
starts the unit, as the phone's own connection would. That process holds no session, so it answers
and refuses tickets: the session is not closed and this is the restarted-game case, not a lost game.
The check finds a TCP game that is down, or a native game whose socket is gone (for instance after
systemd's start limit stopped it). It does not find one that restarted; only the proposed `state`
probe would.

**Not built (owner decisions, AVR-33).** Two further behaviours were written on branch
`fix/avr-33-session-recovery` (3875b7c) and are not in this source: reading an `end` refused with the
reason token `session` as "ended" (an undeclared convention of the games' replies), and a durable
record of the active session that a restarted Party Core ends at startup (persistence that ADR 0006
and ADR 0016 section 8 do not provide for). The proposal names both and the options.

## Not declared here

Player identity (Party never sends device or member ids to a game), chat transport, the shared
`wc-name` display-name key, service worker scopes. They are platform ownership rules in
[PARTY-PLATFORM](PARTY-PLATFORM.md) and [LAN-GAMES-ASSIMILATION](LAN-GAMES-ASSIMILATION.md),
enforced by tests on each side, not a cross-repository interface version.
