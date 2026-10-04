# ADR 0015 — Game result envelope v1

Status: **accepted** · Date: 2026-10-03
Accepted by the owner on 2026-10-03 (AVR-237). What is deployed is recorded in
[SYSTEM](../SYSTEM.md), not here.
Takes up the deferral recorded in [ADR 0006](0006-party-session-protocol.md) ("no results in
v0"; amendment of 2026-10-02) and [ADR 0014](0014-native-games-isolated-lan-games-retired.md)
decision 9. History, stats, retention and privacy are **not** decided here: they are
[AVR-71](https://linear.app/avranakern/issue/AVR-71/define-party-results-history-stats-and-provenance-model).
Reference implementation: `avrana/party/result.py`; cases: `contracts/vectors/game-result.v1.json`.

## Context

The session protocol tells the party that a game session ended, as `completed` or `abandoned`,
and nothing else. BLUFF knows who won; EXPO knows whether the mission was passed. The party does
not. With one game that is harmless. With several, each game would keep its own idea of results
and the party could never hold an authoritative record of any of them.

What already exists and is kept:

- the `ended` message: signed with the game's key, bound to one session id, replay-guarded,
  accepted only from loopback and only for the live session;
- participant ids: random, issued by the party per session, the only name a game has for a
  person. A game never sees a member or device id.

## Decision

### 1. The result rides inside `ended`; it is versioned on its own

`ended` gains one optional field, `result`. Its content is a separate format with its own
identity, `avrana.game-result/v1`. The session protocol stays `avrana.party-session/v0`: a
receiver that does not know the field ignores it, exactly as it ignores `jti` on a ticket.

There is no second message, route or state. A result arrives with the end it describes or not
at all, so there is no window in which a session is over without its result, and no way to send
a result for a session that is still running. Authentication, session binding and replay
protection are those of `ended`; the envelope adds none of its own.

### 2. The envelope

```json
{
  "schema": "avrana.game-result/v1",
  "game": {"id": "bluff", "build": "sha256:3f9c0a…", "content": "…"},
  "mode": "competitive",
  "standings": [
    {"participant": "participant-…", "standing": "won"},
    {"participant": "participant-…", "standing": "lost"}
  ],
  "data_schema": "bluff.result/v1",
  "data": {"steps": 41, "forfeited": ["participant-…"]}
}
```

| Field | Owner | Meaning |
|---|---|---|
| `schema` | platform | exactly `avrana.game-result/v1`; anything else is refused |
| `game.id` | platform | the game; must be the session's game and the message's issuer |
| `game.build` | platform | which implementation produced the result: everything on the game server that can change it, not the rules alone (see §6) |
| `game.content` | platform, optional | which ruleset or content pack, when the game has one |
| `mode` | platform | `competitive` or `cooperative`: how to read the standings |
| `standings` | platform | one entry for **every player** of the session and nobody else: `participant`, `standing` (`won`, `lost`, `draw`), optional `rank` |
| `data_schema` | game | the game's own name and version for `data` |
| `data` | game | small game-owned facts; the party stores it and never interprets it |

Rules the party enforces (`result.check`), each with a case in the vectors:

- unknown top-level or per-participant fields are refused, so nothing rides along unnoticed;
- a participant reference must be well formed and must be a **player** of this session;
  spectators and participants of other sessions are refused; every player must appear once;
- `rank` is given for everyone or for no one, from 1 to the number of players; ties share a rank;
- in `cooperative` mode the whole table shares one standing, `won` or `lost`;
- `data` needs `data_schema` and the reverse; `data` is an object of plain JSON values, at most
  4 containers deep, strings at most 200 characters, integers within ±2^53, and any participant
  id inside it (as a value or a key) must be a player of this session;
- the whole result is at most 2048 bytes of canonical JSON and `data` at most 1024.

The size limits keep the signed message inside the protocol's 8192-byte token limit and both
services' 8192-byte body limits. Authenticated is not the same as trusted: a game server's
result is checked as untrusted input.

There is deliberately no score, team, round or achievement field. A game that has scores puts
them in `data`. A cross-game scoring model, if one is ever wanted, is AVR-71's to design from
real results.

### 3. The end and the result are judged separately

A report that fails as a **message** (bad signature, wrong issuer, wrong or stale session,
replay, not from loopback) is refused whole, as before: nothing ends and nothing is stored.

A report that is a valid message ends the session, as before, whatever its result looks like.
The **result** is then accepted or refused on its own:

| Situation | Session | Result |
|---|---|---|
| `completed`, valid result | ends `completed` | accepted |
| `completed`, invalid result | ends `completed` | refused, reason recorded and returned |
| `completed`, no result | ends `completed` | none (as today) |
| `abandoned`, with or without a result | ends `abandoned` | refused `not_completed` if one was sent |
| host's End already in progress | ends `ended_by_host` | refused `not_completed` if one was sent |

A game with a faulty result must not be able to leave the party showing a game that is over.
Refusing the result while honouring the end fails closed for the record and keeps the lifecycle
exactly what it was. The reply to the game says which happened: `{"ok": true, "result":
"accepted"}` or `{"ok": true, "result": "refused", "reason": "…"}`.

### 4. One result per session, decided by the party

A session ends once. A second `ended` for it, with the same or a different result, is a replay
(403) or a stale session (409), and the stored result does not change. There is no update
message.

Only the game server can make a result: it needs the game's key and a loopback connection to a
route nginx does not forward. A browser has neither, and no message a browser can send to a game
puts anything in the report.

### 5. The acceptance boundary

`PartyCore._accept_result` is the only place a result becomes the party's. It runs once per
session, after the session closed, on a report already authenticated and bound to that session.
What it keeps on the session is the party's own record: the checked result, the session id and
outcome, and for each standing the **member** behind the participant, which only the party
knows.

That record is where AVR-71 starts. Nothing is written to disk here, nothing outlives the
session object, and what phones are shown is unchanged: the party view does not include the
record.

### 6. How a game produces one

A game that vendors `result.py` calls `result.build(...)`, which applies the same check the
party will, so a game cannot send what would be turned away. In the LAN Games fork the game
returns its result in its own seat tokens from `GameSession.game_result()`, and `core/net.py`
translates tokens to participant ids from the launch roster and builds the envelope. A game
without `game_result()` reports exactly as before.

**`game.build`.** A result is produced by a game's rules and by the server around them, so the
identifier must cover both. In the LAN Games fork it is a SHA-256 digest (`sha256:` plus 16 hex
digits) over the shared runtime (`server.py`, `core/`, including the vendored protocol and
result code, `games/registry.py`, `requirements.txt`) and the game's own sources and
server-side content; browser assets, art and documents are excluded
(`core.party_session.build_id`). A change to shared code therefore changes the build id of
every game. The repository commit would be the natural identifier, but the running server
cannot know it reliably: a deployed tree is a copy without trustworthy Git metadata. The digest
is derived from the files actually loaded, is identical for every checkout of one commit, and
can be recomputed at any commit to trace a stored result back. A game with its own repository
and release process may use its release version instead; the envelope only requires that the
value identify the producing implementation.

## The two examples

**BLUFF** (competitive): the last player standing `won`, everyone else `lost`. `data` holds
public facts only: steps played, seats, bots, whether a bot won, the winner's remaining
influence, who forfeited. No card, held or revealed, is included.

**EXPO-shaped** (cooperative): every player shares `won` or `lost`. `data` holds the mission,
`success` or `failure`, attempts and task counts; `game.content` names the mission set. This is
proven by vector and by a stand-in cooperative game through the real reporting path. EXPO itself
is not changed by this work.

Both pass the same `check` and the same `_accept_result`. Neither needs a rule of its own.

## What this decides, and what it does not

| Decided here (AVR-237) | Left to AVR-71 |
|---|---|
| the envelope, its version and its limits | what is stored, where and for how long |
| that the result is carried by `ended` | cross-session history and its schema |
| who may produce one and how it is authenticated | player stats, leaderboards, achievements |
| separate judgement of end and result | attribution to Profiles; privacy and deletion |
| one result per session; the acceptance boundary | whether and how phones see results from the party |

Also deferred: a game manifest field advertising the result schemas a game supports
(`contracts/games/*.json`); reporting the result schema in the deployment manifest and
`/party/api/status`; an `invalid` outcome distinct from `abandoned`; teams.

## Consequences

- `protocol.py` and `result.py` are both vendored by the games repository, byte-identical, and
  both digests are in the two contract declarations. `tools/contract_check.py` compares them and
  the vectors in both repositories' CI.
- The contract stays `avrana.party-games/v0`: the change is additive. A game built before it
  still works; a party built before it ignores the field.
- A later, incompatible envelope is `avrana.game-result/v2`. The party would then accept the
  versions it lists; v1 results are refused by nothing but a decision to stop accepting them.
- Participant-level results exist at the party, linked to members. That is new information for
  the party to hold, even only in memory, and is the reason AVR-71's privacy and retention
  decisions must precede any persistence.
