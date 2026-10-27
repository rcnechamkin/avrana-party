# Party results, history, stats and provenance (AVR-71)

- **Status:** proposal, 2026-10-26. Nothing is implemented. Nothing is persisted by this document, and no
  protocol, envelope or party view changes. **Owner decisions are required** (section 9). ADR 0015 says
  privacy and retention must be decided before anything is persisted.
- **Reads with:** [ADR 0015](../../adr/0015-game-result-envelope.md) (the envelope and the acceptance boundary,
  and what it leaves to AVR-71), [PARTY-PLATFORM.md](../PARTY-PLATFORM.md) principles 3 ("guest-first") and 21
  ("Party owns the durable record; games report"), `avrana/party/core.py` `_accept_result`.

## 1. What exists today

| Fact | Source |
|---|---|
| A game reports `avrana.game-result/v1` inside the signed, session-bound `ended`. The result rides on `ended` or does not arrive at all. | ADR 0015 §1–§2 |
| The game's `game.id` must be the session's game and the message's issuer, so a game cannot report for another game | ADR 0015 §2; `result.check` |
| `_accept_result` is the only place a result becomes the party's. It keeps `{schema, session, game, outcome, mode, standings + member, data_schema, data}` **on the session object, in memory**. | `core.py` |
| A refused result is recorded as `result_refused` with a reason, while the end itself is honoured | ADR 0015 §3 |
| Members are per party. Device ids persist (hashed tokens in `devices.json`). There are no profiles yet. | PARTY-PLATFORM "What is a person?"; `identity.DeviceStore` |
| Deferred by ADR 0015: storage and retention, history schema, stats, leaderboards, achievements, profile attribution, privacy and deletion, what phones see, `invalid` distinct from `abandoned`, teams | ADR 0015 "What this decides" |

## 2. Outcomes: what counts as what

| Session end (exists) | Result (exists) | Proposed record `outcome` | Counts toward stats? |
|---|---|---|---|
| `completed` | accepted | `completed` | **yes** |
| `completed` | none sent | `completed_unscored` | plays and time only |
| `completed` | refused (`result_refused`) | `invalid` (the reason is kept) | plays and time only; the refusal is visible to the owner |
| `abandoned` (game lost, everyone left) | – | `abandoned` | plays only |
| `ended_by_host` | – | `ended_by_host` | plays only |

`invalid` is the outcome ADR 0015 deferred. It needs no protocol change, because the party already knows the
refusal.

## 3. The party's record (`avrana.party-record/v1`)

Written by Party only, from the in-memory record `_accept_result` already builds, at the moment the session closes.

```json
{
  "schema": "avrana.party-record/v1",
  "record": "rec-<random>",
  "game": {"id": "bluff", "build": "sha256:3f9c…", "content": null,
           "source": "first-party", "signed": "first-party"},
  "ended_at": "2026-10-26T21:14:03Z", "time_state": "synced",
  "duration_s": 612,
  "outcome": "completed",
  "mode": "competitive",
  "players": 4, "spectators": 1,
  "standings": [{"who": "profile:pr-7f3a…", "standing": "won"},
                {"who": "guest", "standing": "lost"}],
  "result": {"status": "accepted", "data_schema": "bluff.result/v1"},
  "party": {"version": "<party sha12>"}
}
```

**Platform fields vs game payload.** Every field above is the platform's. The game's `data` is **not** stored in the
record. It goes in a separate, size-capped side file keyed by `record`, labelled with its `data_schema` and the game's
source, and it is shown only as that game's own information (section 6). Nothing in `data` can change a platform
field, and nothing in it is ever rendered as a platform statement.

**Who.** A standing names `profile:<id>` only for a person who chose a saved profile (PARTY-PLATFORM "Save Player").
Everyone else is `guest`. **No member id, participant id, device id, display name or IP is stored.** Members and
participants die with the party, and device ids are not people.

**Time.** `ended_at` is wall time with the AVR-79 `time_state` (avrana-party#228). `duration_s` is monotonic, so a
clock step cannot make a game last a negative or huge time.

## 4. Provenance and trust

| Source of the game (from the install record and AVR-58, avrana-party#230) | Label on every record | Allowed into platform stats |
|---|---|---|
| First-party (repository contract, Avrana-signed) | `first-party` | yes |
| Installed, signed by a pinned publisher key | `community · <publisher claim> · key ab12…` | yes, in that game's own section only |
| Installed, unsigned | `community · unverified` | plays and time only, unless the owner opts in per game (D5) |

Rules:
- **No forging another game's record.** This already holds: the issuer, session binding and `game.id` check (ADR
  0015).
- **No impersonating a platform event.** Records are written by Party only, from its own session object. A game has no
  write path. Platform events ("a new profile was saved", a future achievement) are a separate Party-authored type,
  never derived from `data`.
- **No silent promotion.** A community game whose package is later signed or re-installed does not upgrade its old
  records. A record keeps the label it was written with.
- **The `build` is kept** so a disputed result can be traced to the exact implementation (ADR 0015 §6).

## 5. Retention and storage

- **Where:** `/var/lib/avrana-party/history/records.jsonl` (append-only, 0600, Party Core's own user), and
  `data/<record>.json` beside it. It is never inside a release tree, so a rebuild or a deploy does not touch it.
- **How long (D2):** the newest 1,000 records **or** 1 year, whichever is smaller. Older lines are dropped by a
  rotation on start, never by the game.
- **Deletion:**
  - deleting a profile rewrites its standings to `guest` (the plays stay, the person goes);
  - the owner can clear all history;
  - a removed game's records stay, labelled with its id, unless the owner removes them with the game.
- **Backups:** history is owner data, class O in the backup proposal (AVR-81, avrana-party#227). It is included only
  if the owner chooses (D6).
- **Crash safety:** a record is appended with fsync after the session closes. A crash loses at most the record being
  written, never earlier ones (a reader skips a torn last line).

## 6. Stats, and who sees what

**Platform stats** are computed from records only, never stored separately:
- plays per game; last played; total time;
- per profile and per game: won / lost / drawn / shared from accepted results, and cooperative success rate;
- "Recently played" (game names only).

No cross-game score or ranking. ADR 0015 leaves any cross-game model to be designed, and nothing here needs one.

**Game-specific stats:** a game's `data` side files may be shown on that game's own page in the owner or profile
view, labelled with the game's name and source. A future read API for a game to show its own history back to players
is out of scope.

| Who | Sees |
|---|---|
| Everyone in the current party | the result of the game they just played (the party view; a separate slice, UI-DESIGN-SYSTEM row "Played by …") |
| A person with a saved profile | their own history and stats, on a device they are signed in on |
| The owner (AVR-44 credential) | all records, all stats, refusals and `invalid` reasons, and the clear-history control |
| A guest in a later party | **nothing about earlier people**; "Recently played" game names only if the owner enables it (D4) |
| The network | nothing: records are never sent anywhere (no telemetry; AVR-302 heartbeat data is separate) |

## 7. Teams and achievements

- **Teams:** v1 standings are per participant, and a team game reports each member's standing (everyone on the
  winning team `won`). A `team` label in standings is a later envelope change, under the AVR-72 rules (a named
  feature or `game-result/v2`), with no data model change needed here: the record would gain `team` on a standing.
- **Achievements: none for now (D7).** If they ever exist:
  - platform achievements come only from platform events and records;
  - a game's own achievements are shown as that game's, labelled with its source;
  - a community game's achievements never appear in a platform badge list.

## 8. Privacy summary

- Default: **nothing about a person outlives the party** unless they saved a profile.
- Stored about a profile: which games, when, the standing, and time played. Not where, not with whom by name (other
  players are `guest` unless they also have profiles), not device, not IP.
- The owner can see everything stored on their box. That is stated in the profile-saving words (AVR-85), so a person
  knows before they save.
- Deleting a profile removes the person from history. Clearing history removes everything.
- No record or side file is ever uploaded, synced or included in a support bundle without the owner choosing to
  (AVR-74).

## 9. Owner decisions

| # | Question | Options | Suggestion |
|---|---|---|---|
| D1 | Persist history at all in the prototype? | yes, as above; memory only until profiles exist | **memory only until profiles exist (AVR-85)**, then this design. A guest-only history is just play counts, and those can come first (D3) |
| D2 | Retention | as proposed; shorter; until cleared | **1,000 records or 1 year** |
| D3 | Ship anonymous play counts (no people) before profiles? | yes; no | **yes**: plays per game and last played help the owner and Recently Played, and hold no personal data |
| D4 | "Recently played" visible to guests? | off; game names only | **game names only, owner can turn it off** |
| D5 | Unsigned community games in stats | never; owner opt-in per game | **owner opt-in per game** |
| D6 | History in backups | never; owner choice | **owner choice, off by default** |
| D7 | Achievements | none; platform only; platform and game | **none for now** |

## 10. Phasing

1. **Outcome mapping and record building in memory** (`invalid` included), with tests against the ADR 0015 vectors.
   No disk.
2. **Anonymous play counts** (D3): persisted counters per game, no people.
3. **Profiles (AVR-85), then attributed records** with the deletion rules.
4. **Owner and profile views** (AVR-44), and the "Played by …" party-view slice.

## 11. Tests to write with phase 1 and 2

- Each row of section 2 produces the stated outcome, from the existing `ended` vectors.
- A record never contains a member, participant or device id or a display name (a property test over many sessions).
- `data` never reaches a platform field. A `data` that imitates a platform field name stays in the side file.
- A community game's record keeps its label after the package is re-signed.
- A torn last line is skipped. Rotation keeps exactly the newest N.
- Deleting a profile turns its standings into `guest`, and the stats recompute.
