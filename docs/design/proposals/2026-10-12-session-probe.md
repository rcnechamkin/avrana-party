# Session probe and orphaned-session lifecycle

- **Status:** **PROPOSED (2026-10-12, AVR-33; narrowed 2026-10-14). Mostly not built.** Of Part A, items 1, 2 and 6 are on main (PR #109) and item 4 is in source behind the `close_lost_game` switch, **off by default**; items 3 and 5 exist only on branch `fix/avr-33-session-recovery` (3875b7c) and wait for the owner decisions in section 5. Nothing is deployed. Part B is a proposal that decides nothing and changes no contract: it needs an owner decision and a paired Games change.
- **Reads with:** [PARTY-GAMES-CONTRACT](../PARTY-GAMES-CONTRACT.md), [ADR 0006](../../adr/0006-party-session-protocol.md) (session protocol), [PARTY-LIFECYCLE](../PARTY-LIFECYCLE.md), [ADR 0016](../../adr/0016-service-identities-and-local-trust-boundary.md) (native games, socket activation).
- **Not covered:** any UI. Part C is the contract the UI team needs (AVR-339); nobody here changes Party Home.

Tiers used below: **T1** unit/simulated, **T2** real processes or sockets in one machine, **T3** physical appliance, **T4** real phone. Everything cited here is T1 or T2. Nothing was run on the appliance or on a phone.

## 1. The problem, with reproduced evidence

Party Core and a game server each hold the session in memory. When one of them loses it, the other does not know. All five cases were reproduced in `tests/unit/test_party_recovery.py` (class `Scenarios`, four phones, real HTTP between phones, Party Core and a game server on loopback, T2; the game is a thread there, so a "crash" is a stopped listener).

**What v0 gives Party today.** Party sends the game two messages, `launch` and `end` (`contracts/party-games.v0.json` `routes`). The game sends Party `ended` and the host question. **There is no route by which Party can ask a game what it holds.** The note from sprint 1 that mentions `/avrana/session/v0/state` does not match the code: that string appears nowhere in Party (`origin/main` 04c5844, this branch) or in Games (`origin/main` 2ee23e6, or the deployed a448972). No game, the stand-in and the managed arcade/PS1 runtime included, serves a state or health route to Party. The only negative information a game gives is its refusal of an `end` for a session it does not hold.

| # | Scenario | What a phone sees today (before this change) | After Part A | Classification | Test |
|---|---|---|---|---|---|
| 1 | Games (or a native game process) restarts while the session is ACTIVE | Party says `active`, location `game`, for everyone. Every ticket is issued; the game refuses it (`session`). Followers bounce between Party Home and a game page that refuses them. The host's End worked but was **not confirmed** (the game answered "no such session", read as "did not stop"), and a host **switch** to another game was refused ("the last game did not stop") | Unchanged until the host acts. The host's End or way home (`POST /party/api/lobby`, PR #122) returns everyone to Party Home, and Start works again. With item 3 (owner decision) End would also confirm and a switch would work directly | GRACEFUL TERMINATION by the host (automatic only with Part B) | `Scenarios.test_1_*` |
| 2 | Party Core restarts while the game still runs | Party is empty: members gone (`me: null`), `lobby`/`home`. The game still holds the old session and so does the arcade/PS1 runtime, until some host launches again | In this source: unchanged; the next launch of that game replaces the orphan. With item 5 (owner decision) the restarted Party Core would send the signed `end` for the session it recorded and the game (and the arcade/PS1 runtime) would stop. **In-memory party state is lost either way** | cleanup of the game at the next launch (AUTOMATIC with item 5); UNRECOVERABLE party state (see below) | `Scenarios.test_2_*` (item 5's tests are on 3875b7c) |
| 3 | A native game crashes mid-session | (a) stays down: Party `active`; tickets issued; pages fail to connect, for ever. (b) systemd restarts it (`Restart=on-failure`) or socket activation starts it on the next connection: a new process with no session, which is scenario 1 | (a) after 3 failed checks over 10 s a ticket request closes the session as `abandoned`, reason `game_lost`: everyone goes home. (b) unchanged: it **answers**, so Party cannot tell | (a) AUTOMATIC; (b) as scenario 1 | `Scenarios.test_3_*`, `GameLostRules` |
| 4 | The host reconnects after a service interruption | Games blip (same process answers again): nothing lost. Party restart: the host's cookie works but the party is new; the host is a plain member until they rejoin, and the **first to rejoin becomes host** | Same. The blip case is covered. The restart case is recorded as UNRECOVERABLE | blip AUTOMATIC; restart UNRECOVERABLE | `Scenarios.test_4_*` |
| 5 | Followers reconnect to a dead session | After the host ended it: 409 `no_game`, home. After a game loss: bounce (scenario 3). After a Party restart: 403 `not_member` until they rejoin, then 409 `no_game` | A game that stays down now ends the bounce (scenario 3a). Others unchanged | AUTOMATIC / GRACEFUL | `Scenarios.test_5_*` |

**Party Core restart: what is and is not recovered.** The party lives in memory by design (`avrana/party/core.py`). After a restart the device cookies work (`devices.json` persists), but members, host, roster, tickets, presence and the session are gone. A phone with a profile rejoins on its own; **the first to rejoin is host**, which need not be the old host. A game page that was open follows `nav` home (by design of the bridge; not exercised here, T4 not run). The game that was running is ended by the recovery below, so a round in progress is lost; nothing in v0 can save it, because no ticket can be issued for a member Party Core no longer has. The host who wants the old order back transfers the role in Party Home. This is stated, not fixed.

## 2. Part A: implemented (no contract change)

All of it uses messages and fields v0 already has. Items 1, 2 and 6 are unconditional and on main (PR #109). Item 4 is in source behind `session_recovery.close_lost_game` (**false** by default; [PARTY-GAMES-CONTRACT](../PARTY-GAMES-CONTRACT.md)). Items 3 and 5 were switches `end_not_held_is_ended` (default **true** there) and `end_orphan_on_start` on branch `fix/avr-33-session-recovery` (3875b7c); they are **not** in this source and a config that names them is refused, pending section 5.

1. **One deadline per game call** (`avrana/party/sessions.py`). Every `launch`/`end` is one request on a socket whose every wait is cut to what is left of a single monotonic deadline, started before the connection is made, over TCP and Unix sockets. A game that drips its headers, drips its body or stalls after its headers frees the caller within the link timeout. Before: a header drip held a request thread for 12 to 32 seconds in the tests (confirmed, T2). Redirects are no longer followed. A non-object JSON reply is a failed call, not an exception.
2. **No lock across a game call.** Link calls were already made outside `PartyService.lock`; a test now holds a launch stuck at a stalling game while three phones poll `/party/api/state` (each answer under 0.5 s, the lock free).
3. **Not in this source (owner decision 2).** **An `end` the game answers "no such session" counts as ended.** Both refusal wordings in use are read (`{"reason": "session"}` and `{"error": "bad_message:session"}`). This is an observed convention of the games, not a field of v0; it is read-only and affects only whether Party treats a restarted game as having stopped.
4. **A game that stays down closes the session.** When a phone is about to be sent to the active session's game (a ticket request), Party checks that a connection to it is accepted (no message sent; at most one check per 2 s, waiting as long as a launch would). Three failed checks inside a sliding 10 s window, with no success between, close the session: outcome `abandoned` (already in the vocabulary), `session.reason = "game_lost"` (a key that exists only with the switch on), `session.detail = "The game stopped."`, `nav` home, tickets and seats released as for any abandoned session, a best-effort `end` sent off the request thread. One success starts the count again. A game behind systemd socket activation accepts connections while its process is down, so this finds a game whose socket is gone, not one that restarted.
5. **Not in this source (owner decision 3).** **A durable active-session record** (`avrana/party/record.py`, `active-session.json` beside `devices.json`, or `session_record` in the config): session id and game id only, written (temp file, fsync, rename) when a launch is sent and removed when an `end` for it is answered. At startup Party Core sends the game the signed `end` for the recorded session, up to five tries two seconds apart, then drops it. Safe beside a new launch: an `end` names its session and a game never ends a newer one (tested).
6. **A managed runtime's failure text is capped at 200 characters** (`avrana/party/managed.py`), so Party's 64 KiB reply bound cannot turn the arcade's own explanation into "did not answer". Measured: a 200 KB exception text produced a 200 054 byte reply before.

For scenario 2 the three options were: (i) do nothing until the next launch replaces the orphan (the previous behaviour); (ii) rely on that replace; (iii) persist the active session and `end` it. **Recommended: (iii), implemented on 3875b7c only.** It needs an amendment of ADR 0006 ("the party is memory-only") and ADR 0016 section 8 ("ends by the existing rules"), so it is not carried into source without the owner. It uses the existing signed `end`, it is the only option that stops an orphaned arcade or PS1 runtime (otherwise it keeps running with nobody managing it until some host happens to launch that game again), and a record that cannot be read or written leaves the previous behaviour.

## 3. Part B: the optional `state` probe (proposal only)

Scenario 1 (and 3b) cannot be detected from Party's side with v0: the game answers connections and refuses nothing Party sends. The smallest addition is a question.

**Capability gate.** A game opts in by declaring `extensions["net.avrana.party"].state = true` in its Game Contract (`contracts/games/<id>.json`), next to `pregame`. Party reads it into the game's facts. A game that does not declare it is probed exactly as today (connection check only). No schema version moves.

**Message.** `POST {game}/avrana/session/v0/state` with `{"message": <state>}`, loopback or Unix socket exactly like `launch`.

- `state` (Party to game): `typ "state"`, `iss "party"`, `aud <game>`, `sid` (the session Party is asking about), `iat`, `exp` (the usual 30 s), `nonce`; sealed with the game's key like `launch` and `end`. The game verifies and spends the nonce like any message.
- Reply: `200 {"ok": true, "answer": <state_is>}`. `state_is` (game to party): `typ "state_is"`, `iss <game>`, `aud "party"`, the asked `sid` and `nonce`, and `holds` (boolean: this process holds that session). Sealed with the same key. `unseal` requires a session id, so the answer repeats the asked one and says `holds: false` instead of omitting it.
- Limits: the reply is read under the same bounds as `launch` and `end` (64 KiB and the one deadline; a real answer is about 400 bytes).
- Implementation lives in a new module `avrana/party/probe.py`, not in `protocol.py`, so the digest of `protocol.py` (and with it every vendored copy) does not change. It uses `protocol.seal` and `unseal`. Games would vendor it as `core/party_probe.py`, declared in an optional `probe` block of both declarations with its digest.

**Triggers (minimum set).**

| Trigger | Why | Chosen |
|---|---|---|
| A ticket request for an ACTIVE session | exactly when a phone is about to be sent to the game; cheap; already throttled to one per 2 s | yes |
| A refused-ticket report from the game page or the phone | the bridge has no such message; adding one changes the vendored shim and its digest and is UI-adjacent | no |
| Party Core startup | there is no session to ask about; the record handles it (Part A) | no |
| A background timer | costs a request per interval on a Pi whose CPU the arcade can starve, and protects nobody who is not being sent to the game | no |

**Lifecycle.** States are the existing ones in `core.py`. Only ACTIVE is probed (LAUNCHING has `LAUNCH_TIMEOUT`, ENDING has `END_TIMEOUT`, SETUP never reached the game, and a held results screen has no game page to bounce to).

| Probe result | Action |
|---|---|
| `holds: true` | start the count again; nothing else |
| `holds: false` for the asked session (an authentic, signed answer) | a miss; **2 in a row over at least 3 s** close the session (an authentic "no" is stronger evidence than silence) |
| unreachable, or no answer within the deadline | a miss; **3 inside a 10 s window** (what Part A does) |
| 404/405 from a game that declared the capability, an unsigned, malformed, wrong-nonce or wrong-session answer | ignore, log once; never counts as a miss; the game is probed by connection only until Party restarts |

"Closed" means what Part A does: outcome `abandoned`, `reason "game_lost"`, `nav` home, tickets and seats released, a best-effort signed `end` afterwards. A held result cannot exist for an ACTIVE session (a result is reported by an `ended`, which already ended it). A game that flaps or answers slowly never reaches the thresholds, because any success resets the count.

**Failure behaviour.** The probe can only close a session; it never starts, ends or alters one at the game. A probe that is wrong costs a rejoin: the host presses Start again.

**Compatibility.**

- Old game, new Party: the contract does not declare the capability, so Party sends no `state` message. Identical to today.
- New game, old Party: the route exists and is never called.
- Digests: `protocol.py`, its vectors, the result and bridge files are untouched, so `tools/contract_check.py` passes for every pairing without a paired change. The vendored `party_probe.py` and a `probe` block are optional additions; the checker would compare them only when both sides declare them.
- Not a v0 to v1 change: a Games built against v0 keeps working.

**Tests to add.** Party: vectors for `state`/`state_is` (accept, wrong key, wrong session, replayed nonce, expired); the five scenario tests change as follows: 1 and 3b close the session after two probes instead of staying active. Games, per game (BLUFF/EXPO via the Games server, Checkers, Hello Party/gamekit): holds before launch (false), after launch (true), after `end` (false), after its own `ended` (false), after a process restart (false); a signature or nonce replay is refused; `hello_party/conformance.py` covers the capability. Cross-repo: `tests/test_party_session_cross_repo.py` runs the probe against the real Games server.

## 4. Part C: what the UI team needs (contract only, AVR-339)

No UI is changed here. `GET /party/api/state` carries, for every phone:

- `session.outcome == "abandoned"` and `session.reason == "game_lost"` (new key, present only with `close_lost_game` on, `null` for every other close) with `session.detail == "The game stopped."`; `session.state == "ended"`.
- `location.at == "home"` and `nav.to == "home"`, `nav.from` the game id. Party Home should therefore show "The game stopped" once (keyed on `session.id`) instead of bouncing, and offer Start to the host.
- After a Party Core restart: `me: null` and `state: "lobby"` for a phone that has a device cookie. Party Home should treat this as "the party restarted, rejoining" and not as a new visitor; the host role is not restored (section 1).
- A game page's bridge projection (`publicView`) is closed and does not forward `reason`; a game page only needs `location.at`, which already moves home.

## 5. Decisions for the owner

1. **The optional `state` probe (Part B).** Options: (a) accept it as an additive v0 message, with the capability in the Game Contract extension, a new `probe.py` and a paired Games change, recorded as an ADR 0006 amendment; (b) defer it. Recommendation: (b) for now. With the host's way home (PR #122) scenario 1 costs one tap, and (a) is a cross-repository protocol change.
2. **Reading an `end` refused with reason `session` as ended (item 3).** Options: (a) Party reads the undeclared refusal token (3875b7c, default on there); (b) the games answer `{"ok": true}` to an `end` for a session they do not hold while idle, as the arcade already does (ADR 0009 rule 3), and Party is unchanged; (c) leave it: End is unconfirmed and a switch stops, and the host's way home recovers. Recommendation: (b), a Games change that matches an accepted rule and needs no Party heuristic; (c) until then.
3. **Ending the orphan of a Party Core restart (item 5).** Options: (a) the durable record on 3875b7c, with an ADR 0006 / ADR 0016 section 8 amendment; (b) keep today's rule, where the next launch of that game replaces the orphan; (c) a game-side idle timeout that abandons a session nobody has entered for some minutes (D1 gives a game its own disconnect behaviour). Recommendation: (a) behind its switch if an unmanaged arcade or PS1 runtime after a Party Core crash is measured to matter on the Pi; otherwise (b).
4. **Turning `close_lost_game` on.** It is in source and off. Recommendation: turn it on after C-08 of [offline-acceptance](../../runbooks/offline-acceptance.md) passes on the appliance.
